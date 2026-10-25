"""Characterize original Renderer x87 helpers, including registers and full FSAVE state."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import lift_game
from tools.pe.pe_analyze import analyze_pe, build_iat_map
from test_memmove import compiler_environment

PIN = "a58ee315725502cd295600841accbd2a0df750443aefdd0dd4d9cc709604dbf3"
REGISTERS = (0x76543210, 0x10203040, 0x50607080, 0x11223344, 0, 0x55667788, 0x99AABBCC, 0xDDEEFF00)


def ext(significand, exponent, negative=False):
    return struct.pack("<QH", significand, exponent | (0x8000 if negative else 0))


def from_double(value):
    bits = struct.unpack("<Q", struct.pack("<d", value))[0]
    sign, exponent, fraction = bits >> 63, (bits >> 52) & 0x7FF, bits & ((1 << 52) - 1)
    if exponent == 0x7FF: return ext((1 << 63) | (fraction << 11), 0x7FFF, bool(sign))
    if not exponent:
        if not fraction: return ext(0, 0, bool(sign))
        shift = fraction.bit_length() - 1
        return ext(fraction << (63 - shift), shift - 1074 + 16383, bool(sign))
    return ext((1 << 63) | (fraction << 11), exponent - 1023 + 16383, bool(sign))


def tag(value):
    significand, exponent = struct.unpack("<QH", value); exponent &= 0x7FFF
    if not significand and not exponent: return 1
    return 0 if 0 < exponent < 0x7FFF and significand >> 63 else 2


def state(values, cw, top=6, conditions=0, sticky=0):
    tags = 0xFFFF
    for i, value in enumerate(values):
        physical = (top + i) % 8
        tags = (tags & ~(3 << (2 * physical))) | (tag(value) << (2 * physical))
    env = struct.pack("<7I", cw, (top << 11) | conditions | sticky, tags, 0, 0, 0, 0)
    return env + b"".join(values) + b"\0" * (80 - 10 * len(values))


def main():
    out = ROOT / "build/renderer-math-oracle"; out.mkdir(parents=True, exist_ok=True)
    config = json.loads((ROOT / "port.json").read_text()); path = Path(config["game_directory"]) / "bin/win32/RendererD3D.dll"
    raw = path.read_bytes(); assert hashlib.sha256(raw).hexdigest() == PIN
    info = analyze_pe(str(path)); imports = build_iat_map(info)
    decoder = lift_game.BoundedDisassembler(raw, info.image_base, info.sections)
    entries = (0x10259FB4, 0x1025CB3C, 0x1025CDF4, 0x1025C936, 0x1025CBEE)
    functions = {}
    for address in entries:
        function = decoder.disassemble_function(address, imports)
        instructions = sorted({i.address: i for b in function.blocks.values() for i in b.instructions}.values(), key=lambda i: i.address)
        assert function.calls_to <= set(entries)
        assert all(not i.is_call or i.get_branch_target() in entries for i in instructions)
        assert all(0x10259000 <= i.address < 0x1025A000 or 0x1025C000 <= i.address < 0x1025D000 for i in instructions)
        functions[hex(address)] = {"instruction_count": len(instructions), "calls": sorted(hex(a) for a in function.calls_to),
            "instructions": [{"address": hex(i.address), "bytes": i.bytes.hex(), "text": i.mnemonic + " " + i.op_str} for i in instructions]}
    mapped = bytearray(0x39C000); mapped[:info.sections[0].raw_offset] = raw[:info.sections[0].raw_offset]
    for section in info.sections:
        mapped[section.virtual_address:section.virtual_address + section.raw_size] = raw[section.raw_offset:section.raw_offset + section.raw_size]
    image = out / "Renderer.fixture.bin"; image.write_bytes(mapped)
    vectors = [("seven-two", from_double(7), from_double(2)), ("negative-seven", from_double(-7), from_double(2)),
        ("seven-four", from_double(7), from_double(4)), ("zero", from_double(0), from_double(1)),
        ("signed-zero", from_double(-0.0), from_double(2)), ("large-gap", ext(1 << 63, 16383 + 2000), from_double(3)),
        ("true-extended-denormal", ext(1, 0), from_double(2)), ("denormal-divisor", from_double(1), ext(1, 0)),
        ("infinity", ext(1 << 63, 0x7FFF), from_double(1)), ("zero-divisor", from_double(7), from_double(0)),
        ("quiet-nan", ext(0xC000000000001234, 0x7FFF), from_double(2)),
        ("signaling-nan", ext(0x8000000000001234, 0x7FFF), from_double(2))]
    baseline = out / "baseline-360.json"
    if (out / "result.json").exists() and not baseline.exists():
        baseline.write_bytes((out / "result.json").read_bytes())
    cases, payload = [], bytearray()
    def add_case(entry, label, dividend, divisor, cw, flag=0, top=6, lower=(), conditions=0, sticky=0, edx=None):
        values = ([divisor, dividend] if entry == 0x10259FB4 else [dividend, divisor]) + list(lower)
        arguments = bytearray(b"\xA5" * 64)
        if entry in (0x1025C936, 0x1025CBEE):
            values = list(lower)
            arguments[:10] = divisor; arguments[12:22] = divisor; arguments[24:34] = dividend
        fpu = state(values, cw, top, conditions, sticky)
        registers = list(REGISTERS)
        if edx is not None: registers[2] = edx
        payload.extend(struct.pack("<11I", entry, flag, *registers, 0x202) + fpu + arguments)
        cases.append({"entry": hex(entry), "label": label, "input_cw": hex(cw), "fdiv_flag": flag,
            "dividend": dividend.hex(), "divisor": divisor.hex(), "initial_top": top,
            "initial_conditions": hex(conditions), "initial_sticky": hex(sticky), "input_gprs": registers,
            "lower_values": [value.hex() for value in lower]})
    for entry in entries:
        for label, dividend, divisor in vectors:
            for cw in (0x37F, 0x27F, 0x7F, 0xB7F, 0x37E):
                for flag in ((0, 1) if entry == 0x10259FB4 else (0,)):
                    add_case(entry, label, dividend, divisor, cw, flag)
    # All architecturally defined precision/rounding settings, preserving sticky flags.
    for entry in entries:
        for label, dividend, divisor in vectors:
            for precision in (0, 0x200, 0x300):
                for rounding in (0, 0x400, 0x800, 0xC00):
                    add_case(entry, label + "-pc-rc", dividend, divisor, 0x7F | precision | rounding, sticky=0x20)
    extra = (from_double(123.75), from_double(-11.5), from_double(0))
    for entry in entries:
        for label, dividend, divisor in vectors[:3]:
            for top in (0, 3, 6, 7):
                for lower in ((), extra[:1], extra):
                    for conditions in (0, 0x100, 0x200, 0x400, 0x4000, 0x4300):
                        add_case(entry, label + "-top-tags-cc", dividend, divisor, 0x37F,
                            top=top, lower=lower, conditions=conditions)
    # The leaf's EDX bits select scaling/status restoration paths. They are
    # ABI input flags, not the public FPREM argument order.
    for entry in (0x1025C936, 0x1025CBEE):
        for label, dividend, divisor in vectors:
            for edx in range(4):
                for top in (0, 3, 6, 7):
                    for conditions in (0, 0x100, 0x200, 0x4000, 0x4300):
                        add_case(entry, label + "-leaf-flags", dividend, divisor, 0x37F,
                            top=top, lower=extra[:1], conditions=conditions, edx=edx)
    inputs = out / "cases.bin"; inputs.write_bytes(payload)
    compiler, env, sdk = compiler_environment(); executable = out / "probe.exe"
    compiled = subprocess.run([str(compiler), "/nologo", "/O2", "/W3", "/std:c11", "tests/renderer_math_oracle_probe.c",
        f"/Fo{out}\\", f"/Fe{executable}", "/link", "/MACHINE:X86", "/NXCOMPAT"], cwd=ROOT, env=env, capture_output=True, text=True)
    (out / "compile.log").write_text(compiled.stdout + compiled.stderr)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    outputs = out / "outputs.bin"
    tested = subprocess.run([str(executable), str(image), str(inputs), str(outputs)], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert tested.returncode == 0, tested.stdout + tested.stderr
    result_bytes = outputs.read_bytes(); assert len(result_bytes) == len(cases) * 444
    records = []
    for index, case in enumerate(cases):
        offset = index * 444; integers = struct.unpack_from("<13I", result_bytes, offset)
        exception, pc, stack, return_pc = integers[:4]; regs, flags = integers[4:12], integers[12]
        before = result_bytes[offset + 52:offset + 80]; fpu = result_bytes[offset + 80:offset + 188]
        cw, sw, tags = struct.unpack_from("<3I", fpu)
        if not exception:
            assert regs[4] == stack + 4
            preserved = (0, 1, 2, 3, 5, 6, 7) if case['entry'] in ('0x1025c936', '0x1025cbee') else (1, 2, 3, 5, 6, 7)
            assert all(regs[i] == case['input_gprs'][i] for i in preserved), (case, regs)
            result_count = 1 if case['entry'] == '0x10259fb4' else 2
            for i, lower in enumerate(case['lower_values']):
                assert fpu[28 + (result_count + i) * 10:38 + (result_count + i) * 10].hex() == lower, (case, fpu.hex())
        records.append({**case, "exception_code": hex(exception), "exception_pc": hex(pc), "entry_esp": hex(stack),
            "return_pc": hex(return_pc), "gprs": [hex(v) for v in regs], "eflags": hex(flags),
            "before_environment": before.hex(), "cw": hex(cw & 0xFFFF), "sw": hex(sw & 0xFFFF),
            "top": (sw >> 11) & 7, "tag_word": hex(tags & 0xFFFF),
            "registers80": [fpu[28 + i * 10:38 + i * 10].hex() for i in range(8)],
            "full_fsave": fpu.hex(), "memory": result_bytes[offset + 188:offset + 444].hex()})
    receipt = {"status": "PASS", "original_sha256": PIN, "compiler": str(compiler), "sdk": sdk,
        "case_count": len(cases), "output": tested.stdout + tested.stderr, "whole_game_equivalence": "NOT_TESTED",
        "project_lifter_or_runtime_executed": False, "fixture_only_two_rx_pages": ["0x10259000", "0x1025c000"],
        "scratch_capture": "Returned cases only: return slot overwritten by instrumentation PUSHFD; fault stacks may be overwritten by Windows exception dispatch",
        "functions": functions, "records": records}
    assert hashlib.sha256(path.read_bytes()).hexdigest() == PIN
    (out / "result.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k: v for k, v in receipt.items() if k not in ("functions", "records")}, indent=2))
    print("first", json.dumps(records[0], indent=2))


if __name__ == "__main__": main()
