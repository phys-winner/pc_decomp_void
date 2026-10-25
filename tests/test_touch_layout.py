"""Run saved-layout validation, the shipped button/gesture geometry and the layout editor's touch on the JVM."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_game_apk import JAVA_HOME
from test_touch_controls import method


def main():
    out = ROOT / "build/touch-layout-test"
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / "android/app/src/org/thevoid/port/Controls.java").read_text(encoding="utf-8")
    methods = "\n".join(method(source, declaration) for declaration in (
        "private void applyButtonLayout()", "private boolean onStickSide(float", "private boolean onLookZone(float"))
    probe = out / "TouchLayoutBoundsProbe.java"
    probe.write_text('''package org.thevoid.port;
public class TouchLayoutBoundsProbe {
    static final int VISIBLE = 0, GONE = 8;
    static class android {
        static class os { static class Build { static class VERSION { static final int SDK_INT = 36; } } }
        static class graphics {
            static class Rect { Rect(int l, int t, int r, int b) { assert r > l && b > t; } }
        }
    }
    static class Gravity { static final int TOP = 1, LEFT = 2; }
    static class LayoutParams {
        int width, height, leftMargin, topMargin;
        LayoutParams(int w, int h, int gravity) { width = w; height = h; }
    }
    static class View {
        int x, y, width = 54;
        View(int x, int y) { this.x = x; this.y = y; }
        int getWidth() { return width; }
        void getLocationOnScreen(int[] p) { p[0] = x; p[1] = y; }
    }
    static class IconButton {
        int visibility, updates;
        LayoutParams params = new LayoutParams(0, 0, 0);
        LayoutParams getLayoutParams() { return params; }
        void setLayoutParams(LayoutParams p) { params = p; ++updates; }
        void setOpacity(float value) { }
        int getVisibility() { return visibility; }
    }
    static class Layer {
        int exclusions;
        void setSystemGestureExclusionRects(java.util.List<android.graphics.Rect> rects) { exclusions = rects.size(); }
    }
    static class Prefs {
        String saved; int saves;
        Prefs edit() { return this; } Prefs putString(String key, String value) { assert key.equals("layout"); saved = value; return this; }
        void apply() { ++saves; }
    }
    static class Settings { boolean leftHanded; float buttonScale = 1, buttonOpacity = .6f, textSize = 1; }
    static class RectF { final float l, t, r, b; RectF(float l, float t, float r, float b) { this.l = l; this.t = t; this.r = r; this.b = b; } }
    static class Picker { java.util.List<RectF> obstacles = new java.util.ArrayList<>();
        void setObstacles(java.util.List<RectF> rects) { obstacles = new java.util.ArrayList<>(rects); } }
    final Picker picker = new Picker();
    final java.util.List<RectF> bodyButtons = new java.util.ArrayList<>();
    final Settings settings = new Settings();
    final View[] buttonAnchors = {new View(25, 110), new View(25, 174)};
    final IconButton[] layoutButtons = {new IconButton(), new IconButton()};
    final IconButton menuB = layoutButtons[0], journalB = layoutButtons[1];
    final IconButton bodyBackB = new IconButton();
    final int S_BODY = 3; int screen;
    final Layer buttonLayer = new Layer();
    final Prefs layoutPrefs = new Prefs();
    TouchLayout touchLayout = new TouchLayout();
    boolean insetsKnown = true;
    int insetLeft = 10, insetRight = 20, width = 1000, height = 600, anchorUpdates;
    int dp(float value) { return Math.round(value); }
    int getWidth() { return width; } int getHeight() { return height; }
    void getLocationOnScreen(int[] at) { at[0] = 15; at[1] = 10; }
    void anchorPicker() { ++anchorUpdates; }
''' + methods + '''
    public static void main(String[] args) {
        TouchLayoutBoundsProbe p = new TouchLayoutBoundsProbe();
        p.applyButtonLayout();
        LayoutParams first = p.layoutButtons[0].params;
        assert first.width == 54 && first.height == 54 && first.leftMargin == 10 && first.topMargin == 100;
        assert p.buttonLayer.exclusions == 2 && p.anchorUpdates == 1;
        p.applyButtonLayout(); assert p.layoutButtons[0].updates == 1;
        assert p.picker.obstacles.isEmpty() : "no obstacles outside the body";
        // The body's menu stays where it is on every screen; the book beside it; the palette's
        // drops keep clear of both.
        p.screen = p.S_BODY; p.applyButtonLayout();
        assert p.menuB.params.topMargin == first.topMargin && p.menuB.params.leftMargin == first.leftMargin;
        assert p.picker.obstacles.size() == 2 && p.picker.obstacles.get(0).t == first.topMargin;
        assert p.journalB.params.leftMargin == p.menuB.params.leftMargin + first.width + 10;
        assert p.journalB.params.topMargin == p.menuB.params.topMargin;
        p.screen = 0;
        // Fractions of the whole view: the camera's strip counts too.
        p.touchLayout.put("menu", .75f, .6f, .1f, .15f);
        p.applyButtonLayout(); first = p.layoutButtons[0].params;
        assert first.width == 90 && first.height == 90;
        assert first.leftMargin == 705 && first.topMargin == 315;
        p.screen=p.S_BODY;p.applyButtonLayout();
        assert p.menuB.params.topMargin==315:"keep the user's custom position";
        p.screen=0;
        // A different display size keeps the normalized centre and square hit box.
        p.width = 1600; p.height = 900; p.applyButtonLayout(); first = p.layoutButtons[0].params;
        assert first.width == 135 && first.height == 135;
        assert first.leftMargin == 1133 && first.topMargin == 473;
        // A button may sit beside the camera: no inset keeps it out of the cutout's strip.
        p.touchLayout.put("menu", 0, 0, .025f, .025f);
        p.applyButtonLayout(); first = p.layoutButtons[0].params;
        assert first.leftMargin < p.insetLeft && first.topMargin < 3 && first.width >= 36 : first.leftMargin;
        p.touchLayout.put("menu", 1, 1, .025f, .025f);
        p.applyButtonLayout(); first = p.layoutButtons[0].params;
        assert p.width - (first.leftMargin + first.width) < p.insetRight && p.height - (first.topMargin + first.height) < 3;
        p.layoutButtons[1].visibility = GONE; p.applyButtonLayout(); assert p.buttonLayer.exclusions == 1;
        // An old layout (the cutout-clear frame) moves into the whole view once, when the cutout is known.
        p = new TouchLayoutBoundsProbe();
        p.touchLayout = new TouchLayout("menu,0.5,0.5,0.054,0.09;");
        p.insetsKnown = false; p.applyButtonLayout();
        assert p.touchLayout.legacy && p.layoutPrefs.saves == 0;
        p.insetsKnown = true; p.applyButtonLayout();
        assert !p.touchLayout.legacy && p.layoutPrefs.saves == 1 && p.layoutPrefs.saved.startsWith("v2;");
        first = p.layoutButtons[0].params;
        assert Math.abs(first.leftMargin + first.width / 2f - (10 + .5f * 970)) <= 1 : first.leftMargin;
        p.applyButtonLayout(); assert p.layoutPrefs.saves == 1;

        p = new TouchLayoutBoundsProbe();
        assert p.onStickSide(100, 300) && !p.onStickSide(500, 300);
        assert p.onLookZone(900, 100);
        p.settings.leftHanded = true; assert p.onStickSide(900, 300) && !p.onStickSide(100, 300);
        p.touchLayout.put(TouchLayout.MOVE, .2f, .8f, .3f, .3f);
        p.touchLayout.put(TouchLayout.LOOK, .8f, .5f, .4f, .6f);
        assert p.onStickSide(200, 480) && !p.onStickSide(200, 60) && p.onStickSide(55, 480);
        assert p.onLookZone(800, 300) && !p.onLookZone(200, 480);
    }
}
''', encoding="utf-8")
    editor = (ROOT / "android/app/src/org/thevoid/port/TouchLayoutEditor.java").read_text(encoding="utf-8")
    touch = method(editor, "@Override public boolean onTouchEvent(MotionEvent event)").replace("@Override ", "")
    parts = "\n".join(method(editor, d) for d in (
        "private RectF box(int index)", "private float diameter(TouchLayout.Rect r)", "private int hit(float x, float y)",
        "private void put(int index"))
    contexts = re.search(r"    private static final int\[\]\[\] CONTEXTS = .*?;\n", editor, re.S).group()
    editor_probe = out / "TouchLayoutDragProbe.java"
    editor_probe.write_text('''package org.thevoid.port;
import java.util.*;
public class TouchLayoutDragProbe {
    static class MotionEvent {
        static final int ACTION_DOWN = 0, ACTION_UP = 1, ACTION_MOVE = 2, ACTION_CANCEL = 3,
            ACTION_POINTER_DOWN = 5, ACTION_POINTER_UP = 6;
        final int action, index; final int[] ids; final float[] xs, ys;
        MotionEvent(int action, int index, int[] ids, float[] xs, float[] ys) {
            this.action = action; this.index = index; this.ids = ids; this.xs = xs; this.ys = ys;
        }
        int getActionMasked() { return action; } int getActionIndex() { return index; }
        int getPointerId(int i) { return ids[i]; }
        int findPointerIndex(int id) { for (int i = 0; i < ids.length; ++i) if (ids[i] == id) return i; return -1; }
        float getX() { return xs[0]; } float getY() { return ys[0]; }
        float getX(int i) { return xs[i]; } float getY(int i) { return ys[i]; }
    }
    static class RectF {
        float left, top, right, bottom;
        RectF(float l, float t, float r, float b) { left = l; top = t; right = r; bottom = b; }
        boolean contains(float x, float y) { return x >= left && x < right && y >= top && y < bottom; }
        void inset(float dx, float dy) { left += dx; right -= dx; top += dy; bottom -= dy; }
        float centerX() { return (left + right) / 2; } float centerY() { return (top + bottom) / 2; }
        float width() { return right - left; }
    }
    static class Animation {
        float alpha; Animation alpha(float a) { alpha = a; return this; } Animation setDuration(long ms) { return this; } void start() { }
    }
    static class Tools { final Animation animation = new Animation(); Animation animate() { return animation; } }
    static final int MOVE = TouchLayout.BUTTONS.length, LOOK = MOVE + 1;
    static final float MIN_DP = 36, MAX_DP = 128;
''' + contexts + '''
    final String[] ids = new String[TouchLayout.BUTTONS.length + 2];
    TouchLayout working = TouchLayout.zones(false);
    final Tools tools = new Tools();
    int context, selected = -1, pointer = -1, second = -1, sizeUpdates, placements;
    float grabX, grabY, pinchSpanX, pinchSpanY, pinchWidth, pinchHeight;
    boolean moving, resetLayout = true;
    TouchLayoutDragProbe() {
        System.arraycopy(TouchLayout.BUTTONS, 0, ids, 0, TouchLayout.BUTTONS.length);
        ids[MOVE] = TouchLayout.MOVE; ids[LOOK] = TouchLayout.LOOK;
    }
    static boolean zone(int index) { return index >= MOVE; }
    int dp(float value) { return Math.round(value); }
    int getWidth() { return 1000; } int getHeight() { return 600; }
    void invalidate() { } void updateSizes() { ++sizeUpdates; } void placeTools() { ++placements; }
''' + parts + touch + '''
    static MotionEvent ev(int action, int index, int[] ids, float[] xs, float[] ys) { return new MotionEvent(action, index, ids, xs, ys); }
    static void near(float value, float expected) { assert Math.abs(value - expected) < .002f : value + " vs " + expected; }
    public static void main(String[] args) {
        TouchLayoutDragProbe p = new TouchLayoutDragProbe();
        p.working.put("jump", .9f, .5f, .06f, .1f);   /* 60 px across at the right */
        // Taken off centre: the button keeps that hold while it follows the finger.
        p.onTouchEvent(ev(0, 0, new int[] {7}, new float[] {910}, new float[] {310}));
        assert p.selected == 4 && p.moving && p.tools.animation.alpha < 1 && !p.resetLayout || p.selected == 4;
        p.onTouchEvent(ev(2, 0, new int[] {7}, new float[] {510}, new float[] {110}));
        near(p.working.get("jump").x, .5f); near(p.working.get("jump").y, 1f / 6);
        assert !p.resetLayout;
        // Into the camera's strip at the left: only the screen's edge stops it.
        p.onTouchEvent(ev(2, 0, new int[] {7}, new float[] {-200}, new float[] {110}));
        near(p.working.get("jump").x, p.working.get("jump").width / 2);
        // A second finger sizes it; the first lifting leaves the second moving it.
        p.onTouchEvent(ev(5, 1, new int[] {7, 8}, new float[] {40, 140}, new float[] {110, 110}));
        p.onTouchEvent(ev(2, 0, new int[] {7, 8}, new float[] {40, 240}, new float[] {110, 110}));
        float d = Math.min(p.working.get("jump").width * 1000, p.working.get("jump").height * 600);
        assert d > 100 && d <= 128.5f : d;
        p.onTouchEvent(ev(2, 0, new int[] {7, 8}, new float[] {40, 41}, new float[] {110, 110}));
        d = Math.min(p.working.get("jump").width * 1000, p.working.get("jump").height * 600);
        assert d >= 35.5f && d < 60 : d;
        p.onTouchEvent(ev(6, 0, new int[] {7, 8}, new float[] {40, 41}, new float[] {110, 110}));
        assert p.pointer == 8 && p.second == -1;
        float x = p.working.get("jump").x;
        p.onTouchEvent(ev(2, 0, new int[] {8}, new float[] {141}, new float[] {110}));
        near(p.working.get("jump").x, x + .1f);
        p.onTouchEvent(ev(1, 0, new int[] {8}, new float[] {141}, new float[] {110}));
        assert p.pointer == -1 && !p.moving && p.tools.animation.alpha == 1 && p.placements == 1;
        // A zone is taken where no button is, and two fingers stretch it each way on its own.
        p.onTouchEvent(ev(0, 0, new int[] {1}, new float[] {150}, new float[] {500}));
        assert p.selected == MOVE;
        p.onTouchEvent(ev(5, 1, new int[] {1, 2}, new float[] {150, 250}, new float[] {500, 400}));
        p.onTouchEvent(ev(2, 0, new int[] {1, 2}, new float[] {150, 350}, new float[] {500, 400}));
        near(p.working.get(TouchLayout.MOVE).width, .8f); near(p.working.get(TouchLayout.MOVE).height, 1f);
        p.onTouchEvent(ev(3, 0, new int[] {1, 2}, new float[] {150, 350}, new float[] {500, 400}));
        // Another context: the chamber's jump is not there to take.
        p.context = 2; p.selected = -1;
        RectF jump = p.box(4);
        p.onTouchEvent(ev(0, 0, new int[] {3}, new float[] {jump.centerX()}, new float[] {jump.centerY()}));
        assert p.selected == -1 || p.selected == 5;
        p.onTouchEvent(ev(1, 0, new int[] {3}, new float[] {jump.centerX()}, new float[] {jump.centerY()}));
    }
}
''', encoding="utf-8")
    subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(out),
                    str(ROOT / "android/app/src/org/thevoid/port/TouchLayout.java"),
                    str(ROOT / "tests/TouchLayoutTest.java"), str(probe), str(editor_probe)], check=True)
    for name in ("TouchLayoutTest", "TouchLayoutBoundsProbe", "TouchLayoutDragProbe"):
        subprocess.run([str(JAVA_HOME / "bin/java.exe"), "-ea", "-cp", str(out), "org.thevoid.port." + name], check=True)
    print("PASS: layout persistence, cancel isolation, corruption rejection, whole-view buttons beside the camera, "
          "old layouts moved once, editor drag/pinch/handover, zones stretched, contexts apart, movement/look zones")


if __name__ == "__main__":
    main()
