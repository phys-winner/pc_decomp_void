"""Test extracted host profile functions using real read-only source settings."""
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import uuid

from test_memmove import compiler_environment

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(source, name):
    match = re.search(r"^static (?:HRESULT WINAPI|int) " + re.escape(name) + r"\([^\n]*\)\s*\{", source, re.M)
    assert match, name
    depth, end = 1, match.end()
    while depth:
        if source[end] == "{": depth += 1
        if source[end] == "}": depth -= 1
        end += 1
    return source[match.start():end]


def actual_common():
    shell = ctypes.WinDLL("shell32")
    shell.SHGetFolderPathW.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.HANDLE,
                                     wintypes.DWORD, wintypes.LPWSTR)
    shell.SHGetFolderPathW.restype = ctypes.c_long
    value = ctypes.create_unicode_buffer(260)
    result = shell.SHGetFolderPathW(None, 0x23, None, 0, value)
    assert result >= 0, f"Real CommonAppData query failed: {result & 0xFFFFFFFF:08X}"
    return Path(value.value) / "Ice-pick Lodge" / "Void"


def main():
    allowed = (ROOT / "build/test-profiles").resolve()
    output = allowed / ("profile-settings-" + str(uuid.uuid4()))
    output.mkdir(parents=True)
    output = output.resolve()
    assert output.is_relative_to(allowed) and output.parent == allowed
    profile = output / "profile"
    profile.mkdir()
    host = ROOT / "native/windows_host.c"
    before_host = sha(host)
    source_text = host.read_text()
    bodies = "\n\n".join(extract(source_text, name)
        for name in ("game_folder_path", "seed_profile_settings")) + "\n"
    (output / "host-profile.h").write_text(bodies)
    originals = [actual_common() / name for name in ("rcfg.xml", "scfg.xml", "settings.xml")]
    before = {str(path): sha(path) if path.is_file() else None for path in originals}
    compiler, env, sdk = compiler_environment()
    probe = ROOT / "tests/profile_settings_probe.c"
    executable = output / "probe.exe"
    built = subprocess.run([str(compiler), "/nologo", "/O2", "/W3", "/std:c11",
        "/D_CRT_SECURE_NO_WARNINGS", f"/I{output}", str(probe), f"/Fo{output}\\", f"/Fe{executable}",
        "/link", "/MACHINE:X86", "/NXCOMPAT", "shell32.lib"], cwd=ROOT, env=env, capture_output=True, text=True)
    (output / "compile.log").write_text(built.stdout + built.stderr)
    if built.returncode: raise RuntimeError(built.stdout + built.stderr)
    runs = []
    target_root = profile / "CommonAppData/Ice-pick Lodge/Void"
    for iteration in (1, 2):
        run = subprocess.run([str(executable), str(profile)], capture_output=True, text=True, timeout=20)
        runs.append({"iteration": iteration, "exit": run.returncode, "output": run.stdout + run.stderr})
        (output / f"run-{iteration}.txt").write_text(run.stdout + run.stderr)
        if run.returncode: raise RuntimeError(run.stdout + run.stderr)
        for index, original in enumerate(originals):
            target = (target_root / original.name).resolve()
            assert target.is_relative_to(profile.resolve()) and target.is_relative_to(allowed)
            if iteration == 1:
                if before[str(original)] is not None:
                    assert target.is_file() and sha(target) == before[str(original)], "Seed differs from original XML"
                else:
                    assert not target.exists(), "Missing original XML unexpectedly created a target"
                # This belongs exclusively to this test. Never change original attributes.
                if target.exists(): target.chmod(target.stat().st_mode | stat.S_IWRITE)
                target.write_bytes(f'<profile_probe preserve_existing="{index}"/>\n'.encode())
            else:
                assert target.read_bytes() == f'<profile_probe preserve_existing="{index}"/>\n'.encode(), "Seeding overwrote an edited target"
    after = {str(path): sha(path) if path.is_file() else None for path in originals}
    assert before == after, "Original common settings changed during test"
    assert before_host == sha(host), "Host changed during test"
    receipt = {"utc": datetime.now(timezone.utc).isoformat(), "status": "PASS", "compiler": str(compiler), "sdk": sdk,
        "host_sha256": before_host, "extracted_functions_sha256": hashlib.sha256(bodies.encode()).hexdigest(),
        "probe_sha256": sha(probe), "executable_sha256": sha(executable), "dedicated_test_root": str(output),
        "original_XML_before": before, "original_XML_after": after, "missing_original_allowed": True,
        "edited_target_preserved": True, "no_ui_registry_or_system_writes": True, "runs": runs}
    (output / "result.json").write_text(json.dumps(receipt, indent=2))
    print("".join(row["output"] for row in runs), end="")
    print(f"PASS original XML hashes/existence unchanged; own edits preserved; receipt={output / 'result.json'}")


if __name__ == "__main__": main()
