package org.thevoid.port;

import android.os.Looper;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
import java.util.HashMap;
import java.util.Map;

/** Runs the shipping HardwareInput, Keys and Input against Android's actual event classes. */
public final class HardwareInputTest {
    static int checks;
    static int eventDevice = -42;
    static float lt, rt, hatX, hatY;
    static void check(boolean value, String message) {
        ++checks;
        if (!value) throw new AssertionError(message);
    }
    static KeyEvent key(int device, int code, boolean down, boolean pad, int repeat) {
        return new KeyEvent(0, SystemClock.uptimeMillis(), down ? 0 : 1, code, repeat, 0, device, 0, 0,
            pad ? InputDevice.SOURCE_GAMEPAD : InputDevice.SOURCE_KEYBOARD);
    }
    static MotionEvent motion(int source, int action, int buttons, float x, float y, float rx, float ry) {
        MotionEvent.PointerProperties property = new MotionEvent.PointerProperties();
        property.id = 0; property.toolType = MotionEvent.TOOL_TYPE_MOUSE;
        MotionEvent.PointerCoords point = new MotionEvent.PointerCoords();
        point.x = x; point.y = y;
        point.setAxisValue(MotionEvent.AXIS_Z, rx); point.setAxisValue(MotionEvent.AXIS_RZ, ry);
        point.setAxisValue(MotionEvent.AXIS_LTRIGGER, lt); point.setAxisValue(MotionEvent.AXIS_RTRIGGER, rt);
        point.setAxisValue(MotionEvent.AXIS_HAT_X, hatX); point.setAxisValue(MotionEvent.AXIS_HAT_Y, hatY);
        return MotionEvent.obtain(0, SystemClock.uptimeMillis(), action, 1,
            new MotionEvent.PointerProperties[] {property}, new MotionEvent.PointerCoords[] {point},
            0, buttons, 1, 1, eventDevice, 0, source, 0);
    }
    static void press(HardwareInput h, int device, int key, boolean pad) {
        check(h.key(key(device, key, true, pad, 0)), "key down handled " + key);
    }
    static void lift(HardwareInput h, int device, int key, boolean pad) {
        check(h.key(key(device, key, false, pad, 0)), "key up handled " + key);
    }
    static void set(Object object, String field, Object value) throws Exception {
        java.lang.reflect.Field f = object.getClass().getDeclaredField(field); f.setAccessible(true); f.set(object, value);
    }

    public static void main(String[] args) {
        try { test(); }
        catch (Throwable error) { error.printStackTrace(System.out); System.exit(1); }
    }

