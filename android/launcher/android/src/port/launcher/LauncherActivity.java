package port.launcher;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.res.AssetManager;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.provider.DocumentsContract;
import android.text.InputType;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;

/** The game's launcher: its distributions and their files (a folder, a ZIP to unpack or to play
 *  from), the renderer, options, textures, unneeded files, updates and the port's version. Built
 *  from port.json; the game's own code joins through PortHooks and Launch. */
public final class LauncherActivity extends Activity {
    static final String EXTRA_SHOW = "launcher.show";
    static volatile boolean visible;
    private static final int ASK_FOLDER = 1, ASK_ZIP = 2, ASK_TARGET = 3, ASK_PERMISSION = 4, ASK_DRIVER = 5, ASK_GOG = 6, ASK_GOG_TARGET = 7;
    /** startTextures: the originals a conversion replaced go (TextureBackend.removeOriginals). */
    private static final int TEX_REMOVE_ORIGINALS = -1;
    /** How often the renderer card looks again while the driver check runs. */
    private static final long PROBE_POLL_MS = 400;

    private interface Done<T> { void accept(T value); }

    private final Handler handler = new Handler(Looper.getMainLooper());
    private Ui ui;
    private Spec spec;
    private PortHooks hooks;
    private Spec.Distribution selected, pendingPlay;
    /** The edition whose folder picker is open, including across permission/rotation returns. */
    private String folderDistribution;
    private boolean folderPermissionPending;
    private String gogSetup, gogDistribution;
    private Gpu gpu;
    private String busy;
    private int busySection = Texts.GAME_FILES;
    private boolean filesExpanded, texturesExpanded;
    private String promptedFiles;
    private boolean checking, touching, refreshPending;
    private boolean initializing = true, autoLaunchPending, playRequestedPending, finishAfterLaunch;
    private TextureBackend textures;
    private TextureBackend.Scan textureScan;
    private boolean textureScanning;
    private long textureEpoch;
    private String textureSource;
    private volatile String lastError = "";
    private Object backCallback;
    /** A job waiting for the answer to the notification permission, asked just before it starts. */
    private Work.Job pendingJob;

    /* An archive read and waiting for the player's decision (or a target folder). */
    private Zip pendingZip;
    private Uri pendingUri;
    private File pendingFile;
    private List<Install.ArchivePart> pendingPlan;

