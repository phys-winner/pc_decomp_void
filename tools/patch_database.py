"""ui/database.bin, the journal's encyclopedia: its long texts scroll.

The encyclopedia has three pages, each with a text drawn from a string
canvas (Plane.createStringCanvas, then canvas.prepareWrapped(text, y), which
draws the wrapped lines from y down and returns y plus their height):
  "8" (context 5): the colours' introduction and each colour's text, in a
      canvas half the screen high, centred at 5/8 of it - a longer text was
      cut off at the bottom;
  "Z" (context 4): the description of the chosen glyph beside its picture,
      in a canvas running off the bottom of the screen, under the buttons
      that play its sound and video;
  "S" (context 2): the hero's quests and the souls' notes, a page at a time:
      the wheel (or the arrows by the text) turned to the next quest or note.
Now each text is one column that the wheel moves smoothly (the touch
layer sends the wheel a finger's travel in the game's pixels: 1/120 notch a
pixel, a notch 120 pixels; android/app/src/org/thevoid/port/Controls.java):
  - prepareWrapped(text, 0) at the pages' sites becomes scrollPrepare(canvas,
    text, visible height): the text drawn at the top, the scroll range kept,
    the height returned no more than the canvas's (a long text starts at the
    top of its place instead of above it);
  - each frame of the pages' loops (their shared update) eases the shown
    offset towards the wanted one and draws the canvas again from -offset
    (lines above its top fall outside it);
  - onMouseWheel (the "S" page's, and new ones for "8" and "Z") moves the
    wanted offset, -120 pixels a notch, within the range;
  - "S" joins all the pages of the quests (or of the soul's notes), the
    newest first, with "* * *" between them: the page builder is run for
    each page with its text collected; the arrows move the column by most of
    its height;
  - "Z": the description's canvas ends above the sound and video buttons
    (128 pixels high at the bottom) instead of under them.
The state lives in globals added to the module (its types section declares
one per global: 0 bool, 1 int, 2 float, 3 object, 4 string). A conditional
jump on an object register (op55/op56) leaves the register void (the VM's
truth test releases it): the canvas is tested, then loaded again.
DEBUG = True logs the offsets to the game's log (logInfo, "[scroll]")."""
import struct

from gscript_binary import p32
from patch_native_menu import Assembler

SEPARATOR = "\n* * *\n"
EASE = 0.5            # of the remaining distance a frame
ARROW_STEP = 0.8      # of the visible height an arrow's press
Z_BUTTONS = 128 + 4   # the sound and video buttons' height (pixels), a margin
PAGES = 64            # at most, of a quest list or a soul's notes
S_TOP = 0.285         # of the screen's height: the "S" text's top (the glyphs end at about 0.28)
BAR_GAP = 3           # pixels right of the text's column
BAR_WIDTH = 2
BAR_MIN = 8.0         # the thumb's least length
BAR_COLOUR = (0.72, 0.72, 0.78)
MIN_FONT = 14         # the texts' font at least (pixels of the game's picture)
EIGHT_LEFT = 48       # the "8" text's left edge (pixels)


def f32(v):
    return struct.unpack("<I", struct.pack("<f", v))[0]


class Asm(Assembler):
    def gload(self, g, dest):
        self.emit(14, g, dest)

    def gstore(self, src, g):
        self.emit(13, src, g)

    def fload(self, ctx, field, dest):
        self.emit(12, field, dest, ctx)

    def fstore(self, ctx, src, field):
        self.emit(11, src, field, ctx)

    def flt(self, reg, v):
        self.emit(2, reg, f32(v))

    def call(self, x, target):
        self.emit(63, x, target)

    def jmp(self, target):
        self.emit(54, 0, target)

    def jz(self, reg, target):
        self.emit(55, reg, target)

    def jnz(self, reg, target):
        self.emit(56, reg, target)

    def ret(self):
        self.emit(65, 0)

    def debug(self, slot, text, *regs):
        """logInfo(text + " " + str(r) ...) when DEBUG (uses slot .. slot+3)."""
        if not DEBUG:
            return
        self.global_(slot + 1, "logInfo")
        self.string(slot + 2, "[scroll] " + text)
        for r in regs:
            self.string(slot + 3, " ")
            self.emit(36, slot + 2)
            self.move(r, slot + 3)
            self.emit(20, slot + 3)
            self.emit(36, slot + 2)
            self.clear(slot + 3)
        self.native(slot, 1)
        self.clear(slot, slot + 1, slot + 2)


DEBUG = False


def headers(module):
    return [r["offset"] for r in module.instructions() if r.get("header")]


def function_rows(module, header):
    out, inside = [], False
    for r in module.instructions():
        if r.get("header"):
            if inside:
                break
            inside = r["offset"] == header
            continue
        if inside:
            out.append(r)
    return out


