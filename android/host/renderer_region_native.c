/* RendererD3D's weighted region lighting; same geometry, octant tests and
 * float addition order, without per-record guest register/stack emulation. */
#include "host.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Like generated code, guest accesses run while the guest lock is held. */
#if defined(RECOMP_PLAIN_MEMORY)
#undef RECOMP_MEM_QUAL
#define RECOMP_MEM_QUAL
#endif

#ifdef VOID_RELEASE
#include "release_overrides.h"   /* these bodies' twins in another release (tools/lift_release.py) */
#else
#define RENDERER_SAT sub_160D6ED0                  /* the 2009 RendererD3D.dll */
#define RENDERER_SAT_LIFTED sub_160D6ED0_lifted
#define RENDERER_SAT_EPSILON 0x162D2A64u           /* float 0x3f7fffef */
#define RENDERER_REGION_LIGHT sub_16013760
#define RENDERER_REGION_LIGHT_LIFTED sub_16013760_lifted
#define RENDERER_REGION_WALK sub_16014090
#define RENDERER_REGION_WALK_LIFTED sub_16014090_lifted
#define ENGINE_SAT sub_1105E810                    /* the 2009 Engine.dll */
#define ENGINE_SAT_LIFTED sub_1105E810_lifted
#define ENGINE_SAT_EPSILON 0x11122CE0u
#endif

#if defined(RENDERER_SAT) && defined(ENGINE_SAT) && defined(RENDERER_REGION_LIGHT) && defined(RENDERER_REGION_WALK)
/* GENERATED_REGION_SAT */
void RENDERER_SAT(void);
void RENDERER_SAT_LIFTED(void);
void ENGINE_SAT_LIFTED(void);
int void_renderer_native_enabled(void);
int void_renderer_region_enabled(void);
void RENDERER_REGION_LIGHT_LIFTED(void);
static uint32_t region_native_calls, region_fallback_calls;
uint64_t void_renderer_region_counts(void)
{
    return ((uint64_t)region_native_calls << 32) | region_fallback_calls;
}

static int region_range(uint32_t at, uint32_t bytes)
{
    return at >= 0x10000u && at <= GUEST_USER_TOP && bytes <= GUEST_USER_TOP - at;
}

static int region_overlap(uint32_t a, uint32_t an, uint32_t b, uint32_t bn)
{
    return (uint64_t)a < (uint64_t)b + bn && (uint64_t)b < (uint64_t)a + an;
}

/* All direct callers consume AL; callee-saved GPR, ESP and final flags remain
 * exact. Caller-clobbered GPR/XMM, empty x87 slots and scratch are discarded. */
static void region_sat_call(uint32_t epsilon, void (*lifted)(void))
{
    uint32_t stack = g_esp, box = g_edx;
    if (!void_renderer_native_enabled() || g_fp_top || MEM32(epsilon) != 0x3f7fffefu ||
        !region_range(stack - 136u, 144u) ||
        (recomp_yield_hook && g_backedges >= RECOMP_YIELD_EVERY - 32u)) {
        lifted(); return;
    }
    uint32_t obb = MEM32(stack + 4);
    if (!region_range(box, 24) || !region_range(obb, 60) ||
        region_overlap(box, 24, stack - 136u, 144u) || region_overlap(obb, 60, stack - 136u, 144u) ||
        !recomp_sat_finite(box, obb)) { lifted(); return; }
    uint32_t edges = 0;
    unsigned result = region_sat_overlap((const float *)GPTR(box), (const float *)GPTR(obb), &edges);
    g_backedges += edges;
    g_eax = (g_eax & ~255u) | result;
    g_esp = stack + 8u;
    g_flag_k = FK_ADD; g_flag_a = stack - 120u; g_flag_b = 120u; g_flag_cf = 0;
}

void RENDERER_SAT(void) { region_sat_call(RENDERER_SAT_EPSILON, RENDERER_SAT_LIFTED); }
void ENGINE_SAT(void) { region_sat_call(ENGINE_SAT_EPSILON, ENGINE_SAT_LIFTED); }

static float region_float(uint32_t at) { return sse_f32(MEM32(at)); }
static void region_store(uint32_t at, float value) { memcpy(GPTR(at), &value, 4); }

static float region_volume(uint32_t query, const float lo[3], const float hi[3])
{
    float volume = 1.f;
    for (unsigned i = 0; i < 3; ++i) {
        float qlo = region_float(query + i * 4), qhi = region_float(query + 12 + i * 4);
        float upper = qhi > hi[i] ? hi[i] : qhi;
        float lower = lo[i] > qlo ? lo[i] : qlo;
        float length = upper - lower;
        volume = length * volume;
    }
    return fabsf(volume);
}

