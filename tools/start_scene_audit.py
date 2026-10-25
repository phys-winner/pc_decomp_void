"""Restart only an isolated QA profile, wait for fresh menu warmup, push probes.

The packaged script repair runs during Java startup. Therefore probes must be
pushed after the fresh main menu is ready. This helper never loads a save.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import time

from scene_audit import Device


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--profile', default='userdata-audit20261019')
    parser.add_argument('--probes', type=Path, default=Path('build/scene-audit-20261019/probes/Scripts'))
    parser.add_argument('--out', type=Path, default=Path('build/scene-audit-20261019/startup'))
    parser.add_argument('--region-fast', choices=('0', '1'), default='0')
    parser.add_argument('--timeout', type=float, default=180)
    args = parser.parse_args()
    device = Device(args.serial, args.profile)
    files = sorted(args.probes.rglob('*.bin'))
    if len(files) != 24 or not (args.probes / 'world/world.bin').is_file():
        parser.error('export all 24 current QA probes first with scene_audit.py --script-probes')
    if args.timeout < 20:
        parser.error('startup timeout must allow at least twenty seconds')
    subprocess.run([*device.adb, 'shell', 'am', 'force-stop', 'org.thevoid.port'], check=True)
    # Clearing the stopped QA log prevents an old completion marker from
    # authorizing a /load while the fresh process is still booting.
    for name, contents in (('void.log', b''), ('live.txt', ('regionfast ' + args.region_fast + '\n').encode())):
        subprocess.run([*device.adb, 'shell', 'cat > ' + shlex.quote(device.remote + '/' + name)],
                       input=contents, check=True, timeout=20)
    subprocess.run([*device.adb, 'shell', 'am', 'start', '-n', 'org.thevoid.port/.GameActivity',
                    '--es', 'userdata', args.profile], check=True)
    deadline, previous = time.monotonic() + args.timeout, ''
    while time.monotonic() < deadline:
        time.sleep(1)
        native = device.log()
        progress = re.findall(r'\[shaderwarm\][^\n]+', native)
        if progress and progress[-1] != previous:
            previous = progress[-1]
            print(previous, flush=True)
        complete = re.search(r'\[shaderwarm\] complete (\d+)/(\d+), (\d+) unavailable', native)
        if complete:
            done, total, unavailable = map(int, complete.groups())
            if not total or done != total or unavailable:
                raise RuntimeError('fresh menu warmup did not complete with zero unavailable programs')
            break
    else:
        raise RuntimeError('fresh menu shader warmup did not finish before timeout')
    state = device.status()
    if not state['tags'] & 0x100000:
        raise RuntimeError('fresh warmup completed outside the original main menu')
    subprocess.run([*device.adb, 'push', str(args.probes), device.remote + '/overrides/'], check=True)
    wanted = {device.remote + '/overrides/Scripts/' + p.relative_to(args.probes).as_posix():
              hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    actual = device.shell('sha256sum ' + ' '.join(shlex.quote(p) for p in wanted))
    hashes = {line.split(None, 1)[1]: line.split(None, 1)[0] for line in actual.splitlines()}
    if hashes != wanted:
        raise RuntimeError('device QA probe hashes differ from the exported files')
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'warmup.log').write_text(native, encoding='utf-8')
    summary = dict(serial=args.serial, profile=args.profile, region_fast=int(args.region_fast),
                   warmed=total, unavailable=unavailable, verified_probes=len(files),
                   main_menu_hud=state['tags'], main_menu_frame=state['frame'])
    (args.out / 'startup.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