def function_of(heads, offset):
    return max(h for h in heads if h <= offset)


def method(module, ctx, name, args):
    return next(m for m in module.contexts[ctx]["methods"] if m["name"] == name and m["args"] == args)


def patch_legacy_database(module):
    """Keep the early journal's pages and pagination; scroll each visible text canvas."""
    from patch_touch_native import hook, add
    from patch_readability import scratch
    rows = [r for r in module.instructions() if not r.get('header')]
    sites, groups, wheels = [], {}, {}
    # The glyph, upper/lower notes and colour pages use separate canvases.
    keys = [(20,), (6, 8), (6, 11), (7, 2)]
    for key in keys:
        base = len(module.types)
        groups[key] = tuple(range(base, base + 5))  # canvas, text, height, range, offset
        module.types += bytes([3, 3, 2, 2, 2])

    def load_key(row):
        return (row['register'],) if row['opcode'] == 14 else (row['operands'][1], row['register']) if row['opcode'] == 12 else None

    for i, row in enumerate(rows):
        if row.get('symbol') not in ('createStringCanvas', 'prepareWrapped'):
            continue
        reg = row['register'] - 1
        call = next(j for j in range(i + 1, len(rows)) if rows[j]['opcode'] == 57 and rows[j]['register'] == reg)
        if row['symbol'] == 'createStringCanvas':
            store = next((x for x in rows[call + 1:call + 7] if x['opcode'] in (11, 13)), None)
            if store is None:
                continue
            key = (store['operands'][0],) if store['opcode'] == 13 else (store['operands'][1], store['operands'][0])
            if key not in groups:
                continue
            height = groups[key][2]
            a = Asm(module)
            if key == (20,):
                # The old canvas extends under the audio/video buttons and off-screen.
                base, frame_site = scratch(module, rows[call]['offset'], 3)
                a.global_(base, 'Height'); a.flt(base + 1, .5); a.emit(38, base)
                a.integer(base + 1, 224); a.fload(3, 1, base + 2); a.emit(38, base + 1)
                a.emit(36, base); a.integer(base + 1, Z_BUTTONS); a.emit(37, base)
                a.move(base, reg + 4); a.clear(base, base + 1, base + 2)
                sites.append(frame_site)
            a.gstore(reg + 4, height)
            hook(module, rows[call]['offset'], a)
            sites.append(hex(rows[call]['offset']))
            continue
        key = load_key(rows[i - 1])
        if key not in groups:
            continue  # the old pagination's measuring canvas is not drawn
        canvas, text, height, maximum, offset = groups[key]
        a = Asm(module)
        a.gstore(reg + 2, canvas)
        hook(module, row['offset'], a)
        sites.append(hex(row['offset']))
        a = Asm(module)
        a.gstore(reg + 2, text)
        hook(module, rows[call]['offset'], a)
        sites.append(hex(rows[call]['offset']))
        after = rows[call + 1]
        base, frame_site = scratch(module, after['offset'], 3)
        a = Asm(module)
        a.flt(base, 0); a.gstore(base, offset)
        a.move(reg, base); a.gload(height, base + 1); a.emit(37, base)
        a.move(base, base + 1); a.flt(base + 2, 0); a.emit(48, base + 1)
        a.jz(base + 1, 'positive')
        a.flt(base, 0)
        a.label('positive'); a.gstore(base, maximum)
        a.move(reg, base); a.gload(height, base + 1); a.emit(50, base)
        a.jz(base, 'done')
        a.gload(height, reg)  # keep the original centering inside the visible canvas
        a.label('done'); a.clear(base, base + 1, base + 2)
        hook(module, after['offset'], a, after['size'])
        sites += [frame_site, hex(after['offset'])]

    for key, (canvas, text, height, maximum, offset) in groups.items():
        a = Asm(module)
        a.gload(canvas, 0); a.jz(0, 'done')
        a.gload(offset, 1); a.move(-4, 2); a.flt(3, -120); a.emit(38, 2); a.emit(36, 1)
        a.move(1, 2); a.flt(3, 0); a.emit(48, 2); a.jz(2, 'low')
        a.flt(1, 0)
        a.label('low'); a.move(1, 2); a.gload(maximum, 3); a.emit(50, 2); a.jz(2, 'high')
        a.gload(maximum, 1)
        a.label('high'); a.gstore(1, offset)
        a.flt(2, -1); a.emit(38, 1); a.move(1, 4)
        a.gload(canvas, 2); a.member(1, 'prepareWrapped'); a.gload(text, 2); a.move(4, 3)
        a.native(0, 2)
        a.label('done'); a.clear(*range(5), -6, -5, -4); a.ret()
        start = len(module.code)
        module.code += p32(0xffffffff) + p32(5)
        module.code += a.finish(len(module.code))
        wheels[key] = start
    # The two note panes scroll independently under the finger.
    a = Asm(module)
    a.move(-5, 0); a.global_(1, 'Height'); a.flt(2, .5); a.emit(38, 1); a.emit(48, 0)
    a.jz(0, 'lower'); a.clear(0, 1, 2); a.jmp(wheels[(6, 8)] + 8)
    a.label('lower'); a.clear(0, 1, 2); a.jmp(wheels[(6, 11)] + 8)
    note_wheel = len(module.code)
    module.code += p32(0xffffffff) + p32(5)
    module.code += a.finish(len(module.code))
    for ctx, target in ((2, wheels[(20,)]), (3, wheels[(20,)]), (6, note_wheel), (7, wheels[(7, 2)])):
        assert not any(m['name'] == 'onMouseWheel' for m in module.contexts[ctx]['methods'])
        module.contexts[ctx]['methods'].append(dict(name='onMouseWheel', args=3, signature=[1, 1, 2], link=0xffffffff, code_offset=target))
    return dict(sites=sites, legacy_scroll_groups=list(groups.values()), legacy_wheels=list(wheels.values()), note_wheel=note_wheel)


