package org.thevoid.port;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.File;

/**
 * The Void on Android: a SurfaceView the lifted game renders into through EGL,
 * with the touch layer (Controls) on top, which produces the original
 * keyboard (DirectInput scan codes) and mouse input.
 */
public final class GameActivity extends Activity implements SurfaceHolder.Callback {
    /* The native library is loaded once the release is known (chooseRelease):
     * the 2009 releases (English, Russian, German) run libvoid.so, the 2008
     * Polish "Tension" its own lifted build, libvoid_tension.so. */
    private static native boolean nativeStart(String game, String data, String images, String shaderCache,
        int width, int height, boolean verbose);
    private static native void nativeSurface(Object surface);
    static native void nativeKey(int scanCode, boolean down);
    static native void nativeMouseButton(int button, boolean down);
    static native void nativeMouseMove(float x, float y, boolean relative);
    static native void nativeMouseWarp(float x, float y);
    static native void nativeCursorPosition(float[] out);
    static native void nativeMouseWheel(int delta);
    static native void nativeMovement(float x, float y);
    static native void nativeSetGameplayOptions(float verticalFov, float veinBrightness);
    static native boolean nativeConsoleCommand(String command);
    static native int nativeBodyTarget();
    static native void nativeBodyAmounts(float[] out);
    static native void nativeBodyDetails(float[] out);
    static native int nativeZoneLabels(float[] out);
    static native String nativeBodyStatName(int colour);
    static native String[] nativeHintTexts();
    static native int nativeBrushColour();
    static native int nativeBodyTransferColour();
    static native void nativeCancelStroke();
    static native long nativeHudState();
    private static native long nativeShaderProgress();
    private static native long nativeShaderWarmup();
    private static native long nativeMissingShader();
    static native int nativeHudSlots(float[] out);
    static native void nativeSoundEvents(int[] out);
    static native String nativeSavedPicture();
    static native void nativeSetCursorHidden(boolean hidden);
    static native void nativeSetHudHidden(int tags);
    static native void nativeSetFramePeriod(int microseconds);
    static native void nativeHoldPicture(int milliseconds);
    static native void nativeSetDoubleClicks(boolean on);
    private static native void nativeSetFontScale(float scale);
    private static native void nativeSetPhysicalSize(int width, int height);
    private static native void nativeSetDisplayRate(float hz);
    private static native void nativePause(boolean paused);

    /** A copy of the game (the launcher's choice: a folder anywhere, or
     *  "game", "game-*" under /sdcard/TheVoid from tools/push_game_data.py
     *  --target), described by its data/info.xml. */
    static final class Release {
        final File dir;
        final String title, language, library, images;

        Release(File dir) {
            this(dir, read(new File(dir, "data/info.xml")), read(new File(dir, "data/fsystems.xml")));
        }

        /** From the texts of data/info.xml and data/fsystems.xml (an archive's, before it is unpacked). */
        Release(File dir, String info, String languages) {
            this.dir = dir;
            String eng = attribute(info, "EngTitle");
            String title = attribute(info, "Title");
            int dash = title.indexOf(" - ");
            this.title = dash > 0 ? title.substring(0, dash) : title.isEmpty() ? dir.getName() : title;
            String menu = read(ScriptOverrides.file(dir, "data/Properties/Strings/menu.txt"));
            this.language = menu.codePoints().anyMatch(c -> c >= 0x0400 && c <= 0x04ff) ? "Russian" : attribute(languages, "Name");
            boolean tension = eng.equalsIgnoreCase("Tension");
            this.library = tension ? "void_tension" : "void";
            this.images = tension ? "lifted-tension" : "lifted";
        }

        String label() { return language.isEmpty() ? title : title + " — " + language; }

        static String read(File file) {
            try (java.io.FileInputStream in = new java.io.FileInputStream(file)) {
                byte[] data = new byte[(int) Math.min(file.length(), 1 << 16)];
                int n = in.read(data);
                if (n <= 0) return "";
                if (n >= 2 && data[0] == (byte)0xff && data[1] == (byte)0xfe)
                    return new String(data, 2, n - 2, java.nio.charset.StandardCharsets.UTF_16LE);
                return new String(data, 0, n, java.nio.charset.StandardCharsets.UTF_8);
            } catch (java.io.IOException e) {
                return "";
            }
        }

