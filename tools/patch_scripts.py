"""The port's patches of game scripts for Android, keyed by the original file.

    python tools/patch_scripts.py

For every supported release with an index (research/vfs-index*.json) the patches
below are applied to that release's own scripts; each result goes to
build/overrides/<sha256 of the original>/<VFS path> and is listed in
build/overrides/index.json. The APK carries them as assets; the activity
copies the ones whose original matches the running release into
<data>/overrides, where android/host/files.c serves them as loose files
(the game looks for loose files before its archives).

Patches read the port's settings from the game's own Settings (its
data\\settings.xml, the player's copy in <data>/overrides; keys Port*, which
the activity adds with their defaults), so the game's options menu can
change them:
  Scripts\\player.bin            PortHeadBob 0: the walking camera's
                                 "headbobbing" animation plays at scale 0.
  Scripts\\world\\main_menu.bin   PortSkipIntro 1: the opening videos are not
                                 played; the menu starts at once.
  Scripts\\ui\\main_menu.bin      the options menu gets the port's pages (a
                                 fourth tab): tools/patch_options.py.
  Scripts\\ui\\paint_limfa.bin    the active colour's name and amount stay at the
                                 top left while painting, larger and lighter.
  Scripts\\ui\\database.bin       the journal's long texts scroll smoothly (the
                                 wheel, a finger); the souls' pages are one
                                 column: tools/patch_database.py.
New images made from the release's (keyed by their "source"):
  Textures\\ui\\port_arrow_left, _right (and _mask): the side arrows that
                                 turn options' pages, twice the journal's.
Patch sites are found by their instructions, not fixed offsets, and every
original byte outside the patched instructions is kept (checked).

The game's hints name the key of an action ("Open the Soul Obscura - (B)",
"(RMB)" by a tree, the brush's key on the map) from
Properties\\Strings\\keys.txt; its names of the keys the touch controls
send become the names of those controls (the left button a tap, the right
one the hand, L Ctrl the brush, Space the next button, B the heart...).
The options' mouse settings (Properties\\Strings\\menu.txt) turn the view
by swipes and the gyroscope: they are named the view's. The release's
data\\actions.xml (a loose file) skips cutscenes and lines of dialogue on
Enter instead of Space, which stays the jump: the touch layer's next button
sends Enter, and the hints name the next button and the jump apart.
"""
import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path
import re
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from gscript_binary import Module, p32  # noqa: E402
from patch_native_menu import Assembler  # noqa: E402
from patch_options import patch_options  # noqa: E402
from patch_database import patch_database  # noqa: E402

OUT = ROOT / "build/overrides"
# The 2008 opcode encoding is normalized by Module(legacy=True).
INDEXES = {"research/vfs-index.json": "ru", "research/vfs-index.german.json": "de",
           "research/vfs-index.polish.json": "pl"}


def read_entry(index_path, name):
    index = json.loads((ROOT / index_path).read_text(encoding="utf-8"))
    for container in index["containers"]:
        for entry in container["entries"]:
            if entry["name"].lower() == name.lower():
                with open(Path(index["source"]) / container["name"], "rb") as f:
                    f.seek(entry["offset"])
                    return f.read(entry["size"])
    return None


def rows_of(module):
    return [r for r in module.instructions() if not r.get("header")]


