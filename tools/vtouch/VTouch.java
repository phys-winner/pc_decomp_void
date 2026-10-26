package org.thevoid.vtouch;

import android.os.SystemClock;
import android.view.InputDevice;
import android.view.InputEvent;
import android.view.MotionEvent;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

/**
 * Multi-touch for testing the touch layer on a device: run through
 * app_process as the shell user (which may inject input, as the `input`
 * command does) it turns a script into MotionEvents with several pointers,
 * in the display's own (rotated) pixels. Lines:
 *   d SLOT X Y    finger SLOT touches (X, Y)
 *   m SLOT X Y    finger SLOT moves to (X, Y)
 *   u SLOT        finger SLOT lifts
 *   s MS          sleep MS milliseconds
 * Built and run by tools/vtouch.py.
 */
public final class VTouch {
    private static final class Finger { int slot; float x, y; }

    private static Object manager;
    private static Method inject;
    private static final List<Finger> fingers = new ArrayList<>();
    private static long downTime;

    public static void main(String[] args) throws Exception {
        try {
            Class<?> global = Class.forName("android.hardware.input.InputManagerGlobal");   /* Android 14+ */
            manager = global.getMethod("getInstance").invoke(null);
        } catch (ClassNotFoundException e) {
            Class<?> im = Class.forName("android.hardware.input.InputManager");
            manager = im.getMethod("getInstance").invoke(null);
        }
        inject = manager.getClass().getMethod("injectInputEvent", InputEvent.class, int.class);
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in));
        for (String line; (line = in.readLine()) != null; ) {
            String[] f = line.trim().split("\\s+");
            if (f.length == 0 || f[0].isEmpty()) continue;
            switch (f[0]) {
            case "d": {
                Finger g = new Finger();
                g.slot = Integer.parseInt(f[1]);
                g.x = Float.parseFloat(f[2]);
                g.y = Float.parseFloat(f[3]);
                fingers.add(g);
                if (fingers.size() == 1) {
                    downTime = SystemClock.uptimeMillis();
                    send(MotionEvent.ACTION_DOWN);
                } else {
                    send(MotionEvent.ACTION_POINTER_DOWN | ((fingers.size() - 1) << MotionEvent.ACTION_POINTER_INDEX_SHIFT));
                }
                break;
            }
            case "m": {
                Finger g = find(Integer.parseInt(f[1]));
                if (g == null) break;
                g.x = Float.parseFloat(f[2]);
                g.y = Float.parseFloat(f[3]);
                send(MotionEvent.ACTION_MOVE);
                break;
            }
            case "u": {
                Finger g = find(Integer.parseInt(f[1]));
                if (g == null) break;
                int index = fingers.indexOf(g);
                if (fingers.size() == 1) send(MotionEvent.ACTION_UP);
                else send(MotionEvent.ACTION_POINTER_UP | (index << MotionEvent.ACTION_POINTER_INDEX_SHIFT));
                fingers.remove(g);
                break;
            }
            case "s":
                Thread.sleep(Long.parseLong(f[1]));
                break;
            default:
                break;
            }
        }
    }

    private static Finger find(int slot) {
        for (Finger g : fingers) if (g.slot == slot) return g;
        return null;
    }

    private static void send(int action) throws Exception {
        int n = fingers.size();
        MotionEvent.PointerProperties[] props = new MotionEvent.PointerProperties[n];
        MotionEvent.PointerCoords[] coords = new MotionEvent.PointerCoords[n];
        for (int i = 0; i < n; ++i) {
            props[i] = new MotionEvent.PointerProperties();
            props[i].id = fingers.get(i).slot;
            props[i].toolType = MotionEvent.TOOL_TYPE_FINGER;
            coords[i] = new MotionEvent.PointerCoords();
            coords[i].x = fingers.get(i).x;
            coords[i].y = fingers.get(i).y;
            coords[i].pressure = 1f;
            coords[i].size = 0.05f;
        }
        MotionEvent e = MotionEvent.obtain(downTime, SystemClock.uptimeMillis(), action, n, props, coords, 0, 0, 1f, 1f,
                0, 0, InputDevice.SOURCE_TOUCHSCREEN, 0);
        inject.invoke(manager, e, 1);   /* WAIT_FOR_RESULT: a slow UI must not lengthen the gesture's event times. */
        e.recycle();
    }
}
