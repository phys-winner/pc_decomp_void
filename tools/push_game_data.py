"""Put everything the Android build reads on a device: the user's Steam copy of
the game, the PE images the generated code was lifted from, the shader and
effect caches of the Windows profile and, on request, the user's saves.

    python tools/push_game_data.py [--serial SERIAL] [--saves]
    python tools/push_game_data.py --game original/the-void-german --target game-german

Layout on the device (android/host reads it, the APK and the shell build alike):
    /sdcard/TheVoid/game      the Steam directory (bin/, data/, Void/), read only
    /sdcard/TheVoid/game-*    further releases (--target), chosen in the APK
                              (game.txt) or with the shell build's --game
    /sdcard/TheVoid/lifted    rebased images (generated/input) and GameModule.dll
    /sdcard/TheVoid/userdata  the writable profile (Documents, caches, saves)
Every release runs on the same lifted images: the English/Russian 2009 build
(the German and Polish releases ship other builds of the DLLs; only their data
is used). Files already on the device with the same size and SHA-256 are
skipped (`adb push --sync` compares times only, and copies from Windows carry
fresh ones). Saves go to Documents/My Games/<title>, the release's profile
folder (tools/void_profile.py); --saves-dir picks another source (e.g.
test_save/Savegames).
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from void_profile import game_directory, profile_title

from toolchain import ADB

ROOT = Path(__file__).resolve().parents[1]
DEVICE = "/sdcard/TheVoid"
LIFTED = ["Game.exe", "Engine.dll", "FS.dll", "VFS.dll", "Sound.dll", "Video.dll", "RendererD3D.dll",
          "NxCharacter.dll", "PhysXCore.dll", "PhysXCooking.dll", "d3dx9_36.dll"]
# GameModule.dll is lifted at its own base: the image the generated code was
# made from (the English and Russian releases ship this very file).
GAMEMODULE_SHA256 = "a0075c2316bdb658724aaec595339a8ad2459832620b0a9dac3c7359a4330562"


def adb(serial, *args, capture=True):
    result = subprocess.run([ADB, "-s", serial, *args], capture_output=capture, text=True)
    if result.returncode:
        raise SystemExit(f"adb {' '.join(args[:2])} failed: {result.stderr.strip()}")
    return result.stdout


def device_sizes(serial, directory):
    """Relative path -> size for every file under a device directory."""
    listing = adb(serial, "shell", f"cd '{directory}' 2>/dev/null && find . -type f -exec stat -c '%s %n' {{}} + || true")
    sizes = {}
    for line in listing.splitlines():
        size, _, name = line.partition(" ")
        if name.startswith("./"):
            sizes[name[2:]] = int(size)
    return sizes


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def same_content(serial, path, remote):
    """Size alone misses edits of equal length (fsystems.xml: English -> Russian)."""
    return adb(serial, "shell", f"sha256sum '{remote}'").split(" ")[0] == sha256(path)


def push_tree(serial, source, target):
    have = device_sizes(serial, target)
    pushed = 0
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        rel = path.relative_to(source).as_posix()
        if have.get(rel) == path.stat().st_size and same_content(serial, path, f"{target}/{rel}"):
            continue
        adb(serial, "shell", f"mkdir -p '{target}/{Path(rel).parent.as_posix()}'")
        print(f"push {rel} ({path.stat().st_size / 1e6:.1f} MB)", flush=True)
        adb(serial, "push", str(path), f"{target}/{rel}")
        pushed += 1
    print(f"{target}: {pushed} pushed, {len(have)} already there")


def reference_gamemodule(game):
    """The GameModule.dll the lifted code belongs to: the release's own copy
    when it is that file, else generated/input/GameModule.dll."""
    for path in (game / "bin/win32/GameModule.dll", ROOT / "generated/input/GameModule.dll"):
        if path.is_file() and sha256(path) == GAMEMODULE_SHA256:
            return path
    raise SystemExit("no GameModule.dll with the lifted build's SHA-256: copy the English or Russian "
                     "release's bin/win32/GameModule.dll to generated/input/GameModule.dll")


def other_release(game):
    """The tools/lift_release.py release whose Game.exe this copy ships, if any."""
    exe = game / "bin/win32/Game.exe"
    digest = sha256(exe) if exe.is_file() else None
    for config in sorted((ROOT / "config/releases").glob("*.json")):
        spec = json.loads(config.read_text())
        if any(m["name"] == "Game" and m["sha256"] == digest for m in spec["modules"]):
            return config.stem
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL") or os.environ.get("VOID_SERIAL"),
                        required=not (os.environ.get("ANDROID_SERIAL") or os.environ.get("VOID_SERIAL")))
    parser.add_argument("--game", type=Path, help="Release directory to push (default: port.json game_directory)")
    parser.add_argument("--target", default="game", help="Directory under /sdcard/TheVoid (game, game-german, ...)")
    parser.add_argument("--saves", action="store_true", help="Also copy the user's saves (Documents\\My Games\\<title>)")
    parser.add_argument("--saves-dir", type=Path, help="Where --saves copies from (default: the PC profile)")
    args = parser.parse_args()
    game = args.game or game_directory()
    title = profile_title(game)
    print(f"{game}: profile folder {title}")
    for part in ("bin", "data", "Void"):   # not the DirectX/PhysX installers or the manual
        push_tree(args.serial, game / part, f"{DEVICE}/{args.target}/{part}")
    release = other_release(game)
    if release:
        # Another build of the binaries: its own lifted images (the APK and
        # build/arm64-<release> load them from lifted-<release>).
        images = ROOT / "generated" / release / "input"
        if not images.is_dir():
            raise SystemExit(f"{game} is the {release} release: run tools/lift_release.py {release} first")
        push_tree(args.serial, images, f"{DEVICE}/lifted-{release}")
        subprocess.run([sys.executable, str(ROOT / "tools/push_profile_cache.py"), "--serial", args.serial,
                        "--title", title], check=True)
        saves = args.saves_dir or Path(os.path.expandvars(rf"%USERPROFILE%\Documents\My Games\{title}\Savegames"))
        if args.saves and saves.is_dir():
            push_tree(args.serial, saves, f"{DEVICE}/userdata/Documents/My Games/{title}/Savegames")
        return
    lifted = ROOT / "build/lifted-images"
    lifted.mkdir(parents=True, exist_ok=True)
    for name in LIFTED:
        (lifted / name).write_bytes((ROOT / "generated/input" / name).read_bytes())
    (lifted / "GameModule.dll").write_bytes(reference_gamemodule(game).read_bytes())
    push_tree(args.serial, lifted, f"{DEVICE}/lifted")
    subprocess.run([sys.executable, str(ROOT / "tools/push_profile_cache.py"), "--serial", args.serial,
                    "--title", title], check=True)
    saves = args.saves_dir or Path(os.path.expandvars(rf"%USERPROFILE%\Documents\My Games\{title}\Savegames"))
    if args.saves and saves.is_dir():
        push_tree(args.serial, saves, f"{DEVICE}/userdata/Documents/My Games/{title}/Savegames")


if __name__ == "__main__":
    main()
