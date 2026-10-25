package org.thevoid.port;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.DashPathEffect;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.SeekBar;
import android.widget.TextView;
import java.util.Locale;

/** The touch layout's editor over the paused picture: the buttons of one context at a time (a chamber, the
 *  map, a film) as they look in play, moved by dragging them and sized by pinching them or by the slider;
 *  the movement and look zones as frames. Places are fractions of the whole view: a button may sit beside
 *  the camera (its strip is marked). The tools float in the middle and step aside from what is being moved.
 *  Editing never sends keys or mouse events to the game. */
final class TouchLayoutEditor extends FrameLayout {
    interface Done { void finish(TouchLayout layout); }

    private static final int[] ICONS = {Icons.MENU, Icons.BODY, Icons.JOURNAL, Icons.MAP, Icons.JUMP, Icons.SKIP,
        Icons.USE, Icons.PAINT, Icons.LOCATE, Icons.SLOW, Icons.FAST};
    private static final int MOVE = TouchLayout.BUTTONS.length, LOOK = MOVE + 1;
    /* The elements each context shows (indices of ids): a chamber, the map, a film. The journal's button
     * stands beside the menu's in the body: it follows that one. */
    private static final int[][] CONTEXTS = {{MOVE, LOOK, 0, 1, 3, 4, 6, 7}, {0, 1, 7, 8, 9, 10}, {5}};
    private static final float MIN_DP = 36, MAX_DP = 128;

    private final String[] ids = new String[TouchLayout.BUTTONS.length + 2];
    private final String[] names = {
        text("Menu", "Меню", "Menü", "Menu"), text("Body", "Сердца", "Herzen", "Serca"),
        text("Journal", "Журнал", "Tagebuch", "Dziennik"), text("Map", "Карта", "Karte", "Mapa"),
        text("Jump", "Прыжок", "Springen", "Skok"), text("Skip", "Пропуск", "Überspringen", "Pomiń"),
        text("Use", "Действие", "Benutzen", "Użyj"), text("Brush", "Кисть", "Pinsel", "Pędzel"),
        text("Find hero", "Найти героя", "Held finden", "Znajdź bohatera"),
        text("Slow time", "Замедлить время", "Zeit verlangsamen", "Spowolnij czas"),
        text("Fast time", "Ускорить время", "Zeit beschleunigen", "Przyspiesz czas"),
        text("Movement zone", "Зона движения", "Bewegungszone", "Strefa ruchu"),
        text("Look zone", "Зона обзора", "Blickzone", "Strefa widoku")};
    private final String[] contextNames = {text("Chamber", "Локация", "Ort", "Lokacja"),
        text("Map", "Карта", "Karte", "Mapa"), text("Film", "Ролик", "Film", "Film")};

    private TouchLayout working;
    private final TouchLayout defaults;
    private final Done done;
    private final Runnable help;
    private final float opacity;
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final LinearLayout tools, tabs, sizes;
    private final TextView[] tabViews = new TextView[CONTEXTS.length];
    private final SeekBar width, height;
    private final TextView widthLabel, heightLabel, hint;
    private int leftInset, rightInset;
    private int context, selected = -1;
    private boolean updating, resetLayout;
    /* The finger moving the selection, where on it the finger took hold; a second one sizing it. */
    private int pointer = -1, second = -1;
    private float grabX, grabY, pinchSpanX, pinchSpanY, pinchWidth, pinchHeight;
    private boolean moving;
    private int toolsPlace;   /* 0 the middle, 1 the top, 2 the bottom */

    TouchLayoutEditor(Context c, TouchLayout defaults, TouchLayout saved, int left, int right, float opacity,
                      Done done, Runnable help) {
        super(c);
        this.defaults = defaults.copy();
        this.done = done;
        this.help = help;
        this.opacity = Math.max(.45f, opacity);
        working = defaults.copy();
        working.overlay(saved);
        leftInset = left;
        rightInset = right;
        System.arraycopy(TouchLayout.BUTTONS, 0, ids, 0, TouchLayout.BUTTONS.length);
        ids[MOVE] = TouchLayout.MOVE;
        ids[LOOK] = TouchLayout.LOOK;
        setWillNotDraw(false);
        setClickable(true);

        tools = new LinearLayout(c);
        tools.setOrientation(LinearLayout.VERTICAL);
        tools.setPadding(dp(12), dp(8), dp(12), dp(8));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.argb(232, 18, 18, 26));
        bg.setCornerRadius(dp(16));
        bg.setStroke(dp(1), Color.argb(110, 255, 255, 255));
        tools.setBackground(bg);
        tools.setClickable(true);   /* a touch on the tools is theirs, not a drag */

