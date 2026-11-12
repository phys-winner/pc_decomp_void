package port.launcher;

import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.Map;

/** The Vulkan driver check behind the DXVK renderers, in a process of its own (":probe"): loading a
 *  GPU driver can crash, and only this process goes down with it. It asks the system Vulkan driver
 *  and, on Qualcomm GPUs with a Turnip mode, the port's Turnip through adrenotools what DXVK would
 *  refuse (native/vulkan_probe.c in libportprobe.so), writes the report for this build of the app on
 *  this build of the system (Build.FINGERPRINT: a system update brings another driver) and ends its
 *  process, which unloads the drivers again. Before each driver it notes the stage, so a report still
 *  missing after TIMEOUT_MS names the driver that crashed, and that check is not repeated. The
 *  player's own Turnip driver (TurnipDriver) is checked in place of the port's, and is part of the key.
 *
 *  Report lines (homm5's format): stock.status=ok|missing|error|crash|skipped, stock.device,
 *  stock.vendor (hex), stock.api, stock.driver, stock.driverId (VkDriverId), stock.missing (tokens of vulkan_requirements.h),
 *  stock.error; the same with "turnip.". */
public final class Probe extends Service {
    static final String LIBRARY = "portprobe", FILE = "lib" + LIBRARY + ".so";
    static final String REPORT = "probe.txt", PARTIAL = "probe.part", STAGE = "probe.stage";
    /** A check that has not reported by then crashed or hung in the stage it noted. */
    static final long TIMEOUT_MS = 15000;
    static final int QUALCOMM = 0x5143;

    private static native String nativeProbe(String libraryDir, String driver);
    private static boolean started;

    @Override public int onStartCommand(Intent intent, int flags, int id) {
        synchronized (Probe.class) {
            if (started) return START_NOT_STICKY;
            started = true;
        }
        new Thread(this::check, "vulkan-probe").start();
        return START_NOT_STICKY;
    }

    @Override public IBinder onBind(Intent intent) { return null; }

    private void check() {
        File dir = State.folder(this);
        String key = key(this), libraries = getApplicationInfo().nativeLibraryDir;
        String stock, turnip = "turnip.status=skipped\n";
        write(new File(dir, STAGE), key + "\nstock\n");
        try {
            System.loadLibrary(LIBRARY);
            stock = nativeProbe(libraries, null);
        } catch (UnsatisfiedLinkError e) {
            stock = "stock.status=error\nstock.error=" + line(e.getMessage()) + "\n";
        }
        Spec.Mode mode = turnipMode(Spec.get(this));
        if (mode != null && vendor(parse(stock), "stock") == QUALCOMM && Renderers.libraries(this).containsAll(mode.libraries)) {
            write(new File(dir, PARTIAL), key + "\n" + stock);
            write(new File(dir, STAGE), key + "\nturnip\n");
            File own = TurnipDriver.chosen(this);
            try {
                turnip = nativeProbe(libraries, own != null ? own.getAbsolutePath() : mode.driver);
            } catch (UnsatisfiedLinkError e) {
                turnip = "turnip.status=error\nturnip.error=" + line(e.getMessage()) + "\n";
            }
        }
        write(new File(dir, REPORT), key + "\n" + stock + turnip);
        new File(dir, STAGE).delete();
        new File(dir, PARTIAL).delete();
        android.util.Log.i("Launcher", "Vulkan check:\n" + stock + turnip);
        stopSelf();
        android.os.Process.killProcess(android.os.Process.myPid());
    }

    private static String line(String text) { return String.valueOf(text).replace('\n', ' ').replace('\r', ' '); }

    /* ------------------------------------------------ the launcher's side */

    /** A report belongs to one build of the app on one build of the system, with one Turnip driver. */
    static String key(Context context) { return Build.FINGERPRINT + "|" + Launch.build(context) + "|" + TurnipDriver.identity(context); }

    /** Whether any renderer depends on the check. */
    static boolean needed(Spec spec) {
        for (Spec.Mode m : spec.modes) if (m.vulkanKind()) return true;
        return false;
    }

    /** Whether this build carries the check (a game that leaves libportprobe.so out has none). */
    static boolean carried(Context context) { return Renderers.libraries(context).contains(FILE); }

