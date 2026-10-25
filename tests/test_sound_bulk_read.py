"""Check Sound's fread callback contract and one-byte versus bulk stream reads."""
import hashlib
import json
from pathlib import Path
import subprocess

from test_memmove import compiler_environment

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output = ROOT / "build/sound-bulk-read"
    output.mkdir(parents=True, exist_ok=True)
    compiler, env, sdk = compiler_environment()
    watched = [ROOT / path for path in (
        "tests/test_sound_bulk_read.py", "tests/sound_bulk_read_probe.c",
        "native/void_runtime.c", "native/recomp_types.h",
        "reference/pcrecomp/runtime/recomp32/recomp_types.h",
        "reference/pcrecomp/runtime/recomp32/image_loader.c",
        "reference/pcrecomp/runtime/recomp32/image_loader.h",
        "reference/pcrecomp/runtime/recomp32/recomp_trace.c",
        "reference/pcrecomp/runtime/recomp32/recomp_trace.h",
        "reference/pcrecomp/runtime/native32/native32.c",
        "reference/pcrecomp/runtime/native32/native32.h",
        "reference/pcrecomp/runtime/native32/eh32.c",
        "reference/pcrecomp/runtime/native32/x87crt.c")]
    before = {str(path.relative_to(ROOT)): sha(path) for path in watched}
    results = []
    for local, flat in ((False, False), (True, False), (False, True), (True, True)):
        mode = f"local{int(local)}-flat{int(flat)}"
        destination = output / mode
        destination.mkdir(exist_ok=True)
        defines = ["/DRECOMP_TRACE"]
        if local:
            defines.append("/DRECOMP_LOCAL_REGS")
        if flat:
            defines.append("/DRECOMP_FLAT_MEMORY")
        executable = destination / "probe.exe"
        command = [str(compiler), "/nologo", "/O2", "/std:c11", "/W3",
            "/D_CRT_SECURE_NO_WARNINGS", *defines, "/Inative",
            "/Ireference/pcrecomp/runtime/recomp32", "/Ireference/pcrecomp/runtime/native32",
            "tests/sound_bulk_read_probe.c", "reference/pcrecomp/runtime/recomp32/image_loader.c",
            "reference/pcrecomp/runtime/recomp32/recomp_trace.c", f"/Fo{destination}\\",
            f"/Fe{executable}", "/link", "/MACHINE:X86", "/NXCOMPAT"]
        built = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
        (destination / "compile.log").write_text(built.stdout + built.stderr)
        if built.returncode:
            raise RuntimeError(f"{mode} compile failed:\n{built.stdout}{built.stderr}")
        for control in (None, "stack", "count"):
            arguments = [] if control is None else [f"--negative-{control}"]
            tested = subprocess.run([str(executable), *arguments], cwd=ROOT,
                capture_output=True, text=True, timeout=30)
            label = "result" if control is None else f"negative-{control}"
            (destination / f"{label}.txt").write_text(tested.stdout + tested.stderr)
            results.append({"mode": mode, "defines": defines, "exit": tested.returncode,
                "negative_control": control, "output": tested.stdout + tested.stderr,
                "executable_sha256": sha(executable)})
            print(mode, label, tested.returncode, tested.stdout.strip(), flush=True)
    unchanged = before == {str(path.relative_to(ROOT)): sha(path) for path in watched}
    (output / "result.json").write_text(json.dumps({"compiler": str(compiler), "sdk": sdk,
        "source_hashes": before, "source_hashes_unchanged": unchanged,
        "no_original_pe_or_game_dll_load": True, "no_ui_or_system_changes": True,
        "legacy_is_a_one_byte_request_model_not_original_execution": True,
        "results": results}, indent=2))
    assert unchanged, "Runtime/probe changed during test"
    assert all(row["exit"] == 0 for row in results), "Sound bulk callback contract failed"
    assert all("PASS rejects invalid reader" in row["output"] for row in results
               if row["negative_control"]), "Reader trap negative control was not observed"


if __name__ == "__main__":
    main()
