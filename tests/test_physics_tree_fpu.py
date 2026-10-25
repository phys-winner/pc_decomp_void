"""Compare the shipping guarded per-node PhysX tree transform with emitted C."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_android
from build_android import CLANG, Image, localize_physics_tree
from build_x86_incremental import compiler_environment


def main():
    out = ROOT / 'build/physics-tree-fpu-test'
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'generated/physxcore-x86/physxcore_0074.c'
    host = ROOT / 'android/host/physics_native.c'
    runtime = ROOT / 'android/runtime/recomp_types.h'
    fixture = ROOT / 'tests/physics_tree_probe.c'
    paths = [source, host, runtime, ROOT / 'tools/build_android.py', fixture, Path(__file__)]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    body = re.search(r'^void sub_1819AF40\(void\) \{.*?^\}', source.read_text(), re.M | re.S)[0]
    guard = re.search(r'^int void_physics_tree_node_finite\(.*?^\}', host.read_text(), re.M | re.S)[0]
    transformed = localize_physics_tree((body + '\n').encode()).decode()
    assert transformed.count('double l_st[8]') == 1
    # Six branches share five external cleanup targets.
    assert transformed.count('{ RECOMP_FP_OUT(); goto L_') == 6
    assert transformed.count('RECOMP_FP_OUT(); goto L_1819B075;') == 1
    # The original recursive/callback and postcallback work remains byte exact.
    assert body[body.index('L_1819B075:'):] in transformed
    assert body.count('RECOMP_CALL(') == transformed.count('RECOMP_CALL(') == 2
    assert body.count('RECOMP_ICALL(') == transformed.count('RECOMP_ICALL(') == 1
    assert body.count('RECOMP_BACKEDGE();') == transformed.count('RECOMP_BACKEDGE();') == 1
    for forbidden in ['RECOMP_CALL(sub_18000000);', 'RECOMP_ICALL(0x18000000);', 'RECOMP_BACKEDGE();', 'fp_push_i64(3);']:
        try:
            localize_physics_tree((body.replace('L_1819AF5B:', 'L_1819AF5B:\n' + forbidden, 1) + '\n').encode())
        except AssertionError:
            pass
        else:
            raise AssertionError('unsupported call/yield in pure block was localized')
    other = b'void unrelated(void) {}\n'
    assert localize_physics_tree(other) == other
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
        assert changed != temporary and b'void_physics_tree_node_finite' in changed.read_bytes()
    finally:
        build_android.RELEASE, build_android.OUT = previous_release, previous_out
    image = Image(ROOT / 'generated/input/PhysXCore.dll')
    assert image.u32(0x182f054c) == 0x3f000000 and image.u32(0x182f0400) == 0
    header = runtime.read_text().replace('#if defined(_MSC_VER) || !defined(__aarch64__)', '#if 0', 1)
    header, count = re.subn(r'static inline uint64_t __rdtsc\(void\) \{.*?\n\}', '', header, flags=re.S)
    assert count == 1
    header, count = re.subn(r'^#define ADDR\(va\).+$',
        'static void *guest_address(uint32_t va);\n#define ADDR(va) ((uintptr_t)guest_address((uint32_t)(va)))', header, flags=re.M)
    assert count == 1
    (out / 'runtime-fixture.h').write_text(header)
    # Fixture counters wrap the actual extracted guard without changing it.
    counted = 'static unsigned fast_nodes,fallback_nodes;\n' + guard.replace('void_physics_tree_node_finite', 'guard_actual', 1)
    counted += '\nint void_physics_tree_node_finite(uint32_t c,uint32_t n,uint32_t f) { int hit=guard_actual(c,n,f); if(hit)++fast_nodes;else ++fallback_nodes;return hit;}\n'
    driver = fixture.read_text().replace('/* GUARD */', counted)
    driver = driver.replace('/* ORIGINALS */', body.replace('sub_1819AF40', 'original_af40'))
    driver = driver.replace('/* LOCALIZED */', transformed.replace('sub_1819AF40', 'candidate_af40'))
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
            matched = re.search(r'AF40 (\d+) full-state trees fast(\d+) fallback(\d+)', checked.stdout)
            results.append(dict(local_regs=local, plain_memory=plain, comparisons=int(matched[1]),
                fast_nodes=int(matched[2]), fallback_nodes=int(matched[3]), output=checked.stdout.strip()))
    assert hashes == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    receipt = dict(status='PASS', comparisons=sum(r['comparisons'] for r in results), results=results, source_hashes=hashes,
        oracle='actual shipping builder pass and actual host guard vs original whole emitted recursive function/current Android global x87 helpers',
        scope='Whole guest memory/GPR/flags/FP/shadows/XMM/MM; callback-visible state+memory hashes; recursive depth0-5, callback/query/next-node mutations, raw IEEE/boundary/alias/nonemptyFP/yield+reload/disabled fallback',
        limitations=['No execution of original PE or hardware performance proof.', 'Original live-object/stack and immutable PE constants contracts remain.'])
    (out / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
