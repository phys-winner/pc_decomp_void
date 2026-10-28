"""Validate the original VM's three options pages and both navigation directions."""
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from gscript_binary import Module
from patch_options import ARROW, Check, Slider, Sites, TEXTS, arrow_position, function, pages, patch_options
from patch_scripts import INDEXES, arrow_mask, dds_rgba, enlarged, read_entry
from PIL import Image


def arrow_clearance(original, instructions, index):
    """Execute the viewport-dependent positions and check the real masks."""
    from patch_native_menu import Assembler
    from test_touch_native import VM
    for side, rotation in enumerate((90, -90)):
        module = Module(original.encode())
        assembly = Assembler(module, 10)
        arrow_position(assembly, side)
        assembly.emit(65)
        start = function(module, assembly, 10)
        for aspect in (16 / 9, 20 / 9, 21 / 9):
            _, registers = VM(module, named={'Width': 1200 * aspect, 'Height': 1200,
                                             '!vec2': lambda x, y: (x, y)}).run(start)
            x, y = registers[4]
            half_width = 600 * aspect
            assert abs((x if side == 0 else half_width - x - ARROW['width'])
                       - (-half_width + ARROW['inset'] if side == 0 else ARROW['inset'])) < 1e-6
            assert y == ARROW['width'] / 2
            for suffix in ('', '_mask'):
                transform = arrow_mask if suffix else enlarged
                data, _ = transform(read_entry(index, 'Textures\\ui\\diary_quest_arrow_up' + suffix + '.tex'), 2, rotation)
                width, height, pixels = dds_rgba(data)
                if suffix:
                    # RegionMask samples normalized coordinates over the image's whole rectangle.
                    assert pixels == b'\xff' * (width * height * 4), 'arrow padding and centre must accept taps'
                bbox = Image.frombytes('RGBA', (width, height), pixels).getchannel('A').getbbox()
                scale = ARROW['width'] / width
                assert -half_width <= x + bbox[0] * scale <= x + bbox[2] * scale <= half_width
                assert -600 <= -y + bbox[1] * scale <= -y + bbox[3] * scale <= 600
    # The constructors must use the dynamic position rather than fixed 16:9 offsets.
    for i, row in enumerate(instructions):
        if row.get('text') not in ('ui/port_arrow_left', 'ui/port_arrow_right'): continue
        assert [r.get('symbol') for r in instructions[i + 1:i + 6] if r.get('symbol')] == ['!vec2', 'Width', 'Height']

for index, lang in INDEXES.items():
    if lang == "pl": continue  # the early release uses the Java settings panel
    raw = read_entry(index, "Scripts\\ui\\main_menu.bin")
    original = Module(raw)
    module = Module(raw)
    result = patch_options(module, lang)
    decoded = Module(module.encode())
    instructions = list(decoded.instructions())
    rows = {row["offset"]: row for row in instructions}
    assert decoded.contexts[:len(original.contexts)] == original.contexts
    assert decoded.pool[:len(original.pool)] == original.pool
    assert decoded.debug == original.debug
    assert len(result["contexts"]) == 3
    for row in instructions:
        opcode = row.get("opcode")
        if opcode in (54, 55, 56):
            assert row["operands"][0] in rows, row
        if opcode in (63, 66, 67):
            assert rows[row["operands"][0]].get("header"), row
    for i, click in enumerate(result["clicks"]):
        start = int(click, 16)
        block = [r for r in instructions if r["offset"] > start]
        end = next(r["offset"] for r in block if r.get("opcode") == 65)
        transitions = [(r["register"], r["operands"][0]) for r in block if r["offset"] < end and r.get("opcode") == 67]
        assert transitions == [(result["contexts"][(i - 1) % 3], int(result["constructors"][(i - 1) % 3], 16)),
                               (result["contexts"][(i + 1) % 3], int(result["constructors"][(i + 1) % 3], 16))], transitions
    specs = pages(TEXTS[lang])
    settings = {row.key: row for page in specs for column in page for row in column}
    assert not {"PortSkipIntro", "PortRunEdge", "PortTapTurn"}.intersection(settings)
    assert settings["PortHDR"].values == [0, 1, 2]
    assert settings["PortLightmapQuality"].values == [2, 1, 0]
    for key, expected in {"PortRenderScale": 100, "PortHDR": 2, "PortLightmapQuality": 0,
                          "PortAnisotropy": 4, "PortTextureQuality": True}.items():
        assert settings[key].default == expected, (key, settings[key].default)
    assert settings["PortDebugCommands"].default is False
    assert settings["PortTouchAdaptations"].default is True
    assert settings["PortShowMenuButton"].default is True
    assert settings["PortShowMenuLabels"].default is True
    assert settings["PortShowActionButton"].default is False
    assert (settings["PortFOV"].default, settings["PortFOV"].lo, settings["PortFOV"].hi) == (55, 40, 100)
    assert (settings["PortVeinBrightness"].default, settings["PortVeinBrightness"].lo,
            settings["PortVeinBrightness"].hi) == (100, 100, 500)
    for i in range(3):
        assert sum(r.get("text") == f"{i + 1} / 3" for r in instructions) == 1
    assert sum(r.get("text") == "ui/port_arrow_left" for r in instructions) == 3
    assert sum(r.get("text") == "ui/port_arrow_right" for r in instructions) == 3
    arrow_clearance(original, instructions, index)
    print(f"{lang}: 3 pages, 6 navigation transitions, settings/defaults, bytecode targets and original data PASS")

