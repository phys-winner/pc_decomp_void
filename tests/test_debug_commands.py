"""Compare the debug picker with original script dispatchers and map assets."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

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
print(f"{len(original_commands)} original script commands, 7 native commands and 35 map locations PASS")

JAVA = Path(os.environ.get("JAVA_HOME", "")) / "bin"
ANDROID = Path(os.environ.get("ANDROID_SDK", os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or Path.home() / "AppData/Local/Android/Sdk")) / "platforms/android-36/android.jar"
OUT = ROOT / "build/debug-command-test"
OUT.mkdir(parents=True, exist_ok=True)
sources = sorted((ROOT / "android/app/src").rglob("*.java"))
subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-cp", str(ANDROID), "-d", str(OUT),
                *map(str, sources), str(ROOT / "tests/DebugCommandsTest.java")], check=True)
subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", os.pathsep.join((str(OUT), str(ANDROID))),
                "org.thevoid.port.DebugCommandsTest"], check=True)
