package org.thevoid.port;

import java.util.Locale;

public final class PortLanguageTest {
    public static void main(String[] args) throws Exception {
        Locale.setDefault(Locale.ENGLISH);
        String[] codes = {"en", "ru", "de", "pl"};
        String[] releases = {"English", "Russian", "German", "Polish"};
        for (int i = 0; i < codes.length; ++i) {
            Settings.portLanguage = "";
            Settings.gameLanguage = releases[i];
            String expected = Settings.text(Settings.T_MORE);
            String layout = TouchLayoutEditor.title();
            String gamepad = HardwareInput.helpTitle();
            for (String release : releases) {
                Settings.gameLanguage = release;
                Settings.portLanguage = codes[i];
                assert Settings.language().equals(codes[i]);
                assert Settings.text(Settings.T_MORE).equals(expected);
                assert TouchLayoutEditor.title().equals(layout);
                assert HardwareInput.helpTitle().equals(gamepad);
            }
        }
        System.out.println("PASS: launcher language overrides every release for port settings, layout and gamepad UI");
        java.nio.file.Path root = java.nio.file.Files.createTempDirectory("port-profiles-");
        java.io.File modern = root.resolve("void").toFile(), legacy = root.resolve("tension").toFile();
        java.io.File modernCopy = root.resolve("void-copy").toFile();
        for (java.io.File game : new java.io.File[] {modern, legacy, modernCopy}) {
            java.nio.file.Files.createDirectories(new java.io.File(game, "data").toPath());
            java.nio.file.Files.write(new java.io.File(game, "data/info.xml").toPath(),
                ("<Info EngTitle=\"" + (game == legacy ? "Tension" : "Turgor") + "\" />").getBytes("UTF-8"));
        }
        java.nio.file.Path save = new java.io.File(modern, "userdata/Documents/save.bin").toPath();
        java.nio.file.Files.createDirectories(save.getParent());
        java.nio.file.Files.write(save, new byte[] {1, 2, 3});
        Profile.migrateGame(modern, legacy, "userdata");
        assert java.nio.file.Files.exists(save);
        assert !new java.io.File(legacy, "userdata").exists();
        Profile.migrateGame(modern, modernCopy, "userdata");
        assert !java.nio.file.Files.exists(save);
        assert java.util.Arrays.equals(java.nio.file.Files.readAllBytes(new java.io.File(modernCopy, "userdata/Documents/save.bin").toPath()), new byte[] {1, 2, 3});
        java.io.File emptyBase = root.resolve("old-default").toFile();
        for (java.io.File onlyGame : new java.io.File[] {modern, legacy}) {
            String id = onlyGame == legacy ? "tension" : "void";
            java.io.File caseBase = root.resolve("case-" + id + "/TheVoid").toFile();
            java.util.Map<String, String> choices = LauncherHooks.legacyChoices(caseBase, onlyGame.getAbsolutePath(), false, 60, true);
            assert choices.get("last").equals(id);
            assert choices.get("part." + id + ".game").equals(onlyGame.getAbsolutePath());
            assert !choices.containsKey("part." + (id.equals("void") ? "tension" : "void") + ".game");
            assert choices.get("option.large_address_aware").equals("0");
            assert choices.get("option.fps_limit").equals("60");
            assert choices.get("intro." + id).equals("1");
        }
        java.io.File inferredBase = root.resolve("auto").toFile();
        java.io.File oldGame = new java.io.File(inferredBase, "game-russian");
        java.nio.file.Files.createDirectories(new java.io.File(oldGame, "data").toPath());
        java.nio.file.Files.write(new java.io.File(oldGame, "data/info.xml").toPath(), "<Info EngTitle=\"Turgor\" />".getBytes("UTF-8"));
        java.util.Map<String, String> inferred = LauncherHooks.legacyChoices(inferredBase, "", null, 0, null);
        assert inferred.get("part.void.game").equals(oldGame.getAbsolutePath());
        assert !inferred.containsKey("option.large_address_aware");
        assert !inferred.containsKey("intro.void") && !inferred.containsKey("intro.tension");
        java.nio.file.Files.createDirectories(new java.io.File(legacy, "userdata/overrides").toPath());
        for (String value : new String[] {"0", "1"}) {
            Profile.setProps(new java.io.File(legacy, "userdata/overrides/settings.xml"),
                java.util.Collections.singletonMap("PortSkipIntro", value));
            java.util.Map<String, String> choices = LauncherHooks.legacyChoices(emptyBase, legacy.getAbsolutePath(), null, 0, !value.equals("1"));
            assert choices.get("intro.tension").equals(value) : "the edition's profile overrides the old global preference";
        }
        java.nio.file.Path oldSave = new java.io.File(inferredBase, "userdata/Documents/old-save.bin").toPath();
        java.nio.file.Files.createDirectories(oldSave.getParent());
        java.nio.file.Files.write(oldSave, new byte[] {4, 5, 6});
        Profile.migrateGame(inferredBase, legacy, "userdata");
        assert java.nio.file.Files.exists(oldSave);
        Profile.migrateGame(inferredBase, oldGame, "userdata");
        assert !java.nio.file.Files.exists(oldSave);
        assert java.util.Arrays.equals(java.nio.file.Files.readAllBytes(new java.io.File(oldGame, "userdata/Documents/old-save.bin").toPath()), new byte[] {4, 5, 6});
        java.lang.reflect.Method adopt = org.thevoid.port.launcher.Launch.class.getDeclaredMethod("adopt", java.io.File.class, java.util.Map.class);
        adopt.setAccessible(true);
        java.io.File state = root.resolve("state").toFile();
        java.nio.file.Files.createDirectories(state.toPath());
        java.util.Map<String, String> existing = new java.util.HashMap<>();
        existing.put("part.void.game", "player-choice"); existing.put("last", "void");
        existing.put("intro.void", "0"); existing.put("intro.tension", "0");
        adopt.invoke(null, state, existing);
        adopt.invoke(null, state, LauncherHooks.legacyChoices(emptyBase, legacy.getAbsolutePath(), true, 90, true));
        java.util.Properties persisted = new java.util.Properties();
        try (java.io.InputStream input = new java.io.FileInputStream(new java.io.File(state, "choices.properties"))) { persisted.load(input); }
        assert persisted.getProperty("part.void.game").equals("player-choice");
        assert persisted.getProperty("last").equals("void");
        assert persisted.getProperty("part.tension.game").equals(legacy.getAbsolutePath());
        assert persisted.getProperty("intro.void").equals("0") && persisted.getProperty("intro.tension").equals("0");
        System.out.println("PASS: intro choices migrate per edition, profile values win, newer launcher choices stay");
        System.out.println("PASS: old single-game choices and pre-launcher auto-discovery migrate; later choices are preserved");
        try (java.util.stream.Stream<java.nio.file.Path> paths = java.nio.file.Files.walk(root)) {
            for (java.nio.file.Path path : (Iterable<java.nio.file.Path>)paths.sorted(java.util.Comparator.reverseOrder())::iterator)
                java.nio.file.Files.delete(path);
        }
        System.out.println("PASS: two installed game generations never migrate saves into each other");
    }
}
