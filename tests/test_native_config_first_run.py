"""Real emitted FirstRun gate + extracted host getter; no registry/game writes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

from test_first_run import DRIVER, original, ENTRY, BASE, API, analyze_pe, Disassembler
from test_memmove import compiler_environment

ROOT = Path(__file__).resolve().parents[1]

READY_MAIN = r'''
int main(int argc, char **argv) {
    if (argc != 2) return 93;
    FILE *f = fopen(argv[1], "rb"); if (!f) return 94;
    fseek(f, 0, SEEK_END); long span = ftell(f); rewind(f);
    void *im = VirtualAlloc(NULL, span, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!im) return 95;
    g_mem_base = (ptrdiff_t)((uint32_t)(uintptr_t)im - 0x400000u);
    void *stack = VirtualAlloc((void *)ADDR(0x20000000u), 0x10000,
        MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (stack != (void *)ADDR(0x20000000u)) return 95;
    if (fread(im, 1, span, f) != (size_t)span) return 96;
    fclose(f);
    native_menu_enabled = 1;
    if (!void_native_config_ready()) return 97;
    unsigned count = 0;
    for (unsigned bits = 0; bits < 64; ++bits) {
        uint32_t flags = 2u | ((bits & 1u) ? 1u : 0u) |
            ((bits & 2u) ? 4u : 0u) | ((bits & 4u) ? 16u : 0u) |
            ((bits & 8u) ? 64u : 0u) | ((bits & 16u) ? 128u : 0u) |
            ((bits & 32u) ? 2048u : 0u);
        for (uint32_t window = 0; window <= 2; ++window) {
            memset(stack, 0xA5, 0x10000);
            g_eax = 0x76543210; g_ecx = 0x10203040; g_edx = 0x50607080;
            g_ebx = 0x11223344; g_esp = 0x20008000; g_ebp = 0x55667788;
            g_esi = 0x99AABBCC; g_edi = 0xDDEEFF00;
            MEM32(g_esp) = 0x30000000; MEM32(g_esp + 4) = 0x400200;
            MEM32(0x44B94C) = window;
            g_flag_k = FK_EFLAGS; g_flag_a = flags;
            g_flag_b = 0xC0FFEE03; g_flag_cf = flags & 1u; calls = 0;
            sub_00436A10();
            if (g_eax != 0x76543200 || g_ecx != 0x10203040 ||
                g_edx != 0x50607080 || g_ebx != 0x11223344 ||
                g_esp != 0x20008004 || g_ebp != 0x55667788 ||
                g_esi != 0x99AABBCC || g_edi != 0xDDEEFF00) return 98;
            if (g_flag_k != FK_EFLAGS || g_flag_a != flags ||
                g_flag_b != 0xC0FFEE03 || g_flag_cf != (flags & 1u) ||
                (recomp_eflags(g_flag_k, g_flag_a, g_flag_b, g_flag_cf, 1) & 0x8D5)
                    != (flags & 0x8D5)) return 99;
            if (MEM32(0x44B94C) != (window == 1 ? 0 : window) || calls ||
                MEM32(0x20008000) != 0x30000000 ||
                MEM32(0x20008004) != 0x400200 ||
                MEM32(0x20007FFC) != 0xA5A5A5A5 ||
                MEM32(0x20008008) != 0xA5A5A5A5) return 100;
            ++count;
        }
    }
    printf("PASS ready=1 %u GPR/AL/cdecl/flags/global/no-registry cases\n", count);
    return 0;
}
'''


def main():
    out = ROOT / 'build/native-config-first-run'
    out.mkdir(parents=True, exist_ok=True)
    binary = ROOT / 'generated/input/Game.exe'
    raw = binary.read_bytes()
    expected_hash = json.loads((ROOT / 'port.json').read_text())['game_exe']['recovered_sha256']
    assert hashlib.sha256(raw).hexdigest() == expected_hash
    info = analyze_pe(str(binary))
    reader = Disassembler(raw, info.image_base, info.sections)
    assert info.image_base == BASE
    span = (max(s.va_end for s in info.sections) + 0xFFF) & ~0xFFF
    image = bytearray(span)
    for section in info.sections:
        image[section.virtual_address:section.virtual_address + section.raw_size] = \
            raw[section.raw_offset:section.raw_offset + section.raw_size]
    for slot, target in ((0x43F004, API), (0x43F008, API + 0x1000), (0x43F000, API + 0x2000)):
        struct.pack_into('<I', image, slot - BASE, target)
    mapped = out / 'image.bin'
    mapped.write_bytes(image)
    spec = importlib.util.spec_from_file_location('void_first_run_lifter', ROOT / 'tools/lift_game.py')
    lifter = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = lifter
    spec.loader.exec_module(lifter)
    imports = lifter.build_iat_map(info)
    decoder = lifter.BoundedDisassembler(raw, info.image_base, info.sections)
    function = decoder.disassemble_function(ENTRY, imports)
    lifter.emit_functions(out / 'emitted', imports, decoder, {ENTRY: function}, label='FirstRun fixture')
    full = (out / 'emitted/recomp_0000.c').read_text()
    body = full[full.index('void sub_00436A10(void)'):]
    host = (ROOT / 'native/windows_host.c').read_text()
    getters = re.findall(r'^int void_native_config_ready\(void\)\n\{.*?^\}', host, re.M | re.S)
    assert len(getters) == 1
    getter = getters[0]
    actual = DRIVER.replace('int void_native_config_ready(void) { return 0; }',
        'static int native_menu_enabled = 1;\n' + getter).replace('/* BODY */', body)
    compiler, env, sdk = compiler_environment()
    variants = [('legacy', False, False), ('ready-global', True, False), ('ready-local', True, True)]
    results = []
    scenarios = [(opened, queried, kind, value, closed, flag)
        for opened, queried, kind, value, closed in ((0, 2, 4, 0, 0), (0, 0, 4, 0, 0),
            (0, 0, 4, 1, 0), (0, 0, 4, 0xFFFFFFFF, 0), (0, 0, 1, 0, 0),
            (0, 5, 4, 0, 0), (2, 0, 4, 0, 0), (5, 0, 4, 0, 0),
            (0, 0, 4, 0, 5), (0, 0, 4, 1, 5)) for flag in (0, 1, 2)]
    for name, modern, local in variants:
        c = out / (name + '.c'); exe = out / (name + '.exe')
        c.write_text(actual[:actual.index('int main(')] + READY_MAIN if modern else actual)
        command = [str(compiler), '/nologo', '/O2', '/std:c11', '/D_CRT_SECURE_NO_WARNINGS',
            '/I' + str(ROOT / 'native'), '/I' + str(ROOT / 'reference/pcrecomp/runtime/recomp32'),
            *(['/DVOID_LIFT_GAMEMODULE'] if modern else []),
            *(['/DRECOMP_LOCAL_REGS'] if local else []), str(c),
            '/Fo' + str(out / (name + '.obj')), '/Fe' + str(exe),
            '/link', '/BASE:0x70000000', '/DYNAMICBASE:NO', '/STACK:262144']
        compiled = subprocess.run(command, env=env, cwd=out, capture_output=True, text=True)
        (out / (name + '-compile.log')).write_text(compiled.stdout + compiled.stderr)
        assert compiled.returncode == 0, compiled.stdout + compiled.stderr
        if modern:
            tested = subprocess.run([str(exe), str(mapped)], capture_output=True, text=True, timeout=15)
            assert tested.returncode == 0, (name, tested.returncode, tested.stdout, tested.stderr)
            assert '192' in tested.stdout
            results.append({'variant': name, 'cases': 192, 'output': tested.stdout.strip()})
        else:
            for scenario in scenarios:
                expected = original(image, scenario)
                got = list(map(int, subprocess.check_output(
                    [str(exe), str(mapped), *map(str, scenario)], text=True).split()))
                assert got == expected, (scenario, expected, got)
            results.append({'variant': name, 'cases': len(scenarios),
                'getter': 'actual host getter returns0 without VOID_LIFT_GAMEMODULE, even with native_menu_enabled=1',
                'original_x86_oracle': 'PASS eight GPRs/six arithmetic flags/global/API counts'})
    (out / 'result.json').write_text(json.dumps({'status': 'PASS', 'variants': results,
        'emitted_body_sha256': hashlib.sha256(body.encode()).hexdigest(),
        'actual_getter_sha256': hashlib.sha256(getter.encode()).hexdigest(),
        'input_sha256': expected_hash, 'compiler': str(compiler), 'sdk': sdk,
        'no_real_registry_or_config_exe': True}, indent=2))
    print('PASS: actual getter legacy30 original-x86 cases; ready384 GPR/AL/cdecl/flags/global/no-registry cases')


if __name__ == '__main__':
    main()
