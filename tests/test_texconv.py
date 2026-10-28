"""android/texconv on the PC: the launcher's texture conversion end to end.

A synthetic data/Textures.vfs checks the inventory (DDS .tex, animation frames,
other formats left alone), the pack (format per texture, dedupe, index order,
the header), the content key against an independent Python CRC-32/CRC-32C, the
decode of every converted level against the port's DXT decode, replacing and
removing a pack. The installed Russian game, when present, checks the quality
of both formats on real textures.
"""
import os
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/tests/texconv"
GAME_DATA = ROOT / "original/the-void-russian/data"
TVTX_GL_ETC2_RGB8, TVTX_GL_ETC2_RGBA8, TVTX_GL_ASTC_4x4 = 0x9274, 0x9278, 0x93B0


def msvc_env():
    vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
    installation = Path(subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-property", "installationPath"],
                                                text=True).strip())
    msvc = sorted((installation / "VC/Tools/MSVC").iterdir())[-1]
    sdk = Path(r"C:\Program Files (x86)\Windows Kits\10")
    version = sorted((sdk / "Lib").iterdir())[-1].name
    compiler = msvc / "bin/Hostx64/x64/cl.exe"
    env = os.environ.copy()
    env["PATH"] = str(compiler.parent) + os.pathsep + env["PATH"]
    env["INCLUDE"] = ";".join(map(str, [msvc / "include", sdk / f"Include/{version}/ucrt", sdk / f"Include/{version}/shared",
                                        sdk / f"Include/{version}/um"]))
    env["LIB"] = ";".join(map(str, [msvc / "lib/x64", sdk / f"Lib/{version}/ucrt/x64", sdk / f"Lib/{version}/um/x64"]))
    return compiler, env


def build_probe():
    """texconv_probe.exe from the Android sources; objects are reused while current."""
    compiler, env = msvc_env()
    objects = OUT / "obj"
    objects.mkdir(parents=True, exist_ok=True)
    astc = ["/DASTCENC_SSE=41", "/DASTCENC_POPCNT=1", "/DASTCENC_AVX=0", "/DASTCENC_NEON=0", "/DASTCENC_SVE=0", "/DASTCENC_F16C=0"]
    units = [(p, ["/std:c++17", "/EHsc", *astc]) for p in sorted((ROOT / "reference/astcenc/Source").glob("astcenc_*.cpp"))]
    units += [(ROOT / "reference/etcpak" / n, ["/std:c++17", "/EHsc", "/DBCDEC_STATIC", "/DBCDEC_IMPLEMENTATION"])
              for n in ("ProcessRGB.cpp", "Tables.cpp", "Dither.cpp", "Decode.cpp")]
    units += [(ROOT / "android/texconv/texconv.cpp", ["/std:c++17", "/EHsc", "/W4", "/WX", *astc]),
              (ROOT / "tests/texconv_probe.cpp", ["/std:c++17", "/EHsc", "/W4", "/WX", "/D_CRT_SECURE_NO_WARNINGS"])]
    headers = max(p.stat().st_mtime for p in [ROOT / "android/texconv/texconv.h", ROOT / "android/texconv/tvtx.h",
                                                *(ROOT / "reference/astcenc/Source").glob("*.h"), *(ROOT / "reference/etcpak").glob("*.hpp")])
    built = []
    for source, flags in units:
        obj = objects / (source.stem + ".obj")
        if not obj.exists() or obj.stat().st_mtime < max(source.stat().st_mtime, headers):
            result = subprocess.run([str(compiler), "/nologo", "/c", "/O2", "/MT", "/DNOMINMAX", "/D_CRT_SECURE_NO_WARNINGS", *flags,
                                     str(source), "/Fo" + str(obj)], env=env, text=True, capture_output=True)
            assert result.returncode == 0, result.stdout + result.stderr
        built.append(str(obj))
    exe = OUT / "texconv_probe.exe"
    result = subprocess.run([str(compiler), "/nologo", "/MT", *built, "/Fe" + str(exe)], env=env, text=True, capture_output=True,
                            cwd=objects)
    assert result.returncode == 0, result.stdout + result.stderr
    return exe


def run(exe, *args, expect=0):
    result = subprocess.run([str(exe), *map(str, args)], text=True, capture_output=True, timeout=3600)
    assert result.returncode == expect, f"{args}: {result.returncode}\n{result.stdout}\n{result.stderr}"
    return result.stdout


# ---------------------------------------------------------------- the key

def crc32c(data):
    table = []
    for i in range(256):
        v = i
        for _ in range(8):
            v = (v >> 1) ^ (0x82F63B78 & -(v & 1))
        table.append(v)
    crc = 0xFFFFFFFF
    for b in data:
        crc = (crc >> 8) ^ table[(crc ^ b) & 255]
    return crc ^ 0xFFFFFFFF


def key(data):
    return (crc32c(data) << 32) | zlib.crc32(data)


# ------------------------------------------------------------------ fixtures