/* 16014290 consumes AL then restores GPR/flags; 16014090 returns straight
 * into 16207990, which reloads every used XMM. The original x87 ABI is empty.
 * Callee-saved GPR/AL/ESP/final flags and every live guest byte are preserved;
 * caller-saved GPR/XMM, dead x87 slots and unused scratch are ABI-clobbered. */
int void_renderer_region_calculate(void)
{
    uint32_t stack = g_esp;
    if (!void_renderer_region_enabled() || g_fp_top != 0 || MEM32(RENDERER_SAT_EPSILON) != 0x3f7fffefu ||
        !region_range(stack - 512u, 528u)) return 0;
    uint32_t context = MEM32(stack + 4), box = MEM32(stack + 8), index = MEM32(stack + 12);
    if (!region_range(context, 32) || !region_range(box, 24)) return 0;
    uint32_t tree = MEM32(context), obb = MEM32(context + 4), query = MEM32(context + 8);
    uint32_t channels = MEM32(context + 12);
    if (!region_range(tree, 76) || !region_range(obb, 60) || !region_range(query, 24)) return 0;
    uint32_t channel_count = MEM32(tree + 4), table = MEM32(tree + 0x48), data = MEM32(tree + 0x38);
    if (!channel_count || channel_count > 4096 || index > (GUEST_USER_TOP - 8u) / 8u ||
        !region_range(table, index * 8u + 8u) || !region_range(channels, channel_count * 8u)) return 0;
    uint32_t offset = MEM32(table + index * 8u), colour = MEM32(table + index * 8u + 4);
    uint32_t record = data + (offset & 0x7fffffffu);
    if (record < data || !region_range(record, 2)) return 0;
    unsigned count = MEM16(record);
    if (!region_range(record, 2u + count * ((offset >> 31) ? 4u : 3u))) return 0;
    if (count > 512) return 0;
    uint32_t bytes = 2u + count * ((offset >> 31) ? 4u : 3u);
    uint32_t weights = (offset >> 31) ? record + 2u + count * 3u : 0;
    uint32_t inputs[] = {context, tree, obb, query, box, table + index * 8u, record};
    uint32_t lengths[] = {16, 76, 60, 24, 24, 8, bytes};
    for (unsigned i = 0; i < 7; ++i)
        if (region_overlap(inputs[i], lengths[i], stack - 512u, 528u) ||
            region_overlap(inputs[i], lengths[i], context + 16, 16) ||
            region_overlap(inputs[i], lengths[i], channels, channel_count * 8u)) return 0;
    if (region_overlap(channels, channel_count * 8u, context, 32) ||
        region_overlap(channels, channel_count * 8u, stack - 512u, 528u) ||
        region_overlap(context, 32, stack - 512u, 528u)) return 0;
    for (unsigned i = 0; i < 6; ++i)
        if ((MEM32(query + i * 4) & 0x7fffffffu) > 0x4d7fffffu ||
            (MEM32(box + i * 4) & 0x7fffffffu) > 0x4d7fffffu) return 0;
    if (!recomp_sat_finite(box, obb)) return 0;
    for (unsigned i = 0; i < 4; ++i)
        if ((MEM32(context + 16 + i * 4) & 0x7fffffffu) >= 0x7f800000u) return 0;
    /* Validated record bytes can use native pointers without guest-VA wraps. */
    uint16_t max_channel = 0;
    const RECOMP_MEM_QUAL uint8_t *records = GPTR(record + 2);
    for (unsigned i = 0; i < count; ++i) {
        uint16_t channel = records[i * 3u] | (uint16_t)records[i * 3u + 1u] << 8;
        if (channel > max_channel) max_channel = channel;
    }
    if (max_channel >= channel_count) return 0;

    uint32_t caller = g_cur_func;
    float lo[3], hi[3], delta[3], centre[3], extent[3], cell_weights[8];
    for (unsigned i = 0; i < 3; ++i) { lo[i] = region_float(box + i * 4); hi[i] = region_float(box + 12 + i * 4); }
    float volume = region_volume(query,lo,hi);
    float rgb[3] = {0,0,0};
    if (colour >> 24) {
        /* Every RGBE scale is a normal double: exact 2^(exponent - 136). */
        uint64_t scale_bits = ((uint64_t)(colour >> 24) + 887u) << 52;
        double scale; memcpy(&scale, &scale_bits, sizeof scale);
        for (unsigned i = 0; i < 3; ++i) rgb[i] = (float)((double)((colour >> (i * 8)) & 255u) * scale);
    }
    for (unsigned i = 0; i < 3; ++i) {
        float weighted = rgb[i] * volume;
        region_store(context + 20 + i * 4, weighted + region_float(context + 20 + i * 4));
    }
    region_store(context + 16, (float)((double)volume + (double)region_float(context + 16)));
    for (unsigned i = 0; i < 8; ++i) cell_weights[i] = -1.f;
    for (unsigned i = 0; i < 3; ++i) {
        delta[i] = hi[i] - lo[i];
        float half = delta[i] * .5f;
        delta[i] = half;
        float quarter = half * .25f;
        centre[i] = lo[i] + quarter;
        extent[i] = half * .5f;
    }
    uint32_t cell = stack - 76u;
    const RECOMP_MEM_QUAL uint8_t *record_end = records + count * 3u;
    for (const RECOMP_MEM_QUAL uint8_t *entry = records; entry != record_end; entry += 3u) {
        uint16_t channel = entry[0] | (uint16_t)entry[1] << 8;
        /* Geometry/weights are finite; preserve ordered IEEE channel adds. */
        RECOMP_MEM_QUAL float *destination = (float *)GPTR(channels) + channel * 2u;
        uint8_t mask = entry[2];
        if (__builtin_expect(mask == 255, 1)) { destination[0] = volume + destination[0]; continue; }
        float weight = weights ? (float)((const RECOMP_MEM_QUAL uint8_t *)GPTR(weights))[(entry - records) / 3u] * .03125f : 1.f;
        if (__builtin_expect(!mask, 1)) {
            destination[0] = volume + destination[0];
            float weighted = weight * volume;
            destination[1] = weighted + destination[1];
            continue;
        }
        uint32_t at = channels + channel * 8u;
        /* Keep the emitted traversal, including its continuous X/Y advances
         * across outer loop iterations; do not substitute an idealized grid. */
        float position[3] = {centre[0],centre[1],centre[2]};
        unsigned k = 0;
        for (unsigned z = 0; z < 2; ++z) {
            for (unsigned y = 0; y < 2; ++y) {
                for (unsigned x = 0; x < 2; ++x, ++k) {
                    float value = cell_weights[k];
                    if (value < 0.f) {
                        for (unsigned axis = 0; axis < 3; ++axis) {
                            region_store(cell + axis * 4, position[axis]);
                            region_store(cell + 12 + axis * 4, extent[axis]);
                        }
                        g_edx = cell; g_esp = stack - 192u;
                        MEM32(g_esp) = RECOMP_RETADDR; MEM32(g_esp + 4) = obb;
                        /* At most 17 bounded backedges; retain the original scheduler handover. */
                        if (recomp_yield_hook && g_backedges >= RECOMP_YIELD_EVERY - 32u) RENDERER_SAT();
                        else {
                            uint32_t edges = 0;
                            g_eax = region_sat_overlap((const float *)GPTR(cell), (const float *)GPTR(obb), &edges);
                            g_backedges += edges;
                        }
                        if (!(g_eax & 255u)) {
                            cell_weights[k] = 0.f;
                            position[0] = delta[0] + position[0]; continue;
                        }
                        float cell_lo[3], cell_hi[3];
                        for (unsigned axis = 0; axis < 3; ++axis) {
                            cell_hi[axis] = position[axis] + extent[axis];
                            cell_lo[axis] = position[axis] - extent[axis];
                        }
                        value = cell_weights[k] = region_volume(query,cell_lo,cell_hi);
                    }
                    region_store(at, value + region_float(at));
                    if (!(mask & (1u << k))) {
                        float weighted = value * weight;
                        region_store(at + 4, weighted + region_float(at + 4));
                    }
                    position[0] = delta[0] + position[0];
                }
                position[1] = delta[1] + position[1];
            }
            position[2] = delta[2] + position[2];
        }
    }
    /* The SAT callee preserves GPR/empty-x87 ABI; no dead-slot snapshots. */
    g_eax &= ~255u; g_esp = stack + 16; g_cur_func = caller;
    g_flag_k=FK_ADD;g_flag_a=stack-0xa8u;g_flag_b=0xa8u;g_flag_cf=0;
    return 1;
}

