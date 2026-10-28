/* The Void's converted textures: <game>/data/port-textures.tvt.
 *
 * The game's DXT textures (DDS files and animation frames inside
 * data/Textures.vfs) re-encoded once, by the launcher's converter
 * (android/texconv), into a format a GPU without S3TC samples directly:
 * ETC2 (GLES 3.0 core) or ASTC 4x4 (KHR_texture_compression_astc_ldr). The
 * host's D3DX loader (android/host/d3dx9.c) finds a texture's converted
 * levels by the content of the DDS the game hands it: its header and every
 * DXT level of every face (CRC-32 and CRC-32C together). No container's mount
 * order or path is involved; anything else (a patched copy, an override) keeps
 * its own data, and a pack made from other game files simply never matches.
 *
 * File: tvtx_header, the payloads, then the index (count tvtx_entry, sorted
 * by key). A payload holds each face's levels in order, tightly packed blocks,
 * the level sizes following from the DDS header and the entry's GL format.
 * Little-endian, as written on the device. */
#ifndef VOID_TVTX_H
#define VOID_TVTX_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define TVTX_MAGIC 0x58545654u          /* "TVTX" */
#define TVTX_VERSION 1u
#define TVTX_FILE "port-textures.tvt"   /* in <game>/data, beside the containers */

enum { TVTX_ETC2 = 1, TVTX_ASTC = 2 };

/* GL internal formats of converted levels. */
#define TVTX_GL_ETC2_RGB8 0x9274u       /* COMPRESSED_RGB8_ETC2: 8 bytes a 4x4 block */
#define TVTX_GL_ETC2_RGBA8 0x9278u      /* COMPRESSED_RGBA8_ETC2_EAC: 16 bytes */
#define TVTX_GL_ASTC_4x4 0x93B0u        /* COMPRESSED_RGBA_ASTC_4x4_KHR: 16 bytes */

#define TVTX_OPAQUE 1u                  /* entry flag: every texel's alpha is 255 */

typedef struct {
    uint32_t magic, version, family, count;     /* count: index entries */
    uint64_t index_offset;                      /* the index, after the payloads */
    uint64_t payload_bytes;                     /* every payload together */
    uint64_t source_bytes;                      /* the converted DDS files' bytes */
    uint64_t source_container;                  /* data/Textures.vfs's size when converted */
    uint32_t sources, skipped;                  /* DXT textures found; kept as they are (duplicates excluded) */
    uint32_t reserved[4];
} tvtx_header;                                  /* 64 bytes */

typedef struct {
    uint64_t key;                               /* tvtx_key of the DDS bytes [0, dds_bytes) */
    uint32_t dds_bytes;                         /* the header and every DXT level of every face */
    uint32_t gl_format;                         /* TVTX_GL_* */
    uint64_t offset;                            /* the payload in the file */
    uint32_t bytes, flags;
} tvtx_entry;                                   /* 32 bytes */

/* The index entry of a DDS (an index sorted by key, then size), NULL if none. */
static inline const tvtx_entry *tvtx_find(const tvtx_entry *index, uint32_t count, uint64_t key, uint32_t dds_bytes)
{
    uint32_t lo = 0, hi = count;
    while (lo < hi) {
        uint32_t mid = lo + (hi - lo) / 2;
        const tvtx_entry *e = &index[mid];
        if (e->key < key || (e->key == key && e->dds_bytes < dds_bytes)) lo = mid + 1;
        else hi = mid;
    }
    return lo < count && index[lo].key == key && index[lo].dds_bytes == dds_bytes ? &index[lo] : NULL;
}

/* Bytes of one converted level. */
static inline uint64_t tvtx_level_bytes(uint32_t gl_format, uint32_t w, uint32_t h)
{
    uint64_t blocks = (uint64_t)((w + 3) / 4) * ((h + 3) / 4);
    return blocks * (gl_format == TVTX_GL_ETC2_RGB8 ? 8u : 16u);
}

/* ---------------------------------------------------------- the key
 * CRC-32 (IEEE, zlib's) in the low half, CRC-32C in the high half. ARMv8
 * computes both with its CRC instructions (some 10 GB/s on a phone core);
 * elsewhere, and on a CPU without them, slicing-by-8 tables. */
typedef struct { uint32_t t[2][8][256]; int ready; } tvtx_crc_tables;

static inline void tvtx_crc_init(tvtx_crc_tables *c)
{
    const uint32_t polys[2] = {0xEDB88320u, 0x82F63B78u};
    for (int p = 0; p < 2; ++p) {
        for (uint32_t i = 0; i < 256; ++i) {
            uint32_t v = i;
            for (int k = 0; k < 8; ++k) v = (v >> 1) ^ (polys[p] & (0u - (v & 1u)));
            c->t[p][0][i] = v;
        }
        for (uint32_t i = 0; i < 256; ++i)
            for (int s = 1; s < 8; ++s) c->t[p][s][i] = (c->t[p][s - 1][i] >> 8) ^ c->t[p][0][c->t[p][s - 1][i] & 255u];
    }
    c->ready = 1;
}

