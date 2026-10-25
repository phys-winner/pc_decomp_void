/* android/host/pictures.c on its own: every D3DXIMAGE_FILEFORMAT from a
 * known picture, opaque and with alpha, into the folder of argv[1]
 * (tests/test_pictures.py builds it for the phone and checks the files). */
#include "host.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static int logged, changed;

void void_log(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    pthread_mutex_lock(&lock);
    printf("log ");
    vprintf(fmt, ap);
    printf("\n");
    fflush(stdout);
    ++logged;
    pthread_mutex_unlock(&lock);
    va_end(ap);
}

void void_files_changed(void)
{
    pthread_mutex_lock(&lock);
    ++changed;
    pthread_mutex_unlock(&lock);
}

#define W 37
#define H 23

/* tests/test_pictures.py computes the same values. */
static float *picture(int alpha)
{
    float *p = (float *)malloc(W * H * 16);
    for (int y = 0; y < H; ++y)
        for (int x = 0; x < W; ++x) {
            float *t = p + (y * W + x) * 4;
            t[0] = x / (float)(W - 1);
            t[1] = y / (float)(H - 1);
            t[2] = ((x * 7 + y * 13) % 31) / 30.0f;
            t[3] = alpha ? ((x + y) % 5) / 4.0f : 1.0f;
        }
    p[0] = -0.5f;   /* out of range: clamped */
    p[1] = 1.5f;
    return p;
}

static const char *const ext[] = { "bmp", "jpg", "tga", "png", "dds", "ppm", "dib", "hdr", "pfm" };

int main(int argc, char **argv)
{
    const char *dir = argc > 1 ? argv[1] : ".";
    int calls = 0;
    for (int alpha = 0; alpha < 2; ++alpha)
        for (int f = 0; f <= VOID_IFF_PFM; ++f) {
            char path[512];
            snprintf(path, sizeof path, "%s/%s.%s", dir, alpha ? "alpha" : "opaque", ext[f]);
            unlink(path);
            if (!void_picture_write(strdup(path), (uint32_t)f, W, H, alpha ? 21 : 22, picture(alpha))) {
                printf("failed %s\n", path);
                return 1;
            }
            ++calls;
            /* There before it is written: the game's next name is taken. */
            printf("created %s %d\n", path, access(path, F_OK) == 0);
        }
    printf("unwritable %d\n", void_picture_write(strdup("/nonexistent/x.png"), VOID_IFF_PNG, W, H, 22, picture(0)));
    for (int i = 0; i < 500; ++i) {
        pthread_mutex_lock(&lock);
        int done = logged >= calls + 1;
        pthread_mutex_unlock(&lock);
        if (done) break;
        usleep(10000);
    }
    printf("changed %d\n", changed);
    for (char *s; (s = void_picture_saved()) != NULL; free(s)) printf("saved %s\n", s);
    return 0;
}
