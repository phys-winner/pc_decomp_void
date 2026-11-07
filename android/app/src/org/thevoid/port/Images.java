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
    static File dir(Context c, File base, String images, File game) throws IOException {
        File shared = new File(base, images);
        if (new File(shared, "Game.exe").isFile() && complete(c, images, shared)) return shared;
        File own = new File(c.getFilesDir(), images);
        install(c, images, own, game);
        return own;
    }

    static final class OriginalRequired extends IOException {
        OriginalRequired(String name) { super(name); }
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

    /** Whether a pushed folder has every image this APK carries: one pushed
     *  before an image was added (d3dx9_36.dll, the shader compiler) would
     *  hide it, so such a folder gives way to the APK's own copy. */
    private static boolean complete(Context c, String images, File shared) {
        String index;
        try {
            index = new String(read(c, images + "/index.txt"), StandardCharsets.UTF_8);
        } catch (IOException e) {
            return true;   /* a build without images: the pushed folder is all there is */
        }
        for (String line : index.split("\n")) {
            String name = line.trim().split(" ")[0];
            if (name.isEmpty() || name.contains("/") || new File(shared, name).isFile()) continue;
            android.util.Log.w("TheVoid", "images: " + shared + " lacks " + name + ", the APK's are used");
            return false;
        }
        return true;
    }

    /* The optional fourth field names an apk: asset or a game: original.
     * Original bytes are checked before replacing a previously installed image. */
    private static void install(Context c, String images, File dir, File game) throws IOException {
        String index = new String(read(c, images + "/index.txt"), StandardCharsets.UTF_8);
        File noted = new File(dir, "apk.txt");
        if (noted.isFile() && new String(readFile(noted), StandardCharsets.UTF_8).equals(index)) return;
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("cannot create " + dir);
        int copied = 0;
        for (String line : index.split("\n")) {
            String[] entry = line.trim().split(" ");
            String name = entry[0];
            if (name.isEmpty() || name.contains("/")) continue;
            File part = new File(dir, name + ".part"), out = new File(dir, name);
            if (matches(out, entry)) continue;
            String reference = entry.length == 4 ? entry[3] : "apk:" + images + "/" + name;
            File original = null;
            boolean fromGame = reference.startsWith("game:");
            if (fromGame) {
                original = game;
                for (String component : reference.substring(5).split("/")) {
                    if (component.isEmpty() || component.equals(".") || component.equals("..") || component.contains("\\"))
                        throw new IOException("invalid image source");
                    original = Unpacker.child(original, component);
                }
                if (original == null || !original.isFile() || original.length() != Long.parseLong(entry[1]))
                    throw new OriginalRequired(reference.substring(5));
            } else if (!reference.startsWith("apk:")) {
                throw new IOException("invalid image source");
            }
            try (InputStream in = fromGame ? new java.io.FileInputStream(original)
                    : c.getAssets().open(reference.substring(4)); FileOutputStream o = new FileOutputStream(part)) {
                byte[] buffer = new byte[1 << 16];
                for (int n; (n = in.read(buffer)) > 0;) o.write(buffer, 0, n);
            }
            if (!matches(part, entry)) {
                part.delete();
                if (fromGame) throw new OriginalRequired(reference.substring(5));
                throw new IOException("invalid image: " + name);
            }
            if (!part.renameTo(out)) throw new IOException("cannot write " + out);
            ++copied;
        }
        try (FileOutputStream o = new FileOutputStream(noted)) { o.write(index.getBytes(StandardCharsets.UTF_8)); }
        android.util.Log.i("TheVoid", "images: " + copied + " copied from the APK to " + dir);
    }

    private static boolean matches(File file, String[] entry) throws IOException {
        if (!file.isFile() || file.length() != Long.parseLong(entry[1])) return false;
        try {
            byte[] digest = java.security.MessageDigest.getInstance("SHA-256").digest(readFile(file));
            StringBuilder hex = new StringBuilder();
            for (byte value : digest) hex.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
            return hex.toString().equals(entry[2]);
        } catch (java.security.NoSuchAlgorithmException e) { throw new AssertionError(e); }
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
