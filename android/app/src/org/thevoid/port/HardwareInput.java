package org.thevoid.port;

import android.hardware.input.InputManager;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
import java.util.HashMap;
import java.util.Map;

/** Hardware input shares the touch layer's reference-counted original keys and mouse. */
final class HardwareInput implements InputManager.InputDeviceListener {
    private final Controls controls;
    private final Input in;
    private final Map<String, Integer> actions;
    private final Map<Long, Integer> held = new HashMap<>();
    private int padDevice = -1;
    private float walkX, walkY, lookX, lookY, wheelRest;
    private long frameTime, wheelAt, pointerMoved;
    private boolean pointerActive, mouseActive, mouseKnown;
    private float mouseX, mouseY;
    private Boolean hidden;
    private static final int WALK = 0x10000, MOUSE = 0x20000, EXTRA_A = 0x30000;
    private static final int[] MOUSE_FLAGS = {MotionEvent.BUTTON_PRIMARY, MotionEvent.BUTTON_SECONDARY,
        MotionEvent.BUTTON_TERTIARY, MotionEvent.BUTTON_BACK, MotionEvent.BUTTON_FORWARD};

    HardwareInput(Controls controls, Input in, Map<String, Integer> actions) {
        this.controls = controls;
        this.in = in;
        this.actions = new HashMap<>(actions);
    }

    void settings(java.io.File file) {
        String xml = GameActivity.Release.read(file);
        for (String action : actions.keySet()) {
            String value = Profile.prop(xml, "action_" + action);
            int code = Keys.forName(value.split(",", 2)[0].trim());
            if (code != 0) actions.put(action, code);
        }
    }

    private int action(String name, int fallback) { return actions.getOrDefault(name, fallback); }
    private static long token(int device, int key) { return ((long)device << 32) | (key & 0xffffffffL); }
    private boolean down(int device, int key) { return held.containsKey(token(device, key)); }

    private void send(int code, boolean down) {
        if (code < 0) in.button(-code - 1, down); else if (code > 0) in.key(code, down);
    }

    private void bind(int device, int key, int code, boolean down) {
        long token = token(device, key);
        if (down) {
            if (!held.containsKey(token)) { held.put(token, code); send(code, true); }
        } else {
            Integer before = held.remove(token);
            if (before != null) send(before, false);
        }
    }

    static boolean controller(KeyEvent e) {
        InputDevice device = e.getDevice();
        return e.isFromSource(InputDevice.SOURCE_GAMEPAD) || e.isFromSource(InputDevice.SOURCE_JOYSTICK)
            || device != null && (device.supportsSource(InputDevice.SOURCE_GAMEPAD)
                || device.supportsSource(InputDevice.SOURCE_JOYSTICK));
    }

