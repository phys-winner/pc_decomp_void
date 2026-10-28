"""The port's settings as pages of the game's own options menu
(Scripts\\ui\\main_menu.bin of the 2009 releases), built with the menu's
own controls so that they look and behave like its pages.

The options menu is a set of states (gscript contexts) sharing the fields of
the options state (7 in the Russian release): the vector that maps the
controls' items to actions, the Default and Return controls. The tabs audio,
video and controls are states with a constructor that builds the tabs (one
shared function) and the page's controls, then loops, a click handler that
first runs the tabs' shared handler, and virtual methods (the context's
extra table, called by op64): 0 applies the page's controls to the game's
Settings, 1 resets them, 2 is Return. The patch
  - adds a fourth tab, the painted "O" of the main menu's Options, after the
    three tabs (moved left a little to keep the row centred);
  - lets the tabs' shared handler go to the new pages on its action;
  - appends three states cloned from the video page's (render, mouse moves,
    keys and Return stay the original code) with their own constructor,
    click handler, apply and Default: labels, check boxes, sliders and the
    side arrows that turn the three pages in either direction.
Places follow the original pages: units of 1/1200 of the screen's height
from its centre, y up; a check box's image is 256 units with the box in its
middle, its caption at (+184, -117); a title is 40 units high, a caption 26.
The pages keep clear of the Default and Return controls in the bottom
corners on 16:9 screens (wider ones have more room at the sides).

Settings values are strings in the profile's settings.xml (keys Port*),
which the touch layer reads (Settings.java)."""
import struct

from gscript_binary import p32
from patch_native_menu import Assembler

F32 = lambda v: struct.unpack("<I", struct.pack("<f", float(v)))[0]  # noqa: E731

TAB_ACTION = 50          # the fourth tab's item
PAGE_ACTIONS = (90, 91)  # previous and next page
CHECKBOX = "ui/opt_video_check_box"

TEXTS = {
    "ru": dict(tab="Дополнительно", render="Масштаб рендеринга", ui="Масштаб интерфейса",
               aniso="Анизотропная фильтрация", off="Выкл.", wide="Широкий экран (Hor+)",
               hdr="HDR", simple="Упрощенный", full="Полный",
               light="Качество освещения", high="Высокое", medium="Среднее", low="Низкое",
               textures="Текстуры высокого качества", sound="Звук высокого качества",
               gyro="Гироскоп", size="Размер кнопок", opacity="Непрозрачность кнопок",
               vibration="Вибрация", left="Управление для левши", run="Бег при отклонении стика до края",
               cursor="Скрывать курсор игры", intro="Пропускать начальные ролики",
               bob="Покачивание камеры при ходьбе",
               accel="Ускорение быстрого обзора", decimal=",",
               next="Следующая страница", back="Предыдущая страница",
               picker="Выбор цвета", strip="Полоса", fan="Веер", both="Оба"),
    "de": dict(tab="Erweitert", render="Renderskalierung", ui="Oberflächenskalierung",
               aniso="Anisotrope Filterung", off="Aus", wide="Breitbild (Hor+)",
               hdr="HDR", simple="Vereinfacht", full="Voll",
               light="Beleuchtungsqualität", high="Hoch", medium="Mittel", low="Niedrig",
               textures="Hochwertige Texturen", sound="Hochwertiger Ton",
               gyro="Gyroskop", size="Tastengröße", opacity="Deckkraft der Tasten",
               vibration="Vibration", left="Steuerung für Linkshänder", run="Rennen mit dem Stick am Rand",
               cursor="Spielcursor ausblenden", intro="Startvideos überspringen",
               bob="Kopfwippen beim Gehen",
               accel="Schnelles Umsehen beschleunigen", decimal=",",
               next="Nächste Seite", back="Vorherige Seite",
               picker="Farbwahl", strip="Leiste", fan="Fächer", both="Beides"),
    "en": dict(tab="More", render="Render scale", ui="Interface scale",
               aniso="Anisotropic filtering", off="Off", wide="Wide picture (Hor+)",
               hdr="HDR", simple="Simplified", full="Full",
               light="Lighting quality", high="High", medium="Medium", low="Low",
               textures="High quality textures", sound="High quality sound",
               gyro="Gyroscope", size="Button size", opacity="Button opacity",
               vibration="Vibration", left="Left-handed controls", run="Run with the stick at its edge",
               cursor="Hide the game's cursor", intro="Skip the opening videos",
               bob="Head bobbing while walking",
               accel="Faster turns on quick swipes", decimal=".",
               next="Next page", back="Previous page",
               picker="Choosing a colour", strip="Strip", fan="Fan", both="Both"),
}

