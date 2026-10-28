"""Check publication scope and portable build setup without original game data."""
import ast
import json
import os
from pathlib import Path
import re
import runpy
import struct
import subprocess
import sys
import tempfile
import types
from unittest.mock import patch
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import prepare_android
import generate_debug_levels
import patch_scripts


def main():
    files = subprocess.check_output(["git", "ls-files", "-c", "-o", "--exclude-standard", "-z"], cwd=ROOT).decode().split("\0")
    files = sorted(set(filter(None, files)))
    private_path = re.compile(r'''(?i)[a-z]:[\\/]+(?:Users[\\/]+([^\\/\s"'`]+)|(?:static_recompilation|Portable)[\\/])''')
    private_address = re.compile(r"\b(?:192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+):\d+\b")
    fixed_serial = re.compile(r'''add_argument\(["']--serial["']\s*,\s*default=["'][^"']+["']''')
    forbidden = {".exe", ".dll", ".so", ".apk", ".dex", ".class", ".zip", ".vfs", ".keystore", ".jks", ".pem", ".key", ".log"}
    for name in files:
        path = ROOT / name
        if path.is_dir():
            dependencies = json.loads((ROOT / "dependencies.json").read_text())
            dependency = next(d for d in dependencies.values() if d.get("directory") == name)
            assert dependency.get("submodule"), name
            entry = subprocess.check_output(["git", "ls-files", "--stage", "--", name], cwd=ROOT).decode().split()
            assert entry[:3] == ["160000", dependency["revision"], "0"], entry
            continue
        assert path.suffix.lower() not in forbidden, name
        assert not any(part in {"generated", "build", "original", "pub", "research", "__pycache__"} for part in path.relative_to(ROOT).parts), name
        text = path.read_text(encoding="utf-8")
        assert all((match[1] or "").lower() in {"player", "public"} for match in private_path.finditer(text)), f"personal host path: {name}"
        assert not private_address.search(text), f"private device endpoint: {name}"
        assert not fixed_serial.search(text), f"hardcoded device default: {name}"
        if path.suffix == ".py":
            ast.parse(text, filename=name)
    ignored = ["port.json", "STATE.md", "AGENTS.md", ".env", "original/game.exe", "generated/game.c",
               "build/android/debug.keystore", "pub/release.apk", "research/vfs-index.json",
               "reference/pcrecomp/.git/config", "android/app/private.keystore", "tools/__pycache__/local.pyc"]
    found = subprocess.check_output(["git", "check-ignore", "--no-index", "-z", "--stdin"], cwd=ROOT,
                                    input=("\0".join(ignored) + "\0").encode()).decode().split("\0")
    assert set(filter(None, found)) == set(ignored), (ignored, found)
    config = json.loads((ROOT / "port.example.json").read_text())
    assert "device" not in config
    for value in (config["game_directory"], config["physx_directory"], config["d3dx_compiler"],
                  *config["releases"]["tension"].values()):
        assert not Path(value).is_absolute() and ".." not in Path(value).parts, value
    manifest = ET.parse(ROOT / "android/app/AndroidManifest.xml").getroot()
    ns = "{http://schemas.android.com/apk/res/android}"
    minor = re.fullmatch(r"0\.(\d+)-dev", manifest.get(ns + "versionName"))
    assert minor and int(manifest.get(ns + "versionCode")) == int(minor[1]) + 1
    scene = "girl/test.xml"
    world = b"\x01A\0" + struct.pack("<I", 1) + b"\x011" + bytes([len(scene)]) + scene.encode("utf-16le")
    with patch.object(generate_debug_levels, "read_entry", return_value=world) as read:
        assert generate_debug_levels.catalog(names=False) == ([1], [scene], {})
        read.assert_called_once_with("research/vfs-index.json", "Properties\\World\\world.wmp")
    env = os.environ.copy()
    for name in ("ANDROID_SERIAL", "VOID_SERIAL", "JAVA_HOME"):
        env.pop(name, None)
    for args, message in ((["--install"], "--serial or VOID_SERIAL is required"), (["--java-only"], "set JAVA_HOME")):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/build_game_apk.py"), *args],
                                cwd=ROOT, env=env, capture_output=True, text=True)
        assert result.returncode == 2 and message in result.stderr, result.stderr
    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        overrides = temp / "build/overrides"
        overrides.mkdir(parents=True)
        (overrides / "stale.bin").write_bytes(b"old language patch")
        keep = temp / "keep.txt"
        keep.write_text("private input")
        with patch.object(patch_scripts, "ROOT", temp), patch.object(patch_scripts, "OUT", overrides), \
                patch.object(patch_scripts, "INDEXES", {}), patch("sys.stdout"):
            patch_scripts.main()
            assert {p.name for p in overrides.iterdir()} == {"index.json"}
            assert json.loads((overrides / "index.json").read_text()) == []
            with patch.object(patch_scripts, "OUT", temp / "outside-build"):
                try:
                    patch_scripts.main()
                except ValueError:
                    pass
                else:
                    raise AssertionError("override cleanup escaped the build directory")
            assert keep.read_text() == "private input" and not (temp / "outside-build").exists()
        settings = {"ANDROID_HOME": str(temp / "sdk"), "JAVA_HOME": str(temp / "jdk")}
        with patch.dict(os.environ, settings):
            for name in ("ANDROID_SDK", "ANDROID_SDK_ROOT", "ANDROID_NDK", "ADB"):
                os.environ.pop(name, None)
            tools = runpy.run_path(str(ROOT / "tools/toolchain.py"))
            assert tools["SDK"] == temp / "sdk" and tools["NDK"] == temp / "sdk/ndk/27.2.12479018"
            assert tools["JAVA_HOME"] == temp / "jdk"
            os.environ["ANDROID_SDK"] = str(temp / "priority-sdk")
            os.environ["ANDROID_NDK"] = str(temp / "custom-ndk")
            tools = runpy.run_path(str(ROOT / "tools/toolchain.py"))
            assert tools["SDK"] == temp / "priority-sdk" and tools["NDK"] == temp / "custom-ndk"
        (temp / "port.json").write_text(json.dumps(config))
        for name in ("Game.exe", "GameModule.dll", "Engine.dll", "FS.dll", "VFS.dll", "Sound.dll", "Video.dll", "RendererD3D.dll", "NxCharacter.dll"):
            path = temp / config["game_directory"] / "bin/win32" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        for name in ("PhysXCore.dll", "PhysXCooking.dll"):
            path = temp / config["physx_directory"] / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        (temp / config["d3dx_compiler"]).touch()
        with patch.object(prepare_android, "ROOT", temp), patch.object(prepare_android, "run") as run:
            with patch.object(sys, "argv", ["prepare_android.py"]):
                prepare_android.main()
            assert [call.args[0] for call in run.call_args_list] == [*prepare_android.LIFTERS, "build_vfs_index"]
            run.reset_mock()
            fake_release = types.ModuleType("lift_release")
            fake_release.load_release = lambda _: {"modules": [{"name": "Game", "path": temp / config["game_directory"] / "bin/win32/Game.exe"}]}
            with patch.dict(sys.modules, {"lift_release": fake_release}), patch.object(sys, "argv", ["prepare_android.py", "--tension"]):
                prepare_android.main()
            assert [call.args[0] for call in run.call_args_list][-2:] == ["lift_release", "build_vfs_index"]
            assert run.call_args.args[1:] == ("--game", temp / config["game_directory"], "--out", temp / "research/vfs-index.polish.json")
            (temp / config["game_directory"] / "bin/win32/Game.exe").unlink()
            run.reset_mock()
            with patch.object(sys, "argv", ["prepare_android.py"]), patch("sys.stderr"):
                try:
                    prepare_android.main()
                except SystemExit as error:
                    assert error.code == 2
                else:
                    raise AssertionError("missing original input accepted")
            run.assert_not_called()
    print(f"PASS: {len(files)} publication files; privacy, ignore rules, syntax, version, toolchains and both preparation routes")


if __name__ == "__main__":
    main()
