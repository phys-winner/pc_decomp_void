package org.thevoid.port;

import android.content.Context;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InterruptedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/** The D3DX shader cache made on the PC (tools/shader_service.py, carried in
 *  the APK's assets/shadercache): the device cannot compile HLSL, and a
 *  shader the cache lacks stops the game (android/host/d3dx9.c), so
 *  one app-private copy is shared by all profiles. Writable per-profile
 *  shadercache files still override these bundled results in d3dx9.c.
 *  The bundled manifest also verifies and repairs interrupted or corrupt copies. */
final class ShaderCache {
    private ShaderCache() { }

    interface Progress { void update(int completed, int total); }

    /** Shader generation can first occur on entering a scene, after the main menu. */
    static final class NativeWork {
        private long frame = -1, progress, frameAt, workAt;
        private boolean worked, visible;
        private int movingFrames;
        long beganAt;

        void reset() { frame = -1; worked = visible = false; movingFrames = 0; }

        boolean settled(long now) { return movingFrames >= 2 && now - workAt >= 600; }

        boolean update(long now, long currentFrame, long currentProgress, boolean video) {
            if (frame == -1) {
                frame = currentFrame; progress = currentProgress;
                frameAt = workAt = now;
                return false;
            }
            boolean moved = currentFrame != frame;
            if (moved) {
                frame = currentFrame; frameAt = now;
                movingFrames = Math.min(2, movingFrames + 1);
                if (!visible) worked = false;
            } else movingFrames = 0;
            if (currentProgress != progress) {
                progress = currentProgress; workAt = now;
                if (!moved) worked = true;
            }
            if (video && moved) { visible = worked = false; }
            if (!visible && worked && now - frameAt >= 800) {
                visible = true; beganAt = frameAt;
            }
            /* Keep the badge through one slow compile, even while its counter is still. */
            if (visible && settled(now)) visible = worked = false;
            return visible;
        }
    }

    static void install(Context c, File appFiles, Progress progress) throws IOException {
        installWarmup(c, appFiles);
        installPack(c, appFiles);
        File dir = new File(appFiles, "shadercache");
        String list = new String(read(c, "shadercache/index.txt"), StandardCharsets.UTF_8);
        java.util.List<String[]> names = new java.util.ArrayList<>();
        for (String line : list.split("\n")) {
            String name = line.trim();
            if (name.isEmpty()) continue;
            String[] entry = name.split("\\s+");
            if (!entry[0].matches("[0-9a-f]{16}\\.(bin|err)")
                || entry.length != 1 && entry.length != 3 && entry.length != 4)
                throw new IOException("invalid shader cache entry: " + name);
            if (entry.length >= 3) {
                try {
                    if (Long.parseLong(entry[1]) <= 0 || !entry[2].matches("[0-9a-f]{64}"))
                        throw new NumberFormatException();
                } catch (NumberFormatException e) { throw new IOException("invalid shader cache metadata: " + name, e); }
            }
            /* A fourth field names the shipped content this one duplicates: no
             * asset of its own, a hard link to that name on the device. */
            if (entry.length == 4 && (!entry[3].matches("[0-9a-f]{16}\\.(bin|err)") || entry[3].equals(entry[0])))
                throw new IOException("invalid shader cache alias: " + name);
            names.add(entry);
        }
        File noted = new File(dir, "apk");
        String version = "4:" + sha256(list.getBytes(StandardCharsets.UTF_8));
        /* The note names this APK's list and the stamp of the copies it
         * verified: while no copy was written, removed or replaced since,
         * the copies need not be hashed again (seconds at each start). */
        if (stamped(noted, version, dir, names)) {
            progress.update(names.size(), names.size());
            return;
        }
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("cannot create " + dir);
        int added = 0, completed = 0;
        progress.update(0, names.size());
        for (String[] entry : names) {   // the shipped contents first, so a duplicate can link to one
            if (entry.length == 4) continue;
            if (Thread.currentThread().isInterrupted()) throw new InterruptedIOException("shader cache preparation cancelled");
            String name = entry[0];
            File out = new File(dir, name);
            if (!matches(out, entry)) {
                byte[] data = read(c, "shadercache/" + name);
                if (data.length == 0 || entry.length == 3 && (data.length != Long.parseLong(entry[1]) || !sha256(data).equals(entry[2])))
                    throw new IOException("invalid bundled shader cache entry: " + name);
                write(out, data);
                ++added;
            }
            progress.update(++completed, names.size());
        }
        for (String[] entry : names) {   // the duplicates, as links to the content they share
            if (entry.length != 4) continue;
            if (Thread.currentThread().isInterrupted()) throw new InterruptedIOException("shader cache preparation cancelled");
            File out = new File(dir, entry[0]);
            if (!matches(out, entry) && link(new File(dir, entry[3]), out)) ++added;
            progress.update(++completed, names.size());
        }
        write(noted, (version + "\n" + stamp(dir, names)).getBytes(StandardCharsets.UTF_8));
        android.util.Log.i("TheVoid", "shader cache: " + added + " of " + names.size() + " added to " + dir);
    }