    private LinearLayout main, side, permissions, distributions, files, renderer, options, texturesBox, space, update, about, work;
    private final Map<Integer, TextView> notes = new HashMap<>();
    private final Map<Integer, LinearLayout> notices = new HashMap<>();
    private TextView workTitle, workText, workStop;
    private ProgressBar workBar;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        spec = Spec.get(this);
        hooks = PortHooks.of(this);
        String last = State.get(this, State.CHOICES, "last", "");
        lastError = State.get(this, State.CHOICES, "lastError", "");
        String requested = getIntent().getStringExtra(Launch.EXTRA_DISTRIBUTION);
        selected = spec.distribution(requested != null ? requested : last);
        if (selected == null) selected = spec.distributions.get(0);
        autoLaunchPending = state == null && Work.current == null;
        playRequestedPending = state == null && getIntent().getBooleanExtra(Launch.EXTRA_PLAY, false);
        ui = new Ui(this);
        if (state != null) {
            filesExpanded = state.getBoolean("filesExpanded");
            promptedFiles = state.getString("promptedFiles");
            texturesExpanded = state.getBoolean("texturesExpanded");
            lastError = state.getString("lastError", lastError);
            folderDistribution = state.getString("folderDistribution");
            folderPermissionPending = state.getBoolean("folderPermissionPending");
            gogSetup = state.getString("gogSetup");
            gogDistribution = state.getString("gogDistribution");
        }
        build();
        if (Build.VERSION.SDK_INT >= 33) {
            android.window.OnBackInvokedCallback back = this::finish;
            backCallback = back;
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT, back);
        }
        Work.WorkService.channel(this);
        initialize(requested == null);
        background(() -> Gpu.get(this), found -> {
            gpu = found;
            if (!launchWhenReady()) refresh(Texts.PLAY, Texts.RENDERER, Texts.TEXTURES);
        }, null);
        if (Updates.due(this)) checkUpdates(false);
    }

    private void initialize(boolean useMigratedSelection) {
        initializing = true;
        note(Texts.GAME_FILES, Texts.t(this, Texts.CHECKING), false);
        Spec.Distribution initial = selected;
        background(() -> {
            Launch.migrate(this, hooks);
            boolean interrupted = !Work.busy() && recover();
            if (!Work.busy()) Install.ensureUserFolders(this, spec);
            return interrupted;
        }, interrupted -> {
            initializing = false;
            if (selected == initial && useMigratedSelection && !playRequestedPending) {
                Spec.Distribution migrated = spec.distribution(State.get(this, State.CHOICES, "last", ""));
                if (migrated != null) selected = migrated;
            }
            note(Texts.GAME_FILES, interrupted ? Texts.t(this, Texts.INTERRUPTED) : null, false);
            if (!launchWhenReady()) refresh();
        }, failure -> {
            initializing = false;
            autoLaunchPending = playRequestedPending = false;
            note(Texts.GAME_FILES, Texts.failure(this, Failure.of(failure)), true);
            refresh();
        });
    }

    @Override public void onUserInteraction() {
        super.onUserInteraction();
        autoLaunchPending = playRequestedPending = false;
    }

    @Override public boolean dispatchTouchEvent(MotionEvent event) {
        int action = event.getActionMasked();
        if (action == MotionEvent.ACTION_DOWN) touching = true;
        try {
            return super.dispatchTouchEvent(event);
        } finally {
            if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
                touching = false;
                boolean pending = refreshPending;
                refreshPending = false;
                if (pending && !finishAfterLaunch && !isFinishing() && !isDestroyed()) refresh();
            }
        }
    }

    private boolean launchWhenReady() {
        if (initializing || (gpu == null && needsGpu(selected))) return false;
        boolean automatic = autoLaunchPending;
        autoLaunchPending = false;
        if (automatic && autoLaunch()) return true;
        if (playRequestedPending) {
            playRequestedPending = false;
            playRequested();
        }
        return finishAfterLaunch || isFinishing();
    }

    private boolean idle() { return !finishAfterLaunch && !initializing && busy == null && !Work.busy(); }

    private boolean needsGpu(Spec.Distribution d) {
        return d.renderers.size() > 1 || (d.renderers.size() == 1 && spec.mode(d.renderers.get(0)).vulkanKind());
    }

    /** The game asked for this distribution (Launch.openLauncher with play: its own "switch game"
     *  menu): it starts as its Play button would start it, or the launcher shows what it lacks. */
    private void playRequested() {
        if (isFinishing() || isDestroyed() || busy != null || Work.busy()) return;
        if (Launch.running(this, selected)) {
            Launch.resume(this, selected);
            finish();
        } else if (Launch.present(this, selected) && ready(selected)) {
            play(selected);
        }
    }

    /** Redraws the renderer card until the driver check (process :probe) reports. */
    private final Runnable probeWatch = new Runnable() {
        @Override public void run() {
            boolean running = Probe.running(LauncherActivity.this);
            refresh(Texts.RENDERER, Texts.TEXTURES, Texts.PLAY);
            if (running) handler.postDelayed(this, PROBE_POLL_MS);
        }
    };

    /** The icon goes straight into the last game when this build's last start of it reached its
     *  first frame (port.json "autoLaunch"); a start that crashed opens the launcher instead. */
    private boolean autoLaunch() {
        if (!spec.autoLaunch || getIntent().getBooleanExtra(EXTRA_SHOW, false) || Work.busy()) return false;
        if (installationConflict() != null) return false;
        if (Launch.running(this, selected)) {
            /* The game runs (in a task of its own): back to it, no new start record, which would
               make its earlier first frame look missing. */
            Launch.resume(this, selected);
            finish();
            return true;
        }
        java.util.Properties launch = State.read(this, State.launch(selected.id));
        if (!"1".equals(launch.getProperty("reached")) || !Launch.build(this).equals(launch.getProperty("build"))) return false;
        if (!ready(selected) || (needsAllFiles() && !Storage.allFiles(this))) return false;
        try {
            Launch.start(this, selected, effectiveRenderer(selected), hooks);
        } catch (ActivityNotFoundException e) {
            return false;
        }
        finishAfterLaunch = true;
        return true;
    }

    private String effectiveRenderer(Spec.Distribution d) {
        if (d.renderers.isEmpty()) return null;
        if (!needsGpu(d)) return d.renderers.get(0);
        if (gpu == null) return null;
        List<Renderers.Status> statuses = Renderers.evaluate(this, spec, d, gpu, convertedTextures());
        String explicit = Renderers.explicitChoice(this, spec, d, hooks);
        return Renderers.effective(spec.defaultMode, statuses, explicit != null ? explicit : spec.defaultMode, explicit != null);
    }

    /** Files of a part the game also needs now, by its own settings (PortHooks.missing). */
    private List<String> extraMissing(Spec.Distribution d, Spec.Part p) {
        if (!Install.mount(this, d, p).isEmpty()) return new ArrayList<>();
        try {
            List<String> extra = hooks.missing(this, d.id, p.id, Install.folder(this, spec, d, p));
            return extra != null ? extra : new ArrayList<>();
        } catch (RuntimeException e) {
            android.util.Log.w("Launcher", "hooks missing: " + e);
            return new ArrayList<>();
        }
    }

    /** Everything the distribution's game checks before it starts is in place. */
    private boolean ready(Spec.Distribution d) {
        if (!Install.ready(this, spec, d)) return false;
        for (Spec.Part p : d.parts) if (!extraMissing(d, p).isEmpty()) return false;
        return true;
    }

    /** What the part lacks: port.json's required paths, then the game's own (PortHooks.missing). */
    private List<String> missing(Spec.Distribution d, Spec.Part p) {
        List<String> missing = new ArrayList<>(Install.missing(p, Install.folder(this, spec, d, p)));
        if (Install.ambiguous(this, spec, d, p)) missing.add(0, Texts.t(this, Texts.GROUP_PICK) + " " + Install.legacyFolders(this, spec, p));
        if (missing.isEmpty()) missing.addAll(extraMissing(d, p));
        return missing;
    }

    @Override protected void onResume() {
        super.onResume();
        finishAfterLaunch = false;
        if (ui == null) return;
        visible = true;
        if (!initializing && Launch.migrationPending() && (!spec.allFilesAccess || Storage.allFiles(this)))
            initialize(true);
        else refresh();
        resumeFolderPicker();
        if (Work.current != null) { handler.removeCallbacks(watcher); handler.post(watcher); }
    }

    @Override public void onWindowFocusChanged(boolean focused) {
        super.onWindowFocusChanged(focused);
        if (focused && ui != null) checkRenderer();
    }

    @Override protected void onPause() {
        touching = refreshPending = false;
        visible = false;
        super.onPause();
    }

    // A translucent game still needs this window beneath it until the launcher is actually hidden.
    @Override protected void onStop() {
        super.onStop();
        if (finishAfterLaunch) finish();
    }

    @Override protected void onSaveInstanceState(Bundle state) {
        super.onSaveInstanceState(state);
        state.putBoolean("filesExpanded", filesExpanded);
        state.putString("promptedFiles", promptedFiles);
        state.putBoolean("texturesExpanded", texturesExpanded);
        state.putString("lastError", lastError);
        state.putString("folderDistribution", folderDistribution);
        state.putBoolean("folderPermissionPending", folderPermissionPending);
        state.putString("gogSetup", gogSetup);
        state.putString("gogDistribution", gogDistribution);
    }

    @Override protected void onDestroy() {
        handler.removeCallbacks(watcher);
        handler.removeCallbacks(probeWatch);
        if (Build.VERSION.SDK_INT >= 33 && backCallback != null)
            getOnBackInvokedDispatcher().unregisterOnBackInvokedCallback((android.window.OnBackInvokedCallback) backCallback);
        if (!isChangingConfigurations()) dropPending();
        super.onDestroy();
    }

    /* ---------------------------------------------------------------- UI */

    private void build() {
        FrameLayout root = new FrameLayout(this);
        root.setBackground(ui.backdrop());
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        LinearLayout page = new LinearLayout(this) {
            @Override protected void onMeasure(int w, int h) {
                int max = ui.dp(ui.wide() ? 1100 : 640);
                if (MeasureSpec.getSize(w) > max) w = MeasureSpec.makeMeasureSpec(max, MeasureSpec.EXACTLY);
                super.onMeasure(w, h);
            }
        };
        page.setOrientation(LinearLayout.VERTICAL);
        page.setPadding(ui.dp(16), ui.dp(12), ui.dp(16), ui.dp(24));
        page.addView(header());
        LinearLayout columns = new LinearLayout(this);
        columns.setOrientation(ui.wide() ? LinearLayout.HORIZONTAL : LinearLayout.VERTICAL);
        main = column();
        side = ui.wide() ? column() : main;
        if (ui.wide()) {
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, -2, 1);
            columns.addView(main, lp);
            lp = new LinearLayout.LayoutParams(0, -2, 1);
            lp.leftMargin = ui.dp(16);
            columns.addView(side, lp);
        } else {
            columns.addView(main, new LinearLayout.LayoutParams(-1, -2));
        }
        page.addView(columns);
        update = holder(main);
        permissions = holder(main);
        work = column();
        workTitle = ui.heading("");
        work.addView(workTitle);
        workBar = ui.progress();
        work.addView(workBar, new LinearLayout.LayoutParams(-1, ui.dp(8)));
        workText = ui.label("", 13, ui.text);
        work.addView(workText);
        workStop = ui.button(Texts.t(this, Texts.STOP), Ui.SECONDARY, this::askStop);
        work.addView(ui.buttons(workStop));
        work.setVisibility(View.GONE);
        distributions = holder(main);
        files = holder(main);
        renderer = holder(side);
        options = holder(side);
        texturesBox = holder(side);
        space = holder(side);
        about = holder(side);
        scroll.addView(page, new FrameLayout.LayoutParams(-1, -2, Gravity.CENTER_HORIZONTAL));
        root.addView(scroll, new FrameLayout.LayoutParams(-1, -1));
        setContentView(root);
        ui.edgeToEdge(root);
    }

    private LinearLayout column() {
        LinearLayout c = new LinearLayout(this);
        c.setOrientation(LinearLayout.VERTICAL);
        return c;
    }

    private LinearLayout holder(LinearLayout parent) {
        LinearLayout h = column();
        parent.addView(h, new LinearLayout.LayoutParams(-1, -2));
        return h;
    }

    private TextView message(int section) {
        TextView view = notes.get(section);
        if (view == null) {
            view = ui.label("", 14, ui.accent);
            view.setVisibility(View.GONE);
            view.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
            notes.put(section, view);
        }
        return view;
    }

    private static void attach(LinearLayout parent, View view) {
        if (view.getParent() != null) ((ViewGroup) view.getParent()).removeView(view);
        parent.addView(view);
    }

    private LinearLayout notice(int section) {
        LinearLayout box = notices.get(section);
        if (box == null) {
            box = column();
            box.addView(message(section));
            notices.put(section, box);
        }
        return box;
    }

    private String textureState() {
        if (textureScan == null || textureScanning || !textureSourceKey().equals(textureSource)) return Texts.t(this, Texts.CHECKING);
        if (textureScan.failure != null) return Texts.t(this, Texts.TEX_CHECK_FAILED);
        return textureScan.converted == 0 ? Texts.t(this, Texts.TEX_ORIGINALS)
            : Texts.fmt(this, Texts.TEX_STATUS, textureScan.converted == TextureBackend.ASTC ? "ASTC" : "ETC2");
    }

    /** Status stays outside the folding body, so progress and results remain visible. */
    private LinearLayout section(LinearLayout parent, int title) {
        LinearLayout card = ui.card(parent);
        boolean expanded = title == Texts.GAME_FILES ? filesExpanded : texturesExpanded;
        boolean folded = title == Texts.GAME_FILES || title == Texts.TEXTURES;
        if (folded) {
            Boolean dxt = title == Texts.TEXTURES ? dxtSupport() : null;
            String support = title != Texts.TEXTURES ? null : Texts.t(this,
                dxt == null ? Texts.TEX_DXT_UNKNOWN : dxt ? Texts.TEX_DXT_YES : Texts.TEX_DXT_NO);
            card.addView(ui.foldHeading(Texts.t(this, title), support,
                dxt == null ? ui.muted : dxt ? ui.good : ui.error, expanded, on -> {
                    if (title == Texts.GAME_FILES) filesExpanded = on;
                    else texturesExpanded = on;
                    refresh(title);
                }));
        } else card.addView(ui.heading(Texts.t(this, title)));
        if (title == Texts.TEXTURES) card.addView(ui.label(textureState(), 13, ui.muted));
        LinearLayout body = column();
        Work.Job job = Work.current;
        boolean working = job != null && !job.finished && job.section == title;
        body.setVisibility((!folded || expanded) && !working && !(busy != null && busySection == title) ? View.VISIBLE : View.GONE);
        card.addView(body);
        attach(card, notice(title));
        if (working) {
            attach(card, work);
            work.setVisibility(View.VISIBLE);
        }
        return body;
    }

    private Boolean dxtSupport() {
        if (gpu == null) return null;
        Spec.Mode mode = spec.mode(effectiveRenderer(selected));
        if (mode != null && mode.vulkanKind()) {
            Map<String, String> report = Probe.report(this);
            String bc = report == null ? null : report.get(("turnip".equals(mode.kind) ? "turnip" : "stock") + ".bc");
            return bc == null ? null : "111".equals(bc);
        }
        return gpu.probed ? gpu.s3tc : null;
    }

    private View header() {
        LinearLayout head = new LinearLayout(this);
        head.setGravity(Gravity.CENTER_VERTICAL);
        ImageView icon = new ImageView(this);
        icon.setImageDrawable(getApplicationInfo().loadIcon(getPackageManager()));
        head.addView(icon, new LinearLayout.LayoutParams(ui.dp(60), ui.dp(60)));
        LinearLayout names = column();
        names.setPadding(ui.dp(14), 0, 0, 0);
        TextView title = ui.label(Texts.of(this, spec.title), 25, ui.text);
        title.setTypeface(ui.titleFont);
        names.addView(title);
        String subtitle = Texts.of(this, spec.subtitle);
        if (!subtitle.isEmpty()) names.addView(ui.label(subtitle, 14, ui.muted));
        names.addView(ui.label(versionLine(), 12, ui.accent));
        head.addView(names, new LinearLayout.LayoutParams(0, -2, 1));
        return head;
    }

    /** "v0.7.0-touch (10) · build 2d965db7": what the player reports. */
    private String versionLine() {
        StringBuilder line = new StringBuilder(Texts.fmt(this, Texts.VERSION, Updates.installedName(this)))
            .append(" (").append(Updates.installedCode(this)).append(')');
        String commit = spec.buildText("commit");
        if (!commit.isEmpty()) line.append(" · ").append(Texts.fmt(this, Texts.BUILD, commit));
        return line.toString();
    }

    private void refresh() {
        refresh(Texts.PERM_FILES, Texts.PLAY, Texts.GAME_FILES, Texts.RENDERER, Texts.OPTIONS,
            Texts.TEXTURES, Texts.SPACE, Texts.UPDATE_AVAILABLE, Texts.ABOUT);
    }

    private LinearLayout group(int section) {
        switch (section) {
        case Texts.PERM_FILES: return permissions;
        case Texts.PLAY: return distributions;
        case Texts.GAME_FILES: return files;
        case Texts.RENDERER: return renderer;
        case Texts.OPTIONS: return options;
        case Texts.TEXTURES: return texturesBox;
        case Texts.SPACE: return space;
        case Texts.UPDATE_AVAILABLE: return update;
        default: return about;
        }
    }

    private void refresh(int... sections) {
        if (ui == null) return;
        if (touching) { refreshPending = true; return; }
        boolean idle = idle();
        for (int section : sections) {
            View focused = group(section).findFocus();
            Object tag = focused != null ? focused.getTag() : null;
            switch (section) {
            case Texts.PERM_FILES: refreshPermissions(); break;
            case Texts.PLAY: refreshDistributions(idle); break;
            case Texts.GAME_FILES: {
                refreshFiles(idle);
                String conflict = idle ? installationConflict() : null;
                if (conflict != null) note(conflict, true);
                break;
            }
            case Texts.RENDERER: refreshRenderer(); break;
            case Texts.OPTIONS: refreshOptions(); break;
            case Texts.TEXTURES: refreshTextures(idle); break;
            case Texts.SPACE: refreshSpace(idle); break;
            case Texts.UPDATE_AVAILABLE: refreshUpdate(); break;
            case Texts.ABOUT: refreshAbout(); break;
            }
            if (tag != null) {
                View next = group(section).findViewWithTag(tag);
                if (next != null) next.requestFocus();
            }
        }
    }

    /** Check every configured distribution before an automatic start can hide a conflict. */
    private String installationConflict() {
        for (Spec.Distribution d : spec.distributions) for (Spec.Part p : d.parts) {
            File folder = Install.folder(this, spec, d, p);
            if (!folder.isDirectory()) continue;
            String problem = hooks.installationProblem(this, d.id, p.id, folder);
            if (problem != null) return problem;
        }
        return null;
    }

    private void note(String text, boolean error) {
        note(Texts.GAME_FILES, text, error);
    }

    private void note(int section, String text, boolean error) {
        TextView view = message(section);
        boolean unchanged = (text == null ? view.getVisibility() == View.GONE : text.contentEquals(view.getText()))
            && view.getCurrentTextColor() == (error ? ui.error : ui.accent);
        view.setVisibility(text == null ? View.GONE : View.VISIBLE);
        view.setText(text);
        view.setTextColor(error ? ui.error : ui.accent);
        LinearLayout box = notice(section);
        if (unchanged) return;
        while (box.getChildCount() > 1) box.removeViewAt(1);
        if (!error || text == null) return;
        if (!text.equals(lastError)) {
            lastError = text;
            background(() -> State.update(this, State.CHOICES, values -> values.setProperty("lastError", lastError)), saved -> { }, null);
        }
        List<TextView> actions = new ArrayList<>();
        if (section == Texts.GAME_FILES) {
            actions.add(recoveryButton(Texts.FOLDER, () -> pickFolder(selected)));
            actions.add(recoveryButton(Texts.OTHER_ARCHIVE, () -> pick(Pickers.ZIP, ASK_ZIP, null)));
        } else if (section == Texts.TEXTURES) {
            actions.add(recoveryButton(Texts.RETRY_CHECK, this::rescanTextures));
        } else if (section == Texts.SPACE) {
            actions.add(recoveryButton(Texts.RETRY_CHECK, this::scanCleanup));
        } else if (section == Texts.ABOUT) {
            if (text.equals(Texts.t(this, Texts.E_CLIPBOARD)))
                actions.add(ui.button(Texts.t(this, Texts.COPY_DIAGNOSTICS), Ui.SECONDARY, this::copyDiagnostics));
            else if (spec.updates) actions.add(ui.button(Texts.t(this, Texts.RETRY_CHECK), Ui.SECONDARY, () -> checkUpdates(true)));
        }
        if (!actions.isEmpty()) box.addView(ui.buttons(actions.toArray(new TextView[0])));
    }

    private TextView recoveryButton(int title, Runnable action) {
        return ui.button(Texts.t(this, title), Ui.SECONDARY, () -> { if (idle()) action.run(); });
    }

    private void rescanTextures() {
        if (!idle() || textureScanning) return;
        textureScan = null;
        note(Texts.TEXTURES, null, false);
        refresh(Texts.TEXTURES, Texts.RENDERER);
    }

    private void error(String text) {
        note(text, true);
    }

    private void setBusy(String what) {
        setBusy(what == null ? busySection : Texts.GAME_FILES, what);
    }

    private void setBusy(int section, String what) {
        busySection = section;
        busy = what;
        note(section, what, false);
        refresh(Texts.PLAY, Texts.GAME_FILES, Texts.TEXTURES, Texts.SPACE);
        if (section == Texts.RENDERER) refresh(Texts.RENDERER);
    }

    /** Runs work off the UI thread and hands its result (or failure) back to it. */
    private <T> void background(Callable<T> work, Done<T> done, Done<Throwable> failed) {
        new Thread(() -> {
            T result = null;
            Throwable error = null;
            try { result = work.call(); } catch (Throwable e) { error = e; }
            final T value = result;
            final Throwable problem = error;
            handler.post(() -> {
                if (isFinishing() || isDestroyed()) return;
                if (problem == null) done.accept(value);
                else if (failed != null) failed.accept(problem);
                else android.util.Log.w("Launcher", "background: " + problem, problem);
            });
        }, "launcher-ui").start();
    }

    /* ------------------------------------------------------- permissions */

    private boolean needsAllFiles() {
        if (!spec.allFilesAccess) return false;
        for (Spec.Distribution d : spec.distributions)
            for (Spec.Part p : d.parts) if (!Storage.own(this, Install.folder(this, spec, d, p))) return true;
        return false;
    }

    private void refreshPermissions() {
        permissions.removeAllViews();
        if (needsAllFiles() && !Storage.allFiles(this)) {
            LinearLayout card = ui.card(permissions);
            card.addView(ui.label(Texts.t(this, Texts.PERM_FILES), 15, ui.text));
            card.addView(ui.buttons(ui.button(Texts.t(this, Texts.ALLOW), Ui.SECONDARY, () -> Storage.requestAllFiles(this, ASK_PERMISSION))));
        }
        if (spec.localNetwork && !Storage.granted(this, Storage.LOCAL_NETWORK)) {
            LinearLayout card = ui.card(permissions);
            card.addView(ui.label(Texts.t(this, Texts.PERM_LAN), 15, ui.text));
            card.addView(ui.buttons(ui.button(Texts.t(this, Texts.ALLOW), Ui.SECONDARY,
                () -> requestPermissions(new String[] {Storage.LOCAL_NETWORK}, ASK_PERMISSION))));
        }
    }

    @Override public void onRequestPermissionsResult(int request, String[] names, int[] results) {
        super.onRequestPermissionsResult(request, names, results);
        Spec.Distribution next = pendingPlay;
        Work.Job job = pendingJob;
        pendingPlay = null;
        pendingJob = null;
        /* The start or the work goes on whatever the answer. */
        if (job != null) runJob(job);
        else if (next != null) play(next);
        else { refresh(); resumeFolderPicker(); }
    }

    /** Whether a permission is still to be asked once per install (the system's dialog then follows
     *  the launcher's own explanation): the local network for LAN games, notifications for long work. */
    private boolean unasked(String permission, String key) {
        return Storage.known(this, permission) && !Storage.granted(this, permission)
            && !"1".equals(State.get(this, State.CHOICES, key, "0"));
    }

    private void askOnce(String permission, String key) {
        if (!unasked(permission, key)) return;
        State.put(this, State.CHOICES, key, "1");
        requestPermissions(new String[] {permission}, ASK_PERMISSION);
    }

    /** Notifications are asked right before the first long work, from its confirmation. */
    private boolean notificationsUnasked() {
        return Build.VERSION.SDK_INT >= 33 && unasked(Storage.NOTIFICATIONS, "asked.notifications");
    }

    /** The confirmation's text, with the reason for the notification request that follows it. */
    private String withNotificationNote(String text) {
        return notificationsUnasked() ? text + "\n\n" + Texts.t(this, Texts.PERM_NOTIFY) : text;
    }

    /* ----------------------------------------------------- distributions */

    private void refreshDistributions(boolean idle) {
        distributions.removeAllViews();
        for (Spec.Distribution d : spec.distributions) {
            LinearLayout card = ui.card(distributions);
            boolean chosen = d == selected && spec.distributions.size() > 1;
            TextView title = ui.label(Texts.of(this, d.title) + (d.version.isEmpty() ? "" : "  " + d.version), 18,
                chosen ? ui.accent : ui.text);
            title.setTypeface(ui.bold);
            card.addView(title);
            if (d == selected) attach(card, notice(Texts.PLAY));
            /* By the package manager: loading the game's class here would load its native library. */
            boolean present = Launch.present(this, d);
            boolean access = !needsAllFiles() || Storage.allFiles(this);
            boolean ready = !initializing && present && access && ready(d);
            boolean running = Launch.running(this, d);
            String status;
            if (!present) status = Texts.t(this, Texts.NOT_IN_BUILD);
            else if (initializing || (gpu == null && needsGpu(d))) status = Texts.t(this, Texts.CHECKING);
            else if (ready) status = Texts.t(this, Texts.READY);
            else if (!access) status = Texts.t(this, Texts.NEEDS_FILES_ACCESS);
            else status = Texts.fmt(this, Texts.MISSING, missingSummary(d)) + "\n" + Texts.t(this, Texts.CHOOSE_GAME_FILES);
            card.addView(ui.label(status, 13, ready ? ui.good : ui.muted));
            String refused = running ? null : Launch.refusal(this, d);
            String failed = running ? null : Renderers.failed(this, d);
            if (refused != null) {
                card.addView(ui.label(Texts.fmt(this, Texts.REFUSED, refused), 13, ui.error));
            } else if (failed != null) {
                String exit = Launch.lastExit(this, d);
                String because = exit != null ? Texts.fmt(this, Texts.LAST_EXIT, exit) : "";
                Spec.Mode mode = spec.mode(failed), fallback = spec.mode(spec.defaultMode);
                card.addView(ui.label(failed.isEmpty() || failed.equals(spec.defaultMode)
                    ? Texts.fmt(this, Texts.N_FAILED_DEFAULT, because)
                    : Texts.fmt(this, Texts.N_FAILED, mode != null ? mode.title : failed, because,
                        fallback != null ? fallback.title : spec.defaultMode), 13, ui.error));
            }
            TextView play = ui.button(Texts.t(this, running ? Texts.RETURN : Texts.PLAY), Ui.PRIMARY, d.theme,
                () -> { if (running && !initializing) Launch.resume(this, d); else play(d); });
            card.addView(ui.buttons(play));
            Ui.enable(play, (initializing && present && access && busy == null && !Work.busy()) ||
                (idle && (ready || running) && (running || gpu != null || !needsGpu(d))));
            if (ready || running) ui.attention(play, true);
            if (idle && spec.distributions.size() > 1) card.setOnClickListener(v -> {
                if (selected != d) {
                    note(Texts.PLAY, null, false);
                    textureScan = null;
                    note(Texts.TEXTURES, null, false);
                }
                selected = d;
                refresh(Texts.PLAY, Texts.GAME_FILES, Texts.RENDERER, Texts.OPTIONS, Texts.TEXTURES, Texts.SPACE);
            });
        }
    }

    private String missingSummary(Spec.Distribution d) {
        List<String> names = new ArrayList<>();
        for (Spec.Part p : d.parts) {
            if (!Install.mount(this, d, p).isEmpty()) continue;
            List<String> missing = missing(d, p);
            if (missing.isEmpty()) continue;
            String list = missing.size() > 3 ? String.join(", ", missing.subList(0, 3)) + "…" : String.join(", ", missing);
            names.add(d.parts.size() > 1 ? Texts.of(this, p.title) + " (" + list + ")" : list);
        }
        return String.join("; ", names);
    }

    private void play(Spec.Distribution d) {
        if (initializing && busy == null && !Work.busy()) {
            selected = d;
            autoLaunchPending = false;
            playRequestedPending = true;
            return;
        }
        if (!idle()) return;
        if (gpu == null && needsGpu(d)) {
            note(Texts.PLAY, Texts.t(this, Texts.R_CHECKING), false);
            return;
        }
        if (selected != d) {
            note(Texts.PLAY, null, false);
            selected = d;
            textureScan = null;
            refresh(Texts.PLAY, Texts.GAME_FILES, Texts.RENDERER, Texts.OPTIONS, Texts.TEXTURES, Texts.SPACE);
        }
        if (needsAllFiles() && !Storage.allFiles(this)) { Storage.requestAllFiles(this, ASK_PERMISSION); return; }
        if (spec.localNetwork && unasked(Storage.LOCAL_NETWORK, "asked.lan")) { explainLan(d); return; }
        if (Probe.running(this) && probeDecides(d)) {
            /* A few seconds at most: the driver check decides whether the chosen DXVK mode runs. */
            setBusy(Texts.PLAY, Texts.t(this, Texts.R_CHECKING));
            handler.postDelayed(() -> { if (!isFinishing()) { setBusy(null); play(d); } }, PROBE_POLL_MS);
            return;
        }
        try {
            Launch.start(this, d, effectiveRenderer(d), hooks);
            finishAfterLaunch = true;
        } catch (ActivityNotFoundException e) {
            note(Texts.PLAY, Texts.t(this, Texts.NOT_IN_BUILD), true);
        }
    }

    /** Whether the renderer this start would use waits for the driver check. */
    private boolean probeDecides(Spec.Distribution d) {
        Spec.Mode mode = spec.mode(Renderers.chosen(this, spec, d, hooks));
        return mode != null && mode.vulkanKind() && d.renderers.contains(mode.id);
    }

    /** Before the system's "Nearby devices" request on Android 17: what the local network is for.
     *  Asked once; "Not now" and the system's answer both go on to the game. */
    private void explainLan(Spec.Distribution d) {
        ui.show(ui.dialog().setTitle(Texts.t(this, Texts.LAN_TITLE)).setMessage(Texts.t(this, Texts.LAN_WHY))
            .setPositiveButton(Texts.t(this, Texts.CONTINUE), (dlg, w) -> {
                State.put(this, State.CHOICES, "asked.lan", "1");
                pendingPlay = d;
                requestPermissions(new String[] {Storage.LOCAL_NETWORK}, ASK_PERMISSION);
            })
            .setNegativeButton(Texts.t(this, Texts.NOT_NOW), (dlg, w) -> {
                State.put(this, State.CHOICES, "asked.lan", "1");
                play(d);
            }));
    }

    /* -------------------------------------------------------- game files */

    private boolean allFixed() {
        for (Spec.Part p : selected.parts) if (!p.fixed) return false;
        return true;
    }

    private Object folderTitle(Spec.Distribution distribution) {
        if (distribution.parts.size() == 1 && distribution.parts.get(0).folderTitle != null)
            return distribution.parts.get(0).folderTitle;
        return distribution.title;
    }

    private void refreshFiles(boolean idle) {
        files.removeAllViews();
        boolean needsFiles = !initializing && Launch.present(this, selected) && !ready(selected) && !Launch.running(this, selected);
        if (!initializing) {
            if (needsFiles && !selected.id.equals(promptedFiles)) filesExpanded = true;
            else if (!needsFiles && promptedFiles != null) filesExpanded = false;
            promptedFiles = needsFiles ? selected.id : null;
        }
        LinearLayout card = section(files, Texts.GAME_FILES);
        if (!filesExpanded || initializing) return;
        java.util.Set<String> shown = new java.util.HashSet<>();
        for (Spec.Distribution d : spec.distributions) for (Spec.Part p : d.parts) {
            if (!shown.add(Install.key(d, p))) continue;
            File folder = Install.folder(this, spec, d, p);
            String mount = Install.mount(this, d, p);
            List<String> missing = mount.isEmpty() ? missing(d, p) : new ArrayList<>();
            if (spec.distributions.size() > 1 || d.parts.size() > 1)
                card.addView(ui.label(Texts.of(this, p.folderTitle)
                    + (d.parts.size() > 1 ? " — " + Texts.of(this, p.title) : ""), 15, ui.text));
            /* The folder once; a fixed part says so without repeating it. */
            card.addView(ui.label(mount.isEmpty() ? folder.getPath() : Uri.decode(mount), 12, ui.muted));
            if (!missing.isEmpty()) {
                String list = missing.size() > 4 ? String.join(", ", missing.subList(0, 4)) + "…" : String.join(", ", missing);
                card.addView(ui.label(folder.isDirectory() ? Texts.fmt(this, Texts.MISSING, list) : Texts.t(this, Texts.NOT_FOUND_YET), 12, ui.error));
            }
            if (p.fixed && mount.isEmpty()) card.addView(ui.label(Texts.t(this, Texts.FIXED_HINT), 12, ui.muted));
            if (mount.isEmpty()) for (Map.Entry<String, Object> entry : p.userFolders.entrySet()) {
                if (entry.getValue() == null) continue;
                File content = Install.child(folder, entry.getKey());
                if (content == null) content = new File(folder, entry.getKey());
                card.addView(ui.label(Texts.of(this, entry.getValue()) + "\n" + content.getPath(), 12, ui.muted));
            }
        }
        String hint = Texts.of(this, spec.gameFilesHint);
        if (!hint.isEmpty()) card.addView(ui.label(hint, 13, ui.muted));
        boolean fixed = allFixed();
        TextView folder = ui.button(Texts.t(this, fixed ? Texts.IMPORT_FOLDER : Texts.FOLDER), Ui.SECONDARY,
            () -> pickFolder(selected));
        TextView archive = ui.button(Texts.t(this, fixed ? Texts.IMPORT_ARCHIVE : Texts.ARCHIVE), Ui.SECONDARY,
            () -> pick(Pickers.ZIP, ASK_ZIP, null));
        card.addView(ui.buttons(folder, archive));
        Ui.enable(folder, idle);
        Ui.enable(archive, idle);
        if (needsFiles) {
            ui.attention(folder, false);
            ui.attention(archive, false);
        }
        TextView retry = recoveryButton(Texts.RETRY_CHECK,
            () -> refresh(Texts.PERM_FILES, Texts.PLAY, Texts.GAME_FILES, Texts.TEXTURES, Texts.SPACE));
        card.addView(ui.buttons(retry));
        Ui.enable(retry, idle);
        if (!spec.gogInstaller.isEmpty()) {
            TextView gog = ui.button(Texts.t(this, Texts.GOG_IMPORT), Ui.SECONDARY,
                () -> pick(Pickers.GOG, ASK_GOG, android.os.Environment.getExternalStoragePublicDirectory(android.os.Environment.DIRECTORY_DOWNLOADS)));
            card.addView(ui.buttons(gog));
            card.addView(ui.label(Texts.t(this, Texts.GOG_HINT), 12, ui.muted));
            Ui.enable(gog, idle);
            if (needsFiles) ui.attention(gog, false);
        }
        int picker = Pickers.state(this);
        if (picker != Pickers.OK) {
            card.addView(ui.label(Texts.t(this, picker == Pickers.DISABLED ? Texts.PICKER_DISABLED_BUILTIN : Texts.PICKER_MISSING_BUILTIN),
                12, ui.muted));
            String name = Pickers.disabledPackage();
            if (picker == Pickers.DISABLED && name != null)
                card.addView(ui.buttons(ui.button(Texts.t(this, Texts.ENABLE), Ui.QUIET, () -> Pickers.openSettings(this, name))));
        }
    }

    private void pickFolder(Spec.Distribution distribution) {
        folderDistribution = distribution.id;
        selected = distribution;
        textureScan = null;
        refresh(Texts.PLAY, Texts.GAME_FILES, Texts.RENDERER, Texts.OPTIONS, Texts.TEXTURES, Texts.SPACE);
        folderPermissionPending = spec.allFilesAccess && !Storage.allFiles(this);
        if (folderPermissionPending) { Storage.requestAllFiles(this, ASK_PERMISSION); return; }
        File near = distribution.parts.isEmpty() ? spec.storageRoot()
            : Install.folder(this, spec, distribution, distribution.parts.get(0));
        pick(Pickers.FOLDER, ASK_FOLDER, near);
    }

    private void resumeFolderPicker() {
        if (!folderPermissionPending || !Storage.allFiles(this)) return;
        Spec.Distribution distribution = spec.distribution(folderDistribution);
        folderPermissionPending = false;
        if (distribution != null) pickFolder(distribution);
    }

    private void pick(int kind, int request, File near) {
        if (spec.allFilesAccess && !Storage.allFiles(this) && (kind == Pickers.FOLDER || kind == Pickers.GOG || Pickers.preferBuiltIn(this))) {
            Storage.requestAllFiles(this, ASK_PERMISSION);
            return;
        }
        if (!Pickers.pick(this, kind, request, near, kind == Pickers.GOG))
            note(request == ASK_DRIVER ? Texts.RENDERER : Texts.GAME_FILES, Texts.fmt(this, Texts.E_PICKER, "—"), true);
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        Uri uri = result == RESULT_OK && data != null ? data.getData() : null;
        String path = result == RESULT_OK && data != null ? data.getStringExtra(FileBrowserActivity.RESULT) : null;
        if (uri == null && path == null) {
            /* A picker that closed by itself: offer the built-in browser at once. */
            if (Pickers.instantCancel() && (request == ASK_FOLDER || request == ASK_ZIP || request == ASK_DRIVER))
                Pickers.pick(this, request == ASK_FOLDER ? Pickers.FOLDER : Pickers.ZIP, request, null, true);
            if (request == ASK_TARGET) dropPending();
            return;
        }
        Pickers.resetInstantCancels();
        if (request == ASK_FOLDER) chooseFolder(path != null ? new File(path) : Storage.treePath(uri));
        else if (request == ASK_ZIP) readArchive(uri, path != null ? new File(path) : null);
        else if (request == ASK_TARGET) unpackInto(path != null ? new File(path) : Storage.treePath(uri));
        else if (request == ASK_DRIVER) importDriver(uri, path != null ? new File(path) : null);
        else if (request == ASK_GOG) {
            if (path == null) error(Texts.t(this, Texts.GOG_HINT));
            else readGog(new File(path));
        }
        else if (request == ASK_GOG_TARGET) {
            File directory = path != null ? new File(path) : Storage.treePath(uri);
            Spec.Distribution distribution = spec.distribution(gogDistribution);
            if (directory == null || !directory.isDirectory() || distribution == null || gogSetup == null) {
                error(Texts.t(this, Texts.E_NO_PATH)); return;
            }
            File target = Install.target(directory, new File(distribution.parts.get(0).folder).getName());
            setBusy(Texts.t(this, Texts.GOG_READING));
            background(() -> Gog.inspect(this, new File(gogSetup)), info -> {
                setBusy(null); confirmGog(info, distribution, target);
            }, failure -> { setBusy(null); error(Texts.failure(this, Failure.of(failure))); });
        }
    }

    private void chooseFolder(File dir) {
        if (dir == null || !dir.isDirectory()) { error(Texts.t(this, Texts.E_NO_PATH)); return; }
        Spec.Distribution distribution = spec.distribution(folderDistribution);
        if (distribution == null) distribution = selected;
        final Spec.Distribution choosing = distribution;
        folderDistribution = null;
        setBusy(Texts.t(this, Texts.SEARCHING));
        background(() -> {
            List<Install.Found> found = Install.discover(spec.distributions, choosing, dir);
            for (Install.Found f : found) hooks.verifyInstallation(this, f.distribution.id, f.part.id, f.folder);
            return found;
        }, found -> {
            setBusy(null);
            selected = choosing;
            if (found.isEmpty()) {
                StringBuilder problem = new StringBuilder(Texts.fmt(this, Texts.NO_EDITION, Texts.of(this, choosing.title), dir.getPath()));
                for (Spec.Part part : choosing.parts) {
                    String conflict = hooks.installationProblem(this, choosing.id, part.id, dir);
                    if (conflict != null) { problem.append('\n').append(conflict); continue; }
                    List<String> missing = Install.missing(part, dir);
                    for (String extra : hooks.missing(this, choosing.id, part.id, dir)) if (!missing.contains(extra)) missing.add(extra);
                    if (!missing.isEmpty()) problem.append('\n').append(Texts.fmt(this, Texts.MISSING, String.join(", ", missing)));
                }
                error(problem.toString());
                return;
            }
            for (Install.Found f : found) {
                String problem = hooks.installationProblem(this, f.distribution.id, f.part.id, f.folder);
                if (problem != null) { error(problem); return; }
            }
            List<File> sources = new ArrayList<>(), targets = new ArrayList<>();
            List<List<Glob>> needed = new ArrayList<>();
            StringBuilder body = new StringBuilder();
            for (Install.Found f : found) {
                String problem = hooks.installationProblem(this, f.distribution.id, f.part.id, f.folder);
                if (problem != null) { refresh(); error(problem); return; }
                if (!f.part.fixed) { Install.choose(this, f.distribution, f.part, f.folder); continue; }
                File target = Install.folder(this, spec, f.distribution, f.part);
                if (sameFile(f.folder, target)) continue;
                sources.add(f.folder);
                targets.add(target);
                needed.add(f.part.needed);
                body.append(Texts.of(this, f.part.title)).append(": ").append(f.folder.getPath()).append(" → ").append(target.getPath()).append('\n');
            }
            refresh();
            if (sources.isEmpty()) { note(Texts.t(this, Texts.READY), false); return; }
            for (File t : targets) if (t.exists()) { body.append('\n').append(Texts.t(this, Texts.REPLACE)); break; }
            ui.show(ui.dialog().setTitle(Texts.t(this, Texts.IMPORT_TITLE)).setMessage(withNotificationNote(body.toString().trim()))
                .setPositiveButton(Texts.t(this, Texts.COPY), (dlg, w) -> startJob(new Install.CopyJob(this, sources, targets, needed)))
                .setNeutralButton(Texts.t(this, Texts.MOVE), (dlg, w) -> startJob(new Install.MoveJob(this, sources, targets)))
                .setNegativeButton(Texts.t(this, Texts.CANCEL), null));
        }, e -> { setBusy(null); error(Texts.failure(this, Failure.of(e))); });
    }

    private static boolean sameFile(File a, File b) {
        try { return a.getCanonicalPath().equals(b.getCanonicalPath()); } catch (IOException e) { return a.equals(b); }
    }

    private void readGog(File setup) {
        setBusy(Texts.t(this, Texts.GOG_READING));
        background(() -> Gog.inspect(this, setup), info -> {
            setBusy(null);
            List<Spec.Distribution> choices = Gog.distributions(info, spec);
            if (choices.isEmpty()) { error(Texts.t(this, Texts.GOG_NOT_FOUND)); return; }
            if (choices.size() == 1) { confirmGog(info, choices.get(0)); return; }
            String[] titles = new String[choices.size()];
            for (int i = 0; i < titles.length; ++i) titles[i] = Texts.of(this, choices.get(i).title) + " " + choices.get(i).version;
            ui.show(ui.dialog().setTitle(Texts.t(this, Texts.GOG_EDITION))
                .setItems(titles, (dlg, which) -> confirmGog(info, choices.get(which)))
                .setNegativeButton(Texts.t(this, Texts.CANCEL), null));
        }, failure -> { setBusy(null); error(Texts.failure(this, Failure.of(failure))); });
    }

    private void confirmGog(Gog.Info info, Spec.Distribution distribution) {
        Spec.Part part = distribution.parts.get(0);
        confirmGog(info, distribution, Install.folder(this, spec, distribution, part));
    }

    private void confirmGog(Gog.Info info, Spec.Distribution distribution, File target) {
        Spec.Part part = distribution.parts.get(0);
        gogSetup = info.setup.getAbsolutePath(); gogDistribution = distribution.id;
        String problem = hooks.installationProblem(this, distribution.id, part.id, target);
        String body = Texts.of(this, folderTitle(distribution)) + "\n" + info.setup.getPath()
            + "\n→ " + target.getPath() + "\n" + Texts.size(this, info.bytes) + "\n\n" + Texts.t(this, Texts.GOG_DESTINATION);
        if (problem != null) body += "\n\n" + problem;
        String[] existing = target.list();
        if (existing != null && existing.length > 0) body += "\n\n" + Texts.t(this, Texts.REPLACE);
        ui.show(ui.dialog().setTitle(Texts.t(this, Texts.GOG_IMPORT)).setMessage(withNotificationNote(body))
            .setPositiveButton(Texts.t(this, Texts.UNPACK), (dlg, which) -> {
                if (problem != null) { error(problem); return; }
                selected = distribution;
                startJob(new Gog.Job(this, info, distribution, target));
            }).setNeutralButton(Texts.t(this, Texts.CHOOSE_PART), (dlg, which) -> pick(Pickers.FOLDER, ASK_GOG_TARGET, target.getParentFile()))
            .setNegativeButton(Texts.t(this, Texts.CANCEL), null));
    }

    private void readArchive(Uri uri, File file) {
        dropPending();
        final ParcelFileDescriptor fd;
        try {
            fd = file != null ? ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)
                : getContentResolver().openFileDescriptor(uri, "r");
            if (fd == null) throw new IOException(String.valueOf(uri));
        } catch (IOException | RuntimeException e) {
            error(Texts.fmt(this, Texts.E_IO, e.getMessage()));
            return;
        }
        if (!Storage.seekable(fd)) {
            try { fd.close(); } catch (IOException ignored) { /* nothing to keep */ }
            error(Texts.t(this, Texts.E_REMOTE));
            return;
        }
        File path = file != null ? file : Storage.fileOf(uri, fd);
        setBusy(Texts.t(this, Texts.READING));
        background(() -> {
            Zip zip = new Zip(new ParcelFileDescriptor.AutoCloseInputStream(fd).getChannel());
            try {
                List<Install.ArchivePart> plan = Install.plan(zip, spec);
                if (plan.isEmpty()) throw new Failure(Failure.NOT_FOUND, null);
                return new Object[] {zip, plan};
            } catch (IOException | RuntimeException e) {
                zip.close();
                throw e;
            }
        }, read -> {
            setBusy(null);
            pendingZip = (Zip) read[0];
            @SuppressWarnings("unchecked") List<Install.ArchivePart> plan = (List<Install.ArchivePart>) read[1];
            pendingPlan = plan;
            pendingUri = uri;
            pendingFile = path;
            askImport();
        }, e -> {
            setBusy(null);
            try { fd.close(); } catch (IOException ignored) { /* closed with the archive */ }
            error(Texts.failure(this, Failure.of(e)));
        });
    }

    /** What an archive's part is called in the import dialog: the part, or with several
     *  distributions the distributions it is unpacked for. */
    private String importTitle(Install.ArchivePart plan) {
        List<String> names = new ArrayList<>();
        for (Install.ArchivePart p : plan.served()) {
            String name = Texts.of(this, p.part.title);
            if (spec.distributions.size() > 1) {
                String title = Texts.of(this, p.distribution.title);
                name = p.distribution.parts.size() > 1 ? title + " — " + name : title;
            }
            if (!names.contains(name)) names.add(name);
        }
        return String.join(" / ", names);
    }

    private void askImport() {
        StringBuilder body = new StringBuilder();
        long size = 0;
        boolean replace = false;
        boolean mountable = pendingPlan.size() == 1 && pendingPlan.get(0).part.mount && pendingPlan.get(0).also.isEmpty();
        List<File> targets = defaultTargets();
        for (int i = 0; i < pendingPlan.size(); ++i) {
            Install.ArchivePart part = pendingPlan.get(i);
            File target = targets.get(i);
            size += part.size;
            replace |= target.exists() && target.list() != null && target.list().length > 0;
            body.append(importTitle(part)).append(": ").append(Texts.size(this, part.size))
                .append(" → ").append(target.getPath()).append('\n');
            if (part.compressed > (Math.max(1, spec.json.optJSONObject("app").optLong("mountSidecarLimitMB", 256)) << 20)) mountable = false;
        }
        File first = targets.get(0);
        body.append(Texts.fmt(this, Texts.FREE, Texts.size(this, Storage.free(first))));
        if (replace) body.append("\n\n").append(Texts.t(this, Texts.REPLACE));
        if (mountable) body.append("\n\n").append(Texts.fmt(this, Texts.ARCHIVE_STORED, Texts.size(this, pendingPlan.get(0).compressed)));
        android.app.AlertDialog.Builder b = ui.dialog().setTitle(Texts.t(this, Texts.IMPORT_TITLE)).setMessage(withNotificationNote(body.toString()))
            .setNegativeButton(Texts.t(this, Texts.CANCEL), (dlg, w) -> dropPending())
            .setOnCancelListener(dlg -> dropPending());
        b.setPositiveButton(Texts.t(this, Texts.UNPACK), (dlg, w) -> unpackDefault());
        if (mountable) b.setNeutralButton(Texts.t(this, Texts.PLAY_FROM_ARCHIVE), (dlg, w) -> mount());
        else if (!allFixed()) b.setNeutralButton(Texts.t(this, Texts.CHOOSE_PART), (dlg, w) -> pick(Pickers.FOLDER, ASK_TARGET, spec.storageRoot()));
        ui.show(b);
    }

    private File defaultTarget(Install.ArchivePart part) {
        File folder = spec.resolve(this, part.part.folder);
        if (part.part.fixed) return folder;
        return Install.present(part.part, folder) || !folder.exists() ? folder : Install.target(folder.getParentFile(), folder.getName());
    }

    /** Each part's default folder, no two parts of the import in the same one. */
    private List<File> defaultTargets() {
        List<File> targets = new ArrayList<>();
        for (Install.ArchivePart part : pendingPlan) targets.add(defaultTarget(part));
        return Install.distinct(pendingPlan, targets);
    }

    private void unpackDefault() {
        unpack(defaultTargets());
    }

    /** The player picked where non-fixed parts go. */
    private void unpackInto(File chosen) {
        if (pendingPlan == null) return;
        if (chosen == null || !chosen.isDirectory()) { error(Texts.t(this, Texts.E_NO_PATH)); dropPending(); return; }
        List<File> targets = new ArrayList<>();
        for (Install.ArchivePart part : pendingPlan)
            targets.add(part.part.fixed ? defaultTarget(part) : Install.target(chosen, spec.storage.isEmpty() ? part.part.id : spec.storage));
        unpack(Install.distinct(pendingPlan, targets));
    }

    private void unpack(List<File> targets) {
        for (int i = 0; pendingPlan != null && i < pendingPlan.size(); ++i) {
            Install.ArchivePart part = pendingPlan.get(i);
            String problem = hooks.installationProblem(this, part.distribution.id, part.part.id, targets.get(i));
            if (problem != null) { error(problem); dropPending(); return; }
        }
        Zip zip = pendingZip;
        List<Install.ArchivePart> plan = pendingPlan;
        pendingZip = null;   /* the job owns the archive now */
        pendingPlan = null;
        Install.UnpackJob job = new Install.UnpackJob(this, zip, plan, targets);
        State.update(this, State.CHOICES, values -> {
            values.setProperty("importing", String.join("\n", paths(targets)));
            if (pendingUri != null) values.setProperty("importingFrom", pendingUri.toString());
            else values.remove("importingFrom");
            if (pendingFile != null) values.setProperty("importingFile", pendingFile.getAbsolutePath());
            else values.remove("importingFile");
        });
        startJob(job);
    }

    private static List<String> paths(List<File> files) {
        List<String> result = new ArrayList<>();
        for (File f : files) result.add(f.getAbsolutePath());
        return result;
    }

    /** Plays the single part straight from its stored archive. */
    private void mount() {
        Install.ArchivePart part = pendingPlan.get(0);
        Zip zip = pendingZip;
        Uri uri = pendingUri;
        File file = pendingFile;
        pendingZip = null;
        pendingPlan = null;
        if (uri != null && file == null) {
            try {
                getContentResolver().takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
            } catch (SecurityException e) {
                closeQuietly(zip);
                error(Texts.t(this, Texts.E_REMOTE));
                return;
            }
        }
        String source = file != null ? file.getAbsolutePath() : uri.toString();
        File index = new File(State.folder(this), "mount-" + part.distribution.id + "-" + part.part.id + ".zmi");
        File sidecar = new File(State.folder(this), "mount-" + part.distribution.id + "-" + part.part.id);
        startJob(new MountJob(zip, part, index, sidecar, () -> State.update(this, State.CHOICES, values -> {
            values.setProperty(Install.key(part.distribution, part.part), sidecar.getAbsolutePath());
            values.setProperty(Install.key(part.distribution, part.part) + ".mount", source);
        })));
    }

    /** Unpacks a stored archive's few compressed files beside it and writes the game's index. */
    private final class MountJob extends Work.Job {
        final Zip zip;
        final Install.ArchivePart part;
        final File index, sidecar;
        final Runnable record;

        MountJob(Zip zip, Install.ArchivePart part, File index, File sidecar, Runnable record) {
            super(Texts.t(LauncherActivity.this, Texts.JOB_INDEX), sidecar);
            this.zip = zip;
            this.part = part;
            this.index = index;
            this.sidecar = sidecar;
            this.record = record;
            total = part.compressed;
        }

        @Override void work() throws IOException {
            try {
                StoredArchive.Plan plan = StoredArchive.plan(zip, part.root, part.part.needed);
                if (sidecar.exists()) Install.delete(sidecar);
                byte[] buffer = new byte[1 << 20];
                for (StoredArchive.Item item : plan.items) {
                    if (item.stored()) continue;
                    file = item.path;
                    File out = new File(sidecar, item.path);
                    if (!out.getParentFile().isDirectory() && !out.getParentFile().mkdirs()) throw new Failure(Failure.READ_ONLY, out.getParent());
                    java.util.zip.CRC32 crc = new java.util.zip.CRC32();
                    try (java.io.InputStream in = zip.open(item.entry); java.io.OutputStream o = new java.io.FileOutputStream(out)) {
                        for (int n; (n = in.read(buffer)) > 0;) {
                            check();
                            o.write(buffer, 0, n);
                            crc.update(buffer, 0, n);
                            done += n;
                        }
                    }
                    if (crc.getValue() != item.entry.crc) throw new Failure(Failure.CORRUPT, item.path);
                }
                StoredArchive.writeIndex(plan, zip.length(), StoredArchive.fingerprint(zip), index);
                record.run();
            } finally {
                closeQuietly(zip);
            }
        }
    }

    private static void closeQuietly(Zip zip) {
        if (zip == null) return;
        try { zip.close(); } catch (IOException ignored) { /* only read */ }
    }

    private void dropPending() {
        closeQuietly(pendingZip);
        pendingZip = null;
        pendingPlan = null;
        pendingUri = null;
        pendingFile = null;
    }

    /** Imports that ended with the process leave nothing half-done behind. */
    private boolean recover() {
        String importing = State.get(this, State.CHOICES, "importing", "");
        boolean found = false;
        for (String path : importing.split("\n")) if (!path.isEmpty()) found |= Install.recover(new File(path));
        for (Spec.Distribution d : spec.distributions)
            for (Spec.Part p : d.parts) if (p.fixed && Storage.allFiles(this)) found |= Install.recover(Install.folder(this, spec, d, p));
        if (!importing.isEmpty()) State.put(this, State.CHOICES, "importing", null);
        return found;
    }

    /* ------------------------------------------------------------ work */

    /** Starts long work. The notification permission is asked first, once, from the confirmation
     *  that explained it: the system's dialog then neither covers the progress nor outlives a short
     *  job. The work starts after the answer, whatever it is. */
    private void startJob(Work.Job job) {
        if (notificationsUnasked()) {
            State.put(this, State.CHOICES, "asked.notifications", "1");
            pendingJob = job;
            requestPermissions(new String[] {Storage.NOTIFICATIONS}, ASK_PERMISSION);
            return;
        }
        runJob(job);
    }

    /** Work without a confirmation of its own explains the notification request first. */
    private void confirmJob(Work.Job job) {
        if (!notificationsUnasked()) { startJob(job); return; }
        ui.show(ui.dialog().setTitle(Texts.t(this, Texts.NOTIFY_TITLE)).setMessage(Texts.t(this, Texts.PERM_NOTIFY))
            .setPositiveButton(Texts.t(this, Texts.CONTINUE), (dlg, w) -> startJob(job))
            .setNegativeButton(Texts.t(this, Texts.CANCEL), null));
    }

    private void runJob(Work.Job job) {
        if (!Work.start(this, job)) return;
        ++textureEpoch;
        textureScanning = false;
        textureScan = null;
        note(job.section, null, false);
        handler.removeCallbacks(watcher);
        handler.post(watcher);
        refresh(Texts.PLAY, Texts.GAME_FILES, Texts.TEXTURES, Texts.SPACE);
    }

    private final Runnable watcher = new Runnable() {
        @Override public void run() {
            Work.Job job = Work.current;
            if (job == null) { work.setVisibility(View.GONE); return; }
            work.setVisibility(job.finished ? View.GONE : View.VISIBLE);
            if (!job.finished) {
                workTitle.setText(job.title.toUpperCase(java.util.Locale.getDefault()));
                workBar.setIndeterminate(job.total <= 0);
                workBar.setProgress(job.permille());
                String line = job.progressText(LauncherActivity.this);
                workText.setText(job.file.isEmpty() ? line : line + " · " + job.file);
                Ui.enable(workStop, !job.cancelled);
                handler.postDelayed(this, 250);
            } else if (visible) {
                finished(job);
            }
        }
    };

    private void finished(Work.Job job) {
        Work.current = null;
        String from = State.get(this, State.CHOICES, "importingFrom", ""), fromFile = State.get(this, State.CHOICES, "importingFile", "");
        State.update(this, State.CHOICES, values -> {
            values.remove("importing");
            values.remove("importingFrom");
            values.remove("importingFile");
        });
        if (job.failure != null) {
            note(job.section, job.failure.code == Failure.CANCELLED ? Texts.t(this, Texts.E_CANCELLED)
                : Texts.failure(this, job.failure), job.failure.code != Failure.CANCELLED);
        } else {
            if (job instanceof Install.UnpackJob) {
                Install.UnpackJob unpack = (Install.UnpackJob) job;
                for (int i = 0; i < unpack.plans.size(); ++i)
                    for (Install.ArchivePart served : unpack.plans.get(i).served())
                        if (!served.part.fixed) Install.choose(this, served.distribution, served.part, unpack.targets.get(i));
                note(job.section, Texts.t(this, Texts.DONE), false);
                askDeleteArchive(unpack.targets.get(0), from, fromFile);
            } else if (job instanceof Cleanup.Job) {
                note(job.section, Texts.fmt(this, Texts.CLEAN_DONE, Texts.size(this, job.done)), false);
            } else {
                note(job.section, Texts.t(this, Texts.DONE), false);
            }
        }
        textureScan = null;
        refresh(Texts.PERM_FILES, Texts.PLAY, Texts.GAME_FILES, Texts.RENDERER, Texts.TEXTURES, Texts.SPACE);
    }

    private void askStop() {
        Work.Job job = Work.current;
        if (job == null || job.finished) return;
        ui.show(ui.dialog().setMessage(Texts.t(this, Texts.STOP_ASK))
            .setPositiveButton(Texts.t(this, Texts.STOP), (d, w) -> {
                job.cancelled = true;
                if (textures != null && job.section == Texts.TEXTURES) textures.cancel();
            })
            .setNegativeButton(Texts.t(this, Texts.CONTINUE), null));
    }

    private void askDeleteArchive(File target, String uri, String file) {
        if (uri.isEmpty() && file.isEmpty()) return;
        String name = !file.isEmpty() ? new File(file).getName() : Uri.decode(Uri.parse(uri).getLastPathSegment());
        long size = !file.isEmpty() ? new File(file).length() : -1;
        ui.show(ui.dialog().setMessage(Texts.fmt(this, Texts.DELETE_ARCHIVE, target.getPath(), name, size >= 0 ? Texts.size(this, size) : "?"))
            .setPositiveButton(Texts.t(this, Texts.DELETE), (d, w) -> {
                boolean deleted = false;
                if (!uri.isEmpty()) {
                    try { deleted = DocumentsContract.deleteDocument(getContentResolver(), Uri.parse(uri)); }
                    catch (Exception e) { android.util.Log.i("Launcher", "archive document: " + e); }
                }
                if (!deleted && !file.isEmpty()) new File(file).delete();
            })
            .setNegativeButton(Texts.t(this, Texts.KEEP), null));
    }

    /* --------------------------------------------------------- renderer */

    private boolean convertedTextures() {
        return textureScan != null && textureScan.converted != 0 && textureSourceKey().equals(textureSource);
    }

    private void refreshRenderer() {
        renderer.removeAllViews();
        if (selected.renderers.size() < 2 || gpu == null) return;
        LinearLayout card = section(renderer, Texts.RENDERER);
        List<Renderers.Status> statuses = Renderers.evaluate(this, spec, selected, gpu, convertedTextures());
        String explicit = Renderers.explicitChoice(this, spec, selected, hooks);
        String chosen = explicit != null ? explicit : spec.defaultMode;
        for (Renderers.Status s : statuses) {
            String description = Texts.of(this, s.mode.description);
            /* A mode the driver check has not confirmed says so, and is never picked by itself. */
            String hint = !s.available ? Texts.t(this, Texts.UNAVAILABLE) + ": " + s.reason
                : s.verified ? description : (description.isEmpty() ? "" : description + "\n") + s.reason;
            card.addView(ui.choice(s.mode.title, hint, s.mode.id.equals(chosen), s.available, !s.available ? null : () -> {
                Renderers.choose(this, selected, hooks, s.mode.id);
                refresh(Texts.RENDERER, Texts.TEXTURES, Texts.PLAY);
            }));
        }
        String effective = Renderers.effective(spec.defaultMode, statuses, chosen, explicit != null);
        Renderers.Status current = Renderers.status(statuses, chosen);
        Spec.Mode used = spec.mode(effective), fallback = spec.mode(spec.defaultMode);
        if (!effective.equals(chosen) && current != null) {
            card.addView(ui.label(Texts.fmt(this, Texts.N_FALLBACK, current.mode.title, current.reason, used != null ? used.title : effective), 13, ui.error));
        } else if (current != null && !current.verified && fallback != null && !fallback.id.equals(chosen)) {
            card.addView(ui.label(Texts.fmt(this, Texts.N_UNCHECKED, current.mode.title, fallback.title), 13, ui.error));
        }
        Spec.Mode turnip = Probe.turnipMode(spec);
        if (turnip != null && selected.renderers.contains(turnip.id) && gpu.qualcomm()) {
            File own = TurnipDriver.chosen(this);
            card.addView(ui.label(Texts.fmt(this, Texts.TURNIP_DRIVER, own != null ? TurnipDriver.title(this)
                : Texts.t(this, Texts.TURNIP_BUILTIN)), 14, ui.text));
            card.addView(ui.label(Texts.t(this, Texts.TURNIP_HINT), 12, ui.muted));
            TextView choose = ui.button(Texts.t(this, Texts.TURNIP_CHOOSE), Ui.SECONDARY, () -> pick(Pickers.ZIP, ASK_DRIVER, null));
            if (own == null) card.addView(ui.buttons(choose));
            else card.addView(ui.buttons(choose, ui.button(Texts.t(this, Texts.TURNIP_RESET), Ui.QUIET, this::resetDriver)));
        }
        card.addView(ui.label(Texts.fmt(this, Texts.GPU, gpu.renderer.isEmpty() ? "?" : gpu.renderer, Gpu.version(gpu.vulkan)), 12, ui.muted));
        card.addView(ui.label(Texts.t(this, Texts.N_APPLIES), 12, ui.muted));
    }

    /** The player's own Turnip driver from a picked package or library; the driver check runs for it. */
    private void importDriver(Uri uri, File file) {
        setBusy(Texts.RENDERER, Texts.t(this, Texts.TURNIP_COPYING));
        background(() -> TurnipDriver.install(this, uri, file), title -> {
            setBusy(null);
            note(Texts.RENDERER, Texts.fmt(this, Texts.TURNIP_DRIVER, title), false);
            checkRenderer();
        }, problem -> {
            setBusy(null);
            note(Texts.RENDERER, Texts.fmt(this, Texts.E_TURNIP, String.valueOf(problem.getMessage())), true);
        });
    }

    private void resetDriver() {
        background(() -> { TurnipDriver.reset(this); return true; }, done -> checkRenderer(), null);
    }

    private void checkRenderer() {
        if (hasWindowFocus()) Probe.start(this, spec);
        if (Probe.running(this)) {
            handler.removeCallbacks(probeWatch);
            handler.postDelayed(probeWatch, PROBE_POLL_MS);
        }
        refresh(Texts.RENDERER, Texts.TEXTURES, Texts.PLAY);
    }

    /* ---------------------------------------------------------- options */

    private void refreshOptions() {
        options.removeAllViews();
        List<Spec.Option> list = spec.options(selected.id);
        if (!selected.intro && list.isEmpty()) return;
        LinearLayout card = section(options, Texts.OPTIONS);
        if (selected.intro) {
            String key = "intro." + selected.id;
            card.addView(ui.toggle(Texts.t(this, Texts.SKIP_INTRO), null,
                "1".equals(State.get(this, State.CHOICES, key, selected.introDefault ? "1" : "0")),
                on -> State.put(this, State.CHOICES, key, on ? "1" : "0")));
        }
        for (Spec.Option o : list) {
            if (o.arm64Only && !android.os.Process.is64Bit()) continue;
            String key = "option." + o.key, value = Launch.option(this, o);
            if ("bool".equals(o.type)) {
                card.addView(ui.toggle(Texts.of(this, o.title), Texts.of(this, o.hint), "1".equals(value) || "true".equals(value),
                    on -> State.put(this, State.CHOICES, key, on ? "1" : "0")));
            } else if ("choice".equals(o.type)) {
                if (o.choices.size() > 4) {
                    String[] titles = new String[o.choices.size()];
                    int checked = -1;
                    for (int i = 0; i < titles.length; ++i) {
                        titles[i] = Texts.of(this, o.choiceTitles.get(i));
                        String problem = hooks.optionProblem(this, o.key, o.choices.get(i));
                        if (problem != null) titles[i] += " — " + problem;
                        if (o.choices.get(i).equals(value)) checked = i;
                    }
                    final int selectedChoice = checked;
                    card.addView(ui.choice(Texts.of(this, o.title), checked < 0 ? value : titles[checked], false, true,
                        () -> ui.show(ui.dialog().setTitle(Texts.of(this, o.title))
                            .setSingleChoiceItems(titles, selectedChoice, (dialog, which) -> {
                                String problem = hooks.optionProblem(this, o.key, o.choices.get(which));
                                if (problem != null) {
                                    if (selectedChoice >= 0) ((android.app.AlertDialog)dialog).getListView().setItemChecked(selectedChoice, true);
                                    ui.show(ui.dialog().setMessage(problem).setPositiveButton(Texts.t(this, Texts.OK), null));
                                    return;
                                }
                                State.put(this, State.CHOICES, key, o.choices.get(which));
                                dialog.dismiss();
                                refresh(Texts.OPTIONS);
                            }).setNegativeButton(Texts.t(this, Texts.CANCEL), null))));
                    continue;
                }
                card.addView(ui.label(Texts.of(this, o.title), 15, ui.text));
                for (int i = 0; i < o.choices.size(); ++i) {
                    String choice = o.choices.get(i);
                    card.addView(ui.choice(Texts.of(this, o.choiceTitles.get(i)), null, choice.equals(value), true, () -> {
                        State.put(this, State.CHOICES, key, choice);
                        refresh(Texts.OPTIONS);
                    }));
                }
            } else {
                card.addView(ui.choice(Texts.of(this, o.title), value.isEmpty() ? Texts.of(this, o.hint) : value, false, true,
                    () -> editText(o, key, value)));
            }
        }
        String hint = Texts.of(this, spec.optionsHint);
        if (!hint.isEmpty()) card.addView(ui.label(hint, 13, ui.muted));
    }

    private void editText(Spec.Option o, String key, String value) {
        EditText field = new EditText(this);
        field.setText(value);
        field.setSingleLine(false);
        field.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        ui.show(ui.dialog().setTitle(Texts.of(this, o.title)).setMessage(Texts.of(this, o.hint)).setView(field)
            .setPositiveButton(Texts.t(this, Texts.OK), (d, w) -> {
                State.put(this, State.CHOICES, key, field.getText().toString().trim());
                refresh(Texts.OPTIONS);
            })
            .setNegativeButton(Texts.t(this, Texts.CANCEL), null));
    }

    /* --------------------------------------------------------- textures */

    private File textureRoot() {
        Spec.Part first = selected.parts.get(0);
        return Install.folder(this, spec, selected, first);
    }

    private String textureSourceKey() {
        return selected.id + "\n" + textureRoot().getAbsolutePath() + "\n"
            + Install.mount(this, selected, selected.parts.get(0));
    }

    private void textureScanFinished(String source, long epoch, TextureBackend.Scan scan) {
        if (epoch != textureEpoch) return;
        textureScanning = false;
        if (source.equals(textureSource)) textureScan = scan;
        refresh(Texts.TEXTURES, Texts.RENDERER);
    }

    private void refreshTextures(boolean idle) {
        texturesBox.removeAllViews();
        if (spec.textureBackend.isEmpty() || gpu == null) return;
        LinearLayout card = section(texturesBox, Texts.TEXTURES);
        if (initializing) return;
        if (!Install.ready(this, spec, selected)) return;
        if (textures == null) {
            try {
                textures = (TextureBackend) Class.forName(spec.textureBackend).getDeclaredConstructor().newInstance();
            } catch (ReflectiveOperationException | ClassCastException | LinkageError e) {
                android.util.Log.w("Launcher", "textures: " + e);
                return;
            }
        }
        String source = textureSourceKey();
        if (!source.equals(textureSource)) {
            textureSource = source;
            textureScan = null;
            note(Texts.TEXTURES, null, false);
        }
        if (textureScan == null) {
            if (!textureScanning && idle) {
                File root = textureRoot();
                long epoch = textureEpoch;
                textureScanning = true;
                background(() -> textures.scan(root), scan -> textureScanFinished(source, epoch, scan), failure -> {
                    TextureBackend.Scan scan = new TextureBackend.Scan();
                    scan.failure = failure.getMessage() != null ? failure.getMessage() : failure.toString();
                    textureScanFinished(source, epoch, scan);
                });
            }
            return;
        }
        TextureBackend.Scan s = textureScan;
        boolean converted = s.converted != 0;
        if (s.failure != null) { note(Texts.TEXTURES, s.failure, true); return; }
        if (converted) {
            card.addView(ui.label(Texts.fmt(this, Texts.TEX_DONE, s.converted == TextureBackend.ASTC ? "ASTC" : "ETC2",
                Texts.size(this, s.convertedBytes)), 14, ui.text));
            if (s.originalsRemoved) card.addView(ui.label(Texts.t(this, Texts.TEX_GONE), 13, ui.muted));
            List<TextView> buttons = new ArrayList<>();
            if (s.removable > 0) buttons.add(ui.button(Texts.fmt(this, Texts.TEX_REMOVE, Texts.size(this, s.removable)), Ui.SECONDARY,
                () -> ui.show(ui.dialog().setTitle(Texts.t(this, Texts.TEXTURES))
                    .setMessage(Texts.fmt(this, Texts.TEX_REMOVE_ASK, Texts.size(this, s.removable)))
                    .setPositiveButton(Texts.t(this, Texts.DELETE), (d, w) -> startTextures(TEX_REMOVE_ORIGINALS))
                    .setNegativeButton(Texts.t(this, Texts.CANCEL), null))));
            if (!s.originalsRemoved) buttons.add(ui.button(Texts.t(this, Texts.TEX_UNDO), Ui.SECONDARY, () -> startTextures(0)));
            for (TextView b : buttons) Ui.enable(b, idle);
            if (!buttons.isEmpty()) card.addView(ui.buttons(buttons.toArray(new TextView[0])));
            return;
        }
        if (!gpu.probed || Boolean.TRUE.equals(dxtSupport())) return;
        if (s.textures == 0) { card.addView(ui.label(Texts.t(this, Texts.TEX_NOTHING), 13, ui.muted)); return; }
        card.addView(ui.label(Texts.t(this, Texts.TEX_WHY), 13, ui.muted));
        card.addView(ui.label(Texts.fmt(this, Texts.TEX_FOUND, s.textures, Texts.size(this, s.bytes)), 14, ui.text));
        List<TextView> buttons = new ArrayList<>();
        if (gpu.astc) buttons.add(ui.button(Texts.fmt(this, Texts.TEX_CONVERT, "ASTC"), Ui.SECONDARY, () -> startTextures(TextureBackend.ASTC)));
        buttons.add(ui.button(Texts.fmt(this, Texts.TEX_CONVERT, "ETC2"), Ui.SECONDARY, () -> startTextures(TextureBackend.ETC2)));
        for (TextView b : buttons) Ui.enable(b, idle);
        card.addView(ui.buttons(buttons.toArray(new TextView[0])));
    }

    /** format 0 removes the conversion, TEX_REMOVE_ORIGINALS the originals it replaced. */
    private void startTextures(int format) {
        File root = textureRoot();
        TextureBackend backend = textures;
        confirmJob(new Work.Job(Texts.TEXTURES, Texts.t(this, Texts.JOB_TEXTURES), root) {
            @Override void work() throws Exception {
                Thread poll = new Thread(() -> {
                    while (!finished) {
                        long[] p = backend.progress();
                        if (p != null && p.length >= 4) { done = p[2]; total = p[3]; itemsDone = p[0]; itemsTotal = p[1]; }
                        try { Thread.sleep(250); } catch (InterruptedException e) { return; }
                    }
                }, "texture-progress");
                poll.start();
                int result = format == 0 ? backend.undo(root) : format == TEX_REMOVE_ORIGINALS ? backend.removeOriginals(root)
                    : backend.convert(root, format, Runtime.getRuntime().availableProcessors());
                poll.interrupt();
                check();
                if (result != 0) throw new Failure(Failure.IO, backend.message());
            }
        });
    }

    /* ------------------------------------------------------------ space */

    private void refreshSpace(boolean idle) {
        space.removeAllViews();
        if (initializing) return;
        boolean any = false;
        for (Spec.Category c : spec.categories) any |= c.part.isEmpty() || selected.part(c.part) != null;
        if (!any || !Install.ready(this, spec, selected)) return;
        LinearLayout card = section(space, Texts.SPACE);
        TextView clean = ui.button(Texts.t(this, Texts.CLEAN), Ui.SECONDARY, this::scanCleanup);
        card.addView(ui.buttons(clean));
        Ui.enable(clean, idle);
    }

    private void scanCleanup() {
        setBusy(Texts.SPACE, Texts.t(this, Texts.CLEAN_SCAN));
        background(() -> {
            List<Cleanup.Plan> plans = new ArrayList<>();
            for (Spec.Part p : selected.parts) {
                if (!Install.mount(this, selected, p).isEmpty()) continue;
                List<Spec.Category> categories = new ArrayList<>();
                for (Spec.Category c : spec.categories) if (c.part.isEmpty() || c.part.equals(p.id)) categories.add(c);
                if (!categories.isEmpty()) plans.add(Cleanup.scan(Install.folder(this, spec, selected, p), categories));
            }
            return plans;
        }, plans -> {
            setBusy(null);
            List<Cleanup.Entry> all = new ArrayList<>();
            long bytes = 0;
            for (Cleanup.Plan plan : plans) { all.addAll(plan.files); bytes += plan.bytes; }
            if (all.isEmpty()) { note(Texts.SPACE, Texts.t(this, Texts.CLEAN_NONE), false); return; }
            StringBuilder list = new StringBuilder(withNotificationNote(Texts.fmt(this, Texts.CLEAN_ASK, all.size(), Texts.size(this, bytes)))).append('\n');
            for (Spec.Category c : spec.categories) {
                long size = 0;
                int count = 0;
                for (Cleanup.Plan plan : plans)
                    for (Cleanup.Entry e : plan.files) {
                        String path = e.file.getAbsolutePath().substring(plan.root.getAbsolutePath().length() + 1);
                        for (Glob g : c.globs) if (g.matches(path)) { size += e.size; ++count; break; }
                    }
                if (count > 0) list.append("\n• ").append(Texts.of(this, c.title)).append(" — ").append(count).append(", ").append(Texts.size(this, size));
            }
            for (Cleanup.Plan plan : plans)
                for (Cleanup.Entry e : plan.files)
                    list.append("\n").append(e.file.getAbsolutePath().substring(plan.root.getAbsolutePath().length() + 1));
            ScrollView scroll = new ScrollView(this);
            TextView contents = ui.label(list.toString(), 13, ui.text);
            contents.setPadding(ui.dp(20), ui.dp(8), ui.dp(20), ui.dp(8));
            scroll.addView(contents);
            ui.show(ui.dialog().setTitle(Texts.t(this, Texts.CLEAN)).setView(scroll)
                .setPositiveButton(Texts.t(this, Texts.DELETE), (d, w) -> deletePlans(plans))
                .setNegativeButton(Texts.t(this, Texts.CANCEL), null));
        }, e -> { setBusy(null); note(Texts.SPACE, Texts.failure(this, Failure.of(e)), true); });
    }

    private void deletePlans(List<Cleanup.Plan> plans) {
        List<Cleanup.Entry> all = new ArrayList<>();
        for (Cleanup.Plan plan : plans) all.addAll(plan.files);
        if (plans.size() == 1) { startJob(new Cleanup.Job(this, plans.get(0))); return; }
        startJob(new Work.Job(Texts.SPACE, Texts.t(this, Texts.JOB_CLEAN), plans.get(0).root) {
            @Override void work() throws Exception {
                for (Cleanup.Plan plan : plans) { total += plan.bytes; itemsTotal += plan.files.size(); }
                for (Cleanup.Plan plan : plans) {
                    check();
                    Cleanup.Job one = new Cleanup.Job(LauncherActivity.this, plan);
                    one.work();
                    done += one.done;
                    itemsDone += one.itemsDone;
                }
            }
        });
    }

    /* ---------------------------------------------------------- updates */

    private void checkUpdates(boolean manual) {
        if (checking || !spec.updates) return;
        checking = true;
        note(Texts.ABOUT, null, false);
        refresh(Texts.ABOUT);
        background(() -> Updates.check(this), info -> {
            checking = false;
            if (manual) note(Texts.ABOUT, Updates.available(this) == null ? Texts.t(this, Texts.UP_TO_DATE) : null, false);
            refresh(Texts.ABOUT, Texts.UPDATE_AVAILABLE);
        }, e -> {
            checking = false;
            if (manual) note(Texts.ABOUT, Texts.fmt(this, Texts.UPDATE_FAILED, e.getMessage()), true);
            refresh(Texts.ABOUT, Texts.UPDATE_AVAILABLE);
        });
    }

    private void refreshUpdate() {
        update.removeAllViews();
        Updates.Info info = spec.updates ? Updates.available(this) : null;
        if (info == null) return;
        LinearLayout card = ui.card(update);
        attach(card, notice(Texts.UPDATE_AVAILABLE));
        card.addView(ui.label(Texts.fmt(this, Texts.UPDATE_AVAILABLE, info.versionName, Updates.installedName(this)), 16, ui.accent));
        if (!Updates.sameSigner(this, info)) card.addView(ui.label(Texts.t(this, Texts.UPDATE_SIGNER), 13, ui.error));
        List<TextView> buttons = new ArrayList<>();
        if (!info.apkUrl.isEmpty()) buttons.add(ui.button(Texts.t(this, Texts.DOWNLOAD) + (info.size > 0 ? " · " + Texts.size(this, info.size) : ""),
            Ui.SECONDARY, () -> open(info.apkUrl, Texts.UPDATE_AVAILABLE)));
        if (!info.notes.isEmpty()) buttons.add(ui.button(Texts.t(this, Texts.WHATS_NEW), Ui.SECONDARY, () -> showNotes(info)));
        buttons.add(ui.button(Texts.t(this, Texts.SKIP_VERSION), Ui.QUIET, () -> { Updates.skip(this, info.versionCode); refresh(Texts.ABOUT, Texts.UPDATE_AVAILABLE); }));
        card.addView(ui.buttons(buttons.toArray(new TextView[0])));
    }

    private void showNotes(Updates.Info info) {
        ScrollView scroll = new ScrollView(this);
        TextView text = ui.label(info.notes.replace("**", "").replace("## ", ""), 14, ui.text);
        text.setPadding(ui.dp(20), ui.dp(8), ui.dp(20), ui.dp(8));
        text.setTextIsSelectable(true);
        scroll.addView(text);
        android.app.AlertDialog.Builder b = ui.dialog().setTitle(info.versionName).setView(scroll).setPositiveButton(Texts.t(this, Texts.OK), null);
        if (!info.page.isEmpty()) b.setNeutralButton(Texts.t(this, Texts.RELEASES), (d, w) -> open(info.page, Texts.UPDATE_AVAILABLE));
        ui.show(b);
    }

    private void open(String url) {
        open(url, Texts.ABOUT);
    }

    private void open(String url, int section) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)).addCategory(Intent.CATEGORY_BROWSABLE));
        } catch (ActivityNotFoundException e) {
            note(section, url, true);
        }
    }

    /* ------------------------------------------------------------ about */

    private void refreshAbout() {
        about.removeAllViews();
        LinearLayout card = section(about, Texts.ABOUT);
        TextView version = ui.label(versionLine(), 14, ui.text);
        version.setTextIsSelectable(true);
        card.addView(version);
        if (!spec.github.isEmpty()) {
            TextView link = ui.label("github.com/" + spec.github, 14, ui.accent);
            link.setOnClickListener(v -> open(spec.githubUrl("")));
            card.addView(link);
            List<TextView> buttons = new ArrayList<>();
            buttons.add(ui.button(Texts.t(this, Texts.GITHUB), Ui.SECONDARY, () -> open(spec.githubUrl(""))));
            buttons.add(ui.button(Texts.t(this, Texts.RELEASES), Ui.SECONDARY, () -> open(spec.githubUrl("/releases"))));
            card.addView(ui.buttons(buttons.toArray(new TextView[0])));
        }
        if (spec.updates) {
            TextView check = ui.button(Texts.t(this, checking ? Texts.CHECKING : Texts.CHECK_UPDATES), Ui.SECONDARY, () -> checkUpdates(true));
            Ui.enable(check, !checking);
            card.addView(ui.buttons(check));
            card.addView(ui.toggle(Texts.t(this, Texts.UPDATE_AUTO), null, Updates.automatic(this),
                on -> State.put(this, State.CHOICES, "updates.auto", on ? "1" : "0")));
        }
        card.addView(ui.toggle(Texts.t(this, Texts.ALWAYS_BUILTIN), null, "1".equals(State.get(this, State.CHOICES, "builtInBrowser", "0")),
            on -> State.put(this, State.CHOICES, "builtInBrowser", on ? "1" : "0")));
        if (spec.languages.size() > 1) {
            String current = State.get(this, State.CHOICES, "language", "");
            TextView language = ui.button(Texts.t(this, Texts.LANGUAGE) + ": " + (current.isEmpty() ? Texts.t(this, Texts.SYSTEM_LANGUAGE)
                : current.toUpperCase(java.util.Locale.ROOT)), Ui.QUIET, this::chooseLanguage);
            card.addView(ui.buttons(language));
        }
        List<Spec.License> licenses = licenses();
        if (!licenses.isEmpty()) card.addView(ui.buttons(ui.button(Texts.t(this, Texts.LICENSES), Ui.QUIET, () -> showLicenses(licenses))));
        card.addView(ui.buttons(ui.button(Texts.t(this, Texts.COPY_DIAGNOSTICS), Ui.SECONDARY, this::copyDiagnostics)));
    }

    private void copyDiagnostics() {
        String gpuText = gpu == null ? "not checked" : gpu.renderer + " (" + gpu.vendor + ")"
            + "; GLES DXT=" + (gpu.probed ? Boolean.toString(gpu.s3tc) : "unknown") + "; Vulkan=" + Gpu.version(gpu.vulkan);
        String mode = effectiveRenderer(selected);
        String report = Diagnostics.report(this, Texts.of(this, selected.title), gpuText,
            mode == null ? "not checked" : mode, textureState(), lastError);
        boolean copied = Diagnostics.copy(this, report);
        note(Texts.ABOUT, Texts.t(this, copied ? Texts.DIAGNOSTICS_COPIED : Texts.E_CLIPBOARD), !copied);
    }

    private void chooseLanguage() {
        List<String> codes = new ArrayList<>();
        List<String> names = new ArrayList<>();
        codes.add("");
        names.add(Texts.t(this, Texts.SYSTEM_LANGUAGE));
        for (String code : spec.languages) {
            if (Texts.index(code) == 0 && !"en".equals(code)) continue;
            codes.add(code);
            names.add(new java.util.Locale(code).getDisplayLanguage(new java.util.Locale(code)));
        }
        ui.show(ui.dialog().setTitle(Texts.t(this, Texts.LANGUAGE)).setItems(names.toArray(new String[0]), (d, which) -> {
            State.put(this, State.CHOICES, "language", codes.get(which));
            Texts.reset();
            recreate();
        }));
    }

    /** License texts the APK carries: port.json "licenses" (asset files with their titles, and
     *  folders ending in "/" whose files are named after themselves), and assets/licenses. */
    private List<Spec.License> licenses() {
        List<Spec.License> found = new ArrayList<>();
        AssetManager assets = getAssets();
        List<Spec.License> entries = new ArrayList<>(spec.licenses);
        boolean folder = false;
        for (Spec.License e : entries) folder |= e.path.equals("licenses/");
        if (!folder) entries.add(new Spec.License("licenses/", null));
        for (Spec.License entry : entries) {
            try {
                if (entry.path.endsWith("/")) {
                    String dir = entry.path.substring(0, entry.path.length() - 1);
                    String[] names = assets.list(dir);
                    if (names != null) for (String name : names) found.add(new Spec.License(dir + "/" + name, null));
                } else {
                    assets.open(entry.path).close();
                    found.add(entry);
                }
            } catch (IOException e) {
                /* not in this APK */
            }
        }
        return found;
    }

    /** A license's name for the player: its title, else its file name without the extension. */
    private String licenseTitle(Spec.License license) {
        String title = Texts.of(this, license.title);
        if (!title.isEmpty()) return title;
        String name = license.path.substring(license.path.lastIndexOf('/') + 1);
        int dot = name.lastIndexOf('.');
        return dot > 0 ? name.substring(0, dot) : name;
    }

    private void showLicenses(List<Spec.License> licenses) {
        String[] titles = new String[licenses.size()];
        for (int i = 0; i < titles.length; ++i) titles[i] = licenseTitle(licenses.get(i));
        ui.show(ui.dialog().setTitle(Texts.t(this, Texts.LICENSES)).setItems(titles, (d, which) -> {
            String text;
            try { text = Spec.asset(this, licenses.get(which).path); } catch (IOException e) { text = e.getMessage(); }
            ScrollView scroll = new ScrollView(this);
            TextView view = ui.label(text, 12, ui.text);
            view.setTypeface(Typeface.MONOSPACE);
            view.setPadding(ui.dp(16), ui.dp(8), ui.dp(16), ui.dp(8));
            view.setTextIsSelectable(true);
            scroll.addView(view);
            ui.show(ui.dialog().setTitle(titles[which]).setView(scroll).setPositiveButton(Texts.t(this, Texts.OK), null));
        }));
    }
}
