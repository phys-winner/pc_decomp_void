/* RendererD3D's reserved vector append: one 12-byte triangle record.
 * Growth and unusual layouts retain the original allocator/exception path. */
#include "host.h"

#ifdef VOID_RELEASE
#include "release_overrides.h"   /* these bodies' twins in another release (tools/lift_release.py) */
#else
#define RENDERER_APPEND12 sub_16082260             /* the 2009 RendererD3D.dll */
#define RENDERER_APPEND12_LIFTED sub_16082260_lifted
#define RENDERER_SCENE_PASS sub_1616AED0
#define RENDERER_SCENE_PASS_LIFTED sub_1616AED0_lifted
#define RENDERER_PASS_BUILD sub_161FCEC0
#define RENDERER_PASS_BUILD_LIFTED sub_161FCEC0_lifted
#define RENDERER_PASS_SPLIT sub_161F8460
#define RENDERER_PASS_SPLIT_LIFTED sub_161F8460_lifted
#define ENGINE_LOG_LINE sub_1110BF90               /* the 2009 Engine.dll */
#define ENGINE_LOG_LINE_LIFTED sub_1110BF90_lifted
#endif

static int renderer_native_enabled = 1;
static int renderer_region_enabled = 1;

void void_renderer_native_enable(int enabled) { renderer_native_enabled = enabled != 0; }
int void_renderer_native_enabled(void) { return renderer_native_enabled; }
void void_renderer_region_enable(int enabled) { renderer_region_enabled = enabled != 0; }
int void_renderer_region_enabled(void) { return renderer_region_enabled; }

int void_renderer_append12(int preserve_ecx)
{
    uint32_t vector = g_eax, stack = g_esp;
    uint32_t scratch = stack - (preserve_ecx ? 4u : 0u);
    if (!renderer_native_enabled || vector < 0x10000u || vector > GUEST_USER_TOP - 16u ||
        stack < 0x10020u + (preserve_ecx ? 4u : 0u) || stack > GUEST_USER_TOP - 8u) return 0;
    uint32_t begin = MEM32(vector + 4), end = MEM32(vector + 8), cap = MEM32(vector + 12);
    uint32_t source = MEM32(stack + 4);
    if (begin < 0x10000u || end < begin || cap < end || cap > GUEST_USER_TOP ||
        cap - begin > 0x7fffffffu || (end - begin) % 12u || (cap - begin) % 12u ||
        cap - end < 12u || source < 0x10000u || source > GUEST_USER_TOP - 12u ||
        (vector < cap && begin < vector + 16u) ||
        (vector < stack + 8u && scratch - 32u < vector + 16u) ||
        (source < stack + 8u && scratch - 32u < source + 12u) ||
        (end < stack + 8u && scratch - 32u < end + 12u)) return 0;

    /* Keep the original argument-byte mutation and scratch stack, including
     * the helper's saved ESI; callers can alias the source within the vector. */
    if (preserve_ecx) MEM32(stack - 4) = g_ecx;
    MEM32(scratch - 4) = g_ebx;
    MEM32(scratch - 8) = g_esi;
    MEM32(scratch - 12) = g_edi;
    MEM8(stack + 4) = 0;
    MEM32(scratch - 16) = source & ~255u;
    MEM32(scratch - 20) = source & ~255u;
    MEM32(scratch - 24) = end;
    MEM32(scratch - 28) = RECOMP_RETADDR;
    MEM32(scratch - 32) = end;
    MEM32(end) = MEM32(source);
    MEM32(end + 4) = MEM32(source + 4);
    MEM32(end + 8) = MEM32(source + 8);
    MEM32(vector + 8) = end + 12u;
    g_eax = end + 12u;
    g_ecx = preserve_ecx ? MEM32(stack - 4) : 0;
    g_edx = source;
    g_esp = stack + 8u;
    g_flag_k = FK_ADD;
    g_flag_a = end;
    g_flag_b = 12;
    g_flag_cf = 0;
    return 1;
}

#ifdef RENDERER_APPEND12
void RENDERER_APPEND12_LIFTED(void);
void RENDERER_APPEND12(void) { if (!void_renderer_append12(0)) RENDERER_APPEND12_LIFTED(); }
#endif

