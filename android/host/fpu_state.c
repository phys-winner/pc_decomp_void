/* x87 save images at the original CRT math-error boundary; ported from BioShock. */
#include "host.h"

#ifndef VOID_RELEASE

static uint16_t fpu_status(void)
{
    uint16_t status = void_fpu_cmp >= 0x10000 ? (uint16_t)void_fpu_cmp :
        void_fpu_cmp == 2 ? 0x4500u : void_fpu_cmp < 0 ? 0x0100u :
        void_fpu_cmp == 0 ? 0x4000u : 0;
    return (uint16_t)((status & ~0x3800u) | (((0u - (unsigned)g_fp_top) & 7u) << 11));
}

static void fpu_store_register(uint8_t out[10], unsigned index)
{
    int64_t shadow = g_st_i64[index];
    double value = g_st[index];
    if (shadow && (double)shadow == value) {
        uint64_t magnitude = shadow < 0 ? 0u - (uint64_t)shadow : (uint64_t)shadow;
        unsigned exponent = 63u - (unsigned)__builtin_clzll(magnitude);
        uint64_t mantissa = magnitude << (63u - exponent);
        uint16_t sign_exponent = (uint16_t)((shadow < 0 ? 0x8000u : 0) | (16383u + exponent));
        memcpy(out, &mantissa, 8);
        memcpy(out + 8, &sign_exponent, 2);
    } else fp_st80(out, value);
}

static int64_t fpu_integer_shadow(const uint8_t in[10])
{
    uint64_t mantissa;
    uint16_t sign_exponent;
    memcpy(&mantissa, in, 8);
    memcpy(&sign_exponent, in + 8, 2);
    int exponent = (sign_exponent & 0x7FFF) - 16383;
    if (exponent < 0 || exponent > 63 || !(mantissa >> 63)) return 0;
    unsigned shift = 63u - (unsigned)exponent;
    if (shift && (mantissa & ((1ull << shift) - 1u))) return 0;
    uint64_t integer = mantissa >> shift;
    if (sign_exponent & 0x8000u) {
        if (integer > 0x8000000000000000ull) return 0;
        return integer == 0x8000000000000000ull ? INT64_MIN : -(int64_t)integer;
    }
    return integer <= INT64_MAX ? (int64_t)integer : 0;
}

void void_fpu_state(uint32_t address, uint32_t instruction, int restore, int operand16)
{
    unsigned environment = operand16 ? 14u : 28u, bytes = environment + 80u;
    if ((restore != 0 && restore != 1) || (operand16 != 0 && operand16 != 1) ||
        (restore ? !void_vm_readable(address, bytes) : !void_vm_writable(address, bytes)))
        void_lift_trap(instruction, "x87 save/restore requires a complete readable/writable image");
    uint8_t image[108] = {0};
    uint16_t control, status, tags;
    if (restore) {
        memcpy(image, GPTR(address), bytes);
        memcpy(&control, image, 2);
        memcpy(&status, image + (operand16 ? 2 : 4), 2);
        memcpy(&tags, image + (operand16 ? 4 : 8), 2);
        unsigned top = (status >> 11) & 7u, depth = 0;
        while (depth < 8 && ((tags >> (2u * ((top + depth) & 7u))) & 3u) != 3u) ++depth;
        for (unsigned i = depth; i < 8; ++i)
            if (((tags >> (2u * ((top + i) & 7u))) & 3u) != 3u)
                void_lift_trap(instruction, "x87 restore has noncontiguous stack tags");
        if (top != ((0u - depth) & 7u))
            void_lift_trap(instruction, "x87 restore TOP is outside the logical-stack model");
        double values[8];
        int64_t shadows[8];
        for (unsigned i = 0; i < 8; ++i) {
            values[i] = fp_ld80(image + environment + 10u * i);
            shadows[i] = fpu_integer_shadow(image + environment + 10u * i);
        }
        memcpy(g_st, values, sizeof values);
        memcpy(g_st_i64, shadows, sizeof shadows);
        g_fp_top = (int)depth;
        g_fpu_cw = control;
        void_fpu_cmp = 0x10000 | status;
        return;
    }
    if (g_fp_top < 0 || g_fp_top > 8)
        void_lift_trap(instruction, "x87 save has an invalid logical stack depth");
    control = g_fpu_cw;
    status = fpu_status();
    tags = 0xFFFFu;
    unsigned top = (status >> 11) & 7u;
    for (unsigned i = 0; i < 8; ++i) {
        fpu_store_register(image + environment + 10u * i, i);
        if (i < (unsigned)g_fp_top) {
            unsigned tag = g_st[i] == 0.0 ? 1u : isfinite(g_st[i]) ? 0u : 2u;
            unsigned shift = 2u * ((top + i) & 7u);
            tags = (uint16_t)((tags & ~(3u << shift)) | (tag << shift));
        }
    }
    memcpy(image, &control, 2);
    memcpy(image + (operand16 ? 2 : 4), &status, 2);
    memcpy(image + (operand16 ? 4 : 8), &tags, 2);
    /* shortcut: the existing x87 model has no historical FIP/FDP/FOP or sticky arithmetic exceptions; add producer tracking before exposing those fields. */
    memcpy(GPTR(address), image, bytes);
    double registers[8];
    int64_t shadows[8];
    memcpy(registers, g_st, sizeof registers);
    memcpy(shadows, g_st_i64, sizeof shadows);
    for (unsigned i = 0; i < 8; ++i) {
        g_st[(top + i) & 7u] = registers[i];
        g_st_i64[(top + i) & 7u] = shadows[i];
    }
    g_fp_top = 0;
    g_fpu_cw = 0x037F;
    void_fpu_cmp = 0x10000;
}

#endif
