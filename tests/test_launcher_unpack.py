"""The launcher's unpacking of the game (android/app/src/org/thevoid/port:
Zip.java, Deflate64.java, Unpacker.java), on the PC through
tests/LauncherUnpackTest.java:

  - the Deflate64 decoder against zlib (it decodes plain Deflate too) and
    against hand-made Deflate64 streams: length code 285 up to 65538 bytes,
    distance codes 30 and 31 up to 64 KiB back, a stored block between;
  - archives written here byte by byte: the game's root found above the
    shallowest bin/win32/Game.exe, names with backslashes, the DOS code
    page and Info-ZIP's UTF-8 field, ZIP64 records and fields, a
    self-extractor's stub before the archive, the target folder rules (an
    empty folder itself, including the port's folder, else TheVoid, TheVoid-2),
    and failures that leave nothing behind (no
    Game.exe, no info.xml, a path out of the root, BZip2, encryption, a
    wrong CRC, a stop);
  - with 7-Zip present: its Deflate64 (dynamic blocks) and Deflate;
  - --full ARCHIVE: a whole game archive, compared with the files it was made
    of (--source, the Steam copy by default).

    python tests/test_launcher_unpack.py [--full "build/launcher-test/The Void.zip"]
"""
import argparse
import hashlib
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
JAVA_HOME = Path(os.environ.get("JAVA_HOME", ""))
SEVEN_ZIP = Path(os.environ["ProgramFiles"]) / "7-Zip/7z.exe"
OUT = ROOT / "build/launcher-test/cases"
SOURCES = ["Zip.java", "Deflate64.java", "Unpacker.java"]
INFO = '<?xml version="1.0" encoding="utf-8"?>\n<Info Title="Тургор: Голос Цвета - Test" EngTitle="Turgor" />\n'
LANGUAGES = '<FileSystems><FileSystem Name="Russian" /></FileSystems>\n'


def run_java(*args):
    result = subprocess.run([str(JAVA_HOME / "bin/java.exe"), "-ea", "-Dstdout.encoding=UTF-8", "-cp",
                             str(OUT / "classes"), "org.thevoid.port.LauncherUnpackTest", *map(str, args)],
                            capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise SystemExit(f"java failed: {result.stdout}\n{result.stderr}")
    return result.stdout


# --------------------------------------------------------------- Deflate64

class Bits:
    """Bits LSB first, as Deflate sends them; Huffman codes MSB first."""

    def __init__(self):
        self.out, self.acc, self.n = bytearray(), 0, 0

    def put(self, value, count):
        self.acc |= value << self.n
        self.n += count
        while self.n >= 8:
            self.out.append(self.acc & 0xFF)
            self.acc >>= 8
            self.n -= 8

    def code(self, code, length):
        self.put(int(format(code, f"0{length}b")[::-1], 2), length)

    def align(self):
        if self.n:
            self.put(0, 8 - self.n)


LENGTH_BASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163,
               195, 227]
LENGTH_EXTRA = [0] * 8 + [1] * 4 + [2] * 4 + [3] * 4 + [4] * 4 + [5] * 4
DIST_BASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073,
             4097, 6145, 8193, 12289, 16385, 24577, 32769, 49153]
