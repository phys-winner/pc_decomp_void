/* Image files the game writes: its screenshots (F12, as PNG) and texture
 * dumps (DDS), from D3DXSaveTextureToFile / D3DXSaveSurfaceToFile (d3dx9.c
 * reads the picture back). Encoding a 1080p PNG takes longer than a frame,
 * so it is done on a thread of its own; the file is created first, so the
 * next name the game looks for (scr0000.png, scr0001.png...) is already
 * taken. The pictures a phone can show are handed to the touch layer,
 * which puts them in the gallery. The encoders are stb_image_write's (Sean
 * Barrett, public domain, reference/stb, pinned with stb_vorbis in
 * dependencies.json, used unmodified). */
#include "host.h"
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define STB_IMAGE_WRITE_IMPLEMENTATION
#define STB_IMAGE_WRITE_STATIC
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Weverything"
#include "../../reference/stb/stb_image_write.h"
#pragma clang diagnostic pop

typedef struct picture {
    FILE *f;
    char *path;
    uint32_t file_format, width, height, format;
    int alpha;
    float *rgba;
} picture;

/* The pictures written since the touch layer last asked. */
#define SAVED_MAX 8
static pthread_mutex_t saved_lock = PTHREAD_MUTEX_INITIALIZER;
static char *saved[SAVED_MAX];
static int saved_count;

char *void_picture_saved(void)
{
    char *path = NULL;
    pthread_mutex_lock(&saved_lock);
    if (saved_count) {
        path = saved[0];
        memmove(saved, saved + 1, (size_t)--saved_count * sizeof *saved);
    }
    pthread_mutex_unlock(&saved_lock);
    return path;
}

static void picture_out(void *ctx, void *data, int size) { fwrite(data, 1, (size_t)size, (FILE *)ctx); }

static void put32(uint8_t *p, uint32_t v) { memcpy(p, &v, 4); }

/* An uncompressed A8R8G8B8 DDS. */
static int write_dds(FILE *f, uint32_t w, uint32_t h, const uint8_t *rgba)
{
    uint8_t head[128] = { 'D', 'D', 'S', ' ' };
    put32(head + 4, 124);
    put32(head + 8, 0x100F);           /* CAPS | HEIGHT | WIDTH | PITCH | PIXELFORMAT */
    put32(head + 12, h);
    put32(head + 16, w);
    put32(head + 20, w * 4);
    put32(head + 76, 32);
    put32(head + 80, 0x41);            /* DDPF_RGB | DDPF_ALPHAPIXELS */
    put32(head + 88, 32);
    put32(head + 92, 0x00FF0000u);
    put32(head + 96, 0x0000FF00u);
    put32(head + 100, 0x000000FFu);
    put32(head + 104, 0xFF000000u);
    put32(head + 108, 0x1000);         /* DDSCAPS_TEXTURE */
    if (fwrite(head, 1, sizeof head, f) != sizeof head) return 0;
    uint8_t *row = (uint8_t *)malloc((size_t)w * 4);
    int ok = 1;
    for (uint32_t y = 0; y < h && ok; ++y) {
        const uint8_t *src = rgba + (size_t)y * w * 4;
        for (uint32_t x = 0; x < w; ++x) {
            row[x * 4 + 0] = src[x * 4 + 2];
            row[x * 4 + 1] = src[x * 4 + 1];
            row[x * 4 + 2] = src[x * 4 + 0];
            row[x * 4 + 3] = src[x * 4 + 3];
        }
        ok = fwrite(row, 4, w, f) == w;
    }
    free(row);
    return ok;
}