        static String attribute(String xml, String name) {
            int at = xml.indexOf(name + "=\"");
            if (at < 0) return "";
            int start = at + name.length() + 2, end = xml.indexOf('"', start);
            return end > start ? xml.substring(start, end) : "";
        }
    }

    private File base;
    private boolean started;   /* the native library is loaded and the game runs */
    /** The lifted game runs once per process: the launcher comes back here. */
    static volatile boolean running;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        /* The volume keys set the game's volume, not the ringer's, also
         * while it is silent (loading, paused). */
        setVolumeControlStream(android.media.AudioManager.STREAM_MUSIC);
        hideSystemUi();
        /* The launcher's folder (its extra, else the one it chose last; tools
         * start this activity directly). Without a game, the launcher. */
        File game = Launcher.chosenGame(this, getIntent());
        if (game == null) {
            startActivity(new Intent(this, Launcher.class));
            finish();
            return;
        }
        base = game;
        start(new Release(game));
    }

    private Controls controls;
    private Settings settings;
    private boolean resumed, preparationFailed;
    private Thread preparation;
    private volatile boolean libraryLoaded;
    private SurfaceHolder gameSurface;
    private PreparationOverlay preparationPanel;
    private boolean startupReady;
    private final ShaderCache.NativeWork nativePreparation = new ShaderCache.NativeWork();
    private volatile int preparationPhase, cacheCompleted, cacheTotal;
    private final Runnable preparationTick = this::updatePreparation;
    private long reportedMissingShader;
    /* The overlay holds the screen (startup, the main menu's preparation):
     * the layer is paused under it. In play it is a badge only. */
    private boolean preparationBlocking = true;

    void applyPortSettings() {
        nativeSetGameplayOptions(settings.fieldOfView, settings.veinBrightness);
        nativeConsoleCommand("setting PortTouchInput " + ((controls != null ? controls.touchAdaptations() : settings.touchAdaptations) ? "1" : "0"));
        /* Head bobbing is read from the game's own Settings by a player.bin
         * patch (per jump), so a change must reach the live Settings, not only
         * settings.xml: the layer's own menu otherwise left it untouched and
         * the switch seemed to do nothing. */
        nativeConsoleCommand("setting PortHeadBob " + (settings.headBob ? "1" : "0"));
    }

    /* The touch layout's editor holds the game still (its clock and its
     * sound, as in the background) until it closes. */
    private boolean frozen;

    void freezeGame(boolean on) {
        frozen = on;
        if (started && resumed) nativePause(on);
    }

    void showDebugCommands() {
        if (!started || !settings.debugCommands) return;
        DebugCommands.show(this, controls::runDebugCommand);
    }

    /** The level/teleport list alone, reachable from the menu hold without the
     *  full debug console (the "/go" command works regardless of the toggle). */
    void showLevelSelection() {
        if (!started) return;
        DebugCommands.showLevels(this, controls::runDebugCommand);
    }

    private void start(Release release) {
        android.util.Log.i("TheVoid", "game: " + release.label() + " in " + release.dir);
        settings = new Settings(this);
        Settings.gameLanguage = release.language;
        Settings.legacyGame = release.library.equals("void_tension");
        /* The picture fills the display, the camera cutout too (the columns
         * keep clear of it): the render size follows the display. */
        if (android.os.Build.VERSION.SDK_INT >= 28) {
            WindowManager.LayoutParams lp = getWindow().getAttributes();
            lp.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
            getWindow().setAttributes(lp);
        }
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        /* MIUI's dark mode for other apps recolours views one by one (white
         * icons turned grey, dark discs light): the layer keeps its colours. */
        if (android.os.Build.VERSION.SDK_INT >= 29) root.setForceDarkAllowed(false);
        SurfaceView surface = new SurfaceView(this);
        surface.getHolder().addCallback(this);
        root.addView(surface, new FrameLayout.LayoutParams(-1, -1));
        showPreparation(root);
        setContentView(root);
        hideSystemUi();
        /* Testing: another user folder, a fresh profile whose saves are apart
         * from the player's (am start ... --es userdata NAME). */
        String userdata = getIntent() != null ? getIntent().getStringExtra("userdata") : null;
        if (userdata == null || !userdata.matches("userdata-[A-Za-z0-9_]+")) userdata = "userdata";
        File data = new File(base, userdata);
        prepareAssets(release, data, root);
    }

    private void prepareAssets(Release release, File data, FrameLayout root) {
        preparationFailed = false;
        preparationPhase = cacheCompleted = cacheTotal = 0;
        preparationPanel.post(preparationTick);
        preparation = new Thread(() -> {
            try {
                Profile.migrate(new File(Launcher.baseDir(), data.getName()), data);
                if (!data.isDirectory() && !data.mkdirs()) throw new java.io.IOException("cannot create " + data);
                if (!libraryLoaded) {
                    /* Unpacked from the APK on the first start of a build; a pushed
                     * development library takes precedence (NativeLibrary). */
                    NativeLibrary.load(this, release.library);
                    libraryLoaded = true;
                    runOnUiThread(() -> {
                        if (!isFinishing() && !isDestroyed() && gameSurface != null)
                            nativeSurface(gameSurface.getSurface());
                    });
                }
                if (Thread.currentThread().isInterrupted()) return;
                java.util.Set<String> overrides = ScriptOverrides.install(this, release.dir, data);
                if (Thread.currentThread().isInterrupted()) return;
                preparationPhase = 1;
                ShaderCache.install(this, getFilesDir(), (done, total) -> { cacheCompleted = done; cacheTotal = total; });
                if (Thread.currentThread().isInterrupted()) return;
                preparationPhase = 2;
                File images = Images.dir(this, Launcher.baseDir(), release.images);
                if (Thread.currentThread().isInterrupted()) return;
                runOnUiThread(() -> {
                    if (isFinishing() || isDestroyed()) return;
                    preparation = null;
                    startPrepared(release, data, root, overrides, images);
                });
            } catch (java.io.IOException | LinkageError e) {
                android.util.Log.e("TheVoid", "startup preparation failed", e);
                runOnUiThread(() -> {
                    if (isFinishing() || isDestroyed()) return;
                    preparation = null;
                    preparationFailed = true;
                    preparationPanel.removeCallbacks(preparationTick);
                    showPreparationDialog(startupText("Preparation failed", "Ошибка подготовки",
                            "Vorbereitung fehlgeschlagen", "Przygotowanie nie powiodło się"),
                        startupText("Could not prepare the game files. Please try again.", "Не удалось подготовить файлы игры. Попробуйте ещё раз.",
                            "Die Spieldateien konnten nicht vorbereitet werden. Bitte versuchen Sie es erneut.", "Nie udało się przygotować plików gry. Spróbuj ponownie."),
                        startupText("Retry", "Повторить", "Erneut versuchen", "Ponów"), () -> prepareAssets(release, data, root),
                        startupText("Back", "Назад", "Zurück", "Wstecz"), this::finish);
                });
            }
        }, "void-prepare");
        preparation.start();
    }

    private void startPrepared(Release release, File data, FrameLayout root, java.util.Set<String> overrides, File images) {
        String eng = Release.attribute(Release.read(new File(release.dir, "data/info.xml")), "EngTitle");
        File profileDir = new File(data, "ProgramData/Ice-pick Lodge/" + (eng.isEmpty() ? "Void" : eng));
        profileDir.mkdirs();
        /* The port's patched scripts for this release (the options menu's
         * pages of the port's settings, skipping the opening videos, the
         * head bobbing switch): with the menu, the game's Settings hold the
         * port's settings; the layer only makes sure they all exist. */
        boolean nativeMenu = overrides.contains("Scripts\\ui\\main_menu.bin");
        File gameSettings = new File(data, "overrides/settings.xml");
        Profile.ensureSettings(new File(release.dir, "data/settings.xml"), gameSettings, settings.gameProps());
        if (nativeMenu) {
            settings.loadFromGame(gameSettings);
            /* An interface scale beyond the slider's end (it went to 200 %
             * while it scaled only the text) is written back as used. */
            String ui = Profile.prop(Release.read(gameSettings), "PortUIScale");
            String used = Integer.toString(Math.round(settings.uiScale * 100));
            if (!ui.isEmpty() && !ui.equals(used)) {
                java.util.Map<String, String> fix = new java.util.HashMap<>();
                fix.put("PortUIScale", used);
                Profile.setProps(gameSettings, fix);
            }
        } else {
            Profile.setProps(gameSettings, settings.gameProps());
        }
        /* Runtime input mode must never overwrite the player's touch preference. */
        Profile.setProps(gameSettings, java.util.Collections.singletonMap("PortTouchInput", settings.touchAdaptations ? "1" : "0"));
        if (!settings.sensitivityDefaulted) {
            Profile.defaultSensitivity(gameSettings);
            settings.sensitivityDefaulted = true;
            settings.save();
        }
        /* What Config.exe would have written, from the additional settings:
         * read by the game as it starts. */
        android.graphics.Point real = new android.graphics.Point();
        getWindowManager().getDefaultDisplay().getRealSize(real);
        int[] size = settings.renderSize(real.x, real.y);
        /* The game is told a smaller screen when its interface is to look
         * larger; its picture is still drawn at the render size. */
        int[] game = settings.gameSize(real.x, real.y, getResources().getDisplayMetrics().density);
        Profile.writeRenderer(profileDir, game[0], game[1], settings);
        Profile.writeSound(profileDir, settings);
        /* The port's actions.xml skips on Enter (tools/patch_scripts.py). */
        File actionsXml = overrides.contains("actions.xml") ? new File(data, "overrides/actions.xml")
            : new File(release.dir, "data/actions.xml");
        controls = new Controls(this, settings, new Haptics(this), gameSettings,
            Profile.actions(actionsXml, gameSettings), settings.startKey(), nativeMenu, release.library.equals("void_tension"));
        root.addView(controls, new FrameLayout.LayoutParams(-1, -1));
        preparationPanel.bringToFront();
        if (android.os.Build.VERSION.SDK_INT >= 28) {
            root.setOnApplyWindowInsetsListener((v, insets) -> {
                android.view.DisplayCutout cut = insets.getDisplayCutout();
                /* The holes in the layer's own coordinates (it fills the window). */
                java.util.List<android.graphics.RectF> holes = new java.util.ArrayList<>();
                int[] at = new int[2];
                controls.getLocationInWindow(at);
                if (cut != null) for (android.graphics.Rect r : cut.getBoundingRects())
                    if (!r.isEmpty()) holes.add(new android.graphics.RectF(r.left - at[0], r.top - at[1], r.right - at[0], r.bottom - at[1]));
                controls.setInsets(cut != null ? cut.getSafeInsetLeft() : 0, cut != null ? cut.getSafeInsetRight() : 0, holes);
                return insets;
            });
            root.requestApplyInsets();
        }
        hideSystemUi();
        if (resumed && !preparationBlocking) controls.resume();
        controls.setRenderSize(game[0], game[1]);
        android.util.Log.i("TheVoid", "render size " + size[0] + "x" + size[1] + " for a display of " + real.x + "x" + real.y
            + "; the game's screen " + game[0] + "x" + game[1]);
        /* The game's text is in pixels: at 100% it keeps the size it has at a
         * render height of 540 whatever the render scale, times the interface scale. */
        nativeSetFontScale(1f);
        nativeSetPhysicalSize(size[0], size[1]);
        /* The physics steps at the display's fastest rate (a game draws at it). */
        float hz = getWindowManager().getDefaultDisplay().getRefreshRate();
        if (android.os.Build.VERSION.SDK_INT >= 23)
            for (android.view.Display.Mode m : getWindowManager().getDefaultDisplay().getSupportedModes())
                if (m.getPhysicalHeight() == getWindowManager().getDefaultDisplay().getMode().getPhysicalHeight())
                    hz = Math.max(hz, m.getRefreshRate());
        nativeSetDisplayRate(hz);
        nativeSetGameplayOptions(settings.fieldOfView, settings.veinBrightness);
        android.util.Log.i("TheVoid", "display refresh up to " + hz + " Hz");
        started = running = nativeStart(release.dir.getAbsolutePath(), data.getAbsolutePath(),
                images.getAbsolutePath(), new File(getFilesDir(), "shadercache").getAbsolutePath(),
                game[0], game[1], new File(base, "verbose").exists());
        if (!started) {
            preparationFailed = true;
            String title = startupText("Could not start the game", "Не удалось запустить игру",
                "Das Spiel konnte nicht gestartet werden", "Nie można uruchomić gry");
            preparationPanel.update(title, "", 0, 0);
            preparationPanel.removeCallbacks(preparationTick);
            controls.pause();
            showPreparationDialog(title, "", startupText("Retry", "Повторить", "Erneut versuchen", "Ponów"), this::restart,
                startupText("Back", "Назад", "Zurück", "Wstecz"), this::finish);
            return;
        }
        if (!resumed) nativePause(true);
        preparationPhase = 3;
    }

    private void showPreparation(FrameLayout root) {
        preparationPanel = new PreparationOverlay(this);
        root.addView(preparationPanel, new FrameLayout.LayoutParams(-1, -1));
        updatePreparation();
    }

    private void updatePreparation() {
        if (preparationPanel == null || preparationFailed || isFinishing() || isDestroyed()) return;
        int phase = preparationPhase, completed = 0, total = 0;
        String title, detail;
        if (phase == 3) {
            long now = android.os.SystemClock.elapsedRealtime();
            /* A shader the cache lacks leaves an effect undrawn, as a failed
             * compile would on Windows; play goes on (a restart would not
             * bring it): noted in the log once. */
            long missing = nativeMissingShader();
            if (missing != 0 && missing != reportedMissingShader) {
                reportedMissingShader = missing;
                android.util.Log.w("TheVoid", "scene shader unavailable: " + Long.toHexString(missing));
            }
            long hud = nativeHudState();
            long progress = nativeShaderProgress(), warmup = nativeShaderWarmup();
            boolean menu = (hud & 0x100000) != 0;
            if (!startupReady && (hud & (0x2000 | 0x100000)) != 0) {
                startupReady = true;
                nativePreparation.reset();
            }
            boolean video = (hud & 0x800000) != 0;
            /* Cached HLSL replies also advance during ordinary scene loading. */
            boolean stalledWork = nativePreparation.update(now, hud >>> 32, progress >>> 32, video);
            /* A direct save load can pass the menu between polls. Advancing
             * nonloading frames and settled work also finish startup. */
            if (!startupReady && !video && (hud & 0x20000) == 0 && (hud >>> 32) != 0
                    && nativePreparation.settled(now)) startupReady = true;
            total = (int)(warmup >>> 32);
            completed = (int)warmup;
            boolean warming = total > 0 && completed < total;
            boolean visible = warming || menu && total == 0 || (startupReady ? stalledWork : !video || stalledWork);
            /* Once the main menu is reachable the preparation is only a badge:
             * the native warm loop is time-sliced on the present thread, so the
             * menu (and play) stay interactive while it finishes. Blocking is
             * kept solely before the menu first appears (!startupReady); the
             * in-menu warm/scan and scene-load stalls run behind the badge. */
            setPreparationVisible(visible, !startupReady);
            if (!visible) {
                if (resumed) preparationPanel.postDelayed(preparationTick, 250);
                return;
            }
            title = startupText("Preparing graphics", "Подготовка графики", "Grafik wird vorbereitet", "Przygotowywanie grafiki");
            if (warming || menu && total == 0) {
                detail = startupText("Preparing in the main menu", "Подготовка в главном меню", "Vorbereitung im Hauptmenü", "Przygotowywanie w menu głównym");
                if (total > 0) detail += "  ·  " + (100L * completed / total) + "%";
            } else {
                total = 0;
                detail = startupText("Please wait", "Пожалуйста, подождите", "Bitte warten", "Proszę czekać");
            }
        } else if (phase == 1) {
            title = startupText("Preparing graphics", "Подготовка графики", "Grafik wird vorbereitet", "Przygotowywanie grafiki");
            total = cacheTotal;
            completed = Math.min(cacheCompleted, total);
            detail = total > 0 ? (100L * completed / total) + "%"
                : startupText("Please wait", "Пожалуйста, подождите", "Bitte warten", "Proszę czekać");
        } else {
            title = startupText("Preparing game files", "Подготовка файлов игры", "Spieldateien werden vorbereitet", "Przygotowywanie plików gry");
            detail = startupText("Please wait", "Пожалуйста, подождите", "Bitte warten", "Proszę czekać");
            /* The first start of a build unpacks the game's code (a few seconds). */
            long[] unpacked = NativeLibrary.progress();
            if (unpacked != null) {
                total = 1000;
                completed = (int) (1000 * unpacked[0] / unpacked[1]);
                title = startupText("Unpacking the game's code", "Распаковка кода игры", "Spielcode wird entpackt",
                    "Rozpakowywanie kodu gry");
                detail = (completed / 10) + "%";
            }
        }
        preparationPanel.update(title, detail, completed, total);
        if (resumed) preparationPanel.postDelayed(preparationTick, 200);
    }

    private void setPreparationVisible(boolean visible, boolean blocking) {
        boolean wasBlocking = preparationBlocking;
        preparationBlocking = visible && blocking;
        preparationPanel.setVisibility(visible ? View.VISIBLE : View.GONE);
        preparationPanel.setClickable(preparationBlocking);   /* a badge lets touches through */
        if (started && resumed && controls != null && preparationBlocking != wasBlocking) {
            if (preparationBlocking) controls.pause(); else controls.resume();
        }
    }

    private static String startupText(String en, String ru, String de, String pl) {
        String language = Settings.gameLanguage.toLowerCase(java.util.Locale.ROOT);
        if (language.isEmpty()) language = java.util.Locale.getDefault().getLanguage();
        return language.startsWith("ru") || language.equals("uk") || language.equals("be") ? ru
            : language.startsWith("de") || language.startsWith("german") ? de
            : language.startsWith("pl") || language.startsWith("polish") ? pl : en;
    }

    private AlertDialog showPreparationDialog(String title, String message, String positive, Runnable retry,
            String negative, Runnable back) {
        float density = getResources().getDisplayMetrics().density;
        int pad = Math.round(24 * density);
        Typeface serif = Typeface.create("serif", Typeface.NORMAL);
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(pad, pad, pad, pad / 2);
        TextView heading = new TextView(this);
        heading.setTypeface(serif);
        heading.setTextColor(0xFFF0E8D4);
        heading.setTextSize(24);
        heading.setText(title);
        content.addView(heading);
        if (!message.isEmpty()) {
            TextView body = new TextView(this);
            body.setTypeface(serif);
            body.setTextColor(0xFFBEB7A6);
            body.setTextSize(17);
            body.setText(message);
            body.setPadding(0, pad / 2, 0, 0);
            content.addView(body);
        }
        AlertDialog dialog = new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
            .setView(content).setCancelable(false)
            .setPositiveButton(positive, (d, which) -> retry.run())
            .setNegativeButton(negative, (d, which) -> back.run()).create();
        dialog.show();
        GradientDrawable background = new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,
            new int[] {0xF51A1713, 0xFA080608});
        background.setStroke(Math.max(1, Math.round(density)), 0xFF6C6250);
        dialog.getWindow().setBackgroundDrawable(background);
        dialog.getWindow().getDecorView().setSystemUiVisibility(getWindow().getDecorView().getSystemUiVisibility());
        for (int which : new int[] {AlertDialog.BUTTON_POSITIVE, AlertDialog.BUTTON_NEGATIVE}) {
            android.widget.Button button = dialog.getButton(which);
            button.setTypeface(serif);
            button.setAllCaps(false);
            button.setTextSize(17);
            button.setTextColor(0xFFE1D3B1);
            button.setBackground(new android.graphics.drawable.RippleDrawable(android.content.res.ColorStateList.valueOf(0x40E1D3B1),
                new android.graphics.drawable.ColorDrawable(Color.TRANSPARENT), null));
        }
        return dialog;
    }

    /** Settings the game reads as it starts take a new process: the lifted
     *  game runs once per process. RestartActivity (its own process) ends
     *  this one and opens the game again. */
    void restart() { restart(false); }

    private void restart(boolean launcher) {
        android.content.Intent i = new android.content.Intent(this, RestartActivity.class);
        i.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK);
        i.putExtra(RestartActivity.PID, android.os.Process.myPid());
        i.putExtra(RestartActivity.LAUNCHER, launcher);
        if (getIntent() != null) {
            i.putExtra(Launcher.EXTRA_GAME, getIntent().getStringExtra(Launcher.EXTRA_GAME));
            i.putExtra("userdata", getIntent().getStringExtra("userdata"));
        }
        startActivity(i);
    }

    private void hideSystemUi() {
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN);
        /* Android 11+: the flags above are not enough for the status bar. */
        if (android.os.Build.VERSION.SDK_INT >= 30) {
            android.view.WindowInsetsController c = getWindow().getInsetsController();
            if (c != null) {
                c.hide(android.view.WindowInsets.Type.systemBars());
                c.setSystemBarsBehavior(android.view.WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            }
        }
    }

    /* Coming back from another app shows the system bars again. */
    @Override public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) hideSystemUi();
        if (started) controls.hardwareFocus(hasFocus);
    }

    /** Back is the game's Escape (its menu, or closing a screen); the
     *  layer's own menu closes first. */
    @Override public void onBackPressed() {
        if (!started) { super.onBackPressed(); return; }
        if (preparationBlocking) return;
        if (controls.panelVisible()) { controls.closePanel(); return; }
        controls.escape();
    }

    /** A hardware keyboard or game controller plays as the original keys. */
    @Override public boolean dispatchKeyEvent(android.view.KeyEvent e) {
        int code = e.getKeyCode();
        if (started && preparationBlocking
                && code != android.view.KeyEvent.KEYCODE_VOLUME_UP && code != android.view.KeyEvent.KEYCODE_VOLUME_DOWN) return true;
        if (started && (code != android.view.KeyEvent.KEYCODE_BACK || HardwareInput.controller(e)) && controls.hardwareKey(e))
            return true;
        return super.dispatchKeyEvent(e);
    }

    @Override public boolean dispatchGenericMotionEvent(android.view.MotionEvent e) {
        if (started && preparationBlocking) return true;
        if (started && controls.hardwareMotion(e))
            return true;
        return super.dispatchGenericMotionEvent(e);
    }

    @Override public boolean dispatchTouchEvent(android.view.MotionEvent e) {
        if (started && HardwareInput.mouseEvent(e)) {
            if (preparationBlocking) return true;
            if (controls.hardwareMotion(e)) return true;
        }
        return super.dispatchTouchEvent(e);
    }

    @Override public void surfaceCreated(SurfaceHolder holder) {
        gameSurface = holder;
        if (libraryLoaded) nativeSurface(holder.getSurface());
    }
    @Override public void surfaceChanged(SurfaceHolder holder, int format, int w, int h) { }
    @Override public void surfaceDestroyed(SurfaceHolder holder) {
        gameSurface = null;
        if (libraryLoaded) nativeSurface(null);
    }

    private long pausedAt;

    @Override protected void onPause() {
        resumed = false;
        nativePreparation.reset();
        if (preparationPanel != null) preparationPanel.removeCallbacks(preparationTick);
        if (started) {
            controls.pause();
            nativePause(true);   /* the game's clock stops too */
            pausedAt = android.os.SystemClock.uptimeMillis();
        }
        super.onPause();
    }

    @Override protected void onResume() {
        super.onResume();
        resumed = true;
        if (preparationPanel != null) {
            preparationPanel.removeCallbacks(preparationTick);
            preparationPanel.post(preparationTick);
        }
        if (started) {
            nativePause(frozen);
            if (!preparationBlocking) {
                controls.resume();
                if (pausedAt > 0) controls.cameBack(android.os.SystemClock.uptimeMillis() - pausedAt);
            }
            pausedAt = 0;
        }
    }

    @Override protected void onDestroy() {
        if (preparation != null) preparation.interrupt();
        if (preparationPanel != null) preparationPanel.removeCallbacks(preparationTick);
        super.onDestroy();
    }
}