for lang, values in {
    "ru": ("Вертикальный угол обзора", "Яркость жил для добычи цвета", "Мобильное управление",
           "Команды разработчика"),
    "de": ("Vertikales Sichtfeld", "Leuchten abbaubarer Adern", "Mobile Steuerung",
           "Entwicklerbefehle"),
    "en": ("Vertical field of view", "Harvestable vein glow", "Mobile controls",
           "Developer commands"),
}.items():
    TEXTS[lang].update(zip(("fov", "veins", "touch", "debug"), values))

for lang, values in {
    "ru": "Названия пунктов главного меню",
    "de": "Namen der Hauptmenüpunkte",
    "en": "Main menu item names",
}.items():
    TEXTS[lang]["menu_labels"] = values

for lang, values in {
    "ru": ("Размер субтитров", "Размер текста", "Контрастная подложка"),
    "de": ("Untertitelgröße", "Textgröße", "Hintergrund für Werte und Farbmengen"),
    "en": ("Subtitle size", "Text size", "Background for stats and colour amounts"),
}.items():
    TEXTS[lang].update(zip(("subtitles", "text", "contrast"), values))

for lang, values in {
    "ru": ("Показывать кнопку меню", "Показывать кнопку действия", "Показывать кнопку сердец"),
    "de": ("Menütaste anzeigen", "Aktionstaste anzeigen", "Herztaste anzeigen"),
    "en": ("Show menu button", "Show action button", "Show hearts button"),
}.items():
    TEXTS[lang].update(zip(("menu_button", "action_button", "body_button"), values))

for lang, value in {
    "ru": "Отражения в воде",
    "de": "Spiegelungen im Wasser",
    "en": "Water reflections",
}.items():
    TEXTS[lang]["reflections"] = value

for lang, value in {
    "ru": "Инверсия вертикали гироскопа",
    "de": "Gyroskop-Blick vertikal umkehren",
    "en": "Invert vertical gyroscope look",
}.items():
    TEXTS[lang]["gyro_invert_v"] = value


class Slider:
    """A title, a slider and its value. kind "range": lo..hi in steps (an
    integer setting, the value shown with suffix); "list": the setting's
    values, one per slider position, shown by name; "gyro": off at 0, else
    PortGyro 1 and PortGyroSpeed = position / 10 (0.1 .. 3.0)."""
    def __init__(self, key, title, default, kind="range", lo=0, hi=0, step=1, suffix="", values=(), names=()):
        self.key, self.title, self.default, self.kind = key, title, default, kind
        self.lo, self.hi, self.step, self.suffix = lo, hi, step, suffix
        self.values, self.names = list(values), list(names)

    @property
    def steps(self):
        if self.kind == "range":
            return (self.hi - self.lo) // self.step
        if self.kind == "list":
            return len(self.values) - 1
        return 30


class Radios:
    """A title and a row of check boxes, one checked: the setting's value."""
    def __init__(self, key, title, default, options):
        self.key, self.title, self.default, self.options = key, title, default, list(options)


class Check:
    """A check box with its caption: the setting is on (checked) or off."""
    def __init__(self, key, caption, default, on="1", off="0"):
        self.key, self.caption, self.default, self.on, self.off = key, caption, default, on, off


def pages(t):
    """Graphics, controls and touch adaptations: two columns per page."""
    # Choices are sliders with the value's name: a row of check boxes with
    # captions outgrows its place when the interface scale enlarges text.
    first = (
        [Slider("PortRenderScale", t["render"], 100, lo=50, hi=150, step=10, suffix=" %"),
         Slider("PortUIScale", t["ui"], 100, lo=70, hi=150, step=10, suffix=" %"),
         Slider("PortHDR", t["hdr"], 2, kind="list", values=[0, 1, 2], names=[t["off"], t["simple"], t["full"]])],
        [Slider("PortAnisotropy", t["aniso"], 4, kind="list", values=[0, 2, 4, 8, 16],
                names=[t["off"], "2x", "4x", "8x", "16x"]),
         Slider("PortLightmapQuality", t["light"], 0, kind="list", values=[2, 1, 0],
                names=[t["low"], t["medium"], t["high"]]),
         Check("PortTextureQuality", t["textures"], True, on="0", off="1"),
         Check("PortSoundRate", t["sound"], True, on="44", off="22"),
         # A water mirror draws the scene a second time (a quarter of the frame
         # at the lake Ire); off, its reflection is black (renderer_native.c).
         Check("PortReflections", t["reflections"], True)])
    second = (
        [Slider("PortGyro", t["gyro"], 0, kind="gyro"),
         Slider("PortButtonSize", t["size"], 100, lo=70, hi=150, step=10, suffix=" %"),
         Slider("PortButtonOpacity", t["opacity"], 60, lo=25, hi=95, step=5, suffix=" %"),
         Slider("PortPicker", t["picker"], 2, kind="list", values=[0, 1, 2], names=[t["strip"], t["fan"], t["both"]])],
        [Check("PortGyroInvertV", t["gyro_invert_v"], True),
         Check("PortLeftHanded", t["left"], False),
         Check("PortHideCursor", t["cursor"], True),
         Check("PortHeadBob", t["bob"], False),
         Check("PortVibration", t["vibration"], True),
         Check("PortLookAccel", t["accel"], True)])
    third = (
        [Slider("PortFOV", t["fov"], 55, lo=40, hi=100, suffix="°"),
         Slider("PortVeinBrightness", t["veins"], 100, lo=100, hi=500, step=25, suffix=" %"),
         Slider("PortSubtitleSize", t["subtitles"], 100, lo=100, hi=150, step=10, suffix=" %"),
         Slider("PortTextSize", t["text"], 100, lo=100, hi=150, step=10, suffix=" %")],
        [Check("PortTouchAdaptations", t["touch"], True),
         Check("PortDebugCommands", t["debug"], False),
         Check("PortTextContrast", t["contrast"], True),
         Check("PortShowMenuButton", t["menu_button"], True),
         Check("PortShowMenuLabels", t["menu_labels"], True),
         Check("PortShowActionButton", t["action_button"], False),
         # The body opens from its own corner too (the map's indicator, the
         # hearts' corner on a chamber): its button may go.
         Check("PortShowBodyButton", t["body_button"], True)])
    return [first, second, third]