def patch_database(module, lang):
    if module.legacy:
        return patch_legacy_database(module)
    original = bytes(module.code)
    rows = [r for r in module.instructions() if not r.get("header")]
    heads = headers(module)
    at = {r["offset"]: i for i, r in enumerate(rows)}
    sites = []

    def jump_from(row, target):
        """The instruction at row becomes a jump to target (its other words
        cleared registers, never run): the trampoline goes on from there."""
        o, n = row["offset"], row["size"]
        assert n >= 8 and bytes(module.code[o:o + n]) == original[o:o + n]
        module.code[o:o + n] = p32(module.opcode(54)) + p32(target) + b"".join(p32(74) for _ in range((n - 8) // 4))
        sites.append(hex(o))

    def append(a, slots=None):
        offset = len(module.code)
        if slots is not None:
            module.code += p32(0xffffffff) + p32(slots)
        module.code += a.finish(len(module.code))
        return offset

    # The symbols this module names its own way (a property resolves only by
    # the module's own pool entry).
    pw_rows = [r for r in rows if r["opcode"] == 60 and r.get("symbol") == "prepareWrapped"]
    PW = pw_rows[0]["operands"][0]
    Y = next(r["operands"][0] for r in rows if r["opcode"] == 60 and r.get("symbol") == "y")
    HEIGHT = next(r["operands"][0] for r in rows if r["opcode"] == 71 and r.get("symbol") == "Height")

    # The globals.
    base = len(module.types)
    G_CANVAS, G_TEXT, G_Y, G_SHOWN, G_MAX, G_VIS, G_COLLECT, G_LAST = range(base, base + 8)
    module.types += bytes([3, 3, 2, 2, 2, 2, 1, 3])

    # The "S" page: its text layout (one text: normalised, prepared, centred
    # between fields 14 and 15), its page builder (from field 2, the page
    # counted from the newest), its wheel and its arrows.
    wheel2 = method(module, 2, "onMouseWheel", 3)
    wheel_rows = function_rows(module, wheel2["code_offset"])
    calls = [r for r in wheel_rows if r["opcode"] == 63]
    assert len(calls) == 2
    LAYOUT = calls[1]["operands"][0]
    s_site = next(r for r in pw_rows if rows[at[r["offset"]] - 1]["opcode"] == 12
                  and rows[at[r["offset"]] - 1]["operands"][1] == 2)
    TEXT = function_of(heads, s_site["offset"])
    assert rows[at[TEXT + 8]].get("symbol") == "splitString"

    # scrollPrepare(canvas, text, visible) -> the height to place it by.
    a = Asm(module)
    a.debug(8, "prepare", -6, -4)
    a.emit(10, -6, 0); a.gstore(0, G_CANVAS); a.clear(0)
    a.emit(10, -5, 0); a.gstore(0, G_TEXT); a.clear(0)
    a.emit(10, -4, 0); a.emit(17, 0); a.gstore(0, G_VIS); a.clear(0)
    a.emit(10, -6, 2); a.emit(60, 1, PW); a.clear(2)
    a.emit(10, -5, 2); a.integer(3, 0)
    a.native(0, 2)                                   # r0 = the text's height
    a.clear(1, 2, 3)
    a.emit(17, 0)
    a.move(0, 4); a.gload(G_VIS, 5); a.emit(37, 4)   # r4 = height - visible
    a.move(4, 6); a.flt(7, 0.0); a.emit(50, 6)
    a.jz(6, "fits")
    a.gstore(4, G_MAX)
    a.gload(G_VIS, 0)
    a.jmp("placed")
    a.label("fits")
    a.flt(4, 0.0); a.gstore(4, G_MAX)
    a.label("placed")
    a.flt(4, 0.0); a.gstore(4, G_Y); a.gstore(4, G_SHOWN)
    a.emit(10, 0, -7)
    a.clear(0, 4, 5, 6, 7)
    a.ret()
    PREPARE = append(a, 12)

    # scrollBy(pixels): the wanted offset, within the range.
    a = Asm(module)
    a.debug(4, "by", -4)
    a.gload(G_Y, 0)
    a.emit(10, -4, 1)
    a.emit(36, 0)
    a.move(0, 1); a.flt(2, 0.0); a.emit(48, 1)
    a.jz(1, "low")
    a.flt(0, 0.0)
    a.label("low")
    a.move(0, 1); a.gload(G_MAX, 2); a.emit(50, 1)
    a.jz(1, "high")
    a.gload(G_MAX, 0)
    a.label("high")
    a.gstore(0, G_Y)
    a.clear(0, 1, 2)
    a.ret()
    SCROLL_BY = append(a, 8)

    # onMouseWheel(x, y, notches): -120 pixels a notch.
    a = Asm(module)
    a.emit(10, -4, 1)
    a.flt(2, -120.0)
    a.emit(38, 1)
    a.clear(2)
    a.call(2, SCROLL_BY)
    a.clear(1)
    a.ret()
    WHEEL = append(a, 3)

    # A frame: the shown offset eases to the wanted one; the canvas is drawn
    # again from -offset. (No collecting spans frames.)
    a = Asm(module)
    a.integer(0, 0); a.gstore(0, G_COLLECT)
    a.gload(G_CANVAS, 0)
    a.jz(0, "end")                                  # (the test uses r0 up)
    a.gload(G_Y, 1)
    a.gload(G_SHOWN, 2)
    a.move(1, 3); a.move(2, 4); a.emit(37, 3)        # r3 = wanted - shown
    a.move(3, 4); a.flt(5, 0.0); a.emit(46, 4)
    a.jnz(4, "end")
    a.move(3, 4); a.move(3, 5); a.emit(38, 4)
    a.flt(5, 1.0); a.emit(48, 4)                     # under a pixel: there
    a.jz(4, "ease")
    a.move(1, 2)
    a.jmp("set")
    a.label("ease")
    a.move(3, 4); a.flt(5, EASE); a.emit(38, 4)
    a.move(4, 5); a.move(2, 4); a.emit(36, 4)
    a.move(4, 2)
    a.label("set")
    a.debug(11, "tick", 1, 2)
    a.gstore(2, G_SHOWN)
    a.gload(G_CANVAS, 8); a.emit(60, 7, PW); a.clear(8)
    a.gload(G_TEXT, 8)
    a.flt(9, 0.0); a.move(2, 10); a.emit(37, 9); a.emit(16, 9)
    a.native(6, 2)
    a.clear(6, 7, 8, 9, 10)
    a.label("end")
    a.clear(0, 1, 2, 3, 4, 5)
    a.ret()
    TICK = append(a, 15)

    # The "S" page's pages joined: the builder run for page 0, 1, ... (until
    # it holds to the last), each text collected by the layout; then the
    # layout of them all. The entity (field 1: the quest it computes, or the
    # soul) is kept, the page is 0 again.
    a = Asm(module)
    a.fload(2, 1, 0)
    a.integer(1, 1); a.gstore(1, G_COLLECT)
    a.string(4, "")
    a.integer(6, 0)
    a.integer(1, 0)
    a.label("loop")
    a.move(1, 2); a.integer(3, PAGES); a.emit(48, 2)
    a.jz(2, "done")
    a.fstore(2, 1, 2)
    a.call(8, LAYOUT)
    a.fload(2, 2, 2)
    a.move(1, 3); a.emit(47, 2)
    a.jnz(2, "done")
    a.move(6, 2); a.integer(3, 0); a.emit(50, 2)
    a.jz(2, "first")
    a.string(5, SEPARATOR); a.emit(36, 4); a.clear(5)
    a.label("first")
    a.gload(G_LAST, 5); a.emit(36, 4); a.clear(5)
    a.move(6, 2); a.emit(21, 2); a.move(2, 6)
    a.move(1, 2); a.emit(21, 2); a.move(2, 1)
    a.jmp("loop")
    a.label("done")
    a.integer(2, 0); a.gstore(2, G_COLLECT)
    a.move(6, 2); a.integer(3, 0); a.emit(46, 2)
    a.jz(2, "have")
    a.clear(4); a.gload(G_LAST, 4)                   # no page (no quests yet): its one text
    a.label("have")
    a.integer(2, 0); a.fstore(2, 2, 2)
    a.fstore(2, 0, 1)
    a.move(4, 7); a.clear(4)
    a.call(8, TEXT)
    a.clear(0, 1, 2, 3, 5, 6, 7)
    a.ret()
    JOINED = append(a, 8)

    # The layout, while collecting, keeps its text and returns.
    first = rows[at[TEXT + 8]]
    a = Asm(module)
    a.gload(G_COLLECT, 0)
    a.jz(0, "lay")
    a.clear(0)
    a.emit(10, -4, 0); a.gstore(0, G_LAST); a.clear(0)
    a.clear(-4)
    a.ret()
    a.label("lay")
    a.clear(0)
    a.raw(original[first["offset"]:first["offset"] + first["size"]])
    a.jmp(first["offset"] + first["size"])
    jump_from(first, append(a))

    # The prepareWrapped(text, 0) sites: canvas.prepareWrapped is in r(R+1)
    # (the canvas loaded into r(R+2) just before), the text in r(R+2), y
    # (0) goes to r(R+3), the result to rR. From y on: scrollPrepare.
    def z_visible(a, dest):
        """dest = the "Z" description's canvas height: from its top (the
        glyph's picture's, Height/2 - 224 s) to the buttons; s = field 1
        of context 3 (Height / 1200). Uses dest+1, dest+2."""
        a.emit(71, dest, HEIGHT); a.flt(dest + 1, 0.5); a.emit(38, dest)
        a.flt(dest + 1, 224.0); a.fload(3, 1, dest + 2); a.emit(38, dest + 1)
        a.emit(36, dest)
        a.flt(dest + 1, float(Z_BUTTONS)); a.emit(37, dest)
        a.clear(dest + 1, dest + 2)

    kinds = []
    for pw in pw_rows:
        i = at[pw["offset"]]
        load = rows[i - 1]
        r = pw["register"] - 1
        y0 = next(rows[k] for k in range(i, i + 12) if rows[k]["opcode"] == 1 and rows[k]["register"] == r + 3
                  and rows[k]["operands"] == [0] and rows[k + 1]["opcode"] == 57 and rows[k + 1]["register"] == r)
        after = rows[at[y0["offset"]] + 2]
        assert rows[at[y0["offset"]] + 1]["operands"] == [2]
        a = Asm(module)
        a.clear(r + 1)
        if load["opcode"] == 12 and load["operands"][1] == 2:      # "S": field 8, visible = field 7's y
            assert load["register"] == 8
            a.fload(2, 8, r + 1)
            a.fload(2, 7, r + 4); a.emit(60, r + 3, Y); a.clear(r + 4)
            kinds.append("S")
        elif load["opcode"] == 12 and load["operands"][1] == 5:    # "8": field 2, visible = field 4's y
            assert load["register"] == 2
            a.fload(5, 2, r + 1)
            a.fload(5, 4, r + 4); a.emit(60, r + 3, Y); a.clear(r + 4)
            kinds.append("8")
        else:                                                       # "Z": global 21
            assert load["opcode"] == 14 and load["register"] == 21, load
            a.gload(21, r + 1)
            z_visible(a, r + 3)
            kinds.append("Z")
        a.clear(r + 4, r + 5, r + 6)
        a.call(r + 4, PREPARE)
        a.clear(r + 3)
        a.jmp(after["offset"])
        jump_from(y0, append(a))
    assert sorted(kinds) == ["8", "8", "8", "S", "Z", "Z"], kinds

    # "Z": its canvas as high as the place above the buttons:
    # Height - 320 s (Height; 0x140; s; *; -) becomes z_visible.
    zc = 0
    for k, r in enumerate(rows):
        seq = rows[k:k + 6]
        if not (r["opcode"] == 71 and r.get("symbol") == "Height" and seq[1]["opcode"] == 1
                and seq[1]["operands"] == [0x140] and seq[2]["opcode"] == 12 and seq[2]["register"] == 1
                and seq[2]["operands"][1] == 3 and seq[3]["opcode"] == 38 and seq[4]["opcode"] == 37
                and seq[5]["opcode"] == 57 and seq[5]["operands"] == [3]):
            continue
        h = r["register"]
        assert seq[1]["register"] == h + 1 and seq[4]["register"] == h
        a = Asm(module)
        z_visible(a, h)
        a.jmp(seq[5]["offset"])
        jump_from(r, append(a))
        zc += 1
    assert zc == 4, zc

    # The pages' shared update (each frame of their loops): a scroll frame first.
    updates = [h for h in heads if any(x.get("symbol") == "updateCamera" for x in function_rows(module, h))
               and any(x.get("symbol") == "!rotateX" for x in function_rows(module, h))]
    assert len(updates) == 1, updates
    first = function_rows(module, updates[0])[0]
    assert first["size"] == 8
    a = Asm(module)
    a.call(4, TICK)
    a.raw(original[first["offset"]:first["offset"] + 8])
    a.jmp(first["offset"] + 8)
    jump_from(first, append(a))

    # "S": the builder's callers outside the wheel and the arrows show all
    # pages; so does choosing a soul (its newest note was laid out alone).
    for r in rows:
        if r["opcode"] == 63 and r["operands"] == [LAYOUT]:
            h = function_of(heads, r["offset"])
            if h in (wheel2["code_offset"], method(module, 2, "onMouseButtonLeft", 3)["code_offset"]):
                continue
            module.code[r["offset"] + 4:r["offset"] + 8] = p32(JOINED)
            sites.append(hex(r["offset"]))
    select = function_rows(module, method(module, 2, "onSelectItem", 1)["code_offset"])
    shown = [r for r in select if r["opcode"] == 63 and r["operands"] == [TEXT]]
    assert len(shown) == 3
    for r in shown:
        x = r["register"]
        a = Asm(module)
        a.clear(x - 1)
        a.call(x, JOINED)
        a.jmp(r["offset"] + 8)
        jump_from(r, append(a))

    # "S": the arrows (actions 5 up, 6 down) move the column.
    click = function_rows(module, method(module, 2, "onMouseButtonLeft", 3)["code_offset"])
    ret = click[-1]
    assert ret["opcode"] == 65
    arrows = 0
    for k, r in enumerate(click):
        if not (r["opcode"] == 12 and r["register"] == 2 and r["operands"] == [2, 2]
                and click[k + 1]["opcode"] in (21, 22) and click[k + 3]["operands"] == [LAYOUT]):
            continue
        a = Asm(module)
        a.gload(G_VIS, 2)
        a.flt(3, -ARROW_STEP if click[k + 1]["opcode"] == 21 else ARROW_STEP)
        a.emit(38, 2)
        a.clear(3)
        a.call(3, SCROLL_BY)
        a.clear(2)
        a.jmp(ret["offset"])
        jump_from(r, append(a))
        arrows += 1
    assert arrows == 2

    # A scrolling text shows where it is: a thin thumb right of its column.
    # bar(plane, x, y, width): the thumb as long as the visible share (8
    # pixels at least), as far down as the offset (plane.fill(x, y, w, h,
    # vec3)).
    FILL = next(r["operands"][0] for r in rows if r["opcode"] == 60 and r.get("symbol") == "fill")
    VEC3 = next(r["operands"][0] for r in rows if r["opcode"] == 71 and r.get("symbol") == "!vec3")
    WIDTH = next(r["operands"][0] for r in rows if r["opcode"] == 71 and r.get("symbol") == "Width")
    a = Asm(module)
    a.gload(G_MAX, 0); a.flt(1, 0.0); a.emit(50, 0)
    a.jz(0, "end")
    a.gload(G_MAX, 1); a.gload(G_VIS, 2); a.emit(36, 1)            # r1 = the text's height
    a.gload(G_VIS, 2); a.gload(G_VIS, 3); a.emit(38, 2)
    a.move(1, 3); a.emit(39, 2)                                     # r2 = the thumb's length
    a.move(2, 3); a.flt(4, BAR_MIN); a.emit(48, 3)
    a.jz(3, "long")
    a.flt(2, BAR_MIN)
    a.label("long")
    a.gload(G_SHOWN, 3); a.gload(G_MAX, 4); a.emit(39, 3)
    a.gload(G_VIS, 4); a.move(2, 5); a.emit(37, 4)
    a.emit(38, 3)                                                   # r3 = offset / range * (visible - length)
    a.emit(10, -5, 4); a.emit(36, 3)                                # ... + y
    a.emit(10, -7, 8); a.emit(60, 7, FILL); a.clear(8)
    a.emit(10, -6, 8); a.emit(10, -4, 9); a.emit(36, 8)
    a.flt(9, float(BAR_GAP)); a.emit(36, 8); a.emit(16, 8)
    a.move(3, 9); a.emit(16, 9)
    a.integer(10, BAR_WIDTH)
    a.move(2, 11); a.emit(16, 11)
    a.emit(71, 13, VEC3)
    for k, v in enumerate(BAR_COLOUR):
        a.flt(14 + k, v)
    a.native(12, 3)
    a.clear(13, 14, 15, 16)
    a.native(6, 5)
    a.clear(6, 7, 8, 9, 10, 11, 12)
    a.label("end")
    a.clear(0, 1, 2, 3, 4, 5)
    a.ret()
    BAR = append(a, 17)

    def bar_after(row, x_code, y_reg, width_code):
        """After row (the clear following a page's drawString of its text):
        bar(plane, x, y, width), then on (r6 .. r12 are free there)."""
        a = Asm(module)
        a.raw(original[row["offset"]:row["offset"] + row["size"]])
        a.emit(10, -4, 6)
        x_code(a, 7)
        a.move(y_reg, 8)
        width_code(a, 9)
        a.clear(10, 11, 12)
        a.call(10, BAR)
        a.clear(6, 7, 8, 9)
        a.jmp(row["offset"] + row["size"])
        jump_from(row, append(a))

    def drawn(ctx):
        """The clear after the render method's drawString of a text."""
        rs = function_rows(module, method(module, ctx, "render", 1)["code_offset"])
        k = max(i for i, r in enumerate(rs) if r["opcode"] == 60 and r.get("symbol") == "drawString")
        call = next(j for j in range(k, len(rs)) if rs[j]["opcode"] == 57 and rs[j]["operands"] == [4])
        assert rs[call + 1]["opcode"] in (77, 78) and rs[call + 1]["size"] == 12, rs[call + 1]
        return rs[call + 1]

    def same(reg):
        return lambda a, dest: a.move(reg, dest)

    def field_x(ctx, field, add=0.0):
        def code(a, dest):
            a.fload(ctx, field, dest + 1); a.emit(60, dest, X); a.clear(dest + 1)
            if add:
                a.flt(dest + 1, add); a.emit(36, dest); a.clear(dest + 1)
        return code

    def z_x(offset):
        """Width / 2 + offset s, as 4:render places the description."""
        def code(a, dest):
            a.emit(71, dest, WIDTH); a.integer(dest + 1, 2); a.emit(39, dest)
            a.integer(dest + 1, offset); a.fload(3, 1, dest + 2); a.emit(38, dest + 1)
            a.emit(36, dest)
            a.clear(dest + 1, dest + 2)
        return code

    def z_width(offset):
        """Width - 16 - (Width / 2 + offset s): the description's canvas out to
        the screen's right edge (its original 400 s + 8, 432 s + 8 held a
        dozen letters of the larger font a line). Uses dest+1 .. dest+3."""
        def code(a, dest):
            a.emit(71, dest, WIDTH)
            a.emit(71, dest + 1, WIDTH); a.integer(dest + 2, 2); a.emit(39, dest + 1)
            a.integer(dest + 2, offset); a.fload(3, 1, dest + 3); a.emit(38, dest + 2)
            a.emit(36, dest + 1)
            a.emit(37, dest)
            a.integer(dest + 1, 16); a.emit(37, dest)
            a.clear(dest + 1, dest + 2, dest + 3)
        return code

    # "Z": the description's canvas as wide (400 s or 432 s, + 8 in the
    # Russian release, became z_width of its 320 s or 344 s: op1 width; op12
    # s; op38 [; op1 8; op36]).
    zw = 0
    for k, r in enumerate(rows):
        seq = rows[k:k + 5]
        if not (r["opcode"] == 1 and r["operands"] in ([0x190], [0x1b0]) and seq[1]["opcode"] == 12
                and seq[1]["register"] == 1 and seq[1]["operands"] == [r["register"] + 1, 3]
                and seq[2]["opcode"] == 38 and seq[2]["register"] == r["register"]):
            continue
        end = seq[2]
        if seq[3]["opcode"] == 1 and seq[3]["operands"] == [8] and seq[4]["opcode"] == 36:
            end = seq[4]
        a = Asm(module)
        z_width(0x140 if r["operands"] == [0x190] else 0x158)(a, r["register"])
        a.jmp(end["offset"] + end["size"])
        jump_from(r, append(a))
        zw += 1
    assert zw == 4, zw

    # "8": its text starts at EIGHT_LEFT from the screen's left (the empty
    # side of the page) instead of Width / 2 - 720 s, its right edge where it
    # was (Width / 2 - 202 s + 16, before the colours' indicators): field 4's
    # x, the canvas's width less 16, is Width / 2 - 202 s - EIGHT_LEFT.
    left = 0
    for k, r in enumerate(rows):
        seq = rows[k:k + 4]
        if not (r["opcode"] == 1 and r["operands"] == [0x2d0] and seq[1]["opcode"] == 12
                and seq[1]["register"] == 1 and seq[1]["operands"][1] == 3 and seq[2]["opcode"] == 38
                and seq[3]["opcode"] == 37 and seq[3]["register"] == r["register"] - 1):
            continue
        a = Asm(module)
        a.flt(r["register"] - 1, float(EIGHT_LEFT))
        a.clear(r["register"])
        a.jmp(seq[3]["offset"] + seq[3]["size"])
        jump_from(r, append(a))
        left += 1
    assert left == 3, left
    wide = 0
    for k, r in enumerate(rows):
        seq = rows[k:k + 3]
        if not (r["opcode"] == 1 and r["operands"] == [0x206] and seq[1]["opcode"] == 12
                and seq[1]["register"] == 1 and seq[1]["operands"] == [r["register"] + 1, 3]
                and seq[2]["opcode"] == 38 and seq[2]["register"] == r["register"]):
            continue
        w = r["register"]
        a = Asm(module)
        a.emit(71, w, WIDTH); a.integer(w + 1, 2); a.emit(39, w)
        a.integer(w + 1, 202); a.fload(3, 1, w + 2); a.emit(38, w + 1)
        a.emit(37, w)
        a.flt(w + 1, float(EIGHT_LEFT)); a.emit(37, w)
        a.clear(w + 1, w + 2)
        a.jmp(seq[2]["offset"] + seq[2]["size"])
        jump_from(r, append(a))
        wide += 1
    assert wide == 1, wide

    X = next(r["operands"][0] for r in rows if r["opcode"] == 60 and r.get("symbol") == "x")
    # "S": at (x, y) of its drawString (r3, r4), as wide as field 7's x.
    row = drawn(2)
    assert row["opcode"] == 77
    bar_after(row, same(3), 4, field_x(2, 7))
    # "8": the same registers, as wide as field 4's x and 16.
    row = drawn(5)
    assert row["opcode"] == 77
    bar_after(row, same(3), 4, field_x(5, 4, 16.0))
    # "Z": its two drawStrings (5:4 screens at Width / 2 + 320 s in a canvas
    # 400 s + 8 wide, the others at + 344 s, 432 s + 8), y still in r2.
    rs = function_rows(module, method(module, 4, "render", 1)["code_offset"])
    z_bars = 0
    for k, r in enumerate(rs):
        if not (r["opcode"] == 60 and r.get("symbol") == "drawString"):
            continue
        call = next(j for j in range(k, len(rs)) if rs[j]["opcode"] == 57 and rs[j]["operands"] == [4])
        assert rs[call + 1]["opcode"] == 78
        assert [x["operands"] for x in rs[k:call] if x["opcode"] == 10] == [[7]]
        offset = next(x["operands"][0] for x in rs[k:call] if x["opcode"] == 1 and x["operands"][0] in (0x140, 0x158))
        bar_after(rs[call + 1], z_x(offset), 2, z_width(offset))
        z_bars += 1
    assert z_bars == 2, z_bars

    # "S": its text's place starts below the page's glyphs (8, Z, S) instead
    # of a quarter down the screen (field 14 = Height * 0.25; the canvas,
    # Height - field 14 - 128 high, shortens with it).
    top = 0
    for k, r in enumerate(rows):
        seq = rows[k:k + 5]
        if (r["opcode"] == 71 and r.get("symbol") == "Height" and seq[1]["opcode"] == 2
                and seq[1]["operands"] == [f32(0.25)] and seq[2]["opcode"] == 38 and seq[3]["opcode"] == 16
                and seq[4]["opcode"] == 11 and seq[4]["operands"] == [14, 2]):
            o = seq[1]["offset"]
            module.code[o + 4:o + 8] = p32(f32(S_TOP))
            sites.append(hex(o))
            top += 1
    assert top == 1, top

    # The texts' font: fontmain_N with N = 20 (18 on 4:3) * Height / 1200,
    # 8..28 - in proportion to the screen, so the port's interface scale (a
    # smaller picture for the game, Settings.gameSize) left it about as small
    # as it was (10 at 600 lines, 8 at 400). It is MIN_FONT at least, as
    # 1080 lines would have it: then it grows with the interface scale like
    # the other texts.
    init = function_rows(module, method(module, 1, "initDatabase", 1)["code_offset"])
    k = next(i for i, r in enumerate(init) if r.get("symbol") == "loadFont")
    plane = init[k - 1]
    assert plane["opcode"] == 71 and plane.get("symbol") == "Plane" and plane["size"] == 8
    assert init[k + 3]["opcode"] == 10 and init[k + 3]["register"] == 0    # the size, r0, to its text
    a = Asm(module)
    a.move(0, 1); a.integer(2, MIN_FONT); a.emit(48, 1)
    a.jz(1, "big")
    a.integer(0, MIN_FONT)
    a.label("big")
    a.clear(1, 2)
    a.raw(original[plane["offset"]:plane["offset"] + 8])
    a.jmp(plane["offset"] + 8)
    jump_from(plane, append(a))

    # The wheel: the "S" page's moves the column; "8" and "Z" get one.
    wheel2["code_offset"] = WHEEL
    for ctx in (4, 5):
        assert not any(m["name"] == "onMouseWheel" for m in module.contexts[ctx]["methods"])
        module.contexts[ctx]["methods"].append(dict(wheel2))
    return dict(sites=sites, globals=list(range(base, base + 8)), prepare=hex(PREPARE), tick=hex(TICK),
                joined=hex(JOINED), wheel=hex(WHEEL))
