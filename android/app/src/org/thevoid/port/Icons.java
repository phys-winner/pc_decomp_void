package org.thevoid.port;

import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;

/** Line icons for the touch controls, drawn in a box of side s centred at (cx, cy). */
final class Icons {
    static final int MENU = 0, BODY = 1, JOURNAL = 2, MAP = 3, JUMP = 4, USE = 5, PAINT = 6, RUN = 7, GEAR = 8;
    static final int SAVE = 9, LOAD = 10, CLOSE = 11, CHECK = 12, SKIP = 13, FAST = 14, SLOW = 15, BACK = 16;
    static final int HELP = 17, TOUCH = 18, CAMERA = 19, LOCATE = 20, RESET = 21, DEBUG = 22;

    private Icons() { }

    static void draw(Canvas c, int icon, float cx, float cy, float s, Paint p) {
        float u = s / 24f;   /* the icons are designed on a 24-unit grid */
        p.setStyle(Paint.Style.STROKE);
        p.setStrokeWidth(Math.max(1.5f, 2f * u));
        p.setStrokeCap(Paint.Cap.ROUND);
        p.setStrokeJoin(Paint.Join.ROUND);
        c.save();
        c.translate(cx - 12 * u, cy - 12 * u);
        c.scale(u, u);
        p.setStrokeWidth(2f);
        Path path = new Path();
        switch (icon) {
        case MENU:
            c.drawLine(5, 7, 19, 7, p);
            c.drawLine(5, 12, 19, 12, p);
            c.drawLine(5, 17, 19, 17, p);
            break;
        case BODY:   /* a heart */
            path.moveTo(12, 20);
            path.cubicTo(4, 14.5f, 3, 10, 5, 7);
            path.cubicTo(7, 4, 11, 4.5f, 12, 8);
            path.cubicTo(13, 4.5f, 17, 4, 19, 7);
            path.cubicTo(21, 10, 20, 14.5f, 12, 20);
            path.close();
            c.drawPath(path, p);
            break;
        case JOURNAL:   /* an open book */
            path.moveTo(12, 7);
            path.cubicTo(9.5f, 5.2f, 6.5f, 5, 3.5f, 5.5f);
            path.lineTo(3.5f, 18);
            path.cubicTo(6.5f, 17.5f, 9.5f, 17.8f, 12, 19.5f);
            path.cubicTo(14.5f, 17.8f, 17.5f, 17.5f, 20.5f, 18);
            path.lineTo(20.5f, 5.5f);
            path.cubicTo(17.5f, 5, 14.5f, 5.2f, 12, 7);
            path.lineTo(12, 19.5f);
            c.drawPath(path, p);
            break;
        case MAP:   /* nodes joined by threads, as the game's map */
            c.drawLine(7, 8, 12, 14, p);
            c.drawLine(17, 7, 12, 14, p);
            c.drawLine(12, 14, 13, 20, p);
            p.setStyle(Paint.Style.FILL);
            c.drawCircle(7, 7.5f, 2.6f, p);
            c.drawCircle(17.5f, 6.5f, 2.2f, p);
            c.drawCircle(12, 14, 3.2f, p);
            c.drawCircle(13, 20, 1.8f, p);
            break;
        case JUMP:   /* an arrow up from the ground */
            c.drawLine(12, 17, 12, 5, p);
            path.moveTo(7, 10);
            path.lineTo(12, 5);
            path.lineTo(17, 10);
            c.drawPath(path, p);
            c.drawLine(6, 20.5f, 18, 20.5f, p);
            break;
        case USE:   /* an open hand */
            path.moveTo(7.5f, 6.5f);
            path.lineTo(7.5f, 15);
            path.cubicTo(7.5f, 19, 10, 21, 13, 21);
            path.cubicTo(16, 21, 17.5f, 19, 17.5f, 15);
            path.lineTo(17.5f, 12);
            path.moveTo(10.5f, 12);
            path.lineTo(10.5f, 4.5f);
            path.moveTo(13.5f, 12);
            path.lineTo(13.5f, 5);
            path.moveTo(16.5f, 12.5f);
            path.lineTo(16.5f, 7.5f);
            path.moveTo(7.5f, 15.5f);
            path.lineTo(5, 12.5f);
            c.drawPath(path, p);
            break;
        case PAINT:   /* a brush and its stroke */
            path.moveTo(19.5f, 3.5f);
            path.lineTo(11, 12);
            c.drawPath(path, p);
            path.reset();
            path.moveTo(11, 12);
            path.cubicTo(8, 11, 6, 13, 6, 15.5f);
            path.cubicTo(6, 17.5f, 4.5f, 18.5f, 3.5f, 19);
            path.cubicTo(7, 20.5f, 11.5f, 19.5f, 12.5f, 15.5f);
            path.close();
            p.setStyle(Paint.Style.FILL);
            c.drawPath(path, p);
            break;
        case RUN:   /* fast forward */
            path.moveTo(5, 6);
            path.lineTo(11, 12);
            path.lineTo(5, 18);
            path.moveTo(12, 6);
            path.lineTo(18, 12);
            path.lineTo(12, 18);
            c.drawPath(path, p);
            break;
        case GEAR:
            c.drawCircle(12, 12, 3, p);
            for (int i = 0; i < 8; ++i) {
                double a = Math.PI * i / 4;
                float x0 = 12 + (float) Math.cos(a) * 6.5f, y0 = 12 + (float) Math.sin(a) * 6.5f;
                float x1 = 12 + (float) Math.cos(a) * 9f, y1 = 12 + (float) Math.sin(a) * 9f;
                c.drawLine(x0, y0, x1, y1, p);
            }
            c.drawCircle(12, 12, 6.5f, p);
            break;
        case SAVE:
        case LOAD:   /* a tray with an arrow into it or out of it */
            path.moveTo(4, 14);
            path.lineTo(4, 20);
            path.lineTo(20, 20);
            path.lineTo(20, 14);
            c.drawPath(path, p);
            c.drawLine(12, 3.5f, 12, 15, p);
            path.reset();
            if (icon == SAVE) {
                path.moveTo(7.5f, 10.5f);
                path.lineTo(12, 15);
                path.lineTo(16.5f, 10.5f);
            } else {
                path.moveTo(7.5f, 8);
                path.lineTo(12, 3.5f);
                path.lineTo(16.5f, 8);
            }
            c.drawPath(path, p);
            break;
        case CLOSE:
            c.drawLine(6, 6, 18, 18, p);
            c.drawLine(18, 6, 6, 18, p);
            break;
        case CHECK:
            path.moveTo(5, 12.5f);
            path.lineTo(10, 17.5f);
            path.lineTo(19, 6.5f);
            c.drawPath(path, p);
            break;
        case SKIP:   /* next: a triangle and a bar (the next line of a dialogue) */
            path.moveTo(6, 6);
            path.lineTo(15, 12);
            path.lineTo(6, 18);
            path.close();
            c.drawPath(path, p);
            c.drawLine(18.5f, 6, 18.5f, 18, p);
            break;
        case FAST:   /* time runs fast: two filled triangles */
            p.setStyle(Paint.Style.FILL);
            path.moveTo(3.5f, 6.5f);
            path.lineTo(11.5f, 12);
            path.lineTo(3.5f, 17.5f);
            path.close();
            path.moveTo(12, 6.5f);
            path.lineTo(20, 12);
            path.lineTo(12, 17.5f);
            path.close();
            c.drawPath(path, p);
            break;
        case SLOW:   /* time runs slow: an hourglass */
            c.drawLine(6, 4.5f, 18, 4.5f, p);
            c.drawLine(6, 19.5f, 18, 19.5f, p);
            path.moveTo(7.5f, 4.5f);
            path.cubicTo(7.5f, 9, 11, 10.5f, 12, 12);
            path.cubicTo(13, 10.5f, 16.5f, 9, 16.5f, 4.5f);
            path.moveTo(7.5f, 19.5f);
            path.cubicTo(7.5f, 15, 11, 13.5f, 12, 12);
            path.cubicTo(13, 13.5f, 16.5f, 15, 16.5f, 19.5f);
            c.drawPath(path, p);
            path.reset();
            p.setStyle(Paint.Style.FILL);
            path.moveTo(9.5f, 19);
            path.lineTo(12, 16);
            path.lineTo(14.5f, 19);
            path.close();
            c.drawPath(path, p);
            break;
        case HELP:   /* a question mark */
            path.moveTo(8.5f, 9);
            path.cubicTo(8.5f, 5, 15.5f, 5, 15.5f, 9);
            path.cubicTo(15.5f, 12, 12, 12, 12, 15);
            c.drawPath(path, p);
            p.setStyle(Paint.Style.FILL);
            c.drawCircle(12, 19, 1.4f, p);
            break;
        case TOUCH:   /* a fingertip's ring */
            c.drawCircle(12, 12, 7, p);
            p.setStyle(Paint.Style.FILL);
            c.drawCircle(12, 12, 2.5f, p);
            break;
        case LOCATE:   /* a navigator's arrow pointing up: where the hero is */
            p.setStyle(Paint.Style.FILL);
            path.moveTo(12, 3.5f);
            path.lineTo(19.5f, 20);
            path.lineTo(12, 15.5f);
            path.lineTo(4.5f, 20);
            path.close();
            c.drawPath(path, p);
            break;
        case CAMERA:   /* a camera: its body with the viewfinder's hump, and the lens */
            path.moveTo(3.5f, 8);
            path.lineTo(7.5f, 8);
            path.lineTo(9.2f, 5.5f);
            path.lineTo(14.8f, 5.5f);
            path.lineTo(16.5f, 8);
            path.lineTo(20.5f, 8);
            path.lineTo(20.5f, 19);
            path.lineTo(3.5f, 19);
            path.close();
            c.drawPath(path, p);
            c.drawCircle(12, 13.2f, 3.6f, p);
            break;
        case BACK:   /* an arrow to the left */
            c.drawLine(19, 12, 5.5f, 12, p);
            path.moveTo(11, 6.5f);
            path.lineTo(5.5f, 12);
            path.lineTo(11, 17.5f);
            c.drawPath(path, p);
            break;
        case RESET:   /* an arrow turning back round: as it was */
            path.addArc(new RectF(5, 5, 19, 19), -60, 290);
            c.drawPath(path, p);
            path.reset();
            path.moveTo(15.5f, 3.5f);
            path.lineTo(16, 6.4f);
            path.lineTo(13.1f, 7.2f);
            c.drawPath(path, p);
            break;
        case DEBUG:   /* a console prompt: the game's commands */
            path.moveTo(5, 7.5f);
            path.lineTo(10, 12);
            path.lineTo(5, 16.5f);
            c.drawPath(path, p);
            c.drawLine(12.5f, 17, 19, 17, p);
            break;
        default:
            c.drawOval(new RectF(6, 6, 18, 18), p);
        }
        c.restore();
    }
}