    private static void test() throws Exception {
        if (Looper.getMainLooper() == null) Looper.prepareMainLooper();
        Controls c = new Controls();
        Input input = new Input();
        HardwareInput h = new HardwareInput(c, input, new HashMap<>());
        for (int key = KeyEvent.KEYCODE_A; key <= KeyEvent.KEYCODE_Z; ++key) {
            press(h, 1, key, false);
            check(GameActivity.keys.getOrDefault(Keys.dik(key), false), "keyboard DIK");
            lift(h, 1, key, false);
        }
        for (int key = KeyEvent.KEYCODE_NUMPAD_0; key <= KeyEvent.KEYCODE_NUMPAD_9; ++key)
            check(Keys.dik(key) != 0, "numpad");
        press(h, 1, KeyEvent.KEYCODE_W, false);
        h.key(key(1, KeyEvent.KEYCODE_W, true, false, 1));
        h.key(key(1, KeyEvent.KEYCODE_W, true, false, 2));
        lift(h, 1, KeyEvent.KEYCODE_W, false);
        check(!GameActivity.keys.get(Input.W), "keyboard repeat must not leak refs");
        press(h, 1, KeyEvent.KEYCODE_W, false); press(h, 2, KeyEvent.KEYCODE_W, false);
        lift(h, 1, KeyEvent.KEYCODE_W, false);
        check(GameActivity.keys.get(Input.W), "second keyboard still held");
        h.onInputDeviceRemoved(2);
        check(!GameActivity.keys.get(Input.W), "unplug releases only its refs");

        c.cursor = true;
        press(h, 3, KeyEvent.KEYCODE_BUTTON_A, true);
        check(GameActivity.buttons.getOrDefault(0, false), "menu A is primary click");
        c.cursor = false;
        lift(h, 3, KeyEvent.KEYCODE_BUTTON_A, true);
        check(!GameActivity.buttons.get(0), "release preserves binding across screen change");
        press(h, 3, KeyEvent.KEYCODE_BUTTON_A, true);
        check(GameActivity.keys.getOrDefault(Input.SPACE, false), "world A jumps");
        lift(h, 3, KeyEvent.KEYCODE_BUTTON_A, true);
        c.skipping = true;
        press(h, 3, KeyEvent.KEYCODE_BUTTON_A, true);
        check(GameActivity.keys.getOrDefault(0x1c, false), "A skips dialogue without also jumping");
        lift(h, 3, KeyEvent.KEYCODE_BUTTON_A, true); c.skipping = false;
        press(h, 3, KeyEvent.KEYCODE_BUTTON_L2, true); press(h, 3, KeyEvent.KEYCODE_BUTTON_X, true);
        lift(h, 3, KeyEvent.KEYCODE_BUTTON_X, true);
        check(GameActivity.buttons.get(1), "LT and X share RMB refs");
        h.onInputDeviceRemoved(3);
        check(!GameActivity.buttons.get(1), "unplug held trigger");

        h.motion(motion(InputDevice.SOURCE_JOYSTICK, MotionEvent.ACTION_MOVE, 0, 0, -1, 0, 0));
        h.frame(1000000000L, true); h.frame(1016000000L, true);
        check(GameActivity.keys.get(Input.W), "stick forward");
        press(h, 1, KeyEvent.KEYCODE_W, false);
        c.cursor = true; h.frame(1032000000L, true);
        check(GameActivity.keys.get(Input.W), "menu stops stick without releasing keyboard W");
        lift(h, 1, KeyEvent.KEYCODE_W, false);
        check(!GameActivity.keys.get(Input.W), "no stale stick movement");
        int moves = GameActivity.moves;
        h.frame(1048000000L, true);
        check(GameActivity.moves > moves, "left stick moves menu cursor");
        h.motion(motion(InputDevice.SOURCE_JOYSTICK, MotionEvent.ACTION_MOVE, 0, .05f, -.04f, .02f, 0));
        moves = GameActivity.moves; h.frame(1064000000L, true);
        check(GameActivity.moves == moves, "stick drift dead zone");
        h.motion(motion(InputDevice.SOURCE_JOYSTICK, MotionEvent.ACTION_MOVE, 0, 0, 0, Float.NaN, Float.POSITIVE_INFINITY));
        h.frame(1080000000L, true); check(GameActivity.moves == moves, "nonfinite axes rejected");
        h.motion(motion(InputDevice.SOURCE_JOYSTICK, 2, 0, 0, 0, 1, 0));
        int before = GameActivity.dx;
        h.frame(1096000000L, true); int fast = GameActivity.dx - before;
        press(h, -42, KeyEvent.KEYCODE_BUTTON_THUMBR, true);
        before = GameActivity.dx;
        h.frame(1112000000L, true); int slow = GameActivity.dx - before;
        check(fast >= 7 && slow <= 2, "R3 precision is five times slower");
        h.release();

        h.mouse(motion(InputDevice.SOURCE_MOUSE_RELATIVE, MotionEvent.ACTION_MOVE, 1, 5, -3, 0, 0));
        h.mouse(motion(InputDevice.SOURCE_MOUSE_RELATIVE, MotionEvent.ACTION_BUTTON_PRESS, 1, 5, -3, 0, 0));
        check(GameActivity.buttons.get(0), "mouse primary held exactly once across duplicate events");
        h.mouse(motion(InputDevice.SOURCE_MOUSE_RELATIVE, MotionEvent.ACTION_BUTTON_RELEASE, 0, 0, 0, 0, 0));
        check(!GameActivity.buttons.get(0), "mouse release");
        moves = GameActivity.moves;
        h.mouse(motion(InputDevice.SOURCE_MOUSE, MotionEvent.ACTION_DOWN, 1, 100, 100, 0, 0));
        check(GameActivity.moves > moves, "first absolute mouse click synchronizes cursor without preceding hover");
        h.mouse(motion(InputDevice.SOURCE_MOUSE, MotionEvent.ACTION_UP, 0, 100, 100, 0, 0));
        h.frame(1100000000L, true); check(!GameActivity.hidden, "hardware movement overrides touch hide setting");
        set(h, "pointerMoved", SystemClock.uptimeMillis() - 31000);
        press(h, 1, KeyEvent.KEYCODE_W, false);
        h.frame(1116000000L, true); check(GameActivity.hidden, "keys cannot postpone 30-second pointer timeout");
        lift(h, 1, KeyEvent.KEYCODE_W, false);
        h.mouse(motion(InputDevice.SOURCE_MOUSE_RELATIVE, MotionEvent.ACTION_MOVE, 0, 1, 0, 0, 0));
        h.frame(1132000000L, true); check(!GameActivity.hidden, "movement reveals hidden cursor");
        h.touch(); h.frame(1148000000L, true); check(GameActivity.hidden, "touch restores cursor preference");
        h.frame(1164000000L, false); check(!GameActivity.hidden, "visible touch cursor preference");

        for (int id : InputDevice.getDeviceIds()) {
            if (InputDevice.getDevice(id).getName().equals("Void QA pad")) { eventDevice = id; break; }
        }
        check(eventDevice != -42, "real virtual HID ranges present");
        lt = .8f;
        h.motion(motion(InputDevice.SOURCE_JOYSTICK, 2, 0, 0, 0, 0, 0));
        check(GameActivity.buttons.get(1), "analog LT press");
        lt = .4f;
        h.motion(motion(InputDevice.SOURCE_JOYSTICK, 2, 0, 0, 0, 0, 0));
        check(GameActivity.buttons.get(1), "trigger hysteresis holds above release threshold");
        lt = .3f; rt = .8f;
        h.motion(motion(InputDevice.SOURCE_JOYSTICK, 2, 0, 0, 0, 0, 0));
        check(!GameActivity.buttons.get(1) && GameActivity.buttons.get(0), "LT release and RT press");
        press(h, eventDevice, KeyEvent.KEYCODE_BUTTON_R2, true);
        rt = 0;
        h.motion(motion(InputDevice.SOURCE_JOYSTICK, 2, 0, 0, 0, 0, 0));
        check(!GameActivity.buttons.get(0), "digital and analog trigger reports cannot duplicate refs");
        hatX = 1;
        h.motion(motion(InputDevice.SOURCE_JOYSTICK, 2, 0, 0, 0, 0, 0));
        check(GameActivity.keys.getOrDefault(0xc9, false), "hat right accelerates time");
        hatX = 0; hatY = -1; int wheel = GameActivity.wheel;
        h.motion(motion(InputDevice.SOURCE_JOYSTICK, 2, 0, 0, 0, 0, 0));
        check(!GameActivity.keys.get(0xc9) && GameActivity.wheel == wheel + 120, "hat neutral releases and up scrolls");
        hatY = 0;
        h.motion(motion(InputDevice.SOURCE_JOYSTICK, 2, 0, 0, 0, 0, 0));
        h.release();

        c.panel = true; c.cursor = false;
        press(h, 3, KeyEvent.KEYCODE_BUTTON_R2, true);
        check(!GameActivity.buttons.get(0), "panel must not click game underneath");
        h.motion(motion(InputDevice.SOURCE_JOYSTICK, MotionEvent.ACTION_MOVE, 0, 0, 1, 0, 0));
        h.frame(1170000000L, true);
        h.frame(1180000000L, true); check(c.scroll > 0, "controller scrolls help");
        press(h, 3, KeyEvent.KEYCODE_BUTTON_B, true);
        check(!c.panel, "B closes panel");
        h.release(); input.releaseAll();
        for (boolean held : GameActivity.keys.values()) check(!held, "no held keyboard key after pause");
        for (boolean held : GameActivity.buttons.values()) check(!held, "no held mouse button after pause");
        System.out.println("PASS HardwareInput: " + checks + " checks on Android " + android.os.Build.VERSION.SDK_INT);
    }
}

