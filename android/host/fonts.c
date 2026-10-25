/* The interface scale for the game's text. Its text comes from bitmap fonts
 * of fixed pixel sizes (Textures\Fonts\fontmain_<px>.ft, 8..28 and 36) that
 * the scripts pick by name: mostly fixed sizes, a few by the screen's width,
 * while the images of the interface follow the screen's height. A request
 * for fontmain_N gets the font nearest to N times the scale, copied once
 * from the release's Textures.vfs into <data>/fonts/<container size>; the
 * scripts measure the text with the font they get. */
#include "host.h"
#include "fonts.h"
#include "vfs_dir.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <unistd.h>

#define LARGEST 36

static float scale = 1.0f;
static struct { uint32_t offset, size; } fonts[LARGEST + 1];   /* by pixel size */
static pthread_once_t scanned = PTHREAD_ONCE_INIT;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;

void void_fonts_set_scale(float s)
{
    if (s >= 0.25f && s <= 8.0f) scale = s;
    void_log("[fonts] the game's text at %.2f of its sizes", scale);
}

static int available(int px) { return (px >= 8 && px <= 28) || px == LARGEST; }

static int nearest(float target)
{
    int best = 0;
    for (int px = 8; px <= LARGEST; ++px)
        if (available(px) && (!best || fabsf((float)px - target) < fabsf((float)best - target))) best = px;
    return best;
}

static void found(const char *path, uint32_t offset, uint32_t size, void *ctx)
{
    (void)ctx;
    static const char prefix[] = "textures\\fonts\\fontmain_";
    if (strncasecmp(path, prefix, sizeof prefix - 1)) return;
    char *end;
    long px = strtol(path + sizeof prefix - 1, &end, 10);
    if (px > 0 && px <= LARGEST && !strcasecmp(end, ".ft")) {
        fonts[px].offset = offset;
        fonts[px].size = size;
    }
}

static void scan(void)
{
    FILE *f = void_vfs_open("Textures.vfs");
    if (!f) return;
    if (!void_vfs_scan(f, "textures", found, NULL)) void_log("[fonts] Textures.vfs: unreadable directory");
    fclose(f);
}

/* <data>/fonts/<size of the release's Textures.vfs>: releases differ in their fonts' letters. */
static int cache_dir(char *dir, size_t cap)
{
    FILE *f = void_vfs_open("Textures.vfs");
    struct stat st;
    int ok = f && !fstat(fileno(f), &st);
    if (f) fclose(f);
    if (!ok) return 0;
    snprintf(dir, cap, "%s/fonts", void_data_dir());
    mkdir(dir, 0775);
    snprintf(dir, cap, "%s/fonts/%llx", void_data_dir(), (unsigned long long)st.st_size);
    mkdir(dir, 0775);
    return 1;
}

static int extracted(int px, char *path, size_t cap)
{
    char dir[1100];
    if (!cache_dir(dir, sizeof dir)) return 0;
    snprintf(path, cap, "%s/fontmain_%d.ft", dir, px);
    struct stat st;
    if (!stat(path, &st) && S_ISREG(st.st_mode) && st.st_size > 0) return 1;
    pthread_once(&scanned, scan);
    uint32_t size = fonts[px].size;
    if (!size) return 0;
    FILE *f = void_vfs_open("Textures.vfs");
    uint8_t *data = (uint8_t *)malloc(size);
    int ok = f && data && !fseek(f, (long)fonts[px].offset, SEEK_SET) && fread(data, 1, size, f) == size;
    if (f) fclose(f);
    if (ok) {
        char part[1300];
        snprintf(part, sizeof part, "%s.part", path);
        FILE *o = fopen(part, "wb");
        ok = o && fwrite(data, 1, size, o) == size;
        if (o && fclose(o)) ok = 0;
        ok = ok && !rename(part, path);
        if (!ok) unlink(part);
    }
    free(data);
    return ok;
}

/* The texture system looks for a loose file by name before its archive:
 * data\Textures\lang_<language>\<name>, then data\Textures\<name>. */
char *void_fonts_path(const char *norm)
{
    static const char prefix[] = "C:\\Games\\The Void\\data\\Textures\\";
    if (scale == 1.0f || strncasecmp(norm, prefix, sizeof prefix - 1)) return NULL;
    const char *name = strrchr(norm, '\\') + 1;
    if (strncasecmp(name, "fontmain_", 9)) return NULL;
    char *end;
    long px = strtol(name + 9, &end, 10);
    if (px <= 0 || px > 256 || strcasecmp(end, ".ft")) return NULL;
    int want = nearest((float)px * scale);
    if (want == px) return NULL;
    char *path = (char *)malloc(1300);
    pthread_mutex_lock(&lock);
    int ok = path && extracted(want, path, 1300);
    pthread_mutex_unlock(&lock);
    static int logged;
    if (logged++ < 32) void_log("[fonts] fontmain_%ld.ft: %d px%s", px, want, ok ? "" : " is not available");
    if (!ok) { free(path); return NULL; }
    return path;
}
