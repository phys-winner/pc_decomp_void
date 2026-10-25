package org.thevoid.port;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.view.MotionEvent;
import android.view.View;

/** Choosing the brush's colour. The game's palette (ui/paint.bin) is seven
 *  hearts down the left edge while painting; a click on one makes its colour
 *  the brush's. The host reports where each heart was drawn and its pixel
 *  shader constants (android/host/hud.c, slots 1..7: c0.x = 1 - fill,
 *  c2 = the colour, dimmed to 0.3 unless it is the active one). The layer
 *  offers the colours one has as a strip beside the brush while painting
 *  and as a fan around the brush while it is held; a colour picked clicks
 *  its heart (Controls). */
final class PalettePicker extends View {
    interface Chooser { void choose(int colour); }
    interface HoldChooser {
        void press(int colour, boolean down);
        default void moved(int colour, float dx, float dy) { }
    }

    static final int COLOURS = 7, FIRST_SLOT = 1, FLOATS = 72;
    /* Where to click each heart, in its drawn rectangle: the deepest point
     * of its fill (ui_alimfa_pal<i>_grad), which lies inside its click mask
     * (_mask); the drops hang off centre (the green one at the left edge). */
    private static final float[][] GRIP = {{0.367f, 0.656f}, {0.348f, 0.430f}, {0.398f, 0.484f}, {0.273f, 0.516f},
        {0.320f, 0.430f}, {0.108f, 0.518f}, {0.195f, 0.633f}};
    /* Memory drops have different masks and padded image sizes. These points
     * lie in their dark mask cores, inside each actual control's bounds. */
    private static final float[][] MEMORY_GRIP = {{0.3633f, 0.1797f}, {0.25f, 0.2734f}, {0.3438f, 0.3203f},
        {0.5391f, 0.0312f}, {0.1953f, 0.5156f}, {0.3047f, 0.1094f}, {0.4219f, 0.2812f}};
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Chooser chooser;
    private HoldChooser holdChooser;
    private final int firstSlot;
    private final float[] fill = new float[COLOURS];
    private final float[] current = new float[COLOURS], maximum = new float[COLOURS];
    private final boolean[] amountKnown = new boolean[COLOURS];
    private final int[] rgb = {0xffd4dde5, 0xffc53737, 0xffe59b35, 0xff3d93e0, 0xffa941bf, 0xff30b76c, 0xffe9cb4d};
    private final float[][] heart = new float[COLOURS][4];
    private final int[] steady = new int[COLOURS];   /* frames the heart has kept its place */
    private boolean known;
    private int active = -1;
    /* The brush button's centre (view coordinates) and the side of its column. */
    private float anchorX, anchorY, buttonSize;
    private boolean rightSide = true;
    private boolean customAnchor;
    private float textScale = 1;
    private boolean textContrast = true;
    private boolean strip, fan;
    private boolean body;
    private int heldColour = -1;
    private boolean stripHeld;
    private int stripColour = -1;
    private float heldX, heldY;
    private int highlighted = -1;
    private final float[] dotX = new float[COLOURS], dotY = new float[COLOURS];
    private final boolean[] dotShown = new boolean[COLOURS];
    private float dotRadius;
    private int insetLeft, insetRight;   /* the camera cutout's strips at the sides */
    /* The camera's own holes in the screen (DisplayCutout's bounding rects): a column of drops parts round them;
     * so it does round the layer's buttons over it (the body's menu and book). */
    private final java.util.List<android.graphics.RectF> holes = new java.util.ArrayList<>();
    private final java.util.List<android.graphics.RectF> obstacles = new java.util.ArrayList<>();
    /* The body: every colour's name and amount beside its drop (while the
     * stats are held); a held drop's own. */
    private boolean amountLabels;

    PalettePicker(Context c, Chooser chooser) {
        this(c, chooser, FIRST_SLOT);
    }

    PalettePicker(Context c, Chooser chooser, int firstSlot) {
        super(c);
        this.chooser = chooser;
        this.firstSlot = firstSlot;
    }

    private float dp(float v) { return v * getResources().getDisplayMetrics().density; }

