"""Record native x86 DirectInput creation HRESULTs without reading input."""
import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import uuid

import pefile
from test_memmove import compiler_environment

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def guid_evidence():
    results = []
    for relative, base in (("research/ida/Engine.dll", 0x10000000),
                           ("generated/input/Engine.dll", 0x11000000)):
        path = ROOT / relative
        raw = path.read_bytes()
        pe = pefile.PE(data=raw, fast_load=True)
        values = {}
        for name, rva in (("SysKeyboard", 0x11898C), ("SysMouse", 0x11899C),
                          ("IID_IDirectInput8A", 0x1189EC)):
            offset = pe.get_offset_from_rva(rva)
            data = raw[offset:offset + 16]
            values[name] = {"address": f"0x{base + rva:08X}", "bytes": data.hex(),
                            "guid": str(uuid.UUID(bytes_le=data))}
        results.append({"file": relative, "sha256": sha(path), "guids": values})
    for name in results[0]["guids"]:
        assert results[0]["guids"][name]["bytes"] == results[1]["guids"][name]["bytes"]
    return results


def main():
    output = ROOT / "build/directinput-native"
    output.mkdir(parents=True, exist_ok=True)
    compiler, env, sdk = compiler_environment()
    executable = output / "directinput-native.exe"
    source = ROOT / "tests/directinput_native_probe.c"
    inputs = guid_evidence()
    command = [str(compiler), "/nologo", "/O2", "/W3", "/std:c11",
        str(source), f"/Fo{output}\\", f"/Fe{executable}", "/link",
        "dinput8.lib", "dxguid.lib", "/MACHINE:X86", "/NXCOMPAT"]
    built = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    (output / "compile.log").write_text(built.stdout + built.stderr)
    if built.returncode: raise RuntimeError(built.stdout + built.stderr)
    tested = subprocess.run([str(executable)], cwd=ROOT, capture_output=True, text=True, timeout=20)
    text = tested.stdout + tested.stderr
    (output / "result.txt").write_text(text)
    calls = [{"interface": m[1], "operation": m[2], "hresult": f"0x{m[3]}",
              "pointer": f"0x{m[4]}"} for m in re.finditer(
                  r"result=(A|W) (\w+) ([0-9A-F]{8}) ([0-9A-F]{8})", text)]
    metadata = dict(line.split("=", 1) for line in text.splitlines()
                    if "=" in line and not line.startswith("result="))
    modules = []
    for key, value in metadata.items():
        if key.startswith("module_") and value != "<not loaded>":
            name = key[7:]
            resolved = metadata.get(f"resolved_{name}")
            if resolved is None: raise RuntimeError("Cannot identify physical loaded-module file")
            path = Path(resolved)
            loaded_machine = metadata[f"machine_{name}"]
            disk_machine = f"{pefile.PE(str(path), fast_load=True).FILE_HEADER.Machine:04X}"
            assert loaded_machine == disk_machine == "014C", "Loaded/disk module architecture differs"
            modules.append({"name": name, "reported_path": value, "resolved_path": resolved,
                            "loaded_machine": loaded_machine, "sha256": sha(path)})
    assert inputs == guid_evidence(), "Engine input changed during native probe"
    receipt = {"utc": datetime.now(timezone.utc).isoformat(),
        "compiler": str(compiler), "sdk": sdk, "probe_exit_code": tested.returncode,
        "source_sha256": sha(source), "executable_sha256": sha(executable),
        "engine_guid_evidence": inputs, "metadata": metadata, "modules": modules, "calls": calls,
        "no_device_acquisition_or_input_read_or_ui": True, "no_game_dll_or_guest_runtime": True,
        "output": text}
    (output / "result.json").write_text(json.dumps(receipt, indent=2))
    print(text, end="")
    # A native device failure remains a failure, while its diagnostic receipt is retained.
    raise SystemExit(tested.returncode)


if __name__ == "__main__":
    main()
