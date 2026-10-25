/* Native Theora reconstruction for Video.dll.
 *
 * Video.dll plays the game's videos (1280x720 cutscenes and glyph
 * tutorials, 512x512 video textures in the world) with libtheora 1.0
 * (Xiph.Org, BSD licence, reference/libtheora) built with its MSVC MMX
 * routines. Lifted, the MMX code runs a lane at a time: a 720p frame took
 * 65-175 ms on the device, 42 % of it rebuilding fragments (dequantisation,
 * iDCT, prediction) and 24 % in the loop filter. The decoder reaches both
 * through its function table (oc_base_opt_vtable, cdecl), so they are
 * replaced here by libtheora's own C versions working on the guest's state:
 *
 *   state_frag_recon             0x10018800  (state, frag, pli, dct_coeffs,
 *                                 last_zzi, ncoefs, dc_iquant, ac_iquant)
 *   state_loop_filter_frag_rows  0x10018ED0  (state, bv, refi, pli,
 *                                 fragy0, fragy_end)
 *
 * The iDCT is libtheora's (lib/dec/idct.c, included unmodified); Theora
 * specifies it exactly, and the MMX routines give the same pixels.
 * VOID_THEORA=lifted runs the lifted bodies; =check runs both on the same
 * input and logs any pixel that differs. */
#include "host.h"
#include "hud.h"
#include <stdlib.h>
#include <string.h>

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wshift-op-parentheses"
#include "../../reference/libtheora/lib/dec/idct.c"
#pragma clang diagnostic pop

#ifndef VOID_RELEASE
#define THEORA_FRAG_RECON sub_15018800             /* the 2009 Video.dll */
#define THEORA_FRAG_RECON_LIFTED sub_15018800_lifted
#define THEORA_LOOP_FILTER sub_15018ED0
#define THEORA_LOOP_FILTER_LIFTED sub_15018ED0_lifted
#endif

#ifdef THEORA_FRAG_RECON
void THEORA_FRAG_RECON_LIFTED(void);
void THEORA_LOOP_FILTER_LIFTED(void);

/* libtheora 1.0's oc_theora_state as 32-bit MSVC lays it out. */
#define TS_FRAME_WIDTH 4           /* th_info info */
#define TS_FRAME_HEIGHT 8
#define TS_PIXEL_FMT 48
#define TS_FPLANES 96              /* oc_fragment_plane[3]: nhfrags, nvfrags, froffset, nfrags, ... */
#define TS_FRAGS 196
#define TS_REF_FRAME_IDX 576       /* int[3]: OC_FRAME_GOLD, _PREV, _SELF */
#define TS_REF_FRAME_BUFS 588      /* th_img_plane[3][3]: width, height, stride, data */
#define TS_REF_FRAME_DATA 732
/* oc_fragment: a word of bit fields (coded:1, invalid:1, qi:6, mbmode:8,
 * dc:16), unsigned char *buffer[4], oc_border_info *border, signed char mv[2]. */
#define FRAG_SIZE 28u
#define FRAG_BUFFER 4u
#define FRAG_MV 24u

#define OC_FRAME_SELF 2
#define OC_MODE_INTRA 1
#define CLAMP255(x) ((unsigned char)((((x) < 0) - 1) & ((x) | -((x) > 255))))

static const int OC_FZIG_ZAG[64] = {
     0,  1,  8, 16,  9,  2,  3, 10,
    17, 24, 32, 25, 18, 11,  4,  5,
    12, 19, 26, 33, 40, 48, 41, 34,
    27, 20, 13,  6,  7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36,
    29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46,
    53, 60, 61, 54, 47, 55, 62, 63,
};
/* The reference frame of each macro block mode: PREV, SELF (intra), PREV,
 * PREV, PREV, GOLD, GOLD, PREV. */
static const int OC_FRAME_FOR_MODE[8] = {1, 2, 1, 1, 1, 0, 0, 1};

enum { THEORA_NATIVE, THEORA_LIFTED, THEORA_CHECK };
static int theora_mode = -1;

static int mode(void)
{
    if (theora_mode < 0) {
        const char *env = getenv("VOID_THEORA");
        theora_mode = !env ? THEORA_NATIVE : !strcmp(env, "lifted") ? THEORA_LIFTED :
                      !strcmp(env, "check") ? THEORA_CHECK : THEORA_NATIVE;
        void_log("[video] Theora reconstruction and loop filter: %s", theora_mode == THEORA_LIFTED ? "lifted" :
                 theora_mode == THEORA_CHECK ? "native, checked against the lifted bodies" : "native");
    }
    return theora_mode;
}