    /** The last frame's palette draws (nativeHudSlots). */
    void update(int mask, float[] values) {
        boolean changed = false;
        litHeart = -1;
        for (int i = 0; i < COLOURS; ++i) {
            int slot = firstSlot + i;
            if ((mask & (1 << slot)) == 0) { steady[i] = 0; continue; }
            int base = slot * FLOATS;
            float f = Math.max(0f, Math.min(1f, 1f - values[base]));
            float r = values[base + 8], g = values[base + 9], b = values[base + 10];
            boolean lit = Math.max(r, Math.max(g, b)) >= 0.5f;
            float[] h = heart[i];
            boolean same = Math.abs(h[0] - values[base + 64]) < 0.002f && Math.abs(h[1] - values[base + 65]) < 0.002f;
            for (int j = 0; j < 4; ++j) h[j] = values[base + 64 + j];
            steady[i] = same ? steady[i] + 1 : 0;
            if (lit) litHeart = i;
            /* The body draws no chosen colour; the amounts, once known, are
             * the fill (the shader's would undo them every frame: a redraw
             * of both columns each frame for nothing). */
            if (lit && active != i) { active = i; changed |= !body; }
            if (!amountKnown[i] && Math.abs(fill[i] - f) > 0.01f) { fill[i] = f; changed = true; }
            known = true;
        }
        if (changed && (strip || fan || body)) layoutDots();
    }

    private static int clamp255(float v) { return Math.max(0, Math.min(255, Math.round(v * 255))); }

    boolean known() { return known; }

    boolean has(int colour) { return fill[colour] > 0.005f; }

    /** The game's active colour (its lit heart), -1 if none seen. */
    int active() { return active; }
    /* The heart the game lit in the last frame its palette was drawn (-1: none drawn, none lit). */
    private int litHeart = -1;
    int lit() { return litHeart; }
    void setActive(int colour) {
        if (active != colour) { active = colour; if (!body) invalidate(); }
    }
    int colour(int index) { return rgb[index]; }
    float fill(int index) { return fill[index]; }
    boolean held() { return heldColour >= 0; }

    void setAmounts(float[] amounts, int offset) {
        boolean changed = false;
        for (int i = 0; i < COLOURS; ++i) {
            float value = amounts[offset + 2 * i], max = amounts[offset + 2 * i + 1];
            if (!Float.isFinite(value) || !Float.isFinite(max) || value < 0 || max < 0) continue;
            float fraction = max > 0 ? Math.max(0f, Math.min(1f, value / max)) : 0f;
            changed |= !amountKnown[i] || current[i] != value || maximum[i] != max || fill[i] != fraction;
            current[i] = value;
            maximum[i] = max;
            fill[i] = fraction;
            amountKnown[i] = true;
        }
        if (changed && (body || strip || fan || label >= 0)) invalidate();
    }

    void setHoldChooser(HoldChooser listener) { holdChooser = listener; }

    void cancelHold() {
        if (heldColour >= 0 && holdChooser != null) holdChooser.press(heldColour, false);
        heldColour = -1;
        stripHeld = false;
        stripColour = -1;
    }

    void setBody(boolean on) {
        if (body == on) return;
        cancelHold();
        body = on;
        layoutDots();
    }

    /** The next colour one has from `from` in direction dir (+1 down the
     *  palette, -1 up), round; -1 if none other. */
    int nextValid(int from, int dir) {
        for (int k = 1; k <= COLOURS; ++k) {
            int i = ((from < 0 ? (dir > 0 ? -1 : 0) : from) + dir * k % COLOURS + 2 * COLOURS) % COLOURS;
            if (has(i) && i != from) return i;
        }
        return -1;
    }

    /** The drops keep clear of the camera cutout: its strips (the fan, the strip by the brush) and its holes. */
    void setInsets(int left, int right, java.util.List<android.graphics.RectF> cutouts) {
        if (left == insetLeft && right == insetRight && holes.equals(cutouts)) return;
        insetLeft = left;
        insetRight = right;
        holes.clear();
        holes.addAll(cutouts);
        layoutDots();
    }

    /** The layer's buttons the body's column keeps clear of (view coordinates). */
    void setObstacles(java.util.List<android.graphics.RectF> rects) {
        if (obstacles.equals(rects)) return;
        obstacles.clear();
        obstacles.addAll(rects);
        if (body) layoutDots();
    }

