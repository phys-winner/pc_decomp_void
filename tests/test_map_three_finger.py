"""Execute the shipped map tap recognizer against multi-touch event sequences."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_game_apk import JAVA_HOME


def method(source, declaration):
    start = source.index(declaration)
    brace = source.index("{", start)
    end, depth = brace + 1, 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def main():
    source = (ROOT / "android/app/src/org/thevoid/port/Controls.java").read_text(encoding="utf-8")
    assert method(source, "private void ui(MotionEvent e)").split("{", 1)[1].lstrip().startswith(
        "if (threeFingerTap(e)) return;")
    assert "uiFingers = 0;" in method(source, "void cancel()")
    out = ROOT / "build/test-map-three-finger"
    out.mkdir(parents=True, exist_ok=True)
    probe = out / "MapTapProbe.java"
    probe.write_text('''public class MapTapProbe {
    static final int S_MAP = 2;
    int screen = S_MAP, uiFingers, uiId = -1, uiId2 = -1, uiId3 = -1, centres, cancelled;
    float uiDownX, uiDownY, twoDownX, twoDownY, threeDownX, threeDownY;
    boolean twoMoved, longFired;
    long uiDownTime;
    float slop() { return 9; }
    void startCentring() { ++centres; }
    void cancel() { ++cancelled; uiFingers = 0; uiId = uiId2 = uiId3 = -1; }
    static class MotionEvent {
        static final int ACTION_DOWN=0, ACTION_UP=1, ACTION_MOVE=2, ACTION_CANCEL=3,
            ACTION_POINTER_DOWN=5, ACTION_POINTER_UP=6;
        int action, index; long time; int[] ids; float[] xs, ys;
        MotionEvent(int a, int i, long t, int... fingers) {
            action=a; index=i; time=t; ids=fingers; xs=new float[ids.length]; ys=new float[ids.length];
            for (int k=0; k<ids.length; ++k) { xs[k]=ids[k]*10; ys[k]=100; }
        }
        int getActionMasked() { return action; } int getActionIndex() { return index; }
        int getPointerCount() { return ids.length; } int getPointerId(int i) { return ids[i]; }
        float getX(int i) { return xs[i]; } float getY(int i) { return ys[i]; }
        long getEventTime() { return time; }
    }
''' + method(source, "private boolean threeFingerTap(MotionEvent e)") + '''
    void begin() {
        assert !threeFingerTap(new MotionEvent(0, 0, 1000, 7));
        uiId=7; uiDownX=70; uiDownY=100; uiDownTime=1000;
        assert !threeFingerTap(new MotionEvent(5, 1, 1040, 7, 13));
        uiId2=13; twoDownX=130; twoDownY=100;
    }
    void third() { assert threeFingerTap(new MotionEvent(5, 2, 1080, 7, 13, 29)); }
    void finish(long time) {
        assert threeFingerTap(new MotionEvent(6, 0, 1120, 29, 7, 13));
        assert threeFingerTap(new MotionEvent(6, 1, 1160, 13, 7));
        assert threeFingerTap(new MotionEvent(1, 0, time, 13));
    }
    public static void main(String[] args) {
        int[][] orders={{7,13,29},{7,29,13},{13,7,29},{13,29,7},{29,7,13},{29,13,7}};
        for (int[] order : orders) {
            MapTapProbe p=new MapTapProbe(); p.begin(); p.third();
            // Android may reorder the pointer indices as fingers lift.
            assert p.threeFingerTap(new MotionEvent(6, 0, 1120, order));
            assert p.centres==0;
            assert p.threeFingerTap(new MotionEvent(6, 0, 1160, order[1], order[2]));
            assert p.threeFingerTap(new MotionEvent(1, 0, 1200, order[2]));
            assert p.centres==1 && p.cancelled==1 && p.uiFingers==0;
        }
        MapTapProbe p=new MapTapProbe(); p.begin(); p.third(); p.finish(1449); assert p.centres==1;
        p=new MapTapProbe(); p.begin(); p.third(); p.finish(1450); assert p.centres==0;
        for (int id=0; id<3; ++id) {
            p=new MapTapProbe(); p.begin(); p.third();
            MotionEvent move=new MotionEvent(2, 0, 1100, 7,13,29); move.xs[id]+=10;
            assert p.threeFingerTap(move); p.finish(1200); assert p.centres==0;
        }
        p=new MapTapProbe(); p.begin();
        MotionEvent lateMove=new MotionEvent(5,2,1080,7,13,29); lateMove.ys[0]+=10;
        assert p.threeFingerTap(lateMove); p.finish(1200); assert p.centres==0;
        p=new MapTapProbe(); p.begin(); p.third();
        MotionEvent release=new MotionEvent(6,2,1100,7,13,29); release.xs[2]+=10;
        assert p.threeFingerTap(release); p.finish(1200); assert p.centres==0;
        p=new MapTapProbe(); p.begin(); p.third();
        assert p.threeFingerTap(new MotionEvent(5,3,1100,7,13,29,31));
        assert p.threeFingerTap(new MotionEvent(6,3,1110,7,13,29,31));
        p.finish(1200); assert p.centres==0;
        p=new MapTapProbe(); p.begin(); p.third();
        assert p.threeFingerTap(new MotionEvent(6,2,1100,7,13,29));
        assert p.threeFingerTap(new MotionEvent(5,2,1110,7,13,31));
        assert p.threeFingerTap(new MotionEvent(6,2,1120,7,13,31));
        assert p.threeFingerTap(new MotionEvent(6,1,1160,7,13));
        assert p.threeFingerTap(new MotionEvent(1,0,1200,7)); assert p.centres==0;
        p=new MapTapProbe(); p.begin(); p.third();
        assert p.threeFingerTap(new MotionEvent(3,0,1100,7,13,29)); assert p.centres==0;
        p=new MapTapProbe(); p.begin(); p.twoMoved=true; p.third(); p.finish(1200); assert p.centres==0;
        p=new MapTapProbe(); p.begin(); p.longFired=true; p.third(); p.finish(1200); assert p.centres==0;
        p=new MapTapProbe(); p.screen=3; p.begin(); p.third(); p.finish(1200); assert p.centres==0;
        p=new MapTapProbe(); p.begin();
        assert !p.threeFingerTap(new MotionEvent(2,0,1080,7,13));
        assert !p.threeFingerTap(new MotionEvent(6,1,1120,7,13));
        assert !p.threeFingerTap(new MotionEvent(1,0,1200,7)); assert p.centres==0;
        p.begin(); p.third(); p.cancel();
        assert !p.threeFingerTap(new MotionEvent(1,0,1200,7)); assert p.centres==0;
    }
}
''', encoding="utf-8")
    subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-d", str(out), str(probe)], check=True)
    subprocess.run([str(JAVA_HOME / "bin/java.exe"), "-ea", "-cp", str(out), "MapTapProbe"], check=True)
    print("PASS map three-finger tap: six release orders, duration, all fingers' motion, fourth/replacement finger, cancel, previous pinch/hold, off-map; two-finger pass-through")


if __name__ == "__main__":
    main()
