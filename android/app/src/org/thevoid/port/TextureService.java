package org.thevoid.port;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;

/** Keeps the process in the foreground while the launcher converts the
 *  game's textures (minutes; in the background Android would freeze it),
 *  the progress in a notification. Textures.current is the work. */
public final class TextureService extends Service {
    private static final String CHANNEL = "textures";
    private static final int PROGRESS = 3, RESULT = 4;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private NotificationManager notifications;
    private Notification.Builder builder;

    @Override public void onCreate() {
        super.onCreate();
        notifications = getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel(CHANNEL, Launcher.text(Launcher.T_TEX_CONVERTING),
            NotificationManager.IMPORTANCE_LOW));
        notifications.cancel(RESULT);
        Intent open = new Intent(this, Launcher.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        builder = new Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle(Launcher.text(Launcher.T_TEX_CONVERTING))
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(PendingIntent.getActivity(this, 2, open,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT));
        startForeground(PROGRESS, builder.build());
        handler.post(tick);
    }

    private final Runnable tick = new Runnable() {
        @Override public void run() {
            Textures.Job job = Textures.current;
            if (job == null || job.finished) {
                if (job != null && !Launcher.visible) result(job);
                stopForeground(true);
                stopSelf();
                return;
            }
            long[] p = job.progress();
            builder.setProgress(1000, (int) (p[3] * 1000 / Math.max(1, p[4])), p[0] == Textures.SCANNING)
                .setContentText(Launcher.fmt(Launcher.T_TEX_PROGRESS, p[1], p[2]));
            notifications.notify(PROGRESS, builder.build());
            handler.postDelayed(this, 1000);
        }
    };

    /** The launcher is not on the screen: say how it ended there. */
    private void result(Textures.Job job) {
        Intent open = new Intent(this, Launcher.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        boolean ok = job.failure == null && !job.cancelled;
        notifications.notify(RESULT, new Notification.Builder(this, CHANNEL)
            .setSmallIcon(ok ? android.R.drawable.stat_sys_download_done : android.R.drawable.stat_notify_error)
            .setContentTitle(Launcher.text(ok ? Launcher.T_TEX_DONE : Launcher.T_TEX_FAILED))
            .setContentText(job.game.getPath())
            .setAutoCancel(true)
            .setContentIntent(PendingIntent.getActivity(this, 3, open,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT))
            .build());
    }

    static void cancelResult(android.content.Context c) {
        c.getSystemService(NotificationManager.class).cancel(RESULT);
    }

    @Override public int onStartCommand(Intent intent, int flags, int id) { return START_NOT_STICKY; }

    @Override public void onDestroy() {
        handler.removeCallbacks(tick);
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
