"""Execute shipping hardware routing and shared refs on the requested Android device."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_game_apk import ADB, ANDROID_JAR, JAVA_HOME, TOOLS
from vhid import report


def run(*args):
    result = subprocess.run([str(x) for x in args], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout + result.stderr


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    args = parser.parse_args()
    out = ROOT / "build/hardware-input/unit"
    (out / "classes").mkdir(parents=True, exist_ok=True)
    sources = [ROOT / "tests/HardwareInputTest.java"] + [ROOT / "android/app/src/org/thevoid/port" / (name + ".java")
        for name in ("HardwareInput", "Input", "Keys")]
    run(JAVA_HOME / "bin/javac.exe", "--release", 8, "-cp", ANDROID_JAR, "-d", out / "classes", *sources)
    run(TOOLS / "d8.bat", "--lib", ANDROID_JAR, "--min-api", 26, "--output", out, *sorted((out / "classes").rglob("*.class")))
    remote = "/data/local/tmp/void-hardware-test.dex"
    run(ADB, "-s", args.serial, "push", out / "classes.dex", remote)
    hid = subprocess.Popen([sys.executable, "-u", str(ROOT / "tools/vhid.py"), "--serial", args.serial],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        ready = hid.stdout.readline()
        assert "HID ready:" in ready, ready + hid.stdout.read()
        result = run(ADB, "-s", args.serial, "shell", f"CLASSPATH={remote} app_process / org.thevoid.port.HardwareInputTest")
    finally:
        hid.stdin.close()
        try:
            hid.wait(timeout=8)
        except subprocess.TimeoutExpired:
            hid.terminate()
    (out / "result.txt").write_text(result, encoding="utf-8")
    assert "PASS HardwareInput:" in result, result
    assert report("key", [2, 26]) == [2, 0, 26, 0, 0, 0, 0, 0]
    assert report("mouse", [-1, 256, -1, 3]) == [3, 255, 255, 0, 1, 255]
    assert report("pad", []) == [0, 0, 128, 128, 128, 128, 0, 0, 8]
    for kind, values in (("key", [0] * 8), ("mouse", [32768, 0, 0, 0]), ("pad", [0] * 6 + [4096, 8]),
                         ("mouse", [1.5, 0, 0, 0]), ("key", "26")):
        try:
            report(kind, values)
        except ValueError:
            continue
        raise AssertionError("HID descriptor boundary accepted: " + kind)
    print(result.strip())


if __name__ == "__main__":
    main()