def dds(width, height, fourcc, levels, blocks_for, cube=False):
    """A DDS whose levels' blocks come from blocks_for(fourcc, count, level)."""
    header = bytearray(128)
    header[0:4] = b"DDS "
    struct.pack_into("<IIIIIII", header, 4, 124, 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000 | (0x20000 if levels > 1 else 0),
                     height, width, 0, 0, levels)
    struct.pack_into("<II4s", header, 76, 32, 4, fourcc)
    struct.pack_into("<II", header, 108, 0x1000 | (0x400008 if levels > 1 else 0), 0xFE00 if cube else 0)
    payload = bytearray()
    for _ in range(6 if cube else 1):
        for level in range(levels):
            w, h = max(1, width >> level), max(1, height >> level)
            payload += blocks_for(fourcc, ((w + 3) // 4) * ((h + 3) // 4), level)
    return bytes(header + payload)


def colour_blocks(seed, transparent=False):
    def blocks(fourcc, count, level):
        out = bytearray()
        for i in range(count):
            c0 = (seed * 2654435761 + i * 40503 + level * 977) & 0xFFFF
            c1 = (c0 * 31 + 7) & 0xFFFF
            if fourcc == b"DXT1":
                if transparent and i % 3 == 0:
                    lo, hi = min(c0, c1), max(c0, c1)          # c0 <= c1: three colours and transparent
                    out += struct.pack("<HHI", lo, hi, 0xFFFFFFFF if i % 2 else 0x5555FFFF)
                else:
                    hi, lo = max(c0, c1) | 1, min(c0, c1) & ~1  # c0 > c1: four opaque colours
                    out += struct.pack("<HHI", hi, lo, (i * 0x9E3779B1) & 0xFFFFFFFF)
            else:
                if fourcc == b"DXT3":
                    alpha = struct.pack("<Q", 0xFFFFFFFFFFFFFFFF if not transparent else (i * 0x123456789ABCDEF) & (2 ** 64 - 1))
                else:
                    alpha = (b"\xff\xff" + b"\x00" * 6) if not transparent else bytes([200, 40]) + struct.pack("<Q", i * 77)[:6]
                hi, lo = max(c0, c1), min(c0, c1)
                out += alpha + struct.pack("<HHI", hi, lo, (i * 0x9E3779B1) & 0xFFFFFFFF)
        return bytes(out)
    return blocks


def argb_dds(width, height):
    header = bytearray(128)
    header[0:4] = b"DDS "
    struct.pack_into("<IIIIIII", header, 4, 124, 0x100F, height, width, width * 4, 0, 1)
    struct.pack_into("<IIIIIIII", header, 76, 32, 0x41, 0, 32, 0xFF0000, 0xFF00, 0xFF, 0xFF000000)
    return bytes(header) + bytes(width * height * 4)


def lp2c(files):
    """An LP2C container with the files in its root directory."""
    directory = bytearray(b"LP2C" + struct.pack("<II", 0, len(files)))
    entry_bytes = sum(1 + len(name) + 24 for name, _ in files)
    at = len(directory) + entry_bytes
    body = bytearray()
    for name, data in files:
        encoded = name.encode("latin1")
        directory += bytes([len(encoded)]) + encoded + struct.pack("<6I", len(data), 0, at + len(body), 0, 0, 0)
        body += data
    return bytes(directory + body)


def animation(frames):
    """The game's animated .tex: frame count, sizes, DDS files, then u32 milliseconds and u8 looped."""
    return (struct.pack("<I", len(frames)) + b"".join(struct.pack("<I", len(f)) for f in frames) + b"".join(frames)
            + struct.pack("<IB", 3000, 1))


class TexconvTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exe = build_probe()

    def fixture(self):
        temporary = tempfile.TemporaryDirectory(prefix="game-", dir=OUT)
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "data").mkdir()
        textures = {
            "opaque1.tex": dds(64, 32, b"DXT1", 7, colour_blocks(1)),
            "cutout1.tex": dds(32, 32, b"DXT1", 6, colour_blocks(2, transparent=True)),
            "opaque5.tex": dds(32, 64, b"DXT5", 7, colour_blocks(3)),
            "alpha5.tex": dds(16, 16, b"DXT5", 5, colour_blocks(4, transparent=True)),
            "alpha3.tex": dds(8, 8, b"DXT3", 1, colour_blocks(5, transparent=True)),
            "cube5.tex": dds(16, 16, b"DXT5", 5, colour_blocks(6), cube=True),
            "argb.tex": argb_dds(8, 8),
            "notes.xml": b"<x/>",
        }
        frames = [dds(8, 8, b"DXT5", 4, colour_blocks(10 + i, transparent=True)) for i in range(2)]
        frames.append(textures["opaque1.tex"])                       # the same content as a .tex: one entry
        files = list(textures.items()) + [("anim.tex", animation(frames))]
        (root / "data/Textures.vfs").write_bytes(lp2c(files))
        sources = [v for k, v in textures.items() if k.endswith(".tex") and v[84:88].startswith(b"DXT")] + frames
        return root, sources

    def pack(self, root):
        data = (root / "data/port-textures.tvt").read_bytes()
        magic, version, family, count, index_offset, payload, source_bytes, container, sources, skipped = \
            struct.unpack_from("<4sIII4QII", data, 0)
        self.assertEqual((magic, version), (b"TVTX", 1))
        self.assertEqual(index_offset + count * 32, len(data))
        entries = [struct.unpack_from("<QIIQII", data, index_offset + 32 * i) for i in range(count)]
        self.assertEqual(entries, sorted(entries, key=lambda e: (e[0], e[1])), "index sorted by key")
        return dict(family=family, count=count, sources=sources, skipped=skipped, container=container,
                    entries={(e[0], e[1]): e for e in entries})

    def test_key_matches_independent_crcs(self):
        sample = os.urandom(4099) + bytes(range(256)) * 3
        path = OUT / "key-sample.bin"
        path.write_bytes(sample)
        for n in (0, 1, 7, 8, 9, 63, 64, 1000, len(sample)):
            self.assertIn(f"key {key(sample[:n]):016x}", run(self.exe, "key", path, n))

    def test_convert_both_formats_replace_and_remove(self):
        root, sources = self.fixture()
        scan = run(self.exe, "scan", root)
        self.assertIn(f"scan textures {len(sources)} ", scan)
        self.assertIn("converted 0 0 0 current 0", scan)
        for family, number in (("etc2", 1), ("astc", 2)):
            run(self.exe, "convert", root, family, 3)
            pack = self.pack(root)
            self.assertEqual((pack["family"], pack["sources"], pack["skipped"]), (number, len(sources), 1))
            self.assertEqual(pack["count"], len(sources) - 1)
            self.assertEqual(pack["container"], (root / "data/Textures.vfs").stat().st_size)
            for source in sources:
                entry = pack["entries"][(key(source), len(source))]
                opaque = source in (sources[0], sources[2]) or source[84:88] == b"DXT5" and source is sources[5]
                if family == "etc2":
                    self.assertEqual(entry[2], TVTX_GL_ETC2_RGB8 if entry[5] & 1 else TVTX_GL_ETC2_RGBA8)
                else:
                    self.assertEqual(entry[2], TVTX_GL_ASTC_4x4)
                self.assertEqual(bool(entry[5] & 1), opaque, f"opaque flag of source {sources.index(source)}")
            dds_files = []
            for i, source in enumerate(sources):
                path = root / f"source{i}.dds"
                path.write_bytes(source)
                dds_files.append(path)
            # Random blocks are no picture: the floor here proves the levels' layout, the real
            # textures below their quality.
            self.assertIn("missing 0 bad 0", run(self.exe, "check", root, 12, *dds_files))
            self.assertIn(f"converted {number} {len(sources) - 1} ", run(self.exe, "scan", root))
            self.assertIn("current 1", run(self.exe, "scan", root))
        run(self.exe, "remove", root)
        self.assertFalse((root / "data/port-textures.tvt").exists())
        self.assertIn("converted 0 0 0", run(self.exe, "scan", root))

    def test_missing_container_fails_without_a_pack(self):
        temporary = tempfile.TemporaryDirectory(prefix="empty-", dir=OUT)
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "data").mkdir()
        self.assertIn("cannot open", run(self.exe, "convert", root, "etc2", expect=2))
        self.assertFalse(any((root / "data").iterdir()))

    @unittest.skipUnless((GAME_DATA / "Textures.vfs").is_file(), "the Russian game is not installed")
    def test_real_textures_quality(self):
        container = (GAME_DATA / "Textures.vfs").read_bytes()
        dirs, nfiles = struct.unpack_from("<II", container, 4)
        at, picked, kinds = 12, [], {}
        # The root's files, then a few of each DXT kind and size.
        for _ in range(nfiles):
            n = container[at]
            name = container[at + 1:at + 1 + n].decode("latin1")
            size, _, offset = struct.unpack_from("<III", container, at + 1 + n)
            at += 1 + n + 24
            head = container[offset:offset + 128]
            if not name.lower().endswith(".tex") or head[:4] != b"DDS " or not head[84:87] == b"DXT":
                continue
            width = struct.unpack_from("<I", head, 16)[0]
            kind = (head[84:88], min(width, 512))
            if kinds.get(kind, 0) < 2:
                kinds[kind] = kinds.get(kind, 0) + 1
                path = OUT / f"real-{len(picked)}.dds"
                path.write_bytes(container[offset:offset + size])
                picked.append(path)
            if len(picked) >= 16:
                break
        self.assertGreaterEqual(len(picked), 4)
        # Measured on 16 real textures: ETC2 (etcpak) 24..43 dB, ASTC 4x4 38..99 dB.
        for family, floor in (("etc2", 22.0), ("astc", 35.0)):
            out = run(self.exe, "quality", family, *picked)
            worst = float(out.rsplit("quality worst ", 1)[1].split()[0])
            self.assertGreaterEqual(worst, floor, out)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    unittest.main(verbosity=2)
