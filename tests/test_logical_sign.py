"""Optimized MSVC must preserve narrow logical SF after real lifter capture.

Each predicate is a separate noinline function: combining them can hide the
installed compiler's faulty signed-cast optimization. No game or PE is loaded.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from lift_game import BoundedDisassembler, CheckedLifter
from types import SimpleNamespace
from test_memmove import compiler_environment

SETTERS = {
    8: {"test": "84d2", "and": "20d2", "or": "80ca00", "xor": "80f200"},
    16: {"test": "6685d2", "and": "6621d2", "or": "6683ca00", "xor": "6683f200"},
    32: {"test": "85d2", "and": "21d2", "or": "83ca00", "xor": "83f200"},
}
CONDITIONS = {"s": "negative", "ns": "!negative", "l": "negative",
              "ge": "!negative", "g": "(!negative && !zero)",
              "le": "(negative || zero)"}


def main():
    compiler, env, sdk = compiler_environment()
    out = ROOT / "build/logical-sign"
    out.mkdir(parents=True, exist_ok=True)
    bodies, checks = [], []
    for width, setters in SETTERS.items():
        for setter, hex_bytes in setters.items():
            raw = bytes.fromhex(hex_bytes)
            section = SimpleNamespace(name=".text", virtual_address=0, raw_offset=0,
                raw_size=len(raw), virtual_size=len(raw), is_code=True)
            decoder = BoundedDisassembler(raw, 0x10000000, [section])
            decoder._windows, decoder._start = 0, 0x10000000
            instruction = next(decoder.disassemble_at(0x10000000, len(raw)))
            for cc, expected in CONDITIONS.items():
                for form in ("j", "set", "cmov"):
                    lifter = CheckedLifter()
                    lines = lifter.lift_instruction(instruction)
                    condition = lifter._make_condition(form + cc)
                    name = f"check_{setter}_{width}_{form}{cc}"
                    bodies.append(f"__declspec(noinline) static int {name}(uint32_t v) {{\n"
                        "uint32_t g_edx=v, _flag_a=0, _flag_b=0, _flag_k=FK_NONE, _cf=0;\n"
                        + "\n".join(lines) + f"\nreturn !!({condition});\n}}")
                    value = "(v & 255u)" if width == 8 else "(v & 65535u)" if width == 16 else "v"
                    sign = {8: "0x80u", 16: "0x8000u", 32: "0x80000000u"}[width]
                    checks.append("{ uint32_t value=" + value + "; int negative=!!(value & "
                        + sign + "), zero=(value==0); comparisons++; if ("
                        + name + "(v) != !!(" + expected + ")) { "
                        "if (failures<8) fprintf(stderr,\"" + name
                        + " value=%08X failed\\n\",v); failures++; }}")
    source = '#include <stdint.h>\n#define RECOMP_GENERATED_CODE\n#include "recomp_types.h"\n'
    source += "\n".join(bodies)
    source += "\nstatic uint32_t comparisons,failures;\nstatic void run(uint32_t v) {\n" + "\n".join(checks) + "\n}\n"
    source += "int main(void) { for(uint32_t v=0;v<65536;v++)run(v); "
    source += "const uint32_t edges[]={0x7FFFFFFF,0x80000000,0x80000001,0xFFFFFF80,0xFFFF8000,0xFFFFFFFF}; "
    source += "for(unsigned i=0;i<6;i++)run(edges[i]); printf(\"comparisons=%u failures=%u\\n\",comparisons,failures); return failures?1:0;}\n"
    path, exe = out / "check.c", out / "check.exe"
    path.write_text(source)
    command = [str(compiler), "/nologo", "/O2", "/std:c11", "/I" + str(ROOT / "native"),
               str(path), "/Fo" + str(out) + "\\", "/Fe" + str(exe)]
    built = subprocess.run(command, env=env, cwd=out, capture_output=True, text=True)
    (out / "compile.txt").write_text(built.stdout + built.stderr)
    if built.returncode:
        raise RuntimeError(built.stdout + built.stderr)
    result = subprocess.run([str(exe)], text=True, capture_output=True, timeout=30)
    output = result.stdout + result.stderr
    count = (65536 + 6) * len(checks)
    receipt = {"status": "PASS" if result.returncode == 0 else "FAIL", "compiler": str(compiler),
               "sdk": sdk, "optimization": "/O2", "predicates": len(checks),
               "comparisons": count, "output": output, "game_run": False,
               "generated_probe_sha256": hashlib.sha256(source.encode()).hexdigest()}
    (out / "results.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(output.strip())
    assert result.returncode == 0 and output.startswith(f"comparisons={count} failures=0\n"), receipt


if __name__ == "__main__":
    main()
