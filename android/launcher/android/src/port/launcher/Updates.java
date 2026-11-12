package port.launcher;

import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.os.Build;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Properties;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Updates from the port's GitHub releases. Every release carries update.json (written by
 *  tools/update_manifest.py from the APK itself, see docs/UPDATES.md), so the newest one is at
 *  github.com/<repo>/releases/latest/download/update.json: one small request, no API limits. The
 *  result is kept in the state file "update", which the game reads too (Launch). */
final class Updates {
    static final long INTERVAL_MS = 6 * 60 * 60 * 1000L;
    private static final int TIMEOUT_MS = 15000, LIMIT = 1 << 20;

    static final class Info {
        long versionCode, size;
        int minSdk;
        String versionName = "", tag = "", page = "", notes = "", apkName = "", apkUrl = "", sha256 = "", signer = "";
    }

    private Updates() { }

    static boolean automatic(Context context) { return !"0".equals(State.get(context, State.CHOICES, "updates.auto", "1")); }

    static boolean due(Context context) {
        Spec spec = Spec.get(context);
        if (!spec.updates || !automatic(context)) return false;
        long checked = State.getLong(State.read(context, State.UPDATE), "checked", 0);
        return Math.abs(System.currentTimeMillis() - checked) > INTERVAL_MS;
    }

    /** Blocking: asks GitHub, stores what it found (or why it could not) and returns it. */
    static Info check(Context context) throws IOException {
        Spec spec = Spec.get(context);
        if (spec.github.isEmpty()) throw new IOException("no GitHub repository in port.json");
        String text;
        try {
            text = get(context, "https://github.com/" + spec.github + "/releases/latest/download/update.json");
        } catch (IOException direct) {
            /* The API names the asset too; it is limited to 60 requests an hour per address. */
            try {
                JSONObject release = new JSONObject(get(context, "https://api.github.com/repos/" + spec.github + "/releases/latest"));
                String url = null;
                JSONArray assets = release.optJSONArray("assets");
                if (assets != null) for (int i = 0; i < assets.length(); ++i)
                    if ("update.json".equals(assets.getJSONObject(i).optString("name"))) url = assets.getJSONObject(i).optString("browser_download_url");
                if (url == null) throw direct;
                text = get(context, url);
            } catch (JSONException | IOException fallback) {
                record(context, null, direct.getMessage());
                throw direct;
            }
        }
        Info info;
        try {
            info = parse(context, text);
        } catch (JSONException e) {
            record(context, null, e.getMessage());
            throw new IOException("update.json: " + e.getMessage(), e);
        }
        record(context, info, null);
        return info;
    }

    static Info parse(Context context, String text) throws JSONException {
        JSONObject json = new JSONObject(text);
        if (json.optInt("schema", 0) != 1) throw new JSONException("schema " + json.optInt("schema"));
        String pkg = json.optString("package", "");
        if (!pkg.isEmpty() && !pkg.equals(context.getPackageName())) throw new JSONException("package " + pkg);
        JSONObject latest = json.optJSONObject("latest");
        Info info = new Info();
        if (latest == null) return info;   /* no release yet: nothing newer than this build */
        info.versionCode = latest.getLong("versionCode");
        info.versionName = latest.optString("versionName", "");
        info.tag = latest.optString("tag", "");
        info.page = latest.optString("page", "");
        info.notes = latest.optString("notes", "");
        JSONObject apk = latest.optJSONObject("apk");
        if (apk != null) {
            info.apkName = apk.optString("name", "");
            info.apkUrl = apk.optString("url", "");
            info.size = apk.optLong("size", 0);
            info.sha256 = apk.optString("sha256", "");
            info.signer = apk.optString("signer", "");
            info.minSdk = apk.optInt("minSdk", 0);
        }
        return info;
    }

