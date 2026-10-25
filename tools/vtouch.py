"""Multi-touch gestures on a device for testing the touch layer.

    python tools/vtouch.py build [--serial S]          compile and push the injector
    python tools/vtouch.py run [--serial S] GESTURE...  play gestures in order
Gestures (screen pixels of the rotated display, durations in ms):
    tap:X,Y                 touch and lift
    hold:X,Y,MS             touch, wait, lift
    swipe:X1,Y1,X2,Y2,MS    one finger
    pinch:CX,CY,D1,D2,MS    two fingers apart from distance D1 to D2 (horizontal)
    scroll:CX,CY,DY,MS      two fingers moving together vertically by DY
    stick+look:SX,SY,DY,LX,LY,DX,MS
                            finger 0 holds the stick pushed by DY while
                            finger 1 swipes DX on the right
    stick+tap:SX,SY,DY,TX,TY,MS
                            finger 0 holds the stick pushed by DY for MS
                            while finger 1 taps (TX, TY) after 200 ms
    path:MS,X1,Y1,X2,Y2,... one finger along a polyline in MS (a glyph)
    stick:SX,SY,DX,DY,MS    push the stick from (SX, SY) by (DX, DY), hold MS
    wait:MS
    seq:LINE;LINE;...       the injector's own lines (d SLOT X Y, m SLOT X Y,
                            u SLOT, s MS; "g SLOT X Y MS" glides finger SLOT
                            to (X, Y) in MS): several fingers held, moved and
                            lifted in any order
The injector (tools/vtouch/VTouch.java) runs through app_process as the shell
user, which may inject input like the `input` command, and sends MotionEvents
with several pointers (adb's `input` has one)."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from toolchain import ADB, SDK, JAVA_HOME

ROOT = Path(__file__).resolve().parents[1]
REMOTE = "/data/local/tmp/void/vtouch.dex"
STEP = 16   # ms between moves


def lerp(a, b, t):
    return round(a + (b - a) * t)


def gesture(g):
    kind, _, args = g.partition(":")
    if kind == "seq":
        out, at = [], {}
        for line in args.split(";"):
            f = line.split()
            if not f:
                continue
            if f[0] in ("d", "m"):
                at[f[1]] = (int(float(f[2])), int(float(f[3])))
            if f[0] == "g":
                (x1, y1), x2, y2, ms = at[f[1]], int(float(f[2])), int(float(f[3])), int(f[4])
                n = max(1, ms // STEP)
                for i in range(1, n + 1):
                    out += [f"s {STEP}", f"m {f[1]} {lerp(x1, x2, i / n)} {lerp(y1, y2, i / n)}"]
                at[f[1]] = (x2, y2)
            else:
                out.append(" ".join(f))
        return out
    v = [int(float(x)) for x in args.split(",")] if args else []
    out = []
    if kind == "tap":
        out += [f"d 0 {v[0]} {v[1]}", "s 60", "u 0"]
    elif kind == "hold":
        out += [f"d 0 {v[0]} {v[1]}", f"s {v[2]}", "u 0"]
    elif kind == "swipe":
        x1, y1, x2, y2, ms = v
        n = max(1, ms // STEP)
        out.append(f"d 0 {x1} {y1}")
        for i in range(1, n + 1):
            out += [f"s {STEP}", f"m 0 {lerp(x1, x2, i / n)} {lerp(y1, y2, i / n)}"]
        out.append("u 0")
    elif kind == "pinch":
        cx, cy, d1, d2, ms = v
        n = max(1, ms // STEP)
        out += [f"d 0 {cx - d1 // 2} {cy}", "s 30", f"d 1 {cx + d1 // 2} {cy}"]
        for i in range(1, n + 1):
            d = lerp(d1, d2, i / n)
            out += [f"s {STEP}", f"m 0 {cx - d // 2} {cy}", f"m 1 {cx + d // 2} {cy}"]
        out += ["u 1", "s 20", "u 0"]
    elif kind == "scroll":
        cx, cy, dy, ms = v
        n = max(1, ms // STEP)
        out += [f"d 0 {cx - 120} {cy}", "s 30", f"d 1 {cx + 120} {cy}"]
        for i in range(1, n + 1):
            y = lerp(cy, cy + dy, i / n)
            out += [f"s {STEP}", f"m 0 {cx - 120} {y}", f"m 1 {cx + 120} {y}"]
        out += ["u 1", "s 20", "u 0"]
    elif kind == "stick+look":
        sx, sy, sdy, lx, ly, ldx, ms = v
        n = max(1, ms // STEP)
        out += [f"d 0 {sx} {sy}"]
        for i in range(1, 9):
            out += [f"s {STEP}", f"m 0 {sx} {lerp(sy, sy + sdy, i / 8)}"]
        out += ["s 200", f"d 1 {lx} {ly}"]
        for i in range(1, n + 1):
            out += [f"s {STEP}", f"m 1 {lerp(lx, lx + ldx, i / n)} {ly}"]
        out += ["u 1", "s 300", "u 0"]
    elif kind == "stick+tap":
        sx, sy, sdy, tx, ty, ms = v
        out += [f"d 0 {sx} {sy}"]
        for i in range(1, 9):
            out += [f"s {STEP}", f"m 0 {sx} {lerp(sy, sy + sdy, i / 8)}"]
        out += ["s 200", f"d 1 {tx} {ty}", "s 80", "u 1", f"s {max(0, ms - 280 - 8 * STEP)}", "u 0"]
    elif kind == "stick":
        # Walk: push the floating stick by (DX, DY) and hold it MS.
        sx, sy, dx, dy, ms = v
        out.append(f"d 0 {sx} {sy}")
        for i in range(1, 9):
            out += [f"s {STEP}", f"m 0 {lerp(sx, sx + dx, i / 8)} {lerp(sy, sy + dy, i / 8)}"]
        out += [f"s {ms}", "u 0"]
    elif kind == "path":
        # One finger along a polyline (a glyph): MS, then x1, y1, x2, y2, ...
        ms, pts = v[0], list(zip(v[1::2], v[2::2]))
        lengths = [((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 for (x1, y1), (x2, y2) in zip(pts, pts[1:])]
        total = sum(lengths) or 1
        out.append(f"d 0 {pts[0][0]} {pts[0][1]}")
        for (x1, y1), (x2, y2), length in zip(pts, pts[1:], lengths):
            n = max(1, round(ms * length / total / STEP))
            for i in range(1, n + 1):
                out += [f"s {STEP}", f"m 0 {lerp(x1, x2, i / n)} {lerp(y1, y2, i / n)}"]
        out += ["s 60", "u 0"]
    elif kind == "wait":
        out.append(f"s {v[0]}")
    else:
        raise SystemExit(f"unknown gesture {g}")
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["build", "run"])
    p.add_argument("gestures", nargs="*")
    p.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL") or os.environ.get("VOID_SERIAL"),
                        required=not (os.environ.get("ANDROID_SERIAL") or os.environ.get("VOID_SERIAL")))
    a = p.parse_args()
    if a.command == "build":
        out = ROOT / "build/vtouch"
        (out / "classes").mkdir(parents=True, exist_ok=True)
        jar = SDK / "platforms/android-36/android.jar"
        subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-cp", str(jar), "-d", str(out / "classes"),
                        str(ROOT / "tools/vtouch/VTouch.java")], check=True)
        classes = [str(c) for c in (out / "classes").rglob("*.class")]
        subprocess.run([str(SDK / "build-tools/36.1.0/d8.bat"), "--lib", str(jar), "--min-api", "26", "--output", str(out),
                        *classes], check=True)
        subprocess.run([ADB, "-s", a.serial, "push", str(out / "classes.dex"), REMOTE], check=True, capture_output=True)
        print("vtouch pushed")
        return
    lines = []
    for g in a.gestures:
        lines += gesture(g)
    script = "\n".join(lines) + "\n"
    r = subprocess.run([ADB, "-s", a.serial, "shell", f"CLASSPATH={REMOTE} app_process / org.thevoid.vtouch.VTouch"],
                       input=script.encode(), capture_output=True)
    sys.stdout.write(r.stdout.decode(errors="replace") + r.stderr.decode(errors="replace"))


if __name__ == "__main__":
    main()
