/* The launcher's texture converter (libtexconv.so): the game's DXT textures,
 * which some GPUs cannot sample (no S3TC: Adreno 6xx, Mali), re-encoded once
 * on the device into ETC2 or ASTC 4x4: <game>/data/port-textures.tvt
 * (android/texconv/tvtx.h). The original containers are only read.
 *
 * Sources: every .tex of data/Textures.vfs that is a DXT DDS, and every DXT
 * frame of its animation containers (u32 count, count u32 sizes, the DDS
 * files). The decode is the port's own (android/host/d3d9_format.c), so a
 * converted texture differs from what the port showed before only by the new
 * format's encoding. ETC2: opaque textures ETC2 RGB8 (a DXT5 without alpha
 * halves), the others ETC2 RGBA8 EAC; ASTC: 4x4 for all, opaque ones spending
 * no bits on alpha. */
#ifndef VOID_TEXCONV_H
#define VOID_TEXCONV_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum {
    TEXCONV_IDLE = 0,
    TEXCONV_SCANNING,
    TEXCONV_CONVERTING,
    TEXCONV_FINISHING,
    TEXCONV_DONE,
    TEXCONV_FAILED,
    TEXCONV_CANCELLED,
};

typedef struct {
    int state;
    int64_t done, total;              /* textures */
    int64_t bytes_done, bytes_total;  /* source DDS bytes */
    char message[512];                /* a failure's reason, English */
} texconv_progress;

typedef struct {
    int64_t textures;                 /* convertible DXT textures */
    int64_t bytes;                    /* their DDS bytes */
    int64_t estimate_etc2, estimate_astc;   /* the pack's size in each format */
    int64_t free_bytes;               /* free space in <game>/data */
    int converted;                    /* 0, TVTX_ETC2 or TVTX_ASTC: an existing pack */
    int64_t converted_textures, converted_bytes;   /* its entries and file size */
    int current;                      /* it was made from this Textures.vfs (same size, every source found) */
} texconv_status;

/* What <game>/data holds: 0, else -1 with the reason in the progress message. */
int texconv_scan(const char *game_dir, texconv_status *out);
/* Convert (blocking: a worker thread). threads <= 0: one per CPU. Writes
 * port-textures.tvt.part and renames it when complete; a failure or a cancel
 * leaves no pack (an older complete one stays until the new one replaces it). */
int texconv_convert(const char *game_dir, int family, int threads);
/* Delete the pack (and a leftover .part). */
int texconv_remove(const char *game_dir);
void texconv_cancel(void);
void texconv_get_progress(texconv_progress *out);

/* Building blocks, exported for tests (tests/texconv_probe.cpp). */
/* One DXT DDS: 0 converted (free *out with texconv_free), -1 not convertible. */
int texconv_convert_dds(const uint8_t *dds, uint64_t size, int family, uint8_t **out, uint64_t *out_size,
    uint32_t *gl_format, uint32_t *flags);
void texconv_free(void *pointer);
/* RGBA8 of one level: the DXT decode of a DDS, or a converted payload's level. */
int texconv_decode_dxt(const uint8_t *dds, uint64_t size, uint32_t face, uint32_t level, uint8_t *rgba);
int texconv_decode_converted(uint32_t gl_format, const uint8_t *blocks, uint32_t width, uint32_t height, uint8_t *rgba);
uint64_t texconv_key(const uint8_t *data, uint64_t size);

#ifdef __cplusplus
}
#endif

#endif
