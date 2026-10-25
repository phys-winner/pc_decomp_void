"""Emit a timed input script (android/host/script.c) that paints one gesture
template from data/Gestures.vfs (player.gdb) with L Ctrl held:
  glyph_script.py NAME START_SECONDS [--sample N] [--center X Y] [--height PX] [--duration S]
Coordinates are the game's 1280x720 back buffer; recognition happens in
800x600 space and needs a vertical extent of at least 200 there."""
import argparse
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path


def templates():
    # VOID_VFS_INDEX: another release's index (research/vfs-index.polish.json for Tension).
    index = json.loads(Path(os.environ.get('VOID_VFS_INDEX', 'research/vfs-index.json')).read_text())
    container = next(c for c in index['containers'] if c['name'] == 'Gestures.vfs')
    entry = next(e for e in container['entries'] if e['name'].endswith('player.gdb'))
    with (Path(index['source']) / container['name']).open('rb') as f:
        f.seek(entry['offset'])
        root = ET.fromstring(f.read(entry['size']))
    found = {}
    for g in root:
        points = [(float(p.find('X').text), float(p.find('Y').text)) for p in g.find('Points')]
        found.setdefault(g.get('Name'), []).append(points)
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('name')
    parser.add_argument('start', type=float)
    parser.add_argument('--sample', type=int, default=0)
    parser.add_argument('--center', type=float, nargs=2, default=(640, 360))
    parser.add_argument('--height', type=float, default=300)
    parser.add_argument('--duration', type=float, default=4.0)
    parser.add_argument('--live', action='store_true', help='untimed commands with sleeps (VOID_INPUT_LIVE), L Ctrl already held')
    args = parser.parse_args()
    points = templates()[args.name][args.sample]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    scale = args.height / max(max(ys) - min(ys), 1.0)
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    screen = [(round(args.center[0] + (x - cx) * scale), round(args.center[1] + (y - cy) * scale)) for x, y in points]
    if args.live:
        step = args.duration / max(len(screen) - 1, 1)
        lines = [f'warp {screen[0][0]} {screen[0][1]}', 'sleep 0.3', 'bdown 0']
        for x, y in screen[1:]:
            lines += [f'sleep {step:.3f}', f'warp {x} {y}']
        lines += ['sleep 0.3', 'bup 0']
        print('\n'.join(lines))
        return
    t = args.start
    lines = [f'{t:.2f} down A2', f'{t + 0.8:.2f} warp {screen[0][0]} {screen[0][1]}', f'{t + 1.0:.2f} bdown 0']
    t += 1.2
    step = args.duration / max(len(screen) - 1, 1)
    for x, y in screen[1:]:
        t += step
        lines.append(f'{t:.2f} warp {x} {y}')
    lines += [f'{t + 0.3:.2f} bup 0', f'{t + 0.8:.2f} up A2']
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
