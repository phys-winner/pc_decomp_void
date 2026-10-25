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
        assert DebugCommands.LEVEL_IDS.length == 35;
        assert DebugLevels.RU.length == 35 && DebugLevels.DE.length == 35;
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
            String[] parts = usage.split(" +");
            for (int i = 1; i < parts.length; ++i) assert DebugCommands.argumentValues(parts[i]).length > 0 : usage;
        }
        Settings.legacyGame = false;
        assert java.util.Arrays.asList(DebugCommands.argumentValues("hunter_name")).contains("dudochnik");
        assert java.util.Arrays.asList(DebugCommands.argumentValues("girl_name")).contains("ole");
        assert DebugCommands.argumentValues("chapter_num").length == 7;
        assert DebugCommands.argumentValues("zone").length == 21;
        assert DebugCommands.argumentValues("[zone]")[0].isEmpty();
        System.out.println("debug commands: JNI byte limit, Unicode, control rejection, 35 levels, selectors for every argument PASS");
    }
}