    private static void installWarmup(Context c, File appFiles) throws IOException {
        String list;
        try { list = new String(read(c, "shaderwarm/index.txt"), StandardCharsets.UTF_8); }
        catch (java.io.FileNotFoundException legacy) { return; }
        File dir = new File(appFiles, "shaderwarm");
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("cannot create " + dir);
        java.util.List<String[]> entries = new java.util.ArrayList<>();
        for (String line : list.split("\n")) {
            if (line.trim().isEmpty()) continue;
            String[] entry = line.trim().split("\\s+");
            if (entry.length != 3 || !entry[0].matches("[0-9a-f]{16}\\.bin") || !entry[1].matches("[1-9][0-9]*") || !entry[2].matches("[0-9a-f]{64}"))
                throw new IOException("invalid shader warmup entry: " + line);
            try {
                if (Long.parseLong(entry[1]) > 2 * 256 * 1024 + 1040) throw new NumberFormatException();
            } catch (NumberFormatException invalid) { throw new IOException("invalid shader warmup size: " + line, invalid); }
            entries.add(entry);
        }
        File noted = new File(dir, "apk.txt");
        String version = "1:" + sha256(list.getBytes(StandardCharsets.UTF_8));
        if (stamped(noted, version, dir, entries)) return;
        for (String[] entry : entries) {
            if (Thread.currentThread().isInterrupted()) throw new InterruptedIOException("shader warmup cancelled");
            File out = new File(dir, entry[0]);
            if (!matches(out, entry)) {
                byte[] data = read(c, "shaderwarm/" + entry[0]);
                if (data.length != Long.parseLong(entry[1]) || !sha256(data).equals(entry[2])) throw new IOException("invalid shader warmup recipe: " + entry[0]);
                write(out, data);
            }
        }
        write(noted, (version + "\n" + stamp(dir, entries)).getBytes(StandardCharsets.UTF_8));
    }

    /** assets/shaderpack.bin, the pregenerated variants as one file (d3dx9.c
     *  looks there when the cache folder has no answer; the menu's warm-up
     *  leaves it alone): copied once, streamed and checked against
     *  assets/shaderpack.txt ("size sha256"); the note spares the hash later. */
    private static void installPack(Context c, File appFiles) throws IOException {
        String expected;
        try { expected = new String(read(c, "shaderpack.txt"), StandardCharsets.UTF_8).trim(); }
        catch (java.io.FileNotFoundException legacy) { return; }
        String[] meta = expected.split("\\s+");
        if (meta.length != 2 || !meta[0].matches("[0-9]+") || !meta[1].matches("[0-9a-f]{64}"))
            throw new IOException("invalid shader pack note: " + expected);
        long size = Long.parseLong(meta[0]);
        File pack = new File(appFiles, "shaderpack.bin"), noted = new File(appFiles, "shaderpack.txt");
        if (pack.isFile() && pack.length() == size && noted.isFile()
            && new String(readFile(noted), StandardCharsets.UTF_8).trim().equals(expected)) return;
        File part = new File(pack.getPath() + ".part");
        try {
            java.security.MessageDigest sha;
            try { sha = java.security.MessageDigest.getInstance("SHA-256"); }
            catch (java.security.NoSuchAlgorithmException e) { throw new IOException(e); }
            long copied = 0;
            try (InputStream in = c.getAssets().open("shaderpack.bin"); FileOutputStream out = new FileOutputStream(part)) {
                byte[] buf = new byte[1 << 16];
                int n;
                while ((n = in.read(buf)) > 0) {
                    if (Thread.currentThread().isInterrupted()) throw new InterruptedIOException("shader pack copy cancelled");
                    out.write(buf, 0, n);
                    sha.update(buf, 0, n);
                    copied += n;
                }
            }
            StringBuilder hex = new StringBuilder();
            for (byte b : sha.digest()) hex.append(String.format("%02x", b));
            if (copied != size || !hex.toString().equals(meta[1])) throw new IOException("invalid bundled shader pack");
            Files.move(part.toPath(), pack.toPath(), StandardCopyOption.REPLACE_EXISTING);
        } finally {
            part.delete();
        }
        write(noted, (expected + "\n").getBytes(StandardCharsets.UTF_8));
        android.util.Log.i("TheVoid", "shader pack: " + size + " bytes installed");
    }

