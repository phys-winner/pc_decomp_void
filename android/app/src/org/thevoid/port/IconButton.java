package org.thevoid.port;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.os.SystemClock;
import android.view.MotionEvent;
import android.view.View;

/** A round icon-only touch button: press/release callbacks, a toggled look and a slow blink. */
final class IconButton extends View {
    interface Listener { void onPress(IconButton b, boolean down); }
    /** The pressing finger's path (screen coordinates), before the release's onPress. */
    interface Drag { void moved(float rawX, float rawY, boolean released); }
    static Haptics haptics;   /* the layer's short tick (Haptics) */

    final int icon;
    private final Listener listener;
    private Drag drag;
    private Runnable longPress;
    private boolean longFired;
    private final Runnable hold = this::fireLongPress;

    /* The long press's action first: a listener can tell the release that
     * follows (its key or click) is not to be sent. */
    private void fireLongPress() {
        if (!pressed || longPress == null) return;
        longFired = true;
        longPress.run();
        listener.onPress(this, false);
    }
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private boolean pressed, toggled, dim;
    private long blinkStart = -1;
    private float opacity = 0.6f;
    private int colour;
    private float colourFill = -1;

    IconButton(Context c, int icon, Listener listener) {
        super(c);
        this.icon = icon;
        this.listener = listener;
    }

    void setOpacity(float a) {
        if (opacity != a) { opacity = a; invalidate(); }
    }

    /** Fainter: there, but nothing calls for it now. */
    void setDim(boolean on) {
        if (dim != on) { dim = on; invalidate(); }
    }

    void setDrag(Drag d) { drag = d; }
    void setLongPress(Runnable action) { longPress = action; }

    void setColour(int rgb, float fill) {
        if (colour == rgb && colourFill == fill) return;
        colour = rgb;
        colourFill = Math.max(0, Math.min(1, fill));
        invalidate();
    }

    void setToggled(boolean on) {
        if (toggled != on) { toggled = on; invalidate(); }
    }

    boolean toggled() { return toggled; }

    /** Blink to call attention: the first frame drops almost to transparent,
     *  then the icon fades in and out slowly until stopped. */
    void setBlinking(boolean on) {
        if (on == (blinkStart >= 0)) return;
        blinkStart = on ? SystemClock.uptimeMillis() : -1;
        invalidate();
    }

    @Override protected void onDraw(Canvas c) {
        float w = getWidth(), h = getHeight(), r = Math.min(w, h) / 2f - 1;
        float alpha = opacity;
        if (blinkStart >= 0) {
            double t = (SystemClock.uptimeMillis() - blinkStart) / 1600.0;
            float k = (float) (0.5 - 0.5 * Math.cos(2 * Math.PI * t));   /* 0 at the start */
            alpha = 0.06f + (Math.max(opacity, 0.85f) - 0.06f) * k;
            postInvalidateOnAnimation();
        }
        if (dim && blinkStart < 0) alpha *= 0.5f;
        if (pressed) alpha = Math.min(1f, alpha + 0.3f);
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(toggled && icon != Icons.PAINT ? Color.argb((int) (alpha * 200), 150, 40, 40) : Color.argb((int) (alpha * 150), 20, 20, 30));
        c.drawCircle(w / 2, h / 2, r, paint);
        if (colourFill >= 0) {
            c.save();
            c.clipRect(0, h / 2 + r - 2 * r * colourFill, w, h);
            paint.setColor((colour & 0xffffff) | ((int) (alpha * 220) << 24));
            c.drawCircle(w / 2, h / 2, r, paint);
            c.restore();
        }
        paint.setStyle(Paint.Style.STROKE);
        if (toggled && icon == Icons.PAINT) {
            /* The brush in hand: a ring inside the button's edge (a wider
             * stroke on the edge itself was cut by the button's bounds),
             * breathing slowly while painting goes on. The ring takes the
             * selected colour so the button shows which paint is in hand; a
             * near-black colour is lifted to a floor so the ring stays read. */
            float ring = Math.max(2f, r * 0.16f);
            double t = (SystemClock.uptimeMillis() % 1800L) / 1800.0;
            float glow = 0.72f + 0.28f * (float) (0.5 + 0.5 * Math.cos(2 * Math.PI * t));
            int cr = Math.max(60, (colour >> 16) & 0xff);
            int cg = Math.max(60, (colour >> 8) & 0xff);
            int cb = Math.max(60, colour & 0xff);
            paint.setStrokeWidth(ring);
            paint.setColor(Color.argb((int) (255 * Math.min(1f, Math.max(alpha, 0.7f)) * glow), cr, cg, cb));
            c.drawCircle(w / 2, h / 2, r - ring / 2, paint);
            paint.setStrokeWidth(Math.max(1f, r * 0.04f));
            paint.setColor(Color.argb((int) (alpha * 200), 255, 245, 210));
            c.drawCircle(w / 2, h / 2, r - ring - Math.max(1f, r * 0.02f), paint);
            postInvalidateOnAnimation();
        } else {
            paint.setStrokeWidth(Math.max(1f, r * 0.05f));
            paint.setColor(Color.argb((int) (alpha * 160), 255, 255, 255));
            c.drawCircle(w / 2, h / 2, r, paint);
        }
        paint.setColor(Color.argb((int) (Math.min(1f, alpha + 0.25f) * 255), 255, 255, 255));
        Icons.draw(c, icon, w / 2, h / 2, r * 1.15f, paint);
    }

    /** A finger is on it. */
    boolean held() { return pressed; }

    /** Let go without the finger lifting (the layer took the screen): the
     *  release as if it lifted, unless a long press already ended it. */
    void cancelPress() {
        removeCallbacks(hold);
        if (!pressed) return;
        pressed = false;
        invalidate();
        if (!longFired) listener.onPress(this, false);
    }

    @Override public boolean onTouchEvent(MotionEvent e) {
        int a = e.getActionMasked();
        if (a == MotionEvent.ACTION_DOWN) {
            pressed = true;
            longFired = false;
            if (longPress != null) postDelayed(hold, 650);
            if (haptics != null) haptics.tick();
            invalidate();
            listener.onPress(this, true);
        } else if (a == MotionEvent.ACTION_MOVE) {
            if (pressed && drag != null) drag.moved(e.getRawX(), e.getRawY(), false);
        } else if (a == MotionEvent.ACTION_UP || a == MotionEvent.ACTION_CANCEL) {
            removeCallbacks(hold);
            if (pressed) {
                pressed = false;
                invalidate();
                if (drag != null) drag.moved(e.getRawX(), e.getRawY(), true);
                if (!longFired) listener.onPress(this, false);
            }
        }
        return true;
    }
}