void RENDERER_REGION_LIGHT(void)
{
    if (void_renderer_region_enabled() && void_renderer_region_calculate()) ++region_native_calls;
    else { ++region_fallback_calls; RENDERER_REGION_LIGHT_LIFTED(); }
}

/* ---- the per-object region walk, remembered ----
 * 16207990 (an object's lighting, every frame) zeroes a context (160136B0:
 * the tree, the object's OBB, its box, a channel array, four sums) and has
 * 16014090 walk the region tree into it (thiscall: ECX the tree, [ESP+4] the
 * OBB, [ESP+8] the context; ret 8). The walk only adds into that zeroed
 * memory, from the tree's data, the OBB and the box: its whole result. An
 * object that has not moved since (at the lake Ire most of 300: the walk was
 * a fifth of the frame) gets the same bits written back -- the array's
 * non-zero channels, the sums, EAX/ECX/EDX (dead in the caller: it writes
 * them, and the flags, before reading) -- with the walk's final flags and
 * stack. A changed tree starts afresh (walk_tree_generation). Checked by
 * walking every hit as well: 43792 hits over 7 locations, 0 differing.
 * <data>/no-region-cache turns it off. */
void RENDERER_REGION_WALK_LIFTED(void);

typedef struct {
    uint64_t key;                 /* 0: empty */
    uint32_t tree, generation, stamp;
    uint32_t obb[15], query[6];
    uint32_t sums[4], eax, ecx, edx;
    uint32_t count, capacity;
    uint32_t *entries;            /* count x {channel, first, second} */
} walk_entry;

