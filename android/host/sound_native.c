/* Native replacements for hot lifted Sound.dll code.
 *
 * Sound.dll decodes Ogg Vorbis with libvorbis (Xiph.Org, BSD licence). Under
 * the x87 emulation its inverse MDCT took most of the sound thread's time,
 * and the sound thread holds the machine while it decodes, so the main
 * thread waited for it every frame. mdct_backward is replaced by the same
 * algorithm (libvorbis lib/mdct.c with float data); the arithmetic runs in
 * double as the guest's 53-bit x87 does and rounds where the guest stores.
 *
 * tools/build_android.py compiles the lifted body as sub_14018AB0_lifted.
 * VOID_MDCT=lifted runs only that body (A/B timing); VOID_MDCT=check runs it
 * after the native transform on the same input and logs the largest
 * difference (bit-identical over 13,000 blocks of the first location). */
#include "host.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

#ifdef VOID_RELEASE
#include "release_overrides.h"
#endif
#ifndef SOUND_MDCT_BACKWARD
#define SOUND_MDCT_BACKWARD sub_14018AB0          /* the 2009 Sound.dll */
#define SOUND_MDCT_BACKWARD_LIFTED sub_14018AB0_lifted
#endif
void SOUND_MDCT_BACKWARD_LIFTED(void);

#define D(v) ((double)(v))
#define F(v) ((float)(v))
/* libvorbis' constants are float literals; the guest multiplies by them as such. */
#define cPI3_8 D(.38268343236508977175f)
#define cPI2_8 D(.70710678118654752441f)
#define cPI1_8 D(.92387953251128675613f)

static void butterfly_8(float *x)
{
    double r0 = D(x[6]) + x[2];
    double r1 = D(x[6]) - x[2];
    double r2 = D(x[4]) + x[0];
    double r3 = D(x[4]) - x[0];

    x[6] = F(r0 + r2);
    x[4] = F(r0 - r2);

    r0 = D(x[5]) - x[1];
    r2 = D(x[7]) - x[3];
    x[0] = F(r1 + r0);
    x[2] = F(r1 - r0);

    r0 = D(x[5]) + x[1];
    r1 = D(x[7]) + x[3];
    x[3] = F(r2 + r3);
    x[1] = F(r2 - r3);
    x[7] = F(r1 + r0);
    x[5] = F(r1 - r0);
}

static void butterfly_16(float *x)
{
    double r0 = D(x[1]) - x[9];
    double r1 = D(x[0]) - x[8];

    x[8] = F(D(x[8]) + x[0]);
    x[9] = F(D(x[9]) + x[1]);
    x[0] = F((r0 + r1) * cPI2_8);
    x[1] = F((r0 - r1) * cPI2_8);

    r0 = D(x[3]) - x[11];
    r1 = D(x[10]) - x[2];
    x[10] = F(D(x[10]) + x[2]);
    x[11] = F(D(x[11]) + x[3]);
    x[2] = F(r0);
    x[3] = F(r1);

    r0 = D(x[12]) - x[4];
    r1 = D(x[13]) - x[5];
    x[12] = F(D(x[12]) + x[4]);
    x[13] = F(D(x[13]) + x[5]);
    x[4] = F((r0 - r1) * cPI2_8);
    x[5] = F((r0 + r1) * cPI2_8);

    r0 = D(x[14]) - x[6];
    r1 = D(x[15]) - x[7];
    x[14] = F(D(x[14]) + x[6]);
    x[15] = F(D(x[15]) + x[7]);
    x[6] = F(r0);
    x[7] = F(r1);

    butterfly_8(x);
    butterfly_8(x + 8);
}

