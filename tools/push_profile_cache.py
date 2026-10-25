"""Copy the shader and effect caches the Windows game built on this PC to the
Android profile.

The Void keeps compiled shaders (SQLite *.db) and effect materials
(effects*.dat/hdr, custom.dat/hdr) in Public Documents\\My Games\\<title>\\Cache
and extends them as new materials are met. The copy installed by Steam lacks
materials the game adds at run time (the main menu's captions among them), so
the device starts from the caches the real game and the real D3DX produced on
this PC; the Android build keeps extending them the same way.

<title> follows the release (tools/void_profile.py, --title): Void (English,
German), Turgor (Russian), Tension (Polish). The 2009 releases ship the same
Effects.vfs, so when this PC only ran another of them its caches serve as well;
the Polish one has no PC cache here and starts from its own Void\\Cache.

    python tools/push_profile_cache.py [--serial SERIAL] [--title Turgor] [--force]
"""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess

from toolchain import ADB

from void_profile import profile_title

PC_GAMES = Path(os.environ.get("PUBLIC", Path.home().parent / "Public")) / "Documents/My Games"
# Effects.vfs is the same in the English, Russian and German releases (2009);
# the Polish "Tension" (2008) has its own, and only its Void\Cache fits it.
SHARED_EFFECTS = ("Void", "Turgor")


def adb(serial, *args):
    return subprocess.run([ADB, "-s", serial, *args], check=True, capture_output=True, text=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL") or os.environ.get("VOID_SERIAL"),
                        required=not (os.environ.get("ANDROID_SERIAL") or os.environ.get("VOID_SERIAL")))
    parser.add_argument("--force", action="store_true", help="Replace cache files the device already has")
    parser.add_argument("--title", default=profile_title(), help="Profile folder (data/info.xml EngTitle)")
    args = parser.parse_args()
    candidates = (args.title,) + (SHARED_EFFECTS if args.title in SHARED_EFFECTS else ())
    PC_CACHE = next((PC_GAMES / t / "Cache" for t in candidates if (PC_GAMES / t / "Cache").is_dir()), None)
    if PC_CACHE is None:
        print(f"no PC cache for {args.title}: the device seeds it from the release's Void\\Cache")
        return
    DEVICE_CACHE = f"/sdcard/TheVoid/userdata/PublicDocuments/My Games/{args.title}/Cache"
    files = sorted(p for p in PC_CACHE.iterdir() if p.is_file())
    if not files:
        raise SystemExit(f"no cache files in {PC_CACHE}")
    listing = adb(args.serial, "shell", f"cd '{DEVICE_CACHE}' 2>/dev/null && sha256sum * 2>/dev/null || true")
    device = {line.split()[1]: line.split()[0] for line in listing.splitlines() if len(line.split()) == 2}
    adb(args.serial, "shell", f"mkdir -p '{DEVICE_CACHE}'")
    pushed = 0
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if device.get(path.name) == digest:
            continue
        if path.name in device and not args.force:
            # The device extends its caches as it meets new materials (the
            # .dat/.hdr pairs and the .db files alike, possibly while the game
            # runs): a file it already has stays unless --force.
            print(f"keep device {path.name}")
            continue
        adb(args.serial, "push", str(path), f"{DEVICE_CACHE}/{path.name}")
        pushed += 1
        print(f"pushed {path.name}")
    print(f"{pushed} of {len(files)} cache files pushed")


if __name__ == "__main__":
    main()
