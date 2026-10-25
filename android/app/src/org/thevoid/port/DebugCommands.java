package org.thevoid.port;

import android.app.Activity;
import android.app.AlertDialog;
import android.graphics.Color;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;
import java.util.Arrays;
import java.util.Locale;
import java.util.function.Consumer;

/** The original game's console commands, from world/world.bin and game.bin. */
final class DebugCommands {
    static final String[] COMMANDS = {
        "/revert_girl hunter_name", "/damage color color_amount", "/flash", "/chapters chapter_num", "/chapter chapter_num",
        "/add_girl girl_name", "/talk_girl girl_name", "/kill_girl girl_name", "/open_zone [zone]",
        "/automonolog automonolog_name", "/add_hunter [hunter_name]", "/turgor", "/stronger", "/hunter_festival",
        "/hunter_festival_end", "/girl_execute", "/hunter_fights", "/sister_die", "/ole_born", "/end", "/void",
        "/final girl_name", "/meet_hunter hunter_index", "/hunter_demo hunter_name", "/openall", "/skip num_of_hours",
        "/save_map", "/gopt point_name", "/go location_number", "/realm domain_index color", "/add_fl color amount",
        "/add_al color amount", "/hunter_list", "/execution_start_cutscene", "/execute_girl_cutscene girl_name",
        "/fight_hunter attacker_hunter_name victim_hunter_name", "/trap_hunter hunter_name", "/execute_girl hunter_index",
        "/talk_hunter hunter_name [theme]", "/uplevel_camera animation_set camera_name",
        "/level_camera scene animation_set camera_name", "/surface_exit exit_number", "/giveall", "/kill_mongol",
        "/respawn_sister", "/backyard", "/plot", "/save save_name", "/load save_name", "/god",
        "setvar variable value", "getvar variable", "setting name [value]", "save_settings", "broadcast event [arguments]",
        "string string_name", "gamma [value]"
    };
    static final int[] LEVEL_IDS = DebugLevels.IDS;

    private DebugCommands() { }

    static int[] levelIds() { return Settings.legacyGame ? DebugLevelsTension.IDS : LEVEL_IDS; }

    static String[] commands() {
        if (!Settings.legacyGame) return COMMANDS;
        java.util.ArrayList<String> commands = new java.util.ArrayList<>();
        for (String usage : COMMANDS) {
            String name = usage.split(" ")[0];
            if (name.equals("/girl_execute")) { commands.add("/girl_executions"); continue; }
            if (name.equals("/chapters") || name.equals("/ole_born") || name.equals("/end") || name.equals("/void")
                || name.equals("/realm") || name.equals("/execution_start_cutscene")) continue;
            commands.add(usage);
        }
        return commands.toArray(new String[0]);
    }

    static void show(Activity activity, Consumer<String> execute) {
        AlertDialog[] owner = new AlertDialog[1];
        Consumer<String> dispatch = value -> { owner[0].dismiss(); execute.accept(value); };
        LinearLayout content = new LinearLayout(activity);
        content.setOrientation(LinearLayout.VERTICAL);
        int pad = Math.round(14 * activity.getResources().getDisplayMetrics().density);
        content.setPadding(pad, 0, pad, 0);
        Button levels = new Button(activity);
        levels.setText(words("Level selection", "Выбор уровня", "Level wählen", "Wybór poziomu"));
        levels.setOnClickListener(v -> showLevels(activity, dispatch));
        content.addView(levels);
        Button physics = new Button(activity);
        physics.setText(words("Physical boundaries", "Физические границы", "Physikalische Grenzen", "Granice fizyczne"));
        physics.setOnClickListener(v -> new AlertDialog.Builder(activity)
            .setTitle(physics.getText()).setItems(new String[] {words("Show", "Показать", "Anzeigen", "Pokaż"),
                words("Hide", "Скрыть", "Ausblenden", "Ukryj")}, (d, which) -> dispatch.accept("setvar show_physics " + (which == 0 ? "1" : "0")))
            .show());
        content.addView(physics);
        TextView label = new TextView(activity);
        label.setText(words("All commands (tap to select)", "Все команды (тап — выбор)",
            "Alle Befehle (zum Auswählen antippen)", "Wszystkie polecenia (dotknij, aby wybrać)"));
        label.setTextColor(Color.WHITE);
        label.setPadding(0, pad / 2, 0, pad / 2);
        content.addView(label);
        String[] commands = commands();
        ListView list = new ListView(activity);
        list.setAdapter(new ArrayAdapter<>(activity, android.R.layout.simple_list_item_1, commands));
        list.setOnItemClickListener((parent, view, position, id) -> command(activity, dispatch, commands[position]));
        int height = Math.round(activity.getResources().getDisplayMetrics().heightPixels * 0.48f);
        content.addView(list, new LinearLayout.LayoutParams(-1, height));
        owner[0] = new AlertDialog.Builder(activity).setTitle(words("Debug commands", "Отладочные команды", "Debug-Befehle", "Polecenia debugowania"))
            .setView(content).setNegativeButton(words("Close", "Закрыть", "Schließen", "Zamknij"), null).create();
        owner[0].show();
    }