static int plane_stride(uint32_t state, uint32_t framei, int pli)
{
    return (int32_t)MEM32(state + TS_REF_FRAME_BUFS + 48u * framei + 16u * (uint32_t)pli + 8u);
}

/* oc_state_get_mv_offsets: the offsets of the predictor(s) for a motion
 * vector; 2 when it has a fractional part (the average of two). */
static int mv_offsets(uint32_t state, int offsets[2], int dx, int dy, int ystride, int pli)
{
    int fmt = (int32_t)MEM32(state + TS_PIXEL_FMT);
    int xprec = 1 + (!(fmt & 1) && pli), yprec = 1 + (!(fmt & 2) && pli);
    int xfrac = !!(dx & ((1 << xprec) - 1)), yfrac = !!(dy & ((1 << yprec) - 1));
    offsets[0] = (dx >> xprec) + (dy >> yprec) * ystride;
    if (!xfrac && !yfrac) return 1;
    offsets[1] = offsets[0];
    offsets[dx >= 0] += xfrac;
    offsets[dy >= 0] += ystride & -yfrac;
    return 2;
}

/* oc_state_frag_recon_c over guest memory; 0 if the fragment is not one
 * this code knows (the lifted body takes it). */
static int frag_recon(uint32_t state, uint32_t frag, int pli, uint32_t coeffs, int last_zzi, int ncoefs,
                      unsigned dc_iquant, uint32_t ac_iquant)
{
    int mbmode = (int8_t)MEM8(frag + 1);
    if (mbmode < 0 || mbmode > 7 || ncoefs > 64) return 0;
    int16_t res[64];
    int dc = (int16_t)MEM16(frag + 2);
    if (last_zzi < 2) {
        int16_t p = (int16_t)((dc * (int32_t)dc_iquant + 15) >> 5);
        for (int i = 0; i < 64; ++i) res[i] = p;
    } else {
        const int16_t *c = (const int16_t *)GPTR(coeffs);
        const uint16_t *q = (const uint16_t *)GPTR(ac_iquant);
        int16_t dct[64];
        int zzi;
        dct[0] = (int16_t)(dc * (int32_t)dc_iquant);
        for (zzi = 1; zzi < ncoefs; ++zzi) {
            int ci = OC_FZIG_ZAG[zzi];
            dct[ci] = (int16_t)((int32_t)c[zzi] * q[ci]);
        }
        if (last_zzi < 10) {
            for (; zzi < 10; ++zzi) dct[OC_FZIG_ZAG[zzi]] = 0;
            oc_idct8x8_10_c(res, dct);
        } else {
            for (; zzi < 64; ++zzi) dct[OC_FZIG_ZAG[zzi]] = 0;
            oc_idct8x8_c(res, dct);
        }
    }
    uint32_t dst_framei = MEM32(state + TS_REF_FRAME_IDX + 4u * OC_FRAME_SELF);
    int dst_stride = plane_stride(state, dst_framei, pli);
    uint8_t *dst = (uint8_t *)GPTR(MEM32(frag + FRAG_BUFFER + 4u * dst_framei));
    const int16_t *r = res;
    if (mbmode == OC_MODE_INTRA) {
        for (int i = 0; i < 8; ++i, dst += dst_stride)
            for (int j = 0; j < 8; ++j, ++r) dst[j] = CLAMP255(*r + 128);
        return 1;
    }
    uint32_t ref_framei = MEM32(state + TS_REF_FRAME_IDX + 4u * (uint32_t)OC_FRAME_FOR_MODE[mbmode]);
    int ref_stride = plane_stride(state, ref_framei, pli);
    uint32_t ref = MEM32(frag + FRAG_BUFFER + 4u * ref_framei);
    int offsets[2];
    if (mv_offsets(state, offsets, (int8_t)MEM8(frag + FRAG_MV), (int8_t)MEM8(frag + FRAG_MV + 1), ref_stride, pli) > 1) {
        const uint8_t *s1 = (const uint8_t *)GPTR(ref + (uint32_t)offsets[0]);
        const uint8_t *s2 = (const uint8_t *)GPTR(ref + (uint32_t)offsets[1]);
        for (int i = 0; i < 8; ++i, dst += dst_stride, s1 += ref_stride, s2 += ref_stride)
            for (int j = 0; j < 8; ++j, ++r) dst[j] = CLAMP255(*r + (((int)s1[j] + s2[j]) >> 1));
    } else {
        const uint8_t *s = (const uint8_t *)GPTR(ref + (uint32_t)offsets[0]);
        for (int i = 0; i < 8; ++i, dst += dst_stride, s += ref_stride)
            for (int j = 0; j < 8; ++j, ++r) dst[j] = CLAMP255(*r + s[j]);
    }
    return 1;
}

