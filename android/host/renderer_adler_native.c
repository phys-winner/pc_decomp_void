/* RendererD3D's cdecl Adler32 leaf; the original persistent inflater remains intact. */
#include "host.h"
#include <zlib.h>

#ifdef VOID_RELEASE
#include "release_overrides.h"   /* its twin in another release (tools/lift_release.py) */
#else
#define RENDERER_ADLER32 sub_16120040             /* the 2009 RendererD3D.dll */
#define RENDERER_ADLER32_LIFTED sub_16120040_lifted
#endif

#ifdef RENDERER_ADLER32
void RENDERER_ADLER32_LIFTED(void);
int void_renderer_native_enabled(void);

static int adler_overlap(uint32_t a, uint32_t an, uint32_t b, uint32_t bn)
{
    return (uint64_t)a < (uint64_t)b + bn && (uint64_t)b < (uint64_t)a + an;
}

static int adler_valid(uint32_t at, uint32_t length)
{
    return at >= 0x10000u && at <= GUEST_USER_TOP && length <= GUEST_USER_TOP - at
        && void_vm_readable(at, length);
}

void RENDERER_ADLER32(void)
{
    uint32_t stack = g_esp;
    if (!void_renderer_native_enabled() || stack < 16u || !adler_valid(stack - 16u, 32u)) {
        RENDERER_ADLER32_LIFTED(); return;
    }
    uint32_t seed = MEM32(stack + 4), buffer = MEM32(stack + 8), length = MEM32(stack + 12);
    uint32_t remaining = length % 5552u;
    uint32_t edges = buffer && length != 1u ? length / 5552u * 348u + remaining / 16u + remaining % 16u : 0;
    /* Original len==1 reads the byte before checking NULL; retain that path. */
    if ((!buffer && length == 1u) || (buffer &&
        ((seed & 65535u) >= 65521u || (seed >> 16) >= 65521u || !adler_valid(buffer, length)
         || adler_overlap(buffer, length, stack - 16u, 32u))) ||
        (recomp_yield_hook && edges && (edges >= RECOMP_YIELD_EVERY || g_backedges >= RECOMP_YIELD_EVERY - edges))) {
        RENDERER_ADLER32_LIFTED(); return;
    }
    g_eax = (uint32_t)adler32(seed, buffer ? (const Bytef *)GPTR(buffer) : Z_NULL, length);
    /* Fallback above retains every handover if this call would reach one. */
    g_backedges += edges;
    /* All original callers consume EAX. ECX/EDX/flags and dead stack scratch
     * are caller-clobbered by this cdecl ABI; all preserved state is unchanged. */
    g_esp = stack + 4u;
}
#endif