LEFT_X, RIGHT_X = -820, 120
TOP_Y = 260
SLIDER_PITCH, RADIO_PITCH, CHECK_PITCH = 210, 240, 120
RADIO_STEP = 270
# Native hit testing maps the solid mask over the doubled, rotated arrow.
# Positions follow the viewport edges
# in the menu's units of 1/1200 of its height.
ARROW = dict(y=128, scale=1.0, inset=12, width=256)
ARROW_IMAGES = ("ui/port_arrow_left", "ui/port_arrow_right")


def arrow_position(a, side):
    """r4 = vec2 at either viewport edge, vertically centred (uses r5..r8)."""
    a.global_(5, "!vec2")
    a.global_(6, "Width")
    a.emit(17, 6)
    a.global_(7, "Height")
    a.emit(39, 6)
    a.integer(7, 600 if side else -600)
    a.emit(38, 6)
    a.integer(7, -ARROW["width"] - ARROW["inset"] if side else ARROW["inset"])
    a.emit(36, 6)
    a.integer(7, ARROW["y"])
    a.native(4, 2)
    a.clear(5, 6, 7)


class Asm(Assembler):
    """The Assembler with the menu's calling patterns; pool strings shared."""
    def pool(self, text, wide=False):
        cache = self.module.__dict__.setdefault("pool_cache", {})
        if (text, wide) not in cache:
            cache[(text, wide)] = Assembler.pool(self, text, wide)
        return cache[(text, wide)]

    def call_begin(self, base, name):
        """r(base+1) = controls.call, r(base+2) = name: the arguments follow."""
        self.emit(14, 17, base + 2)
        self.member(base + 1, "call")
        self.clear(base + 2)
        self.string(base + 2, name)

    def setting(self, dest, key, conversion):
        """r(dest) = Settings[key].conversion (uses dest+1 .. dest+3)."""
        self.global_(dest + 2, "Settings")
        self.string(dest + 3, key)
        self.emit(58, dest + 1, 1)
        self.clear(dest + 3)
        self.member(dest, conversion)
        self.clear(dest + 1, dest + 2)

    def store(self, key):
        """Settings[key] = str(r0); clears r0 .. r2."""
        self.emit(20, 0)
        self.global_(1, "Settings")
        self.string(2, key)
        self.emit(59, 1, 1)
        self.clear(0, 1, 2)

    def store_text(self, key, text):
        self.string(0, text)
        self.global_(1, "Settings")
        self.string(2, key)
        self.emit(59, 1, 1)
        self.clear(0, 1, 2)

    def boolean(self, reg, cond_reg, tag):
        """r(reg) = bool constant of r(cond_reg) (the menu passes constants)."""
        self.emit(56, cond_reg, f"{tag}_t")
        self.emit(0, reg, 0)
        self.emit(54, 0, f"{tag}_d")
        self.label(f"{tag}_t")
        self.emit(0, reg, 1)
        self.label(f"{tag}_d")

    def add_action(self, opt_ctx, action):
        """The options' action vector (field 0 of the options state) gets action."""
        self.emit(12, 0, 2, opt_ctx)
        self.member(1, "add")
        self.clear(2)
        self.integer(2, action)
        self.native(0, 1)
        self.emit(75, 1, 0)

    def label_text(self, text, x, y, size):
        self.call_begin(0, "createLabel")
        self.string(3, text)
        self.vec2(4, x, y)
        self.integer(5, 0)
        # Private negative raw sizes keep these fixed-column labels at their
        # designed size. patch_readability recognizes them before the original
        # font clamp, including when setLabelText refreshes slider values.
        self.integer(6, -{1: 18, 2: 26, 3: 40}[size])
        self.native(0, 5)
        self.emit(78, 1, 0x30002, 0x4)

    def get_check(self, dest, index):
        """r(dest) = controls.getCheckBoxState(index) (uses dest+1 .. dest+3)."""
        self.emit(14, 17, dest + 2)
        self.member(dest + 1, "call")
        self.clear(dest + 2)
        self.string(dest + 2, "getCheckBoxState")
        self.integer(dest + 3, index)
        self.native(dest, 2)
        self.emit(75, dest + 1, dest + 2)

    def set_check(self, index, state_code):
        """controls.setCheckBoxState(index, r6), r6 from state_code (r6 .. r9)."""
        self.emit(14, 17, 4)
        self.member(3, "call")
        self.clear(4)
        self.string(4, "setCheckBoxState")
        self.integer(5, index)
        state_code()
        self.native(2, 3)
        self.emit(76, 3, 0x20004)
        self.clear(6)

    def get_slider(self, dest, index):
        self.emit(14, 17, dest + 2)
        self.member(dest + 1, "call")
        self.clear(dest + 2)
        self.string(dest + 2, "getSliderValue")
        self.integer(dest + 3, index)
        self.native(dest, 2)
        self.emit(75, dest + 1, dest + 2)

    def set_slider(self, index, value):
        self.emit(14, 17, 2)
        self.member(1, "call")
        self.clear(2)
        self.string(2, "setSliderValue")
        self.integer(3, index)
        self.emit(2, 4, F32(value))
        self.native(0, 3)
        self.emit(76, 1, 0x2)
        self.clear(0)

    def set_label(self, index):
        """controls.setLabelText(index, r6); clears r2 .. r6."""
        self.emit(14, 17, 4)
        self.member(3, "call")
        self.clear(4)
        self.string(4, "setLabelText")
        self.integer(5, index)
        self.native(2, 3)
        self.emit(76, 3, 0x20004)
        self.clear(6)


