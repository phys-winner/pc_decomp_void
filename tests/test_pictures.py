"""android/host/pictures.c (the game's screenshots) on the phone, through the
shell only: tests/pictures_probe.c writes every D3DXIMAGE_FILEFORMAT from a
known picture, opaque and with alpha; the files are read back here (Pillow,
or by hand for PFM and HDR) and compared with the values pictures.c must
have written.

    python tests/test_pictures.py [--serial S]
"""
import argparse
import os
import struct
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
NDK = Path(os.environ.get("ANDROID_NDK", (Path(os.environ.get("ANDROID_SDK") or os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or Path.home() / "AppData/Local/Android/Sdk") / "ndk/27.2.12479018")))
CLANG = NDK / "toolchains/llvm/prebuilt/windows-x86_64/bin/clang.exe"
ADB = os.environ.get("ADB", str(Path(os.environ.get("ANDROID_SDK") or os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or Path.home() / "AppData/Local/Android/Sdk") / "platform-tools/adb.exe"))
REMOTE = "/data/local/tmp/void"
W, H = 37, 23
EXT = ["bmp", "jpg", "tga", "png", "dds", "ppm", "dib", "hdr", "pfm"]


def expected(alpha):
    """The probe's picture as float32 RGBA, computed as C does (no FMA)."""
    f = np.float32
    p = np.zeros((H, W, 4), np.float32)
    for y in range(H):
        for x in range(W):
            p[y, x] = (f(x) / f(W - 1), f(y) / f(H - 1), f((x * 7 + y * 13) % 31) / f(30),
                       f((x + y) % 5) / f(4) if alpha else f(1))
    p[0, 0, 0], p[0, 0, 1] = f(-0.5), f(1.5)
    return p


def to_bytes(p):
    v = p * np.float32(255) + np.float32(0.5)
    return np.where(p <= 0, 0, np.where(p >= 1, 255, v.astype(np.int32))).astype(np.uint8)


def read_pfm(path):
    data = path.read_bytes()
    head, rest = data.split(b"\n", 3)[:3], data.split(b"\n", 3)[3]
    assert head[0] == b"PF" and head[1] == f"{W} {H}".encode() and float(head[2]) < 0, head
    rows = np.frombuffer(rest, "<f4").reshape(H, W, 3)
    return rows[::-1]


