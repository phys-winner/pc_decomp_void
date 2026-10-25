/* The directory of one of the release's VFS containers (LP2C, the layout
 * tools/build_vfs_index.py reads): every file's path, offset and size. The
 * touch layer's helpers (hud.c, sound_events.c) find game files by name. */
#include "host.h"
#include "vfs_dir.h"
#include <dirent.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>

typedef struct { void_vfs_entry_fn fn; void *ctx; } scan_t;

/* One directory level: its files, then its subdirectories. */
static int read_dir(FILE *f, char *path, size_t len, uint32_t dirs, uint32_t files, int depth, scan_t *s)
{
    if (depth > 32) return 0;
    for (uint32_t i = 0; i < files; ++i) {
        int n = fgetc(f);
        char name[256];
        uint32_t meta[6];
        if (n < 0 || fread(name, 1, (size_t)n, f) != (size_t)n || fread(meta, 4, 6, f) != 6) return 0;
        name[n] = 0;
        if (len + 1 + (size_t)n + 1 > 1024) continue;
        snprintf(path + len, 1024 - len, "\\%s", name);
        long here = ftell(f);
        s->fn(path, meta[2], meta[0], s->ctx);
        fseek(f, here, SEEK_SET);   /* the callback may read the file's data */
        path[len] = 0;
    }
    for (uint32_t i = 0; i < dirs; ++i) {
        int n = fgetc(f);
        char name[256];
        uint32_t counts[2];
        if (n < 0 || fread(name, 1, (size_t)n, f) != (size_t)n || fread(counts, 4, 2, f) != 2) return 0;
        name[n] = 0;
        if (len + 1 + (size_t)n + 1 > 1024) return 0;
        snprintf(path + len, 1024 - len, "\\%s", name);
        if (!read_dir(f, path, len + 1 + (size_t)n, counts[0], counts[1], depth + 1, s)) return 0;
        path[len] = 0;
    }
    return 1;
}

FILE *void_vfs_open(const char *container)
{
    char dir[1100], file[1400];
    snprintf(dir, sizeof dir, "%s/data", void_root_dir());
    file[0] = 0;
    DIR *d = opendir(dir);
    if (d) {
        struct dirent *e;
        while ((e = readdir(d)))
            if (!strcasecmp(e->d_name, container)) { snprintf(file, sizeof file, "%s/%s", dir, e->d_name); break; }
        closedir(d);
    }
    return file[0] ? fopen(file, "rb") : NULL;
}

int void_vfs_scan(FILE *f, const char *root, void_vfs_entry_fn fn, void *ctx)
{
    char magic[4];
    uint32_t counts[2];
    char path[1024];
    snprintf(path, sizeof path, "%s", root);
    if (fseek(f, 0, SEEK_SET) || fread(magic, 1, 4, f) != 4 || memcmp(magic, "LP2C", 4) || fread(counts, 4, 2, f) != 2)
        return 0;
    scan_t s = { fn, ctx };
    return read_dir(f, path, strlen(path), counts[0], counts[1], 0, &s);
}
