"""Compare the debug picker with original script dispatchers and map assets."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from generate_debug_levels import OUT as LEVELS_FILE, source
from gscript_binary import Module
from patch_scripts import method_rows, read_entry

assert LEVELS_FILE.with_name("DebugLevelsTension.java").read_text(encoding="utf-8") == source("research/vfs-index.polish.json", "DebugLevelsTension")
assert LEVELS_FILE.read_text(encoding="utf-8") == source(), "debug level catalog needs regeneration"
original_commands = set()
for script in ("Scripts\\world\\world.bin", "Scripts\\game.bin"):
    rows = method_rows(Module(read_entry("research/vfs-index.json", script)), "onConsoleCommand")
    original_commands.update(rows[i]["text"] for i in range(len(rows) - 1)
                             if rows[i].get("text") and rows[i + 1].get("opcode") == 46)
java = (ROOT / "android/app/src/org/thevoid/port/DebugCommands.java").read_text(encoding="utf-8")
array = java.split("COMMANDS = {", 1)[1].split("};", 1)[0]
commands = [json.loads('"' + text + '"').split()[0].lstrip("/") for text in re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', array)]
assert len(commands) == len(set(commands)), "duplicate commands"
assert set(commands) == original_commands | {"setvar", "getvar", "setting", "save_settings", "broadcast", "string", "gamma"}
for index in ("research/vfs-index.json", "research/vfs-index.polish.json"):
    rows = method_rows(Module(read_entry(index, "Scripts\\world\\world.bin"), legacy="polish" in index), "onConsoleCommand")
    body = ET.fromstring(read_entry(index, "Properties\\World\\body.xml"))
    assert {row.get("Name") for row in body if row.get("Name", "").startswith("Zone")} == {f"Zone{i}" for i in range(21)}
    assert any(row.get("text") == "Usage: /open_zone [zone]  (opens random zone if zone is undefined)" for row in rows)
    assert any(row.get("text") == "Error: chapter must be a number [0-6]" for row in rows)
    start = next(i for i, row in enumerate(rows) if row.get("text") == "surface_exit")
    end = rows[start + 2]["operands"][0]
    surface = [row for row in rows[start:] if row["offset"] < end]
    assert {row["operands"][0] for row in surface if row["opcode"] == 1 and row["register"] == 3} == {0, 1, 2, 255}
print(f"{len(original_commands)} original script commands, 7 native commands and 26 selectable map locations PASS")

JAVA = Path(os.environ.get("JAVA_HOME", "")) / "bin"
ANDROID = Path(os.environ.get("ANDROID_SDK", os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or Path.home() / "AppData/Local/Android/Sdk")) / "platforms/android-36/android.jar"
OUT = ROOT / "build/debug-command-test"
OUT.mkdir(parents=True, exist_ok=True)
from build_game_apk import prepare_launcher, ANDROID_JAR
ANDROID = ANDROID_JAR
prepared = prepare_launcher(OUT / "launcher")
sources = sorted((ROOT / "android/app/src").rglob("*.java")) + [Path(p) for p in prepared["sources"]]
subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-cp", str(ANDROID), "-d", str(OUT),
                *map(str, sources), str(ROOT / "tests/DebugCommandsTest.java")], check=True)
subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", os.pathsep.join((str(OUT), str(ANDROID))),
                "org.thevoid.port.DebugCommandsTest"], check=True)
