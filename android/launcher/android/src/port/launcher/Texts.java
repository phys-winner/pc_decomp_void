package port.launcher;

import android.content.Context;
import java.util.Iterator;
import java.util.Locale;
import org.json.JSONObject;

/** The launcher's words in English, Russian, German and Polish. The language follows the system
 *  (Ukrainian and Belarusian read Russian) unless the player picks one; the port's own texts in
 *  port.json fall back to English, then to their first language. */
final class Texts {
    static final String[] LANGUAGES = {"en", "ru", "de", "pl"};

    static final int PLAY = 0, RETURN = 1, READY = 2, MISSING = 3, NOT_FOUND_YET = 4, GAME_FILES = 5, FOLDER = 6,
        ARCHIVE = 7, IMPORT_FOLDER = 8, IMPORT_ARCHIVE = 9, FIXED_HINT = 10, SEARCHING = 11, READING = 12,
        NOTHING_FOUND = 13, IMPORT_TITLE = 14, IMPORT_BODY = 15, REPLACE = 16, COPY = 17, MOVE = 18, UNPACK = 19,
        USE_HERE = 20, PLAY_FROM_ARCHIVE = 21, ARCHIVE_STORED = 22, CANCEL = 23, OK = 24, STOP = 25, CONTINUE = 26,
        STOP_ASK = 27, PROGRESS = 28, DONE = 29, DELETE_ARCHIVE = 30, DELETE = 31, KEEP = 32, INTERRUPTED = 33,
        JOB_UNPACK = 34, JOB_COPY = 35, JOB_MOVE = 36, JOB_CLEAN = 37, JOB_INDEX = 38, JOB_TEXTURES = 39,
        PERM_FILES = 40, ALLOW = 41, PERM_LAN = 42, PICKER_DISABLED = 43, PICKER_MISSING = 44, ENABLE = 45,
        BUILTIN = 46, ALWAYS_BUILTIN = 47, BROWSER_FOLDER = 48, BROWSER_ZIP = 49, BROWSER_SELECT = 50,
        BROWSER_UP = 51, BROWSER_EMPTY = 52, BROWSER_DENIED = 53, INTERNAL = 54, DOWNLOADS = 55, FREE = 56,
        HAS_GAME = 57, ZIP_STORED = 58, RENDERER = 59, AVAILABLE = 60, UNAVAILABLE = 61, GPU = 62,
        R_ANDROID = 63, R_LIBRARIES = 64, R_VULKAN = 65, R_NO_VULKAN = 66, R_ADRENO = 67, R_CONVERTED = 68,
        N_FALLBACK = 69, N_FAILED = 70, N_APPLIES = 71, OPTIONS = 72, SKIP_INTRO = 73, SPACE = 74, CLEAN = 75,
        CLEAN_SCAN = 76, CLEAN_NONE = 77, CLEAN_ASK = 78, CLEAN_DONE = 79, ABOUT = 80, VERSION = 81, GITHUB = 82,
        RELEASES = 83, LICENSES = 84, LANGUAGE = 85, SYSTEM_LANGUAGE = 86, CHECK_UPDATES = 87, CHECKING = 88,
        UP_TO_DATE = 89, UPDATE_AVAILABLE = 90, DOWNLOAD = 91, WHATS_NEW = 92, SKIP_VERSION = 93,
        UPDATE_FAILED = 94, UPDATE_SIGNER = 95, UPDATE_AUTO = 96, UPDATE_BANNER = 97, TEXTURES = 98, TEX_WHY = 99,
        TEX_CONVERT = 100, TEX_UNDO = 101, TEX_DONE = 102, TEX_FOUND = 103, E_NOT_ZIP = 104, E_SPLIT = 105,
        E_NOT_FOUND = 106, E_UNSAFE = 107, E_METHOD = 108, E_ENCRYPTED = 109, E_CORRUPT = 110, E_FULL = 111,
        E_READ_ONLY = 112, E_IO = 113, E_CANCELLED = 114, E_REMOTE = 115, E_CHANGED = 116, E_SPACE = 117,
        E_NO_PATH = 118, E_PICKER = 119, GB = 120, MB = 121, LAST_EXIT = 122, CRASHED = 123, BUILD = 124,
        PERM_NOTIFY = 125, TEX_NOTHING = 126, NOT_IN_BUILD = 127, CHOOSE_PART = 128, DOWNLOADING = 129,
        PICKER_DISABLED_BUILTIN = 130, PICKER_MISSING_BUILTIN = 131, KB = 132, NEEDS_FILES_ACCESS = 133, REFUSED = 134,
        N_FAILED_DEFAULT = 135, LAN_TITLE = 136, LAN_WHY = 137, NOT_NOW = 138, NOTIFY_TITLE = 139, R_UNCHECKED = 140,
        R_CHECKING = 141, R_CRASH = 142, R_ERROR = 143, R_BC = 144, R_ROBUSTNESS = 145, R_PRESENT = 146, R_FEATURES = 147,
        R_NOT_TURNIP = 148, R_VULKAN13 = 149, R_UNFIT = 150, N_UNCHECKED = 151, TEX_REMOVE = 152, TEX_REMOVE_ASK = 153,
        TEX_GONE = 154, TURNIP_DRIVER = 155, TURNIP_BUILTIN = 156, TURNIP_CHOOSE = 157, TURNIP_RESET = 158,
        TURNIP_COPYING = 159, TURNIP_HINT = 160, E_TURNIP = 161,
        TEX_DXT_YES = 162, TEX_DXT_NO = 163, TEX_DXT_UNKNOWN = 164,
        TEX_ORIGINALS = 165, TEX_STATUS = 166, TEX_CHECK_FAILED = 167, COPY_DIAGNOSTICS = 168, DIAGNOSTICS_COPIED = 169, E_CLIPBOARD = 170, RETRY_CHECK = 171, OTHER_ARCHIVE = 172,
        FOLDER_FOR = 173, NO_EDITION = 174,
        GOG_IMPORT = 175, GOG_HINT = 176, GOG_PICK = 177, GOG_READING = 178, GOG_BAD_INPUT = 179,
        GOG_NOT_FOUND = 180, GOG_EDITION = 181, GOG_DESTINATION = 182, GOG_INSTALLING = 183, GROUP_PICK = 184,
        CHOOSE_GAME_FILES = 185;
    /** The last id: the table has one row per id (the selfcheck verifies it). */
    static final int LAST = CHOOSE_GAME_FILES;

