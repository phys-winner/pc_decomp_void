package port.launcher;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.SystemClock;
import android.provider.DocumentsContract;
import java.io.File;

/** Choosing a folder or a ZIP archive: the system picker (DocumentsUI) when it works, else the
 *  built-in browser. Some firmwares and debloat scripts turn "Files" off or remove it; some boxes
 *  ship a stub that closes at once. The player can also prefer the built-in browser. */
final class Pickers {
    static final int FOLDER = 1, ZIP = 2, GOG = 3;
    static final int OK = 0, DISABLED = 1, MISSING = 2;
    static final String[] DOCUMENTS_UI = {"com.google.android.documentsui", "com.android.documentsui"};
    private static final long INSTANT_CANCEL_MS = 400;

    private static long launched;
    private static int instantCancels;
    private static String disabledPackage;

    private Pickers() { }

    /** OK, DISABLED (the picker app is turned off; disabledPackage() names it) or MISSING. */
    static int state(Context context) {
        PackageManager pm = context.getPackageManager();
        disabledPackage = null;
        for (String name : DOCUMENTS_UI) {
            try {
                int setting = pm.getApplicationEnabledSetting(name);
                if (setting == PackageManager.COMPONENT_ENABLED_STATE_DISABLED
                        || setting == PackageManager.COMPONENT_ENABLED_STATE_DISABLED_USER
                        || setting == PackageManager.COMPONENT_ENABLED_STATE_DISABLED_UNTIL_USED) disabledPackage = name;
            } catch (IllegalArgumentException notInstalled) {
                /* this one is not on the device */
            }
        }
        boolean resolves = !pm.queryIntentActivities(systemIntent(FOLDER, null), 0).isEmpty()
            && !pm.queryIntentActivities(systemIntent(ZIP, null), 0).isEmpty();
        if (resolves) return OK;
        return disabledPackage != null ? DISABLED : MISSING;
    }

    static String disabledPackage() { return disabledPackage; }

    static boolean preferBuiltIn(Context context) {
        return "1".equals(State.get(context, State.CHOICES, "builtInBrowser", "0")) || instantCancels >= 2;
    }

    static Intent systemIntent(int kind, File near) {
        Intent intent;
        if (kind == FOLDER) {
            intent = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        } else {
            intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
            intent.putExtra(Intent.EXTRA_MIME_TYPES, new String[] {"application/zip", "application/x-zip-compressed",
                "application/x-zip", "application/octet-stream"});
        }
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        Uri initial = near != null ? Storage.documentOf(near) : null;
        if (initial != null) intent.putExtra(DocumentsContract.EXTRA_INITIAL_URI, initial);
        return intent;
    }

    /** Opens a picker; false if neither the system's nor the built-in one could start. */
    static boolean pick(Activity activity, int kind, int request, File near, boolean builtIn) {
        if (!builtIn && !preferBuiltIn(activity) && state(activity) == OK) {
            try {
                launched = SystemClock.uptimeMillis();
                activity.startActivityForResult(systemIntent(kind, near), request);
                return true;
            } catch (ActivityNotFoundException | SecurityException e) {
                android.util.Log.w("Launcher", "system picker: " + e);
            }
        }
        Intent browser = new Intent(activity, FileBrowserActivity.class).putExtra(FileBrowserActivity.MODE, kind);
        if (near != null) browser.putExtra(FileBrowserActivity.START, near.getAbsolutePath());
        activity.startActivityForResult(browser, request);
        return true;
    }

    /** A cancel the player could not have made: the picker closed within a blink of opening. */
    static boolean instantCancel() {
        boolean instant = launched != 0 && SystemClock.uptimeMillis() - launched < INSTANT_CANCEL_MS;
        launched = 0;
        if (instant) ++instantCancels;
        return instant;
    }

    static void resetInstantCancels() { launched = 0; }

    /** The picker app's own page, where the player can turn it on again. */
    static void openSettings(Activity activity, String name) {
        try {
            activity.startActivity(new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                Uri.fromParts("package", name, null)));
        } catch (ActivityNotFoundException e) {
            activity.startActivity(new Intent(android.provider.Settings.ACTION_MANAGE_APPLICATIONS_SETTINGS));
        }
    }
}
