package org.thevoid.port;

public final class TouchLayoutTest {
    private static void near(float value, float expected) { assert Math.abs(value - expected) < .00001f : value; }
    public static void main(String[] args) {
        TouchLayout layout = TouchLayout.zones(false);
        assert layout.get(TouchLayout.MOVE).contains(.1f, .9f);
        assert !layout.get(TouchLayout.MOVE).contains(.7f, .5f);
        assert layout.get(TouchLayout.LOOK).contains(.7f, .5f);
        assert TouchLayout.zones(true).get(TouchLayout.MOVE).contains(.9f, .9f);
        assert TouchLayout.zones(true).get(TouchLayout.LOOK).contains(.1f, .5f);
        layout.put("jump", .9f, .8f, .06f, .1f);
        TouchLayout restored = new TouchLayout(layout.encode());
        near(restored.get("jump").x, .9f);
        near(restored.get("jump").height, .1f);
        assert restored.encode().equals(layout.encode());
        assert layout.encode().startsWith("v2;") && !restored.legacy : "saved in the whole view's fractions";

        // The editor's working copy cannot change the saved layout on Cancel.
        TouchLayout working = layout.copy();
        working.put("jump", .3f, .4f, .1f, .2f);
        near(layout.get("jump").x, .9f);
        working = TouchLayout.zones(true);
        working.overlay(layout);
        near(working.get("jump").x, .9f);
        assert working.get(TouchLayout.MOVE).contains(.1f, .9f);

        restored = new TouchLayout("jump,NaN,.5,.1,.1;use,.5,Infinity,.1,.1;map,.5,.5,0,.1;"
            + "unknown,.5,.5,.1,.1;menu,bad,.5,.1,.1;paint,4,-3,9,2;body,.2,.3,.1,.1;settings,.5,.5,.1,.1;");
        assert restored.get("jump") == null && restored.get("use") == null;
        assert restored.get("map") == null && restored.get("menu") == null;
        assert restored.get("unknown") == null && restored.get("settings") == null : "the gear is gone";
        near(restored.get("paint").width, 1);
        near(restored.get("paint").height, 1);
        near(restored.get("paint").x, .5f);
        near(restored.get("paint").y, .5f);
        near(restored.get("body").x, .2f);
        assert new TouchLayout((String) null).encode().isEmpty();
        assert new TouchLayout("").isEmpty() && !new TouchLayout("").legacy;
        boolean rejected = false;
        try { layout.put("jump", Float.NaN, .5f, .1f, .1f); }
        catch (IllegalArgumentException expected) { rejected = true; }
        assert rejected;

        // A layout saved before (no mark) measured across the part clear of the camera: moved into the
        // whole view it keeps every place on the screen.
        TouchLayout old = new TouchLayout("menu,0.1,0.2,0.05,0.1;movement,0.2,0.5,0.4,1.0;");
        assert old.legacy;
        int left = 100, right = 40, total = 2000;
        TouchLayout moved = old.fromSafeArea(left, right, total);
        assert !moved.legacy;
        near(moved.get("menu").x * total, left + .1f * (total - left - right));
        near(moved.get("menu").width * total, .05f * (total - left - right));
        near(moved.get("menu").y, .2f);
        near(moved.get("movement").x * total, left + .2f * (total - left - right));
        assert new TouchLayout(moved.encode()).encode().equals(moved.encode());
        TouchLayout same = old.fromSafeArea(0, 0, total);
        near(same.get("menu").x, .1f);
        System.out.println("PASS: whole-view layouts, the old gear dropped, corrupt rows rejected, cutout-clear layouts moved once");
    }
}
