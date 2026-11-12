package port.launcher;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.os.ParcelFileDescriptor;
import android.os.storage.StorageManager;
import android.os.storage.StorageVolume;
import android.provider.DocumentsContract;
import android.provider.Settings;
import android.system.Os;
import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Storage access with a modern target SDK: game files are read by path, which needs "All files
 *  access" outside the app's own folders; the system picker's documents are mapped back to paths;
 *  storage volumes for the built-in browser; and the runtime permissions the launcher asks for. */
final class Storage {
    static final String EXTERNAL = "com.android.externalstorage.documents",
        DOWNLOADS = "com.android.providers.downloads.documents";
    /** Android 17's permission for sockets to the local network (LAN games); a string, so that a
     *  platform without it simply reports it unknown. */
    static final String LOCAL_NETWORK = "android.permission.ACCESS_LOCAL_NETWORK";
    static final String NOTIFICATIONS = "android.permission.POST_NOTIFICATIONS";

    static final class Volume {
        final File root;
        final String title;
        final boolean removable;

        Volume(File root, String title, boolean removable) {
            this.root = root;
            this.title = title;
            this.removable = removable;
        }
    }

    private Storage() { }

    static final String READ = "android.permission.READ_EXTERNAL_STORAGE", WRITE = "android.permission.WRITE_EXTERNAL_STORAGE";

    /** Whether files outside the app's own folders can be read and written by path. */
    static boolean allFiles(Context context) {
        if (Build.VERSION.SDK_INT >= 30) return Environment.isExternalStorageManager();
        return context.checkSelfPermission(WRITE) == PackageManager.PERMISSION_GRANTED;
    }

