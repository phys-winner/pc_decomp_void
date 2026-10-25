"""Compile a standalone private-runtime catch-routing probe; never run the game."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_memmove import compiler_environment


def main():
    compiler, env, sdk = compiler_environment()
    out = ROOT / "build/engine-eh-probe"
    out.mkdir(parents=True, exist_ok=True)
    exe = out / "engine-eh-probe.exe"
    command = [str(compiler), "/nologo", "/O2", "/std:c11", "/D_CRT_SECURE_NO_WARNINGS",
               "/I" + str(ROOT / "native"), "/I" + str(ROOT / "reference/pcrecomp/runtime/native32"),
               "/I" + str(ROOT / "reference/pcrecomp/runtime/recomp32")]
    command += [str(ROOT / p) for p in ["tests/engine_raise_probe.c", "native/void_runtime.c",
        "reference/pcrecomp/runtime/recomp32/image_loader.c", "reference/pcrecomp/runtime/recomp32/recomp_trace.c"]]
    command += ["/Fo" + str(out) + "\\", "/Fe" + str(exe), "/link", "/MACHINE:X86", "/NXCOMPAT"]
    built = subprocess.run(command, env=env, cwd=out, text=True, capture_output=True)
    (out / "compile.txt").write_text(built.stdout + built.stderr)
    if built.returncode:
        raise RuntimeError(built.stdout + built.stderr)
    results = []
    for mode, code, text in [(None, 0, "PASS thread-name fallback"),
        ("uncaught", 7, "Uncaught guest MSVC C++ exception"),
        ("malformed", 7, "Unsupported MSVC C++ RaiseException record"),
        ("invalid-params", 7, "Unsupported MSVC C++ RaiseException record"),
        ("invalid-info", 7, "Missing MSVC C++ throw metadata"),
        ("magic", 7, "Unsupported MSVC C++ exception format")]:
        run = subprocess.run([str(exe)] + ([mode] if mode else []), text=True,
                             capture_output=True, timeout=10)
        output = run.stdout + run.stderr
        assert run.returncode == code and text in output, (mode, run.returncode, output)
        results.append({"mode": mode or "three valid magics and fallback", "exit_code": run.returncode, "output": output})
        print(output.strip())
    (out / "results.json").write_text(json.dumps({"status": "PASS", "sdk": sdk,
        "compiler": str(compiler), "game_run": False, "results": results}, indent=2) + "\n")
    print("PASS: real guest catch/unwind/longjmp; uncaught and unsupported records remain fatal")


if __name__ == "__main__":
    main()
