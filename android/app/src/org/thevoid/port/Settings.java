package org.thevoid.port;

import android.content.Context;
import android.content.SharedPreferences;
import java.io.File;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;

/** The port's settings. Where the game's options menu carries the port's
 *  pages (a patched ui/main_menu.bin), they live in the game's own Settings
 *  (its data\settings.xml, the player's copy: keys Port*) and the menu
 *  changes them; the layer reads them back. Elsewhere (the 2008 Polish
 *  release) the layer's
 *  own menu keeps them in SharedPreferences. Look speed and inversion are the
 *  game's own MouseSensitivity and InvertMouse: the camera turns by mouse
 *  motion, which the game scales and inverts. */
final class Settings {
    /* The camera turns 1 degree per 9.05 pixels of mouse motion at the game's
     * MouseSensitivity 0.192621 (measured): 1.7432 pixels a degree at 1. */
    static final float PIXELS_PER_DEGREE = 9.05f * 0.192621f;
    /* A swipe turns the camera 0.25 degree per dp at MouseSensitivity 1. */
    static final float SWIPE_DEGREES_PER_DP = 0.25f;
    static final int PICK_STRIP = 0, PICK_FAN = 1, PICK_BOTH = 2;
    /* The game's own look settings (its options): mouse motion turns the
     * camera by MouseSensitivity / PIXELS_PER_DEGREE degrees a pixel, upside
     * down with InvertMouse. */
    float mouseSensitivity = 1f;
    boolean invertMouse;

    private final SharedPreferences prefs;
    float gyroSpeed;       /* camera degrees per degree the device turns, at MouseSensitivity 1 */
    float buttonScale, buttonOpacity;
    boolean gyro, leftHanded, runAtEdge, vibration;
    /* Additional settings. Render scale, the interface scale and the
     * configurator's values apply when the game starts. The picture always
     * fills the screen (Hor+). */
    boolean skipIntro, hideCursor, headBob;
    boolean lookAccel;     /* quick swipes turn further */
    boolean invertGyroVertical;   /* the gyroscope's vertical look inverted (default on); horizontal is always inverted */
    boolean touchHelpShown;   /* the gestures were shown once (the main menu's first coming) */
    int colorPicker;       /* PICK_*: how a colour is chosen for painting */
    float fieldOfView, veinBrightness;
    boolean debugCommands, touchAdaptations, showMenuButton, showActionButton, showMenuLabels;
    boolean showBodyButton;   /* the hearts' button (the body opens from its corner too) */
    float renderScale;     /* of the screen's height, 0.5..1.5 */
    float uiScale;         /* the game's interface, 0.7..1.5: the size it lays out in (gameSize) */
    float subtitleSize, textSize;
    boolean textContrast;
    int hdr;               /* 0 off, 1 simplified, 2 full; all use SM3 strategies. */
    int anisotropy;        /* 0 (off), 2, 4, 8, 16; 4 by default (16 cost the Adreno 618 a third of its frames) */
    int textureQuality;    /* 0 high, 1 low (the configurator's values) */
    int lightmapQuality;   /* 0 high, 1 medium, 2 low */
    int soundRate;         /* 22 or 44 kHz */
    int fpsLimit;          /* frames a second at most: one of the display's refresh rates; 0 its fastest */
    boolean reflections;   /* water mirrors drawn (off: their reflection is black) */
    boolean sensitivityDefaulted;   /* the game's MouseSensitivity was set to 1 once (in data\settings.xml) */
    boolean anisotropyDefaulted;    /* the earlier default filtering, x16, went to x4 once */

    Settings(Context c) {
        prefs = c.getSharedPreferences("touch", Context.MODE_PRIVATE);
        gyroSpeed = prefs.getFloat("gyroSpeed", 1.0f);
        buttonScale = prefs.getFloat("buttonScale", 1.0f);
        buttonOpacity = prefs.getFloat("buttonOpacity", 0.6f);
        gyro = prefs.getBoolean("gyro", false);
        leftHanded = prefs.getBoolean("leftHanded", false);
        runAtEdge = prefs.getBoolean("runAtEdge", true);
        vibration = prefs.getBoolean("vibration", true);
        skipIntro = prefs.getBoolean("skipIntro", false);
        hideCursor = prefs.getBoolean("hideCursor", true);
        headBob = prefs.getBoolean("headBob", false);
        lookAccel = prefs.getBoolean("lookAccel", true);
        invertGyroVertical = prefs.getBoolean("gyroInvertV", true);
        colorPicker = prefs.getInt("colorPicker", PICK_BOTH);
        fieldOfView = bounded(prefs.getFloat("fieldOfView", 55f), 55f, 40f, 100f);
        veinBrightness = bounded(prefs.getFloat("veinBrightness", 1f), 1f, 1f, 5f);
        debugCommands = prefs.getBoolean("debugCommands", false);
        touchAdaptations = prefs.getBoolean("touchAdaptations", true);
        showMenuButton = prefs.getBoolean("showMenuButton", true);
        showMenuLabels = prefs.getBoolean("showMenuLabels", true);
        showActionButton = prefs.getBoolean("showActionButton", false);
        showBodyButton = prefs.getBoolean("showBodyButton", true);
        renderScale = prefs.getFloat("renderScale", 1.0f);
        uiScale = prefs.getFloat("uiScale", 1.0f);
        subtitleSize = bounded(prefs.getFloat("subtitleSize", 1f), 1f, 1f, 1.5f);
        textSize = bounded(prefs.getFloat("textSize", 1f), 1f, 1f, 1.5f);
        textContrast = prefs.getBoolean("textContrast", true);
        hdr = Math.max(0, Math.min(2, prefs.getInt("hdr", 2)));
        anisotropy = prefs.getInt("anisotropy", 4);
        textureQuality = prefs.getInt("textureQuality", 0);
        lightmapQuality = Math.max(0, Math.min(2, prefs.getInt("lightmapQuality", 0)));
        soundRate = prefs.getInt("soundRate", 44);
        fpsLimit = Math.max(0, prefs.getInt("fpsLimit", 0));
        reflections = prefs.getBoolean("reflections", true);
        sensitivityDefaulted = prefs.getBoolean("gameSensitivityDefaulted", false);
        anisotropyDefaulted = prefs.getBoolean("anisotropyDefaulted4", false);
        touchHelpShown = prefs.getBoolean("touchHelpShown", false);
    }