    /** Android 11+: the system's "All files access" page. Android 8-10: the storage permissions
     *  (tools/launcher.py declares them up to API 29); once refused for good ("Don't ask again") the
     *  system no longer shows its dialog, so the app's own settings page opens instead. */
    static void requestAllFiles(Activity activity, int request) {
        if (Build.VERSION.SDK_INT < 30) {
            boolean asked = "1".equals(State.get(activity, State.CHOICES, "asked.storage", "0"));
            if (asked && !allFiles(activity) && !activity.shouldShowRequestPermissionRationale(WRITE)) {
                appSettings(activity);
                return;
            }
            State.put(activity, State.CHOICES, "asked.storage", "1");
            activity.requestPermissions(new String[] {READ, WRITE}, request);
            return;
        }
        try {
            activity.startActivity(new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                Uri.parse("package:" + activity.getPackageName())));
        } catch (ActivityNotFoundException e) {
            activity.startActivity(new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION));
        }
    }

    /** The app's page in the system settings (permissions). */
    static void appSettings(Activity activity) {
        try {
            activity.startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                Uri.fromParts("package", activity.getPackageName(), null)));
        } catch (ActivityNotFoundException e) {
            android.util.Log.w("Launcher", "app settings: " + e);
        }
    }

    /** A path in the app's own folders needs no permission. */
    static boolean own(Context context, File path) {
        String p = path.getAbsolutePath();
        List<File> owned = new ArrayList<>();
        owned.add(context.getFilesDir());
        owned.add(context.getCacheDir());
        for (File f : context.getExternalFilesDirs(null)) if (f != null) owned.add(f.getParentFile());
        for (File f : owned) if (f != null && (p.equals(f.getAbsolutePath()) || p.startsWith(f.getAbsolutePath() + "/"))) return true;
        return false;
    }

    /** Whether the platform knows a permission: Android 17's local network one, for example. */
    static boolean known(Context context, String permission) {
        try {
            context.getPackageManager().getPermissionInfo(permission, 0);
            return true;
        } catch (PackageManager.NameNotFoundException e) {
            return false;
        }
    }

    static boolean granted(Context context, String permission) {
        return !known(context, permission) || context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED;
    }

    static List<Volume> volumes(Context context) {
        List<Volume> result = new ArrayList<>();
        StorageManager manager = (StorageManager) context.getSystemService(Context.STORAGE_SERVICE);
        if (manager != null) {
            for (StorageVolume volume : manager.getStorageVolumes()) {
                File root = Build.VERSION.SDK_INT >= 30 ? volume.getDirectory()
                    : volume.isPrimary() ? Environment.getExternalStorageDirectory()
                    : volume.getUuid() != null ? new File("/storage", volume.getUuid()) : null;
                if (root == null || !Environment.MEDIA_MOUNTED.equals(volume.getState())) continue;
                result.add(new Volume(root, volume.isPrimary() ? Texts.t(context, Texts.INTERNAL)
                    : volume.getDescription(context), volume.isRemovable()));
            }
        }
        if (result.isEmpty()) result.add(new Volume(Environment.getExternalStorageDirectory(), Texts.t(context, Texts.INTERNAL), false));
        return result;
    }

    static long free(File path) {
        for (File at = path; at != null; at = at.getParentFile()) if (at.isDirectory()) return at.getUsableSpace();
        return 0;
    }

    /* ----------------------------------------------- system picker → path */

    /** A folder chosen in the system's picker as a path (game files are read by path). */
    static File treePath(Uri tree) {
        try {
            return documentPath(tree.getAuthority(), DocumentsContract.getTreeDocumentId(tree));
        } catch (RuntimeException e) {
            return null;
        }
    }

    static File documentPath(String authority, String id) {
        if (id == null) return null;
        if (DOWNLOADS.equals(authority) && id.startsWith("raw:")) return new File(id.substring(4));
        if (!EXTERNAL.equals(authority)) return null;
        int colon = id.indexOf(':');
        String volume = colon < 0 ? id : id.substring(0, colon), path = colon < 0 ? "" : id.substring(colon + 1);
        File root = volume.equals("primary") ? Environment.getExternalStorageDirectory()
            : volume.equals("home") ? new File(Environment.getExternalStorageDirectory(), Environment.DIRECTORY_DOCUMENTS)
            : new File("/storage", volume);
        return path.isEmpty() ? root : new File(root, path);
    }

    /** The picker's starting folder for a path in shared storage; null elsewhere. */
    static Uri documentOf(File dir) {
        String storage = Environment.getExternalStorageDirectory().getPath(), p = dir.getPath(), id;
        if (p.equals(storage)) {
            id = "primary:";
        } else if (p.startsWith(storage + "/")) {
            id = "primary:" + p.substring(storage.length() + 1);
        } else {
            Matcher m = Pattern.compile("^/storage/([^/]+)(?:/(.*))?$").matcher(p);
            if (!m.matches() || m.group(1).equals("emulated") || m.group(1).equals("self")) return null;
            id = m.group(1) + ":" + (m.group(2) != null ? m.group(2) : "");
        }
        return DocumentsContract.buildDocumentUri(EXTERNAL, id);
    }

    /** A picked document's path, when it is a file of this device's storage of the same size as its
     *  descriptor (the provider's id, else where the descriptor points); null otherwise. */
    static File fileOf(Uri uri, ParcelFileDescriptor fd) {
        long size = -1;
        try {
            size = Os.fstat(fd.getFileDescriptor()).st_size;
        } catch (Exception e) {
            /* compared only when known */
        }
        List<String> candidates = new ArrayList<>();
        try {
            File f = documentPath(uri.getAuthority(), DocumentsContract.getDocumentId(uri));
            if (f != null) candidates.add(f.getPath());
        } catch (RuntimeException e) {
            /* not a document */
        }
        try {
            String link = Os.readlink("/proc/self/fd/" + fd.getFd());
            candidates.add(link);
            Matcher m;
            if ((m = Pattern.compile("^/data/media/(\\d+)/(.*)$").matcher(link)).matches())
                candidates.add("/storage/emulated/" + m.group(1) + "/" + m.group(2));
            if ((m = Pattern.compile("^/mnt/[a-z_]+/\\d+/emulated/(\\d+)/(.*)$").matcher(link)).matches())
                candidates.add("/storage/emulated/" + m.group(1) + "/" + m.group(2));
            if ((m = Pattern.compile("^/mnt/[a-z_]+/\\d+/([0-9A-Fa-f]{4}-[0-9A-Fa-f]{4})/(.*)$").matcher(link)).matches())
                candidates.add("/storage/" + m.group(1) + "/" + m.group(2));
            if ((m = Pattern.compile("^/mnt/media_rw/([^/]+)/(.*)$").matcher(link)).matches())
                candidates.add("/storage/" + m.group(1) + "/" + m.group(2));
        } catch (Exception e) {
            /* no such link */
        }
        for (String c : candidates) {
            File f = new File(c);
            if (f.isFile() && (size < 0 || f.length() == size)) return f;
        }
        return null;
    }

    /** Whether the descriptor can be read at any offset: a cloud provider's pipe cannot back a game. */
    static boolean seekable(ParcelFileDescriptor fd) {
        try {
            return Os.lseek(fd.getFileDescriptor(), 0, android.system.OsConstants.SEEK_END) >= 0;
        } catch (Exception e) {
            return false;
        }
    }
}