def function(module, a, slots):
    """Appends a function (frame header, code) and returns its offset."""
    offset = len(module.code)
    module.code += p32(0xffffffff) + p32(slots)
    module.code += a.finish(len(module.code))
    return offset


def inline(module, a):
    offset = len(module.code)
    module.code += a.finish(offset)
    return offset


def rows_of(module):
    return [r for r in module.instructions() if not r.get("header")]


def function_of(module, offset):
    """The header offset of the function holding offset."""
    best = None
    for r in module.instructions():
        if r["offset"] > offset:
            break
        if r.get("header"):
            best = r["offset"]
    return best


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


def relocated(module, start, end, base):
    """Bytes of [start, end) to run at base: jumps into the range, or to its
    end (what follows the copy), follow it."""
    code = bytearray(module.code[start:end])
    for r in rows_of(module):
        if start <= r["offset"] < end and r["opcode"] in (54, 55, 56):
            target = r["operands"][0]
            assert start <= target <= end, (hex(r["offset"]), hex(target))
            struct.pack_into("<I", code, r["offset"] - start + 4, base + target - start)
    return bytes(code)


class Sites:
    """Where the release's options menu is (offsets differ between releases)."""
    def __init__(self, module):
        rows = rows_of(module)
        by = {r["offset"]: r for r in rows}
        state = next(r for r in rows if r.get("text") == "Video Options State")
        self.video_ctor = function_of(module, state["offset"])
        video = function_rows(module, self.video_ctor)
        self.tabs = next(r for r in video if r["opcode"] == 63)["operands"][0]
        # The tabs' shared handler: transitions to the three pages.
        trans = [r for r in rows if r["opcode"] == 67 and r["operands"][1] == 0x200]
        handler = None
        for r in trans:
            if r["operands"][0] != self.video_ctor:
                continue
            f = function_of(module, r["offset"])
            regs = {x["register"] for x in function_rows(module, f) if x["opcode"] == 67}
            if len(regs) == 3:
                handler = f
        assert handler, "the tabs' shared handler"
        self.handler = handler
        hrows = function_rows(module, handler)
        changes = [x for x in hrows if x["opcode"] == 67]
        self.video_ctx = next(x["register"] for x in changes if x["operands"][0] == self.video_ctor)
        last = changes[-1]                       # the controls page (action 2), last in the chain
        i = hrows.index(last)
        j = max(k for k in range(i) if hrows[k]["opcode"] == 64)
        self.leave = (hrows[j]["offset"], last["offset"])   # apply, remove Default and Return
        self.end = hrows[-1]["offset"]           # op65
        assert hrows[-1]["opcode"] == 65
        # The action == 2 test: op10 r1 0x2; op1 r3 2; op46 r2; op55 r2 end.
        k = j
        while not (hrows[k]["opcode"] == 10 and hrows[k + 1]["opcode"] == 1 and hrows[k + 1]["operands"] == [2]):
            k -= 1
        self.check2 = hrows[k]
        assert hrows[k + 2]["opcode"] == 46 and hrows[k + 3]["opcode"] == 55
        # The tabs: the options state's index (the vector's field), the x of
        # each glyph and the place after the third tab's action.
        trows = function_rows(module, self.tabs)
        self.opt_ctx = next(x for x in trows if x["opcode"] == 11)["operands"][1]
        glyphs = [n for n, x in enumerate(trows) if x.get("text", "").startswith("ui/opt_glyph_")]
        assert len(glyphs) == 3
        self.glyph_x = []
        for n in glyphs:
            m = n
            while trows[m].get("symbol") != "!vec2":
                m += 1
            assert trows[m + 1]["opcode"] == 1
            self.glyph_x.append(trows[m + 1])
        n = glyphs[2]
        while not (trows[n]["opcode"] == 1 and trows[n]["operands"] == [2] and trows[n + 1]["opcode"] == 57):
            n += 1
        assert trows[n + 2]["opcode"] == 75
        self.after_tabs = trows[n + 3]
        assert self.after_tabs["opcode"] == 14 and self.after_tabs["size"] == 8
        # The video page's loop (from the clear before its yield to its jump back).
        y = next(n for n, x in enumerate(video) if x["opcode"] == 68)
        self.loop = (video[y - 1]["offset"], video[-1]["offset"] + video[-1]["size"])
        assert video[y - 1]["opcode"] == 74 and video[-1]["opcode"] == 54
        self.by = by


