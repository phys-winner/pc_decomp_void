"""Execute the release's patched Use, font and tooltip seams in the bounded VM."""
import hashlib
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from gscript_binary import Module
from patch_scripts import INDEXES, PATCHES, NEW_IMAGES, dds_argb, read_entry
from patch_readability import patch_fonts, patch_backplate, patch_use_distance, rows, frame_at
from patch_touch_native import method
from test_touch_native import VM


class Property:
    def __init__(self, value): self.value = value
    @property
    def asFloat(self): return float(self.value)
    @property
    def asBool(self): return bool(self.value)


class Entity:
    def __init__(self, distance): self.distance = distance
    def callDef(self, default, method):
        assert method == 'getUseDistance'
        return self.distance if self.distance is not None else default


def distance_boundaries(index, lang):
    module = Module(read_entry(index, 'Scripts\\player.bin'))
    original = {r['offset']: r for r in rows(module)}
    info = patch_use_distance(module, lang)
    assert len(info['use_distance_filters']) == 3
    for site in info['use_distance_filters']:
        result_reg = original[site]['register']
        original_range = original[site - 24]['operands'][0]
        assert original_range in (3, 5)
        for entity in (Entity(3), Entity(None), object()):
            for distance in (0, 2.9999, 3, 3.0001, 4.9999, 5, 5.0001):
                for hit in (False, True):
                    ray = (hit and distance <= 5, distance, entity)
                    called = []
                    def trace(*args):
                        called.append(args)
                        return ray
                    vm = VM(module, named={'!tuple': lambda *args: tuple(args)})
                    _, regs = vm.run(site, {result_reg + 1: trace}, stops=(site + 8,))
                    limit = 3 if isinstance(entity, Entity) and entity.distance == 3 else original_range
                    assert bool(regs[result_reg][0]) == (hit and distance <= limit), (lang, site, entity, distance)
                    assert len(called) == 1
        # Rejected/no-entity hits never invoke the optional script method.
        vm = VM(module, named={'!tuple': lambda *args: tuple(args)})
        _, regs = vm.run(site, {result_reg + 1: lambda *args: (False, 0, None)}, stops=(site + 8,))
        assert regs[result_reg] == (False, 0, None)


def font_sizes(index, lang):
    for name in ('body_wheel', 'paint_limfa', 'subtitle', 'video', 'database', 'main_menu'):
        raw = read_entry(index, 'Scripts\\ui\\' + name + '.bin')
        module = Module(raw)
        original = {r['offset']: r for r in rows(module)}
        info = patch_fonts(module, lang, name in ('subtitle', 'video'))
        for site in info['readable_font_sites']:
            row = original[site]
            # Execute literals and numeric->string seams, including their
            # unmodified string concatenation instruction after each hook.
            if row['opcode'] not in (3, 16, 20, 63): continue
            for text_percent, subtitle_percent in ((100, 100), (150, 100), (100, 150), (150, 150)):
                settings = {'PortTextSize': Property(text_percent), 'PortSubtitleSize': Property(subtitle_percent)}
                vm = VM(module, named={'Settings': settings})
                if row['opcode'] == 3:
                    _, regs = vm.run(site, stops=(site + 12,))
                    size = int(row['text'].split('_')[1].split('.')[0])
                    target = round(size * text_percent / 100)
                    assert regs[row['register']] == 'fontmain_%d.ft' % (36 if target > 28 else max(8, target))
                elif row['opcode'] == 20:
                    prefix = row['register'] - 1
                    owner = frame_at(module, site)['offset']
                    is_subtitle = name in ('subtitle', 'video') and any(
                        m['code_offset'] == owner and m['name'] == 'loadDialogueFont'
                        for c in module.contexts for m in c['methods'])
                    _, regs = vm.run(site, {prefix: 'fontmain_', row['register']: 16}, stops=(site + 8,))
                    percent = subtitle_percent if is_subtitle else text_percent
                    assert regs[prefix] == 'fontmain_%d' % round(16 * percent / 100)
                elif row['opcode'] == 63:
                    # Port labels bypass text scaling before the original
                    # supported-size clamp; ordinary labels still scale once.
                    helper_calls = []
                    def supported_label_size(regs, base):
                        helper_calls.append(regs[base - 1])
                        _, result = VM(module).run(row['operands'][0], {-4: regs[base - 1]})
                        regs[base - 2] = result[-5]
                    vm.calls[row['operands'][0]] = supported_label_size
                    for source, expected in ((-7, 8), (-11, 11), (-18, 18), (-54, 28),
                                             (16, round(16 * text_percent / 100))):
                        before = len(helper_calls)
                        _, regs = vm.run(site, {row['register'] - 1: source}, stops=(site + 8,))
                        assert regs[row['register'] - 2] == expected
                        assert len(helper_calls) == before + 1
                else:
                    # Run the original supported-size helper with its real
                    # CALL input/output window, then resume the appended seam.
                    call = original[site + 4]
                    assert call['opcode'] == 63
                    def supported_size(regs, base):
                        _, result = VM(module).run(call['operands'][0], {-4: regs[base - 1]})
                        regs[base - 2] = result[-5]
                    vm.calls[call['operands'][0]] = supported_size
                    _, regs = vm.run(site, {row['register']: 16}, stops=(site + 12,))
                    assert regs[row['register']] == round(16 * subtitle_percent / 100)


