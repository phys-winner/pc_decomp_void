"""Test the real host dispatch/shim bodies against this machine's Win32 APIs."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from test_memmove import compiler_environment

ROOT = Path(__file__).resolve().parents[1]


def extract(source, name):
    match = re.search(r"^(?:static void|recomp_func_t) " + re.escape(name) + r"\([^\n]*\)\s*\{", source, re.M)
    assert match, name
    depth = 1
    end = match.end()
    while depth:
        if source[end] == "{": depth += 1
        if source[end] == "}": depth -= 1
        end += 1
    return source[match.start():end]


def main():
    output = ROOT / 'build/thread-api-shims'
    output.mkdir(parents=True, exist_ok=True)
    host = ROOT / 'native/windows_host.c'
    before = hashlib.sha256(host.read_bytes()).hexdigest()
    source = host.read_text()
    names = ('thread_get_error', 'thread_set_error', 'thread_tls_value', 'thread_fls_value', 'recomp_lookup_manual')
    (output / 'host-shims.h').write_text('\n\n'.join(extract(source, name) for name in names) + '\n')
    compiler, env, sdk = compiler_environment()
    executable = output / 'probe.exe'
    command = [str(compiler), '/nologo', '/O2', '/W3', '/std:c11', '/D_CRT_SECURE_NO_WARNINGS',
        f'/I{output}', 'tests/thread_api_shims_probe.c', f'/Fo{output}\\', f'/Fe{executable}',
        '/link', '/MACHINE:X86', '/NXCOMPAT']
    compiled = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    (output / 'compile.log').write_text(compiled.stdout + compiled.stderr)
    if compiled.returncode: raise RuntimeError(compiled.stdout + compiled.stderr)
    tested = subprocess.run([str(executable)], cwd=ROOT, capture_output=True, text=True, timeout=20)
    (output / 'result.json').write_text(json.dumps({'compiler': str(compiler), 'sdk': sdk,
        'host_sha256': before, 'test_source_sha256': hashlib.sha256((ROOT / 'tests/thread_api_shims_probe.c').read_bytes()).hexdigest(),
        'exit': tested.returncode, 'output': tested.stdout + tested.stderr,
        'no_game_pe_or_dll_loaded': True}, indent=2))
    assert before == hashlib.sha256(host.read_bytes()).hexdigest(), 'Host changed during test'
    print(tested.stdout + tested.stderr, end='')
    assert tested.returncode == 0, 'Thread API shim or strict dispatch check failed'


if __name__ == '__main__': main()