#define WALK_SLOTS 8192u
#define WALK_PROBES 8u
static walk_entry *walk_cache;
static int walk_mode = -1;        /* -1 unread, 0 off, 1 on */
/* A region tree as the walk reads it: the header, its split nodes, the leaf
 * table and the records (megabytes: 28 MB at the lake Ire). Hashed whole
 * when first met, in 64 KB chunks; a frame checks its header and the next
 * few chunks in turn, a changed chunk giving the tree a new generation. */
#define WALK_CHUNK 65536u
#define WALK_CHECKS 4u
typedef struct {
    uint32_t tree, frame, generation, chunks, cursor;
    uint32_t header[19];
    uint32_t at[3], bytes[3];     /* nodes, table, records */
    uint64_t *hashes;
} walk_tree_state;
static walk_tree_state walk_tree[8];
static uint32_t walk_generations;

static uint64_t walk_hash(uint32_t at, uint32_t n)
{
    const RECOMP_MEM_QUAL uint8_t *b = GPTR(at);
    uint64_t h = 0x9E3779B97F4A7C15ull ^ n;
    uint32_t i = 0;
    for (; i + 8 <= n; i += 8) {
        uint64_t w;
        memcpy(&w, (const void *)(b + i), 8);
        h = (h ^ w) * 0x100000001B3ull;
        h ^= h >> 29;
    }
    for (; i < n; ++i) h = (h ^ b[i]) * 0x100000001B3ull;
    return h;
}

/* Chunk k of the tree's parts: its address and length. */
static void walk_chunk(const walk_tree_state *t, uint32_t k, uint32_t *at, uint32_t *n)
{
    for (unsigned p = 0; p < 3; ++p) {
        uint32_t chunks = (t->bytes[p] + WALK_CHUNK - 1u) / WALK_CHUNK;
        if (k < chunks) {
            *at = t->at[p] + k * WALK_CHUNK;
            *n = t->bytes[p] - k * WALK_CHUNK < WALK_CHUNK ? t->bytes[p] - k * WALK_CHUNK : WALK_CHUNK;
            return;
        }
        k -= chunks;
    }
    *at = 0; *n = 0;
}

static int walk_tree_layout(uint32_t tree, walk_tree_state *t)
{
    uint32_t internal = MEM32(tree + 60), nodes = MEM32(tree + 68), table = MEM32(tree + 72), data = MEM32(tree + 56);
    if (internal > 1u << 22 || !region_range(nodes, internal * 12u + 12u)) return 0;
    uint32_t leaves = internal ? 0 : 1;
    for (uint32_t i = 0; i < internal; ++i)
        for (uint32_t side = 0; side < 2; ++side) {
            uint32_t child = MEM32(nodes + i * 12u + side * 4u);
            if (child >= internal && child - internal >= leaves) leaves = child - internal + 1u;
        }
    if (leaves > 1u << 22 || !region_range(table, leaves * 8u)) return 0;
    uint32_t span = 0;
    for (uint32_t i = 0; i < leaves; ++i) {
        uint32_t offset = MEM32(table + i * 8u), at = data + (offset & 0x7fffffffu);
        if (at < data || !region_range(at, 2)) return 0;
        uint32_t end = (offset & 0x7fffffffu) + 2u + MEM16(at) * ((offset >> 31) ? 4u : 3u);
        if (end > span) span = end;
    }
    if (!region_range(data, span)) return 0;
    t->at[0] = nodes; t->bytes[0] = internal * 12u;
    t->at[1] = table; t->bytes[1] = leaves * 8u;
    t->at[2] = data;  t->bytes[2] = span;
    t->chunks = 0;
    for (unsigned p = 0; p < 3; ++p) t->chunks += (t->bytes[p] + WALK_CHUNK - 1u) / WALK_CHUNK;
    return 1;
}

