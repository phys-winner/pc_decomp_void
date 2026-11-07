package org.thevoid.port;

import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import java.util.ArrayDeque;
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
    private static final class MouseClick {
        final int code;
        final Runnable hover;
        MouseClick(int code, Runnable hover) { this.code = code; this.hover = hover; }
    }
    private final ArrayDeque<MouseClick> clicks = new ArrayDeque<>();
    private boolean clickPressed;
    private long clickFrame, clickTime;
    private final Runnable clickStep = this::advanceClick;

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

    /** Hover first, then keep Down through a complete input-polling frame. */
    void click(int code) { click(code, null); }

    void click(int code, Runnable hover) {
        clicks.addLast(new MouseClick(code, hover));
        if (clicks.size() == 1) startClick();
    }

    private void startClick() {
        MouseClick click = clicks.peekFirst();
        if (click.hover != null) click.hover.run();
        handler.postDelayed(clickStep, 50);
    }

    private void advanceClick() {
        MouseClick click = clicks.peekFirst();
        if (click == null) return;
        if (!clickPressed) {
            button(click.code, true);
            clickPressed = true;
            clickFrame = GameActivity.nativeHudState() >>> 32;
            clickTime = SystemClock.uptimeMillis();
            handler.postDelayed(clickStep, 90);
        } else {
            long frames = ((GameActivity.nativeHudState() >>> 32) - clickFrame) & 0xffffffffL;
            // One Present can finish a frame that polled before Down arrived.
            if (frames < 2 && SystemClock.uptimeMillis() - clickTime < 600) {
                handler.postDelayed(clickStep, 10);
                return;
            }
            button(click.code, false);
            clickPressed = false;
            clicks.removeFirst();
            if (!clicks.isEmpty()) startClick();
        }
    }

    void cancelClicks() {
        handler.removeCallbacks(clickStep);
        if (clickPressed) button(clicks.peekFirst().code, false);
        clicks.clear();
        clickPressed = false;
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
        cancelClicks();
        handler.removeCallbacksAndMessages(null);
        for (Integer code : keyRefs.keySet().toArray(new Integer[0])) GameActivity.nativeKey(code, false);
        for (Integer code : buttonRefs.keySet().toArray(new Integer[0])) GameActivity.nativeMouseButton(code, false);
        keyRefs.clear();
        buttonRefs.clear();
        restX = restY = 0;
        movement(0, 0);
    }
}