    void save() {
        prefs.edit().putFloat("gyroSpeed", gyroSpeed)
            .putFloat("buttonScale", buttonScale).putFloat("buttonOpacity", buttonOpacity)
            .putBoolean("gyro", gyro).putBoolean("leftHanded", leftHanded).putBoolean("runAtEdge", runAtEdge)
            .putBoolean("vibration", vibration).putBoolean("skipIntro", skipIntro).putBoolean("hideCursor", hideCursor)
            .putBoolean("headBob", headBob).putBoolean("lookAccel", lookAccel)
            .putBoolean("gyroInvertV", invertGyroVertical).putInt("colorPicker", colorPicker)
            .putFloat("fieldOfView", fieldOfView).putFloat("veinBrightness", veinBrightness)
            .putBoolean("debugCommands", debugCommands).putBoolean("touchAdaptations", touchAdaptations)
            .putBoolean("showMenuButton", showMenuButton).putBoolean("showActionButton", showActionButton)
            .putBoolean("showMenuLabels", showMenuLabels)
            .putBoolean("showBodyButton", showBodyButton).putFloat("renderScale", renderScale).putFloat("uiScale", uiScale).putInt("hdr", hdr)
            .putFloat("subtitleSize", subtitleSize).putFloat("textSize", textSize).putBoolean("textContrast", textContrast)
            .putInt("anisotropy", anisotropy).putInt("textureQuality", textureQuality)
            .putInt("lightmapQuality", lightmapQuality).putInt("soundRate", soundRate).putInt("fpsLimit", fpsLimit)
            .putBoolean("reflections", reflections)
            .putBoolean("gameSensitivityDefaulted", sensitivityDefaulted)
            .putBoolean("anisotropyDefaulted4", anisotropyDefaulted)
            .putBoolean("touchHelpShown", touchHelpShown).apply();
    }

    /** The props of the game's Settings that carry these values. */
    Map<String, String> gameProps() {
        Map<String, String> m = new LinkedHashMap<>();
        m.put("PortGyro", b(gyro));
        m.put("PortGyroSpeed", String.format(Locale.ROOT, "%.1f", gyroSpeed));
        m.put("PortButtonSize", Integer.toString(Math.round(buttonScale * 100)));
        m.put("PortButtonOpacity", Integer.toString(Math.round(buttonOpacity * 100)));
        m.put("PortLeftHanded", b(leftHanded));
        m.put("PortRunEdge", b(runAtEdge));
        m.put("PortVibration", b(vibration));
        m.put("PortSkipIntro", b(skipIntro));
        m.put("PortHideCursor", b(hideCursor));
        m.put("PortHeadBob", b(headBob));
        m.put("PortLookAccel", b(lookAccel));
        m.put("PortGyroInvertV", b(invertGyroVertical));
        m.put("PortPicker", Integer.toString(colorPicker));
        m.put("PortFOV", Integer.toString(Math.round(fieldOfView)));
        m.put("PortVeinBrightness", Integer.toString(Math.round(veinBrightness * 100)));
        m.put("PortDebugCommands", b(debugCommands));
        m.put("PortTouchAdaptations", b(touchAdaptations));
        m.put("PortBodyPut", "0");
        m.put("PortShowMenuButton", b(showMenuButton));
        m.put("PortShowMenuLabels", b(showMenuLabels));
        m.put("PortShowActionButton", b(showActionButton));
        m.put("PortShowBodyButton", b(showBodyButton));
        m.put("PortRenderScale", Integer.toString(Math.round(renderScale * 100)));
        m.put("PortUIScale", Integer.toString(Math.round(uiScale * 100)));
        m.put("PortSubtitleSize", Integer.toString(Math.round(subtitleSize * 100)));
        m.put("PortTextSize", Integer.toString(Math.round(textSize * 100)));
        m.put("PortTextContrast", b(textContrast));
        m.put("PortHDR", Integer.toString(hdr));
        m.put("PortAnisotropy", Integer.toString(anisotropy));
        m.put("PortTextureQuality", Integer.toString(textureQuality));
        m.put("PortLightmapQuality", Integer.toString(lightmapQuality));
        m.put("PortSoundRate", Integer.toString(soundRate));
        m.put("PortReflections", b(reflections));
        return m;
    }

