/* Scripted input for unattended runs.
 *
 * $VOID_INPUT names a file (default <data>/input.txt; absent = no script)
 * with one event per line, "<seconds> <action> [args]", timed from the
 * moment the script starts:
 *   key <vk>              press, hold 100 ms, release (vk in hex)
 *   down <vk> / up <vk>
 *   click <x> <y> [b]     cursor to (x, y) in game pixels, press and release button b (0 left)
 *   cursor <x> <y>        move the cursor to (x, y) in game pixels
 *   move <dx> <dy>        relative mouse motion
 *   warp <x> <y>          put the cursor at (x, y) without mouse motion
 *   bdown <b> / bup <b>   press / release mouse button b where the cursor is
 *   wheel <delta>
 *   console <command>    queue an original game/engine console command
 *   memfind <word>        log guest addresses holding the word as UTF-16 (debugging)
 *   shot                  dump the next presented frame to <data>/frames
 *   trace                 trace the next frame (see VOID_TRACE_FRAME in d3d9_gl.c)
 *   shaderwarm [first last] pregenerate the 2009 library or an effect range (1..N)
 *   physicsfast <0|1>     compare original and optimized PhysX/debug-line leaves
 *   regionfast <0|1>      compare original and native weighted region lighting
 *   timescale <x>         run the game clock at x times real time (0.1 = slow motion)
 *   hud [force <hex>]     log what the last frame showed for the touch layer (hud.h);
 *                         "force" adds tags to every frame (testing the layer; 0 ends it)
 *   hud body              log exact touch body target, brush and cached amounts
 *   sound <land|damage|absorb> [0|1]
 *                         as if the sound played (testing the layer's vibration);
 *                         "absorb 1" plays on until "absorb 0"
 *   profile               write the PGO profile (instrumented builds; LLVM_PROFILE_FILE)
 *   quit                  end the process (writing the profile first)
 * '#' starts a comment.
 *
 * $VOID_INPUT_LIVE names a file that is read as it grows, for exploring a
 * running game: each new line is "<action> [args]" without a time and runs
 * at once; "sleep <seconds>" paces a batch (adb shell "echo 'down 57' >> …").
 * Without the variable (the APK), <data>/live.txt is that file if it exists
 * when the game starts. */
#include "host.h"
#include "hud.h"
#include "sound_events.h"
#include "input.h"
#include "touch_native.h"
#include "shader_warm.h"
#include <time.h>
#include <unistd.h>

void d3d_request_frame_dump(void);
void d3d_request_trace(void);
void d3d_request_camera_log(int frames);
void void_renderer_native_enable(int enabled);
void void_physics_native_enable(int enabled);
/* Present in a build instrumented for PGO (tools/build_android.py --pgo-generate). */
extern int __llvm_profile_write_file(void) __attribute__((weak));

static void write_profile(void)
{
    if (__llvm_profile_write_file) void_log("[script] profile written (%d)", __llvm_profile_write_file());
}

typedef struct { double at; char action[16]; int a, b, c; double seconds; char text[512]; uint32_t force_tags; } script_event;

