"""Prove native weighted region accumulation against the emitted implementation."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_android import CLANG, HOST_FLAGS, Image, localize_fpu, localize_sse
from build_x86_incremental import compiler_environment
from test_renderer_append import function


def main():
    out = ROOT / 'build/region-native-test'
    out.mkdir(parents=True, exist_ok=True)
    native_path = ROOT / 'android/host/renderer_region_native.c'
    for plain in (False, True):
        macros = subprocess.run([str(CLANG), *HOST_FLAGS,
            *(['-DRECOMP_PLAIN_MEMORY'] if plain else []), '-E', '-dM', str(native_path)],
            cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
        assert ('#define RECOMP_MEM_QUAL' if plain else '#define RECOMP_MEM_QUAL volatile') in [m.rstrip() for m in macros]
    paths = [ROOT / 'generated/renderer-x86/renderer_0006.c',
             ROOT / 'generated/renderer-x86/renderer_0074.c',
             ROOT / 'generated/renderer-x86/renderer_0161.c',
             ROOT / 'android/runtime/recomp_types.h', native_path,
             ROOT / 'tools/build_android.py',
             ROOT / 'tests/region_native_probe.c', ROOT / 'tests/region_native_checks.c']
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    header = paths[3].read_text()
    header = header.replace('#if defined(_MSC_VER) || !defined(__aarch64__)', '#if 0', 1)
    header, count = re.subn(r'static inline uint64_t __rdtsc\(void\) \{.*?\n\}', '', header, flags=re.S)
    assert count == 1
    header, count = re.subn(r'^#define ADDR\(va\).+$',
        'static void *guest_address(uint32_t va);\n#define ADDR(va) ((uintptr_t)guest_address((uint32_t)(va)))',
        header, flags=re.M)
    assert count == 1
    (out / 'runtime-fixture.h').write_text(header)
    image = Image(ROOT / 'generated/input/RendererD3D.dll')
    constants = '\n'.join('    if(va == 0x%xu) { static uint32_t value = 0x%xu; return &value; }' % (va, image.u32(va))
        for va in (0x162ec320, 0x162ec35c, 0x162ec3ec, 0x162d2f24, 0x162d2a64))
    helpers = '\n'.join((function(paths[0], 'sub_160145A0'),
                         function(paths[1], 'sub_160D6ED0'), function(paths[2], 'sub_1620EA40')))
    native = native_path.read_text().replace('#include "host.h"', '#define GUEST_USER_TOP 0x7ffe0000u')
    native = re.sub(r'^void sub_16013760\(void\)\n\{.*?^\}', '', native, flags=re.M | re.S)
    checks = (ROOT / 'tests/region_native_checks.c').read_text()
    driver = (ROOT / 'tests/region_native_probe.c').read_text()
    _, env, _ = compiler_environment()
    env['LIB'] = env['LIB'].replace('\\x86', '\\x64')
    results = []
    configurations = [(local, sse, plain, False) for plain in (False, True)
                      for local, sse in ((False, False), (True, False), (True, True))]
    configurations += [(True, True, plain, True) for plain in (False, True)]
    for local, sse, plain, production_helpers in configurations:
        original = (function(paths[0], 'sub_16013760') + '\n').encode()
        if sse:
            original = localize_sse(original)
        original = original.replace(b'void sub_16013760(void)', b'void original_region(void)', 1)
        selected_helpers = helpers
        if production_helpers:
            # Shipping helpers use both passes: local SSE plus the guarded
            # local-x87 SAT body and its original global-x87 fallback.
            selected_helpers = localize_fpu(localize_sse((helpers + '\n').encode())).decode()
            assert 'int l_fp_top = g_fp_top;' in selected_helpers
            assert 'sub_160D6ED0_fp_global(void)' in selected_helpers
            assert 'xmm_t l_xmm[8];' in selected_helpers
            selected_helpers = 'int void_renderer_native_enabled(void) { return 1; }\n' + selected_helpers
        text = driver.replace('/* CONSTANTS */', constants).replace('/* HELPERS */', selected_helpers)
        text = text.replace('/* ORIGINAL */', original.decode()).replace('/* OPTIMIZED */', '')
        text = text.replace('static uint32_t random_state', native + '\nvoid sub_16013760(void);\nstatic uint32_t random_state', 1)
        text += '\n' + checks
        source = out / ('native-reg%d-sse%d-plain%d-helpers%d.c' % (local, sse, plain, production_helpers))
        source.write_text(text)
        exe = source.with_suffix('.exe')
        built = subprocess.run([str(CLANG), '--target=x86_64-pc-windows-msvc', '-fuse-ld=link', '-O2', '-std=c11',
            '-fno-strict-aliasing', '-fwrapv', '-ffp-contract=off', '-DRECOMP_TRACE',
            *(['-DRECOMP_LOCAL_REGS'] if local else []), *(['-DRECOMP_PLAIN_MEMORY'] if plain else []),
            *(['-DREGION_PRODUCTION_HELPERS'] if production_helpers else []),
            str(source), '-o', str(exe)], cwd=ROOT, env=env, capture_output=True, text=True)
        assert built.returncode == 0, built.stdout + built.stderr
        tested = subprocess.run([str(exe)], cwd=ROOT, capture_output=True, text=True, timeout=90)
        assert tested.returncode == 0, tested.stdout + tested.stderr
        print('production_helpers=%s: %s' % (production_helpers, tested.stdout.strip()))
        results.append(dict(local_registers=local, local_sse=sse, plain_memory=plain,
            production_helpers=production_helpers, output=tested.stdout.strip()))
    assert hashes == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (out / 'result.json').write_text(json.dumps(dict(status='PASS', source_hashes=hashes, results=results,
        oracle='actual emitted weighted region, RGBE, fabs and SAT; shared ldexp boundary stub',
        compared='all guest memory outside proven dead 512-byte scratch; callee-saved registers, AL/ESP/final flags/live x87',
        excluded='ABI caller-saved GPR/XMM, dead x87 slots, trace and scheduling counters',
        original_pe_executed=False), indent=2))


if __name__ == '__main__':
    main()