    static void showLevels(Activity activity, Consumer<String> execute) {
        int[] ids = levelIds();
        String[] labels = new String[ids.length];
        for (int i = 0; i < labels.length; ++i) labels[i] = Settings.gameText(15 + ids[i]) + "  (" + ids[i] + ")";
        new AlertDialog.Builder(activity).setTitle(words("Level selection", "Выбор уровня", "Level wählen", "Wybór poziomu"))
            .setItems(labels, (d, which) -> execute.accept("/go " + ids[which]))
            .setNegativeButton(words("Cancel", "Отмена", "Abbrechen", "Anuluj"), null).show();
    }

    private static void command(Activity activity, Consumer<String> execute, String usage) {
        if (usage.startsWith("/go ")) { showLevels(activity, execute); return; }
        String[] parts = usage.split(" +");
        argument(activity, execute, usage, parts, 1, parts[0]);
    }

    private static void argument(Activity activity, Consumer<String> execute, String usage, String[] parts, int index, String command) {
        if (index == parts.length) { execute.accept(command); return; }
        String parameter = parts[index];
        String[] values = argumentValues(parameter);
        String[] labels = values.clone();
        for (int i = 0; i < labels.length; ++i) {
            if (labels[i].isEmpty()) labels[i] = words("Default", "По умолчанию", "Standard", "Domyślne");
            else if (parameter.equals("color") && !usage.startsWith("/realm "))
                labels[i] = Settings.gameText(Integer.parseInt(values[i]));
        }
        new AlertDialog.Builder(activity).setTitle(command + " · " + parameter)
            .setItems(labels, (d, which) -> argument(activity, execute, usage, parts,
                values[which].isEmpty() ? parts.length : index + 1, command + (values[which].isEmpty() ? "" : " " + values[which])))
            .setNeutralButton(words("Enter command…", "Ввести команду…", "Befehl eingeben…", "Wpisz polecenie…"),
                (d, which) -> enterCommand(activity, execute, usage, command + " "))
            .setNegativeButton(words("Cancel", "Отмена", "Abbrechen", "Anuluj"), null).show();
    }