    /** A column of COLOURS drops at x, centred between top and bottom at most `step` apart; where a camera
     *  hole (or a button) crosses the column, the drops part round it (some above, the rest below, alike apart). */
    private void column(float x, float top, float bottom, float step) {
        float margin = dp(6), blockTop = Float.MAX_VALUE, blockBottom = -Float.MAX_VALUE;
        java.util.List<android.graphics.RectF> blocks = new java.util.ArrayList<>(holes);
        if (body) blocks.addAll(obstacles);
        for (android.graphics.RectF hole : blocks) {
            if (hole.right < x - dotRadius - margin || hole.left > x + dotRadius + margin) continue;
            blockTop = Math.min(blockTop, hole.top - dotRadius - margin);
            blockBottom = Math.max(blockBottom, hole.bottom + dotRadius + margin);
        }
        step = Math.min(step, (bottom - top) / (COLOURS - 1f));
        boolean upper = body && firstSlot == FIRST_SLOT;
        float first = upper ? top : (top + bottom) / 2 - step * (COLOURS - 1) / 2f;
        boolean crossed = false;
        for (int i = 0; i < COLOURS; ++i) {
            float y = first + i * step;
            crossed |= y > blockTop && y < blockBottom;
        }
        if (!crossed) {
            for (int i = 0; i < COLOURS; ++i) { dotX[i] = x; dotY[i] = first + i * step; dotShown[i] = true; }
            return;
        }
        /* k drops above the hole, the rest below: the k that leaves them farthest apart. */
        int bestK = -1;
        float bestStep = -1;
        for (int k = 0; k <= COLOURS; ++k) {
            int below = COLOURS - k;
            if (k > 0 && blockTop < top || below > 0 && blockBottom > bottom) continue;
            float s = step;
            if (k > 1) s = Math.min(s, (blockTop - top) / (k - 1));
            if (below > 1) s = Math.min(s, (bottom - blockBottom) / (below - 1));
            float balance = Math.abs(k - COLOURS / 2f), bestBalance = Math.abs(bestK - COLOURS / 2f);
            if (s > bestStep + .5f || Math.abs(s - bestStep) <= .5f
                    && (balance < bestBalance || upper && balance == bestBalance && k > bestK)) {
                bestStep = s;
                bestK = k;
            }
        }
        if (bestK < 0) {   /* no room either side: as it was */
            for (int i = 0; i < COLOURS; ++i) { dotX[i] = x; dotY[i] = first + i * step; dotShown[i] = true; }
            return;
        }
        for (int i = 0; i < COLOURS; ++i) {
            dotX[i] = x;
            dotY[i] = i < bestK ? blockTop - (bestK - 1 - i) * bestStep : blockBottom + (i - bestK) * bestStep;
            dotShown[i] = true;
        }
    }

    /** Every colour's name and amount beside its drop (the body's stats held). */
    void setAmountLabels(boolean on) {
        if (amountLabels != on) { amountLabels = on; invalidate(); }
    }

    /* Where a colour's drop stands (view coordinates; the body's columns):
     * the Controls' cards beside it point at it. */
    boolean dotShown(int colour) { return dotShown[colour]; }
    float dotX(int colour) { return dotX[colour]; }
    float dotY(int colour) { return dotY[colour]; }
    float dotRadius() { return dotRadius; }

    /** A finger landing here is this picker's (a drop it reacts to). */
    boolean wants(float x, float y) {
        if ((!strip && !body) || fan) return false;
        for (int i = 0; i < COLOURS; ++i)
            if (dotShown[i] && Math.hypot(x - dotX[i], y - dotY[i]) < dotRadius * 1.25f) return true;
        return false;
    }

    /* The colours' zone beside the brush (the strip's column and out to the
     * edge): no painting there; a vertical swipe turns the colours. */
    boolean inZone(float x, float y) {
        if (!strip && !fan) return false;
        for (int i = 0; i < COLOURS; ++i)
            if (dotShown[i] && Math.abs(x - dotX[i]) <= dotRadius * 1.6f
                    && Math.abs(y - dotY[i]) <= dotRadius * 1.6f) return true;
        return false;
    }

    /* The colour just chosen, named, with how much of it one has, by the brush. */
    private int label = -1;
    private long labelUntil;
    private final android.graphics.Rect textBounds = new android.graphics.Rect();
    private final Runnable labelExpiry = this::invalidate;

    /* A colour chosen for the brush: its label stays until the stroke begins. */
    private boolean labelPinned;

