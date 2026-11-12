# Техдолг: Tension (2008)

2026-11-09: both game editions received their requested animated Play-button
palettes. This UI change did not change either native runtime.

Здесь учитываются переносы из игры 2009 года (`libvoid.so`) в Tension 2008
(`libvoid_tension.so`, `config/releases/tension.json`): что, где и как проверено.
По запросу пользователя 2026-10-31 перенесены оставшиеся пункты 12, 15 и 16.
Общий код хоста отделяется
через `#ifndef VOID_RELEASE` (сборка Tension определяет `VOID_RELEASE`), Java — через
`GameActivity.Release.library` (`"void"` — 2009, `"void_tension"` — 2008).

Нативные подмены 2009 переносятся через двойников: `tools/lift_release.py --finish` ищет
в модулях выпуска тела функций 2009, совпадающие байт в байт, кроме переадресуемых полей
и переходов за пределы тела (таблица `TWINS`), и пишет их адреса и прочитанные из них
константы в `generated/<выпуск>/release_overrides.h`. Файлы хоста называют подменённые
функции и константы макросами (значения 2009 — под `#ifndef VOID_RELEASE`); подмена,
двойника которой у выпуска нет, для него просто не компилируется.

## Shared launcher and settings — 0.5-dev

Both editions use the shared launcher, with separate installation paths and
profiles, distinct activity identities and three in-game port-settings pages.
The launcher language selects translated port labels and Unicode label fonts;
original game dialogue retains the installed distribution's language. Progress,
texture status and copyable diagnostics are available for both editions.

Both runtimes honor the large-address-space option through consistent guest
limits, PE flags and Win32 memory reports. Reused host subpages are zeroed and
failed commits release reservations. Production VM/PE/Win32 checks cover both
option states and 4/16 KiB branches, including the legacy negative control.

Menus and hit regions fit narrow screens, captions wrap, and opening-video
choices migrate independently per edition. All developer dialogs use an explicit
dark Material theme. Selected Pixel 10/API 37 tests cover both real game UIs and
four host-theme/day-night configurations. No game command was executed and all
347 player-profile files remained unchanged. Items 23 and 24 below remain open.

## Открыто

| # | Изменение 2009 | Почему не перенесено | Что требуется |
|---|---|---|---|
| 23 | Категории команд разработчика, локализованная алфавитная сортировка и общий ручной ввод | Текущий запрос относится к The Void; правило проекта сохраняет интерфейс Tension. В `DebugCommands.show` польская игра использует прежний список | Разрешение менять Tension, затем включить новый выбор категорий для её собственного списка команд и проверить интерфейс на устройстве; соответствие категорий обеим версиям уже покрыто Java-тестом |
| 24 | Образы x87 FNSAVE/FRSTOR вместо no-op в CRT-границах | `tools/fpu_state.py`, `android/host/fpu_state.c`: перенос из BioShock включён только для Android 2009; `VOID_RELEASE` и его генерация сохраняют прежнее поведение | Разрешение менять Tension, инвентаризация её собственных PE-инструкций, включение checked-маршрута и игровой прогон. Общая модель по-прежнему double + int64 shadows; нет полной 80-битной арифметики и истории FIP/FDP/FOP/sticky exceptions; неподдерживаемые TOP/tags отклоняются |

Пункты 18–21 закрыты
2026-11-06: код, обе сборки, дифференциальные проверки ПК/ARM64 и игровой smoke
на выбранном пользователем POCO X3 NFC. Подробности, границы приёмки и квитанции —
[итоги аудита и границы проверки](STATE.md).

## Перенесено в Tension: 2026-11-06