# Keep the Java/VM keys and localized text offsets aligned without needing Android.
source = (ROOT / "android/app/src/org/thevoid/port/Settings.java").read_text(encoding="utf-8")
for key in ("PortFOV", "PortVeinBrightness", "PortDebugCommands", "PortTouchAdaptations", "PortShowMenuButton", "PortShowMenuLabels", "PortShowActionButton"):
    assert source.count('"' + key + '"') == 2, key
for getter, key, value in [("getFloat", "renderScale", "1.0f"),
                           ("getInt", "anisotropy", "4"), ("getInt", "textureQuality", "0"),
                           ("getInt", "soundRate", "44")]:
    assert f'prefs.{getter}("{key}", {value})' in source, key
assert settings["PortSoundRate"].default is True
assert settings["PortSoundRate"].on == "44"
assert "Float.isNaN(value) || Float.isInfinite(value)" in source
assert 'readF(xml, "PortVeinBrightness", veinBrightness * 100, 100, 500)' in source
for key in ("PortSubtitleSize", "PortTextSize", "PortTextContrast"):
    assert source.count('"' + key + '"') == 2, key
for key in ("PortSubtitleSize", "PortTextSize"):
    assert (settings[key].default, settings[key].lo, settings[key].hi, settings[key].step) == (100, 100, 150, 10)
assert settings['PortTextContrast'].default is True

# The native bridge previously emitted decimal strings for integer-looking
# settings. Exercise the exact constructor seam with properties that reject
# asInt("55.0000"), as the real game does, rather than inspecting its opcodes.
from patch_options import Asm, function, slider_value
from test_touch_native import VM


class NumericProperty:
    def __init__(self, text): self.text = text

    @property
    def asFloat(self): return float(self.text)

    @property
    def asInt(self): return int(self.text)


specs = pages(TEXTS['ru'])
for column in specs[2]:
    for row in column:
        if not isinstance(row, Slider): continue
        for value in (row.lo, row.default, row.hi):
            for text in (str(value), '%.4f' % value):
                module = Module(read_entry('research/vfs-index.json', 'Scripts\\ui\\main_menu.bin'))
                assembly = Asm(module, 8)
                slider_value(assembly, row, 'decimal')
                assembly.emit(65)
                start = function(module, assembly, 8)
                vm = VM(module, named={'Settings': {row.key: NumericProperty(text)}})
                _, registers = vm.run(start)
                assert abs(registers[4] - (value - row.lo) / (row.hi - row.lo)) < 1e-6
print('FOV/vein native slider constructors accept integer and decimal property values PASS')