    /** The game's look settings, as its options left them. */
    void loadLook(File settingsXml) {
        String xml = GameActivity.Release.read(settingsXml);
        if (xml.isEmpty()) return;
        mouseSensitivity = readF(xml, "MouseSensitivity", mouseSensitivity, 0.01f, 20f);
        invertMouse = readB(xml, "InvertMouse", invertMouse);
    }

    /** Takes the values the game's Settings hold (props that are present). */
    void loadFromGame(File settingsXml) {
        String xml = GameActivity.Release.read(settingsXml);
        if (xml.isEmpty()) return;
        gyro = readB(xml, "PortGyro", gyro);
        gyroSpeed = readF(xml, "PortGyroSpeed", gyroSpeed, 0.1f, 3f);
        buttonScale = readPercent(xml, "PortButtonSize", buttonScale, 70, 150);
        buttonOpacity = readPercent(xml, "PortButtonOpacity", buttonOpacity, 25, 95);
        leftHanded = readB(xml, "PortLeftHanded", leftHanded);
        runAtEdge = readB(xml, "PortRunEdge", runAtEdge);
        vibration = readB(xml, "PortVibration", vibration);
        skipIntro = readB(xml, "PortSkipIntro", skipIntro);
        hideCursor = readB(xml, "PortHideCursor", hideCursor);
        headBob = readB(xml, "PortHeadBob", headBob);
        lookAccel = readB(xml, "PortLookAccel", lookAccel);
        invertGyroVertical = readB(xml, "PortGyroInvertV", invertGyroVertical);
        colorPicker = readI(xml, "PortPicker", colorPicker, 0, 2);
        fieldOfView = readF(xml, "PortFOV", fieldOfView, 40f, 100f);
        veinBrightness = readF(xml, "PortVeinBrightness", veinBrightness * 100, 100, 500) / 100f;
        debugCommands = readB(xml, "PortDebugCommands", debugCommands);
        touchAdaptations = readB(xml, "PortTouchAdaptations", touchAdaptations);
        showMenuButton = readB(xml, "PortShowMenuButton", showMenuButton);
        showMenuLabels = readB(xml, "PortShowMenuLabels", showMenuLabels);
        showActionButton = readB(xml, "PortShowActionButton", showActionButton);
        showBodyButton = readB(xml, "PortShowBodyButton", showBodyButton);
        renderScale = readI(xml, "PortRenderScale", Math.round(renderScale * 100), 50, 150) / 100f;
        uiScale = readI(xml, "PortUIScale", Math.round(uiScale * 100), 70, 150) / 100f;
        subtitleSize = readF(xml, "PortSubtitleSize", subtitleSize * 100, 100, 150) / 100f;
        textSize = readF(xml, "PortTextSize", textSize * 100, 100, 150) / 100f;
        textContrast = readB(xml, "PortTextContrast", textContrast);
        hdr = readI(xml, "PortHDR", hdr, 0, 2);
        anisotropy = readI(xml, "PortAnisotropy", anisotropy, 0, 16);
        textureQuality = readI(xml, "PortTextureQuality", textureQuality, 0, 1);
        lightmapQuality = readI(xml, "PortLightmapQuality", lightmapQuality, 0, 2);
        soundRate = readI(xml, "PortSoundRate", soundRate, 22, 44) < 33 ? 22 : 44;
        reflections = readB(xml, "PortReflections", reflections);
    }

    private static String b(boolean v) { return v ? "1" : "0"; }
    private static String f(float v) { return String.format(Locale.ROOT, "%.3f", v); }

    private static boolean readB(String xml, String key, boolean def) {
        String v = Profile.prop(xml, key);
        return v.isEmpty() ? def : !v.equals("0") && !v.equalsIgnoreCase("false");
    }

    private static float readF(String xml, String key, float def, float min, float max) {
        try {
            float v = Float.parseFloat(Profile.prop(xml, key));
            return bounded(v, def, min, max);
        } catch (RuntimeException e) {
            return def;
        }
    }

    private static float bounded(float value, float def, float min, float max) {
        return Float.isNaN(value) || Float.isInfinite(value) ? def : Math.max(min, Math.min(max, value));
    }

    /** A percentage (the options page's sliders) as a factor; earlier
     *  versions wrote the factor itself. */
    private static float readPercent(String xml, String key, float def, int min, int max) {
        try {
            float v = Float.parseFloat(Profile.prop(xml, key));
            if (v <= 3f) v *= 100f;
            return Math.max(min, Math.min(max, Math.round(v))) / 100f;
        } catch (RuntimeException e) {
            return def;
        }
    }