| # | Изменение | Где и чем проверено |
|---|---|---|
| 18 | Корректный FSINCOS: ST(0)=cos, ST(1)=sin | `tools/build_android.py:352`: downgrade удалён; 110 emissions в 7 собственных generated TU проверены/исправлены по pinned D9FB, ещё 15 shared compiler сохраняют правильный порядок. Native x86/Unicorn, все 240 физических C emissions, 8 холодных ARM64 ответов byte-exact с Windows; New Game, движение/обзор, прыжок и сцены 3/14 на POCO PASS |
| 19 | Driver-specific programcache с точным бюджетом | `android/host/shader_warm.c:113`, `:184`, `:211`, `:217`, `:234`, `:391`: общие housekeeping и header accounting. ПК и Android ARM64: stale/corrupt/.part, 384MiB/trim до 288MiB, реальные symlink/target сохранены. Реальная Tension удалила 3 seed-файла; warm process принял 543 Adreno binaries, 0 новых links, 5991/5991 и 0 unavailable |
| 20 | Buffer Lock без uint32 overflow | `android/host/d3d9_resource.c:895`: общая безопасная арифметика; по 5120 случаев каждого real release define на ПК и ARM64, независимый uint64 oracle и old-code negative control. Игровые сцены и lifecycle Tension PASS |
| 21 | Границы guest VirtualAlloc/VirtualFree/VirtualProtect | `android/host/memory.c:95`, `:195`, `:251`, `:301`: 64-bit validation до metadata/mutex. Оба выпуска: 3 overrun, 7 boundary pairs, соседи 4/16KiB на ПК/ARM64; загрузки `Park/foggyroots.xml`, `Mine/fort.xml`, прыжок/приземление и lifecycle Tension PASS |
| 22 | Флаги и ошибки EVENT query в общем GLES-хосте | `android/host/d3d9_resource.c`, `tests/test_query_flush.py`: при `flags=0` нет принудительного flush; `GL_WAIT_FAILED` возвращает `D3DERR_DEVICELOST` без записи результата. На ПК оба release define проходят 2304 прежних и 48 новых случаев; обе прежние ошибки независимо обнаруживаются негативными контролями. Production-функция ARM64 проверена с настоящими fence Mali-G615 и подставным отказом ожидания. Это не доказательство прироста FPS или воспроизведения отказа реального драйвера |

Граница приёмки пунктов 18–21: POCO X3 NFC, Android 16, Adreno 618. Отдельная
проверка пункта 22 на Mali-G615, Android 16: обе игры из нового локального APK
прошли запуск, новую игру, сенсорное движение/обзор, сцены 3/14 и Home/resume;
Tension — также вступление до управления и экран тела/Back. Прогрев каждой игры
4487/4487, 0 unavailable; загрузка новых библиотек подтверждена SHA-256.
Полное прохождение, полноценный игровой save/load, физический
режим 5–8 FPS и парный замер ускорения не приняты этими прогонами. В приёмке пунктов
18–21 консольные QA-файлы созданы, но `/load` не восстановил ожидаемую игровую сцену; обычный Save был недоступен
на отладочном маршруте. Это ограничение проверки не скрыто под статусом PASS.
В приёмке пунктов 18–21 исходные данные приложения восстановлены побайтно: 19826 файлов, 1603 symlink,
9 каталогов; все 57 оригинальных файлов игры сохранили SHA-256. Настройки ориентации
возвращены, временные QA-входы удалены по проверенным хешам; отдельный профиль сохранён.

Защита loose-подмен в `GameCleanup` применена также к польской версии по прямому запросу пользователя; она не является отложенным переносом. DocumentsUI и CP866 также применены к общему импорту обеих игр после отдельного явного разрешения пользователя 2026-11-05; regression и полный unpack-тест прошли. Это не отложенные переносы.

Полное прохождение и Mali-G720 не проверены;
историческая аппаратная проверка ниже относится к подтверждённому пользователем Honor LLD-L31,
Android 9, Mali-T830. Прирост FPS от PGO не измерялся в парном сравнении.

## Перенесено в Tension: 2026-10-31

