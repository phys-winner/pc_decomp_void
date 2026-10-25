package org.thevoid.port;

import java.util.LinkedHashMap;
import java.util.Map;

/** Normalized touch rectangles; independent of Android so saved layouts can be checked on the JVM.
 *  Positions are fractions of the whole view, the camera cutout included: a button may sit beside
 *  the camera. Layouts saved before (no "v2" mark) measured across the part clear of the cutout;
 *  {@link #fromSafeArea} moves them into the whole view once the cutout is known. */
final class TouchLayout {
    static final String MOVE = "movement", LOOK = "look";
    static final String[] BUTTONS = {"menu", "body", "journal", "map", "jump", "skip",
        "use", "paint", "locate", "slow", "fast"};
    private static final String VERSION = "v2";

    static final class Rect {
        final float x, y, width, height;
        Rect(float x, float y, float width, float height) {
            this.width = Math.max(.025f, Math.min(1, width));
            this.height = Math.max(.025f, Math.min(1, height));
            this.x = Math.max(this.width / 2, Math.min(1 - this.width / 2, x));
            this.y = Math.max(this.height / 2, Math.min(1 - this.height / 2, y));
        }
        boolean contains(float px, float py) {
            return Math.abs(px - x) <= width / 2 && Math.abs(py - y) <= height / 2;
        }
    }

    private final Map<String, Rect> entries = new LinkedHashMap<>();
    /** Read from a layout of the cutout-clear frame, not yet moved into the whole view. */
    boolean legacy;

    TouchLayout() { }

    TouchLayout(String encoded) {
        if (encoded == null || encoded.length() > 8192) return;
        boolean marked = false;
        for (String row : encoded.split(";")) {
            if (row.equals(VERSION)) { marked = true; continue; }
            String[] fields = row.split(",");
            if (fields.length != 5 || !known(fields[0])) continue;
            try {
                float x = Float.parseFloat(fields[1]), y = Float.parseFloat(fields[2]);
                float w = Float.parseFloat(fields[3]), h = Float.parseFloat(fields[4]);
                if (finite(x) && finite(y) && finite(w) && finite(h) && w > 0 && h > 0)
                    put(fields[0], x, y, w, h);
            } catch (NumberFormatException ignored) { }
        }
        legacy = !marked && !entries.isEmpty();
    }

    private static boolean finite(float value) { return !Float.isNaN(value) && !Float.isInfinite(value); }

    private static boolean known(String id) {
        if (MOVE.equals(id) || LOOK.equals(id)) return true;
        for (String button : BUTTONS) if (button.equals(id)) return true;
        return false;
    }

    Rect get(String id) { return entries.get(id); }

    boolean isEmpty() { return entries.isEmpty(); }

    void put(String id, float x, float y, float width, float height) {
        if (!known(id) || !finite(x) || !finite(y) || !finite(width) || !finite(height) || width <= 0 || height <= 0)
            throw new IllegalArgumentException("Invalid touch rectangle: " + id);
        entries.put(id, new Rect(x, y, width, height));
    }

    void remove(String id) { entries.remove(id); }

    TouchLayout copy() {
        TouchLayout copy = new TouchLayout();
        copy.entries.putAll(entries);
        copy.legacy = legacy;
        return copy;
    }

    void overlay(TouchLayout other) { entries.putAll(other.entries); }

    /** A layout measured across the part of a view `total` pixels wide that is clear of the
     *  cutout (`left` and `right` pixels at its sides), moved into the whole view. */
    TouchLayout fromSafeArea(int left, int right, int total) {
        TouchLayout moved = new TouchLayout();
        float safe = Math.max(1, total - left - right), whole = Math.max(1, total);
        for (Map.Entry<String, Rect> entry : entries.entrySet()) {
            Rect r = entry.getValue();
            moved.put(entry.getKey(), (left + r.x * safe) / whole, r.y, r.width * safe / whole, r.height);
        }
        return moved;
    }

    String encode() {
        if (entries.isEmpty()) return "";
        StringBuilder text = new StringBuilder(VERSION).append(';');
        for (Map.Entry<String, Rect> entry : entries.entrySet()) {
            Rect r = entry.getValue();
            text.append(entry.getKey()).append(',').append(r.x).append(',').append(r.y)
                .append(',').append(r.width).append(',').append(r.height).append(';');
        }
        return text.toString();
    }

    static TouchLayout zones(boolean leftHanded) {
        TouchLayout layout = new TouchLayout();
        layout.put(MOVE, leftHanded ? .8f : .2f, .5f, .4f, 1);
        layout.put(LOOK, leftHanded ? .3f : .7f, .5f, .6f, 1);
        return layout;
    }
}