def build_ctor(module, s, page, ctx, others):
    """The page's constructor: tabs, the arrow, the rows, the original loop."""
    a = Asm(module, 12)
    a.global_(1, "logInfo")
    a.string(2, f"Port Options State {ctx}")
    a.native(0, 1)
    a.emit(76, 1, 2)
    a.emit(63, 0, s.tabs)
    # Buttons precede check boxes in the control factory's action vector.
    for side in range(2):
        a.call_begin(0, "createButton")
        a.string(3, ARROW_IMAGES[side])
        arrow_position(a, side)
        a.integer(5, 0)
        a.emit(2, 6, F32(ARROW["scale"]))
        a.string(7, page["arrow_tips"][side])
        a.native(0, 6)
        a.emit(78, 1, 0x30002, 0x70004)
        a.clear(5, 6, 0)
        a.add_action(s.opt_ctx, PAGE_ACTIONS[side])
    a.label_text(page["number"], -40, -410, 2)
    labels = 1
    checks = 0
    sliders = 0
    for column, x in ((page["rows"][0], LEFT_X), (page["rows"][1], RIGHT_X)):
        # Six or seven check boxes fit only closer together, a little higher up.
        long_column = len(column) > 5
        y = TOP_Y + (20 if long_column else 0)
        check_pitch = 100 if long_column else CHECK_PITCH
        for row in column:
            if isinstance(row, Slider):
                a.label_text(row.title, x, y, 3)
                labels += 1
                a.call_begin(0, "createSlider")
                a.vec2(3, x + 78, y - 34)
                slider_value(a, row, f"init{sliders}")
                a.native(0, 3)
                a.emit(78, 1, 0x30002, 0x4)
                row.slider = sliders
                sliders += 1
                a.label_text(" ", x + 700, y - 130, 2)   # the value: the apply below writes it
                row.value_label = labels
                labels += 1
                y -= SLIDER_PITCH
            elif isinstance(row, Radios):
                a.label_text(row.title, x, y, 3)
                labels += 1
                row.checks = []
                for i, (value, caption) in enumerate(row.options):
                    bx = x + 94 + i * RADIO_STEP
                    a.call_begin(0, "createCheckbox")
                    a.string(3, CHECKBOX)
                    a.vec2(4, bx, y - 31)
                    a.integer(5, 0)
                    a.setting(6, row.key, "asInt")
                    a.integer(7, value)
                    a.emit(46, 6)
                    a.boolean(6, 6, f"r{checks}")
                    a.native(0, 5)
                    a.emit(78, 1, 0x30002, 0x60004)
                    a.clear(0)
                    row.checks.append((checks, value))
                    a.add_action(s.opt_ctx, page["first_action"] + checks)
                    checks += 1
                    a.label_text(caption, bx + 184, y - 31 - 117, 2)
                    labels += 1
                y -= RADIO_PITCH
            else:
                cx = x if x == LEFT_X else x + 40
                a.call_begin(0, "createCheckbox")
                a.string(3, CHECKBOX)
                a.vec2(4, cx, y)
                a.integer(5, 0)
                a.setting(6, row.key, "asInt")
                a.integer(7, int(row.on))
                a.emit(46, 6)
                a.boolean(6, 6, f"c{checks}")
                a.native(0, 5)
                a.emit(78, 1, 0x30002, 0x60004)
                a.clear(0)
                row.check = checks
                a.add_action(s.opt_ctx, page["first_action"] + checks)
                checks += 1
                a.label_text(row.caption, cx + 184, y - 117, 2)
                labels += 1
                y -= check_pitch
    # The values' labels: the page's apply writes them (and the same settings).
    a.emit(64, 2, 0)
    # The original page loop.
    start, end = s.loop
    base = len(module.code) + 8 + len(a.data)
    a.raw(relocated(module, start, end, base))
    return function(module, a, 12)


