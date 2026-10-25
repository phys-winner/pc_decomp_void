"""Original VM seams for readable fonts, tooltip backplates and use distance."""
import re
import struct

from gscript_binary import p32
from patch_native_menu import Assembler
from patch_touch_native import add, hook, rows


def frame_at(module, offset):
    return max((r for r in module.instructions() if r.get('header') and r['offset'] < offset),
               key=lambda r: r['offset'])


def scratch(module, offset, count):
    frame = frame_at(module, offset)
    base = frame['frame_slots']
    module.code[frame['offset'] + 4:frame['offset'] + 8] = p32(base + count)
    return base, hex(frame['offset'] + 4)


def replace(module, row, assembly, length=None):
    length = length or row['size']
    assembly.emit(54, 0, row['offset'] + length)
    module.code[row['offset']:row['offset'] + length] = p32(module.opcode(54)) + p32(add(module, assembly)) + p32(74) * ((length - 8) // 4)


def scale_font(a, size, key, base):
    """Use the release's real bitmap font sizes: 8..28 and 36 only."""
    a.get_setting(key, base, 'asFloat')
    a.integer(base + 1, 100)
    a.emit(39, base)
    a.move(size, base + 1)
    a.emit(38, base)
    a.emit(2, base + 1, struct.unpack('<I', struct.pack('<f', .5))[0])
    a.emit(36, base)
    a.emit(16, base)
    a.move(base, base + 1)
    a.integer(base + 2, 28)
    a.emit(50, base + 1)
    a.emit(55, base + 1, 'font_small')
    a.integer(base, 36)
    a.label('font_small')
    a.move(base, base + 1)
    a.integer(base + 2, 8)
    a.emit(48, base + 1)
    a.emit(55, base + 1, 'font_ready')
    a.integer(base, 8)
    a.label('font_ready')
    a.move(base, size)
    a.clear(*range(base, base + 4))


def patch_fonts(module, lang, subtitle=False):
    """Scale original game fonts, leaving image layout and UI scale alone."""
    original_rows = rows(module)
    sites, loads = [], []
    subtitle_methods = {m['code_offset'] for c in module.contexts for m in c['methods']
                        if subtitle and m['name'] in ('loadDialogueFont', 'loadFontScaled')}
    label_methods = {m['code_offset'] for c in module.contexts for m in c['methods']
                     if (m['name'], m['args']) in (('createLabel', 4), ('setLabelText', 2))}
    fixed_labels = []
    for i, row in enumerate(original_rows):
        if not row.get('text', '').startswith('fontmain_'):
            continue
        text, reg = row['text'], row['register']
        key = 'PortSubtitleSize' if frame_at(module, row['offset'])['offset'] in subtitle_methods else 'PortTextSize'
        # Subtitle.loadFontScaled has its own supported-size formatter, after
        # multiplying by the screen scale. Its result is a string, not a size.
        dynamic = None
        if text == 'fontmain_':
            for candidate in original_rows[i + 1:i + 20]:
                if candidate['opcode'] == 20 and candidate['register'] == reg + 1:
                    dynamic = candidate
                    break
                if candidate['opcode'] == 57:
                    break
            if dynamic is None:
                # This is the scaled loader's numeric input before its helper.
                dynamic = next((x for x in original_rows[i + 1:i + 10]
                                if x['opcode'] == 16 and x['register'] == reg + 2), None)
                if dynamic is None:
                    continue
        else:
            assert re.fullmatch(r'fontmain_\d+\.ft', text), text
        site = dynamic or row
        fixed_label = dynamic and dynamic['opcode'] == 20 and frame_at(module, row['offset'])['offset'] in label_methods
        if fixed_label:
            site = original_rows[original_rows.index(dynamic) - 1]
            assert site['opcode'] == 63 and site['register'] == dynamic['register'] + 2, site
        base, frame_site = scratch(module, site['offset'], 4)
        a = Assembler(module)
        if fixed_label:
            # Only the port pages supply negative sizes. Preserve their marker
            # in the original label record so later value updates stay fixed.
            # All ordinary labels retain the original clamp then text scaling.
            source, size = site['register'] - 1, site['register'] - 2
            a.move(source, base)
            a.integer(base + 1, 0)
            a.emit(48, base)
            a.emit(55, base, 'scaled_label')
            a.integer(base, -1)
            a.move(source, base + 1)
            a.emit(38, base)
            a.move(base, source)
            a.raw(module.code[site['offset']:site['offset'] + 8])
            # Avoid the original 28-to-36 bitmap jump overflowing a column
            # on large logical screens; ordinary game labels retain 36.
            a.move(size, base)
            a.integer(base + 1, 28)
            a.emit(50, base)
            a.emit(55, base, 'label_ready')
            a.integer(size, 28)
            a.emit(54, 0, 'label_ready')
            a.label('scaled_label')
            a.raw(module.code[site['offset']:site['offset'] + 8])
            scale_font(a, size, key, base)
            a.label('label_ready')
            a.clear(*range(base, base + 4))
            replace(module, site, a)
            fixed_labels.append(site['offset'])
        elif dynamic:
            size = dynamic['register']
            scale_font(a, size, key, base)
            hook(module, site['offset'], a, 8 if site['opcode'] == 20 else 12)
        else:
            a.integer(reg, int(re.search(r'\d+', text)[0]))
            scale_font(a, reg, key, base)
            a.emit(20, reg)
            a.string(base, 'fontmain_')
            a.move(reg, base + 1)
            a.emit(36, base)
            a.string(base + 1, '.ft')
            a.emit(36, base)
            a.move(base, reg)
            a.clear(base, base + 1)
            replace(module, row, a)
        sites += [frame_site, hex(site['offset'])]
        loads.append(site['offset'])
    assert loads
    return dict(sites=sites, readable_font_sites=loads, fixed_label_font_sites=fixed_labels)


def patch_backplate(module, lang):
    method = next(m['code_offset'] for c in module.contexts for m in c['methods'] if m['name'] == 'renderTooltip')
    instructions = rows(module)
    code = [r for r in instructions if r['offset'] > method]
    draw = next(r for r in code if r.get('symbol') in ('drawString', 'drawStringAlpha'))
    # prepare() returns the size vector; shadow offsets also subtract and may load the canvas.
    prepare = next(i for i, r in enumerate(instructions) if r.get('symbol') == 'prepare')
    dimensions = next(r['operands'][0] for r in instructions[prepare + 1:] if r['opcode'] == 13)
    image = len(module.types)
    module.types += bytes([3])
    base, frame_site = scratch(module, draw['offset'], 12)
    a = Assembler(module)
    a.get_setting('PortTextContrast', base, 'asBool')
    a.emit(55, base, 'normal')
    a.emit(14, image, base)
    a.emit(56, base, 'image_ready')
    a.global_(base + 2, 'Plane')
    a.member(base + 1, 'loadImage')
    a.clear(base + 2)
    a.string(base + 2, 'ui/port_text_backplate')
    a.native(base, 1)
    a.clear(base + 1, base + 2)
    a.emit(13, base, image)
    a.label('image_ready')
    a.clear(base)
    a.move(draw['register'] + 1, base + 2)
    a.member(base + 1, 'drawImageAlphaScaled')
    a.clear(base + 2)
    a.emit(14, image, base + 2)
    for dest, source in ((base + 3, -5), (base + 4, -4)):
        a.move(source, dest)
        a.integer(dest + 1, 4)
        a.emit(37, dest)
    for dest, index in ((base + 5, 0), (base + 6, 1)):
        a.emit(14, dimensions, dest + 1)
        a.integer(dest + 2, index)
        a.emit(58, dest, 1)
        a.integer(dest + 1, 8)
        a.emit(36, dest)
    a.emit(2, base + 7, struct.unpack('<I', struct.pack('<f', .82))[0])
    a.native(base, 6)
    a.label('normal')
    a.clear(*range(base, base + 12))
    hook(module, draw['offset'], a)
    return dict(sites=[frame_site, hex(draw['offset'])], text_backplate=draw['offset'],
                backplate_dimensions=dimensions, backplate_image=image)


def patch_use_distance(module, lang):
    """The helper and held Use share each entity's original use-distance getter."""
    code = rows(module)
    sites, filters = [], []
    for i, row in enumerate(code):
        if row.get('symbol') != 'rayTraceObj':
            continue
        call = next(x for x in code[i + 1:] if x['opcode'] == 57)
        # Only the forward interaction rays, not painting or ground collision.
        args = code[i + 1:code.index(call)]
        distance = next((x for x in args if x['opcode'] == 1 and x['register'] == call['register'] + 4), None)
        if distance is None or distance['operands'][0] not in (3, 5):
            continue
        if not any(x.get('symbol') == 'LookDirection' for x in code[max(0, i - 8):i]):
            continue
        original_max = distance['operands'][0]
        # Trace the same segment at the exact endpoint in both states; keep
        # the idle helper's original upper bound for every other object.
        if original_max == 3:
            module.code[distance['offset'] + 4:distance['offset'] + 8] = p32(5)
            sites.append(hex(distance['offset']))
        base, frame_site = scratch(module, call['offset'], 7)
        a = Assembler(module)
        a.raw(module.code[call['offset']:call['offset'] + 8])
        result = call['register']
        a.move(result, base + 1)
        a.integer(base + 2, 0)
        a.emit(58, base, 1)
        a.emit(55, base, 'normal')
        a.move(result, base + 2)
        a.integer(base + 3, 2)
        a.emit(58, base + 1, 1)
        a.move(base + 1, base + 3)
        a.emit(61, base + 2, a.pool('callDef'))
        a.clear(base + 3)
        a.emit(55, base + 2, 'default_distance')
        a.move(base + 1, base + 3)
        a.member(base + 2, 'callDef')
        a.clear(base + 3)
        a.integer(base + 3, original_max)
        a.string(base + 4, 'getUseDistance')
        a.native(base + 1, 2)
        a.clear(base + 2, base + 3, base + 4)
        a.emit(54, 0, 'distance_ready')
        a.label('default_distance')
        a.integer(base + 1, original_max)
        a.label('distance_ready')
        if original_max == 3:
            a.move(base + 1, base + 2)
            a.integer(base + 3, original_max)
            a.emit(50, base + 2)
            a.emit(55, base + 2, 'idle_cap')
            a.integer(base + 1, original_max)
            a.label('idle_cap')
        a.move(result, base + 3)
        a.integer(base + 4, 1)
        a.emit(58, base + 2, 1)
        a.move(base + 1, base + 3)
        a.emit(50, base + 2)
        a.emit(55, base + 2, 'normal')
        a.global_(base + 1, '!tuple')
        a.emit(0, base + 2, 0)
        a.integer(base + 3, 0)
        a.emit(4, base + 4)
        a.native(base, 3)
        a.move(base, result)
        a.label('normal')
        a.clear(*range(base, base + 7))
        replace(module, call, a)
        sites += [frame_site, hex(call['offset'])]
        filters.append(call['offset'])
    assert len(filters) == 3, filters
    return dict(sites=sites, use_distance_filters=filters)


FONT_MODULES = ('skip_helper takeall playaudio playvideo delete return default newsave diary_hero diary_color '
                'diary_girls monologue diary_hunter item_list quest body_active_limfa body_free_limfa '
                'paint_limfa map_body_indicator credits obscure_wheel subtitle video body_wheel gamewin '
                'health_progress journal database_wheel map_wheel options_video_menu hud hunter tree load_menu '
                'save_menu obscure_final database obscure body main_menu map_strip map').split()

PATCHES = [('Scripts\\player.bin', patch_use_distance)]
PATCHES += [('Scripts\\ui\\' + name + '.bin',
             lambda m, l, subtitle=name in ('subtitle', 'video'): patch_fonts(m, l, subtitle)) for name in FONT_MODULES]
PATCHES += [('Scripts\\ui\\' + name + '.bin', patch_backplate)
            for name in ('paint_limfa', 'body_free_limfa', 'body_active_limfa', 'body_wheel')]
