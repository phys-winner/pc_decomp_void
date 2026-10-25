"""Compare the shipped PhysX sweep leaf with its guarded local-x87 transform."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_android
from build_android import CLANG, localize_fpu
from build_x86_incremental import compiler_environment


def main():
    out = ROOT / 'build/physics-sweep-fpu-test'
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'generated/physxcore-x86/physxcore_0018.c'
    host = ROOT / 'android/host/physics_native.c'
    runtime = ROOT / 'android/runtime/recomp_types.h'
    driver_path = ROOT / 'tests/physics_sweep_probe.c'
    paths = [source, host, runtime, ROOT / 'tools/build_android.py', driver_path, Path(__file__)]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    body = re.search(r'^void sub_18064830\(void\) \{.*?^\}', source.read_text(), re.M | re.S)[0]
    assert 'RECOMP_CALL(' not in body and 'RECOMP_ICALL(' not in body and 'fp_push_i64(' not in body
    assert body.count('RECOMP_BACKEDGE();') == 2 and 'xmm' not in body
    guard = re.search(r'^int void_physics_sweep_finite\(void\)\s*\{.*?^\}', host.read_text(), re.M | re.S)[0]
    localized = localize_fpu((body + '\n').encode()).decode()
    assert 'if (!void_physics_sweep_finite())' in localized
    assert localized.count('double l_st[8]') == 1 and '_fp_global(void)' in localized
    for forbidden in ['RECOMP_CALL(sub_18000000);', 'RECOMP_ICALL(0x18000000);', 'fp_push_i64(3);']:
        try:
            localize_fpu(body.replace('RECOMP_ENTER(', forbidden + '\n    RECOMP_ENTER(', 1).encode())
        except AssertionError:
            pass
        else:
            raise AssertionError('unsupported physics body was localized')
    fixture = out / 'sweep.c'
    fixture.write_text(body + '\n')
    previous_release, previous_out = build_android.RELEASE, build_android.OUT
    try:
        build_android.RELEASE = {'name': 'other-release'}
        build_android.OUT = out / 'override'
        unchanged, flags = build_android.override_source(fixture, False)
        assert unchanged == fixture and not flags
        build_android.RELEASE = None
        transformed, _ = build_android.override_source(fixture, False)
        assert transformed != fixture and b'void_physics_sweep_finite' in transformed.read_bytes()
    finally:
        build_android.RELEASE, build_android.OUT = previous_release, previous_out

    # Host-only adaptations match the existing exact-state local-FPU fixtures.
    header = runtime.read_text()
    architecture = '#if defined(_MSC_VER) || !defined(__aarch64__)'
    assert header.count(architecture) == 1
    header = header.replace(architecture, '#if 0', 1)
    header, count = re.subn(r'static inline uint64_t __rdtsc\(void\) \{.*?\n\}', '', header, flags=re.S)
    assert count == 1
    header, count = re.subn(r'^#define ADDR\(va\).+$',
        'static void *guest_address(uint32_t va);\n#define ADDR(va) ((uintptr_t)guest_address((uint32_t)(va)))',
        header, flags=re.M)
    assert count == 1
    (out / 'runtime-fixture.h').write_text(header)
    original = body.replace('void sub_18064830(void)', 'void original_leaf(void)', 1)
    driver = driver_path.read_text().replace('/* ORIGINALS */', original)
    driver = driver.replace('/* LOCALIZED */', localized).replace('/* GUARD */', guard)
    _, env, _ = compiler_environment()
    env['LIB'] = env['LIB'].replace('\\x86', '\\x64')
    results = []
    for local in (False, True):
        for plain in (False, True):
            p = out / ('probe-reg%d-plain%d.c' % (local, plain))
            p.write_text(driver)
            executable = p.with_suffix('.exe')
            command = [str(CLANG), '--target=x86_64-pc-windows-msvc', '-fuse-ld=link', '-O2', '-std=c11',
                '-fno-strict-aliasing', '-fwrapv', '-ffp-contract=off', '-DRECOMP_TRACE', '-DRECOMP_YIELD_EVERY=1',
                *(['-DRECOMP_LOCAL_REGS'] if local else []), *(['-DRECOMP_PLAIN_MEMORY'] if plain else []),
                str(p), '-o', str(executable)]
            compiled = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
            p.with_suffix('.compile.log').write_text(compiled.stdout + compiled.stderr)
            assert compiled.returncode == 0, compiled.stdout + compiled.stderr
            checked = subprocess.run([str(executable)], cwd=ROOT, capture_output=True, text=True, timeout=90)
            p.with_suffix('.run.log').write_text(checked.stdout + checked.stderr)
            assert checked.returncode == 0, checked.stdout + checked.stderr
            print('regs=%s plain=%s: %s' % (local, plain, checked.stdout.strip()), flush=True)
            comparisons = int(re.search(r'PhysX18064830 (\d+) full-state cases', checked.stdout)[1])
            results.append(dict(local_regs=local, plain_memory=plain, comparisons=comparisons, output=checked.stdout.strip()))
    assert hashes == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    receipt = dict(status='PASS', comparisons=sum(r['comparisons'] for r in results), results=results,
        source_hashes=hashes, oracle='actual emitted shipping leaf/current Android global helpers vs actual production localizer and host guard',
        scope='Full guest memory/GPR/flags/x87/shadows/CW/MXCSR/MM/XMM/current/backedge state; finite/IEEE/overflow/alias/nonemptyFP/yields+reload/fallback',
        limitations=['Original PE is not executed.', 'Caller contract supplies five live fixed vec3 inputs and two live outputs.',
                     'No arbitrary concurrent nonfinite geometry mutation proof or hardware performance claim.'])
    (out / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