        tabs = new LinearLayout(c);
        tabs.setGravity(Gravity.CENTER);
        for (int i = 0; i < CONTEXTS.length; ++i) {
            final int index = i;
            TextView tab = pill(contextNames[i]);
            tab.setOnClickListener(v -> showContext(index));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, dp(40), 1);
            lp.setMargins(dp(3), 0, dp(3), 0);
            tabs.addView(tab, lp);
            tabViews[i] = tab;
        }
        tools.addView(tabs);

        hint = label(text("Drag a button. Two fingers or the slider size it.",
            "Перетащите кнопку. Размер — двумя пальцами или ползунком.",
            "Taste ziehen. Größe mit zwei Fingern oder dem Regler.", "Przeciągnij przycisk. Rozmiar dwoma palcami lub suwakiem."));
        hint.setTextSize(12);
        hint.setGravity(Gravity.CENTER);
        hint.setPadding(0, dp(6), 0, dp(2));
        tools.addView(hint);

        sizes = new LinearLayout(c);
        sizes.setOrientation(LinearLayout.VERTICAL);
        widthLabel = label("");
        heightLabel = label("");
        width = seek(sizes, widthLabel, true);
        height = seek(sizes, heightLabel, false);
        tools.addView(sizes);

        LinearLayout actions = new LinearLayout(c);
        actions.setGravity(Gravity.CENTER);
        actions.setPadding(0, dp(4), 0, 0);
        actions.addView(action(Icons.RESET, text("Reset", "Сброс", "Zurücksetzen", "Resetuj"), () -> {
            working = this.defaults.copy();
            resetLayout = true;
            updateSizes();
            invalidate();
        }));
        actions.addView(action(Icons.HELP, text("Help", "Справка", "Hilfe", "Pomoc"), help));
        actions.addView(action(Icons.CLOSE, text("Cancel", "Отмена", "Abbrechen", "Anuluj"), () -> done.finish(null)));
        actions.addView(action(Icons.CHECK, text("Save", "Сохранить", "Speichern", "Zapisz"),
            () -> done.finish(resetLayout ? new TouchLayout() : working.copy())));
        tools.addView(actions);
        addView(tools, new LayoutParams(-2, -2, Gravity.CENTER_HORIZONTAL | Gravity.TOP));
        addOnLayoutChangeListener((v, l, t, r, b, ol, ot, or, ob) -> post(this::placeTools));
        showContext(0);
    }

    void setInsets(int left, int right) {
        if (left == leftInset && right == rightInset) return;
        leftInset = left;
        rightInset = right;
        placeTools();
        invalidate();
    }

    static String title() {
        return text("Touch layout", "Расположение кнопок", "Touch-Anordnung", "Układ przycisków");
    }

    private static String text(String en, String ru, String de, String pl) {
        String game = Settings.gameLanguage.toLowerCase(Locale.ROOT);
        String lang = game.startsWith("russian") ? "ru" : game.startsWith("german") ? "de"
            : game.startsWith("polish") ? "pl" : game.startsWith("english") ? "en" : Locale.getDefault().getLanguage();
        return "ru".equals(lang) || "uk".equals(lang) || "be".equals(lang) ? ru
            : "de".equals(lang) ? de : "pl".equals(lang) ? pl : en;
    }

    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private static boolean zone(int index) { return index >= MOVE; }

    private TextView label(String value) {
        TextView label = new TextView(getContext());
        label.setTextColor(Color.WHITE);
        label.setText(value);
        label.setTextSize(13);
        return label;
    }

    private TextView pill(String value) {
        TextView tab = label(value);
        tab.setTextSize(14);
        tab.setGravity(Gravity.CENTER);
        tab.setPadding(dp(8), 0, dp(8), 0);
        return tab;
    }

    /** A round tool with its icon (and its name for screen readers). */
    private View action(int icon, String name, Runnable run) {
        IconButton b = new IconButton(getContext(), icon, (v, down) -> { if (!down) run.run(); });
        b.setOpacity(.9f);
        b.setContentDescription(name);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(48), dp(48));
        lp.setMargins(dp(8), 0, dp(8), 0);
        b.setLayoutParams(lp);
        return b;
    }

    private SeekBar seek(LinearLayout box, TextView label, boolean horizontal) {
        box.addView(label);
        SeekBar bar = new SeekBar(getContext());
        bar.setMax(100);
        bar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar view, int progress, boolean user) {
                if (updating || !user || selected < 0 || getHeight() <= 0) return;
                TouchLayout.Rect old = working.get(ids[selected]);
                float w = old.width, h = old.height;
                if (zone(selected)) {
                    if (horizontal) w = .1f + .9f * progress / 100f;
                    else h = .1f + .9f * progress / 100f;
                } else {
                    float diameter = dp(MIN_DP + (MAX_DP - MIN_DP) * progress / 100f);
                    w = Math.min(1, diameter / getWidth());
                    h = Math.min(1, diameter / getHeight());
                }
                put(selected, old.x, old.y, w, h);
                updateSizes();
                invalidate();
            }
            @Override public void onStartTrackingTouch(SeekBar bar) { }
            @Override public void onStopTrackingTouch(SeekBar bar) { }
        });
        box.addView(bar, new LinearLayout.LayoutParams(dp(300), dp(40)));
        return bar;
    }

    private void showContext(int index) {
        context = index;
        selected = -1;
        for (int i = 0; i < tabViews.length; ++i) {
            GradientDrawable d = new GradientDrawable();
            d.setCornerRadius(dp(10));
            d.setColor(i == index ? Color.rgb(170, 125, 20) : Color.argb(255, 46, 46, 58));
            tabViews[i].setBackground(d);
        }
        updateSizes();
        placeTools();
        invalidate();
    }

    private void put(int index, float x, float y, float w, float h) {
        resetLayout = false;
        working.put(ids[index], x, y, w, h);
    }

    private void updateSizes() {
        boolean any = selected >= 0 && working.get(ids[selected]) != null && getHeight() > 0;
        sizes.setVisibility(any ? VISIBLE : GONE);
        hint.setVisibility(any ? GONE : VISIBLE);
        if (!any) return;
        TouchLayout.Rect rect = working.get(ids[selected]);
        updating = true;
        if (zone(selected)) {
            width.setProgress(Math.round((rect.width - .1f) / .9f * 100));
            height.setProgress(Math.round((rect.height - .1f) / .9f * 100));
            widthLabel.setText(names[selected] + " · " + text("width", "ширина", "Breite", "szerokość") + " "
                + Math.round(rect.width * 100) + "%");
            heightLabel.setText(text("Height", "Высота", "Höhe", "Wysokość") + " " + Math.round(rect.height * 100) + "%");
        } else {
            float diameter = diameter(rect) / getResources().getDisplayMetrics().density;
            width.setProgress(Math.round((diameter - MIN_DP) / (MAX_DP - MIN_DP) * 100));
            widthLabel.setText(names[selected] + " · " + text("size", "размер", "Größe", "rozmiar") + " "
                + Math.round(diameter) + " dp");
        }
        width.setContentDescription(widthLabel.getText());
        height.setContentDescription(heightLabel.getText());
        height.setVisibility(zone(selected) ? VISIBLE : GONE);
        heightLabel.setVisibility(zone(selected) ? VISIBLE : GONE);
        updating = false;
        post(this::placeTools);
    }

    /** A button's diameter in pixels, as play lays it out. */
    private float diameter(TouchLayout.Rect r) {
        float d = Math.min(r.width * getWidth(), r.height * getHeight());
        return Math.min(Math.min(getWidth(), getHeight()), Math.max(dp(MIN_DP), d));
    }

    /** The element's box on the screen. */
    private RectF box(int index) {
        TouchLayout.Rect r = working.get(ids[index]);
        if (r == null) return null;
        float x = r.x * getWidth(), y = r.y * getHeight(), w, h;
        if (zone(index)) { w = r.width * getWidth(); h = r.height * getHeight(); }
        else w = h = diameter(r);
        return new RectF(x - w / 2, y - h / 2, x + w / 2, y + h / 2);
    }

    /* The tools in the middle unless what is selected (or moved) is there:
     * then the top or the bottom, whichever is clear of it. */
    private void placeTools() {
        if (getHeight() <= 0 || tools.getHeight() <= 0) {
            if (getHeight() > 0) post(this::placeTools);
            return;
        }
        int th = tools.getHeight(), h = getHeight();
        int[] tops = {(h - th) / 2, dp(8), h - th - dp(8)};
        RectF busy = selected >= 0 ? box(selected) : null;
        int place = 0;
        if (busy != null && !zone(selected)) {
            for (int i = 0; i < tops.length; ++i) {
                if (busy.bottom < tops[i] - dp(6) || busy.top > tops[i] + th + dp(6)) { place = i; break; }
                place = busy.centerY() < h / 2f ? 2 : 1;
            }
        }
        toolsPlace = place;
        LayoutParams lp = (LayoutParams) tools.getLayoutParams();
        int left = Math.max(leftInset, rightInset);   /* centred, clear of the camera on either side */
        if (lp.topMargin != tops[place] || lp.leftMargin != left || lp.rightMargin != left) {
            lp.topMargin = tops[place];
            lp.leftMargin = lp.rightMargin = left;
            tools.setLayoutParams(lp);
        }
    }

    @Override protected void onDraw(Canvas canvas) {
        float w = getWidth(), h = getHeight();
        canvas.drawColor(Color.argb(120, 0, 0, 0));
        /* The camera's strips: buttons may go there, the zones and the game's picture too. */
        paint.setStyle(Paint.Style.FILL);
        for (int side = 0; side < 2; ++side) {
            int inset = side == 0 ? leftInset : rightInset;
            if (inset <= 0) continue;
            float x0 = side == 0 ? 0 : w - inset, x1 = side == 0 ? inset : w;
            paint.setColor(Color.argb(60, 255, 205, 50));
            canvas.drawRect(x0, 0, x1, h, paint);
            paint.setColor(Color.argb(90, 255, 205, 50));
            paint.setStrokeWidth(dp(1));
            for (float y = -inset; y < h; y += dp(14)) canvas.drawLine(x0, y + inset, x1, y, paint);
        }
        int[] shown = CONTEXTS[context];
        for (int index : shown) if (zone(index)) drawZone(canvas, index);
        for (int index : shown) if (!zone(index) && index != selected) drawButton(canvas, index);
        if (selected >= 0 && !zone(selected)) drawButton(canvas, selected);
    }

    private void drawZone(Canvas canvas, int index) {
        RectF r = box(index);
        if (r == null) return;
        boolean active = index == selected;
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(active ? Color.argb(55, 255, 205, 50) : Color.argb(28, 150, 170, 210));
        canvas.drawRoundRect(r, dp(14), dp(14), paint);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(dp(active ? 3 : 1.5f));
        paint.setPathEffect(new DashPathEffect(new float[] {dp(10), dp(7)}, 0));
        paint.setColor(active ? Color.rgb(255, 205, 50) : Color.argb(170, 220, 225, 255));
        canvas.drawRoundRect(r.left + dp(2), r.top + dp(2), r.right - dp(2), r.bottom - dp(2), dp(14), dp(14), paint);
        paint.setPathEffect(null);
        paint.setStyle(Paint.Style.FILL);
        paint.setTextAlign(Paint.Align.CENTER);
        paint.setTextSize(dp(15));
        paint.setColor(active ? Color.rgb(255, 225, 140) : Color.argb(200, 230, 232, 245));
        canvas.drawText(names[index], r.centerX(), r.centerY() + dp(5), paint);
        paint.setTextAlign(Paint.Align.LEFT);
    }

    /* As IconButton draws it in play; the selected one ringed in gold and named. */
    private void drawButton(Canvas canvas, int index) {
        RectF b = box(index);
        if (b == null) return;
        float cx = b.centerX(), cy = b.centerY(), r = b.width() / 2 - 1;
        boolean active = index == selected;
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(Color.argb((int) (opacity * 190), 20, 20, 30));
        canvas.drawCircle(cx, cy, r, paint);
        paint.setStyle(Paint.Style.STROKE);
        float ring = active ? Math.max(2f, r * .14f) : Math.max(1f, r * .05f);
        paint.setStrokeWidth(ring);
        paint.setColor(active ? Color.rgb(255, 205, 50) : Color.argb((int) (opacity * 200), 255, 255, 255));
        canvas.drawCircle(cx, cy, r - ring / 2, paint);
        paint.setColor(Color.argb(240, 255, 255, 255));
        Icons.draw(canvas, ICONS[index], cx, cy, r * 1.15f, paint);
        if (!active) return;
        paint.setStyle(Paint.Style.FILL);
        paint.setTextSize(dp(13));
        float tw = paint.measureText(names[index]), ty = b.bottom + dp(18) < getHeight() - dp(4) ? b.bottom + dp(18) : b.top - dp(8);
        float tx = Math.max(dp(6), Math.min(getWidth() - tw - dp(6), cx - tw / 2));
        paint.setColor(Color.argb(210, 10, 10, 16));
        canvas.drawRoundRect(tx - dp(6), ty - dp(14), tx + tw + dp(6), ty + dp(5), dp(6), dp(6), paint);
        paint.setColor(Color.rgb(255, 225, 140));
        canvas.drawText(names[index], tx, ty, paint);
    }

    /** The element under a finger: buttons over the zones, the selected one first. */
    private int hit(float x, float y) {
        int[] shown = CONTEXTS[context];
        if (selected >= 0 && !zone(selected)) {
            RectF b = box(selected);
            if (b != null && b.contains(x, y)) return selected;
        }
        for (int i = shown.length - 1; i >= 0; --i) {
            int index = shown[i];
            if (zone(index)) continue;
            RectF b = box(index);
            if (b == null) continue;
            b.inset(-dp(6), -dp(6));   /* a small button is still easy to take */
            if (b.contains(x, y)) return index;
        }
        if (selected >= 0 && zone(selected)) {
            RectF b = box(selected);
            if (b != null && b.contains(x, y)) return selected;
        }
        for (int index : shown) {
            if (!zone(index)) continue;
            RectF b = box(index);
            if (b != null && b.contains(x, y)) return index;
        }
        return -1;
    }

    @Override public boolean onTouchEvent(MotionEvent event) {
        int action = event.getActionMasked(), at = event.getActionIndex();
        if (action == MotionEvent.ACTION_DOWN) {
            int index = hit(event.getX(), event.getY());
            if (index != selected) {
                selected = index;
                updateSizes();
            }
            pointer = selected >= 0 ? event.getPointerId(0) : -1;
            second = -1;
            if (pointer >= 0) {
                TouchLayout.Rect r = working.get(ids[selected]);
                grabX = event.getX() - r.x * getWidth();
                grabY = event.getY() - r.y * getHeight();
                moving = true;
                tools.animate().alpha(.25f).setDuration(120).start();
            }
            invalidate();
        } else if (action == MotionEvent.ACTION_POINTER_DOWN && pointer >= 0 && second < 0) {
            second = event.getPointerId(at);
            int first = event.findPointerIndex(pointer);
            TouchLayout.Rect r = working.get(ids[selected]);
            pinchSpanX = Math.max(dp(20), Math.abs(event.getX(at) - event.getX(first)));
            pinchSpanY = Math.max(dp(20), Math.abs(event.getY(at) - event.getY(first)));
            pinchWidth = r.width;
            pinchHeight = r.height;
        } else if (action == MotionEvent.ACTION_MOVE && pointer >= 0) {
            int first = event.findPointerIndex(pointer);
            if (first < 0) return true;
            TouchLayout.Rect r = working.get(ids[selected]);
            int two = second >= 0 ? event.findPointerIndex(second) : -1;
            float w = r.width, h = r.height;
            if (two >= 0) {
                float spanX = Math.max(dp(20), Math.abs(event.getX(two) - event.getX(first)));
                float spanY = Math.max(dp(20), Math.abs(event.getY(two) - event.getY(first)));
                if (zone(selected)) {
                    w = Math.max(.1f, Math.min(1, pinchWidth * spanX / pinchSpanX));
                    h = Math.max(.1f, Math.min(1, pinchHeight * spanY / pinchSpanY));
                } else {
                    float k = (float) (Math.hypot(spanX, spanY) / Math.hypot(pinchSpanX, pinchSpanY));
                    float d = Math.max(dp(MIN_DP), Math.min(dp(MAX_DP), Math.min(pinchWidth * getWidth(), pinchHeight * getHeight()) * k));
                    w = d / getWidth();
                    h = d / getHeight();
                }
                put(selected, r.x, r.y, w, h);
            } else {
                put(selected, (event.getX(first) - grabX) / getWidth(), (event.getY(first) - grabY) / getHeight(), w, h);
            }
            updateSizes();
            invalidate();
        } else if (action == MotionEvent.ACTION_POINTER_UP) {
            int id = event.getPointerId(at);
            if (id == second) second = -1;
            else if (id == pointer) {
                /* The other finger keeps moving it, from where it took hold. */
                pointer = second;
                second = -1;
                int index = event.findPointerIndex(pointer);
                if (pointer >= 0 && index >= 0) {
                    TouchLayout.Rect r = working.get(ids[selected]);
                    grabX = event.getX(index) - r.x * getWidth();
                    grabY = event.getY(index) - r.y * getHeight();
                }
            }
        } else if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
            pointer = second = -1;
            if (moving) {
                moving = false;
                tools.animate().alpha(1f).setDuration(160).start();
                placeTools();
            }
        }
        return true;
    }
}
