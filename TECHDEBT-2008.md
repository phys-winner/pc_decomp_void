# Техдолг: Tension (2008)

Изменения делаются только для игры 2009 года (`libvoid.so`). Всё, что нужно перенести
в Tension 2008 (`libvoid_tension.so`, `config/releases/tension.json`), записывается сюда:
что, где, почему не перенесено и что нужно для переноса. Общий код хоста отделяется
через `#ifndef VOID_RELEASE` (сборка Tension определяет `VOID_RELEASE`), Java — через
`GameActivity.Release.library` (`"void"` — 2009, `"void_tension"` — 2008).

Нативные подмены 2009 переносятся через двойников: `tools/lift_release.py --finish` ищет
в модулях выпуска тела функций 2009, совпадающие байт в байт, кроме переадресуемых полей
и переходов за пределы тела (таблица `TWINS`), и пишет их адреса и прочитанные из них
константы в `generated/<выпуск>/release_overrides.h`. Файлы хоста называют подменённые
функции и константы макросами (значения 2009 — под `#ifndef VOID_RELEASE`); подмена,
двойника которой у выпуска нет, для него просто не компилируется.

## Открыто

| # | Изменение 2009 | Где | Что нужно для 2008 |
|---|---|---|---|
| 12 | Предгенерация вариантов эффекта (`shaderwarm` в режиме сбора) и пакет ответов APK `assets/shaderpack.bin`; 520 рецептов прогрева GL-программ | `android/host/script.c` (`warm_shaders`: CEffectLibrary 2009, `0x16203D50`, `0x162D6794`), `d3dx9.c` (`void_shader_pregenerating`, `shader_pack_*`), `tools/build_game_apk.py` (`shader_pack`), `ShaderCache.java` (`installPack`), `build/shaderwarm` | Пакет и рецепты адресуются содержимым и общие для APK: Tension берёт те, что совпадут с его вариантами. Свои нужно собрать на локациях Tension на устройстве: найти двойников адресов CEffectLibrary (`tools/lift_release.py`), снять ограничение в `script.c`, прогнать `shaderwarm` и пройти локации |
| 15 | Нативные восстановление фрагментов и loop filter libtheora 1.0 | `android/host/theora_native.c` | В Video.dll 2008 другая сборка libtheora: двойников `sub_15018800` и `sub_15018ED0` нет, похожих тел близкого размера тоже. Найти эти функции 2008 и раскладку `oc_theora_state`, сверить пиксели с `VOID_THEORA=check` |
| 16 | Локальные копии x87 и горячая секция для SAT, PhysX sweep и частиц; профиль PGO | `tools/build_android.py` (`localize_fpu`, `HOT_FUNCTIONS`, `--pgo-use`), проверки в `physics_native.c` и `renderer_particle_native.c` | Это преобразование исходников сборки 2009 по именам 2009; выпуск собирается без него и без PGO. Нужны имена двойников (SAT `0x160D67E0`, sweep PhysX `0x1805B460` находятся), их константы и замеры |

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
| 10 | Переключатель «Отражения в воде» (`PortReflections`) | `android/host/renderer_native.c` (`RENDERER_SCENE_PASS`), `Controls.java`, `Settings.java` (`T_REFLECTIONS`) | Двойник прохода scene-render `0x1616AC50`. В игровом меню 2008 нет страниц настроек порта, поэтому переключатель стоит в панели порта («Дополнительные настройки») и действует сразу после её закрытия |
| 11 | Сервис компиляции шейдеров в отдельном процессе | `android/host/renderer_native.c` (`RENDERER_PASS_BUILD`, `RENDERER_PASS_SPLIT`, `ENGINE_LOG_LINE`), `d3dx9.c`, `GameActivity.java`, `ShaderCompilerService.java` | Двойники: построитель проходов `0x161FCA20`, одно разбиение `0x161F7FC0`, строка лога Engine `0x11108D20` (тот же слот `+0xC` таблицы лога, что и в 2009). Сервис загружает библиотеку той игры, которая его запустила, поэтому игроку Tension не нужно распаковывать `libvoid.so` |
| 13 | Подписи сердец при переносе Цвета из Памяти берут точку героя `pt_zone<N+1>` для зоны N, как оригинальный `render` экрана тела | `tools/patch_touch_native.py`, `patch_body_memory_counts` | У героя 2008 те же точки `pt_zone1`…`pt_zone21` (`Properties\Actors\hero_last.xml` совпадает с 2009). Условие `legacy` снято: польский `Scripts\ui\body.bin` e3a488ec → baf06f72, остальные переопределения не изменились; мок `tests/test_menu_refinements.py` одинаков для всех языков |
| 14 | Низкое качество текстур (`TextureQuality` 1) не уменьшает картинки интерфейса с цепочкой mip-уровней: превью локации на карте больше не рисуется в четверть своего места | `android/host/d3dx9.c`, `interface_picture`, `load_texture` | Картинки берутся из каталога `Textures.vfs` (тот же формат LP2C), путь сравнивается без учёта регистра (`Textures\UI` в 2008). В 2008 таких картинок 35, среди них все 22 превью локаций (в 2009 — 44) |
| — | Нативные ускорения | `vorbis_native.c`, `navmesh_native.c`, `renderer_native.c`, `renderer_region_native.c`, `renderer_adler_native.c`, `renderer_inflate_native.c`, `physics_native.c` | Двойники 24 тел 2009: libvorbisfile (open, read, clear, pcm_total, pcm_seek), полигоны листа навигационной сетки, SAT обоих модулей, добавление треугольника (`0x16081F90`: вторая из двух одинаковых копий, как и в 2009), Adler32 и inflate (сообщения zlib найдены как строки), отладочный вектор Engine, отладочная линия PhysX (`0x18159550`: отличается только номером строки для аллокатора, 0x118 вместо 0x121, на пути роста, который остаётся оригиналу) |

## Общее для обеих версий (не закрыто, учитывать при переносе)

- Ответы шейдерного кэша APK (`build/shadercache/results`) и `files/shaderlearned` общие и
  адресуются содержимым: вариант, скомпилированный одной игрой, годится и другой.
- `libtexconv.so`, `TextureService` и лицензии astcenc/etcpak входят в APK целиком.
- Образ `d3dx9_36.dll` лежит в APK дважды (`lifted` и `lifted-tension`), около 1,7 МБ сжатым.