def jump_patch(module, original, offset, length, target):
    """Replace the instruction(s) of `length` bytes at offset by a jump to
    target, padded with clears of r0 (never run: the jump passes them)."""
    assert length >= 8 and length % 4 == 0
    code = p32(module.opcode(54)) + p32(target) + b"".join(p32(74) for _ in range((length - 8) // 4))
    assert bytes(module.code[offset:offset + length]) == original[offset:offset + length]
    module.code[offset:offset + length] = code


def append(module, assembler):
    base = len(module.code)
    module.code += assembler.finish(base)
    return base


def patch_subtitle_timing(module, lang):
    """Reject a failed optional toInt result before indexing its timing."""
    rows = rows_of(module)
    at = next(i for i, row in enumerate(rows) if row.get("symbol") == "toInt")
    seq = rows[at:at + 10]
    assert [(row["opcode"], row["register"]) for row in seq] == [
        (71, 5), (10, 3), (1, 8), (58, 6), (57, 4),
        (75, 5), (18, 4), (10, 1), (10, 4), (1, 8)]
    assert seq[4]["operands"] == [1] and seq[7]["operands"] == [5]
    error = next(i for i, row in enumerate(rows)
                 if row.get("text") == "wrong number of timings in subtitles")
    error = rows[error - 1]
    assert error.get("symbol") == "logError" and error["register"] == 5
    original = bytes(module.code)
    site = seq[7]["offset"]
    a = Assembler(module)
    # toInt returns null for missing or malformed subtitle timing metadata.
    a.move(4, 5)
    a.emit(55, 5, error["offset"])
    a.raw(original[site:site + 8])
    a.emit(54, 0, site + 8)
    trampoline = append(module, a)
    jump_patch(module, original, site, 8, trampoline)
    return dict(sites=[hex(site)], subtitle_timing_guard=hex(trampoline))


def patch_damage_limfa_target(module, lang):
    """Let targetless damage particles enter their original cleanup state."""
    rows = rows_of(module)
    name = next(i for i, row in enumerate(rows) if row.get("text") == "getLimfaTargetOffset")
    call = next(i for i in range(name - 1, -1, -1) if rows[i].get("symbol") == "callDef")
    site = rows[call - 1]
    assert site["opcode"] == 14 and site["register"] == 1 and site["operands"] == [3]
    # The authored loop already retires the effect when its target is null,
    # but dereferences it for the initial offset before reaching that check.
    check = next(i for i in range(name + 1, len(rows) - 2)
                 if rows[i]["opcode"] == 14 and rows[i]["register"] == 1
                 and rows[i + 1]["opcode"] == 56 and rows[i + 2]["opcode"] == 66)
    assert rows[check]["operands"] == [rows[check + 1]["register"]]
    cleanup = rows[check + 2]
    assert cleanup["register"] == 4 and cleanup["operands"][1] == 0x400
    original = bytes(module.code)
    a = Assembler(module)
    a.raw(original[site["offset"]:site["offset"] + 8])
    a.emit(55, site["operands"][0], cleanup["offset"])
    # JZ consumes an object condition in the shipped VM (10146BA0). Reload
    # the retained global before the original callDef uses that register.
    a.raw(original[site["offset"]:site["offset"] + 8])
    a.emit(54, 0, site["offset"] + 8)
    trampoline = append(module, a)
    jump_patch(module, original, site["offset"], 8, trampoline)
    return dict(sites=[hex(site["offset"])], damage_limfa_target_guard=hex(trampoline),
                null_target_transition=hex(cleanup["offset"]))


def patch_head_bob(module, lang):
    """player.bin: playCameraAnimationScaled(0, "headbobbing", 1) gets the
    scale 1 or 0 from Settings PortHeadBob."""
    rows = rows_of(module)
    for i, r in enumerate(rows):
        if r.get("symbol") != "playCameraAnimationScaled" or r["opcode"] != 71:
            continue
        seq = rows[i:i + 5]
        if not (seq[1]["opcode"] == 1 and seq[2]["opcode"] == 3 and seq[2].get("text") == "headbobbing"
                and seq[3]["opcode"] == 1 and seq[3]["operands"] == [1] and seq[4]["opcode"] == 57):
            continue
        base = r["register"]
        assert [s["register"] for s in seq[:4]] == [base, base + 1, base + 2, base + 3]
        original = bytes(module.code)
        start, resume = r["offset"], seq[4]["offset"]
        head = original[start:seq[3]["offset"]]   # op71, op1, op3: the call's target and first arguments
        a = Assembler(module)
        a.get_setting("PortHeadBob", base, "asBool")
        a.emit(55, base, "off")
        a.clear(base)
        a.raw(head)
        a.integer(base + 3, 1)
        a.emit(54, 0, resume)
        a.label("off")
        a.clear(base)
        a.raw(head)
        a.emit(2, base + 3, struct.unpack("<I", struct.pack("<f", 0.0))[0])
        a.emit(54, 0, resume)
        tramp = append(module, a)
        jump_patch(module, original, start, 8, tramp)
        return dict(sites=[hex(start)], trampoline=hex(tramp))
    raise ValueError("player.bin: the headbobbing call was not found")


def patch_skip_intro(module, lang):
    """world/main_menu.bin: the state that plays the opening videos creates
    its UI plane, then a video window per file; with PortSkipIntro it goes
    from the plane straight to the main menu's transition."""
    rows = rows_of(module)
    # The first video window: createWindow("video.xml") after createUIPlane.
    plane = next(i for i, r in enumerate(rows) if r.get("symbol") == "createUIPlane")
    window = next(i for i in range(plane, len(rows)) if rows[i].get("text") == "video.xml")
    # The instruction that starts the window's setup (loads the plane back).
    setup = window
    while rows[setup]["opcode"] != 12:
        setup -= 1
    assert setup > plane
    # The end of the sequence: the state change after the last video loop.
    intro = next(i for i, r in enumerate(rows) if r.get("text") == "intro.the")
    change = next(i for i in range(intro, len(rows)) if rows[i]["opcode"] == 66)
    finish = change
    while rows[finish - 1]["opcode"] in (0, 4):   # the transition's arguments
        finish -= 1
    original = bytes(module.code)
    site = rows[setup]
    length = site["size"]
    a = Assembler(module)
    # Resolve through the game's own string manager, including loose translations.
    names = ["main_menu_new_game", "main_menu_load_game", "main_menu_save_game",
             "main_menu_save_game_disabled", "main_menu_options", "main_menu_credits",
             "main_menu_return_to_game", "main_menu_exit_game"]
    from generate_debug_levels import menu_catalog
    map_ids = menu_catalog("research/vfs-index.polish.json" if module.legacy else "research/vfs-index.json", names=False)[0]
    strings = list(enumerate(list(range(20009, 20016)) + names))
    strings += [(15 + number, 1000 + number) for number in map_ids]
    for index, name in strings:
        a.global_(1, "format")
        a.string(2, "port_hint %d %s")
        a.integer(3, index)
        a.global_(5, "getString" if isinstance(name, int) else "getNamedString")
        (a.integer if isinstance(name, int) else a.string)(6, name)
        a.native(4, 1)
        a.clear(5, 6)
        a.native(0, 3)
        a.move(0, 2)
        a.global_(1, "executeConsoleCommand")
        a.native(0, 1)
        a.clear(0, 1, 2, 3, 4)
    a.global_(1, "executeConsoleCommand")
    a.string(2, "port_hints_ready")
    a.native(0, 1)
    a.clear(0, 1, 2)
    frame = max(r["offset"] for r in module.instructions() if r.get("header") and r["offset"] < site["offset"])
    old_slots = struct.unpack_from("<I", module.code, frame + 4)[0]
    module.code[frame + 4:frame + 8] = p32(max(old_slots, 7))
    if module.legacy:
        a.global_(1, "executeConsoleCommand")
        a.string(2, "port_ready")
        a.native(0, 1)
        a.clear(0, 1, 2)
    a.get_setting("PortSkipIntro", 0, "asBool")
    a.emit(55, 0, "play")
    a.clear(0)
    a.emit(54, 0, rows[finish]["offset"])
    a.label("play")
    a.clear(0)
    a.raw(original[site["offset"]:site["offset"] + length])
    a.emit(54, 0, site["offset"] + length)
    tramp = append(module, a)
    jump_patch(module, original, site["offset"], length, tramp)
    return dict(sites=[hex(frame + 4), hex(site["offset"])], skip_to=hex(rows[finish]["offset"]), trampoline=hex(tramp))


def method_rows(module, name, args=None):
    """The instructions of the method called name (with args arguments)."""
    offset = next(m["code_offset"] for c in module.contexts for m in c["methods"]
                  if m["name"] == name and (args is None or m["args"] == args))
    out, inside = [], False
    for r in module.instructions():
        if r.get("header"):
            if inside:
                break
            inside = r["offset"] == offset
            continue
        if inside:
            out.append(r)
    return out


def f32(v):
    return struct.unpack("<I", struct.pack("<f", v))[0]


def ascii_symbol(module, text):
    """The pool offset of the module's own name text (a window's properties,
    Width and Height, resolve by the module's own entry), else None."""
    pool = bytes(module.pool)
    needle = text.encode("ascii") + b"\0"
    at = pool.find(needle)
    while at > 0 and pool[at - 1] != 0:
        at = pool.find(needle, at + 1)
    return at if at >= 0 else None


def patch_palette_label(module, lang):
    """ui/paint_limfa.bin, a heart of the painting palette: its tooltip
    (the colour's name, "amount / most" in thousands) followed the cursor,
    under a finger, in a small font. It shows for the active colour, in a
    larger font (16 px, then the interface scale) and a lighter tone of the
    colour; the text is remade when the amounts or the active colour
    change."""
    original = bytes(module.code)
    sites = []

    def at(row, length=None):
        sites.append(hex(row["offset"]))
        return row["offset"], length or row["size"]

    def same_size(row, word=None, operands=None):
        o = row["offset"]
        if word is not None:
            module.code[o:o + 4] = p32(word)
        for i, v in enumerate(operands or []):
            if v is not None:
                module.code[o + 4 + 4 * i:o + 8 + 4 * i] = p32(v)
        sites.append(hex(o))

    # The font: fontmain_10 -> fontmain_16 (a new pool string).
    init = method_rows(module, "initUI")
    font = next(r for r in init if r.get("text") == "fontmain_10.ft")
    a = Assembler(module)
    same_size(font, operands=[len("fontmain_16.ft"), a.pool("fontmain_16.ft", True)])
    # The text's canvas: 256 x 64 -> 512 x 128 (two lines of a larger font).
    upd = method_rows(module, "updateTooltip")
    width = next(r for r in upd if r["opcode"] == 1 and r["operands"] == [0x100])
    height = next(r for r in upd if r["opcode"] == 1 and r["operands"] == [0x40])
    same_size(width, operands=[0x200])
    same_size(height, operands=[0x80])
    # The control's loop remakes the text when hovered and changed: also
    # when active (op14 r9 -> r2 = hovered).
    rows = rows_of(module)
    remake = next(i for i, r in enumerate(rows) if r["opcode"] == 63 and r["operands"][0] ==
                  next(m["code_offset"] for c in module.contexts for m in c["methods"] if m["name"] == "updateTooltip"))
    hovered = next(rows[i] for i in range(remake, 0, -1) if rows[i]["opcode"] == 14 and rows[i]["register"] == 9)
    a = Assembler(module)
    a.emit(14, 9, 2)
    a.emit(56, 2, "go")
    a.emit(14, 6, 2)
    a.label("go")
    a.emit(54, 0, hovered["offset"] + 8)
    o, n = at(hovered)
    jump_patch(module, original, o, n, append(module, a))
    # setProgress and setAsActive mark the text changed (field 10).
    prog = method_rows(module, "setProgress", 2)
    prog = [r for r in prog if r["opcode"] == 10][0]
    a = Assembler(module)
    a.emit(0, 0, 1)
    a.emit(13, 0, 0xA)
    a.raw(original[prog["offset"]:prog["offset"] + 8])
    a.emit(54, 0, prog["offset"] + 8)
    o, n = at(prog)
    jump_patch(module, original, o, n, append(module, a))
    act = method_rows(module, "setAsActive")
    store = [r for r in act if r["opcode"] == 13 and r["operands"] == [6]][-1]
    a = Assembler(module)
    a.raw(original[store["offset"]:store["offset"] + 8])
    a.emit(0, 0, 1)
    a.emit(13, 0, 0xA)
    a.emit(54, 0, store["offset"] + 8)
    o, n = at(store)
    jump_patch(module, original, o, n, append(module, a))
    # renderTooltip: drawn for the active colour once its text exists
    # (r1 = active instead of hovered; r1 = the canvas instead of !changed).
    tip = method_rows(module, "renderTooltip")
    first = tip[1]
    assert first["opcode"] == 14 and first["register"] == 9
    same_size(first, word=(6 << 8) | 14)
    changed = tip[3]
    assert changed["opcode"] == 14 and changed["register"] == 10 and tip[4]["opcode"] == 23
    same_size(changed, word=(11 << 8) | 14)
    same_size(tip[4], word=(8 << 8) | 74)            # the "not" becomes a clear of a free register
    # Its place comes from the palette's window (patch_palette_place).
    # A lighter tone of the colour: 0.45 + 0.55 * c for each component.
    j = next(i for i, r in enumerate(tip) if r.get("text") == "getLimfaColor")
    while tip[j]["opcode"] != 18:
        j += 1
    after = tip[j + 1]
    assert after["opcode"] == 10 and after["size"] == 8
    a = Assembler(module)
    a.global_(2, "!vec3")
    for reg, comp in ((3, "x"), (4, "y"), (5, "z")):
        a.move(0, reg + 1)
        a.member(reg, comp)
        a.clear(reg + 1)
        a.emit(2, reg + 1, f32(0.55))
        a.emit(38, reg)
        a.emit(2, reg + 1, f32(0.45))
        a.emit(36, reg)
        a.clear(reg + 1)
    a.native(1, 3)
    a.clear(2, 3, 4, 5)
    a.move(1, 0)
    a.clear(1)
    a.raw(original[after["offset"]:after["offset"] + 8])
    a.emit(54, 0, after["offset"] + 8)
    o, n = at(after)
    jump_patch(module, original, o, n, append(module, a))
    return dict(sites=sites)


def patch_tooltip_font(module, lang):
    """ui/body_free_limfa.bin and body_active_limfa.bin (the body screen's
    Memory and colours): their tooltips (name, "amount / most") in a 16 px
    font instead of 10 (then the interface scale), on a canvas that holds
    it."""
    sites = []
    a = Assembler(module)
    init = method_rows(module, "initUI")
    font = next(r for r in init if r.get("text") == "fontmain_10.ft")
    o = font["offset"]
    module.code[o + 4:o + 12] = p32(len("fontmain_16.ft")) + p32(a.pool("fontmain_16.ft", True))
    sites.append(hex(o))
    upd = method_rows(module, "updateTooltip")
    for value, wider in ((0x100, 0x200), (0x40, 0x80)):
        r = next(r for r in upd if r["opcode"] == 1 and r["operands"] == [value])
        module.code[r["offset"] + 4:r["offset"] + 8] = p32(wider)
        sites.append(hex(r["offset"]))
    return dict(sites=sites)

def patch_health_hold(module, lang):
    """F13 is the touch layer's held-heart command; keep normal mouse hover."""
    rows = method_rows(module, "renderTooltip")
    branch = rows[1]
    assert rows[0]["opcode"] == 14 and rows[0]["register"] == (11 if module.legacy else 17)
    assert branch["opcode"] == 55 and branch["register"] == 0
    inside, outside = branch["offset"] + branch["size"], branch["operands"][0]
    a = Assembler(module)
    a.emit(56, 0, inside)
    a.global_(1, "isKeyPressed")
    a.integer(2, 0x64)  # DIK_F13, reserved by the port for this hold.
    a.native(0, 1)
    a.clear(1, 2)
    a.emit(56, 0, inside)
    a.emit(54, 0, outside)
    original = bytes(module.code)
    jump_patch(module, original, branch["offset"], 8, append(module, a))
    return dict(sites=[hex(branch["offset"])], inside=inside, outside=outside)


def patch_dialogue_key(module, lang):
    """Dialogue polls the skip key directly, bypassing actions.xml."""
    rows = rows_of(module)
    a = Assembler(module)
    sites = []
    for i, row in enumerate(rows):
        if row.get("symbol") != "isKeyPressed":
            continue
        key = rows[i + 1]
        if key["opcode"] == 1 and key["operands"] == [0x39]:
            module.code[key["offset"] + 4:key["offset"] + 8] = p32(0x1c)
        elif key.get("symbol") == "getKeyCode" and rows[i + 2].get("text") == "space":
            key = rows[i + 2]
            module.code[key["offset"] + 4:key["offset"] + 12] = p32(6) + p32(a.pool("return", True))
        else:
            continue
        sites.append(hex(key["offset"]))
    assert module.legacy or len(sites) in (2, 4, 8, 12), sites
    return dict(sites=sites)


def patch_palette_place(module, lang):
    """The windows with a painting palette (ui/paint.bin, tree, hunter,
    obscure, obscure_final) draw the tooltip of a heart where the cursor is:
    it goes to a fixed place right of the palette's vine at the top (from the
    window's, the screen's, height; the heart adds 32 px)."""
    original = bytes(module.code)
    rows = rows_of(module)
    sites = []
    for i, r in enumerate(rows):
        if r.get("text") != "renderTooltip" or r["opcode"] != 3:
            continue
        base = r["register"]
        first = i + 2
        assert rows[i + 1]["opcode"] == 10 and rows[first].get("symbol") == "Plane", hex(r["offset"])
        call = next(j for j in range(first, first + 20) if rows[j]["opcode"] == 57 and rows[j]["register"] == base - 2)
        assert sum(1 for j in range(first, call) if rows[j].get("symbol") == "getCursorPosition") == 2
        a = Assembler(module)
        height = ascii_symbol(module, "Height")
        assert height is not None
        t = base + 4                                  # a binary op takes r(X+1)
        health = any(row.get("text") == "health" for row in rows[max(0, i - 12):i])
        point = (0.48, 0.70) if health else (0.36, 0.035)
        for share, dest in zip(point, (base + 2, base + 3)):
            a.emit(71, t, height)
            a.emit(17, t)
            a.emit(2, t + 1, f32(share))
            a.emit(38, t)
            a.emit(16, t)
            a.move(t, dest)
        a.clear(t, t + 1)
        a.emit(54, 0, rows[call]["offset"])
        sites.append(hex(rows[first]["offset"]))
        jump_patch(module, original, rows[first]["offset"], rows[first]["size"], append(module, a))
    assert sites, "no renderTooltip call"
    return dict(sites=sites)

# Named strings for touch, by table and language. keys.txt: the keys the
# touch controls send, by the control's name (android/app/src/org/thevoid/
# port/Controls.java and Icons.java): taps are the left button, the hand (or
# touching the helper) the right one, the brush L Ctrl, the next line of a
# dialogue (the jump button elsewhere) Space, the heart, the book and the
# map buttons B, J and M, the menu button Escape, the run button L Shift,
# skipping Enter (actions.xml below).
# menu.txt: the mouse settings, which apply to swipes and the gyroscope.
TOUCH_TEXTS = {
    "Properties\\Strings\\keys.txt": {
        "ru": {"key_lbutton": "касание", "key_rbutton": "рука", "key_lctrl": "кисть", "key_space": "прыжок",
               "key_return": "далее", "key_b": "сердце", "key_j": "книга", "key_m": "карта", "key_escape": "меню",
               "key_lshift": "бег"},
        "de": {"key_lbutton": "Tippen", "key_rbutton": "Hand", "key_lctrl": "Pinsel", "key_space": "Sprung",
               "key_return": "Weiter", "key_b": "Herz", "key_j": "Buch", "key_m": "Karte", "key_escape": "Menü",
               "key_lshift": "Rennen"},
    },
    "Properties\\Strings\\menu.txt": {
        "ru": {"options_menu_invert_mouse": "Инвертировать Обзор",
               "options_menu_mouse_sensitivity": "Чувствительность Обзора",
               "options_menu_mouse_smoothing": "Сглаживание Обзора"},
        "de": {"options_menu_invert_mouse": "Blick invertieren",
               "options_menu_mouse_sensitivity": "Blickempfindlichkeit",
               "options_menu_mouse_smoothing": "Blickglättung"},
    },
    "Properties\\Strings\\tutorial.txt": {
        "ru": {5001: "Удерживайте Лазурь в Памяти справа (%s) до смены подсказки.",
               5002: "Отпустите палец и коснитесь кружка над пустым Сердцем."},
        "en": {5001: "Hold the Azure drop in Memory on the right (%s) until this hint changes.",
               5002: "Lift your finger, then tap the circle over an empty Heart to transfer the Color."},
        "de": {5001: "Halte den Azur-Tropfen rechts im Gedächtnis (%s), bis sich dieser Hinweis ändert.",
               5002: "Lass los und tippe dann auf den Kreis über einem leeren Herz, um die Farbe zu übertragen."},
        "pl": {5001: "Przytrzymaj błękitną kroplę w Pamięci po prawej (%s), aż zmieni się wskazówka.",
               5002: "Podnieś palec, a potem dotknij kółka nad pustym Sercem, aby przenieść Barwę."},
    },
}


def patch_actions(data):
    """actions.xml: skip_cutscene (cutscenes, the next line of a dialogue,
    the opening videos) on Enter; Space stays the jump."""
    old = b'<Action name="skip_cutscene" handler="space" />'
    assert data.count(old) == 1
    return data.replace(old, b'<Action name="skip_cutscene" handler="return" />'), dict(skip_cutscene="return")


# Loose files of a release's data folder.
LOOSE_PATCHES = [
    ("actions.xml", patch_actions),
]


def patch_named_strings(data, names):
    """A string table (UTF-16 LE, a BOM, CRLF): the value line after each
    named or numbered entry in names replaced, every other byte kept."""
    assert data[:2] == b"\xff\xfe"
    lines = data[2:].decode("utf-16-le").split("\r\n")
    done = set()
    base = 0
    for i, line in enumerate(lines[:-1]):
        if line.startswith("@base "):
            base = int(line[len("@base "):])
        key = line[len("@nstring "):] if line.startswith("@nstring ") else None
        if line.startswith("@string "):
            key = base + int(line[len("@string "):])
        if key in names:
            lines[i + 1] = names[key]
            done.add(key)
    assert done == set(names), set(names) - done
    return b"\xff\xfe" + "\r\n".join(lines).encode("utf-16-le"), dict(strings=sorted(done))

def dds_rgba(data):
    """(width, height, RGBA rows) of a DDS: DXT5 or A8R8G8B8, level 0."""
    assert data[:4] == b"DDS "
    h, w = struct.unpack_from("<2I", data, 12)
    flags, fourcc, bits = struct.unpack_from("<3I", data, 80)
    body = data[128:]
    if fourcc == 0x35545844:   # DXT5
        out = bytearray(w * h * 4)
        blocks = 0
        for by in range(0, h, 4):
            for bx in range(0, w, 4):
                b = body[blocks * 16:blocks * 16 + 16]
                blocks += 1
                a0, a1 = b[0], b[1]
                alphas = [a0, a1] + ([((6 - i) * a0 + (i + 1) * a1) // 7 for i in range(6)] if a0 > a1 else
                                     [((4 - i) * a0 + (i + 1) * a1) // 5 for i in range(4)] + [0, 255])
                abits = int.from_bytes(b[2:8], "little")
                c0, c1 = struct.unpack_from("<2H", b, 8)
                cbits = struct.unpack_from("<I", b, 12)[0]

                def rgb(c):
                    return ((c >> 11) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31)
                p0, p1 = rgb(c0), rgb(c1)
                cols = [p0, p1, tuple((2 * x + y) // 3 for x, y in zip(p0, p1)), tuple((x + 2 * y) // 3 for x, y in zip(p0, p1))]
                for i in range(16):
                    x, y = bx + i % 4, by + i // 4
                    if x < w and y < h:
                        r, g, bb = cols[(cbits >> (2 * i)) & 3]
                        out[(y * w + x) * 4:(y * w + x) * 4 + 4] = bytes((r, g, bb, alphas[(abits >> (3 * i)) & 7]))
        return w, h, bytes(out)
    assert bits == 32, bits
    px = bytearray(body[:w * h * 4])
    for i in range(0, len(px), 4):   # BGRA -> RGBA
        px[i], px[i + 2] = px[i + 2], px[i]
    return w, h, bytes(px)


def dds_argb(w, h, rgba):
    """An uncompressed A8R8G8B8 DDS, one level."""
    header = struct.pack("<4s7I44x8I5I", b"DDS ", 124, 0x100F, h, w, w * 4, 0, 0,
                         32, 0x41, 0, 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000, 0x1000, 0, 0, 0, 0)
    assert len(header) == 128
    px = bytearray(rgba)
    for i in range(0, len(px), 4):
        px[i], px[i + 2] = px[i + 2], px[i]
    return header + bytes(px)


def enlarged(data, factor, rotation=0):
    """A DDS image (or mask) factor times larger, alpha kept clean at the edges."""
    from PIL import Image
    w, h, rgba = dds_rgba(data)
    im = Image.frombytes("RGBA", (w, h), rgba).convert("RGBa")   # premultiplied: no dark fringes
    big = im.resize((w * factor, h * factor), Image.BICUBIC).convert("RGBA")
    if rotation:
        big = big.rotate(rotation, expand=True)
    return dds_argb(*big.size, big.tobytes()), dict(size=list(big.size), factor=factor, rotation=rotation)


def arrow_mask(data, factor, rotation):
    """Accept the whole arrow button, including its hollow centre and padding."""
    mask, info = enlarged(data, factor, rotation)
    w, h, _ = dds_rgba(mask)
    return dds_argb(w, h, b"\xff" * (w * h * 4)), info


NEW_IMAGES = [
    ("Textures\\ui\\port_text_backplate.tex", "Textures\\BlackBitmap.tex", 2, 0),
    ("Textures\\ui\\port_arrow_left.tex", "Textures\\ui\\diary_quest_arrow_up.tex", 2, 90),
    ("Textures\\ui\\port_arrow_left_mask.tex", "Textures\\ui\\diary_quest_arrow_up_mask.tex", 2, 90),
    ("Textures\\ui\\port_arrow_right.tex", "Textures\\ui\\diary_quest_arrow_up.tex", 2, -90),
    ("Textures\\ui\\port_arrow_right_mask.tex", "Textures\\ui\\diary_quest_arrow_up_mask.tex", 2, -90),
]

PATCHES = [
    ("Scripts\\player.bin", patch_head_bob),
    ("Scripts\\world\\main_menu.bin", patch_skip_intro),
    ("Scripts\\ui\\subtitle.bin", patch_subtitle_timing),
    ("Scripts\\fx\\fx_player_damage_limfa.bin", patch_damage_limfa_target),
    ("Scripts\\ui\\main_menu.bin", patch_options),
    ("Scripts\\ui\\paint_limfa.bin", patch_palette_label),
    ("Scripts\\ui\\database.bin", patch_database),
    ("Scripts\\ui\\body_free_limfa.bin", patch_tooltip_font),
    ("Scripts\\ui\\body_active_limfa.bin", patch_tooltip_font),
    ("Scripts\\ui\\health_progress.bin", patch_health_hold),
    ("Scripts\\ui\\paint.bin", patch_palette_place),
    ("Scripts\\ui\\tree.bin", patch_palette_place),
    ("Scripts\\ui\\hunter.bin", patch_palette_place),
    ("Scripts\\ui\\obscure.bin", patch_palette_place),
    ("Scripts\\ui\\obscure_final.bin", patch_palette_place),
]
# Each dialogue helper has its own direct key poll.
PATCHES += [(name, patch_dialogue_key) for name in [
    'Scripts\\scene\\hunter_09_dudochnik_talk.bin',
    'Scripts\\scene\\hunter_08_hole_talk.bin',
    'Scripts\\scene\\hunter_06_driller_talk.bin',
    'Scripts\\scene\\hunter_02_ironclad_talk.bin',
    'Scripts\\scene\\hunter_07_catterpillar_talk.bin',
    'Scripts\\scene\\hunter_01_kolesnik_talk.bin',
    'Scripts\\scene\\hunter_05_whaler_talk.bin',
    'Scripts\\scene\\hunter_10_lattice_talk.bin',
    'Scripts\\scene\\hunter_04_mongolfier_talk.bin',
    'Scripts\\scene\\hunter_03_stiltman_talk.bin',
    'Scripts\\scene\\obscure_yani.bin',
    'Scripts\\scene\\obscure_echo.bin',
    'Scripts\\scene\\obscure_ava.bin',
    'Scripts\\scene\\obscure_eli.bin',
    'Scripts\\scene\\obscure_ole.bin',
    'Scripts\\scene\\obscure_ima.bin',
    'Scripts\\scene\\obscure_uta.bin',
    'Scripts\\scene\\obscure_aya.bin',
    'Scripts\\scene\\obscure_ire.bin',
    'Scripts\\scene\\obscure_una.bin',
    'Scripts\\scene\\obscure_sister.bin',
    'Scripts\\ui\\map_strip.bin',
    'Scripts\\ui\\map.bin',
    'Scripts\\world\\world.bin',
]]


def combined_patch(original, touch):
    def apply(module, lang):
        info = original(module, lang)
        added = touch(module, lang)
        sites = info["sites"] + added["sites"]
        info.update(added)
        info["sites"] = sites
        return info
    return apply


from patch_touch_native import PATCHES as TOUCH_PATCHES  # noqa: E402
from patch_readability import PATCHES as READABILITY_PATCHES  # noqa: E402
from patch_debug_locations import patch_debug_locations  # noqa: E402
from patch_poema_audio import poema_overrides  # noqa: E402


# These empty RU/EN actors were removed in the shipped DE2009 scenes.
GARDEN_ORPHANS = {
    "trunk": "7d6eeed4c9effa657b8b69c6b00dde972fd2a6f8e8cf8879984538fe38e15d72",
    "trunkbright": "630b0f456a1e07e0177f1da22749010cb97268dd24bc898dec4b7b103ffd0155",
}


def patch_garden_orphan_trigger(data, scene, binary_size):
    assert hashlib.sha256(data).hexdigest() == GARDEN_ORPHANS[scene]
    match, = list(re.finditer(rb'(?m)^\t\t<Actor Type="trigger" Name="t_butterfly_trunk"[^\n]*\n.*?^\t\t</Actor>\n', data, re.S))
    actor = ET.fromstring(match.group())
    assert actor.attrib == dict(Type="trigger", Name="t_butterfly_trunk", BinOffset=str(binary_size))
    assert [child.tag for child in actor] == ["Physics", "Script", "Transform"]
    physics = actor.find("Physics")
    assert not physics.attrib and not list(physics)
    assert actor.find("Script").attrib == {"Filename": "trigger/t_butterfly_" + scene}
    # Its EOF BinOffset contains no scene-binary payload; keep every other byte.
    return data[:match.start()] + data[match.end():]


def garden_scene_overrides(index_path):
    index = json.loads((ROOT / index_path).read_text(encoding="utf-8"))
    for scene, source_sha in GARDEN_ORPHANS.items():
        name = "Scenes\\Garden\\" + scene + ".xml"
        original = read_entry(index_path, name)
        if original is None or hashlib.sha256(original).hexdigest() != source_sha:
            continue
        binary = "Scenes\\Garden\\" + scene + ".s"
        binary_size, = [e["size"] for c in index["containers"] for e in c["entries"] if e["name"] == binary]
        yield name, original, patch_garden_orphan_trigger(original, scene, binary_size)

for name, patch in TOUCH_PATCHES + READABILITY_PATCHES + [('Scripts\\world\\world.bin', patch_debug_locations)]:
    match = next((i for i, (path, _) in enumerate(PATCHES) if path.lower() == name.lower()), None)
    if match is None:
        PATCHES.append((name, patch))
    else:
        PATCHES[match] = (name, combined_patch(PATCHES[match][1], patch))


def main():
    OUT.resolve().relative_to((ROOT / "build").resolve())
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    entries = []
    # The early options keep the Java panel; original video/shadow controls stay.
    legacy_patches = [(path, patch) for path, patch in PATCHES
                      if path != 'Scripts\\ui\\hud.bin']
    for index_path, lang in INDEXES.items():
        if not (ROOT / index_path).is_file():
            continue
        legacy = lang == "pl"
        for name, original, payload in garden_scene_overrides(index_path):
            sha = hashlib.sha256(original).hexdigest()
            if any(e["original_sha256"] == sha and e["path"] == name for e in entries):
                continue
            out = OUT / sha / name.replace("\\", "/")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(payload)
            entries.append(dict(path=name, original_sha256=sha, original_size=len(original),
                                file=f"{sha}/{name.replace(chr(92), '/')}", sha256=hashlib.sha256(payload).hexdigest(),
                                index=index_path, scene_fix="Remove the empty missing-script trigger absent from the original DE2009 scene"))
        for name, source_name, original, payload in poema_overrides(index_path):
            sha = hashlib.sha256(original).hexdigest()
            if any(e["original_sha256"] == sha and e["path"] == name for e in entries):
                continue
            out = OUT / sha / name.replace("\\", "/")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(payload)
            entries.append(dict(path=name, source=source_name, original_sha256=sha, original_size=len(original),
                                file=f"{sha}/{name.replace(chr(92), '/')}", sha256=hashlib.sha256(payload).hexdigest(),
                                index=index_path, audio_fix="Uta mono ambience has a unique name; original PCM unchanged"))
        for name, patch in legacy_patches if legacy else PATCHES:
            data = read_entry(index_path, name)
            if data is None:
                continue
            sha = hashlib.sha256(data).hexdigest()
            if any(e["original_sha256"] == sha and e["path"] == name for e in entries):
                continue
            module = Module(data, legacy=legacy)
            original_code = bytes(module.code)
            info = patch(module, lang)
            payload = module.encode()
            check = Module(payload, legacy=legacy)
            rows = list(check.instructions())
            assert check.debug == module.debug and check.pool[:len(Module(data).pool)] == Module(data).pool
            # Original bytes change only at the patch sites (an instruction each,
            # at most 16 bytes).
            allowed = {int(site, 16) + n for site in info["sites"] for n in range(16)}
            changed = [i for i in range(len(original_code)) if check.code[i] != original_code[i]]
            assert set(changed) <= allowed, [hex(i) for i in changed if i not in allowed]
            out = OUT / sha / name.replace("\\", "/")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(payload)
            entries.append(dict(path=name, original_sha256=sha, original_size=len(data),
                                file=f"{sha}/{name.replace(chr(92), '/')}", sha256=hashlib.sha256(payload).hexdigest(),
                                index=index_path, instructions=len(rows), **info))
            print(f"{index_path}: {name} {sha[:12]} -> {info}")
        source = Path(json.loads((ROOT / index_path).read_text(encoding="utf-8"))["source"])
        if not source.is_absolute():
            source = ROOT / source
        for name, patch in LOOSE_PATCHES:
            original = source / name
            if not original.is_file():
                continue
            data = original.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            if any(e["original_sha256"] == sha and e["path"] == name for e in entries):
                continue
            payload, info = patch(data)
            out = OUT / sha / name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(payload)
            entries.append(dict(path=name, original_sha256=sha, original_size=len(data), file=f"{sha}/{name}",
                                sha256=hashlib.sha256(payload).hexdigest(), index=index_path, **info))
            print(f"{index_path}: {name} {sha[:12]} -> {info}")
        for name, source_name, factor, rotation in NEW_IMAGES:
            data = read_entry(index_path, source_name)
            if data is None:
                continue
            sha = hashlib.sha256(data).hexdigest()
            if any(e["original_sha256"] == sha and e["path"] == name for e in entries):
                continue
            if name.endswith("port_text_backplate.tex"):
                # A distinct texture keeps text panels out of the HUD's
                # BlackBitmap/subtitle recognition and tap-to-skip region.
                payload, info = dds_argb(2, 2, b"\0\0\0\xff" * 4), dict(size=[2, 2])
            elif name.endswith("_mask.tex"):
                payload, info = arrow_mask(data, factor, rotation)
            else:
                payload, info = enlarged(data, factor, rotation)
            out = OUT / sha / name.replace("\\", "/")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(payload)
            entries.append(dict(path=name, source=source_name, original_sha256=sha, original_size=len(data),
                                file=f"{sha}/{name.replace(chr(92), '/')}", sha256=hashlib.sha256(payload).hexdigest(),
                                index=index_path, **info))
            print(f"{index_path}: {name} from {source_name} {sha[:12]} -> {info}")
    # English scripts share the 2009 bytecode; its localized text has its own hash.
    for index_path, lang in {**INDEXES, 'research/vfs-index.english.json': 'en'}.items():
        if not (ROOT / index_path).is_file():
            continue
        for name, by_lang in TOUCH_TEXTS.items():
            data = read_entry(index_path, name)
            if data is None or lang not in by_lang:
                continue
            sha = hashlib.sha256(data).hexdigest()
            if any(e["original_sha256"] == sha and e["path"] == name for e in entries):
                continue
            payload, info = patch_named_strings(data, by_lang[lang])
            out = OUT / sha / name.replace("\\", "/")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(payload)
            entries.append(dict(path=name, original_sha256=sha, original_size=len(data),
                                file=f"{sha}/{name.replace(chr(92), '/')}", sha256=hashlib.sha256(payload).hexdigest(),
                                index=index_path, **info))
            print(f"{index_path}: {name} {sha[:12]} -> {info}")
    from patch_touch_native import export_mobile_gestures
    for index_path, lang in INDEXES.items():
        if (ROOT / index_path).is_file():
            export_mobile_gestures(index_path, OUT / 'mobile-icons' / lang, read_entry, dds_rgba)
    (OUT / "index.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")
    print(f"{len(entries)} patched files in {OUT}")


if __name__ == "__main__":
    main()
