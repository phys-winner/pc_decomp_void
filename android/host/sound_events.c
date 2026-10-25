/* Sound events for the touch layer's vibration (sound_events.h): the hero
 * lands, takes damage, or sucks colour from a tree or a vein. Sound.dll
 * decodes each static sound whole into a DirectSound buffer of exactly its
 * PCM size, so a buffer is recognised by its size: the sizes of the wanted
 * Ogg Vorbis files (both rate variants) are worked out from the release's
 * data/Sounds.vfs (channels from the identification header, samples from
 * the last page's granule position). */
#include "host.h"
#include "sound_events.h"
#include "vfs_dir.h"
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

static const struct { const char *part; int event; } wanted[] = {
    {"fx_player_jump_end_", SOUND_EVENT_LAND},
    {"fx_player_damage", SOUND_EVENT_DAMAGE},
    {"vein_suck", SOUND_EVENT_ABSORB},
    {"garden_tree_suck", SOUND_EVENT_ABSORB},
    {"plant1_suck_limfa", SOUND_EVENT_ABSORB},
    /* newgame_tree_suck (the tutorial tree's short suck) is deliberately left
     * out: its decoded PCM size is identical to vein_empty (the sound played
     * when a not-yet-filled vein is harpooned — 217952 B at 22 kHz, 435904 at
     * 44), and buffers are recognised only by size. Counting that size as an
     * absorb made every empty-vein interaction buzz a harvest pulse through
     * the whole game; the one-off tutorial suck losing its pulse is the far
     * smaller cost (the real sucks — vein_suck/garden_tree_suck/
     * plant1_suck_limfa — keep unique sizes and still pulse). */
};
#define WANTED (int)(sizeof wanted / sizeof wanted[0])

static struct { uint32_t bytes; int event; } sizes[128];
static int size_count;
static pthread_once_t once = PTHREAD_ONCE_INIT;
static _Atomic uint32_t counts[SOUND_EVENTS];
static FILE *scan_file;

/* PCM bytes (16-bit) of an Ogg Vorbis file, 0 if it is not one. */
static uint32_t pcm_bytes(const uint8_t *d, uint32_t n)
{
    if (n < 64 || memcmp(d, "OggS", 4)) return 0;
    uint32_t segments = d[26], packet = 27 + segments;
    if (packet + 16 > n || d[packet] != 1 || memcmp(d + packet + 1, "vorbis", 6)) return 0;
    uint32_t channels = d[packet + 11];
    for (uint32_t at = n - 27; at > 0; --at) {
        if (memcmp(d + at, "OggS", 4)) continue;
        uint64_t granule = 0;
        memcpy(&granule, d + at + 6, 8);
        return granule && granule < (1ull << 30) ? (uint32_t)(granule * channels * 2u) : 0;
    }
    return 0;
}

static void found(const char *path, uint32_t offset, uint32_t size, void *ctx)
{
    (void)ctx;
    const char *name = strrchr(path, '\\');
    name = name ? name + 1 : path;
    for (int w = 0; w < WANTED; ++w) {
        if (strncasecmp(name, wanted[w].part, strlen(wanted[w].part))) continue;
        uint8_t *data = malloc(size);
        if (data && size_count < (int)(sizeof sizes / sizeof sizes[0]) &&
            !fseek(scan_file, (long)offset, SEEK_SET) && fread(data, 1, size, scan_file) == size) {
            uint32_t bytes = pcm_bytes(data, size);
            if (bytes) { sizes[size_count].bytes = bytes; sizes[size_count++].event = wanted[w].event; }
        }
        free(data);
        return;
    }
}

static void load_sizes(void)
{
    scan_file = void_vfs_open("Sounds.vfs");
    if (!scan_file) { void_log("[sound] no data/Sounds.vfs: no sound events"); return; }
    if (!void_vfs_scan(scan_file, "sounds", found, NULL)) void_log("[sound] Sounds.vfs: unreadable directory");
    fclose(scan_file);
    scan_file = NULL;
    void_log("[sound] %d landing, damage and colour-sucking sounds known by size", size_count);
}

int void_sound_event_for_size(uint32_t bytes)
{
    pthread_once(&once, load_sizes);
    for (int i = 0; i < size_count; ++i)
        if (sizes[i].bytes == bytes) return sizes[i].event;
    return -1;
}

void void_sound_event_played(int event)
{
    if (event >= 0 && event < SOUND_EVENTS) atomic_fetch_add(&counts[event], 1);
}

void void_sound_events(uint32_t out[SOUND_EVENTS])
{
    for (int i = 0; i < SOUND_EVENTS; ++i) out[i] = atomic_load(&counts[i]);
}

static _Atomic int forced[SOUND_EVENTS];

void void_sound_event_force(int event, int playing)
{
    if (event < 0 || event >= SOUND_EVENTS) return;
    if (playing < 0) void_sound_event_played(event);
    else atomic_store(&forced[event], playing);
}

int void_sound_event_forced(int event)
{
    return event >= 0 && event < SOUND_EVENTS ? atomic_load(&forced[event]) : 0;
}