    private static int readI(String xml, String key, int def, int min, int max) {
        try {
            int v = Math.round(Float.parseFloat(Profile.prop(xml, key)));
            return Math.max(min, Math.min(max, v));
        } catch (RuntimeException e) {
            return def;
        }
    }

    /** The values the game reads when it starts: a change of these asks for a restart. */
    String startKey() {
        return Math.round(renderScale * 10) + "/" + Math.round(uiScale * 10) + "/" + hdr + "/"
            + anisotropy + "/" + textureQuality + "/" + lightmapQuality + "/" + soundRate
            + "/" + Math.round(subtitleSize * 100) + "/" + Math.round(textSize * 100) + "/" + textContrast;
    }

    /** The refresh rates the display offers at its present resolution, whole
     *  hertz, fastest first: the frame limits there are to choose from. */
    static int[] refreshRates(android.view.Display display) {
        java.util.TreeSet<Integer> rates = new java.util.TreeSet<>(java.util.Collections.reverseOrder());
        android.view.Display.Mode now = display.getMode();
        for (android.view.Display.Mode m : display.getSupportedModes())
            if (m.getPhysicalWidth() == now.getPhysicalWidth() && m.getPhysicalHeight() == now.getPhysicalHeight())
                rates.add(Math.round(m.getRefreshRate()));
        rates.add(Math.round(now.getRefreshRate()));
        int[] out = new int[rates.size()];
        int i = 0;
        for (int r : rates) out[i++] = r;
        return out;
    }

    /** The display's mode at the present resolution whose refresh is `hz`, or null. */
    static android.view.Display.Mode modeFor(android.view.Display display, int hz) {
        android.view.Display.Mode now = display.getMode();
        for (android.view.Display.Mode m : display.getSupportedModes())
            if (m.getPhysicalWidth() == now.getPhysicalWidth() && m.getPhysicalHeight() == now.getPhysicalHeight()
                    && Math.round(m.getRefreshRate()) == hz)
                return m;
        return null;
    }

    /** The game's render size: the screen's height times the render scale,
     *  at the screen's aspect (Hor+: the game keeps its vertical field of
     *  view and shows more at the sides). Even sizes. */
    int[] renderSize(int screenW, int screenH) {
        int w = Math.max(screenW, screenH), h = Math.min(screenW, screenH);
        float aspect = (float) w / h;
        int rh = Math.max(360, Math.round(h * renderScale)) & ~1;
        int rw = Math.max(640, Math.round(rh * aspect)) & ~1;
        return new int[] {rw, rh};
    }

    /** The size the game is told its screen has, which its interface lays
     *  out in: its pictures and text keep their pixel sizes, so a smaller
     *  picture shows them larger. About 600 pixels high on a phone (the game
     *  was made for 600 to 1200), more on a larger screen (1.46 per dp of
     *  height, 480 to 1080), divided by the interface scale. The host draws
     *  the 3D picture at renderSize all the same (d3d_set_physical_size).
     *  Even sizes. */
    int[] gameSize(int screenW, int screenH, float density) {
        int w = Math.max(screenW, screenH), h = Math.min(screenW, screenH);
        float base = Math.max(480f, Math.min(1080f, h / Math.max(0.5f, density) * 1.46f));
        int gh = Math.max(360, Math.round(base / Math.max(0.5f, uiScale))) & ~1;
        int gw = Math.round(gh * (float) w / h) & ~1;
        return new int[] {gw, gh};
    }

