"""A cold catch resume belongs to the owning generated frame, not just an alias."""
import json
from pathlib import Path
import re
import struct
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import lift_game
from tools.pe.pe_analyze import analyze_pe, build_iat_map


def instructions(function):
    return sorted({i.address: i for b in function.blocks.values()
                   for i in b.instructions}.values(), key=lambda i: i.address)


def emitted(decoder, function, imports, entries):
    return lift_game.lift_function_linear(lift_game.CheckedLifter(iat_map=imports, lifted=set(entries)),
        f"sub_{function.address:08X}", instructions(function), set(function.blocks),
        function.address, indirect_targets=function.jump_targets, eh_resume=function.eh_resume)


def main():
    base = 0x10000000
    raw = bytearray(b"\xCC" * 0x400)
    prologue = bytes.fromhex("558bec6aff68") + struct.pack("<I", base + 0x40)
    prologue += bytes.fromhex("64a100000000506489250000000031c05dc3")
    raw[:len(prologue)] = prologue
    raw[0x40:0x4A] = b"\xB8" + struct.pack("<I", base + 0x200) + b"\xE9" + struct.pack("<i", 0xF0 - 0x4A)
    raw[0x60:0x66] = b"\xB8" + struct.pack("<I", base + 0x80) + b"\xC3"
    # Unreachable adjacent catch-like code must not become an owner resume.
    raw[0x66:0x6C] = b"\xB8" + struct.pack("<I", base + 0xC0) + b"\xC3"
    raw[0x80:0x8B] = b"\xE8" + struct.pack("<i", 0xF0 - 0x85) + bytes.fromhex("b802000000c3")
    raw[0xC0] = raw[0xF0] = 0xC3
    raw[0x200:0x214] = struct.pack("<5I", 0x19930522, 1, base + 0x220, 1, base + 0x240)
    raw[0x240:0x254] = struct.pack("<5I", 0, 0, 1, 1, base + 0x260)
    raw[0x260:0x270] = struct.pack("<4I", 0, 0, 0, base + 0x60)
    sections = [SimpleNamespace(name=".text", virtual_address=0, raw_offset=0,
        raw_size=0x100, virtual_size=0x100, is_code=True), SimpleNamespace(name=".rdata",
        virtual_address=0x200, raw_offset=0x200, raw_size=0x200, virtual_size=0x200, is_code=False)]
    info = SimpleNamespace(image_base=base, entry_point_rva=0, sections=sections)
    with tempfile.TemporaryDirectory(prefix="void-eh-closure-") as tmp:
        path = Path(tmp) / "synthetic.bin"; path.write_bytes(raw)
        with patch.object(lift_game, "analyze_pe", return_value=info), patch.object(lift_game, "build_iat_map", return_value={}):
            _, _, decoder, functions, _ = lift_game.collect_functions(path, [{"address": base}], label="EH regression")
        owner = functions[base]
        assert owner.eh_resume == {base + 0x80}
        assert base + 0xF0 in functions and base + 0x80 in functions
        assert base + 0xC0 not in {i.address for i in instructions(owner)}
        body = emitted(decoder, owner, {}, functions)
        assert "RECOMP_EH_ENTER();" in body and "L_10000080:" in body
        assert "case 0x10000080u: goto L_10000080;" in body
        assert set(re.findall(r"RECOMP_CALL\((sub_[0-9A-F]+)\)", body)) <= {f"sub_{a:08X}" for a in functions}

    path = ROOT / "generated/input/Engine.dll"
    info = analyze_pe(str(path)); imports = build_iat_map(info)
    decoder = lift_game.BoundedDisassembler(path.read_bytes(), info.image_base, info.sections)
    owner = decoder.disassemble_function(0x11103FD0, imports)
    assert 0x11104054 not in {i.address for i in instructions(owner)}
    lift_game.complete_eh_owner(decoder, owner, imports)
    assert owner.eh_resume == {0x11104054} and owner.eh_added_instructions == 9
    body = emitted(decoder, owner, imports, {owner.address, *owner.calls_to})
    assert "RECOMP_EH_ENTER();" in body and "L_11104054:" in body
    assert "case 0x11104054u: goto L_11104054;" in body
    print("PASS: cold EH owner + alias, new callee closure, unreachable neighboring RET excluded; original Engine owner adds 9 instructions and landing")


if __name__ == "__main__":
    main()
