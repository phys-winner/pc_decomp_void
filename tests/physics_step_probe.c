/* physx.c's physics_wanted_step on synthetic shown rates: the display's step from about
 * 72 frames a second, the original 1/60 below about 58, each after a second there. */
#include <assert.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static double rate;
static uint64_t clock_ns;
static int writes, logs;
static float written;
static double void_present_rate(void) { return rate; }
static uint64_t void_monotonic_ns(void) { return clock_ns; }
static void void_log(const char *fmt, ...) { va_list a; va_start(a, fmt); vprintf(fmt, a); va_end(a); putchar('\n'); ++logs; }
static float fine_step = 1.0f / 120.0f, coarse_step = 1.0f / 60.0f;
static int fine_steps = 1;
static uint32_t step_generation = 1;
static void engine_step_write(float step) { written = step; ++writes; }

#include "physics-step.h"

/* Frames at `fps` for `seconds`, the step asked at each. */
static float run(double fps, double seconds)
{
    float step = 0;
    rate = fps;
    for (double t = 0; t < seconds; t += 1.0 / (fps > 0 ? fps : 30)) {
        clock_ns += (uint64_t)(1e9 / (fps > 0 ? fps : 30));
        step = physics_wanted_step();
    }
    return step;
}

int main(void)
{
    assert(run(120, 3) == fine_step && writes == 0);            /* a fast game keeps the display's step */
    assert(run(40, 0.9) == fine_step);                           /* under a second: no change yet */
    assert(run(40, 0.2) == coarse_step && writes == 1 && written == coarse_step && step_generation == 2);
    assert(run(65, 5) == coarse_step);                           /* between the thresholds: stays */
    assert(run(80, 0.5) == coarse_step);                         /* a short burst: stays */
    assert(run(50, 0.5) == coarse_step);
    assert(run(80, 1.2) == fine_step && written == fine_step && step_generation == 3);
    assert(run(60, 5) == fine_step);                             /* 58..72 keeps the fine step too */
    assert(run(0, 3) == fine_step);                              /* no rate yet (loading): no change */
    uint32_t g = step_generation;
    for (int i = 0; i < 20; ++i) { run(57, 0.5); run(73, 0.5); }  /* flapping half-seconds never switch */
    assert(step_generation == g);
    assert(logs == writes && writes == 2);
    printf("PASS: physics step follows the shown rate with a 58/72 fps hysteresis of one second\n");
    return 0;
}