def slider_value(a, row, tag):
    """r4 = the slider's position 0..1 from the setting (uses r5 .. r7)."""
    if row.kind == "range":
        # The live native bridge and older profiles may store "55.0000".
        # Property.asInt rejects that representation; the slider is floating
        # point, and its apply path already rounds to the requested steps.
        a.setting(4, row.key, "asFloat")
        a.integer(5, row.lo)
        a.emit(37, 4)
        a.emit(17, 4)
        a.emit(2, 5, F32(row.hi - row.lo))
        a.emit(39, 4)
        a.clear(5)
    elif row.kind == "list":
        a.setting(4, row.key, "asInt")
        n = len(row.values) - 1
        for i, v in enumerate(row.values):
            a.move(4, 5)
            a.integer(6, v)
            a.emit(46, 5)
            a.emit(55, 5, f"{tag}_n{i}")
            a.emit(2, 4, F32(i / n))
            a.emit(54, 0, f"{tag}_d")
            a.label(f"{tag}_n{i}")
        a.emit(2, 4, F32(row.values.index(row.default) / n))
        a.label(f"{tag}_d")
        a.clear(5, 6)
    else:
        a.setting(4, "PortGyro", "asBool")
        a.emit(55, 4, f"{tag}_off")
        a.setting(4, "PortGyroSpeed", "asFloat")
        a.emit(2, 5, F32(3.0))
        a.emit(39, 4)
        a.clear(5)
        a.emit(54, 0, f"{tag}_d")
        a.label(f"{tag}_off")
        a.emit(2, 4, F32(0.0))
        a.label(f"{tag}_d")


def build_apply(module, page, texts):
    """The page's controls into Settings, the sliders' values into their labels."""
    a = Asm(module, 10)
    for column in page["rows"]:
        for row in column:
            if isinstance(row, Slider):
                tag = f"s{row.slider}"
                # r0 = position: int(v * steps + 0.5)
                a.get_slider(0, row.slider)
                a.emit(2, 1, F32(row.steps))
                a.emit(38, 0)
                a.emit(2, 1, F32(0.5))
                a.emit(36, 0)
                a.emit(16, 0)
                a.clear(1)
                if row.kind == "range":
                    a.integer(1, row.step)
                    a.emit(38, 0)
                    a.integer(1, row.lo)
                    a.emit(36, 0)
                    a.move(0, 6)
                    a.store(row.key)
                    a.emit(20, 6)
                    a.string(7, row.suffix)
                    a.emit(36, 6)
                    a.clear(7)
                    a.set_label(row.value_label)
                elif row.kind == "list":
                    a.move(0, 8)
                    for i, (v, name) in enumerate(zip(row.values, row.names)):
                        a.move(8, 1)
                        a.integer(2, i)
                        a.emit(46, 1)
                        a.emit(55, 1, f"{tag}_n{i}")
                        a.clear(1, 2)
                        a.integer(0, v)
                        a.store(row.key)
                        a.string(6, name)
                        a.set_label(row.value_label)
                        a.emit(54, 0, f"{tag}_d")
                        a.label(f"{tag}_n{i}")
                    a.label(f"{tag}_d")
                    a.clear(1, 2, 8)
                else:
                    # Off at 0; else PortGyroSpeed "w.f" (tenths), shown "w,f".
                    a.move(0, 8)
                    a.move(8, 1)
                    a.integer(2, 0)
                    a.emit(46, 1)
                    a.emit(55, 1, f"{tag}_on")
                    a.clear(1, 2)
                    a.store_text("PortGyro", "0")
                    a.string(6, texts["off"])
                    a.set_label(row.value_label)
                    a.emit(54, 0, f"{tag}_d")
                    a.label(f"{tag}_on")
                    a.clear(1, 2)
                    a.store_text("PortGyro", "1")
                    # r8 tenths: r9 = whole = int(r8 * 0.1 + 0.001), r8 -= r9 * 10
                    a.move(8, 9)
                    a.emit(17, 9)
                    a.emit(2, 0, F32(0.1))
                    a.move(0, 1)
                    a.move(9, 0)
                    a.emit(38, 0)
                    a.emit(2, 1, F32(0.001))
                    a.emit(36, 0)
                    a.emit(16, 0)
                    a.move(0, 9)
                    a.integer(1, 10)
                    a.emit(38, 0)                   # r0 = whole * 10
                    a.move(0, 1)
                    a.move(8, 0)
                    a.emit(37, 0)                   # r0 = tenths - whole * 10
                    a.move(0, 8)
                    a.clear(1)
                    # PortGyroSpeed = "<whole>.<frac>"
                    a.move(9, 0)
                    a.emit(20, 0)
                    a.string(1, ".")
                    a.emit(36, 0)
                    a.move(8, 1)
                    a.emit(20, 1)
                    a.emit(36, 0)
                    a.clear(1)
                    a.global_(1, "Settings")
                    a.string(2, "PortGyroSpeed")
                    a.emit(59, 1, 1)
                    a.clear(0, 1, 2)
                    # the label "<whole><decimal><frac>"
                    a.move(9, 6)
                    a.emit(20, 6)
                    a.string(7, texts["decimal"])
                    a.emit(36, 6)
                    a.move(8, 7)
                    a.emit(20, 7)
                    a.emit(36, 6)
                    a.clear(7)
                    a.set_label(row.value_label)
                    a.label(f"{tag}_d")
                    a.clear(8, 9)
            elif isinstance(row, Radios):
                for index, value in row.checks:
                    a.get_check(1, index)
                    a.emit(0, 2, 1)
                    a.emit(46, 1)
                    a.emit(55, 1, f"r{index}_n")
                    a.clear(1, 2)
                    a.integer(0, value)
                    a.store(row.key)
                    a.label(f"r{index}_n")
                    a.clear(1, 2)
            else:
                a.get_check(1, row.check)
                a.emit(56, 1, f"c{row.check}_on")
                a.clear(1)
                a.store_text(row.key, row.off)
                a.emit(54, 0, f"c{row.check}_d")
                a.label(f"c{row.check}_on")
                a.clear(1)
                a.store_text(row.key, row.on)
                a.label(f"c{row.check}_d")
    a.global_(1, "saveSettings")
    a.native(0, 0)
    a.emit(75, 1, 0)
    a.emit(65)
    return function(module, a, 10)


