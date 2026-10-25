"""Read-only native x86 default-audio endpoint calibration; no windows or playback."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import time
from test_memmove import compiler_environment

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    started = datetime.now(timezone.utc).isoformat()
    elapsed_start = time.perf_counter()
    output = ROOT / "build/directsound-native"
    output.mkdir(parents=True, exist_ok=True)
    source = ROOT / "tests/directsound_native_probe.c"
    driver = Path(__file__).resolve()
    before = {str(path.relative_to(ROOT)): digest(path) for path in (source, driver)}
    compiler, env, sdk = compiler_environment()
    executable = output / "probe.exe"
    command = [str(compiler), "/nologo", "/O2", "/std:c11", "/W4", str(source),
               f"/Fo{output}\\", f"/Fe{executable}", "/link", "/MACHINE:X86", "/NXCOMPAT"]
    built = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, timeout=60)
    (output / "compile.log").write_bytes(built.stdout + built.stderr)
    if built.returncode:
        raise RuntimeError((built.stdout + built.stderr).decode("utf-8", errors="replace"))
    tested = subprocess.run([str(executable)], cwd=ROOT, capture_output=True, timeout=10,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    text = (tested.stdout + tested.stderr).decode("utf-8", errors="strict").replace("\r\n", "\n")
    (output / "output.txt").write_text(text, encoding="utf-8")
    module_paths = re.findall(r"^module name=(\S+) path=(.*?) final_path=(.*?)$", text, re.M)
    modules = []
    for name, displayed, resolved in module_paths:
        path = Path(resolved.removeprefix("\\\\?\\"))
        modules.append({"name": name, "module_path": displayed, "final_path": resolved,
                        "sha256": digest(path)})
    after = {str(path.relative_to(ROOT)): digest(path) for path in (source, driver)}
    receipt = {
        "status": "RECORDED" if tested.returncode == 0 and before == after else "FAILED",
        "started_utc": started, "elapsed_seconds": time.perf_counter() - elapsed_start,
        "scope": "native x86 default DirectSound object creation and device enumeration only",
        "compiler": str(compiler), "compiler_sha256": digest(compiler), "sdk": sdk,
        "compile_command": command, "source_sha256": before, "source_unchanged": before == after,
        "executable_sha256": digest(executable), "exit": tested.returncode,
        "output": text, "loaded_system_modules": modules,
        "windows_created": False, "sound_played": False, "devices_or_settings_changed": False,
        "game_or_project_runtime_executed": False, "cooperative_level_or_buffers_tested": False,
        "default_create8_hresult": re.search(r"^create8 .* hr=([0-9a-f]{8}) ", text, re.M)[1],
        "enumeration_hresult": re.search(r"^enumerate hr=([0-9a-f]{8}) ", text, re.M)[1],
        "enumeration_concrete_devices": int(re.search(r"concrete_devices=(\d+)", text)[1]),
        "waveout_device_count": int(re.search(r"^wave count=(\d+)$", text, re.M)[1]),
    }
    (output / "result.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(text, end="")
    assert receipt["status"] == "RECORDED", receipt
    assert len(modules) == 2, receipt
    assert "pointer_bits=32" in text, receipt
    assert "cleanup winmm_closed=1 dsound_closed=1" in text, receipt


if __name__ == "__main__":
    main()