static void butterfly_32(float *x)
{
    double r0 = D(x[30]) - x[14];
    double r1 = D(x[31]) - x[15];

    x[30] = F(D(x[30]) + x[14]);
    x[31] = F(D(x[31]) + x[15]);
    x[14] = F(r0);
    x[15] = F(r1);

    r0 = D(x[28]) - x[12];
    r1 = D(x[29]) - x[13];
    x[28] = F(D(x[28]) + x[12]);
    x[29] = F(D(x[29]) + x[13]);
    x[12] = F(r0 * cPI1_8 - r1 * cPI3_8);
    x[13] = F(r0 * cPI3_8 + r1 * cPI1_8);

    r0 = D(x[26]) - x[10];
    r1 = D(x[27]) - x[11];
    x[26] = F(D(x[26]) + x[10]);
    x[27] = F(D(x[27]) + x[11]);
    x[10] = F((r0 - r1) * cPI2_8);
    x[11] = F((r0 + r1) * cPI2_8);

    r0 = D(x[24]) - x[8];
    r1 = D(x[25]) - x[9];
    x[24] = F(D(x[24]) + x[8]);
    x[25] = F(D(x[25]) + x[9]);
    x[8] = F(r0 * cPI3_8 - r1 * cPI1_8);
    x[9] = F(r1 * cPI3_8 + r0 * cPI1_8);

    r0 = D(x[22]) - x[6];
    r1 = D(x[7]) - x[23];
    x[22] = F(D(x[22]) + x[6]);
    x[23] = F(D(x[23]) + x[7]);
    x[6] = F(r1);
    x[7] = F(r0);

    r0 = D(x[4]) - x[20];
    r1 = D(x[5]) - x[21];
    x[20] = F(D(x[20]) + x[4]);
    x[21] = F(D(x[21]) + x[5]);
    x[4] = F(r1 * cPI1_8 + r0 * cPI3_8);
    x[5] = F(r1 * cPI3_8 - r0 * cPI1_8);

    r0 = D(x[2]) - x[18];
    r1 = D(x[3]) - x[19];
    x[18] = F(D(x[18]) + x[2]);
    x[19] = F(D(x[19]) + x[3]);
    x[2] = F((r1 + r0) * cPI2_8);
    x[3] = F((r1 - r0) * cPI2_8);

    r0 = D(x[0]) - x[16];
    r1 = D(x[1]) - x[17];
    x[16] = F(D(x[16]) + x[0]);
    x[17] = F(D(x[17]) + x[1]);
    x[0] = F(r1 * cPI3_8 + r0 * cPI1_8);
    x[1] = F(r1 * cPI1_8 - r0 * cPI3_8);

    butterfly_16(x);
    butterfly_16(x + 16);
}

/* One radix-2 step on 8 values of each half; T advances by trigint after each pair. */
#define BUTTERFLY_PAIR(a, b, t0, t1)                \
    do {                                             \
        double r0 = D(x1[a]) - x2[a];                \
        double r1 = D(x1[b]) - x2[b];                \
        x1[a] = F(D(x1[a]) + x2[a]);                 \
        x1[b] = F(D(x1[b]) + x2[b]);                 \
        x2[a] = F(r1 * (t1) + r0 * (t0));            \
        x2[b] = F(r1 * (t0) - r0 * (t1));            \
    } while (0)

static void butterfly_first(const float *T, float *x, int points)
{
    float *x1 = x + points - 8;
    float *x2 = x + (points >> 1) - 8;
    for (;;) {
        BUTTERFLY_PAIR(6, 7, T[0], T[1]);
        BUTTERFLY_PAIR(4, 5, T[4], T[5]);
        BUTTERFLY_PAIR(2, 3, T[8], T[9]);
        BUTTERFLY_PAIR(0, 1, T[12], T[13]);
        T += 16;
        if (x2 == x) break;
        x1 -= 8;
        x2 -= 8;
    }
}

static void butterfly_generic(const float *T, float *x, int points, int trigint)
{
    float *x1 = x + points - 8;
    float *x2 = x + (points >> 1) - 8;
    for (;;) {
        BUTTERFLY_PAIR(6, 7, T[0], T[1]);
        T += trigint;
        BUTTERFLY_PAIR(4, 5, T[0], T[1]);
        T += trigint;
        BUTTERFLY_PAIR(2, 3, T[0], T[1]);
        T += trigint;
        BUTTERFLY_PAIR(0, 1, T[0], T[1]);
        T += trigint;
        if (x2 == x) break;
        x1 -= 8;
        x2 -= 8;
    }
}

static void butterflies(const float *trig, int log2n, float *x, int points)
{
    int stages = log2n - 5;
    if (--stages > 0) butterfly_first(trig, x, points);
    for (int i = 1; --stages > 0; i++)
        for (int j = 0; j < (1 << i); j++)
            butterfly_generic(trig, x + (points >> i) * j, points >> i, 4 << i);
    for (int j = 0; j < points; j += 32) butterfly_32(x + j);
}

