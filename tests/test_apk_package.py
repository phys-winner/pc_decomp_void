"""Check the full APK, its asset indices and lossless native-library stripping."""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
from xml.etree import ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_game_apk import OUT, TOOLS, run, sha256, xz_tool
from build_shader_cache import shaders


def elf(data):
    assert data[:6] == b"\x7fELF\x02\x01", "expected little-endian ELF64"
    assert struct.unpack_from("<H", data, 18)[0] == 183, "expected AArch64"
    shoff = struct.unpack_from("<Q", data, 40)[0]
    shsize, count, names = struct.unpack_from("<HHH", data, 58)
    headers = [struct.unpack_from("<IIQQQQIIQQ", data, shoff + i * shsize) for i in range(count)]
    table = headers[names]
    strings = data[table[4]:table[4] + table[5]]
    sections = {}
    for h in headers:
        name = strings[h[0]:].split(b"\0", 1)[0].decode()
        sections[name] = (h[1:4], h[5], b"" if h[1] == 8 else data[h[4]:h[4] + h[5]])
    phoff = struct.unpack_from("<Q", data, 32)[0]
    phsize, count = struct.unpack_from("<HH", data, 54)
    for i in range(count):
        p = struct.unpack_from("<IIQQQQQQ", data, phoff + i * phsize)
        if p[0] == 1:
            assert p[7] >= 16384 and p[2] % 16384 == p[3] % 16384, "LOAD alignment"
    return sections


