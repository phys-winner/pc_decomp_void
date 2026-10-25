/* Touch axes enter the player's original force accumulator. The original
 * script still supplies speed bonuses, walking, gravity and collision. */
#include "host.h"
#include "hud.h"
#include "input.h"
#include "touch_native.h"
#include <math.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static pthread_mutex_t touch_lock = PTHREAD_MUTEX_INITIALIZER;
static float move_x, move_y;
static int move_active, move_walking;
static float chosen_fov = 55, chosen_veins = 1;
static int options_pending = 1;
static _Atomic uint32_t console_object;
static _Atomic int body_target = -1;
static _Atomic int body_transfer_colour = -1;
static float body_amounts[28];
static unsigned body_amounts_known;
static float body_details[14] = {-1, -1, -1, -1, -1, 0, 0, 0, 0, 0, 0, 0, -1, -1};
static char body_stat_names[7][256];
/* The hearts a carried Memory colour can go into: where the camera shows
 * each (the game's pixels), its amount, and when the script last said so. */
typedef struct { int x, y; unsigned current, maximum; uint64_t at; } zone_label;
static zone_label zone_labels[21];
static char hint_texts[56][256];
static int hints_ready;
static _Atomic int brush_colour = -1;
static int movement_force_armed;
static char commands[32][512];
static unsigned command_first, command_count;
static _Atomic uint64_t cancel_until;
static _Atomic int find_console;
static _Atomic int harvest_blocked;

void void_touch_harvest_begin(void) { atomic_store(&harvest_blocked, 0); }
void void_touch_harvest_stop(void) { atomic_store(&harvest_blocked, 1); }
int void_touch_harvest_blocked(void) { return atomic_load(&harvest_blocked); }

void void_touch_movement(float x, float y)
{
    if (!isfinite(x) || !isfinite(y)) x = y = 0;
    float radius = hypotf(x, y);
    if (radius > 1) { x /= radius; y /= radius; radius = 1; }
    int active = radius > .001f, walking = active && radius < .5f;
    pthread_mutex_lock(&touch_lock);
    int old_active = move_active, old_walking = move_walking;
    move_x = x; move_y = y; move_active = active; move_walking = walking;
    pthread_mutex_unlock(&touch_lock);
    if (old_active != active) void_input_key('W', active);
    if (old_walking != walking) void_input_key(0xA0, walking);
}

void void_touch_gameplay_options(float fov, float veins)
{
    if (!isfinite(fov) || fov < 40 || fov > 100 || !isfinite(veins) || veins < 1 || veins > 5) return;
    pthread_mutex_lock(&touch_lock);
    chosen_fov = fov; chosen_veins = veins; options_pending = 1;
    pthread_mutex_unlock(&touch_lock);
}

int void_touch_console(const char *command)
{
    if (!command || !*command || strlen(command) >= sizeof commands[0] || strchr(command, '\n') || strchr(command, '\r')) return 0;
    pthread_mutex_lock(&touch_lock);
    int accepted = command_count < 32;
    if (accepted) {
        snprintf(commands[(command_first + command_count) % 32], sizeof commands[0], "%s", command);
        ++command_count;
        atomic_store(&find_console, 1);
    }
    pthread_mutex_unlock(&touch_lock);
    return accepted;
}

#ifdef VOID_RELEASE
#define sub_101C61C0 sub_101C4FC0
#define sub_101C61C0_lifted sub_101C4FC0_lifted
#define sub_1017E0F0 sub_1017D3C0
#define sub_1017E0F0_lifted sub_1017D3C0_lifted
#endif
void sub_101C61C0_lifted(void);
void sub_1017E0F0_lifted(void);

static int console_usable(uint32_t console)
{
    if (!void_vm_readable(console, 4) || !void_vm_readable(MEM32(console), 0x38)) return 0;
    uint32_t entry = MEM32(MEM32(console) + 0x34);
#ifdef VOID_RELEASE
    /* Read from the verified 2008 binding's module +0x124 and vtable +0x34. */
    return entry >= 0x11000000u && entry < 0x12000000u && void_vm_readable(entry, 1);
#else
    return entry == 0x110F0370u;
#endif
}