def build_default(module, page):
    """Default: the page's settings as the port starts them."""
    a = Asm(module, 8)
    for column in page["rows"]:
        for row in column:
            if isinstance(row, Slider):
                if row.kind == "range":
                    v = (row.default - row.lo) / (row.hi - row.lo)
                elif row.kind == "list":
                    v = row.values.index(row.default) / (len(row.values) - 1)
                else:
                    v = 0.0
                a.set_slider(row.slider, v)
            elif isinstance(row, Radios):
                for index, value in row.checks:
                    a.set_check(index, lambda value=value: a.emit(0, 6, int(value == row.default)))
            else:
                a.set_check(row.check, lambda row=row: a.emit(0, 6, int(bool(row.default))))
    a.emit(64, 0, 0)
    a.emit(65)
    return function(module, a, 8)


def build_click(module, s, page, ctors, contexts):
    """Clicks: the tabs' shared handler, then the page's check boxes (a
    radio row keeps one checked, a check box toggles) and the arrow; every
    change is applied at once."""
    a = Asm(module, 10)
    a.move(-6, 0)
    a.move(-5, 1)
    a.move(-4, 2)
    a.emit(63, 3, s.handler)
    a.call_begin(0, "handleMouseButtonLeft")
    a.move(-6, 3)
    a.move(-5, 4)
    a.move(-4, 5)
    a.native(0, 4)
    a.emit(75, 1, 2)
    a.emit(16, 0)
    a.move(-4, 1)
    a.emit(55, 1, "end")
    a.move(0, 1)
    a.integer(2, -1)
    a.emit(50, 1)
    a.emit(55, 1, "end")
    a.emit(12, 0, 2, s.opt_ctx)
    a.move(0, 3)
    a.emit(58, 1, 1)
    a.emit(16, 1)
    # Both side arrows wrap, so every page can be reached in either direction.
    for side, delta in enumerate((-1, 1)):
        a.move(1, 2)
        a.integer(3, PAGE_ACTIONS[side])
        a.emit(46, 2)
        a.emit(55, 2, f"arrow_next{side}")
        start, end = s.leave
        base = len(module.code) + 8 + len(a.data)
        a.raw(relocated(module, start, end, base))
        other = (page["index"] + delta) % len(ctors)
        a.emit(67, contexts[other], ctors[other], 0x200)
        a.emit(54, 0, "end")
        a.label(f"arrow_next{side}")
    a.label("checks")
    for column in page["rows"]:
        for row in column:
            if isinstance(row, Radios):
                for index, value in row.checks:
                    a.move(1, 2)
                    a.integer(3, page["first_action"] + index)
                    a.emit(46, 2)
                    a.emit(55, 2, f"n{index}")
                    for other, _ in row.checks:
                        a.set_check(other, lambda on=(other == index): a.emit(0, 6, int(on)))
                    a.emit(54, 0, "apply")
                    a.label(f"n{index}")
            elif isinstance(row, Check):
                index = row.check
                a.move(1, 2)
                a.integer(3, page["first_action"] + index)
                a.emit(46, 2)
                a.emit(55, 2, f"n{index}")

                def toggled(index=index):
                    a.get_check(6, index)
                    a.boolean(6, 6, f"t{index}")
                    # boolean() gives r6 = checked: the toggle is its negation
                    a.emit(55, 6, f"t{index}_was_off")
                    a.emit(0, 6, 0)
                    a.emit(54, 0, f"t{index}_set")
                    a.label(f"t{index}_was_off")
                    a.emit(0, 6, 1)
                    a.label(f"t{index}_set")
                a.set_check(index, toggled)
                a.emit(54, 0, "apply")
                a.label(f"n{index}")
    a.emit(54, 0, "end")
    a.label("apply")
    a.emit(64, 2, 0)
    a.label("end")
    a.emit(65)
    return function(module, a, 10)


