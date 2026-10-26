/* HUD state for the touch layer (hud.h): which of the game's cursor, helper
 * and screen images the last frame drew. The images are found by name in the
 * running release's data/Textures.vfs (LP2C container, the layout
 * tools/build_vfs_index.py reads) and recognised by size and FNV-1a 64 of
 * the file bytes when D3DX creates a texture from them. */
#include "host.h"
#include "hud.h"
#include "vfs_dir.h"
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include "hud_shaders.h"
#include "touch_native.h"

#define P(n) "textures\\ui\\ui_alimfa_pal" #n "_grad.tex"
#define M(n) "textures\\ui\\ui_flimfa_pal" #n "_grad.tex"
static const struct { const char *name; uint32_t tag, slot; } wanted[] = {
    {"textures\\cursor_paint.tex", HUD_CURSOR, 0},
    {"textures\\cursor_paint_with_limfa.tex", HUD_CURSOR_LYMPHA, 0},
    {"textures\\ui\\helper\\ui_helper_use.tex", HUD_USE, 0},
    {"textures\\ui\\helper\\ui_helper_use_arrow.tex", HUD_USE_ARROW, 0},
    {"textures\\ui\\helper\\ui_helper_paint.tex", HUD_PAINT, 0},
    {"textures\\ui\\helper\\ui_helper_trap.tex", HUD_TRAP, 0},
    {"textures\\ui\\helper\\ui_helper_wait.tex", HUD_WAIT, 0},
    {"textures\\ui\\helper\\ui_helper_wait_wheel.tex", HUD_WAIT, 0},
    {"textures\\ui\\helper\\ui_helper_death.tex", HUD_DEATH, 0},
    {"textures\\ui\\helper\\ui_helper_not_enough_limfa.tex", HUD_NO_LYMPHA, 0},
    {"textures\\ui\\helper\\ui_helper_not_enough_limfa_col.tex", HUD_NO_LYMPHA, 0},
    {"textures\\ui\\helper\\ui_helper_questlog.tex", HUD_QUESTLOG, 0},
    {"textures\\map_hero.tex", HUD_MAP, HUD_SLOT_HERO},
    {"textures\\map_girl.tex", HUD_MAP, 0},
    {"textures\\map_loc_cubemap.tex", HUD_MAP3D, 0},
    {"textures\\map_shaft_cubemap.tex", HUD_MAP3D, 0},
    {"textures\\ui\\ui_alimfa_left_up.tex", HUD_PALETTE | HUD_BODY_DECOR, 0},
    {"textures\\ui\\ui_flimfa_right_up.tex", HUD_MEMORY | HUD_BODY_DECOR, 0},
    {"textures\\ui\\mainmenu_options.tex", HUD_MENU, HUD_SLOT_MENU + 4},
    {"textures\\ui\\mainmenu_new.tex", HUD_MAINMENU, HUD_SLOT_MENU + 0},
    {"textures\\ui\\mainmenu_new_ru.tex", HUD_MAINMENU, HUD_SLOT_MENU + 0},
    {"textures\\ui\\mainmenu_continue.tex", HUD_PAUSE, HUD_SLOT_MENU + 6},
    {"textures\\ui\\mainmenu_continue_ru.tex", HUD_PAUSE, HUD_SLOT_MENU + 6},
    {"textures\\ui\\mainmenu_load.tex", 0, HUD_SLOT_MENU + 1},
    {"textures\\ui\\mainmenu_save.tex", 0, HUD_SLOT_MENU + 2},
    {"textures\\ui\\mainmenu_save_gray.tex", 0, HUD_SLOT_MENU + 3},
    {"textures\\ui\\mainmenu_credits.tex", 0, HUD_SLOT_MENU + 5},
    {"textures\\ui\\mainmenu_exit.tex", 0, HUD_SLOT_EXIT},
    {"textures\\ui\\ui_return_button.tex", HUD_BACK, HUD_SLOT_BACK},
    {"textures\\ui\\opt_glyph_video.tex", HUD_OPTIONS, 0},
    {"textures\\ui\\opt_glyph_audio.tex", HUD_OPTIONS, 0},
    {"textures\\ui\\opt_glyph_controls.tex", HUD_OPTIONS, 0},
    {"textures\\ui\\opt_glyph_audio_ru.tex", HUD_OPTIONS, 0},
    {"textures\\ui\\opt_glyph_controls_ru.tex", HUD_OPTIONS, 0},
    {"textures\\ui\\diary_quest_arrow_up.tex", HUD_ARROWS, 0},
    {"textures\\ui\\diary_quest_arrow_down.tex", HUD_ARROWS, 0},
    {"textures\\ui\\diary_marks_simbol_marks.tex", HUD_JOURNAL, 0},
    {"textures\\ui\\diary_marks_simbol_souls.tex", HUD_JOURNAL, 0},
    {"textures\\ui\\diary_marks_simbol_souls_gray.tex", HUD_JOURNAL, 0},
    {"textures\\ui\\diary_marks_simbol_time.tex", HUD_JOURNAL, 0},
    {"textures\\ui\\diary_marks_simbol_time_gray.tex", HUD_JOURNAL, 0},
    {"textures\\ui\\ui_girl_good_color1.tex", HUD_OBSCURA, 0},
    {"textures\\ui\\ui_girl_good_color2.tex", HUD_OBSCURA, 0},
    {"textures\\ui\\wheel\\ui_wheel_acc_manipulator.tex", HUD_WHEEL, HUD_SLOT_WHEEL},
    {"textures\\ui\\wheel\\ui_wheel_acc_manipulator_h.tex", HUD_WHEEL, HUD_SLOT_WHEEL},
    {"textures\\ui\\wheel\\ui_wheel_acc_manipulator_h_.tex", HUD_WHEEL, HUD_SLOT_WHEEL},
    {"textures\\ui\\loading\\loading_bg1.tex", HUD_LOADING, 0},
    {"textures\\ui\\loading\\loading_bg2.tex", HUD_LOADING, 0},
    {"textures\\ui\\loading\\loading_bg3.tex", HUD_LOADING, 0},
    {"textures\\ui\\loading\\loading_bg4.tex", HUD_LOADING, 0},
    {"textures\\ui\\loading\\loading_bg5.tex", HUD_LOADING, 0},
    {"textures\\blackbitmap.tex", HUD_SUBTITLE, HUD_SLOT_SUBTITLE},
    {"textures\\ui\\ui_alimfa_left_down.tex", HUD_BODY_DECOR, 0},
    {"textures\\ui\\ui_alimfa_left_up_bg.tex", HUD_BODY_DECOR, 0},
    {"textures\\ui\\ui_flimfa_right_down.tex", HUD_BODY_DECOR, 0},
    {"textures\\ui\\ui_flimfa_right_up_bg.tex", HUD_BODY_DECOR, 0},
    {"textures\\ui\\ui_giveall_button.tex", HUD_TAKEALL, 0},
    {P(0), HUD_BODY_DECOR, HUD_SLOT_PALETTE + 0}, {P(1), HUD_BODY_DECOR, HUD_SLOT_PALETTE + 1}, {P(2), HUD_BODY_DECOR, HUD_SLOT_PALETTE + 2},
    {P(3), HUD_BODY_DECOR, HUD_SLOT_PALETTE + 3}, {P(4), HUD_BODY_DECOR, HUD_SLOT_PALETTE + 4}, {P(5), HUD_BODY_DECOR, HUD_SLOT_PALETTE + 5},
    {P(6), HUD_BODY_DECOR, HUD_SLOT_PALETTE + 6},
    {M(0), HUD_BODY_DECOR, HUD_SLOT_MEMORY + 0}, {M(1), HUD_BODY_DECOR, HUD_SLOT_MEMORY + 1}, {M(2), HUD_BODY_DECOR, HUD_SLOT_MEMORY + 2},
    {M(3), HUD_BODY_DECOR, HUD_SLOT_MEMORY + 3}, {M(4), HUD_BODY_DECOR, HUD_SLOT_MEMORY + 4}, {M(5), HUD_BODY_DECOR, HUD_SLOT_MEMORY + 5},
    {M(6), HUD_BODY_DECOR, HUD_SLOT_MEMORY + 6},
};
#undef P
#undef M
#define WANTED (int)(sizeof wanted / sizeof wanted[0])
#define PREFIX 256u   /* bytes hashed first: most textures of a known size differ there */

