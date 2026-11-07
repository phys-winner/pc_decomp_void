"""Run production Java mouse taps against a slow frame-polled menu."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_game_apk import JAVA_HOME
from test_touch_controls import method


def main():
    out = ROOT / "build/menu-click-frames-test"
    out.mkdir(parents=True, exist_ok=True)
    controls = (ROOT / "android/app/src/org/thevoid/port/Controls.java").read_text(encoding="utf-8")
    (out / "Looper.java").write_text("""package android.os;
public final class Looper { public static Looper getMainLooper() { return new Looper(); } }
""")
    (out / "SystemClock.java").write_text("""package android.os;
public final class SystemClock { public static long now; public static long uptimeMillis() { return now; } }
""")
    (out / "Handler.java").write_text("""package android.os;
import java.util.*;
public final class Handler {
    static final class Event implements Comparable<Event> {
        Handler owner; Runnable task; long at, order;
        public int compareTo(Event b) { int c=Long.compare(at,b.at); return c!=0?c:Long.compare(order,b.order); }
    }
    static PriorityQueue<Event> events=new PriorityQueue<>(); static long sequence;
    public Handler(Looper unused) { }
    public boolean postDelayed(Runnable task,long delay) {
        Event e=new Event(); e.owner=this; e.task=task; e.at=SystemClock.now+delay; e.order=sequence++;
        events.add(e); return true;
    }
    public void removeCallbacks(Runnable task) { events.removeIf(e->e.owner==this&&e.task==task); }
    public void removeCallbacksAndMessages(Object unused) { events.removeIf(e->e.owner==this); }
    public static void reset() { events.clear(); SystemClock.now=sequence=0; }
    public static void run(long until) {
        while(!events.isEmpty()&&events.peek().at<=until) {
            Event e=events.remove(); SystemClock.now=e.at; e.task.run();
        }
        SystemClock.now=until;
    }
}
""")
    tap = method(controls, "private void tap(float x, float y, long time)")
    finish = method(controls, "private void finishClick()") if "private void finishClick()" in controls else ""
    (out / "MenuClickProbe.java").write_text("""package org.thevoid.port;
import android.os.*;
import java.util.*;

final class GameActivity {
    static long frame; static boolean down, hovered, armed;
    static float x,y; static int activations, presses, releases, doubles;
    static long lastDown=-1000; static float lastX,lastY;
    static final ArrayList<Long> edges=new ArrayList<>();
    static final ArrayList<float[]> pendingDowns=new ArrayList<>();
    static void reset(long firstFrame) {
        Handler.reset(); frame=firstFrame; down=hovered=armed=false;
        x=y=0; activations=presses=releases=doubles=0; lastDown=-1000; edges.clear(); pendingDowns.clear();
    }
    static long nativeHudState() { return frame<<32; }
    static void nativeMouseButton(int code,boolean held) {
        if(code!=Input.LEFT) return;
        down=held; edges.add(SystemClock.now);
        if(held) {
            ++presses;
            pendingDowns.add(new float[]{x,y});
        } else ++releases;
    }
    static void nativeMouseMove(float a,float b,boolean relative) { if(!relative) { x=a; y=b; } }
    static void nativeMouseWarp(float a,float b) { x=a; y=b; }
    static void nativeMouseWheel(int ignored) { }
    static void nativeMovement(float a,float b) { }
    static void nativeKey(int code,boolean held) { }
    // The menu first updates hover, then a later frame can arm its button.
    // Poll before Present: the first advance after an event may be an already
    // running frame whose input snapshot predates that event.
    static void pollMenu() {
        // Native input.c posts queued messages on the guest thread; user32's
        // double-click clock is read there, not at the Android touch timestamp.
        for(float[] point:pendingDowns) {
            if(SystemClock.now-lastDown<=500&&point[0]==lastX&&point[1]==lastY) {
                ++doubles; lastDown=-1000;
            } else { lastDown=SystemClock.now; lastX=point[0]; lastY=point[1]; }
        }
        pendingDowns.clear();
        boolean target=x>0&&y>0;
        if(hovered&&target&&down) armed=true;
        if(armed&&!down) { ++activations; armed=false; }
        hovered=target;
    }
    static void frames(int period,int start,long until) {
        Handler h=new Handler(Looper.getMainLooper());
        for(int at=start;at<=until;at+=period) {
            h.postDelayed(GameActivity::pollMenu,at);
            h.postDelayed(()->frame=(frame+1)&0xffffffffL,at+period-1);
        }
    }
}

