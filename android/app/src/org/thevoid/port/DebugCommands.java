package org.thevoid.port;

import android.app.Activity;
import android.app.AlertDialog;
import android.graphics.Color;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;
import java.text.Collator;
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
    static final String PHYSICS_COMMAND = "setvar show_physics value";
    static final int[] LEVEL_IDS = DebugLevels.IDS;

    private DebugCommands() { }

    static int[] levelIds() { return Settings.legacyGame ? DebugLevelsTension.IDS : LEVEL_IDS; }

    static String[] extraLabels() { return Settings.legacyGame ? DebugLevelsTension.EXTRA_LABELS : DebugLevels.EXTRA_LABELS; }

    static String[] levelCommands(int index) {
        int[] ids = levelIds();
        if (index < ids.length) return new String[] {"/go " + ids[index]};
        return (Settings.legacyGame ? DebugLevelsTension.EXTRA_COMMANDS : DebugLevels.EXTRA_COMMANDS)[index - ids.length].clone();
    }

    static void selectLevel(int index, Consumer<String[]> execute) {
        execute.accept(levelCommands(index));
    }

    static String[] commands() {
        java.util.ArrayList<String> commands = new java.util.ArrayList<>();
        for (String usage : COMMANDS) {
            if (Settings.legacyGame) {
                String name = usage.split(" ")[0];
                if (name.equals("/girl_execute")) { commands.add("/girl_executions"); continue; }
                if (name.equals("/chapters") || name.equals("/ole_born") || name.equals("/end") || name.equals("/void")
                    || name.equals("/realm") || name.equals("/execution_start_cutscene")) continue;
            }
            commands.add(usage);
        }
        commands.add(PHYSICS_COMMAND);
        return commands.toArray(new String[0]);
    }

    static String commandCategory(String usage) {
        switch (usage.split(" ")[0]) {
            case "/revert_girl": case "/add_hunter": case "/hunter_festival": case "/hunter_festival_end":
            case "/hunter_fights": case "/meet_hunter": case "/hunter_demo": case "/hunter_list":
            case "/fight_hunter": case "/trap_hunter": case "/execute_girl": case "/talk_hunter": case "/kill_mongol":
                return words("Brothers", "Братья", "Brüder", "Bracia");
            case "/damage": case "/open_zone": case "/turgor": case "/stronger": case "/add_fl": case "/add_al":
            case "/giveall": case "/god":
                return words("Hero and colour", "Герой и цвет", "Held und Farbe", "Bohater i kolor");
            case "/uplevel_camera": case "/level_camera": case "gamma":
                return words("Camera and graphics", "Камера и графика", "Kamera und Grafik", "Kamera i grafika");
            case "/flash": case "/openall": case "/save_map": case "/gopt": case "/go": case "/realm":
            case "/surface_exit": case "/backyard": case "/plot":
                return words("Locations and map", "Локации и карта", "Orte und Karte", "Lokacje i mapa");
            case "setvar": case "getvar": case "setting": case "save_settings": case "broadcast": case "string":
                return words("Settings and debugging", "Настройки и отладка", "Einstellungen und Debugging", "Ustawienia i debugowanie");
            case "/add_girl": case "/talk_girl": case "/kill_girl": case "/girl_execute": case "/girl_executions":
            case "/sister_die": case "/ole_born": case "/execute_girl_cutscene": case "/respawn_sister":
                return words("Sisters", "Сёстры", "Schwestern", "Siostry");
            case "/save": case "/load":
                return words("Saved games", "Сохранения", "Spielstände", "Zapisy gry");
            case "/chapters": case "/chapter": case "/automonolog": case "/end": case "/void": case "/final":
            case "/skip": case "/execution_start_cutscene":
                return words("Story and time", "Сюжет и время", "Handlung und Zeit", "Fabuła i czas");
            default: throw new IllegalArgumentException("Uncategorized command: " + usage);
        }
    }

    private static Collator alphabet() {
        return Collator.getInstance(new Locale(words("en", "ru", "de", "pl")));
    }

    static String[] categoryChoices() {
        java.util.ArrayList<String> categories = new java.util.ArrayList<>();
        for (String usage : commands()) {
            String category = commandCategory(usage);
            if (!categories.contains(category)) categories.add(category);
        }
        categories.sort(alphabet());
        categories.add(words("Enter command", "Ввод команды", "Befehl eingeben", "Wpisz polecenie"));
        return categories.toArray(new String[0]);
    }

    static String[] commandsInCategory(String category) {
        java.util.ArrayList<String> commands = new java.util.ArrayList<>();
        for (String usage : commands()) if (commandCategory(usage).equals(category)) commands.add(usage);
        Collator order = alphabet();
        commands.sort((a, b) -> order.compare(commandName(a), commandName(b)));
        return commands.toArray(new String[0]);
    }

    static String commandName(String usage) {
        if (usage.equals(PHYSICS_COMMAND)) return words("Physical boundaries and collisions", "Физические границы и коллизии", "Physikalische Grenzen und Kollisionen", "Granice fizyczne i kolizje");
        switch (usage.split(" ")[0]) {
            case "/revert_girl": return words("Reset a Brother's Sister choice", "Сбросить выбор Сестры у Брата", "Schwesterwahl eines Bruders zurücksetzen", "Zresetuj wybór Siostry przez Brata");
            case "/damage": return words("Damage the hero with colour", "Нанести герою урон цветом", "Helden mit Farbe verletzen", "Zadaj bohaterowi obrażenia kolorem");
            case "/flash": return words("Update the map", "Обновить карту", "Karte aktualisieren", "Odśwież mapę");
            case "/chapters": return words("Play a chapter scene", "Запустить сцену главы", "Kapitelszene abspielen", "Odtwórz scenę rozdziału");
            case "/chapter": return words("Set the story chapter", "Изменить главу сюжета", "Handlungskapitel setzen", "Ustaw rozdział fabuły");
            case "/add_girl": return words("Add a Sister", "Добавить Сестру", "Schwester hinzufügen", "Dodaj Siostrę");
            case "/talk_girl": return words("Talk to a Sister", "Поговорить с Сестрой", "Mit einer Schwester sprechen", "Porozmawiaj z Siostrą");
            case "/kill_girl": return words("Kill a Sister", "Убить Сестру", "Schwester töten", "Zabij Siostrę");
            case "/open_zone": return words("Unlock hearts", "Открыть сердца", "Herzen freischalten", "Odblokuj serca");
            case "/automonolog": return words("Play an inner monologue", "Запустить внутренний монолог", "Inneren Monolog abspielen", "Odtwórz monolog wewnętrzny");
            case "/add_hunter": return words("Add a Brother", "Добавить Брата", "Bruder hinzufügen", "Dodaj Brata");
            case "/turgor": return words("Enter Turgor", "Войти в Тургор", "Turgor erreichen", "Osiągnij Turgor");
            case "/stronger": return words("Strengthen the hero", "Усилить героя", "Helden stärken", "Wzmocnij bohatera");
            case "/hunter_festival": return words("Start the Brothers' festival", "Начать праздник Братьев", "Fest der Brüder starten", "Rozpocznij święto Braci");
            case "/hunter_festival_end": return words("End the Brothers' festival", "Завершить праздник Братьев", "Fest der Brüder beenden", "Zakończ święto Braci");
            case "/girl_execute": case "/girl_executions": return words("Start the Sisters' executions", "Начать казни Сестёр", "Hinrichtungen der Schwestern starten", "Rozpocznij egzekucje Sióstr");
            case "/hunter_fights": return words("Start fights between Brothers", "Начать бои между Братьями", "Kämpfe zwischen Brüdern starten", "Rozpocznij walki między Braćmi");
            case "/sister_die": return words("Play Sister's death", "Показать смерть Сестры", "Tod der Schwester abspielen", "Odtwórz śmierć Siostry");
            case "/ole_born": return words("Play Ole's birth", "Показать рождение Оле", "Oles Geburt abspielen", "Odtwórz narodziny Ole");
            case "/end": return words("Play the hero's finale", "Запустить финал героя", "Finale des Helden abspielen", "Odtwórz finał bohatera");
            case "/void": return words("Play the death of the Void", "Показать гибель Пустоты", "Untergang der Leere abspielen", "Odtwórz śmierć Pustki");
            case "/final": return words("Play a Sister's finale", "Запустить финал Сестры", "Finale einer Schwester abspielen", "Odtwórz finał Siostry");
            case "/meet_hunter": return words("Meet a Brother", "Встретить Брата", "Einem Bruder begegnen", "Spotkaj Brata");
            case "/hunter_demo": return words("Play a Brother's appearance", "Показать появление Брата", "Auftritt eines Bruders abspielen", "Odtwórz pojawienie się Brata");
            case "/openall": return words("Unlock all locations", "Открыть все локации", "Alle Orte freischalten", "Odblokuj wszystkie lokacje");
            case "/skip": return words("Advance game time", "Промотать игровое время", "Spielzeit vorspulen", "Przewiń czas gry");
            case "/save_map": return words("Save the map state", "Сохранить состояние карты", "Kartenzustand speichern", "Zapisz stan mapy");
            case "/gopt": return words("Move to a named point", "Перейти к именованной точке", "Zu einem benannten Punkt gehen", "Przejdź do nazwanego punktu");
            case "/go": return words("Go to a location", "Перейти в локацию", "Zu einem Ort wechseln", "Przejdź do lokacji");
            case "/realm": return words("Change a domain's colour", "Изменить цвет владения", "Farbe eines Gebiets ändern", "Zmień kolor domeny");
            case "/add_fl": return words("Add colour to Memory", "Добавить цвет в Память", "Farbe zur Erinnerung hinzufügen", "Dodaj kolor do Pamięci");
            case "/add_al": return words("Add colour to the Palette", "Добавить цвет в Палитру", "Farbe zur Palette hinzufügen", "Dodaj kolor do Palety");
            case "/hunter_list": return words("List Brothers and their indices", "Показать Братьев и их номера", "Brüder und ihre Nummern auflisten", "Pokaż Braci i ich numery");
            case "/execution_start_cutscene": return words("Play the execution opening", "Показать начало казни", "Beginn der Hinrichtung abspielen", "Odtwórz początek egzekucji");
            case "/execute_girl_cutscene": return words("Play a Sister's execution", "Показать казнь Сестры", "Hinrichtung einer Schwester abspielen", "Odtwórz egzekucję Siostry");
            case "/fight_hunter": return words("Make two Brothers fight", "Стравить двух Братьев", "Zwei Brüder kämpfen lassen", "Wywołaj walkę dwóch Braci");
            case "/trap_hunter": return words("Trap a Brother", "Поймать Брата в ловушку", "Bruder in eine Falle locken", "Złap Brata w pułapkę");
            case "/execute_girl": return words("Order a Brother to execute a Sister", "Отправить Брата на казнь Сестры", "Bruder zur Hinrichtung einer Schwester schicken", "Wyślij Brata na egzekucję Siostry");
            case "/talk_hunter": return words("Talk to a Brother", "Поговорить с Братом", "Mit einem Bruder sprechen", "Porozmawiaj z Bratem");
            case "/uplevel_camera": return words("Play a surface camera", "Запустить камеру на поверхности", "Oberflächenkamera abspielen", "Uruchom kamerę na powierzchni");
            case "/level_camera": return words("Play a scene camera", "Запустить камеру сцены", "Szenenkamera abspielen", "Uruchom kamerę sceny");
            case "/surface_exit": return words("Go to the surface", "Выйти на поверхность", "Zur Oberfläche gehen", "Wyjdź na powierzchnię");
            case "/giveall": return words("Give all hearts and colour", "Выдать все сердца и цвет", "Alle Herzen und Farbe geben", "Daj wszystkie serca i kolor");
            case "/kill_mongol": return words("Play Mongolfier's death", "Показать гибель Монгольфьера", "Mongolfiers Tod abspielen", "Odtwórz śmierć Mongolfiera");
            case "/respawn_sister": return words("Bring Sister back", "Вернуть Сестру", "Schwester zurückbringen", "Przywróć Siostrę");
            case "/backyard": return words("Go to the Backyard", "Перейти на задний двор", "Zum Hinterhof wechseln", "Przejdź na podwórko");
            case "/plot": return words("Go to the Plot", "Перейти на делянку", "Zum Grundstück wechseln", "Przejdź na działkę");
            case "/save": return words("Save the game", "Сохранить игру", "Spiel speichern", "Zapisz grę");
            case "/load": return words("Load a saved game", "Загрузить сохранение", "Spielstand laden", "Wczytaj zapis");
            case "/god": return words("Toggle invulnerability", "Переключить неуязвимость", "Unverwundbarkeit umschalten", "Przełącz nieśmiertelność");
            case "setvar": return words("Set a world variable", "Изменить переменную мира", "Weltvariable setzen", "Ustaw zmienną świata");
            case "getvar": return words("Read a world variable", "Прочитать переменную мира", "Weltvariable lesen", "Odczytaj zmienną świata");
            case "setting": return words("Read or change a setting", "Прочитать или изменить настройку", "Einstellung lesen oder ändern", "Odczytaj lub zmień ustawienie");
            case "save_settings": return words("Save settings", "Сохранить настройки", "Einstellungen speichern", "Zapisz ustawienia");
            case "broadcast": return words("Send a game event", "Отправить игровое событие", "Spielereignis senden", "Wyślij zdarzenie gry");
            case "string": return words("Look up game text", "Найти игровой текст", "Spieltext nachschlagen", "Wyszukaj tekst gry");
            case "gamma": return words("Read or change gamma", "Прочитать или изменить гамму", "Gamma lesen oder ändern", "Odczytaj lub zmień gammę");
            default: throw new IllegalArgumentException("Unknown command: " + usage);
        }
    }

    static String parameterName(String parameter) {
        switch (parameter.replace("[", "").replace("]", "")) {
            case "girl_name": return words("Sister", "Сестра", "Schwester", "Siostra");
            case "hunter_name": return words("Brother", "Брат", "Bruder", "Brat");
            case "attacker_hunter_name": return words("Attacking Brother", "Атакующий Брат", "Angreifender Bruder", "Atakujący Brat");
            case "victim_hunter_name": return words("Target Brother", "Брат-цель", "Angegriffener Bruder", "Atakowany Brat");
            case "color": return words("Colour", "Цвет", "Farbe", "Kolor");
            case "chapter_num": return words("Chapter", "Глава", "Kapitel", "Rozdział");
            case "zone": return words("Heart number", "Номер сердца", "Herznummer", "Numer serca");
            case "automonolog_name": return words("Monologue", "Монолог", "Monolog", "Monolog");
            case "hunter_index": return words("Brother index", "Номер Брата", "Brudernummer", "Numer Brata");
            case "num_of_hours": return words("Game hours", "Игровые часы", "Spielstunden", "Godziny gry");
            case "point_name": return words("Point", "Точка", "Punkt", "Punkt");
            case "location_number": return words("Location", "Локация", "Ort", "Lokacja");
            case "domain_index": return words("Domain index", "Номер владения", "Gebietsnummer", "Numer domeny");
            case "amount": case "color_amount": return words("Amount", "Количество", "Menge", "Ilość");
            case "theme": return words("Conversation topic", "Тема разговора", "Gesprächsthema", "Temat rozmowy");
            case "animation_set": return words("Animation set", "Набор анимаций", "Animationssatz", "Zestaw animacji");
            case "camera_name": return words("Camera", "Камера", "Kamera", "Kamera");
            case "scene": return words("Scene", "Сцена", "Szene", "Scena");
            case "exit_number": return words("Surface entrance", "Выход на поверхность", "Oberflächenausgang", "Wyjście na powierzchnię");
            case "save_name": return words("Save name", "Имя сохранения", "Spielstandname", "Nazwa zapisu");
            case "variable": return words("Variable", "Переменная", "Variable", "Zmienna");
            case "value": return words("Value", "Значение", "Wert", "Wartość");
            case "name": return words("Setting", "Настройка", "Einstellung", "Ustawienie");
            case "event": return words("Event", "Событие", "Ereignis", "Zdarzenie");
            case "arguments": return words("Event arguments", "Параметры события", "Ereignisparameter", "Argumenty zdarzenia");
            case "string_name": return words("Text identifier", "Идентификатор текста", "Textkennung", "Identyfikator tekstu");
            default: throw new IllegalArgumentException("Unknown command argument: " + parameter);
        }
    }

    static String commandHelp(String usage) {
        if (usage.equals(PHYSICS_COMMAND)) return usage + "\n\n" + words("1 shows collision boundaries; 0 hides them.",
            "1 — показать границы коллизий; 0 — скрыть.", "1 zeigt Kollisionsgrenzen; 0 blendet sie aus.", "1 pokazuje granice kolizji; 0 je ukrywa.");
        String[] parts = usage.split(" +");
        if (parts.length == 1) return usage + "\n\n" + words("No parameters.", "Без параметров.", "Keine Parameter.", "Bez parametrów.");
        StringBuilder help = new StringBuilder(usage).append("\n");
        for (int i = 1; i < parts.length; ++i) {
            String parameter = parts[i], key = parameter.replace("[", "").replace("]", "");
            help.append("\n").append(parameterName(parameter)).append(": ");
            if (key.equals("zone")) help.append(words("0–20 (21 hearts). Omit the number to unlock one random closed heart.",
                "0–20 (21 сердце). Без номера открывается одно случайное закрытое сердце.",
                "0–20 (21 Herzen). Ohne Nummer wird ein zufälliges geschlossenes Herz freigeschaltet.",
                "0–20 (21 serc). Bez numeru odblokowuje jedno losowe zamknięte serce."));
            else if (key.equals("chapter_num") || key.equals("color")) help.append("0–6.");
            else if (key.equals("exit_number")) help.append(words("0, 1 or 2; 255 is the original special entrance.",
                "0, 1 или 2; 255 — специальный вход оригинальной игры.", "0, 1 oder 2; 255 ist der ursprüngliche Sondereingang.",
                "0, 1 lub 2; 255 to specjalne wejście oryginalnej gry."));
            else if (key.equals("hunter_index")) help.append("0–").append((Settings.legacyGame ? DebugLevelsTension.HUNTERS.length : DebugLevels.HUNTERS.length) - 1).append('.');
            else help.append(words("Choose a value from the list or enter your own.", "Выберите значение из списка или введите своё.",
                "Wert aus der Liste wählen oder selbst eingeben.", "Wybierz wartość z listy lub wpisz własną."));
            if (parameter.startsWith("[") && !key.equals("zone")) help.append(' ').append(words("Optional.", "Необязательный параметр.", "Optional.", "Parametr opcjonalny."));
        }
        return help.toString();
    }

    static void show(Activity activity, Consumer<String[]> execute) {
        if (Settings.legacyGame) { showLegacy(activity, execute); return; }
        AlertDialog[] owner = new AlertDialog[1];
        Consumer<String[]> dispatch = value -> { owner[0].dismiss(); execute.accept(value); };
        Consumer<String> single = value -> dispatch.accept(new String[] {value});
        String[] choices = categoryChoices();
        ListView list = new ListView(activity);
        list.setAdapter(new ArrayAdapter<>(activity, android.R.layout.simple_list_item_1, choices));
        list.setOnItemClickListener((parent, view, position, id) -> {
            if (position == choices.length - 1) { enterCommand(activity, single, "", ""); return; }
            String category = choices[position];
            String[] commands = commandsInCategory(category);
            String[] labels = new String[commands.length];
            for (int i = 0; i < commands.length; ++i) labels[i] = commandName(commands[i]);
            new AlertDialog.Builder(activity).setTitle(category)
                .setItems(labels, (dialog, selected) -> command(activity, single, dispatch, commands[selected]))
                .setNegativeButton(words("Back", "Назад", "Zurück", "Wstecz"), null).show();
        });
        owner[0] = new AlertDialog.Builder(activity).setTitle(Settings.text(Settings.T_DEBUG_LIST))
            .setView(list).setNegativeButton(words("Close", "Закрыть", "Schließen", "Zamknij"), null).create();
        owner[0].show();
    }

    private static void showLegacy(Activity activity, Consumer<String[]> execute) {
        AlertDialog[] owner = new AlertDialog[1];
        Consumer<String[]> dispatch = value -> { owner[0].dismiss(); execute.accept(value); };
        Consumer<String> single = value -> dispatch.accept(new String[] {value});
        LinearLayout content = new LinearLayout(activity);
        content.setOrientation(LinearLayout.VERTICAL);
        int pad = Math.round(14 * activity.getResources().getDisplayMetrics().density);
        content.setPadding(pad, 0, pad, 0);
        TextView label = new TextView(activity);
        label.setText(words("All commands (tap to select)", "Все команды (тап — выбор)",
            "Alle Befehle (zum Auswählen antippen)", "Wszystkie polecenia (dotknij, aby wybrać)"));
        label.setTextColor(Color.WHITE);
        label.setPadding(0, pad / 2, 0, pad / 2);
        content.addView(label);
        String[] commands = commands();
        String[] labels = new String[commands.length];
        for (int i = 0; i < commands.length; ++i) labels[i] = commandName(commands[i]);
        ListView list = new ListView(activity);
        list.setAdapter(new ArrayAdapter<>(activity, android.R.layout.simple_list_item_1, labels));
        list.setOnItemClickListener((parent, view, position, id) -> command(activity, single, dispatch, commands[position]));
        int height = Math.round(activity.getResources().getDisplayMetrics().heightPixels * 0.48f);
        content.addView(list, new LinearLayout.LayoutParams(-1, height));
        owner[0] = new AlertDialog.Builder(activity).setTitle(Settings.text(Settings.T_DEBUG_LIST))
            .setView(content).setNegativeButton(words("Close", "Закрыть", "Schließen", "Zamknij"), null).create();
        owner[0].show();
    }

    static void showLevels(Activity activity, Consumer<String[]> execute) {
        int[] ids = levelIds();
        String[] extra = extraLabels();
        String[] labels = new String[ids.length + extra.length];
        for (int i = 0; i < ids.length; ++i) labels[i] = Settings.gameText(15 + ids[i]) + "  (" + ids[i] + ")";
        System.arraycopy(extra, 0, labels, ids.length, extra.length);
        new AlertDialog.Builder(activity).setTitle(words("Level selection", "Выбор уровня", "Level wählen", "Wybór poziomu"))
            .setItems(labels, (d, which) -> selectLevel(which, execute))
            .setNegativeButton(words("Cancel", "Отмена", "Abbrechen", "Anuluj"), null).show();
    }

    private static void command(Activity activity, Consumer<String> execute, Consumer<String[]> route, String usage) {
        new AlertDialog.Builder(activity).setTitle(commandName(usage)).setMessage(commandHelp(usage))
            .setPositiveButton(usage.contains(" ") ? words("Choose parameters", "Выбрать параметры", "Parameter wählen", "Wybierz parametry")
                : words("Execute", "Выполнить", "Ausführen", "Wykonaj"), (d, which) -> {
                if (usage.startsWith("/go ")) { showLevels(activity, route); return; }
                if (usage.equals(PHYSICS_COMMAND)) {
                    new AlertDialog.Builder(activity).setTitle(commandName(usage))
                        .setItems(new String[] {words("Show", "Показать", "Anzeigen", "Pokaż"),
                            words("Hide", "Скрыть", "Ausblenden", "Ukryj")},
                            (dialog, selected) -> execute.accept("setvar show_physics " + (selected == 0 ? "1" : "0")))
                        .setNegativeButton(words("Cancel", "Отмена", "Abbrechen", "Anuluj"), null).show();
                    return;
                }
                String[] parts = usage.split(" +");
                argument(activity, execute, usage, parts, 1, parts[0]);
            })
            .setNeutralButton(words("Enter command…", "Ввести команду…", "Befehl eingeben…", "Wpisz polecenie…"),
                (d, which) -> enterCommand(activity, execute, usage, usage.equals(PHYSICS_COMMAND) ? "setvar show_physics " : usage.split(" ")[0] + " "))
            .setNegativeButton(words("Cancel", "Отмена", "Abbrechen", "Anuluj"), null).show();
    }

    private static void argument(Activity activity, Consumer<String> execute, String usage, String[] parts, int index, String command) {
        if (index == parts.length) { execute.accept(command); return; }
        String parameter = parts[index];
        String[] values = argumentValues(parameter);
        String[] labels = values.clone();
        for (int i = 0; i < labels.length; ++i) {
            if (labels[i].isEmpty()) labels[i] = parameter.equals("[zone]")
                ? words("Random locked heart", "Случайное закрытое сердце", "Zufälliges geschlossenes Herz", "Losowe zamknięte serce")
                : words("Default", "По умолчанию", "Standard", "Domyślne");
            else if (parameter.equals("color") && !usage.startsWith("/realm "))
                labels[i] = Settings.gameText(Integer.parseInt(values[i]));
        }
        new AlertDialog.Builder(activity).setTitle(commandName(usage) + " · " + parameterName(parameter))
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
            case "exit_number": values = new String[] {"0", "1", "2", "255"}; break;
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
        input.setHint(usage.isEmpty() ? words("Command", "Команда", "Befehl", "Polecenie") : usage);
        input.setSelection(input.length());
        AlertDialog dialog = new AlertDialog.Builder(activity)
            .setTitle(usage.isEmpty() ? words("Enter command", "Ввод команды", "Befehl eingeben", "Wpisz polecenie") : commandName(usage)).setView(input)
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
        if (usage.isEmpty()) input.requestFocus();
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
