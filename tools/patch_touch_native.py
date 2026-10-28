"""Small original-script seams used by Android's native touch bridge."""
import struct
import json
from pathlib import Path
from gscript_binary import p32
from patch_native_menu import Assembler


def export_mobile_gestures(index_path, destination, read_entry, decode):
    from xml.etree import ElementTree as ET
    from PIL import Image
    body = ET.fromstring(read_entry(index_path, 'Properties\\World\\body.xml'))
    gestures = ET.fromstring(read_entry(index_path, 'Properties\\World\\gesture.xml'))
    images = {node.attrib['Name']: next(p.attrib['value'] for p in node if p.attrib['name'] == 'Image')
              for node in gestures}
    destination.mkdir(parents=True, exist_ok=True)
    for zone in range(21):
        category = body.find("Category[@Name='Zone%d']" % zone)
        gesture = next(p.attrib['value'] for p in category if p.attrib['name'] == 'Gesture')
        texture = 'Textures\\' + images[gesture].replace('/', '\\') + '.tex'
        width, height, pixels = decode(read_entry(index_path, texture))
        assert width > 0 and height > 0 and any(pixels[3::4])
        Image.frombytes('RGBA', (width, height), pixels).save(destination / ('zone%d.png' % zone))


def rows(module):
    return [r for r in module.instructions() if not r.get('header')]


def method(module, name):
    return next(m['code_offset'] for c in module.contexts for m in c['methods'] if m['name'] == name)


def add(module, assembler):
    at = len(module.code)
    module.code += assembler.finish(at)
    return at


