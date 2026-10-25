package org.thevoid.portprobe;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;

/** Diagnostic only: dispatches multi-pointer events through the actual Activity view tree. */
public final class InputProbe extends Instrumentation {
    private long downTime;
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }

    private static View find(View view, String label) {
        if (view instanceof Button && ((Button) view).getText().toString().equals(label)) return view;
        if (label.equals("surface") && view.getContentDescription() != null &&
                view.getContentDescription().toString().startsWith("Movement and camera")) return view;
        if (view instanceof ViewGroup) {
            ViewGroup group = (ViewGroup) view;
            for (int i = 0; i < group.getChildCount(); i++) {
                View found = find(group.getChildAt(i), label);
                if (found != null) return found;
            }
        }
        return null;
    }

    private static float[] point(View view, float x, float y) {
        if (view == null) throw new AssertionError("test control missing");
        int[] position = new int[2];
        view.getLocationOnScreen(position);
        return new float[] {position[0] + view.getWidth() * x, position[1] + view.getHeight() * y};
    }

    private void event(int action, int[] ids, float[]... points) {
        MotionEvent.PointerProperties[] properties = new MotionEvent.PointerProperties[ids.length];
        MotionEvent.PointerCoords[] coords = new MotionEvent.PointerCoords[ids.length];
        for (int i = 0; i < ids.length; i++) {
            properties[i] = new MotionEvent.PointerProperties();
            properties[i].id = ids[i];
            properties[i].toolType = MotionEvent.TOOL_TYPE_FINGER;
            coords[i] = new MotionEvent.PointerCoords();
            coords[i].x = points[i][0]; coords[i].y = points[i][1];
            coords[i].pressure = 1; coords[i].size = 1;
        }
        if (action == MotionEvent.ACTION_DOWN) downTime = SystemClock.uptimeMillis();
        MotionEvent event = MotionEvent.obtain(downTime, SystemClock.uptimeMillis(), action, ids.length,
                properties, coords, 0, 0, 1, 1, 0, 0, InputDevice.SOURCE_TOUCHSCREEN, 0);
        try { sendPointerSync(event); } finally { event.recycle(); }
        waitForIdleSync();
    }

    private static void check(MainActivity activity, int held, int pointers) {
        if (activity.input.heldCount() != held || activity.input.pointerCount() != pointers)
            throw new AssertionError("held=" + activity.input.heldCount() + " pointers=" + activity.input.pointerCount()
                    + ", expected " + held + "/" + pointers);
    }

    @Override public void onStart() {
        Bundle result = new Bundle();
        MainActivity activity = null;
        try {
            Intent intent = new Intent(getTargetContext(), MainActivity.class);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            activity = (MainActivity) startActivitySync(intent);
            waitForIdleSync();
            View root = activity.getWindow().getDecorView();
            View surface = find(root, "surface");
            float[] move = point(surface, 0.16f, 0.65f);
            float[] forward = {move[0], move[1] - 80};
            float[] look = point(surface, 0.70f, 0.50f);
            float[] lookMoved = {look[0] + 30, look[1] + 20};
            float[] run = point(find(root, "Run"), 0.5f, 0.5f);
            event(MotionEvent.ACTION_DOWN, new int[] {7}, move);
            event(MotionEvent.ACTION_MOVE, new int[] {7}, forward);
            event(MotionEvent.ACTION_POINTER_DOWN | (1 << 8), new int[] {7, 19}, forward, look);
            event(MotionEvent.ACTION_POINTER_DOWN | (2 << 8), new int[] {7, 19, 31}, forward, look, run);
            check(activity, 2, 3);
            event(MotionEvent.ACTION_POINTER_UP, new int[] {7, 19, 31}, forward, look, run);
            event(MotionEvent.ACTION_MOVE, new int[] {19, 31}, lookMoved, run);
            check(activity, 1, 2);
            event(MotionEvent.ACTION_POINTER_UP | (1 << 8), new int[] {19, 31}, lookMoved, run);
            event(MotionEvent.ACTION_UP, new int[] {19}, lookMoved);
            check(activity, 0, 0);

            float[] paint = point(find(root, "Paint (hold)"), 0.5f, 0.5f);
            event(MotionEvent.ACTION_DOWN, new int[] {2}, paint);
            event(MotionEvent.ACTION_POINTER_DOWN | (1 << 8), new int[] {2, 9}, paint, look);
            check(activity, 2, 2);
            event(MotionEvent.ACTION_MOVE, new int[] {2, 9}, paint, lookMoved);
            event(MotionEvent.ACTION_POINTER_UP, new int[] {2, 9}, paint, lookMoved);
            check(activity, 0, 1);
            event(MotionEvent.ACTION_UP, new int[] {9}, lookMoved);
            check(activity, 0, 0);

            event(MotionEvent.ACTION_DOWN, new int[] {4}, run);
            event(MotionEvent.ACTION_POINTER_DOWN | (1 << 8), new int[] {4, 11}, run, move);
            event(MotionEvent.ACTION_MOVE, new int[] {4, 11}, run, forward);
            check(activity, 2, 2);
            event(MotionEvent.ACTION_CANCEL, new int[] {4, 11}, run, forward);
            check(activity, 0, 0);

            event(MotionEvent.ACTION_DOWN, new int[] {0}, run);
            check(activity, 1, 1);
            final MainActivity tested = activity;
            runOnMainSync(() -> tested.finish());
            waitForIdleSync();
            check(activity, 0, 0);
            result.putString("result", "PASS: real Activity multitouch IDs 7/19/31, movement+look+run, paint stroke, cancellation, pause release");
            finish(Activity.RESULT_OK, result);
        } catch (Throwable error) {
            if (activity != null) {
                final MainActivity failed = activity;
                runOnMainSync(() -> failed.input.cancel());
            }
            result.putString("result", "FAIL: " + error);
            finish(Activity.RESULT_CANCELED, result);
        }
    }
}
