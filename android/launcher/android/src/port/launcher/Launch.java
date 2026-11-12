package port.launcher;

import android.app.Activity;
import android.app.ActivityManager;
import android.app.ApplicationExitInfo;
import android.content.ActivityNotFoundException;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.system.ErrnoException;
import android.system.Os;
import android.view.Gravity;
import android.widget.FrameLayout;
import android.widget.TextView;
import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Properties;
import java.util.regex.Pattern;

/** The hand-over between the launcher and the game. The launcher records each start in
 *  files/launcher/launch-<distribution>.properties and starts the distribution's activity by name
 *  (the launcher's process never loads the game's classes, whose static blocks load its native
 *  library); the game's activity calls {@link #attach} first (paths, options and update in the
 *  PORT_* environment for native code), {@link #failed} when it refuses to start (files, access,
 *  preparation), {@link #firstFrame} once the game shows a picture, and {@link #exited} when the
 *  game ends. A start that never reached its first frame tells the launcher the renderer failed. */
public final class Launch {
    public static final String EXTRA_DISTRIBUTION = "launcher.distribution", EXTRA_RENDERER = "renderer",
        EXTRA_SKIP_INTRO = "skipIntro", EXTRA_PLAY = "launcher.play";
    /** The choices an earlier launcher of the game may hand over (adopt). */
    private static final Pattern ADOPTABLE = Pattern.compile("(part|option|intro|renderer)\\.[a-z0-9_.]+|last");

    private final Activity activity;
    private final Spec spec;
    private final Spec.Distribution distribution;
    private boolean reached;
    private static boolean migrated;

    private Launch(Activity activity, Spec spec, Spec.Distribution distribution) {
        this.activity = activity;
        this.spec = spec;
        this.distribution = distribution;
    }

    /* ----------------------------------------------------------- the game */

    /** For the game's activity, before it starts native code. */
    public static Launch attach(Activity activity) {
        Spec spec = Spec.get(activity);
        migrate(activity, PortHooks.of(activity));
        String id = activity.getIntent().getStringExtra(EXTRA_DISTRIBUTION);
        Spec.Distribution d = id != null ? spec.distribution(id) : null;
        if (d == null) {
            /* Started by a tool (am start) or the game's own restart: the distribution of this activity. */
            for (Spec.Distribution each : spec.distributions)
                if (each.activity.equals(activity.getClass().getName())) { d = each; break; }
        }
        if (d == null) d = spec.distributions.get(0);
        Launch launch = new Launch(activity, spec, d);
        launch.environment();
        return launch;
    }

    public String distribution() { return distribution.id; }

    /** The launcher's language for the game's own messages: "en", "ru", "de" or "pl". */
    public String language() { return language(activity); }

    public static String language(Context context) { return Texts.language(context); }

    /** The renderer the launcher chose for this start; null when started without the launcher. */
    public String renderer() { return activity.getIntent().getStringExtra(EXTRA_RENDERER); }

    /** A part's folder (the game reads it by path). */
    public File folder(String part) {
        Spec.Part p = distribution.part(part);
        return p == null ? null : Install.folder(activity, spec, distribution, p);
    }

    /** A distribution's configured folder, also available to installation checks in game hooks. */
    public static File folder(Context context, String distribution, String part) {
        Spec spec = Spec.get(context);
        Spec.Distribution d = spec.distribution(distribution);
        Spec.Part p = d != null ? d.part(part) : null;
        return p == null ? null : Install.folder(context, spec, d, p);
    }

    /** An option of port.json as the player set it, else its default. */
    public String option(String key) {
        return option(activity, key);
    }

    public static String option(Context context, String key) {
        Spec spec = Spec.get(context);
        for (Spec.Option o : spec.options) if (o.key.equals(key)) return option(context, o);
        return null;
    }