    boolean key(KeyEvent e) {
        int key = e.getKeyCode(), device = e.getDeviceId();
        boolean down = e.getAction() == KeyEvent.ACTION_DOWN, pad = controller(e);
        if (!down && e.getAction() != KeyEvent.ACTION_UP) return false;
        if (!down && held.containsKey(token(device, key))) {
            if (pad && key == KeyEvent.KEYCODE_BUTTON_A) bind(device, EXTRA_A, 0, false);
            bind(device, key, 0, false);
            return true;
        }
        if (controls.panelVisible()) {
            if (key == KeyEvent.KEYCODE_ESCAPE || pad && (key == KeyEvent.KEYCODE_BUTTON_B
                    || key == KeyEvent.KEYCODE_BUTTON_START || key == KeyEvent.KEYCODE_BUTTON_A)) {
                if (down && e.getRepeatCount() == 0) controls.closePanel();
                return true;
            }
            if (!pad) return false;
            if (down && (key == KeyEvent.KEYCODE_DPAD_UP || key == KeyEvent.KEYCODE_DPAD_DOWN))
                controls.scrollHardwareHelp(key == KeyEvent.KEYCODE_DPAD_UP ? -90 : 90);
            return true;
        }
        if (!pad) {
            int code = Keys.dik(key);
            if (code == 0) return false;
            if (down) controls.hardwareUsed();
            if (down && e.getRepeatCount() > 0 && down(device, key)) GameActivity.nativeKey(held.get(token(device, key)), true);
            else bind(device, key, code, down);
            return true;
        }
        if (down) controls.hardwareUsed();
        if (padDevice != device) {
            stopWalking();
            walkX = walkY = lookX = lookY = 0;
            padDevice = device;
        }
        if (down && down(device, key)) return true;
        int code;
        switch (key) {
        case KeyEvent.KEYCODE_BUTTON_A:
            code = controls.hardwareSkipping() ? action("skip_cutscene", 0x1c)
                : controls.hardwareCursor() ? Keys.MOUSE_LEFT : action("jump", Input.SPACE);
            // Some original scenes expose neither subtitles nor a cursor while waiting for skip.
            if (down && !controls.hardwareCursor() && !controls.hardwareSkipping() && code != action("skip_cutscene", 0x1c))
                bind(device, EXTRA_A, action("skip_cutscene", 0x1c), true);
            break;
        case KeyEvent.KEYCODE_BUTTON_B:
        case KeyEvent.KEYCODE_BUTTON_START:
        case KeyEvent.KEYCODE_BACK:
            if (down) controls.escape();
            code = 0;
            break;
        case KeyEvent.KEYCODE_BUTTON_X: code = action("use", Keys.MOUSE_RIGHT); break;
        case KeyEvent.KEYCODE_BUTTON_Y: code = action("body", Input.B); break;
        case KeyEvent.KEYCODE_BUTTON_L1: code = action("paint", Input.CTRL); break;
        case KeyEvent.KEYCODE_BUTTON_R1:
            code = action("database", Input.J);
            if (down && controls.hardwareJournal(code)) code = 0;
            break;
        case KeyEvent.KEYCODE_BUTTON_SELECT: code = action("map", Input.M); break;
        case KeyEvent.KEYCODE_BUTTON_THUMBL: code = action("run", Input.SHIFT); break;
        case KeyEvent.KEYCODE_BUTTON_THUMBR: code = 0; break;
        case KeyEvent.KEYCODE_BUTTON_L2: code = Keys.MOUSE_RIGHT; break;
        case KeyEvent.KEYCODE_BUTTON_R2: code = Keys.MOUSE_LEFT; break;
        case KeyEvent.KEYCODE_DPAD_UP:
        case KeyEvent.KEYCODE_DPAD_DOWN:
            if (down) { in.wheel(key == KeyEvent.KEYCODE_DPAD_UP ? 120 : -120); wheelAt = SystemClock.uptimeMillis() + 400; }
            code = 0;
            break;
        case KeyEvent.KEYCODE_DPAD_LEFT: code = action("time_decelerate", 0xd1); break;
        case KeyEvent.KEYCODE_DPAD_RIGHT: code = action("time_accelerate", 0xc9); break;
        default: return KeyEvent.isGamepadButton(key);
        }
        if (down && code == Keys.MOUSE_LEFT && controls.openHardwareHelp()) code = 0;
        bind(device, key, code, down);
        return true;
    }

    private static float axis(MotionEvent e, int axis) {
        float value = e.getAxisValue(axis);
        if (!Float.isFinite(value)) return 0;
        InputDevice device = e.getDevice();
        InputDevice.MotionRange range = device == null ? null : device.getMotionRange(axis, e.getSource());
        float dead = Math.min(.9f, Math.max(.15f, range == null ? 0 : range.getFlat()));
        return Math.abs(value) <= dead ? 0 : Math.copySign(Math.min(1f, (Math.abs(value) - dead) / (1f - dead)), value);
    }

    boolean motion(MotionEvent e) {
        if (!e.isFromSource(InputDevice.SOURCE_JOYSTICK) || e.getActionMasked() != MotionEvent.ACTION_MOVE) return false;
        float x = axis(e, MotionEvent.AXIS_X), y = axis(e, MotionEvent.AXIS_Y);
        InputDevice device = e.getDevice();
        boolean z = device == null || device.getMotionRange(MotionEvent.AXIS_Z, e.getSource()) != null
            && device.getMotionRange(MotionEvent.AXIS_RZ, e.getSource()) != null;
        float rx = axis(e, z ? MotionEvent.AXIS_Z : MotionEvent.AXIS_RX);
        float ry = axis(e, z ? MotionEvent.AXIS_RZ : MotionEvent.AXIS_RY);
        if (x != 0 || y != 0 || rx != 0 || ry != 0) controls.hardwareUsed();
        if (padDevice != e.getDeviceId()) {
            if (x == 0 && y == 0 && rx == 0 && ry == 0 && padDevice != -1) return true;
            stopWalking();
            padDevice = e.getDeviceId();
        }
        walkX = x; walkY = y; lookX = rx; lookY = ry;
        hat(e, MotionEvent.AXIS_HAT_X, KeyEvent.KEYCODE_DPAD_LEFT, KeyEvent.KEYCODE_DPAD_RIGHT);
        hat(e, MotionEvent.AXIS_HAT_Y, KeyEvent.KEYCODE_DPAD_UP, KeyEvent.KEYCODE_DPAD_DOWN);
        trigger(e, MotionEvent.AXIS_LTRIGGER, MotionEvent.AXIS_BRAKE, KeyEvent.KEYCODE_BUTTON_L2, Keys.MOUSE_RIGHT);
        trigger(e, MotionEvent.AXIS_RTRIGGER, MotionEvent.AXIS_GAS, KeyEvent.KEYCODE_BUTTON_R2, Keys.MOUSE_LEFT);
        return true;
    }

