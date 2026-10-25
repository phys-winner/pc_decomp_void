"""Rebuild research/vfs-index.json from the game's data/*.vfs (LP2C containers,
directory layout as in Grumbel/thevoid-extractor). The analysis tools
(gscript_binary.py, glyph_script.py, patch_native_menu.py) read assets through
it, so it has to follow the installed data (English, Russian, German or Polish
release).

    python tools/build_vfs_index.py [--game DIR] [--out FILE] [--old FILE]
--game indexes another copy (default: port.json game_directory), --out writes
elsewhere (research/vfs-index.<language>.json), --old keeps a copy of the
previous index and reports the entries whose size changed between the two."""
import argparse
import collections
import json
import os
import shutil
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "research/vfs-index.json"
EXTRACTOR_COMMIT = "cca9adafa0c7fa36e691072256bf586eee336391"


def read_dir(f, parent, dir_count, file_count, out):
    for _ in range(file_count):
        name = f.read(f.read(1)[0])
        size, _unknown3, offset, _zero, _unknown1, _unknown2 = struct.unpack("<6I", f.read(24))
        out.append((parent + "\\" + name.decode("latin1"), offset, size))
    for _ in range(dir_count):
        name = f.read(f.read(1)[0])
        dirs, files = struct.unpack("<2I", f.read(8))
        read_dir(f, parent + "\\" + name.decode("latin1"), dirs, files, out)


def index_container(path):
    with path.open("rb") as f:
        if f.read(4) != b"LP2C":
            return None
        dirs, files = struct.unpack("<2I", f.read(8))
        entries = []
        read_dir(f, path.stem, dirs, files, entries)
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--old", type=Path, help="Keep the current index here and report changed entries")
    parser.add_argument("--game", type=Path, help="Game directory to index (default: port.json game_directory)")
    parser.add_argument("--out", type=Path, default=INDEX, help="Index file to write")
    args = parser.parse_args()
    game = args.game or Path(json.loads((ROOT / "port.json").read_text())["game_directory"])
    data = game / "data"
    if not data.is_dir() or not any(data.glob("*.vfs")):
        parser.error("game directory must contain data/*.vfs")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    previous = json.loads(args.out.read_text()) if args.out.exists() else None
    if args.old and previous:
        shutil.copyfile(args.out, args.old)
    containers = []
    for path in sorted(data.glob("*.vfs"), key=lambda p: p.name.lower()):
        entries = index_container(path)
        if entries is None:
            print(f"{path.name}: not an LP2C container, skipped")
            continue
        extensions = collections.Counter(os.path.splitext(n)[1].lower() for n, _, _ in entries)
        containers.append({
            "name": path.name,
            "size": path.stat().st_size,
            "entry_count": len(entries),
            "payload_bytes": sum(s for _, _, s in entries),
            "extensions": dict(extensions.most_common()),
            "entries": [{"name": n, "offset": o, "size": s} for n, o, s in entries],
        })
        print(f"{path.name}: {len(entries)} entries")
    args.out.write_text(json.dumps({"source": str(data), "extractor_commit": EXTRACTOR_COMMIT,
                                    "containers": containers}, indent=1))
    if previous:
        old = {e["name"]: e["size"] for c in previous["containers"] for e in c["entries"]}
        new = {e["name"]: e["size"] for c in containers for e in c["entries"]}
        changed = [n for n in new if n in old and old[n] != new[n]]
        added = [n for n in new if n not in old]
        removed = [n for n in old if n not in new]
        print(f"vs previous index: {len(changed)} resized, {len(added)} added, {len(removed)} removed")
        for label, names in (("resized", changed), ("added", added), ("removed", removed)):
            by_ext = collections.Counter(os.path.splitext(n)[1].lower() for n in names)
            print(f"  {label}: {dict(by_ext.most_common(12))}")


if __name__ == "__main__":
    main()
