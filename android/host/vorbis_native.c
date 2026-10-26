/* Native Ogg Vorbis for Sound.dll.
 *
 * Sound.dll decodes its sounds with libvorbisfile (Xiph.Org, BSD licence)
 * built into it; lifted, the decoding took a third of a save's loading, and
 * a sound object decodes its whole file when it is made (CSound3DNormal's
 * constructor at 0x10061FE0: open, read every sample into the DirectSound
 * buffer, clear), so a long sound started with a frame of seconds (the
 * colour sucked from a vein). The library's entry points the game calls are
 * replaced here by stb_vorbis (Sean Barrett, public domain,
 * reference/stb) over the whole file, read once through the game's own
 * read callback:
 *
 *   open1      0x1000F440  EAX vf, ECX datasource, callbacks by value
 *   open2      0x1000F540  EAX vf
 *   read       0x10010500  ESI vf; (buffer, bytes, bitstream*), 16-bit LE signed
 *   clear      0x1000F590  EDI vf
 *   pcm_total  0x1000F6D0  cdecl (vf, link) -> EDX:EAX
 *   pcm_seek   0x100101D0  cdecl (vf, int64 pos)
 *
 * (research/sound-bulk-read.md has the ABI). The game's own code reads a few
 * fields of the OggVorbis_File (ov_info, ov_pcm_tell inlined at 0x100612A0
 * and 0x10061320): those are kept as libvorbisfile keeps them. Sounds up to
 * PREDECODE_SAMPLES are decoded whole when opened and kept in a PCM cache by
 * the file's content, so a sound made again (every play of some) is a copy;
 * longer streams (music) decode as they are read. A stream ends exactly at
 * the length the file's last granule gives, as libvorbisfile's does (the
 * game reads exactly pcm_total samples into a buffer of that size).
 *
 * VOID_VORBIS=lifted runs the lifted library (A/B timing). */
#include "host.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define STB_VORBIS_NO_STDIO
#define STB_VORBIS_NO_PUSHDATA_API
#include "../../reference/stb/stb_vorbis.c"

#ifdef VOID_RELEASE
#include "release_overrides.h"
#else
#define SOUND_VORBIS_OPEN1 sub_1400F440          /* the 2009 Sound.dll */
#define SOUND_VORBIS_OPEN1_LIFTED sub_1400F440_lifted
#define SOUND_VORBIS_OPEN2 sub_1400F540
#define SOUND_VORBIS_OPEN2_LIFTED sub_1400F540_lifted
#define SOUND_VORBIS_READ sub_14010500
#define SOUND_VORBIS_READ_LIFTED sub_14010500_lifted
#define SOUND_VORBIS_CLEAR sub_1400F590
#define SOUND_VORBIS_CLEAR_LIFTED sub_1400F590_lifted
#define SOUND_VORBIS_PCM_TOTAL sub_1400F6D0
#define SOUND_VORBIS_PCM_TOTAL_LIFTED sub_1400F6D0_lifted
#define SOUND_VORBIS_PCM_SEEK sub_140101D0
#define SOUND_VORBIS_PCM_SEEK_LIFTED sub_140101D0_lifted
#endif

#ifdef SOUND_VORBIS_OPEN1
void SOUND_VORBIS_OPEN1_LIFTED(void);
void SOUND_VORBIS_OPEN2_LIFTED(void);
void SOUND_VORBIS_READ_LIFTED(void);
void SOUND_VORBIS_CLEAR_LIFTED(void);
void SOUND_VORBIS_PCM_TOTAL_LIFTED(void);
void SOUND_VORBIS_PCM_SEEK_LIFTED(void);

