package org.thevoid.port;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.os.VibrationEffect;
import android.os.Vibrator;

/** The layer's vibration: short ticks for the on-screen buttons, a tap when
 *  the hero lands, a longer one when he is hurt, and a soft pulse while he
 *  sucks colour from a tree or a vein (android/host/sound_events.c). The
 *  platform's haptic constants are long on some phones (MIUI): the layer
 *  sets its own durations and strengths. */
final class Haptics {
    private final Vibrator vibrator;
    private final boolean amplitude;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private boolean enabled = true, pulsing;
    private long busyUntil;   /* a one-shot plays: the pulse waits for it */
    private final Runnable resumePulse = this::startPulse;

    Haptics(Context c) {
        Vibrator v = (Vibrator) c.getSystemService(Context.VIBRATOR_SERVICE);
        vibrator = v != null && v.hasVibrator() ? v : null;
        amplitude = vibrator != null && vibrator.hasAmplitudeControl();
    }

    void setEnabled(boolean on) {
        enabled = on;
        if (!on && vibrator != null) { handler.removeCallbacks(resumePulse); vibrator.cancel(); }
        else if (on && pulsing) startPulse();
    }

    /** An on-screen button. */
    void tick() { once(9, 70); }

    /** The hero lands after a jump or a fall. */
    void land() { once(16, 110); }

    /** The hero is hurt. */
    void damage() { once(45, 220); }

    /** Sucking colour: a soft beat while it lasts. */
    void pulse(boolean on) {
        if (on == pulsing) return;
        pulsing = on;
        if (on) startPulse();
        else if (vibrator != null) { handler.removeCallbacks(resumePulse); vibrator.cancel(); }
    }

    private void startPulse() {
        if (!enabled || !pulsing || vibrator == null) return;
        long wait = busyUntil - SystemClock.uptimeMillis();
        if (wait > 0) { handler.postDelayed(resumePulse, wait); return; }
        long[] timings = {0, 22, 210};
        int[] strengths = {0, 45, 0};
        vibrator.vibrate(amplitude ? VibrationEffect.createWaveform(timings, strengths, 1)
                                   : VibrationEffect.createWaveform(timings, 1));
    }

    private void once(int ms, int strength) {
        if (!enabled || vibrator == null) return;
        vibrator.vibrate(VibrationEffect.createOneShot(ms, amplitude ? strength : VibrationEffect.DEFAULT_AMPLITUDE));
        busyUntil = SystemClock.uptimeMillis() + ms;
        if (pulsing) {   /* a one-shot replaces the pulse: start it again after */
            handler.removeCallbacks(resumePulse);
            handler.postDelayed(resumePulse, ms + 10);
        }
    }
}
