/* RendererD3D's weighted region lighting; same geometry, octant tests and
 * float addition order, without per-record guest register/stack emulation. */
#include "host.h"
#include <math.h>
#include <string.h>

/* Like generated code, guest accesses run while the guest lock is held. */
#if defined(RECOMP_PLAIN_MEMORY)
#undef RECOMP_MEM_QUAL
#define RECOMP_MEM_QUAL
#endif

#ifndef VOID_RELEASE
/* GENERATED_REGION_SAT */
void sub_160D6ED0(void);
void sub_160D6ED0_lifted(void);
void sub_1105E810_lifted(void);
int void_renderer_native_enabled(void);
int void_renderer_region_enabled(void);
void sub_16013760_lifted(void);
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

void sub_160D6ED0(void) { region_sat_call(0x162D2A64u, sub_160D6ED0_lifted); }
void sub_1105E810(void) { region_sat_call(0x11122CE0u, sub_1105E810_lifted); }

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
    if (!void_renderer_region_enabled() || g_fp_top != 0 || MEM32(0x162D2A64u) != 0x3f7fffefu ||
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
                        if (recomp_yield_hook && g_backedges >= RECOMP_YIELD_EVERY - 32u) sub_160D6ED0();
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

void sub_16013760(void)
{
    if (void_renderer_region_enabled() && void_renderer_region_calculate()) ++region_native_calls;
    else { ++region_fallback_calls; sub_16013760_lifted(); }
}
#else
uint64_t void_renderer_region_counts(void) { return 0; }
#endif