| # | Изменение | Где | Что сделано для 2008 |
|---|---|---|---|
| 12 | Собственная предгенерация шейдеров и прогрев GL-программ | `script.c`, `d3dx9.c`, `tools/lift_release.py`, `tools/build_shader_cache.py`, `build/shadercache/pregen-results`, `build/shaderwarm` | Проверены двойники CEffectLibrary `0x162038B0` и `0x162D678C`. На Honor собраны все 115 штатных эффектов: 55 119 разных запросов. Дополнительно 55 114 PS3-запросов независимо скомпилированы с настоящими флагами рендеринга `0x8410`; ответы с другими флагами не переименовывались. Итоговый набор предгенерации: 114 635 ответов, из них 108 727 bytecode и 5908 штатных отказов компилятора Windows по ограничениям SM3; неожиданных ошибок нет. Все прежние 9130 ответов сохранены побайтно. Проверены индекс и содержимое пакета, а также перевод 15 953 уникальных стадий через production MojoShader. Общий набор GL-рецептов вырос с 520 до 530, конфликтов нет. Состояние сборщика изолировано между потоками; его запросы не отравляют отрицательный кэш обычного рендеринга |
| 15 | Нативные восстановление фрагментов и loop filter Theora | `android/host/theora_native.c`, `tools/lift_release.py`, `tests/test_theora_native.py` | Найдены функции Video.dll 2008 `0x150068D0` и `0x150070C0`; проверяются исходный образ и тела. Учтены отличающиеся INTRA/mode table и начало bounding table. Дифференциальный тест обеих версий: 5024 случая против исходного x86-кода, включая стек и пиксели. На Honor `VOID_THEORA=check`: 8 847 361 вызов восстановления и 15 361 вызов фильтра, различий нет. Проверено включение подмен именно в Android-сборку. Остальной декодер сохраняет исходное поведение |
| 16 | Локальные копии x87, горячий код и отдельный профиль PGO | `tools/build_android.py`, `physics_native.c`, `renderer_particle_native.c`, `tests/test_tension_fpu.py`, `build/pgo/tension.profdata` | Найдены и проверены имена и константы двойников SAT, sweep/tree/worker и частиц; перенесены преобразования SSE/x87. Полное состояние, память и выходы проверены в 181 276 случаях Tension и 214 922 случаях 2009. Профиль Tension собран отдельно на меню, Сестре, Туманных Корнях и Форте; счётчики VM, рендера и физики подтверждают выполнение маршрутов. Использован только последний полный накопительный снимок исправленного процесса; диагностические и ошибочные запуски исключены. Обе Android-библиотеки собраны, Tension — с собственным PGO. Профиль 2009 не подставляется вместо Tension; сравнительного замера FPS с PGO и без него нет |

Причина чёрного экрана после предисловия оказалась отдельной ошибкой камеры:
`getCameraFOV` в Tension использует `g34`, а прежний патч читал `g35` — добавленный
кэш выбранного Цвета. Начальное значение 0 давало нулевой FOV и NaN в проекции.
`tools/patch_touch_native.py` теперь определяет поле по оригинальному getter каждого
выпуска. На Honor обычная «Новая игра» → «Tak» → предисловие → первая передача
управления воспроизведена до исправления и проверена после него; изображение,
движение и повороты работают. Проверены также переходы в локации 3 и 14.
ASTC-пакет покрывает все 8298 исходных DXT-текстур Tension.

Дополнение к пункту 17: описанные выше маршруты Tension проверены на устройстве
2026-10-31. Отдельный тест разрушения скалы эффектом «Удар» в Tension не выполнялся.

## Перенесено в Tension: 2026-10-29

| # | Изменение | Где | Что сделано для 2008 |
|---|---|---|---|
| 17 | Атомарная сборка проходов шейдеров: защита от вылета эффекта «Удар» на холодном кэше | `android/host/renderer_native.c`, `RENDERER_PASS_BUILD`; `tests/test_shader_pass_atomic.py` | Построитель 2008 `0x161FCA20` выполняется целиком, недостающий HLSL компилируется синхронно. Проверены все четыре прямых вызова в RendererD3D: `0x161FF075` и `0x161FF19F` используют частичные проходы без проверки AL, как и 2009; ещё два вызова проверяют AL. Удалён прежний путь отложенной сборки. Общий тест проверяет завершённые проходы и стек на холодном/готовом кэше с реальными макросами обеих версий; отрицательные проверки отвергают возврат отложенной сборки. Аппаратной проверки Tension нет: на указанном тестовом телефоне установлена только игра 2009 |