static struct { uint32_t offset, size, tag, slot; uint64_t prefix, hash; } known[WANTED];
static int known_count;
static pthread_once_t once = PTHREAD_ONCE_INIT;
static uint32_t frame_tags, logged_tags, frame_slots;
static _Atomic uint32_t shown_tags, shown_frame, forced_tags, shown_slots;
static _Atomic uint32_t cursor_history;   /* bit i: the frame i presents ago showed a cursor */
static _Atomic int cursor_hidden;
static _Atomic uint32_t hidden_tags;
void void_hud_set_hidden(uint32_t tags) { atomic_store(&hidden_tags, tags); }
uint32_t void_hud_hidden(void) { return atomic_load(&hidden_tags); }
static _Atomic uint32_t path_ready_frames;
static _Atomic int controls_locked = 1;
/* The hero's script asks ControlsLocked as it runs. A scene that only
 * shows the place (a brother's coming, a flight over it) runs no hero:
 * nothing asks, and the last answer would stay whatever it was before. */
static _Atomic uint32_t lock_reads;
static uint32_t presents_unread, unread_logged;
#define UNREAD_PRESENTS 12
static float slot_values[HUD_SLOTS][HUD_SLOT_FLOATS];
static pthread_mutex_t slot_lock = PTHREAD_MUTEX_INITIALIZER;

