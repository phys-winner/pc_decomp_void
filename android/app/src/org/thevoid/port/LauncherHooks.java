package org.thevoid.port;

import android.content.Context;
import android.content.Intent;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.thevoid.port.launcher.Launch;
import org.thevoid.port.launcher.PortHooks;

/** Carries existing installations and choices into the shared launcher. */
public final class LauncherHooks implements PortHooks {
    private static String edition(File folder) {
        try {
            String info = new String(Files.readAllBytes(ScriptOverrides.file(folder, "data/info.xml").toPath()), StandardCharsets.UTF_8);
            return info.contains("EngTitle=\"Tension\"") ? "tension" : "void";
        } catch (IOException e) { return ""; }
    }

    @Override public List<String> missing(Context c, String distribution, String part, File folder) {
        return distribution.equals(edition(folder)) ? Collections.emptyList() : Collections.singletonList("data/info.xml (" + distribution + ")");
    }

    @Override public void verifyInstallation(Context c, String distribution, String part, File folder) throws IOException {
        if (!distribution.equals(edition(folder))) throw new IOException("data/info.xml (" + distribution + ")");
    }

    @Override public void prepare(Context c, String distribution, Intent intent) {
        File folder = Launch.folder(c, distribution, "game");
        intent.putExtra(Launcher.EXTRA_GAME, folder.getAbsolutePath());
    }

    @Override public void migrate(Context c) {
        android.content.SharedPreferences old = c.getSharedPreferences(Launcher.PREFS, Context.MODE_PRIVATE);
        android.content.SharedPreferences touch = c.getSharedPreferences("touch", Context.MODE_PRIVATE);
        Launch.adopt(c, legacyChoices(Launcher.baseDir(), old.getString("game", ""),
            old.contains("large_address_aware") ? old.getBoolean("large_address_aware", false) : null,
            touch.getInt("fpsLimit", 0), touch.contains("skipIntro") ? touch.getBoolean("skipIntro", false) : null));
    }

    static Map<String, String> legacyChoices(File base, String saved, Boolean largeAddressAware, int fpsLimit, Boolean skipIntro) {
        Map<String, String> choices = new HashMap<>();
        if (Unpacker.isVoid(base)) choices.put("part." + edition(base) + ".game", base.getAbsolutePath());
        for (File folder : Launcher.copies(base))
            choices.putIfAbsent("part." + edition(folder) + ".game", folder.getAbsolutePath());
        File tension = new File(base.getParentFile(), "Tension");
        if (Unpacker.isVoid(tension)) choices.putIfAbsent("part.tension.game", tension.getAbsolutePath());
        if (!saved.isEmpty() && Unpacker.isVoid(new File(saved))) {
            String id = edition(new File(saved));
            choices.put("part." + id + ".game", saved);
            choices.put("last", id);
        }
        if (largeAddressAware != null)
            choices.put("option.large_address_aware", largeAddressAware ? "1" : "0");
        choices.put("option.fps_limit", Integer.toString(fpsLimit));
        for (String id : new String[] {"void", "tension"}) {
            String folder = choices.get("part." + id + ".game");
            String intro = folder == null ? "" : Profile.prop(GameActivity.Release.read(
                new File(folder, "userdata/overrides/settings.xml")), "PortSkipIntro");
            if (intro.isEmpty() && skipIntro != null) intro = skipIntro ? "1" : "0";
            if (intro.equals("0") || intro.equals("1")) choices.put("intro." + id, intro);
        }
        return choices;
    }
}