#ifndef VOID_RELEASE
static int console_candidate(uint32_t candidate)
{
    /* CConsole owns two red-black maps. Their sentinel flags distinguish the
     * live object from constructor immediates and transient copies of its VT. */
    if (!void_vm_writable(candidate, 0x40) || MEM32(candidate) != 0x1111F74Cu) return 0;
    uint32_t first = MEM32(candidate + 0x2C), second = MEM32(candidate + 0x38);
    return void_vm_readable(first, 0x1A) && MEM8(first + 0x19) == 1 &&
           void_vm_readable(second, 0x1E) && MEM8(second + 0x1D) == 1;
}

#endif

void void_touch_observe_context(uint32_t context)
{
    if (atomic_load(&console_object) || !void_vm_readable(context, 4)) return;
    uint32_t vt = MEM32(context);
    if (!void_vm_readable(vt, 0x18) || !void_vm_readable(MEM32(vt + 0x14), 1)) return;
    void_regs saved;
    void_regs_save(&saved);
    uint32_t module = void_call_guest_this(MEM32(vt + 0x14), context, 0, NULL);
    if (void_vm_readable(module, 0x128)) {
        uint32_t console = MEM32(module + 0x124);
        if (console_usable(console)) {
            atomic_store(&console_object, console);
            void_log("[touch] original console ready at %08X", console);
        }
    }
    void_regs_load(&saved);
}

void sub_101C61C0(void)
{
    float x, y; int active, walking;
    pthread_mutex_lock(&touch_lock);
    x = move_x; y = move_y; active = move_active; walking = move_walking;
    pthread_mutex_unlock(&touch_lock);
    uint32_t vector = MEM32(g_esp + 4);
    int armed = movement_force_armed;
    movement_force_armed = 0;
    if (!armed || !active || !void_vm_writable(vector, 12)) { sub_101C61C0_lifted(); return; }
    float original[3], redirected[3];
    memcpy(original, GPTR(vector), sizeof original);
    float radius = hypotf(x, y), factor = walking ? radius / .5f : .66f + .68f * (radius - .5f);
    /* Right is forward cross the downward axis; preserve the supplied Y force. */
    redirected[0] = (original[0] * y + original[2] * x) / radius * factor;
    redirected[1] = original[1];
    redirected[2] = (original[2] * y - original[0] * x) / radius * factor;
    memcpy(GPTR(vector), redirected, sizeof redirected);
    sub_101C61C0_lifted();
    memcpy(GPTR(vector), original, sizeof original);
}


