"""Measure the actual emitted FNSAVE/FRSTOR no-op against native x86 instructions."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from lift_game import BoundedDisassembler, CheckedLifter, lift_function_linear
from tools.pe.pe_analyze import analyze_pe
from test_memmove import compiler_environment


def main():
    out = ROOT / 'build/x87-save-gap'; out.mkdir(parents=True, exist_ok=True)
    path = Path(json.loads((ROOT / 'port.json').read_text())['game_directory']) / 'bin/win32/RendererD3D.dll'
    raw = path.read_bytes()
    pin = 'a58ee315725502cd295600841accbd2a0df750443aefdd0dd4d9cc709604dbf3'
    assert hashlib.sha256(raw).hexdigest() == pin
    info = analyze_pe(str(path))
    original = BoundedDisassembler(raw, info.image_base, info.sections)
    sources = []
    for address, expected in ((0x10259D8D, 'dd7108'), (0x10259D99, 'dd6108')):
        offset = next(s.raw_offset + address-info.image_base-s.virtual_address for s in info.sections
            if s.virtual_address <= address-info.image_base < s.virtual_address+s.raw_size)
        assert raw[offset:offset+3].hex() == expected
        # RET is a fixture boundary, not an instruction claimed to exist after the original site.
        code = raw[offset:offset+3] + b'\xc3'
        section = SimpleNamespace(name='.text', virtual_address=0, raw_offset=0, raw_size=4, virtual_size=4, is_code=True)
        decoder = BoundedDisassembler(code, address, [section])
        f = decoder.disassemble_function(address, {})
        instructions = sorted({i.address:i for b in f.blocks.values() for i in b.instructions}.values(), key=lambda i:i.address)
        sources.append(lift_function_linear(CheckedLifter(lifted={address}), f'sub_{address:08X}', instructions,
            set(f.blocks), address, indirect_targets=f.jump_targets, eh_resume=None))
    generated = out / 'save-functions.c'
    generated.write_text('#define RECOMP_GENERATED_CODE\n#include "recomp_types.h"\n'+'\n'.join(sources))
    watched = [ROOT/'native/recomp_types.h', ROOT/'tools/lift_game.py', ROOT/'native/void_runtime.c']
    before = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}
    compiler, env, sdk = compiler_environment()
    exe = out / 'probe.exe'
    command = [str(compiler), '/nologo', '/O2', '/std:c11', '/W3', '/Inative',
        '/Ireference/pcrecomp/runtime/recomp32', f'/I{out}', 'tests/x87_save_gap_probe.c', str(generated),
        f'/Fo{out}\\', f'/Fe{exe}', '/link', '/MACHINE:X86', '/NXCOMPAT']
    compiled = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True)
    (out/'compile.log').write_text(compiled.stdout+compiled.stderr)
    assert compiled.returncode == 0, compiled.stdout+compiled.stderr
    tested = subprocess.run([str(exe)], cwd=ROOT, text=True, capture_output=True, timeout=20)
    unchanged = before == {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}
    receipt = dict(status='GAP_REPRODUCED' if tested.returncode == 0 and unchanged else 'FAILED',
        output=tested.stdout+tested.stderr, compiler=str(compiler), sdk=sdk, original_sha256=pin,
        source_hashes=before, source_hashes_unchanged=unchanged,
        generated_sha256=hashlib.sha256(generated.read_bytes()).hexdigest(),
        original_sites={'0x10259D8D':'dd7108','0x10259D99':'dd6108'},
        fixture_scope='two byte-pinned single-instruction leaves; synthetic RET boundary',
        whole_pow_or_game_executed=False, guest_pe_executed=False)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == pin
    (out/'result.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2)); assert receipt['status']=='GAP_REPRODUCED'


if __name__ == '__main__': main()
