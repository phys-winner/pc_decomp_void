package org.thevoid.port;

public final class DebugCommandsTest {
    private static String repeated(String text, int count) {
        StringBuilder result = new StringBuilder();
        for (int i = 0; i < count; ++i) result.append(text);
        return result.toString();
    }

    public static void main(String[] args) {
        assert !DebugCommands.validCommand("");
        assert DebugCommands.validCommand("/go 40");
        assert DebugCommands.validCommand("setvar show_physics 1");
        assert DebugCommands.validCommand(repeated("a", 511));
        assert !DebugCommands.validCommand(repeated("a", 512));
        assert DebugCommands.validCommand(repeated("я", 255));
        assert !DebugCommands.validCommand(repeated("я", 256));
        assert DebugCommands.validCommand(repeated("\ud83d\ude00", 85));
        assert !DebugCommands.validCommand(repeated("\ud83d\ude00", 86));
        assert !DebugCommands.validCommand("/god\n/go 1");
        assert !DebugCommands.validCommand("/god\r/go 1");
        assert !DebugCommands.validCommand("/god\0");
        assert DebugCommands.LEVEL_IDS.length == 26;
        assert DebugLevels.RU.length == 26 && DebugLevels.DE.length == 26;
        for (boolean legacy : new boolean[] {false, true}) {
            Settings.legacyGame = legacy;
            for (String language : new String[] {"English", "Russian", "German", "Polish"}) {
                Settings.gameLanguage = language;
                java.util.HashSet<String> names = new java.util.HashSet<>();
                for (String usage : DebugCommands.commands()) {
                    String name = DebugCommands.commandName(usage);
                    assert !name.isEmpty() && !name.equals(usage) : usage;
                    assert names.add(name) : "duplicate command label: " + name;
                    assert DebugCommands.commandHelp(usage).startsWith(usage + "\n") : usage;
                }
                String[] categories = DebugCommands.categoryChoices();
                assert categories.length == 9 : "eight categories and manual entry";
                java.text.Collator alphabet = java.text.Collator.getInstance(new java.util.Locale(
                    language.equals("Russian") ? "ru" : language.equals("German") ? "de" : language.equals("Polish") ? "pl" : "en"));
                java.util.HashSet<String> grouped = new java.util.HashSet<>();
                for (int i = 0; i < categories.length - 1; ++i) {
                    if (i > 0) assert alphabet.compare(categories[i - 1], categories[i]) < 0 : categories[i];
                    String[] commands = DebugCommands.commandsInCategory(categories[i]);
                    assert commands.length > 0 : categories[i];
                    for (int j = 0; j < commands.length; ++j) {
                        assert grouped.add(commands[j]) : "command in multiple categories: " + commands[j];
                        if (j > 0) assert alphabet.compare(DebugCommands.commandName(commands[j - 1]),
                            DebugCommands.commandName(commands[j])) <= 0 : commands[j];
                    }
                }
                assert grouped.equals(new java.util.HashSet<>(java.util.Arrays.asList(DebugCommands.commands())))
                    : "every available command must appear exactly once";
                assert DebugCommands.commandsInCategory(categories[categories.length - 1]).length == 0 : "manual entry is last";
                if (language.equals("Russian")) {
                    assert categories[0].equals("Братья");
                    assert categories[categories.length - 2].equals("Сюжет и время");
                    assert categories[categories.length - 1].equals("Ввод команды");
                    assert DebugCommands.commandsInCategory("Сохранения")[0].equals("/load save_name");
                    assert DebugCommands.commandsInCategory("Сохранения")[1].equals("/save save_name");
                }
            }
            Settings.gameLanguage = "ru";
            assert DebugCommands.commandName("/open_zone [zone]").equals("Открыть сердца");
            assert DebugCommands.commandHelp("/open_zone [zone]").contains("0–20 (21 сердце)");
            assert DebugCommands.commandHelp("/open_zone [zone]").contains("случайное");
            assert java.util.Arrays.asList(DebugCommands.commands()).contains(DebugCommands.PHYSICS_COMMAND);
            Settings.gameLanguage = "Russian";
            assert Settings.text(Settings.T_REFLECTIONS).equals("Отражения");
            Settings.gameLanguage = "English";
            assert Settings.text(Settings.T_REFLECTIONS).equals("Reflections");
            int normal = DebugCommands.levelIds().length;
            String[] extra = DebugCommands.extraLabels();
            assert extra.length == (legacy ? 50 : 43);
            if (!legacy) {
                for (int id : DebugCommands.levelIds()) assert id != 26;
                for (String label : extra) {
                    assert !label.equals("[*] Twin's appearance");
                    for (String hunter : new String[] {"ironclad", "driller", "caterpillar", "dudochnik", "lattice"}) {
                        assert !label.equals("[*] Brother: " + hunter) && !label.equals("[*] Battle: " + hunter);
                    }
                }
            }
            assert extra[extra.length - 1].equals("[?] Backyard");
            for (int i = 0; i < normal + extra.length; ++i) {
                if (i >= normal && i < normal + extra.length - 1) assert extra[i - normal].startsWith("[*] ");
                String[] expected = DebugCommands.levelCommands(i);
                java.util.ArrayList<String[]> selected = new java.util.ArrayList<>();
                DebugCommands.selectLevel(i, selected::add);
                assert selected.size() == 1 : "a complete route must unpause once";
                assert java.util.Arrays.equals(selected.get(0), expected);
                for (String command : expected) assert DebugCommands.validCommand(command);
                if (i < normal) assert expected[0].equals("/go " + DebugCommands.levelIds()[i]);
                String first = expected[0];
                expected[0] = "changed";
                assert DebugCommands.levelCommands(i)[0].equals(first) : "must not mutate generated route";
            }
        }
        Settings.legacyGame = false;
        for (String usage : DebugCommands.COMMANDS) {
            String[] parts = usage.split(" +");
            StringBuilder selected = new StringBuilder(parts[0]);
            for (int i = 1; i < parts.length; ++i) {
                String[] choices = DebugCommands.argumentValues(parts[i]);
                assert choices.length > 0 : usage;
                for (String choice : choices) assert choice.isEmpty() || DebugCommands.validCommand(choice) : usage;
                if (!parts[i].startsWith("[")) {
                    assert !choices[0].isEmpty() : usage;
                    selected.append(' ').append(choices[0]);
                } else assert choices[0].isEmpty() : usage;
            }
            assert DebugCommands.validCommand(selected.toString()) : selected;
        }
        Settings.legacyGame = true;
        assert DebugCommands.levelIds().length == 29;
        java.util.List<String> old = java.util.Arrays.asList(DebugCommands.commands());
        assert old.contains("/girl_executions") && !old.contains("/girl_execute") && !old.contains("/void");
        for (String usage : DebugCommands.commands()) {
            if (usage.equals(DebugCommands.PHYSICS_COMMAND)) continue;
            String[] parts = usage.split(" +");
            for (int i = 1; i < parts.length; ++i) assert DebugCommands.argumentValues(parts[i]).length > 0 : usage;
        }
        Settings.legacyGame = false;
        assert java.util.Arrays.asList(DebugCommands.argumentValues("hunter_name")).contains("dudochnik");
        assert java.util.Arrays.asList(DebugCommands.argumentValues("girl_name")).contains("ole");
        assert DebugCommands.argumentValues("chapter_num").length == 7;
        assert DebugCommands.argumentValues("zone").length == 21;
        assert DebugCommands.argumentValues("[zone]")[0].isEmpty();
        assert java.util.Arrays.equals(DebugCommands.argumentValues("exit_number"), new String[] {"0", "1", "2", "255"});
        System.out.println("debug commands: complete categories, localized alphabet, manual entry last, JNI byte limit, 26 levels and argument selectors PASS");
    }
}