    private static void record(Context context, Info info, String error) {
        State.update(context, State.UPDATE, values -> {
            values.setProperty("checked", Long.toString(System.currentTimeMillis()));
            if (error != null) { values.setProperty("error", error); return; }
            values.remove("error");
            values.setProperty("versionCode", Long.toString(info.versionCode));
            values.setProperty("versionName", info.versionName);
            values.setProperty("tag", info.tag);
            values.setProperty("page", info.page);
            values.setProperty("notes", info.notes);
            values.setProperty("apkName", info.apkName);
            values.setProperty("apkUrl", info.apkUrl);
            values.setProperty("apkSize", Long.toString(info.size));
            values.setProperty("sha256", info.sha256);
            values.setProperty("signer", info.signer);
            values.setProperty("minSdk", Integer.toString(info.minSdk));
        });
    }

    /** The newest release when it is newer than this build, runs here and was not skipped. */
    static Info available(Context context) {
        Properties values = State.read(context, State.UPDATE);
        long code = State.getLong(values, "versionCode", 0);
        if (code <= installedCode(context) || code == State.getLong(values, "skipped", -1)) return null;
        Info info = new Info();
        info.versionCode = code;
        info.versionName = values.getProperty("versionName", "");
        info.tag = values.getProperty("tag", "");
        info.page = values.getProperty("page", "");
        info.notes = values.getProperty("notes", "");
        info.apkName = values.getProperty("apkName", "");
        info.apkUrl = values.getProperty("apkUrl", "");
        info.size = State.getLong(values, "apkSize", 0);
        info.sha256 = values.getProperty("sha256", "");
        info.signer = values.getProperty("signer", "");
        info.minSdk = (int) State.getLong(values, "minSdk", 0);
        if (info.minSdk > Build.VERSION.SDK_INT) return null;
        return info;
    }

    static String lastError(Context context) { return State.read(context, State.UPDATE).getProperty("error"); }

    static void skip(Context context, long versionCode) { State.put(context, State.UPDATE, "skipped", Long.toString(versionCode)); }

    static long installedCode(Context context) {
        PackageInfo info = installed(context);
        return info == null ? 0 : Build.VERSION.SDK_INT >= 28 ? info.getLongVersionCode() : info.versionCode;
    }

    static String installedName(Context context) {
        PackageInfo info = installed(context);
        return info == null || info.versionName == null ? "" : info.versionName;
    }

    private static PackageInfo installed(Context context) {
        try {
            return context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
        } catch (PackageManager.NameNotFoundException e) {
            return null;
        }
    }

    /** SHA-256 of this build's signing certificate, as apksigner prints it. */
    static String installedSigner(Context context) {
        if (Build.VERSION.SDK_INT < 28) return "";
        try {
            PackageInfo info = context.getPackageManager().getPackageInfo(context.getPackageName(), PackageManager.GET_SIGNING_CERTIFICATES);
            Signature[] signers = info.signingInfo == null ? null : info.signingInfo.getApkContentsSigners();
            if (signers == null || signers.length == 0) return "";
            return hex(MessageDigest.getInstance("SHA-256").digest(signers[0].toByteArray()));
        } catch (PackageManager.NameNotFoundException | NoSuchAlgorithmException e) {
            return "";
        }
    }

    /** Whether the release would install over this build: same signing certificate. */
    static boolean sameSigner(Context context, Info info) {
        String own = installedSigner(context);
        return info.signer.isEmpty() || own.isEmpty() || own.equalsIgnoreCase(info.signer);
    }

    private static String hex(byte[] bytes) {
        StringBuilder text = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) text.append(String.format(java.util.Locale.ROOT, "%02x", b & 0xFF));
        return text.toString();
    }

    private static String get(Context context, String address) throws IOException {
        HttpURLConnection connection = (HttpURLConnection) new URL(address).openConnection();
        try {
            connection.setConnectTimeout(TIMEOUT_MS);
            connection.setReadTimeout(TIMEOUT_MS);
            connection.setInstanceFollowRedirects(true);
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("User-Agent", context.getPackageName() + "/" + installedName(context));
            int code = connection.getResponseCode();
            if (code != 200) throw new IOException("HTTP " + code);
            try (InputStream in = connection.getInputStream(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[8192];
                for (int n; (n = in.read(buffer)) > 0;) {
                    out.write(buffer, 0, n);
                    if (out.size() > LIMIT) throw new IOException("update.json is too large");
                }
                return new String(out.toByteArray(), StandardCharsets.UTF_8);
            }
        } finally {
            connection.disconnect();
        }
    }
}
