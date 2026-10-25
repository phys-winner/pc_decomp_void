/* RendererD3D's reserved vector append: one 12-byte triangle record.
 * Growth and unusual layouts retain the original allocator/exception path. */
#include "host.h"

#ifndef VOID_RELEASE
void sub_16082260_lifted(void);
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

void sub_16082260(void) { if (!void_renderer_append12(0)) sub_16082260_lifted(); }
#else
void void_renderer_native_enable(int enabled) { (void)enabled; }
int void_renderer_native_enabled(void) { return 0; }
void void_renderer_region_enable(int enabled) { (void)enabled; }
int void_renderer_region_enabled(void) { return 0; }
int void_renderer_append12(int preserve_ecx) { (void)preserve_ecx; return 0; }
#endif