static uint32_t walk_tree_generation(uint32_t tree)
{
    uint32_t frame = void_frames_presented(), slot = 8, oldest = 0;
    for (uint32_t i = 0; i < 8; ++i) {
        if (walk_tree[i].tree == tree && walk_tree[i].generation && !memcmp(walk_tree[i].header, (const void *)GPTR(tree), 76)) {
            slot = i;
            break;
        }
        if (frame - walk_tree[i].frame > frame - walk_tree[oldest].frame) oldest = i;
    }
    if (slot < 8) {
        walk_tree_state *t = &walk_tree[slot];
        if (t->frame != frame) {
            t->frame = frame;
            for (uint32_t c = 0; c < WALK_CHECKS && t->chunks; ++c) {
                uint32_t k = t->cursor++ % t->chunks, at, n;
                walk_chunk(t, k, &at, &n);
                uint64_t h = walk_hash(at, n);
                if (h != t->hashes[k]) {
                    t->hashes[k] = h;
                    t->generation = ++walk_generations ? walk_generations : ++walk_generations;
                    void_log("[region] tree %08X changed (chunk %u): generation %u", tree, k, t->generation);
                }
            }
        }
        return t->generation;
    }
    /* A tree met for the first time, or rebuilt (its header differs). */
    walk_tree_state *t = &walk_tree[oldest];
    free(t->hashes);
    memset(t, 0, sizeof *t);
    if (!walk_tree_layout(tree, t)) return 0;
    t->hashes = (uint64_t *)malloc((size_t)t->chunks * sizeof *t->hashes);
    if (!t->hashes) { memset(t, 0, sizeof *t); return 0; }
    for (uint32_t k = 0; k < t->chunks; ++k) {
        uint32_t at, n;
        walk_chunk(t, k, &at, &n);
        t->hashes[k] = walk_hash(at, n);
    }
    t->tree = tree;
    t->frame = frame;
    t->generation = ++walk_generations ? walk_generations : ++walk_generations;
    memcpy(t->header, (const void *)GPTR(tree), 76);
    return t->generation;
}

static uint64_t walk_key(uint32_t tree, uint32_t generation, uint32_t obb, uint32_t query)
{
    uint64_t h = 0xCBF29CE484222325ull;
    h = (h ^ tree) * 0x100000001B3ull;
    h = (h ^ generation) * 0x100000001B3ull;
    for (unsigned i = 0; i < 15; ++i) h = (h ^ MEM32(obb + i * 4u)) * 0x100000001B3ull;
    for (unsigned i = 0; i < 6; ++i) h = (h ^ MEM32(query + i * 4u)) * 0x100000001B3ull;
    return h ? h : 1;
}

static int walk_same(const walk_entry *e, uint64_t key, uint32_t tree, uint32_t generation, uint32_t obb, uint32_t query)
{
    if (e->key != key || e->tree != tree || e->generation != generation) return 0;
    for (unsigned i = 0; i < 15; ++i) if (e->obb[i] != MEM32(obb + i * 4u)) return 0;
    for (unsigned i = 0; i < 6; ++i) if (e->query[i] != MEM32(query + i * 4u)) return 0;
    return 1;
}

static int walk_zero(uint32_t channels, uint32_t count, uint32_t context)
{
    for (uint32_t i = 0; i < count * 2u; ++i) if (MEM32(channels + i * 4u)) return 0;
    for (unsigned i = 0; i < 4; ++i) if (MEM32(context + 16 + i * 4u)) return 0;
    return 1;
}