def backplates(index, lang):
    for name in ('paint_limfa', 'body_free_limfa', 'body_active_limfa', 'body_wheel'):
        module = Module(read_entry(index, 'Scripts\\ui\\' + name + '.bin'), legacy=lang == 'pl')
        original = {r['offset']: r for r in rows(module)}
        info = patch_backplate(module, lang)
        site = info['text_backplate']
        draws, loads = [], []
        class Window:
            def drawImageAlphaScaled(self, *args): draws.append(args)
            def drawString(self, *args): pass
            def drawStringAlpha(self, *args): pass
        class Plane:
            def loadImage(self, name):
                loads.append(name)
                assert name == 'ui/port_text_backplate'
                return 'dark image'
        receiver = original[site]['register'] + 1
        # These are the original prepare() result fields, not the patch's claimed dimensions.
        size_field = {'paint_limfa': 13, 'body_free_limfa': 14, 'body_active_limfa': 14, 'body_wheel': 17}[name]
        globals = {i: object() for i in range(len(module.types))}
        globals[size_field] = (150, 60)
        globals[info['backplate_image']] = None
        vm = VM(module, globals=globals,
                named={'Settings': {'PortTextContrast': Property(False)}, 'Plane': Plane()})
        regs = {receiver: Window(), -5: 100, -4: 200}
        vm.run(site, regs, stops=(site + 8,))
        assert not draws and not loads
        vm.named['Settings']['PortTextContrast'] = Property(True)
        for _ in range(2): vm.run(site, regs, stops=(site + 8,))
        assert loads == ['ui/port_text_backplate']
        assert len(draws) == 2
        assert draws[0][:5] == ('dark image', 96, 196, 158, 68), draws
        assert abs(draws[0][5] - .82) < .00001
        assert regs[-5] == 100 and regs[-4] == 200


def full_overrides(index, lang):
    # Preserve the original pool/debug; validate every branch target after
    # composing readability with existing touch and game-menu patches.
    for name, patch in PATCHES:
        raw = read_entry(index, name)
        if raw is None: continue
        module = Module(raw)
        original = bytes(module.code)
        patch_info = patch(module, lang)
        decoded = Module(module.encode())
        assert decoded.pool[:len(Module(raw).pool)] == Module(raw).pool
        assert decoded.debug == Module(raw).debug
        allowed = {int(site, 16) + n for site in patch_info['sites'] for n in range(16)}
        assert all(decoded.code[i] == value or i in allowed for i, value in enumerate(original))
        targets = {r['offset']: r for r in decoded.instructions()}
        for row in targets.values():
            if row.get('opcode') in (54, 55, 56): assert row['operands'][0] in targets, row
            if row.get('opcode') in (63, 66, 67): assert targets[row['operands'][0]].get('header'), row