    static String option(Context context, Spec.Option option) {
        if (option.arm64Only && !android.os.Process.is64Bit()) return "0";
        String saved = State.get(context, State.CHOICES, "option." + option.key, null);
        if (saved != null) return saved;
        if (option.defaultMinRamGiB <= 0) return option.value;
        ActivityManager manager = (ActivityManager)context.getSystemService(Context.ACTIVITY_SERVICE);
        ActivityManager.MemoryInfo memory = new ActivityManager.MemoryInfo();
        if (manager != null) manager.getMemoryInfo(memory);
        return memoryDefault(option, memory.totalMem);
    }

    static String memoryDefault(Spec.Option option, long totalMem) {
        return totalMem >= option.defaultMinRamGiB * (1L << 30) ? "1" : "0";
    }

    public boolean skipIntro() {
        return "1".equals(State.get(activity, State.CHOICES, "intro." + distribution.id, distribution.introDefault ? "1" : "0"));
    }

    /** PORT_* variables for the game's native code (native/port_env.h): no JNI names involved. */
    private void environment() {
        set("PORT_DISTRIBUTION", distribution.id);
        set("PORT_VERSION_NAME", Updates.installedName(activity));
        set("PORT_VERSION_CODE", Long.toString(Updates.installedCode(activity)));
        set("PORT_LANGUAGE", Texts.language(activity));
        String mode = renderer();
        if (mode != null) set("PORT_RENDERER", mode);
        if (distribution.intro) set("PORT_SKIP_INTRO", skipIntro() ? "1" : "0");
        for (Spec.Part p : distribution.parts) {
            File folder = Install.folder(activity, spec, distribution, p);
            set("PORT_PART_" + p.id.toUpperCase(Locale.ROOT), folder.getAbsolutePath());
            String mount = Install.mount(activity, distribution, p);
            if (!mount.isEmpty()) {
                String id = p.id.toUpperCase(Locale.ROOT);
                set("PORT_MOUNT_" + id, new File(State.folder(activity), "mount-" + distribution.id + "-" + p.id + ".zmi").getAbsolutePath());
                /* The archive's descriptor, opened here and left open for the process: the game's file
                   layer (native/zipmount.c) reads it in place, whatever provider the archive came from. */
                try {
                    android.os.ParcelFileDescriptor fd = mount.startsWith("content:")
                        ? activity.getContentResolver().openFileDescriptor(android.net.Uri.parse(mount), "r")
                        : android.os.ParcelFileDescriptor.open(new File(mount), android.os.ParcelFileDescriptor.MODE_READ_ONLY);
                    if (fd != null) set("PORT_MOUNT_FD_" + id, Integer.toString(fd.detachFd()));
                } catch (java.io.IOException | RuntimeException e) {
                    android.util.Log.w("Launcher", "archive " + mount + ": " + e);
                }
            }
        }
        for (Spec.Option o : spec.options(distribution.id))
            set("PORT_OPTION_" + o.key.toUpperCase(Locale.ROOT), option(o.key));
        /* Empty for the port's own Turnip driver: an earlier start's choice must not linger. */
        File turnip = TurnipDriver.chosen(activity);
        set("PORT_TURNIP_DRIVER", turnip != null ? turnip.getAbsolutePath() : "");
        Updates.Info update = Updates.available(activity);
        if (update != null) {
            set("PORT_UPDATE_VERSION", update.versionName);
            set("PORT_UPDATE_PAGE", update.page);
        }
    }

    private static void set(String name, String value) {
        try {
            Os.setenv(name, value != null ? value : "", true);
        } catch (ErrnoException e) {
            android.util.Log.w("Launcher", "setenv " + name + ": " + e);
        }
    }

    /** The game shows its first picture: this build and renderer start here. Shows the update
     *  notice over the game once per version. */
    public void firstFrame(FrameLayout root) {
        if (reached) return;
        reached = true;
        State.put(activity, State.launch(distribution.id), "reached", "1");
        Updates.Info update = Updates.available(activity);
        if (update == null || root == null) return;
        String shown = State.get(activity, State.UPDATE, "noticed", "");
        if (shown.equals(Long.toString(update.versionCode))) return;
        State.put(activity, State.UPDATE, "noticed", Long.toString(update.versionCode));
        banner(root, Texts.fmt(activity, Texts.UPDATE_BANNER, update.versionName));
    }

