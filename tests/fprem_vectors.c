/* Reference vectors for FPREM/FPREM1 on doubles from the real x87 (MSVC x86).
 * Output lines: nearest x_bits y_bits result_bits status(C0|C1|C2|C3 mask 0x4700). */
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <math.h>

static uint64_t state = 0x1234567890ABCDEFull;
static uint64_t next(void) { state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state; }

static double rnd(void)
{
    switch (next() % 6) {
    case 0: return (double)(int64_t)(next() % 2000001) - 1000000.0;
    case 1: return ((double)(next() % 1000000000) / 1e3) * ((next() & 1) ? 1 : -1);
    case 2: return ldexp((double)(next() >> 11) / 9007199254740992.0 + 0.5, (int)(next() % 140) - 70) * ((next() & 1) ? 1 : -1);
    case 3: return 3.14159265358979323846 * (double)(next() % 9 + 1) / 4.0;
    case 4: return ldexp(1.0, (int)(next() % 200) - 60);
    default: { uint64_t b = next(); double d; memcpy(&d, &b, 8); return isfinite(d) ? d : 1.5; }
    }
}

int main(void)
{
    for (int i = 0; i < 20000; ++i) {
        double x = rnd(), y = rnd();
        if (y == 0.0) y = 1.0;
        for (int nearest = 0; nearest < 2; ++nearest) {
            double result;
            unsigned short status;
            if (nearest) {
                __asm {
                    fld y
                    fld x
                    fprem1
                    fnstsw status
                    fstp result
                    fstp st(0)
                }
            } else {
                __asm {
                    fld y
                    fld x
                    fprem
                    fnstsw status
                    fstp result
                    fstp st(0)
                }
            }
            uint64_t xb, yb, rb;
            memcpy(&xb, &x, 8); memcpy(&yb, &y, 8); memcpy(&rb, &result, 8);
            printf("%d %016llX %016llX %016llX %04X\n", nearest, (unsigned long long)xb, (unsigned long long)yb,
                (unsigned long long)rb, status & 0x4700);
        }
    }
    return 0;
}
