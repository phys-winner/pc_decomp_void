/* What the game shows that the touch layer reacts to: the paint cursor (any
 * screen with a cursor: menus, the body, the map, painting), the helper
 * icons the HUD draws at the centre of the screen when the hero can interact
 * with something, and images that tell the screens apart. Recognised by
 * content: the game loads them as DDS files through
 * D3DXCreateTextureFromFileInMemoryEx (hud.c). */
#ifndef VOID_HUD_H
#define VOID_HUD_H
#include <stdint.h>

enum {
    HUD_CURSOR = 1u << 0,       /* cursor_paint */
    HUD_USE = 1u << 1,          /* ui/helper/ui_helper_use */
    HUD_USE_ARROW = 1u << 2,    /* ui/helper/ui_helper_use_arrow */
    HUD_PAINT = 1u << 3,        /* ui/helper/ui_helper_paint */
    HUD_TRAP = 1u << 4,         /* ui/helper/ui_helper_trap */
    HUD_WAIT = 1u << 5,         /* ui/helper/ui_helper_wait, _wait_wheel */
    HUD_DEATH = 1u << 6,        /* ui/helper/ui_helper_death */
    HUD_NO_LYMPHA = 1u << 7,    /* ui/helper/ui_helper_not_enough_limfa, _col */
    HUD_QUESTLOG = 1u << 8,     /* ui/helper/ui_helper_questlog */
    HUD_CURSOR_LYMPHA = 1u << 9,   /* cursor_paint_with_limfa: the brush carries a colour */
    HUD_MAP = 1u << 10,         /* map_hero, map_girl: the map's markers */
    HUD_PALETTE = 1u << 11,     /* ui/ui_alimfa_left_up: the palette (painting, the body) */
    HUD_MEMORY = 1u << 12,      /* ui/ui_flimfa_right_up: the Memory, so the hero's body */
    HUD_MENU = 1u << 13,        /* ui/mainmenu_options: the main or pause menu */
    HUD_JOURNAL = 1u << 14,     /* ui/diary_marks_simbol_*: the journal */
    HUD_OBSCURA = 1u << 15,     /* ui/ui_girl_good_color1, 2: a Sister's camera obscura */
    HUD_WHEEL = 1u << 16,       /* ui/wheel/ui_wheel_acc_manipulator*: the map's Wheel of Time */
    HUD_LOADING = 1u << 17,     /* ui/loading/loading_bg1..5 */
    HUD_SUBTITLE = 1u << 18,    /* blackbitmap: under subtitles (and some HUD and map captions) */
    HUD_OPTIONS = 1u << 19,     /* ui/opt_glyph_*: the options pages */
    HUD_MAINMENU = 1u << 20,    /* ui/mainmenu_new: the main menu (not the pause menu) */
    HUD_PAUSE = 1u << 21,       /* ui/mainmenu_continue: the pause menu */
    HUD_ARROWS = 1u << 22,      /* ui/diary_quest_arrow_up, _down: a list (saves, journal) */
    HUD_VIDEO = 1u << 23,       /* a film fills the screen: Theora decoded, little else drawn */
    HUD_MAP3D = 1u << 24,       /* map_loc_cubemap, map_shaft_cubemap: the map's chambers and threads are drawn */
    HUD_CONTROL_LOCKED = 1u << 25, /* the game's ControlsLocked property */
    HUD_PATH_READY = 1u << 26,  /* the map accepted the drawn trajectory */
    HUD_BODY_DECOR = 1u << 28,  /* artwork replaced by the body overlay */
    HUD_TAKEALL = 1u << 29,    /* the redundant collect-all button */
    HUD_JOURNAL_VIDEO = 1u << 30, /* the journal's fullscreen glyph lesson */
    HUD_BACK = 1u << 27,        /* original return button */
};

/* Images whose draws the layer measures (their shader constants): the
 * palette's seven colours (ui_alimfa_pal0..6_grad), the Memory's
 * (ui_flimfa_pal0..6_grad), the time wheel's handle, the hero's marker on
 * the map (map_hero), the strip under subtitles (blackbitmap), the
 * menus' exit (mainmenu_exit) and the main and pause menus' other glyphs
 * (mainmenu_new ... _continue: the layer names them, as the mouse's hover
 * would). */
enum { HUD_SLOT_PALETTE = 1, HUD_SLOT_MEMORY = 8, HUD_SLOT_WHEEL = 15, HUD_SLOT_HERO = 16, HUD_SLOT_SUBTITLE = 17,
       HUD_SLOT_EXIT = 18, HUD_SLOT_BACK = 19, HUD_SLOT_MENU = 20, HUD_SLOTS = 27, HUD_SLOT_FLOATS = 72 };

/* The tag of a texture created from these file bytes (0: none) and its
 * slot (0: none). */
uint32_t void_hud_tag_for(const uint8_t *data, uint32_t size, uint32_t *slot);
void void_hud_set_hidden(uint32_t tags);
uint32_t void_hud_hidden(void);
uint32_t void_hud_shader_tag_for(const uint8_t *data, uint32_t size);
/* A draw sampled textures with these tags. */
void void_hud_draw(uint32_t tags);
/* A draw sampled a slot's image: pixel shader constants c0..c7, vertex
 * shader constants c0..c7 and the part of the screen it covered
 * ([x0, y0, x1, y1] in 0..1; zeros if unknown). */
void void_hud_slot_draw(uint32_t slot, const float *ps, const float *vs, const float rect[4]);
/* A frame was presented: what it drew becomes the state. */
void void_hud_present(uint32_t draws);
/* Video.dll decoded a Theora frame (theora_native.c, any thread). */
void void_hud_video_frame(void);
/* Tags drawn in the last presented frame; *frame (if set) counts presents. */
uint32_t void_hud_state(uint32_t *frame);
/* The constants of each slot's last draw (HUD_SLOT_FLOATS a slot: ps c0..c7,
 * vs c0..c7, then its rectangle); returns the mask of slots drawn in the
 * last presented frame (bit = slot). */
uint32_t void_hud_slots(float out[HUD_SLOTS][HUD_SLOT_FLOATS]);
/* Testing the touch layer: these tags count as shown in every frame (0: off). */
void void_hud_force(uint32_t tags);
/* Whether one of the last frames presented showed the game's cursor (a menu). */
int void_hud_cursor_recent(int frames);
/* The touch layer can hide the game's cursor (its draws are skipped). */
void void_hud_set_cursor_hidden(int hidden);
int void_hud_cursor_hidden(void);
/* The touch layer slows a still menu (the body, the journal, the pause menu
 * with no finger on the screen for a while): a present at most every this
 * many microseconds (0: every vertical blank). */
void void_hud_set_frame_period(uint32_t microseconds);
uint32_t void_hud_frame_period(void);
/* The touch layer hides a screen change (the body to the journal and back:
 * the world in between is not shown): for up to ms milliseconds (0 lets go)
 * the game goes on drawing while the window keeps its last picture. */
void void_hud_hold_picture(uint32_t ms);
int void_hud_picture_held(void);
void void_hud_path_ready(void);

#endif