    private static final String[][] TEXTS = {
        {"Play", "Играть", "Spielen", "Graj"},
        {"Return to the game", "Вернуться в игру", "Zurück zum Spiel", "Wróć do gry"},
        {"Ready to play", "Готово к запуску", "Bereit zum Spielen", "Gotowe do gry"},
        {"Files are missing: %s", "Не хватает файлов: %s", "Es fehlen Dateien: %s", "Brakuje plików: %s"},
        {"Not found yet", "Ещё не найдено", "Noch nicht gefunden", "Jeszcze nie znaleziono"},
        {"Game files", "Файлы игры", "Spieldateien", "Pliki gry"},
        {"Folder…", "Папка…", "Ordner…", "Folder…"},
        {"ZIP archive…", "ZIP-архив…", "ZIP-Archiv…", "Archiwum ZIP…"},
        {"Import from a folder…", "Импорт из папки…", "Aus einem Ordner importieren…", "Importuj z folderu…"},
        {"Import from a ZIP…", "Импорт из ZIP…", "Aus einem ZIP importieren…", "Importuj z ZIP…"},
        {"The port reads this part only from this folder.", "Порт читает эту часть только из этой папки.",
         "Der Port liest diesen Teil nur aus diesem Ordner.", "Port czyta tę część tylko z tego folderu."},
        {"Looking for the game…", "Ищу игру…", "Suche das Spiel…", "Szukam gry…"},
        {"Reading the archive…", "Читаю архив…", "Lese das Archiv…", "Czytam archiwum…"},
        {"No game files were found there.", "Там не найдено файлов игры.", "Dort wurden keine Spieldateien gefunden.",
         "Nie znaleziono tam plików gry."},
        {"Import the game files?", "Импортировать файлы игры?", "Spieldateien importieren?", "Zaimportować pliki gry?"},
        {"%1$s\n%2$s → %3$s\nFree there: %4$s", "%1$s\n%2$s → %3$s\nСвободно там: %4$s", "%1$s\n%2$s → %3$s\nDort frei: %4$s",
         "%1$s\n%2$s → %3$s\nWolne miejsce: %4$s"},
        {"The folder already holds files; they are replaced.", "В папке уже есть файлы — они будут заменены.",
         "Der Ordner enthält bereits Dateien; sie werden ersetzt.", "Folder zawiera już pliki — zostaną zastąpione."},
        {"Copy", "Скопировать", "Kopieren", "Kopiuj"},
        {"Move", "Переместить", "Verschieben", "Przenieś"},
        {"Unpack", "Распаковать", "Entpacken", "Rozpakuj"},
        {"Use this folder", "Использовать эту папку", "Diesen Ordner verwenden", "Użyj tego folderu"},
        {"Play from the archive", "Играть из архива", "Aus dem Archiv spielen", "Graj z archiwum"},
        {"The archive's files are not compressed: the game can read it as it is, without unpacking. Keep the archive "
             + "where it is. Compressed files beside it: %s.",
         "Файлы архива не сжаты: игра может читать его как есть, без распаковки. Не перемещайте архив. "
             + "Сжатых файлов, которые будут распакованы рядом: %s.",
         "Die Dateien im Archiv sind nicht komprimiert: Das Spiel kann es ohne Entpacken lesen. Lassen Sie das Archiv, "
             + "wo es ist. Komprimierte Dateien, die daneben entpackt werden: %s.",
         "Pliki archiwum nie są skompresowane: gra może czytać je bez rozpakowywania. Nie przenoś archiwum. "
             + "Skompresowane pliki rozpakowane obok: %s."},
        {"Cancel", "Отмена", "Abbrechen", "Anuluj"},
        {"OK", "OK", "OK", "OK"},
        {"Stop", "Прервать", "Stoppen", "Przerwij"},
        {"Continue", "Продолжить", "Fortsetzen", "Kontynuuj"},
        {"Stop? What was done so far is removed.", "Прервать? Сделанное будет удалено.",
         "Stoppen? Bisher Erledigtes wird entfernt.", "Przerwać? Dotychczasowa praca zostanie usunięta."},
        {"%1$s of %2$s", "%1$s из %2$s", "%1$s von %2$s", "%1$s z %2$s"},
        {"Done", "Готово", "Fertig", "Gotowe"},
        {"The game files are in %1$s.\n\nDelete the archive %2$s (%3$s)?", "Файлы игры в папке %1$s.\n\nУдалить архив %2$s (%3$s)?",
         "Die Spieldateien liegen in %1$s.\n\nDas Archiv %2$s (%3$s) löschen?", "Pliki gry są w %1$s.\n\nUsunąć archiwum %2$s (%3$s)?"},
        {"Delete", "Удалить", "Löschen", "Usuń"},
        {"Keep", "Оставить", "Behalten", "Zachowaj"},
        {"The last import was interrupted; its leftovers are removed.", "Прошлый импорт прервался — его остатки удалены.",
         "Der letzte Import wurde unterbrochen; seine Reste wurden entfernt.", "Poprzedni import został przerwany — jego pozostałości usunięto."},
        {"Unpacking", "Распаковка", "Entpacken", "Rozpakowywanie"},
        {"Copying", "Копирование", "Kopieren", "Kopiowanie"},
        {"Moving", "Перемещение", "Verschieben", "Przenoszenie"},
        {"Removing files", "Удаление файлов", "Dateien entfernen", "Usuwanie plików"},
        {"Preparing the archive", "Подготовка архива", "Archiv vorbereiten", "Przygotowanie archiwum"},
        {"Converting textures", "Конвертация текстур", "Texturen konvertieren", "Konwersja tekstur"},
        {"The game reads its files from the device's storage: allow access to all files.",
         "Игра читает свои файлы из памяти устройства: разрешите доступ ко всем файлам.",
         "Das Spiel liest seine Dateien aus dem Gerätespeicher: Erlauben Sie den Zugriff auf alle Dateien.",
         "Gra czyta swoje pliki z pamięci urządzenia: zezwól na dostęp do wszystkich plików."},
        {"Allow", "Разрешить", "Erlauben", "Zezwól"},
        {"Network games over Wi-Fi (LAN) need access to devices on the local network.",
         "Для сетевой игры по Wi-Fi (LAN) нужен доступ к устройствам в локальной сети.",
         "Netzwerkspiele über WLAN (LAN) brauchen Zugriff auf Geräte im lokalen Netzwerk.",
         "Gra sieciowa przez Wi-Fi (LAN) wymaga dostępu do urządzeń w sieci lokalnej."},
        {"The system file picker (Files) is turned off on this device.", "Системный выбор файлов («Файлы») отключён на этом устройстве.",
         "Die Dateiauswahl des Systems („Dateien“) ist auf diesem Gerät deaktiviert.",
         "Systemowy wybór plików („Pliki”) jest wyłączony na tym urządzeniu."},
        {"This device has no system file picker.", "На устройстве нет системного выбора файлов.",
         "Dieses Gerät hat keine Dateiauswahl des Systems.", "To urządzenie nie ma systemowego wyboru plików."},
        {"Turn on", "Включить", "Aktivieren", "Włącz"},
        {"Built-in browser", "Встроенный браузер", "Eingebauter Browser", "Wbudowana przeglądarka"},
        {"Always use the built-in file browser", "Всегда использовать встроенный браузер файлов",
         "Immer den eingebauten Dateibrowser verwenden", "Zawsze używaj wbudowanej przeglądarki plików"},
        {"Choose a folder", "Выберите папку", "Ordner wählen", "Wybierz folder"},
        {"Choose a ZIP archive", "Выберите ZIP-архив", "ZIP-Archiv wählen", "Wybierz archiwum ZIP"},
        {"Choose this folder", "Выбрать эту папку", "Diesen Ordner wählen", "Wybierz ten folder"},
        {"Up", "Вверх", "Nach oben", "W górę"},
        {"The folder is empty", "Папка пуста", "Der Ordner ist leer", "Folder jest pusty"},
        {"No access to this folder.", "Нет доступа к этой папке.", "Kein Zugriff auf diesen Ordner.", "Brak dostępu do tego folderu."},
        {"Internal storage", "Внутренняя память", "Interner Speicher", "Pamięć wewnętrzna"},
        {"Downloads", "Загрузки", "Downloads", "Pobrane"},
        {"%s free", "свободно %s", "%s frei", "wolne: %s"},
        {"game files: %s", "файлы игры: %s", "Spieldateien: %s", "pliki gry: %s"},
        {"not compressed: playable without unpacking", "без сжатия: можно играть без распаковки",
         "nicht komprimiert: ohne Entpacken spielbar", "bez kompresji: można grać bez rozpakowywania"},
        {"Renderer", "Отрисовка", "Renderer", "Renderer"},
        {"available", "доступно", "verfügbar", "dostępny"},
        {"unavailable", "недоступно", "nicht verfügbar", "niedostępny"},
        {"GPU: %1$s · Vulkan %2$s", "Видеочип: %1$s · Vulkan %2$s", "GPU: %1$s · Vulkan %2$s", "GPU: %1$s · Vulkan %2$s"},
        {"needs Android %1$d or newer (this is API %2$d)", "нужен Android %1$d или новее (здесь API %2$d)",
         "benötigt Android %1$d oder neuer (hier API %2$d)", "wymaga Androida %1$d lub nowszego (tu API %2$d)"},
        {"this build lacks %s", "в этой сборке нет %s", "in diesem Build fehlt %s", "w tej wersji brakuje %s"},
        {"the system driver offers Vulkan %1$s; %2$s is needed", "системный драйвер даёт Vulkan %1$s, а нужен %2$s",
         "der Systemtreiber bietet Vulkan %1$s; %2$s wird benötigt", "sterownik systemu oferuje Vulkan %1$s; potrzebny jest %2$s"},
        {"no Vulkan driver", "нет драйвера Vulkan", "kein Vulkan-Treiber", "brak sterownika Vulkan"},
        {"needs an Adreno %1$d–%2$d GPU; this is %3$s", "нужен видеочип Adreno %1$d–%2$d, здесь %3$s",
         "benötigt eine Adreno-GPU %1$d–%2$d; hier %3$s", "wymaga GPU Adreno %1$d–%2$d; tu %3$s"},
        {"cannot read the converted textures", "не читает сконвертированные текстуры",
         "kann die konvertierten Texturen nicht lesen", "nie odczyta skonwertowanych tekstur"},
        {"%1$s is unavailable here (%2$s): the game starts with %3$s.", "%1$s здесь недоступен (%2$s): игра запустится с %3$s.",
         "%1$s ist hier nicht verfügbar (%2$s): Das Spiel startet mit %3$s.", "%1$s jest tu niedostępny (%2$s): gra uruchomi się z %3$s."},
        {"The last start with %1$s did not reach the menu%2$s. If the game does not start, choose %3$s.",
         "Прошлый запуск с %1$s не дошёл до меню%2$s. Если игра не запускается, выберите %3$s.",
         "Der letzte Start mit %1$s erreichte das Menü nicht%2$s. Startet das Spiel nicht, wählen Sie %3$s.",
         "Ostatnie uruchomienie z %1$s nie dotarło do menu%2$s. Jeśli gra się nie uruchamia, wybierz %3$s."},
        {"The choice applies from the next start.", "Выбор применяется со следующего запуска.",
         "Die Auswahl gilt ab dem nächsten Start.", "Wybór obowiązuje od następnego uruchomienia."},
        {"Options", "Параметры", "Optionen", "Opcje"},
        {"Skip the opening videos", "Пропускать вступительные ролики", "Intro-Videos überspringen", "Pomijaj filmy wprowadzające"},
        {"Storage", "Место", "Speicher", "Miejsce"},
        {"Remove files the game does not use…", "Удалить файлы, которые игра не использует…",
         "Vom Spiel nicht genutzte Dateien entfernen…", "Usuń pliki, których gra nie używa…"},
        {"Counting…", "Подсчёт…", "Zähle…", "Liczenie…"},
        {"Nothing to remove.", "Удалять нечего.", "Nichts zu entfernen.", "Nie ma nic do usunięcia."},
        {"Remove %1$d files (%2$s)? Saves and settings stay.", "Удалить файлов: %1$d (%2$s)? Сохранения и настройки останутся.",
         "%1$d Dateien (%2$s) entfernen? Spielstände und Einstellungen bleiben.", "Usunąć plików: %1$d (%2$s)? Zapisy i ustawienia zostaną."},
        {"Freed: %s", "Освобождено: %s", "Freigegeben: %s", "Zwolniono: %s"},
        {"About", "О порте", "Über den Port", "O porcie"},
        {"Version %s", "Версия %s", "Version %s", "Wersja %s"},
        {"GitHub", "GitHub", "GitHub", "GitHub"},
        {"Releases", "Релизы", "Releases", "Wydania"},
        {"Licenses", "Лицензии", "Lizenzen", "Licencje"},
        {"Language", "Язык", "Sprache", "Język"},
        {"System", "Системный", "System", "Systemowy"},
        {"Check for updates", "Проверить обновления", "Nach Updates suchen", "Sprawdź aktualizacje"},
        {"Checking…", "Проверяю…", "Prüfe…", "Sprawdzam…"},
        {"This is the latest version.", "Это последняя версия.", "Das ist die neueste Version.", "To najnowsza wersja."},
        {"Version %1$s is available (installed: %2$s).", "Доступна версия %1$s (установлена %2$s).",
         "Version %1$s ist verfügbar (installiert: %2$s).", "Dostępna jest wersja %1$s (zainstalowana: %2$s)."},
        {"Download", "Скачать", "Herunterladen", "Pobierz"},
        {"What's new", "Что нового", "Neuigkeiten", "Co nowego"},
        {"Skip this version", "Пропустить эту версию", "Diese Version überspringen", "Pomiń tę wersję"},
        {"Could not check for updates: %s", "Не удалось проверить обновления: %s", "Update-Prüfung fehlgeschlagen: %s",
         "Nie udało się sprawdzić aktualizacji: %s"},
        {"This release is signed with another key: it cannot be installed over this one. Back up your saves before reinstalling.",
         "Этот релиз подписан другим ключом: поверх текущей версии он не установится. Перед переустановкой сохраните сохранения.",
         "Dieses Release ist mit einem anderen Schlüssel signiert und lässt sich nicht darüber installieren. Sichern Sie vor einer Neuinstallation Ihre Spielstände.",
         "To wydanie jest podpisane innym kluczem: nie zainstaluje się na obecnej wersji. Przed ponowną instalacją zrób kopię zapisów."},
        {"Check for updates automatically", "Проверять обновления автоматически", "Automatisch nach Updates suchen",
         "Automatycznie sprawdzaj aktualizacje"},
        {"Port update %s is available: see the launcher.", "Доступно обновление порта %s — подробности в лаунчере.",
         "Port-Update %s ist verfügbar: Details im Launcher.", "Dostępna aktualizacja portu %s — szczegóły w launcherze."},
        {"Textures", "Текстуры", "Texturen", "Tekstury"},
        {"This GPU cannot read the format of the game's textures: the processor unpacks every texture while a screen "
             + "loads, and in video memory it takes 4–8 times more room. Converted once into a format the GPU reads, "
             + "the textures load at once and need less memory.",
         "Видеочип не умеет читать формат текстур игры: каждую текстуру при загрузке распаковывает процессор, и в "
             + "видеопамяти она занимает в 4–8 раз больше места. Один раз сконвертированные в формат видеочипа, "
             + "текстуры загружаются сразу и требуют меньше памяти.",
         "Die GPU kann das Texturformat des Spiels nicht lesen: Der Prozessor entpackt jede Textur beim Laden, und im "
             + "Grafikspeicher braucht sie 4–8-mal mehr Platz. Einmal in ein GPU-Format konvertiert, laden die Texturen "
             + "sofort und brauchen weniger Speicher.",
         "GPU nie odczytuje formatu tekstur gry: procesor rozpakowuje każdą teksturę przy wczytywaniu, a w pamięci "
             + "wideo zajmuje ona 4–8 razy więcej miejsca. Raz skonwertowane do formatu GPU tekstury wczytują się od razu "
             + "i zajmują mniej pamięci."},
        {"Convert to %s", "Сконвертировать в %s", "In %s konvertieren", "Konwertuj do %s"},
        {"Delete the converted textures", "Удалить сконвертированные текстуры", "Konvertierte Texturen löschen",
         "Usuń skonwertowane tekstury"},
        {"Converted to %1$s: %2$s.", "Сконвертировано в %1$s: %2$s.", "In %1$s konvertiert: %2$s.", "Skonwertowano do %1$s: %2$s."},
        {"Textures to convert: %1$d (%2$s).", "Текстур для конвертации: %1$d (%2$s).", "Zu konvertierende Texturen: %1$d (%2$s).",
         "Tekstur do konwersji: %1$d (%2$s)."},
        {"This is not a ZIP archive, or it is damaged.", "Это не ZIP-архив, или он повреждён.",
         "Das ist kein ZIP-Archiv, oder es ist beschädigt.", "To nie jest archiwum ZIP albo jest uszkodzone."},
        {"The archive is split into parts: join them into one ZIP.", "Архив разбит на части: соберите его в один ZIP.",
         "Das Archiv ist in Teile aufgeteilt: Fügen Sie sie zu einem ZIP zusammen.", "Archiwum jest podzielone na części: połącz je w jeden ZIP."},
        {"No game files were found in it.", "В нём не найдено файлов игры.", "Darin wurden keine Spieldateien gefunden.",
         "Nie znaleziono w nim plików gry."},
        {"The archive has a path leading out of its folder: %s", "В архиве есть путь, ведущий за пределы его папки: %s",
         "Das Archiv enthält einen Pfad, der aus seinem Ordner führt: %s", "Archiwum zawiera ścieżkę wychodzącą poza jego folder: %s"},
        {"The archive is packed with %s; a ZIP packed with Deflate, Deflate64 or not packed is needed.",
         "Архив сжат методом %s; нужен ZIP со сжатием Deflate, Deflate64 или без сжатия.",
         "Das Archiv ist mit %s gepackt; nötig ist ein ZIP mit Deflate, Deflate64 oder ohne Kompression.",
         "Archiwum spakowano metodą %s; potrzebny jest ZIP z kompresją Deflate, Deflate64 lub bez kompresji."},
        {"The archive is encrypted.", "Архив зашифрован.", "Das Archiv ist verschlüsselt.", "Archiwum jest zaszyfrowane."},
        {"%s came out damaged (CRC): the archive is damaged.", "%s распаковался с ошибкой (CRC): архив повреждён.",
         "%s ist beschädigt (CRC): Das Archiv ist beschädigt.", "%s jest uszkodzony (CRC): archiwum jest uszkodzone."},
        {"The storage ran out of space.", "В хранилище кончилось место.", "Der Speicher ist voll.", "Zabrakło miejsca w pamięci."},
        {"The app cannot write there (%s): choose a folder in the device's storage.",
         "Приложение не может писать туда (%s): выберите папку в памяти устройства.",
         "Die App kann dort nicht schreiben (%s): Wählen Sie einen Ordner im Gerätespeicher.",
         "Aplikacja nie może tam zapisywać (%s): wybierz folder w pamięci urządzenia."},
        {"Error: %s", "Ошибка: %s", "Fehler: %s", "Błąd: %s"},
        {"Stopped; nothing was changed.", "Остановлено; ничего не изменено.", "Gestoppt; nichts wurde geändert.",
         "Zatrzymano; nic nie zmieniono."},
        {"This file is not on the device (a cloud?): copy it to the device first.",
         "Этого файла нет на устройстве (облако?): сначала скопируйте его на устройство.",
         "Diese Datei ist nicht auf dem Gerät (Cloud?): Kopieren Sie sie zuerst auf das Gerät.",
         "Tego pliku nie ma na urządzeniu (chmura?): najpierw skopiuj go na urządzenie."},
        {"Some files changed while working; nothing was removed.", "Часть файлов изменилась во время работы — ничего не удалено.",
         "Einige Dateien haben sich währenddessen geändert; nichts wurde entfernt.", "Część plików zmieniła się w trakcie — nic nie usunięto."},
        {"Not enough space: %1$s needed, %2$s free.", "Не хватает места: нужно %1$s, свободно %2$s.",
         "Nicht genug Platz: %1$s nötig, %2$s frei.", "Za mało miejsca: potrzeba %1$s, wolne %2$s."},
        {"This is not in the device's storage (a cloud?): choose a folder on the device.",
         "Это не в памяти устройства (облако?): выберите папку на устройстве.",
         "Das liegt nicht im Gerätespeicher (Cloud?): Wählen Sie einen Ordner auf dem Gerät.",
         "To nie jest w pamięci urządzenia (chmura?): wybierz folder na urządzeniu."},
        {"The file picker could not be opened: %s", "Не удалось открыть выбор файлов: %s", "Die Dateiauswahl ließ sich nicht öffnen: %s",
         "Nie udało się otworzyć wyboru plików: %s"},
        {"GB", "ГБ", "GB", "GB"},
        {"MB", "МБ", "MB", "MB"},
        {" (%s)", " (%s)", " (%s)", " (%s)"},
        {"the game crashed", "игра упала", "das Spiel ist abgestürzt", "gra uległa awarii"},
        {"build %s", "сборка %s", "Build %s", "kompilacja %s"},
        {"Android will ask to allow notifications: they show the progress of this work while the launcher is in the background.",
         "Android спросит разрешение на уведомления: в них виден ход работы, пока лаунчер свёрнут.",
         "Android fragt nach Benachrichtigungen: Sie zeigen den Fortschritt dieser Arbeit, solange der Launcher im Hintergrund ist.",
         "Android zapyta o zgodę na powiadomienia: pokazują postęp tej pracy, gdy launcher jest w tle."},
        {"There are no textures to convert.", "Текстур для конвертации нет.", "Es gibt keine Texturen zu konvertieren.", "Nie ma tekstur do konwersji."},
        {"This game is not available in the installed build.", "Эта игра недоступна в установленной сборке.",
         "Dieses Spiel ist im installierten Build nicht verfügbar.", "Ta gra nie jest dostępna w zainstalowanej wersji."},
        {"Where are these files?", "Где лежат эти файлы?", "Wo liegen diese Dateien?", "Gdzie są te pliki?"},
        {"Downloading %s", "Загрузка %s", "Lade %s herunter", "Pobieranie %s"},
        {"The system file picker (Files) is turned off on this device. The built-in browser is used instead.",
         "Системный выбор файлов («Файлы») отключён на этом устройстве. Вместо него используется встроенный браузер.",
         "Die Dateiauswahl des Systems („Dateien“) ist auf diesem Gerät deaktiviert. Stattdessen wird der eingebaute Browser verwendet.",
         "Systemowy wybór plików („Pliki”) jest wyłączony na tym urządzeniu. Zamiast niego używana jest wbudowana przeglądarka."},
        {"This device has no system file picker. The built-in browser is used instead.",
         "На устройстве нет системного выбора файлов. Вместо него используется встроенный браузер.",
         "Dieses Gerät hat keine Dateiauswahl des Systems. Stattdessen wird der eingebaute Browser verwendet.",
         "To urządzenie nie ma systemowego wyboru plików. Zamiast niego używana jest wbudowana przeglądarka."},
        {"KB", "КБ", "KB", "KB"},
        {"Needs access to all files", "Нужен доступ ко всем файлам", "Zugriff auf alle Dateien nötig", "Wymaga dostępu do wszystkich plików"},
        {"The last start stopped before the game began: %s", "Прошлый запуск остановился до начала игры: %s",
         "Der letzte Start brach vor Spielbeginn ab: %s", "Ostatnie uruchomienie zatrzymało się przed startem gry: %s"},
        {"The last start did not reach the menu%s.", "Прошлый запуск не дошёл до меню%s.", "Der letzte Start erreichte das Menü nicht%s.",
         "Ostatnie uruchomienie nie dotarło do menu%s."},
        {"Network games (LAN)", "Сетевая игра (LAN)", "Netzwerkspiele (LAN)", "Gra sieciowa (LAN)"},
        {"To find network games on your Wi-Fi (LAN) and join them, the game needs access to devices on the local network. "
             + "Android asks for it as \"Nearby devices\"; the game does not use your location. Without it the game still starts, "
             + "only without LAN games; you can allow it later on the launcher's card.",
         "Чтобы находить сетевые игры в вашей сети Wi-Fi (LAN) и подключаться к ним, игре нужен доступ к устройствам в "
             + "локальной сети. Android спросит его как «Устройства поблизости»; местоположение игра не использует. Без разрешения "
             + "игра тоже запустится, только без игры по LAN; разрешить можно позже на карточке лаунчера.",
         "Um Netzwerkspiele in Ihrem WLAN (LAN) zu finden und ihnen beizutreten, braucht das Spiel Zugriff auf Geräte im lokalen "
             + "Netzwerk. Android fragt danach als „Geräte in der Nähe“; Ihren Standort verwendet das Spiel nicht. Ohne die Erlaubnis "
             + "startet das Spiel trotzdem, nur ohne LAN-Spiele; Sie können sie später auf der Karte im Launcher erlauben.",
         "Aby znajdować gry sieciowe w twojej sieci Wi-Fi (LAN) i do nich dołączać, gra potrzebuje dostępu do urządzeń w sieci "
             + "lokalnej. Android zapyta o to jako „Urządzenia w pobliżu”; gra nie używa twojej lokalizacji. Bez tej zgody gra też "
             + "się uruchomi, tylko bez gry przez LAN; możesz zezwolić później na karcie launchera."},
        {"Not now", "Не сейчас", "Nicht jetzt", "Nie teraz"},
        {"Progress notifications", "Уведомления о ходе работы", "Fortschrittsbenachrichtigungen", "Powiadomienia o postępie"},
        {"not checked on this device yet", "ещё не проверен на этом устройстве", "auf diesem Gerät noch nicht geprüft",
         "jeszcze nie sprawdzony na tym urządzeniu"},
        {"checking the graphics driver…", "проверяю видеодрайвер…", "Grafiktreiber wird geprüft…", "sprawdzam sterownik grafiki…"},
        {"the driver check crashed", "проверка драйвера завершилась сбоем", "die Treiberprüfung ist abgestürzt",
         "sprawdzanie sterownika uległo awarii"},
        {"Vulkan is unavailable: %s", "Vulkan недоступен: %s", "Vulkan ist nicht verfügbar: %s", "Vulkan jest niedostępny: %s"},
        {"the GPU cannot sample BC (DXT) compressed textures, the format of the game's textures",
         "видеочип не читает сжатые текстуры BC (DXT), в которых хранятся текстуры игры",
         "die GPU kann keine BC-(DXT-)komprimierten Texturen lesen, das Format der Spieltexturen",
         "GPU nie odczytuje tekstur skompresowanych BC (DXT), w których zapisane są tekstury gry"},
        {"the driver lacks VK_EXT_robustness2", "в драйвере нет VK_EXT_robustness2", "dem Treiber fehlt VK_EXT_robustness2",
         "sterownikowi brakuje VK_EXT_robustness2"},
        {"the driver cannot show Vulkan on an Android surface", "драйвер не выводит Vulkan на экран Android",
         "der Treiber kann Vulkan nicht auf einer Android-Oberfläche anzeigen", "sterownik nie wyświetla Vulkana na powierzchni Androida"},
        {"missing Vulkan features DXVK needs: %s", "нет возможностей Vulkan, нужных DXVK: %s",
         "es fehlen Vulkan-Funktionen, die DXVK braucht: %s", "brak funkcji Vulkana potrzebnych DXVK: %s"},
        {"adrenotools did not load Turnip", "adrenotools не загрузил Turnip", "adrenotools hat Turnip nicht geladen",
         "adrenotools nie załadował Turnipa"},
        {"the driver offers Vulkan %s; DXVK needs Vulkan 1.3", "драйвер даёт Vulkan %s, а DXVK нужен Vulkan 1.3",
         "der Treiber bietet Vulkan %s; DXVK braucht Vulkan 1.3", "sterownik oferuje Vulkana %s; DXVK potrzebuje Vulkana 1.3"},
        {"the driver does not qualify", "драйвер не подходит", "der Treiber ist nicht geeignet", "sterownik się nie nadaje"},
        {"%1$s has not been checked on this device yet; if the game does not start, choose %2$s.",
         "%1$s ещё не проверен на этом устройстве; если игра не запустится, выберите %2$s.",
         "%1$s wurde auf diesem Gerät noch nicht geprüft; startet das Spiel nicht, wählen Sie %2$s.",
         "%1$s nie został jeszcze sprawdzony na tym urządzeniu; jeśli gra się nie uruchomi, wybierz %2$s."},
        {"Delete the original textures (%s)…", "Удалить оригинальные текстуры (%s)…", "Originaltexturen löschen (%s)…",
         "Usuń oryginalne tekstury (%s)…"},
        {"The game will use only the converted textures: the originals are removed from its files, which frees %s. "
             + "This cannot be undone: to convert again or into the other format, import the game files anew.",
         "Игра будет использовать только сконвертированные текстуры: оригиналы удаляются из её файлов, освободится %s. "
             + "Это необратимо: чтобы сконвертировать заново или в другой формат, файлы игры придётся импортировать снова.",
         "Das Spiel verwendet dann nur die konvertierten Texturen: Die Originale werden aus seinen Dateien entfernt, das gibt %s frei. "
             + "Das lässt sich nicht rückgängig machen: Um erneut oder in das andere Format zu konvertieren, importieren Sie die Spieldateien neu.",
         "Gra będzie używać tylko przekonwertowanych tekstur: oryginały zostaną usunięte z jej plików, co zwolni %s. "
             + "Tego nie można cofnąć: aby przekonwertować ponownie lub do innego formatu, zaimportuj pliki gry od nowa."},
        {"The original textures are deleted; the conversion can no longer be undone.",
         "Оригинальные текстуры удалены; конвертацию больше нельзя отменить.",
         "Die Originaltexturen sind gelöscht; die Konvertierung lässt sich nicht mehr rückgängig machen.",
         "Oryginalne tekstury zostały usunięte; konwersji nie można już cofnąć."},
        {"Turnip driver: %s", "Драйвер Turnip: %s", "Turnip-Treiber: %s", "Sterownik Turnip: %s"},
        {"the port's own", "встроенный в порт", "der des Ports", "wbudowany w port"},
        {"Own driver…", "Свой драйвер…", "Eigener Treiber…", "Własny sterownik…"},
        {"Use the port's driver", "Вернуть встроенный", "Treiber des Ports nehmen", "Użyj wbudowanego"},
        {"Copying the driver…", "Копирую драйвер…", "Kopiere den Treiber…", "Kopiuję sterownik…"},
        {"A Turnip driver package for adrenotools (a ZIP with meta.json) or its .so library. The driver check runs again for it.",
         "Пакет драйвера Turnip для adrenotools (ZIP с meta.json) или его библиотека .so. Проверка драйвера пройдёт для него заново.",
         "Ein Turnip-Treiberpaket für adrenotools (ein ZIP mit meta.json) oder seine .so-Bibliothek. Die Treiberprüfung läuft dafür erneut.",
         "Pakiet sterownika Turnip dla adrenotools (ZIP z meta.json) albo jego biblioteka .so. Sprawdzenie sterownika odbędzie się dla niego ponownie."},
        {"This is no Turnip driver: %s", "Это не драйвер Turnip: %s", "Das ist kein Turnip-Treiber: %s", "To nie jest sterownik Turnip: %s"},
        {"DXT is supported", "DXT поддерживается", "DXT wird unterstützt", "DXT jest obsługiwany"},
        {"DXT is not supported", "DXT не поддерживается", "DXT wird nicht unterstützt", "DXT nie jest obsługiwany"},
        {"DXT support could not be checked.", "Не удалось проверить поддержку DXT.",
         "Die DXT-Unterstützung konnte nicht geprüft werden.", "Nie udało się sprawdzić obsługi DXT."},
        {"Original textures", "Оригинальные текстуры", "Originaltexturen", "Oryginalne tekstury"},
        {"Converted to %s", "Конвертировано в %s", "In %s konvertiert", "Przekonwertowano do %s"},
        {"Texture check failed", "Не удалось проверить текстуры", "Texturprüfung fehlgeschlagen", "Nie udało się sprawdzić tekstur"},
        {"Copy diagnostic report", "Скопировать отчёт диагностики", "Diagnosebericht kopieren", "Kopiuj raport diagnostyczny"},
        {"Diagnostic report copied", "Отчёт диагностики скопирован", "Diagnosebericht kopiert", "Raport diagnostyczny skopiowany"},
        {"Could not copy the report", "Не удалось скопировать отчёт", "Bericht konnte nicht kopiert werden", "Nie udało się skopiować raportu"},
        {"Check again", "Повторить проверку", "Erneut prüfen", "Sprawdź ponownie"},
        {"Choose another archive…", "Выбрать другой архив…", "Anderes Archiv wählen…", "Wybierz inne archiwum…"},
        {"Folder for %s…", "Папка для %s…", "Ordner für %s…", "Folder dla %s…"},
        {"%1$s was not found in %2$s. The other editions' folders were kept.",
         "%1$s не найдена в %2$s. Папки остальных изданий сохранены.",
         "%1$s wurde in %2$s nicht gefunden. Die Ordner der anderen Editionen wurden beibehalten.",
         "Nie znaleziono %1$s w %2$s. Foldery pozostałych edycji zostały zachowane."},
        {"Install from GOG…", "Установить из GOG…", "Aus GOG installieren…", "Zainstaluj z GOG…"},
        {"Choose the offline setup EXE in device storage. Keep all its BIN files beside it. All files access is required.",
         "Выберите EXE офлайн-установщика в памяти устройства. Все его BIN должны лежать рядом. Нужен доступ ко всем файлам.",
         "Wählen Sie die Offline-Setup-EXE im Gerätespeicher. Alle BIN-Dateien müssen daneben liegen. Zugriff auf alle Dateien ist nötig.",
         "Wybierz EXE instalatora offline w pamięci urządzenia. Wszystkie pliki BIN muszą znajdować się obok. Wymagany jest dostęp do wszystkich plików."},
        {"Choose a GOG setup EXE", "Выберите EXE установщика GOG", "GOG-Setup-EXE wählen", "Wybierz EXE instalatora GOG"},
        {"Reading the GOG installer…", "Читаю установщик GOG…", "GOG-Installer wird gelesen…", "Odczytywanie instalatora GOG…"},
        {"Could not read the GOG installer. Check the complete EXE and all adjacent BIN files.",
         "Не удалось прочитать установщик GOG. Проверьте полную загрузку EXE и всех соседних BIN.",
         "GOG-Installer konnte nicht gelesen werden. Prüfen Sie die vollständige EXE und alle benachbarten BIN-Dateien.",
         "Nie można odczytać instalatora GOG. Sprawdź kompletny EXE i wszystkie sąsiednie pliki BIN."},
        {"This installer does not contain the game files required by this port.", "В этом установщике нет файлов игры, необходимых этому порту.",
         "Dieser Installer enthält nicht die von diesem Port benötigten Spieldateien.", "Ten instalator nie zawiera plików gry wymaganych przez ten port."},
        {"Choose the edition to install", "Выберите издание для установки", "Zu installierende Edition wählen", "Wybierz edycję do instalacji"},
        {"The installer is kept. Editions in the same package use one shared folder. The other game package's folder is kept. Choose another destination to use an empty folder or create a game folder inside a chosen parent.",
         "Установщик сохранится. Издания одного комплекта используют общую папку. Каталог другого комплекта останется прежним. Можно выбрать пустую папку или родительский каталог для новой папки игры.",
         "Der Installer bleibt erhalten. Editionen desselben Pakets verwenden einen gemeinsamen Ordner. Der Ordner des anderen Spielpakets bleibt erhalten. Als neues Ziel können Sie einen leeren Ordner oder den übergeordneten Ordner für einen neuen Spielordner wählen.",
         "Instalator zostanie zachowany. Edycje z jednego pakietu używają wspólnego folderu. Folder drugiego pakietu gry nie zmieni się. Możesz wybrać pusty folder lub katalog nadrzędny dla nowego folderu gry."},
        {"Installing from GOG", "Установка из GOG", "Installation aus GOG", "Instalacja z GOG"},
        {"Earlier editions used different folders. Choose one complete shared installation; existing files are kept.",
         "Раньше у изданий были разные папки. Выберите одну полную общую установку; существующие файлы сохранятся.",
         "Die Editionen verwendeten bisher verschiedene Ordner. Wählen Sie eine vollständige gemeinsame Installation; vorhandene Dateien bleiben erhalten.",
         "Edycje używały wcześniej różnych folderów. Wybierz jedną kompletną wspólną instalację; istniejące pliki zostaną zachowane."},
        {"Choose the game data folder or ZIP archive in the Game files section below.",
         "Укажите путь к игровым данным или ZIP-архив в разделе «Файлы игры» ниже.",
         "Wählen Sie den Spieldatenordner oder das ZIP-Archiv unten unter Spieldateien.",
         "Wskaż folder z danymi gry lub archiwum ZIP w sekcji Pliki gry poniżej."},
    };