    void pinLabel(boolean on) {
        if (labelPinned == on) return;
        labelPinned = on;
        if (!on) labelUntil = Math.min(labelUntil, android.os.SystemClock.uptimeMillis() + 300);
        removeCallbacks(labelExpiry);
        postDelayed(labelExpiry, on ? 1850 : 350);
        invalidate();
    }

    void showLabel(int colour) {
        label = colour;
        labelUntil = android.os.SystemClock.uptimeMillis() + 1800;
        invalidate();
        removeCallbacks(labelExpiry);
        postDelayed(labelExpiry, 1850);
    }

    /** Where to click colour's heart now, if it has kept still a few frames: [x, y] in 0..1. */
    float[] heartPoint(int colour) {
        float[] h = heart[colour];
        if (steady[colour] < 3 || h[2] <= h[0]) return null;
        float[] point = (firstSlot == FIRST_SLOT ? GRIP : MEMORY_GRIP)[colour];
        return new float[] {h[0] + (h[2] - h[0]) * point[0], h[1] + (h[3] - h[1]) * point[1]};
    }

    void setAnchor(float x, float y, float size, boolean right, boolean custom) {
        if (anchorX == x && anchorY == y && buttonSize == size && rightSide == right && customAnchor == custom) return;
        anchorX = x;
        anchorY = y;
        buttonSize = size;
        rightSide = right;
        customAnchor = custom;
        if (strip || fan) layoutDots();
    }

    void setReadability(float scale, boolean contrast) {
        if (textScale == scale && textContrast == contrast) return;
        textScale = scale;
        textContrast = contrast;
        invalidate();
    }

    void setStrip(boolean on) {
        if (on == strip) return;
        strip = on;
        layoutDots();
    }

    boolean fanShown() { return fan; }

    void setFan(boolean on) {
        if (on == fan) return;
        fan = on;
        highlighted = -1;
        layoutDots();
    }

    /** The finger holding the brush (view coordinates): the fan's colour under it. */
    int fanAt(float x, float y) {
        int best = -1;
        float bestD = dotRadius * 1.6f;
        for (int i = 0; i < COLOURS; ++i) {
            if (!dotShown[i]) continue;
            float d = (float) Math.hypot(x - dotX[i], y - dotY[i]);
            if (d < bestD) { bestD = d; best = i; }
        }
        if (best != highlighted) {
            highlighted = best;
            if (best >= 0) showLabel(best);
            invalidate();
        } else if (best >= 0) labelUntil = android.os.SystemClock.uptimeMillis() + 1800;
        return best;
    }

    private void layoutDots() {
        java.util.Arrays.fill(dotShown, false);
        int n = COLOURS;
        dotRadius = dp(19);
        if (body) {
            /* The body: the palette's drops by its hearts at the left edge,
             * the Memory's at the right one, parting round the camera. */
            float top = dp(30) + dotRadius;
            float bottom = getHeight() - dp(30) - dotRadius;
            column(firstSlot == FIRST_SLOT ? dp(34) : getWidth() - dp(34), top, bottom, dp(48));
        } else if (strip && !fan) {
            /* Painting: a column beside the brush, on its side of the screen
             * (the right one unless the brush was moved or the layout is
             * left-handed), clear of the camera cutout. */
            float step = Math.min(dp(48), (getHeight() - dp(60)) / (COLOURS - 1f));
            float gap = Math.max(buttonSize, dp(40)) / 2 + dp(12) + dotRadius;
            float edge = dotRadius * 1.3f + dp(4);
            float x = rightSide ? anchorX - gap : anchorX + gap;
            x = Math.max(insetLeft + edge, Math.min(getWidth() - insetRight - edge, x));
            column(x, dp(30) + dotRadius, getHeight() - dp(30) - dotRadius, step);
        } else if (n > 0 && fan) {
            /* An arc around the brush, opening towards the middle of the screen. */
            float radius = Math.max(dp(92), buttonSize * 1.7f);
            float span = (float) Math.toRadians(Math.min(150, 26 * (n + 1)));
            float centre = (float) (rightSide ? Math.PI : 0);
            int k = 0;
            for (int i = 0; i < COLOURS; ++i) {
                float a = n == 1 ? centre : centre - span / 2 + span * k / (n - 1);
                if (!rightSide) a = -a;
                dotX[i] = anchorX + radius * (float) Math.cos(a);
                dotY[i] = anchorY - radius * (float) Math.sin(a);
                dotShown[i] = true;
                ++k;
            }
        }
        if (fan && !body) {
            float edge = dotRadius * 1.3f + dp(4);
            for (int i = 0; i < COLOURS; ++i) if (dotShown[i]) {
                dotX[i] = Math.max(insetLeft + edge, Math.min(getWidth() - insetRight - edge, dotX[i]));
                dotY[i] = Math.max(edge, Math.min(getHeight() - edge, dotY[i]));
            }
        }
        invalidate();
    }