    static Spec.Mode turnipMode(Spec spec) {
        for (Spec.Mode m : spec.modes) if ("turnip".equals(m.kind) && !m.driver.isEmpty()) return m;
        return null;
    }

    /** This build's report on this system; a check that crashed or hung counts as done (its driver
     *  reports "crash") so that it is not repeated on every start. Null while it runs or before it. */
    static Map<String, String> report(Context context) {
        File dir = State.folder(context);
        String key = key(context);
        String text = read(new File(dir, REPORT));
        if (text != null && text.startsWith(key + "\n")) return parse(text.substring(key.length() + 1));
        File stage = new File(dir, STAGE);
        String running = read(stage);
        if (running == null || !running.startsWith(key + "\n") || age(stage) <= TIMEOUT_MS) return null;
        String driver = running.substring(key.length() + 1).trim();
        String partial = read(new File(dir, PARTIAL));
        String done = partial != null && partial.startsWith(key + "\n") ? partial.substring(key.length() + 1) : "";
        String crashed = done + ("turnip".equals(driver) ? "turnip.status=crash\n"
            : "stock.status=crash\nturnip.status=skipped\n");
        write(new File(dir, REPORT), key + "\n" + crashed);
        stage.delete();
        new File(dir, PARTIAL).delete();
        android.util.Log.w("Launcher", "Vulkan check: the " + driver + " stage did not finish");
        return parse(crashed);
    }

    /** Whether a check of this build runs now (or was just started). */
    static boolean running(Context context) {
        if (reported(context)) return false;
        File stage = new File(State.folder(context), STAGE);
        String text = read(stage);
        return text != null && text.startsWith(key(context) + "\n") && age(stage) <= TIMEOUT_MS;
    }

    private static boolean reported(Context context) {
        String text = read(new File(State.folder(context), REPORT));
        return text != null && text.startsWith(key(context) + "\n");
    }

    /** Starts the check unless this build and system have a report or a check runs now. */
    static void start(Context context, Spec spec) {
        if (!needed(spec) || !carried(context) || report(context) != null || running(context)) return;
        /* Noted before the service starts: a service that never comes up times out as a crash too. */
        write(new File(State.folder(context), STAGE), key(context) + "\nstart\n");
        try {
            context.startService(new Intent(context, Probe.class));
        } catch (RuntimeException e) {
            android.util.Log.w("Launcher", "Vulkan check: " + e);
            String failure = startFailure(e);
            if (failure != null) write(new File(State.folder(context), REPORT), key(context) + "\n" + failure);
            new File(State.folder(context), STAGE).delete();
        }
    }

    /** Android's background-start rejection is transient; retry when the launcher regains focus. */
    static String startFailure(RuntimeException error) {
        if (error instanceof IllegalStateException) return null;
        return "stock.status=error\nstock.error=" + line(error.getMessage()) + "\nturnip.status=skipped\n";
    }

    static Map<String, String> parse(String report) {
        Map<String, String> values = new HashMap<>();
        if (report == null) return values;
        for (String row : report.split("\n")) {
            int equals = row.indexOf('=');
            if (equals > 0) values.put(row.substring(0, equals).trim(), row.substring(equals + 1).trim());
        }
        return values;
    }

    static int vendor(Map<String, String> report, String driver) {
        try { return Integer.parseInt(report.getOrDefault(driver + ".vendor", ""), 16); }
        catch (NumberFormatException e) { return 0; }
    }

    private static long age(File file) { return Math.abs(System.currentTimeMillis() - file.lastModified()); }

    static String read(File file) {
        if (!file.isFile()) return null;
        try { return new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8); }
        catch (IOException e) { return null; }
    }

    static void write(File file, String text) {
        File part = new File(file.getPath() + ".tmp");
        try (FileOutputStream out = new FileOutputStream(part)) {
            out.write(text.getBytes(StandardCharsets.UTF_8));
            out.getFD().sync();
        } catch (IOException e) {
            Work.warn("Vulkan check: " + e, e);
            return;
        }
        if (!part.renameTo(file)) Work.warn("Vulkan check: cannot replace " + file, null);
    }
}
