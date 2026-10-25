"""Fill the device's D3DX shader cache: pull recorded compile requests, compile
them with Microsoft's d3dx9_36.dll on this PC (a standalone x86 tool, not the
game) and push the bytecode back.

    python tools/shader_service.py [--serial SERIAL]
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from toolchain import ADB

ROOT = Path(__file__).resolve().parents[1]
DEVICE_CACHE = os.environ.get("VOID_DEVICE_CACHE", "/sdcard/TheVoid/userdata/shadercache")
WORK = ROOT / "build/shadercache"


def adb(serial, *args, check=True):
    return subprocess.run([ADB, "-s", serial, *args], check=check, capture_output=True, text=True)


def build_tool():
    from lift_d3dx import SPEC
    config = json.loads((ROOT / "port.json").read_text())
    source_dll = ROOT / config["d3dx_compiler"]
    if hashlib.sha256(source_dll.read_bytes()).hexdigest() != SPEC["sha256"]:
        raise ValueError("d3dx9_36.dll hash mismatch")
    WORK.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_dll, WORK / "d3dx9_36.dll")
    sys.path.insert(0, str(ROOT / "tools"))
    import build_x86_incremental as b
    compiler, env, _ = b.compiler_environment()
    exe = WORK / "shader_compile_requests.exe"
    source = ROOT / "tools/shader_compile_requests.c"
    if not exe.exists() or exe.stat().st_mtime < source.stat().st_mtime:
        subprocess.run([str(compiler), "/nologo", "/O1", str(source), "/Fe" + str(exe), "/Fo" + str(WORK) + "\\"],
                       cwd=WORK, env=env, check=True)
    return exe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL") or os.environ.get("VOID_SERIAL"),
                        required=not (os.environ.get("ANDROID_SERIAL") or os.environ.get("VOID_SERIAL")))
    parser.add_argument("--watch", type=float, default=0, help="Keep serving for this many seconds")
    args = parser.parse_args()
    if args.watch:
        deadline = time.time() + args.watch
        while time.time() < deadline:
            serve(args)
            time.sleep(0.5)
        return
    serve(args)


def serve(args):
    requests = WORK / "requests"
    results = WORK / "results"
    requests.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    listing = adb(args.serial, "shell", f"ls {DEVICE_CACHE}/requests/ 2>/dev/null", check=False).stdout.split()
    names = [n for n in listing if n.endswith(".req")]
    if not names:
        if not args.watch:
            print("no pending requests on the device")
        return
    for name in names:
        adb(args.serial, "pull", f"{DEVICE_CACHE}/requests/{name}", str(requests / name))
    exe = build_tool()
    run = subprocess.run([str(exe), str(requests), str(results)], capture_output=True, text=True)
    print(run.stdout)
    if run.stderr:
        print(run.stderr, file=sys.stderr)
    pushed = 0
    for name in names:
        stem = name[:-4]
        # Bytecode, or the error Windows reports: the game must see either exactly.
        for suffix in (".bin", ".err"):
            result = results / (stem + suffix)
            if result.exists():
                # Push under a temporary name, then rename: the waiting game polls for the final name.
                adb(args.serial, "push", str(result), f"{DEVICE_CACHE}/{stem}.tmp")
                adb(args.serial, "shell", f"mv {DEVICE_CACHE}/{stem}.tmp {DEVICE_CACHE}/{stem}{suffix} && rm {DEVICE_CACHE}/requests/{name}")
                pushed += 1
                break
        (requests / name).unlink(missing_ok=True)
    print(f"pushed {pushed} results")


if __name__ == "__main__":
    main()