    @Override protected void onSizeChanged(int w, int h, int oldW, int oldH) {
        layoutDots();
    }

    @Override protected void onDraw(Canvas c) {
        drawLabel(c);
        if (!strip && !fan && !body) return;
        for (int i = 0; i < COLOURS; ++i) {
            if (!dotShown[i]) continue;
            float r = dotRadius * (i == highlighted ? 1.3f : 1f);
            float x = dotX[i], y = dotY[i];
            paint.setStyle(Paint.Style.FILL);
            paint.setColor(Color.argb(170, 10, 10, 16));
            c.drawCircle(x, y, r, paint);
            /* The colour fills the drop from below, as much as one has. */
            c.save();
            c.clipRect(x - r, y + r - 2 * r * Math.max(0.12f, fill[i]), x + r, y + r);
            paint.setColor(rgb[i]);
            c.drawCircle(x, y, r * 0.86f, paint);
            c.restore();
            paint.setStyle(Paint.Style.STROKE);
            /* The brush's colour stands out while painting; the body's
             * drops are all alike (none of them is "chosen" there). */
            boolean on = i == active && !body;
            paint.setStrokeWidth(on ? dp(3) : dp(1.5f));
            paint.setColor(on ? Color.WHITE : Color.argb(150, 255, 255, 255));
            c.drawCircle(x, y, r, paint);
            if (!has(i)) {
                paint.setStrokeWidth(dp(2));
                paint.setColor(Color.argb(210, 240, 240, 240));
                c.drawLine(x - r * .3f, y - r * .3f, x + r * .3f, y + r * .3f, paint);
                c.drawLine(x - r * .3f, y + r * .3f, x + r * .3f, y - r * .3f, paint);
            }
        }
        /* A held drop's amount is the Controls' card (it stays while the
         * colour is in the hand). */
        if (body && amountLabels) for (int i = 0; i < COLOURS; ++i) if (dotShown[i]) drawDotLabel(c, i);
    }

    /** A drop's colour name and amount beside it, towards the middle of the screen. */
    private void drawDotLabel(Canvas c, int i) {
        String name = Settings.gameText(i);
        String amount = amountKnown[i] ? (int) Math.ceil(current[i]) + " / " + (int) Math.ceil(maximum[i])
            : Math.round(fill[i] * 100) + " %";
        float size = dp(14) * textScale;
        paint.setStyle(Paint.Style.FILL);
        paint.setTextSize(size);
        float nameWidth = paint.measureText(name), gap = dp(6), width = nameWidth + gap + paint.measureText(amount);
        boolean left = firstSlot == FIRST_SLOT;
        float x = left ? dotX[i] + dotRadius + dp(10) : dotX[i] - dotRadius - dp(10) - width, y = dotY[i] + size * .35f;
        if (textContrast) {
            paint.setColor(Color.argb(205, 10, 10, 16));
            c.drawRoundRect(x - dp(6), dotY[i] - size * .8f, x + width + dp(6), dotY[i] + size * .8f, dp(8), dp(8), paint);
        }
        paint.setTextAlign(Paint.Align.LEFT);
        paint.setColor(rgb[i]);
        c.drawText(name, x, y, paint);
        paint.setColor(Color.argb(230, 255, 255, 255));
        c.drawText(amount, x + nameWidth + gap, y, paint);
    }