/* OggVorbis_File (32-bit libvorbisfile) fields the game or this file uses. */
#define VF_DATASOURCE 0x00u
#define VF_SEEKABLE 0x04u
#define VF_LINKS 0x34u
#define VF_VI 0x48u
#define VF_PCM_OFFSET 0x50u
#define VF_READY_STATE 0x58u
#define VF_CURRENT_LINK 0x60u
#define VF_CALLBACKS 0x2C0u      /* read, seek, close, tell */
#define VF_SIZE 0x2D0u
enum { PARTOPEN = 1, OPENED = 2, INITSET = 4 };

#define CHUNK 0x10000u
#define PREDECODE_SAMPLES (30u * 44100u)        /* per channel */
#define CACHE_BUDGET (64u << 20)               /* bytes of PCM kept */

typedef struct entry {
    struct entry *next;
    uint64_t hash;
    uint32_t size;          /* of the file */
    int channels, rate;
    uint32_t total;         /* samples per channel */
    int16_t *pcm;           /* interleaved */
    int refs;
    uint64_t used;
} entry_t;

typedef struct stream {
    struct stream *next;
    uint32_t vf, vi;        /* guest OggVorbis_File and vorbis_info */
    int channels, rate;
    uint32_t total, pos;
    entry_t *pcm;           /* decoded whole */
    stb_vorbis *v;          /* or decoded as read */
    uint8_t *data;
    size_t size;
} stream_t;

static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static stream_t *streams;
static entry_t *cache;
static uint64_t cache_bytes, clock_tick;
static int mode = -1;    /* 1 native, 0 lifted */
static struct { uint32_t opens, hits, decoded, fallbacks; double decode_ms; } stats;

static int native(void)
{
    if (mode < 0) {
        const char *env = getenv("VOID_VORBIS");
        mode = !(env && !strcmp(env, "lifted"));
        void_log("[sound] Vorbis: %s", mode ? "native (stb_vorbis), PCM cache" : "lifted libvorbisfile");
    }
    return mode;
}

static stream_t *find(uint32_t vf)
{
    pthread_mutex_lock(&lock);
    stream_t *s = streams;
    while (s && s->vf != vf) s = s->next;
    pthread_mutex_unlock(&lock);
    return s;
}

static uint64_t fnv64(const uint8_t *p, size_t n)
{
    uint64_t h = 0xCBF29CE484222325ull;
    for (size_t i = 0; i < n; ++i) h = (h ^ p[i]) * 0x100000001B3ull;
    return h;
}

static double now_ms(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1e3 + t.tv_nsec / 1e6;
}

/* Under the lock: drop unused entries, least recently used first, until
 * the cache fits its budget. */
static void trim_cache(void)
{
    while (cache_bytes > CACHE_BUDGET) {
        entry_t **victim = NULL;
        for (entry_t **e = &cache; *e; e = &(*e)->next)
            if (!(*e)->refs && (!victim || (*e)->used < (*victim)->used)) victim = e;
        if (!victim) return;
        entry_t *gone = *victim;
        *victim = gone->next;
        cache_bytes -= (uint64_t)gone->total * gone->channels * 2;
        free(gone->pcm);
        free(gone);
    }
}

/* The whole file through the game's read callback (cdecl ptr, size, nmemb,
 * datasource -> items); NULL if it cannot be read. */
static uint8_t *read_all(uint32_t datasource, uint32_t read_func, size_t *size)
{
    uint32_t bounce = void_galloc(CHUNK);
    if (!bounce) return NULL;
    uint8_t *data = NULL;
    size_t n = 0, cap = 0;
    for (;;) {
        uint32_t args[4] = {bounce, 1, CHUNK, datasource};
        uint32_t got = void_call_guest(read_func, 4, args, 0);
        if (!got || got > CHUNK) break;
        if (n + got > cap) {
            cap = (n + got) * 2;
            uint8_t *grown = realloc(data, cap);
            if (!grown) { free(data); data = NULL; n = 0; break; }
            data = grown;
        }
        memcpy(data + n, GPTR(bounce), got);
        n += got;
    }
    void_gfree(bounce);
    *size = n;
    return data;
}

