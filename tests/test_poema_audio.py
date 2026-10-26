"""Original VFS case-collision oracle and byte-exact Uta mono alias repair."""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "tests")]
from patch_poema_audio import ALIAS, SCENE, poema_overrides
from test_memmove import compiler_environment
from test_touch_controls import method
from build_game_apk import JAVA_HOME


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    out = ROOT / "build/audio-workers-test/poema"
    out.mkdir(parents=True, exist_ok=True)
    archives = []
    shared = {}
    for language in ("", ".english", ".german", ".polish"):
        index_path = "research/vfs-index" + language + ".json"
        index = json.loads((ROOT / index_path).read_text())
        container = next(c for c in index["containers"] if c["name"] == "Sounds.vfs")
        source = Path(index["source"])
        if not source.is_absolute():
            source = ROOT / source
        archive = source / "Sounds.vfs"
        assert archive.stat().st_size == container["size"]
        archives.append(archive)
        assets = poema_overrides(index_path)
        assert len(assets) == 3
        name, original_name, original, patched = assets[0]
        assert name == original_name == SCENE
        assert patched.replace(ALIAS.encode(), b"poema") == original
        sounds = ET.fromstring(patched).findall(".//property[@name='Sound']")
        assert sum(p.get("value") == ALIAS for p in sounds) == 1
        assert all(p.get("value") != "poema" for p in sounds)
        for rate, (name, original_name, original, patched) in zip((22, 44), assets[1:]):
            assert name == "Sounds\\%s#%d.ogg" % (ALIAS, rate)
            assert original_name == "Sounds\\poema#%d.ogg" % rate
            assert patched == original and original.startswith(b"OggS")
            packet = original.index(b"\x01vorbis")
            assert original[packet + 11] == 1
            if language != ".polish":
                assert struct.unpack_from("<I", original, packet + 12)[0] == {22: 22050, 44: 44100}[rate]
                previous = shared.setdefault(rate, sha(original))
                assert sha(original) == previous, "EN/RU/DE must reuse the same original mono data"
        # Alias generation reads the original entry; it must not replace the
        # distinct localized capital-P intro asset or alter its archive bytes.
        intro = next((e for e in container["entries"] if e["name"] == "Sounds\\Poema#44.ogg"), None)
        if intro:
            with archive.open("rb") as f:
                f.seek(intro["offset"])
                data = f.read(intro["size"])
            packet = data.index(b"\x01vorbis")
            assert data[packet + 11] == 2
            assert all(name != intro["name"] for name, _, _, _ in assets)
        print(index_path + ": one scene property, original mono alias bytes, intro preserved PASS")

    # The deployed problem reproduces in the unmodified original Windows DLL:
    # both English spellings select the stereo intro before any port codec runs.
    dll = ROOT / "research/ida/VFS.dll"
    assert sha(dll.read_bytes()) == "93d03784e761f64f27d7f6ca4198942f0efe68fa5b758922aeefd5f4f3904f8a"
    compiler, env, _ = compiler_environment()
    native = out / "vfs-case-probe.exe"
    built = subprocess.run([str(compiler), "/nologo", "/O2", "/Oy-", "/W3", "/std:c++17",
                            str(ROOT / "tests/vfs_case_probe.cpp"), "/Fo" + str(out / "vfs-case-probe.obj"),
                            "/Fe" + str(native), "/link", "/MACHINE:X86", "/NXCOMPAT"],
                           env=env, capture_output=True, text=True)
    (out / "native-build.log").write_text(built.stdout + built.stderr)
    assert built.returncode == 0, built.stdout + built.stderr
    checked = subprocess.run([str(native), str(dll), str(archives[1].with_suffix(""))],
                             capture_output=True, text=True, timeout=30)
    (out / "native-oracle.log").write_text(checked.stdout + checked.stderr)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    matches = re.findall(r"name=(\S+) .*?magic=OggS channels=(\d+) rate=(\d+)", checked.stdout)
    assert matches == [("poema#44.ogg", "2", "44100"), ("Poema#44.ogg", "2", "44100"),
                       ("poema#22.ogg", "2", "22050"), ("Poema#22.ogg", "2", "22050")]
    print("original Windows VFS: English case collision reproduces without host codec PASS")

    # Execute the production Java directory reader and exact-first source
    # selection against actual English/German archives with opposite entry order.
    source = (ROOT / "android/app/src/org/thevoid/port/ScriptOverrides.java").read_text()
    helpers = "\n".join(method(source, signature) for signature in (
        "static long[] entry(", "static Map<String, long[]> directory(", "private static void level(",
        "private static String name(", "private static int le("))
    probe = out / "PoemaSourceProbe.java"
    probe.write_text('''import java.io.*;
import java.util.*;
public class PoemaSourceProbe {
''' + helpers + '''
    public static void main(String[] args) throws Exception {
        for (String arg : args) {
            File vfs = new File(arg);
            Map<String,long[]> dir = directory(vfs, "sounds");
            long[] mono = entry(dir, "sounds\\\\poema#44.ogg");
            long[] stereo = entry(dir, "sounds\\\\Poema#44.ogg");
            assert mono != null && stereo != null && mono[0] != stereo[0];
            assert entry(dir, "SOUNDS\\\\POEMA#44.OGG") != null;
            try (RandomAccessFile f = new RandomAccessFile(vfs, "r")) {
                f.seek(mono[0] + 39); assert f.readUnsignedByte() == 1;
                f.seek(stereo[0] + 39); assert f.readUnsignedByte() == 2;
            }
        }
        System.out.println("actual Java directory: exact mono/stereo spelling and legacy fallback PASS");
    }
}
''')
    subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-d", str(out), str(probe)], check=True)
    subprocess.run([str(JAVA_HOME / "bin/java.exe"), "-ea", "-cp", str(out), "PoemaSourceProbe",
                    str(archives[1]), str(archives[2])], check=True)


if __name__ == "__main__":
    main()