static inline uint32_t tvtx_crc_soft(const tvtx_crc_tables *c, int p, uint32_t crc, const uint8_t *s, size_t n)
{
    const uint32_t (*t)[256] = c->t[p];
    while (n >= 8) {
        uint32_t lo = (uint32_t)s[0] | ((uint32_t)s[1] << 8) | ((uint32_t)s[2] << 16) | ((uint32_t)s[3] << 24);
        uint32_t hi = (uint32_t)s[4] | ((uint32_t)s[5] << 8) | ((uint32_t)s[6] << 16) | ((uint32_t)s[7] << 24);
        lo ^= crc;
        crc = t[7][lo & 255u] ^ t[6][(lo >> 8) & 255u] ^ t[5][(lo >> 16) & 255u] ^ t[4][lo >> 24] ^
              t[3][hi & 255u] ^ t[2][(hi >> 8) & 255u] ^ t[1][(hi >> 16) & 255u] ^ t[0][hi >> 24];
        s += 8;
        n -= 8;
    }
    while (n--) crc = (crc >> 8) ^ t[0][(crc ^ *s++) & 255u];
    return crc;
}

#if defined(__aarch64__) && defined(__clang__)
#include <arm_acle.h>
#if defined(__ANDROID__) || defined(__linux__)
#include <sys/auxv.h>
#ifndef HWCAP_CRC32
#define HWCAP_CRC32 (1 << 7)
#endif
#endif
__attribute__((target("crc"))) static inline uint64_t tvtx_key_crc(const uint8_t *s, size_t n)
{
    uint32_t a = 0xFFFFFFFFu, c = 0xFFFFFFFFu;
    for (; n >= 8; s += 8, n -= 8) {
        uint64_t v;
        memcpy(&v, s, 8);
        a = __crc32d(a, v);
        c = __crc32cd(c, v);
    }
    for (; n; ++s, --n) {
        a = __crc32b(a, *s);
        c = __crc32cb(c, *s);
    }
    return ((uint64_t)~c << 32) | (uint32_t)~a;
}
#endif

/* tables: zeroed storage the caller keeps (filled on first use). */
static inline uint64_t tvtx_key(tvtx_crc_tables *tables, const uint8_t *data, size_t n)
{
#if defined(__aarch64__) && defined(__clang__) && (defined(__ANDROID__) || defined(__linux__))
    static int hardware = -1;
    if (hardware < 0) hardware = (getauxval(AT_HWCAP) & HWCAP_CRC32) != 0;
    if (hardware) return tvtx_key_crc(data, n);
#endif
    if (!tables->ready) tvtx_crc_init(tables);
    uint32_t a = ~tvtx_crc_soft(tables, 0, 0xFFFFFFFFu, data, n);
    uint32_t c = ~tvtx_crc_soft(tables, 1, 0xFFFFFFFFu, data, n);
    return ((uint64_t)c << 32) | a;
}

/* ------------------------------------------------------------ DDS
 * The DXT DDS files the conversion covers: 2D or full cube, DXT1/2/3/4/5,
 * every stored level present. tvtx_dds_bytes: the header and levels, 0 for
 * anything else (other formats, volumes, partial cubes, truncated data). */
typedef struct { uint32_t width, height, mips, faces, fourcc, block; } tvtx_dds;

static inline uint32_t tvtx_le32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static inline uint64_t tvtx_dds_bytes(const uint8_t *data, uint64_t size, tvtx_dds *d)
{
    if (size < 128 || memcmp(data, "DDS ", 4) || tvtx_le32(data + 4) != 124) return 0;
    const uint8_t *h = data + 4;
    if (!(tvtx_le32(h + 76) & 4u)) return 0;                        /* DDPF_FOURCC */
    uint32_t fourcc = tvtx_le32(h + 80);
    if ((fourcc & 0x00FFFFFFu) != 0x00545844u) return 0;            /* "DXT?" */
    uint32_t kind = fourcc >> 24;
    if (kind < '1' || kind > '5') return 0;
    d->fourcc = fourcc;
    d->block = kind == '1' ? 8u : 16u;
    d->height = tvtx_le32(h + 8);
    d->width = tvtx_le32(h + 12);
    d->mips = tvtx_le32(h + 24) ? tvtx_le32(h + 24) : 1u;
    uint32_t caps2 = tvtx_le32(h + 108);
    if (caps2 & 0x200000u) return 0;                               /* volume */
    d->faces = (caps2 & 0x200u) ? 6u : 1u;
    if (d->faces == 6 && (caps2 & 0xFC00u) != 0xFC00u) return 0;   /* partial cube */
    if (!d->width || !d->height || d->width > 16384 || d->height > 16384 || d->mips > 15) return 0;
    uint64_t levels = 0;
    for (uint32_t l = 0; l < d->mips; ++l) {
        uint32_t w = d->width >> l ? d->width >> l : 1, hh = d->height >> l ? d->height >> l : 1;
        levels += (uint64_t)((w + 3) / 4) * ((hh + 3) / 4) * d->block;
    }
    uint64_t total = 128 + levels * d->faces;
    return total <= size && total <= 0xFFFFFFFFu ? total : 0;
}

#endif
