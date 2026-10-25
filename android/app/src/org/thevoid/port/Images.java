package org.thevoid.port;

import android.content.Context;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/** The PE images the lifted code runs on: the release's Game.exe and DLLs
 *  as they were lifted (rebased, the recovered Game.exe). tools/
 *  push_game_data.py puts them in /sdcard/TheVoid/<images>, which stays
 *  first (development); the full APK carries them as assets/<images>
 *  (tools/build_game_apk.py), copied into the app's own files once per
 *  APK, so a phone needs only the game's own files. */
final class Images {
    private Images() { }

    /** The folder the game reads the images from (nativeStart's images). */
    static File dir(Context c, File base, String images) {
        File shared = new File(base, images);
        if (new File(shared, "Game.exe").isFile()) return shared;
        File own = new File(c.getFilesDir(), images);
        try {
            install(c, images, own);
        } catch (IOException e) {
            android.util.Log.w("TheVoid", "images: " + e);
        }
        return own;
    }

    /** Whether the game will find them (the launcher asks before it starts the game). */
    static boolean available(Context c, File base, String images) {
        if (new File(base, images + "/Game.exe").isFile() || new File(c.getFilesDir(), images + "/Game.exe").isFile())
            return true;
        try (InputStream in = c.getAssets().open(images + "/index.txt")) {
            return true;
        } catch (IOException e) {
            return false;
        }
    }

    /* assets/<images>/index.txt: "name size sha256" a line; the copy notes
     * the index it was made from. */
    private static void install(Context c, String images, File dir) throws IOException {
        String index = new String(read(c, images + "/index.txt"), StandardCharsets.UTF_8);
        File noted = new File(dir, "apk.txt");
        if (noted.isFile() && new String(readFile(noted), StandardCharsets.UTF_8).equals(index)) return;
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("cannot create " + dir);
        int copied = 0;
        for (String line : index.split("\n")) {
            String name = line.trim().split(" ")[0];
            if (name.isEmpty() || name.contains("/")) continue;
            File part = new File(dir, name + ".part"), out = new File(dir, name);
            try (InputStream in = c.getAssets().open(images + "/" + name); FileOutputStream o = new FileOutputStream(part)) {
                byte[] buffer = new byte[1 << 16];
                for (int n; (n = in.read(buffer)) > 0;) o.write(buffer, 0, n);
            }
            if (!part.renameTo(out)) throw new IOException("cannot write " + out);
            ++copied;
        }
        try (FileOutputStream o = new FileOutputStream(noted)) { o.write(index.getBytes(StandardCharsets.UTF_8)); }
        android.util.Log.i("TheVoid", "images: " + copied + " copied from the APK to " + dir);
    }

    private static byte[] read(Context c, String asset) throws IOException {
        try (InputStream in = c.getAssets().open(asset)) {
            return drain(in);
        }
    }

    private static byte[] readFile(File f) throws IOException {
        try (InputStream in = new java.io.FileInputStream(f)) {
            return drain(in);
        }
    }

    private static byte[] drain(InputStream in) throws IOException {
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
        byte[] buffer = new byte[16384];
        for (int n; (n = in.read(buffer)) > 0;) out.write(buffer, 0, n);
        return out.toByteArray();
    }
}
