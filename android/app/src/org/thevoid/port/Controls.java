package org.thevoid.port;

import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Canvas;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.RectF;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.drawable.GradientDrawable;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.Choreographer;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.Surface;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.SeekBar;
import android.widget.TextView;
import java.io.File;
import java.util.Map;

/**
 * The touch layer over the game picture. It follows what the game shows
 * (android/host/hud.c reports the cursor, the helper icons and the images
 * that tell the screens apart in every presented frame):
 *   WORLD  exploring in 3D: an invisible analogue movement area,
 *          swipes turn the camera; while the game shows a helper at the
 *          centre, touching it acts at once (the "use" one holds the right
 *          button, the "paint" one switches the brush on);
 *   UI     a screen with the cursor (menus, body, map, journal): the cursor
 *          goes under the finger, tap = click, double tap = double click,
 *          long press = right click, drag = the left button (the map pans
 *          and the body turns with the right one; a list of saves scrolls,
 *          the journal's texts follow the finger pixel by pixel), pinch =
 *          the mouse wheel in small steps, two-finger swipes = the wheel's
 *          notches (in the journal its pixels, no pinch); three-finger tap
 *          centres the map on the hero;
 *   PAINT  the brush is on (L Ctrl held): the picture is a canvas, a stroke
 *          is the left button with the cursor under the finger.
 * A button shows only where pressing it does something (the game's scripts
 * handle that key there). The camera turns by mouse motion, so the game's
 * own MouseSensitivity and InvertMouse apply to swipes and the gyroscope.
 */
final class Controls extends FrameLayout implements Choreographer.FrameCallback, SensorEventListener {
    static final int WORLD = 0, UI = 1, PAINT = 2;
    private static final float MAP_PAN = 0.3f;     /* mouse pixels per finger pixel when panning the map */
    private static final float BODY_TURN = 0.6f;   /* ... when turning the hero's body */
    /* Pinch: one wheel notch (120) used to go per 18 % of finger distance;
     * now 1.5 times as fast, sent in small steps as the fingers move. */
    private static final double NOTCH = Math.log(1.18);
    private static final float ZOOM_SPEED = 1.5f;
    /* android/host/hud.h */
    private static final int HUD_CURSOR = 1, HUD_USE = 2, HUD_USE_ARROW = 4, HUD_PAINT = 8,
        HUD_TRAP = 0x10, HUD_WAIT = 0x20, HUD_DEATH = 0x40, HUD_NO_LYMPHA = 0x80, HUD_CURSOR_LYMPHA = 0x200,
        HUD_MAP = 0x400, HUD_PALETTE = 0x800, HUD_MEMORY = 0x1000, HUD_MENU = 0x2000, HUD_JOURNAL = 0x4000,
        HUD_OBSCURA = 0x8000, HUD_WHEEL = 0x10000, HUD_LOADING = 0x20000, HUD_SUBTITLE = 0x40000, HUD_MAP3D = 0x1000000,
        HUD_OPTIONS = 0x80000, HUD_MAINMENU = 0x100000, HUD_PAUSE = 0x200000, HUD_ARROWS = 0x400000,
        HUD_VIDEO = 0x800000, HUD_CONTROL_LOCKED = 0x2000000, HUD_PATH_READY = 0x4000000, HUD_BACK = 0x8000000,
        HUD_JOURNAL_VIDEO = 0x40000000;
    /* Warning helpers still accept use: the game explains why the action is blocked. */
    private static final int HUD_ACTION = HUD_USE | HUD_USE_ARROW | HUD_TRAP | HUD_WAIT | HUD_DEATH | HUD_NO_LYMPHA;
    /* Images of the screens with a cursor (menus, the body, the journal, the map...). */
    private static final int MENU_IMAGES = HUD_MAP | HUD_MEMORY | HUD_MENU | HUD_JOURNAL | HUD_OBSCURA | HUD_OPTIONS
        | HUD_MAINMENU | HUD_PAUSE | HUD_ARROWS | HUD_LOADING;
    /* Screens, told apart by those images. */
    private static final int S_WORLD = 0, S_SCENE = 1, S_MAP = 2, S_BODY = 3, S_JOURNAL = 4, S_PAUSE = 5,
        S_OPTIONS = 6, S_MAIN = 7, S_LIST = 8, S_OBSCURA = 9, S_LOADING = 10, S_PAINT = 11, S_OTHER = 12, S_INTRO = 13,
        S_VIDEO = 14;
    private static final String[] SCREEN_NAMES = {"world", "scene", "map", "body", "journal", "pause", "options",
        "main menu", "list", "obscura", "loading", "paint", "other", "intro", "video"};
    private boolean menuSeen;   /* the main menu has come: the opening videos are over */

    private final GameActivity activity;
    private final Input in = new Input();
    private final HardwareInput hardware;
    private final android.hardware.input.InputManager inputManager;
    private final Settings settings;
    private final Haptics haptics;
    private final File gameSettings;   /* the game's settings.xml (its data\settings.xml) */
    private final String startKey;     /* the start-time settings the game runs with */
    private String declinedKey = "";   /* start-time settings the player chose not to restart for */
    private final boolean lymphHearts;  /* The 2008 executable owns separate heart lymph. */
    private final boolean nativeMenu;  /* the game's options menu carries the port's settings */
    /* The release's time actions on the map (German swaps the keys of the
     * default and the slowest flow): scan codes. */
    private final int timeMin, timeDefault, timeAvg, timeMax;
    /* Jumping and skipping (cutscenes, a line of dialogue): Space and, with
     * the port's actions.xml, Enter, so the hints name the two buttons apart. */
    private final int jumpKey, skipKey;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final TouchView touch;
    private final PalettePicker picker, memoryPicker;
    /* The HUD's measured images (hud.h): palette 1-7, Memory 8-14, the
     * wheel's handle 15, the hero on the map 16, the subtitles' strip 17,
     * the menus' exit 18, the body's return 19, the menus' other glyphs
     * 20-26 (new, load, save, save greyed, options, credits, continue). */
    private static final int SLOT_WHEEL = 15, SLOT_HERO = 16, SLOT_SUBTITLE = 17, SLOT_EXIT = 18, SLOT_BACK = 19,
        SLOT_MENU = 20, MENU_GLYPHS = 7, SLOTS = 27;
    /* The map's camera, from the matrix its draws carry (the vertex
     * shader's c0..c3, seen with the wheel's handle every frame and with the
     * hero's marker): it looks down from distance w (c3.w), x scale c0.x,
     * y scale f (c1.z), translations c0.w and c1.w. A mouse pixel of a
     * right-button drag moves it 0.0637 of the map's units at every
     * distance (measured on the Pixel 10a: 3.07 game pixels a mouse pixel
     * at distance 37.5, 3.85 at 30, 4.37 at 26.5). */
    private static final float MAP_UNITS_PER_MOUSE = 0.0637f;
    private float mapW, mapF, mapC0, mapT0, mapT1;   /* mapW 0: not seen */
    private float heroX, heroZ;          /* the hero on the map's ground, from its marker */
    private boolean heroKnown;
    private int centring;                /* game frames left of turning the map to the hero */
    private long centringFrame;
    private long subtitleSeen, exitSeen; /* when the subtitles' strip, a menu's exit last showed */
    private final float[] slotValues = new float[SLOTS * PalettePicker.FLOATS];
    private final float[] bodyAmounts = new float[28];
    private final float[] bodyDetails = new float[14];
    /* The hearts a carried Memory colour can go into (the body's script
     * publishes them): zone, x, y in the game's pixels, current, maximum. */
    private final float[] zoneLabels = new float[21 * 5];
    private int zoneLabelCount;
    private final String[] bodyStatNames = new String[7];
    private final Bitmap[] bodyGlyphs = new Bitmap[21];
    private final boolean[] bodyGlyphRead = new boolean[21];
    private int pendingColour = -1, fanChoice = -1;   /* a colour to click in the palette; the fan's */
    private int brushColour = -1, publishedColour = -2;
    private long pendingSince, picked;   /* when a colour was asked for; when it was clicked */
    private long heartClicked, raised;   /* the layer's last click on a heart; its last taking up of the brush */
    private int raises;                  /* takings up since the game last showed its brush */
    private Runnable fanShow;
    private final LinearLayout systemColumn, actionColumn, timeRow;
    private final FrameLayout buttonLayer;
    private final IconButton[] layoutButtons;
    private final View[] buttonAnchors;
    private final SharedPreferences layoutPrefs;
    private TouchLayout touchLayout;
    private TouchLayoutEditor layoutEditor;
    private final FrameLayout[] slots = new FrameLayout[3];
    private final IconButton menuB, bodyB, journalB, mapB, jumpB, useB, paintB, skipB, fastB, slowB, locateB, bodyBackB;
    private boolean menuHeld;   /* the menu button's hold opened the layer's choices: its release sends nothing */
    private boolean bodyHeld;   /* the heart button's hold opened the journal: its release sends nothing */
    private final FrameLayout panel;
    private final TextView gamepadHelp;
    private int mode = WORLD, hud, screen = -1;
    private long hudFrame = -1, cursorFrame = -100, menuFrame = -100, paintSince, paintPressTime, strokeEnded, settingsRead;
    private final long[] seen = new long[32];   /* when each HUD tag was last drawn */
    private boolean paintMode, paintMomentary, polling, resumed, slowTime, avgTime, fastHeld;
    private boolean videoSkipVisible;
    private long lastTouch = SystemClock.uptimeMillis(), alphaTime = lastTouch;
    private int fingersDown;
    private float overlayAlpha = 1f;
    private int cancelFinger = -1;
    private float cancelX, cancelY;
    private long cancelTime;
    private final Runnable raiseBrush = () -> { if (paintMode) in.key(Input.CTRL, true); };
    private boolean obscuraView;
    private final int[] sounds = new int[4], soundsBefore = new int[4];
    private boolean soundsKnown;
    private SensorManager sensors;
    private long gyroTime;
    private int insetLeft, insetRight;   /* display cutout */

    Controls(GameActivity a, Settings settings, Haptics haptics, File gameSettings, Map<String, Integer> actions,
             String startKey, boolean nativeMenu, boolean lymphHearts) {
        super(a);
        activity = a;
        this.settings = settings;
        this.haptics = haptics;
        this.gameSettings = gameSettings;
        this.startKey = startKey;
        this.nativeMenu = nativeMenu;
        this.lymphHearts = lymphHearts;
        hardware = new HardwareInput(this, in, actions);
        inputManager = (android.hardware.input.InputManager) a.getSystemService(Context.INPUT_SERVICE);
        setFocusableInTouchMode(true);
        setPointerIcon(android.view.PointerIcon.getSystemIcon(a, android.view.PointerIcon.TYPE_NULL));
        layoutPrefs = a.getSharedPreferences("touch-layout", Context.MODE_PRIVATE);
        touchLayout = new TouchLayout(layoutPrefs.getString("layout", ""));
        timeMin = actionKey(actions, "time_min", 0x02);
        timeDefault = actionKey(actions, "time_default", 0x0B);
        timeAvg = actionKey(actions, "time_avg", 0x03);
        timeMax = actionKey(actions, "time_max", 0x04);
        jumpKey = actionKey(actions, "jump", Input.SPACE);
        skipKey = actionKey(actions, "skip_cutscene", Input.SPACE);
        IconButton.haptics = haptics;
        haptics.setEnabled(settings.vibration);
        setMotionEventSplittingEnabled(true);
        Context c = a;
        touch = new TouchView(c);
        addView(touch, new LayoutParams(-1, -1));
        picker = new PalettePicker(c, this::chooseColour);
        addView(picker, new LayoutParams(-1, -1));
        memoryPicker = new PalettePicker(c, colour -> { }, 8);
        addView(memoryPicker, new LayoutParams(-1, -1));
        picker.setHoldChooser(new PalettePicker.HoldChooser() {
            @Override public void press(int colour, boolean down) { touch.bodyColour(false, colour, down); }
            @Override public void moved(int colour, float dx, float dy) {
                if (dx < -dp(20)) touch.startBodyColour(false, colour);
            }
        });
        memoryPicker.setHoldChooser((colour, down) -> touch.bodyColour(true, colour, down));
        systemColumn = column();
        actionColumn = column();
        /* Escape when the finger lifts: held, the button opens the touch
         * layout's editor (or the layer's choices) instead. */
        menuB = button(systemColumn, Icons.MENU, (b, down) -> {
            if (down) { menuHeld = false; return; }
            if (menuHeld) return;
            setPaintMode(false);
            if (!journalBackToBody()) in.tapKey(Input.ESC);
        });
        menuB.setLongPress(() -> { menuHeld = true; menuHold(); });
        /* B when the finger lifts: held, the button opens the journal (J). */
        bodyB = button(systemColumn, Icons.BODY, (b, down) -> {
            if (down) { bodyHeld = false; return; }
            if (!bodyHeld) in.tapKey(Input.B);
        });
        bodyB.setLongPress(() -> {
            bodyHeld = true;
            haptics.tick();
            android.util.Log.i("TheVoid", "journal: the heart held, J");
            journalFromBody = false;
            in.tapKey(Input.J);
        });
        journalB = button(systemColumn, Icons.JOURNAL, (b, down) -> journal(down));
        mapB = button(systemColumn, Icons.MAP, (b, down) -> in.key(Input.M, down));
        /* The pause menu's gear had the fifth place: the others keep theirs. */
        View spare = new View(c);
        spare.setVisibility(INVISIBLE);
        systemColumn.addView(spare);
        for (int i = 0; i < slots.length; ++i) {
            slots[i] = new FrameLayout(c);
            slots[i].setMotionEventSplittingEnabled(false);
            actionColumn.addView(slots[i]);
        }
        jumpB = slotButton(0, Icons.JUMP, (b, down) -> in.key(jumpKey, down));
        skipB = slotButton(0, Icons.SKIP, (b, down) -> in.key(skipKey, down));
        useB = slotButton(1, Icons.USE, (b, down) -> in.button(Input.RIGHT, down));
        paintB = slotButton(2, Icons.PAINT, (b, down) -> paintButton(down));
        paintB.setDrag(this::brushDrag);
        /* The map: back to the hero, as a navigator's arrow. */
        locateB = slotButton(1, Icons.LOCATE, (b, down) -> { if (down) startCentring(); });
        /* Time on the map: at the bottom, in the middle. */
        timeRow = new LinearLayout(c);
        timeRow.setOrientation(LinearLayout.HORIZONTAL);
        timeRow.setMotionEventSplittingEnabled(true);
        slowB = new IconButton(c, Icons.SLOW, (b, down) -> { if (down) setSlowTime(!slowTime); });
        fastB = new IconButton(c, Icons.FAST, (b, down) -> fastTime(down));
        timeRow.addView(slowB);
        timeRow.addView(fastB);
        addView(systemColumn);
        addView(actionColumn);
        addView(timeRow);
        layoutButtons = new IconButton[] {menuB, bodyB, journalB, mapB, jumpB, skipB,
            useB, paintB, locateB, slowB, fastB};
        buttonAnchors = new View[layoutButtons.length];
        buttonLayer = new FrameLayout(c);
        addView(buttonLayer, new LayoutParams(-1, -1));
        for (int i = 0; i < layoutButtons.length; ++i) {
            IconButton button = layoutButtons[i];
            ViewGroup parent = (ViewGroup) button.getParent();
            int index = parent.indexOfChild(button);
            ViewGroup.LayoutParams original = button.getLayoutParams();
            parent.removeView(button);
            View anchor = new View(c);
            anchor.setVisibility(INVISIBLE);
            parent.addView(anchor, index, original);
            buttonAnchors[i] = anchor;
            /* No size until laid out (a frame's default is the whole screen). */
            buttonLayer.addView(button, new LayoutParams(0, 0));
        }
        bodyBackB = new IconButton(c, Icons.BACK, (b, down) -> {
            if (down) setPaintMode(false);
            in.key(Input.ESC, down);
        });
        bodyBackB.setVisibility(GONE);
        buttonLayer.addView(bodyBackB, new LayoutParams(0, 0));
        for (View anchor : new View[] {systemColumn, actionColumn, timeRow, buttonLayer})
            anchor.addOnLayoutChangeListener((v, l2, t2, r2, b2, ol2, ot2, or2, ob2) -> post(this::applyButtonLayout));
        paintB.addOnLayoutChangeListener((v, l2, t2, r2, b2, ol2, ot2, or2, ob2) -> anchorPicker());
        gamepadHelp = label(HardwareInput.helpTitle());
        gamepadHelp.setTextSize(16);
        gamepadHelp.setTypeface(android.graphics.Typeface.create("serif", android.graphics.Typeface.NORMAL));
        gamepadHelp.setTextColor(0xFFF0E6CE);
        gamepadHelp.setShadowLayer(dp(3), 0, dp(1), Color.BLACK);
        gamepadHelp.setPadding(dp(18), dp(12), dp(18), dp(12));
        gamepadHelp.setBackgroundColor(0x40101018);
        gamepadHelp.setOnClickListener(v -> showGamepadHelp());
        gamepadHelp.setVisibility(GONE);
        LayoutParams helpAt = new LayoutParams(-2, -2, Gravity.BOTTOM | Gravity.RIGHT);
        helpAt.setMargins(dp(24), dp(12), dp(24), dp(16));
        addView(gamepadHelp, helpAt);
        panel = new FrameLayout(c);
        panel.setBackgroundColor(Color.argb(150, 0, 0, 0));
        panel.setVisibility(GONE);
        panel.setOnTouchListener((v, e) -> {   /* a tap beside the menu closes it, not one meant for the screen before */
            if (e.getActionMasked() == MotionEvent.ACTION_UP && SystemClock.uptimeMillis() - panelShown > 1000) closePanel();
            return true;
        });
        addView(panel, new LayoutParams(-1, -1));
        applyLayout();
        updateButtons();
        /* The window can be narrower than the display (a camera cutout): size
         * the columns from the laid-out view, which is what the picture fits. */
        addOnLayoutChangeListener((v, l, t, r, b, ol, ot, or, ob) -> {
            if (r - l != or - ol || b - t != ob - ot) post(this::applyLayout);
        });
        GameActivity.nativeSetCursorHidden(settings.hideCursor);
        settings.loadLook(gameSettings);
    }

    private static int actionKey(Map<String, Integer> actions, String name, int fallback) {
        Integer code = actions.get(name);
        return code != null && code > 0 ? code : fallback;
    }

    /* ------------------------------------------------------------ layout */

    private int dp(float v) { return Math.round(v * getResources().getDisplayMetrics().density); }

    private LinearLayout column() {
        LinearLayout c = new LinearLayout(getContext());
        c.setOrientation(LinearLayout.VERTICAL);
        c.setGravity(Gravity.CENTER_HORIZONTAL);
        c.setMotionEventSplittingEnabled(true);
        return c;
    }

    private IconButton button(LinearLayout column, int icon, IconButton.Listener l) {
        IconButton b = new IconButton(getContext(), icon, l);
        column.addView(b);
        return b;
    }

    private IconButton slotButton(int slot, int icon, IconButton.Listener l) {
        IconButton b = new IconButton(getContext(), icon, l);
        slots[slot].addView(b, new FrameLayout.LayoutParams(-1, -1));
        b.setVisibility(GONE);
        return b;
    }

    /** The display cutout (the activity draws into it): the default columns
     *  and the colours keep clear; a button the player placed may sit there. */
    void setInsets(int left, int right, java.util.List<android.graphics.RectF> holes) {
        insetsKnown = true;
        picker.setInsets(left, right, holes);
        memoryPicker.setInsets(left, right, holes);
        if (left == insetLeft && right == insetRight) return;
        insetLeft = left;
        insetRight = right;
        if (layoutEditor != null) layoutEditor.setInsets(left, right);
        post(this::applyLayout);
    }

    private boolean insetsKnown = android.os.Build.VERSION.SDK_INT < 28;   /* no cutouts before Android 9 */

    /** Columns at the picture's sides (system keys on one, actions on the
     *  other, mirrored for the left hand): in the bars beside a 16:9
     *  picture, over the edges of a wide one; the time buttons at the
     *  bottom, in the middle, above the line where the map writes its
     *  helpers (the brush's key, "click to enter"). */
    private void applyLayout() {
        int w = getWidth() > 0 ? getWidth() : getResources().getDisplayMetrics().widthPixels;
        int h = getHeight() > 0 ? getHeight() : getResources().getDisplayMetrics().heightPixels;
        int size = dp(54 * settings.buttonScale), margin = dp(5 * settings.buttonScale);
        int free = 0;   /* the picture fills the screen (Hor+): no bars beside it */
        int across = Math.max(dp(2), Math.min(margin, (free - size) / 2));
        if (free - 2 * across < size && free - 2 * across >= size * 4 / 5) size = free - 2 * across;   /* shrink a little to fit */
        int bar = Math.max(size + 2 * across, free);
        for (int i = 0; i < systemColumn.getChildCount(); ++i) sizeButton(systemColumn.getChildAt(i), size, across, margin);
        for (FrameLayout slot : slots) {
            sizeButton(slot, size, across, margin);
        }
        for (IconButton button : layoutButtons) button.setOpacity(settings.buttonOpacity);
        picker.setReadability(settings.textSize, settings.textContrast);
        memoryPicker.setReadability(settings.textSize, settings.textContrast);
        for (int i = 0; i < timeRow.getChildCount(); ++i) sizeButton(timeRow.getChildAt(i), size, dp(10 * settings.buttonScale), 0);
        boolean left = settings.leftHanded;
        /* The system keys from the top edge down: the menu in the corner, as on
         * every screen (the body's too), the heart below it. */
        LayoutParams sys = new LayoutParams(bar, -2, (left ? Gravity.RIGHT : Gravity.LEFT) | Gravity.TOP);
        sys.topMargin = Math.max(0, dp(10) - margin);
        LayoutParams act = new LayoutParams(bar, -2, (left ? Gravity.LEFT : Gravity.RIGHT) | Gravity.CENTER_VERTICAL);
        if (left) { sys.rightMargin = insetRight; act.leftMargin = insetLeft; }
        else { sys.leftMargin = insetLeft; act.rightMargin = insetRight; }
        systemColumn.setLayoutParams(sys);
        actionColumn.setLayoutParams(act);
        LayoutParams time = new LayoutParams(-2, -2, Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL);
        time.bottomMargin = Math.round(h * 0.125f);
        timeRow.setLayoutParams(time);
        post(this::applyButtonLayout);
        touch.invalidate();
    }