    private static boolean matches(File file, String[] entry) throws IOException {
        return file.isFile() && file.length() > 0 && (entry.length == 1
            || file.length() == Long.parseLong(entry[1]) && sha256(readFile(file)).equals(entry[2]));
    }

    /** The names, sizes and modification times of the copies. */
    private static String stamp(File dir, java.util.List<String[]> entries) throws IOException {
        StringBuilder all = new StringBuilder(entries.size() * 48);
        for (String[] entry : entries) {
            if (Thread.currentThread().isInterrupted()) throw new InterruptedIOException("shader cache preparation cancelled");
            File file = new File(dir, entry[0]);
            all.append(entry[0]).append(' ').append(file.length()).append(' ').append(file.lastModified()).append('\n');
        }
        return sha256(all.toString().getBytes(StandardCharsets.UTF_8));
    }

    /** The note names this list and the copies are as it found them. */
    private static boolean stamped(File noted, String version, File dir, java.util.List<String[]> entries) throws IOException {
        if (!noted.isFile()) return false;
        String[] note = new String(readFile(noted), StandardCharsets.UTF_8).split("\n");
        return note.length == 2 && note[0].equals(version) && note[1].equals(stamp(dir, entries));
    }

    private static String sha256(byte[] bytes) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(bytes);
            StringBuilder hex = new StringBuilder(64);
            for (byte value : digest) hex.append(Character.forDigit((value & 255) >> 4, 16)).append(Character.forDigit(value & 15, 16));
            return hex.toString();
        } catch (NoSuchAlgorithmException e) { throw new AssertionError(e); }
    }

    /** A duplicate shader as a relative symbolic link to the one copy of its
     *  content, so it costs only a directory entry (Android forbids hard links
     *  in app storage but allows symlinks, and the native reader follows them);
     *  a plain copy where even a symlink is refused. The link names its target
     *  in the same directory, so it survives the content being repaired in
     *  place, and is made through a .part name so a reader never sees it half
     *  made. Returns whether the link or copy was made. */
    private static boolean link(File content, File out) throws IOException {
        if (!content.isFile()) throw new IOException("missing shader cache content: " + content.getName());
        File part = new File(out.getPath() + ".part");
        part.delete();
        try {
            try {
                Files.createSymbolicLink(part.toPath(), content.toPath().getFileName());
            } catch (UnsupportedOperationException | IOException noLink) {
                write(out, readFile(content));
                return true;
            }
            Files.move(part.toPath(), out.toPath(), StandardCopyOption.REPLACE_EXISTING);
            return true;
        } finally {
            part.delete();
        }
    }

    private static void write(File out, byte[] data) throws IOException {
        File part = new File(out.getPath() + ".part");
        try {
            try (FileOutputStream o = new FileOutputStream(part)) { o.write(data); }
            Files.move(part.toPath(), out.toPath(), StandardCopyOption.REPLACE_EXISTING);
        } finally {
            part.delete();
        }
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
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[16384];
        int n;
        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        return out.toByteArray();
    }
}