    private void banner(FrameLayout root, String text) {
        float density = activity.getResources().getDisplayMetrics().density;
        TextView view = new TextView(activity);
        view.setText(text);
        view.setTextColor(0xFFFFFFFF);
        view.setTextSize(15);
        int pad = Math.round(12 * density);
        view.setPadding(pad * 2, pad, pad * 2, pad);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(0xD0141820);
        bg.setCornerRadius(14 * density);
        bg.setStroke(Math.round(density), 0x60FFFFFF);
        view.setBackground(bg);
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(-2, -2, Gravity.TOP | Gravity.CENTER_HORIZONTAL);
        lp.topMargin = Math.round(24 * density);
        root.addView(view, lp);
        view.setOnClickListener(v -> root.removeView(view));
        new Handler(Looper.getMainLooper()).postDelayed(() -> root.removeView(view), 7000);
    }

    /** The game refused this start before its native code ran (files missing, no access, its
     *  preparation failed): the reason in the player's words, shown on the distribution's card.
     *  The renderer is not blamed for it. */
    public void failed(String reason) { recordFailure(State.folder(activity), distribution.id, reason); }

    /** The game's native code starts now (after the player fixed what it refused, say): an earlier
     *  refusal of this start no longer applies. */
    public void starting() {
        State.update(activity, State.launch(distribution.id), values -> {
            values.remove("failed");
            values.remove("failedTime");
        });
    }

    static void recordFailure(File dir, String distribution, String reason) {
        String text = reason == null || reason.trim().isEmpty() ? "?" : reason.trim().replace('\n', ' ');
        State.update(dir, State.launch(distribution), values -> {
            values.setProperty("failed", text);
            values.setProperty("failedTime", Long.toString(System.currentTimeMillis()));
        });
    }

    /** The game ended: a clean exit opens the launcher in a fresh process state. */
    public void exited(int code) {
        State.put(activity, State.launch(distribution.id), "exit", Integer.toString(code));
        if (code != 0) return;
        openLauncher(activity, distribution.id);
        activity.finishAndRemoveTask();
        android.os.Process.killProcess(android.os.Process.myPid());
    }

    /** For a game whose native code ends its process itself right after telling Java (a JNI exit
     *  callback, then exit()): the record and, for a clean exit, the launcher, which starts next at
     *  once when it is given and ready (the game's own "switch game"; null: the launcher itself).
     *  The process is not killed here, so Android reports the game's own exit status. Any thread. */
    public void exiting(int code, String next) {
        State.put(activity, State.launch(distribution.id), "exit", Integer.toString(code));
        if (code == 0) openLauncher(activity, next != null ? next : distribution.id, next != null);
    }

    /** The launcher, from the game (a menu item, or after the game ends). */
    public static void openLauncher(Activity activity, String distribution) { openLauncher(activity, distribution, false); }

