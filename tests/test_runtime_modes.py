"""Exercise emitted code and the real x86 native bridge in four build modes."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from lift_game import CheckedLifter, lift_function_linear
from tools.disasm.disasm32 import Instruction
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from test_memmove import compiler_environment

BASE, DATA = 0x21000000, 0x21008000


def u32(value):
    return struct.pack("<I", value)


def call(at, target):
    return b"\xE8" + struct.pack("<i", target - at - 5)


def source():
    # Synthetic original x86 instructions; the project lifter emits each body.
    leaf = bytes.fromhex("8b44240483c007b9") + u32(0x11121314)
    leaf += b"\xBA" + u32(0x21222324) + b"\xBB" + u32(0x41424344)
    leaf += b"\xBE" + u32(0x51525354) + b"\xBF" + u32(0x61626364)
    leaf += b"\xBD" + u32(0x71727374) + bytes.fromhex("c20400")
    stored = bytes.fromhex("83d000")
    for index, opcode in enumerate((0xA3, 0x0D, 0x15, 0x1D, 0x35, 0x3D, 0x2D)):
        stored += (bytes([opcode]) if index == 0 else bytes([0x89, opcode])) + u32(DATA + 0x20 + index * 4)
    stored += b"\xC3"
    direct = b"\x68" + u32(0xFFFFFFFC) + call(BASE + 5, BASE + 0x100) + stored
    indirect = b"\x68" + u32(0xFFFFFFFC) + b"\xB8" + u32(BASE + 0x100) + bytes.fromhex("ffd0") + stored
    tail = b"\xB8" + u32(BASE + 0x100) + bytes.fromhex("ffe0")
    native = b"\x68" + u32(0xAABBCCDD) + b"\x68" + u32(0x11223344)
    native += b"\x68" + u32(BASE + 0x500) + b"\xB9" + u32(0x31323334)
    native += b"\xA1" + u32(DATA + 4) + bytes.fromhex("ffd0c3")
    callback = bytes.fromhex("8b44240433442408bb") + u32(0xDEADBEEF)
    callback += b"\xBE" + u32(0xDEADBEEF) + b"\xBF" + u32(0xDEADBEEF)
    callback += b"\xBD" + u32(0xDEADBEEF) + bytes.fromhex("c20800")
    loop = b"\xB8" + u32(5) + b"\xB9" + u32(7) + bytes.fromhex("31d283c0014975fac3")
    owner = bytes.fromhex("558bec6aff68") + u32(DATA + 0x200)
    owner += bytes.fromhex("64a100000000506489250000000083ec248965f0c70424") + u32(0xA1B2C3D4)
    owner += bytes.fromhex("c745fc0000000068") + u32(DATA + 0x1E0)
    owner += bytes.fromhex("6a036a0168") + u32(0xE06D7363)
    owner += b"\xB8" + u32(0x22000000) + bytes.fromhex("ffd0cc")
    resume = bytes.fromhex("8b04248b4df464890d000000008be55dc3")
    # Put the cold continuation in the owner without decoding padding as code.
    blobs = {BASE: direct, BASE + 0x100: leaf, BASE + 0x200: indirect,
        BASE + 0x300: tail, BASE + 0x400: native, BASE + 0x500: callback,
        BASE + 0x600: loop, BASE + 0x700: owner,
        BASE + 0x800: b"\xB8" + u32(BASE + 0x780) + b"\xC3"}
    md = Cs(CS_ARCH_X86, CS_MODE_32); md.detail = True
    entries = set(blobs)
    header = '#include "recomp_types.h"\n' + "\n".join(f"void sub_{a:08X}(void);" for a in sorted(entries))
    bodies = ['#define RECOMP_GENERATED_CODE', '#include "runtime_modes_funcs.h"']
    for address, blob in sorted(blobs.items()):
        instructions = [Instruction(i.address, i.size, i.mnemonic, i.op_str, i.bytes, i.operands)
                        for i in md.disasm(blob, address)]
        if address == BASE + 0x700:
            instructions += [Instruction(i.address, i.size, i.mnemonic, i.op_str, i.bytes, i.operands)
                             for i in md.disasm(resume, BASE + 0x780)]
        assert sum(i.size for i in instructions) == len(blob) + (len(resume) if address == BASE + 0x700 else 0)
        leaders = {address} | {i.get_branch_target() for i in instructions if i.is_jump and i.get_branch_target() is not None}
        bodies.append(lift_function_linear(CheckedLifter(lifted=entries), f"sub_{address:08X}",
            instructions, leaders, address, indirect_targets=set(),
            eh_resume={BASE + 0x780} if address == BASE + 0x700 else None))
    bodies += ["const recomp_dispatch_entry_t recomp_dispatch_table[] = {",
               *[f"    {{0x{a:08X}u, sub_{a:08X}}}," for a in sorted(entries)],
               "};", f"const uint32_t recomp_dispatch_count = {len(entries)};"]
    return header + "\n", "\n\n".join(bodies) + "\n"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output = ROOT / "build/runtime-modes"
    output.mkdir(parents=True, exist_ok=True)
    header, generated = source()
    (output / "runtime_modes_funcs.h").write_text(header)
    (output / "runtime_modes_generated.c").write_text(generated)
    compiler, env, sdk = compiler_environment()
    watched = [ROOT / p for p in ("native/recomp_types.h", "native/void_runtime.c", "tools/lift_game.py",
        "reference/pcrecomp/runtime/recomp32/recomp_types.h", "reference/pcrecomp/runtime/native32/native32.c",
        "reference/pcrecomp/runtime/native32/eh32.c", "reference/pcrecomp/tools/lift/generate.py")]
    before = {str(p.relative_to(ROOT)): sha(p) for p in watched}
    results = []
    modes = [(False, False, None), (True, False, None), (False, True, None),
             (True, True, None), (True, True, "OUT"), (True, True, "IN")]
    for local, flat, omitted_transfer in modes:
        mode = f"local{int(local)}-flat{int(flat)}"
        if omitted_transfer: mode += f"-negative-{omitted_transfer.lower()}"
        destination = output / mode
        destination.mkdir(exist_ok=True)
        tested_source = output / "runtime_modes_generated.c"
        if omitted_transfer:
            tested_source = destination / "missing-transfer.c"
            tested_source.write_text(generated.replace('#include "runtime_modes_funcs.h"',
                '#include "runtime_modes_funcs.h"\n'
                f'#undef RECOMP_REGS_{omitted_transfer}\n'
                f'#define RECOMP_REGS_{omitted_transfer}() ((void)0)', 1))
        defines = ["/DRECOMP_TRACE", "/DRECOMP_YIELD_EVERY=1"]
        if local: defines += ["/DRECOMP_LOCAL_REGS"]
        if flat: defines += ["/DRECOMP_FLAT_MEMORY"]
        executable = destination / "probe.exe"
        command = [str(compiler), "/nologo", "/O2", "/std:c11", "/W3", "/D_CRT_SECURE_NO_WARNINGS",
            *defines, "/Inative", "/Ireference/pcrecomp/runtime/recomp32", "/Ireference/pcrecomp/runtime/native32",
            f"/I{output}", "tests/runtime_modes_probe.c", str(tested_source),
            "reference/pcrecomp/runtime/recomp32/image_loader.c", "reference/pcrecomp/runtime/recomp32/recomp_trace.c",
            f"/Fo{destination}\\", f"/Fe{executable}", "/link", "/MACHINE:X86", "/NXCOMPAT"]
        built = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
        (destination / "compile.log").write_text(built.stdout + built.stderr)
        if built.returncode: raise RuntimeError(f"{mode} compile failed:\n{built.stdout}{built.stderr}")
        tested = subprocess.run([str(executable)], cwd=ROOT, capture_output=True, text=True, timeout=20)
        (destination / "result.txt").write_text(tested.stdout + tested.stderr)
        expected_exit = 94 if omitted_transfer else 0
        results.append({"mode": mode, "defines": defines, "exit": tested.returncode,
                        "expected_exit": expected_exit, "negative_control": omitted_transfer,
                        "output": tested.stdout + tested.stderr})
        print(mode, tested.returncode, tested.stdout.strip(), flush=True)
    assert before == {str(p.relative_to(ROOT)): sha(p) for p in watched}, "Runtime/lifter changed during test"
    (output / "result.json").write_text(json.dumps({"compiler": str(compiler), "sdk": sdk,
        "no_guest_pe_or_game_dll_load": True, "source_hashes": before,
        "generated_sha256": sha(output / "runtime_modes_generated.c"), "results": results}, indent=2))
    assert all(r["exit"] == r["expected_exit"] for r in results), "Runtime mode or negative control failed"


if __name__ == "__main__":
    main()