    private static int column = -1;

    private Texts() { }

    /** The column of the chosen language: the player's choice, else the system's. */
    static synchronized int column(Context context) {
        if (column < 0) {
            String chosen = context != null ? State.read(context, State.CHOICES).getProperty("language", "") : "";
            column = index(chosen.isEmpty() ? system() : chosen);
        }
        return column;
    }

    static synchronized void reset() { column = -1; }

    static String system() {
        String language = Locale.getDefault().getLanguage();
        return "uk".equals(language) || "be".equals(language) ? "ru" : language;
    }

    static int index(String language) {
        for (int i = 0; i < LANGUAGES.length; ++i) if (LANGUAGES[i].equals(language)) return i;
        return 0;
    }

    static String language(Context context) { return LANGUAGES[column(context)]; }

    static String t(Context context, int id) { return TEXTS[id][column(context)]; }

    static String fmt(Context context, int id, Object... args) {
        return String.format(Locale.getDefault(), t(context, id), args);
    }

    /** A text of port.json: a plain string, or a map by language. */
    static String of(Context context, Object value) {
        if (value == null) return "";
        if (!(value instanceof JSONObject)) return String.valueOf(value);
        JSONObject map = (JSONObject) value;
        String text = map.optString(language(context), "");
        if (text.isEmpty()) text = map.optString("en", "");
        if (text.isEmpty()) {
            Iterator<String> keys = map.keys();
            if (keys.hasNext()) text = map.optString(keys.next(), "");
        }
        return text;
    }

