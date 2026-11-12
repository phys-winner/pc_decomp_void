package port.launcher;

import android.app.Activity;
import android.app.AlertDialog;
import android.animation.ValueAnimator;
import android.content.res.ColorStateList;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Matrix;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.Shader;
import android.graphics.Typeface;
import android.graphics.drawable.ClipDrawable;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.LayerDrawable;
import android.graphics.drawable.RippleDrawable;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.os.Build;
import android.os.SystemClock;
import android.provider.Settings;
import android.view.Gravity;
import android.view.Surface;
import android.view.View;
import android.view.WindowInsets;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import org.json.JSONArray;
import org.json.JSONObject;

/** The launcher's look from the theme tokens of port.json: cards, buttons, a drawn switch (the
 *  platform's one is near invisible on dark backgrounds), progress bars and edge-to-edge insets. */
final class Ui {
    static final int PRIMARY = 0, SECONDARY = 1, QUIET = 2;
    static final int WARNING = 0xFFFFD166;

    final Activity activity;
    final int[] background;
    final int card, cardStroke, cell, accent, accentDark, primaryFill, playGlow, playParticles, text, muted, error, good;
    final String playParticleStyle;
    final Typeface titleFont, bold, regular;

    Ui(Activity activity) {
        this.activity = activity;
        JSONObject t = Spec.get(activity).theme;
        JSONArray gradient = t.optJSONArray("background");
        int[] colours = {0xFF141A22, 0xFF0B0F14, 0xFF030405};
        if (gradient != null && gradient.length() > 0) {
            colours = new int[gradient.length()];
            for (int i = 0; i < colours.length; ++i) colours[i] = parse(gradient.optString(i), 0xFF0B0F14);
        }
        background = colours;
        card = colour(t, "card", 0xEB181B22);
        cardStroke = colour(t, "cardStroke", 0x40FFFFFF);
        cell = colour(t, "cell", 0xFF262A33);
        accent = colour(t, "accent", 0xFFE8742A);
        accentDark = colour(t, "accentDark", 0xFF9A4A16);
        primaryFill = colour(t, "primaryFill", 0xFF3A2414);
        text = colour(t, "text", 0xFFF2F4F7);
        playGlow = colour(t, "playGlow", accent);
        playParticles = colour(t, "playParticles", text);
        playParticleStyle = t.optString("playParticleStyle", "magic");
        muted = colour(t, "muted", 0xFFA7AFBC);
        error = colour(t, "error", 0xFFFF8C7A);
        good = colour(t, "good", 0xFF9FD59A);
        titleFont = font(t.optString("titleFont", "sans-serif-medium"));
        bold = Typeface.create("sans-serif-medium", Typeface.NORMAL);
        regular = Typeface.create("sans-serif", Typeface.NORMAL);
    }

    private static int colour(JSONObject theme, String key, int fallback) { return theme == null ? fallback : parse(theme.optString(key, ""), fallback); }

    static int parse(String text, int fallback) {
        try { return text.isEmpty() ? fallback : Color.parseColor(text); }
        catch (IllegalArgumentException e) { return fallback; }
    }

    /** "serif-bold", "sans-serif-medium", "serif-italic", "monospace". */
    static Typeface font(String name) {
        int style = Typeface.NORMAL;
        if (name.endsWith("-bold")) { style = Typeface.BOLD; name = name.substring(0, name.length() - 5); }
        else if (name.endsWith("-italic")) { style = Typeface.ITALIC; name = name.substring(0, name.length() - 7); }
        return Typeface.create(name, style);
    }

    int dp(float v) { return Math.round(v * activity.getResources().getDisplayMetrics().density); }

    boolean wide() { return activity.getResources().getConfiguration().screenWidthDp >= 720; }

