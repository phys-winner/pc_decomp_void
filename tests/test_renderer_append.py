"""Differential reserved append against the actual emitted body and copy helper."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_x86_incremental import compiler_environment


def function(path, name):
    source = path.read_text()
    match = re.search(r'^void ' + name + r'\(void\) \{.*?^\}', source, re.M | re.S)
    assert match, (path, name)
    return match[0]


def main():
    out = ROOT / 'build/renderer-append-test'
    out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / 'generated/renderer-x86/renderer_0047.c',
               ROOT / 'generated/renderer-x86/renderer_0032.c', ROOT / 'android/host/renderer_native.c']
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    header = function(sources[1], 'sub_16056EE0')
    header += '\n' + function(sources[0], 'sub_16082260').replace('void sub_16082260(void)', 'void original_append(void)')
    native = sources[2].read_text().replace('#include "host.h"', '')
    driver = (ROOT / 'tests/renderer_append_probe.c').read_text().replace('/* EMITTED */', header).replace('/* NATIVE */', native)
    (out / 'probe.c').write_text(driver)
    compiler, env, _ = compiler_environment()
    results = []
    for local in (False, True):
        exe = out / ('probe-local%d.exe' % local)
        result = subprocess.run([str(compiler), '/nologo', '/O2', '/W3', '/std:c11',
                                 '/DRECOMP_TRACE', *(['/DRECOMP_LOCAL_REGS'] if local else []),
                                 '/Inative', '/Ireference/pcrecomp/runtime/recomp32', str(out / 'probe.c'),
                                 '/Fe' + str(exe), '/Fo' + str(out / ('probe-local%d.obj' % local))],
                                env=env, cwd=ROOT, check=True, capture_output=True, text=True)
        checked = subprocess.run([str(exe)], check=True, capture_output=True, text=True)
        print(checked.stdout.strip())
        results.append(dict(local_registers=local, output=checked.stdout.strip()))
    assert hashes == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    (out / 'result.json').write_text(json.dumps(dict(status='PASS', source_hashes=hashes, results=results,
                                                   original_pe_loaded=False, generated_sources_unchanged=True), indent=2))


if __name__ == '__main__':
    main()
