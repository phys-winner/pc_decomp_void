/* Keep the emitted particle interpolation in local x87 slots for bounded inputs. */
#include "host.h"

/* The guard is pure and holds the same guest lock as generated plain-memory code. */
#if defined(RECOMP_PLAIN_MEMORY)
#undef RECOMP_MEM_QUAL
#define RECOMP_MEM_QUAL
#endif

int void_renderer_native_enabled(void);

static int particle_range(uint32_t at, uint32_t bytes)
{
    return at >= 0x10000u && at <= GUEST_USER_TOP && bytes <= GUEST_USER_TOP - at;
}

static int particle_overlap(uint32_t a, uint32_t an, uint32_t b, uint32_t bn)
{
    return (uint64_t)a < (uint64_t)b + bn && (uint64_t)b < (uint64_t)a + an;
}

int void_renderer_particle_finite(uint32_t scale, uint32_t coefficients, uint32_t integer_bias, uint32_t lookup)
{
    if (!void_renderer_native_enabled() || g_fp_top || !particle_range(g_ecx, 12)
            || g_esp < 0x10040u || !particle_range(g_esp - 48, 56)) return 0;
    /* The pinned renderer's scale/bias constants keep both polynomials finite. */
    if (MEM32(scale) != 0x358637bdu || MEM32(coefficients) != 0x40000000u
            || MEM32(coefficients + 4u) != 0x40400000u || MEM32(coefficients + 8u) != 0x3f800000u
            || MEM32(coefficients + 12u) != 0x45800000u || MEM32(integer_bias) != 0x4f800000u) return 0;
    uint32_t first = MEM32(g_ecx + 4), end = MEM32(g_ecx + 8);
    if (end < first || (end - first) % 24 || end - first > 4096u * 24u
            || !particle_range(first, end - first)) return 0;
    if (particle_overlap(first, end - first, g_ecx, 12)
            || particle_overlap(first, end - first, g_esp - 48, 56)
            || particle_overlap(first, end - first, scale, 4)
            || particle_overlap(first, end - first, coefficients, 64)
            || particle_overlap(first, end - first, lookup, 0x4000u)) return 0;
    const RECOMP_MEM_QUAL uint32_t *entry = (const uint32_t *)GPTR(first), *limit = (const uint32_t *)GPTR(end);
    for (; entry != limit; entry += 6) {
        if ((entry[3] & 0x7fffffffu) > 0x44800000u
                || (entry[4] & 0x7fffffffu) > 0x44800000u
                || (entry[2] == 1 && (entry[5] & 0x7fffffffu) > 0x44800000u)) return 0;
        uint32_t output = g_edi + entry[0] * 4u;
        if (!particle_range(output, 4) || particle_overlap(output, 4, first, end - first)
                || particle_overlap(output, 4, g_ecx, 12)
                || particle_overlap(output, 4, g_esp - 48, 56)
                || particle_overlap(output, 4, scale, 4)
                || particle_overlap(output, 4, coefficients, 64)
                || particle_overlap(output, 4, lookup, 0x4000u)) return 0;
    }
    return 1;
}
