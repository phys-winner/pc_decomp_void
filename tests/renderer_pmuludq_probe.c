/* Compare the actual emitted PMULUDQ with the x86 CPU's SSE2 instruction. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "recomp_types.h"

uint32_t g_eax, g_ecx, g_edx, g_ebx, g_esp, g_esi, g_edi, g_ebp;
ptrdiff_t g_mem_base;
xmm_t g_xmm[8];
uint32_t g_mxcsr;

static uint32_t preserved_flags[4];
static uint32_t random_state = 0x31415926u;
static uint32_t next_random(void) {
    random_state ^= random_state << 13;
    random_state ^= random_state >> 17;
    random_state ^= random_state << 5;
    return random_state;
}

static __declspec(noinline) void native_product(const xmm_t *left, const xmm_t *right,
    xmm_t *result, uint32_t flags, uint32_t *after, int memory) {
    if (memory) {
        __asm {
            mov esi, left
            mov edi, right
            mov edx, result
            mov ecx, after
            push flags
            popfd
            movdqu xmm0, [esi]
            pmuludq xmm0, [edi]
            movdqu [edx], xmm0
            pushfd
            pop eax
            mov [ecx], eax
        }
    } else {
        __asm {
            mov esi, left
            mov edi, right
            mov edx, result
            mov ecx, after
            movdqu xmm0, [esi]
            movdqu xmm1, [edi]
            push flags
            popfd
            pmuludq xmm0, xmm1
            movdqu [edx], xmm0
            pushfd
            pop eax
            mov [ecx], eax
        }
    }
}

#include "pmuludq-generated.h"

int main(void) {
    const uint32_t edges[] = {0, 1, 2, 0x7FFFFFFFu, 0x80000000u, 0x80000001u, 0xFFFFFFFEu, 0xFFFFFFFFu};
    const uint32_t flags[] = {0x202u, 0xAD7u};
    uint32_t comparisons = 0;
    for (unsigned sample = 0; sample < 4160; sample++) {
        for (unsigned c = 0; c < sizeof(pmul_cases) / sizeof(pmul_cases[0]); c++) {
            const pmul_case_t *test = pmul_cases + c;
            __declspec(align(16)) xmm_t memory_value;
            xmm_t before[8], expected;
            uint32_t registers[8], native_flags;
            for (unsigned x = 0; x < 8; x++)
                for (unsigned lane = 0; lane < 4; lane++)
                    g_xmm[x].u32[lane] = next_random();
            for (unsigned lane = 0; lane < 4; lane++) memory_value.u32[lane] = next_random();
            if (sample < 64) {
                g_xmm[test->destination].u32[0] = edges[sample / 8];
                g_xmm[test->destination].u32[2] = edges[sample % 8];
                if (test->memory) {
                    memory_value.u32[0] = edges[sample % 8];
                    memory_value.u32[2] = edges[sample / 8];
                } else if (test->destination != test->source) {
                    g_xmm[test->source].u32[0] = edges[sample % 8];
                    g_xmm[test->source].u32[2] = edges[sample / 8];
                }
            }
            memcpy(before, g_xmm, sizeof(before));
            g_eax = registers[0] = 0x10203040u;
            g_ecx = registers[1] = 0x50607080u;
            g_edx = registers[2] = 0x90ABCDEFu;
            g_ebx = registers[3] = (uint32_t)(uintptr_t)&memory_value;
            g_esp = registers[4] = 0x11223344u;
            g_esi = registers[5] = 0x55667788u;
            g_edi = registers[6] = 0x99AABBCCu;
            g_ebp = registers[7] = 0xDDEEFF00u;
            g_flag_k = 0x15u; g_flag_a = 0x81234567u;
            g_flag_b = 0x76543210u; g_flag_cf = 1u;
            for (unsigned f = 0; f < sizeof(flags) / sizeof(flags[0]); f++) {
                memcpy(g_xmm, before, sizeof(before));
                native_product(before + test->destination,
                    test->memory ? &memory_value : before + test->source,
                    &expected, flags[f], &native_flags, test->memory);
                test->lifted();
                for (unsigned x = 0; x < 8; x++)
                    if (memcmp(g_xmm + x, x == test->destination ? &expected : before + x, sizeof(xmm_t))) {
                        fprintf(stderr, "case=%u sample=%u xmm=%u mismatch\n", c, sample, x);
                        return 1;
                    }
                const uint32_t observed[] = {g_eax, g_ecx, g_edx, g_ebx, g_esp, g_esi, g_edi, g_ebp};
                const uint32_t lazy_flags[] = {0x15u, 0x81234567u, 0x76543210u, 1u};
                if (memcmp(observed, registers, sizeof(registers)) ||
                    memcmp(preserved_flags, lazy_flags, sizeof(lazy_flags)) ||
                    g_flag_k != lazy_flags[0] || g_flag_a != lazy_flags[1] ||
                    g_flag_b != lazy_flags[2] || g_flag_cf != lazy_flags[3] ||
                    ((native_flags ^ flags[f]) & 0x8D5u)) {
                    fprintf(stderr, "case=%u sample=%u register or flag mutation\n", c, sample);
                    return 2;
                }
                comparisons++;
            }
        }
    }
    printf("PASS PMULUDQ cases=%u comparisons=%u\n", (unsigned)(sizeof(pmul_cases) / sizeof(pmul_cases[0])), comparisons);
    return 0;
}