#ifdef VOID_RELEASE
#define sub_101BF450 sub_101BE240
#define sub_101BF450_lifted sub_101BE240_lifted
#endif
/* Observe the original property getter, preserving its guest ABI and result. */
void sub_101BF450_lifted(void);
void sub_101BF450(void)
{
    uint32_t context = g_ecx;
    sub_101BF450_lifted();
    atomic_store(&controls_locked, (g_eax & 0xff) != 0);
    atomic_fetch_add_explicit(&lock_reads, 1, memory_order_relaxed);
    void_touch_observe_context(context);
}

static uint64_t fnv64(const uint8_t *p, size_t n)
{
    uint64_t h = 0xCBF29CE484222325ull;
    for (size_t i = 0; i < n; ++i) h = (h ^ p[i]) * 0x100000001B3ull;
    return h;
}

uint32_t void_hud_shader_tag_for(const uint8_t *data, uint32_t size)
{
    uint64_t hash = fnv64(data, size);
    for (size_t i = 0; i < sizeof obscura_shaders / sizeof *obscura_shaders; ++i)
        if (obscura_shaders[i] == hash) return HUD_OBSCURA;
    return 0;
}

static void found(const char *path, uint32_t offset, uint32_t size, void *ctx)
{
    (void)ctx;
    for (int w = 0; w < WANTED; ++w) {
        if (strcasecmp(path, wanted[w].name)) continue;
        known[w].size = size;
        known[w].offset = offset;
    }
}

static void load_table(void)
{
    FILE *f = void_vfs_open("Textures.vfs");
    if (f && !void_vfs_scan(f, "textures", found, NULL)) void_log("[hud] Textures.vfs: unreadable directory");
    for (int i = 0; i < WANTED; ++i) {
        char path[1200];
        snprintf(path, sizeof path, "C:\\Games\\The Void\\data\\%s", wanted[i].name);
        char *host = void_path_to_host(path);
        FILE *loose = host ? fopen(host, "rb") : NULL;
        free(host);
        FILE *image = loose ? loose : f;
        uint32_t offset = known[i].offset;
        if (loose) {
            long size = fseek(loose, 0, SEEK_END) ? -1 : ftell(loose);
            known[i].size = size > 0 && (uint64_t)size <= UINT32_MAX ? (uint32_t)size : 0;
            offset = 0;
        }
        uint8_t *data = known[i].size && image ? malloc(known[i].size) : NULL;
        if (data && fseek(image, (long)offset, SEEK_SET) == 0 && fread(data, 1, known[i].size, image) == known[i].size) {
            known[i].prefix = fnv64(data, known[i].size < PREFIX ? known[i].size : PREFIX);
            known[i].hash = fnv64(data, known[i].size);
            known[i].tag = wanted[i].tag;
            known[i].slot = wanted[i].slot;
            ++known_count;
        }
        free(data);
        if (loose) fclose(loose);
    }
    if (f) fclose(f);
    void_log("[hud] %d of %d cursor, helper and screen images recognised by content", known_count, WANTED);
}

uint32_t void_hud_tag_for(const uint8_t *data, uint32_t size, uint32_t *slot)
{
    pthread_once(&once, load_table);
    uint64_t prefix = 0, h = 0;
    int prefixed = 0, hashed = 0;
    uint32_t tag = 0, s = 0;
    for (int i = 0; i < WANTED; ++i) {
        if (known[i].size != size || !(known[i].tag | known[i].slot)) continue;
        if (!prefixed) { prefix = fnv64(data, size < PREFIX ? size : PREFIX); prefixed = 1; }
        if (prefix != known[i].prefix) continue;
        if (!hashed) { h = fnv64(data, size); hashed = 1; }
        if (h != known[i].hash) continue;
        tag |= known[i].tag;
        if (known[i].slot) s = known[i].slot;
    }
    if (slot) *slot = s;
    if (tag && (tag & ~logged_tags)) {   /* each image once: the HUD loads them at start */
        logged_tags |= tag;
        void_log("[hud] image of %u bytes loaded: tag %X", size, tag);
    }
    return tag;
}

