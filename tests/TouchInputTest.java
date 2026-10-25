package org.thevoid.portprobe;

import java.util.ArrayList;
import java.util.List;

public final class TouchInputTest {
    private static final class Recorder implements TouchInput.Sink {
        final List<String> events = new ArrayList<>();
        @Override public void key(int code, boolean down) { events.add("k" + code + ":" + down); }
        @Override public void mouseButton(int button, boolean down) { events.add("b" + button + ":" + down); }
        @Override public void mouseMove(float x, float y, boolean relative) { events.add("m" + relative + ":" + x + "," + y); }
    }

    public static void main(String[] args) {
        Recorder recorder = new Recorder();
        TouchInput input = new TouchInput(recorder);
        input.joystick(7, 100, 100, 40);
        input.move(7, 120, 70);
        assert recorder.events.contains("k17:true") && recorder.events.contains("k32:true");
        input.look(19, 300, 100);
        input.move(19, 330, 90);
        assert recorder.events.contains("mtrue:30.0,-10.0");
        input.button(31, TouchInput.SHIFT, false);
        assert input.heldCount() == 3 && input.pointerCount() == 3;
        input.release(7);
        input.move(19, 340, 95);
        assert recorder.events.contains("mtrue:10.0,5.0");
        assert input.heldCount() == 1;
        input.cancel();
        assert input.heldCount() == 0 && input.pointerCount() == 0;

        recorder.events.clear();
        input.look(3, 400, 100);
        input.button(6, TouchInput.CTRL, false);
        assert recorder.events.get(0).equals("k29:true");
        assert recorder.events.get(1).equals("mfalse:400.0,100.0");
        assert recorder.events.get(2).equals("b0:true");
        input.move(3, 420, 150);
        assert recorder.events.get(3).equals("mfalse:420.0,150.0");
        input.release(6);
        assert recorder.events.get(4).equals("k29:false");
        assert recorder.events.get(5).equals("b0:false");
        input.move(3, 430, 160);
        assert recorder.events.get(6).equals("mtrue:10.0,10.0");
        input.cancel();

        recorder.events.clear();
        input.button(2, TouchInput.SPACE, false);
        input.button(9, TouchInput.SPACE, false);
        assert recorder.events.size() == 1;
        input.release(2);
        assert recorder.events.size() == 1 && input.heldCount() == 1;
        input.click(TouchInput.SPACE, false);
        assert recorder.events.size() == 1;
        input.release(9);
        assert recorder.events.size() == 2 && recorder.events.get(1).equals("k57:false");

        recorder.events.clear();
        input.joystick(0, 0, 0, 40);
        input.joystick(5, 0, 0, 40);
        input.move(5, 50, -50);
        assert recorder.events.isEmpty();
        input.move(0, -20, 20);
        assert recorder.events.contains("k31:true") && recorder.events.contains("k30:true");
        input.release(5);
        assert input.heldCount() == 2;
        input.cancel();
        assert input.heldCount() == 0;

        input.button(4, 1, true);
        input.button(8, TouchInput.CTRL, false);
        input.look(12, 300, 20);
        assert input.heldCount() == 3;
        input.cancel();
        assert input.heldCount() == 0 && input.pointerCount() == 0;
        boolean rejected = false;
        try { input.move(0, Float.NaN, 0); } catch (IllegalArgumentException expected) { rejected = true; }
        assert rejected;
        System.out.println("TouchInputTest: concurrent IDs, movement, paint transitions, shared keys, ignored extra pointers, cancellation, validation passed.");
    }
}
