#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <stdlib.h>
#include <io.h>
#define access _access
#define F_OK 0
static const char *test_profile;
static const char *void_data_dir(void) { return test_profile; }

typedef struct { int alive, started, disconnected; } AAudioStream;
typedef int AAudioStreamBuilder;
typedef int32_t aaudio_result_t;
typedef unsigned useconds_t;
typedef int pthread_mutex_t;
typedef int pthread_t;
#define PTHREAD_MUTEX_INITIALIZER 0
#define AAUDIO_OK 0
#define AAUDIO_FORMAT_PCM_I16 1
#define AAUDIO_PERFORMANCE_MODE_LOW_LATENCY 12
#define AAUDIO_USAGE_GAME 14
#define AAUDIO_CONTENT_TYPE_MUSIC 2
static _Atomic int audio_paused;
static AAudioStream streams[256];
static int creates, closes, writes, sleeps, locked, builder_fail, open_fail, start_fail, write_error, partial;
static char last_log[256];
static void pthread_mutex_lock(pthread_mutex_t *lock) { (void)lock; assert(!locked); locked = 1; }
static void pthread_mutex_unlock(pthread_mutex_t *lock) { (void)lock; assert(locked); locked = 0; }
static void usleep(useconds_t us) { assert(!locked && us >= 10000); ++sleeps; }
static void void_log(const char *fmt, ...) {
    va_list ap; va_start(ap, fmt); vsnprintf(last_log, sizeof last_log, fmt, ap); va_end(ap);
}
static aaudio_result_t AAudio_createStreamBuilder(AAudioStreamBuilder **out) {
    static AAudioStreamBuilder builder;
    assert(locked); if (builder_fail) return -1; *out = &builder; return AAUDIO_OK;
}
#define SETTER(name, expected) static void AAudioStreamBuilder_##name(AAudioStreamBuilder *b, int value) { assert(locked && b && value == expected); }
SETTER(setFormat, AAUDIO_FORMAT_PCM_I16)
SETTER(setChannelCount, 2)
SETTER(setSampleRate, 48000)
SETTER(setPerformanceMode, AAUDIO_PERFORMANCE_MODE_LOW_LATENCY)
SETTER(setUsage, AAUDIO_USAGE_GAME)
SETTER(setContentType, AAUDIO_CONTENT_TYPE_MUSIC)
static void AAudioStreamBuilder_delete(AAudioStreamBuilder *b) { assert(locked && b); }
static aaudio_result_t AAudioStreamBuilder_openStream(AAudioStreamBuilder *b, AAudioStream **out) {
    assert(locked && b); if (open_fail) return -2;
    assert(creates < 256); *out = &streams[creates++]; (*out)->alive = 1; return AAUDIO_OK;
}
static aaudio_result_t AAudioStream_requestStart(AAudioStream *s) {
    assert(locked && s->alive);
    if (start_fail || s->disconnected) return -899;
    s->started = 1; return AAUDIO_OK;
}
static aaudio_result_t AAudioStream_requestPause(AAudioStream *s) {
    assert(locked && s->alive); s->started = 0; return AAUDIO_OK;
}
static aaudio_result_t AAudioStream_requestStop(AAudioStream *s) {
    assert(locked && s->alive); s->started = 0; return s->disconnected ? -899 : AAUDIO_OK;
}
static aaudio_result_t AAudioStream_close(AAudioStream *s) {
    assert(locked && s->alive); s->alive = 0; ++closes; return AAUDIO_OK;
}
static int32_t AAudioStream_write(AAudioStream *s, const void *frames, int32_t count, int64_t timeout) {
    assert(locked && s->alive && frames && count > 0 && timeout == 20000000LL);
    ++writes;
    if (s->disconnected || write_error) return -899;
    assert(s->started); return partial ? partial : count;
}
static int32_t AAudioStream_getXRunCount(AAudioStream *s) { assert(locked && s->alive); return 0; }

typedef struct { uint32_t guest; } void_com_object;
typedef struct { int unused; } facet_t;
typedef struct dsbuf dsbuf_t;
#define MIX_RATE 48000
#define DSBCAPS_CTRL3D 0x10
#define DS_OK 0
#define DSERR_INVALIDPARAM 0x80070057u
#define COM_METHOD(kind, name, count) static uint32_t kind##_##name(void)
static uint32_t arguments[3];
#define ARG(n) arguments[n]
#define DSTRACE(...) ((void)0)
static uint8_t guest_pcm[4096];
#define GPTR(addr) (guest_pcm + (addr))
#define MEM8(addr) guest_pcm[addr]
#define MEM16(addr) (*(uint16_t *)(guest_pcm + (addr)))
#define MEM32(addr) (*(uint32_t *)(guest_pcm + (addr)))
static int notifications;
static void signal_event(uint32_t event) { assert(event == 1); ++notifications; }

/* PRODUCTION */

