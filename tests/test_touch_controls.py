"""Execute the shipped touch movement, fading, and map-speed methods on the JVM."""
from pathlib import Path
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_game_apk import JAVA_HOME


def method(source, declaration):
    start = source.index(declaration)
    brace = source.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def memory_mask_points():
    from patch_scripts import dds_rgba, read_entry
    source = (ROOT / "android/app/src/org/thevoid/port/PalettePicker.java").read_text(encoding="utf-8")
    table = re.search(r"MEMORY_GRIP = (\{\{.*?\}\});", source, re.S)[1]
    grips = json.loads(table.replace("f", "").replace("{", "[").replace("}", "]"))
    for index in ("research/vfs-index.json", "research/vfs-index.german.json"):
        ui = ET.fromstring(read_entry(index, "Properties\\UI\\body.xml"))
        controls = []
        for control in ui.findall("Control"):
            if not control.attrib["name"].startswith("flimfa"):
                continue
            colour = int(control.attrib["name"][6:])
            props = control.attrib
            width, height = int(props["width"]), int(props["height"])
            x, y = 1024 - int(props["x"]) - width, int(props["y"])
            mw, mh, mask = dds_rgba(read_entry(index, f"Textures\\ui\\ui_flimfa_pal{colour}_mask.tex"))
            gw, gh, _ = dds_rgba(read_entry(index, f"Textures\\ui\\ui_flimfa_pal{colour}_grad.tex"))
            assert (mw, mh) == (gw, gh)
            point = round(grips[colour][0] * mw), round(grips[colour][1] * mh)
            assert 0 <= point[0] < width and 0 <= point[1] < height, (index, colour, point)
            controls.append((colour, x, y, width, height, mw, mask, point))
        assert len(controls) == 7
        for colour, x, y, _, _, _, _, point in controls:
            for other, ox, oy, width, height, mw, mask, _ in controls:
                lx, ly = x + point[0] - ox, y + point[1] - oy
                if not (0 <= lx < width and 0 <= ly < height):
                    continue
                at = (ly * mw + lx) * 4
                luminance = sum(mask[at:at + 3]) / 3
                assert luminance < 100 if other == colour else luminance >= 250, (index, colour, other, luminance)


def router_probe(source, out):
    """Run the layer's own finger routing: a full-screen layer an earlier
    finger holds must not take a later one (the old split did)."""
    route = method(source, "private boolean route(MotionEvent e)")
    target = method(source, "private View fingerTarget(float x, float y)")
    probe = out / "FingerRouterProbe.java"
    probe.write_text('''import java.util.*;
public class FingerRouterProbe {
    static final int VISIBLE = 0, GONE = 8;
    static class MotionEvent {
        static final int ACTION_DOWN = 0, ACTION_UP = 1, ACTION_MOVE = 2, ACTION_CANCEL = 3,
            ACTION_POINTER_DOWN = 5, ACTION_POINTER_UP = 6;
        final int action, index; final int[] ids; final float[] xs, ys;
        MotionEvent(int action, int index, int[] ids, float[] xs, float[] ys) {
            this.action = action; this.index = index; this.ids = ids; this.xs = xs; this.ys = ys;
        }
        int getActionMasked() { return action; } int getActionIndex() { return index; }
        int getPointerCount() { return ids.length; } int getPointerId(int i) { return ids[i]; }
        float getX(int i) { return xs[i]; } float getY(int i) { return ys[i]; }
        void recycle() { }
    }
    static class View {
        final String name; int visibility = VISIBLE, left, top, right, bottom;
        final List<String> got = new ArrayList<>();
        View(String name) { this.name = name; }
        View(String name, int l, int t, int r, int b) { this(name); left = l; top = t; right = r; bottom = b; }
        int getVisibility() { return visibility; } int getWidth() { return right - left; }
        int getLeft() { return left; } int getTop() { return top; } int getRight() { return right; } int getBottom() { return bottom; }
        void dispatchTouchEvent(MotionEvent part) { got.add(((Part) part).text); }
    }
    static class Part extends MotionEvent {
        final String text;
        Part(String text) { super(0, 0, new int[0], new float[0], new float[0]); this.text = text; }
    }
    static class Layer {
        final List<View> children = new ArrayList<>();
        int getChildCount() { return children.size(); } View getChildAt(int i) { return children.get(i); }
    }
    static class Picker extends View {
        boolean wantsAll; Picker(String name) { super(name); }
        boolean wants(float x, float y) { return wantsAll; }
    }
    static class Touch extends View {
        int uiFingers;
        Touch() { super("touch"); }
    }
    static class Fingers {
        final Map<Integer, View> map = new HashMap<>();
        void clear() { map.clear(); } void put(int id, View v) { map.put(id, v); }
        View get(int id) { return map.get(id); } void remove(int id) { map.remove(id); }
    }
    final Layer buttonLayer = new Layer();
    final View jump = new View("jump", 900, 400, 960, 460);
    final Touch touch = new Touch();
    final View gamepadHelp = new View("gamepad-help");
    final Picker picker = new Picker("picker"), memoryPicker = new Picker("memory");
    final Fingers fingers = new Fingers();
    FingerRouterProbe() { buttonLayer.children.add(jump); }
    /* The owner's own event: the actions as the owner sees them and its fingers. */
    MotionEvent fingersOf(MotionEvent e, View owner) {
        StringBuilder text = new StringBuilder();
        int n = 0, mine = -1;
        for (int i = 0; i < e.getPointerCount(); ++i) if (fingers.get(e.getPointerId(i)) == owner) {
            if (i == e.getActionIndex()) mine = n;
            text.append(n++ == 0 ? "" : ",").append(e.getPointerId(i));
        }
        int a = e.getActionMasked();
        String action = a == MotionEvent.ACTION_MOVE || a == MotionEvent.ACTION_CANCEL || mine < 0
            ? (a == MotionEvent.ACTION_CANCEL ? "cancel" : "move")
            : (a == MotionEvent.ACTION_DOWN || a == MotionEvent.ACTION_POINTER_DOWN) ? (n == 1 ? "down" : "pdown")
            : (n == 1 ? "up" : "pup");
        return new Part(action + ":" + text);
    }
''' + target + route + '''
    static MotionEvent ev(int action, int index, int[] ids, float[] xs, float[] ys) { return new MotionEvent(action, index, ids, xs, ys); }
    public static void main(String[] args) {
        FingerRouterProbe p = new FingerRouterProbe();
        // The stick (left), then the jump (held), then a look finger anywhere on the right.
        p.route(ev(0, 0, new int[] {1}, new float[] {100}, new float[] {300}));
        p.route(ev(5, 1, new int[] {1, 2}, new float[] {100, 930}, new float[] {300, 430}));
        p.route(ev(5, 2, new int[] {1, 2, 3}, new float[] {100, 930, 700}, new float[] {300, 430, 200}));
        assert p.touch.got.equals(Arrays.asList("down:1", "pdown:1,3")) : p.touch.got;
        assert p.jump.got.equals(Arrays.asList("down:2")) : p.jump.got;
        p.route(ev(2, 0, new int[] {1, 2, 3}, new float[] {110, 931, 650}, new float[] {280, 430, 210}));
        assert p.touch.got.get(2).equals("move:1,3") && p.jump.got.get(1).equals("move:2");
        // The jump lifts first: only its owner hears it; the look goes on.
        p.route(ev(6, 1, new int[] {1, 2, 3}, new float[] {110, 931, 650}, new float[] {280, 430, 210}));
        assert p.jump.got.get(2).equals("up:2") && p.touch.got.size() == 3;
        p.route(ev(2, 0, new int[] {1, 3}, new float[] {120, 600}, new float[] {280, 210}));
        assert p.touch.got.get(3).equals("move:1,3") && p.jump.got.size() == 3;
        // A new finger on the jump while two are on the picture is the jump's.
        p.route(ev(5, 2, new int[] {1, 3, 4}, new float[] {120, 600, 940}, new float[] {280, 210, 440}));
        assert p.jump.got.get(3).equals("down:4");
        p.route(ev(6, 0, new int[] {1, 3, 4}, new float[] {120, 600, 940}, new float[] {280, 210, 440}));
        assert p.touch.got.get(4).equals("pup:1,3");
        p.route(ev(3, 0, new int[] {3, 4}, new float[] {600, 940}, new float[] {210, 440}));
        assert p.touch.got.get(5).equals("cancel:3") && p.jump.got.get(4).equals("cancel:4");
        // A hidden button takes nothing; a picker's drop takes its finger only.
        p.jump.visibility = GONE; p.picker.wantsAll = true;
        p.route(ev(0, 0, new int[] {7}, new float[] {930}, new float[] {430}));
        assert p.picker.got.equals(Arrays.asList("down:7")) && p.jump.got.size() == 5;
        p.picker.wantsAll = false;
        p.route(ev(5, 1, new int[] {7, 8}, new float[] {930, 300}, new float[] {430, 300}));
        assert p.touch.got.get(6).equals("down:8") && p.picker.got.size() == 1;
        // A fourth finger on a button also invalidates a three-finger map tap.
        p.touch.uiFingers = 3;
        p.jump.visibility = VISIBLE;
        p.route(ev(5, 3, new int[] {7, 8, 9, 10}, new float[] {200, 300, 400, 930}, new float[] {300, 300, 300, 430}));
        assert p.touch.uiFingers == 4;
    }
}
''', encoding="utf-8")
    subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-d", str(out), str(probe)],
                   check=True, capture_output=True)
    subprocess.run([str(JAVA_HOME / "bin/java.exe"), "-ea", "-cp", str(out), "FingerRouterProbe"], check=True)


