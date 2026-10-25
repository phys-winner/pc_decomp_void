package org.thevoid.portprobe;

import android.app.Activity;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.os.Bundle;
import android.util.Log;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowInsets;
import android.widget.Button;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.util.Locale;

public final class MainActivity extends Activity {
    private static final String TAG = "TheVoidInput";
    TouchInput input;
    private TextView status;
    private boolean touchClick;
    private static native String nativeProof();

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        input = new TouchInput(new TouchInput.Sink() {
            @Override public void key(int code, boolean down) {
                trace(String.format(Locale.ROOT, "key 0x%02x %s", code, down ? "down" : "up"));
            }
            @Override public void mouseButton(int button, boolean down) {
                trace("mouse button " + button + (down ? " down" : " up"));
            }
            @Override public void mouseMove(float x, float y, boolean relative) {
                trace(String.format(Locale.ROOT, "mouse %s %.1f %.1f", relative ? "relative" : "absolute", x, y));
            }
        });

        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setBackgroundColor(Color.rgb(16, 21, 29));
        layout.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        TextView title = new TextView(this);
        title.setText("The Void port input test — input trace only; game runtime incomplete");
        title.setTextColor(Color.WHITE);
        title.setPadding(dp(12), dp(4), dp(12), dp(4));
        layout.addView(title);

        HorizontalScrollView toolbar = new HorizontalScrollView(this);
        LinearLayout top = new LinearLayout(this);
        top.setMotionEventSplittingEnabled(true);
        addButton(top, "Body", TouchInput.B, false);
        addButton(top, "Journal", TouchInput.J, false);
        addButton(top, "Map", TouchInput.M, false);
        addButton(top, "Menu", TouchInput.ESC, false);
        addButton(top, "Skip", TouchInput.SPACE, false);
        addButton(top, "Save", TouchInput.F5, false);
        addButton(top, "Load", TouchInput.F8, false);
        addButton(top, "Capture", TouchInput.F12, false);
        addButton(top, "Time +", TouchInput.PAGE_UP, false);
        addButton(top, "Time -", TouchInput.PAGE_DOWN, false);
        addButton(top, "Time default", TouchInput.ZERO, false);
        addButton(top, "Time min", TouchInput.ONE, false);
        addButton(top, "Time avg", TouchInput.TWO, false);
        addButton(top, "Time max", TouchInput.THREE, false);
        toolbar.addView(top);
        layout.addView(toolbar);

        layout.addView(new TouchSurface(this), new LinearLayout.LayoutParams(-1, 0, 1));
        LinearLayout bottom = new LinearLayout(this);
        bottom.setMotionEventSplittingEnabled(true);
        addButton(bottom, "Run", TouchInput.SHIFT, false);
        addButton(bottom, "Jump", TouchInput.SPACE, false);
        addButton(bottom, "Use", 1, true);
        addButton(bottom, "Paint (hold)", TouchInput.CTRL, false);
        layout.addView(bottom);
        status = new TextView(this);
        status.setTextColor(Color.LTGRAY);
        status.setPadding(dp(12), dp(3), dp(12), dp(3));
        status.setText("Drag left: move. Drag right: look. Hold Paint + drag right: drawing.");
        layout.addView(status);
        setContentView(layout);
        layout.requestApplyInsets();
        try {
            System.loadLibrary("voidprobe");
            String proof = nativeProof();
            Log.i("TheVoidNative", proof);
            title.append("\n" + proof);
        } catch (UnsatisfiedLinkError error) {
            Log.i("TheVoidNative", "Native lifted proof not bundled: " + error.getMessage());
        }
        Log.i(TAG, "ready " + android.os.Build.MODEL + " API " + android.os.Build.VERSION.SDK_INT);
    }

    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private void trace(String event) {
        Log.i(TAG, event);
        if (status != null) status.setText(event);
    }

    private void addButton(LinearLayout row, String label, int code, boolean mouse) {
        Button button = new Button(this);
        button.setText(label);
        button.setContentDescription(label + (mouse ? ", right mouse button" : ", original key"));
        button.setMinHeight(dp(48));
        button.setOnTouchListener((view, event) -> {
            int action = event.getActionMasked(), index = event.getActionIndex();
            int id = event.getPointerId(index);
            if (action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_POINTER_DOWN) {
                input.button(id, code, mouse);
                button.setPressed(true);
            } else if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_POINTER_UP) {
                input.release(id);
                button.setPressed(false);
                touchClick = true;
                view.performClick();
                touchClick = false;
            } else if (action == MotionEvent.ACTION_CANCEL) {
                for (int i = 0; i < event.getPointerCount(); i++) input.release(event.getPointerId(i));
                button.setPressed(false);
            }
            return true;
        });
        button.setOnClickListener(view -> { if (!touchClick) input.click(code, mouse); });
        row.addView(button, new LinearLayout.LayoutParams(-2, dp(52)));
    }

    @Override protected void onPause() {
        input.cancel();
        Log.i(TAG, "pause released held=" + input.heldCount() + " pointers=" + input.pointerCount());
        super.onPause();
    }

    @Override public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (!hasFocus && input != null) input.cancel();
    }

    private final class TouchSurface extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        TouchSurface(Context context) {
            super(context);
            setContentDescription("Movement and camera input test. Left area: movement joystick. Right area: camera or paint drag.");
            setFocusable(true);
            setClickable(true);
        }

        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            float split = getWidth() * 0.32f;
            paint.setColor(Color.rgb(43, 66, 70));
            canvas.drawRect(0, 0, split, getHeight(), paint);
            paint.setColor(Color.rgb(56, 41, 70));
            canvas.drawRect(split, 0, getWidth(), getHeight(), paint);
            paint.setColor(Color.WHITE);
            paint.setTextSize(dp(17));
            canvas.drawText("MOVE", dp(20), dp(28), paint);
            canvas.drawText("LOOK / PAINT", split + dp(20), dp(28), paint);
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(dp(2));
            canvas.drawCircle(split / 2, getHeight() / 2f, dp(48), paint);
            paint.setStyle(Paint.Style.FILL);
            paint.setTextSize(dp(12));
            canvas.drawText("Joystick starts where your finger lands", dp(12), getHeight() - dp(12), paint);
        }

        @Override public boolean onTouchEvent(MotionEvent event) {
            int action = event.getActionMasked(), index = event.getActionIndex();
            int id = event.getPointerId(index);
            if (action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_POINTER_DOWN) {
                float x = event.getX(index), y = event.getY(index);
                if (x < getWidth() * 0.32f) input.joystick(id, x, y, dp(48));
                else input.look(id, x, y);
            } else if (action == MotionEvent.ACTION_MOVE) {
                for (int history = 0; history < event.getHistorySize(); history++) {
                    for (int i = 0; i < event.getPointerCount(); i++)
                        input.move(event.getPointerId(i), event.getHistoricalX(i, history), event.getHistoricalY(i, history));
                }
                for (int i = 0; i < event.getPointerCount(); i++)
                    input.move(event.getPointerId(i), event.getX(i), event.getY(i));
            } else if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_POINTER_UP) {
                input.move(id, event.getX(index), event.getY(index));
                input.release(id);
                performClick();
            } else if (action == MotionEvent.ACTION_CANCEL) input.cancel();
            return true;
        }

        @Override public boolean performClick() { return super.performClick(); }
    }
}