/* RendererD3D's scene-render pass (sub_1616AED0, thiscall: ECX the view, its
 * texture first; [ESP+4] the scene, [ESP+8] the scene render, [ESP+0x18]
 * reflected; ret 0x1C). A water mirror ("scene-render" Mirror="1") draws the
 * scene a second time each frame: a quarter of the frame at the lake Ire.
 * With water reflections off (the player's PortReflections 0) its reflected
 * pass goes the way the pass itself goes with the camera behind the mirror:
 * the view's texture filled black (IDirect3DDevice9::ColorFill), the render
 * target untouched. EAX/ECX/EDX and the flags are dead in all three callers. */
static int reflections_off;

void void_renderer_set_reflections(int on)
{
    if (reflections_off != !on) void_log("[renderer] water reflections %s", on ? "on" : "off");
    reflections_off = !on;
}

#ifdef RENDERER_SCENE_PASS
void RENDERER_SCENE_PASS_LIFTED(void);

void RENDERER_SCENE_PASS(void)
{
    uint32_t stack = g_esp, view = g_ecx;
    if (!reflections_off || !void_vm_readable(stack, 32) || !void_vm_readable(view, 4)) { RENDERER_SCENE_PASS_LIFTED(); return; }
    uint32_t scene = MEM32(stack + 4), render = MEM32(stack + 8), reflected = MEM8(stack + 0x18);
    if (!reflected || !void_vm_readable(scene + 56, 4) || !void_vm_readable(render, 4) ||
        !void_vm_readable(MEM32(render) + 48, 4)) { RENDERER_SCENE_PASS_LIFTED(); return; }
    void_regs saved;
    void_regs_save(&saved);
    uint32_t mirror = void_call_guest_this(MEM32(MEM32(render) + 48), render, 0, NULL) & 255u;
    void_regs_load(&saved);
    uint32_t holder = MEM32(scene + 56), texture = MEM32(view);
    if (!mirror || !void_vm_readable(holder + 8, 4) || !void_vm_readable(MEM32(holder + 8) + 24, 4) ||
        !texture || !void_vm_readable(texture, 4)) { RENDERER_SCENE_PASS_LIFTED(); return; }
    uint32_t device = MEM32(MEM32(holder + 8) + 24);
    if (!device || !void_vm_readable(device, 4)) { RENDERER_SCENE_PASS_LIFTED(); return; }
    static uint32_t out;
    if (!out) out = void_galloc(4);
    MEM32(out) = 0;
    uint32_t level[3] = { texture, 0, out };
    void_call_guest(MEM32(MEM32(texture) + 72), 3, level, 1);           /* GetSurfaceLevel(0, &surface) */
    uint32_t surface = MEM32(out);
    if (surface) {
        uint32_t fill[4] = { device, surface, 0, 0 };
        void_call_guest(MEM32(MEM32(device) + 140), 4, fill, 1);        /* ColorFill(surface, NULL, black) */
        void_call_guest(MEM32(MEM32(surface) + 8), 1, &surface, 1);     /* Release */
    }
    void_regs_load(&saved);
    g_esp = stack + 32u;   /* ret 0x1c */
}
#endif

/* RendererD3D's pass builder (sub_161FCEC0; ECX the generation, +40 its
 * flags, +44..+56 the counts of the lights to place; [ESP+4] the strategy,
 * [ESP+8] the effect's ID, a CEffectIDB with its text at +4, [ESP+12] a flag;
 * ret, AL whether it built) splits the effect's lights into passes,
 * generating and compiling the HLSL of each split it tries (sub_161F8460)
 * until one compiles; when none does it logs the effect's whole text, and its
 * caller asks again in the next frame. With the compile service running a
 * variant the cache lacks goes there (d3dx9.c): the builder's other tries and
 * the dump fail at once, and while the service works on it the next frames'
 * builds of the same effect are not run at all. EAX/ECX/EDX are the callers'
 * to lose. */
#if defined(RENDERER_PASS_BUILD) && defined(RENDERER_PASS_SPLIT) && defined(ENGINE_LOG_LINE)
void RENDERER_PASS_BUILD_LIFTED(void);
void RENDERER_PASS_SPLIT_LIFTED(void);
void void_d3dx_async_begin(uint32_t esp);
uint64_t void_d3dx_async_end(void);
int void_d3dx_async_aborted(void);
int void_d3dx_async_waiting(uint64_t key);