    private void hat(MotionEvent e, int axis, int negative, int positive) {
        InputDevice device = e.getDevice();
        if (device == null || device.getMotionRange(axis, e.getSource()) == null) return;
        float value = e.getAxisValue(axis);
        for (int key : new int[] {negative, positive}) {
            boolean next = key == negative ? value < -.5f : value > .5f;
            if (next == down(e.getDeviceId(), key)) continue;
            key(new KeyEvent(0, 0, next ? KeyEvent.ACTION_DOWN : KeyEvent.ACTION_UP, key, 0,
                0, e.getDeviceId(), 0, 0, InputDevice.SOURCE_GAMEPAD));
        }
    }

    private void trigger(MotionEvent e, int axis, int fallback, int key, int code) {
        InputDevice device = e.getDevice();
        if (device == null) return;
        if (device.getMotionRange(axis, e.getSource()) == null) axis = fallback;
        InputDevice.MotionRange range = device.getMotionRange(axis, e.getSource());
        if (range == null || range.getMax() <= range.getMin()) return;
        float value = (e.getAxisValue(axis) - range.getMin()) / (range.getMax() - range.getMin());
        boolean next = value > (down(e.getDeviceId(), key) ? .35f : .55f);
        if (next && !down(e.getDeviceId(), key)) {
            controls.hardwareUsed();
            if (code == Keys.MOUSE_LEFT && controls.openHardwareHelp()) code = 0;
        }
        if (!controls.panelVisible()) bind(e.getDeviceId(), key, code, next);
    }

    static boolean mouseEvent(MotionEvent e) {
        return e.isFromSource(InputDevice.SOURCE_MOUSE) || e.isFromSource(InputDevice.SOURCE_MOUSE_RELATIVE);
    }

    boolean mouse(MotionEvent e) {
        if (!mouseEvent(e) || controls.panelVisible()) return false;
        int action = e.getActionMasked();
        controls.hardwareUsed();
        mouseActive = true;
        boolean relative = e.isFromSource(InputDevice.SOURCE_MOUSE_RELATIVE);
        if (action == MotionEvent.ACTION_MOVE || action == MotionEvent.ACTION_HOVER_MOVE || action == MotionEvent.ACTION_HOVER_ENTER
                || !relative && action != MotionEvent.ACTION_HOVER_EXIT && action != MotionEvent.ACTION_CANCEL) {
            if (relative) {
                for (int i = 0; i < e.getHistorySize(); ++i) move(e.getHistoricalX(i), e.getHistoricalY(i));
                move(e.getX(), e.getY());
            } else if (!mouseKnown || e.getX() != mouseX || e.getY() != mouseY) {
                if (controls.hardwareCursor()) in.cursorTo(e.getX() / controls.getWidth(), e.getY() / controls.getHeight());
                else in.look(e.getAxisValue(MotionEvent.AXIS_RELATIVE_X), e.getAxisValue(MotionEvent.AXIS_RELATIVE_Y));
                moved();
                mouseX = e.getX(); mouseY = e.getY(); mouseKnown = true;
            }
        }
        if (action == MotionEvent.ACTION_SCROLL) {
            wheelRest += e.getAxisValue(MotionEvent.AXIS_VSCROLL) * 120;
            int delta = (int)wheelRest;
            wheelRest -= delta;
            if (delta != 0) in.wheel(delta);
        }
        int buttons = action == MotionEvent.ACTION_CANCEL ? 0 : e.getButtonState();
        for (int i = 0; i < MOUSE_FLAGS.length; ++i) {
            boolean next = (buttons & MOUSE_FLAGS[i]) != 0;
            if (next && !down(e.getDeviceId(), MOUSE + i) && i == 0 && controls.openHardwareHelp()) return true;
            bind(e.getDeviceId(), MOUSE + i, -i - 1, next);
        }
        capture();
        return true;
    }

    private void moved() {
        pointerActive = true;
        pointerMoved = SystemClock.uptimeMillis();
        controls.hardwareActivity();
    }

