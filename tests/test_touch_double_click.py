"""Direct body widgets must retain every press; Windows lists keep double-clicks."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_x86_incremental import compiler_environment
from build_game_apk import JAVA_HOME
from test_touch_controls import method


def main():
    out = ROOT / "build/touch-fixes/input-test"
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / "android/host/user32.c").read_text()
    probe = out / "double_click.c"
    probe.write_text('''#include <assert.h>
#include <stdint.h>
#include <time.h>
#define VLOG(...) ((void)0)
#define CLOCK_MONOTONIC 1
typedef struct { unsigned style; } class_t;
typedef struct { class_t *cls; } window_t;
static long milliseconds = 1000;
static int widget;
static int fake_clock(int clock, struct timespec *out) {
    out->tv_sec = milliseconds / 1000;
    out->tv_nsec = (milliseconds % 1000) * 1000000;
    return 0;
}
#define clock_gettime fake_clock
static int16_t void_input_key_state(uint32_t key) { assert(key == 0x81); return widget ? (int16_t)0x8000 : 0; }
static int double_clicks = 1;
#define atomic_load(p) (*(p))
''' + method(source, "static uint32_t dblclk_translate(") + '''
int main(void) {
    class_t cls = {8}; window_t window = {&cls};
    assert(dblclk_translate(&window, 0x201, 0x100010) == 0x201);
    milliseconds += 40;
    assert(dblclk_translate(&window, 0x201, 0x100010) == 0x203);
    widget = 1;
    for (int i = 0; i < 10; ++i) {
        milliseconds += 40;
        assert(dblclk_translate(&window, 0x201, 0x100010) == 0x201);
        assert(dblclk_translate(&window, 0x202, 0x100010) == 0x202);
    }
    widget = 0;
    milliseconds += 40;
    assert(dblclk_translate(&window, 0x201, 0x100010) == 0x201);
    milliseconds += 40;
    assert(dblclk_translate(&window, 0x201, 0x100010) == 0x203);
    /* The options' pages and the journal: every quick tap on an arrow is a press of its own. */
    double_clicks = 0;
    for (int i = 0; i < 10; ++i) {
        milliseconds += 120;
        assert(dblclk_translate(&window, 0x201, 0x100010) == 0x201);
        assert(dblclk_translate(&window, 0x202, 0x100010) == 0x202);
    }
    double_clicks = 1;
    milliseconds += 40;
    assert(dblclk_translate(&window, 0x201, 0x100010) == 0x201);
    milliseconds += 40;
    assert(dblclk_translate(&window, 0x201, 0x100010) == 0x203);
    return 0;
}
''')
    compiler, env, _ = compiler_environment()
    exe = out / "double_click.exe"
    subprocess.run([str(compiler), "/nologo", "/std:c11", str(probe), "/Fe" + str(exe), "/Fo" + str(out / "double_click.obj")], env=env, check=True, capture_output=True)
    subprocess.run([str(exe)], check=True)
    controls = (ROOT / "android/app/src/org/thevoid/port/Controls.java").read_text(encoding="utf-8")
    begin = controls.index("if (screen != S_BODY && !panelVisible()")
    guard = controls[begin:controls.index(" {", begin)]
    java = out / "BackPriorityProbe.java"
    java.write_text('''public class BackPriorityProbe {
    static final int S_BODY = 3, HUD_BACK = 1;
    static class MotionEvent { static final int ACTION_DOWN = 0; }
    static class Settings { boolean touchAdaptations = true; }
    static class Event { float getX(int i) { return 95; } float getY(int i) { return 90; } }
    Settings settings = new Settings(); Event event = new Event();
    int screen, hud = HUD_BACK, action, index;
    int getWidth() { return 100; } int getHeight() { return 100; }
    boolean panelVisible() { return false; }
    static final int SLOT_BACK = 19;
    boolean inSlot(int slot, float x, float y, int pad) { return true; }
    static class PalettePicker { static final int FLOATS = 72; }
    static class Input {
        static final int LEFT=0, ESC=1;
        int clicks, escapes, cursors; float x,y;
        void cursorTo(float a,float b) { ++cursors; x=a; y=b; }
        void click(int code) { assert code==LEFT; ++clicks; }
        void tapKey(int code) { assert code==ESC; ++escapes; }
    }
    static class Touch { int cancelled; void cancel() { ++cancelled; } }
    final Input in=new Input(); final Touch touch=new Touch();
    final float[] slotValues=new float[27*PalettePicker.FLOATS];
    boolean paintMode, journalHandled; int journalCalls;
    boolean touchAdaptations() { return settings.touchAdaptations; }
    void setPaintMode(boolean on) { paintMode=on; }
    boolean journalBackToBody() { ++journalCalls; return journalHandled; }
    boolean oldBackTakesTouch() {
''' + guard + ''' return true;
        return false;
    }
''' + method(controls, "void escape()") + '''
    public static void main(String[] args) {
        BackPriorityProbe p = new BackPriorityProbe();
        p.screen = S_BODY;
        assert !p.oldBackTakesTouch() : "the old Back image's transparent rectangle must not intercept Gold";
        p.screen = 2;
        assert p.oldBackTakesTouch() : "other screens retain their original Back action";
        // Android Back must use Body's Escape handler, including carried Gold.
        p = new BackPriorityProbe(); p.screen=S_BODY; p.escape();
        assert p.in.escapes==1&&p.in.clicks==0&&p.in.cursors==0&&p.touch.cancelled==0
            : "Android Back in Body/Gold must send Escape, not a measured mouse click";
        p = new BackPriorityProbe(); p.screen=S_BODY; p.paintMode=true; p.escape();
        assert !p.paintMode&&p.in.escapes==0&&p.in.clicks==0&&p.journalCalls==0
            : "putting the brush down keeps priority over closing Body";
        // Non-Body HUD_BACK still clicks the measured control, ahead of keys.
        p = new BackPriorityProbe(); p.screen=2; p.paintMode=true;
        int at=SLOT_BACK*PalettePicker.FLOATS+64;
        p.slotValues[at]=.1f; p.slotValues[at+1]=.2f;
        p.slotValues[at+2]=.3f; p.slotValues[at+3]=.6f;
        p.escape();
        assert !p.paintMode&&p.touch.cancelled==1&&p.in.clicks==1&&p.in.escapes==0&&p.journalCalls==0;
        assert Math.abs(p.in.x-.2f)<.00001f&&Math.abs(p.in.y-.4f)<.00001f;
        p = new BackPriorityProbe(); p.screen=4; p.hud=0; p.journalHandled=true; p.escape();
        assert p.journalCalls==1&&p.in.escapes==0&&p.in.clicks==0
            : "the journal bridge handles its own Escape without a second key";
        p = new BackPriorityProbe(); p.screen=4; p.hud=0; p.escape();
        assert p.journalCalls==1&&p.in.escapes==1&&p.in.clicks==0;
        p = new BackPriorityProbe(); p.screen=2; p.settings.touchAdaptations=false; p.escape();
        assert p.in.escapes==1&&p.in.clicks==0;
    }
}
''', encoding="utf-8")
    subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-d", str(out), str(java)], check=True, capture_output=True)
    subprocess.run([str(JAVA_HOME / "bin/java.exe"), "-ea", "-cp", str(out), "BackPriorityProbe"], check=True)
    print("PASS: repeated body-widget presses, quick page taps, Windows double-clicks, production Android Back Body/Gold Escape, paint/journal priority and non-Body measured Back")


if __name__ == "__main__":
    main()