static void loop_filter_h(uint8_t *pix, int ystride, const int32_t *bv)
{
    pix -= 2;
    for (int y = 0; y < 8; ++y, pix += ystride) {
        int f = pix[0] - pix[3] + 3 * (pix[2] - pix[1]);
        f = bv[(f + 4) >> 3];
        pix[1] = CLAMP255(pix[1] + f);
        pix[2] = CLAMP255(pix[2] - f);
    }
}

static void loop_filter_v(uint8_t *pix, int ystride, const int32_t *bv)
{
    pix -= ystride * 2;
    for (int x = 0; x < 8; ++x, ++pix) {
        int f = pix[0] - pix[ystride * 3] + 3 * (pix[ystride * 2] - pix[ystride]);
        f = bv[(f + 4) >> 3];
        pix[ystride] = CLAMP255(pix[ystride] + f);
        pix[ystride * 2] = CLAMP255(pix[ystride * 2] - f);
    }
}

/* oc_state_loop_filter_frag_rows_c: the bounding values (oc_state_loop_
 * filter_init, run by the lifted decoder before) say how far to move each
 * edge; the order of the edges is VP3's. */
static void loop_filter_rows(uint32_t state, uint32_t bv_va, int refi, int pli, int fragy0, int fragy_end)
{
    const int32_t *bv = (const int32_t *)GPTR(bv_va) + 127;
    int stride = plane_stride(state, (uint32_t)refi, pli);
    uint32_t fplane = state + TS_FPLANES + 32u * (uint32_t)pli;
    uint32_t nhfrags = MEM32(fplane), froffset = MEM32(fplane + 8), nfrags = MEM32(fplane + 12);
    uint32_t row = FRAG_SIZE * nhfrags, buffer = FRAG_BUFFER + 4u * (uint32_t)refi;
    uint32_t frag_top = MEM32(state + TS_FRAGS) + FRAG_SIZE * froffset;
    uint32_t frag0 = frag_top + row * (uint32_t)fragy0;
    uint32_t frag0_end = frag0 + row * (uint32_t)(fragy_end - fragy0);
    uint32_t frag_bot = frag_top + FRAG_SIZE * nfrags;
    for (; frag0 < frag0_end; frag0 += row) {
        uint32_t frag_end = frag0 + row;
        for (uint32_t frag = frag0; frag < frag_end; frag += FRAG_SIZE) {
            if (!(MEM8(frag) & 1)) continue;
            uint8_t *pix = (uint8_t *)GPTR(MEM32(frag + buffer));
            if (frag > frag0) loop_filter_h(pix, stride, bv);
            if (frag0 > frag_top) loop_filter_v(pix, stride, bv);
            if (frag + FRAG_SIZE < frag_end && !(MEM8(frag + FRAG_SIZE) & 1)) loop_filter_h(pix + 8, stride, bv);
            if (frag + row < frag_bot && !(MEM8(frag + row) & 1))
                loop_filter_v((uint8_t *)GPTR(MEM32(frag + row + buffer)), stride, bv);
        }
    }
}

static struct { uint32_t calls, differ; } recon_check, filter_check;

static void check_report(const char *what, uint32_t calls, uint32_t differ, uint32_t every)
{
    if ((calls & (every - 1)) == 1)
        void_log("[video] %s check: %u calls, %u differ from the lifted body", what, calls, differ);
}

