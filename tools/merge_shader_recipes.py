"""Merge GL program recipes recorded on phones into build/shaderwarm (packed by build_game_apk.py).

A phone records a recipe (the GLSL of a linked program and its attribute names)
in <app files>/shaderwarm whenever it links a program; the menu's warm-up
links the packed ones before play (android/host/shader_warm.c). Recipes do not
depend on the device. Each is checked as shader_warm.c checks it, and its file
name must be the FNV-1a hash of its bytes; same-name files with different
bytes are reported and the first source wins.

  adb exec-out run-as org.thevoid.port tar -cf - files/shaderwarm > recipes.tar   (then unpack)
  python -B tools/merge_shader_recipes.py DIR [DIR...]
"""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/shaderwarm"
MAGIC = 0x31575356
HEADER = 16 + 16 * 64
LIMIT = 256 * 1024


def fnv(data):
    h = 0xCBF29CE484222325
    for b in data:
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def invalid(data):
    """Why a recipe is unusable, or None."""
    if len(data) < HEADER:
        return "short"
    magic, vs, ps, count = struct.unpack_from("<4I", data, 0)
    if magic != MAGIC or not vs or not ps or count > 16 or vs > LIMIT or ps > LIMIT or HEADER + vs + ps != len(data):
        return "header"
    for i in range(count):
        name = data[16 + i * 64:16 + (i + 1) * 64]
        if not name[0] or b"\0" not in name:
            return "names"
    v = data[HEADER:HEADER + vs]
    p = data[HEADER + vs:]
    if v[-1] or p[-1] or v.index(b"\0") + 1 != vs or p.index(b"\0") + 1 != ps:
        return "text"
    return None


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    OUT.mkdir(parents=True, exist_ok=True)
    taken, bad, conflicts = {}, 0, 0
    for source in sys.argv[1:]:
        for f in sorted(Path(source).glob("*.bin")):
            data = f.read_bytes()
            why = invalid(data)
            if why is None and f.stem != f"{fnv(data):016x}":
                why = "hash"
            if why:
                bad += 1
                print(f"skip {f}: {why}")
                continue
            if f.name in taken:
                if taken[f.name] != data:
                    conflicts += 1
                    print(f"conflict {f.name}: kept the first")
                continue
            taken[f.name] = data
    for name, data in taken.items():
        target = OUT / name
        if not target.is_file() or target.read_bytes() != data:
            target.write_bytes(data)
    print(f"recipes: {len(taken)} in {OUT} ({sum(len(d) for d in taken.values()) / 1e6:.1f} MB), "
          f"{bad} skipped, {conflicts} conflicts")


if __name__ == "__main__":
    main()
