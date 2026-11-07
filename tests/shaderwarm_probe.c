#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#ifndef RENDERER_EFFECT_PREGENERATE_VA
#define RENDERER_EFFECT_PREGENERATE_VA 0x16203D50u
#define RENDERER_EFFECT_LIBRARY_VT 0x162D6794u
#endif

static uint32_t memory[0x10000 / 4];
#define MEM32(address) memory[(address) / 4]
static int void_vm_readable(uint32_t address, uint32_t size)
{
    return address >= 0x100 && (uint64_t)address + size <= sizeof memory;
}
#include "library-effects.h"

static int void_shader_warming, calls, locks, hits = 1;
#ifdef _MSC_VER
#define _Thread_local __declspec(thread)
#endif
_Thread_local int void_shader_pregenerating;
static uint32_t last_effect;
static void void_machine_enter(void) { assert(!locks); ++locks; }
static void void_machine_leave(void) { assert(locks == 1); --locks; }
static void void_log(const char *format, ...) { (void)format; }
static uint64_t void_monotonic_ns(void) { return 0; }
static int void_vm_find(const uint8_t *needle, size_t size, uint32_t *out, int max)
{
    assert(*(const uint32_t *)needle == RENDERER_EFFECT_LIBRARY_VT && size == 4 && max == 64);
    for (int i = 0; i < hits; ++i) out[i] = 0x1000;
    return hits;
}
static uint32_t void_call_guest_this(uint32_t address, uint32_t self, int argc, const uint32_t *argv)
{
    assert(address == RENDERER_EFFECT_PREGENERATE_VA && !argc && !argv && locks == 1
           && void_shader_warming && void_shader_pregenerating);
    last_effect = self;
    ++calls;
    return 1;
}
#include "warm-shaders.h"

int main(void)
{
    uint32_t effects[512];
    MEM32(0x1000 + 0x2C) = 0x2000;
    MEM32(0x1000 + 0x30) = 2;
    MEM32(0x2000) = 0x2100; MEM32(0x2004) = 0x2200;
    MEM32(0x2100) = 0x2200; MEM32(0x2104) = 0x2000; MEM32(0x2110) = 0x3000;
    MEM32(0x2200) = 0x2000; MEM32(0x2204) = 0x2100; MEM32(0x2210) = 0x3100;
    MEM32(0x300C) = 0x4000; MEM32(0x310C) = 0x4000; MEM32(0x403C) = RENDERER_EFFECT_PREGENERATE_VA;
    assert(library_effects(0x1000, effects) == 2 && effects[0] == 0x3000 && effects[1] == 0x3100);
    warm_shaders(0, 0); assert(calls == 2 && last_effect == 0x310C && !locks && !void_shader_warming);
    calls = 0; warm_shaders(2, 0); assert(calls == 1 && last_effect == 0x310C && !locks && !void_shader_warming);
    calls = 0; warm_shaders(1, 1); assert(calls == 1 && last_effect == 0x300C && !locks && !void_shader_warming);
    calls = 0; warm_shaders(-1, 0); warm_shaders(3, 0); warm_shaders(2, 1); warm_shaders(1, 3);
    assert(!calls && !locks && !void_shader_warming);
    hits = 2; warm_shaders(0, 0); assert(!calls && !locks && !void_shader_warming); hits = 1;
    MEM32(0x2204) = 0; assert(!library_effects(0x1000, effects)); MEM32(0x2204) = 0x2100;
    MEM32(0x2200) = 0x2100; assert(!library_effects(0x1000, effects)); MEM32(0x2200) = 0x2000;
    MEM32(0x310C) = 0xFFF0; assert(!library_effects(0x1000, effects)); MEM32(0x310C) = 0x4000;
    MEM32(0x403C) = 0; assert(!library_effects(0x1000, effects)); MEM32(0x403C) = RENDERER_EFFECT_PREGENERATE_VA;
    MEM32(0x1030) = 513; assert(!library_effects(0x1000, effects));
    MEM32(0x1030) = 0; assert(!library_effects(0x1000, effects));
    assert(!library_effects(0xFFFFFFF0, effects));
    assert(!void_shader_pregenerating);
    puts("effect enumeration: valid list, broken links, cycle, inaccessible vtable, wrong type/count/address passed");
    return 0;
}