def stats_lines(index, lang):
    raw = read_entry(index, 'Scripts\\ui\\body_wheel.bin')
    module = Module(raw)
    start = method(module, 'updateTooltip')
    prepare = next(r['offset'] - 8 for r in rows(module)
                   if r['offset'] > start and r.get('symbol') == 'prepare')
    patch = next(p for name, p in PATCHES if name == 'Scripts\\ui\\body_wheel.bin')
    patch(module, lang)
    values = {i: [i * 100, 1000 if i else 0] for i in range(7)}
    vm = VM(module, {13: values, 16: True, 19: {i: 'effect' + str(i) for i in range(7)}},
            {'isKeyPressed': lambda key: True,
             'format': lambda fmt, *args: fmt.replace('%u', '%d') % args})
    end, regs = vm.run(start, stops=(prepare,))
    assert end == prepare
    expected = ['effect%d : %d%%' % (i, i * 10) for i in range(7)]
    assert regs[0] == '\n'.join(expected)
    # Native prepare includes a blank line after a trailing newline. The
    # release's real 24px font (16px at 150%) fits seven rows in this canvas;
    # the German font's eighth blank row would incorrectly measure 352px.
    font = read_entry(index, 'Textures\\Fonts\\fontmain_24.ft')
    line_height = struct.unpack_from('<I', font)[0]
    assert (regs[0].count('\n') + 1) * line_height <= 320


