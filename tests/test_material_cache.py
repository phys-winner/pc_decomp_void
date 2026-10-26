"""Source-pinned SM3 choices; real production copy/migration fixtures."""
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_android import CLANG
from build_x86_incremental import compiler_environment
from material_cache_manifest import manifest, selected, OMITTED
from test_touch_native import function


data = manifest()
assert json.loads((ROOT / "research/material-cache-fixed-high.json").read_text()) == data
assert data["releases"][0]["files"] == data["releases"][1]["files"], "same original cache payload for both games"
for release in data["releases"]:
    assert (release["bytes_original"], release["bytes_seeded"], release["bytes_omitted"]) == (90242550, 56439744, 33802806)
    omitted = {f["name"] for f in release["files"] if not f["seed"]}
    assert omitted == OMITTED and len(omitted) == 12
    assert {f["name"] for f in release["files"] if f["seed"]} == {
        "effects30.dat", "effects30.hdr", "effects30h.dat", "effects30h.hdr", "custom.dat", "custom.hdr",
        "vs1_1.db", "vs2_0.db", "vs3_0.db", "ps2_0.db", "ps3_0.db"}

device = (ROOT / "android/host/d3d9_device.c").read_text()
caps = bytes.fromhex("".join(re.findall(r'"([0-9A-F]+)"', device.split("pc_caps_hex[] =", 1)[1].split(";", 1)[0])))
assert struct.unpack_from("<I", caps, 0xc4)[0] == 0xfffe0300
assert struct.unpack_from("<I", caps, 0xcc)[0] == 0xffff0300
profile = (ROOT / "android/app/src/org/thevoid/port/Profile.java").read_text(encoding="utf-8")
assert '<HDR />' in profile and '<Profile force=' in profile

out = ROOT / "build/material-cache-test" / str(uuid.uuid4())
out.mkdir(parents=True)
source, fresh, old, retry, read_retry = (out / name for name in ("source", "fresh", "old", "retry", "read-retry"))
all_files = {f["name"]: ("original:" + f["name"]).encode() for f in data["releases"][0]["files"]}
all_files.update({"effects20.dat.backup": b"keep-backup", "effects40.dat": b"keep-unknown", "readme.txt": b"keep-sidecar"})
for directory in (source / "Cache", old, retry, read_retry):
    directory.mkdir(parents=True)
    for name, payload in all_files.items():
        (directory / name).write_bytes(payload)
(source / "settings.xml").write_bytes(b"do-not-change-settings")
(source / "Save01.sav").write_bytes(b"do-not-change-save")
# The filter applies to the original Cache directory, not arbitrary same-named
# files elsewhere in the copied profile tree.
(source / "other").mkdir()
(source / "other/effects20.dat").write_bytes(b"not-a-material-cache")
main = (ROOT / "android/host/main.c").read_text(encoding="utf-8")
probe = (ROOT / "tests/material_cache_probe.c").read_text()
probe = probe.replace("/* __PRODUCTION_FUNCTIONS__ */", "\n".join(function(main, name) for name in
                      ("seed_cache_file", "copy_tree", "prune_legacy_material_cache")))
selectors = []
for year, directory, family, plain in (("2009", "generated/renderer-x86", "sub_16084BF0", "sub_16084C10"),
                                        ("2008", "generated/tension/renderer-x86", "sub_160849A0", "sub_160849C0")):
    original = (ROOT / directory / "renderer_0048.c").read_text()
    selectors += [function(original, family).replace(family, "selector_" + year),
                  function(original, plain).replace(plain, "plain_" + year)]
    profile_name = "sub_16180CC0" if year == "2009" else "sub_16180820"
    selectors.append(function((ROOT / directory / "renderer_0130.c").read_text(), profile_name).replace(profile_name, "profile_" + year))
probe = probe.replace("/* __SELECTOR_FUNCTIONS__ */", "\n".join(selectors))
path = out / "probe.c"
path.write_text(probe)
_, env, _ = compiler_environment()
env["LIB"] = env["LIB"].replace("\\x86", "\\x64").replace("/x86", "/x64")
binary = out / "probe.exe"
subprocess.run([str(CLANG), "--target=x86_64-pc-windows-msvc", "-fuse-ld=link", "-O2", "-std=c11",
                str(path), "-o", str(binary)], env=env, check=True)
result = subprocess.check_output([str(binary), *map(lambda p: p.as_posix(), (source, fresh, old, retry, read_retry))], text=True)
import pefile
images = {year: pefile.PE(str(ROOT / file)).get_memory_mapped_image() for year, file in
          (("2009", "generated/input/RendererD3D.dll"), ("2008", "generated/tension/input/RendererD3D.dll"))}
for line in result.splitlines():
    if not re.fullmatch(r"(?:plain|profile)?200[89] [012] [0-9a-f]{8}", line):
        continue
    name, hdr, address = line.split()
    image = images[name[-4:]]
    at = int(address, 16) - 0x16000000
    text = image[at:image.index(0, at)].decode("ascii")
    expected = ("fx_3_0", "fx_3_0hs", "fx_3_0hf")[int(hdr)] if name.startswith("profile") else "30h" if not name.startswith("plain") and int(hdr) else "30"
    assert text == expected, line
for directory in (fresh / "Cache", old, retry, read_retry):
    for name, payload in all_files.items():
        target = directory / name
        assert target.exists() == selected(name), target
        if target.exists(): assert target.read_bytes() == payload
assert (fresh / "settings.xml").read_bytes() == b"do-not-change-settings"
assert (fresh / "Save01.sav").read_bytes() == b"do-not-change-save"
assert (fresh / "other/effects20.dat").read_bytes() == b"not-a-material-cache"
print(result.strip())
print("both original renderer selectors + SM3 caps; 33,802,806-byte material-cache reduction; originals unchanged PASS")
