package org.thevoid.portprobe;

import java.util.HashMap;
import java.util.Map;

/** Original DirectInput scan codes; mouse button 0 is left, 1 is right. */
public final class TouchInput {
    public static final int ESC = 0x01, ONE = 0x02, TWO = 0x03, THREE = 0x04, ZERO = 0x0b;
    public static final int W = 0x11, CTRL = 0x1d, A = 0x1e, S = 0x1f, D = 0x20;
    public static final int J = 0x24, SHIFT = 0x2a, B = 0x30, M = 0x32, SPACE = 0x39;
    public static final int F5 = 0x3f, F8 = 0x42, F12 = 0x58, PAGE_UP = 0xc9, PAGE_DOWN = 0xd1;

    public interface Sink {
        void key(int scanCode, boolean down);
        void mouseButton(int button, boolean down);
        void mouseMove(float x, float y, boolean relative);
    }

    private static final int BUTTON = 1, JOYSTICK = 2, LOOK = 3;
    private static final class Pointer {
        int kind, code;
        boolean mouse, drawing;
        float x, y, originX, originY, radius;
        final boolean[] directions = new boolean[4];
    }

    private final Sink sink;
    private final Map<Integer, Pointer> pointers = new HashMap<>();
    private final Map<Integer, Integer> keys = new HashMap<>();
    private final Map<Integer, Integer> buttons = new HashMap<>();
    private static final int[] DIRECTIONS = {W, S, A, D};
    private int joystickId = -1, lookId = -1;

    public TouchInput(Sink sink) {
        if (sink == null) throw new IllegalArgumentException("sink is required");
        this.sink = sink;
    }

    private Pointer begin(int id, int kind, float x, float y) {
        if (id < 0 || !Float.isFinite(x) || !Float.isFinite(y))
            throw new IllegalArgumentException("invalid pointer");
        release(id);
        Pointer pointer = new Pointer();
        pointer.kind = kind;
        pointer.x = pointer.originX = x;
        pointer.y = pointer.originY = y;
        pointers.put(id, pointer);
        return pointer;
    }

    private void ref(int code, boolean mouse, boolean down) {
        Map<Integer, Integer> state = mouse ? buttons : keys;
        int before = state.containsKey(code) ? state.get(code) : 0;
        if (!down && before == 0) return;
        int after = before + (down ? 1 : -1);
        if (after == 0) state.remove(code); else state.put(code, after);
        if ((before == 0) != (after == 0)) {
            if (mouse) sink.mouseButton(code, down); else sink.key(code, down);
            if (!mouse && code == CTRL) syncDrawing();
        }
    }

    public void button(int id, int code, boolean mouse) {
        if ((mouse && (code < 0 || code > 1)) || (!mouse && (code < 1 || code > 255)))
            throw new IllegalArgumentException("invalid input code");
        Pointer pointer = begin(id, BUTTON, 0, 0);
        pointer.code = code;
        pointer.mouse = mouse;
        ref(code, mouse, true);
    }

    public void joystick(int id, float x, float y, float radius) {
        if (!Float.isFinite(radius) || radius <= 0) throw new IllegalArgumentException("invalid radius");
        Pointer pointer = begin(id, joystickId < 0 || joystickId == id ? JOYSTICK : 0, x, y);
        if (pointer.kind == JOYSTICK) {
            joystickId = id;
            pointer.radius = radius;
        }
    }

    public void look(int id, float x, float y) {
        Pointer pointer = begin(id, lookId < 0 || lookId == id ? LOOK : 0, x, y);
        if (pointer.kind == LOOK) {
            lookId = id;
            syncDrawing();
        }
    }

    private void syncDrawing() {
        Pointer pointer = pointers.get(lookId);
        if (pointer == null) return;
        boolean drawing = keys.containsKey(CTRL);
        if (pointer.drawing == drawing) return;
        if (drawing) sink.mouseMove(pointer.x, pointer.y, false);
        pointer.drawing = drawing;
        ref(0, true, drawing);
    }

    public void move(int id, float x, float y) {
        if (!Float.isFinite(x) || !Float.isFinite(y)) throw new IllegalArgumentException("invalid coordinates");
        Pointer pointer = pointers.get(id);
        if (pointer == null) return;
        if (pointer.kind == JOYSTICK) {
            float threshold = pointer.radius * 0.25f;
            float dx = x - pointer.originX, dy = y - pointer.originY;
            boolean[] next = {dy < -threshold, dy > threshold, dx < -threshold, dx > threshold};
            for (int i = 0; i < next.length; i++) {
                if (pointer.directions[i] != next[i]) {
                    pointer.directions[i] = next[i];
                    ref(DIRECTIONS[i], false, next[i]);
                }
            }
        } else if (pointer.kind == LOOK) {
            if (pointer.drawing) sink.mouseMove(x, y, false);
            else sink.mouseMove(x - pointer.x, y - pointer.y, true);
        }
        pointer.x = x;
        pointer.y = y;
    }

    public void release(int id) {
        Pointer pointer = pointers.remove(id);
        if (pointer == null) return;
        if (pointer.kind == BUTTON) ref(pointer.code, pointer.mouse, false);
        else if (pointer.kind == JOYSTICK) {
            for (int i = 0; i < DIRECTIONS.length; i++) {
                if (pointer.directions[i]) ref(DIRECTIONS[i], false, false);
            }
            joystickId = -1;
        } else if (pointer.kind == LOOK) {
            if (pointer.drawing) ref(0, true, false);
            lookId = -1;
        }
    }

    public void cancel() {
        for (int id : pointers.keySet().toArray(new Integer[0])) release(id);
    }

    public void click(int code, boolean mouse) {
        ref(code, mouse, true);
        ref(code, mouse, false);
    }

    public int pointerCount() { return pointers.size(); }
    public int heldCount() { return keys.size() + buttons.size(); }
}
