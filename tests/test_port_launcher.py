"""Execute settings bytecode for both generations and the independent port UI language."""
import os
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_game_apk import ANDROID_JAR, JAVA_HOME, prepare_launcher
from gscript_binary import Module
from patch_options import TEXTS, patch_options
from patch_scripts import INDEXES, PATCHES, read_entry
from test_touch_native import VM


spec = json.loads((ROOT / "android/port.json").read_text(encoding="utf-8"))
editions = {d["id"]: d for d in spec["distributions"]}
assert all(d["intro"] == {"default": False} for d in editions.values())
assert editions["void"]["activity"] != editions["tension"]["activity"]
assert editions["void"]["theme"] == dict(zip(("primaryFill", "accentDark", "playGlow", "playParticles"),
    ("#3C2C0A", "#AA7D14", "#FFCD32", "#FFF0B0")))
assert editions["tension"]["theme"] == dict(zip(("primaryFill", "accentDark", "playGlow", "playParticles"),
    ("#321529", "#AC577B", "#E792B8", "#FFD4EB")))

count = 0
for index, edition in INDEXES.items():
    original = read_entry(index, "Scripts\\ui\\main_menu.bin")
    for language in TEXTS:
        module = Module(original, legacy=edition == "pl")
        info = patch_options(module, language)
        module = Module(module.encode(), legacy=module.legacy)
        rows = {r["offset"]: r for r in module.instructions()}
        assert len(info["contexts"]) == 3
        for row in rows.values():
            if row.get("opcode") in (54, 55, 56):
                assert row["operands"][0] in rows
            if row.get("opcode") in (63, 66, 67):
                assert rows[row["operands"][0]].get("header")
        for context in info["contexts"]:
            assert len(bytes.fromhex(module.contexts[context]["extra"])) == 12
        assert TEXTS[language]["tab"].encode("utf-16le") in module.pool
        for page, apply in enumerate(info["applies"]):
            for position in (0, 1):
                settings, labels, saved = {}, {}, []
                def control(name, *args):
                    if name == "getSliderValue": return float(position)
                    if name == "getCheckBoxState": return bool(position)
                    if name == "setLabelText": labels[args[0]] = args[1]; return None
                    raise AssertionError(name)
                VM(module, {11 if module.legacy else 17: {"call": control}},
                   {"Settings": settings, "saveSettings": lambda: saved.append(True)}).run(int(apply, 16))
                assert saved == [True]
                assert settings and all(k.startswith("Port") for k in settings)
                if page == 0:
                    assert settings["PortRenderScale"] == str(50 + 100 * position)
                    assert settings["PortReflections"] == str(position)
                elif page == 1:
                    assert settings["PortGyro"] == str(position)
                    assert settings["PortGyroInvertV"] == str(position)
                else:
                    assert settings["PortFOV"] == str(40 + 60 * position)
                count += 1
print(f"PASS: {count} executed options-page/slider cases across 2009 and Tension, four UI languages")

font_patch = next(p for name, p in PATCHES if name == "Scripts\\ui\\main_menu.bin")
for index, edition in INDEXES.items():
    raw = read_entry(index, "Scripts\\ui\\main_menu.bin")
    original = Module(raw, legacy=edition == "pl")
    module = Module(raw, legacy=original.legacy)
    info = font_patch(module, edition)
    original_rows = {r["offset"]: r for r in original.instructions()}
    for site in info["fixed_label_font_sites"]:
        row = original_rows[site]
        call = row["register"]
        def supported(regs, base):
            value = regs[base - 1]
            regs[base - 2] = max(8, value) if value <= 28 else 36
        for size in (-8, -18, -26, -40, -64, 8, 18, 26, 36):
            class Property:
                asFloat = 100.0
            _, regs = VM(module, named={"Settings": {"PortTextSize": Property()}},
                         calls={row["operands"][0]: supported}).run(site,
                             {call - 1: size, call - 3: "fontmain_"}, stops=(site + 8,))
            assert regs[call - 3] == ("portfont_" if size < 0 else "fontmain_")
            if size < 0: assert regs[call - 2] == min(28, max(8, -size))
for file in (ROOT / "build/overrides/port-fonts").glob("*.ft"):
    data = file.read_bytes()
    _, bitmap_height, count = struct.unpack_from("<3I", data)
    glyphs = [struct.unpack_from("<H4I", data, 12 + 18 * i) for i in range(count)]
    assert len(data) == 16 + 18 * count + bitmap_height * sum(glyph[1] for glyph in glyphs)
    needed = set("".join(value for texts in TEXTS.values() for value in texts.values()))
    assert needed <= {chr(glyph[0]) for glyph in glyphs}, (file, needed - {chr(glyph[0]) for glyph in glyphs})
print("PASS: both original label factories select complete Unicode port fonts; ordinary fonts remain unchanged")

out = ROOT / "build/port-launcher-test"
prepared = prepare_launcher(out / "launcher")
sources = sorted((ROOT / "android/app/src").rglob("*.java")) + [Path(p) for p in prepared["sources"]]
subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-encoding", "UTF-8", "-cp", str(ANDROID_JAR),
                "-d", str(out / "classes"), *map(str, sources), str(ROOT / "tests/PortLanguageTest.java")], check=True)
subprocess.run([str(JAVA_HOME / "bin/java.exe"), "-ea", "-cp", os.pathsep.join((str(out / "classes"), str(ANDROID_JAR))),
                "org.thevoid.port.PortLanguageTest"], check=True)
