"""Compare the shipping guarded worker transform prefix transform with emitted C."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_android
from build_android import CLANG, Image, localize_physics_worker
from build_x86_incremental import compiler_environment


def main():
    out = ROOT / 'build/physics-worker-fpu-test'
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'generated/physxcore-x86/physxcore_0098.c'
    host = ROOT / 'android/host/physics_native.c'
    runtime = ROOT / 'android/runtime/recomp_types.h'
    fixture = ROOT / 'tests/physics_worker_probe.c'
    paths = [source, host, runtime, ROOT / 'tools/build_android.py', fixture, Path(__file__)]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    body = re.search(r'^void sub_181F1F80\(void\) \{.*?^\}', source.read_text(), re.M | re.S)[0]
    guard = re.search(r'^int void_physics_worker_pair_finite\(.*?^\}', host.read_text(), re.M | re.S)[0]
    transformed = localize_physics_worker((body + '\n').encode()).decode()
    cut = '    RECOMP_CALL(sub_181E7720);'
    prefix = body[body.index('L_181F1F80:'):body.index(cut)]
    assert transformed.count('double l_st[8]') == 1
    assert transformed.count('RECOMP_FP_OUT(); goto L_181F2824_LOCAL_DONE;') == 1
    assert body[body.index(cut):] in transformed
    assert body.count('RECOMP_CALL(') == transformed.count('RECOMP_CALL(')
    assert body.count('RECOMP_ICALL(') == transformed.count('RECOMP_ICALL(')
    assert body.count('RECOMP_BACKEDGE();') == transformed.count('RECOMP_BACKEDGE();')
    assert not any(x in prefix for x in ['goto ', 'RECOMP_CALL(', 'RECOMP_ICALL(', 'RECOMP_BACKEDGE(', 'fp_push_i64(', '/=', 'sqrt('])
    for forbidden in ['RECOMP_CALL(sub_18000000);', 'RECOMP_ICALL(0x18000000);', 'RECOMP_BACKEDGE();', 'fp_push_i64(3);', 'goto L_181F2829;', '_st[0] /= _st[1];', '_st[0] = _st[1] / _st[2];', '_st[0] = sqrt(_st[0]);']:
        try:
            localize_physics_worker((body.replace('L_181F1F80:', 'L_181F1F80:\n' + forbidden, 1) + '\n').encode())
        except AssertionError:
            pass
        else:
            raise AssertionError('unsupported call/yield/branch in pure prefix was localized')
    other = b'void unrelated(void) {}\n'
    assert localize_physics_worker(other) == other
    temporary = out / 'tree.c'
    temporary.write_text(body + '\n')
    previous_release, previous_out = build_android.RELEASE, build_android.OUT
    try:
        build_android.RELEASE = {'name': 'other-release'}
        build_android.OUT = out / 'override'
        unchanged, flags = build_android.override_source(temporary, False)
        assert unchanged == temporary and not flags
        build_android.RELEASE = None
        changed, _ = build_android.override_source(temporary, False)
        assert changed != temporary and b'void_physics_worker_pair_finite' in changed.read_bytes()
    finally:
        build_android.RELEASE, build_android.OUT = previous_release, previous_out
    image = Image(ROOT / 'generated/input/PhysXCore.dll')
    assert image.u32(0x182f0548) == 0x40000000
    header = runtime.read_text().replace('#if defined(_MSC_VER) || !defined(__aarch64__)', '#if 0', 1)
    header, count = re.subn(r'static inline uint64_t __rdtsc\(void\) \{.*?\n\}', '', header, flags=re.S)
    assert count == 1
    header, count = re.subn(r'^#define ADDR\(va\).+$',
        'static void *guest_address(uint32_t va);\n#define ADDR(va) ((uintptr_t)guest_address((uint32_t)(va)))', header, flags=re.M)
    assert count == 1
    (out / 'runtime-fixture.h').write_text(header)
    # Counters wrap the actual shipping guard only in this fixture.
    counted = 'static unsigned fast_prefixes,fallback_prefixes;\n' + guard.replace('void_physics_worker_pair_finite', 'guard_actual', 1)
    counted += '\nint void_physics_worker_pair_finite(void) { int hit=guard_actual(); if(hit)++fast_prefixes;else ++fallback_prefixes;return hit;}\n'
    driver = fixture.read_text().replace('/* GUARD */', counted)
    names = sorted(set(re.findall(r'\bsub_[0-9A-F]+', body)) - {'sub_181F1F80'})
    stubs = '\n'.join('void %s(void);' % name for name in names)
    stubs += '\n' + '\n'.join('void %s(void) { abort(); }' % name for name in names if name != 'sub_181E7720')
    driver = driver.replace('/* STUBS */', stubs)
    driver = driver.replace('/* ORIGINALS */', body.replace('sub_181F1F80', 'original_worker'))
    driver = driver.replace('/* LOCALIZED */', transformed.replace('sub_181F1F80', 'candidate_worker'))
    _, env, _ = compiler_environment()
    env['LIB'] = env['LIB'].replace('\\x86', '\\x64')
    results = []
    for local in (False, True):
        for plain in (False, True):
            p = out / ('probe-r%d-p%d.c' % (local, plain))
            p.write_text(driver)
            executable = p.with_suffix('.exe')
            command = [str(CLANG), '--target=x86_64-pc-windows-msvc', '-fuse-ld=link', '-O2', '-std=c11',
                '-fno-strict-aliasing', '-fwrapv', '-ffp-contract=off', '-DRECOMP_TRACE', '-DRECOMP_YIELD_EVERY=1',
                *(['-DRECOMP_LOCAL_REGS'] if local else []), *(['-DRECOMP_PLAIN_MEMORY'] if plain else []),
                str(p), '-o', str(executable)]
            compiled = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
            p.with_suffix('.compile.log').write_text(compiled.stdout + compiled.stderr)
            assert compiled.returncode == 0, compiled.stdout + compiled.stderr
            checked = subprocess.run([str(executable)], cwd=ROOT, capture_output=True, text=True, timeout=120)
            p.with_suffix('.run.log').write_text(checked.stdout + checked.stderr)
            print('regs=%s plain=%s: %s' % (local, plain, checked.stdout.strip()), flush=True)
            assert checked.returncode == 0, checked.stdout + checked.stderr
            matched = re.search(r'F1F80 (\d+) full-state boundaries fast(\d+) fallback(\d+)', checked.stdout)
            results.append(dict(local_regs=local, plain_memory=plain, comparisons=int(matched[1]),
                fast_prefixes=int(matched[2]), fallback_prefixes=int(matched[3]), output=checked.stdout.strip()))
    assert hashes == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    receipt = dict(status='PASS', comparisons=sum(r['comparisons'] for r in results), results=results, source_hashes=hashes,
        oracle='actual shipping builder pass and host guard vs original whole emitted worker/current Android global x87 helpers, stopped at unchanged first callee',
        scope='Whole guest memory/GPR/flags/FP/shadows/XMM/MM/trace/current at first call; bounded and raw IEEE transforms, frame/input aliases, nonempty FP, stack/pointer guard boundaries, disabled fallback. Continuation is byte-exact; no call/yield/branch in prefix.',
        limitations=['No execution of original PE or hardware performance proof.', 'Original live-object/stack and immutable PE constants contracts remain.'])
    (out / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