/* Script patches publish only their own measured state through this binding. */
void sub_1017E0F0(void)
{
    void_touch_observe_context(g_ecx);
    uint32_t wrapper = MEM32(g_esp + 4);
    uint32_t object = void_vm_readable(wrapper, 4) ? MEM32(wrapper) : 0;
    char *text = void_vm_readable(object, 10) ? void_wstr_utf8(object + 8) : NULL;
    int target, side, colour, location, percent, consumed = 0;
    unsigned current, maximum, lymph;
    if (text && sscanf(text, "port_hint %d %n", &target, &consumed) == 1 &&
        target >= 0 && target < 56 && consumed > 0 && strlen(text + consumed) < sizeof hint_texts[0]) {
        pthread_mutex_lock(&touch_lock);
        memcpy(hint_texts[target], text + consumed, strlen(text + consumed) + 1);
        pthread_mutex_unlock(&touch_lock);
        g_eax = 0; g_esp += 8;
    } else if (text && !strcmp(text, "port_hints_ready")) {
        pthread_mutex_lock(&touch_lock);
        hints_ready = 1;
        pthread_mutex_unlock(&touch_lock);
        g_eax = 0; g_esp += 8;
    } else if (text && !strcmp(text, "port_ready")) {
        g_eax = 0; g_esp += 8;
    } else if (text && !strcmp(text, "port_journal_video")) {
        void_hud_draw(HUD_VIDEO | HUD_JOURNAL_VIDEO);
        g_eax = 0; g_esp += 8;
    } else if (text && sscanf(text, "port_body_target %d", &target) == 1) {
        atomic_store(&body_target, target);
        g_eax = 0; g_esp += 8;
    } else if (text && sscanf(text, "port_body_transfer_colour %d", &colour) == 1 && colour >= 0 && colour < 7) {
        atomic_store(&body_transfer_colour, colour);
        g_eax = 0; g_esp += 8;
    } else if (text && (lymph = 0, sscanf(text, "port_body_heart %d %u %u %d %u", &colour, &current, &maximum, &target, &lymph)) >= 4 &&
               colour >= 0 && colour < 7 && target >= 0 && target < 21 && maximum > 0) {
        pthread_mutex_lock(&touch_lock);
        body_details[0] = (float)colour;
        body_details[1] = current / 1000.0f;
        body_details[2] = maximum / 1000.0f;
        body_details[12] = (float)target;
        body_details[13] = lymph / 1000.0f;
        pthread_mutex_unlock(&touch_lock);
        g_eax = 0; g_esp += 8;
    } else if (text && sscanf(text, "port_zone_label %d %d %d %u %u", &target, &side, &location, &current, &maximum) == 5 &&
               target >= 0 && target < 21) {
        pthread_mutex_lock(&touch_lock);
        zone_labels[target] = (zone_label){ side, location, current, maximum, void_monotonic_ns() };
        pthread_mutex_unlock(&touch_lock);
        g_eax = 0; g_esp += 8;
    } else if (text && sscanf(text, "port_body_progress %u %u", &current, &maximum) == 2 && current <= maximum) {
        pthread_mutex_lock(&touch_lock);
        body_details[3] = (float)current;
        body_details[4] = (float)maximum;
        pthread_mutex_unlock(&touch_lock);
        g_eax = 0; g_esp += 8;
    } else if (text && sscanf(text, "port_body_stat %d %d %n", &colour, &percent, &consumed) == 2 &&
               colour >= 0 && colour < 7 && percent >= 0 && percent <= 100 && consumed > 0 &&
               strlen(text + consumed) < sizeof body_stat_names[0]) {
        pthread_mutex_lock(&touch_lock);
        body_details[5 + colour] = (float)percent;
        memcpy(body_stat_names[colour], text + consumed, strlen(text + consumed) + 1);
        pthread_mutex_unlock(&touch_lock);
        g_eax = 0; g_esp += 8;
    } else if (text && !strcmp(text, "port_path_ready")) {
        void_hud_path_ready();
        g_eax = 0; g_esp += 8;
    } else if (text && !strcmp(text, "port_move_force")) {
        movement_force_armed = 1;
        g_eax = 0; g_esp += 8;
    } else if (text && !strcmp(text, "port_harvest_stop")) {
        void_touch_harvest_stop();
        g_eax = 0; g_esp += 8;
    } else if (text && sscanf(text, "port_location_accepted %d", &location) == 1) {
        void_log("[location] accepted %d", location);
        g_eax = 0; g_esp += 8;
    } else if (text && sscanf(text, "port_brush %d %u %u", &colour, &current, &maximum) == 3 &&
               colour >= 0 && colour < 7 && current <= maximum) {
        pthread_mutex_lock(&touch_lock);
        body_amounts[colour * 2] = current / 1000.0f;
        body_amounts[colour * 2 + 1] = maximum / 1000.0f;
        body_amounts_known |= 1u << colour;
        pthread_mutex_unlock(&touch_lock);
        atomic_store(&brush_colour, colour);
        g_eax = 0; g_esp += 8;
    } else if (text && sscanf(text, "port_colour %d %d %u %u", &side, &colour, &current, &maximum) == 4 &&
               side >= 0 && side < 2 && colour >= 0 && colour < 7 && current <= maximum) {
        pthread_mutex_lock(&touch_lock);
        body_amounts[side * 14 + colour * 2] = current / 1000.0f;
        body_amounts[side * 14 + colour * 2 + 1] = maximum / 1000.0f;
        body_amounts_known |= 1u << (side * 7 + colour);
        pthread_mutex_unlock(&touch_lock);
        g_eax = 0; g_esp += 8;
    } else {
        free(text);
        sub_1017E0F0_lifted();
        return;
    }
    free(text);
}

static void execute_command(uint32_t console, const char *command)
{
    uint32_t wide = void_galloc(2 * (uint32_t)(strlen(command) + 1));
    if (!wide) return;
    void_utf8_to_gw(command, wide, (uint32_t)strlen(command) + 1);
    void_log("[touch-console] %s", command);
    void_call_guest_this(MEM32(MEM32(console) + 0x34), console, 1, &wide);
    void_gfree(wide);
}

