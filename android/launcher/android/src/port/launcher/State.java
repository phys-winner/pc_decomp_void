package port.launcher;

import android.content.Context;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.channels.FileLock;
import java.util.Properties;

/** Small property files in files/launcher, shared by the launcher's process and the game's. Every
 *  read is fresh from disk and every write goes through a synced temporary file and a rename, under
 *  a file lock: SharedPreferences give neither across processes. */
final class State {
    /** The player's choices: part folders, renderer, options, language, picker preference. */
    static final String CHOICES = "choices";
    /** Updates: the last check and what it found. */
    static final String UPDATE = "update";
    /** A distribution's starts ("launch-<id>"): build, renderer, whether the first frame came. */
    static String launch(String distribution) { return "launch-" + distribution; }

    interface Change { void apply(Properties values); }

    private State() { }

    static File folder(Context context) {
        File dir = new File(context.getFilesDir(), "launcher");
        if (!dir.isDirectory()) dir.mkdirs();
        return dir;
    }

    static Properties read(Context context, String name) { return read(folder(context), name); }

    static Properties read(File dir, String name) {
        Properties values = new Properties();
        File file = new File(dir, name + ".properties");
        if (file.isFile()) {
            try (FileInputStream in = new FileInputStream(file)) {
                values.load(in);
            } catch (IOException | IllegalArgumentException e) {
                Work.warn("state " + name + ": " + e, e);
            }
        }
        return values;
    }

    /** Read, change and write back under the lock; false if it could not be written. */
    static boolean update(Context context, String name, Change change) { return update(folder(context), name, change); }

    static synchronized boolean update(File dir, String name, Change change) {
        try (RandomAccessFile lockFile = new RandomAccessFile(new File(dir, name + ".lock"), "rw");
             FileLock lock = lockFile.getChannel().lock()) {
            Properties values = read(dir, name);
            change.apply(values);
            File part = new File(dir, name + ".tmp"), file = new File(dir, name + ".properties");
            try (FileOutputStream out = new FileOutputStream(part)) {
                values.store(out, null);
                out.getFD().sync();
            }
            /* Android renames over the old file atomically; Windows (the PC checks) cannot. */
            if (!part.renameTo(file) && !(File.separatorChar == '\\' && file.delete() && part.renameTo(file)))
                throw new IOException("cannot replace " + file);
            return true;
        } catch (IOException e) {
            Work.warn("state " + name + ": " + e, e);
            return false;
        }
    }

    static boolean put(Context context, String name, String key, String value) {
        return update(context, name, values -> {
            if (value == null) values.remove(key); else values.setProperty(key, value);
        });
    }

    static String get(Context context, String name, String key, String fallback) {
        return read(context, name).getProperty(key, fallback);
    }

    static long getLong(Properties values, String key, long fallback) {
        try { return Long.parseLong(values.getProperty(key, "")); }
        catch (NumberFormatException e) { return fallback; }
    }
}