def main():
    paths = [arg for arg in sys.argv[1:] if arg != "--no-publish"]
    assert len(paths) <= 1, "expected at most one APK path"
    path = Path(paths[0]) if paths else OUT / "the-void.apk"
    manifest = ET.parse(ROOT / "android/app/AndroidManifest.xml").getroot()
    ns = "{http://schemas.android.com/apk/res/android}"
    version, code = manifest.get(ns + "versionName"), manifest.get(ns + "versionCode")
    assert re.fullmatch(r"0\.\d+(?:\.\d+)?-dev", version), "development version format"
    assert re.fullmatch(r"[1-9]\d*", code), "positive Android version code"
    badging = run(TOOLS / "aapt2.exe", "dump", "badging", path).stdout
    assert f"versionCode='{code}'" in badging and f"versionName='{version}'" in badging
    assert "minSdkVersion:'26'" in badging
    run(TOOLS / "apksigner.bat", "verify", "--verbose", path)
    run(TOOLS / "zipalign.exe", "-c", "-P", "16", "4", path)
    with zipfile.ZipFile(path) as apk:
        assert apk.testzip() is None, "ZIP checksum failure"
        names = apk.namelist()
        assert len(names) == len(set(names)), "duplicate APK entries"
        assert apk.read("assets/licenses/GPL-3.0.txt") == (ROOT / "LICENSE").read_bytes()
        assert apk.read("assets/licenses/THIRD_PARTY_NOTICES.md") == (ROOT / "THIRD_PARTY_NOTICES.md").read_bytes()
        cached = {line.split()[0] for line in apk.read("assets/shadercache/index.txt").decode().splitlines() if line.strip()}
        for label, key, _ in shaders():
            assert key + ".bin" in cached, "missing required shader: " + label + " (" + key + ")"
        libraries = {"libvoid.so": "arm64", "libvoid_tension.so": "arm64-tension"}
        # lib/ holds the unpacker and the texture converter; the game libraries are xz streams in assets/native.
        assert {n for n in names if n.startswith("lib/")} == {"lib/arm64-v8a/libvoidxz.so", "lib/arm64-v8a/libtexconv.so"}
        unpacker = apk.read("lib/arm64-v8a/libvoidxz.so")
        dynstr = elf(unpacker)[".dynstr"][2]
        for symbol in (b"Java_org_thevoid_port_NativeLibrary_nativeUnpack\0",
                       b"Java_org_thevoid_port_NativeLibrary_nativeUnpacked\0"):
            assert symbol in dynstr, symbol
        dynstr = elf(apk.read("lib/arm64-v8a/libtexconv.so"))[".dynstr"][2]
        for method in ("Scan", "Convert", "Remove", "Cancel", "Progress", "Message"):
            symbol = b"Java_org_thevoid_port_Textures_native" + method.encode() + b"\0"
            assert symbol in dynstr, symbol
        for encoder in ("astcenc", "etcpak"):
            assert apk.read(f"assets/licenses/{encoder}.txt") == (ROOT / f"reference/{encoder}/LICENSE.txt").read_bytes(), encoder
        index, chunks = {}, {}
        for line in apk.read("assets/native/index.txt").decode().splitlines():
            name, size, digest, chunk, packed = line.split()
            index[name] = (int(size), digest)
            chunks[name] = (int(chunk), [int(s) for s in packed.split(",")])
        assert set(index) == set(libraries), "native index"
        assert {n for n in names if n.startswith("assets/native/")} == \
            {"assets/native/index.txt"} | {f"assets/native/{n}.xz" for n in libraries}
        for name, folder in libraries.items():
            info = apk.getinfo(f"assets/native/{name}.xz")
            assert info.compress_type == zipfile.ZIP_STORED, "the xz stream must be stored: " + name
            # Chunks of `chunk` bytes, one stream each, back to back (unpacked on all cores at once).
            chunk, packed = chunks[name]
            assert sum(packed) == info.file_size and len(packed) == -(-index[name][0] // chunk), "chunk table " + name
            # Decode each indexed stream independently, as the phone's workers do.
            payload, offset, decoded = apk.read(info.filename), 0, []
            for part, packed_size in enumerate(packed):
                data = subprocess.run([xz_tool(), "--decompress", "--stdout"],
                                      input=payload[offset:offset + packed_size], capture_output=True, check=True).stdout
                assert len(data) == min(chunk, index[name][0] - part * chunk), "chunk output " + name
                decoded.append(data)
                offset += packed_size
            unpacked = b"".join(decoded)
            assert (len(unpacked), hashlib.sha256(unpacked).hexdigest()) == index[name], "unpacked " + name
            original = elf((ROOT / "build" / folder / name).read_bytes())
            shipped = elf(unpacked)
            assert ".symtab" not in shipped and ".strtab" not in shipped, name
            assert not any(s.startswith(".debug") for s in shipped), name
            allocated = lambda sections: {n: s for n, s in sections.items() if s[0][1] & 2}
            assert allocated(original) == allocated(shipped), "stripping changed loadable sections: " + name
            tags = dict(struct.iter_unpack("<qQ", shipped[".dynamic"][2]))
            assert 0x60000011 in tags and 0x60000012 in tags, "missing Android packed RELA"
            assert not ({35, 36, 37, 0x6fffe000} & tags.keys()), "RELR needs a newer Android API"
        # The pregenerated shader variants: one sorted, deduplicated file (build_game_apk.shader_pack).
        pack = apk.read("assets/shaderpack.bin")
        size, digest = apk.read("assets/shaderpack.txt").decode().split()
        assert len(pack) == int(size) and hashlib.sha256(pack).hexdigest() == digest, "shader pack note"
        magic, pack_version, count, _ = struct.unpack_from("<4I", pack, 0)
        assert (magic, pack_version) == (0x4B505356, 1) and 16 + 24 * count <= len(pack), "shader pack header"
        source = {int(f.stem, 16): (f.suffix, f.read_bytes()) for f in (ROOT / "build/shadercache/pregen-results").glob("*")
                  if f.suffix in (".bin", ".err")} if (ROOT / "build/shadercache/pregen-results").is_dir() else {}
        assert count == len(source), ("shader pack entries", count, len(source))
        # A compile error names the compiling process's folder (<cwd>\memory(line,col)):
        # answers compiled elsewhere than the repository root may carry a user's folder.
        user_folder = b":\\Users\\"
        previous = -1
        for i in range(count):
            key, length, kind, offset = struct.unpack_from("<QIIQ", pack, 16 + 24 * i)
            assert key > previous and offset + length <= len(pack), ("shader pack entry", i)
            suffix, content = source[key]
            assert kind == (suffix == ".err") and pack[offset:offset + length] == content, ("shader pack content", hex(key))
            assert user_folder not in content, ("a user folder in a shader answer", hex(key))
            previous = key
        checked = 0
        for folder in ("lifted", "lifted-tension", "shadercache", "shaderwarm"):
            prefix = "assets/" + folder + "/"
            expected = {prefix + "index.txt"}
            for line in apk.read(prefix + "index.txt").decode().splitlines():
                name, size, digest, *alias = line.split()
                target = alias[0] if alias else name
                content = apk.read(prefix + target)
                assert len(content) == int(size) and hashlib.sha256(content).hexdigest() == digest, name
                assert folder != "shadercache" or user_folder not in content, ("a user folder in a shader answer", name)
                expected.add(prefix + target)
                checked += 1
            assert {n for n in names if n.startswith(prefix)} == expected, folder
        for file in (ROOT / "build/overrides").rglob("*"):
            if file.is_file():
                name = "assets/overrides/" + file.relative_to(ROOT / "build/overrides").as_posix()
                assert apk.read(name) == file.read_bytes(), name
        overrides = ROOT / "build/overrides"
        patches = json.loads((overrides / "index.json").read_text(encoding="utf-8"))
        expected = {"index.json"} | {row["file"] for row in patches}
        expected |= {p.relative_to(overrides).as_posix() for p in (overrides / "mobile-icons").rglob("*") if p.is_file()}
        assert {n.removeprefix("assets/overrides/") for n in names if n.startswith("assets/overrides/")} == expected, "stale override assets"
    published = ROOT / "pub" / f"the-void-{version}-{sha256(path)[:8]}.apk"
    if "--no-publish" not in sys.argv:
        assert published.is_file() and sha256(published) == sha256(path), "published APK differs"
    print(f"PASS: {version}/code{code}, signature, ZIP, 16 KB alignment, both libraries xz-packed and unpacked "
          f"byte-exact, the unpacker's JNI, {checked} indexed assets, overrides, SHA-256")


if __name__ == "__main__":
    main()