#define WAITING_EFFECTS 256u
static struct { uint64_t effect, variant; } waiting_effects[WAITING_EFFECTS];
static uint32_t waiting_next;

/* A frame in which a build has left a variant to the service already waits
 * for something: its builds stop after BUILD_BUDGET_NS of building, the rest
 * are asked for again in the next frames (a scene the caches do not cover
 * comes in over some frames instead of in one frame of seconds). Frames
 * without such a miss build everything as before. */
#define BUILD_BUDGET_NS 8000000ull
static uint32_t budget_frame;
static uint64_t budget_spent;
static int budget_waiting;

static uint64_t effect_identity(uint32_t generation, uint32_t strategy, uint32_t idb, uint32_t flag)
{
    uint64_t h = 0xCBF29CE484222325ull;
    const uint8_t *text = GPTR(idb + 4);
    for (uint32_t i = 0; i < 516u && text[i]; ++i) h = (h ^ text[i]) * 0x100000001B3ull;
    uint32_t words[7] = { strategy, flag, MEM32(generation + 40), MEM32(generation + 44), MEM32(generation + 48),
        MEM32(generation + 52), MEM32(generation + 56) };
    const uint8_t *w = (const uint8_t *)words;
    for (size_t i = 0; i < sizeof words; ++i) h = (h ^ w[i]) * 0x100000001B3ull;
    return h;
}

void RENDERER_PASS_BUILD(void)
{
    uint32_t stack = g_esp, generation = g_ecx;
    if (!void_vm_readable(stack, 16) || !void_vm_readable(generation, 60)) { RENDERER_PASS_BUILD_LIFTED(); return; }
    uint32_t strategy = MEM32(stack + 4), idb = MEM32(stack + 8), flag = MEM8(stack + 12);
    if (!void_vm_readable(idb, 520)) { RENDERER_PASS_BUILD_LIFTED(); return; }
    uint64_t effect = effect_identity(generation, strategy, idb, flag);
    for (uint32_t i = 0; i < WAITING_EFFECTS; ++i) {
        if (!waiting_effects[i].variant || waiting_effects[i].effect != effect) continue;
        if (void_d3dx_async_waiting(waiting_effects[i].variant)) {
            g_eax = 0;
            g_esp = stack + 4u;   /* ret */
            return;
        }
        waiting_effects[i].variant = 0;   /* answered, or the service gone: built as usual */
    }
    uint32_t frame = void_frames_presented();
    if (frame != budget_frame) {
        budget_frame = frame;
        budget_spent = 0;
        budget_waiting = 0;
    }
    if (budget_waiting && budget_spent >= BUILD_BUDGET_NS) {
        g_eax = 0;
        g_esp = stack + 4u;   /* ret: built in a later frame */
        return;
    }
    uint64_t t0 = void_monotonic_ns();
    void_d3dx_async_begin(stack);
    RENDERER_PASS_BUILD_LIFTED();
    uint64_t variant = void_d3dx_async_end();
    budget_spent += void_monotonic_ns() - t0;
    if (variant) budget_waiting = 1;
    if (variant && !(g_eax & 255u)) {
        waiting_effects[waiting_next].effect = effect;
        waiting_effects[waiting_next].variant = variant;
        waiting_next = (waiting_next + 1u) % WAITING_EFFECTS;
    }
}

/* Engine's log line (the log's vtable+12, sub_1110BF90; ECX the log, [ESP+4]
 * the text, [ESP+8] the level; ret 8): a build that left its variant to the
 * service fails as if no split compiled, and would log "Error generating
 * shader text" as a fatal error; within such a build nothing is logged. */
void ENGINE_LOG_LINE_LIFTED(void);

void ENGINE_LOG_LINE(void)
{
    if (void_d3dx_async_aborted()) {
        g_esp += 12u;   /* ret 8 */
        return;
    }
    ENGINE_LOG_LINE_LIFTED();
}

/* One split generated and compiled (sub_161F8460, cdecl; ret, AL): within a
 * build that waits for the service, a failure at once. */
void RENDERER_PASS_SPLIT(void)
{
    if (void_d3dx_async_aborted()) {
        g_eax = 0;
        g_esp += 4u;   /* ret */
        return;
    }
    RENDERER_PASS_SPLIT_LIFTED();
}
#endif