static double now_seconds(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static void sleep_until(double t)
{
    for (;;) {
        double left = t - now_seconds();
        if (left <= 0) return;
        struct timespec ts = { (time_t)left, (long)((left - (double)(time_t)left) * 1e9) };
        nanosleep(&ts, NULL);
    }
}

static void hold(double seconds)
{
    sleep_until(now_seconds() + seconds);
}

#ifndef VOID_ANDROID_APP
int void_shader_warming;   /* The standalone collector needs no progress-window draws. */
#endif

#ifndef VOID_RELEASE
/* CEffectLibrary's hash-map list: node links, uint64 ID, shared_ptr<CEffectCustom>. */
static int library_effects(uint32_t lib, uint32_t effects[512])
{
    if (!void_vm_readable(lib, 0x34)) return 0;
    uint32_t head = MEM32(lib + 0x2C), count = MEM32(lib + 0x30);
    if (!count || count > 512 || !void_vm_readable(head, 8)) return 0;
    uint32_t node = MEM32(head), prev = head;
    for (uint32_t i = 0; i < count; ++i) {
        if (node == head || !void_vm_readable(node, 0x18) || MEM32(node + 4) != prev) return 0;
        uint32_t effect = MEM32(node + 0x10);
        if (!void_vm_readable(effect, 0x10)) return 0;
        uint32_t vt = MEM32(effect + 0xC);
        if (!void_vm_readable(vt, 64) || MEM32(vt + 60) != 0x16203D50u) return 0;
        effects[i] = effect;
        prev = node;
        node = MEM32(node);
    }
    return node == head && MEM32(head + 4) == prev ? (int)count : 0;
}

static void warm_shaders(int first, int last)
{
    uint32_t vt = 0x162D6794u, hits[64], effects[512], candidate[512];
    void_machine_enter();
    int found = void_vm_find((const uint8_t *)&vt, sizeof vt, hits, 64), libraries = 0, count = 0;
    for (int i = 0; i < found; ++i) {
        int n = library_effects(hits[i], candidate);
        if (!n) continue;
        ++libraries;
        count = n;
        memcpy(effects, candidate, (size_t)n * sizeof *effects);
    }
    if (libraries != 1 || found == 64) {
        void_log("[shaderwarm] expected one effect library, found %d (%d candidates)", libraries, found);
        void_machine_leave();
        return;
    }
    if (!first) first = 1;
    if (!last) last = count;
    if (first < 1 || last > count || last < first) {
        void_log("[shaderwarm] effect range must be within 1..%d", count);
        void_machine_leave();
        return;
    }
    int ready = 0;
#ifndef VOID_ANDROID_APP
    void_shader_warming = 1;
#endif
    for (int i = first - 1; i < last; ++i) {
        uint32_t ok = void_call_guest_this(0x16203D50u, effects[i] + 0xC, 0, NULL);
        ready += (ok & 0xFF) != 0;
        void_log("[shaderwarm] effect %d/%d: %s", i + 1, count, (ok & 0xFF) ? "ready" : "unbounded");
    }
#ifndef VOID_ANDROID_APP
    void_shader_warming = 0;
#endif
    void_log("[shaderwarm] complete %d..%d: %d effects ready", first, last, ready);
    void_machine_leave();
}
#endif

static void run_event(const script_event *e)
{
    if (!strcmp(e->action, "console")) {
        void_log("[script] console %s: %s", e->text, void_touch_console(e->text) ? "queued" : "rejected");
    } else if (!strcmp(e->action, "key")) {
        void_input_key((uint32_t)e->a, 1);
        hold(0.1);
        void_input_key((uint32_t)e->a, 0);
    } else if (!strcmp(e->action, "down")) {
        void_input_key((uint32_t)e->a, 1);
    } else if (!strcmp(e->action, "up")) {
        void_input_key((uint32_t)e->a, 0);
    } else if (!strcmp(e->action, "click")) {
        uint32_t x, y;
        void_input_cursor(&x, &y);
        void_input_mouse_move(e->a - (int)x, e->b - (int)y);
        hold(0.05);
        void_input_mouse_button(e->c, 1);
        hold(0.1);
        void_input_mouse_button(e->c, 0);
    } else if (!strcmp(e->action, "cursor")) {
        uint32_t x, y;
        void_input_cursor(&x, &y);
        void_input_mouse_move(e->a - (int)x, e->b - (int)y);
    } else if (!strcmp(e->action, "move")) {
        void_input_mouse_move(e->a, e->b);
    } else if (!strcmp(e->action, "warp")) {
        void_input_mouse_warp(e->a, e->b);
    } else if (!strcmp(e->action, "bdown")) {
        void_input_mouse_button(e->a, 1);
    } else if (!strcmp(e->action, "bup")) {
        void_input_mouse_button(e->a, 0);
    } else if (!strcmp(e->action, "wheel")) {
        void_input_mouse_wheel(e->a);
    } else if (!strcmp(e->action, "shot")) {
        d3d_request_frame_dump();
    } else if (!strcmp(e->action, "trace")) {
        d3d_request_trace();
    } else if (!strcmp(e->action, "camera")) {
        d3d_request_camera_log(e->a > 0 ? e->a : 60);
    } else if (!strcmp(e->action, "rendererfast")) {
        void_machine_enter();
        void_renderer_native_enable(e->a != 0);
        void_machine_leave();
    } else if (!strcmp(e->action, "physicsfast")) {
        void_machine_enter();
        void_physics_native_enable(e->a != 0);
        void_machine_leave();
    } else if (!strcmp(e->action, "regionfast")) {
        void_machine_enter();
        void_renderer_region_enable(e->a != 0);
        void_machine_leave();
    } else if (!strcmp(e->action, "physhz")) {
        /* Experiment: the physics step Engine's scenes are given (setTiming,
         * the float 1/60 at Engine+0x12a25c), for scenes made after this. */
        uint32_t va = void_module_handle("Engine.dll") + 0x12a25cu, old = 0;
        if (e->a > 0 && void_vm_protect(va & ~0xFFFu, 0x1000, 0x04, &old)) {
            float step = 1.0f / (float)e->a;
            memcpy(GPTR(va), &step, 4);
            void_vm_protect(va & ~0xFFFu, 0x1000, old, &old);
            void_log("[script] physics step 1/%d s at %08X", e->a, va);
        }
    } else if (!strcmp(e->action, "timescale")) {
        void_set_time_scale(e->seconds);
    } else if (!strcmp(e->action, "hud") && !strcmp(e->text, "force")) {
        void_hud_force(e->force_tags);
        void_log("[hud] forced tags %X", e->force_tags);
    } else if (!strcmp(e->action, "hud") && !strcmp(e->text, "slots")) {
        static float slots[HUD_SLOTS][HUD_SLOT_FLOATS];
        uint32_t drawn = void_hud_slots(slots);
        for (int s = 1; s < HUD_SLOTS; ++s)
            if (drawn & (1u << s))
                void_log("[hud] slot %d at %.4f %.4f %.4f %.4f; vs c0 %g %g %g %g c3 %g %g %g %g", s, slots[s][64], slots[s][65],
                    slots[s][66], slots[s][67], slots[s][32], slots[s][33], slots[s][34], slots[s][35], slots[s][44],
                    slots[s][45], slots[s][46], slots[s][47]);
    } else if (!strcmp(e->action, "hud") && !strcmp(e->text, "body")) {
        float amounts[28];
        void_touch_body_amounts(amounts);
        char text[1024];
        size_t at = (size_t)snprintf(text, sizeof text, "[hud] body target=%d brush=%d",
            void_touch_body_target(), void_touch_brush_colour());
        for (int i = 0; i < 14 && at < sizeof text; ++i)
            at += (size_t)snprintf(text + at, sizeof text - at, " %c%d=%.3f/%.3f",
                i < 7 ? 'A' : 'M', i % 7, amounts[i * 2], amounts[i * 2 + 1]);
        void_log("%s", text);
    } else if (!strcmp(e->action, "hud")) {
        uint32_t frame = 0, tags = void_hud_state(&frame);
        void_log("[hud] frame %u shows %X%s%s%s%s%s%s%s%s%s%s%s", frame, tags, tags & HUD_CURSOR ? " cursor" : "",
            tags & HUD_CURSOR_LYMPHA ? " cursor-lympha" : "", tags & HUD_MAP ? " map" : "",
            tags & HUD_USE ? " use" : "", tags & HUD_USE_ARROW ? " use-arrow" : "", tags & HUD_PAINT ? " paint" : "",
            tags & HUD_TRAP ? " trap" : "", tags & HUD_WAIT ? " wait" : "", tags & HUD_DEATH ? " death" : "",
            tags & HUD_NO_LYMPHA ? " no-lympha" : "", tags & HUD_QUESTLOG ? " questlog" : "");
        d3d_shader_warm_stats();
        void_machine_enter();
        uint64_t regions = void_renderer_region_counts();
        void_machine_leave();
        void_log("[region] native=%u fallback=%u", (uint32_t)(regions >> 32), (uint32_t)regions);
    } else if (!strcmp(e->action, "sound")) {
        int event = !strcmp(e->text, "land") ? SOUND_EVENT_LAND : !strcmp(e->text, "damage") ? SOUND_EVENT_DAMAGE
                  : !strcmp(e->text, "absorb") ? SOUND_EVENT_ABSORB : -1;
        void_sound_event_force(event, event == SOUND_EVENT_ABSORB ? e->b : -1);
        void_log("[script] sound %s %d", e->text, e->b);
    } else if (!strcmp(e->action, "sleep")) {
        hold(e->seconds);
    } else if (!strcmp(e->action, "memfind")) {
        /* Debugging: where guest memory holds the UTF-16 text (ASCII word),
         * with the 40 code units before it. */
        uint8_t pattern[64];
        uint32_t n = 0, hits[16];
        for (const unsigned char *c = (const unsigned char *)e->text; *c && n + 2 <= sizeof pattern;) {
            uint32_t u = *c++;                                     /* UTF-8 -> UTF-16 (BMP) */
            int extra = u >= 0xE0 ? 2 : u >= 0xC0 ? 1 : 0;
            if (extra) u &= 0x3Fu >> extra;
            while (extra-- && (*c & 0xC0) == 0x80) u = (u << 6) | (*c++ & 0x3Fu);
            pattern[n++] = (uint8_t)u;
            pattern[n++] = (uint8_t)(u >> 8);
        }
        void_machine_enter();   /* nothing unmaps guest pages under the scan */
        int found = void_vm_find(pattern, n, hits, 16);
        void_log("[script] memfind %s: %d hits", e->text, found);
        for (int h = 0; h < found; ++h) {
            char line[512];
            size_t at = 0;
            uint32_t from = hits[h] >= 80 ? hits[h] - 80 : 0;
            for (uint32_t va = from; va < hits[h] + n + 8 && at + 8 < sizeof line; va += 2) {
                if (!void_vm_readable(va, 2)) break;
                at += (size_t)snprintf(line + at, sizeof line - at, "%04X ", MEM16(va));
            }
            void_log("[script]   %08X: %s", hits[h], line);
        }
        void_machine_leave();
    } else if (!strcmp(e->action, "shaderwarm")) {
#ifndef VOID_RELEASE
        warm_shaders(e->a, e->b);
#endif
    } else if (!strcmp(e->action, "profile")) {
        write_profile();
    } else if (!strcmp(e->action, "quit")) {
        void_log("[script] quit");
        write_profile();
        _exit(0);
    } else {
        void_log("[script] unknown action '%s'", e->action);
    }
}

/* One line into an event; `timed` lines start with their time in seconds. */
static int parse_line(char *line, script_event *e, int timed)
{
    char *hash = strchr(line, '#');
    if (hash) *hash = 0;
    memset(e, 0, sizeof *e);
    char a[32] = "", b[32] = "", c[32] = "";
    if (timed) {
        if (sscanf(line, "%lf %15s %31s %31s %31s", &e->at, e->action, a, b, c) < 2) return 0;
    } else if (sscanf(line, "%15s %31s %31s %31s", e->action, a, b, c) < 1) {
        return 0;
    }
    if (!strcmp(e->action, "console")) {
        int start = 0;
        if (timed) sscanf(line, "%*lf %*15s %n", &start);
        else sscanf(line, "%*15s %n", &start);
        size_t n = strcspn(line + start, "\r\n");
        if (!n || n >= sizeof e->text) return 0;
        memcpy(e->text, line + start, n);
        e->text[n] = 0;
        return 1;
    }
    int hex = !strcmp(e->action, "key") || !strcmp(e->action, "down") || !strcmp(e->action, "up");
    e->a = (int)strtol(a, NULL, hex ? 16 : 10);
    e->b = (int)strtol(b, NULL, 10);
    e->c = (int)strtol(c, NULL, 10);
    e->seconds = strtod(a, NULL);
    snprintf(e->text, sizeof e->text, "%s", a);
    e->force_tags = (uint32_t)strtoul(b, NULL, 16);
    return 1;
}

static void *script_thread(void *arg)
{
    script_event *events = (script_event *)arg;
    double start = now_seconds();
    for (script_event *e = events; e->action[0]; ++e) {
        sleep_until(start + e->at);
        void_log("[script] %.1fs %s %d %d %d", e->at, e->action, e->a, e->b, e->c);
        run_event(e);
    }
    free(events);
    return NULL;
}

typedef struct {
    char text[1024];
    size_t used;
    int discard;
} script_line_buffer;

/* Drop an oversized or binary line in full; never execute a truncated prefix. */
static int script_line_byte(script_line_buffer *pending, int ch)
{
    if (ch != '\n') {
        if (!ch || pending->used + 1 >= sizeof pending->text) pending->discard = 1;
        else if (!pending->discard) pending->text[pending->used++] = (char)ch;
        return 0;
    }
    pending->text[pending->used] = 0;
    int complete = !pending->discard;
    pending->used = 0;
    pending->discard = 0;
    if (!complete) void_log("[script] rejected oversized or binary input line");
    return complete;
}

static void *live_thread(void *arg)
{
    char *path = (char *)arg;
    long offset = 0;
    script_line_buffer pending = {0};
    for (;;) {
        FILE *f = fopen(path, "r");
        if (f) {
            if (fseek(f, offset, SEEK_SET) == 0) {
                int ch;
                while ((ch = fgetc(f)) != EOF) {
                    ++offset;
                    if (!script_line_byte(&pending, ch)) continue;
                    script_event e;
                    if (!parse_line(pending.text, &e, 0)) continue;
                    void_log("[live] %s %d %d %d", e.action, e.a, e.b, e.c);
                    run_event(&e);
                }
            }
            fclose(f);
        }
        hold(0.05);
    }
    return NULL;
}

static void start_detached(void *(*fn)(void *), void *arg)
{
    pthread_t thread;
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    if (pthread_create(&thread, &attr, fn, arg)) void_log("[script] thread start failed");
    pthread_attr_destroy(&attr);
}

void void_input_script_start(void)
{
    const char *live = getenv("VOID_INPUT_LIVE");
    char live_default[1024];
    if (!live || !*live) {
        /* The APK takes no environment: a live.txt in the data folder, if
         * present at start, is the live command file (development). */
        snprintf(live_default, sizeof live_default, "%s/live.txt", void_data_dir());
        if (access(live_default, F_OK) == 0) live = live_default;
    }
    if (live && *live) {
        void_log("[live] reading commands from %s", live);
        start_detached(live_thread, strdup(live));
    }
    char path[1024];
    const char *env = getenv("VOID_INPUT");
    if (env && *env) snprintf(path, sizeof path, "%s", env);
    else snprintf(path, sizeof path, "%s/input.txt", void_data_dir());
    FILE *f = fopen(path, "r");
    if (!f) return;
    script_event *events = (script_event *)calloc(1025, sizeof *events);
    int count = 0;
    script_line_buffer pending = {0};
    int ch;
    while (count < 1024 && (ch = fgetc(f)) != EOF)
        if (script_line_byte(&pending, ch) && parse_line(pending.text, &events[count], 1)) ++count;
    if (count < 1024 && (pending.used || pending.discard) && script_line_byte(&pending, '\n') &&
        parse_line(pending.text, &events[count], 1)) ++count;
    fclose(f);
    void_log("[script] %d events from %s", count, path);
    start_detached(script_thread, events);
}
