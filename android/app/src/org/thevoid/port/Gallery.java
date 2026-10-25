package org.thevoid.port;

import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.media.MediaScannerConnection;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.util.Log;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** The game's screenshots go to the phone's gallery too (Pictures/The Void),
 *  named by the time they were taken; the game's own copy stays where it
 *  said it saved it. */
final class Gallery {
    private static final String ALBUM = "The Void";

    private Gallery() { }

    static void add(Context context, String path) {
        Context c = context.getApplicationContext();
        new Thread(() -> {
            File src = new File(path);
            String lower = path.toLowerCase(Locale.ROOT);
            String ext = lower.endsWith(".jpg") ? ".jpg" : lower.endsWith(".bmp") ? ".bmp" : ".png";
            String mime = ext.equals(".jpg") ? "image/jpeg" : ext.equals(".bmp") ? "image/bmp" : "image/png";
            String name = "TheVoid_" + new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.ROOT).format(new Date()) + ext;
            try {
                if (Build.VERSION.SDK_INT >= 29) {
                    ContentResolver r = c.getContentResolver();
                    ContentValues v = new ContentValues();
                    v.put(MediaStore.Images.Media.DISPLAY_NAME, name);
                    v.put(MediaStore.Images.Media.MIME_TYPE, mime);
                    v.put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/" + ALBUM);
                    v.put(MediaStore.Images.Media.IS_PENDING, 1);
                    Uri uri = r.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, v);
                    if (uri == null) throw new java.io.IOException("no gallery entry");
                    try (InputStream in = new FileInputStream(src); OutputStream out = r.openOutputStream(uri)) {
                        copy(in, out);
                    } catch (Exception e) {
                        r.delete(uri, null, null);
                        throw e;
                    }
                    v.clear();
                    v.put(MediaStore.Images.Media.IS_PENDING, 0);
                    r.update(uri, v, null, null);
                } else {
                    File dir = new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES), ALBUM);
                    if (!dir.isDirectory() && !dir.mkdirs()) throw new java.io.IOException("no " + dir);
                    File dst = new File(dir, name);
                    try (InputStream in = new FileInputStream(src); OutputStream out = new FileOutputStream(dst)) {
                        copy(in, out);
                    }
                    MediaScannerConnection.scanFile(c, new String[] {dst.getPath()}, new String[] {mime}, null);
                }
                Log.i("TheVoid", "picture: in the gallery as " + ALBUM + "/" + name);
            } catch (Exception e) {
                Log.w("TheVoid", "picture: not put in the gallery: " + e);
            }
        }, "gallery").start();
    }

    private static void copy(InputStream in, OutputStream out) throws java.io.IOException {
        byte[] buffer = new byte[1 << 16];
        for (int n; (n = in.read(buffer)) > 0;) out.write(buffer, 0, n);
    }
}
