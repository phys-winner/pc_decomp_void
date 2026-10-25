"""Exercise the actual host's script-console interception and file shim ABI."""
import hashlib
import json
from pathlib import Path
import subprocess
from test_memmove import compiler_environment
from test_thread_api_shims import extract
from test_host_dependency import extract as extract_typed

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT / 'build/host-menu-abi'
    out.mkdir(parents=True, exist_ok=True)
    host = ROOT / 'native/windows_host.c'
    before = hashlib.sha256(host.read_bytes()).hexdigest()
    watched = [ROOT / p for p in ('native/windows_host.c', 'native/void_runtime.c', 'native/recomp_types.h',
        'reference/pcrecomp/runtime/native32/native32.c', 'reference/pcrecomp/runtime/recomp32/recomp_types.h',
        'tests/host_menu_abi_probe.c')]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}
    source = host.read_text()
    names = ('native_menu_call', 'native_menu_publish_settings', 'native_menu_command',
             'game_show_window', 'game_window_position', 'show_window', 'window_position', 'asset_create_file_a', 'asset_create_file_w',
             'asset_attributes_a', 'asset_attributes_w', 'thread_get_error', 'thread_set_error',
             'thread_tls_value', 'thread_fls_value', 'recomp_lookup_manual')
    (out / 'host-menu.h').write_text('\n\n'.join(
        (extract_typed if n in ('game_show_window', 'game_window_position') else extract)(source, n) for n in names))
    compiler, env, sdk = compiler_environment()
    exe = out / 'probe.exe'
    compiled = subprocess.run([str(compiler), '/nologo', '/O2', '/W4', '/WX', '/std:c11',
        '/D_CRT_SECURE_NO_WARNINGS', f'/I{out}',
        '/DVOID_LIFT_GAMEMODULE',
        '/Inative', '/Ireference/pcrecomp/runtime/recomp32', '/Ireference/pcrecomp/runtime/native32',
        'tests/host_menu_abi_probe.c',
        'reference/pcrecomp/runtime/recomp32/image_loader.c', 'reference/pcrecomp/runtime/recomp32/recomp_trace.c',
        f'/Fo{out}\\', f'/Fe{exe}', '/link', '/MACHINE:X86', '/NXCOMPAT'],
        cwd=ROOT, env=env, capture_output=True, text=True)
    (out / 'compile.log').write_text(compiled.stdout + compiled.stderr)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    tested = subprocess.run([str(exe)], capture_output=True, text=True, timeout=15)
    (out / 'result.json').write_text(json.dumps(dict(host_sha256=before, compiler=str(compiler),
        sdk=sdk, exit=tested.returncode, output=tested.stdout + tested.stderr,
        source_hashes=hashes, actual_extracted_functions=names, real_native32_import_bridge=True,
        snapshot='Controlled fifteen numeric Port keys; actual backend tested separately',
        no_game_pe_or_original_dll_loaded=True), indent=2))
    assert before == hashlib.sha256(host.read_bytes()).hexdigest(), 'Host changed during test'
    assert hashes == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}, 'Probe/runtime source changed during test'
    print(tested.stdout + tested.stderr, end='')
    assert tested.returncode == 0


if __name__ == '__main__':
    main()