    /* The layer's menus speak the release's language, else the device's (ru, de, pl; English otherwise). */
    static final int T_LOAD_ASK = 0, T_MORE = 1, T_SKIP_INTRO = 2, T_HIDE_CURSOR = 3, T_WIDE = 4,
        T_RENDER_SCALE = 5, T_UI_SCALE = 6, T_PICKER = 7, T_PICK_STRIP = 8, T_PICK_FAN = 9, T_PICK_BOTH = 10,
        T_HDR = 11, T_OFF = 12, T_SIMPLE = 13, T_FULL = 14, T_ANISO = 15, T_TEXTURES = 16, T_LIGHTING = 17,
        T_SOUND = 18, T_HIGH = 19, T_MEDIUM = 20, T_LOW = 21, T_RESTART = 22, T_RESTART_ASK = 23, T_GAME = 24,
        T_SOUND_LOW = 25, T_SOUND_HIGH = 26, T_CONTROLS = 27, T_GYRO = 28, T_GYRO_SPEED = 29, T_LEFT = 30, T_SIZE = 31,
        T_OPACITY = 32, T_RUN_EDGE = 33, T_VIBRATION = 34, T_HEAD_BOB = 35, T_SETTINGS = 36,
        T_LOOK_ACCEL = 37, T_HELP_TITLE = 38, T_HELP_FIRST = 39, HELP_LINES = 12, T_EXIT_ASK = T_HELP_FIRST + HELP_LINES,
        T_COLOUR_FIRST = T_EXIT_ASK + 1,
        T_FOV = T_COLOUR_FIRST + 7, T_VEIN_BRIGHTNESS = T_FOV + 1,
        T_TOUCH_ADAPTATIONS = T_FOV + 2, T_DEBUG_COMMANDS = T_FOV + 3,
        T_SUBTITLE_SIZE = T_FOV + 4, T_TEXT_SIZE = T_FOV + 5, T_TEXT_CONTRAST = T_FOV + 6,
        T_SHOW_MENU_BUTTON = T_FOV + 7, T_SHOW_ACTION_BUTTON = T_FOV + 8, T_SHOW_BODY_BUTTON = T_FOV + 9,
        T_DEBUG_LIST = T_FOV + 10, T_GYRO_INVERT_V = T_FOV + 11, T_IN_HAND = T_FOV + 12,
        T_LEVELS = T_FOV + 13, T_HEART = T_FOV + 14, T_PALETTE = T_FOV + 15, T_MEMORY = T_FOV + 16,
        T_TAP_PUT = T_FOV + 17, T_TAP_RETURN = T_FOV + 18,
        /* The main and pause menus' glyphs, as the game's own hover names them
         * (Properties\Strings\menu.txt main_menu_*): HUD slots 20..26, then the exit. */
        T_MENU_FIRST = T_FOV + 19, T_MENU_EXIT = T_MENU_FIRST + 7, T_SHOW_MENU_LABELS = T_MENU_EXIT + 1,
        T_REFLECTIONS = T_SHOW_MENU_LABELS + 1;
    private static final String[][] TEXTS = {
        {"Load the quick save?", "Загрузить быстрое сохранение?", "Schnellspeicherstand laden?", "Wczytać szybki zapis?"},
        {"Additional settings", "Дополнительные настройки", "Weitere Einstellungen", "Dodatkowe ustawienia"},
        {"Skip the opening videos", "Пропускать начальные ролики", "Startvideos überspringen", "Pomijaj filmy początkowe"},
        {"Hide the game's cursor", "Скрывать курсор игры", "Spielcursor ausblenden", "Ukryj kursor gry"},
        {"Wide picture (Hor+)", "Широкий экран (Hor+)", "Breitbild (Hor+)", "Szeroki obraz (Hor+)"},
        {"Render scale", "Масштаб рендеринга", "Renderskalierung", "Skala renderowania"},
        {"Interface scale", "Масштаб интерфейса", "Oberflächenskalierung", "Skala interfejsu"},
        {"Choosing a colour", "Выбор цвета", "Farbwahl", "Wybór koloru"},
        {"Strip by the brush", "Полоса у кисти", "Leiste am Pinsel", "Pasek przy pędzlu"},
        {"Fan from the brush", "Веер от кисти", "Fächer vom Pinsel", "Wachlarz z pędzla"},
        {"Both", "Оба", "Beides", "Oba"},
        {"HDR", "HDR", "HDR", "HDR"},
        {"Off", "Выкл.", "Aus", "Wył."},
        {"Simplified", "Упрощённый", "Vereinfacht", "Uproszczony"},
        {"Full", "Полный", "Voll", "Pełny"},
        {"Anisotropic filtering", "Анизотропная фильтрация", "Anisotrope Filterung", "Filtrowanie anizotropowe"},
        {"Texture quality", "Качество текстур", "Texturqualität", "Jakość tekstur"},
        {"Lighting quality", "Качество освещения", "Beleuchtungsqualität", "Jakość oświetlenia"},
        {"Sound quality", "Качество звука", "Tonqualität", "Jakość dźwięku"},
        {"High", "Высокое", "Hoch", "Wysoka"},
        {"Medium", "Среднее", "Mittel", "Średnia"},
        {"Low", "Низкое", "Niedrig", "Niska"},
        {"Restart the game to apply", "Перезапустить игру, чтобы применить", "Spiel neu starten, um anzuwenden",
         "Uruchom grę ponownie, aby zastosować"},
        {"Restart now? Progress since the last save is lost.", "Перезапустить сейчас? Всё, что не сохранено, пропадёт.",
         "Jetzt neu starten? Nicht Gespeichertes geht verloren.", "Uruchomić ponownie? Niezapisany postęp przepadnie."},
        {"Graphics and sound (the game's configurator)", "Графика и звук (конфигуратор игры)",
         "Grafik und Ton (Konfigurator des Spiels)", "Grafika i dźwięk (konfigurator gry)"},
        {"Low (22 kHz)", "Низкое (22 кГц)", "Niedrig (22 kHz)", "Niska (22 kHz)"},
        {"High (44 kHz)", "Высокое (44 кГц)", "Hoch (44 kHz)", "Wysoka (44 kHz)"},
        {"Controls", "Управление", "Steuerung", "Sterowanie"},
        {"Look with the gyroscope", "Обзор гироскопом", "Umsehen per Gyroskop", "Rozglądanie żyroskopem"},
        {"Gyroscope speed", "Скорость гироскопа", "Gyroskop-Geschwindigkeit", "Szybkość żyroskopu"},
        {"Left-handed layout", "Раскладка для левши", "Linkshänder-Layout", "Układ dla leworęcznych"},
        {"Button size", "Размер кнопок", "Tastengröße", "Rozmiar przycisków"},
        {"Button opacity", "Непрозрачность кнопок", "Deckkraft der Tasten", "Krycie przycisków"},
        {"Run when the stick is at its edge", "Бег у края джойстика", "Laufen am Rand des Sticks", "Bieg przy krawędzi drążka"},
        {"Vibration", "Вибрация", "Vibration", "Wibracje"},
        {"Head bobbing", "Покачивание камеры при ходьбе", "Kopfwippen beim Gehen", "Kołysanie kamery przy chodzeniu"},
        {"Settings", "Настройки", "Einstellungen", "Ustawienia"},
        {"Faster turns on quick swipes", "Ускорение быстрого обзора", "Schnelles Umsehen beschleunigen",
         "Szybsze obroty przy szybkim przesunięciu"},
        {"Touch controls", "Сенсорное управление", "Touch-Steuerung", "Sterowanie dotykowe"},
        /* The gestures (Controls' help page, a line each). */
        {"At the side: invisible movement area, starting under your finger. A small deflection walks, a full one runs. Swipe elsewhere to look.",
         "Сбоку — невидимая зона движения с центром под пальцем. Малое отклонение — ходьба, полное — бег. В остальной части экрана — обзор свайпом.",
         "Seitlich: unsichtbarer Bewegungsbereich mit Mitte unter dem Finger. Leicht auslenken geht, voll auslenken rennt. Anderswo wischen zum Umsehen.",
         "Z boku: niewidoczny obszar ruchu ze środkiem pod palcem. Małe wychylenie to chód, pełne to bieg. Przesuń gdzie indziej, aby się rozejrzeć."},
        {"After 20 seconds without touch, controls fade over 5 seconds. Touch restores them in half a second.",
         "Через 20 секунд без касаний кнопки плавно исчезают за 5 секунд. Касание возвращает их за полсекунды.",
         "Nach 20 Sekunden ohne Berührung verblassen die Tasten in 5 Sekunden. Eine Berührung zeigt sie in einer halben Sekunde wieder.",
         "Po 20 sekundach bez dotyku przyciski znikają przez 5 sekund. Dotknięcie przywraca je w pół sekundy."},
        {"Use: the hand (bright when the game offers it), or a finger held still on the picture: hold to take "
             + "what the hero faces or draw its colour out. A tap on the helper in the middle uses too.",
         "Использовать: рука (яркая, когда игра предлагает) или палец, задержанный на картинке: держите — взять "
             + "то, на что смотрит герой, или высасывать цвет. Тап по подсказке в центре — тоже.",
         "Benutzen: die Hand (hell, wenn das Spiel es anbietet) oder ein still gehaltener Finger: halten nimmt, "
             + "worauf der Held blickt, oder saugt seine Farbe. Tippen auf den Hinweis in der Mitte benutzt auch.",
         "Użyj: ręka (jasna, gdy gra to proponuje) lub palec przytrzymany na obrazie: trzymaj, by wziąć to, na co "
             + "patrzy bohater, lub wysysać kolor. Dotknięcie podpowiedzi na środku też używa."},
        {"The brush: a tap takes it up or puts it down; held, it paints while you hold it and fans out the colours. "
             + "Beside the brush a swipe changes colour. Tap with a second finger to cancel a glyph and keep the brush.",
         "Кисть: тап — взять или убрать; удержание — рисовать, пока держишь, и веер цветов. "
             + "У кисти свайп меняет цвет. Тап вторым пальцем отменяет знак, оставляя кисть в руке.",
         "Der Pinsel: Tippen nimmt ihn auf oder legt ihn weg; gehalten malt er, solange man hält, mit dem Farbfächer. "
             + "Neben dem Pinsel wechselt Wischen die Farbe. Mit einem zweiten Finger tippen verwirft das Zeichen und behält den Pinsel.",
         "Pędzel: dotknięcie bierze go lub odkłada; przytrzymany maluje, póki trzymasz, i rozkłada wachlarz kolorów. "
             + "Obok pędzla przesunięcie zmienia kolor. Dotknięcie drugim palcem anuluje znak i pozostawia pędzel."},
        {"Tap dialogue to advance; hold to keep skipping lines. Tap a full-screen video to show its Skip button, then tap the button to skip. The up arrow jumps.",
         "Тап по диалогу — следующая реплика; удержание — постоянный пропуск реплик. Тап по полноэкранному видео показывает кнопку пропуска. Стрелка вверх — прыжок.",
         "Dialog antippen schaltet weiter; halten überspringt fortlaufend. Vollbildvideo antippen zeigt die Überspringen-Taste. Der Pfeil nach oben springt.",
         "Dotknij dialogu, aby przejść dalej; przytrzymaj, aby pomijać kolejne kwestie. Dotknij filmu, aby pokazać przycisk pominięcia. Strzałka w górę to skok."},
        {"The heart, the book, the map: the body, the journal, the map (at the exits). Hold the heart: the journal.",
         "Сердце, книга, карта — тело, журнал, карта (у выходов). Удержание сердца — журнал.",
         "Herz, Buch, Karte: Körper, Journal, Karte (an den Ausgängen). Herz halten: Journal.",
         "Serce, księga, mapa — ciało, dziennik, mapa (przy wyjściach). Przytrzymaj serce — dziennik."},
        {"Menus, the body, the journal, the map: a tap clicks, a double tap opens a save, a two-finger tap is the right "
             + "button (holding too, but on the map), dragging moves sliders; one finger scrolls lists and the journal, two "
             + "fingers scroll, pinching zooms the map.",
         "В меню, теле, журнале, на карте: тап — щелчок, двойной — открыть сохранение, тап двумя пальцами — правая "
             + "кнопка (и удержание, кроме карты), перетаскивание — ползунки; пальцем листаются списки и журнал, двумя — "
             + "прокрутка, щипок — масштаб карты.",
         "In Menüs, Körper, Journal und Karte: Tippen klickt, doppeltes Tippen öffnet einen Spielstand, Tippen mit zwei "
             + "Fingern ist die rechte Taste (auch Halten, außer auf der Karte), Ziehen bewegt Regler; ein Finger blättert "
             + "Listen und das Journal, zwei scrollen, Spreizen zoomt die Karte.",
         "W menu, ciele, dzienniku i na mapie: dotknięcie — klik, podwójne — otwiera zapis, dotknięcie dwoma palcami — "
             + "prawy przycisk (także przytrzymanie, poza mapą), przeciąganie — suwaki; palcem przewija się listy i "
             + "dziennik, dwoma — przewijanie, rozsunięcie — zoom mapy."},
        {"The body: hold Memory on the right to take colour into the Palette. From a heart, swipe right to move its colour into Memory or left to move capillary lymph into the Palette. Tap empty space to return colour; touch the lower left for progress and body bonuses.",
         "Тело: удержание Памяти справа набирает цвет в Палитру. На сердце свайп вправо передаёт его цвет в Память, влево — лимфу из приростков в Палитру. Тап по пустому месту возвращает цвет; касание внизу слева показывает прогресс и характеристики.",
         "Körper: Erinnerung rechts halten nimmt Farbe in die Palette. Am Herzen nach rechts wischen gibt Herzfarbe in die Erinnerung, nach links Kapillarlymphe in die Palette. Leere Stelle antippen gibt Farbe zurück; links unten berühren zeigt Fortschritt und Körperboni.",
         "Ciało: przytrzymaj Pamięć po prawej, aby pobrać kolor do Palety. Na sercu przesuń w prawo, aby przenieść jego kolor do Pamięci, lub w lewo, aby przenieść limfę z naczyń do Palety. Dotknij pustego miejsca, aby oddać kolor; lewy dół pokazuje postęp i premie."},
        {"The map: the hourglass slows time; the arrows accelerate time only while held. "
             + "The navigator's arrow or a three-finger tap centres the map on the hero.",
         "Карта: песочные часы — медленное время; стрелки ускоряют время только пока их держат. "
             + "Стрелка навигатора или тап тремя пальцами — центрирование карты на герое.",
         "Karte: die Sanduhr verlangsamt die Zeit; die Pfeile beschleunigen sie nur beim Halten. "
             + "Der Navigationspfeil oder Tippen mit drei Fingern zentriert die Karte auf den Helden.",
         "Mapa: klepsydra zwalnia czas; strzałki przyspieszają go tylko podczas przytrzymania. "
             + "Strzałka nawigacji lub dotknięcie trzema palcami centruje mapę na bohaterze."},
        {"The map: a finger held on a place shows it (its sister, its name) without going there; a tap goes there.",
         "Карта: палец, задержанный на месте, показывает его (сестру, название) без перехода; тап — идти туда.",
         "Karte: ein auf einem Ort gehaltener Finger zeigt ihn (seine Schwester, seinen Namen), ohne hinzugehen; "
             + "Tippen geht hin.",
         "Mapa: palec przytrzymany na miejscu pokazuje je (siostrę, nazwę) bez przejścia; dotknięcie — idź tam."},
        {"Back (Android) is Escape; it puts the brush down first. A controller or keyboard hides the buttons; "
             + "a touch brings them back.",
         "«Назад» Android — Esc; сначала убирает кисть. Геймпад или клавиатура прячут кнопки, касание их возвращает.",
         "Zurück (Android) ist Esc; zuerst legt es den Pinsel weg. Controller oder Tastatur blenden die Tasten aus; "
             + "eine Berührung holt sie zurück.",
         "Wstecz (Android) to Esc; najpierw odkłada pędzel. Pad lub klawiatura chowają przyciski, dotknięcie je przywraca."},
        {"Hold the menu button: the buttons' layout (drag a button; pinch or the slider sizes it; this help is "
             + "there too). With developer commands on, a choice of them first.",
         "Удержание кнопки меню — расположение кнопок (перетаскивание, размер щипком или ползунком; там же эта "
             + "памятка). С включёнными командами разработчика — сначала выбор.",
         "Menütaste halten: die Anordnung der Tasten (ziehen; Größe per Spreizen oder Regler; dort auch diese "
             + "Hilfe). Mit Entwicklerbefehlen zuerst eine Auswahl.",
         "Przytrzymaj przycisk menu: układ przycisków (przeciągnij; rozmiar szczypnięciem lub suwakiem; tam też "
             + "ta pomoc). Z poleceniami deweloperskimi najpierw wybór."},
        {"Leave the game?", "Выйти из игры?", "Das Spiel verlassen?", "Wyjść z gry?"},
        /* The seven colours, as the palette's hearts go (the journal's names). */
        {"Silver", "Серебро", "Silber", "Srebro"},
        {"Purple", "Пурпур", "Purpur", "Purpura"},
        {"Amber", "Янтарь", "Bernstein", "Bursztyn"},
        {"Azure", "Лазурь", "Azur", "Lazur"},
        {"Lilac", "Сирень", "Flieder", "Bez"},
        {"Emerald", "Изумруд", "Smaragd", "Szmaragd"},
        {"Gold", "Золото", "Gold", "Złoto"},
        {"Vertical field of view", "Вертикальный угол обзора", "Vertikales Sichtfeld", "Pionowe pole widzenia"},
        {"Harvestable vein glow", "Яркость жил для добычи цвета", "Leuchten abbaubarer Adern", "Blask żył z kolorem"},
        {"Mobile controls", "Мобильное управление", "Mobile Steuerung", "Sterowanie mobilne"},
        {"Developer commands (hold the menu)", "Команды разработчика (удержание меню)",
         "Entwicklerbefehle (Menü halten)", "Polecenia deweloperskie (przytrzymaj menu)"},
        {"Subtitle size", "Размер субтитров", "Untertitelgröße", "Rozmiar napisów"},
        {"Text size", "Размер текста", "Textgröße", "Rozmiar tekstu"},
        {"Dark background for stats and colour amounts", "Контрастная подложка характеристик и количества цвета",
         "Dunkler Hintergrund für Werte und Farbmengen", "Ciemne tło statystyk i ilości koloru"},
        {"Show menu button", "Показывать кнопку меню", "Menütaste anzeigen", "Pokaż przycisk menu"},
        {"Show action button", "Показывать кнопку действия", "Aktionstaste anzeigen", "Pokaż przycisk akcji"},
        {"Show hearts button", "Показывать кнопку сердец", "Herztaste anzeigen", "Pokaż przycisk serc"},
        {"Developer commands", "Команды разработчика", "Entwicklerbefehle", "Polecenia deweloperskie"},
        {"Invert vertical gyroscope look", "Инверсия вертикали гироскопа",
         "Gyroskop-Blick vertikal umkehren", "Odwróć pion rozglądania żyroskopem"},
        {"in hand", "в руке", "in der Hand", "w ręce"},
        {"Teleport", "Телепорт", "Teleport", "Teleportacja"},
        {"Heart", "Сердце", "Herz", "Serce"},
        {"Palette", "Палитра", "Palette", "Paleta"},
        {"Memory", "Память", "Erinnerung", "Pamięć"},
        {"tap: put it here", "тап — положить сюда", "Tippen: hierher legen", "dotknij: odłóż tutaj"},
        {"tap: put it back", "тап — вернуть", "Tippen: zurücklegen", "dotknij: oddaj"},
        {"New game", "Новая игра", "Neues Spiel", "Nowa gra"},
        {"Load game", "Загрузить игру", "Spiel laden", "Wczytaj grę"},
        {"Save game", "Сохранить игру", "Spiel speichern", "Zapisz grę"},
        {"Only on the map!", "Только на карте!", "Speichern nur auf Karte möglich!", "Tylko na mapie!"},
        {"Options", "Настройки", "Optionen", "Opcje"},
        {"Credits", "Авторы", "Credits", "Autorzy"},
        {"Back to the game", "Назад", "Zurück zum Spiel", "Powrót do gry"},
        {"Exit", "Выйти", "Spiel verlassen", "Wyjdź"},
        {"Main menu item names", "Названия пунктов главного меню", "Namen der Hauptmenüpunkte", "Nazwy pozycji menu głównego"},
        {"Water reflections", "Отражения в воде", "Spiegelungen im Wasser", "Odbicia w wodzie"},
    };

    /** The release's language (fsystems.xml: Russian, German, Polish,
     *  English): the layer speaks it too, as the game's own menus do. */
    static String gameLanguage = "";
    static boolean legacyGame;
    private static String[] gameTexts;

    static void loadGameTexts() {
        if (gameTexts == null) gameTexts = GameActivity.nativeHintTexts();
    }

    /** Original string-manager results; a missing translation leaves its icon alone. */
    static String gameText(int index) {
        return gameTexts != null && index >= 0 && index < gameTexts.length ? gameTexts[index].trim() : "";
    }

    static String text(int id) {
        String game = gameLanguage.toLowerCase(Locale.ROOT);
        String lang = game.startsWith("russian") ? "ru" : game.startsWith("german") ? "de" : game.startsWith("polish") ? "pl"
            : game.startsWith("english") ? "en" : Locale.getDefault().getLanguage();
        int col = "ru".equals(lang) || "uk".equals(lang) || "be".equals(lang) ? 1 : "de".equals(lang) ? 2 : "pl".equals(lang) ? 3 : 0;
        return TEXTS[id][col];
    }
}