def hook(module, at, assembler, length=8):
    old = bytes(module.code[at:at + length])
    assembler.raw(old)
    assembler.emit(54, 0, at + length)
    module.code[at:at + length] = p32(module.opcode(54)) + p32(add(module, assembler)) + p32(74) * ((length - 8) // 4)


def float_(a, reg, value):
    a.emit(2, reg, struct.unpack('<I', struct.pack('<f', value))[0])


def poll(a, key, reg=0):
    a.global_(reg + 1, 'isKeyPressed')
    a.integer(reg + 2, key)
    a.native(reg, 1)
    a.clear(reg + 1, reg + 2)


def patch_player(module, lang):
    r = rows(module)
    fov = method(module, 'getCameraFOV')
    assert module.code[fov + 4:fov + 8] == p32(1)
    module.code[fov + 4:fov + 8] = p32(5)
    a = Assembler(module)
    a.emit(14, 35, 0)
    a.get_setting('PortFOV', 1, 'asFloat')
    a.integer(2, 55)
    a.emit(39, 1)
    a.emit(38, 0)
    a.move(0, -4)
    a.clear(0, 1, 2, 3, 4)
    a.emit(65)
    at = fov + 8
    module.code[at:at + 8] = p32(module.opcode(54)) + p32(add(module, a))
    # The movement call is the one whose vector is a local, not an external impulse.
    force = next(x for x in r if x.get('symbol') == 'addForce' and x['register'] == (9 if module.legacy else 8))
    frame = max((x for x in module.instructions() if x.get('header') and x['offset'] < force['offset']), key=lambda x: x['offset'])
    base = frame['frame_slots']
    module.code[frame['offset'] + 4:frame['offset'] + 8] = p32(base + 3)
    a = Assembler(module)
    a.global_(base + 1, 'executeConsoleCommand')
    a.string(base + 2, 'port_move_force')
    a.native(base, 1)
    a.clear(base, base + 1, base + 2)
    hook(module, force['offset'], a)
    # At zero smoothing touch event batches become alternating velocity spikes.
    smooth = next(x for x in r if x['opcode'] == 14 and x['register'] == 0 and x['operands'] == [1]
                  and x['offset'] > (40000 if module.legacy else 45000))
    a = Assembler(module)
    a.emit(14, 0, 1)
    float_(a, 2, .25)
    a.emit(48, 1)
    a.emit(55, 1, 'unchanged')
    float_(a, 1, .25)
    a.emit(13, 1, 0)
    a.label('unchanged')
    hook(module, smooth['offset'], a)
    return dict(sites=[hex(fov + 4), hex(at), hex(frame['offset'] + 4), hex(force['offset']), hex(smooth['offset'])], minimum_mouse_smoothing=.25)


def clone_helper(module, source, start, end, calls):
    original = list(source.instructions())
    frame = next(x['frame_slots'] for x in original if x['offset'] == start)
    a = Assembler(module)
    for row in [x for x in original if start < x['offset'] < end]:
        a.label('original_' + str(row['offset']))
        op, reg, args = row['opcode'], row['register'], row['operands']
        if op == 3:
            a.string(reg, row['text'])
        elif 'symbol' in row:
            assert op in (60, 61, 71, 73)
            a.emit(op, reg, a.pool(row['symbol']))
        elif op in (54, 55, 56):
            a.emit(op, reg, 'original_' + str(args[0]))
        elif op == 63:
            a.emit(op, reg, calls[args[0]])
        else:
            a.emit(op, reg, *args)
    at = len(module.code)
    module.code += p32(0xffffffff) + p32(frame)
    module.code += a.finish(len(module.code))
    return at


def patch_brush_capacity(module, lang):
    # The original availability update runs when a heart is collected/unlocked.
    # Invalidate the cheap capacity cache; the player computes it once afterward.
    start = method(module, 'updateBodyGestures') + 8
    a = Assembler(module)
    a.integer(1, 0)
    a.global_(2, 'Vars')
    a.string(3, 'PortActiveCapacity')
    # STORE packs the value register; its key window starts at value + 2.
    a.emit(59, 2, (1 << 8) | 1)
    a.clear(1, 2, 3)
    hook(module, start, a)
    return dict(sites=[hex(start)])


def patch_brush_live(module, lang):
    from gscript_binary import Module
    root = Path(__file__).resolve().parents[1]
    index = json.loads((root / ('research/vfs-index.polish.json' if module.legacy else 'research/vfs-index.german.json' if lang == 'de' else 'research/vfs-index.json')).read_text())
    for container in index['containers']:
        entry = next((x for x in container['entries'] if x['name'] == 'Scripts\\ui\\paint.bin'), None)
        if entry:
            with (Path(index['source']) / container['name']).open('rb') as handle:
                handle.seek(entry['offset'])
                source = Module(handle.read(entry['size']), legacy=module.legacy)
            break
    else:
        raise AssertionError('Original paint capacity helper missing')
    old = list(source.instructions())
    capacity_row = next(x['offset'] for x in old if x.get('symbol') == 'ActiveLimfaBottleSizeBase')
    capacity = max(x['offset'] for x in old if x.get('header') and x['offset'] < capacity_row)
    count = next(x['operands'][0] for x in old if x.get('opcode') == 63 and x['offset'] > capacity)
    count_end = next(x['offset'] for x in old if x.get('header') and x['offset'] > count)
    cloned_count = clone_helper(module, source, count, count_end, {})
    cloned_capacity = clone_helper(module, source, capacity, count, {count: cloned_count})
    cache = len(module.types)
    module.types += bytes([1, 2, 2, 0])  # Last published color, amount, capacity, initialized.
    a = Assembler(module)
    a.global_(0, 'World')
    a.move(0, 2)
    a.member(1, 'Vars')
    a.move(1, 4)
    a.member(3, 'has')
    a.string(4, 'LastChoosenLimfa')
    a.native(2, 1)
    a.clear(3, 4)
    a.emit(55, 2, 'default_colour')
    a.move(1, 3)
    a.string(4, 'LastChoosenLimfa')
    a.emit(58, 2, 1)
    a.emit(16, 2)
    a.move(2, 5)
    a.integer(6, 0)
    a.emit(48, 5)
    a.emit(56, 5, 'default_colour')
    a.move(2, 5)
    a.integer(6, 7)
    a.emit(48, 5)
    a.emit(56, 5, 'colour_ready')
    a.label('default_colour')
    a.integer(2, 0)
    a.label('colour_ready')
    a.move(1, 5)
    a.member(4, 'has')
    a.string(5, 'PortActiveCapacity')
    a.native(3, 1)
    a.emit(55, 3, 'capacity_needed')
    a.move(1, 4)
    a.string(5, 'PortActiveCapacity')
    a.emit(58, 3, 1)
    a.move(3, 5)
    a.integer(6, 0)
    a.emit(50, 5)
    a.emit(56, 5, 'capacity_ready')
    a.label('capacity_needed')
    a.move(0, 10)
    a.emit(63, 11, cloned_capacity)
    a.move(9, 3)
    a.move(3, 10)
    a.move(1, 11)
    a.string(12, 'PortActiveCapacity')
    a.emit(59, 11, (10 << 8) | 1)
    a.clear(9, 10, 11, 12, 13)
    a.label('capacity_ready')
    a.move(0, 8)
    a.member(7, 'call')
    a.string(8, 'getPlayerEntity')
    a.native(6, 1)
    a.move(6, 7)
    a.member(6, 'Properties')
    a.member(5, 'ActiveLimfa')
    a.move(2, 6)
    a.emit(20, 6)
    a.emit(58, 4, 1)
    a.move(4, 5)
    a.move(3, 6)
    a.emit(50, 5)
    a.emit(55, 5, 'bounded')
    a.move(3, 4)
    a.label('bounded')
    a.emit(14, cache + 3, 5)
    a.emit(55, 5, 'changed')
    for reg, slot in ((2, cache), (4, cache + 1), (3, cache + 2)):
        a.move(reg, 5)
        a.emit(14, slot, 6)
        a.emit(46, 5)
        a.emit(55, 5, 'changed')
    a.emit(54, 0, 'done')
    a.label('changed')
    for reg, slot in ((2, cache), (4, cache + 1), (3, cache + 2)):
        a.emit(13, reg, slot)
    a.emit(0, 5, 1)
    a.emit(13, 5, cache + 3)
    a.global_(6, 'format')
    a.string(7, 'port_brush %d %d %d')
    a.move(2, 8)
    a.move(4, 9)
    a.move(3, 10)
    a.native(5, 4)
    a.move(5, 7)
    a.global_(6, 'executeConsoleCommand')
    a.native(5, 1)
    a.label('done')
    a.clear(*range(14))
    a.emit(65)
    publish = len(module.code)
    module.code += p32(0xffffffff) + p32(14)
    module.code += a.finish(len(module.code))
    r = rows(module)
    tick = [x for x in r if x.get('symbol') == 'OnGround'][-1] if module.legacy else next(x for x in r if x.get('symbol') == 'OnGround' and x['offset'] > 45000)
    header = max(x['offset'] for x in module.instructions() if x.get('header') and x['offset'] < tick['offset'])
    a = Assembler(module)
    a.emit(63, 0, publish)
    a.clear(0, 1, 2)
    hook(module, header + 8, a)
    return dict(sites=[hex(header + 8)], brush_publisher=publish, brush_cache_global=cache,
                capacity_helper=cloned_capacity, live_selected_colour=True)


def patch_body(module, lang):
    r = rows(module)
    sound_row = next(x['offset'] for x in r if x.get('symbol') == 'playSound' and x['offset'] > (0 if module.legacy else 25000))
    sound_helper = max(x['offset'] for x in module.instructions() if x.get('header') and x['offset'] < sound_row)
    move = method(module, 'onMouseMove') + 8
    # Original hit test: -1 empty, even heart, odd capillary; no screen heuristics.
    hit = next(x['operands'][0] for i, x in enumerate(r)
               if x['opcode'] == 63 and r[i-2]['opcode'] == 10 and r[i-2]['register'] == -6
               and r[i-1]['opcode'] == 10 and r[i-1]['register'] == -5)
    end = next(x['offset'] for x in module.instructions() if x.get('header') and x['offset'] > hit)
    a = Assembler(module)
    for row in [x for x in r if hit < x['offset'] < end]:
        a.label('hit_' + str(row['offset']))
        if row['opcode'] == 23 and row['register'] == 2:
            a.emit(0, 2, 1)  # Accept the capillary surface of an enabled pair too.
        elif row['opcode'] in (54, 55, 56):
            a.emit(row['opcode'], row['register'], 'hit_' + str(row['operands'][0]))
        else:
            a.raw(module.code[row['offset']:row['offset'] + row['size']])
    raw_hit = len(module.code)
    module.code += p32(0xffffffff) + p32(8)
    module.code += a.finish(len(module.code))
    module._touch_body_hit = raw_hit
    a = Assembler(module)
    a.move(-5, 1)
    a.move(-4, 2)
    a.emit(63, 3, raw_hit)
    a.emit(20, 0)
    a.move(0, 1)
    a.string(0, 'port_body_target ')
    a.emit(36, 0)
    a.move(0, 2)
    a.global_(1, 'executeConsoleCommand')
    a.native(0, 1)
    a.clear(0, 1, 2, 3)
    hook(module, move, a)
    sites = [hex(move)]
    # The original tooltip polls the cursor even when no mouse-move event is
    # delivered (including repeated touches at the same pixel). Reuse that hit
    # result, accepting both surfaces, so Java's invalidated target is refreshed.
    amount_text = next(x['offset'] for x in r if x.get('text') == '(%u / %u)')
    hover_hit = max((x for x in r if x.get('opcode') == 63 and
                     x['operands'] == [hit] and x['offset'] < amount_text), key=lambda x: x['offset'])
    module.code[hover_hit['offset'] + 4:hover_hit['offset'] + 8] = p32(raw_hit)
    a = Assembler(module)
    a.move(0, 2)
    a.emit(20, 2)
    a.string(1, 'port_body_target ')
    a.emit(36, 1)
    a.move(1, 3)
    a.global_(2, 'executeConsoleCommand')
    a.native(1, 1)
    a.clear(1, 2, 3)  # Preserve r0 for the original tooltip's hit checks.
    hook(module, hover_hit['offset'] + 8, a)
    sites += [hex(hover_hit['offset'] + 4), hex(hover_hit['offset'] + 8)]
    # Both original carried-colour Escape handlers already return the full amount.
    offsets = sorted({m['code_offset'] for c in module.contexts for m in c['methods']
                      if m['name'] == 'onWinKeyDown'})
    for start in offsets:
        body = [x for x in r if start < x['offset'] < start + 400]
        if not any(x.get('symbol') in ('FreeLimfa', 'ZoneLimfa') for x in body):
            continue
        a = Assembler(module)
        a.move(-5, 0)
        a.integer(1, 0x7f)
        a.emit(46, 0)
        a.emit(55, 0, 'normal')
        a.integer(-5, 27)
        a.move(-4, 0)
        a.emit(56, 0, 'normal')
        a.global_(0, 'Plane')
        a.global_(2, 'loadSound')
        a.string(3, 'ui_body_limfa_drop0')
        a.native(1, 1)
        a.clear(2, 3)
        a.string(2, 'Sound')
        a.emit(63, 3, sound_helper)
        a.clear(0, 1, 2, 3)
        a.label('normal')
        hook(module, start + 8, a)
        sites.append(hex(start + 8))
    return dict(sites=sites, body_hit_test=hex(hit), body_hover_hit=hover_hit['offset'],
                body_hover_publish=hover_hit['offset'] + 8)


def patch_body_counts(module, lang, side):
    start = method(module, 'setProgress')
    # The base image also defines setProgress(float); use the amount,max overload.
    start = next(m['code_offset'] for c in module.contexts for m in c['methods']
                 if m['name'] == 'setProgress' and m['args'] == 2)
    a = Assembler(module)
    a.string(2, 'port_colour %d %d %d %d')
    a.integer(3, side)
    a.emit(14, 4, 4)
    a.move(-5, 5)
    a.move(-4, 6)
    a.move(5, 0)
    a.move(6, 1)
    a.emit(50, 0)
    a.emit(55, 0, 'bounded')
    a.move(6, 5)
    a.label('bounded')
    a.global_(1, 'format')
    a.native(0, 5)
    a.clear(1, 2, 3, 4, 5, 6)
    a.move(0, 2)
    a.global_(1, 'executeConsoleCommand')
    a.native(0, 1)
    a.clear(0, 1, 2)
    module.code[start + 4:start + 8] = p32(7)
    hook(module, start + 8, a)
    sites = [hex(start + 4), hex(start + 8)]
    # Overlay controls forward intentional presses with F18 held. A finger on
    # the old, still visible artwork must not start another inventory action.
    left = method(module, 'onMouseButtonLeft')
    frame = next(x['frame_slots'] for x in module.instructions() if x['offset'] == left)
    a = Assembler(module)
    a.get_setting('PortTouchInput', frame, 'asBool')
    a.emit(55, frame, 'normal')
    poll(a, 0x69, frame)
    a.emit(56, frame, 'normal')
    a.clear(*range(frame, frame + 5), -4)
    a.emit(65)
    a.label('normal')
    a.clear(*range(frame, frame + 5))
    module.code[left + 4:left + 8] = p32(frame + 5)
    hook(module, left + 8, a)
    sites += [hex(left + 4), hex(left + 8)]
    render = method(module, 'renderTooltip')
    frame = next(x['frame_slots'] for x in module.instructions() if x['offset'] == render)
    a = Assembler(module)
    a.get_setting('PortTouchInput', frame, 'asBool')
    a.emit(55, frame, 'normal')
    a.emit(0, -7, 0)
    a.clear(*range(frame, frame + 5), -6, -5, -4)
    a.emit(65)
    a.label('normal')
    a.clear(*range(frame, frame + 5))
    module.code[render + 4:render + 8] = p32(frame + 5)
    hook(module, render + 8, a)
    sites += [hex(render + 4), hex(render + 8)]
    if side == 1:
        # Publish the original Memory circle's exact colour on a real press.
        # The original callback remains responsible for moving the colour.
        press = next(x['offset'] for x in rows(module)
                     if left < x['offset'] < left + 100 and x.get('symbol') == 'Window')
        a = Assembler(module)
        a.string(0, 'port_body_transfer_colour ')
        a.emit(14, 4, 1)
        a.emit(20, 1)
        a.emit(36, 0)
        a.move(0, 2)
        a.global_(1, 'executeConsoleCommand')
        a.native(0, 1)
        a.clear(0, 1, 2)
        hook(module, press, a)
        sites.append(hex(press))
    return dict(sites=sites, side=side)


def patch_body_sources(module, lang):
    r = rows(module)
    forced = len(module.types)
    module.types += bytes([1])
    base = method(module, 'onMouseButtonLeft')
    original_hit = next(x['operands'] for x in r if base < x['offset'] < base + 100 and x['opcode'] == 63)
    # The last hit-testing left-button handler puts a carried Memory colour into a heart.
    memory = max(m['code_offset'] for c in module.contexts for m in c['methods']
                 if m['name'] == 'onMouseButtonLeft' and any(m['code_offset'] < x['offset'] < m['code_offset'] + 100
                    and x['opcode'] == 63 and x['operands'] == original_hit for x in r))
    sites, starts = [], []
    for left in (base, memory):
        hit = next(x for x in r if left < x['offset'] < left + 100 and x['opcode'] == 63)
        module.code[hit['offset'] + 4:hit['offset'] + 8] = p32(module._touch_body_hit)
        site = hit['offset'] + hit['size']
        a = Assembler(module)
        a.get_setting('PortTouchInput', 4, 'asBool')
        a.emit(55, 4, 'normal')
        if left == memory:
            a.emit(14, forced, 4)
            a.emit(55, 4, 'hit')
            a.move(4, 0)
            a.integer(1, 1)
            a.emit(37, 0)
            a.integer(1, 2)
            a.emit(38, 0)
            a.integer(4, 0)
            a.emit(13, 4, forced)
            a.label('hit')
        a.move(0, 1)
        a.integer(2, 0)
        a.emit(48, 1)
        a.emit(56, 1, 'normal')
        a.integer(1, 2)
        a.emit(39, 0)
        a.emit(16, 0)
        a.integer(1, 2)
        a.emit(38, 0)
        if module.legacy and left == base:
            # Only 2008 owns a separate reserve at ZoneLimfa[zone][1].
            poll(a, 0x68, 4)
            a.emit(55, 4, 'normal')
            a.integer(1, 1)
            a.emit(36, 0)
        a.label('normal')
        a.clear(*range(1, 8))
        module.code[left + 4:left + 8] = p32(8)
        hook(module, site, a)
        sites += [hex(left + 4), hex(hit['offset']), hex(site)]
        starts.append(site)
    division = next(x for x in r if x['offset'] > starts[1] and x['opcode'] == 39)
    module._touch_body_put_zone = division['offset'] + division['size']
    module._touch_body_put = memory
    module._touch_body_forced = forced
    constructors = [x for x in r if base < x['offset'] < base + 200 and x['opcode'] == 67]
    return dict(sites=sites, source_start=starts[0], memory_put_start=starts[1],
                memory_put_zone=module._touch_body_put_zone, forced_zone_global=forced,
                heart_entry=constructors[-1]['operands'][0],
                lymph_entry=constructors[0]['operands'][0] if module.legacy else None)


def hide_mobile_tooltip(module, start, args, result=None):
    frame = next(x['frame_slots'] for x in module.instructions() if x['offset'] == start)
    length = next(x['size'] for x in rows(module) if x['offset'] == start + 8)
    a = Assembler(module)
    a.get_setting('PortTouchInput', frame, 'asBool')
    a.emit(55, frame, 'original')
    if result is not None:
        a.emit(0, result, 0)
    a.clear(*range(frame, frame + 4), *args)
    a.emit(65)
    a.label('original')
    a.clear(*range(frame, frame + 4))
    module.code[start + 4:start + 8] = p32(frame + 4)
    hook(module, start + 8, a, length)
    return [hex(start + 4), hex(start + 8)]


def patch_body_details(module, lang):
    r = rows(module)
    last_zone = len(module.types)
    module.types += bytes([1, 0, 0])
    a = Assembler(module)
    a.emit(14, last_zone + 2, 0)
    a.emit(55, 0, 'publish')
    a.emit(14, last_zone, 0)
    a.move(-4, 1)
    a.emit(46, 0)
    a.emit(56, 0, 'publish')
    a.clear(0, 1, -4)
    a.emit(65)
    a.label('publish')
    a.move(-4, 0)
    a.emit(13, 0, last_zone)
    a.emit(0, 0, 1)
    a.emit(13, 0, last_zone + 1)
    a.emit(14, 7, 2)
    a.member(1, 'call')
    a.string(2, 'getPlayerEntity')
    a.native(0, 1)
    a.move(0, 2)
    a.member(1, 'Properties')
    a.member(0, 'ZoneLimfa')
    a.move(0, 2)
    a.move(-4, 3)
    a.emit(20, 3)
    a.emit(58, 1, 1)
    a.move(1, 3)
    a.integer(4, 0)
    a.emit(58, 2, 1)
    a.move(1, 4)
    a.integer(5, 2)
    a.emit(58, 3, 1)
    a.emit(14, 7, 7)
    a.member(6, 'Properties')
    a.member(5, 'get')
    a.string(6, 'Body/Zone')
    a.move(-4, 7)
    a.emit(20, 7)
    a.emit(36, 6)
    a.native(4, 1)
    a.move(4, 6)
    a.member(5, 'MaxLimfa')
    a.member(4, 'asInt')
    a.integer(5, 1000)
    a.emit(38, 4)
    if module.legacy:
        a.move(1, 6)
        a.integer(7, 1)
        a.emit(58, 5, 1)
        a.move(5, 11)
    a.move(2, 8)
    a.move(3, 7)
    a.move(4, 9)
    a.move(-4, 10)
    a.global_(5, 'format')
    a.string(6, 'port_body_heart %d %d %d %d' + (' %d' if module.legacy else ''))
    a.native(4, 6 if module.legacy else 5)
    a.move(4, 6)
    a.global_(5, 'executeConsoleCommand')
    a.native(4, 1)
    a.clear(*range(12), -4)
    a.emit(65)
    publisher = len(module.code)
    module.code += p32(0xffffffff) + p32(12)
    module.code += a.finish(len(module.code))
    module._touch_body_publisher = publisher
    left = method(module, 'onMouseButtonLeft')
    heart = next(x['operands'][0] for x in r if left < x['offset'] < left + 200 and x['opcode'] == 67 and x['operands'][1] == 259)
    constructors = [(heart, -6)]
    if module.legacy:
        lymph = next(x['operands'][0] for x in r if left < x['offset'] < left + 200 and x['opcode'] == 67)
        constructors.append((lymph, -4))
    latch_sites = []
    for constructor, argument in constructors:
        frame = next(x['frame_slots'] for x in module.instructions() if x['offset'] == constructor)
        a = Assembler(module)
        a.emit(13, argument, last_zone)
        a.emit(0, frame, 1)
        a.emit(13, frame, last_zone + 2)
        a.clear(frame)
        module.code[constructor + 4:constructor + 8] = p32(frame + 1)
        hook(module, constructor + 8, a)
        latch_sites += [hex(constructor + 4), hex(constructor + 8)]
    # Inventory refresh must publish the heart being filled, including a capillary hit.
    a = Assembler(module)
    a.emit(13, 2, last_zone)
    a.emit(0, 3, 1)
    a.emit(13, 3, last_zone + 1)
    a.emit(13, 3, last_zone + 2)
    a.clear(3)
    hook(module, module._touch_body_put_zone, a, 12)
    latch_sites.append(hex(module._touch_body_put_zone))
    base = next(x['operands'][0] for x in r if x['opcode'] == 67 and x['operands'][1] == 0)
    frame = next(x['frame_slots'] for x in module.instructions() if x['offset'] == base)
    a = Assembler(module)
    a.emit(0, frame, 0)
    a.emit(13, frame, last_zone + 2)
    a.clear(frame)
    module.code[base + 4:base + 8] = p32(frame + 1)
    hook(module, base + 8, a)
    latch_sites += [hex(base + 4), hex(base + 8)]
    # The original hover prepares the gesture icon and current/max; publish
    # from this same exact zone, then refresh it with every inventory update.
    tooltips = sorted({max(x['offset'] for x in module.instructions() if x.get('header') and x['offset'] < text['offset'])
                       for text in r if text.get('text') == '(%u / %u)'})
    sites = list(latch_sites)
    for tooltip in tooltips:
        frame = next(x['frame_slots'] for x in module.instructions() if x['offset'] == tooltip)
        a = Assembler(module)
        a.move(-4, frame + 1)
        a.emit(63, frame + 2, publisher)
        a.clear(*range(frame, frame + 5))
        module.code[tooltip + 4:tooltip + 8] = p32(frame + 5)
        hook(module, tooltip + 8, a)
        sites += [hex(tooltip + 4), hex(tooltip + 8)]
    free = next(x['offset'] for x in r if x.get('symbol') == 'FreeLimfa')
    refresh = max(x['offset'] for x in module.instructions() if x.get('header') and x['offset'] < free)
    tail = next(x['offset'] for x in r if x['offset'] > refresh and x['opcode'] == 65)
    # The preceding clear is eight bytes and has no control-flow targets.
    site = next(x['offset'] for x in r if x['offset'] == tail - 8)
    frame = next(x['frame_slots'] for x in module.instructions() if x['offset'] == refresh)
    a = Assembler(module)
    a.emit(14, last_zone + 1, frame)
    a.emit(55, frame, 'done')
    a.emit(14, last_zone, frame + 1)
    a.emit(63, frame + 2, publisher)
    a.label('done')
    a.clear(*range(frame, frame + 5))
    module.code[refresh + 4:refresh + 8] = p32(frame + 5)
    hook(module, site, a)
    sites += [hex(refresh + 4), hex(site)]
    # Keep the original update/hit pipeline, replacing only the small draws.
    render_text = next(x['offset'] for x in r if x.get('text') == 'renderTooltip')
    common = max(x['offset'] for x in module.instructions() if x.get('header') and x['offset'] < render_text)
    sites += hide_mobile_tooltip(module, common, (-4,))
    for context in ((5, 7, 8, 9) if module.legacy else (6, 7, 9, 10)):
        render = next(m['code_offset'] for m in module.contexts[context]['methods'] if m['name'] == 'renderDone')
        sites += hide_mobile_tooltip(module, render, (-4,))
    back = method(module, 'hideReturn')
    frame = next(x['frame_slots'] for x in module.instructions() if x['offset'] == back)
    a = Assembler(module)
    a.get_setting('PortTouchInput', 0, 'asBool')
    a.emit(55, 0, 'original')
    a.emit(0, -4, 1)
    a.label('original')
    a.clear(0, 1, 2, 3)
    module.code[back + 4:back + 8] = p32(max(frame, 4))
    hook(module, back + 8, a)
    sites += [hex(back + 4), hex(back + 8)]
    return dict(sites=sites, body_publisher=publisher, last_zone_global=last_zone,
                zone_tooltip=tooltip, inventory_refresh=refresh)


def patch_body_progress(module, lang):
    start = method(module, 'setProgress')
    frame = next(x['frame_slots'] for x in module.instructions() if x['offset'] == start)
    a = Assembler(module)
    a.global_(1, 'format')
    a.string(2, 'port_body_progress %d %d')
    a.move(-6, 3)
    a.move(-4, 4)
    a.native(0, 3)
    a.move(0, 2)
    a.global_(1, 'executeConsoleCommand')
    a.native(0, 1)
    a.clear(*range(5))
    hook(module, start + 8, a)
    assert frame >= 5
    return dict(sites=[hex(start + 8)])


def patch_stat_details(module, lang):
    start = method(module, 'setProgress')
    frame = next(x['frame_slots'] for x in module.instructions() if x['offset'] == start)
    a = Assembler(module)
    for colour in range(7):
        a.move(-4, 2)
        a.integer(3, colour)
        a.emit(58, 1, 1)
        a.move(1, 3)
        a.integer(4, 0)
        a.emit(58, 2, 1)
        a.integer(3, 100)
        a.emit(38, 2)
        a.move(1, 4)
        a.integer(5, 1)
        a.emit(58, 3, 1)
        a.move(3, 4)
        a.integer(5, 0)
        a.emit(50, 4)
        a.emit(55, 4, 'empty_' + str(colour))
        a.emit(39, 2)
        a.emit(54, 0, 'ready_' + str(colour))
        a.label('empty_' + str(colour))
        a.integer(2, 0)
        a.label('ready_' + str(colour))
        a.emit(16, 2)
        a.move(2, 5)
        a.emit(14, 19, 7)
        a.integer(8, colour)
        a.emit(58, 6, 1)
        a.global_(1, 'format')
        a.string(2, 'port_body_stat %d %d %s')
        a.integer(3, colour)
        a.move(5, 4)
        a.move(6, 5)
        a.native(0, 4)
        a.move(0, 2)
        a.global_(1, 'executeConsoleCommand')
        a.native(0, 1)
        a.clear(*range(9))
    module.code[start + 4:start + 8] = p32(max(frame, 9))
    hook(module, start + 8, a)
    return dict(sites=[hex(start + 4), hex(start + 8)], stat_details=True)


def patch_location_marker(module, lang):
    site = next(x['offset'] for x in rows(module) if x.get('text') == 'Going to location: ')
    a = Assembler(module)
    a.string(3, 'port_location_accepted ')
    a.move(0, 4)
    a.emit(36, 3)
    a.move(3, 5)
    a.global_(4, 'executeConsoleCommand')
    a.native(3, 1)
    a.clear(3, 4, 5)
    hook(module, site, a, 12)
    return dict(sites=[hex(site)], location_acceptance_marker=True)


def patch_stats(module, lang):
    r = rows(module)
    start = method(module, 'updateTooltip')
    stats_active = len(module.types)
    module.types += bytes([0])
    create = next(x['offset'] for x in r if start < x['offset'] and x.get('symbol') == 'Plane')
    format_at = next(x['offset'] for x in r if start < x['offset'] and x.get('symbol') == 'format')
    prepare_at = next(x['offset'] - 8 for x in r if format_at < x['offset'] and x.get('symbol') == 'prepare')
    # Full statistics fit once in the same original tooltip canvas.
    sites = []
    for x in r:
        if create <= x['offset'] < format_at and x['opcode'] == 1 and x['operands'][0] in (256, 64):
            module.code[x['offset'] + 4:x['offset'] + 8] = p32(512 if x['operands'][0] == 256 else 320)
            sites.append(hex(x['offset']))
    a = Assembler(module)
    poll(a, 0x66)
    a.emit(55, 0, 'normal')
    a.emit(14, 13, 0)
    a.emit(55, 0, 'normal')
    a.emit(14, 16, 0)
    a.emit(56, 0, 'has_canvas')
    a.raw(module.code[create:format_at])
    a.label('has_canvas')
    a.string(9, '')
    for colour in range(7):
        a.global_(1, 'format')
        a.string(2, '%s : %u%%')
        a.emit(14, 19, 4)
        a.integer(5, colour)
        a.emit(58, 3, 1)
        a.integer(4, 100)
        a.emit(14, 13, 7)
        a.integer(8, colour)
        a.emit(58, 6, 1)
        a.integer(7, 0)
        a.emit(58, 5, 1)
        a.emit(38, 4)
        a.emit(14, 13, 7)
        a.integer(8, colour)
        a.emit(58, 6, 1)
        a.integer(7, 1)
        a.emit(58, 5, 1)
        a.integer(6, 0)
        a.emit(50, 5)
        a.emit(55, 5, 'empty_bonus_' + str(colour))
        a.emit(14, 13, 7)
        a.integer(8, colour)
        a.emit(58, 6, 1)
        a.integer(7, 1)
        a.emit(58, 5, 1)
        a.emit(39, 4)
        a.emit(54, 0, 'bonus_ready_' + str(colour))
        a.label('empty_bonus_' + str(colour))
        a.integer(4, 0)
        a.label('bonus_ready_' + str(colour))
        a.emit(16, 4)
        a.native(0, 3)
        a.clear(1, 2, 3, 4, 5, 6, 7, 8)
        a.move(0, 10)
        a.emit(36, 9)
        if colour < 6:
            a.string(10, '\n')
            a.emit(36, 9)
        a.clear(0, 10)
    a.move(9, 0)
    a.clear(9)
    a.emit(54, 0, prepare_at)
    a.label('normal')
    module.code[start + 4:start + 8] = p32(11)
    hook(module, start + 8, a)
    render = method(module, 'renderTooltip') + 8
    a = Assembler(module)
    poll(a, 0x66)
    a.emit(55, 0, 'released')
    # A key press does not run the original hover-only tooltip update. Create
    # and prepare its canvas before reading the dimensions on the first hold.
    a.emit(14, stats_active, 0)
    a.emit(55, 0, 'refresh')
    a.emit(14, 16, 0)
    a.emit(55, 0, 'refresh')
    a.emit(14, 17, 0)
    a.emit(56, 0, 'ready')
    a.label('refresh')
    a.emit(63, 0, start)
    a.clear(0, 1, 2)
    a.emit(0, 0, 1)
    a.emit(13, 0, stats_active)
    a.label('ready')
    a.emit(14, 16, 0)
    a.emit(55, 0, 'normal')
    a.emit(14, 17, 0)
    a.emit(55, 0, 'normal')
    a.global_(0, 'Width')
    a.integer(1, 2)
    a.emit(39, 0)
    a.emit(14, 17, 2)
    a.integer(3, 0)
    a.emit(58, 1, 1)
    a.integer(2, 2)
    a.emit(39, 1)
    a.emit(37, 0)
    a.move(0, -5)
    a.global_(0, 'Height')
    a.integer(1, 2)
    a.emit(39, 0)
    a.emit(14, 17, 2)
    a.integer(3, 1)
    a.emit(58, 1, 1)
    a.integer(2, 2)
    a.emit(39, 1)
    a.emit(36, 0)  # Original rendering subtracts the prepared text height.
    a.move(0, -4)
    a.clear(0, 1, 2, 3)
    a.emit(54, 0, 'normal')
    a.label('released')
    a.emit(14, stats_active, 0)
    a.emit(55, 0, 'normal')
    # Restore or hide the regular hovered tooltip once when the hold ends.
    a.emit(0, 0, 0)
    a.emit(13, 0, stats_active)
    a.emit(63, 0, start)
    a.label('normal')
    a.clear(0, 1, 2, 3)
    hook(module, render, a)
    colour_name = next(i for i, x in enumerate(r) if x.get('text') == 'getLimfaColor' and x['offset'] > render)
    colour_call = next(x['offset'] for x in r[colour_name:] if x['opcode'] == 57)
    a = Assembler(module)
    poll(a, 0x66, 4)
    a.emit(55, 4, 'normal')
    a.integer(3, 0)  # The all-effects dialog has no hovered colour (-1).
    a.label('normal')
    a.clear(4, 5, 6)
    hook(module, colour_call, a)
    return dict(sites=sites + [hex(start + 4), hex(start + 8), hex(render), hex(colour_call)],
                stats_active_global=stats_active)


def patch_map(module, lang):
    r = rows(module)
    start = method(module, 'onSetPath')
    transition = next(i for i, x in enumerate(r) if x['offset'] > start and x['opcode'] == 67)
    accepted = r[transition - 3:transition]
    assert [(x['opcode'], x['register'], x['operands']) for x in accepted] == [
        (10, -6 if module.legacy else -7, [0]), (10, -5 if module.legacy else -6, [1]), (10, -4 if module.legacy else -5, [2])]
    a = Assembler(module)
    a.global_(1, 'executeConsoleCommand')
    a.string(2, 'port_path_ready')
    a.native(0, 1)
    a.clear(0, 1, 2)
    # Only World's accepted path branch reaches here; the Map UI also sends
    # onSetPath for empty or incorrectly started strokes.
    hook(module, accepted[0]['offset'], a)
    return dict(sites=[hex(accepted[0]['offset'])], accepted_path_marker=True)


def patch_map_rearm(module, lang):
    instructions = list(module.instructions())
    r = rows(module)
    notify = next(i for i, x in enumerate(r) if x.get('text') == 'onSetPath')
    tail = next(x for x in r[notify:] if x['opcode'] == 67)
    assert tail['register'] == (1 if module.legacy else 2) and (tail['operands'][1] & 255) == 0
    activate = method(module, 'activate')
    armed = next(x for x in r if x['offset'] > activate and x['opcode'] == 67)
    assert armed['register'] == (4 if module.legacy else 6) and armed['operands'][1] == 0
    base_ctor = tail['operands'][0]
    setup = next(x['operands'][0] for x in r if x['offset'] > base_ctor and x['opcode'] == 63)
    ready = next(x for x in r if x['offset'] > setup and x['opcode'] == 66)
    assert module.contexts[ready['register']]['parent'] == tail['register']
    initialize = next(x['operands'][0] for x in reversed(r)
                      if setup < x['offset'] < ready['offset'] and x['opcode'] == 63)
    pending = len(module.types)
    module.types += bytes([0])
    a = Assembler(module)
    poll(a, 0x1d, 5)
    a.emit(13, 5, pending)
    a.clear(5)
    # Keep the original base transition AND its following local cleanup.
    # Entering child6 directly from the unrelated stroke state preserves vector
    # fields where parent2 requires tracked entities and other typed fields.
    hook(module, tail['offset'], a, 12)
    frame = next(x['frame_slots'] for x in instructions if x.get('header') and x['offset'] == setup)
    module.code[setup + 4:setup + 8] = p32(frame + 3)
    a = Assembler(module)
    a.emit(14, pending, frame)
    a.emit(55, frame, 'normal')
    a.emit(0, frame + 1, 0)
    a.emit(13, frame + 1, pending)
    poll(a, 0x1d, frame)
    a.emit(55, frame, 'normal')
    a.clear(frame, frame + 1, frame + 2)
    # Base setup has now rebuilt the 24 correctly typed parent fields. This is
    # the original immediate child-entry seam, so no later pending jump can be
    # overwritten by the original base-loop PUSH that follows it.
    a.emit(66, armed['register'], armed['operands'][0], 0)
    a.emit(65)
    a.label('normal')
    a.clear(frame, frame + 1, frame + 2)
    hook(module, ready['offset'], a, 12)
    return dict(sites=[hex(tail['offset']), hex(setup + 4), hex(ready['offset'])],
                rearm_tail=tail['offset'], armed_ctor=armed['operands'][0],
                released_ctor=base_ctor, pending_global=pending, rearm_ready=ready['offset'],
                base_setup=setup, base_initializer=initialize,
                base_loop_context=ready['register'], base_loop_ctor=ready['operands'][0])


def patch_vein(module, lang):
    instructions = list(module.instructions())
    r = rows(module)
    colour = next(i for i, x in enumerate(r) if x.get('symbol') == 'setLocalGeomParameterColor')
    call = next(x for x in r[colour:] if x['opcode'] == 57)
    header = max(x['offset'] for x in module.instructions() if x.get('header') and x['offset'] < call['offset'])
    caller = next(i for i, x in enumerate(r) if x['opcode'] == 63 and x['operands'] == [header])
    assert r[caller - 2]['opcode'] == 14 and r[caller - 2]['register'] == 2
    assert r[caller - 2]['operands'] == [3] and r[caller - 1]['opcode'] == 63
    colour_getter = r[caller - 1]['operands'][0]
    initialized, last_gain = len(module.types), len(module.types) + 1
    # Channel wrappers cannot be serialized. Retain only scalar state; the
    # original getter reconstructs the color from the saved Limfa index G2.
    module.types += bytes([0, 2])
    a = Assembler(module)
    a.emit(0, 8, 1)
    a.emit(13, 8, initialized)
    a.get_setting('PortVeinBrightness', 6, 'asFloat')
    a.emit(13, 6, last_gain)
    a.integer(7, 100)
    a.emit(39, 6)
    a.emit(38, 5)
    a.clear(6, 7, 8, 9)
    module.code[header + 4:header + 8] = p32(10)
    hook(module, call['offset'], a)
    sites = [hex(header + 4), hex(call['offset'])]
    yield_sites = []
    for i, row in enumerate(instructions):
        if row.get('opcode') != 68:
            continue
        owner = max((x for x in instructions if x.get('header') and x['offset'] < row['offset']),
                    key=lambda x: x['offset'])
        base = owner['frame_slots']
        module.code[owner['offset'] + 4:owner['offset'] + 8] = p32(base + 7)
        a = Assembler(module)
        a.emit(14, initialized, base)
        a.emit(55, base, 'unchanged')
        a.get_setting('PortVeinBrightness', base, 'asFloat')
        a.emit(14, last_gain, base + 1)
        a.emit(46, base)
        a.emit(56, base, 'unchanged')
        a.emit(14, 2, base + 3)
        a.emit(63, base + 4, colour_getter)
        a.move(base + 2, base + 3)
        a.clear(base + 2)
        a.emit(63, base + 4, header)
        a.label('unchanged')
        a.clear(*range(base, base + 7))
        # YIELD is one word; replace only complete following instructions.
        length = 0
        for stolen in instructions[i:]:
            assert not stolen.get('header')
            length += stolen['size']
            if length >= 8:
                break
        assert not any(x.get('opcode') in (54, 55, 56) and
                       row['offset'] < x['operands'][0] < row['offset'] + length for x in instructions)
        hook(module, row['offset'], a, length)
        sites += [hex(owner['offset'] + 4), hex(row['offset'])]
        yield_sites.append(row['offset'])
    return dict(sites=sites, live_brightness=True, yield_sites=yield_sites,
                initialized_global=initialized, gain_global=last_gain,
                colour_getter=colour_getter, material_helper=header)


def patch_cancel(module, lang):
    instructions = list(module.instructions())
    functions = []
    for i, row in enumerate(instructions):
        if not row.get('header'):
            continue
        end = next((j for j in range(i + 1, len(instructions)) if instructions[j].get('header')), len(instructions))
        functions.append((row['offset'], instructions[i + 1:end]))
    release = next(at for at, code in functions if len(code) <= 6 and
                   any(x.get('opcode') == 64 and x['operands'] == [2] for x in code))
    completion = next(code for _, code in functions if len(code) >= 3 and
                      [x.get('opcode') for x in code[:2]] == [63, 63])
    cleanup = completion[:2]
    transitions = [x for x in completion if x.get('opcode') == 67]
    transition = transitions[-1] if transitions else None
    assert transition is None or transition['operands'][1] == 0, transition
    # DirectInput may deliver mouse-up before the queued window key event.
    frame = next(x['frame_slots'] for x in instructions if x['offset'] == release)
    a = Assembler(module)
    poll(a, 0x65, frame)
    a.emit(55, frame, 'normal')
    for call in cleanup:
        a.emit(63, frame, call['operands'][0])
    if transition:
        a.raw(module.code[transition['offset']:transition['offset'] + transition['size']])
    a.clear(*range(frame, frame + 4), -4)
    a.emit(65)
    a.label('normal')
    a.clear(*range(frame, frame + 4))
    module.code[release + 4:release + 8] = p32(frame + 4)
    hook(module, release + 8, a)
    changed = []
    for index, context in enumerate(module.contexts):
        if not any(m['name'] == 'onMouseButtonLeft' and m['code_offset'] == release for m in context['methods']):
            continue
        old = next((m for m in context['methods'] if m['name'] == 'onWinKeyDown'), None)
        a = Assembler(module)
        a.move(-5, 0)
        a.integer(1, 0x7d)
        a.emit(46, 0)
        a.emit(55, 0, 'normal')
        a.move(-4, 0)
        a.emit(55, 0, 'normal')
        for call in cleanup:
            a.emit(63, 0, call['operands'][0])
        if transition:
            a.raw(module.code[transition['offset']:transition['offset'] + transition['size']])
        a.emit(65)
        a.label('normal')
        if old:
            a.move(-5, 0)
            a.move(-4, 1)
            a.emit(63, 2, old['code_offset'])
        a.emit(65)
        at = len(module.code)
        module.code += p32(0xffffffff) + p32(6)
        module.code += a.finish(len(module.code))
        if old:
            old['code_offset'] = at
        else:
            context['methods'].append(dict(name='onWinKeyDown', args=2, signature=[1, 0], link=0xffffffff, code_offset=at))
        changed.append(index)
    assert changed
    return dict(sites=[hex(release + 4), hex(release + 8)], cancelled_contexts=changed,
                cancel_release=release)


def patch_menu_map_hint(module, lang):
    r = rows(module)
    text = next(i for i, x in enumerate(r) if x.get('text') == 'main_menu_save_game_disabled')
    call = r[text + 1]
    assert call['opcode'] == 57 and call['operands'] == [1]
    a = Assembler(module)
    a.string(call['register'], '')
    a.clear(call['register'] + 1, call['register'] + 2)
    a.emit(54, 0, call['offset'] + 8)
    module.code[call['offset']:call['offset'] + 8] = p32(module.opcode(54)) + p32(add(module, a))
    return dict(sites=[hex(call['offset'])], disabled_save_hint=call['offset'])


def patch_journal_video(module, lang):
    r = rows(module)
    video = next(x for x in r if x.get('symbol') == 'drawVideoScaled')
    start = max(x['offset'] for x in module.instructions() if x.get('header') and x['offset'] < video['offset'])
    frame = next(x['frame_slots'] for x in module.instructions() if x['offset'] == start)
    a = Assembler(module)
    a.global_(frame + 1, 'executeConsoleCommand')
    a.string(frame + 2, 'port_journal_video')
    a.native(frame, 1)
    a.clear(*range(frame, frame + 3))
    module.code[start + 4:start + 8] = p32(frame + 3)
    hook(module, start + 8, a)
    return dict(sites=[hex(start + 4), hex(start + 8)], journal_video_render=start)


def patch_body_memory_counts(module, lang):
    """During a Memory carry, each heart that can take the colour (empty, or
    of that colour) is published with its place on the screen, by the
    game's camera, and its exact amount: "port_zone_label zone x y current
    maximum" (x, y in the game's pixels, android/host/touch_native.c). The
    layer draws the numbers centred on the hearts, on its own backing, as
    its other cards (Controls.drawZoneLabels)."""
    r = rows(module)
    entries = list(module.instructions())
    callbacks = {m['code_offset'] for c in module.contexts for m in c['methods'] if m['name'] == 'onFreeLimfa'}
    carry = next(r[i + 1]['operands'][0] for i, x in enumerate(r[:-2])
                 if x['offset'] - 8 in callbacks and x['opcode'] == 10 and x['register'] == -4
                 and r[i + 1]['opcode'] == 67)
    base = next(x['operands'][0] for x in r if x['opcode'] == 67 and x['operands'][1] == 0)
    active = len(module.types)
    module.types += bytes([1])
    sites = []
    for start, taking in ((carry, True), (base, False)):
        frame = next(x['frame_slots'] for x in entries if x['offset'] == start)
        a = Assembler(module)
        if taking:
            a.move(-4, frame)
            a.emit(21, frame)
        else:
            a.integer(frame, 0)
        a.emit(13, frame, active)
        a.global_(frame + 1, 'executeConsoleCommand')
        a.string(frame + 2, 'setting PortBodyPut 0')
        a.native(frame, 1)
        a.clear(frame, frame + 1, frame + 2)
        module.code[start + 4:start + 8] = p32(frame + 3)
        hook(module, start + 8, a)
        sites += [hex(start + 4), hex(start + 8)]
    render = method(module, 'render')
    images = next(x['operands'][0] for x in r if x['offset'] > render and x['opcode'] == 63)
    tail = next(x['offset'] for x in r if x['offset'] > images and x['opcode'] == 65) - 4
    assert next(x for x in r if x['offset'] == tail)['opcode'] == 74
    frame = next(x['frame_slots'] for x in entries if x['offset'] == images)
    a = Assembler(module)
    a.get_setting('PortTouchInput', frame, 'asBool')
    a.emit(55, frame, 'done')
    a.emit(14, active, frame)
    a.emit(55, frame, 'done')
    a.integer(frame + 1, 1)
    a.emit(37, frame)
    colour, zone, inventory = frame, frame + 1, frame + 2
    # r(frame+3): Properties; r(frame+4): hero; scratch starts at frame+6.
    a.emit(14, 7, frame + 8)
    a.member(frame + 7, 'call')
    a.string(frame + 8, 'getPlayerEntity')
    a.native(frame + 6, 1)
    a.move(frame + 6, frame + 8)
    a.member(frame + 7, 'Properties')
    a.move(frame + 7, frame + 3)
    a.member(frame + 6, 'ZoneLimfa')
    a.move(frame + 6, inventory)
    a.emit(14, 8, frame + 8)
    a.member(frame + 7, 'call')
    a.string(frame + 8, 'getHero')
    a.native(frame + 6, 1)
    a.move(frame + 6, frame + 4)
    a.integer(zone, 0)
    a.label('zone')
    a.move(inventory, frame + 7)
    a.move(zone, frame + 8)
    a.emit(20, frame + 8)
    a.emit(58, frame + 6, 1)
    a.move(frame + 6, frame + 5)
    a.move(frame + 5, frame + 7)
    a.integer(frame + 8, 3)
    a.emit(58, frame + 6, 1)
    a.emit(55, frame + 6, 'next')
    a.move(frame + 5, frame + 7)
    a.integer(frame + 8, 0)
    a.emit(58, frame + 6, 1)
    a.emit(56, frame + 6, 'matching')
    a.emit(54, 0, 'label')
    a.label('matching')
    a.move(frame + 5, frame + 7)
    a.integer(frame + 8, 2)
    a.emit(58, frame + 6, 1)
    a.move(colour, frame + 7)
    a.emit(46, frame + 6)
    a.emit(55, frame + 6, 'next')
    a.label('label')
    a.emit(14, 7, frame + 9)
    a.member(frame + 8, 'Properties')
    a.member(frame + 7, 'get')
    a.string(frame + 8, 'Body/Zone')
    a.move(zone, frame + 9)
    a.emit(20, frame + 9)
    a.emit(36, frame + 8)
    a.native(frame + 6, 1)
    a.move(frame + 6, frame + 8)
    a.member(frame + 7, 'MaxLimfa')
    a.member(frame + 6, 'asInt')
    a.move(frame + 6, frame + 17)                 # r17: the heart's maximum
    a.move(frame + 5, frame + 8)
    a.integer(frame + 9, 0)
    a.emit(58, frame + 7, 1)
    a.integer(frame + 8, 999)
    a.emit(36, frame + 7)
    a.integer(frame + 8, 1000)
    a.emit(39, frame + 7)
    a.move(frame + 7, frame + 16)                 # r16: what it holds, rounded up
    # Its place: the camera's projection of the hero's pt_zone<N>.
    a.move(frame + 4, frame + 8)
    a.member(frame + 7, 'makeAttachPoint')
    a.string(frame + 8, 'pt_zone')
    a.move(zone, frame + 9)
    # The hero's points are pt_zone1..pt_zone21 for the zones 0..20 in both
    # games, as the body's own render names them; "pt_zone0" is no point, and
    # its null stopped the body screen once zone 0 was open.
    a.integer(frame + 10, 1)
    a.emit(36, frame + 9)
    a.emit(20, frame + 9)
    a.emit(36, frame + 8)
    a.native(frame + 6, 1)
    a.move(frame + 6, frame + 9)
    a.member(frame + 8, 'Position')
    a.move(frame + 8, frame + 9)
    a.emit(14, 9, frame + 8)
    a.member(frame + 7, 'pointToScreenSpace')
    a.move(frame + 9, frame + 8)
    a.native(frame + 6, 1)                        # r6: the point on the screen
    a.move(frame + 6, frame + 19)
    a.member(frame + 18, 'x')
    a.emit(16, frame + 18)                        # r18: x, whole pixels
    a.move(frame + 6, frame + 14)
    a.member(frame + 13, 'y')
    a.emit(16, frame + 13)                        # r13: y
    # format("port_zone_label %d %d %d %d %d", zone, x, y, current, maximum)
    a.move(frame + 18, frame + 12)
    a.move(frame + 16, frame + 14)
    a.move(frame + 17, frame + 15)
    a.move(zone, frame + 11)
    a.global_(frame + 9, 'format')
    a.string(frame + 10, 'port_zone_label %d %d %d %d %d')
    a.native(frame + 8, 6)
    a.move(frame + 8, frame + 10)
    a.global_(frame + 9, 'executeConsoleCommand')
    a.native(frame + 8, 1)
    a.label('next')
    a.emit(21, zone)
    a.move(zone, frame + 6)
    a.integer(frame + 7, 21)
    a.emit(48, frame + 6)
    a.emit(56, frame + 6, 'zone')
    # A circle supplies the exact zone; use the original carry callback for debit/refund.
    a.get_setting('PortBodyPut', frame + 6)
    a.emit(55, frame + 6, 'done')
    a.move(frame + 6, zone)
    a.global_(frame + 7, 'executeConsoleCommand')
    a.string(frame + 8, 'setting PortBodyPut 0')
    a.native(frame + 6, 1)
    a.move(zone, frame + 6)
    a.integer(frame + 7, 1)
    a.emit(48, frame + 6)
    a.emit(56, frame + 6, 'done')
    a.move(zone, frame + 6)
    a.integer(frame + 7, 21)
    a.emit(50, frame + 6)
    a.emit(56, frame + 6, 'done')
    a.move(zone, frame + 6)
    a.integer(frame + 7, 1)
    a.emit(37, frame + 6)
    a.move(frame + 6, zone)
    a.move(inventory, frame + 7)
    a.move(zone, frame + 8)
    a.emit(20, frame + 8)
    a.emit(58, frame + 6, 1)
    a.move(frame + 6, frame + 5)
    a.move(frame + 5, frame + 7)
    a.integer(frame + 8, 3)
    a.emit(58, frame + 6, 1)
    a.emit(55, frame + 6, 'done')
    a.move(frame + 5, frame + 7)
    a.integer(frame + 8, 0)
    a.emit(58, frame + 6, 1)
    a.emit(55, frame + 6, 'put')
    a.move(frame + 5, frame + 7)
    a.integer(frame + 8, 2)
    a.emit(58, frame + 6, 1)
    a.move(colour, frame + 7)
    a.emit(46, frame + 6)
    a.emit(55, frame + 6, 'done')
    a.label('put')
    a.move(zone, frame + 6)
    a.emit(21, frame + 6)
    a.emit(13, frame + 6, module._touch_body_forced)
    a.integer(frame + 9, 0)
    a.integer(frame + 10, 0)
    a.emit(0, frame + 11, 1)
    a.emit(63, frame + 12, module._touch_body_put)
    a.move(zone, frame + 10)
    a.emit(63, frame + 11, module._touch_body_publisher)
    a.label('done')
    a.clear(*range(frame, frame + 20))
    module.code[images + 4:images + 8] = p32(frame + 20)
    hook(module, tail, a)
    sites += [hex(images + 4), hex(tail)]
    return dict(sites=sites, memory_counts_render=tail, memory_counts_global=active,
                memory_counts_carry=carry, memory_counts_reset=base)


def patch_body_tutorial(module, lang):
    """Keep the original manual Body lesson modal after a colour carry returns."""
    original = list(module.instructions())
    r = [x for x in original if not x.get('header')]

    def body(start):
        end = next((x['offset'] for x in original if x.get('header') and x['offset'] > start), len(module.code))
        return [x for x in r if start < x['offset'] < end]

    action = method(module, 'onInputAction')
    if module.legacy:
        # The 2008 close handlers already preserve their authored tutorial lock.
        for name in ('onInputAction', 'onReturn', 'onWinKeyDown'):
            assert any(x.get('text') == 'tutorial_end' for x in body(method(module, name)))
        return dict(sites=[], tutorial_guard='original_2008')

    close, = [x for x in body(action) if x['opcode'] == 67]
    close_state, close_constructor = close['register'], close['operands'][0]
    assert any(x.get('symbol') == 'destroy' for x in body(close_constructor))
    entries = [(action, (-5, -4))]
    for name in ('onReturn', 'onWinKeyDown'):
        candidates = {m['code_offset'] for c in module.contexts for m in c['methods'] if m['name'] == name}
        start, = [start for start in candidates if any(x['opcode'] == 67 and x['register'] == close_state
                  and x['operands'] == [close_constructor, 0] for x in body(start))]
        entries.append((start, () if name == 'onReturn' else (-5, -4)))
    zone_return, = [x for x in r if x['opcode'] == 67 and x['register'] == close_state
                    and x['operands'] == [close_constructor, 256] and any(
                        m['name'] == 'onReturn' and m['code_offset'] < x['offset']
                        and x in body(m['code_offset']) for c in module.contexts for m in c['methods'])]
    # The original carry Escape path refunds the same colour, then restores the base state.
    carry_keys = [m['code_offset'] for c in module.contexts for m in c['methods'] if m['name'] == 'onWinKeyDown'
                  and any(x.get('symbol') == 'ZoneLimfa' for x in body(m['code_offset']))]
    base, = {tuple((x['register'], x['operands'][0])) for start in carry_keys for x in body(start) if x['opcode'] == 67}
    marker = len(module.types)
    module.types += bytes([0])
    sites, close_sites = [], []
    init, demo = method(module, 'initUI'), method(module, 'initBodyDemonstration')
    for start, value in ((init, False), (demo, True)):
        # The existing initialization runs first; the marker is not a World/progress variable.
        call = next(x for x in body(start) if x['opcode'] == 63)
        site = call['offset'] + call['size']
        a = Assembler(module)
        a.emit(0, 0, value)
        a.emit(13, 0, marker)
        a.clear(0)
        hook(module, site, a)
        sites.append(hex(site))
    for start, args in entries:
        frame = next(x['frame_slots'] for x in original if x['offset'] == start)
        a = Assembler(module)
        a.emit(14, marker, frame)
        a.emit(55, frame, 'normal')
        a.clear(frame, *args)
        a.emit(65)
        a.label('normal')
        a.clear(frame)
        module.code[start + 4:start + 8] = p32(frame + 1)
        hook(module, start + 8, a, max(8, body(start)[0]['size']))
        close_sites.append(start + 8)
        sites += [hex(start + 4), hex(start + 8)]
    # Do not suppress this callback: the complete original refund and sound precede it.
    zone_entry = max(x['offset'] for x in original if x.get('header') and x['offset'] < zone_return['offset'])
    frame = next(x['frame_slots'] for x in original if x['offset'] == zone_entry)
    a = Assembler(module)
    a.emit(14, marker, frame)
    a.emit(55, frame, 'normal')
    a.clear(frame)
    a.emit(67, base[0], base[1], 256)
    a.emit(54, 0, zone_return['offset'] + zone_return['size'])
    a.label('normal')
    a.clear(frame)
    module.code[zone_entry + 4:zone_entry + 8] = p32(frame + 1)
    hook(module, zone_return['offset'], a, zone_return['size'])
    sites += [hex(zone_entry + 4), hex(zone_return['offset'])]
    return dict(sites=sites, tutorial_guard='per_body_window', marker_global=marker,
                init_ui_site=int(sites[0], 16), demo_site=int(sites[1], 16),
                init_ui_entry=init, demo_entry=demo,
                demo_initializer=next(x['operands'][0] for x in body(demo) if x['opcode'] == 63),
                close_entries=[start for start, _ in entries], close_sites=close_sites,
                zone_return_entry=zone_entry, zone_return_site=zone_return['offset'],
                normal_state=base[0], base_constructor=base[1],
                zone_return_original_state=close_state, zone_return_original_constructor=close_constructor)


def patch_harvest_stop(module, lang):
    instructions = list(module.instructions())
    r = rows(module)
    calls = []
    for i, row in enumerate(r):
        if row.get('symbol') != 'fade':
            continue
        call = next(x for x in r[i + 1:] if x['opcode'] == 57)
        window = [x for x in r[i + 1:] if x['offset'] < call['offset']]
        literals = {x['register']: x['operands'][0] for x in window if x['opcode'] == 1}
        if (call['register'] == row['register'] - 1 and call['operands'] == [2] and
                literals.get(row['register'] + 1) == 0 and literals.get(row['register'] + 2) == 1000):
            calls.append(call['offset'])
    assert calls
    sites = []
    for site in calls:
        owner = max((x for x in instructions if x.get('header') and x['offset'] < site), key=lambda x: x['offset'])
        base = owner['frame_slots']
        module.code[owner['offset'] + 4:owner['offset'] + 8] = p32(base + 3)
        a = Assembler(module)
        a.global_(base + 1, 'executeConsoleCommand')
        a.string(base + 2, 'port_harvest_stop')
        a.native(base, 1)
        a.clear(base, base + 1, base + 2)
        hook(module, site, a)
        sites += [hex(owner['offset'] + 4), hex(site)]
    return dict(sites=sites, harvest_stop_calls=calls)


def patch_context_helpers(module, lang):
    start = method(module, '_setHelper')
    frame = next(x['frame_slots'] for x in module.instructions() if x['offset'] == start)
    a = Assembler(module)
    a.get_setting('PortTouchInput', frame, 'asBool')
    a.emit(55, frame, 'original')
    a.string(-4, '')
    a.label('original')
    a.clear(*range(frame, frame + 4))
    module.code[start + 4:start + 8] = p32(frame + 4)
    hook(module, start + 8, a)
    return dict(sites=[hex(start + 4), hex(start + 8)])



PATCHES = [('Scripts\\ui\\hud.bin', patch_context_helpers), ('Scripts\\player.bin', patch_player), ('Scripts\\ui\\body.bin', patch_body),
           ('Scripts\\player.bin', patch_brush_live),
           ('Scripts\\world\\world.bin', patch_brush_capacity),
           ('Scripts\\world\\world.bin', patch_location_marker),
           ('Scripts\\world\\world.bin', patch_map),
           ('Scripts\\ui\\body.bin', patch_body_sources),
           ('Scripts\\ui\\body.bin', patch_body_details),
           ('Scripts\\ui\\body.bin', patch_body_memory_counts),
           ('Scripts\\ui\\body.bin', patch_body_tutorial),
           ('Scripts\\ui\\main_menu.bin', patch_menu_map_hint),
           ('Scripts\\ui\\database.bin', patch_journal_video),
           ('Scripts\\ui\\health_progress.bin', patch_body_progress),
           ('Scripts\\ui\\body_wheel.bin', patch_stat_details),
           ('Scripts\\ui\\body_free_limfa.bin', lambda m, l: patch_body_counts(m, l, 1)),
           ('Scripts\\ui\\body_active_limfa.bin', lambda m, l: patch_body_counts(m, l, 0)),
           ('Scripts\\ui\\paint_limfa.bin', lambda m, l: patch_body_counts(m, l, 0)),
           ('Scripts\\ui\\body_wheel.bin', patch_stats),
           ('Scripts\\ui\\map.bin', patch_map_rearm)]
PATCHES += [('Scripts\\' + name + '.bin', patch_vein) for name in (
    'vein_fort_rock', 'vein_arbocliff_rock', 'vein_zewB', 'vein_zewC', 'vein_fortC',
    'vein_zewA', 'vein_zewD', 'vein_fortD', 'vein_arbocliff_usual')]
PATCHES += [('Scripts\\ui\\' + name + '.bin', patch_cancel) for name in (
    'paint', 'tree', 'hunter', 'obscure', 'obscure_final')]
PATCHES += [('Scripts\\' + name + '.bin', patch_harvest_stop) for name in (
    'tree_sister', 'treeonlysprout', 'tree_bridgeship', 'tree_garden2_a', 'tree_garden2_b',
    'tree_garden2_c', 'tree_garden2_abig', 'tree_garden2_bbig', 'tree_garden2_cbig',
    'tree_garden2_dbig', 'tree_lemnamod', 'tree_foggyroots_bent', 'tree_foggyroots_ushan',
    'tree_bottles', 'tree_garden1b', 'tree_garden1', 'treesuper', 'fx\\fx_player_crystal')]