/* The next `frames` samples of decoder v into out (interleaved), silence
 * past its end. */
static void fill(stb_vorbis *v, int channels, int16_t *out, uint32_t frames)
{
    uint32_t done = 0;
    while (done < frames) {
        int got = stb_vorbis_get_samples_short_interleaved(v, channels, out + (size_t)done * channels,
                                                            (int)((frames - done) * channels));
        if (got <= 0) break;
        done += (uint32_t)got;
    }
    if (done < frames) memset(out + (size_t)done * channels, 0, (size_t)(frames - done) * channels * 2);
}

/* Samples [pos, pos + frames) of the stream into out (interleaved). */
static void produce(stream_t *s, int16_t *out, uint32_t frames)
{
    if (s->pcm) {
        memcpy(out, s->pcm->pcm + (size_t)s->pos * s->channels, (size_t)frames * s->channels * 2);
        return;
    }
    fill(s->v, s->channels, out, frames);
}

/* Decoding on every core. A range is cut into chunks; each worker opens
 * its own decoder on the file and seeks to its chunk (stb_vorbis_seek
 * decodes the frame before it), which gives the same samples, bit for bit,
 * as one decoder from the start (checked on the game's files: a 16 s loop
 * in 33 ms instead of 93 on the device). The caller takes chunks too and
 * returns when all are done; the guest waits anyway, the sound object reads
 * the whole file when it is made. */
#define PAR_CHUNK 32768u
#define PAR_MIN (3u * PAR_CHUNK)
#define PAR_THREADS 7

typedef struct {
    const uint8_t *data;
    int size, channels;
    uint32_t start, frames, chunks;
    int16_t *out;
    atomic_uint next;
    atomic_int failed;
} par_job;

static pthread_mutex_t pool_busy = PTHREAD_MUTEX_INITIALIZER;     /* one job at a time */
static pthread_mutex_t pool_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t pool_wake = PTHREAD_COND_INITIALIZER, pool_idle = PTHREAD_COND_INITIALIZER;
static par_job *pool_job;
static uint64_t pool_generation;
static int pool_threads, pool_working;

static void par_work(par_job *j)
{
    stb_vorbis *v = NULL;
    for (;;) {
        uint32_t c = atomic_fetch_add(&j->next, 1);
        if (c >= j->chunks) break;
        if (!v) {
            int error = 0;
            v = stb_vorbis_open_memory(j->data, j->size, &error, NULL);
            if (!v) { atomic_store(&j->failed, 1); break; }
        }
        uint32_t at = j->start + c * PAR_CHUNK, n = j->frames - c * PAR_CHUNK;
        if (n > PAR_CHUNK) n = PAR_CHUNK;
        if (at ? !stb_vorbis_seek(v, at) : !stb_vorbis_seek_start(v)) { atomic_store(&j->failed, 1); continue; }
        fill(v, j->channels, j->out + (size_t)c * PAR_CHUNK * j->channels, n);
    }
    if (v) stb_vorbis_close(v);
}

static void *pool_main(void *arg)
{
    (void)arg;
    void_host_thread_init();
    uint64_t seen = 0;
    pthread_mutex_lock(&pool_lock);
    for (;;) {
        while (pool_generation == seen) pthread_cond_wait(&pool_wake, &pool_lock);
        seen = pool_generation;
        par_job *j = pool_job;
        if (!j) continue;
        ++pool_working;
        pthread_mutex_unlock(&pool_lock);
        par_work(j);
        pthread_mutex_lock(&pool_lock);
        if (--pool_working == 0) pthread_cond_broadcast(&pool_idle);
    }
    return NULL;
}

/* Samples [start, start + frames) of the file into out on every core; 0 if
 * not done so (short, the pool busy, a decoder failing): decode in line. */
