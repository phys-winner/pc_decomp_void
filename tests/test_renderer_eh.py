"""Pin the Renderer biased EBP owner and exercise real EH dispatch without a game."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import lift_game
from tools.pe.pe_analyze import analyze_pe, build_iat_map
from tools.lift.eh32 import funcinfo, catch_funclets
from test_memmove import compiler_environment
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX,
    UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_ESP)

BASE = 0x21000000
ORIGINAL_SHA = "a58ee315725502cd295600841accbd2a0df750443aefdd0dd4d9cc709604dbf3"
OWNER, HANDLER, FI, RESUME = 0x16249970, 0x16270501, 0x16328E34, 0x16249B92


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def insns(function):
    return sorted({i.address: i for b in function.blocks.values()
                   for i in b.instructions}.values(), key=lambda i: i.address)


def original_frame_oracle(raw, info):
    # Execute only the actual prologue and cold epilogue. Allocation and
    # Direct3D are outside this narrow oracle; no guessed native ABI is used.
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(0, 0x1000); machine.mem_write(0, struct.pack("<I", 0xFFFFFFFF))
    machine.mem_map(info.image_base, 0x39C000)
    for section in info.sections:
        data = raw[section.raw_offset:section.raw_offset + section.raw_size]
        machine.mem_write(info.image_base + section.virtual_address, data)
    machine.mem_map(0x22000000, 0x10000); machine.mem_map(0x23000000, 0x1000)
    stack = 0x22008000
    machine.mem_write(stack, struct.pack("<10I", 0x23000000, *range(9)))
    registers = {UC_X86_REG_EBP: 0x71727374, UC_X86_REG_EBX: 0x41424344,
        UC_X86_REG_ESI: 0x51525354, UC_X86_REG_EDI: 0x61626364, UC_X86_REG_ESP: stack}
    for register, value in registers.items(): machine.reg_write(register, value)
    machine.emu_start(OWNER, 0x162499A5, count=40)
    frame, saved_stack = machine.reg_read(UC_X86_REG_EBP), machine.reg_read(UC_X86_REG_ESP)
    record = struct.unpack("<I", machine.mem_read(0, 4))[0]
    assert frame == stack - 4 - 0x38 and record == frame - 12
    assert struct.unpack("<I", machine.mem_read(frame - 0x10, 4))[0] == saved_stack
    machine.emu_start(RESUME, 0x23000000, count=30)
    assert machine.reg_read(UC_X86_REG_ESP) == stack + 40
    assert all(machine.reg_read(r) == registers[r] for r in
        (UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI))
    assert machine.reg_read(UC_X86_REG_EAX) == 0
    assert struct.unpack("<I", machine.mem_read(0, 4))[0] == 0xFFFFFFFF
    return {"status": "PASS", "oracle": "Unicorn original Renderer prologue and cold epilogue",
        "entry_esp": hex(stack), "frame_ebp": hex(frame), "seh_record": hex(record),
        "saved_esp": hex(saved_stack), "normalized_owner_esp": hex(frame + 4),
        "return_esp": hex(machine.reg_read(UC_X86_REG_ESP)), "return_eax": 0,
        "nonvolatiles_restored": True, "seh_restored": True}


def synthetic():
    raw = bytearray(b"\xCC" * 0x4000)
    def put(address, data):
        raw[address - BASE:address - BASE + len(data)] = data
    def words(address, *values):
        put(address, struct.pack("<" + "I" * len(values), *values))
    for index, bias in enumerate((0, 0x38)):
        owner, data = BASE + index * 0x400, BASE + 0x2000 + index * 0x400
        resume, catch = owner + 0x100, owner + 0x180
        frame = bytes.fromhex("558bec") if not bias else bytes.fromhex("558d6c24c883ec38")
        frame += bytes.fromhex("6aff68") + struct.pack("<I", data + 0x200)
        frame += bytes.fromhex("64a100000000506489250000000083ec245356578965f0")
        frame += bytes.fromhex("c745e0d4c3b2a1c745fc0000000068") + struct.pack("<I", data + 0x1E0)
        frame += bytes.fromhex("6a036a016863736de0b800000022ffd0cc")
        put(owner, frame)
        finish = bytes.fromhex("8b45e08b4df45f5e64890d000000005b")
        if bias: finish += bytes.fromhex("83c538")
        finish += bytes.fromhex("8be55dc3")
        put(resume, finish)
        put(catch, b"\xFF\x05" + struct.pack("<I", data + 0x300) +
            b"\xB8" + struct.pack("<I", resume) + b"\xC3")
        # Unreachable adjacent code is deliberately catch-return-shaped.
        put(catch + 12, b"\xB8" + struct.pack("<I", owner + 0x300) + b"\xC3")
        put(owner + 0x300, b"\xC3")
        words(data + 0x100, 0x19930522, 1, data + 0x140, 1, data + 0x160)
        words(data + 0x140, 0xFFFFFFFF, 0)
        words(data + 0x160, 0, 0, 1, 1, data + 0x180)
        words(data + 0x180, 0, 0, 0, catch)
        words(data + 0x1B0, 0, 0, 0, data + 0x1D0)
        words(data + 0x1D0, 0)
        words(data + 0x1E0, 0x19930520, data + 0x340, data + 0x1B0)
        put(data + 0x200, b"\xB8" + struct.pack("<I", data + 0x100) + b"\xE9\x00\x00\x00\x00")
        words(data + 0x300, 0)
    sections = [SimpleNamespace(name=".text", virtual_address=0, raw_offset=0,
        raw_size=0x1000, virtual_size=0x1000, is_code=True), SimpleNamespace(name=".rdata",
        virtual_address=0x2000, raw_offset=0x2000, raw_size=0x2000,
        virtual_size=0x2000, is_code=False)]
    return raw, SimpleNamespace(image_base=BASE, entry_point_rva=0, sections=sections)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-missing", action="store_true",
                        help="Record the original omission before the project fix")
    args = parser.parse_args()
    destination = ROOT / "build/renderer-eh" / ("before-fix" if args.expect_missing else "fixed")
    destination.mkdir(parents=True, exist_ok=True)
    watched = [ROOT / p for p in ("tools/lift_game.py", "native/recomp_types.h", "native/void_runtime.c",
        "reference/pcrecomp/tools/lift/eh32.py", "reference/pcrecomp/tools/lift/generate.py",
        "reference/pcrecomp/runtime/native32/eh32.c")]
    before = {str(p.relative_to(ROOT)): sha(p) for p in watched}
    config = json.loads((ROOT / "port.json").read_text())
    original = Path(config["game_directory"]) / "bin/win32/RendererD3D.dll"
    assert sha(original) == ORIGINAL_SHA
    image = ROOT / "generated/input/RendererD3D.dll"
    info = analyze_pe(str(image)); imports = build_iat_map(info)
    decoder = lift_game.BoundedDisassembler(image.read_bytes(), info.image_base, info.sections)
    original_frame = original_frame_oracle(image.read_bytes(), info)
    assert decoder.read_bytes(OWNER, 16).hex() == "558d6c24c883ec386aff680105271664"
    assert funcinfo(decoder.read_bytes, HANDLER) == FI
    catches = catch_funclets(decoder.read_bytes, FI)
    assert catches == [0x16249A03, 0x16249B3D]
    original_resumes = []
    for address in catches:
        function = decoder.disassemble_function(address, imports)
        instructions = insns(function); ends = {i.end_address: i for i in instructions}
        returns = {int(ends[i.address].op_str[5:], 16) for i in instructions
            if i.is_ret and i.address in ends and ends[i.address].mnemonic == "mov"
            and ends[i.address].op_str.startswith("eax, 0x")}
        assert returns == {RESUME}
        lift_game.complete_eh_owner(decoder, function, imports)
        assert not function.eh_resume, "Catch funclet must not register its own owner frame"
        original_resumes.append({"funclet": hex(address), "returns": [hex(a) for a in returns]})
    owner = decoder.disassemble_function(OWNER, imports)
    assert RESUME not in {i.address for i in insns(owner)}
    lift_game.complete_eh_owner(decoder, owner, imports)
    proof = {"owner": hex(OWNER), "handler": hex(HANDLER), "funcinfo": hex(FI),
        "resume": hex(RESUME), "original_sha256": ORIGINAL_SHA, "catch_funclets": original_resumes,
        "eh_resume": sorted(hex(a) for a in owner.eh_resume or ()),
        "frame_bias": getattr(owner, "eh_frame_bias", None),
        "added_instructions": owner.eh_added_instructions, "original_frame_oracle": original_frame}
    if args.expect_missing:
        assert not owner.eh_resume
        proof["status"] = "CONFIRMED_MISSING_BIASED_OWNER"
    else:
        assert owner.eh_resume == {RESUME}
        lift_game.emit_functions(destination / "original-owner", imports, decoder, {OWNER: owner},
            label="Renderer EH owner regression", additional_entries=owner.calls_to)
        body = (destination / "original-owner/recomp_0000.c").read_text()
        assert "RECOMP_EH_ENTER();" in body and f"case 0x{RESUME:08X}u: goto L_{RESUME:08X};" in body
        assert re.search(r"_ehf\.entry_esp\s*[-+]=\s*(?:0x0*38[uU]?|56)\s*;", body)
        assert set(re.findall(r"RECOMP_CALL\((sub_[0-9A-F]+)\)", body)) <= {
            f"sub_{a:08X}" for a in {OWNER, *owner.calls_to}}
        raw, synthetic_info = synthetic()
        input_path = destination / "synthetic.bin"; input_path.write_bytes(raw)
        # A catch-shaped function or a nonmatching LEA/SUB pair cannot claim
        # an EH frame merely because valid metadata occurs nearby.
        for kind, offset, value in (("unequal-stack-bias", 0x407, 0x34),
                                    ("positive-lea-displacement", 0x404, 0x38)):
            invalid = bytearray(raw); invalid[offset] = value
            bad_decoder = lift_game.BoundedDisassembler(bytes(invalid), BASE, synthetic_info.sections)
            bad_owner = bad_decoder.disassemble_function(BASE + 0x400, {})
            lift_game.complete_eh_owner(bad_decoder, bad_owner, {})
            assert not bad_owner.eh_resume, kind
        with patch.object(lift_game, "analyze_pe", return_value=synthetic_info), \
                patch.object(lift_game, "build_iat_map", return_value={}):
            _, synthetic_imports, synthetic_decoder, functions, _ = lift_game.collect_functions(
                input_path, [{"address": BASE}, {"address": BASE + 0x400}], label="Biased EH regression")
        for index in range(2):
            function = functions[BASE + index * 0x400]
            assert function.eh_resume == {BASE + index * 0x400 + 0x100}
            assert BASE + index * 0x400 + 0x300 not in {i.address for i in insns(function)}
        generated = destination / "generated"
        lift_game.emit_functions(generated, synthetic_imports, synthetic_decoder, functions,
            label="Biased EH regression", header_name="renderer_eh_funcs.h", chunk_prefix="probe")
        lift_game.emit_dispatch(generated / "recomp_dispatch.c", sorted(functions), ["renderer_eh_funcs.h"])
        compiler, env, sdk = compiler_environment()
        results = []
        for local in (False, True):
            out = destination / ("local" if local else "global"); out.mkdir(exist_ok=True)
            executable = out / "probe.exe"
            command = [str(compiler), "/nologo", "/O2", "/std:c11", "/W3", "/D_CRT_SECURE_NO_WARNINGS",
                *( ["/DRECOMP_LOCAL_REGS", "/DRECOMP_FLAT_MEMORY"] if local else []),
                "/Inative", "/Ireference/pcrecomp/runtime/recomp32", "/Ireference/pcrecomp/runtime/native32",
                f"/I{generated}", "tests/renderer_eh_probe.c", str(generated / "probe_0000.c"),
                str(generated / "recomp_dispatch.c"), "reference/pcrecomp/runtime/recomp32/image_loader.c",
                "reference/pcrecomp/runtime/recomp32/recomp_trace.c", f"/Fo{out}\\", f"/Fe{executable}",
                "/link", "/MACHINE:X86", "/NXCOMPAT"]
            built = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
            (out / "compile.log").write_text(built.stdout + built.stderr)
            assert built.returncode == 0, built.stdout + built.stderr
            tested = subprocess.run([str(executable), str(input_path)], cwd=ROOT,
                capture_output=True, text=True, timeout=20)
            results.append({"mode": "local+flat" if local else "global", "exit": tested.returncode,
                "output": tested.stdout + tested.stderr})
            assert tested.returncode == 0, results[-1]
        proof.update(status="PASS", compiler=str(compiler), sdk=sdk, results=results,
            rejected_prologues=["unequal-stack-bias", "positive-lea-displacement"])
    assert before == {str(p.relative_to(ROOT)): sha(p) for p in watched}, "Source changed during regression"
    proof["source_hashes"] = before
    (destination / "result.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(proof, indent=2))


if __name__ == "__main__":
    main()
