package port.launcher;

import android.content.Context;
import android.os.Environment;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** The port specification (assets/launcher/port.json, written by tools/launcher.py from the
 *  game's android/port.json): everything that tells one game's launcher from another's and needs
 *  no code. Texts are a string or a {"en": …, "ru": …} map (Texts.of picks the language). */
final class Spec {
    static final String ASSET = "launcher/port.json", BUILD_ASSET = "launcher/build.json";

    static final class Part {
        String id, folder, marker, folderGroup = "";
        Object title, folderTitle;
        boolean fixed, mount;
        List<String> required = new ArrayList<>();
        List<Glob> needed = new ArrayList<>();
        Map<String, Object> userFolders = new LinkedHashMap<>();
    }

    static final class Distribution {
        String id, version, activity;
        Object title;
        JSONObject theme;
        List<Part> parts = new ArrayList<>();
        List<String> renderers = new ArrayList<>();
        boolean intro, introDefault;

        Part part(String id) {
            for (Part p : parts) if (p.id.equals(id)) return p;
            return null;
        }
    }

    static final class Mode {
        String id, kind, title;
        int vulkan;                   /* VK_MAKE_API_VERSION of the needed Vulkan; 0 none */
        int minSdk;
        int adrenoMin, adrenoMax;     /* Turnip: the Adreno models its driver supports */
        String driver = "";           /* Turnip: the driver library adrenotools loads */
        boolean needsBC = true;       /* a Vulkan mode needs BC1-3 (DXT) sampling: the game's textures */
        List<String> libraries = new ArrayList<>();
        Object description;

        boolean vulkanKind() { return "vulkan".equals(kind) || "turnip".equals(kind); }
    }

    /** A license text the APK carries (an asset file), with the name the player reads. */
    static final class License {
        final String path;
        final Object title;           /* null: named after the file */

        License(String path, Object title) {
            this.path = path;
            this.title = title;
        }
    }

    static final class Option {
        String key, type, value, extra;
        int defaultMinRamGiB;
        boolean arm64Only;
        Object title, hint;
        List<String> only = new ArrayList<>();
        List<String> choices = new ArrayList<>();
        List<Object> choiceTitles = new ArrayList<>();
    }

    static final class Category {
        String id, part;
        Object title, hint;
        List<Glob> globs = new ArrayList<>();
    }

    final JSONObject json;
    final String label, logTag, storage, github, hooks, textureBackend, gogInstaller;
    final Object title, subtitle, gameFilesHint, optionsHint;
    final boolean allFilesAccess, localNetwork, updates, autoLaunch;
    final List<String> languages = new ArrayList<>();
    final List<Distribution> distributions = new ArrayList<>();
    final List<Mode> modes = new ArrayList<>();
    final String defaultMode;
    final List<String> autoModes = new ArrayList<>(), verifiedModes = new ArrayList<>();
    final List<Option> options = new ArrayList<>();
    final List<Category> categories = new ArrayList<>();
    final List<License> licenses = new ArrayList<>();
    final JSONObject theme, build;

    private static Spec loaded;

    static synchronized Spec get(Context context) {
        if (loaded == null) {
            try {
                JSONObject build = new JSONObject();
                try { build = new JSONObject(asset(context, BUILD_ASSET)); } catch (IOException missing) { /* a development build */ }
                loaded = new Spec(new JSONObject(asset(context, ASSET)), build);
            } catch (IOException | JSONException e) {
                throw new IllegalStateException("The launcher's port.json is missing or invalid: " + e.getMessage(), e);
            }
        }
        return loaded;
    }

    Spec(JSONObject json, JSONObject build) throws JSONException {
        this.json = json;
        this.build = build;
        if (json.optInt("schema", 0) != 1) throw new JSONException("schema must be 1");
        JSONObject app = json.getJSONObject("app");
        label = app.getString("label");
        title = app.opt("title") != null ? app.opt("title") : label;
        subtitle = app.opt("subtitle");
        logTag = app.optString("logTag", "Launcher");
        storage = app.optString("storage", "");
        github = app.optString("github", "").trim();
        hooks = app.optString("hooks", "");
        gogInstaller = app.optString("gogInstaller", "");
        allFilesAccess = app.optBoolean("allFilesAccess", true);
        localNetwork = app.optBoolean("localNetwork", false);
        updates = app.optBoolean("updates", true) && !github.isEmpty();
        autoLaunch = app.optBoolean("autoLaunch", false);
        strings(app.optJSONArray("languages"), languages);
        if (languages.isEmpty()) languages.add("en");
        JSONArray texts = app.optJSONArray("licenses");
        if (texts != null) for (int i = 0; i < texts.length(); ++i) {
            JSONObject entry = texts.optJSONObject(i);
            if (entry != null) licenses.add(new License(entry.getString("path"), entry.opt("title")));
            else licenses.add(new License(texts.getString(i), null));
        }
        theme = json.optJSONObject("theme") != null ? json.optJSONObject("theme") : new JSONObject();
        JSONObject hints = json.optJSONObject("hints");
        gameFilesHint = hints != null ? hints.opt("gameFiles") : null;
        optionsHint = hints != null ? hints.opt("options") : null;

        JSONObject renderers = json.optJSONObject("renderers");
        if (renderers != null) {
            JSONArray list = renderers.getJSONArray("modes");
            for (int i = 0; i < list.length(); ++i) {
                JSONObject m = list.getJSONObject(i);
                Mode mode = new Mode();
                mode.id = m.getString("id");
                mode.kind = m.optString("kind", "gles");
                mode.title = m.optString("title", mode.id);
                mode.description = m.opt("description");
                mode.vulkan = vulkanVersion(m.optString("vulkan", ""));
                mode.minSdk = m.optInt("minSdk", 0);
                JSONArray adreno = m.optJSONArray("adreno");
                if (adreno != null) { mode.adrenoMin = adreno.getInt(0); mode.adrenoMax = adreno.getInt(1); }
                mode.driver = m.optString("driver", "");
                mode.needsBC = m.optBoolean("needsBC", true);
                strings(m.optJSONArray("libraries"), mode.libraries);
                modes.add(mode);
            }
            defaultMode = renderers.optString("default", modes.isEmpty() ? "" : modes.get(0).id);
            strings(renderers.optJSONArray("auto"), autoModes);
            strings(renderers.optJSONArray("verified"), verifiedModes);
        } else {
            defaultMode = "";
        }

        JSONArray list = json.getJSONArray("distributions");
        for (int i = 0; i < list.length(); ++i) {
            JSONObject d = list.getJSONObject(i);
            Distribution dist = new Distribution();
            dist.id = d.getString("id");
            dist.title = d.opt("title") != null ? d.opt("title") : label;
            dist.version = d.optString("version", "");
            dist.activity = d.getString("activity");
            dist.theme = d.optJSONObject("theme");
            JSONObject intro = d.optJSONObject("intro");
            dist.intro = intro != null;
            dist.introDefault = intro != null && intro.optBoolean("default", true);
            strings(d.optJSONArray("renderers"), dist.renderers);
            if (dist.renderers.isEmpty()) for (Mode m : modes) dist.renderers.add(m.id);
            JSONArray parts = d.getJSONArray("parts");
            for (int j = 0; j < parts.length(); ++j) {
                JSONObject p = parts.getJSONObject(j);
                Part part = new Part();
                part.id = p.getString("id");
                part.title = p.opt("title") != null ? p.opt("title") : part.id;
                part.folder = p.optString("folder", "{storage}/" + part.id);
                part.folderGroup = p.optString("folderGroup", "");
                part.folderTitle = p.opt("folderTitle") != null ? p.opt("folderTitle") : dist.title;
                part.fixed = p.optBoolean("fixed", false);
                part.mount = p.optBoolean("mount", false);
                strings(p.optJSONArray("required"), part.required);
                if (part.required.isEmpty()) throw new JSONException(dist.id + "/" + part.id + ": required is empty");
                part.marker = p.optString("marker", part.required.get(0));
                List<String> needed = new ArrayList<>();
                strings(p.optJSONArray("needed"), needed);
                for (String glob : needed) part.needed.add(new Glob(glob));
                JSONObject folders = p.optJSONObject("userFolders");
                if (folders != null) for (Iterator<String> names = folders.keys(); names.hasNext();) {
                    String path = names.next();
                    part.userFolders.put(path, folders.isNull(path) ? null : folders.get(path));
                }
                dist.parts.add(part);
            }
            if (dist.parts.isEmpty()) throw new JSONException(dist.id + ": no parts");
            distributions.add(dist);
        }
        if (distributions.isEmpty()) throw new JSONException("no distributions");

        JSONArray opts = json.optJSONArray("options");
        if (opts != null) for (int i = 0; i < opts.length(); ++i) {
            JSONObject o = opts.getJSONObject(i);
            Option option = new Option();
            option.key = o.getString("key");
            option.type = o.optString("type", "bool");
            option.value = String.valueOf(o.opt("default") != null ? o.opt("default") : "");
            option.defaultMinRamGiB = o.optInt("defaultMinRamGiB", 0);
            option.arm64Only = o.optBoolean("arm64Only", false);
            option.extra = o.optString("extra", "");
            option.title = o.opt("title") != null ? o.opt("title") : option.key;
            option.hint = o.opt("hint");
            strings(o.optJSONArray("only"), option.only);
            JSONArray choices = o.optJSONArray("choices");
            if (choices != null) for (int j = 0; j < choices.length(); ++j) {
                JSONObject c = choices.getJSONObject(j);
                option.choices.add(c.getString("value"));
                option.choiceTitles.add(c.opt("title") != null ? c.opt("title") : c.getString("value"));
            }
            options.add(option);
        }

        JSONObject cleanup = json.optJSONObject("cleanup");
        JSONArray cats = cleanup != null ? cleanup.optJSONArray("categories") : null;
        if (cats != null) for (int i = 0; i < cats.length(); ++i) {
            JSONObject c = cats.getJSONObject(i);
            Category category = new Category();
            category.id = c.getString("id");
            category.part = c.optString("part", "");
            category.title = c.opt("title") != null ? c.opt("title") : category.id;
            category.hint = c.opt("hint");
            List<String> globs = new ArrayList<>();
            strings(c.getJSONArray("globs"), globs);
            for (String glob : globs) category.globs.add(new Glob(glob));
            categories.add(category);
        }
        JSONObject textures = json.optJSONObject("textures");
        textureBackend = textures != null ? textures.optString("backend", "") : "";
    }

    Distribution distribution(String id) {
        for (Distribution d : distributions) if (d.id.equals(id)) return d;
        return null;
    }

    Mode mode(String id) {
        for (Mode m : modes) if (m.id.equals(id)) return m;
        return null;
    }

    /** /sdcard/<app.storage>: the port's folder in shared storage. */
    File storageRoot() {
        return storage.isEmpty() ? Environment.getExternalStorageDirectory() : new File(Environment.getExternalStorageDirectory(), storage);
    }

    /** A part's folder template: {storage}, {files} (app-specific external files), {private}. */
    File resolve(Context context, String template) {
        String text = template.replace("{storage}", storageRoot().getPath());
        if (text.contains("{files}")) {
            File files = context.getExternalFilesDir(null);
            text = text.replace("{files}", files != null ? files.getPath() : context.getFilesDir().getPath());
        }
        return new File(text.replace("{private}", context.getFilesDir().getPath()));
    }

    String buildText(String key) { return build.optString(key, ""); }

    String githubUrl(String path) { return github.isEmpty() ? null : "https://github.com/" + github + path; }

    List<Option> options(String distribution) {
        List<Option> result = new ArrayList<>();
        for (Option o : options) if (o.only.isEmpty() || o.only.contains(distribution)) result.add(o);
        return Collections.unmodifiableList(result);
    }

    /** "1.3" → VK_MAKE_API_VERSION(0, 1, 3, 0), the form PackageManager's Vulkan features use. */
    static int vulkanVersion(String text) {
        if (text.isEmpty()) return 0;
        String[] parts = text.split("\\.");
        int major = Integer.parseInt(parts[0]), minor = parts.length > 1 ? Integer.parseInt(parts[1]) : 0;
        return (major << 22) | (minor << 12);
    }

    private static void strings(JSONArray array, List<String> out) throws JSONException {
        if (array != null) for (int i = 0; i < array.length(); ++i) out.add(array.getString(i));
    }

    static String asset(Context context, String name) throws IOException {
        try (InputStream in = context.getAssets().open(name); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[16384];
            for (int n; (n = in.read(buffer)) > 0;) out.write(buffer, 0, n);
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        }
    }
}