static int decode_parallel(const uint8_t *data, size_t size, int channels, uint32_t start, uint32_t frames,
                           int16_t *out)
{
    if (frames < PAR_MIN || size > 0x7FFFFFFF || pthread_mutex_trylock(&pool_busy)) return 0;
    if (!pool_threads) {
        long cpus = sysconf(_SC_NPROCESSORS_ONLN);
        int want = cpus > 1 ? (int)(cpus - 1 < PAR_THREADS ? cpus - 1 : PAR_THREADS) : 0;
        for (int i = 0; i < want; ++i) {
            pthread_t t;
            if (!pthread_create(&t, NULL, pool_main, NULL)) { pthread_detach(t); ++pool_threads; }
        }
        void_log("[sound] Vorbis decodes long sounds on %d more threads", pool_threads);
        if (!pool_threads) pool_threads = -1;
    }
    if (pool_threads < 0) { pthread_mutex_unlock(&pool_busy); return 0; }
    par_job j = {data, (int)size, channels, start, frames, (frames + PAR_CHUNK - 1) / PAR_CHUNK, out};
    atomic_init(&j.next, 0);
    atomic_init(&j.failed, 0);
    pthread_mutex_lock(&pool_lock);
    pool_job = &j;
    ++pool_generation;
    pthread_cond_broadcast(&pool_wake);
    pthread_mutex_unlock(&pool_lock);
    par_work(&j);
    pthread_mutex_lock(&pool_lock);
    pool_job = NULL;
    while (pool_working) pthread_cond_wait(&pool_idle, &pool_lock);
    pthread_mutex_unlock(&pool_lock);
    pthread_mutex_unlock(&pool_busy);
    return !atomic_load(&j.failed);
}

/* A stream for the file: cached PCM, PCM decoded now, or a decoder. */
static stream_t *open_stream(uint8_t *data, size_t size)
{
    uint64_t hash = fnv64(data, size);
    stream_t *s = calloc(1, sizeof *s);
    if (!s) return NULL;
    pthread_mutex_lock(&lock);
    for (entry_t *e = cache; e; e = e->next) {
        if (e->hash == hash && e->size == size) {
            ++e->refs;
            e->used = ++clock_tick;
            s->pcm = e;
            break;
        }
    }
    pthread_mutex_unlock(&lock);
    if (s->pcm) {
        s->channels = s->pcm->channels;
        s->rate = s->pcm->rate;
        s->total = s->pcm->total;
        free(data);
        ++stats.hits;
        return s;
    }
    int error = 0;
    stb_vorbis *v = stb_vorbis_open_memory(data, (int)size, &error, NULL);
    if (!v) { free(s); return NULL; }
    stb_vorbis_info info = stb_vorbis_get_info(v);
    unsigned int total = stb_vorbis_stream_length_in_samples(v);
    if (info.channels < 1 || info.channels > 8 || !total) {
        stb_vorbis_close(v);
        free(s);
        return NULL;
    }
    s->channels = info.channels;
    s->rate = (int)info.sample_rate;
    s->total = total;
    if (total > PREDECODE_SAMPLES) {
        s->v = v;
        s->data = data;
        s->size = size;
        return s;
    }
    /* Decoded whole, as the game reads it right away. */
    double t0 = now_ms();
    entry_t *e = calloc(1, sizeof *e);
    int16_t *pcm = e ? malloc((size_t)total * info.channels * 2) : NULL;
    if (!pcm) {
        free(e);
        s->v = v;
        s->data = data;
        s->size = size;
        return s;
    }
    s->v = v;
    s->pos = 0;
    if (!decode_parallel(data, size, s->channels, 0, total, pcm)) produce(s, pcm, total);
    stb_vorbis_close(v);
    s->v = NULL;
    free(data);
    e->hash = hash;
    e->size = (uint32_t)size;
    e->channels = s->channels;
    e->rate = s->rate;
    e->total = total;
    e->pcm = pcm;
    e->refs = 1;
    double ms = now_ms() - t0;
    pthread_mutex_lock(&lock);
    e->used = ++clock_tick;
    e->next = cache;
    cache = e;
    cache_bytes += (uint64_t)total * s->channels * 2;
    trim_cache();
    stats.decoded++;
    stats.decode_ms += ms;
    pthread_mutex_unlock(&lock);
    s->pcm = e;
    if (ms > 20 || stats.decoded <= 3)
        void_log("[sound] decoded %u samples x %d (%u bytes of Ogg) in %.1f ms", total, s->channels, (unsigned)size, ms);
    return s;
}