public final class MenuClickProbe {
    static final class Tap {
        Input in; long lastTapTime; float lastTapX,lastTapY;
        Runnable clickDown,clickUp;
        Handler handler=new Handler(Looper.getMainLooper());
        Tap(Input input) { in=input; }
        int getWidth() { return 100; } int getHeight() { return 100; }
        int dp(int n) { return n; }
        void postDelayed(Runnable r,long ms) { handler.postDelayed(r,ms); }
        void removeCallbacks(Runnable r) { handler.removeCallbacks(r); }
""" + tap + "\n" + finish + """
    }
    static void cancelClicks(Input in) throws Exception {
        // The pre-fix class has no pulse-only cancellation helper.
        try { Input.class.getDeclaredMethod("cancelClicks").invoke(in); }
        catch(NoSuchMethodException e) { in.releaseAll(); }
    }
    public static void main(String[] unused) throws Exception {
        int slowCases=0;
        for(int period:new int[]{125,143,200}) for(int phase=1;phase<period;phase+=7) {
            for(boolean touch:new boolean[]{false,true}) {
                if(touch&&unused.length>0) continue;
                GameActivity.reset(0); Input in=new Input();
                GameActivity.frames(period,phase,2000);
                if(touch) new Tap(in).tap(30,40,0);
                else { in.cursorTo(.3f,.4f); in.click(Input.LEFT); }
                Handler.run(2000);
                assert GameActivity.activations==1 : "missed click at period="+period+", phase="+phase+", touch="+touch;
                assert GameActivity.presses==1&&GameActivity.releases==1&&!GameActivity.down;
                ++slowCases;
            }
        }
        // Holding a finger for 250 ms used to produce the same short pulse on Up.
        GameActivity.reset(0); Input in=new Input(); Tap tap=new Tap(in);
        GameActivity.frames(143,1,2000); in.cursorTo(.3f,.4f); Handler.run(250);
        tap.tap(30,40,250); Handler.run(2000);
        assert GameActivity.activations==1 : "missed long-finger menu tap";
        // Fast UI still has 50 ms hover/90 ms press; queued taps stay two clicks.
        GameActivity.reset(0); in=new Input(); tap=new Tap(in);
        GameActivity.frames(16,1,1000); tap.tap(30,40,0); Handler.run(80); tap.tap(32,42,80); Handler.run(1000);
        assert GameActivity.activations==2&&GameActivity.presses==2&&GameActivity.releases==2;
        assert GameActivity.doubles==1 : "a fast second tap must remain a Windows double click";
        assert GameActivity.edges.get(0)>=50&&GameActivity.edges.get(0)<=60;
        assert GameActivity.edges.get(1)>=140&&GameActivity.edges.get(1)<=150;
        // At 7 FPS the second native Down must still meet Windows' 500 ms
        // double-click window. A second two-frame hover wait would break it.
        for(int phase=1;phase<143;phase+=7) {
            GameActivity.reset(0); in=new Input(); tap=new Tap(in);
            GameActivity.frames(143,phase,2000);
            tap.tap(30,40,0); Handler.run(80); tap.tap(32,42,80); Handler.run(2000);
            assert GameActivity.presses==2&&GameActivity.releases==2;
            assert GameActivity.doubles==1 : "slow Windows double-click interval at phase="+phase;
            assert GameActivity.edges.get(2)-GameActivity.edges.get(0)<500;
        }
        // A uint32 frame wrap must not make a pulse wait for its deadline.
        GameActivity.reset(0xfffffffeL); in=new Input(); GameActivity.frames(16,1,500);
        in.cursorTo(.3f,.4f); in.click(Input.LEFT); Handler.run(500);
        assert GameActivity.activations==1&&GameActivity.edges.get(1)<=150;
        // A stopped renderer cannot leave a mouse button held indefinitely.
        GameActivity.reset(0); in=new Input(); in.click(Input.LEFT); Handler.run(1500);
        assert GameActivity.presses==1&&GameActivity.releases==1&&!GameActivity.down;
        assert GameActivity.edges.get(1)<=1300;
        // Cancel before Down must never synthesize a phantom click.
        GameActivity.reset(0); in=new Input(); GameActivity.frames(16,1,1000);
        in.click(Input.LEFT); Handler.run(20); cancelClicks(in); Handler.run(1000);
        assert GameActivity.presses==0&&GameActivity.releases==0;
        // Cancel a held pulse and its queued successor; preserve other owners.
        GameActivity.reset(0); in=new Input(); GameActivity.frames(16,1,1000);
        in.button(Input.LEFT,true); in.click(Input.LEFT); in.click(Input.LEFT);
        Handler.run(80); cancelClicks(in); assert in.held(Input.LEFT)&&GameActivity.down;
        in.button(Input.LEFT,false); Handler.run(1000);
        assert GameActivity.presses==1&&GameActivity.releases==1&&!GameActivity.down;
        GameActivity.reset(0); in=new Input(); GameActivity.frames(16,1,1000);
        in.click(Input.LEFT); in.click(Input.LEFT); Handler.run(80); in.releaseAll(); Handler.run(1000);
        assert GameActivity.presses==1&&GameActivity.releases==1&&!GameActivity.down;
        System.out.println("PASS: "+slowCases+" real Input/TouchView low-FPS phases, long finger, fast/7 FPS Windows double-click, wrap, stall, cancellation and shared owners");
    }
}
""", encoding="utf-8")
    sources = [ROOT / "android/app/src/org/thevoid/port/Input.java", *out.glob("*.java")]
    compile_result = subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-encoding", "UTF-8",
                                     "-d", str(out), *map(str, sources)], capture_output=True, text=True)
    (out / "build.log").write_text(compile_result.stdout + compile_result.stderr)
    assert compile_result.returncode == 0, compile_result.stdout + compile_result.stderr
    run = subprocess.run([str(JAVA_HOME / "bin/java.exe"), "-ea", "-cp", str(out),
                          "org.thevoid.port.MenuClickProbe"], capture_output=True, text=True)
    (out / "result.log").write_text(run.stdout + run.stderr)
    assert run.returncode == 0, run.stdout + run.stderr
    cancel = method(controls, "void cancel()")
    assert "in.cancelClicks();" in cancel and "clickDown.run()" not in cancel
    print(run.stdout, end="")


if __name__ == "__main__":
    main()