    private final java.util.List<RectF> bodyButtons = new java.util.ArrayList<>();

    /** Invisible original slots retain the default positions; actual hit boxes can move anywhere,
     *  beside the camera too (the layout is in fractions of the whole view). */
    private void applyButtonLayout() {
        int w = getWidth(), h = getHeight();
        if (w <= 0 || h <= 0) return;
        if (touchLayout.legacy && insetsKnown) {
            /* Saved before buttons could sit by the camera: measured across
             * the part clear of it. Moved into the whole view once. */
            touchLayout = touchLayout.fromSafeArea(insetLeft, insetRight, w);
            layoutPrefs.edit().putString("layout", touchLayout.encode()).apply();
        }
        int[] me = new int[2], at = new int[2];
        getLocationOnScreen(me);
        java.util.ArrayList<android.graphics.Rect> exclusions = new java.util.ArrayList<>();
        for (int i = 0; i < layoutButtons.length; ++i) {
            View anchor = buttonAnchors[i];
            anchor.getLocationOnScreen(at);
            int size = anchor.getWidth(), x = at[0] - me[0], y = at[1] - me[1];
            TouchLayout.Rect custom = touchLayout.get(TouchLayout.BUTTONS[i]);
            if (custom != null) {
                size = Math.max(dp(36), Math.round(Math.min(custom.width * w, custom.height * h)));
                size = Math.min(Math.min(w, h), size);
                x = Math.round(custom.x * w - size / 2f);
                y = Math.round(custom.y * h - size / 2f);
                x = Math.max(0, Math.min(w - size, x));
                y = Math.max(0, Math.min(h - size, y));
            }
            if (size <= 0) continue;
            IconButton button = layoutButtons[i];
            /* In the body the book stands beside the menu, at its height. */
            if (button == journalB && screen == S_BODY) {
                LayoutParams menu = (LayoutParams) menuB.getLayoutParams();
                x = Math.min(w - size, menu.leftMargin + menu.width + dp(10));
                y = Math.max(0, Math.min(h - size, menu.topMargin + (menu.height - size) / 2));
            }
            LayoutParams old = (LayoutParams) button.getLayoutParams();
            if (old.width != size || old.height != size || old.leftMargin != x || old.topMargin != y) {
                LayoutParams position = new LayoutParams(size, size, Gravity.TOP | Gravity.LEFT);
                position.leftMargin = x;
                position.topMargin = y;
                button.setLayoutParams(position);
            }
            if (button.getVisibility() == VISIBLE) exclusions.add(new android.graphics.Rect(x, y, x + size, y + size));
            /* The body's palette drops keep clear of the menu and the book above them. */
            if ((button == menuB || button == journalB) && screen == S_BODY && button.getVisibility() == VISIBLE)
                bodyButtons.add(new RectF(x, y, x + size, y + size));
        }
        picker.setObstacles(bodyButtons);
        bodyButtons.clear();
        int backSize = dp(54 * settings.buttonScale);
        LayoutParams back = new LayoutParams(backSize, backSize, Gravity.TOP | Gravity.LEFT);
        back.leftMargin = Math.max(insetLeft, getWidth() - insetRight - dp(70) - backSize);
        back.topMargin = h - backSize - dp(12);
        LayoutParams previousBack = (LayoutParams) bodyBackB.getLayoutParams();
        if (previousBack.width != backSize || previousBack.leftMargin != back.leftMargin || previousBack.topMargin != back.topMargin)
            bodyBackB.setLayoutParams(back);
        bodyBackB.setOpacity(settings.buttonOpacity);
        if (android.os.Build.VERSION.SDK_INT >= 29) buttonLayer.setSystemGestureExclusionRects(exclusions);
        anchorPicker();
    }

    private TouchLayout defaultTouchLayout() {
        TouchLayout defaults = TouchLayout.zones(settings.leftHanded);
        int w = Math.max(1, getWidth()), h = Math.max(1, getHeight());
        int[] me = new int[2], at = new int[2];
        getLocationOnScreen(me);
        for (int i = 0; i < buttonAnchors.length; ++i) {
            View anchor = buttonAnchors[i];
            anchor.getLocationOnScreen(at);
            defaults.put(TouchLayout.BUTTONS[i], (at[0] - me[0] + anchor.getWidth() / 2f) / w,
                (at[1] - me[1] + anchor.getHeight() / 2f) / h,
                Math.max(1, anchor.getWidth()) / (float) w, Math.max(1, anchor.getHeight()) / (float) h);
        }
        return defaults;
    }

    /** The touch layout's editor over the paused picture (the menu button held). */
    private void editTouchLayout() {
        releaseAll();
        panel.setVisibility(GONE);
        panel.removeAllViews();
        layoutEditor = new TouchLayoutEditor(getContext(), defaultTouchLayout(), touchLayout, insetLeft, insetRight,
            settings.buttonOpacity, value -> {
                removeView(layoutEditor);
                layoutEditor = null;
                editorClosed();
                if (value != null) {
                    touchLayout = value;
                    layoutPrefs.edit().putString("layout", value.encode()).apply();
                    applyButtonLayout();
                }
            }, this::showHelp);
        addView(layoutEditor, new LayoutParams(-1, -1));
        /* The game holds still under it; the real buttons give way to their previews. */
        activity.freezeGame(true);
        buttonLayer.setVisibility(INVISIBLE);
        picker.setVisibility(INVISIBLE);
        memoryPicker.setVisibility(INVISIBLE);
    }

    private void editorClosed() {
        activity.freezeGame(false);
        buttonLayer.setVisibility(VISIBLE);
        picker.setVisibility(VISIBLE);
        memoryPicker.setVisibility(VISIBLE);
    }

    /** The colour picker sits by the brush (the action column's third slot), from its laid-out place. */
    private void anchorPicker() {
        LayoutParams at = (LayoutParams) paintB.getLayoutParams();
        if (at.width <= 0) return;
        float x = at.leftMargin + at.width / 2f;
        boolean custom = touchLayout.get("paint") != null;
        picker.setAnchor(x, at.topMargin + at.height / 2f,
            at.width, custom ? x >= getWidth() / 2f : !settings.leftHanded, custom);
    }