static void *picture_main(void *arg)
{
    picture *p = (picture *)arg;
    uint32_t w = p->width, h = p->height;
    size_t n = (size_t)w * h;
    int ok = 0;
    if (p->file_format == VOID_IFF_HDR || p->file_format == VOID_IFF_PFM) {
        float *rgb = (float *)malloc(n * 12);
        for (size_t i = 0; i < n; ++i)
            for (int c = 0; c < 3; ++c) {
                float v = p->rgba[i * 4 + c];
                rgb[i * 3 + c] = p->file_format == VOID_IFF_HDR && v < 0.0f ? 0.0f : v;   /* RGBE has no sign */
            }
        if (p->file_format == VOID_IFF_HDR) {
            ok = stbi_write_hdr_to_func(picture_out, p->f, (int)w, (int)h, 3, rgb);
        } else {   /* rows bottom to top */
            ok = fprintf(p->f, "PF\n%u %u\n-1.0\n", w, h) > 0;
            for (uint32_t y = h; ok && y-- > 0;) ok = fwrite(rgb + (size_t)y * w * 3, 12, w, p->f) == w;
        }
        free(rgb);
    } else {
        uint8_t *px = (uint8_t *)malloc(n * 4);
        for (size_t i = 0; i < n * 4; ++i) {
            float v = p->rgba[i];
            px[i] = (uint8_t)(v <= 0.0f ? 0 : v >= 1.0f ? 255 : (int)(v * 255.0f + 0.5f));
        }
        int comps = p->alpha && p->file_format != VOID_IFF_JPG && p->file_format != VOID_IFF_PPM ? 4 : 3;
        if (p->file_format == VOID_IFF_DDS) {
            ok = write_dds(p->f, w, h, px);
        } else {
            if (comps == 3)
                for (size_t i = 0; i < n; ++i) {
                    px[i * 3 + 0] = px[i * 4 + 0];
                    px[i * 3 + 1] = px[i * 4 + 1];
                    px[i * 3 + 2] = px[i * 4 + 2];
                }
            switch (p->file_format) {
            case VOID_IFF_JPG: ok = stbi_write_jpg_to_func(picture_out, p->f, (int)w, (int)h, 3, px, 95); break;
            case VOID_IFF_TGA: ok = stbi_write_tga_to_func(picture_out, p->f, (int)w, (int)h, comps, px); break;
            case VOID_IFF_PNG:
                ok = stbi_write_png_to_func(picture_out, p->f, (int)w, (int)h, comps, px, (int)w * comps);
                break;
            case VOID_IFF_PPM:
                ok = fprintf(p->f, "P6\n%u %u\n255\n", w, h) > 0 && fwrite(px, 3, n, p->f) == n;
                break;
            default: ok = stbi_write_bmp_to_func(picture_out, p->f, (int)w, (int)h, comps, px); break;
            }
        }
        free(px);
    }
    ok = !fclose(p->f) && ok;
    void_log("[d3dx] picture %ux%u (format %u%s) %s: %s", w, h, p->format, p->alpha ? ", alpha" : "",
        ok ? "written" : "failed", p->path);
    if (ok && (p->file_format == VOID_IFF_PNG || p->file_format == VOID_IFF_JPG || p->file_format == VOID_IFF_BMP)) {
        pthread_mutex_lock(&saved_lock);
        if (saved_count < SAVED_MAX) saved[saved_count++] = p->path, p->path = NULL;
        pthread_mutex_unlock(&saved_lock);
    }
    free(p->path);
    free(p->rgba);
    free(p);
    return NULL;
}

int void_picture_write(char *host_path, uint32_t file_format, uint32_t width, uint32_t height, uint32_t format,
    float *rgba)
{
    picture *p = (picture *)calloc(1, sizeof *p);
    p->path = host_path;
    p->file_format = file_format;
    p->width = width;
    p->height = height;
    p->format = format;
    p->rgba = rgba;
    /* Alpha where the format keeps it: a render target's X8R8G8B8 does not. */
    float a = 1.0f;
    size_t n = (size_t)width * height;
    for (size_t i = 0; i < n && a == 1.0f; ++i) a = rgba[i * 4 + 3];
    p->alpha = a != 1.0f;
    p->f = fopen(host_path, "wb");
    if (!p->f) {
        void_log("[d3dx] picture: %s cannot be created (%d)", host_path, errno);
        free(p->rgba), free(p->path), free(p);
        return 0;
    }
    void_files_changed();
    pthread_t thread;
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    if (pthread_create(&thread, &attr, picture_main, p)) picture_main(p);
    pthread_attr_destroy(&attr);
    return 1;
}