    /** The launcher, from the game; play: start that distribution at once, as its Play button would
     *  (a game's own "switch game" menu), when it can start, else the launcher shows what it lacks. */
    public static void openLauncher(Activity activity, String distribution, boolean play) {
        activity.startActivity(new Intent(activity, LauncherActivity.class)
            .putExtra(LauncherActivity.EXTRA_SHOW, true).putExtra(EXTRA_DISTRIBUTION, distribution)
            .putExtra(EXTRA_PLAY, play)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK));
    }

    /** The distributions this build can start now, their files in place, in port.json's order: what a
     *  game's own "switch game" menu offers. */
    public static List<String> ready(Context context) {
        Spec spec = Spec.get(context);
        List<String> ids = new ArrayList<>();
        for (Spec.Distribution d : spec.distributions) if (present(context, d) && Install.ready(context, spec, d)) ids.add(d.id);
        return ids;
    }

    /* ------------------------------------------- an earlier launcher's settings */

    /** For PortHooks.migrate: choices an earlier launcher of the game kept, named as the base names
     *  them: part folders ("part.<distribution>.<part>"), options ("option.<key>"), opening videos
     *  ("intro.<distribution>": "1" skips them), "renderer.<distribution>" and "last" (the selected
     *  distribution). Only what the player has not chosen here yet is taken; returns the keys taken. */
    public static List<String> adopt(Context context, Map<String, String> choices) { return adopt(State.folder(context), choices); }

    static List<String> adopt(File dir, Map<String, String> choices) {
        List<String> taken = new ArrayList<>();
        if (choices == null || choices.isEmpty()) return taken;
        State.update(dir, State.CHOICES, values -> {
            for (Map.Entry<String, String> e : choices.entrySet()) {
                String key = e.getKey(), value = e.getValue();
                if (key == null || value == null || !ADOPTABLE.matcher(key).matches() || values.containsKey(key)) continue;
                values.setProperty(key, value);
                taken.add(key);
            }
        });
        return taken;
    }

    /** The game's PortHooks.migrate, once per process, before the player's choices are read. */
    static synchronized void migrate(Context context, PortHooks hooks) {
        if (migrated) return;
        if (Spec.get(context).allFilesAccess && !Storage.allFiles(context)) return;
        migrated = true;
        try {
            hooks.migrate(context);
        } catch (RuntimeException e) {
            android.util.Log.w("Launcher", "hooks migrate: " + e, e);
        }
    }

    static synchronized boolean migrationPending() { return !migrated; }

    /* ------------------------------------------------------- the launcher */

    /** This build: a launch record of another build (before an update) says nothing about this one. */
    static String build(Context context) {
        try {
            android.content.pm.PackageInfo info = context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
            return (Build.VERSION.SDK_INT >= 28 ? info.getLongVersionCode() : info.versionCode) + ":" + info.lastUpdateTime;
        } catch (android.content.pm.PackageManager.NameNotFoundException e) {
            return "";
        }
    }

    /** Whether this build declares the distribution's activity. Asked of the package manager: loading
     *  the class here would run its static initialiser (the game's native library) in the
     *  launcher's process. */
    static boolean present(Context context, Spec.Distribution d) {
        try {
            context.getPackageManager().getActivityInfo(new ComponentName(context.getPackageName(), d.activity), 0);
            return true;
        } catch (PackageManager.NameNotFoundException e) {
            return false;
        }
    }

    /** Why the game refused the last start of this build, in its own words; null if it did not. */
    static String refusal(Context context, Spec.Distribution d) {
        return refusal(State.read(context, State.launch(d.id)), build(context));
    }

    static String refusal(Properties launch, String build) {
        if (!build.equals(launch.getProperty("build")) || "1".equals(launch.getProperty("reached"))) return null;
        String reason = launch.getProperty("failed", "");
        return reason.isEmpty() ? null : reason;
    }

    /** The record a start leaves before the game's activity runs (Launch.start). */
    static void recordStart(File dir, String distribution, String build, String renderer) {
        State.update(dir, State.launch(distribution), values -> {
            values.clear();
            values.setProperty("build", build);
            values.setProperty("started", "1");
            values.setProperty("time", Long.toString(System.currentTimeMillis()));
            if (renderer != null) values.setProperty("renderer", renderer);
        });
    }

    /** Records and starts a distribution. */
    static void start(Activity launcher, Spec.Distribution d, String renderer, PortHooks hooks) {
        if (!present(launcher, d)) throw new ActivityNotFoundException(d.activity);
        recordStart(State.folder(launcher), d.id, build(launcher), renderer);
        State.put(launcher, State.CHOICES, "last", d.id);
        Intent intent = new Intent().setClassName(launcher.getPackageName(), d.activity).putExtra(EXTRA_DISTRIBUTION, d.id);
        if (renderer != null && !renderer.isEmpty()) intent.putExtra(EXTRA_RENDERER, renderer);
        if (d.intro) intent.putExtra(EXTRA_SKIP_INTRO, "1".equals(State.get(launcher, State.CHOICES, "intro." + d.id, d.introDefault ? "1" : "0")));
        hooks.prepare(launcher, d.id, intent);
        launcher.startActivity(intent);
    }

    /** Whether one of this app's tasks still shows the distribution's game and its process lives: a
     *  game that ended its process itself (a native exit), crashed or was killed for memory leaves
     *  its task in the recent apps, which would only start it anew. */
    static boolean running(Context context, Spec.Distribution d) {
        ActivityManager manager = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
        try {
            String process = process(context, d);
            if (process != null && !alive(manager, process)) return false;
            for (ActivityManager.AppTask task : manager.getAppTasks()) {
                ActivityManager.RecentTaskInfo info = task.getTaskInfo();
                if ((info.baseActivity != null && d.activity.equals(info.baseActivity.getClassName()))
                        || (info.topActivity != null && d.activity.equals(info.topActivity.getClassName()))) return true;
            }
        } catch (RuntimeException e) {
            android.util.Log.w("Launcher", "tasks: " + e);
        }
        return false;
    }

    /** The process the distribution's activity runs in (the manifest's android:process). */
    static String process(Context context, Spec.Distribution d) {
        try {
            return context.getPackageManager().getActivityInfo(new ComponentName(context.getPackageName(), d.activity), 0).processName;
        } catch (PackageManager.NameNotFoundException e) {
            return null;
        }
    }

    static boolean alive(ActivityManager manager, String process) {
        List<ActivityManager.RunningAppProcessInfo> processes = manager.getRunningAppProcesses();
        if (processes != null) for (ActivityManager.RunningAppProcessInfo p : processes) if (process.equals(p.processName)) return true;
        return false;
    }

    static void resume(Activity launcher, Spec.Distribution d) {
        ActivityManager manager = (ActivityManager) launcher.getSystemService(Context.ACTIVITY_SERVICE);
        for (ActivityManager.AppTask task : manager.getAppTasks()) {
            ActivityManager.RecentTaskInfo info = task.getTaskInfo();
            if ((info.baseActivity != null && d.activity.equals(info.baseActivity.getClassName()))
                    || (info.topActivity != null && d.activity.equals(info.topActivity.getClassName()))) {
                task.moveToFront();
                return;
            }
        }
    }

    /** How Android saw the game's last process end (Android 11+), for the launcher's note. */
    static String lastExit(Context context, Spec.Distribution d) {
        if (Build.VERSION.SDK_INT < 30) return null;
        Properties launch = State.read(context, State.launch(d.id));
        long started = State.getLong(launch, "time", 0);
        ActivityManager manager = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
        try {
            List<ApplicationExitInfo> exits = manager.getHistoricalProcessExitReasons(context.getPackageName(), 0, 8);
            for (ApplicationExitInfo exit : exits) {
                if (exit.getTimestamp() < started) break;
                if (exit.getProcessName() != null && exit.getProcessName().endsWith(":launcher")) continue;
                String reason;
                switch (exit.getReason()) {
                case ApplicationExitInfo.REASON_CRASH: case ApplicationExitInfo.REASON_CRASH_NATIVE: reason = "crash"; break;
                case ApplicationExitInfo.REASON_ANR: reason = "ANR"; break;
                case ApplicationExitInfo.REASON_LOW_MEMORY: reason = "low memory"; break;
                default: continue;
                }
                return reason + (exit.getDescription() != null ? ": " + exit.getDescription() : "");
            }
        } catch (RuntimeException e) {
            android.util.Log.w("Launcher", "exit reasons: " + e);
        }
        return null;
    }
}