void void_touch_commands_pump(void)
{
    uint64_t until = atomic_load(&cancel_until);
    if (until && void_monotonic_ns() >= until) {
        atomic_store(&cancel_until, 0);
        void_input_key(0x7D, 0);
    }
    uint32_t console = atomic_load(&console_object);
#ifndef VOID_RELEASE
    if (!console && atomic_exchange(&find_console, 0)) {
        uint32_t vt = 0x1111F74Cu, hits[64];
        if (void_vm_readable(vt, 0x38) && MEM32(vt + 0x34) == 0x110F0370u) {
            int found = void_vm_find((const uint8_t *)&vt, sizeof vt, hits, 64), valid = 0;
            for (int i = 0; i < found; ++i) {
                if (!console_candidate(hits[i])) continue;
                console = hits[i];
                ++valid;
            }
            if (valid == 1 && found < 64) {
                atomic_store(&console_object, console);
                void_log("[touch] original console found at %08X", console);
            } else {
                console = 0;
                void_log("[touch] original console scan has %d valid objects (%d candidates)", valid, found);
            }
        }
    }
#endif
    if (!console || !console_usable(console)) return;
    char next[512]; float fov, veins;
    pthread_mutex_lock(&touch_lock);
    int apply = options_pending;
    fov = chosen_fov; veins = chosen_veins; options_pending = 0;
    int have = command_count != 0;
    if (have) {
        memcpy(next, commands[command_first], sizeof next);
        command_first = (command_first + 1) % 32; --command_count;
    }
    pthread_mutex_unlock(&touch_lock);
    void_regs saved;
    void_regs_save(&saved);
    if (apply) {
        char option[80];
        snprintf(option, sizeof option, "setting PortFOV %d", (int)lroundf(fov));
        execute_command(console, option);
        snprintf(option, sizeof option, "setting PortVeinBrightness %d", (int)lroundf(veins * 100));
        execute_command(console, option);
    }
    if (have) execute_command(console, next);
    void_regs_load(&saved);
}

int void_touch_body_target(void) { return atomic_load(&body_target); }
int void_touch_body_transfer_colour(void) { return atomic_exchange(&body_transfer_colour, -1); }
void void_touch_body_target_reset(void) { atomic_store(&body_target, -1); }
void void_touch_body_amounts(float out[28])
{
    pthread_mutex_lock(&touch_lock);
    memcpy(out, body_amounts, sizeof body_amounts);
    for (unsigned i = 0; i < 14; ++i)
        if (!(body_amounts_known & (1u << i))) out[2 * i] = out[2 * i + 1] = -1;
    pthread_mutex_unlock(&touch_lock);
}

void void_touch_body_details(float out[14])
{
    pthread_mutex_lock(&touch_lock);
    memcpy(out, body_details, sizeof body_details);
    pthread_mutex_unlock(&touch_lock);
}

/* The labels the script published in the last fifth of a second (it does
 * every frame while a Memory colour is carried): zone, x, y, current,
 * maximum per label. Returns how many. */
int void_touch_zone_labels(float out[21 * 5])
{
    uint64_t now = void_monotonic_ns();
    int n = 0;
    pthread_mutex_lock(&touch_lock);
    for (int zone = 0; zone < 21; ++zone) {
        const zone_label *l = &zone_labels[zone];
        if (!l->at || now - l->at > 200000000ull) continue;
        float *o = out + 5 * n++;
        o[0] = (float)zone; o[1] = (float)l->x; o[2] = (float)l->y;
        o[3] = (float)l->current; o[4] = (float)l->maximum;
    }
    pthread_mutex_unlock(&touch_lock);
    return n;
}

void void_touch_body_stat_name(int colour, char out[256])
{
    pthread_mutex_lock(&touch_lock);
    if (colour >= 0 && colour < 7) memcpy(out, body_stat_names[colour], 256);
    else out[0] = 0;
    pthread_mutex_unlock(&touch_lock);
}
int void_touch_hint_texts(char out[56][256])
{
    pthread_mutex_lock(&touch_lock);
    int ready = hints_ready;
    if (ready) memcpy(out, hint_texts, sizeof hint_texts);
    pthread_mutex_unlock(&touch_lock);
    return ready;
}
int void_touch_brush_colour(void) { return atomic_load(&brush_colour); }
void void_touch_cancel_stroke(void)
{
    atomic_store(&cancel_until, void_monotonic_ns() + 250000000ull);
    void_input_key(0x7D, 1);
}
