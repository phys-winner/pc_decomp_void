"""Use the project emitter and native SSE2 to test Renderer PMULUDQ semantics."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from lift_game import BoundedDisassembler, CheckedLifter
from test_memmove import compiler_environment


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output = ROOT / "build/renderer-pmuludq"
    output.mkdir(parents=True, exist_ok=True)
    watched = [ROOT / p for p in ("tools/lift_game.py", "tests/test_renderer_pmuludq.py",
        "tests/renderer_pmuludq_probe.c", "native/recomp_types.h",
        "reference/pcrecomp/runtime/recomp32/recomp_types.h")]
    before = {str(p.relative_to(ROOT)): sha(p) for p in watched}
    definitions, cases = [], []
    for destination in range(8):
        for source in range(9):
            memory = source == 8
            encoded = bytes.fromhex("660ff4") + bytes([destination * 8 + (3 if memory else 0xC0 + source)])
            section = SimpleNamespace(name=".text", virtual_address=0, raw_offset=0,
                raw_size=len(encoded), virtual_size=len(encoded), is_code=True)
            decoder = BoundedDisassembler(encoded, 0x16000000, [section])
            decoder._windows, decoder._start = 0, 0x16000000
            instruction = next(decoder.disassemble_at(0x16000000, len(encoded)))
            assert instruction.mnemonic == "pmuludq" and instruction.size == len(encoded)
            lines = CheckedLifter().lift_instruction(instruction)
            assert not any("void_lift_trap" in line or "UNIMPLEMENTED" in line for line in lines), lines
            name = f"lifted_{destination}_{source}"
            body = "\n".join(lines)
            definitions.append(f"static __declspec(noinline) void {name}(void) {{\n"
                "uint32_t ebx=g_ebx, _flag_k=g_flag_k, _flag_a=g_flag_a, _flag_b=g_flag_b, _cf=g_flag_cf;\n"
                + body + "\npreserved_flags[0]=_flag_k; preserved_flags[1]=_flag_a; "
                "preserved_flags[2]=_flag_b; preserved_flags[3]=_cf;\n}")
            cases.append(f"{{{destination}, {source if not memory else 0}, {int(memory)}, {name}}}")
    header = "#define _xmm g_xmm\n" + "\n\n".join(definitions)
    header += "\ntypedef struct { unsigned destination,source,memory; void (*lifted)(void); } pmul_case_t;\n"
    header += "static const pmul_case_t pmul_cases[]={\n" + ",\n".join(cases) + "\n};\n#undef _xmm\n"
    (output / "pmuludq-generated.h").write_text(header)
    compiler, env, sdk = compiler_environment()
    results = []
    for optimization in ("/O1", "/O2"):
        folder = output / optimization[1:]
        folder.mkdir(exist_ok=True)
        executable = folder / "probe.exe"
        command = [str(compiler), "/nologo", optimization, "/std:c11", "/W3", "/arch:SSE2",
            f"/I{ROOT / 'native'}", f"/I{output}", "tests/renderer_pmuludq_probe.c",
            f"/Fo{folder}\\", f"/Fe{executable}", "/link", "/MACHINE:X86", "/NXCOMPAT"]
        compiled = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
        (folder / "compile.log").write_text(compiled.stdout + compiled.stderr)
        if compiled.returncode:
            raise RuntimeError(compiled.stdout + compiled.stderr)
        tested = subprocess.run([str(executable)], cwd=ROOT, capture_output=True, text=True, timeout=30)
        result = {"optimization": optimization, "exit": tested.returncode, "output": tested.stdout + tested.stderr,
            "executable_sha256": sha(executable)}
        results.append(result)
        print(result["output"].strip(), flush=True)
    unchanged = before == {str(p.relative_to(ROOT)): sha(p) for p in watched}
    receipt = {"status": "PASS" if unchanged and all(r["exit"] == 0 for r in results) else "FAIL",
        "compiler": str(compiler), "sdk": sdk, "source_hashes": before, "source_hashes_unchanged": unchanged,
        "generated_header_sha256": sha(output / "pmuludq-generated.h"), "cases": 72,
        "comparisons_per_optimization": 599040, "game_or_original_pe_loaded": False,
        "invalid_alignment_exceptions_checked": False, "results": results}
    (output / "result.json").write_text(json.dumps(receipt, indent=2) + "\n")
    assert receipt["status"] == "PASS", receipt
    assert all(r["output"] == "PASS PMULUDQ cases=72 comparisons=599040\n" for r in results), receipt


if __name__ == "__main__":
    main()
