package org.thevoid.port;

import android.os.Handler;
import android.os.Looper;
import java.util.HashMap;
import java.util.Map;

/**
 * The original keyboard (DirectInput scan codes) and mouse, shared by every
 * touch control on the UI thread: presses are reference counted, so a key
 * held by two controls is released when the last one lets go.
 */
final class Input {
    static final int ESC = 0x01, W = 0x11, A = 0x1e, S = 0x1f, D = 0x20, CTRL = 0x1d, SHIFT = 0x2a;
    static final int SPACE = 0x39, B = 0x30, J = 0x24, M = 0x32, F5 = 0x3f, F8 = 0x42;
    static final int HEART_PROGRESS = 0x64;   /* F13, reserved for the held-heart command. */
    static final int BODY_STATS = 0x66, BODY_RETURN = 0x67, BODY_LYMPHA = 0x68;
    static final int BODY_WIDGET = 0x69;
    static final int LEFT = 0, RIGHT = 1;

    private final Map<Integer, Integer> keyRefs = new HashMap<>();
    private final Map<Integer, Integer> buttonRefs = new HashMap<>();
    private final Handler handler = new Handler(Looper.getMainLooper());
    private float restX, restY;   /* fractions of a pixel of relative motion not sent yet */

    void key(int code, boolean down) {
        int before = keyRefs.getOrDefault(code, 0), after = Math.max(0, before + (down ? 1 : -1));
        if (after == 0) keyRefs.remove(code); else keyRefs.put(code, after);
        if ((before == 0) != (after == 0)) GameActivity.nativeKey(code, down);
    }

    /** Press and release: held long enough for a game that polls once a frame. */
    void tapKey(int code) {
        key(code, true);
        handler.postDelayed(() -> key(code, false), 90);
    }

    void button(int code, boolean down) {
        int before = buttonRefs.getOrDefault(code, 0), after = Math.max(0, before + (down ? 1 : -1));
        if (after == 0) buttonRefs.remove(code); else buttonRefs.put(code, after);
        if ((before == 0) != (after == 0)) GameActivity.nativeMouseButton(code, down);
    }

    /** A click as a mouse makes it: the press a frame after the cursor
     *  arrived (menus highlight on motion), held a few frames. */
    void click(int code) {
        handler.postDelayed(() -> button(code, true), 50);
        handler.postDelayed(() -> button(code, false), 140);
    }

    boolean held(int code) { return buttonRefs.containsKey(code); }

    /** Relative mouse motion in game pixels (camera), keeping the fractions. */
    void look(float dx, float dy) {
        restX += dx;
        restY += dy;
        int ix = (int) restX, iy = (int) restY;
        if (ix == 0 && iy == 0) return;
        restX -= ix;
        restY -= iy;
        GameActivity.nativeMouseMove(ix, iy, true);
    }

    /** The cursor to a point of the view in [0,1] (motion the game sees). */
    void cursorTo(float fx, float fy) { GameActivity.nativeMouseMove(fx, fy, false); }

    /** The cursor to a point of the view without mouse motion. */
    void warp(float fx, float fy) { GameActivity.nativeMouseWarp(fx, fy); }

    void wheel(int delta) { GameActivity.nativeMouseWheel(delta); }

    void movement(float x, float y) { GameActivity.nativeMovement(x, y); }

    void releaseAll() {
        handler.removeCallbacksAndMessages(null);
        for (Integer code : keyRefs.keySet().toArray(new Integer[0])) GameActivity.nativeKey(code, false);
        for (Integer code : buttonRefs.keySet().toArray(new Integer[0])) GameActivity.nativeMouseButton(code, false);
        keyRefs.clear();
        buttonRefs.clear();
        restX = restY = 0;
        movement(0, 0);
    }
}
