"""Run both menu scale setters and check real bitmap text on narrow displays."""
from pathlib import Path
import math
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from gscript_binary import Module
from patch_options import Asm, DESIGN_WIDTH, LEFT_X, RIGHT_X, Slider, TEXTS, function, menu_scale_slot, pages, patch_options
from patch_scripts import read_entry
from test_touch_native import VM

fonts = {}


def metrics(size):
    if size not in fonts:
        data = read_entry('research/vfs-index.json', f'Textures\\Fonts\\fontmain_{size}.ft')
        height, _, count = struct.unpack_from('<3I', data)
        glyphs = {chr(struct.unpack_from('<H', data, 12 + 18 * i)[0]):
                  struct.unpack_from('<4i', data, 14 + 18 * i) for i in range(count)}
        fonts[size] = height, glyphs
    return fonts[size]


cases = 0
for index, legacy in (('research/vfs-index.json', False), ('research/vfs-index.polish.json', True)):
    raw = read_entry(index, 'Scripts\\ui\\main_menu.bin')
    original, module = Module(raw, legacy=legacy), Module(raw, legacy=legacy)
    info = patch_options(module, 'pl' if legacy else 'en')
    slot = menu_scale_slot(original)
    for height in (360, 450, 540, 771, 1080, 1542):
        for aspect in (4 / 3, 1680 / 1264, 16 / 10, 16 / 9, 20 / 9):
            width = round(height * aspect)
            proposed = height / 1200
            expected = min(proposed, width / DESIGN_WIDTH)
            for site in map(lambda value: int(value, 16), info['viewport_scale_sites']):
                vm = VM(module, named={'Width': width})
                vm.run(site, {0: proposed}, stops=(site + 8,))
                scale = vm.globals[slot]
                assert math.isclose(scale, expected, rel_tol=1e-7), (legacy, width, height, scale)
                assert LEFT_X * scale >= -width / 2
                assert (RIGHT_X + 900) * scale <= width / 2 + 1e-4
                before = VM(original)
                before.run(site, {0: proposed}, stops=(site + 8,))
                assert before.globals[slot] == proposed
                if aspect < 1.4:
                    assert LEFT_X * before.globals[slot] < -width / 2, 'old-code negative control'
                cases += 1
            for lang, texts in TEXTS.items():
                for page in pages(texts):
                    for side, column in enumerate(page):
                        for position, row in enumerate(column):
                            title = isinstance(row, Slider)
                            text = row.title if title else row.caption
                            px = min(28, max(8, int((40 if title else 26) * scale)))
                            line_height, glyphs = metrics(px)
                            x = (LEFT_X if side == 0 else RIGHT_X) + (0 if title else 184 if side == 0 else 224)
                            right = RIGHT_X * scale if side == 0 else width / 2
                            for line in text.splitlines():
                                advance = ink_width = 0
                                for char in line:
                                    ink, _, _, step = glyphs[char]
                                    ink_width = max(ink_width, advance + ink)
                                    advance += step
                                assert x * scale >= -width / 2
                                assert x * scale + ink_width + 4 <= right + 1e-4, (lang, height, aspect, text)
                            if not title and position < len(column) - 1:
                                pitch = 100 if len(column) > 5 else 120
                                assert (len(text.splitlines()) - 1) * 50 * scale + line_height <= pitch * scale + 1e-4, (lang, height, text)

    emitted = []
    a = Asm(module, 12)
    assert a.label_text('first\nsecond\nthird', 100, 200, 2) == 3
    a.emit(65)
    entry = function(module, a, 12)
    VM(module, {11 if legacy else 17: {'call': lambda *args: emitted.append(args)}},
       {'!vec2': lambda *args: args}).run(entry)
    assert emitted == [('createLabel', line, (100, y), 0, -26)
                       for line, y in zip(('first', 'second', 'third'), (200, 150, 100))]

print(f'PASS: {cases} actual scale setters, both editions, old-code negative control; four-language bitmap bounds and row spacing')