static void bitreverse(int n, const int32_t *bit, const float *trig, float *x)
{
    float *w0 = x;
    float *w1 = x = w0 + (n >> 1);
    const float *T = trig + n;
    do {
        const float *x0 = x + bit[0];
        const float *x1 = x + bit[1];
        double r0 = D(x0[1]) - x1[1];
        double r1 = D(x0[0]) + x1[0];
        double r2 = r1 * T[0] + r0 * T[1];
        double r3 = r1 * T[1] - r0 * T[0];

        w1 -= 4;

        r0 = (D(x0[1]) + x1[1]) * D(.5f);
        r1 = (D(x0[0]) - x1[0]) * D(.5f);
        w0[0] = F(r0 + r2);
        w1[2] = F(r0 - r2);
        w0[1] = F(r1 + r3);
        w1[3] = F(r3 - r1);

        x0 = x + bit[2];
        x1 = x + bit[3];
        r0 = D(x0[1]) - x1[1];
        r1 = D(x0[0]) + x1[0];
        r2 = r1 * T[2] + r0 * T[3];
        r3 = r1 * T[3] - r0 * T[2];

        r0 = (D(x0[1]) + x1[1]) * D(.5f);
        r1 = (D(x0[0]) - x1[0]) * D(.5f);
        w0[2] = F(r0 + r2);
        w1[0] = F(r0 - r2);
        w0[3] = F(r1 + r3);
        w1[1] = F(r3 - r1);

        T += 4;
        bit += 4;
        w0 += 4;
    } while (w0 < w1);
}

/* mdct_backward(init, in, out): in and out may be the same buffer (the
 * decoder transforms each channel's PCM vector in place). Reads in[0, n/2),
 * writes out[0, n). */
static void mdct_backward(int n, int log2n, const float *trig, const int32_t *bitrev,
                          const float *in, float *out)
{
    int n2 = n >> 1, n4 = n >> 2;

    /* rotate */
    {
        float *oX = out + n2 + n4;
        const float *T = trig + n4;
        for (int i = n2 - 7; i >= 0; i -= 8) {
            const float *iX = in + i;
            oX -= 4;
            oX[0] = F(-(D(iX[2]) * T[3]) - D(iX[0]) * T[2]);
            oX[1] = F(D(iX[0]) * T[3] - D(iX[2]) * T[2]);
            oX[2] = F(-(D(iX[6]) * T[1]) - D(iX[4]) * T[0]);
            oX[3] = F(D(iX[4]) * T[1] - D(iX[6]) * T[0]);
            T += 4;
        }
    }
    {
        float *oX = out + n2 + n4;
        const float *T = trig + n4;
        for (int i = n2 - 8; i >= 0; i -= 8) {
            const float *iX = in + i;
            T -= 4;
            oX[0] = F(D(iX[4]) * T[3] + D(iX[6]) * T[2]);
            oX[1] = F(D(iX[4]) * T[2] - D(iX[6]) * T[3]);
            oX[2] = F(D(iX[0]) * T[1] + D(iX[2]) * T[0]);
            oX[3] = F(D(iX[0]) * T[0] - D(iX[2]) * T[1]);
            oX += 4;
        }
    }

    butterflies(trig, log2n, out + n2, n2);
    bitreverse(n, bitrev, trig, out);

    /* rotate + window */
    {
        float *oX1 = out + n2 + n4;
        float *oX2 = out + n2 + n4;
        const float *iX = out;
        const float *T = trig + n2;
        do {
            oX1 -= 4;
            oX1[3] = F(D(iX[0]) * T[1] - D(iX[1]) * T[0]);
            oX2[0] = F(-(D(iX[0]) * T[0] + D(iX[1]) * T[1]));
            oX1[2] = F(D(iX[2]) * T[3] - D(iX[3]) * T[2]);
            oX2[1] = F(-(D(iX[2]) * T[2] + D(iX[3]) * T[3]));
            oX1[1] = F(D(iX[4]) * T[5] - D(iX[5]) * T[4]);
            oX2[2] = F(-(D(iX[4]) * T[4] + D(iX[5]) * T[5]));
            oX1[0] = F(D(iX[6]) * T[7] - D(iX[7]) * T[6]);
            oX2[3] = F(-(D(iX[6]) * T[6] + D(iX[7]) * T[7]));
            oX2 += 4;
            iX += 8;
            T += 8;
        } while (iX < oX1);

        iX = out + n2 + n4;
        oX1 = out + n4;
        oX2 = oX1;
        do {
            oX1 -= 4;
            iX -= 4;
            oX2[0] = -(oX1[3] = iX[3]);
            oX2[1] = -(oX1[2] = iX[2]);
            oX2[2] = -(oX1[1] = iX[1]);
            oX2[3] = -(oX1[0] = iX[0]);
            oX2 += 4;
        } while (oX2 < iX);

        iX = out + n2 + n4;
        oX1 = out + n2 + n4;
        oX2 = out + n2;
        do {
            oX1 -= 4;
            oX1[0] = iX[3];
            oX1[1] = iX[2];
            oX1[2] = iX[1];
            oX1[3] = iX[0];
            iX += 4;
        } while (oX1 > oX2);
    }
}