def patch_options(module, lang):
    if module.legacy:
        return dict(sites=[])
    texts = TEXTS.get(lang, TEXTS["en"])
    s = Sites(module)
    original = bytes(module.code)
    contexts = len(module.contexts)
    specs = pages(texts)
    count = len(specs)
    ctx = [contexts + i for i in range(count)]
    page = [dict(index=i, rows=specs[i], first_action=100 + 100 * i,
                 arrow_tips=(texts["back"], texts["next"]), number=f"{i + 1} / {count}") for i in range(count)]
    # Constructors first (the click handlers name them), then the rest.
    ctor = [build_ctor(module, s, page[i], ctx[i], None) for i in range(count)]
    apply_ = [build_apply(module, page[i], texts) for i in range(count)]
    default = [build_default(module, page[i]) for i in range(count)]
    click = [build_click(module, s, page[i], ctor, ctx) for i in range(count)]
    video = module.contexts[s.video_ctx]
    import copy
    for i in range(count):
        c = copy.deepcopy(video)
        bind = bytes.fromhex(c["bindings"])
        words = list(struct.unpack(f"<{len(bind) // 4}I", bind))
        assert words[-1] & 0xffff == s.video_ctx
        words[-1] = (words[-1] & 0xffff0000) | ctx[i]
        c["bindings"] = struct.pack(f"<{len(words)}I", *words).hex()
        extra = list(struct.unpack("<3I", bytes.fromhex(c["extra"])))
        extra[0], extra[1] = apply_[i], default[i]
        c["extra"] = struct.pack("<3I", *extra).hex()
        for m in c["methods"]:
            if m["name"] == "onMouseButtonLeft":
                m["code_offset"] = click[i]
            elif m["name"] == "onDefault":
                m["code_offset"] = default[i]
        module.contexts.append(c)
    sites = []

    def jump(at, target):
        assert bytes(module.code[at:at + 8]) == original[at:at + 8]
        module.code[at:at + 8] = p32(module.opcode(54)) + p32(target)
        sites.append(at)

    # The fourth tab after the third one's action.
    a = Asm(module, 8)
    a.call_begin(0, "createButton")
    a.string(3, "ui/mainmenu_options")
    a.vec2(4, 170, 600)
    a.string(5, texts["tab"])
    a.native(0, 4)
    a.emit(78, 1, 0x30002, 0x50004)
    a.clear(0)
    a.add_action(s.opt_ctx, TAB_ACTION)
    at = s.after_tabs["offset"]
    a.raw(original[at:at + 8])
    a.emit(54, 0, at + 8)
    jump(at, inline(module, a))
    # The three glyphs a little to the left.
    for row in s.glyph_x:
        at = row["offset"]
        old = row["operands"][0]
        old = old - (1 << 32) if old >= 1 << 31 else old
        assert bytes(module.code[at:at + 8]) == original[at:at + 8]
        module.code[at + 4:at + 8] = p32(old - 110)
        sites.append(at)
    # The shared handler: the fourth tab's action goes to the first page.
    a = Asm(module, 6)
    a.move(1, 2)
    a.integer(3, TAB_ACTION)
    a.emit(46, 2)
    a.emit(55, 2, "next")
    start, end = s.leave
    base = len(module.code) + len(a.data)
    a.raw(relocated(module, start, end, base))
    a.emit(67, ctx[0], ctor[0], 0x200)
    a.emit(54, 0, s.end)
    a.label("next")
    at = s.check2["offset"]
    a.raw(original[at:at + 8])
    a.emit(54, 0, at + 8)
    jump(at, inline(module, a))
    return dict(tabs=hex(s.tabs), handler=hex(s.handler), contexts=ctx, constructors=[hex(c) for c in ctor],
                clicks=[hex(c) for c in click], applies=[hex(c) for c in apply_], defaults=[hex(c) for c in default],
                sites=[hex(x) for x in sites])
