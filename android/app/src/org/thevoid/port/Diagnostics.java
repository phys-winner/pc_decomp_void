package org.thevoid.port;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.os.Build;

/** A report the player can copy, without device identifiers or a list of personal folders. */
final class Diagnostics {
    static String report(Context context, String edition, String gpu, String renderer, String textures, String error) {
        String version = "?";
        try {
            PackageInfo info = context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
            version = info.versionName + " (" + (Build.VERSION.SDK_INT >= 28 ? info.getLongVersionCode() : info.versionCode) + ")";
        } catch (PackageManager.NameNotFoundException ignored) { }
        return "Package: " + context.getPackageName() + "\nVersion: " + version + "\nGame: " + edition
            + "\nAndroid: " + Build.VERSION.RELEASE + " (API " + Build.VERSION.SDK_INT + ")"
            + "\nABI: " + String.join(", ", Build.SUPPORTED_ABIS) + "\nGPU: " + gpu + "\nRenderer: " + renderer
            + "\nTextures: " + textures + "\nLast error: " + (error == null || error.isEmpty() ? "none" : error);
    }

    static boolean copy(Context context, String report) {
        try {
            ClipboardManager clipboard = context.getSystemService(ClipboardManager.class);
            if (clipboard == null) return false;
            clipboard.setPrimaryClip(ClipData.newPlainText("Launcher diagnostics", report));
            return true;
        } catch (RuntimeException unavailable) { return false; }
    }
}