/* Guest mdct_lookup: int n, log2n; float *trig; int *bitrev; float scale. */
#define MDCT_MAX 8192

enum { MDCT_NATIVE, MDCT_LIFTED, MDCT_CHECK };
static int mdct_mode = -1;
static uint32_t check_calls;
static double check_worst, check_worst_scale;

/* Sound.dll 0x14018AB0, LTCG convention: ecx = mdct_lookup *, eax = in,
 * [esp+4] = out; plain ret, caller pops. */
void SOUND_MDCT_BACKWARD(void)
{
    uint32_t init = g_ecx, in = g_eax, out = MEM32(g_esp + 4);
    int32_t n = (int32_t)MEM32(init), log2n = (int32_t)MEM32(init + 4);
    uint32_t trig = MEM32(init + 8), bitrev = MEM32(init + 12);
    if (mdct_mode < 0) {
        const char *env = getenv("VOID_MDCT");
        mdct_mode = !env ? MDCT_NATIVE : !strcmp(env, "lifted") ? MDCT_LIFTED :
                    !strcmp(env, "check") ? MDCT_CHECK : MDCT_NATIVE;
        void_log("[sound] mdct_backward: %s", mdct_mode == MDCT_LIFTED ? "lifted" :
                 mdct_mode == MDCT_CHECK ? "native, checked against the lifted body" : "native");
    }
    if (mdct_mode == MDCT_LIFTED ||
        n < 64 || n > MDCT_MAX || (n & (n - 1)) || (1 << log2n) != n || !trig || !bitrev) {
        /* Not a block size the native code knows: run the guest's own. */
        SOUND_MDCT_BACKWARD_LIFTED();
        return;
    }
    const float *T = (const float *)GPTR(trig);
    const int32_t *bit = (const int32_t *)GPTR(bitrev);
    if (mdct_mode == MDCT_NATIVE) {
        mdct_backward(n, log2n, T, bit, (const float *)GPTR(in), (float *)GPTR(out));
        g_esp += 4;   /* ret */
        return;
    }
    /* Per thread: the lifted body can hand the machine to another decoding
     * thread at a backward branch, and that one checks its own block here. */
    static __thread float input[MDCT_MAX / 2], result[MDCT_MAX];
    memcpy(input, GPTR(in), (size_t)(n / 2) * sizeof(float));
    mdct_backward(n, log2n, T, bit, input, result);
    SOUND_MDCT_BACKWARD_LIFTED();   /* in place on the guest buffer; pops the return address */
    const float *guest = (const float *)GPTR(out);
    double worst = 0, scale = 0;
    for (int i = 0; i < n; ++i) {
        double diff = fabs(D(result[i]) - guest[i]);
        if (diff > worst || diff != diff) worst = diff;
        if (fabs(D(guest[i])) > scale) scale = fabs(D(guest[i]));
    }
    if (worst > check_worst) { check_worst = worst; check_worst_scale = scale; }
    if (++check_calls % 500 == 1 || worst > 1e-4 * (scale > 1 ? scale : 1))
        void_log("[sound] mdct check: %u calls (n=%d), worst |native - lifted| %.3g at peak %.3g, this call %.3g / %.3g",
                 check_calls, n, check_worst, check_worst_scale, worst, scale);
}