## Перенесено в Tension: 2026-10-28

Проверено тестами и сборкой `libvoid_tension.so`. На устройстве не проверялось: Tension
нет на тестовом телефоне (POCO X3 NFC).

| # | Изменение | Где | Что сделано для 2008 |
|---|---|---|---|
| 1 | Шаг физики следует за частотой кадров: 1/60 с ниже 58 FPS, частота экрана выше 72 | `android/host/physx.c` (`ENGINE_SCENE_FETCH`, `ENGINE_STEP_RVA`, `CSCENE_SIMULATING`, `NXSCENE_*`) | Engine 2008 (PhysX 2.7.3): CScene::fetch `0x110DD050`, флаг «simulating» `+0x54`, setTiming и getTiming в слотах `+0x100` и `+0x104` NxScene, шаг 1/60 в `Engine+0x1261D8`. `tools/lift_release.py` находит их по шаблонам конструктора CScene и fetch (`SCENE_TIMING`, `SCENE_FETCH`) и сначала проверяет, что те же шаблоны дают значения 2009 |
| 2 | Недостающие варианты шейдеров компилируются на устройстве по умолчанию | `config/releases/tension.json` (`shared_modules`), `tools/lift_release.py`, `tools/build_android.py` (`module_dir`), `android/host/d3dx9.c` | Поднятый компилятор 2009 (`generated/d3dxcompiler-x86`, 6723 функции, код игры не вызывает) входит в таблицу диспетчеризации Tension и собирается в `libvoid_tension.so`, его образ `d3dx9_36.dll` лежит в `lifted-tension`. Прежний opt-in `device-compile` заменён общим отказом `no-device-compile`; ответы обеих игр — в `files/shaderlearned` (ключи по содержимому) |
| 3 | Сконвертированные текстуры ETC2/ASTC (`data/port-textures.tvt`) | `Launcher.java` (карточка для папки любой игры), `android/host/d3dx9.c` (`converted_find`) | Textures.vfs 2008 — тот же LP2C: конвертер на ПК находит в нём 8298 текстур DXT, 3,19 ГБ (в 2009 — 8825). 16 текстур 2008 в ETC2 и ASTC 4×4 — не хуже 23,99 и 37,93 дБ (пороги теста 22 и 35) |
| 4 | DXT-блоки как есть на видеочипах с S3TC | `android/host/d3d9_resource.c`, `s3tc_internal` | Ограничение снято. Как и в 2009, на устройстве с S3TC не проверялось |
| 5 | Ограничение FPS по режимам дисплея | `GameActivity.java`, `Launcher.java`, `d3d9_gl.c` | Предел передаётся и игре 2008, строка лаунчера видна для папки любой игры |
| 6 | Фильтрация ×4 по умолчанию: разовый перевод прежних ×16 в ×4 | `GameActivity.java` (`anisotropyDefaulted`) | Перевод выполняется при первом запуске любой из игр. Игра 2008 получает значение из настроек приложения (`Profile.setProps`), поэтому общий флаг перевода ей подходит |
| 7 | Быстрый поиск COM-объекта | `android/host/com.c`, `void_com_host` | Включён для обеих игр; на Tension не замерялся |
| 8 | Кэш обхода регионального освещения объекта, нативное взвешенное освещение и SAT | `android/host/renderer_region_native.c`, `tools/build_android.py` (`host_source`: помощник SAT из тела 2009) | Двойники: обход `0x16014350`, освещение `0x16013A20`, SAT RendererD3D `0x160D67E0` и Engine `0x1105BF40`; их эпсилоны `0x162D2A5C` и `0x1111EC68` (`0x3f7fffef`, как в 2009) |
| 9 | Папка образов используется, только если в ней есть все образы APK | `Images.java`, `complete()` | Проверка действует и для `lifted-tension`; `tests/test_images_fallback.py` проверяет обе папки |
| 10 | Переключатель «Отражения» (`PortReflections`) | `android/host/renderer_native.c` (`RENDERER_SCENE_PASS`), `Controls.java`, `Settings.java` (`T_REFLECTIONS`) | Двойник прохода scene-render `0x1616AC50`. В игровом меню 2008 нет страниц настроек порта, поэтому переключатель стоит в панели порта («Дополнительные настройки») и действует сразу после её закрытия. Подпись сокращена в обеих версиях 2026-10-31 |
| 11 | Сервис компиляции шейдеров в отдельном процессе | `android/host/renderer_native.c` (`RENDERER_PASS_BUILD`, `RENDERER_PASS_SPLIT`, `ENGINE_LOG_LINE`), `d3dx9.c`, `GameActivity.java`, `ShaderCompilerService.java` | Двойники: построитель проходов `0x161FCA20`, одно разбиение `0x161F7FC0`, строка лога Engine `0x11108D20` (тот же слот `+0xC` таблицы лога, что и в 2009). Сервис загружает библиотеку той игры, которая его запустила, поэтому игроку Tension не нужно распаковывать `libvoid.so` |
| 13 | Подписи сердец при переносе Цвета из Памяти берут точку героя `pt_zone<N+1>` для зоны N, как оригинальный `render` экрана тела | `tools/patch_touch_native.py`, `patch_body_memory_counts` | У героя 2008 те же точки `pt_zone1`…`pt_zone21` (`Properties\Actors\hero_last.xml` совпадает с 2009). Условие `legacy` снято: польский `Scripts\ui\body.bin` e3a488ec → baf06f72, остальные переопределения не изменились; мок `tests/test_menu_refinements.py` одинаков для всех языков |
| 14 | Низкое качество текстур (`TextureQuality` 1) не уменьшает картинки интерфейса с цепочкой mip-уровней: превью локации на карте больше не рисуется в четверть своего места | `android/host/d3dx9.c`, `interface_picture`, `load_texture` | Картинки берутся из каталога `Textures.vfs` (тот же формат LP2C), путь сравнивается без учёта регистра (`Textures\UI` в 2008). В 2008 таких картинок 35, среди них все 22 превью локаций (в 2009 — 44) |
| — | Нативные ускорения | `vorbis_native.c`, `navmesh_native.c`, `renderer_native.c`, `renderer_region_native.c`, `renderer_adler_native.c`, `renderer_inflate_native.c`, `physics_native.c` | Двойники 24 тел 2009: libvorbisfile (open, read, clear, pcm_total, pcm_seek), полигоны листа навигационной сетки, SAT обоих модулей, добавление треугольника (`0x16081F90`: вторая из двух одинаковых копий, как и в 2009), Adler32 и inflate (сообщения zlib найдены как строки), отладочный вектор Engine, отладочная линия PhysX (`0x18159550`: отличается только номером строки для аллокатора, 0x118 вместо 0x121, на пути роста, который остаётся оригиналу) |

## Общее для обеих версий (требования к сборке)

- Ответы шейдерного кэша APK (`build/shadercache/results`) и `files/shaderlearned` общие и
  адресуются содержимым: вариант, скомпилированный одной игрой, годится и другой.
- `libtexconv.so`, `TextureService` и лицензии astcenc/etcpak входят в APK целиком.
- Начиная с 0.4-dev образ `d3dx9_36.dll` хранится в APK один раз: `lifted/d3dx9_36.dll`.
  Индекс Tension ссылается на него через `apk:lifted/d3dx9_36.dll`; общий поднятый
  компилятор по-прежнему входит в обе библиотеки. Оригинальные `Game.exe` и
  `GameModule.dll` Tension берутся из польского дистрибутива 2008 с проверкой
  размера и SHA-256. Дедупликация и новый контракт установки проверены тестами
  `test_images_fallback.py` и `test_apk_package.py`.