    private void sizeButton(View b, int size, int across, int margin) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(size, size);
        lp.setMargins(across, margin, across, margin);
        b.setLayoutParams(lp);
        if (b instanceof IconButton) ((IconButton) b).setOpacity(settings.buttonOpacity);
    }

    /* ------------------------------------------------------------- modes */

    void resume() {
        resumed = true;
        if (inputManager != null) inputManager.registerInputDeviceListener(hardware, handler);
        hardware.capture();
        if (!polling) { polling = true; Choreographer.getInstance().postFrameCallback(this); }
        registerGyro();
    }

    void pause() {
        resumed = false;
        if (inputManager != null) inputManager.unregisterInputDeviceListener(hardware);
        unregisterGyro();
        haptics.pulse(false);
        releaseAll();
        releasePicture();
        journalAfterBody = bodyAfterJournal = holdTouch = false;
    }

    /** Back from the background (a call, another app) after awayMs: in the
     *  world the game's menu opens, so play goes on when the player chooses
     *  (the game's clock stood still meanwhile). */
    void cameBack(long awayMs) {
        if (awayMs > 3000 && screen == S_WORLD && !paintMode) {
            android.util.Log.i("TheVoid", "back after " + awayMs + " ms: the game's menu");
            in.tapKey(Input.ESC);
        }
    }

    void releaseAll() {
        touch.cancel();
        picker.cancelHold();
        memoryPicker.cancelHold();
        for (int i = 0; i < buttonLayer.getChildCount(); ++i)
            if (buttonLayer.getChildAt(i) instanceof IconButton) ((IconButton) buttonLayer.getChildAt(i)).cancelPress();
        fingers.clear();
        if (fastHeld) fastTime(false);
        if (paintMode) setPaintMode(false);
        fingersDown = 0;
        hardware.release();
        in.releaseAll();
    }

    @Override public boolean dispatchTouchEvent(MotionEvent event) {
        if (HardwareInput.mouseEvent(event)) return hardware.mouse(event) || super.dispatchTouchEvent(event);
        if (layoutEditor != null) return super.dispatchTouchEvent(event);
        lastTouch = SystemClock.uptimeMillis();
        int action = event.getActionMasked();
        int index = event.getActionIndex();
        /* The body and the journal changing places under a held picture: the
         * screen between them takes no touch (a finger down then stays out). */
        if (holdingFor >= 0 && action == MotionEvent.ACTION_DOWN) holdTouch = true;
        if (holdTouch) {
            if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) holdTouch = false;
            return true;
        }
        if (screen != S_BODY && !panelVisible() && settings.touchAdaptations && action == MotionEvent.ACTION_DOWN
                && (hud & HUD_BACK) != 0 && inSlot(SLOT_BACK, event.getX(index) / getWidth(), event.getY(index) / getHeight(), 0)) {
            setPaintMode(false);
            touch.cancel();
            in.cursorTo(event.getX(index) / getWidth(), event.getY(index) / getHeight());
            in.click(Input.LEFT);
            return true;
        }
        boolean cancelContact = false;
        if (action == MotionEvent.ACTION_POINTER_DOWN && paintMode && touch.stroking()) {
            cancelFinger = event.getPointerId(index);
            cancelX = event.getX(index);
            cancelY = event.getY(index);
            cancelTime = event.getEventTime();
            cancelContact = true;
        } else if (action == MotionEvent.ACTION_MOVE && cancelFinger >= 0) {
            int at = event.findPointerIndex(cancelFinger);
            if (at < 0 || Math.hypot(event.getX(at) - cancelX, event.getY(at) - cancelY) > dp(12)) cancelFinger = -1;
        } else if (action == MotionEvent.ACTION_POINTER_UP && event.getPointerId(index) == cancelFinger) {
            if (event.getEventTime() - cancelTime <= 300) touch.cancelStroke();
            cancelFinger = -1;
            cancelContact = true;
        } else if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) cancelFinger = -1;
        fingersDown = action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL ? 0
            : event.getPointerCount() - (action == MotionEvent.ACTION_POINTER_UP ? 1 : 0);
        if (action == MotionEvent.ACTION_DOWN && padActive && !panelVisible()) {
            hardware.touch();
            padActive = false;
            activity.applyPortSettings();
            revealing = true;
            android.util.Log.i("TheVoid", "input: a touch, the buttons are back");
            updateButtons();
        }
        if (revealing) {
            if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) revealing = false;
            return true;
        }
        if (cancelContact) return true;
        if (panelVisible()) {
            fingers.clear();
            return super.dispatchTouchEvent(event);
        }
        return route(event);
    }

    /* Each finger belongs to what it landed on (a button, a colour, the
     * picture) until it lifts, whatever the others do: the stick, a look and
     * the jump at once. Android's own split would give a finger to a
     * full-screen layer another finger already holds (the buttons' layer,
     * the colours), wherever it lands. */
    private final android.util.SparseArray<View> fingers = new android.util.SparseArray<>();

    private View fingerTarget(float x, float y) {
        if (gamepadHelp.getVisibility() == VISIBLE && x >= gamepadHelp.getLeft() && x < gamepadHelp.getRight()
                && y >= gamepadHelp.getTop() && y < gamepadHelp.getBottom()) return gamepadHelp;
        for (int i = buttonLayer.getChildCount() - 1; i >= 0; --i) {
            View b = buttonLayer.getChildAt(i);
            if (b.getVisibility() == VISIBLE && b.getWidth() > 0 && x >= b.getLeft() && x < b.getRight()
                    && y >= b.getTop() && y < b.getBottom()) return b;
        }
        if (memoryPicker.wants(x, y)) return memoryPicker;
        if (picker.wants(x, y)) return picker;
        return touch;
    }

    private boolean route(MotionEvent e) {
        int action = e.getActionMasked();
        if (e.getPointerCount() > 3) touch.uiFingers = 4;
        if (action == MotionEvent.ACTION_DOWN) fingers.clear();
        if (action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_POINTER_DOWN) {
            int i = e.getActionIndex();
            fingers.put(e.getPointerId(i), fingerTarget(e.getX(i), e.getY(i)));
        }
        /* A finger's landing and lifting go to its owner only; moves and a
         * cancel to every owner, each with its own fingers. */
        View changed = action == MotionEvent.ACTION_MOVE || action == MotionEvent.ACTION_CANCEL ? null
            : fingers.get(e.getPointerId(e.getActionIndex()));
        java.util.ArrayList<View> owners = new java.util.ArrayList<>(3);
        for (int i = 0; i < e.getPointerCount(); ++i) {
            View owner = fingers.get(e.getPointerId(i));
            if (owner != null && !owners.contains(owner) && (changed == null || owner == changed)) owners.add(owner);
        }
        for (View owner : owners) {
            MotionEvent part = fingersOf(e, owner);
            owner.dispatchTouchEvent(part);
            part.recycle();
        }
        if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) fingers.clear();
        else if (action == MotionEvent.ACTION_POINTER_UP) fingers.remove(e.getPointerId(e.getActionIndex()));
        return true;
    }

    /** The event as the owner's own: its fingers only, in its coordinates (screen ones kept raw). */
    private MotionEvent fingersOf(MotionEvent e, View owner) {
        int count = e.getPointerCount(), n = 0, index = -1;
        for (int i = 0; i < count; ++i) if (fingers.get(e.getPointerId(i)) == owner) ++n;
        MotionEvent.PointerProperties[] properties = new MotionEvent.PointerProperties[n];
        MotionEvent.PointerCoords[] coords = new MotionEvent.PointerCoords[n];
        float screenX = e.getRawX() - e.getX(), screenY = e.getRawY() - e.getY();
        for (int i = 0, k = 0; i < count; ++i) {
            if (fingers.get(e.getPointerId(i)) != owner) continue;
            properties[k] = new MotionEvent.PointerProperties();
            e.getPointerProperties(i, properties[k]);
            coords[k] = new MotionEvent.PointerCoords();
            e.getPointerCoords(i, coords[k]);
            coords[k].x += screenX;
            coords[k].y += screenY;
            if (i == e.getActionIndex()) index = k;
            ++k;
        }
        int action = e.getActionMasked(), part;
        if (action == MotionEvent.ACTION_MOVE || action == MotionEvent.ACTION_CANCEL || index < 0) {
            part = action == MotionEvent.ACTION_CANCEL ? action : MotionEvent.ACTION_MOVE;
        } else {
            boolean down = action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_POINTER_DOWN;
            part = n == 1 ? (down ? MotionEvent.ACTION_DOWN : MotionEvent.ACTION_UP)
                : (down ? MotionEvent.ACTION_POINTER_DOWN : MotionEvent.ACTION_POINTER_UP)
                    | (index << MotionEvent.ACTION_POINTER_INDEX_SHIFT);
        }
        MotionEvent out = MotionEvent.obtain(e.getDownTime(), e.getEventTime(), part, n, properties, coords,
            e.getMetaState(), e.getButtonState(), e.getXPrecision(), e.getYPrecision(), e.getDeviceId(),
            e.getEdgeFlags(), e.getSource(), e.getFlags());
        View parent = (View) owner.getParent();
        float left = owner.getLeft() + (parent != this ? parent.getLeft() : 0);
        float top = owner.getTop() + (parent != this ? parent.getTop() : 0);
        out.offsetLocation(-(screenX + left), -(screenY + top));
        return out;
    }

    private void fadeControls(long now) {
        if (fingersDown > 0 || panelVisible()) lastTouch = now;
        long elapsed = Math.max(0, now - alphaTime), idle = Math.max(0, now - lastTouch);
        alphaTime = now;
        overlayAlpha = idle <= 20000 ? Math.min(1f, overlayAlpha + elapsed / 500f)
            : Math.min(overlayAlpha, Math.max(0f, 1f - (idle - 20000) / 5000f));
        buttonLayer.setAlpha(overlayAlpha);
        systemColumn.setAlpha(overlayAlpha);
        actionColumn.setAlpha(overlayAlpha);
        timeRow.setAlpha(overlayAlpha);
        picker.setAlpha(overlayAlpha);
        memoryPicker.setAlpha(overlayAlpha);
        /* The menus' names of their glyphs stay (they are the menu's, not controls). */
        touch.setAlpha(screen == S_MAIN || screen == S_PAUSE ? 1f : overlayAlpha);
    }

    /** Whether the game drew an image with this tag within the last ms. */
    private boolean shown(int tag, long ms) {
        long now = SystemClock.uptimeMillis();
        for (int bit = 0; bit < 32; ++bit)
            if ((tag & (1 << bit)) != 0 && seen[bit] != 0 && now - seen[bit] < ms) return true;
        return false;
    }

    private long lastSeen(int tag) {
        long t = 0;
        for (int bit = 0; bit < 32; ++bit) if ((tag & (1 << bit)) != 0) t = Math.max(t, seen[bit]);
        return t;
    }

    /** The screen the game shows now. */
    private int screen() {
        /* The opening videos draw none of the images: until the main menu
         * comes, only skipping does something. */
        if (!menuSeen && !(menuSeen = shown(HUD_MAINMENU | HUD_MAP3D | HUD_MEMORY | HUD_JOURNAL, 700)
                || GameActivity.nativeBrushColour() >= 0)) return S_INTRO;
        if (mode == PAINT) return S_PAINT;
        if ((hud & HUD_LOADING) != 0) return S_LOADING;
        /* A film after the opening ones (a glyph shown, a death, the end of
         * a cycle): the host saw Theora decoded and frames of a few draws. */
        if (shown(HUD_VIDEO, 500)) return S_VIDEO;
        /* The map with the cursor hidden (the hero on his way, a new cycle's
         * flight over it): still the map, its time buttons stay. */
        if (mode == WORLD) return shown(HUD_MAP3D, 400) ? S_MAP : shown(HUD_SUBTITLE, 800) ? S_SCENE : S_WORLD;
        /* A screen's own image in the last frame decides at once: the map
         * opened from the pause menu is the map while the menu's images
         * still count as shown. The times below bridge the frames a screen
         * leaves its images out (fades, a page loading). */
        if ((hud & HUD_OPTIONS) != 0) return S_OPTIONS;
        if ((hud & HUD_PAUSE) != 0) return S_PAUSE;
        if ((hud & HUD_MAINMENU) != 0) return S_MAIN;
        if ((hud & HUD_MEMORY) != 0) return S_BODY;
        if ((hud & HUD_JOURNAL) != 0) return S_JOURNAL;
        if ((hud & (HUD_MAP | HUD_WHEEL | HUD_MAP3D)) != 0 && (hud & HUD_OBSCURA) == 0) return S_MAP;
        if (shown(HUD_OPTIONS, 700)) return S_OPTIONS;
        if (shown(HUD_PAUSE, 700)) return S_PAUSE;
        if (shown(HUD_MAINMENU, 700)) return S_MAIN;
        if (shown(HUD_MEMORY, 700)) return S_BODY;
        if (shown(HUD_JOURNAL, 700)) return S_JOURNAL;
        /* A sister's face over the map is the map's own pointing (the mouse
         * resting on her chamber), not her obscura. */
        if (shown(HUD_OBSCURA, 1000) && !shown(HUD_MAP, 400)) return S_OBSCURA;
        if (shown(HUD_MAP | HUD_WHEEL | HUD_MAP3D, 1500)) return S_MAP;
        if (shown(HUD_ARROWS, 700)) return S_LIST;
        return S_OTHER;
    }

    @Override public void doFrame(long frameTimeNanos) {
        if (!resumed) { polling = false; return; }
        long state = GameActivity.nativeHudState();
        Settings.loadGameTexts();
        long frame = state >>> 32;
        long now = SystemClock.uptimeMillis();
        if (frame != hudFrame) {
            hudFrame = frame;
            hud = (int) state;
            /* The game does not draw its cursor and helpers in every frame (the
             * palette slides in, screens fade): each counts as shown for a
             * while after the last frame that had it. */
            for (int bit = 0; bit < 32; ++bit) if ((hud & (1 << bit)) != 0) seen[bit] = now;
            if ((hud & (HUD_CURSOR | HUD_CURSOR_LYMPHA)) != 0) cursorFrame = frame;
            if ((hud & MENU_IMAGES) != 0) menuFrame = frame;
        }
        /* Back in the world the touches turn the camera at once: six frames
         * shown without the cursor end a menu (a swipe right after "continue"
         * is a look). A screen whose images are still drawn (it fades) keeps
         * the menu for a second. Counted in frames: a menu that loads a page
         * shows none for seconds and stays a menu. */
        boolean cursor = (hud & (HUD_CURSOR | HUD_CURSOR_LYMPHA | MENU_IMAGES)) != 0;
        if (screen == S_OBSCURA) obscuraView = true;
        if (!shown(HUD_OBSCURA, 350)) obscuraView = false;
        cursor |= obscuraView;   /* Colour transfer hides the sister's cursor. */
        /* Body rotation and colour transfer hide the cursor without leaving
         * the screen. Keep the captured gesture until every finger lets go. */
        cursor |= screen == S_BODY && (touch.bodyGesture() || (hud & HUD_MEMORY) != 0);
        long cursorSeen = lastSeen(HUD_CURSOR | HUD_CURSOR_LYMPHA);
        long paletteSeen = lastSeen(HUD_PALETTE);
        if (paintMode && (hud & HUD_PATH_READY) != 0) setPaintMode(false);
        /* Only the palette confirms a ready brush; menus also draw a cursor. */
        if (paintMode && !paintMomentary && !touch.stroking() && paletteSeen < paintSince && now - paintSince > 5000)
            setPaintMode(false);
        /* The game put its brush away (no palette, no paint cursor) while
         * the layer still paints. After a glyph the brush is done, as when
         * Ctrl is let go. After a tap or the layer's click on a heart (an
         * empty stroke, which the game also ends painting with) it is taken
         * up again - else nothing could be drawn any more (an empty tree
         * waiting for the Donor glyph). Twice at most without the palette
         * coming back. */
        boolean gameBrush = shown(HUD_PALETTE, 350);
        /* A tree/sister view can lower the brush while Ctrl is still held. */
        boolean drawingMenu = shown((MENU_IMAGES & ~HUD_OBSCURA) | HUD_MAP3D, 400);
        boolean drawingView = shown(HUD_CURSOR | HUD_CURSOR_LYMPHA, 150) && !drawingMenu;
        if (gameBrush) raises = 0;
        if (paintMode && !paintMomentary && !touch.stroking() && !gameBrush && now - paintSince > 900 && now - raised > 900) {
            boolean empty = now - heartClicked < 2500 || (strokeEnded > paintSince && touch.lastStrokeShort());
            boolean starting = paletteSeen < paintSince && strokeEnded < paintSince && !drawingMenu;
            if ((empty || drawingView || starting) && raises < 2) {
                ++raises;
                raised = now;
                android.util.Log.i("TheVoid", "paint: brush restored after an empty stroke or drawing-view transition");
                removeCallbacks(raiseBrush);
                in.key(Input.CTRL, false);
                postDelayed(raiseBrush, 90);
            } else if (strokeEnded > paintSince && now - strokeEnded > 700 && now - cursorSeen > 600) {
                setPaintMode(false);
            }
        }
        int m = paintMode ? PAINT : cursor ? UI : WORLD;
        if (m != mode) switchMode(m);
        int s = screen();
        if (screen == S_BODY && touch.bodyGesture() && (hud & (HUD_OPTIONS | HUD_PAUSE | HUD_MAINMENU | HUD_MAP3D)) == 0)
            s = S_BODY;
        if (s != screen) {
            android.util.Log.i("TheVoid", "screen " + SCREEN_NAMES[s] + " (hud " + Integer.toHexString(hud) + ")");
            if (screen == S_OPTIONS) {   /* the options may have changed the port's settings */
                readSettings();
                String key = settings.startKey();
                if (nativeMenu && !key.equals(startKey) && !key.equals(declinedKey)) askRestart();
            }
            if (s == S_BODY) bodyOnMap = screen == S_MAP;
            /* The options' pages and the journal take no double click: each
             * quick tap on their arrows turns a page. */
            GameActivity.nativeSetDoubleClicks(s != S_OPTIONS && s != S_JOURNAL && s != S_BODY);
            screen = s;
            lastTouch = alphaTime = now;
            overlayAlpha = 1f;
            applyButtonLayout();
            if (s == S_VIDEO || s == S_INTRO) touch.cancel();
            videoSkipVisible = false;
            screenSince = now;
            if (s == S_MAIN && !settings.touchHelpShown && !padActive && !panelVisible()) {
                settings.touchHelpShown = true;
                settings.save();
                showHelp();
            }
        }
        if (screen == S_OPTIONS && now - settingsRead > 1500) readSettings();
        paintB.setBlinking((screen == S_WORLD || screen == S_SCENE) && shown(HUD_PAINT, 400));
        palette(now);
        touch.useHint = mode == WORLD && shown(HUD_ACTION, 300);
        touch.paintHint = mode == WORLD && shown(HUD_PAINT, 400);
        journalBridge(now);
        /* Under a held picture the buttons stay those of the screen it shows. */
        if (holdingFor < 0) updateButtons();
        picture(now);
        soundEvents();
        hardware.frame(frameTimeNanos, settings.hideCursor);
        fadeControls(now);
        stillMenu(now);
        Choreographer.getInstance().postFrameCallback(this);
    }

    /* A menu that only stands there (the body, the journal, the pause menu;
     * no finger for 1.5 s, nothing carried) is shown at 30 frames a second:
     * the same picture, half the game's work and heat. A touch brings the
     * full rate back at once. */
    private boolean stillShown;

    private void stillMenu(long now) {
        boolean still = (screen == S_BODY || screen == S_JOURNAL || screen == S_PAUSE) && fingersDown == 0
            && now - lastTouch > 1500 && !touch.bodyGesture() && !panelVisible();
        if (still == stillShown) return;
        stillShown = still;
        android.util.Log.i("TheVoid", "still menu: " + still);
        GameActivity.nativeSetFramePeriod(still ? 33333 : 0);
    }

    /** Landing, damage and sucking colour, as the host hears them. */
    private void soundEvents() {
        GameActivity.nativeSoundEvents(sounds);
        if (soundsKnown) {
            if (sounds[0] != soundsBefore[0]) { android.util.Log.i("TheVoid", "haptic: land"); haptics.land(); }
            if (sounds[1] != soundsBefore[1]) { android.util.Log.i("TheVoid", "haptic: damage"); haptics.damage(); }
            if ((sounds[3] > 0) != (soundsBefore[3] > 0)) android.util.Log.i("TheVoid", "haptic: sucking " + (sounds[3] > 0));
        }
        haptics.pulse(sounds[3] > 0 && mode == WORLD);
        System.arraycopy(sounds, 0, soundsBefore, 0, 4);
        soundsKnown = true;
    }

    /** The port's settings as the game's options menu left them. */
    private void readSettings() {
        settingsRead = SystemClock.uptimeMillis();
        settings.loadLook(gameSettings);
        if (!nativeMenu) return;
        boolean gyro = settings.gyro, left = settings.leftHanded;
        float size = settings.buttonScale, opacity = settings.buttonOpacity;
        settings.loadFromGame(gameSettings);
        hardware.settings(gameSettings);
        activity.applyPortSettings();
        haptics.setEnabled(settings.vibration);
        picker.setReadability(settings.textSize, settings.textContrast);
        memoryPicker.setReadability(settings.textSize, settings.textContrast);
        if (gyro != settings.gyro) registerGyro();
        if (left != settings.leftHanded || size != settings.buttonScale || opacity != settings.buttonOpacity) applyLayout();
    }

    private void switchMode(int m) {
        android.util.Log.i("TheVoid", "mode " + (m == WORLD ? "world" : m == UI ? "ui" : "paint"));
        touch.cancel();
        mode = m;
        touch.invalidate();
    }

    /** Each button only where the game's scripts handle its key: in a menu,
     *  the body or the journal the keys of exploring do nothing. The right
     *  column's slots keep their places (jump or skip, use, the brush),
     *  so a button that stays never moves under the thumb. */
    private void updateButtons() {
        show(gamepadHelp, screen == S_MAIN && !shown(HUD_ARROWS, 500));
        if (!paintMode || !settings.touchAdaptations) {
            if (fanShow != null) { removeCallbacks(fanShow); fanShow = null; }
            picker.setFan(false);
        }
        int s = padActive ? -1 : screen;   /* a controller in use (or no screen seen yet): no buttons */
        boolean world = s == S_WORLD, scene = s == S_SCENE, map = s == S_MAP;
        /* A line spoken in the world (the hero thinking aloud as he walks,
         * a lesson) leaves him the stick and his hands. A conversation, a
         * brother's coming, a scene locks the controls (the game's
         * ControlsLocked): then the hero neither walks, jumps, paints nor
         * opens his body. */
        boolean play = (world || scene) && (hud & HUD_CONTROL_LOCKED) == 0;
        /* A Sister speaking in her obscura: neither the menu nor the brush
         * answers until she is silent. */
        boolean speaking = s == S_OBSCURA && shown(HUD_SUBTITLE, 800);
        /* The body's stats held: the colours' names stand where these are. */
        boolean stats = s == S_BODY && touch.bodyStatsHeld;
        /* While painting the palette has the top left corner; the brush ends it. */
        show(menuB, settings.showMenuButton && s >= 0 && s != S_MAIN && s != S_LOADING && s != S_INTRO && s != S_VIDEO
            && s != S_PAINT && !speaking && !stats);
        /* B and J open the body and the journal; there only Escape closes them. */
        show(bodyB, settings.showBodyButton && (play || map));
        show(journalB, s == S_BODY && !stats);
        show(bodyBackB, settings.touchAdaptations && s == S_BODY && !stats);
        show(mapB, play && shown(HUD_USE_ARROW, 700));   /* M leaves a chamber at its exits */
        show(jumpB, play);
        /* Next: cutscenes, the opening videos, and any screen while a line is
         * spoken (the Sister's lessons on the map and in the body). */
        show(skipB, !padActive && videoSkipVisible && !shown(HUD_JOURNAL_VIDEO, 500)
            && shown(HUD_VIDEO, 500) && (s == S_INTRO || s == S_VIDEO));
        /* The right button is the game's use wherever the hero stands: the
         * first Heart of a new game (a glotok) is taken with it though the
         * game shows no helper over it. The hand is bright when the game
         * offers use (its helper), fainter otherwise. */
        show(useB, settings.showActionButton && play);
        useB.setDim(!shown(HUD_ACTION, 700));
        show(locateB, map && heroKnown);
        show(paintB, (play || map || s == S_OBSCURA || s == S_PAINT) && !speaking);
        show(slowB, map);
        show(fastB, map);
        if (touch.stickShown != play) {
            touch.stickShown = play;
            touch.invalidate();
        }
    }

    private void show(View v, boolean on) {
        int want = on ? VISIBLE : (v instanceof LinearLayout || v.getParent() instanceof FrameLayout ? GONE : INVISIBLE);
        if (v.getVisibility() != want) {
            v.setVisibility(want);
            removeCallbacks(layoutChanged);
            post(layoutChanged);
        }
    }

    private final Runnable layoutChanged = this::applyButtonLayout;

    /* The book: the body answers no J (neither a chamber's nor the map's),
     * so the body closes first and J follows once the world or the map is
     * back (J opens the journal from either). The window holds the body's
     * picture meanwhile (GameActivity.nativeHoldPicture): the journal opens
     * from the body as one screen from another. Its Escape (the menu button,
     * Back) goes the same way back, B after it, to the body. */
    private boolean bodyOnMap, journalAfterBody, journalFromBody, journalShown, bodyAfterJournal;
    private int journalAfterKey = Input.J;
    private long journalAsked, bodyAsked, bodyAskedFrame;
    /* The picture is held until this screen shows (-1: not held), or the time runs out. */
    private int holdingFor = -1;
    private long holdingSince, overlayHeldUntil = -1;
    private boolean heldBodyColours;
    private boolean holdTouch;
    private static final int HOLD_MS = 3000;

    private void holdPicture(int until) {
        holdingFor = until;
        holdingSince = SystemClock.uptimeMillis();
        GameActivity.nativeHoldPicture(HOLD_MS);
    }

    private void releasePicture() {
        if (holdingFor < 0) return;
        holdingFor = -1;
        GameActivity.nativeHoldPicture(0);
        /* The frame being presented now may still be held: the body's drops
         * wait for the one after it, the first the screen surely shows. */
        overlayHeldUntil = hudFrame + 1;
    }

    private void journal(boolean down) {
        if (screen == S_BODY) {
            if (!down) return;
            journalAfterBody = journalFromBody = true;
            journalShown = false;
            journalAfterKey = Input.J;
            journalAsked = SystemClock.uptimeMillis();
            setPaintMode(false);
            holdPicture(S_JOURNAL);
            in.tapKey(Input.ESC);
            return;
        }
        in.key(Input.J, down);
    }

    /** The journal opened from the body closes back into it: true if this Escape is that. */
    private boolean journalBackToBody() {
        if (screen != S_JOURNAL || !journalFromBody || bodyAfterJournal || shown(HUD_JOURNAL_VIDEO, 500)) return false;
        android.util.Log.i("TheVoid", "journal: back to the body");
        bodyAfterJournal = true;
        bodyAsked = SystemClock.uptimeMillis();
        bodyAskedFrame = hudFrame;
        holdPicture(S_BODY);
        in.tapKey(Input.ESC);
        return true;
    }

    private void journalBridge(long now) {
        if (holdingFor >= 0 && (screen == holdingFor || now - holdingSince > HOLD_MS)) {
            android.util.Log.i("TheVoid", "journal: the picture moves again (" + SCREEN_NAMES[screen] + ")");
            releasePicture();
        }
        if (bodyAfterJournal) {
            /* The journal's Escape went back a step inside it: it is still drawn
             * twenty frames on (counted in frames: the world coming back may
             * take a long one). */
            if (hudFrame - bodyAskedFrame > 20 && (hud & HUD_JOURNAL) != 0 || now - bodyAsked > HOLD_MS) {
                bodyAfterJournal = false;
                releasePicture();
            } else if (screen == S_WORLD || screen == S_SCENE || screen == S_MAP) {
                bodyAfterJournal = journalFromBody = journalShown = false;
                android.util.Log.i("TheVoid", "journal: closed, B in the " + SCREEN_NAMES[screen]);
                in.tapKey(Input.B);
            }
        } else if (journalFromBody && !journalAfterBody) {
            if (screen == S_JOURNAL) {
                journalShown = true;
            } else if (journalShown && (screen == S_WORLD || screen == S_SCENE || screen == S_MAP)) {
                /* Closed some other way (a controller's Escape, its own control): back to the body all the same. */
                journalFromBody = journalShown = false;
                android.util.Log.i("TheVoid", "journal: closed, B in the " + SCREEN_NAMES[screen]);
                in.tapKey(Input.B);
            } else if (!journalShown && now - journalAsked > HOLD_MS) {
                journalFromBody = false;   /* it never opened */
            }
        }
        if (!journalAfterBody) return;
        if (now - journalAsked > 2500) { journalAfterBody = false; journalFromBody = false; releasePicture(); return; }
        if (screen != S_WORLD && screen != S_SCENE && screen != S_MAP) return;
        journalAfterBody = false;
        android.util.Log.i("TheVoid", "journal: the body closed, J in the " + SCREEN_NAMES[screen]);
        if (journalAfterKey < 0) in.click(-journalAfterKey - 1); else in.tapKey(journalAfterKey);
    }

    /** The brush (L Ctrl): a tap switches it on or off; held, it paints
     *  until it is let go. */
    private void paintButton(boolean down) {
        long now = SystemClock.uptimeMillis();
        if (down) {
            if (paintMode) { setPaintMode(false); return; }
            setPaintMode(true);
            paintMomentary = true;
            paintPressTime = now;
            fanChoice = -1;
            /* Held: the fan of colours around the brush. */
            if (settings.touchAdaptations && settings.colorPicker != Settings.PICK_STRIP && picker.known()) {
                fanShow = () -> { fanShow = null; if (paintMomentary) picker.setFan(true); };
                postDelayed(fanShow, 280);
            }
        } else if (paintMomentary) {
            paintMomentary = false;
            if (fanShow != null) { removeCallbacks(fanShow); fanShow = null; }
            if (picker.fanShown()) {
                picker.setFan(false);
                /* Let go on a colour: it is the brush's, and the brush stays. */
                if (fanChoice >= 0) {
                    if (picker.has(fanChoice)) chooseColour(fanChoice);
                    return;
                }
            }
            if (now - paintPressTime > 400) setPaintMode(false);
        }
    }

    /** A swipe in the colours' zone: the next colour one has, from the one
     *  last chosen (or the game's active one), with a tick. */
    private void turnColour(int dir) {
        int from = pendingColour >= 0 ? pendingColour : picker.active();
        int next = picker.nextValid(from, dir);
        if (next < 0) return;
        haptics.tick();
        chooseColour(next);
    }

    /** The finger holding the brush moves over the fan. */
    private void brushDrag(float rawX, float rawY, boolean released) {
        if (!picker.fanShown()) return;
        int[] me = new int[2];
        getLocationOnScreen(me);
        int at = picker.fanAt(rawX - me[0], rawY - me[1]);
        if (at != fanChoice && at >= 0 && IconButton.haptics != null) IconButton.haptics.tick();
        fanChoice = at;
    }

    /** A colour from the strip or the fan: its heart in the game's palette is
     *  clicked once the palette is there and still (it slides in). */
    private void chooseColour(int colour) {
        android.util.Log.i("TheVoid", "colour " + colour + " chosen");
        picker.showLabel(colour);
        picker.pinLabel(true);
        pendingColour = colour;
        picker.setActive(colour);
        pendingSince = SystemClock.uptimeMillis();
        if (!paintMode) setPaintMode(true);
    }

    /** Each frame: the palette's colours for the picker; a chosen colour's click. */
    private void palette(long now) {
        int mask = GameActivity.nativeHudSlots(slotValues);
        picker.update(mask, slotValues);
        memoryPicker.update(mask, slotValues);
        /* Under a held picture the drops stay as they were (the body's, leaving
         * it); let go, none until the new picture is surely shown. */
        boolean bodyColours = holdingFor >= 0 ? heldBodyColours
            : hudFrame > overlayHeldUntil && touchAdaptations() && screen == S_BODY;
        heldBodyColours = bodyColours;
        GameActivity.nativeSetHudHidden(touchAdaptations() ? (1 << 29) | (bodyColours ? HUD_BACK : 0) : 0);
        picker.setBody(bodyColours);
        memoryPicker.setBody(bodyColours);
        /* The brush's colour: one just chosen; else the heart the game lights
         * in its palette, when the palette is there; else what the hero's
         * script last published (World.Vars.LastChoosenLimfa), when it
         * publishes a new one: on the map no hero runs, and an old value (of
         * another save) must not take back a colour chosen there. */
        int originalColour = GameActivity.nativeBrushColour();
        boolean published = originalColour != publishedColour;
        publishedColour = originalColour;
        int lit = shown(HUD_PALETTE, 300) ? picker.lit() : -1;
        boolean settled = picked == 0 && !paintMomentary && !picker.fanShown();
        if (pendingColour >= 0) brushColour = pendingColour;
        else if (lit >= 0 && settled && now - heartClicked > 400) brushColour = lit;   /* the game lights it a few frames after the click */
        else if (published && originalColour >= 0 && originalColour < PalettePicker.COLOURS && settled) brushColour = originalColour;
        int selected = brushColour >= 0 ? brushColour : picker.active();
        if (bodyColours || picker.known() || selected >= 0) {
            GameActivity.nativeBodyAmounts(bodyAmounts);
            picker.setAmounts(bodyAmounts, 0);
            memoryPicker.setAmounts(bodyAmounts, 14);
        }
        if (selected >= 0) picker.setActive(selected);
        if (bodyColours) {
            GameActivity.nativeBodyDetails(bodyDetails);
            zoneLabelCount = GameActivity.nativeZoneLabels(zoneLabels);
            for (int i = 0; i < 7; ++i)
                if (bodyStatNames[i] == null || bodyStatNames[i].isEmpty()) bodyStatNames[i] = GameActivity.nativeBodyStatName(i);
            if (touch.uiId >= 0 && !touch.bodyStatsHeld) touch.captureBodyTarget();
        } else {
            zoneLabelCount = 0;
        }
        touch.bodyFrame(bodyColours);
        touch.menuFrame(mask, screen == S_MAIN || screen == S_PAUSE);
        touch.showBodyTransferLabel();
        if (selected >= 0) paintB.setColour(picker.colour(selected), picker.fill(selected));
        if (screen == S_MAP) {
            restoreMapTime(mask, now);
            timeFromWheel(mask, now);
            mapTrack(mask);
            if (centring > 0 && hudFrame != centringFrame) {
                centringFrame = hudFrame;
                centringStep();
            }
        } else if (centring > 0) {
            stopCentring();
        }
        if ((mask & (1 << SLOT_SUBTITLE)) != 0) subtitleSeen = now;
        if ((mask & (1 << SLOT_EXIT)) != 0) exitSeen = now;
        picker.setStrip(settings.touchAdaptations && mode == PAINT && settings.colorPicker != Settings.PICK_FAN && shown(HUD_PALETTE, 500));
        /* A click on a heart chooses its colour (the game keeps it,
         * Vars.LastChoosenLimfa) and begins a stroke there, which, empty,
         * would put the brush away: the stroke is cancelled while the button
         * is down (as a second finger's tap cancels a glyph), so the brush
         * stays up. Should the game put it away all the same, doFrame takes
         * it up again (an empty stroke). */
        if (picked > 0 && now - picked > 180) {
            picked = 0;
            return;
        }
        if (pendingColour < 0 || picked > 0 || now - raised < 180) return;
        float[] at = shown(HUD_PALETTE, 300) ? picker.heartPoint(pendingColour) : null;
        if (at != null) {
            int colour = pendingColour;
            pendingColour = -1;
            touch.cancel();
            in.key(Input.BODY_WIDGET, true);
            in.cursorTo(at[0], at[1]);
            postDelayed(() -> { if (paintMode) GameActivity.nativeMouseButton(Input.LEFT, true); }, 40);
            postDelayed(() -> { if (paintMode) GameActivity.nativeCancelStroke(); }, 70);
            postDelayed(() -> {
                GameActivity.nativeMouseButton(Input.LEFT, false);
                in.key(Input.BODY_WIDGET, false);
            }, 110);
            picked = now;
            heartClicked = now;
            android.util.Log.i("TheVoid", "colour " + colour + ": its heart clicked at " + at[0] + "," + at[1]);
        } else if (now - pendingSince > 2500) {
            pendingColour = -1;
        }
    }

    private void setPaintMode(boolean on) {
        if (on == paintMode) return;
        removeCallbacks(raiseBrush);
        android.util.Log.i("TheVoid", "paint " + (on ? "on" : "off") + " (hud " + Integer.toHexString(hud) + ")");
        touch.cancel();
        paintMode = on;
        if (!on) { pendingColour = -1; picked = 0; picker.pinLabel(false); }
        paintMomentary = false;
        paintSince = SystemClock.uptimeMillis();
        in.key(Input.CTRL, on);
        paintB.setToggled(on);
    }

    /* Time on the map: the hourglass toggles slow flow; the arrows hold
     * maximum speed until release, then restore the previous flow. */
    private long timeSent;   /* when a time key was last sent */
    private int pendingTimeRestore = -1;
    private long timeRestoreFrame;

    private void timeKey(int key) {
        timeSent = SystemClock.uptimeMillis();
        in.tapKey(key);
    }

    private void fastTime(boolean down) {
        if (!down && !fastHeld) return;
        if (!down) {
            pendingTimeRestore = baseTime();
            timeRestoreFrame = hudFrame;
        }
        fastHeld = down;
        gameFlow = -1;
        gameFastest = false;
        timeButtons();
        timeKey(down ? timeMax : pendingTimeRestore);
    }

    private void restoreMapTime(int mask, long now) {
        /* A cutscene may remove the map's key handler before release. Retry
         * its saved flow once the real wheel returns, after the key pulse. */
        if (pendingTimeRestore < 0 || fastHeld || screen != S_MAP || (mask & (1 << SLOT_WHEEL)) == 0
                || (hud & (HUD_VIDEO | HUD_LOADING)) != 0
                || hudFrame == timeRestoreFrame || now - timeSent < 180) return;
        int key = pendingTimeRestore;
        pendingTimeRestore = -1;
        timeKey(key);
    }

    private void setSlowTime(boolean on) {
        gameFlow = -1;
        gameFastest = false;
        slowTime = on;
        if (on) avgTime = false;
        if (pendingTimeRestore >= 0) pendingTimeRestore = baseTime();
        timeButtons();
        timeKey(baseTime());
    }

    private int baseTime() { return avgTime ? timeAvg : slowTime ? timeMin : timeDefault; }

    private void timeButtons() {
        slowB.setToggled(slowTime);
        fastB.setToggled(avgTime || fastHeld || gameFastest);
    }

    /* The buttons show the flow the game runs, read from its Wheel of Time:
     * ui/map_wheel's setTimeScale(s) keeps p = (s - 1) / 119 and its handle
     * (ui_wheel_acc_manipulator, HUD slot 15) turns about the wheel's middle
     * by 28.8 + 170 p degrees. The game draws its interface images in
     * pixels of its picture, from the corner they keep to: the wheel's
     * middle is 74.7 render pixels from the left and 71.75 from the bottom,
     * the handle's middle 39.4 from it. Measured on the map: Redmi
     * (render 1170x540) at 1, 10 and 60.5 times 28.8, 41.4 and 113.8 degrees
     * (41.66 predicted for 10); Pixel 10a (render 1696x756) the same circle
     * in render pixels, 28.8 and 41.35 degrees at 1 and 10. So a loaded game
     * running at 1 time shows the hourglass, and the game's own changes
     * (its wheel dragged, a key, a script) show too. */
    private static final float WHEEL_X = 74.7f, WHEEL_BOTTOM = 71.75f, WHEEL_R = 39.4f;
    private int renderW, renderH;   /* the game's picture, pixels */

    void setRenderSize(int w, int h) {
        renderW = w;
        renderH = h;
    }
    private boolean gameFastest;   /* the game runs the fastest flow without the arrows held */
    private int gameFlow = -1;     /* the flow last read: 0 slowest, 1 default, 2 fast, 3 fastest */

    private void timeFromWheel(int mask, long now) {
        if ((mask & (1 << 15)) == 0 || fastB.held() || fastHeld || pendingTimeRestore >= 0 || now - timeSent < 800) return;
        if (renderW <= 0 || renderH <= 0) return;
        int base = 15 * PalettePicker.FLOATS + 64;   /* the handle's rectangle (x0, y0, x1, y1), 0..1 of the picture */
        float x = (slotValues[base] + slotValues[base + 2]) / 2 * renderW - WHEEL_X;
        float y = (slotValues[base + 1] + slotValues[base + 3]) / 2 * renderH - (renderH - WHEEL_BOTTOM);
        float r = (float) Math.hypot(x, y);
        if (r < WHEEL_R * 0.75f || r > WHEEL_R * 1.25f) return;   /* not the wheel measured */
        double angle = Math.toDegrees(Math.atan2(y, x));
        if (angle < -90) angle += 360;
        double scale = 1 + 119 * (angle - 28.8) / 170;
        int flow = scale < 5 ? 0 : scale < 35 ? 1 : scale < 90 ? 2 : 3;
        if (flow == gameFlow) return;
        gameFlow = flow;
        slowTime = flow == 0;
        avgTime = flow == 2;
        gameFastest = flow == 3;
        timeButtons();
        android.util.Log.i("TheVoid", "time: the game runs " + String.format(java.util.Locale.ROOT, "%.1f", scale)
            + " times (flow " + flow + String.format(java.util.Locale.ROOT, "; handle %.1f %.1f from the wheel, render %dx%d)",
            x, y, renderW, renderH));
    }

    /* The game's own screenshot (its F12, from a keyboard) saves its picture
     * only; the host hands the file on to the phone's gallery (Gallery). */
    private long screenSince;

    private void picture(long now) {
        String saved = GameActivity.nativeSavedPicture();
        if (saved != null) Gallery.add(activity, saved);
    }

    /* ------------------------------------------------------------- panel */

    boolean panelVisible() { return layoutEditor != null || panel.getVisibility() == VISIBLE; }

    /* A game controller or a keyboard in use hides the buttons, which only
     * covered the picture then; the next touch brings them back and does
     * nothing else (a button not seen is not pressed by chance). Keys that
     * play no part (the volume) change nothing. */
    private boolean padActive, revealing;

    void hardwareUsed() {
        hardwareActivity();
        if (padActive) return;
        padActive = true;
        activity.applyPortSettings();
        android.util.Log.i("TheVoid", "input: a controller or keyboard, the buttons hide");
        releaseAll();
        updateButtons();
    }

    void hardwareActivity() { lastTouch = SystemClock.uptimeMillis(); }
    boolean touchAdaptations() { return settings.touchAdaptations && !padActive; }
    boolean hardwareCursor() { return mode != WORLD; }
    float hardwareCursorSpeed() { return (renderH > 0 ? renderH : getHeight()) * .8f; }
    boolean hardwareSkipping() {
        return screen == S_VIDEO || screen == S_INTRO || (screen == S_SCENE || screen == S_OBSCURA) && shown(HUD_SUBTITLE, 800);
    }
    boolean hardwareKey(android.view.KeyEvent event) { return hardware.key(event); }
    boolean hardwareJournal(int code) {
        if (screen != S_BODY) return false;
        journal(true);
        journalAfterKey = code;
        return true;
    }
    boolean hardwareMotion(MotionEvent event) { return hardware.mouse(event) || hardware.motion(event); }
    @Override public boolean onCapturedPointerEvent(MotionEvent event) { return hardware.mouse(event); }

    @Override public void onPointerCaptureChange(boolean captured) {
        super.onPointerCaptureChange(captured);
        if (!captured) hardware.release();
    }

    void hardwareFocus(boolean focused) {
        if (focused) hardware.capture(); else releaseAll();
    }

    private final float[] hardwareCursor = new float[2];

    boolean openHardwareHelp() {
        if (gamepadHelp.getVisibility() != VISIBLE || panelVisible()) return false;
        GameActivity.nativeCursorPosition(hardwareCursor);
        float x = hardwareCursor[0] * getWidth(), y = hardwareCursor[1] * getHeight();
        if (x < gamepadHelp.getLeft() || x >= gamepadHelp.getRight() || y < gamepadHelp.getTop() || y >= gamepadHelp.getBottom()) return false;
        showGamepadHelp();
        return true;
    }

    private void showGamepadHelp() {
        releaseAll();
        buildPanel(PAGE_GAMEPAD);
        openPanel();
    }

    void scrollHardwareHelp(int pixels) {
        if (panel.getChildCount() > 0 && panel.getChildAt(0) instanceof ScrollView)
            ((ScrollView)panel.getChildAt(0)).scrollBy(0, pixels);
    }

    /** Android's Back: puts the brush down, otherwise the game's Escape. */
    void escape() {
        if (touchAdaptations() && (hud & HUD_BACK) != 0) {
            setPaintMode(false);
            touch.cancel();
            int at = SLOT_BACK * PalettePicker.FLOATS + 64;
            in.cursorTo((slotValues[at] + slotValues[at + 2]) / 2f, (slotValues[at + 1] + slotValues[at + 3]) / 2f);
            in.click(Input.LEFT);
            return;
        }
        if (paintMode) { setPaintMode(false); return; }
        if (!journalBackToBody()) in.tapKey(Input.ESC);
    }

    void runDebugCommand(String command) {
        runDebugCommands(new String[] {command});
    }

    void runDebugCommands(String[] commands) {
        while (panelVisible()) closePanel();
        releaseAll();
        if (screen == S_PAUSE || shown(HUD_PAUSE, 700)) in.tapKey(Input.ESC);
        handler.postDelayed(() -> {
            for (String command : commands) {
                if (!GameActivity.nativeConsoleCommand(command)) {
                    android.widget.Toast.makeText(getContext(), "Command rejected: " + command, android.widget.Toast.LENGTH_LONG).show();
                    break;
                }
            }
        }, 180);
    }

    private static final int PAGE_SETTINGS = 0, PAGE_HOLD = 2, PAGE_RESTART = 3, PAGE_HELP = 4, PAGE_EXIT = 5, PAGE_GAMEPAD = 6;
    private float exitX, exitY;   /* where the finger asked to leave the game */
    /* The icon of each line of the help page. */
    private static final int[] HELP_ICONS = {Icons.TOUCH, Icons.TOUCH, Icons.USE, Icons.PAINT, Icons.SKIP, Icons.BODY,
        Icons.MENU, Icons.BODY, Icons.FAST, Icons.MAP, Icons.BACK, Icons.MENU};

    /** The gestures, once when the main menu first comes, later from the
     *  touch layout's editor (its question mark). */
    private void showHelp() {
        android.util.Log.i("TheVoid", "help: the gestures");
        releaseAll();
        buildPanel(PAGE_HELP);
        openPanel();
    }

    private void openPanel() {
        hardware.release();
        setPointerIcon(android.view.PointerIcon.getSystemIcon(getContext(), android.view.PointerIcon.TYPE_DEFAULT));
        panel.setVisibility(VISIBLE);
        panel.bringToFront();   /* over the layout's editor too */
        panelShown = SystemClock.uptimeMillis();
    }

    /** The menu button held: the touch layout's editor; with debug commands on,
     *  a choice panel first (layout, the level/teleport list, the full console).
     *  The 2008 release (no native options menu) always gets the panel. */
    private void menuHold() {
        android.util.Log.i("TheVoid", "menu: held");
        if (!settings.debugCommands && nativeMenu) {
            editTouchLayout();
            return;
        }
        releaseAll();
        buildPanel(PAGE_HOLD);
        openPanel();
    }

    private long panelShown;
    private int settingsPage;

    /** The options changed what the game reads as it starts (render size,
     *  text size, the configurator's values): a restart applies them. */
    /** The menus' exit leaves the game at once: the layer asks first. */
    private void askExit(float x, float y) {
        android.util.Log.i("TheVoid", "exit: asked");
        exitX = x;
        exitY = y;
        releaseAll();
        buildPanel(PAGE_EXIT);
        openPanel();
    }

    /** A finger on the subtitles' text (the strip under it, while a line is
     *  spoken; the strip spans the width, the text its middle): the next
     *  line, as the next button. */
    private boolean onSubtitle(float fx, float fy) {
        return fx >= 0.18f && fx <= 0.82f && ((screen == S_OBSCURA && fy >= 0.65f)
            || (SystemClock.uptimeMillis() - subtitleSeen < 400 && shown(HUD_SUBTITLE, 400)
                && inSlot(SLOT_SUBTITLE, fx, fy, 0.04f)));
    }

    private void nextLine() {
        android.util.Log.i("TheVoid", "subtitle: tapped, the next line");
        haptics.tick();
        in.tapKey(skipKey);
    }

    /** The main or pause menu's exit under the finger. The save list opens
     *  over the pause menu, so for ~700 ms the screen still reads S_PAUSE and
     *  the stale EXIT rectangle sits under the list; a tap there must not ask
     *  to quit. The list's own arrows (never drawn by the bare main/pause
     *  menu) tell it apart, so suppress the exit while they show. */
    private boolean onExit(float fx, float fy) {
        return (screen == S_MAIN || screen == S_PAUSE) && SystemClock.uptimeMillis() - exitSeen < 500
            && !shown(HUD_ARROWS, 500) && inSlot(SLOT_EXIT, fx, fy, 0f);
    }

    /** A point (0..1 of the picture) in a measured image's rectangle, widened by margin. */
    private boolean inSlot(int slot, float fx, float fy, float margin) {
        int r = slot * PalettePicker.FLOATS + 64;
        float x0 = Math.min(slotValues[r], slotValues[r + 2]), x1 = Math.max(slotValues[r], slotValues[r + 2]);
        float y0 = Math.min(slotValues[r + 1], slotValues[r + 3]), y1 = Math.max(slotValues[r + 1], slotValues[r + 3]);
        return x1 > x0 && fx >= x0 - margin && fx <= x1 + margin && fy >= y0 - margin && fy <= y1 + margin;
    }

    /* --------------------------------------------------------------- map */

    /** The map's camera, and the hero's place on its ground, from this frame's draws. */
    private void mapTrack(int mask) {
        int source = (mask & (1 << SLOT_HERO)) != 0 ? SLOT_HERO : (mask & (1 << SLOT_WHEEL)) != 0 ? SLOT_WHEEL : -1;
        if (source < 0) return;
        int vs = source * PalettePicker.FLOATS + 32;
        float w = slotValues[vs + 15], f = slotValues[vs + 6], c0 = slotValues[vs];
        if (w < 0.5f || f < 0.1f || c0 < 0.05f) return;
        mapW = w; mapF = f; mapC0 = c0;
        mapT0 = slotValues[vs + 3];
        mapT1 = slotValues[vs + 7];
        if (source == SLOT_HERO) {
            int r = SLOT_HERO * PalettePicker.FLOATS + 64;
            float nx = slotValues[r] + slotValues[r + 2] - 1f, ny = 1f - (slotValues[r + 1] + slotValues[r + 3]);
            heroX = (nx * mapW - mapT0) / mapC0;
            heroZ = (ny * mapW - mapT1) / mapF;
            heroKnown = true;
        }
    }

    /** The map turns to the hero: the right button held, the mouse moved a
     *  quarter of the way each frame, the hero's marker followed (where the
     *  camera would show it, also off the screen). */
    private void startCentring() {
        if (!heroKnown || mapW <= 0 || renderW <= 0 || centring > 0) return;
        android.util.Log.i("TheVoid", "map: to the hero");
        in.button(Input.RIGHT, true);
        centring = 150;
        centringFrame = hudFrame;
    }

    private void centringStep() {
        float nx = (mapC0 * heroX + mapT0) / mapW, ny = (mapF * heroZ + mapT1) / mapW;
        float dx = nx * renderW / 2f, dy = -ny * renderH / 2f;   /* game pixels from the middle, y down */
        float g = MAP_UNITS_PER_MOUSE * mapF * renderH / (2f * mapW);   /* game pixels a mouse pixel */
        if (Math.hypot(dx, dy) < 2.5f || --centring <= 0 || g <= 0) {
            stopCentring();
            return;
        }
        float step = Math.hypot(dx, dy) > 40 ? 0.22f : 0.35f;
        in.look(-step * dx / g, -step * dy / g);
    }

    private void stopCentring() {
        if (centring > 0 || in.held(Input.RIGHT)) in.button(Input.RIGHT, false);
        centring = 0;
    }

    private void askRestart() {
        releaseAll();
        buildPanel(PAGE_RESTART);
        openPanel();
    }

    /** Back or a page's close: the topmost of the layer's pages goes (a page
     *  over the layout's editor first; the editor itself as its Cancel). */
    void closePanel() {
        if (panel.getVisibility() == VISIBLE) {
            panel.setVisibility(GONE);
            panel.removeAllViews();
            settings.save();
            activity.applyPortSettings();
            haptics.setEnabled(settings.vibration);
            setPointerIcon(android.view.PointerIcon.getSystemIcon(getContext(), android.view.PointerIcon.TYPE_NULL));
            hardware.capture();
            applyLayout();
            registerGyro();
            return;
        }
        if (layoutEditor != null) {
            removeView(layoutEditor);
            layoutEditor = null;
            editorClosed();
        }
    }

    /** The choices of the menu button's hold; the gestures' help; the port's
     *  settings where the game's options menu does not carry them (the 2008
     *  release); questions before leaving or restarting. */
    private void buildPanel(int page) {
        panel.removeAllViews();
        Context c = getContext();
        LinearLayout box = new LinearLayout(c);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(18), dp(12), dp(18), dp(12));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.argb(235, 18, 18, 26));
        bg.setCornerRadius(dp(14));
        bg.setStroke(dp(1), Color.argb(120, 255, 255, 255));
        box.setBackground(bg);
        box.setOnTouchListener((v, e) -> true);
        LinearLayout row = new LinearLayout(c);
        row.setGravity(Gravity.CENTER);
        int size = dp(56);
        if (page == PAGE_GAMEPAD) {
            TextView title = label(HardwareInput.helpTitle());
            title.setGravity(Gravity.CENTER);
            title.setTextColor(0xFFF0E6CE);
            box.addView(title);
            TextView text = label(HardwareInput.helpText());
            text.setTextSize(15);
            text.setPadding(0, dp(12), 0, dp(12));
            box.addView(text);
            row.addView(panelButton(Icons.CHECK, size, this::closePanel));
            box.addView(row);
        } else if (page == PAGE_HELP) {
            TextView title = label(Settings.text(Settings.T_HELP_TITLE));
            title.setTextColor(Color.rgb(255, 205, 50));
            title.setTextSize(17);
            title.setGravity(Gravity.CENTER);
            box.addView(title);
            for (int i = 0; i < Settings.HELP_LINES; ++i) {
                LinearLayout line = new LinearLayout(c);
                line.setGravity(Gravity.CENTER_VERTICAL);
                line.setPadding(0, dp(5), 0, dp(5));
                final int icon = HELP_ICONS[i];
                View mark = new View(c) {
                    private final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
                    @Override protected void onDraw(Canvas canvas) {
                        p.setColor(Color.WHITE);
                        Icons.draw(canvas, icon, getWidth() / 2f, getHeight() / 2f, Math.min(getWidth(), getHeight()), p);
                    }
                };
                line.addView(mark, new LinearLayout.LayoutParams(dp(26), dp(26)));
                TextView t = label(Settings.text(Settings.T_HELP_FIRST + i));
                t.setTextSize(14);
                t.setPadding(dp(10), 0, 0, 0);
                line.addView(t, new LinearLayout.LayoutParams(0, -2, 1));
                box.addView(line);
            }
            row.addView(panelButton(Icons.CHECK, size, this::closePanel));
            box.addView(row);
        } else if (page == PAGE_HOLD) {
            box.addView(choiceRow(Icons.TOUCH, TouchLayoutEditor.title(), this::editTouchLayout));
            if (settings.debugCommands) {
                /* The quick level/teleport list, and the full debug console. */
                box.addView(choiceRow(Icons.MAP, Settings.text(Settings.T_LEVELS), () -> {
                    closePanel();
                    activity.showLevelSelection();
                }));
                box.addView(choiceRow(Icons.DEBUG, Settings.text(Settings.T_DEBUG_LIST), () -> {
                    closePanel();
                    activity.showDebugCommands();
                }));
            }
            if (!nativeMenu) box.addView(choiceRow(Icons.GEAR, Settings.text(Settings.T_SETTINGS), () -> buildPanel(PAGE_SETTINGS)));
            row.addView(panelButton(Icons.CLOSE, size, this::closePanel));
            box.addView(row);
        } else if (page == PAGE_EXIT) {
            TextView q = label(Settings.text(Settings.T_EXIT_ASK));
            q.setGravity(Gravity.CENTER);
            box.addView(q);
            row.addView(panelButton(Icons.CHECK, size, () -> {
                closePanel();
                android.util.Log.i("TheVoid", "exit: confirmed");
                touch.tap(exitX, exitY, SystemClock.uptimeMillis());
            }));
            row.addView(panelButton(Icons.CLOSE, size, this::closePanel));
            box.addView(row);
        } else if (page == PAGE_RESTART) {
            TextView q = label(Settings.text(Settings.T_RESTART_ASK));
            q.setGravity(Gravity.CENTER);
            box.addView(q);
            row.addView(panelButton(Icons.CHECK, size, () -> { settings.save(); activity.restart(); }));
            row.addView(panelButton(Icons.CLOSE, size, () -> {
                declinedKey = settings.startKey();
                if (nativeMenu) closePanel(); else buildPanel(PAGE_SETTINGS);
            }));
            box.addView(row);
        } else {
            row.addView(panelButton(Icons.CHECK, size, this::closePanel));
            box.addView(row);
            settingsRows(box);
        }
        ScrollView scroll = new ScrollView(c);
        scroll.addView(box);
        int width = Math.min(dp(page == PAGE_HELP || page == PAGE_GAMEPAD ? 620 : page == PAGE_SETTINGS ? 520 : page == PAGE_HOLD ? 420 : 320),
            Math.round(getWidth() * 0.86f));
        panel.addView(scroll, new LayoutParams(width, -2, Gravity.CENTER));
        if (page == PAGE_SETTINGS) {
            for (int direction : new int[] {-1, 1}) {
                TextView arrow = label(direction < 0 ? "‹" : "›");
                arrow.setTextSize(40);
                arrow.setGravity(Gravity.CENTER);
                arrow.setContentDescription(direction < 0 ? "Previous settings page" : "Next settings page");
                arrow.setOnClickListener(v -> { settingsPage = (settingsPage + direction + 3) % 3; buildPanel(PAGE_SETTINGS); });
                panel.addView(arrow, new LayoutParams(dp(56), dp(80), Gravity.CENTER_VERTICAL | (direction < 0 ? Gravity.LEFT : Gravity.RIGHT)));
            }
        }
    }

    /** A line of the menu button's choices: its icon and what it opens. */
    private View choiceRow(int icon, String text, Runnable action) {
        LinearLayout line = new LinearLayout(getContext());
        line.setGravity(Gravity.CENTER_VERTICAL);
        line.setPadding(dp(6), dp(10), dp(6), dp(10));
        line.setMinimumHeight(dp(56));
        View mark = new View(getContext()) {
            private final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
            @Override protected void onDraw(Canvas canvas) {
                p.setColor(Color.rgb(255, 205, 50));
                Icons.draw(canvas, icon, getWidth() / 2f, getHeight() / 2f, Math.min(getWidth(), getHeight()), p);
            }
        };
        line.addView(mark, new LinearLayout.LayoutParams(dp(30), dp(30)));
        TextView t = label(text);
        t.setTextSize(16);
        t.setPadding(dp(14), 0, 0, 0);
        line.addView(t, new LinearLayout.LayoutParams(0, -2, 1));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.argb(255, 34, 34, 46));
        bg.setCornerRadius(dp(10));
        line.setBackground(bg);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(4), 0, dp(4));
        line.setLayoutParams(lp);
        line.setOnClickListener(v -> action.run());
        return line;
    }

    private void settingsRows(LinearLayout box) {
        box.addView(heading((settingsPage + 1) + " / 3"));
        if (settingsPage == 0) {
        box.addView(heading(Settings.text(Settings.T_CONTROLS)));
        box.addView(toggle(Settings.T_GYRO, settings.gyro, v -> { settings.gyro = v; }));
        box.addView(slider(Settings.T_GYRO_SPEED, 0.3f, 3f, settings.gyroSpeed, v -> settings.gyroSpeed = v));
        box.addView(toggle(Settings.T_GYRO_INVERT_V, settings.invertGyroVertical, v -> settings.invertGyroVertical = v));
        box.addView(toggle(Settings.T_LEFT, settings.leftHanded, v -> settings.leftHanded = v));
        box.addView(slider(Settings.T_SIZE, 0.7f, 1.5f, settings.buttonScale, v -> settings.buttonScale = v));
        box.addView(slider(Settings.T_OPACITY, 0.25f, 0.95f, settings.buttonOpacity, v -> settings.buttonOpacity = v));
        box.addView(toggle(Settings.T_VIBRATION, settings.vibration, v -> settings.vibration = v));
        box.addView(toggle(Settings.T_TOUCH_ADAPTATIONS, settings.touchAdaptations, v -> settings.touchAdaptations = v));
        box.addView(toggle(Settings.T_SHOW_MENU_BUTTON, settings.showMenuButton, v -> settings.showMenuButton = v));
        box.addView(toggle(Settings.T_SHOW_MENU_LABELS, settings.showMenuLabels, v -> settings.showMenuLabels = v));
        box.addView(toggle(Settings.T_SHOW_ACTION_BUTTON, settings.showActionButton, v -> settings.showActionButton = v));
        box.addView(toggle(Settings.T_SHOW_BODY_BUTTON, settings.showBodyButton, v -> settings.showBodyButton = v));
        box.addView(heading(Settings.text(Settings.T_MORE)));
        box.addView(toggle(Settings.T_HIDE_CURSOR, settings.hideCursor, v -> settings.hideCursor = v));
        box.addView(choice(Settings.T_PICKER, new int[] {Settings.T_PICK_STRIP, Settings.T_PICK_FAN, Settings.T_PICK_BOTH},
            new int[] {Settings.PICK_STRIP, Settings.PICK_FAN, Settings.PICK_BOTH}, settings.colorPicker,
            v -> settings.colorPicker = v));
        return;
        }
        if (settingsPage == 1) {
            box.addView(heading(Settings.text(Settings.T_MORE)));
            box.addView(slider(Settings.T_FOV, 40f, 100f, settings.fieldOfView, v -> settings.fieldOfView = v));
            box.addView(slider(Settings.T_VEIN_BRIGHTNESS, 1f, 5f, settings.veinBrightness, v -> settings.veinBrightness = v));
            /* The 2009 game has it on its own options page (tools/patch_options.py). */
            if (Settings.legacyGame)
                box.addView(toggle(Settings.T_REFLECTIONS, settings.reflections, v -> settings.reflections = v));
            box.addView(toggle(Settings.T_DEBUG_COMMANDS, settings.debugCommands, v -> settings.debugCommands = v));
            box.addView(toggle(Settings.T_HEAD_BOB, settings.headBob, v -> settings.headBob = v));
            box.addView(toggle(Settings.T_LOOK_ACCEL, settings.lookAccel, v -> settings.lookAccel = v));
            return;
        }
        /* Read when the game starts: a restart applies them. */
        TextView restart = label("↻ " + Settings.text(Settings.T_RESTART));
        restart.setTextColor(Color.rgb(255, 205, 50));
        restart.setPadding(0, dp(10), 0, dp(4));
        restart.setOnClickListener(v -> buildPanel(PAGE_RESTART));
        Runnable changed = () -> restart.setVisibility(settings.startKey().equals(startKey) ? GONE : VISIBLE);
        box.addView(steps(Settings.T_RENDER_SCALE, 50, 150, Math.round(settings.renderScale * 100),
            v -> { settings.renderScale = v / 100f; changed.run(); }));
        box.addView(steps(Settings.T_UI_SCALE, 70, 150, Math.round(settings.uiScale * 100),
            v -> { settings.uiScale = v / 100f; changed.run(); }));
        box.addView(steps(Settings.T_SUBTITLE_SIZE, 100, 150, Math.round(settings.subtitleSize * 100),
            v -> { settings.subtitleSize = v / 100f; changed.run(); }));
        box.addView(steps(Settings.T_TEXT_SIZE, 100, 150, Math.round(settings.textSize * 100),
            v -> { settings.textSize = v / 100f; changed.run(); }));
        box.addView(toggle(Settings.T_TEXT_CONTRAST, settings.textContrast,
            v -> { settings.textContrast = v; changed.run(); }));
        box.addView(heading(Settings.text(Settings.T_GAME)));
        box.addView(choice(Settings.T_HDR, new int[] {Settings.T_OFF, Settings.T_SIMPLE, Settings.T_FULL},
            new int[] {0, 1, 2}, settings.hdr, v -> { settings.hdr = v; changed.run(); }));
        box.addView(choice(Settings.T_ANISO, new int[] {Settings.T_OFF, -2, -4, -8, -16},
            new int[] {0, 2, 4, 8, 16}, settings.anisotropy, v -> { settings.anisotropy = v; changed.run(); }));
        box.addView(choice(Settings.T_TEXTURES, new int[] {Settings.T_HIGH, Settings.T_LOW},
            new int[] {0, 1}, settings.textureQuality, v -> { settings.textureQuality = v; changed.run(); }));
        box.addView(choice(Settings.T_LIGHTING, new int[] {Settings.T_LOW, Settings.T_MEDIUM, Settings.T_HIGH},
            new int[] {2, 1, 0}, settings.lightmapQuality, v -> { settings.lightmapQuality = v; changed.run(); }));
        box.addView(choice(Settings.T_SOUND, new int[] {Settings.T_SOUND_LOW, Settings.T_SOUND_HIGH},
            new int[] {22, 44}, settings.soundRate, v -> { settings.soundRate = v; changed.run(); }));
        box.addView(restart);
        changed.run();
    }

    private interface FloatSink { void set(float v); }
    private interface BoolSink { void set(boolean v); }
    private interface IntSink { void set(int v); }

    private TextView label(String text) {
        TextView t = new TextView(getContext());
        t.setText(text);
        t.setTextColor(Color.WHITE);
        t.setTextSize(15);
        t.setPadding(0, dp(8), 0, dp(2));
        return t;
    }

    private TextView heading(String text) {
        TextView t = label(text);
        t.setTextSize(13);
        t.setTextColor(Color.rgb(255, 205, 50));
        t.setPadding(0, dp(14), 0, dp(2));
        return t;
    }

    private View slider(int text, float min, float max, float value, FloatSink sink) {
        LinearLayout l = new LinearLayout(getContext());
        l.setOrientation(LinearLayout.VERTICAL);
        l.addView(label(Settings.text(text)));
        SeekBar s = new SeekBar(getContext());
        s.setMax(1000);
        s.setProgress(Math.round((value - min) / (max - min) * 1000));
        s.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar b, int p, boolean user) { sink.set(min + (max - min) * p / 1000f); }
            @Override public void onStartTrackingTouch(SeekBar b) { }
            @Override public void onStopTrackingTouch(SeekBar b) { }
        });
        l.addView(s);
        return l;
    }

    /** A slider in steps of 10 %, its value beside the label. */
    private View steps(int text, int min, int max, int value, IntSink sink) {
        LinearLayout l = new LinearLayout(getContext());
        l.setOrientation(LinearLayout.VERTICAL);
        TextView t = label(Settings.text(text) + ": " + value + "%");
        l.addView(t);
        SeekBar s = new SeekBar(getContext());
        s.setMax((max - min) / 10);
        s.setProgress(Math.max(0, Math.min(s.getMax(), Math.round((value - min) / 10f))));
        s.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar b, int p, boolean user) {
                int v = min + p * 10;
                t.setText(Settings.text(text) + ": " + v + "%");
                sink.set(v);
            }
            @Override public void onStartTrackingTouch(SeekBar b) { }
            @Override public void onStopTrackingTouch(SeekBar b) { }
        });
        l.addView(s);
        return l;
    }

    /** A label and a drawn switch (the platform Switch is near invisible on the black theme). */
    private View toggle(int text, boolean value, BoolSink sink) {
        LinearLayout row = new LinearLayout(getContext());
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(0, dp(6), 0, dp(6));
        TextView t = label(Settings.text(text));
        t.setPadding(0, 0, dp(10), 0);
        row.addView(t, new LinearLayout.LayoutParams(0, -2, 1));
        final boolean[] on = {value};
        View pill = new View(getContext()) {
            private final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);

            @Override protected void onDraw(Canvas c) {
                float w = getWidth(), h = getHeight(), r = h / 2f;
                p.setStyle(Paint.Style.FILL);
                p.setColor(on[0] ? Color.rgb(170, 125, 20) : Color.rgb(85, 85, 95));
                c.drawRoundRect(0, 0, w, h, r, r, p);
                p.setColor(on[0] ? Color.rgb(255, 205, 50) : Color.rgb(215, 215, 222));
                c.drawCircle(on[0] ? w - r : r, r, r * 0.8f, p);
            }
        };
        row.addView(pill, new LinearLayout.LayoutParams(dp(52), dp(30)));
        row.setOnClickListener(v -> {
            on[0] = !on[0];
            sink.set(on[0]);
            pill.invalidate();
        });
        return row;
    }

    /** A label and a row of choices; a negative text id is a number ("×n"). */
    private View choice(int text, int[] texts, int[] values, int value, IntSink sink) {
        LinearLayout l = new LinearLayout(getContext());
        l.setOrientation(LinearLayout.VERTICAL);
        l.addView(label(Settings.text(text)));
        LinearLayout row = new LinearLayout(getContext());
        row.setPadding(0, dp(4), 0, dp(4));
        TextView[] cells = new TextView[texts.length];
        final int[] current = {value};
        Runnable paint = () -> {
            for (int i = 0; i < cells.length; ++i) {
                boolean on = values[i] == current[0];
                GradientDrawable d = new GradientDrawable();
                d.setCornerRadius(dp(8));
                d.setColor(on ? Color.rgb(170, 125, 20) : Color.argb(255, 50, 50, 60));
                cells[i].setBackground(d);
                cells[i].setTextColor(on ? Color.WHITE : Color.rgb(205, 205, 212));
            }
        };
        for (int i = 0; i < texts.length; ++i) {
            TextView cell = new TextView(getContext());
            cell.setText(texts[i] < 0 ? "×" + (-texts[i]) : Settings.text(texts[i]));
            cell.setTextSize(14);
            cell.setGravity(Gravity.CENTER);
            cell.setPadding(dp(6), dp(8), dp(6), dp(8));
            final int v = values[i];
            cell.setOnClickListener(x -> { current[0] = v; sink.set(v); paint.run(); });
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, -2, 1);
            lp.setMargins(dp(3), 0, dp(3), 0);
            row.addView(cell, lp);
            cells[i] = cell;
        }
        paint.run();
        l.addView(row);
        return l;
    }

    private View panelButton(int icon, int size, Runnable action) {
        IconButton b = new IconButton(getContext(), icon, (v, down) -> { if (!down) action.run(); });
        b.setOpacity(0.9f);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(size, size);
        lp.setMargins(dp(10), dp(4), dp(10), dp(4));
        b.setLayoutParams(lp);
        return b;
    }

    /* -------------------------------------------------------------- gyro */

    private void registerGyro() {
        unregisterGyro();
        if (!settings.gyro || !resumed) return;
        sensors = (SensorManager) getContext().getSystemService(Context.SENSOR_SERVICE);
        Sensor g = sensors != null ? sensors.getDefaultSensor(Sensor.TYPE_GYROSCOPE) : null;
        if (g == null) { sensors = null; return; }
        gyroTime = 0;
        sensors.registerListener(this, g, SensorManager.SENSOR_DELAY_GAME, handler);
    }

    private void unregisterGyro() {
        if (sensors != null) sensors.unregisterListener(this);
        sensors = null;
    }

    /** Turning the device turns the camera (rates around the screen's axes). */
    @Override public void onSensorChanged(SensorEvent e) {
        long t = e.timestamp;
        float dt = gyroTime == 0 ? 0 : (t - gyroTime) / 1e9f;
        gyroTime = t;
        if (dt <= 0 || dt > 0.1f || mode != WORLD || panelVisible() || padActive) return;
        int rotation = ((WindowManager) getContext().getSystemService(Context.WINDOW_SERVICE)).getDefaultDisplay().getRotation();
        /* A device at rest still reports a little noise: ignore it. */
        float gx = Math.abs(e.values[0]) < 0.015f ? 0 : e.values[0], gy = Math.abs(e.values[1]) < 0.015f ? 0 : e.values[1];
        /* Rates around the screen's up and right axes. */
        float up, right;
        switch (rotation) {
        case Surface.ROTATION_90: up = -gx; right = gy; break;
        case Surface.ROTATION_270: up = gx; right = -gy; break;
        case Surface.ROTATION_180: up = -gy; right = -gx; break;
        default: up = gy; right = gx; break;
        }
        float k = (float) Math.toDegrees(dt) * settings.gyroSpeed * Settings.PIXELS_PER_DEGREE;
        /* Horizontal is always inverted (no option): turning the device one
         * way sweeps the view the other. Vertical is inverted by default, with
         * a setting to undo it; the game's own InvertMouse then applies atop. */
        float vert = settings.invertGyroVertical ? -right : right;
        in.look(up * k, vert * k);
    }

    @Override public void onAccuracyChanged(Sensor sensor, int accuracy) { }

    /* ------------------------------------------------------- touch view */

    /** Everything on the picture that is not a button. */
    private final class TouchView extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        boolean useHint, paintHint, stickShown = true;
        /* WORLD: the stick, the look finger and a finger on the helper */
        private int stickId = -1, lookId = -1, hintId = -1;
        private boolean hintUse;
        private float stickCx, stickCy, lookX, lookY, lookDownX, lookDownY;
        private long stickDownTime, lookDownTime, lookTime;
        private float lookSpeed;   /* the look finger's sideways speed, dp a second (smoothed) */
        private boolean stickMoved, lookMoved;
        /* UI: direct manipulation */
        private int uiId = -1, uiId2 = -1;
        private float uiDownX, uiDownY, uiLastX, uiLastY, pinchDist, zoomRest, lastMidY, scrollRest;
        private long uiDownTime, lastTapTime;
        private float lastTapX, lastTapY;
        private boolean dragging, longFired, twoFinger, listScroll, heartProgressHeld;
        private boolean twoMoved;   /* the two fingers zoomed, scrolled or moved */
        private int uiFingers, uiId3 = -1;
        private float threeDownX, threeDownY;
        private boolean bodyStatsHeld, bodyDragPending, bodyLymphaHeld;
        private boolean bodyReleasePending, bodyTransferHeld;
        private int bodyTransferColour = -1;
        private final Runnable bodyTransferRelease = this::releaseBodyTransfer;
        private void resetBodyTransferColour() {
            bodyTransferColour = -1;
            GameActivity.nativeBodyTransferColour();  // Discard a previous transfer's unread event.
        }
        private void showBodyTransferLabel() {
            boolean memory = pouring && memoryPour;
            if (!memory && (!bodyTransferHeld || !bodyLymphaHeld)) return;
            int colour = GameActivity.nativeBodyTransferColour();
            if (colour >= 0 && colour < PalettePicker.COLOURS) bodyTransferColour = colour;
            if (bodyTransferColour >= 0) (memory ? memoryPicker : picker).showLabel(bodyTransferColour);
        }
        private void releaseBodyTransfer() {
            showBodyTransferLabel();
            if (bodyTransferHeld) in.button(Input.LEFT, false);
            bodyTransferHeld = false;
            bodySource(false);
            releaseHand();
        }
        private int bodyTarget = -1;
        private void captureBodyTarget() {
            if (bodyTarget < 0) bodyTarget = GameActivity.nativeBodyTarget();
        }
        private final Runnable bodyDragReady = this::finishBodyDragStart;
        private void finishBodyDragStart() {
            bodyDragPending = false;
            if ((dragging || bodyReleasePending) && dragButton == Input.LEFT && screen == S_BODY) {
                in.cursorTo(uiLastX / getWidth(), uiLastY / getHeight());
                if (bodyReleasePending) {
                    bodyReleasePending = false;
                    postDelayed(bodyTransferRelease, 90);
                }
            }
        }
        private boolean skippingLines;
        private boolean videoContact;
        private final Runnable skipHold = new Runnable() {
            @Override public void run() {
                if (!skippingLines) return;
                if (shown(HUD_SUBTITLE, 800)) in.tapKey(skipKey);
                postDelayed(this, 200);
            }
        };

        boolean bodyGesture() { return uiId >= 0 || uiId2 >= 0 || dragging || pouring || bodyTransferHeld || picker.held() || memoryPicker.held(); }

        private void startBodyColour(boolean memory, int colour) {
            if (pouring) return;
            float[] at = (memory ? memoryPicker : picker).heartPoint(colour);
            if (at == null) return;
            in.cursorTo(at[0], at[1]);
            beginPour();
        }

        private void bodyColour(boolean memory, int colour, boolean down) {
            if (!down) { stopPouring(); releaseHand(); return; }
            if (handHolds() && memory && handFrom == HAND_MEMORY && handColour == colour) {
                stopPouring();
                in.tapKey(Input.BODY_RETURN);
                clearHand();
                return;
            }
            if (handHolds()) { useCard(CARD_PUT | (memory ? 0x20 : 0x10)); return; }
            cancel();
            guideUntil = 0;
            heartTicked = false;
            resetBodyTransferColour();
            if (memory) bodyTransferColour = colour;
            float source = bodyAmounts[(memory ? 14 : 0) + colour * 2];
            in.key(Input.BODY_WIDGET, true);
            memoryPour = memory;
            /* An absent colour has nothing to draw out: no pour that can take nothing. */
            if (source > 0.5f) {
                startHand(memory ? HAND_MEMORY : HAND_PALETTE, colour, -1);
                startBodyColour(memory, colour);
            }
        }

        /* The colour in the hand: what it was drawn out of (a heart to the
         * right, its lymph to the left, the Memory, the palette) and how much
         * has left the source since. It stays shown, with the card of where
         * it can go, after the finger lets go, until it is put somewhere or
         * goes back (a tap, a card, the source full again). */
        private static final int HAND_NONE = 0, HAND_HEART = 1, HAND_LYMPHA = 2, HAND_MEMORY = 3, HAND_PALETTE = 4;
        private static final int CARD_NONE = 0, CARD_PUT = 1, CARD_RETURN = 2;
        private int handFrom = HAND_NONE, handColour = -1, handZone = -1;
        private float handPeak = -1, handTaken, handDestAt = -1;
        private boolean handDrawing;
        private final RectF paletteCard = new RectF(), memoryCard = new RectF();
        private int paletteCardAction, memoryCardAction;
        private boolean cardTap;

        private float handSource() {
            switch (handFrom) {
            case HAND_HEART: case HAND_LYMPHA:
                /* The heart's card reports the zone the game last latched. */
                if (handZone < 0 || Math.round(bodyDetails[12]) != handZone) return -1;
                if (handColour < 0) handColour = Math.round(bodyDetails[0]);
                return bodyDetails[handFrom == HAND_LYMPHA && lymphHearts ? 13 : 1];
            case HAND_MEMORY: return bodyAmounts[14 + handColour * 2];
            case HAND_PALETTE: return bodyAmounts[handColour * 2];
            default: return -1;
            }
        }

        private void startHand(int from, int colour, int zone) {
            handFrom = from;
            handColour = colour;
            handZone = zone;
            handPeak = -1;
            handTaken = 0;
            handDestAt = -1;
            handDrawing = true;
            handPeak = handSource();
            android.util.Log.i("TheVoid", "body: hand from " + from + ", colour " + handColour + ", zone " + zone + ", source " + handPeak);
            invalidate();
        }

        private void releaseHand() {
            if (handFrom == HAND_NONE || !handDrawing) return;
            if (lymphHearts && handFrom == HAND_LYMPHA) { clearHand(); return; }
            handDrawing = false;
            handDestAt = -1;
            android.util.Log.i("TheVoid", "body: hand holds " + handTaken + " of colour " + handColour);
            invalidate();
        }

        private void clearHand() {
            if (handFrom == HAND_NONE) return;
            handFrom = HAND_NONE;
            handColour = -1;
            invalidate();
        }

        /** Something of a colour is in the hand, by the layer's count or the game's carrying cursor. */
        private boolean handHolds() {
            return handFrom != HAND_NONE && !handDrawing && handTaken >= 0.5f || shown(HUD_CURSOR_LYMPHA, 300);
        }

        /* Each frame: how much the source gave; the hand let go of (put or back). */
        private void handFrame() {
            if (handFrom == HAND_NONE) return;
            float source = handSource();
            if (source >= 0) {
                if (handPeak < 0 || handDrawing && source > handPeak) handPeak = source;
                handTaken = Math.max(0, handPeak - source);
            }
            if (handDrawing || handColour < 0) return;
            float dest = handFrom == HAND_HEART ? bodyAmounts[14 + handColour * 2]
                : handFrom == HAND_LYMPHA ? bodyAmounts[handColour * 2] : -1;
            if (handDestAt < 0) handDestAt = dest;
            boolean back = source >= 0 && handTaken < 0.5f;
            boolean put = dest >= 0 && handDestAt >= 0 && dest - handDestAt >= Math.max(0.5f, handTaken * 0.5f);
            if (back || put) {
                android.util.Log.i("TheVoid", "body: hand empty (" + (put ? "put" : "back") + ")");
                clearHand();
            }
        }

        /* A tap on a card: the hand's colour into the palette or the Memory
         * (a click on its drop there, as the overlay's drops click), or back. */
        private int cardAt(float x, float y) {
            if (paletteCardAction != CARD_NONE && paletteCard.contains(x, y)) return paletteCardAction | 0x10;
            if (memoryCardAction != CARD_NONE && memoryCard.contains(x, y)) return memoryCardAction | 0x20;
            return 0;
        }

        private void useCard(int card) {
            int colour = handColour;
            haptics.tick();
            if ((card & 0xf) == CARD_RETURN) {
                android.util.Log.i("TheVoid", "body: card, colour " + colour + " back");
                in.tapKey(Input.BODY_RETURN);
            } else {
                PalettePicker side = (card & 0x20) != 0 ? memoryPicker : picker;
                float[] at = colour >= 0 ? side.heartPoint(colour) : null;
                android.util.Log.i("TheVoid", "body: card, colour " + colour + " into the " + ((card & 0x20) != 0 ? "Memory" : "palette")
                    + (at == null ? " (its drop not seen)" : ""));
                if (at != null) {
                    in.key(Input.BODY_WIDGET, true);
                    in.cursorTo(at[0], at[1]);
                    postDelayed(() -> GameActivity.nativeMouseButton(Input.LEFT, true), 40);
                    postDelayed(() -> {
                        GameActivity.nativeMouseButton(Input.LEFT, false);
                        in.key(Input.BODY_WIDGET, false);
                    }, 110);
                }
            }
            clearHand();
        }

        /* The heart under the finger answers at once (no hold): a tick and
         * the arrows; a tap with nothing in the hand shows them a while. */
        private boolean heartTicked;
        private boolean depositHint;
        private float guideX, guideY;
        private long guideUntil;

        private boolean heartShown() {
            if (twoFinger || cardTap) return false;
            if (uiId >= 0) return bodyTarget >= 0 && heartTicked && !(dragging && dragButton == Input.RIGHT);
            return SystemClock.uptimeMillis() < guideUntil;
        }

        /* The last frame drawn of the body's cards (they redraw when it changes). */
        private final float[] drawnDetails = new float[14], drawnAmounts = new float[28], drawnZones = new float[21 * 5];
        private int drawnZoneCount;
        private boolean drawnSomething;

        void bodyFrame(boolean body) {
            if (!body) {
                clearHand();
                guideUntil = 0;
                if (drawnSomething) { drawnSomething = false; invalidate(); }
                return;
            }
            if (uiId >= 0 && !heartTicked && bodyTarget >= 0 && !twoFinger && !dragging && !bodyStatsHeld && !cardTap) {
                heartTicked = true;
                guideX = uiDownX;
                guideY = uiDownY;
                haptics.tick();
                android.util.Log.i("TheVoid", "body: heart " + bodyTarget + " touched at " + uiDownX + "," + uiDownY);
            }
            handFrame();
            boolean heart = heartShown() && handFrom != HAND_MEMORY;
            boolean something = bodyStatsHeld || heart || handFrom != HAND_NONE || zoneLabelCount > 0;
            boolean changed = something != drawnSomething || something && (!java.util.Arrays.equals(drawnDetails, bodyDetails)
                || !java.util.Arrays.equals(drawnAmounts, bodyAmounts) || drawnZoneCount != zoneLabelCount
                || !java.util.Arrays.equals(drawnZones, zoneLabels));
            /* The guide's arrows glide: they alone redraw every frame. */
            if (changed || heart && !bodyTransferHeld && !depositHint) {
                System.arraycopy(bodyDetails, 0, drawnDetails, 0, drawnDetails.length);
                System.arraycopy(bodyAmounts, 0, drawnAmounts, 0, drawnAmounts.length);
                System.arraycopy(zoneLabels, 0, drawnZones, 0, drawnZones.length);
                drawnZoneCount = zoneLabelCount;
                drawnSomething = something;
                invalidate();
            }
        }

        /* The main and pause menus name their glyphs (the mouse's hover would):
         * each where it was last drawn, while the game draws it. */
        private final float[] menuRects = new float[(MENU_GLYPHS + 1) * 4];
        private final long[] menuSeen = new long[MENU_GLYPHS + 1];
        private int menuShown;

        void menuFrame(int mask, boolean on) {
            long now = SystemClock.uptimeMillis();
            on &= settings.showMenuLabels && !shown(HUD_ARROWS, 500);
            int visible = 0;
            boolean changed = false;
            for (int i = 0; i <= MENU_GLYPHS; ++i) {
                int slot = i < MENU_GLYPHS ? SLOT_MENU + i : SLOT_EXIT;
                if (on && (mask & (1 << slot)) != 0) {
                    menuSeen[i] = now;
                    for (int k = 0; k < 4; ++k) {
                        float v = slotValues[slot * PalettePicker.FLOATS + 64 + k];
                        if (Math.abs(menuRects[i * 4 + k] - v) > 0.002f) { menuRects[i * 4 + k] = v; changed = true; }
                    }
                }
                if (on && now - menuSeen[i] < 300) visible |= 1 << i;
            }
            if (changed || visible != menuShown) {
                menuShown = visible;
                invalidate();
            }
        }

        /* Where each glyph's name stands, on its free side (the glyphs fall
         * in a diagonal): new game at the left, load above, save at the
         * right (high, clear of continue below it), options left, credits
         * right (low, clear of continue above it), continue right, exit left. */
        private static final int ABOVE = 0, LEFT = 1, RIGHT = 2;
        private final int[] menuSide = {LEFT, ABOVE, RIGHT, RIGHT, LEFT, RIGHT, RIGHT, LEFT};
        private final float[] menuHeight = {.5f, 0, .3f, .3f, .5f, .85f, .5f, .5f};
        private final Paint menuPaint = new Paint(Paint.ANTI_ALIAS_FLAG);

        private void drawMenuLabels(Canvas c) {
            float w = getWidth(), h = getHeight(), size = dp(15) * settings.textSize;
            menuPaint.setTypeface(android.graphics.Typeface.create(android.graphics.Typeface.SERIF, android.graphics.Typeface.NORMAL));
            menuPaint.setTextSize(size);
            for (int i = 0; i <= MENU_GLYPHS; ++i) {
                if ((menuShown & (1 << i)) == 0 || i == 3) continue;
                float x0 = Math.min(menuRects[i * 4], menuRects[i * 4 + 2]) * w, x1 = Math.max(menuRects[i * 4], menuRects[i * 4 + 2]) * w;
                float y0 = Math.min(menuRects[i * 4 + 1], menuRects[i * 4 + 3]) * h, y1 = Math.max(menuRects[i * 4 + 1], menuRects[i * 4 + 3]) * h;
                if (x1 - x0 < dp(8) || y1 - y0 < dp(8)) continue;
                /* The painted letter fills the middle of its image. */
                float ix = (x1 - x0) * .22f, iy = (y1 - y0) * .22f;
                x0 += ix; x1 -= ix; y0 += iy; y1 -= iy;
                String text = Settings.gameText(7 + i);
                if (text.isEmpty()) continue;
                float width = menuPaint.measureText(text), x, y;
                switch (menuSide[i]) {
                case LEFT: x = x0 - dp(8) - width; y = y0 + (y1 - y0) * menuHeight[i] + size * .35f; break;
                case RIGHT: x = x1 + dp(8); y = y0 + (y1 - y0) * menuHeight[i] + size * .35f; break;
                default: x = (x0 + x1 - width) / 2; y = y0 - dp(6); break;
                }
                x = Math.max(dp(8), Math.min(w - width - dp(8), x));
                y = Math.max(size + dp(4), Math.min(h - dp(6), y));
                if (settings.textContrast) {
                    menuPaint.setColor(Color.argb(150, 6, 8, 12));
                    c.drawRoundRect(x - dp(8), y - size * 1.05f, x + width + dp(8), y + size * .45f, dp(9), dp(9), menuPaint);
                }
                menuPaint.setShadowLayer(dp(3), 0, dp(1), Color.BLACK);
                menuPaint.setColor(i == 3 ? Color.argb(190, 200, 196, 186) : 0xFFF0E6CE);
                c.drawText(text, x, y, menuPaint);
                menuPaint.clearShadowLayer();
            }
        }

        private boolean bodyMemory(float x, float y) {
            for (int colour = 0; colour < PalettePicker.COLOURS; ++colour)
                if (inSlot(8 + colour, x, y, 0)) return true;
            return false;
        }

        private void stopSkipping() {
            skippingLines = false;
            removeCallbacks(skipHold);
        }

        private boolean beginSubtitle(float x, float y) {
            if (!onSubtitle(x / getWidth(), y / getHeight())) return false;
            skippingLines = true;
            postDelayed(skipHold, 450);
            return true;
        }
        private long twoDownTime;
        private float twoDownX, twoDownY;   /* where the second finger landed */
        private int dragButton = Input.LEFT;
        private float dragScale;
        private Runnable clickDown, clickUp;
        private boolean pouring, pourPressed, memoryPour;
        private void beginPour() {
            if (pouring) return;
            pouring = pourPressed = true;
            in.button(Input.LEFT, true);
        }
        private void releasePour() {
            if (pourPressed) in.button(Input.LEFT, false);
            pourPressed = false;
        }

        private void stopPouring() {
            showBodyTransferLabel();
            pouring = memoryPour = false;
            releasePour();
            in.key(Input.BODY_WIDGET, false);
        }
        private final Runnable uiLongPress = () -> {
            if (uiId >= 0 && !dragging && !twoFinger) {
                /* The body's original carry contexts accumulate while the
                 * left button stays held, then keep the colour on release. */
                if (screen == S_BODY) {
                    /* A heart answers its touch at once (bodyFrame). */
                    if (settings.touchAdaptations) return;
                    longFired = true;
                    beginPour();
                    return;
                }
                longFired = true;
                /* The map: a finger held still only points, as the mouse
                 * resting on a chamber shows it (its sister's face, its
                 * name); let go, nothing is clicked (a click sends the hero
                 * there). Its right button is a two-finger tap. */
                if (screen == S_MAP) {
                    android.util.Log.i("TheVoid", "map: pointing");
                    return;
                }
                in.click(Input.RIGHT);
            }
        };
        /* A list of saves follows the finger a row at a time; the journal's
         * texts follow it pixel by pixel (its patched script takes the
         * wheel's 1/120 notch as one of the game's pixels:
         * tools/patch_database.py). Both keep going for a while after a
         * flick. */
        private float flingVelocity, flingRest;   /* rows (or game pixels) a second; the fraction not sent */
        private boolean flingPixels;
        private long flingTime;
        private final android.view.VelocityTracker[] tracker = new android.view.VelocityTracker[1];
        private final Runnable fling = new Runnable() {
            @Override public void run() {
                long now = SystemClock.uptimeMillis();
                float dt = (now - flingTime) / 1000f;
                flingTime = now;
                flingRest += flingVelocity * dt;
                if (flingPixels) {
                    int step = (int) flingRest;
                    if (step != 0) { in.wheel(step); flingRest -= step; }
                } else {
                    while (flingRest >= 1) { in.wheel(-120); flingRest -= 1; }
                    while (flingRest <= -1) { in.wheel(120); flingRest += 1; }
                }
                flingVelocity *= (float) Math.pow(0.05, dt);   /* slows to 5 % in a second */
                if (Math.abs(flingVelocity) > (flingPixels ? 20f : 1.5f)) postOnAnimation(this);
            }
        };

        /** The game's pixels a pixel of this view (its picture's height over the view's). */
        private float gamePixel() { return renderH > 0 && getHeight() > 0 ? (float) renderH / getHeight() : 1f; }
        /* PAINT */
        private int strokeId = -1;

        TouchView(Context c) { super(c); }

        private float slop() { return dp(9); }
        /* How far a finger on a heart goes sideways before its colour moves:
         * wider than a tap's slop, so a held finger's tremor carries nothing. */
        private float transferSlop() { return dp(28); }
        private float stickRadius() { return dp(58 * settings.buttonScale); }
        /* A row of the list of saves. */
        private float rowHeight() { return getHeight() * 0.072f; }

        private boolean onHeartProgress(float x, float y) {
            return x <= getHeight() * 0.4f && y >= getHeight() * 0.55f;
        }

        private void heartProgress(boolean show) {
            if (heartProgressHeld == show) return;
            heartProgressHeld = show;
            if (show) in.cursorTo(0, 0);
            in.key(Input.HEART_PROGRESS, show);
        }

        private void bodyStats(boolean show) {
            if (bodyStatsHeld == show) return;
            bodyStatsHeld = show;
            if (show) longFired = true;
            if (!settings.touchAdaptations) in.key(Input.BODY_STATS, show);
            picker.setAmountLabels(show && settings.touchAdaptations);
            memoryPicker.setAmountLabels(show && settings.touchAdaptations);
            invalidate();
        }

        private void bodySource(boolean lympha) {
            if (bodyLymphaHeld == lympha) return;
            bodyLymphaHeld = lympha;
            in.key(Input.BODY_LYMPHA, lympha);
        }

        @Override public boolean onHoverEvent(MotionEvent e) {
            if (screen != S_OBSCURA) return super.onHoverEvent(e);
            heartProgress(e.getActionMasked() != MotionEvent.ACTION_HOVER_EXIT && onHeartProgress(e.getX(), e.getY()));
            return true;
        }

        /** Lets go of everything this view holds (mode switch, pause). */
        void cancel() {
            videoContact = false;
            removeCallbacks(depositStep);
            depositZone = -1;
            stopSkipping();
            bodyStats(false);
            bodySource(false);
            removeCallbacks(bodyDragReady);
            removeCallbacks(bodyTransferRelease);
            boolean bodyTransfer = bodyTransferHeld;
            releaseBodyTransfer();
            clearHand();
            guideUntil = 0;
            depositHint = false;
            cardTap = false;
            bodyDragPending = bodyReleasePending = false;
            heartProgress(false);
            removeCallbacks(uiLongPress);
            stopPouring();
            removeCallbacks(fling);
            if (stickId >= 0) stickRelease();
            if (hintId >= 0 && hintUse) in.button(Input.RIGHT, false);
            hintId = -1;
            endLookUse();
            if (dragging && !listScroll && !(bodyTransfer && dragButton == Input.LEFT)) in.button(dragButton, false);
            dragging = listScroll = false;
            if (strokePress != null) { removeCallbacks(strokePress); strokePress = null; strokeId = -1; }
            if (strokeId >= 0) { strokeId = -1; in.button(Input.LEFT, false); }
            if (clickDown != null) { removeCallbacks(clickDown); clickDown.run(); }
            if (clickUp != null) { removeCallbacks(clickUp); clickUp.run(); }
            lookId = uiId = uiId2 = -1;
            uiFingers = 0;
            uiId3 = -1;
            colourId = cancelFinger = -1;
            twoFinger = false;
            invalidate();
        }

        @Override protected void onDraw(Canvas c) {
            if (settings.touchAdaptations && screen == S_BODY) drawBodyDetails(c);
            if (menuShown != 0 && (screen == S_MAIN || screen == S_PAUSE)) drawMenuLabels(c);
            if (mode != WORLD || !stickShown) return;
            if (lookUse && lookId >= 0) {   /* the finger that uses */
                paint.setStyle(Paint.Style.STROKE);
                paint.setStrokeWidth(dp(3));
                paint.setColor(Color.argb(150, 255, 255, 255));
                c.drawCircle(lookX, lookY, dp(40), paint);
            }
        }

        private String amount(float value) { return Float.isFinite(value) && value >= 0 ? Integer.toString((int) Math.ceil(value)) : "—"; }

        private float bodyTextWidth;
        private float bodyTextRight;
        private void bodyCard(Canvas c, float x, float y, float width, float height) {
            bodyTextWidth = Math.max(1, width - dp(32));
            bodyTextRight = x + width - dp(12);
            paint.setStyle(Paint.Style.FILL);
            paint.setColor(Color.argb(settings.textContrast ? 235 : 180, 10, 10, 16));
            c.drawRoundRect(x, y, x + width, y + height, dp(12), dp(12), paint);
        }

        private void bodyLine(Canvas c, String text, float x, float y, float size, int colour) {
            paint.setStyle(Paint.Style.FILL);
            paint.setTextAlign(Paint.Align.LEFT);
            paint.setTextSize(dp(size) * settings.textSize);
            float width = paint.measureText(text);
            float available = Math.max(1, Math.min(bodyTextWidth, bodyTextRight - x));
            if (width > available) paint.setTextSize(paint.getTextSize() * available / width);
            paint.setColor(colour);
            c.drawText(text, x, y, paint);
        }

        /* The stats' card fits its widest line: the lines are made and
         * measured again only when a value or a name changes, not in each
         * frame the body redraws. */
        private final String[] statLines = new String[8];
        private final float[] statValues = new float[9];
        private float statWidth, statTextSize;
        private int statNames = -1;

        private void layoutStats() {
            float size = dp(18) * settings.textSize;
            int names = 0;
            for (String name : bodyStatNames) if (name != null && !name.isEmpty()) ++names;
            boolean same = statLines[0] != null && statTextSize == size && statNames == names;
            for (int i = 0; i < 9 && same; ++i) same = Float.compare(statValues[i], bodyDetails[3 + i]) == 0;
            if (same) return;
            for (int i = 0; i < 9; ++i) statValues[i] = bodyDetails[3 + i];
            statTextSize = size;
            statNames = names;
            statLines[0] = "♡  "
                + amount(bodyDetails[3]) + " / " + amount(bodyDetails[4]);
            for (int i = 0; i < 7; ++i) {
                String name = bodyStatNames[i] == null || bodyStatNames[i].isEmpty()
                    ? Settings.gameText(i) : bodyStatNames[i];
                statLines[i + 1] = name + ": " + Math.round(bodyDetails[5 + i]) + "%";
            }
            paint.setTextSize(size);
            statWidth = dp(16) + paint.measureText(statLines[0]);
            for (int i = 1; i < 8; ++i) statWidth = Math.max(statWidth, dp(38) + paint.measureText(statLines[i]));
            statWidth += dp(20);
        }

        private void drawBodyDetails(Canvas c) {
            float w = getWidth(), h = getHeight(), scale = settings.textSize;
            paletteCardAction = memoryCardAction = CARD_NONE;
            if (bodyStatsHeld) {
                layoutStats();
                float row = Math.min(dp(27) * scale, (h - dp(16)) / 9.2f);
                float width = Math.min(w - dp(16), Math.max(dp(200), statWidth));
                float height = row * 9.2f, left = (w - width) / 2, top = Math.max(dp(8), (h - height) / 2);
                bodyCard(c, left, top, width, height);
                bodyLine(c, statLines[0], left + dp(16), top + row, 18, Color.WHITE);
                for (int i = 0; i < 7; ++i) {
                    float y = top + row * (i + 2.2f);
                    paint.setColor(picker.colour(i));
                    paint.setStyle(Paint.Style.FILL);
                    c.drawCircle(left + dp(22), y - dp(5), dp(6), paint);
                    bodyLine(c, statLines[i + 1], left + dp(38), y, 18, picker.colour(i));
                }
                return;
            }
            float line = dp(23) * scale;
            boolean heart = heartShown() && handFrom != HAND_MEMORY;
            int colour = Math.round(bodyDetails[0]);
            heart &= colour >= 0 && colour < 7;
            heartCardTop = heartCardBottom = -1;
            drawZoneLabels(c);
            if (heart) drawHeartCard(c, colour, line);
            if (handFrom != HAND_NONE && handColour >= 0 && handColour < 7 && (handDrawing || handTaken >= 0.5f)) {
                /* Nothing drawn out yet (the palette gives none to the hand): the source's card alone. */
                if (handTaken >= 0.5f && handFrom != HAND_MEMORY) drawHandDrop(c, handColour, handTaken, handPeak, line);
                /* Where the colour can go: a heart's into the Memory, its
                 * lymph into the palette; one poured out of either goes back
                 * there (or into a heart, tapped). */
                int put = handDrawing ? CARD_NONE : CARD_PUT, back = handDrawing ? CARD_NONE : CARD_RETURN;
                switch (handFrom) {
                case HAND_HEART: sideCards(c, handColour, false, true, put, line); break;
                case HAND_LYMPHA: sideCards(c, handColour, true, false, put, line); break;
                /* Drawn out of the Memory: its card, by the drop the finger holds. */
                case HAND_MEMORY: sideCards(c, handColour, false, true, CARD_NONE, line); break;
                default: sideCards(c, handColour, true, false, back, line); break;
                }
            } else if (heart && !bodyTransferHeld && !depositHint) {
                sideCards(c, colour, lymphHearts, true, CARD_NONE, line);
            }
            if (heart && !bodyTransferHeld && !depositHint) drawHeartGuide(c, colour);
        }

        /* The heart held: its colour, how much it holds (the lymph its
         * capillaries hold a separate reserve in 2008) and its gesture, compact, at
         * the top; at the bottom when the finger is in the upper half. */
        private void drawHeartCard(Canvas c, int colour, float line) {
            float w = getWidth(), h = getHeight(), scale = settings.textSize;
            float current = bodyDetails[1], maximum = bodyDetails[2];
            String name = Settings.gameText(colour);
            String held = "♡  " + amount(current) + " / " + amount(maximum);
            paint.setTextSize(dp(20) * scale);
            float text = paint.measureText(name);
            paint.setTextSize(dp(17) * scale);
            text = Math.max(text, paint.measureText(held));
            float glyphSize = dp(40) * Math.min(1.3f, scale);
            float width = Math.min(w * .3f, Math.max(dp(150), dp(14) + text + dp(10) + glyphSize + dp(12)));
            String lymph = lymphHearts ? "↳  " + amount(bodyDetails[13]) : "";
            float height = line * (lymphHearts ? 3.9f : 2.9f), left = (w - width) / 2;
            float y = uiId >= 0 ? uiDownY : guideY;
            /* Low, it stands above the Back button's row. */
            float top = y < h / 2 ? h - height - dp(78) : dp(12);
            heartCardTop = top;
            heartCardBottom = top + height;
            bodyCard(c, left, top, width, height);
            bodyTextWidth = Math.max(1, width - dp(36) - glyphSize);
            bodyTextRight = left + width - glyphSize - dp(20);
            bodyLine(c, name, left + dp(14), top + line, 20, picker.colour(colour));
            bodyLine(c, held, left + dp(14), top + line * 1.95f, 17, Color.WHITE);
            if (lymphHearts) bodyLine(c, lymph, left + dp(14), top + line * 2.9f, 17, Color.WHITE);
            bar(c, left + dp(14), top + line * (lymphHearts ? 3.3f : 2.3f), width - dp(28), current, 0, maximum, colour);
            Bitmap glyph = bodyGlyph(Math.round(bodyDetails[12]));
            if (glyph != null) {
                paint.setColor(Color.WHITE);
                float gx = left + width - glyphSize - dp(10), gy = top + (line * 2.2f - glyphSize) / 2 + dp(2);
                c.drawBitmap(glyph, null, new RectF(gx, gy, gx + glyphSize, gy + glyphSize), paint);
            }
        }

        /** A bar filled to `current`, then to `current + more` lighter, of `maximum`. */
        private void bar(Canvas c, float x, float y, float width, float current, float more, float maximum, int colour) {
            paint.setStyle(Paint.Style.FILL);
            paint.setColor(Color.argb(100, 255, 255, 255));
            c.drawRect(x, y, x + width, y + dp(5), paint);
            if (maximum <= 0) return;
            float a = Math.max(0, Math.min(1, current / maximum)), b = Math.max(0, Math.min(1, (current + more) / maximum));
            if (b > a) {
                paint.setColor((picker.colour(colour) & 0xffffff) | 0x90000000);
                c.drawRect(x + width * a, y, x + width * b, y + dp(5), paint);
            }
            paint.setColor(picker.colour(colour));
            c.drawRect(x, y, x + width * a, y + dp(5), paint);
        }

        /* A heart touched, nothing taken yet: arrows from the finger to either
         * side, gliding outwards, where its colour goes (left the palette,
         * right the Memory). */
        private void drawHeartGuide(Canvas c, int colour) {
            float x = uiId >= 0 ? uiDownX : guideX, y = uiId >= 0 ? uiDownY : guideY, r = dp(26);
            float t = (SystemClock.uptimeMillis() % 1100L) / 1100f;
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(dp(3));
            paint.setColor((picker.colour(colour) & 0xffffff) | 0xd0000000);
            c.drawCircle(x, y, r, paint);
            paint.setStrokeCap(Paint.Cap.ROUND);
            for (int side = lymphHearts ? -1 : 1; side <= 1; side += 2) {
                for (int k = 0; k < 3; ++k) {
                    float along = (k + t) / 3f;   /* 0 at the ring, 1 at the end */
                    float cx = x + side * (r + dp(14) + along * dp(54)), s = dp(9);
                    paint.setColor(Color.argb((int) (235 * (1 - along) + 20), 255, 255, 255));
                    c.drawLine(cx - side * s, y - s, cx, y, paint);
                    c.drawLine(cx - side * s, y + s, cx, y, paint);
                }
            }
            paint.setStrokeCap(Paint.Cap.BUTT);
        }

        /* A colour gathered into the hand: a drop at the centre fills as more
         * is drawn in (of `total`, what the source held), with how much and
         * the colour's name. */
        private float heartCardTop = -1, heartCardBottom = -1;

        private void drawHandDrop(Canvas c, int colour, float taken, float total, float line) {
            float w = getWidth(), h = getHeight();
            int col = picker.colour(colour);
            float cx = w / 2, cy = h * .42f, r = dp(44) * settings.textSize;
            /* Clear of the heart's card, above or below it. */
            if (heartCardTop >= 0 && heartCardTop > h / 2) cy = Math.min(cy, heartCardTop - r - line - dp(22));
            else if (heartCardBottom >= 0) cy = Math.max(cy, heartCardBottom + r + dp(20));
            paint.setTextSize(dp(15) * settings.textSize);
            String caption = Settings.gameText(colour);
            float half = Math.max(r + dp(16), paint.measureText(caption) / 2 + dp(14));
            paint.setStyle(Paint.Style.FILL);
            paint.setColor(Color.argb(settings.textContrast ? 220 : 160, 10, 10, 16));
            c.drawRoundRect(cx - half, cy - r - dp(12), cx + half, cy + r + line + dp(14), dp(18), dp(18), paint);
            /* the hand's drop fills from below with the colour as it is drawn in */
            float fill = total > 0.5f ? Math.min(1f, taken / total) : (taken > 0 ? 1f : 0f);
            c.save();
            c.clipRect(cx - r, cy + r - 2 * r * fill, cx + r, cy + r);
            paint.setColor(col);
            c.drawCircle(cx, cy, r, paint);
            c.restore();
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(Math.max(2f, dp(2)));
            paint.setColor(Color.argb(230, 255, 255, 255));
            c.drawCircle(cx, cy, r, paint);
            paint.setStyle(Paint.Style.FILL);
            paint.setTextAlign(Paint.Align.CENTER);
            float size = dp(22) * settings.textSize;
            paint.setTextSize(size);
            /* White, but dark on a light colour that fills the drop up past
             * the number (amber on amber would not read; dark on the empty
             * drop would not either). */
            int lum = (((col >> 16) & 0xff) * 299 + ((col >> 8) & 0xff) * 587 + (col & 0xff) * 114) / 1000;
            float baseline = cy + size * .35f;
            boolean covered = cy + r - 2 * r * fill <= baseline - size * .8f;
            paint.setColor(lum > 150 && covered ? 0xFF101018 : 0xFFFFFFFF);
            if (!covered) paint.setShadowLayer(dp(2), 0, 0, Color.BLACK);
            c.drawText("+" + Math.round(taken), cx, baseline, paint);
            paint.clearShadowLayer();
            paint.setTextSize(dp(15) * settings.textSize);
            paint.setColor(0xFFF0E8D4);
            c.drawText(caption, cx, cy + r + line, paint);
            paint.setTextAlign(Paint.Align.LEFT);
        }

        /* A Memory colour carried: each heart that can take it says how much
         * it holds, right above the heart where the game's camera shows it,
         * on the cards' backing and rimmed in the colour carried. The game's
         * pt_zone points stand above and left of the hearts drawn on the
         * body (by 35 and 12 of its pixels, measured on the Pixel 10). */
        private void drawZoneLabels(Canvas c) {
            labelsDrawn = 0;
            if (handFrom != HAND_MEMORY || zoneLabelCount <= 0 || renderW <= 0 || renderH <= 0) return;
            final float below = 35, right = 12;
            float w = getWidth(), h = getHeight(), size = dp(14) * settings.textSize, pad = dp(6), radius = dp(26);
            paint.setTextSize(size);
            paint.setTextAlign(Paint.Align.CENTER);
            Paint.FontMetrics metrics = paint.getFontMetrics();
            for (int i = 0; i < zoneLabelCount; ++i) {
                float x = (zoneLabels[5 * i + 1] + right) / renderW * w;
                float y = (zoneLabels[5 * i + 2] + below) / renderH * h;   /* the heart */
                if (x < -pad || x > w + pad || y < -pad || y > h + pad) continue;
                x = Math.max(radius, Math.min(w - radius, x));
                y = Math.max(radius, Math.min(h - radius, y));
                paint.setStyle(Paint.Style.STROKE);
                paint.setStrokeWidth(dp(3));
                paint.setColor(handColour >= 0 && handColour < PalettePicker.COLOURS
                    ? (picker.colour(handColour) & 0xffffff) | 0xd0000000 : Color.WHITE);
                c.drawCircle(x, y, radius, paint);
                String text = amount(zoneLabels[5 * i + 3]) + " / " + amount(zoneLabels[5 * i + 4]);
                float half = paint.measureText(text) / 2 + pad;
                float bottom = y - radius - dp(8), baseline = bottom - pad * .6f - metrics.descent;
                float top = baseline + metrics.ascent - pad * .6f;
                /* Whole on the screen, a heart at its edge too. */
                float dx = Math.max(0, half - x) - Math.max(0, x + half - w), dy = Math.max(0, -top) - Math.max(0, bottom - h);
                paint.setStyle(Paint.Style.FILL);
                paint.setColor(Color.argb(settings.textContrast ? 220 : 160, 10, 10, 16));
                c.drawRoundRect(x - half + dx, top + dy, x + half + dx, bottom + dy, dp(8), dp(8), paint);
                if (handColour >= 0 && handColour < PalettePicker.COLOURS) {
                    paint.setStyle(Paint.Style.STROKE);
                    paint.setStrokeWidth(Math.max(1.5f, dp(1.5f)));
                    paint.setColor((picker.colour(handColour) & 0xffffff) | 0xb0000000);
                    c.drawRoundRect(x - half + dx, top + dy, x + half + dx, bottom + dy, dp(8), dp(8), paint);
                    paint.setStyle(Paint.Style.FILL);
                }
                paint.setColor(Color.WHITE);
                c.drawText(text, x + dx, baseline + dy, paint);
                int k = labelsDrawn++;
                labelCircles[2 * k] = x; labelCircles[2 * k + 1] = y;
                labelRects[4 * k] = x - half + dx; labelRects[4 * k + 1] = top + dy;
                labelRects[4 * k + 2] = x + half + dx; labelRects[4 * k + 3] = bottom + dy;
                labelZones[k] = Math.round(zoneLabels[5 * i]);
            }
            paint.setTextAlign(Paint.Align.LEFT);
        }

        /* The heart labels as drawn: a tap on one puts the hand's colour into
         * its heart, as a tap on the heart would (the label stands over it,
         * where a tap would miss every heart and send the colour back). */
        private final float[] labelRects = new float[21 * 4], labelCircles = new float[21 * 2];
        private final int[] labelZones = new int[21];
        private int labelsDrawn;

        private int labelAt(float x, float y) {
            float margin = dp(6);
            int closest = -1;
            double distance = dp(26) + margin;
            for (int k = 0; k < labelsDrawn; ++k) {
                double d = Math.hypot(x - labelCircles[2 * k], y - labelCircles[2 * k + 1]);
                if (d <= distance) { closest = k; distance = d; }
            }
            if (closest >= 0) return closest;
            for (int k = 0; k < labelsDrawn; ++k)
                if (x >= labelRects[4 * k] - margin && x <= labelRects[4 * k + 2] + margin
                        && y >= labelRects[4 * k + 1] - margin && y <= labelRects[4 * k + 3] + margin) return k;
            return -1;
        }

        /* The script fills this exact zone through its original carry callback. */
        private int depositZone = -1;
        private long depositUntil;
        private final Runnable depositStep = this::depositStep;

        private void depositInto(int label) {
            if (screen != S_BODY || !handHolds() || depositZone >= 0) return;
            int zone = labelZones[label];
            if (!GameActivity.nativeConsoleCommand("setting PortBodyPut " + (zone + 1))) return;
            depositZone = zone;
            depositUntil = SystemClock.uptimeMillis() + 2000;
            guideX = labelCircles[2 * label];
            guideY = labelCircles[2 * label + 1];
            haptics.tick();
            removeCallbacks(depositStep);
            postDelayed(depositStep, 40);
        }

        private void depositStep() {
            if (depositZone < 0 || screen != S_BODY) { depositZone = -1; return; }
            if (zoneLabelCount == 0 && Math.round(bodyDetails[12]) == depositZone) {
                android.util.Log.i("TheVoid", "body: label tapped, colour " + Math.round(bodyDetails[0]) + " into heart " + depositZone);
                depositZone = -1;
                depositHint = true;
                guideUntil = SystemClock.uptimeMillis() + 3000;
                clearHand();
                invalidate();
                return;
            }
            if (SystemClock.uptimeMillis() < depositUntil) { postDelayed(depositStep, 40); return; }
            android.util.Log.i("TheVoid", "body: heart " + depositZone + " did not confirm the transfer");
            depositZone = -1;
        }

        private Bitmap bodyGlyph(int zone) {
            if (zone < 0 || zone >= bodyGlyphs.length) return null;
            if (!bodyGlyphRead[zone]) {
                bodyGlyphRead[zone] = true;
                String game = Settings.gameLanguage.toLowerCase(java.util.Locale.ROOT);
                String language = lymphHearts ? "pl" : game.startsWith("de") || game.startsWith("german") ? "de" : "ru";
                try (java.io.InputStream source = getContext().getAssets().open("overrides/mobile-icons/" + language + "/zone" + zone + ".png")) {
                    bodyGlyphs[zone] = BitmapFactory.decodeStream(source);
                } catch (java.io.IOException e) { android.util.Log.w("TheVoid", "body glyph " + zone + ": " + e); }
            }
            return bodyGlyphs[zone];
        }

        /* The palette's and the Memory's cards for a colour, by its drops at
         * the screen's sides (pointing at them), both at one height: what
         * that side holds and, with the hand's colour, what it will. A card
         * with an action is tapped: the colour goes there, or back. */
        private void sideCards(Canvas c, int colour, boolean palette, boolean memory, int action, float line) {
            float w = getWidth(), h = getHeight();
            boolean left = palette && picker.dotShown(colour), right = memory && memoryPicker.dotShown(colour);
            if (!left && !right) return;
            float ly = left ? picker.dotY(colour) : 0, ry = right ? memoryPicker.dotY(colour) : 0;
            float level = left && right ? (ly + ry) / 2 : left ? ly : ry;
            float width = Math.min(w * .23f, dp(215) * settings.textSize);
            /* Only the palette's card says "→ ◯" (tap to put it there). */
            float height = line * (action == CARD_PUT && left ? 3.55f : 2.75f);
            float top = Math.max(dp(66), Math.min(h - dp(74) - height, level - height / 2));
            float gap = picker.dotRadius() + dp(12);
            if (left) sideCard(c, colour, false, picker.dotX(colour) + gap, top, width, height, ly, action, line);
            if (right) sideCard(c, colour, true, memoryPicker.dotX(colour) - gap - width, top, width, height, ry, action, line);
        }

        private void sideCard(Canvas c, int colour, boolean memory, float left, float top, float width, float height,
                              float dotY, int action, float line) {
            bodyCard(c, left, top, width, height);
            (memory ? memoryCard : paletteCard).set(left, top, left + width, top + height);
            if (memory) memoryCardAction = action; else paletteCardAction = action;
            int at = (memory ? 14 : 0) + colour * 2;
            float current = bodyAmounts[at], maximum = bodyAmounts[at + 1];
            /* What it would hold with the hand's colour put in: a card that takes
             * it, and the Memory the colour is being drawn out of (back there). */
            boolean source = memory && handFrom == HAND_MEMORY && handColour == colour;
            float more = action != CARD_NONE || source ? handTaken : 0;
            float textLeft = left + (memory ? dp(12) : dp(26));
            bodyTextRight = left + width - (memory ? dp(26) : dp(12));
            bodyTextWidth = bodyTextRight - textLeft;
            String name = Settings.gameText(colour);
            if (handFrom == HAND_MEMORY && handColour == colour) name += " → " + amount(handTaken);
            bodyLine(c, name, textLeft, top + line, 16, picker.colour(colour));
            String held = more >= 0.5f && current >= 0 && maximum > 0
                ? amount(current) + " → " + amount(Math.min(maximum, current + more)) + " / " + amount(maximum)
                : amount(current) + " / " + amount(maximum);
            bodyLine(c, held, textLeft, top + line * 1.95f, 18, Color.WHITE);
            bar(c, textLeft, top + line * 2.25f, bodyTextRight - textLeft, current, more, maximum, colour);
            if (action == CARD_PUT && !memory)
                bodyLine(c, "→ ◯",
                    textLeft, top + line * 3.15f, 14, 0xFFC8C0AE);
            /* The arrow at the card's outer side, level with its drop. */
            float ax = memory ? left + width - dp(13) : left + dp(13), s = dp(8) * settings.textSize;
            float ay = Math.max(top + s + dp(4), Math.min(top + height - s - dp(4), dotY));
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(dp(3));
            paint.setStrokeCap(Paint.Cap.ROUND);
            paint.setColor(Color.argb(230, 255, 255, 255));
            int side = memory ? 1 : -1;
            c.drawLine(ax - side * s * .6f, ay - s, ax + side * s * .4f, ay, paint);
            c.drawLine(ax - side * s * .6f, ay + s, ax + side * s * .4f, ay, paint);
            paint.setStrokeCap(Paint.Cap.BUTT);
            if (action != CARD_NONE) {
                paint.setStrokeWidth(Math.max(1.5f, dp(1.5f)));
                paint.setColor((picker.colour(colour) & 0xffffff) | 0xb0000000);
                c.drawRoundRect(left, top, left + width, top + height, dp(12), dp(12), paint);
            }
        }

        /* The stick takes the outer 40 % of the width: the middle, where the
         * game finds what to use, stays for looking and for a finger held
         * on a thing (a Heart just left of the middle is held, not walked). */
        private boolean onStickSide(float x, float y) {
            TouchLayout.Rect zone = touchLayout.get(TouchLayout.MOVE);
            if (zone != null) return zone.contains(x / Math.max(1, getWidth()), y / getHeight());
            return settings.leftHanded ? x > getWidth() * 0.6f : x < getWidth() * 0.4f;
        }

        private boolean onLookZone(float x, float y) {
            TouchLayout.Rect zone = touchLayout.get(TouchLayout.LOOK);
            return zone == null || zone.contains(x / Math.max(1, getWidth()), y / getHeight());
        }

        /** The helper icon the game draws at the centre (128 of 768 units of height). */
        private boolean onHint(float x, float y) {
            return Math.hypot(x - getWidth() / 2f, y - getHeight() / 2f) <= getHeight() * 0.14f;
        }

        private void stick(float x, float y) {
            float r = stickRadius(), dx = x - stickCx, dy = y - stickCy, len = (float) Math.hypot(dx, dy);
            if (len > slop()) stickMoved = true;
            float magnitude = Math.max(0f, Math.min(1f, (len / r - 0.12f) / 0.88f));
            in.movement(len > 0 ? dx / len * magnitude : 0, len > 0 ? -dy / len * magnitude : 0);
        }

        private void stickRelease() {
            in.movement(0, 0);
            stickId = -1;
            invalidate();
        }

        private void useTap() {
            android.util.Log.i("TheVoid", "use: tap");
            in.click(Input.RIGHT);
            haptics.tick();
        }

        /* Quick sideways swipes turn further, so turning round needs no
         * swipe across the whole screen; slow ones (aiming) as they were.
         * The vertical is never sped up. */
        private float accel(float dpPerSecond) {
            if (dpPerSecond <= 500f) return 1f;
            return Math.min(2.5f, 1f + (dpPerSecond - 500f) / 2000f * 1.5f);
        }

        /* A finger held still on the picture uses what the hero faces (the
         * game finds it in the middle), as the mouse's right button held,
         * until the finger lets go — taking a Heart, drawing colour out of a
         * tree or a vein, with or without the game's helper. The camera
         * stays as it is; moving the finger afterwards looks round with the
         * button held, as the mouse would. */
        private static final long HOLD_USE_MS = 450;
        private boolean lookUse, lookUsePressed;

        private final Runnable lookUseStart = () -> {
            if (lookId < 0 || lookMoved || mode != WORLD) return;
            lookUse = lookUsePressed = true;
            haptics.tick();
            android.util.Log.i("TheVoid", "use: a finger held on the picture");
            in.button(Input.RIGHT, true);
            invalidate();
        };

        private void endLookUse() {
            removeCallbacks(lookUseStart);
            if (lookUsePressed) in.button(Input.RIGHT, false);
            if (lookUse) android.util.Log.i("TheVoid", "use: let go");
            lookUse = lookUsePressed = false;
            invalidate();
        }

        /* A scene the hero only watches (the controls locked, no line
         * spoken: a brother's coming, a flight over the place): a tap low
         * on the screen skips it, as a tap on a dialogue's line goes on. */
        private boolean onWatchedScene(float fx, float fy) {
            return mode == WORLD && (hud & HUD_CONTROL_LOCKED) != 0 && fy >= 0.68f && fx >= 0.1f && fx <= 0.9f;
        }

        /* With the hearts' button hidden, the body opens from the screen's
         * lower corner on the action side (as the map's own indicator in its
         * corner opens it). */
        private boolean onBodyCorner(float fx, float fy) {
            return !settings.showBodyButton && (hud & HUD_CONTROL_LOCKED) == 0 && fy >= 0.8f
                && (settings.leftHanded ? fx <= 0.12f : fx >= 0.88f);
        }

        /** A quick tap in the world: the next line, the scene skipped, the body, or the helper's use. */
        private void worldTap(float x, float y) {
            float fx = x / getWidth(), fy = y / getHeight();
            if (onSubtitle(fx, fy)) nextLine();
            else if (onWatchedScene(fx, fy)) {
                android.util.Log.i("TheVoid", "scene: tapped low, skipped");
                haptics.tick();
                in.tapKey(skipKey);
            } else if (onBodyCorner(fx, fy)) {
                android.util.Log.i("TheVoid", "body: the corner tapped");
                haptics.tick();
                in.tapKey(Input.B);
            } else if (useHint) useTap();
        }

        @Override public boolean onTouchEvent(MotionEvent e) {
            if (panelVisible()) return true;
            if ((screen == S_INTRO || screen == S_VIDEO) && shown(HUD_VIDEO, 500)) {
                int action = e.getActionMasked();
                if (action == MotionEvent.ACTION_DOWN) videoContact = true;
                else if (action == MotionEvent.ACTION_UP) {
                    if (videoContact) {
                        if (shown(HUD_JOURNAL_VIDEO, 500)) in.tapKey(Input.ESC);
                        else { videoSkipVisible = !videoSkipVisible; updateButtons(); }
                    }
                    videoContact = false;
                } else if (action == MotionEvent.ACTION_CANCEL) {
                    videoContact = false;
                }
                return true;
            }
            switch (mode) {
            case WORLD: world(e); break;
            case UI: ui(e); break;
            default: paint(e); break;
            }
            return true;
        }

        private void world(MotionEvent e) {
            int a = e.getActionMasked(), idx = e.getActionIndex(), id = e.getPointerId(idx);
            long now = e.getEventTime();
            if (a == MotionEvent.ACTION_DOWN || a == MotionEvent.ACTION_POINTER_DOWN) {
                float x = e.getX(idx), y = e.getY(idx);
                if (a == MotionEvent.ACTION_DOWN && beginSubtitle(x, y)) {
                    lookId = id;
                    lookX = lookDownX = x;
                    lookY = lookDownY = y;
                    lookDownTime = now;
                    lookMoved = false;
                } else if (hintId < 0 && (useHint || paintHint) && onHint(x, y)) {
                    /* The helper itself acts at once, as its button would:
                     * use is held while the finger stays (sucking colour from
                     * a vein), paint switches the brush on. */
                    hintId = id;
                    hintUse = useHint;
                    haptics.tick();
                    if (hintUse) {
                        android.util.Log.i("TheVoid", "use: helper pressed");
                        in.button(Input.RIGHT, true);
                    } else {
                        android.util.Log.i("TheVoid", "paint: helper pressed");
                        setPaintMode(true);
                    }
                } else if (stickShown && onStickSide(x, y) && stickId < 0) {
                    stickId = id;
                    stickCx = x;
                    stickCy = y;
                    stickDownTime = now;
                    stickMoved = false;
                    invalidate();
                } else if (lookId < 0 && onLookZone(x, y)) {
                    lookId = id;
                    lookX = lookDownX = x;
                    lookY = lookDownY = y;
                    lookDownTime = lookTime = now;
                    lookSpeed = 0;
                    lookMoved = false;
                    postDelayed(lookUseStart, HOLD_USE_MS);
                }
            } else if (a == MotionEvent.ACTION_MOVE) {
                for (int i = 0; i < e.getPointerCount(); i++) {
                    int pid = e.getPointerId(i);
                    float x = e.getX(i), y = e.getY(i);
                    if (pid == stickId) {
                        stick(x, y);
                    } else if (pid == lookId) {
                        if (!lookMoved && Math.hypot(x - lookDownX, y - lookDownY) > slop()) {
                            lookMoved = true;
                            stopSkipping();
                            if (!lookUse) removeCallbacks(lookUseStart);
                        }
                        if (lookMoved) {
                            float density = getResources().getDisplayMetrics().density;
                            float k = Settings.SWIPE_DEGREES_PER_DP * Settings.PIXELS_PER_DEGREE / density;
                            long t = e.getEventTime();
                            float dt = Math.max(1, t - lookTime) / 1000f;
                            lookSpeed = lookSpeed * 0.6f + Math.abs(x - lookX) / density / dt * 0.4f;
                            lookTime = t;
                            in.look((x - lookX) * k * (settings.lookAccel ? accel(lookSpeed) : 1f), (y - lookY) * k);
                        }
                        lookX = x;
                        lookY = y;
                    }
                }
            } else if (a == MotionEvent.ACTION_UP || a == MotionEvent.ACTION_POINTER_UP || a == MotionEvent.ACTION_CANCEL) {
                if (a == MotionEvent.ACTION_CANCEL) { cancel(); return; }
                stopSkipping();
                if (id == hintId) {
                    if (hintUse) in.button(Input.RIGHT, false);
                    hintId = -1;
                } else if (id == stickId) {
                    boolean tap = !stickMoved && now - stickDownTime < 300;
                    stickRelease();
                    if (tap) worldTap(e.getX(idx), e.getY(idx));
                } else if (id == lookId) {
                    if (lookUse) {
                        endLookUse();
                    } else {
                        removeCallbacks(lookUseStart);
                        if (!lookMoved && now - lookDownTime < 300) worldTap(lookDownX, lookDownY);
                    }
                    lookId = -1;
                }
            }
        }

        private boolean threeFingerTap(MotionEvent e) {
            int a = e.getActionMasked(), idx = e.getActionIndex();
            if (a == MotionEvent.ACTION_DOWN) {
                uiFingers = 1;
                uiId3 = -1;
                return false;
            }
            if (a == MotionEvent.ACTION_POINTER_DOWN) {
                uiFingers = Math.max(uiFingers, e.getPointerCount());
                if (uiFingers == 3 && uiId3 < 0 && uiId >= 0 && uiId2 >= 0) {
                    uiId3 = e.getPointerId(idx);
                    threeDownX = e.getX(idx);
                    threeDownY = e.getY(idx);
                } else if (uiFingers >= 3) twoMoved = true;
            }
            if (uiFingers < 3) return false;
            for (int i = 0; i < e.getPointerCount(); ++i) {
                int id = e.getPointerId(i);
                float x = id == uiId ? uiDownX : id == uiId2 ? twoDownX : threeDownX;
                float y = id == uiId ? uiDownY : id == uiId2 ? twoDownY : threeDownY;
                if ((id != uiId && id != uiId2 && id != uiId3)
                        || Math.hypot(e.getX(i) - x, e.getY(i) - y) > slop()) twoMoved = true;
            }
            if (a == MotionEvent.ACTION_UP || a == MotionEvent.ACTION_CANCEL) {
                boolean locate = a == MotionEvent.ACTION_UP && screen == S_MAP && uiFingers == 3
                    && !twoMoved && !longFired && e.getEventTime() - uiDownTime < 450;
                cancel();
                if (locate) startCentring();
            }
            return true;
        }

        private void ui(MotionEvent e) {
            if (threeFingerTap(e)) return;
            int a = e.getActionMasked(), idx = e.getActionIndex(), id = e.getPointerId(idx);
            float w = getWidth(), h = getHeight();
            if (tracker[0] == null) tracker[0] = android.view.VelocityTracker.obtain();
            if (a == MotionEvent.ACTION_DOWN) {
                if (screen == S_BODY && depositZone >= 0) {
                    cardTap = true;
                    uiId = id;
                    return;
                }
                int card = settings.touchAdaptations && screen == S_BODY && handFrom != HAND_NONE && !handDrawing
                    ? cardAt(e.getX(idx), e.getY(idx)) : 0;
                if (card != 0) {
                    /* The finger is the card's until it lifts. */
                    cardTap = true;
                    uiId = id;
                    useCard(card);
                    return;
                }
                int label = settings.touchAdaptations && screen == S_BODY && handHolds() && depositZone < 0
                    ? labelAt(e.getX(idx), e.getY(idx)) : -1;
                if (label >= 0) {
                    cardTap = true;   /* the finger is the label's until it lifts */
                    uiId = id;
                    depositInto(label);
                    return;
                }
                cardTap = false;
                heartTicked = false;
                guideUntil = 0;
                depositHint = false;
                if (bodyTransferHeld) cancel();
                tracker[0].clear();
                removeCallbacks(fling);
                uiId = id;
                uiDownX = uiLastX = e.getX(idx);
                uiDownY = uiLastY = e.getY(idx);
                uiDownTime = e.getEventTime();
                dragging = longFired = twoFinger = listScroll = false;
                bodyTarget = -1;
                if (screen == S_BODY) resetBodyTransferColour();
                scrollRest = 0;
                finishClick();
                in.cursorTo(uiDownX / w, uiDownY / h);   /* hover first, as a mouse arrives */
                if (beginSubtitle(uiDownX, uiDownY)) {
                    /* The long hold repeats Enter while the subtitle is on screen. */
                } else if (screen == S_OBSCURA && onHeartProgress(uiDownX, uiDownY)) {
                    heartProgress(true);
                    longFired = true;   /* Pointing at the rings never clicks through. */
                } else if (settings.touchAdaptations && screen == S_BODY && onHeartProgress(uiDownX, uiDownY)) {
                    bodyStats(true);
                } else if (settings.touchAdaptations && screen == S_BODY && bodyMemory(uiDownX / w, uiDownY / h)) {
                    longFired = true;
                } else postDelayed(uiLongPress, screen == S_BODY ? 350 : 500);
            } else if (a == MotionEvent.ACTION_POINTER_DOWN) {
                if (cardTap) return;
                if (uiId >= 0 && uiId2 < 0) {
                    uiId2 = id;
                    twoFinger = true;
                    twoMoved = dragging || listScroll;   /* the first finger was already moving */
                    twoDownTime = e.getEventTime();
                    twoDownX = e.getX(idx);
                    twoDownY = e.getY(idx);
                    removeCallbacks(uiLongPress);
                    stopSkipping();
                    stopPouring();
                    heartProgress(false);
                    bodyStats(false);
                    bodySource(false);
                    if (dragging && !listScroll) {
                        if (bodyTransferHeld) releaseBodyTransfer();
                        else in.button(dragButton, false);
                    }
                    removeCallbacks(bodyDragReady);
                    bodyDragPending = bodyReleasePending = false;
                    dragging = listScroll = false;
                    int i1 = e.findPointerIndex(uiId);
                    pinchDist = (float) Math.hypot(e.getX(idx) - e.getX(i1), e.getY(idx) - e.getY(i1));
                    lastMidY = (e.getY(idx) + e.getY(i1)) / 2;
                    zoomRest = scrollRest = 0;
                }
            } else if (a == MotionEvent.ACTION_MOVE) {
                if (cardTap) return;
                tracker[0].addMovement(e);
                int i1 = e.findPointerIndex(uiId);
                if (i1 < 0) return;
                if (twoFinger) {
                    int i2 = e.findPointerIndex(uiId2);
                    if (i2 < 0) return;
                    /* A finger that slid is no tap, though no zoom or scroll step came of it. */
                    if (Math.hypot(e.getX(i1) - uiDownX, e.getY(i1) - uiDownY) > slop()
                            || Math.hypot(e.getX(i2) - twoDownX, e.getY(i2) - twoDownY) > slop())
                        twoMoved = true;
                    float d = (float) Math.hypot(e.getX(i2) - e.getX(i1), e.getY(i2) - e.getY(i1));
                    /* Pinch: the wheel in small steps as the distance changes
                     * (the game zooms by the wheel's delta, not by notches). */
                    if (pinchDist > 0 && d > 0 && screen != S_JOURNAL) {
                        zoomRest += (float) (Math.log(d / pinchDist) / NOTCH) * 120f * ZOOM_SPEED;
                        pinchDist = d;
                        int step = (int) zoomRest;
                        if (step != 0) { in.wheel(step); zoomRest -= step; twoMoved = true; }
                    }
                    /* Two fingers moving together: scroll (content follows the fingers). */
                    float mid = (e.getY(i1) + e.getY(i2)) / 2;
                    if (screen == S_JOURNAL) {
                        /* The journal's text follows them as it follows one finger. */
                        scrollRest += (mid - lastMidY) * gamePixel();
                        lastMidY = mid;
                        int px = (int) scrollRest;
                        if (px != 0) { in.wheel(px); scrollRest -= px; }
                    } else {
                        scrollRest += mid - lastMidY;
                        lastMidY = mid;
                        float step = dp(34);
                        while (scrollRest > step) { in.wheel(120); scrollRest -= step; twoMoved = true; }
                        while (scrollRest < -step) { in.wheel(-120); scrollRest += step; twoMoved = true; }
                    }
                } else {
                    float x = e.getX(i1), y = e.getY(i1);
                    if (screen == S_OBSCURA && (heartProgressHeld || (!dragging && onHeartProgress(x, y)))) {
                        removeCallbacks(uiLongPress);
                        heartProgress(onHeartProgress(x, y));
                        longFired = true;
                        return;
                    }
                    if (settings.touchAdaptations && screen == S_BODY && !dragging && !pouring && !bodyStatsHeld) {
                        /* Wait for the game's hit-test after hover, then keep
                         * its exact heart/capillary target for this gesture. */
                        if (e.getEventTime() - uiDownTime < 60) return;
                        captureBodyTarget();
                        if (handHolds() && bodyTarget >= 0) { longFired = true; return; }
                        float dx = x - uiDownX, dy = y - uiDownY;
                        if (bodyTarget >= 0) {
                            if (!lymphHearts && dx < 0) return;
                            if (Math.abs(dx) <= transferSlop() || Math.abs(dx) < Math.abs(dy)) return;
                            dragging = true;
                            longFired = false;
                            dragButton = Input.LEFT;
                            removeCallbacks(uiLongPress);
                            bodySource(dx < 0);
                            android.util.Log.i("TheVoid", "body: transfer target " + bodyTarget + ", source "
                                + (dx < 0 ? "lympha" : "heart") + ", from " + uiDownX + "," + uiDownY + ", dx " + dx);
                            in.cursorTo(uiDownX / w, uiDownY / h);
                            in.button(Input.LEFT, true);
                            bodyTransferHeld = true;
                            /* The original hit test pairs each heart with its lymph. */
                            startHand(dx < 0 ? HAND_LYMPHA : HAND_HEART, -1, bodyTarget >> 1);
                            bodyDragPending = true;
                            postDelayed(bodyDragReady, 60);
                        }
                    }
                    if (!dragging && !longFired && Math.hypot(x - uiDownX, y - uiDownY) > slop()) {
                        dragging = true;
                        stopSkipping();
                        removeCallbacks(uiLongPress);
                        stopPouring();
                        if ((screen == S_LIST || screen == S_JOURNAL) && Math.abs(y - uiDownY) > Math.abs(x - uiDownX)) {
                            /* A list of saves, the journal: the finger scrolls it. */
                            listScroll = true;
                        } else {
                            /* The map pans and the body turns with the right
                             * button held; elsewhere a drag is the left
                             * button (sliders). */
                            boolean map = screen == S_MAP, body = screen == S_BODY;
                            dragButton = map || body ? Input.RIGHT : Input.LEFT;
                            dragScale = map ? MAP_PAN : BODY_TURN;
                            if (body) android.util.Log.i("TheVoid", "body: rotate, target " + bodyTarget);
                            in.button(dragButton, true);   /* pressed where the finger landed */
                        }
                    }
                    if (listScroll && screen == S_JOURNAL) {
                        /* The text moves with the finger: the wheel up (the
                         * text down) as far as the finger went down. */
                        scrollRest += (y - uiLastY) * gamePixel();
                        int step = (int) scrollRest;
                        if (step != 0) { in.wheel(step); scrollRest -= step; }
                    } else if (listScroll) {
                        scrollRest += (y - uiLastY) / rowHeight();
                        while (scrollRest >= 1) { in.wheel(120); scrollRest -= 1; }
                        while (scrollRest <= -1) { in.wheel(-120); scrollRest += 1; }
                    } else if (dragging && dragButton == Input.RIGHT) {
                        /* The map moves with the finger: a finger's pixel
                         * is so many of the map's units at its camera's
                         * distance (closer, less mouse); the body turns. */
                        float k = dragScale * 720f / h;
                        if (screen == S_MAP && mapW > 0 && mapF > 0) k = 2f * mapW / (MAP_UNITS_PER_MOUSE * mapF * h);
                        in.look((x - uiLastX) * k, (y - uiLastY) * k);
                    } else if (dragging && !bodyDragPending) {
                        in.cursorTo(x / w, y / h);
                    }
                    uiLastX = x;
                    uiLastY = y;
                }
            } else if (a == MotionEvent.ACTION_POINTER_UP) {
                if (cardTap) return;
                if (id == uiId2) uiId2 = -1;
                else if (id == uiId) { uiId = uiId2; uiId2 = -1; }
            } else if (a == MotionEvent.ACTION_UP || a == MotionEvent.ACTION_CANCEL) {
                if (cardTap) {
                    cardTap = false;
                    uiId = uiId2 = -1;
                    return;
                }
                removeCallbacks(uiLongPress);
                stopSkipping();
                stopPouring();
                heartProgress(false);
                bodyStats(false);
                if (a == MotionEvent.ACTION_CANCEL) { cancel(); return; }
                if (listScroll) {
                    tracker[0].addMovement(e);
                    tracker[0].computeCurrentVelocity(1000);
                    flingPixels = screen == S_JOURNAL;
                    flingVelocity = flingPixels ? tracker[0].getYVelocity() * gamePixel()
                        : -tracker[0].getYVelocity() / rowHeight();
                    flingRest = 0;
                    flingTime = SystemClock.uptimeMillis();
                    if (Math.abs(flingVelocity) > (flingPixels ? 120 : 3) && (flingPixels || screen == S_LIST))
                        postOnAnimation(fling);
                } else if (dragging) {
                    if (bodyDragPending && dragButton == Input.LEFT) bodyReleasePending = true;
                    else if (bodyTransferHeld) releaseBodyTransfer();
                    else { in.button(dragButton, false); bodySource(false); }
                } else if (!twoFinger && !longFired && e.getEventTime() - uiDownTime < 450) {
                    float tx = e.getX(idx), ty = e.getY(idx);
                    boolean body = settings.touchAdaptations && screen == S_BODY;
                    if (onSubtitle(tx / w, ty / h)) nextLine();
                    else if (onExit(tx / w, ty / h)) askExit(tx, ty);
                    else if (body && GameActivity.nativeBodyTarget() < 0) {
                        in.tapKey(Input.BODY_RETURN);
                        clearHand();
                    } else if (body && !handHolds()) {
                        /* A heart tapped with nothing in the hand: its arrows
                         * and cards a while (a click would start a carry). */
                        if (!heartTicked) haptics.tick();
                        guideX = uiDownX;
                        guideY = uiDownY;
                        guideUntil = SystemClock.uptimeMillis() + 1800;
                        invalidate();
                    } else {
                        tap(tx, ty, e.getEventTime());
                        if (body) clearHand();
                    }
                } else if (twoFinger && !twoMoved && e.getEventTime() - twoDownTime < 450) {
                    /* Two fingers tapped together: the right button where
                     * the first one landed. */
                    android.util.Log.i("TheVoid", "ui: two-finger tap (right button)");
                    in.cursorTo(uiDownX / w, uiDownY / h);
                    in.click(Input.RIGHT);
                }
                dragging = listScroll = false;
                uiId = uiId2 = -1;
                twoFinger = false;
            }
        }

        /** A click where the finger was; a second tap close in time and place
         *  lands on the first one's point, so Windows' double-click rectangle
         *  holds for a finger (Load game opens a save on a double click). */
        private void tap(float x, float y, long time) {
            if (time - lastTapTime < 450 && Math.hypot(x - lastTapX, y - lastTapY) < dp(40)) { x = lastTapX; y = lastTapY; }
            lastTapTime = time;
            lastTapX = x;
            lastTapY = y;
            finishClick();
            in.cursorTo(x / getWidth(), y / getHeight());
            clickDown = () -> { GameActivity.nativeMouseButton(Input.LEFT, true); clickDown = null; };
            clickUp = () -> { GameActivity.nativeMouseButton(Input.LEFT, false); clickUp = null; };
            postDelayed(clickDown, 50);
            postDelayed(clickUp, 120);
        }

        /** A quick second tap first finishes the first click. */
        private void finishClick() {
            if (clickDown != null) { removeCallbacks(clickDown); clickDown.run(); }
            if (clickUp != null) { removeCallbacks(clickUp); clickUp.run(); }
        }

        /* PAINT: the cursor goes under the finger without mouse motion (that
         * would turn the camera), the button goes down a frame later so the
         * palette sees the hover first; the stroke moves the cursor only. */
        private Runnable strokePress;
        private float strokeX, strokeY, strokeLength;
        private boolean strokeShort;
        /* A finger in the colours' zone beside the brush: no stroke; up or
         * down it turns the colours, a notch a step. */
        private int colourId = -1;
        private float colourY;

        boolean stroking() { return strokeId >= 0; }

        /** The last stroke was a touch rather than a glyph (shorter than a finger's width). */
        boolean lastStrokeShort() { return strokeShort; }

        private void cancelStroke() {
            if (strokePress != null) { removeCallbacks(strokePress); strokePress = null; }
            GameActivity.nativeCancelStroke();
            if (strokeId >= 0) in.button(Input.LEFT, false);
            strokeId = -1;
            strokeShort = true;
            heartClicked = SystemClock.uptimeMillis();
            haptics.tick();
        }

        private void paint(MotionEvent e) {
            int a = e.getActionMasked(), idx = e.getActionIndex(), id = e.getPointerId(idx);
            float w = getWidth(), h = getHeight();
            if (a == MotionEvent.ACTION_DOWN || a == MotionEvent.ACTION_POINTER_DOWN) {
                if (colourId < 0 && strokeId < 0 && picker.inZone(e.getX(idx), e.getY(idx))) {
                    colourId = id;
                    colourY = e.getY(idx);
                } else if (strokeId < 0 && id != colourId) {
                    strokeId = id;
                    strokeX = e.getX(idx);
                    strokeY = e.getY(idx);
                    strokeLength = 0;
                    in.warp(e.getX(idx) / w, e.getY(idx) / h);
                    strokePress = () -> { strokePress = null; picker.pinLabel(false); in.button(Input.LEFT, true); };
                    postDelayed(strokePress, 40);
                }
            } else if (a == MotionEvent.ACTION_MOVE) {
                int i = e.findPointerIndex(strokeId);
                if (i >= 0) {
                    strokeLength += (float) Math.hypot(e.getX(i) - strokeX, e.getY(i) - strokeY);
                    strokeX = e.getX(i);
                    strokeY = e.getY(i);
                    in.warp(e.getX(i) / w, e.getY(i) / h);
                }
                int c = e.findPointerIndex(colourId);
                if (c >= 0 && Math.abs(e.getY(c) - colourY) >= dp(34)) {
                    int dir = e.getY(c) > colourY ? 1 : -1;
                    colourY = e.getY(c);
                    turnColour(dir);
                }
            } else if (a == MotionEvent.ACTION_UP || a == MotionEvent.ACTION_POINTER_UP || a == MotionEvent.ACTION_CANCEL) {
                if (id == colourId || a == MotionEvent.ACTION_CANCEL) colourId = -1;
                if (id == strokeId || a == MotionEvent.ACTION_CANCEL) {
                    strokeShort = strokeLength < dp(30);
                    if (strokeId >= 0) {
                        if (strokePress != null) {   /* a quick tap: press now, release a frame later */
                            removeCallbacks(strokePress);
                            strokePress.run();
                            postDelayed(() -> in.button(Input.LEFT, false), 60);
                        } else {
                            in.button(Input.LEFT, false);
                        }
                    }
                    strokeId = -1;
                    strokeEnded = SystemClock.uptimeMillis();
                }
            }
        }
    }
}
