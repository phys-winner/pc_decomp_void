package org.thevoid.port;

import android.content.Context;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.RandomAccessFile;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONObject;

/** The port's patched game files (tools/patch_scripts.py, carried in the
 *  APK's assets/overrides): scripts from Scripts.vfs, string tables from
 *  Properties.vfs, repaired scene/audio assets, and loose data files (actions.xml). Each patch is made from one release's original, so a
 *  file goes into <data>/overrides (android/host/files.c serves it to the
 *  game as a loose file) only when the running release's original has the
 *  same SHA-256; overrides of other releases are removed. */
final class ScriptOverrides {
    private ScriptOverrides() { }

    /** Returns the paths installed (e.g. "Scripts\\ui\\main_menu.bin"). */
    static Set<String> install(Context c, File gameDir, File dataDir) {
        Set<String> installed = new HashSet<>();
        File root = new File(dataDir, "overrides");
        try {
            JSONArray index = new JSONArray(new String(asset(c, "overrides/index.json"), "UTF-8"));
            /* The archive of each path's first folder: Scripts\... in Scripts.vfs. */
            Map<String, Map<String, long[]>> archives = new HashMap<>();
            Map<String, String> originals = new HashMap<>();   /* path -> the release's SHA-256 */
            Set<String> paths = new HashSet<>(), sources = new HashSet<>();
            for (int i = 0; i < index.length(); ++i) {
                JSONObject e = index.getJSONObject(i);
                paths.add(e.getString("path"));
                sources.add(e.optString("source", e.getString("path")));
            }
            /* A new file made from one of the release's (a larger image) is
             * keyed by that file, its "source". */
            for (String path : sources) {
                int slash = path.indexOf('\\');
                if (slash < 0) {   /* a loose file of the data folder */
                    File loose = file(new File(gameDir, "data"), path);
                    if (loose.isFile()) originals.put(path, sha256(readAll(loose)));
                    continue;
                }
                if (slash == 0) continue;
                File loose = file(new File(gameDir, "data"), path);
                if (loose.isFile()) {
                    originals.put(path, sha256(readAll(loose)));
                    continue;
                }
                String top = path.substring(0, slash).toLowerCase(Locale.ROOT);
                File vfs = file(new File(gameDir, "data"), top + ".vfs");
                Map<String, long[]> dir = archives.get(top);
                if (dir == null) {
                    dir = vfs.isFile() ? directory(vfs, top) : new HashMap<>();
                    archives.put(top, dir);
                }
                long[] at = entry(dir, top + path.substring(slash));
                if (at != null) originals.put(path, sha256(read(vfs, at[0], (int) at[1])));
            }
            for (int i = 0; i < index.length(); ++i) {
                JSONObject e = index.getJSONObject(i);
                String path = e.getString("path");
                if (!e.getString("original_sha256").equals(originals.get(e.optString("source", path)))) continue;
                File out = new File(root, path.replace('\\', '/'));
                byte[] patched = asset(c, "overrides/" + e.getString("file"));
                if (!out.isFile() || !sha256(readAll(out)).equals(sha256(patched))) {
                    out.getParentFile().mkdirs();
                    try (FileOutputStream o = new FileOutputStream(out)) { o.write(patched); }
                }
                installed.add(path);
            }
            for (String path : paths) {
                File out = new File(root, path.replace('\\', '/'));
                if (!installed.contains(path) && out.exists()) out.delete();
            }
        } catch (Exception e) {
            android.util.Log.w("TheVoid", "script overrides: " + e);
        }
        android.util.Log.i("TheVoid", "script overrides for this release: " + installed);
        return installed;
    }

    /** A file of dir by case-insensitive name. */
    static File file(File dir, String path) {
        for (String part : path.replace('\\', '/').split("/")) {
            String found = part;
            String[] names = dir.list();
            if (names != null) for (String name : names) if (name.equalsIgnoreCase(part)) { found = name; break; }
            dir = new File(dir, found);
        }
        return dir;
    }

    /** Exact archive spelling wins; legacy paths still fall back without case. */
    static long[] entry(Map<String, long[]> directory, String path) {
        long[] exact = directory.get(path);
        if (exact != null) return exact;
        for (Map.Entry<String, long[]> item : directory.entrySet())
            if (item.getKey().equalsIgnoreCase(path)) return item.getValue();
        return null;
    }

    /** An LP2C container's directory: "<root>\dir\file" -> {offset, size}. */
    static Map<String, long[]> directory(File vfs, String root) throws IOException {
        Map<String, long[]> map = new HashMap<>();
        try (RandomAccessFile f = new RandomAccessFile(vfs, "r")) {
            byte[] magic = new byte[4];
            f.readFully(magic);
            if (!new String(magic, "ISO-8859-1").equals("LP2C")) throw new IOException(vfs + ": not LP2C");
            int dirs = le(f), files = le(f);
            level(f, root, dirs, files, map, 0);
        }
        return map;
    }

    private static void level(RandomAccessFile f, String path, int dirs, int files, Map<String, long[]> map, int depth)
            throws IOException {
        if (depth > 32) throw new IOException("too deep");
        for (int i = 0; i < files; ++i) {
            String name = name(f);
            int[] meta = new int[6];
            for (int k = 0; k < 6; ++k) meta[k] = le(f);
            map.put(path + "\\" + name, new long[] {meta[2] & 0xFFFFFFFFL, meta[0] & 0xFFFFFFFFL});
        }
        for (int i = 0; i < dirs; ++i) {
            String name = name(f);
            int sub = le(f), subFiles = le(f);
            level(f, path + "\\" + name, sub, subFiles, map, depth + 1);
        }
    }

    private static String name(RandomAccessFile f) throws IOException {
        int n = f.readUnsignedByte();
        byte[] b = new byte[n];
        f.readFully(b);
        return new String(b, "ISO-8859-1");
    }

    private static int le(RandomAccessFile f) throws IOException {
        int a = f.readUnsignedByte(), b = f.readUnsignedByte(), c = f.readUnsignedByte(), d = f.readUnsignedByte();
        return a | b << 8 | c << 16 | d << 24;
    }

    private static byte[] read(File f, long offset, int size) throws IOException {
        try (RandomAccessFile r = new RandomAccessFile(f, "r")) {
            byte[] b = new byte[size];
            r.seek(offset);
            r.readFully(b);
            return b;
        }
    }

    private static byte[] readAll(File f) throws IOException { return read(f, 0, (int) f.length()); }

    private static byte[] asset(Context c, String name) throws IOException {
        try (InputStream in = c.getAssets().open(name)) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[65536];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            return out.toByteArray();
        }
    }

    static String sha256(byte[] data) throws Exception {
        byte[] d = MessageDigest.getInstance("SHA-256").digest(data);
        StringBuilder s = new StringBuilder();
        for (byte b : d) s.append(String.format(Locale.ROOT, "%02x", b));
        return s.toString();
    }
}
