"""Execute audio worker entries with an inherited guest-only affinity mask."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_android import CLANG, TARGET
from build_x86_incremental import compiler_environment


def main():
    out = ROOT / "build/audio-workers-test"
    out.mkdir(parents=True, exist_ok=True)
    entries = []
    for file, function in (("dsound.c", "mixer_main"), ("vorbis_native.c", "pool_main")):
        source = (ROOT / "android/host" / file).read_text(encoding="utf-8")
        entries.append(re.search(r"^static void \*" + function + r"\(.*?^\}", source, re.M | re.S).group())
    fixture = r'''
#include <assert.h>
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
typedef int pthread_mutex_t;
struct timespec { long tv_sec, tv_nsec; };
#define CLOCK_MONOTONIC 1
#define TIMER_ABSTIME 1
#define MIX_CHUNK 480
#define DSTRACE(...) ((void)0)
static int inherited_mask, resets, mixer_running, dstrace;
static int mix_lock, pool_lock, pool_wake, pool_idle, pool_working;
static uint64_t pool_generation;
typedef struct { int unused; } par_job;
static par_job *pool_job;
typedef struct dsbuf { int playing; struct dsbuf *next; } dsbuf_t;
static dsbuf_t *buffers;
static jmp_buf idle;
static void void_host_thread_init(void) { assert(inherited_mask == 128); inherited_mask = 255; ++resets; }
static void clock_gettime(int clock, struct timespec *t) { assert(clock == CLOCK_MONOTONIC && inherited_mask == 255); t->tv_sec = t->tv_nsec = 0; }
static void clock_nanosleep(int clock, int flags, const struct timespec *t, void *left) {
    assert(inherited_mask == 255 && clock == CLOCK_MONOTONIC && flags == TIMER_ABSTIME && t->tv_nsec == 10000000 && !left);
}
static void pthread_mutex_lock(int *lock) { assert(inherited_mask == 255 && lock); }
static void pthread_mutex_unlock(int *lock) { assert(inherited_mask == 255 && lock); }
static void pthread_cond_wait(int *condition, int *lock) { assert(condition == &pool_wake && lock == &pool_lock); longjmp(idle, 1); }
static void pthread_cond_broadcast(int *condition) { (void)condition; }
static void par_work(par_job *job) { (void)job; assert(0); }
static void mix_chunk(float *pcm, uint32_t frames) {
    assert(inherited_mask == 255 && frames == MIX_CHUNK);
    for (unsigned i = 0; i < 2 * frames; ++i) pcm[i] = 0.25f;
}
static void void_audio_output(const int16_t *pcm, uint32_t frames) {
    assert(inherited_mask == 255 && frames == MIX_CHUNK && pcm[0] == 8191);
    mixer_running = 0;
}
/* PRODUCTION */
int main(void) {
    inherited_mask = 128; mixer_running = 1;
    mixer_main(NULL);
    assert(resets == 1 && inherited_mask == 255);
    inherited_mask = 128;
    if (!setjmp(idle)) pool_main(NULL);
    assert(resets == 2 && inherited_mask == 255);
    puts("PASS: mixer and Vorbis worker restore host affinity before mixing, decoding or waiting");
    return 0;
}
'''
    generated = out / "probe.c"
    generated.write_text(fixture.replace("/* PRODUCTION */", "\n".join(entries)), encoding="utf-8")
    _, env, _ = compiler_environment()
    env["LIB"] = env["LIB"].replace("\\x86", "\\x64")
    exe = out / "probe.exe"
    built = subprocess.run([str(CLANG), "--target=x86_64-pc-windows-msvc", "-fuse-ld=link", "-O2",
                            "-std=c11", str(generated), "-o", str(exe)], env=env, capture_output=True, text=True)
    (out / "build.log").write_text(built.stdout + built.stderr)
    assert built.returncode == 0, built.stdout + built.stderr
    tested = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
    (out / "run.log").write_text(tested.stdout + tested.stderr)
    assert tested.returncode == 0, tested.stdout + tested.stderr
    print(tested.stdout, end="")
    threads = (ROOT / "android/host/threads.c").read_text(encoding="utf-8")
    affinity = threads[threads.index("static cpu_set_t big_cores;"):threads.index("static void *thread_main")]
    native_fixture = (ROOT / "tests/host_thread_affinity_probe.c").read_text(encoding="utf-8")
    native_source = out / "affinity.c"
    native_source.write_text(native_fixture.replace("/* PRODUCTION */", affinity), encoding="utf-8")
    native_exe = out / "affinity-probe"
    native = subprocess.run([str(CLANG), "--target=" + TARGET, "-O2", "-std=gnu11", "-Wall",
                             str(native_source), "-o", str(native_exe)], capture_output=True, text=True)
    (out / "affinity-build.log").write_text(native.stdout + native.stderr)
    assert native.returncode == 0, native.stdout + native.stderr
    print(f"Built real pthread/affinity device probe: {native_exe}")


if __name__ == "__main__":
    main()