DIST_EXTRA = [0, 0, 0, 0] + [i // 2 for i in range(2, 30)]


def fixed_literal(bits, symbol):
    if symbol < 144:
        bits.code(0x30 + symbol, 8)
    elif symbol < 256:
        bits.code(0x190 + symbol - 144, 9)
    elif symbol < 280:
        bits.code(symbol - 256, 7)
    else:
        bits.code(0xC0 + symbol - 280, 8)


def deflate64_stream():
    """A Deflate64 stream in fixed-code blocks and a stored one, and its bytes."""
    rng = random.Random(64)
    data = bytearray()
    bits = Bits()

    def literals(chunk):
        for b in chunk:
            fixed_literal(bits, b)
        data.extend(chunk)

    def match(length, distance, long_code=False):
        if long_code or length > 258:
            fixed_literal(bits, 285)
            bits.put(length - 3, 16)
        else:
            code = max(i for i, base in enumerate(LENGTH_BASE) if base <= length)
            fixed_literal(bits, 257 + code)
            bits.put(length - LENGTH_BASE[code], LENGTH_EXTRA[code])
        d = max(i for i, base in enumerate(DIST_BASE) if base <= distance)
        bits.code(d, 5)
        bits.put(distance - DIST_BASE[d], DIST_EXTRA[d])
        for _ in range(length):
            data.append(data[-distance])

    bits.put(0, 1)   # not final
    bits.put(1, 2)   # fixed codes
    literals(bytes(rng.randrange(256) for _ in range(60000)))
    match(65538, 60000)          # the longest match, code 31, overlapping
    match(300, 40000)            # code 30
    match(258, 1, long_code=True)
    literals(b"hello")
    match(3, 65536)              # the farthest distance
    match(200, 32769)
    fixed_literal(bits, 256)
    bits.put(0, 1)               # a stored block
    bits.put(0, 2)
    bits.align()
    chunk = bytes(rng.randrange(256) for _ in range(1000))
    bits.put(len(chunk), 16)
    bits.put(len(chunk) ^ 0xFFFF, 16)
    for b in chunk:
        bits.put(b, 8)
    data.extend(chunk)
    bits.put(1, 1)               # final, fixed codes
    bits.put(1, 2)
    literals(b"end")
    match(65538, 3)
    match(17, 70000 - 60000)
    fixed_literal(bits, 256)
    bits.align()
    return bytes(bits.out), bytes(data)


def sample_data():
    rng = random.Random(7)
    text = b"".join(b"line %d of the void, the colour of %s\n" % (i, rng.choice([b"amber", b"azure", b"gold"]))
                    for i in range(40000))
    noise = rng.randbytes(300000)
    runs = b"".join(bytes([rng.randrange(256)]) * rng.randrange(1, 400) for _ in range(3000))
    return {"text": text, "noise": noise, "runs": runs, "mixed": text[:100000] + noise[:50000] + runs + text,
            "empty": b"", "byte": b"x"}


def check_inflate():
    for name, data in sample_data().items():
        for level in (0, 1, 6, 9):
            c = zlib.compressobj(level, zlib.DEFLATED, -15)
            raw = c.compress(data) + c.flush()
            stream, expected = OUT / f"inflate-{name}-{level}.raw", OUT / f"inflate-{name}-{level}.bin"
            stream.write_bytes(raw)
            expected.write_bytes(data)
            line = run_java("inflate", stream, expected, "32")
            assert line.startswith(f"inflated {len(data)} same"), (name, level, line)
    raw, data = deflate64_stream()
    (OUT / "deflate64.raw").write_bytes(raw)
    (OUT / "deflate64.bin").write_bytes(data)
    line = run_java("inflate", OUT / "deflate64.raw", OUT / "deflate64.bin", "64")
    assert line.startswith(f"inflated {len(data)} same"), line
    # As plain Deflate the same stream is refused (length code 285 means 258 there, distance codes 30/31 are invalid).
    line = run_java("inflate", OUT / "deflate64.raw", OUT / "deflate64.bin", "32")
    assert line.startswith("error") or "DIFFERENT" in line, line
    # Cut short.
    (OUT / "deflate64-cut.raw").write_bytes(raw[:len(raw) // 2])
    line = run_java("inflate", OUT / "deflate64-cut.raw", OUT / "deflate64.bin", "64")
    assert line.startswith("error"), line
    print(f"inflate: zlib streams of {len(sample_data())} kinds at 4 levels, a Deflate64 stream of {len(data)} bytes")
    return raw, data


# -------------------------------------------------------------- archives

def write_zip(path, entries, zip64=False, prefix=b""):
    """entries: dicts with name (bytes), data, method (0, 8, 9, 12), flags,
    payload (packed bytes for method 9), crc (to lie), unicode (UTF-8 name
    for Info-ZIP's 0x7075 field), directory."""
    body, central = bytearray(prefix), bytearray()
    for e in entries:
        data = e.get("data", b"")
        method = e.get("method", 8)
        if "payload" in e:
            packed = e["payload"]
        elif method == 8:
            c = zlib.compressobj(6, zlib.DEFLATED, -15)
            packed = c.compress(data) + c.flush()
        elif method == 12:
            import bz2
            packed = bz2.compress(data)
        else:
            packed = data
        crc = e.get("crc", zlib.crc32(data))
        flags = e.get("flags", 0)
        name = e["name"]
        extra = b""
        if "unicode" in e:
            u = e["unicode"].encode("utf-8")
            extra += struct.pack("<HHBI", 0x7075, 5 + len(u), 1, zlib.crc32(name)) + u
        offset = len(body) - len(prefix)
        local_extra = extra
        if zip64:
            local_extra = struct.pack("<HHQQ", 1, 16, len(data), len(packed)) + extra
        body += struct.pack("<IHHHHHIIIHH", 0x04034b50, 45 if zip64 else 20, flags, method, 0, 0x21, crc,
                            0xFFFFFFFF if zip64 else len(packed), 0xFFFFFFFF if zip64 else len(data),
                            len(name), len(local_extra)) + name + local_extra + packed
        central_extra = extra
        if zip64:
            central_extra = struct.pack("<HHQQQ", 1, 24, len(data), len(packed), offset) + extra
        central += struct.pack("<IHHHHHHIIIHHHHHII", 0x02014b50, 0x033F, 45 if zip64 else 20, flags, method, 0, 0x21,
                               crc, 0xFFFFFFFF if zip64 else len(packed), 0xFFFFFFFF if zip64 else len(data),
                               len(name), len(central_extra), 0, 0, 0, 0x10 if e.get("directory") else 0x20,
                               0xFFFFFFFF if zip64 else offset) + name + central_extra
    cd_offset = len(body) - len(prefix)
    out = body + central
    if zip64:
        record_at = len(out) - len(prefix)
        out += struct.pack("<IQHHIIQQQQ", 0x06064b50, 44, 45, 45, 0, 0, len(entries), len(entries), len(central),
                           cd_offset)
        out += struct.pack("<IIQI", 0x07064b50, 0, record_at, 1)
        out += struct.pack("<IHHHHIIH", 0x06054b50, 0, 0, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0)
    else:
        out += struct.pack("<IHHHHIIH", 0x06054b50, 0, 0, len(entries), len(entries), len(central), cd_offset, 0)
    path.write_bytes(bytes(out))


def game_entries(root=b"The Void/", sep=b"/", extra=()):
    rng = random.Random(1)
    files = {
        b"bin/win32/Game.exe": b"MZ" + rng.randbytes(5000),
        b"data/info.xml": INFO.encode("utf-8"),
        b"data/fsystems.xml": LANGUAGES.encode("utf-8"),
        b"data/Scripts.vfs": rng.randbytes(200000) + b"\0" * 500000,
        b"data/stored.bin": rng.randbytes(70000),
        b"Void/Cache/effects.hdr": b"effects " * 5000,
        b"readme.txt": b"The Void\r\n",
    }
    entries = []
    for rel, data in files.items():
        entries.append(dict(name=(root + rel).replace(b"/", sep), data=data,
                            method=0 if rel.endswith(b"stored.bin") else 8))
    entries.append(dict(name=(root + b"Void/Empty/").replace(b"/", sep), data=b"", method=0, directory=True))
    entries.extend(extra)
    return entries, {rel.decode(): data for rel, data in files.items()}


def tree(path):
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in path.rglob("*") if p.is_file()}


def fresh(name):
    d = OUT / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


def unpack(archive, chosen, cancel=None):
    args = ["unpack", archive, chosen]
    if cancel is not None:
        args.append(cancel)
    return run_java(*args).splitlines()


def check_archives(d64_raw, d64_data):
    # The game at the top of a folder in the archive; a sibling stays out.
    entries, files = game_entries(extra=[dict(name=b"outside.txt", data=b"not the game"),
                                         dict(name=b"__MACOSX/The Void/bin/win32/Game.exe", data=b"fork")])
    write_zip(OUT / "basic.zip", entries)
    chosen = fresh("basic")
    lines = unpack(OUT / "basic.zip", chosen)
    assert lines[0].startswith(f"plan root=The Void/ files={len(files)} folders=1"), lines
    assert lines[0].endswith(f"target={chosen}"), lines
    assert lines[1] == "info Тургор: Голос Цвета - Test / Russian", lines
    assert lines[2].startswith("unpacked"), lines
    assert tree(chosen) == files, sorted(tree(chosen))
    assert (chosen / "Void/Empty").is_dir() and not (chosen / ".unpacking").exists()

    # A folder that holds something gets TheVoid, then TheVoid-2.
    chosen = fresh("nonempty")
    (chosen / "photo.jpg").write_bytes(b"jpg")
    lines = unpack(OUT / "basic.zip", chosen)
    assert lines[0].endswith(f"target={chosen / 'TheVoid'}"), lines
    assert tree(chosen / "TheVoid") == files
    lines = unpack(OUT / "basic.zip", chosen)
    assert lines[0].endswith(f"target={chosen / 'TheVoid-2'}"), lines
    assert tree(chosen / "TheVoid-2") == files and (chosen / "photo.jpg").read_bytes() == b"jpg"

    # A fresh /sdcard/TheVoid must be used directly, just like any empty folder.
    chosen = fresh("TheVoid")
    lines = unpack(OUT / "basic.zip", chosen)
    assert lines[0].endswith(f"target={chosen}"), lines
    assert tree(chosen) == files
    assert not (chosen / "TheVoid").exists()
    # Once a profile exists, preserve it and unpack into a child instead.
    chosen = fresh("with-profile")
    (chosen / "userdata").mkdir()
    (chosen / "userdata/save.dat").write_bytes(b"save")
    lines = unpack(OUT / "basic.zip", chosen)
    assert lines[0].endswith(f"target={chosen / 'TheVoid'}"), lines
    assert tree(chosen / "TheVoid") == files
    assert (chosen / "userdata/save.dat").read_bytes() == b"save"

    # Backslashes, ZIP64 fields and records, a stub before the archive.
    entries, files = game_entries(root=b"Games\\The Void\\", sep=b"\\")
    write_zip(OUT / "zip64.zip", entries, zip64=True, prefix=b"MZ" + b"\0" * 998)
    chosen = fresh("zip64")
    lines = unpack(OUT / "zip64.zip", chosen)
    assert lines[0].startswith("plan root=Games/The Void/"), lines
    assert lines[2].startswith("unpacked") and tree(chosen) == files, lines

    # Deflate64 entries; the game at the archive's top.
    entries, files = game_entries(root=b"")
    entries.append(dict(name=b"data/Textures.vfs", data=d64_data, method=9, payload=d64_raw))
    files["data/Textures.vfs"] = d64_data
    write_zip(OUT / "deflate64.zip", entries)
    chosen = fresh("deflate64")
    lines = unpack(OUT / "deflate64.zip", chosen)
    assert lines[0].startswith("plan root= "), lines
    assert lines[2].startswith("unpacked") and tree(chosen) == files, lines

    # The shallowest copy is the game; names in the DOS code page (Windows
    # Explorer), with and without Info-ZIP's UTF-8 field, and flagged UTF-8.
    deep, _ = game_entries(root=b"a/b/The Void/")
    top, files = game_entries(root="Тургор/".encode("cp866"))
    for e in top:
        e["unicode"] = e["name"].decode("cp866")
    write_zip(OUT / "nested.zip", deep + top)
    chosen = fresh("nested")
    lines = unpack(OUT / "nested.zip", chosen)
    assert lines[0].startswith("plan root=Тургор/ "), lines
    assert lines[2].startswith("unpacked") and tree(chosen) == files, lines
    for e in top:
        del e["unicode"]
    write_zip(OUT / "dos.zip", deep + top)
    chosen = fresh("dos")
    lines = unpack(OUT / "dos.zip", chosen)
    assert lines[0].startswith("plan root=") and "a/b/" not in lines[0], lines
    assert lines[2].startswith("unpacked") and tree(chosen) == files, lines
    flagged, files = game_entries(root="Тургор/".encode("utf-8"))
    for e in flagged:
        e["flags"] = 0x800
    write_zip(OUT / "utf8.zip", flagged)
    chosen = fresh("utf8")
    lines = unpack(OUT / "utf8.zip", chosen)
    assert lines[0].startswith("plan root=Тургор/ "), lines
    assert lines[2].startswith("unpacked") and tree(chosen) == files, lines

    # Failures leave nothing: the chosen folder as it was, a new one gone.
    def fails(name, entries, code, detail=None, nonempty=False, cancel=None):
        write_zip(OUT / f"{name}.zip", entries)
        chosen = fresh(name)
        if nonempty:
            (chosen / "keep.txt").write_bytes(b"keep")
        lines = unpack(OUT / f"{name}.zip", chosen, cancel=cancel)
        failure = next(l for l in lines if l.startswith("failure"))
        assert failure.split()[1] == str(code), (name, lines)
        if detail is not None:
            assert failure.split(None, 2)[2] == detail, (name, lines)
        assert sorted(p.name for p in chosen.iterdir()) == (["keep.txt"] if nonempty else []), (name, lines)

    entries, _ = game_entries()
    fails("no-game", [e for e in entries if not e["name"].endswith(b"Game.exe")], 3)
    fails("not-void", [e for e in entries if not e["name"].endswith(b"info.xml")], 4, "The Void/")
    fails("unsafe", entries + [dict(name=b"The Void/../evil.txt", data=b"x")], 5, "The Void/../evil.txt")
    fails("bzip2", entries + [dict(name=b"The Void/data/x.bin", data=b"x" * 1000, method=12)], 6, "BZip2")
    fails("encrypted", entries + [dict(name=b"The Void/data/x.bin", data=b"x", flags=1)], 7)
    bad = [dict(e) for e in entries]
    bad[3]["crc"] = 12345
    fails("crc", bad, 8, "data/Scripts.vfs")
    fails("crc-nonempty", bad, 8, "data/Scripts.vfs", nonempty=True)
    big = [dict(name=b"The Void/data/big%d.bin" % i, data=random.Random(i).randbytes(24 << 20), method=0)
           for i in range(4)]
    fails("cancel", entries + big, 12, cancel=1 << 20)
    fails("cancel-nonempty", entries + big, 12, nonempty=True, cancel=30 << 20)
    print("archives: roots, names, ZIP64, stub, Deflate64, targets, 9 failures")


def check_roots():
    entries, files = game_entries(root=b"")
    write_zip(OUT / "roots.zip", entries)
    base = fresh("roots")
    game = base / "Games" / "The Void"
    game.mkdir(parents=True)
    lines = unpack(OUT / "roots.zip", game)
    assert lines[2].startswith("unpacked"), lines
    (base / "Other").mkdir()
    for chosen, want in ((game, game), (game / "data", game), (game / "bin/win32", game), (base, game),
                         (base / "Games", game), (base / "Other", None)):
        line = run_java("root", chosen).rstrip("\n").split(" ", 2)
        assert line[2] == (str(want) if want else "-"), (chosen, line)
        assert line[1] == ("true" if want else "false"), (chosen, line)
    print("roots: the folder, above it, below it, none")


def check_seven_zip(d64_data):
    if not SEVEN_ZIP.is_file():
        print("7-Zip: not found, skipped")
        return
    src = fresh("7z-source") / "The Void"
    _, files = game_entries(root=b"")
    files["data/Textures.vfs"] = d64_data + sample_data()["mixed"] + random.Random(3).randbytes(2 << 20)
    for rel, data in files.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_bytes(data)
    for method in ("Deflate64", "Deflate"):
        archive = OUT / f"7z-{method}.zip"
        archive.unlink(missing_ok=True)
        subprocess.run([str(SEVEN_ZIP), "a", "-tzip", f"-mm={method}", "-mx=9", str(archive), "The Void"],
                       cwd=src.parent, check=True, capture_output=True)
        chosen = fresh(f"7z-{method}-out")
        lines = unpack(archive, chosen)
        assert lines[2].startswith("unpacked") and tree(chosen) == files, (method, lines)
    print("7-Zip: Deflate64 and Deflate archives")


def check_full(archive, source):
    chosen = fresh("full")
    lines = unpack(archive, chosen)
    print("\n".join(lines))
    assert lines[2].startswith("unpacked"), lines
    want = {p.relative_to(source).as_posix() for p in source.rglob("*") if p.is_file()}
    got = {p.relative_to(chosen).as_posix() for p in chosen.rglob("*") if p.is_file()}
    assert want == got, sorted(want ^ got)[:20]
    for rel in sorted(want):
        a, b = source / rel, chosen / rel
        assert a.stat().st_size == b.stat().st_size, rel
        ha, hb = hashlib.sha256(), hashlib.sha256()
        for h, p in ((ha, a), (hb, b)):
            with p.open("rb") as f:
                for block in iter(lambda: f.read(1 << 22), b""):
                    h.update(block)
        assert ha.digest() == hb.digest(), rel
    print(f"full: {len(want)} files the same as {source}")
    shutil.rmtree(chosen)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--full", type=Path, help="a whole game archive to unpack and compare")
    parser.add_argument("--source", type=Path, default=ROOT / "original/the-void-russian")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")   # the release's titles
    OUT.mkdir(parents=True, exist_ok=True)
    classes = OUT / "classes"
    if classes.exists():
        shutil.rmtree(classes)
    sources = [ROOT / "android/app/src/org/thevoid/port" / s for s in SOURCES] + [ROOT / "tests/LauncherUnpackTest.java"]
    subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(classes),
                    *map(str, sources)], check=True)
    raw, data = check_inflate()
    check_archives(raw, data)
    check_roots()
    check_seven_zip(data)
    if args.full:
        check_full(args.full, args.source)
    print("PASS")


if __name__ == "__main__":
    sys.exit(main())