def fixed_port_labels(index, lang):
    from patch_options import Asm, function, Slider, pages, TEXTS
    raw = read_entry(index, 'Scripts\\ui\\main_menu.bin')
    original = Module(raw)
    module = Module(raw)
    patch = next(p for name, p in PATCHES if name == 'Scripts\\ui\\main_menu.bin')
    patch(module, lang)
    methods = {m['name']: m['code_offset'] for c in original.contexts for m in c['methods']
               if (m['name'], m['args']) in (('createLabel', 4), ('setLabelText', 2))}
    create = methods['createLabel']
    body = [r for r in rows(original) if create < r['offset'] < methods['setLabelText']]
    start = next(r['offset'] for r in body if r['opcode'] == 10 and r['register'] == -4)
    calls = [r for r in body if r['opcode'] == 63][:2]
    font_helper, position_helper = (r['operands'][0] for r in calls)

    class Vector(list):
        @property
        def Count(self): return len(self)
        def add(self, value): self.append(value)

    class Canvas:
        def clear(self): pass
        def prepare(self, text): return (100, 20)

    fonts = {}
    def metrics(px):
        if px not in fonts:
            data = read_entry(index, 'Textures\\Fonts\\fontmain_%d.ft' % px)
            height, _, count = struct.unpack_from('<3I', data)
            glyphs = {chr(struct.unpack_from('<H', data, 12 + 18 * i)[0]):
                      struct.unpack_from('<4i', data, 14 + 18 * i) for i in range(count)}
            fonts[px] = height, glyphs
        return fonts[px]

    for height in (360, 540, 771, 1542):
        screen_scale = height / 1200
        for percent in (100, 150):
            for size in (2, 3):
                seen, labels = [], Vector()
                def load_font(name):
                    seen.append(name)
                    px = int(name.split('_')[1].split('.')[0])
                    return {'Height': metrics(px)[0]}
                vm = VM(module, {6: screen_scale}, {'Settings': {'PortTextSize': Property(percent)},
                    '!vector': Vector, 'Width': round(height * 16 / 9),
                    'Plane': {'loadFont': load_font, 'createStringCanvas': lambda *args: Canvas()},
                    '__externals__': {(2, 4): labels}})
                def supported(regs, base):
                    _, result = VM(original).run(font_helper, {-4: regs[base - 1]})
                    regs[base - 2] = result[-5]
                vm.calls[font_helper] = supported
                vm.calls[position_helper] = lambda regs, base: regs.__setitem__(base - 4, regs[base - 2])
                emitted = []
                a = Asm(module, 12)
                a.label_text('caption', 0, 0, size)
                a.emit(65)
                label_site = function(module, a, 12)
                VM(module, {17: {'call': lambda *args: emitted.append(args)}}, {'!vec2': lambda *args: args}).run(label_site)
                assert emitted == [('createLabel', 'caption', (0, 0), 0, -{2: 26, 3: 40}[size])]
                # Execute the original factory from after vector allocation,
                # then its original refresh method on the stored label record.
                marker = emitted[0][-1]
                vm.run(start, {0: Vector(), -7: 'caption', -6: 'position', -5: 0, -4: marker})
                expected_size = max(8, int(-marker * screen_scale))
                expected_size = min(28, expected_size)
                assert labels[0][4] == int(marker * screen_scale)
                # Opcode8 initializes dead r0 before the native font load;
                # this bounded VM does not model that variant constant.
                dead_init = next(r['offset'] for r in rows(original)
                                 if r['offset'] > methods['setLabelText'] and r['opcode'] == 8)
                _, refresh = vm.run(methods['setLabelText'], {-5: 0, -4: '150 %'}, stops=(dead_init,))
                vm.run(dead_init + 4, refresh)
                assert seen == ['fontmain_%d.ft' % expected_size] * 2, (lang, height, percent, size, seen)
                # The same original methods keep increasing ordinary menu
                # labels once, both at creation and on value/text refresh.
                vm.run(start, {0: Vector(), -7: 'ordinary', -6: 'position', -5: 0, -4: size})
                ordinary_size = int({2: 26, 3: 40}[size] * screen_scale)
                assert labels[1][4] == ordinary_size
                supported_size = 36 if ordinary_size > 28 else max(8, ordinary_size)
                ordinary_font = int(supported_size * percent / 100 + .5)
                ordinary_font = 36 if ordinary_font > 28 else ordinary_font
                _, refresh = vm.run(methods['setLabelText'], {-5: 1, -4: 'ordinary'}, stops=(dead_init,))
                vm.run(dead_init + 4, refresh)
                assert seen[2:] == ['fontmain_%d.ft' % ordinary_font] * 2

    # The activity can choose any even logical height from 360 to 1542 as
    # display density and interface scale vary. Check the real glyph advances
    # and overhangs at every height, including discrete bitmap-font jumps.
    for height in range(360, 1543, 2):
        screen_scale = height / 1200
        for page in pages(TEXTS[lang]):
            for side, column in enumerate(page):
                for row in column:
                    title = isinstance(row, Slider)
                    text = row.title if title else row.caption
                    px = max(8, int((40 if title else 26) * screen_scale))
                    px = min(28, px)
                    _, glyphs = metrics(px)
                    advance = width = 0
                    for char in text:
                        ink, _, _, step = glyphs[char]
                        width = max(width, advance + ink)
                        advance += step
                    x = (-820 if side == 0 else 120) + (0 if title else 184 if side == 0 else 224)
                    limit = (120 if side == 0 else 1200 * 8 / 9) - x
                    assert width + 4 <= limit * screen_scale, (lang, height, text, width, limit * screen_scale)


for index, lang in INDEXES.items():
    if lang == "pl":
        backplates(index, lang)
        continue  # other legacy VM/canvas compatibility is exercised in test_touch_legacy
    distance_boundaries(index, lang)
    font_sizes(index, lang)
    backplates(index, lang)
    stats_lines(index, lang)
    fixed_port_labels(index, lang)
    full_overrides(index, lang)
    print(lang + ': exact tree/helper/harvest boundaries, independent bitmap fonts, cached padded backplates and composed bytecode PASS')

backplate = dds_argb(2, 2, b'\0\0\0\xff' * 4)
for index in INDEXES:
    original_black = read_entry(index, 'Textures\\BlackBitmap.tex')
    assert len(backplate) != len(original_black)
    assert hashlib.sha256(backplate).digest() != hashlib.sha256(original_black).digest()
print('backplate cannot be mistaken for the original subtitle/tap-to-skip texture PASS')
