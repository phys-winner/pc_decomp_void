"""Original pinned CRT initialization vs actual Win32 precision-errata query.

No game DLL is loaded; only two verified fixture pages are executable. This
measures original initialization, not live AOT post-attach flag values.
"""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from lift_game import BoundedDisassembler
from tools.pe.pe_analyze import analyze_pe, build_iat_map
from test_memmove import compiler_environment

SPEC = (
    ("RendererD3D", "a58ee315725502cd295600841accbd2a0df750443aefdd0dd4d9cc709604dbf3",
     0x1013712D, 0x101370F1, 0x1012AEAE, 0x10357CF8, 0x1027E0D4, 0x1027E0E0),
    ("GameModule", "a0075c2316bdb658724aaec595339a8ad2459832620b0a9dac3c7359a4330562",
     0x10138BA0, 0x10138B64, 0x1012C272, 0x102DB3A8, 0x10236188, 0x10236024),
    ("Sound", "855c2b0cd392b7d4faf82bc62bd9d3db211c5a7b34cd273db60617fc657de6f9",
     0x10056B0D, 0x10056AD1, 0x10055FCB, 0x100CCF5C, 0x100680F4, 0x100680F0),
)


def main():
    config = json.loads((ROOT / "port.json").read_text())
    original = Path(config["game_directory"]) / "bin/win32"
    out = ROOT / "build/fdiv-flags"; out.mkdir(parents=True, exist_ok=True)
    compiler, env, sdk = compiler_environment(); executable = out / "probe.exe"
    compiled = subprocess.run([str(compiler), "/nologo", "/O2", "/W4", "/WX", "/std:c11",
        "tests/fdiv_flag_probe.c", f"/Fo{out}\\", f"/Fe{executable}", "/link", "/MACHINE:X86", "/NXCOMPAT"],
        cwd=ROOT, env=env, capture_output=True, text=True)
    (out / "compile.log").write_text(compiled.stdout + compiled.stderr)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    records = []
    for name, pin, detector, fallback, initializer, flag, mod_iat, proc_iat in SPEC:
        path = original / (name + ".dll"); raw = path.read_bytes(); digest = hashlib.sha256(raw).hexdigest()
        if pin is not None: assert digest == pin
        info = analyze_pe(str(path)); assert info.image_base == 0x10000000
        decoder = BoundedDisassembler(raw, info.image_base, info.sections); imports = build_iat_map(info)
        assert imports[mod_iat] == ("KERNEL32.dll", "GetModuleHandleA")
        assert imports[proc_iat] == ("KERNEL32.dll", "GetProcAddress")
        pages = {detector & ~0xFFF, initializer & ~0xFFF}
        functions = {}
        for address in (detector, fallback, initializer):
            function = decoder.disassemble_function(address, imports)
            instructions = sorted({i.address: i for b in function.blocks.values() for i in b.instructions}.values(), key=lambda i: i.address)
            # All actual instructions of these entry CFGs fit the two RX pages.
            assert all((i.address & ~0xFFF) in pages for i in instructions)
            functions[hex(address)] = [{"address": hex(i.address), "bytes": i.bytes.hex(),
                "instruction": i.mnemonic + " " + i.op_str} for i in instructions]
        # The optional nonzero-argument FP-control call is never entered; our
        # initializer always receives zero. Pointer-table initialization stays
        # inside its initializer RX page and writes only this private image.
        size = struct.unpack_from("<I", raw, struct.unpack_from("<I", raw, 0x3C)[0] + 24 + 56)[0]
        image = bytearray(size)
        headers = min(s.raw_offset for s in info.sections if s.raw_size)
        image[:headers] = raw[:headers]
        for section in info.sections:
            image[section.virtual_address:section.virtual_address + section.raw_size] = raw[section.raw_offset:section.raw_offset + section.raw_size]
        assert any(info.image_base + s.virtual_address <= flag and
            flag + 4 <= info.image_base + s.virtual_address + s.virtual_size for s in info.sections)
        initial_flag = struct.unpack_from("<I", image, flag - info.image_base)[0]
        fixture = out / (name + ".fixture.bin"); fixture.write_bytes(image)
        command = [str(executable), str(fixture), hex(info.image_base), hex(size)] + [hex(x) for x in (detector, fallback, initializer, flag, mod_iat, proc_iat)]
        tested = subprocess.run(command, capture_output=True, text=True, timeout=10)
        assert tested.returncode == 0, (name, tested.returncode, tested.stdout, tested.stderr)
        record = json.loads(tested.stdout)
        assert record["original_detector"] == record["system_errata"]
        assert record["original_initialized_flag"] == record["original_detector"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        records.append({"module": name, "source_sha256": digest, "initial_flag": initial_flag,
            "original_flag_address": hex(flag), **record, "functions": functions})
        print(name, json.dumps({k: v for k, v in record.items()}))
    receipt = {"status": "PASS", "compiler": str(compiler), "sdk": sdk,
        "scope": "Original isolated CRT flag initialization + fallback; no DLL bootstrap or live AOT attach",
        "records": records}
    (out / "result.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__": main()