class Controls {
    boolean cursor, skipping, panel;
    int scroll;
    void hardwareUsed() { } void hardwareActivity() { }
    boolean hardwareCursor() { return cursor; } boolean hardwareSkipping() { return skipping; }
    boolean hardwareJournal(int code) { return false; }
    float hardwareCursorSpeed() { return 500; }
    boolean panelVisible() { return panel; } void closePanel() { panel = false; }
    void scrollHardwareHelp(int pixels) { scroll += pixels; }
    void escape() { } boolean openHardwareHelp() { return false; }
    int getHeight() { return 1080; } int getWidth() { return 2400; }
    boolean hasWindowFocus() { return false; } boolean hasPointerCapture() { return false; }
    void requestFocus() { } void requestPointerCapture() { } void releasePointerCapture() { }
}
class Settings { static String gameLanguage = "English"; static final float PIXELS_PER_DEGREE = 1.7432f; }
class Profile {
    static String prop(String xml, String name) {
        java.util.regex.Matcher m = java.util.regex.Pattern.compile("name=\"" + name + "\" value=\"([^\"]*)\"").matcher(xml);
        return m.find() ? m.group(1) : "";
    }
}
class GameActivity {
    static final Map<Integer, Boolean> keys = new HashMap<>(), buttons = new HashMap<>();
    static int moves, wheel, dx; static boolean hidden;
    static void nativeKey(int key, boolean down) { keys.put(key, down); }
    static void nativeMouseButton(int button, boolean down) { buttons.put(button, down); }
    static void nativeMouseMove(float x, float y, boolean relative) { ++moves; if (relative) dx += (int)x; }
    static void nativeMouseWarp(float x, float y) { }
    static void nativeMouseWheel(int delta) { wheel += delta; }
    static void nativeMovement(float x, float y) { }
    static void nativeSetCursorHidden(boolean value) { hidden = value; }
    static class Release {
        static String read(java.io.File file) {
            try { return new String(java.nio.file.Files.readAllBytes(file.toPath()), java.nio.charset.StandardCharsets.UTF_8); }
            catch (java.io.IOException e) { return ""; }
        }
    }
}