    private void move(float x, float y) {
        if (!Float.isFinite(x) || !Float.isFinite(y) || x == 0 && y == 0) return;
        in.look(x, y);
        moved();
    }

    void capture() {
        if (mouseActive && controls.hasWindowFocus() && !controls.panelVisible() && !controls.hasPointerCapture()) {
            controls.requestFocus();
            controls.requestPointerCapture();
        }
    }

    private void stopWalking() {
        if (padDevice == -1) return;
        for (int i = 0; i < 4; ++i) bind(padDevice, WALK + i, 0, false);
    }

    void frame(long nanos, boolean touchHidesCursor) {
        float dt = frameTime == 0 ? 0 : Math.max(0, Math.min(.05f, (nanos - frameTime) / 1e9f));
        frameTime = nanos;
        if (controls.panelVisible()) {
            stopWalking();
            controls.scrollHardwareHelp(Math.round((lookY != 0 ? lookY : walkY) * dt * 700));
        } else if (padDevice != -1) {
            boolean cursor = controls.hardwareCursor();
            float x = lookX, y = lookY;
            if (cursor && Math.hypot(walkX, walkY) > Math.hypot(x, y)) { x = walkX; y = walkY; }
            float speed = cursor ? controls.hardwareCursorSpeed() : 180f * Settings.PIXELS_PER_DEGREE;
            if (down(padDevice, KeyEvent.KEYCODE_BUTTON_THUMBR)) speed *= .2f;
            if (dt > 0) move(x * Math.abs(x) * speed * dt, y * Math.abs(y) * speed * dt);
            boolean[] directions = {!cursor && walkY < -.25f, !cursor && walkY > .25f,
                !cursor && walkX < -.25f, !cursor && walkX > .25f};
            String[] names = {"forward", "back", "left", "right"};
            int[] defaults = {Input.W, Input.S, Input.A, Input.D};
            for (int i = 0; i < 4; ++i) bind(padDevice, WALK + i, action(names[i], defaults[i]), directions[i]);
            long now = SystemClock.uptimeMillis();
            int scroll = (down(padDevice, KeyEvent.KEYCODE_DPAD_UP) ? 1 : 0) - (down(padDevice, KeyEvent.KEYCODE_DPAD_DOWN) ? 1 : 0);
            if (scroll != 0 && now >= wheelAt) { in.wheel(scroll * 120); wheelAt = now + 100; }
        }
        boolean next = pointerActive ? SystemClock.uptimeMillis() - pointerMoved >= 30000 : touchHidesCursor;
        if (hidden == null || hidden != next) {
            hidden = next;
            GameActivity.nativeSetCursorHidden(next);
            android.util.Log.i("TheVoid", "hardware cursor: " + (next ? "hidden" : "visible"));
        }
    }

    void touch() {
        release();
        pointerActive = mouseActive = false;
    }

    void release() {
        for (long token : held.keySet().toArray(new Long[0])) send(held.remove(token), false);
        walkX = walkY = lookX = lookY = wheelRest = 0;
        frameTime = 0;
        padDevice = -1;
        mouseKnown = false;
        if (controls.hasPointerCapture()) controls.releasePointerCapture();
    }

    @Override public void onInputDeviceRemoved(int id) {
        for (long token : held.keySet().toArray(new Long[0]))
            if ((int)(token >> 32) == id) send(held.remove(token), false);
        if (padDevice == id) { walkX = walkY = lookX = lookY = 0; padDevice = -1; }
    }
    @Override public void onInputDeviceAdded(int id) { }
    @Override public void onInputDeviceChanged(int id) { }

    private static String language() {
        String language = Settings.gameLanguage.toLowerCase(java.util.Locale.ROOT);
        return language.isEmpty() ? java.util.Locale.getDefault().getLanguage() : language;
    }

    static String helpTitle() {
        String l = language();
        return l.startsWith("ru") ? "Управление геймпадом" : l.startsWith("de") || l.startsWith("german")
            ? "Gamepad-Steuerung" : l.startsWith("pl") || l.startsWith("polish") ? "Sterowanie padem" : "Gamepad controls";
    }

