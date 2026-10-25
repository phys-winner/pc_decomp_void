"""Compile the host's actual serial Engine/Nx lifecycle with controlled DllMain outcomes."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
from test_memmove import compiler_environment

ROOT = Path(__file__).resolve().parents[1]


def extract(source, name):
    found = re.search(r"^static [^\n]+\b" + name + r"\([^\n]*\)\s*\{", source, re.M)
    assert found, name
    depth, end = 1, found.end()
    while depth:
        if source[end] == "{": depth += 1
        if source[end] == "}": depth -= 1
        end += 1
    return source[found.start():end]


def main():
    output = ROOT / "build/host-dependency"; output.mkdir(parents=True, exist_ok=True)
    host = ROOT / "native/windows_host.c"
    before = hashlib.sha256(host.read_bytes()).hexdigest(); source = host.read_text()
    types = re.search(r"enum \{ GM_UNMAPPED[^\n]+\};\s*typedef struct \{.*?\} manual_module;", source, re.S)
    assert types
    (output / "host-dependency-types.h").write_text(types.group())
    names = ("basename_a", "manual_named_a", "manual_release", "manual_detach_all", "manual_attach", "manual_load")
    (output / "host-dependency-functions.h").write_text("\n\n".join(extract(source, n) for n in names))
    compiler, env, sdk = compiler_environment()
    results = []
    for character in (False, True):
        path = output / ("with-nx" if character else "without-nx"); path.mkdir(exist_ok=True)
        exe = path / "probe.exe"
        built = subprocess.run([str(compiler), "/nologo", "/O2", "/std:c11", "/W4", "/WX",
            "/D_CRT_SECURE_NO_WARNINGS", *(["/DVOID_LIFT_NXCHARACTER"] if character else []),
            f"/I{output}", "tests/host_dependency_probe.c", f"/Fo{path}\\", f"/Fe{exe}",
            "/link", "/MACHINE:X86", "/NXCOMPAT"], cwd=ROOT, env=env, capture_output=True, text=True)
        (path / "compile.log").write_text(built.stdout + built.stderr)
        assert built.returncode == 0, built.stdout + built.stderr
        tested = subprocess.run([str(exe)], cwd=ROOT, capture_output=True, text=True, timeout=15)
        results.append({"NxCharacter": character, "exit": tested.returncode, "output": tested.stdout + tested.stderr})
        assert tested.returncode == 0, results[-1]
    assert before == hashlib.sha256(host.read_bytes()).hexdigest(), "Host changed during lifecycle probe"
    receipt = {"status": "PASS", "host_sha256": before, "compiler": str(compiler), "sdk": sdk,
        "actual_extracted_functions": names, "dll_events": "Controlled results, no original DLL/code loaded",
        "results": results}
    (output / "result.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__": main()
