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
        int getVisibility() { return visibility; }
        View parent;
        View getParent() { if (parent == null) parent = new View(); return parent; }
    }
    static class TextView extends View {
        String text; int colour;
        void setText(CharSequence value) { text = value == null ? null : value.toString(); }
        void setTextColor(int value) { colour = value; }
    }
    static class ProgressBar extends View { void setIndeterminate(boolean value) { } void setProgress(int value) { } }
    static class Color { static int rgb(int r, int g, int b) { return 0xff000000 | r << 16 | g << 8 | b; } }
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
    static class Textures {
        static final int ASTC = 2, ETC2 = 1, SCANNING = 3, FINISHING = 4;
        static class Job { boolean finished, cancelled; final Meter meter=new Meter(); long[] progress() { return new long[5]; } }
        static class Meter { String describe(String language,boolean textures,long done,long total,long items,long all){return done+"/"+total;} }
        static class Gpu { boolean probed = true, s3tc, astc = true; String renderer = "GPU"; }
        static class Status { File game; String failure; int converted; long textures, bytes, convertedTextures, convertedBytes, estimateAstc, estimateEtc2, free; boolean current; }
        static Job current;
    }
    static final int GOLD = 0xffffcd32, GREY = 0xffa5a5b2;
    final Handler handler = new Handler(); final Copies copies = new Copies();
    final View archiveButton = new View(), folderButton = new View(), play = new View(), optionsBox = new View();
    final TextView cleanupButton = new TextView();
    final TextView filesHeading = new TextView(), playNote = new TextView(), note = new TextView();
    final View fileDetails = new View(); TextView busyNote;
    boolean filesExpanded;
    boolean texturesExpanded, gameFolder;
    final View texBox = new View(), texProgressBox = new View(), texDetails = new View(), texAstc = new View(),
        texEtc2 = new View(), texRemove = new View(), texStop = new View();
    final TextView texNote = new TextView(), texHeading = new TextView(), texSupport = new TextView(), texState = new TextView(), texInfo = new TextView(), texProgressText = new TextView();
    final ProgressBar texProgress = new ProgressBar();
    Textures.Gpu texGpu; Textures.Status texStatus;
    File game, cleanupScanning, texScanning; GameCleanup.Plan cleanupPlan; int cleanupGeneration;
    String busy; boolean storage = true, destroyed;
    boolean storage() { return storage; }
    boolean isFinishing() { return false; } boolean isDestroyed() { return destroyed; }
    static String text(int id) { return "Remove extra game files"; }
    static String size(long bytes) { return bytes + " bytes"; }
    static String fmt(int id, Object... args) { return text(id) + Arrays.toString(args); }
    static String progressText(long done, long total) { return done + "/" + total; }
    static void ignored(Exception e) { }
''' + source[source.index("    static final int T_GAME ="):source.index("    private static final String[][] TEXTS =")]
    + scan + '\n' + method(source, "private void enable()") + '\n' + method(source, "private void showTextures(boolean idle)") + '\n'
    + method(source, "private static void setEnabled(View v, boolean on)") + '''
    void choose(String name, Gate gate) { game = new File(name); GameCleanup.gates.put(game, gate); }
    public static void main(String[] args) throws Exception {
        CleanupPreviewProbe p = new CleanupPreviewProbe();
        p.playNote.setVisibility(View.GONE);
        p.enable();
        assert p.play.visibility == View.GONE && p.optionsBox.visibility == View.GONE;
        assert p.fileDetails.visibility == View.GONE : "file paths must start collapsed";
        p.filesExpanded = true; p.enable();
        assert p.fileDetails.visibility == View.VISIBLE;
        p.game = new File("/textures"); p.gameFolder = true; p.texGpu = new Textures.Gpu();
        p.texStatus = new Textures.Status(); p.texStatus.game = p.game; p.texStatus.textures = 10;
        p.showTextures(true); assert p.texDetails.visibility == View.GONE;
        assert p.texSupport.colour == GOLD;
        p.texturesExpanded = true; p.showTextures(true);
        assert p.texDetails.visibility == View.VISIBLE && p.texEtc2.visibility == View.VISIBLE;
        Textures.current = new Textures.Job(); p.showTextures(false);
        assert p.texDetails.visibility == View.GONE && p.texProgressBox.visibility == View.VISIBLE;
        Textures.current = null; p.texGpu.s3tc = true; p.showTextures(true);
        assert p.texSupport.colour == Color.rgb(159, 213, 154) && p.texEtc2.visibility == View.GONE;
        p.texGpu.probed = false; p.showTextures(true); assert p.texSupport.colour == GREY;
        Unpacker.current = new Object(); p.enable();
        assert p.fileDetails.visibility == View.GONE : "installation progress replaces file controls";
        Unpacker.current = null; p.enable();
        assert p.fileDetails.visibility == View.VISIBLE;
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