    static String helpText() {
        String l = language();
        if (l.startsWith("ru")) return
            "Левый стик — движение. В меню и при рисовании оба стика перемещают курсор.\n\n"
            + "Правый стик — камера / курсор. Удерживайте R3 (нажатие стика) для точного движения.\n\n"
            + "A / × — прыжок; в меню — выбор; в сценах и роликах — пропуск.\n"
            + "B / ○ — назад / меню. Start / Options — меню.\n"
            + "X / □ — взаимодействие (правая кнопка мыши).\n"
            + "Y / △ — тело. RB / R1 — журнал. Select / View — карта / выход из камеры.\n\n"
            + "LB / L1 — удерживать кисть. RT / R2 — удерживать левую кнопку мыши (мазок, перенос цвета, перетаскивание).\n"
            + "LT / L2 — правая кнопка мыши (взаимодействие, поворот тела, сдвиг карты).\n"
            + "L3 — удерживать бег.\n\n"
            + "Крестовина ↑ / ↓ — колесо мыши: цвет, прокрутка, масштаб. ← / → — замедлить / ускорить время на карте.\n\n"
            + "Курсор скрывается через 30 секунд без движения мыши или стика. Кнопки названы по Xbox / PlayStation.\n"
            + "Здесь: стик или ↑ / ↓ — прокрутка; A, B или Start — закрыть.";
        if (l.startsWith("de") || l.startsWith("german")) return
            "Linker Stick: bewegen; in Menüs und beim Malen bewegen beide Sticks den Cursor.\n\n"
            + "Rechter Stick: Kamera / Cursor. R3 halten: präzise Bewegung.\n\n"
            + "A / ×: springen, auswählen, Szenen überspringen.\nB / ○: zurück / Menü. Start / Options: Menü.\n"
            + "X / □: benutzen (rechte Maustaste). Y / △: Körper. RB / R1: Tagebuch. Select / View: Karte.\n\n"
            + "LB / L1 halten: Pinsel. RT / R2: linke Maustaste (malen, Farbe übertragen, ziehen).\n"
            + "LT / L2: rechte Maustaste (benutzen, Körper drehen, Karte verschieben). L3 halten: laufen.\n\n"
            + "Steuerkreuz ↑ / ↓: Mausrad (Farbe, scrollen, Zoom). ← / →: Zeit auf der Karte langsamer / schneller.\n\n"
            + "Nach 30 Sekunden ohne Maus- oder Stickbewegung verschwindet der Cursor. Xbox- / PlayStation-Tasten.\n"
            + "Hier: Stick oder ↑ / ↓ zum Scrollen; A, B oder Start zum Schließen.";
        if (l.startsWith("pl") || l.startsWith("polish")) return
            "Lewy drążek: ruch; w menu i podczas malowania oba drążki poruszają kursorem.\n\n"
            + "Prawy drążek: kamera / kursor. Przytrzymaj R3: precyzyjny ruch.\n\n"
            + "A / ×: skok, wybór, pomijanie scen. B / ○: wstecz / menu. Start / Options: menu.\n"
            + "X / □: użyj (prawy przycisk myszy). Y / △: ciało. RB / R1: dziennik. Select / View: mapa.\n\n"
            + "LB / L1: przytrzymaj pędzel. RT / R2: lewy przycisk myszy (malowanie, przenoszenie koloru, przeciąganie).\n"
            + "LT / L2: prawy przycisk myszy (użycie, obrót ciała, przesuwanie mapy). L3: przytrzymaj bieg.\n\n"
            + "Krzyżak ↑ / ↓: kółko myszy (kolor, przewijanie, zoom). ← / →: wolniejszy / szybszy czas na mapie.\n\n"
            + "Kursor znika po 30 sekundach bez ruchu myszy lub drążka. Przyciski Xbox / PlayStation.\n"
            + "Tutaj: drążek lub ↑ / ↓ przewija; A, B lub Start zamyka.";
        return "Left stick: move. In menus and while painting, either stick moves the cursor.\n\n"
            + "Right stick: camera / cursor. Hold R3 (stick click) for precise movement.\n\n"
            + "A / ×: jump; select in menus; skip scenes and videos.\nB / ○: back / menu. Start / Options: menu.\n"
            + "X / □: use (right mouse button). Y / △: body. RB / R1: journal. Select / View: map / leave chamber.\n\n"
            + "Hold LB / L1: brush. RT / R2: left mouse button (paint, transfer colour, drag).\n"
            + "LT / L2: right mouse button (use, rotate body, pan map). Hold L3: run.\n\n"
            + "D-pad ↑ / ↓: mouse wheel (colour, scroll, zoom). ← / →: slower / faster time on the map.\n\n"
            + "The cursor hides after 30 seconds without mouse or stick movement. Buttons use Xbox / PlayStation names.\n"
            + "Here: stick or ↑ / ↓ scrolls; A, B or Start closes.";
    }
}