static void free_stream(stream_t *s)
{
    if (s->pcm) {
        pthread_mutex_lock(&lock);
        --s->pcm->refs;
        trim_cache();
        pthread_mutex_unlock(&lock);
    }
    if (s->v) stb_vorbis_close(s->v);
    free(s->data);
    free(s);
}

static void set_offset(stream_t *s)
{
    MEM32(s->vf + VF_PCM_OFFSET) = s->pos;
    MEM32(s->vf + VF_PCM_OFFSET + 4) = 0;
}

void SOUND_VORBIS_OPEN1(void)
{
    uint32_t vf = g_eax, datasource = g_ecx, esp = g_esp;
    uint32_t callbacks[4] = {MEM32(esp + 4), MEM32(esp + 8), MEM32(esp + 12), MEM32(esp + 16)};
    if (!native() || !datasource || !callbacks[0]) {
        SOUND_VORBIS_OPEN1_LIFTED();
        return;
    }
    size_t size = 0;
    uint8_t *data = read_all(datasource, callbacks[0], &size);
    stream_t *s = data && size ? open_stream(data, size) : NULL;
    if (!s) {
        /* Not a file stb_vorbis takes: the library's own, from the start. */
        free(data);
        if (callbacks[1]) {
            uint32_t args[4] = {datasource, 0, 0, 0};   /* SEEK_SET 0 */
            void_call_guest(callbacks[1], 4, args, 0);
        }
        ++stats.fallbacks;
        void_log("[sound] Vorbis stream of %u bytes left to the lifted library", (unsigned)size);
        g_eax = vf;
        g_ecx = datasource;
        g_esp = esp;
        SOUND_VORBIS_OPEN1_LIFTED();
        return;
    }
    s->vf = vf;
    s->vi = void_galloc(32);
    memset(GPTR(vf), 0, VF_SIZE);
    MEM32(vf + VF_DATASOURCE) = datasource;
    MEM32(vf + VF_SEEKABLE) = 1;
    MEM32(vf + VF_LINKS) = 1;
    MEM32(vf + VF_VI) = s->vi;
    MEM32(vf + VF_READY_STATE) = PARTOPEN;
    MEM32(vf + VF_CURRENT_LINK) = 0;
    for (int i = 0; i < 4; ++i) MEM32(vf + VF_CALLBACKS + 4u * i) = callbacks[i];
    if (s->vi) {
        memset(GPTR(s->vi), 0, 32);
        MEM32(s->vi + 4) = (uint32_t)s->channels;
        MEM32(s->vi + 8) = (uint32_t)s->rate;
    }
    set_offset(s);
    pthread_mutex_lock(&lock);
    s->next = streams;
    streams = s;
    uint32_t opens = ++stats.opens;
    pthread_mutex_unlock(&lock);
    if ((opens & 255) == 0)
        void_log("[sound] Vorbis: %u streams, %u from the cache, %u decoded in %.0f ms, %u left to the library, "
                 "%llu KB of PCM cached", opens, stats.hits, stats.decoded, stats.decode_ms, stats.fallbacks,
                 (unsigned long long)(cache_bytes >> 10));
    g_eax = 0;
    g_esp = esp + 4;
}

