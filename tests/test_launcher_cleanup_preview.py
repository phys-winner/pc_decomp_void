"""Exercise the shipped launcher's asynchronous availability scan on the JVM."""
import os
from pathlib import Path
import subprocess

from test_touch_controls import method

ROOT = Path(__file__).resolve().parents[1]
JAVA = Path(os.environ.get("JAVA_HOME", "")) / "bin"
OUT = ROOT / "build/cleanup-preview-test"
OUT.mkdir(parents=True, exist_ok=True)
source = (ROOT / "android/app/src/org/thevoid/port/Launcher.java").read_text(encoding="utf-8")
scan = method(source, "private void refreshCleanup()")
scan = scan.replace('android.util.Log.w("TheVoid", "cleanup preview: " + selected, e);', 'ignored(e);')
probe = OUT / "CleanupPreviewProbe.java"
probe.write_text('''import java.io.*;
import java.util.*;
import java.util.concurrent.*;
public class CleanupPreviewProbe {
    static class View {
        static final int GONE = 8, VISIBLE = 0;
        int visibility; boolean enabled;
        void setVisibility(int value) { visibility = value; }
        void setEnabled(boolean value) { enabled = value; }
        void setAlpha(float value) { }
    }
    static class TextView extends View { String text; void setText(String value) { text = value; } }
    static class Copies { int getChildCount() { return 0; } View getChildAt(int i) { throw new AssertionError(); } }
    static class Handler {
        final BlockingQueue<Runnable> results = new LinkedBlockingQueue<>();
        void post(Runnable result) { results.add(result); }
        void deliver() throws Exception { Runnable r = results.poll(3, TimeUnit.SECONDS); assert r != null; r.run(); }
    }
    static class Gate {
        final CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        final int files; final long bytes; int calls;
        Gate(int files, long bytes) { this.files = files; this.bytes = bytes; }
    }
    static class GameCleanup {
        static final Map<File, Gate> gates = new ConcurrentHashMap<>();
        static class Plan {
            final File root; final List<Object> files; final long bytes;
            Plan(File root, int files, long bytes) { this.root = root; this.files = Collections.nCopies(files, this); this.bytes = bytes; }
        }
        static Plan scan(File root) throws IOException {
            Gate g = gates.get(root); ++g.calls; g.entered.countDown();
            try { if (!g.release.await(3, TimeUnit.SECONDS)) throw new IOException("timeout"); }
            catch (InterruptedException e) { throw new IOException(e); }
            if (g.files < 0) throw new IOException("unreadable");
            return new Plan(root, g.files, g.bytes);
        }
    }
    static class Unpacker { static Object current; }
    static final int T_CLEAN = 1;
    final Handler handler = new Handler(); final Copies copies = new Copies();
    final View archiveButton = new View(), folderButton = new View(), play = new View(), optionsBox = new View();
    final TextView cleanupButton = new TextView();
    File game, cleanupScanning; GameCleanup.Plan cleanupPlan; int cleanupGeneration;
    String busy; boolean storage = true, destroyed;
    boolean storage() { return storage; }
    boolean isFinishing() { return false; } boolean isDestroyed() { return destroyed; }
    static String text(int id) { return "Remove extra game files"; }
    static String size(long bytes) { return bytes + " bytes"; }
    static void ignored(Exception e) { }
''' + scan + '\n' + method(source, "private void enable()") + '\n'
    + method(source, "private static void setEnabled(View v, boolean on)") + '''
    void choose(String name, Gate gate) { game = new File(name); GameCleanup.gates.put(game, gate); }
    public static void main(String[] args) throws Exception {
        CleanupPreviewProbe p = new CleanupPreviewProbe();
        p.enable();
        assert p.play.visibility == View.GONE && p.optionsBox.visibility == View.GONE;
        p.game = new File("/selected"); p.enable();
        assert p.play.visibility == View.VISIBLE && p.optionsBox.visibility == View.VISIBLE && p.play.enabled;
        p.busy = "extracting"; p.enable();
        assert p.play.visibility == View.VISIBLE && !p.play.enabled;
        p.busy = null; p.game = null; p.enable();
        assert p.play.visibility == View.GONE && p.optionsBox.visibility == View.GONE;
        Gate first = new Gate(1, 123456);
        p.choose("/first", first); p.refreshCleanup();
        assert first.entered.await(1, TimeUnit.SECONDS);
        assert p.cleanupButton.visibility == View.GONE : "button shown before background result";
        p.refreshCleanup(); assert first.calls == 1 : "duplicate scan";
        Gate second = new Gate(2, 9000000);
        p.choose("/second", second); p.refreshCleanup();
        assert second.entered.await(1, TimeUnit.SECONDS);
        first.release.countDown(); p.handler.deliver();
        assert p.cleanupButton.visibility == View.GONE && p.cleanupPlan == null : "stale folder result";
        second.release.countDown(); p.handler.deliver();
        assert p.cleanupButton.visibility == View.VISIBLE && p.cleanupButton.enabled;
        assert p.cleanupButton.text.contains("9000000 bytes");
        p.busy = "extracting"; p.enable(); assert !p.cleanupButton.enabled;
        p.busy = null;
        Gate empty = new Gate(0, 0); p.choose("/empty", empty); p.refreshCleanup();
        assert empty.entered.await(1, TimeUnit.SECONDS);
        empty.release.countDown(); p.handler.deliver();
        assert p.cleanupButton.visibility == View.GONE;
        Gate failed = new Gate(-1, 0); p.choose("/failed", failed); p.refreshCleanup();
        assert failed.entered.await(1, TimeUnit.SECONDS);
        failed.release.countDown(); p.handler.deliver();
        assert p.cleanupButton.visibility == View.GONE && p.cleanupPlan == null;
        p.storage = false; p.refreshCleanup();
        assert p.cleanupScanning == null && p.cleanupButton.visibility == View.GONE;
        System.out.println("cleanup preview: asynchronous scan, stale result rejection, deduplication, exact size, empty/error visibility PASS");
    }
}
''', encoding="utf-8")
subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(OUT), str(probe)], check=True)
subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(OUT), "CleanupPreviewProbe"], check=True)
