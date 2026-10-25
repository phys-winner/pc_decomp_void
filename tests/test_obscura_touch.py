"""Exercise shipped dialogue polls, the held-heart gate, and guest input ABI."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from gscript_binary import Module
from patch_scripts import PATCHES, read_entry, patch_health_hold, patch_dialogue_key
from build_shader_cache import hash64, shaders
from build_x86_incremental import compiler_environment
from build_game_apk import JAVA_HOME


def brush_transition():
    source = (ROOT / "android/app/src/org/thevoid/port/Controls.java").read_text(encoding="utf-8")
    block = source[source.index("        boolean gameBrush ="):source.index("        int m = paintMode")]
    constants = "\n".join(re.search(r"private static final int " + name + r" =.*?;", source, re.S).group()
                          for name in ("HUD_CURSOR", "MENU_IMAGES"))
    raise_brush = re.search(r"private final Runnable raiseBrush =.*?; \};", source).group()
    set_paint = re.search(r"private void setPaintMode\(.*?\n    \}", source, re.S).group()
    out = ROOT / "build/tree-sister/brush-transition-test"
    out.mkdir(parents=True, exist_ok=True)
    probe = out / "BrushTransitionProbe.java"
    probe.write_text('''public class BrushTransitionProbe {
    static class android { static class util { static class Log {
        static void i(String tag, String text) { }
    } } }
    static class Picker { void pinLabel(boolean on) {} }
    final Picker picker = new Picker();
    static class Input { static final int CTRL = 0x1d; }
    static class SystemClock { static long uptimeMillis() { return 5000; } }
    static class Sink {
        int refs = 1, presses;
        void key(int key, boolean down) {
            assert key == Input.CTRL;
            refs = Math.max(0, refs + (down ? 1 : -1)); if (down) ++presses;
            assert refs >= 0 && refs <= 1;
        }
    }
    static class Touch {
        boolean shortStroke, drawing;
        boolean stroking() { return drawing; }
        boolean lastStrokeShort() { return shortStroke; }
        void cancel() { }
    }
    static class Button { void setToggled(boolean on) { } }
    final Sink in = new Sink(); final Touch touch = new Touch();
    final Button paintB = new Button();
    final java.util.List<Runnable> callbacks = new java.util.ArrayList<>();
    int hud, raises, pendingColour = -1; boolean paintMode = true, paintMomentary; long picked;
    long now = 5000, paintSince = 1000, raised, heartClicked, strokeEnded = 3000, cursorSeen = 5000, paletteSeen;
    boolean shown(int mask, long ms) { return (hud & mask) != 0; }
    void postDelayed(Runnable callback, long delay) { callbacks.add(callback); }
    void removeCallbacks(Runnable callback) { callbacks.removeIf(r -> r == callback); }
    void flush() {
        for (Runnable r : new java.util.ArrayList<>(callbacks)) { callbacks.remove(r); r.run(); }
    }
    void frame() { tick(); flush(); }
''' + constants + "\n" + raise_brush + "\n" + set_paint + "\n    void tick() {\n" + block + '''
    }
    public static void main(String[] args) {
        BrushTransitionProbe p = new BrushTransitionProbe();
        p.hud = HUD_CURSOR; p.frame();   // Tree camera changed after a full glyph.
        assert p.paintMode && p.in.presses == 1 && p.in.refs == 1 && p.raises == 1;
        p.hud |= HUD_PALETTE; p.frame();
        assert p.raises == 0 && p.in.presses == 1;
        p = new BrushTransitionProbe(); p.hud = HUD_CURSOR_LYMPHA; p.frame();
        assert p.in.presses == 1;       // A coloured cursor without its palette is not ready either.
        p = new BrushTransitionProbe(); p.strokeEnded = 0; p.frame();
        assert p.in.presses == 1;       // Recover an initial press the game did not accept.
        p = new BrushTransitionProbe(); p.hud = HUD_CURSOR | HUD_OBSCURA; p.frame();
        assert p.in.presses == 1;       // The sister's drawing view has the same transition.
        for (int menu : new int[] {HUD_PAUSE, HUD_MAINMENU, HUD_MAP, HUD_MEMORY, HUD_JOURNAL}) {
            p = new BrushTransitionProbe(); p.hud = HUD_CURSOR | menu; p.frame();
            assert p.in.presses == 0;
            p.strokeEnded = 0; p.now += 1000; p.frame();
            assert p.in.presses == 0;   // Initial retries must also respect menus.
        }
        p = new BrushTransitionProbe(); p.cursorSeen = 4000; p.frame();
        assert !p.paintMode && p.in.presses == 0; // Back in the world, put the brush away.
        p = new BrushTransitionProbe(); p.hud = HUD_CURSOR; p.touch.drawing = true; p.frame();
        assert p.in.presses == 0;       // Never interrupt a stroke.
        p = new BrushTransitionProbe(); p.hud = HUD_CURSOR; p.raises = 2; p.frame();
        assert p.in.presses == 0;       // A rejected brush cannot cause a key loop.
        p = new BrushTransitionProbe(); p.hud = HUD_CURSOR; p.tick();
        assert p.in.refs == 0 && p.callbacks.size() == 1;
        p.setPaintMode(false); p.setPaintMode(true); p.flush();
        assert p.in.refs == 1 && p.in.presses == 1 && p.callbacks.isEmpty();
        p.setPaintMode(false); assert p.in.refs == 0; // No old callback may hold Ctrl across a toggle.
    }
}
''')
    subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-d", str(out), str(probe)],
                   check=True, capture_output=True)
    subprocess.run([str(JAVA_HOME / "bin/java.exe"), "-ea", "-cp", str(out), "BrushTransitionProbe"], check=True)


def hover_input():
    source = (ROOT / "android/app/src/org/thevoid/port/Controls.java").read_text(encoding="utf-8")
    methods = [re.search(pattern + r".*?\n        \}", source, re.S).group()
               for pattern in (r"private boolean onHeartProgress\(",
                               r"private void heartProgress\(",
                               r"@Override public boolean onHoverEvent\(")]
    out = ROOT / "build/tree-sister/hover-input-test"
    out.mkdir(parents=True, exist_ok=True)
    probe = out / "HeartProgressProbe.java"
    probe.write_text('''class MotionEvent {
    static final int ACTION_HOVER_EXIT = 10;
    int action; float x, y;
    MotionEvent(int a, float x, float y) { action = a; this.x = x; this.y = y; }
    int getActionMasked() { return action; }
    float getX() { return x; } float getY() { return y; }
}
class Parent { public boolean onHoverEvent(MotionEvent e) { return false; } }
public class HeartProgressProbe extends Parent {
    static class Input { static final int HEART_PROGRESS = 0x64; }
    static class Sink {
        int refs, presses, warps;
        void cursorTo(float x, float y) { assert x == 0 && y == 0; ++warps; }
        void key(int key, boolean down) {
            assert key == Input.HEART_PROGRESS;
            refs += down ? 1 : -1; if (down) ++presses;
            assert refs >= 0 && refs <= 1;
        }
    }
    final Sink in = new Sink();
    static final int S_OBSCURA = 9;
    int screen = S_OBSCURA; boolean heartProgressHeld;
    int getHeight() { return 1080; }
''' + "\n".join(methods) + '''
    public static void main(String[] args) {
        HeartProgressProbe p = new HeartProgressProbe();
        assert p.onHoverEvent(new MotionEvent(9, 50, 1000));
        assert p.in.refs == 1 && p.in.warps == 1;
        p.onHoverEvent(new MotionEvent(7, 380, 650));
        assert p.in.refs == 1 && p.in.presses == 1;
        p.onHoverEvent(new MotionEvent(7, 800, 650));
        assert p.in.refs == 0;
        p.onHoverEvent(new MotionEvent(7, 300, 900));
        p.onHoverEvent(new MotionEvent(10, 300, 900));
        assert p.in.refs == 0;
        p.heartProgress(true); p.heartProgress(false); p.heartProgress(false);
        assert p.in.refs == 0;
        assert p.onHeartProgress(432, 594) && !p.onHeartProgress(433, 594);
        assert !p.onHeartProgress(300, 593);
        p.screen = 0;
        assert !p.onHoverEvent(new MotionEvent(9, 50, 1000)) && p.in.refs == 0;
    }
}
''')
    subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-d", str(out), str(probe)],
                   check=True, capture_output=True)
    subprocess.run([str(JAVA_HOME / "bin/java.exe"), "-ea", "-cp", str(out), "HeartProgressProbe"], check=True)


def dialogue_key(index):
    direct = named = count = 0
    for name, patch in PATCHES:
        module = Module(read_entry(index, name))
        original = list(module.instructions())
        has_dialogue_poll = any(x.get('symbol') == 'isKeyPressed' and
            ((original[i + 1].get('opcode') == 1 and original[i + 1]['operands'] == [0x39]) or
             (original[i + 1].get('symbol') == 'getKeyCode' and original[i + 2].get('text') == 'space'))
            for i, x in enumerate(original[:-2]))
        if not has_dialogue_poll:
            continue
        count += 1
        patch_dialogue_key(module, "ru")
        patched = list(Module(module.encode()).instructions())
        assert len(original) == len(patched)
        for i, row in enumerate(original):
            if row.get("symbol") != "isKeyPressed":
                continue
            old, new = original[i + 1], patched[i + 1]
            if old.get("opcode") == 1 and old["operands"] == [0x39]:
                assert new["operands"] == [0x1c]
                direct += 1
            elif old.get("symbol") == "getKeyCode":
                old, new = original[i + 2], patched[i + 2]
                if old.get("opcode") != 3:
                    continue   # The dance polls the action's configured handlers.
                assert new["text"] == ("return" if old["text"] == "space" else old["text"])
                named += old["text"] == "space"
    assert (direct, named, count) == (46, 44, 24), (direct, named, count)


def control_lock():
    import pefile
    pe = pefile.PE(str(ROOT / "generated/input/GameModule.dll"))
    # ControlsLocked's registered getter, including its original property slot.
    assert pe.get_data(0x101bf450 - pe.OPTIONAL_HEADER.ImageBase, 15).hex() == "8b018b501cffd283c040e9c117e8ff"
    source = (ROOT / "android/host/hud.c").read_text(encoding="utf-8")
    body = re.search(r"void sub_101BF450\(void\).*?\n\}", source, re.S).group()
    out = ROOT / "build/tree-sister/control-lock-test"
    out.mkdir(parents=True, exist_ok=True)
    probe = out / "probe.c"
    mapping = re.search(r"uint32_t void_vk_to_dik\(.*?\n\}",
                        (ROOT / "android/host/input.c").read_text(), re.S).group()
    probe.write_text('''#include <assert.h>
#include <stdint.h>
#define atomic_store(p, v) (*(p) = (v))
#define atomic_fetch_add_explicit(p, v, order) (*(p) += (v))
static uint32_t g_eax, g_ecx, g_esp, flags, result, lock_reads;
static void void_touch_observe_context(uint32_t context) { (void)context; }
static int controls_locked;
static void sub_101BF450_lifted(void) {
    g_eax = result; g_esp += 4; flags = 0x246;
}
''' + body + mapping + '''
int main(void) {
    assert(void_vk_to_dik(0x7c) == 0x64);
    assert(void_vk_to_dik(0x0d) == 0x1c && void_vk_to_dik(0x20) == 0x39);
    uint32_t values[] = {0, 1, 0xabcdef00, 0xabcdef01, 0x123400ff};
    for (int i = 0; i < 5; ++i) {
        result = values[i]; g_esp = 0x1000; flags = 0;
        sub_101BF450();
        assert(g_eax == result && g_esp == 0x1004 && flags == 0x246);
        assert(controls_locked == ((result & 255) != 0));
        /* Each read is counted: a scene whose getter nobody calls is known by none. */
        assert(lock_reads == (uint32_t)i + 1);
    }
    return 0;
}
''')
    compiler, env, _ = compiler_environment()
    subprocess.run([str(compiler), "/nologo", "/O2", "/std:c11", str(probe),
                    "/Fe" + str(out / "probe.exe"), "/Fo" + str(out / "probe.obj")],
                   env=env, check=True, capture_output=True)
    subprocess.run([str(out / "probe.exe")], check=True)


def tooltip(module, info, hovered, held):
    rows = {r["offset"]: r for r in module.instructions()}
    pc = int(info["sites"][0], 16)
    regs = {0: hovered}
    for _ in range(80):
        if pc == info["inside"]:
            return True
        if pc == info["outside"]:
            return False
        row = rows[pc]
        op, r, args = row["opcode"], row["register"], row["operands"]
        pc += row["size"]
        if op == 1:
            regs[r] = args[0]
        elif op == 57:
            assert regs[r + 1] == "isKeyPressed" and regs[r + 2] == 0x64
            regs[r] = held
        elif op == 54:
            pc = args[0]
        elif op in (55, 56):
            if bool(regs[r]) == (op == 56):
                pc = args[0]
        elif op == 71:
            regs[r] = module.ascii(args[0])
        elif op == 74:
            regs.pop(r, None)
        else:
            raise AssertionError((hex(row["offset"]), op))
    raise AssertionError("tooltip gate did not finish")


def main():
    brush_transition()
    hover_input()
    for index in ("research/vfs-index.json", "research/vfs-index.german.json"):
        dialogue_key(index)
        module = Module(read_entry(index, "Scripts\\ui\\health_progress.bin"))
        info = patch_health_hold(module, "ru")
        module = Module(module.encode())
        for hovered in (False, True):
            for held in (False, True):
                assert tooltip(module, info, hovered, held) == (hovered or held)


    control_lock()
    variants = list(shaders())
    tagged = {hash64((ROOT / "build/shadercache/results" / (key + ".bin")).read_bytes())
              for name, key, _ in variants if name.startswith("static/CompositeObscure")}
    for name, key, _ in variants:
        fingerprint = hash64((ROOT / "build/shadercache/results" / (key + ".bin")).read_bytes())
        if fingerprint in tagged:
            # HeroExit shares this effect, but has no UI cursor (Controls.screen).
            assert name.startswith(("static/CompositeObscure", "static/CompositeHeroExit")), name
    print("PASS: 180 dialogue polls, held-heart/mouse gate in both releases, getter ABI, compositor scope")


if __name__ == "__main__":
    main()