static int walk_cached(void)
{
    if (walk_mode < 0) {
        char path[1200];
        snprintf(path, sizeof path, "%s/no-region-cache", void_data_dir());
        walk_mode = access(path, F_OK) == 0 ? 0 : 1;
        if (!walk_mode) void_log("[region] per-object walk cache off");
        if (walk_mode) walk_cache = (walk_entry *)calloc(WALK_SLOTS, sizeof *walk_cache);
        if (!walk_cache) walk_mode = 0;
    }
    uint32_t stack = g_esp, tree = g_ecx;
    if (!walk_mode || !void_renderer_region_enabled() || g_fp_top != 0 || !region_range(stack, 12) ||
        !region_range(tree, 76)) return 0;
    uint32_t obb = MEM32(stack + 4), context = MEM32(stack + 8);
    if (!region_range(obb, 60) || !region_range(context, 32) || MEM32(context) != tree || MEM32(context + 4) != obb)
        return 0;
    uint32_t query = MEM32(context + 8), channels = MEM32(context + 12), count = MEM32(tree + 4);
    if (!region_range(query, 24) || !count || count > 4096 || !region_range(channels, count * 8u) ||
        region_overlap(channels, count * 8u, context, 32) || region_overlap(channels, count * 8u, stack - 4096u, 4108u) ||
        !walk_zero(channels, count, context)) return 0;
    uint32_t generation = walk_tree_generation(tree);
    if (!generation) return 0;
    uint64_t key = walk_key(tree, generation, obb, query);
    uint32_t frame = void_frames_presented(), at = (uint32_t)key & (WALK_SLOTS - 1u), victim = at;
    walk_entry *hit = NULL;
    for (uint32_t i = 0; i < WALK_PROBES; ++i) {
        walk_entry *e = &walk_cache[(at + i) & (WALK_SLOTS - 1u)];
        if (walk_same(e, key, tree, generation, obb, query)) { hit = e; break; }
        if (!e->key) { victim = (at + i) & (WALK_SLOTS - 1u); break; }
        if (frame - e->stamp > frame - walk_cache[victim].stamp) victim = (at + i) & (WALK_SLOTS - 1u);
    }
    if (hit) {
        for (uint32_t i = 0; i < hit->count; ++i) {
            uint32_t c = hit->entries[i * 3u];
            MEM32(channels + c * 8u) = hit->entries[i * 3u + 1];
            MEM32(channels + c * 8u + 4u) = hit->entries[i * 3u + 2];
        }
        for (unsigned i = 0; i < 4; ++i) MEM32(context + 16 + i * 4u) = hit->sums[i];
        g_eax = hit->eax; g_ecx = hit->ecx; g_edx = hit->edx;
        /* As the walk ends: add esp, 0x2c; ret 8. */
        g_flag_k = FK_ADD; g_flag_a = stack - 0x2Cu; g_flag_b = 0x2Cu; g_flag_cf = 0;
        g_esp = stack + 12u;
        hit->stamp = frame;
        return 1;
    }
    RENDERER_REGION_WALK_LIFTED();
    walk_entry *e = &walk_cache[victim];
    uint32_t n = 0;
    for (uint32_t c = 0; c < count; ++c) if (MEM32(channels + c * 8u) || MEM32(channels + c * 8u + 4u)) ++n;
    if (n > e->capacity) {
        uint32_t *grown = (uint32_t *)realloc(e->entries, (size_t)n * 3u * sizeof *grown);
        if (!grown) { e->key = 0; return 1; }
        e->entries = grown;
        e->capacity = n;
    }
    e->count = 0;
    for (uint32_t c = 0; c < count; ++c) {
        uint32_t first = MEM32(channels + c * 8u), second = MEM32(channels + c * 8u + 4u);
        if (!first && !second) continue;
        e->entries[e->count * 3u] = c;
        e->entries[e->count * 3u + 1] = first;
        e->entries[e->count * 3u + 2] = second;
        ++e->count;
    }
    for (unsigned i = 0; i < 4; ++i) e->sums[i] = MEM32(context + 16 + i * 4u);
    for (unsigned i = 0; i < 15; ++i) e->obb[i] = MEM32(obb + i * 4u);
    for (unsigned i = 0; i < 6; ++i) e->query[i] = MEM32(query + i * 4u);
    e->eax = g_eax; e->ecx = g_ecx; e->edx = g_edx;
    e->tree = tree; e->generation = generation; e->stamp = frame; e->key = key;
    return 1;
}

void RENDERER_REGION_WALK(void) { if (!walk_cached()) RENDERER_REGION_WALK_LIFTED(); }
#else
uint64_t void_renderer_region_counts(void) { return 0; }
#endif