/* Draws and presents happen on the rendering thread. */
void void_hud_draw(uint32_t tags) { frame_tags |= tags; }

void void_hud_slot_draw(uint32_t slot, const float *ps, const float *vs, const float rect[4])
{
    if (!slot || slot >= HUD_SLOTS) return;
    frame_slots |= 1u << slot;
    pthread_mutex_lock(&slot_lock);
    memcpy(slot_values[slot], ps, 32 * sizeof(float));
    memcpy(slot_values[slot] + 32, vs, 32 * sizeof(float));
    memcpy(slot_values[slot] + 64, rect, 4 * sizeof(float));
    pthread_mutex_unlock(&slot_lock);
}

/* A film: Theora decoded in the last 3 s or so, and a frame of a few draws
 * (the film's quad, maybe a subtitle), also while the film holds a still
 * picture and decodes nothing. A film inside a scene (a Sister's obscura
 * over the map) comes with the scene's many draws. */
static atomic_int video_decoded;
static uint32_t video_recent;   /* presents left of the 3 s */

void void_hud_video_frame(void) { atomic_store_explicit(&video_decoded, 1, memory_order_relaxed); }

void void_hud_present(uint32_t draws)
{
    uint32_t ready = atomic_load(&path_ready_frames);
    if (ready) { frame_tags |= HUD_PATH_READY; atomic_fetch_sub(&path_ready_frames, 1); }
    if (atomic_exchange(&video_decoded, 0)) video_recent = 180;
    else if (video_recent) --video_recent;
    if (video_recent && draws <= 8) frame_tags |= HUD_VIDEO;
    if (atomic_exchange_explicit(&lock_reads, 0, memory_order_relaxed)) presents_unread = 0;
    else if (presents_unread <= UNREAD_PRESENTS) ++presents_unread;
    int unread = presents_unread > UNREAD_PRESENTS;
    if (unread != (int)unread_logged) {
        unread_logged = (uint32_t)unread;
        void_log("[hud] the hero's controls %s", unread ? "unasked: a scene without him, locked" : "asked again");
    }
    if (atomic_load(&controls_locked) || unread) frame_tags |= HUD_CONTROL_LOCKED;
    atomic_store(&shown_tags, frame_tags | atomic_load(&forced_tags));
    atomic_store(&cursor_history, atomic_load(&cursor_history) << 1 | ((frame_tags & (HUD_CURSOR | HUD_CURSOR_LYMPHA)) != 0));
    atomic_store(&shown_slots, frame_slots);
    atomic_fetch_add(&shown_frame, 1);
    frame_tags = 0;
    frame_slots = 0;
}

void void_hud_force(uint32_t tags) { atomic_store(&forced_tags, tags); }

int void_hud_cursor_recent(int frames)
{
    uint32_t mask = frames >= 32 ? ~0u : (1u << frames) - 1u;
    return (atomic_load(&cursor_history) & mask) != 0;
}

uint32_t void_hud_state(uint32_t *frame)
{
    if (frame) *frame = atomic_load(&shown_frame);
    return atomic_load(&shown_tags);
}

uint32_t void_hud_slots(float out[HUD_SLOTS][HUD_SLOT_FLOATS])
{
    pthread_mutex_lock(&slot_lock);
    memcpy(out, slot_values, sizeof slot_values);
    pthread_mutex_unlock(&slot_lock);
    return atomic_load(&shown_slots);
}

void void_hud_set_cursor_hidden(int hidden) { atomic_store(&cursor_hidden, hidden ? 1 : 0); }
static _Atomic uint32_t frame_period;
void void_hud_set_frame_period(uint32_t microseconds) { atomic_store(&frame_period, microseconds > 100000u ? 100000u : microseconds); }
uint32_t void_hud_frame_period(void) { return atomic_load(&frame_period); }
static _Atomic uint64_t hold_until;
void void_hud_hold_picture(uint32_t ms)
{
    if (ms > 4000) ms = 4000;
    atomic_store(&hold_until, ms ? void_monotonic_ns() + (uint64_t)ms * 1000000ull : 0);
}
int void_hud_picture_held(void)
{
    uint64_t until = atomic_load(&hold_until);
    return until && void_monotonic_ns() < until;
}
int void_hud_cursor_hidden(void) { return atomic_load(&cursor_hidden); }
void void_hud_path_ready(void) { atomic_store(&path_ready_frames, 8); }
