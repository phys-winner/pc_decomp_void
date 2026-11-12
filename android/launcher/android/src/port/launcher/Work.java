package port.launcher;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import java.io.File;

/** Long work (unpacking, copying, cleaning, textures) on its own thread, kept alive by a
 *  foreground service while the launcher may be in the background. One job at a time; the
 *  launcher polls {@link #current}. */
final class Work {
    private Work() { }

    static volatile Job current;

    abstract static class Job implements Runnable {
        final int section;
        final String title;
        final File target;
        final long started = System.currentTimeMillis();
        volatile long done, total;
        volatile long itemsDone, itemsTotal;
        final WorkProgress meter = new WorkProgress();
        volatile String file = "";
        volatile boolean cancelled, finished;
        volatile Failure failure;

        Job(String title, File target) {
            this(Texts.GAME_FILES, title, target);
        }

        Job(int section, String title, File target) {
            this.section = section;
            this.title = title;
            this.target = target;
        }

        abstract void work() throws Exception;

        void check() throws Failure {
            if (cancelled) throw new Failure(Failure.CANCELLED, null);
        }

        @Override public final void run() {
            try {
                work();
            } catch (Throwable e) {
                failure = Failure.of(e);
                if (failure.code != Failure.CANCELLED) warn(title + ": " + e, e);
            } finally {
                finished = true;
            }
        }

        int permille() { return (int) (total > 0 ? Math.min(1000, done * 1000 / total) : 0); }

        String progressText(Context context) {
            return meter.describe(Texts.language(context), section == Texts.TEXTURES, done, total, itemsDone, itemsTotal);
        }
    }

    /** Starts a job unless one runs; the service keeps the process (and the CPU) up. */
    static boolean start(Context context, Job job) {
        synchronized (Work.class) {
            if (current != null && !current.finished) return false;
            current = job;
        }
        new Thread(job, "launcher-work").start();
        try {
            context.startForegroundService(new Intent(context, WorkService.class));
        } catch (RuntimeException e) {
            /* Battery savers may refuse: the job still runs while the launcher is on screen. */
            android.util.Log.w("Launcher", "work service: " + e);
        }
        return true;
    }

    /** Logs on the device; on the PC (the tests) Android's log is only a stub. */
    static void warn(String text, Throwable error) {
        try {
            android.util.Log.w("Launcher", text, error);
        } catch (RuntimeException stub) {
            System.err.println(text);
        }
    }

    static boolean busy() {
        Job job = current;
        return job != null && !job.finished;
    }

    public static final class WorkService extends Service {
        private static final String CHANNEL = "work";
        private static final int ONGOING = 1, RESULT = 2;
        private final Handler handler = new Handler(Looper.getMainLooper());
        private PowerManager.WakeLock wake;

        @Override public IBinder onBind(Intent intent) { return null; }

        @Override public int onStartCommand(Intent intent, int flags, int id) {
            channel(this);
            Job job = current;
            Notification n = notification(job, true);
            if (Build.VERSION.SDK_INT >= 29) startForeground(ONGOING, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
            else startForeground(ONGOING, n);
            if (wake == null) {
                PowerManager power = (PowerManager) getSystemService(POWER_SERVICE);
                wake = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "launcher:work");
                wake.setReferenceCounted(false);
                wake.acquire(6 * 60 * 60 * 1000L);
            }
            handler.removeCallbacks(tick);
            handler.post(tick);
            return START_NOT_STICKY;
        }

        private final Runnable tick = new Runnable() {
            @Override public void run() {
                Job job = current;
                NotificationManager manager = getSystemService(NotificationManager.class);
                if (job == null || job.finished) {
                    if (job != null && !LauncherActivity.visible && job.failure == null)
                        manager.notify(RESULT, notification(job, false));
                    if (wake != null) wake.release();
                    stopForeground(STOP_FOREGROUND_REMOVE);
                    stopSelf();
                    return;
                }
                manager.notify(ONGOING, notification(job, true));
                handler.postDelayed(this, 1000);
            }
        };

        @Override public void onDestroy() {
            handler.removeCallbacks(tick);
            if (wake != null && wake.isHeld()) wake.release();
            super.onDestroy();
        }

        static void channel(Context context) {
            NotificationManager manager = context.getSystemService(NotificationManager.class);
            if (manager.getNotificationChannel(CHANNEL) == null)
                manager.createNotificationChannel(new NotificationChannel(CHANNEL, Spec.get(context).label, NotificationManager.IMPORTANCE_LOW));
        }

        private Notification notification(Job job, boolean ongoing) {
            Intent open = new Intent(this, LauncherActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
            PendingIntent tap = PendingIntent.getActivity(this, 0, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
            Notification.Builder b = new Notification.Builder(this, CHANNEL).setContentIntent(tap).setOnlyAlertOnce(true)
                .setSmallIcon(icon(this, ongoing)).setOngoing(ongoing);
            if (job == null) return b.setContentTitle(Spec.get(this).label).build();
            b.setContentTitle(job.title);
            if (ongoing) {
                b.setContentText(job.progressText(this).replace('\n', ' '))
                    .setProgress(1000, job.permille(), job.total <= 0);
            } else {
                b.setContentText(Texts.t(this, Texts.DONE)).setAutoCancel(true);
            }
            if (Build.VERSION.SDK_INT >= 31) b.setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE);
            return b.build();
        }

        /** The port's notification icon (res/drawable/ic_notify) when it has one. */
        static int icon(Context context, boolean ongoing) {
            int own = context.getResources().getIdentifier("ic_notify", "drawable", context.getPackageName());
            return own != 0 ? own : ongoing ? android.R.drawable.stat_sys_download : android.R.drawable.stat_sys_download_done;
        }
    }
}
