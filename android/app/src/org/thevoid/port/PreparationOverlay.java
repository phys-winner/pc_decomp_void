package org.thevoid.port;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.Shader;
import android.graphics.Typeface;
import android.view.View;

/** The game's muted ivory rules and serif lettering, without Android widget chrome. */
final class PreparationOverlay extends View {
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private String title = "", detail = "";
    private int completed, total;

    PreparationOverlay(Context context) {
        super(context);
        paint.setTypeface(Typeface.create("serif", Typeface.NORMAL));
        setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_YES);
        setClickable(true);
    }

    void update(String title, String detail, int completed, int total) {
        this.title = title;
        this.detail = detail;
        this.total = Math.max(0, total);
        this.completed = Math.max(0, Math.min(completed, this.total));
        setContentDescription(title + ". " + detail);
        invalidate();
    }

    @Override protected void onDraw(Canvas canvas) {
        float w = getWidth(), h = getHeight();
        float unit = Math.min(h / 540f, w / 800f);
        float center = w / 2, width = Math.min(w - 56 * unit, 360 * unit);
        float left = center - width / 2, right = center + width / 2;
        float line = h - 26 * unit;
        paint.setShader(new LinearGradient(0, h - 92 * unit, 0, h,
            new int[] {0x00060408, 0xD9060408, 0xF0060408}, null, Shader.TileMode.CLAMP));
        canvas.drawRect(left - 20 * unit, Math.max(0, h - 92 * unit), right + 20 * unit, h, paint);
        paint.setShader(null);
        paint.setStyle(Paint.Style.FILL);
        paint.setTextAlign(Paint.Align.CENTER);
        label(canvas, title, center, line - 18 * unit, 18 * unit, width, 0xFFF0E8D4);
        paint.setStrokeWidth(Math.max(1, unit));
        paint.setColor(0x705C5649);
        canvas.drawLine(left, line, right, line, paint);
        paint.setColor(0xFFE1D3B1);
        if (total > 0) {
            canvas.drawLine(left, line, left + width * completed / total, line, paint);
        } else {
            float phase = (android.os.SystemClock.uptimeMillis() % 2400L) / 2400f;
            float position = left + (width - width / 6) * (1 - Math.abs(phase * 2 - 1));
            canvas.drawLine(position, line, position + width / 6, line, paint);
        }
        diamond(canvas, left - 9 * unit, line, 3 * unit);
        diamond(canvas, right + 9 * unit, line, 3 * unit);
    }

    private void label(Canvas canvas, String text, float x, float y, float size, float width, int colour) {
        paint.setTextSize(size);
        float measured = paint.measureText(text);
        if (measured > width) paint.setTextSize(size * width / measured);
        paint.setColor(colour);
        canvas.drawText(text, x, y, paint);
    }

    private void diamond(Canvas canvas, float x, float y, float r) {
        canvas.drawLine(x - r, y, x, y - r, paint);
        canvas.drawLine(x, y - r, x + r, y, paint);
        canvas.drawLine(x + r, y, x, y + r, paint);
        canvas.drawLine(x, y + r, x - r, y, paint);
    }
}