void SOUND_VORBIS_OPEN2(void)
{
    uint32_t vf = g_eax;
    if (!find(vf)) { SOUND_VORBIS_OPEN2_LIFTED(); return; }
    if (MEM32(vf + VF_READY_STATE) != PARTOPEN) {
        g_eax = (uint32_t)-131;   /* OV_EINVAL */
    } else {
        MEM32(vf + VF_READY_STATE) = OPENED;
        g_eax = 0;
    }
    g_esp += 4;
}

void SOUND_VORBIS_READ(void)
{
    uint32_t vf = g_esi, esp = g_esp;
    stream_t *s = find(vf);
    if (!s) { SOUND_VORBIS_READ_LIFTED(); return; }
    uint32_t buffer = MEM32(esp + 4), bytes = MEM32(esp + 8), bitstream = MEM32(esp + 12);
    uint32_t frame = 2u * (uint32_t)s->channels;
    uint32_t frames = bytes / frame;
    if (frames > s->total - s->pos) frames = s->total - s->pos;
    if (frames && s->v && !s->pcm
        && decode_parallel(s->data, s->size, s->channels, s->pos, frames, (int16_t *)GPTR(buffer))) {
        /* A long sound read in one piece: the stream's decoder goes on after
         * it (decoded up to there should the seek fail). */
        if (s->pos + frames < s->total && !stb_vorbis_seek(s->v, s->pos + frames)) {
            stb_vorbis_seek_start(s->v);
            int16_t scratch[4096];
            uint32_t step = 4096u / (uint32_t)s->channels;
            for (uint32_t left = s->pos + frames; left;) {
                uint32_t n = left < step ? left : step;
                fill(s->v, s->channels, scratch, n);
                left -= n;
            }
        }
    } else if (frames) {
        produce(s, (int16_t *)GPTR(buffer), frames);
    }
    s->pos += frames;
    set_offset(s);
    MEM32(vf + VF_READY_STATE) = INITSET;
    if (bitstream) MEM32(bitstream) = 0;
    g_eax = frames * frame;
    g_esp = esp + 4;
}

void SOUND_VORBIS_CLEAR(void)
{
    uint32_t vf = g_edi;
    pthread_mutex_lock(&lock);
    stream_t **p = &streams;
    while (*p && (*p)->vf != vf) p = &(*p)->next;
    stream_t *s = *p;
    if (s) *p = s->next;
    pthread_mutex_unlock(&lock);
    if (!s) { SOUND_VORBIS_CLEAR_LIFTED(); return; }
    uint32_t esp = g_esp, datasource = MEM32(vf + VF_DATASOURCE), close = MEM32(vf + VF_CALLBACKS + 8);
    if (datasource && close) {
        uint32_t args[1] = {datasource};
        void_call_guest(close, 1, args, 0);
    }
    if (s->vi) void_gfree(s->vi);
    memset(GPTR(vf), 0, VF_SIZE);
    free_stream(s);
    g_eax = 0;
    g_esp = esp + 4;
}

void SOUND_VORBIS_PCM_TOTAL(void)
{
    stream_t *s = find(MEM32(g_esp + 4));
    if (!s) { SOUND_VORBIS_PCM_TOTAL_LIFTED(); return; }
    g_eax = s->total;
    g_edx = 0;
    g_esp += 4;
}

void SOUND_VORBIS_PCM_SEEK(void)
{
    uint32_t esp = g_esp;
    stream_t *s = find(MEM32(esp + 4));
    if (!s) { SOUND_VORBIS_PCM_SEEK_LIFTED(); return; }
    uint32_t lo = MEM32(esp + 8), hi = MEM32(esp + 12);
    uint32_t pos = hi || lo > s->total ? s->total : lo;
    if (s->v && !stb_vorbis_seek(s->v, pos)) {
        stb_vorbis_seek_start(s->v);
        pos = 0;
    }
    s->pos = pos;
    set_offset(s);
    g_eax = 0;
    g_esp = esp + 4;
}
#endif