    private void drawLabel(Canvas c) {
        if (body) return;
        if (label < 0 || (heldColour < 0 && !labelPinned && android.os.SystemClock.uptimeMillis() > labelUntil)
                || (!body && buttonSize <= 0)) return;
        String name = Settings.gameText(label);
        String amount = Math.round(fill[label] * 100) + " %";
        if (amountKnown[label]) amount = (int) Math.ceil(current[label]) + " / " + (int) Math.ceil(maximum[label]);
        paint.setStyle(Paint.Style.FILL);
        paint.setTextSize(dp(12) * textScale);
        float textWidth = Math.max(dp(70), paint.measureText(amount));
        paint.setTextSize(dp(17) * textScale);
        paint.getTextBounds(name, 0, name.length(), textBounds);
        textWidth = Math.max(textBounds.width(), textWidth);
        float edge = buttonSize / 2 + dp(14) + 2 * dp(19) + dp(18);
        float right = rightSide ? anchorX - edge : anchorX + edge + textWidth;
        float left = right - textWidth;
        /* As far from the top as it stood by the brush from the bottom
         * (the brush's own height, its fingers below it). */
        float below = Math.max(dp(24) * textScale, Math.min(getHeight() - dp(30) * textScale, anchorY - dp(6)));
        float y = getHeight() - below - dp(30) * textScale + dp(24) * textScale;
        textWidth = right - left;
        left = Math.max(dp(10), Math.min(getWidth() - textWidth - dp(10), left));
        right = left + textWidth;
        y = Math.max(dp(24) * textScale, Math.min(getHeight() - dp(30) * textScale, y));
        if (textContrast) {
            paint.setColor(Color.argb(220, 10, 10, 16));
            c.drawRoundRect(left - dp(10), y - dp(24) * textScale, right + dp(10), y + dp(30) * textScale,
                dp(10), dp(10), paint);
        }
        paint.setColor(rgb[label]);
        paint.setTextAlign(Paint.Align.LEFT);
        c.drawText(name, left, y, paint);
        /* How much: a bar filled as the heart is, and the share. */
        float barTop = y + dp(8) * textScale, barW = right - left;
        paint.setColor(Color.argb(110, 255, 255, 255));
        c.drawRect(left, barTop, right, barTop + dp(5), paint);
        paint.setColor(rgb[label]);
        c.drawRect(left, barTop, left + barW * Math.max(0f, Math.min(1f, fill[label])), barTop + dp(5), paint);
        paint.setTextSize(dp(12) * textScale);
        paint.setColor(Color.argb(220, 255, 255, 255));
        c.drawText(amount, left, barTop + dp(18) * textScale, paint);
    }

    @Override public boolean onTouchEvent(MotionEvent e) {
        if (body && heldColour >= 0) {
            if (e.getActionMasked() == MotionEvent.ACTION_MOVE && holdChooser != null)
                holdChooser.moved(heldColour, e.getX() - heldX, e.getY() - heldY);
            if (e.getActionMasked() == MotionEvent.ACTION_UP || e.getActionMasked() == MotionEvent.ACTION_CANCEL) {
                if (holdChooser != null) holdChooser.press(heldColour, false);
                heldColour = -1;
            }
            return true;
        }
        if (stripHeld) {
            if (e.getActionMasked() == MotionEvent.ACTION_MOVE) selectAt(e.getX(), e.getY());
            if (e.getActionMasked() == MotionEvent.ACTION_UP || e.getActionMasked() == MotionEvent.ACTION_CANCEL) {
                stripHeld = false;
                stripColour = -1;
            }
            return true;
        }
        if ((!strip && !body) || fan || e.getActionMasked() != MotionEvent.ACTION_DOWN) return false;
        for (int i = 0; i < COLOURS; ++i) {
            if (dotShown[i] && Math.hypot(e.getX() - dotX[i], e.getY() - dotY[i]) < dotRadius * 1.25f) {
                if (body) {
                    if (IconButton.haptics != null) IconButton.haptics.tick();
                    heldColour = i;
                    heldX = e.getX();
                    heldY = e.getY();
                    if (holdChooser != null) holdChooser.press(i, true);
                } else {
                    stripHeld = true;
                    selectAt(e.getX(), e.getY());
                }
                return true;
            }
        }
        return false;
    }

    private void selectAt(float x, float y) {
        for (int i = 0; i < COLOURS; ++i) {
            if (!dotShown[i] || Math.hypot(x - dotX[i], y - dotY[i]) >= dotRadius * 1.25f) continue;
            if (i != stripColour) {
                stripColour = i;
                showLabel(i);
                if (has(i)) {
                    setActive(i);
                    if (IconButton.haptics != null) IconButton.haptics.tick();
                    chooser.choose(i);
                }
            }
            return;
        }
    }
}