void THEORA_FRAG_RECON(void)
{
    void_hud_video_frame();   /* a film is being decoded (the touch layer's skip) */
    uint32_t esp = g_esp;
    uint32_t state = MEM32(esp + 4), frag = MEM32(esp + 8), coeffs = MEM32(esp + 16), ac_iquant = MEM32(esp + 32);
    int pli = (int32_t)MEM32(esp + 12), last_zzi = (int32_t)MEM32(esp + 20), ncoefs = (int32_t)MEM32(esp + 24);
    unsigned dc_iquant = MEM16(esp + 28);
    int m = mode();
    if (m == THEORA_LIFTED) { THEORA_FRAG_RECON_LIFTED(); return; }
    if (m == THEORA_NATIVE) {
        if (frag_recon(state, frag, pli, coeffs, last_zzi, ncoefs, dc_iquant, ac_iquant)) g_esp = esp + 4;
        else THEORA_FRAG_RECON_LIFTED();
        return;
    }
    /* Check: the block before, the native result, the lifted result. */
    uint32_t dst_framei = MEM32(state + TS_REF_FRAME_IDX + 4u * OC_FRAME_SELF);
    int stride = plane_stride(state, dst_framei, pli);
    uint8_t *dst = (uint8_t *)GPTR(MEM32(frag + FRAG_BUFFER + 4u * dst_framei));
    uint8_t before[64], native_px[64];
    for (int i = 0; i < 8; ++i) memcpy(before + 8 * i, dst + i * stride, 8);
    int known = frag_recon(state, frag, pli, coeffs, last_zzi, ncoefs, dc_iquant, ac_iquant);
    for (int i = 0; i < 8; ++i) {
        memcpy(native_px + 8 * i, dst + i * stride, 8);
        memcpy(dst + i * stride, before + 8 * i, 8);
    }
    THEORA_FRAG_RECON_LIFTED();
    int same = 1;
    for (int i = 0; i < 8; ++i) same &= !memcmp(native_px + 8 * i, dst + i * stride, 8);
    ++recon_check.calls;
    if (known && !same) {
        if (recon_check.differ++ < 8)
            void_log("[video] frag_recon differs: mode %d, last_zzi %d, ncoefs %d, pli %d", (int8_t)MEM8(frag + 1),
                     last_zzi, ncoefs, pli);
    }
    check_report("frag_recon", recon_check.calls, recon_check.differ, 0x10000);
}

void THEORA_LOOP_FILTER(void)
{
    void_hud_video_frame();
    uint32_t esp = g_esp;
    uint32_t state = MEM32(esp + 4), bv = MEM32(esp + 8);
    int refi = (int32_t)MEM32(esp + 12), pli = (int32_t)MEM32(esp + 16);
    int fragy0 = (int32_t)MEM32(esp + 20), fragy_end = (int32_t)MEM32(esp + 24);
    int m = mode();
    if (m == THEORA_LIFTED || refi < 0 || refi > 2 || pli < 0 || pli > 2) { THEORA_LOOP_FILTER_LIFTED(); return; }
    if (m == THEORA_NATIVE) {
        loop_filter_rows(state, bv, refi, pli, fragy0, fragy_end);
        g_esp = esp + 4;
        return;
    }
    /* Check: the whole plane before, after the native filter, after the lifted one. */
    int fmt = (int32_t)MEM32(state + TS_PIXEL_FMT);
    size_t yh = MEM32(state + TS_FRAME_WIDTH) + 32, yv = MEM32(state + TS_FRAME_HEIGHT) + 32;
    size_t ysz = yh * yv, csz = (yh >> !(fmt & 1)) * (yv >> !(fmt & 2));
    uint8_t *plane = (uint8_t *)GPTR(MEM32(state + TS_REF_FRAME_DATA)) + (size_t)refi * (ysz + 2 * csz) +
                     (pli ? ysz + (size_t)(pli - 1) * csz : 0);
    size_t size = pli ? csz : ysz;
    uint8_t *before = malloc(size), *native_px = malloc(size);
    if (!before || !native_px) { free(before); free(native_px); THEORA_LOOP_FILTER_LIFTED(); return; }
    memcpy(before, plane, size);
    loop_filter_rows(state, bv, refi, pli, fragy0, fragy_end);
    memcpy(native_px, plane, size);
    memcpy(plane, before, size);
    THEORA_LOOP_FILTER_LIFTED();
    ++filter_check.calls;
    if (memcmp(native_px, plane, size)) {
        size_t at = 0;
        while (at < size && native_px[at] == plane[at]) ++at;
        if (filter_check.differ++ < 8)
            void_log("[video] loop filter differs: plane %d rows %d-%d, first at byte %zu of %zu", pli, fragy0,
                     fragy_end, at, size);
    }
    free(before);
    free(native_px);
    check_report("loop filter", filter_check.calls, filter_check.differ, 0x100);
}
#endif