    Drawable backdrop() {
        return background.length == 1 ? new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, new int[] {background[0], background[0]})
            : new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, background);
    }

    /** Draws behind the system bars and pads the content by them and the display cutout. */
    void edgeToEdge(View root) {
        if (Build.VERSION.SDK_INT >= 35) { /* edge to edge already */ }
        else if (Build.VERSION.SDK_INT >= 30) activity.getWindow().setDecorFitsSystemWindows(false);
        else root.setSystemUiVisibility(View.SYSTEM_UI_FLAG_LAYOUT_STABLE | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
            | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
        if (Build.VERSION.SDK_INT < 35) {
            activity.getWindow().setStatusBarColor(Color.TRANSPARENT);
            activity.getWindow().setNavigationBarColor(Color.TRANSPARENT);
        }
        final int left = root.getPaddingLeft(), top = root.getPaddingTop(), right = root.getPaddingRight(), bottom = root.getPaddingBottom();
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            int[] e = edges(insets);
            view.setPadding(left + e[0], top + e[1], right + e[2], bottom + e[3]);
            return insets;
        });
        root.requestApplyInsets();
    }

    private static int[] edges(WindowInsets insets) {
        if (Build.VERSION.SDK_INT >= 30) {
            android.graphics.Insets e = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
            return new int[] {e.left, e.top, e.right, e.bottom};
        }
        return new int[] {insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
            insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom()};
    }

    LinearLayout card(LinearLayout parent) {
        LinearLayout c = new LinearLayout(activity);
        c.setOrientation(LinearLayout.VERTICAL);
        c.setPadding(dp(16), dp(10), dp(16), dp(14));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(card);
        bg.setCornerRadius(dp(16));
        bg.setStroke(dp(1), cardStroke);
        c.setBackground(bg);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(12), 0, 0);
        if (parent != null) parent.addView(c, lp);
        else c.setLayoutParams(lp);
        return c;
    }

    TextView label(String value, float sp, int colour) {
        TextView t = new TextView(activity);
        t.setText(value);
        t.setTextSize(sp);
        t.setTextColor(colour);
        t.setTypeface(regular);
        t.setLineSpacing(dp(1), 1.05f);
        t.setPadding(0, dp(3), 0, dp(2));
        return t;
    }

    TextView heading(String value) {
        TextView t = label(value.toUpperCase(java.util.Locale.getDefault()), 12, accent);
        t.setTypeface(bold);
        t.setLetterSpacing(0.08f);
        t.setPadding(0, dp(6), 0, dp(4));
        return t;
    }

    TextView button(String value, int kind, Runnable action) {
        return button(value, kind, null, action);
    }

    TextView button(String value, int kind, JSONObject theme, Runnable action) {
        TextView b = new ActionButton(theme);
        b.setText(value);
        b.setTag(value);
        b.setGravity(Gravity.CENTER);
        b.setTextSize(kind == PRIMARY ? 19 : 15);
        b.setTypeface(bold);
        b.setTextColor(kind == PRIMARY ? accent : kind == SECONDARY ? text : muted);
        b.setMinHeight(dp(kind == PRIMARY ? 54 : 46));
        b.setPadding(dp(14), dp(8), dp(14), dp(8));
        GradientDrawable shape = new GradientDrawable();
        shape.setCornerRadius(dp(kind == PRIMARY ? 14 : 12));
        shape.setColor(kind == PRIMARY ? colour(theme, "primaryFill", primaryFill) : kind == SECONDARY ? cell : Color.TRANSPARENT);
        if (kind == PRIMARY) shape.setStroke(dp(2), colour(theme, "accentDark", accentDark));
        GradientDrawable mask = new GradientDrawable();
        mask.setCornerRadius(dp(14));
        mask.setColor(Color.WHITE);
        b.setBackground(new RippleDrawable(ColorStateList.valueOf(0x30FFFFFF), shape, mask));
        b.setFocusable(true);
        b.setOnClickListener(v -> action.run());
        return b;
    }

    void attention(TextView button, boolean sparkle) {
        ((ActionButton) button).effect = sparkle ? 2 : 1;
        if (sparkle) button.setTextColor(text);
        button.invalidate();
    }

    private final class ActionButton extends TextView implements SensorEventListener {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Path clip = new Path();
        private final Matrix shift = new Matrix();
        private final int glow, particles, particleStyle;
        private final LinearGradient sheen;
        private final float[] particleX = new float[6], particlePhase = new float[6];
        private final Path water = new Path();
        private final Path plumbob = new Path();
        private SensorManager sensors;
        private boolean listening;
        private float tilt, waterTilt, ripple;
        int effect;

        ActionButton(JSONObject theme) {
            super(activity);
            glow = colour(theme, "playGlow", playGlow);
            particles = colour(theme, "playParticles", playParticles);
            String style = theme == null ? playParticleStyle : theme.optString("playParticleStyle", playParticleStyle);
            if (!"magic".equals(style) && !"snow".equals(style) && !"embers".equals(style) && !"water".equals(style) && !"plumbob".equals(style)) style = playParticleStyle;
            particleStyle = "plumbob".equals(style) ? 4 : "water".equals(style) ? 3 : "snow".equals(style) ? 1 : "embers".equals(style) ? 2 : 0;
            java.util.concurrent.ThreadLocalRandom random = java.util.concurrent.ThreadLocalRandom.current();
            for (int i = 0; i < particleX.length; ++i) {
                particleX[i] = 0.1f + 0.8f * random.nextFloat();
                particlePhase[i] = random.nextFloat();
            }
            int rgb = particles & 0x00FFFFFF;
            sheen = new LinearGradient(0, 0, dp(80), 0,
                new int[] {rgb, 0x28000000 | rgb, rgb}, null, Shader.TileMode.CLAMP);
        }

        @Override protected void onSizeChanged(int w, int h, int oldw, int oldh) {
            super.onSizeChanged(w, h, oldw, oldh);
            clip.reset();
            clip.addRoundRect(0, 0, w, h, dp(14), dp(14), Path.Direction.CW);
        }

        @Override public void onWindowFocusChanged(boolean focused) {
            super.onWindowFocusChanged(focused);
            updateSensors();
            invalidate();
        }

        @Override protected void onWindowVisibilityChanged(int visibility) {
            super.onWindowVisibilityChanged(visibility);
            updateSensors();
            invalidate();
        }

        @Override protected void onAttachedToWindow() { super.onAttachedToWindow(); updateSensors(); }
        @Override protected void onDetachedFromWindow() {
            if (sensors != null) sensors.unregisterListener(this);
            listening = false;
            super.onDetachedFromWindow();
        }

        private void updateSensors() {
            if (particleStyle != 3) return;
            boolean active = isAttachedToWindow() && hasWindowFocus() && getWindowVisibility() == View.VISIBLE
                && isShown() && ValueAnimator.areAnimatorsEnabled();
            if (active == listening) return;
            if (sensors == null) sensors = (SensorManager) activity.getSystemService(android.content.Context.SENSOR_SERVICE);
            if (sensors == null) return;
            listening = active;
            if (!active) { sensors.unregisterListener(this); return; }
            Sensor gravity = sensors.getDefaultSensor(Sensor.TYPE_GRAVITY);
            if (gravity == null) gravity = sensors.getDefaultSensor(Sensor.TYPE_ACCELEROMETER);
            if (gravity != null) sensors.registerListener(this, gravity, SensorManager.SENSOR_DELAY_GAME);
            Sensor gyro = sensors.getDefaultSensor(Sensor.TYPE_GYROSCOPE);
            if (gyro != null) sensors.registerListener(this, gyro, SensorManager.SENSOR_DELAY_GAME);
        }

        @Override public void onSensorChanged(SensorEvent event) {
            if (event.sensor.getType() == Sensor.TYPE_GYROSCOPE) {
                ripple = Math.min(dp(4), ripple + Math.abs(event.values[2]) * dp(.3f));
                return;
            }
            float x = event.values[0], y = event.values[1];
            int rotation = getDisplay() != null ? getDisplay().getRotation() : Surface.ROTATION_0;
            float horizontal = rotation == Surface.ROTATION_90 ? -y : rotation == Surface.ROTATION_270 ? y
                : rotation == Surface.ROTATION_180 ? -x : x;
            float vertical = rotation == Surface.ROTATION_90 ? x : rotation == Surface.ROTATION_270 ? -x
                : rotation == Surface.ROTATION_180 ? -y : y;
            if (Math.hypot(horizontal, vertical) > 1)
                tilt = Math.max(-1, Math.min(1, horizontal / Math.max(2, Math.abs(vertical))));
        }

        @Override public void onAccuracyChanged(Sensor sensor, int accuracy) { }

        private void drawWater(Canvas canvas, float phase, boolean motion) {
            waterTilt += (tilt - waterTilt) * .25f;
            ripple *= .96f;
            float w = getWidth(), h = getHeight(), slope = motion ? waterTilt : 0;
            float level = waterLevel(w, h, slope);
            water.reset();
            water.moveTo(0, h);
            for (int i = 0; i <= 48; ++i) {
                float x = w * i / 48;
                float wave = motion ? (float) Math.sin(x / Math.max(1, w) * Math.PI * 4 + phase * Math.PI * 2)
                    * (dp(1.2f) + ripple) : 0;
                water.lineTo(x, level + (x - w / 2) * slope + wave);
            }
            water.lineTo(w, h); water.close();
            paint.setColor(0xFF146D86); paint.setAlpha(210);
            canvas.drawPath(water, paint);
            int saved = canvas.save();
            canvas.clipPath(water);
            paint.setColor(0xFF80E8F0); paint.setStyle(Paint.Style.STROKE); paint.setStrokeWidth(dp(1));
            for (int i = 0; i < particleX.length; ++i) {
                float age = (phase + particlePhase[i]) % 1;
                float x = w * particleX[i] + (float) Math.sin(age * 8 + i) * dp(4);
                float surface = level + (x - w / 2) * slope;
                float y = h - age * (h - Math.max(0, surface));
                float radius = dp(2 + i % 3);
                paint.setAlpha((int) (170 * Math.sin(age * Math.PI)));
                canvas.drawCircle(x, y, radius, paint);
                paint.setAlpha(90);
                canvas.drawCircle(x - radius * .3f, y - radius * .3f, dp(.6f), paint);
            }
            paint.setStyle(Paint.Style.FILL);
            canvas.restoreToCount(saved);
        }

        private void drawPlumbob(Canvas canvas, float x, float y, float fade) {
            float h = dp(7) * (.75f + .25f * fade), w = h * .6f;
            float dx = dp(.75f), dy = dp(1);
            plumbob.reset();
            plumbob.moveTo(x + dx, y - h + dy); plumbob.lineTo(x + w + dx, y + dy);
            plumbob.lineTo(x + dx, y + h + dy); plumbob.lineTo(x - w + dx, y + dy); plumbob.close();
            paint.setColor(Color.BLACK); paint.setAlpha((int) (70 * fade));
            canvas.drawPath(plumbob, paint);
            plumbob.reset();
            plumbob.moveTo(x, y - h); plumbob.lineTo(x + w, y);
            plumbob.lineTo(x, y + h); plumbob.lineTo(x - w, y); plumbob.close();
            paint.setColor(particles); paint.setAlpha((int) (220 * fade));
            canvas.drawPath(plumbob, paint);
            plumbob.reset();
            plumbob.moveTo(x, y - h); plumbob.lineTo(x - w, y); plumbob.lineTo(x, y + h / 6); plumbob.close();
            paint.setColor(0xFFB8F580); paint.setAlpha((int) (220 * fade));
            canvas.drawPath(plumbob, paint);
            plumbob.reset();
            plumbob.moveTo(x, y - h); plumbob.lineTo(x, y + h / 6); plumbob.lineTo(x + w, y); plumbob.close();
            paint.setColor(0xFF56BF35); paint.setAlpha((int) (220 * fade));
            canvas.drawPath(plumbob, paint);
            plumbob.reset();
            plumbob.moveTo(x, y + h / 6); plumbob.lineTo(x, y + h); plumbob.lineTo(x + w, y); plumbob.close();
            paint.setColor(0xFF267D22); paint.setAlpha((int) (220 * fade));
            canvas.drawPath(plumbob, paint);
        }

        @Override protected void onDraw(Canvas canvas) {
            if (effect != 0 && isEnabled()) {
                boolean motion = Build.VERSION.SDK_INT >= 26 ? ValueAnimator.areAnimatorsEnabled()
                    : Settings.Global.getFloat(activity.getContentResolver(), Settings.Global.ANIMATOR_DURATION_SCALE, 1f) > 0;
                float phase = motion ? (SystemClock.uptimeMillis() % 3600) / 3600f : 0.25f;
                float pulse = (float) (0.5 - 0.5 * Math.cos(phase * Math.PI * 2));
                float inset = dp(1);
                int saved = canvas.save();
                canvas.clipPath(clip);
                paint.setColor(effect == 2 ? glow : accent);
                paint.setAlpha((int) (12 + 22 * pulse));
                canvas.drawRoundRect(0, 0, getWidth(), getHeight(), dp(14), dp(14), paint);
                paint.setStyle(Paint.Style.STROKE);
                paint.setStrokeWidth(dp(2));
                paint.setAlpha((int) (45 + 85 * pulse));
                canvas.drawRoundRect(inset, inset, getWidth() - inset, getHeight() - inset, dp(13), dp(13), paint);
                paint.setStyle(Paint.Style.FILL);
                if (effect == 2 && particleStyle == 3) drawWater(canvas, phase, motion);
                if (effect == 2 && particleStyle != 3) {
                    shift.setTranslate(-dp(80) + phase * (getWidth() + dp(160)), 0);
                    sheen.setLocalMatrix(shift);
                    paint.setShader(sheen);
                    paint.setAlpha(255);
                    canvas.drawRect(0, 0, getWidth(), getHeight(), paint);
                    paint.setShader(null);
                    paint.setColor(particles);
                    paint.setStrokeWidth(dp(1));
                    for (int i = 0; i < particleX.length; ++i) {
                        float age = (phase + particlePhase[i]) % 1;
                        float fade = (float) Math.sin(age * Math.PI);
                        float sway = (float) Math.sin((age + particlePhase[i]) * Math.PI * 2);
                        float x = getWidth() * (particleX[i] + 0.025f * sway);
                        float y = getHeight() * (particleStyle == 1 ? 0.05f + age * 0.9f
                            : particleStyle == 2 ? 0.95f - age * 0.9f : 0.5f + 0.25f * sway);
                        if (particleStyle == 4) {
                            drawPlumbob(canvas, x, y, fade);
                            continue;
                        }
                        float radius = dp(1.5f) * (particleStyle == 1 ? 0.55f + 0.25f * fade : fade);
                        paint.setAlpha((int) (190 * fade));
                        canvas.drawCircle(x, y, radius * (particleStyle == 2 ? 0.7f : 0.35f), paint);
                        if (particleStyle == 2) {
                            paint.setAlpha((int) (85 * fade));
                            canvas.drawLine(x, y + radius * 0.4f, x, y + radius * 3, paint);
                        } else {
                            canvas.drawLine(x - radius * 2, y, x + radius * 2, y, paint);
                            if (particleStyle == 1) {
                                canvas.drawLine(x - radius, y - radius * 1.732f, x + radius, y + radius * 1.732f, paint);
                                canvas.drawLine(x - radius, y + radius * 1.732f, x + radius, y - radius * 1.732f, paint);
                            } else {
                                canvas.drawLine(x, y - radius * 2, x, y + radius * 2, paint);
                                canvas.drawLine(x - radius, y - radius, x + radius, y + radius, paint);
                                canvas.drawLine(x - radius, y + radius, x + radius, y - radius, paint);
                            }
                        }
                    }
                }
                canvas.restoreToCount(saved);
                if (motion && hasWindowFocus() && getWindowVisibility() == View.VISIBLE && isShown()) postInvalidateDelayed(33);
            }
            super.onDraw(canvas);
        }
    }

    /** Height of a tilted surface with 80% of the rectangular button below it. */
    static float waterLevel(float width, float height, float slope) {
        double span = Math.abs(slope) * width;
        if (span < .0001) return height * .2f;
        double lo = -span / 2, hi = height + span / 2;
        for (int i = 0; i < 24; ++i) {
            double level = (lo + hi) / 2, a = height - level + span / 2, b = height - level - span / 2;
            double aa = Math.max(0, a), ab = Math.max(0, a - height), ba = Math.max(0, b), bb = Math.max(0, b - height);
            double area = (aa * aa - ab * ab - ba * ba + bb * bb) / (2 * span);
            if (area > height * .8) lo = level; else hi = level;
        }
        return (float) ((lo + hi) / 2);
    }

    /** Buttons side by side (wide screens) or stacked. */
    LinearLayout buttons(TextView... list) {
        LinearLayout row = new LinearLayout(activity);
        boolean side = list.length > 1 && (wide() || list.length == 2);
        row.setOrientation(side ? LinearLayout.HORIZONTAL : LinearLayout.VERTICAL);
        for (int i = 0; i < list.length; ++i) {
            LinearLayout.LayoutParams lp = side ? new LinearLayout.LayoutParams(0, -2, 1) : new LinearLayout.LayoutParams(-1, -2);
            if (i > 0) { if (side) lp.leftMargin = dp(8); else lp.topMargin = dp(8); }
            row.addView(list[i], lp);
        }
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = dp(10);
        row.setLayoutParams(lp);
        return row;
    }

    interface BoolSink { void set(boolean value); }

    View foldHeading(String title, String summary, int colour, boolean expanded, BoolSink changed) {
        LinearLayout row = new LinearLayout(activity);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setMinimumHeight(dp(48));
        row.setTag("fold:" + title);
        row.addView(heading((expanded ? "▾ " : "▸ ") + title));
        if (summary != null && !summary.isEmpty()) {
            TextView status = label(summary, 13, colour);
            status.setTypeface(bold, Typeface.BOLD);
            status.setGravity(Gravity.END);
            status.setPadding(dp(8), 0, 0, 0);
            row.addView(status, new LinearLayout.LayoutParams(0, -2, 1));
        }
        row.setFocusable(true);
        row.setOnClickListener(v -> changed.set(!expanded));
        return row;
    }

    /** A label (and hint) with a drawn switch; the whole row toggles. */
    View toggle(String title, String hint, boolean value, BoolSink sink) {
        LinearLayout row = new LinearLayout(activity);
        row.setTag(title);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(0, dp(6), 0, dp(6));
        row.setMinimumHeight(dp(48));
        LinearLayout words = new LinearLayout(activity);
        words.setOrientation(LinearLayout.VERTICAL);
        words.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
        words.addView(label(title, 15, text));
        if (hint != null && !hint.isEmpty()) words.addView(label(hint, 12, muted));
        row.addView(words, new LinearLayout.LayoutParams(0, -2, 1));
        final boolean[] on = {value};
        View pill = new View(activity) {
            private final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);

            @Override protected void onDraw(Canvas c) {
                float w = getWidth(), h = getHeight(), r = h / 2f;
                p.setColor(on[0] ? accentDark : 0xFF555A63);
                c.drawRoundRect(0, 0, w, h, r, r, p);
                p.setColor(on[0] ? accent : 0xFFD7DAE0);
                c.drawCircle(on[0] ? w - r : r, r, r * 0.78f, p);
            }
        };
        pill.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(52), dp(30));
        lp.leftMargin = dp(12);
        row.addView(pill, lp);
        row.setFocusable(true);
        row.setContentDescription(hint == null || hint.isEmpty() ? title : title + "\n" + hint);
        row.setAccessibilityDelegate(new View.AccessibilityDelegate() {
            @Override public void onInitializeAccessibilityNodeInfo(View host, AccessibilityNodeInfo info) {
                super.onInitializeAccessibilityNodeInfo(host, info);
                info.setClassName(android.widget.Switch.class.getName());
                info.setCheckable(true);
                info.setChecked(on[0]);
            }

            @Override public void onInitializeAccessibilityEvent(View host, AccessibilityEvent event) {
                super.onInitializeAccessibilityEvent(host, event);
                event.setClassName(android.widget.Switch.class.getName());
                event.setChecked(on[0]);
            }
        });
        row.setOnClickListener(v -> {
            on[0] = !on[0];
            sink.set(on[0]);
            pill.invalidate();
            row.sendAccessibilityEvent(AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED);
        });
        return row;
    }

    /** A tappable choice: title, hint, a stroke when chosen, faded when unavailable. */
    View choice(String title, String hint, boolean chosen, boolean available, Runnable action) {
        LinearLayout row = new LinearLayout(activity);
        row.setOrientation(LinearLayout.VERTICAL);
        row.setTag(title);
        row.setPadding(dp(12), dp(8), dp(12), dp(8));
        GradientDrawable bg = new GradientDrawable();
        bg.setCornerRadius(dp(12));
        bg.setColor(cell);
        if (chosen) bg.setStroke(dp(2), accent);
        row.setBackground(bg);
        row.addView(label(title, 15, available ? text : muted));
        if (hint != null && !hint.isEmpty()) row.addView(label(hint, 12, muted));
        row.setAlpha(available ? 1f : 0.55f);
        if (action != null) {
            row.setFocusable(true);
            row.setOnClickListener(v -> action.run());
        }
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = dp(8);
        row.setLayoutParams(lp);
        return row;
    }

    ProgressBar progress() {
        ProgressBar bar = new ProgressBar(activity, null, android.R.attr.progressBarStyleHorizontal);
        bar.setMax(1000);
        GradientDrawable track = new GradientDrawable(), fill = new GradientDrawable();
        track.setColor(cell);
        track.setCornerRadius(dp(4));
        fill.setColor(accent);
        fill.setCornerRadius(dp(4));
        LayerDrawable layers = new LayerDrawable(new Drawable[] {track, new ClipDrawable(fill, Gravity.START, ClipDrawable.HORIZONTAL)});
        layers.setId(0, android.R.id.background);
        layers.setId(1, android.R.id.progress);
        bar.setProgressDrawable(layers);
        bar.setIndeterminateTintList(ColorStateList.valueOf(accent));
        return bar;
    }

    AlertDialog.Builder dialog() { return new AlertDialog.Builder(activity, android.R.style.Theme_Material_Dialog_Alert); }

    /** Shows a dialog with its buttons in the port's accent colour instead of the platform's teal. */
    AlertDialog show(AlertDialog.Builder builder) {
        AlertDialog shown = builder.show();
        for (int which : new int[] {AlertDialog.BUTTON_POSITIVE, AlertDialog.BUTTON_NEGATIVE, AlertDialog.BUTTON_NEUTRAL}) {
            android.widget.Button button = shown.getButton(which);
            if (button != null) button.setTextColor(accent);
        }
        return shown;
    }

    static void enable(View v, boolean on) {
        v.setEnabled(on);
        v.setAlpha(on ? 1f : 0.42f);
    }
}