    /** "4.2 GB", "37 MB", "0.4 MB" and, below 0.1 MB, kilobytes ("12 KB", "0.5 KB"). */
    static String size(Context context, long bytes) {
        Locale locale = Locale.getDefault();
        long b = Math.max(0, bytes);
        if (b >= 1_000_000_000L) return String.format(locale, "%.1f %s", b / 1e9, t(context, GB));
        if (b >= 100_000L) return String.format(locale, b >= 10_000_000L ? "%.0f %s" : "%.1f %s", b / 1e6, t(context, MB));
        return String.format(locale, b >= 10_000L || b == 0 ? "%.0f %s" : "%.1f %s", b / 1e3, t(context, KB));
    }

    static String failure(Context context, Failure f) {
        switch (f.code) {
        case Failure.NOT_ZIP: return t(context, E_NOT_ZIP);
        case Failure.SPLIT: return t(context, E_SPLIT);
        case Failure.NOT_FOUND: return t(context, E_NOT_FOUND);
        case Failure.UNSAFE: return fmt(context, E_UNSAFE, f.detail);
        case Failure.METHOD: return fmt(context, E_METHOD, f.detail);
        case Failure.ENCRYPTED: return t(context, E_ENCRYPTED);
        case Failure.CORRUPT: return fmt(context, E_CORRUPT, f.detail);
        case Failure.FULL: return f.required >= 0 && f.available >= 0
            ? fmt(context, E_SPACE, size(context, f.required), size(context, f.available)) : t(context, E_FULL);
        case Failure.READ_ONLY: return fmt(context, E_READ_ONLY, f.detail);
        case Failure.CANCELLED: return t(context, E_CANCELLED);
        case Failure.REMOTE: return t(context, E_REMOTE);
        case Failure.CHANGED: return t(context, E_CHANGED);
        default: return fmt(context, E_IO, f.detail);
        }
    }
}