def read_hdr(path):
    """Radiance RGBE as stb writes it (new-style run-length scanlines)."""
    data = path.read_bytes()
    end = data.index(b"\n\n") + 2
    header = data[:end].decode("ascii")
    assert header.startswith("#?RADIANCE") and "FORMAT=32-bit_rle_rgbe" in header, header
    line_end = data.index(b"\n", end)
    assert data[end:line_end] == f"-Y {H} +X {W}".encode(), data[end:line_end]
    pos = line_end + 1
    out = np.zeros((H, W, 3), np.float32)
    for y in range(H):
        assert data[pos:pos + 2] == b"\x02\x02", data[pos:pos + 4]
        assert (data[pos + 2] << 8 | data[pos + 3]) == W
        pos += 4
        rgbe = np.zeros((4, W), np.uint8)
        for c in range(4):
            x = 0
            while x < W:
                n = data[pos]
                pos += 1
                if n > 128:
                    rgbe[c, x:x + n - 128] = data[pos]
                    pos += 1
                    x += n - 128
                else:
                    rgbe[c, x:x + n] = list(data[pos:pos + n])
                    pos += n
                    x += n
        e = rgbe[3].astype(np.int32)
        scale = np.where(e == 0, 0.0, np.ldexp(1.0, e - (128 + 8)))
        for c in range(3):
            out[y, :, c] = (rgbe[c] + 0.5) * scale * (e != 0)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL") or os.environ.get("VOID_SERIAL"),
                        required=not (os.environ.get("ANDROID_SERIAL") or os.environ.get("VOID_SERIAL")))
    args = parser.parse_args()
    out = ROOT / "build/pictures-probe"
    out.mkdir(parents=True, exist_ok=True)
    probe = out / "pictures_probe"
    flags = ["--target=aarch64-linux-android30", "-fno-strict-aliasing", "-fwrapv", "-fPIC", "-ffp-contract=off",
             "-fno-math-errno", "-O2", "-std=gnu11", "-Wall", "-Wno-unused-function", "-Werror",
             "-Iandroid/runtime", "-Iandroid/host"]
    subprocess.run([str(CLANG), *flags, "tests/pictures_probe.c", "android/host/pictures.c", "-lm", "-o", str(probe)],
                   cwd=ROOT, check=True)
    adb = [ADB, "-s", args.serial]
    folder = f"{REMOTE}/pictures"
    subprocess.run([*adb, "shell", f"mkdir -p {folder}"], check=True)   # the probe replaces its own files
    subprocess.run([*adb, "push", str(probe), f"{REMOTE}/pictures_probe"], check=True, capture_output=True)
    run = subprocess.run([*adb, "shell", f"chmod 755 {REMOTE}/pictures_probe && {REMOTE}/pictures_probe {folder}"],
                         check=True, capture_output=True, text=True)
    log = run.stdout.splitlines()
    (out / "output.txt").write_text(run.stdout)
    files = out / "files"
    files.mkdir(exist_ok=True)
    for name in files.iterdir():
        name.unlink()
    for alpha in ("opaque", "alpha"):
        for ext in EXT:
            subprocess.run([*adb, "pull", f"{folder}/{alpha}.{ext}", str(files / f"{alpha}.{ext}")], check=True,
                           capture_output=True)

    created = [line for line in log if line.startswith("created ")]
    assert len(created) == 18 and all(line.endswith(" 1") for line in created), created
    assert "unwritable 0" in log, log
    assert "changed 18" in log, log
    written = [line for line in log if line.startswith("log ") and " written: " in line]
    assert len(written) == 18, log
    assert sum(" (format 21, alpha) " in line for line in written) == 9, written
    saved = sorted(line.split("/")[-1] for line in log if line.startswith("saved "))
    assert saved == sorted(f"{a}.{e}" for a in ("opaque", "alpha") for e in ("png", "jpg", "bmp")), saved

    report = []
    for alpha in (False, True):
        want = expected(alpha)
        want8 = to_bytes(want)
        prefix = "alpha" if alpha else "opaque"
        for ext in ("png", "bmp", "dib", "tga", "dds", "ppm"):
            image = Image.open(files / f"{prefix}.{ext}")
            keeps_alpha = alpha and ext not in ("ppm",)
            mode = "RGBA" if keeps_alpha or ext == "dds" else "RGB"
            assert image.mode == mode, (prefix, ext, image.mode)
            got = np.asarray(image)
            ref = want8 if mode == "RGBA" else want8[..., :3]
            if ext == "dds" and not alpha:
                assert (got[..., 3] == 255).all()
            assert got.shape == ref.shape and (got == ref).all(), (prefix, ext, np.argwhere(got != ref)[:5])
            report.append(f"{prefix}.{ext} {image.mode} exact")
        jpg = np.asarray(Image.open(files / f"{prefix}.jpg").convert("RGB")).astype(np.int32)
        error = np.abs(jpg - want8[..., :3].astype(np.int32))
        assert error.mean() < 4, (prefix, error.mean())
        report.append(f"{prefix}.jpg mean error {error.mean():.2f}")
        pfm = read_pfm(files / f"{prefix}.pfm")
        assert (pfm == want[..., :3]).all(), prefix
        report.append(f"{prefix}.pfm exact")
        hdr = read_hdr(files / f"{prefix}.hdr")
        clipped = np.clip(want[..., :3], 0, None)
        assert np.abs(hdr - clipped).max() < 0.02 * max(1.0, clipped.max()), (prefix, np.abs(hdr - clipped).max())
        report.append(f"{prefix}.hdr within RGBE precision")
    print("\n".join(report))
    print("pictures.c: 18 files, the names taken before writing, 6 for the gallery")


if __name__ == "__main__":
    main()