    static String[] argumentValues(String parameter) {
        boolean optional = parameter.startsWith("[");
        String key = parameter.replace("[", "").replace("]", "");
        String[] values;
        switch (key) {
            case "girl_name": values = Settings.legacyGame ? DebugLevelsTension.GIRLS : DebugLevels.GIRLS; break;
            case "hunter_name": case "attacker_hunter_name": case "victim_hunter_name": values = Settings.legacyGame ? DebugLevelsTension.HUNTERS : DebugLevels.HUNTERS; break;
            case "automonolog_name": values = Settings.legacyGame ? DebugLevelsTension.AUTOMONOLOGS : DebugLevels.AUTOMONOLOGS; break;
            case "point_name": values = Settings.legacyGame ? DebugLevelsTension.POINTS : DebugLevels.POINTS; break;
            case "animation_set": values = Settings.legacyGame ? DebugLevelsTension.ANIMATIONS : DebugLevels.ANIMATIONS; break;
            case "camera_name": values = Settings.legacyGame ? DebugLevelsTension.CAMERAS : DebugLevels.CAMERAS; break;
            case "scene": values = Settings.legacyGame ? DebugLevelsTension.SCENES : DebugLevels.SCENES; break;
            case "variable": values = Settings.legacyGame ? DebugLevelsTension.VARIABLES : DebugLevels.VARIABLES; break;
            case "event": values = Settings.legacyGame ? DebugLevelsTension.EVENTS : DebugLevels.EVENTS; break;
            case "string_name": values = Settings.legacyGame ? DebugLevelsTension.STRINGS : DebugLevels.STRINGS; break;
            case "theme": values = Settings.legacyGame ? DebugLevelsTension.THEMES : DebugLevels.THEMES; break;
            case "name": values = new String[] {"PortFOV", "PortVeinBrightness", "PortTouchAdaptations", "PortShowMenuButton",
                "PortShowMenuLabels",
                "PortShowActionButton", "PortShowBodyButton", "PortDebugCommands", "MouseSensitivity", "InvertMouse",
                "GammaCorrection"}; break;
            case "color": case "chapter_num": values = numbers(7); break;
            case "zone": values = numbers(21); break;
            case "domain_index": values = numbers(12); break;
            case "hunter_index": values = numbers(Settings.legacyGame ? DebugLevelsTension.HUNTERS.length : DebugLevels.HUNTERS.length); break;
            case "exit_number": values = numbers(10); break;
            case "location_number":
                values = new String[levelIds().length];
                for (int i = 0; i < values.length; ++i) values[i] = Integer.toString(levelIds()[i]);
                break;
            case "amount": case "color_amount": values = new String[] {"1", "10", "100", "1000", "10000", "100000"}; break;
            case "num_of_hours": values = new String[] {"1", "2", "4", "6", "12", "24"}; break;
            case "save_name": values = new String[] {"debug", "debug2", "debug3", "quicksave"}; break;
            case "value": values = new String[] {"0", "1", "1.25", "1.5", "2", "5", "10", "50", "55", "70", "100", "125", "150", "200", "500"}; break;
            case "arguments": values = new String[] {""}; break;
            default: throw new IllegalArgumentException("Unknown command argument: " + parameter);
        }
        if (!optional || values.length == 1 && values[0].isEmpty()) return values;
        String[] choices = Arrays.copyOf(values, values.length + 1);
        System.arraycopy(choices, 0, choices, 1, values.length);
        choices[0] = "";
        return choices;
    }

    private static String[] numbers(int count) {
        String[] values = new String[count];
        for (int i = 0; i < count; ++i) values[i] = Integer.toString(i);
        return values;
    }

    private static void enterCommand(Activity activity, Consumer<String> execute, String usage, String initialValue) {
        EditText input = new EditText(activity);
        input.setSingleLine(true);
        input.setText(initialValue);
        input.setHint(usage);
        input.setSelection(input.length());
        AlertDialog dialog = new AlertDialog.Builder(activity).setTitle(usage).setView(input)
            .setPositiveButton(words("Execute", "Выполнить", "Ausführen", "Wykonaj"), null)
            .setNegativeButton(words("Cancel", "Отмена", "Abbrechen", "Anuluj"), null).create();
        dialog.setOnShowListener(d -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            String value = input.getText().toString().trim();
            if (!validCommand(value)) {
                input.setError(words("Enter one command, up to 511 UTF-8 bytes", "Введите одну команду длиной до 511 байт UTF-8",
                    "Einen Befehl mit bis zu 511 UTF-8-Bytes eingeben", "Wpisz jedno polecenie do 511 bajtów UTF-8"));
                return;
            }
            execute.accept(value);
            dialog.dismiss();
        }));
        dialog.show();
    }

    static boolean validCommand(String value) {
        if (value.isEmpty()) return false;
        int bytes = 0;
        for (int i = 0; i < value.length(); ++i) {
            char c = value.charAt(i);
            if (c < 32 || c == 127) return false;
            // JNI GetStringUTFChars encodes each UTF-16 surrogate as three bytes.
            bytes += c <= 0x7f ? 1 : c <= 0x7ff ? 2 : 3;
            if (bytes >= 512) return false;
        }
        return true;
    }

    private static String language() {
        return (Settings.gameLanguage.isEmpty() ? Locale.getDefault().getLanguage() : Settings.gameLanguage).toLowerCase(Locale.ROOT);
    }

    private static String words(String en, String ru, String de, String pl) {
        String language = language();
        return language.startsWith("ru") || language.equals("uk") || language.equals("be") ? ru
            : language.startsWith("de") || language.startsWith("german") ? de
            : language.startsWith("pl") || language.startsWith("polish") ? pl : en;
    }
}