int main(int argc, char **argv) {
    assert(argc == 2);
    test_profile = argv[1];
    assert(_putenv_s("VOID_DSOUND_TRACE", "") == 0 && !trace_enabled());
    char marker[1024];
    snprintf(marker, sizeof marker, "%s/dsound-trace", test_profile);
    FILE *file = fopen(marker, "wb"); assert(file && fclose(file) == 0);
    assert(trace_enabled());
    assert(remove(marker) == 0 && !trace_enabled());
    assert(_putenv_s("VOID_DSOUND_TRACE", "1") == 0 && trace_enabled());
    assert(_putenv_s("VOID_DSOUND_TRACE", "0") == 0 && !trace_enabled());
    int16_t pcm[960];
    for (unsigned i = 0; i < 960; ++i) pcm[i] = 123;
    audio_paused = 1;
    void_audio_output(pcm, 480);
    assert(creates == 0 && writes == 0 && sleeps == 1 && !stream);
    audio_paused = 0;
    void_audio_output(pcm, 480);
    assert(creates == 1 && writes == 1 && stream && stream->started);
    for (unsigned i = 0; i < 30; ++i) {
        AAudioStream *previous = stream;
        int old_writes = writes, old_creates = creates;
        audio_paused = 1;
        void_audio_output(pcm, 480);
        assert(!stream && !previous->alive && writes == old_writes);
        void_audio_output(pcm, 480);
        assert(creates == old_creates);
        audio_paused = 0;
        void_audio_output(pcm, 480);
        assert(stream && stream != previous && stream->started && writes == old_writes + 1);
    }
    stream->disconnected = 1;
    void_audio_output(pcm, 480);
    assert(!stream && creates == closes);
    void_audio_output(pcm, 480);
    assert(stream && stream->started);
    write_error = 1;
    void_audio_output(pcm, 480);
    assert(!stream && creates == closes);
    write_error = 0;
    start_fail = 1;
    int old_writes = writes;
    void_audio_output(pcm, 480);
    assert(!stream && creates == closes && writes == old_writes);
    start_fail = 0;
    for (int i = 0; i < 2; ++i) {
        builder_fail = i == 0; open_fail = i == 1;
        int old_sleeps = sleeps;
        void_audio_output(pcm, 480);
        assert(!stream && creates == closes && sleeps > old_sleeps);
    }
    builder_fail = open_fail = 0;
    void_audio_output(pcm, 480);
    assert(stream && stream->started);
    /* Partial writes must not claim that the unwritten loud tail played. */
    partial = 240;
    for (int i = 480; i < 960; ++i) pcm[i] = 30000;
    for (int i = 0; i < 4000; ++i) void_audio_output(pcm, 480);
    assert(strstr(last_log, "peak 123, rms 123,"));
    audio_paused = 1;
    void_audio_output(pcm, 480);
    assert(!stream && creates == closes && !locked);
    dsbuf_t one_shot = {0};
    one_shot.playing = 1; one_shot.size = 1920; one_shot.block = 4;
    one_shot.bits = 16; one_shot.channels = 2; one_shot.frequency = MIX_RATE;
    one_shot.notify_count = 1; one_shot.notify_offset[0] = 0xFFFFFFFFu; one_shot.notify_event[0] = 1;
    buffers = &one_shot;
    float mixed[960];
    for (int i = 0; i < 1000; ++i) mix_chunk(mixed, 480);
    assert(one_shot.playing && one_shot.play_pos == 0 && one_shot.frac == 0 && !notifications);
    for (unsigned i = 0; i < 960; ++i) assert(mixed[i] == 0);
    audio_paused = 0;
    mix_chunk(mixed, 240);
    assert(one_shot.playing && one_shot.play_pos == 960 && !notifications);
    audio_paused = 1;
    mix_chunk(mixed, 480);
    assert(one_shot.playing && one_shot.play_pos == 960 && !notifications);
    audio_paused = 0;
    mix_chunk(mixed, 240);
    assert(!one_shot.playing && notifications == 1);
    arguments[1] = 2048;
    memset(GPTR(2048), 0xAA, 64);
    MEM32(2048) = 64;
    assert(lst_GetAllParameters() == DS_OK);
    float *listener = (float *)GPTR(2048);
    assert(listener[9] == 1.0f && listener[11] == 1.0f);
    assert(listener[13] == 1.0f && listener[14] == 1.0f && listener[15] == 1.0f);
    assert(listener[1] == 0 && listener[4] == 0 && listener[7] == 0);
    assert(lst_SetAllParameters() == DS_OK);
    assert(listener_front[2] == 1 && listener_top[1] == 1 && distance_factor == 1 && rolloff == 1);
    dsbuf_t distant = {0};
    distant.playing = distant.looping = 1; distant.size = 4; distant.block = 4;
    distant.bits = 16; distant.channels = 2; distant.frequency = MIX_RATE;
    distant.flags = DSBCAPS_CTRL3D; distant.pos[2] = 10;
    distant.min_distance = 1; distant.max_distance = 100;
    MEM16(0) = MEM16(2) = 16384;
    buffers = &distant;
    mix_chunk(mixed, 1);
    assert(fabsf(mixed[0] - 0.05f) < 1e-6f && mixed[0] == mixed[1]);
    listener[1] = 0; listener[2] = 0; listener[3] = 9;
    assert(lst_SetAllParameters() == DS_OK);
    mix_chunk(mixed, 1);
    assert(mixed[0] == 0.5f && mixed[1] == 0.5f);
    listener[7] = 1; listener[9] = 0; listener[13] = 0.5f; listener[14] = 0.75f;
    assert(lst_SetAllParameters() == DS_OK);
    memset(GPTR(2304), 0xAA, 64); MEM32(2304) = 64; arguments[1] = 2304;
    assert(lst_GetAllParameters() == DS_OK);
    assert(!memcmp(GPTR(2048), GPTR(2304), 64));
    MEM32(2304) = 60;
    assert(lst_GetAllParameters() == DSERR_INVALIDPARAM && lst_SetAllParameters() == DSERR_INVALIDPARAM);
    arguments[1] = 0;
    assert(lst_GetAllParameters() == DSERR_INVALIDPARAM && lst_SetAllParameters() == DSERR_INVALIDPARAM);
    puts("PASS: 30 pause/resume cycles, paused startup, disconnect/write/start/open failures, paced retry, partial-write levels; paused one-shot cursor/notifications; DS3DLISTENER layout, defaults, roundtrip, near/far PCM; profile-only trace marker and environment switch");
    return 0;
}