def main():
    source = (ROOT / "android/app/src/org/thevoid/port/Controls.java").read_text(encoding="utf-8")
    methods = "\n".join(method(source, declaration) for declaration in (
        "private void stick(float", "private void stickRelease()", "private void fadeControls(long",
        "private void fastTime(boolean", "private void bodySource(boolean", "private void releaseBodyTransfer()",
        "private void captureBodyTarget()", "private void resetBodyTransferColour()",
        "private void showBodyTransferLabel()", "private void beginPour()", "private void releasePour()",
        "private void stopPouring()"))
    latch = source[source.index("cursor |= screen == S_BODY"):]
    methods += "\nboolean bodyContext(boolean cursor) { " + latch[:latch.index(";") + 1] + " return cursor; }"
    brush = source[source.index("        int originalColour = GameActivity.nativeBrushColour();"):]
    methods += "\nint updateBrush() { long now = clock; " + brush[:brush.index("        if (bodyColours ||")] + " return selected; }"
    out = ROOT / "build/touch-controls-test"
    out.mkdir(parents=True, exist_ok=True)
    probe = out / "TouchControlsProbe.java"
    probe.write_text('''public class TouchControlsProbe {
    static class View {
        float alpha; boolean gesture, fan; int active = -1, label = -1, labelCalls, litHeart = -1;
        void setAlpha(float value) { alpha = value; } boolean bodyGesture() { return gesture; }
        boolean fanShown() { return fan; } int active() { return active; } int lit() { return litHeart; }
        void showLabel(int colour) { label = colour; ++labelCalls; }
    }
    static class PalettePicker { static final int COLOURS = 7; }
    static class GameActivity {
        static int colour = -1, target = -1, targetReads, transferColour = -1;
        static int nativeBrushColour() { return colour; }
        static int nativeBodyTarget() { ++targetReads; return target; }
        static int nativeBodyTransferColour() { int value = transferColour; transferColour = -1; return value; }
    }
    static class Input { static final int LEFT = 0, BODY_LYMPHA = 0x68, BODY_WIDGET = 0x69; }
    static class Sink {
        float x, y; int buttons, keys;
        void movement(float x, float y) { this.x = x; this.y = y; }
        void button(int code, boolean down) { assert code == Input.LEFT; buttons += down ? 1 : -1; assert buttons >= 0; }
        void key(int code, boolean down) {
            if (code == Input.BODY_WIDGET) return;
            assert code == Input.BODY_LYMPHA; keys += down ? 1 : -1; assert keys >= 0;
        }
    }
    final Sink in = new Sink();
    final View buttonLayer = new View(), systemColumn = new View(), actionColumn = new View(), timeRow = new View(),
        picker = new View(), memoryPicker = new View(), touch = new View();
    float stickCx = 200, stickCy = 200; int stickId = 1; boolean stickMoved;
    float stickRadius() { return 100; } float slop() { return 9; } void invalidate() { }
    void releaseHand() { }
    int fingersDown; boolean panel;
    long lastTouch, alphaTime; float overlayAlpha = 1;
    boolean panelVisible() { return panel; }
    boolean fastHeld, gameFastest; int gameFlow, lastKey;
    int pendingTimeRestore = -1; long hudFrame, timeRestoreFrame;
    boolean bodyLymphaHeld, bodyTransferHeld;
    boolean pouring, pourPressed, memoryPour;
    int pendingColour = -1, brushColour = -1, publishedColour = -2; long picked, heartClicked, clock = 10000;
    boolean paintMomentary, paletteSeen;
    int bodyTarget = -1, bodyTransferColour = -1;
    final int S_BODY=3, S_MAIN=7, S_PAUSE=5, HUD_MEMORY=0x1000, HUD_PALETTE=0x800; int screen=3, hud; boolean memorySeen;
    boolean shown(int mask, long millis) {
        if (mask == HUD_PALETTE) { assert millis == 300; return paletteSeen; }
        assert mask == HUD_MEMORY && millis == 350; return memorySeen;
    }
    final int timeMax = 4; int base = 11;
    void timeButtons() { }
    void timeKey(int key) { lastKey = key; }
    int baseTime() { return base; }
''' + methods + '''
    static void near(float actual, float expected) { assert Math.abs(actual - expected) < .0001f : actual; }
    public static void main(String[] args) {
        TouchControlsProbe p = new TouchControlsProbe();
        p.stick(205, 205); near(p.in.x, 0); near(p.in.y, 0);
        p.stick(200, 150); near(p.in.y, (.5f - .12f) / .88f); near(p.in.x, 0);
        p.stick(230, 160); near(p.in.x / p.in.y, .75f);
        assert p.in.x > 0 && p.in.y > 0 && Math.hypot(p.in.x, p.in.y) < .5;
        p.stick(500, -200); near((float)Math.hypot(p.in.x, p.in.y), 1);
        near(p.stickCx, 200); near(p.stickCy, 200);
        p.stick(100, 200); near(p.in.x, -1); near(p.in.y, 0);
        p.stickRelease(); near(p.in.x, 0); near(p.in.y, 0); assert p.stickId == -1;

        p.fadeControls(20000); near(p.touch.alpha, 1);
        p.fadeControls(22500); near(p.touch.alpha, .5f);
        p.fadeControls(25000); near(p.touch.alpha, 0); near(p.picker.alpha, 0);
        p.lastTouch = 25000;
        p.fadeControls(25250); near(p.touch.alpha, .5f);
        p.fadeControls(25500); near(p.touch.alpha, 1); near(p.memoryPicker.alpha, 1);
        p.fingersDown = 1; p.fadeControls(60000); near(p.touch.alpha, 1); assert p.lastTouch == 60000;
        p.fingersDown = 0; p.panel = true; p.fadeControls(90000); near(p.touch.alpha, 1);

        p.fastTime(true); assert p.fastHeld && p.lastKey == p.timeMax;
        p.fastTime(false); assert !p.fastHeld && p.lastKey == 11;
        p.fastTime(true); p.fastTime(false); assert p.lastKey == 11;
        p.base = 2; p.fastTime(true); p.fastTime(false); assert p.lastKey == 2;
        p.bodySource(false); assert p.in.keys == 0;
        p.bodySource(true); p.bodySource(true); assert p.in.keys == 1;
        p.bodyTransferHeld = true; p.in.buttons = 1;
        p.releaseBodyTransfer(); assert p.in.buttons == 0 && p.in.keys == 0 && !p.bodyTransferHeld;
        p.releaseBodyTransfer(); assert p.in.buttons == 0 && p.in.keys == 0;
        p.hud = p.HUD_MEMORY; assert p.bodyContext(false);
        p.hud = 0; p.touch.gesture = true; assert p.bodyContext(false);
        p.touch.gesture = false; assert !p.bodyContext(false);
        p.memorySeen = true; p.screen = 0; assert !p.bodyContext(false);
        GameActivity.colour = 5; assert p.updateBrush() == 5;
        GameActivity.colour = -1; assert p.updateBrush() == 5;
        p.pendingColour = 2; GameActivity.colour = 5; assert p.updateBrush() == 2;
        p.pendingColour = -1; p.picked = 1000; assert p.updateBrush() == 2;
        p.picked = 0; p.paintMomentary = true; assert p.updateBrush() == 2;
        p.paintMomentary = false; p.picker.fan = true; assert p.updateBrush() == 2;
        p.picker.fan = false; GameActivity.colour = 2; assert p.updateBrush() == 2;
        GameActivity.colour = 6; assert p.updateBrush() == 6;
        GameActivity.colour = 7; assert p.updateBrush() == 6;
        /* A colour chosen where no hero publishes (the map): the old published value does not take it back. */
        GameActivity.colour = 6; p.pendingColour = 1; assert p.updateBrush() == 1;
        p.pendingColour = -1; assert p.updateBrush() == 1 && p.updateBrush() == 1;
        GameActivity.colour = 4; assert p.updateBrush() == 4;
        /* The heart the palette lights wins once the click has settled. */
        p.paletteSeen = true; p.picker.litHeart = 3; p.heartClicked = p.clock - 100; assert p.updateBrush() == 4;
        p.heartClicked = p.clock - 500; assert p.updateBrush() == 3;
        p.paintMomentary = true; p.picker.litHeart = 5; assert p.updateBrush() == 3;
        p.paintMomentary = false; p.paletteSeen = false; p.picker.litHeart = -1;
        p = new TouchControlsProbe(); GameActivity.colour = -1; p.picker.active = 3;
        assert p.updateBrush() == 3;
        GameActivity.target = 8; p.captureBodyTarget(); assert p.bodyTarget == 8;
        int reads = GameActivity.targetReads;
        GameActivity.target = -1; p.captureBodyTarget();
        assert p.bodyTarget == 8 && GameActivity.targetReads == reads;
        p.bodyTarget = -1; p.captureBodyTarget(); assert p.bodyTarget == -1;
        GameActivity.target = 10; p.captureBodyTarget(); assert p.bodyTarget == 10;
        GameActivity.transferColour = 5; p.resetBodyTransferColour();
        assert p.bodyTransferColour == -1 && GameActivity.transferColour == -1;
        p.bodyTransferHeld = p.bodyLymphaHeld = true;
        p.showBodyTransferLabel(); assert p.picker.label == -1;
        GameActivity.transferColour = 2; p.showBodyTransferLabel();
        assert p.picker.label == 2 && p.bodyTransferColour == 2 && GameActivity.transferColour == -1;
        int labels = p.picker.labelCalls;
        p.showBodyTransferLabel(); assert p.picker.labelCalls == labels + 1 && p.picker.label == 2;
        GameActivity.transferColour = 7; p.showBodyTransferLabel(); assert p.picker.label == 2;
        p.in.buttons = p.in.keys = 1; labels = p.picker.labelCalls;
        p.releaseBodyTransfer(); assert p.picker.labelCalls == labels + 1;
        assert !p.bodyTransferHeld && !p.bodyLymphaHeld && p.in.buttons == 0 && p.in.keys == 0;
        GameActivity.transferColour = 4; p.showBodyTransferLabel();
        assert GameActivity.transferColour == 4 && p.picker.label == 2;
        p.resetBodyTransferColour(); assert p.bodyTransferColour == -1 && GameActivity.transferColour == -1;
        p.pouring = p.memoryPour = true;
        GameActivity.transferColour = 6; p.showBodyTransferLabel();
        assert p.memoryPicker.label == 6 && p.picker.label == 2 && p.bodyTransferColour == 6;
        labels = p.memoryPicker.labelCalls; p.stopPouring();
        assert !p.pouring && !p.memoryPour && p.memoryPicker.labelCalls == labels + 1;
        GameActivity.transferColour = 3; p.showBodyTransferLabel();
        assert p.memoryPicker.label == 6 && GameActivity.transferColour == 3;
        p = new TouchControlsProbe(); p.memoryPour = true; p.beginPour();
        assert p.pouring && p.pourPressed && p.in.buttons == 1;
        for (int i = 0; i < 100; ++i) p.beginPour();
        assert p.in.buttons == 1;
        GameActivity.transferColour = 4; p.showBodyTransferLabel(); assert p.memoryPicker.label == 4;
        p.stopPouring(); assert !p.pouring && !p.pourPressed && !p.memoryPour && p.in.buttons == 0;
        p.stopPouring(); assert p.in.buttons == 0;
    }
}
''')
    subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-d", str(out), str(probe)],
                   check=True, capture_output=True)
    subprocess.run([str(JAVA_HOME / "bin/java.exe"), "-ea", "-cp", str(out), "TouchControlsProbe"], check=True)
    time_methods = "\n".join(method(source, declaration) for declaration in (
        "private void timeKey(int", "private void fastTime(boolean", "private void restoreMapTime(int",
        "private void setSlowTime(boolean", "private int baseTime()", "private void timeFromWheel(int"))
    wheel = source[source.index("    private static final float WHEEL_X"):]
    time_methods += "\n" + wheel[:wheel.index(";") + 1]
    time_probe = out / "TimeRestoreProbe.java"
    time_probe.write_text('''public class TimeRestoreProbe {
    static class SystemClock { static long now = 1000; static long uptimeMillis() { return now; } }
    static class android { static class util { static class Log { static void i(String tag, String text) { } } } }
    static class PalettePicker { static final int FLOATS = 72; }
    static class Button { boolean held; boolean held() { return held; } }
    static class Sink { int lastKey, sent; void tapKey(int key) { lastKey = key; ++sent; } }
    final Sink in = new Sink(); final Button fastB = new Button();
    final int S_MAP = 2, S_SCENE = 1, SLOT_WHEEL = 15;
    final int HUD_CONTROL_LOCKED = 0x2000000, HUD_VIDEO = 0x800000, HUD_LOADING = 0x20000;
    int screen = S_MAP, hud, pendingTimeRestore = -1, gameFlow = -1;
    int timeMin = 2, timeDefault = 11, timeAvg = 3, timeMax = 4;
    int renderW = 1000, renderH = 600;
    float[] slotValues = new float[19 * 72];
    long hudFrame = 10, timeRestoreFrame, timeSent;
    boolean fastHeld, gameFastest, slowTime, avgTime;
    void timeButtons() { }
''' + time_methods + '''
    public static void main(String[] args) {
        final int wheel = 1 << 15;
        TimeRestoreProbe p = new TimeRestoreProbe();
        p.fastTime(true); assert p.in.lastKey == p.timeMax && p.fastHeld;
        SystemClock.now = 1100; p.fastTime(false);
        assert p.in.lastKey == p.timeDefault && p.pendingTimeRestore == p.timeDefault && !p.fastHeld;
        p.hudFrame++;
        p.restoreMapTime(wheel, 1279); assert p.in.sent == 2;
        SystemClock.now = 1280; p.restoreMapTime(wheel, SystemClock.now);
        assert p.in.sent == 3 && p.in.lastKey == p.timeDefault && p.pendingTimeRestore == -1;
        for (int i = 0; i < 20; ++i) p.restoreMapTime(wheel, 2000 + i);
        assert p.in.sent == 3;

        p = new TimeRestoreProbe(); p.slowTime = true; SystemClock.now = 3000;
        p.fastTime(true); p.screen = p.S_SCENE; p.hud = p.HUD_CONTROL_LOCKED;
        SystemClock.now = 3100; p.fastTime(false);
        assert p.pendingTimeRestore == p.timeMin && p.in.lastKey == p.timeMin;
        // A visible old 120x wheel must not overwrite the saved slow flow.
        int at = 15 * 72 + 64;
        double angle = Math.toRadians(198.8);
        p.slotValues[at] = p.slotValues[at + 2] = (74.7f + 39.4f * (float)Math.cos(angle)) / p.renderW;
        p.slotValues[at + 1] = p.slotValues[at + 3] = (p.renderH - 71.75f + 39.4f * (float)Math.sin(angle)) / p.renderH;
        p.timeFromWheel(wheel, 10000);
        assert p.slowTime && !p.gameFastest && p.baseTime() == p.timeMin;
        p.hudFrame++;
        for (int i = 0; i < 20; ++i) p.restoreMapTime(wheel, 10000 + i);
        assert p.in.sent == 2 && p.pendingTimeRestore == p.timeMin;
        p.screen = p.S_MAP;
        for (int blocked : new int[] {p.HUD_VIDEO, p.HUD_LOADING}) {
            p.hud = p.HUD_CONTROL_LOCKED | blocked;
            p.restoreMapTime(wheel, 10000); assert p.in.sent == 2;
        }
        // The map locks the original 3D player while its wheel still accepts time keys.
        p.hud = p.HUD_CONTROL_LOCKED; p.restoreMapTime(0, 10000); assert p.in.sent == 2;
        p.hudFrame = p.timeRestoreFrame; p.restoreMapTime(wheel, 10000); assert p.in.sent == 2;
        p.hudFrame++; p.fastTime(true); int sent = p.in.sent;
        p.restoreMapTime(wheel, 10000); assert p.in.sent == sent;
        SystemClock.now = 10100; p.fastTime(false); p.hudFrame++;
        SystemClock.now = 10300; p.restoreMapTime(wheel, SystemClock.now);
        assert p.in.lastKey == p.timeMin && p.pendingTimeRestore == -1;
        sent = p.in.sent; p.restoreMapTime(wheel, 20000); assert p.in.sent == sent;

        // A deliberate new flow selection supersedes an outstanding restore.
        p = new TimeRestoreProbe(); p.slowTime = true;
        p.fastTime(true); p.fastTime(false); p.setSlowTime(false);
        assert p.pendingTimeRestore == p.timeDefault;
        p.hudFrame++; SystemClock.now += 200; p.restoreMapTime(wheel, SystemClock.now);
        assert p.in.lastKey == p.timeDefault && p.pendingTimeRestore == -1;
        // The release-specific action keys remain intact when slow/default swap.
        p = new TimeRestoreProbe(); p.timeMin = 11; p.timeDefault = 2; p.slowTime = true;
        p.fastTime(true); p.fastTime(false); p.hudFrame++;
        SystemClock.now += 200; p.restoreMapTime(wheel, SystemClock.now);
        assert p.in.lastKey == 11 && p.pendingTimeRestore == -1;
    }
}
''')
    subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-d", str(out), str(time_probe)],
                   check=True, capture_output=True)
    subprocess.run([str(JAVA_HOME / "bin/java.exe"), "-ea", "-cp", str(out), "TimeRestoreProbe"], check=True)
    palette = (ROOT / "android/app/src/org/thevoid/port/PalettePicker.java").read_text(encoding="utf-8")
    palette_methods = "\n".join(method(palette, declaration) for declaration in (
        "boolean has(int", "int nextValid(int", "int fanAt(float", "private void layoutDots()",
        "void setAmounts(float", "void showLabel(int", "boolean inZone(float", "void setReadability(float", "private void drawLabel(Canvas",
        "private void selectAt(float", "void setActive(int", "boolean wants(float", "void setInsets(int",
        "private void column(float", "void setObstacles(java.util.List"))
    palette_methods += "\n" + method(palette, "@Override public boolean onTouchEvent(MotionEvent e)").replace("@Override ", "")
    palette_probe = out / "PaletteProbe.java"
    palette_probe.write_text('''public class PaletteProbe {
    static class android {
        static class os { static class SystemClock {
            static long now = 1000; static long uptimeMillis() { return now; }
        } }
        static class graphics { static class RectF {
            final float left, top, right, bottom;
            RectF(float l, float t, float r, float b) { left = l; top = t; right = r; bottom = b; }
            @Override public boolean equals(Object o) {
                if (!(o instanceof RectF)) return false;
                RectF r = (RectF)o; return left == r.left && top == r.top && right == r.right && bottom == r.bottom;
            }
            @Override public int hashCode() { return (int)(left + top * 31 + right * 961 + bottom * 29791); }
        } }
    }
    static java.util.List<android.graphics.RectF> none() { return java.util.Collections.emptyList(); }
    static java.util.List<android.graphics.RectF> hole(float l, float t, float r, float b) {
        return java.util.Collections.singletonList(new android.graphics.RectF(l, t, r, b));
    }
    static class MotionEvent {
        static final int ACTION_DOWN = 0, ACTION_UP = 1, ACTION_MOVE = 2, ACTION_CANCEL = 3;
        int action; float x, y;
        MotionEvent(int value) { action = value; }
        MotionEvent(int value, float x, float y) { action = value; this.x = x; this.y = y; }
        int getActionMasked() { return action; }
        float getX() { return x; } float getY() { return y; }
    }
    static class IconButton { static class Haptics { void tick() { } } static Haptics haptics; }
    static class Color { static int argb(int a, int r, int g, int b) { return a << 24; } }
    static class Settings { static final int T_COLOUR_FIRST = 0; static String gameText(int key) { return "Colour name"; } }
    static class Rect { int width; int width() { return width; } }
    static class Paint {
        static class Style { static final int FILL = 0; } static class Align { static final int LEFT = 0; }
        float size;
        void setStyle(int style) { } void setColor(int color) { } void setTextAlign(int align) { }
        void setTextSize(float size) { this.size = size; }
        float measureText(String text) { return size * text.length() / 2; }
        void getTextBounds(String text, int start, int end, Rect bounds) { bounds.width = Math.round(measureText(text)); }
    }
    static class Canvas {
        int backplates, texts; float firstSize, secondSize;
        void drawRoundRect(float l, float t, float r, float b, float rx, float ry, Paint paint) {
            ++backplates; assert l >= 0 && t >= 0 && r <= 1000 && b <= 600;
        }
        void drawRect(float l, float t, float r, float b, Paint paint) { }
        void drawText(String text, float x, float y, Paint paint) {
            if (texts++ == 0) firstSize = paint.size; else secondSize = paint.size;
            assert x >= 0 && y >= 0 && x < 1000 && y < 600;
        }
    }
    interface HoldChooser { void press(int colour, boolean down); default void moved(int colour, float x, float y) { } }
    interface Chooser { void choose(int colour); }
    int choices, chosen = -1;
    HoldChooser holdChooser; Chooser chooser = colour -> { ++choices; chosen = colour; };
    int heldColour = -1; float heldX, heldY;
    boolean stripHeld; int stripColour = -1, active = -1;
    final int COLOURS = 7, FIRST_SLOT = 1;
    int firstSlot = 1;
    float[] fill = new float[7], current = new float[7], maximum = new float[7], dotX = new float[7], dotY = new float[7];
    boolean[] dotShown = new boolean[7];
    boolean[] amountKnown = new boolean[7];
    boolean labelPinned;
    boolean body, fan, strip = true, rightSide = true, customAnchor, amountLabels;
    float dotRadius, buttonSize = 56, anchorX = 900, anchorY = 300;
    int insetLeft, insetRight;
    final java.util.List<android.graphics.RectF> holes = new java.util.ArrayList<>();
    final java.util.List<android.graphics.RectF> obstacles = new java.util.ArrayList<>();
    float textScale = 1; boolean textContrast = true;
    final Paint paint = new Paint(); final Rect textBounds = new Rect(); final int[] rgb = new int[7];
    int highlighted = -1, label = -1; long labelUntil;
    final Runnable labelExpiry = this::invalidate; Runnable pendingExpiry;
    int expiryCallbacks;
    float dp(float v) { return v; }
    int getHeight() { return 600; } int getWidth() { return 1000; }
    void invalidate() { }
    void removeCallbacks(Runnable callback) {
        assert callback == labelExpiry;
        if (pendingExpiry != null) { pendingExpiry = null; --expiryCallbacks; }
    }
    void postDelayed(Runnable callback, long delay) {
        assert callback == labelExpiry && delay == 1850;
        pendingExpiry = callback; ++expiryCallbacks;
    }
''' + palette_methods + '''
    public static void main(String[] args) {
        PaletteProbe p = new PaletteProbe();
        p.layoutDots();
        for (int i = 0; i < 7; ++i) { assert p.dotShown[i]; assert p.dotY[i] > 0 && p.dotY[i] < 600; }
        assert p.inZone(p.dotX[0], p.dotY[0]) && !p.inZone(500, 300);
        // Beside the brush on its side, never on the button itself.
        assert p.dotX[0] < p.anchorX - p.buttonSize / 2 - p.dotRadius && p.dotX[0] > 500;
        assert p.wants(p.dotX[3], p.dotY[3]) && !p.wants(500, 300);
        p.anchorX = 990; p.setInsets(0, 80, none());
        assert p.dotX[0] <= 1000 - 80 - p.dotRadius * 1.3f - 4 : "clear of the camera at the right";
        p.setInsets(0, 0, none()); p.anchorX = 900; p.layoutDots();
        p.customAnchor = true; p.anchorX = 500; p.anchorY = 30; p.layoutDots();
        assert p.inZone(p.dotX[0], p.dotY[0]) && !p.inZone(990, 300);
        p.fan = true; p.layoutDots();
        for (int i = 0; i < 7; ++i) assert p.dotY[i] >= p.dotRadius && p.dotY[i] <= 600 - p.dotRadius;
        p.customAnchor = p.fan = false; p.anchorX = 900; p.anchorY = 300; p.layoutDots();
        assert p.nextValid(-1, 1) == -1;
        p.fill[2] = .25f; p.fill[5] = .8f;
        p.onTouchEvent(new MotionEvent(MotionEvent.ACTION_DOWN, p.dotX[2], p.dotY[2]));
        assert p.stripHeld && p.chosen == 2 && p.active == 2 && p.choices == 1;
        p.onTouchEvent(new MotionEvent(MotionEvent.ACTION_MOVE, p.dotX[5], p.dotY[5]));
        assert p.chosen == 5 && p.active == 5 && p.choices == 2;
        p.onTouchEvent(new MotionEvent(MotionEvent.ACTION_MOVE, p.dotX[5], p.dotY[5]));
        assert p.choices == 2;
        p.onTouchEvent(new MotionEvent(MotionEvent.ACTION_MOVE, p.dotX[1], p.dotY[1]));
        assert p.choices == 2 && p.active == 5;
        p.onTouchEvent(new MotionEvent(MotionEvent.ACTION_UP)); assert !p.stripHeld;
        assert p.nextValid(-1, 1) == 2 && p.nextValid(2, 1) == 5 && p.nextValid(5, 1) == 2;
        assert p.nextValid(2, -1) == 5;
        p.strip = false; p.fan = true; p.layoutDots();
        assert p.fanAt(p.dotX[2], p.dotY[2]) == 2 && p.label == 2;
        p.labelUntil = 0; p.fanAt(p.dotX[2], p.dotY[2]); assert p.labelUntil == 2800;
        p.fan = false; p.body = true; p.layoutDots(); assert p.dotX[0] == 34;
        p.firstSlot = 8; p.layoutDots(); assert p.dotX[0] == 966;
        // The body's columns keep their place by the edge; where the camera's hole
        // crosses one, its drops part round it, alike apart, all on the screen.
        p.setInsets(50, 90, none()); assert p.dotX[0] == 1000 - 34;
        p.firstSlot = 1; p.layoutDots(); assert p.dotX[0] == 34;
        assert p.dotY[0]==49:"left colours use the upper free space";
        float apart = p.dotY[1] - p.dotY[0];
        for (int i = 1; i < 7; ++i) assert Math.abs(p.dotY[i] - p.dotY[i - 1] - apart) < .01f;
        p.setInsets(50, 0, hole(0, 260, 50, 330));
        for (int i = 0; i < 7; ++i) {
            assert p.dotShown[i] && p.dotX[i] == 34;
            assert p.dotY[i] + p.dotRadius <= 260 || p.dotY[i] - p.dotRadius >= 330 : "clear of the camera: " + p.dotY[i];
            assert p.dotY[i] - p.dotRadius >= 0 && p.dotY[i] + p.dotRadius <= 600;
            if (i > 0) assert p.dotY[i] > p.dotY[i - 1];
        }
        int above = 0;
        for (int i = 0; i < 7; ++i) if (p.dotY[i] < 260) ++above;
        assert above >= 2 && above <= 6 : "upper column parts around the camera: " + above;
        // A hole at the other edge leaves this column as it was.
        p.setInsets(0, 50, hole(950, 260, 1000, 330));
        for (int i = 1; i < 7; ++i) assert Math.abs(p.dotY[i] - p.dotY[i - 1] - apart) < .01f;
        // The body's menu button over the left column (no camera there): the drops start below it,
        // alike apart; the right column and painting's strip ignore it.
        p.setInsets(0, 0, none()); p.firstSlot = 1; p.body = true;
        p.setObstacles(hole(2, 10, 56, 64));
        assert p.dotY[0] - p.dotRadius >= 64 : "below the menu: " + p.dotY[0];
        for (int i = 1; i < 7; ++i) assert p.dotY[i] > p.dotY[i - 1] && p.dotY[i] + p.dotRadius <= 600;
        p.firstSlot = 8; p.layoutDots(); float memoryTop = p.dotY[0]; p.setObstacles(none()); assert p.dotY[0] == memoryTop : "the Memory column keeps its place"; p.setObstacles(hole(2, 10, 56, 64));
        p.setObstacles(none()); p.firstSlot = 1; p.layoutDots(); assert p.dotY[0] == 49;
        p.setInsets(0, 0, none()); p.firstSlot = 8; p.layoutDots();
        float[] amounts = new float[28]; amounts[14] = 4.5f; amounts[15] = 20;
        p.fill[0] = .9f;
        p.setAmounts(amounts, 14); assert p.current[0] == 4.5f && p.maximum[0] == 20;
        assert Math.abs(p.fill[0] - .225f) < .00001f;
        amounts[14] = Float.NaN; p.setAmounts(amounts, 14); assert p.current[0] == 4.5f;
        assert Math.abs(p.fill[0] - .225f) < .00001f;
        amounts[14] = -1; p.setAmounts(amounts, 14); assert p.current[0] == 4.5f;
        amounts[15] = -1; p.setAmounts(amounts, 14); assert Math.abs(p.fill[0] - .225f) < .00001f;
        amounts[15] = 20;
        amounts[14] = 25; p.setAmounts(amounts, 14); assert p.fill[0] == 1;
        amounts[14] = amounts[15] = 0; p.setAmounts(amounts, 14);
        assert p.current[0] == 0 && p.maximum[0] == 0 && p.fill[0] == 0 && p.amountKnown[0];
        android.os.SystemClock.now = 9000;
        for (int i = 0; i < 300; ++i) { ++android.os.SystemClock.now; p.showLabel(2); }
        assert p.label == 2 && p.labelUntil == 11100 && p.expiryCallbacks == 1;
        p.heldColour = 2; android.os.SystemClock.now = 15000;
        p.holdChooser = (colour, down) -> { assert colour == 2 && !down; };
        p.onTouchEvent(new MotionEvent(MotionEvent.ACTION_UP));
        assert p.heldColour == -1 && p.label == 2 && p.labelUntil == 11100 && p.expiryCallbacks == 1;
        p.body = false; p.showLabel(2); p.anchorX = 20; p.anchorY = 10;
        p.setReadability(1.5f, true); Canvas canvas = new Canvas(); p.drawLabel(canvas);
        assert canvas.backplates == 1 && canvas.texts == 2 && canvas.firstSize == 25.5f && canvas.secondSize == 18;
        p.setReadability(1, false); canvas = new Canvas(); p.drawLabel(canvas);
        assert canvas.backplates == 0 && canvas.firstSize == 17 && canvas.secondSize == 12;
    }
}
''')
    subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-d", str(out), str(palette_probe)],
                   check=True, capture_output=True)
    subprocess.run([str(JAVA_HOME / "bin/java.exe"), "-ea", "-cp", str(out), "PaletteProbe"], check=True)
    queue = source[source.index("        if (picked > 0 && now - picked > 180)"):]
    queue = queue[:queue.index("        float[] at =")]
    queue_probe = out / "ColourQueueProbe.java"
    queue_probe.write_text('''public class ColourQueueProbe {
    static class Input { static final int CTRL = 29; }
    static class Sink { boolean held = true; void key(int code, boolean down) { assert code == Input.CTRL; held = down; } }
    final Sink in = new Sink(); boolean paintMode = true;
    long picked = 1000, raised; int pendingColour = 3, sent;
    void dispatch(long now) {
''' + queue + '''
        ++sent;
    }
    public static void main(String[] args) {
        ColourQueueProbe p = new ColourQueueProbe();
        p.dispatch(1100); assert p.sent == 0 && p.in.held;
        // The click's stroke is cancelled while it is down: the brush stays up, Ctrl is never let go.
        p.pendingColour = 5; p.dispatch(1181);
        assert p.sent == 0 && p.picked == 0 && p.in.held;
        p.dispatch(1182); assert p.sent == 1 && p.pendingColour == 5 && p.in.held;
        p.pendingColour = -1; p.dispatch(1500); assert p.sent == 1;
        p.pendingColour = 2; p.picked = 1500; p.paintMode = false;
        p.dispatch(1681); assert p.sent == 1 && p.picked == 0 && p.in.held;
        p.raised = 1600; p.dispatch(1700); assert p.sent == 1;
        p.dispatch(1780); assert p.sent == 2;
    }
}
''')
    subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-d", str(out), str(queue_probe)],
                   check=True, capture_output=True)
    subprocess.run([str(JAVA_HOME / "bin/java.exe"), "-ea", "-cp", str(out), "ColourQueueProbe"], check=True)
    transition = source[source.index("            if (s == S_VIDEO || s == S_INTRO) touch.cancel();"):]
    transition = transition[:transition.index(";") + 1]
    video_probe = out / "VideoProbe.java"
    video_probe.write_text('''public class VideoProbe {
    static class MotionEvent {
        static final int ACTION_DOWN = 0, ACTION_UP = 1, ACTION_CANCEL = 3;
        int action; MotionEvent(int value) { action = value; } int getActionMasked() { return action; }
    }
    final int WORLD = 0, UI = 1, S_WORLD = 0, S_BODY = 3, S_INTRO = 13, S_VIDEO = 14, HUD_VIDEO = 0x800000, HUD_JOURNAL_VIDEO = 0x40000000;
    static class Input { static final int ESC=1; }
    static class Sink { int skips; void tapKey(int key) { assert key==Input.ESC; ++skips; } }
    final Sink in=new Sink(); boolean journalVideo;
    final VideoProbe touch = this;
    int screen = S_WORLD, mode = WORLD, cancellations, buttonUpdates, dispatched;
    boolean videoContact, videoSkipVisible, skippingLines, using, video = true;
    float movement;
    boolean panelVisible() { return false; }
    boolean shown(int tag, long duration) { assert duration == 500; return tag==HUD_JOURNAL_VIDEO ? journalVideo : video; }
    void updateButtons() { ++buttonUpdates; }
    void world(MotionEvent event) { ++dispatched; } void ui(MotionEvent event) { ++dispatched; }
    void paint(MotionEvent event) { ++dispatched; }
    void cancel() { videoContact = skippingLines = using = false; movement = 0; ++cancellations; }
    void transition(int s) { screen = s;
''' + transition + '''
    }
''' + method(source, "@Override public boolean onTouchEvent(MotionEvent e)").replace("@Override ", "") + '''
    public static void main(String[] args) {
        VideoProbe p = new VideoProbe(); p.skippingLines = p.using = true; p.movement = 1;
        p.transition(p.S_VIDEO);
        assert p.cancellations == 1 && !p.skippingLines && !p.using && p.movement == 0;
        // The old world's release neither sticks nor reveals the video's skip button.
        p.onTouchEvent(new MotionEvent(MotionEvent.ACTION_UP));
        assert !p.videoSkipVisible && p.buttonUpdates == 0 && p.dispatched == 0;
        p.onTouchEvent(new MotionEvent(MotionEvent.ACTION_DOWN));
        p.onTouchEvent(new MotionEvent(MotionEvent.ACTION_UP));
        assert p.videoSkipVisible && p.buttonUpdates == 1;
        p.onTouchEvent(new MotionEvent(MotionEvent.ACTION_DOWN));
        p.onTouchEvent(new MotionEvent(MotionEvent.ACTION_CANCEL));
        p.onTouchEvent(new MotionEvent(MotionEvent.ACTION_UP));
        assert p.videoSkipVisible && p.buttonUpdates == 1;
        p.transition(p.S_INTRO); assert p.cancellations == 2;
        p.onTouchEvent(new MotionEvent(MotionEvent.ACTION_DOWN));
        p.onTouchEvent(new MotionEvent(MotionEvent.ACTION_UP));
        assert !p.videoSkipVisible && p.buttonUpdates == 2;
        p.journalVideo=true;p.transition(p.S_VIDEO);
        p.onTouchEvent(new MotionEvent(MotionEvent.ACTION_DOWN));p.onTouchEvent(new MotionEvent(MotionEvent.ACTION_UP));
        assert p.in.skips==1&&!p.videoSkipVisible&&p.buttonUpdates==2;
        p.transition(p.S_WORLD); assert p.cancellations == 3;
        p.onTouchEvent(new MotionEvent(MotionEvent.ACTION_DOWN)); assert p.dispatched == 1;
    }
}
''')
    subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-d", str(out), str(video_probe)],
                   check=True, capture_output=True)
    subprocess.run([str(JAVA_HOME / "bin/java.exe"), "-ea", "-cp", str(out), "VideoProbe"], check=True)
    cancellation = out / "CancelProbe.java"
    cancellation.write_text('''class MotionEvent {
    static final int ACTION_DOWN=0, ACTION_UP=1, ACTION_MOVE=2, ACTION_CANCEL=3,
        ACTION_POINTER_DOWN=5, ACTION_POINTER_UP=6;
    int action; long time; float x;
    MotionEvent(int action, long time, float x) { this.action=action; this.time=time; this.x=x; }
    int getActionMasked() { return action; } int getActionIndex() { return 1; }
    int getPointerId(int i) { return i == 0 ? 4 : 8; } int findPointerIndex(int id) { return id == 8 ? 1 : 0; }
    int getPointerCount() { return 2; } long getEventTime() { return time; }
    float getX(int i) { return i == 0 ? 100 : x; } float getY(int i) { return 200; }
}
class Parent { public boolean dispatchTouchEvent(MotionEvent e) { return true; } }
public class CancelProbe extends Parent {
    int screen = -1; static final int S_BODY = 3;
    static class android { static class util { static class Log { static void i(String t,String v) { } } } }
    static class SystemClock { static long uptimeMillis() { return 1000; } }
    static class GameActivity { static int cancelled; static void nativeCancelStroke() { ++cancelled; } }
    final Activity activity = new Activity(); static class Activity { void applyPortSettings() { } }
    static class Input { static final int LEFT=0; }
    static class Sink {
        int refs=1; void button(int key, boolean down) { refs += down ? 1 : -1; assert refs >= 0; }
        int clicks; void cursorTo(float x, float y) { } void click(int code) { ++clicks; }
    }
    static class Haptics { void tick() { } }
    final Sink in = new Sink(); final Haptics haptics = new Haptics();
    final Touch touch = new Touch();
    static class HardwareInput {
        static boolean mouseEvent(MotionEvent event) { return false; }
        boolean mouse(MotionEvent event) { return false; } void touch() { }
    }
    final HardwareInput hardware = new HardwareInput();
    Object layoutEditor;
    int holdingFor = -1; boolean holdTouch;
    static class Settings { boolean touchAdaptations = true; }
    final Settings settings = new Settings();
    final int HUD_BACK = 0x8000000, SLOT_BACK = 19; int hud;
    int getWidth() { return 1000; } int getHeight() { return 600; }
    boolean backHit; boolean inSlot(int slot, float x, float y, float margin) { assert slot == SLOT_BACK; return backHit; }
    void setPaintMode(boolean on) { paintMode = on; }
    class Touch { boolean stroking() { return strokeId >= 0; } void cancelStroke() { CancelProbe.this.cancelStroke(); } void cancel() { } }
    boolean paintMode = true, padActive, revealing, strokeShort;
    int cancelFinger=-1, fingersDown, strokeId=4;
    float cancelX,cancelY; long lastTouch,cancelTime,heartClicked;
    Runnable strokePress;
    float dp(float value) { return value; } boolean panelVisible() { return false; }
    void updateButtons() { } void removeCallbacks(Runnable r) { }
    static class Fingers { void clear() { } } final Fingers fingers = new Fingers();
    int routed; boolean route(MotionEvent e) { ++routed; return true; }
''' + method(source, "@Override public boolean dispatchTouchEvent(MotionEvent event)") + "\n"
        + method(source, "private void cancelStroke()") + '''
    public static void main(String[] args) {
        CancelProbe p = new CancelProbe(); p.strokePress = () -> { throw new AssertionError(); };
        p.dispatchTouchEvent(new MotionEvent(5, 1000, 600));
        p.dispatchTouchEvent(new MotionEvent(6, 1200, 600));
        assert GameActivity.cancelled == 1 && p.paintMode && p.strokeId == -1 && p.strokeShort;
        assert p.in.refs == 0 && p.strokePress == null && p.routed == 0 : "the cancelling finger is the layer's";
        p = new CancelProbe();
        p.dispatchTouchEvent(new MotionEvent(5, 2000, 600));
        p.dispatchTouchEvent(new MotionEvent(2, 2050, 630));
        p.dispatchTouchEvent(new MotionEvent(6, 2100, 630));
        assert GameActivity.cancelled == 1 && p.strokeId == 4;
        p = new CancelProbe(); p.hud = p.HUD_BACK; p.backHit = true;
        p.dispatchTouchEvent(new MotionEvent(0, 5000, 900));
        assert !p.paintMode && p.in.clicks == 1;
        p = new CancelProbe(); p.hud = p.HUD_BACK; p.backHit = true; p.settings.touchAdaptations = false;
        p.dispatchTouchEvent(new MotionEvent(0, 5000, 900));
        assert p.paintMode && p.in.clicks == 0;
        p.dispatchTouchEvent(new MotionEvent(5, 3000, 600));
        p.dispatchTouchEvent(new MotionEvent(6, 3400, 600));
        assert GameActivity.cancelled == 1 && p.strokeId == 4;
        p.layoutEditor = new Object();
        p.dispatchTouchEvent(new MotionEvent(5, 4000, 600));
        p.dispatchTouchEvent(new MotionEvent(6, 4100, 600));
        assert GameActivity.cancelled == 1 && p.strokeId == 4;
    }
}
''')
    subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-d", str(out), str(cancellation)],
                   check=True, capture_output=True)
    subprocess.run([str(JAVA_HOME / "bin/java.exe"), "-ea", "-cp", str(out), "CancelProbe"], check=True)
    router_probe(source, out)
    memory_mask_points()
    print("PASS: fingers' owners (stick, look and jump at once), radial axes, fade, interrupted map-speed restore, source labels, palettes/amounts, second-finger cancel, exclusive Memory masks in both releases")


if __name__ == "__main__":
    main()
