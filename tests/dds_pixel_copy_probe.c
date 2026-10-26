/* Compare both entire shipping format tables/converters. Guard every output,
 * vary both input/output alignment, and preserve source bytes including pitch. */
#include <stdio.h>
#include "format-types.h"

typedef struct allocation { uint8_t *base, *data; size_t size, total; } allocation;
static allocation slots[2];
static unsigned output_alignment;
static uint32_t rng = 0x21f0a753u;
static unsigned tests;
#define CHECK(x) do { if (!(x)) { printf("FAIL line %d case %u: %s\n", __LINE__, tests, #x); exit(1); } } while (0)
static uint32_t random32(void) { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return rng; }
static void *allocate(unsigned which, size_t size) {
    allocation *a = &slots[which];
    CHECK(!a->base);
    a->size = size; a->total = size + 128 + output_alignment;
    a->base = malloc(a->total); CHECK(a->base);
    memset(a->base, 0xcd, a->total); a->data = a->base + 64 + output_alignment;
    return a->data;
}
void *original_alloc(size_t size) { return allocate(0, size); }
void *fixed_alloc(size_t size) { return allocate(1, size); }
static int guard_ok(const allocation *a, size_t output_size) {
    for (size_t i = 0; i < (size_t)(a->data - a->base); ++i) if (a->base[i] != 0xcd) return 0;
    for (size_t i = (size_t)(a->data - a->base) + output_size; i < a->total; ++i) if (a->base[i] != 0xcd) return 0;
    return 1;
}
static void one(uint32_t format, uint32_t width, uint32_t height, uint32_t padding, unsigned alignment, unsigned pattern) {
    ++tests;
    const d3d_format *a = original_d3d_format_find(format), *b = fixed_d3d_format_find(format);
    CHECK(a && b && !memcmp(a, b, sizeof *a));
    uint32_t pitch = original_d3d_format_pitch(a, width) + padding;
    CHECK(original_d3d_format_pitch(a, width) == fixed_d3d_format_pitch(b, width));
    uint32_t rows = original_d3d_format_rows(a, height);
    CHECK(rows == fixed_d3d_format_rows(b, height));
    size_t size = (size_t)pitch * rows, total = size + 128 + alignment;
    uint8_t *input = malloc(total), *saved = malloc(total); CHECK(input && saved);
    memset(input, 0xa6, total);
    uint8_t *data = input + 64 + alignment;
    for (size_t i = 0; i < size; ++i) data[i] = pattern == 1 ? 0 : pattern == 2 ? 255 : (uint8_t)random32();
    if (pattern >= 3) {
        for (uint32_t y = 0; y < rows; ++y) for (uint32_t x = 0; x < (width + 3) / 4; ++x) {
            uint8_t *p = data + (size_t)y * pitch + x * a->block_bytes;
            if (a->conv == CONV_DXT1 || a->conv == CONV_DXT3 || a->conv == CONV_DXT5) {
                unsigned offset = a->conv == CONV_DXT1 ? 0 : 8;
                p[offset] = p[offset + 2] = 0x55; p[offset + 1] = p[offset + 3] = 0xaa;
            }
            if (a->conv == CONV_DXT5 || a->conv == CONV_ATI1 || a->conv == CONV_ATI2) {
                p[0] = p[1] = 127;
                if (a->conv == CONV_ATI2) p[8] = p[9] = 127;
            }
        }
    }
    memcpy(saved, input, total);
    output_alignment = (alignment * 7 + padding) & 31;
    void *owned_a = NULL, *owned_b = NULL; size_t bytes_a = 0, bytes_b = 0;
    const void *result_a = original_d3d_format_convert(a, data, width, height, pitch, &owned_a, &bytes_a, 0);
    const void *result_b = fixed_d3d_format_convert(b, data, width, height, pitch, &owned_b, &bytes_b, 0);
    CHECK(result_a == owned_a && result_b == owned_b && result_a == slots[0].data && result_b == slots[1].data);
    CHECK(bytes_a == bytes_b && bytes_a == (size_t)width * height * (a->gl_bits / 8));
    CHECK(slots[0].size == slots[1].size && !memcmp(result_a, result_b, bytes_a));
    CHECK(guard_ok(&slots[0], bytes_a) && guard_ok(&slots[1], bytes_b));
    CHECK(!memcmp(input, saved, total));
    for (int i = 0; i < 2; ++i) { free(slots[i].base); memset(&slots[i], 0, sizeof slots[i]); }
    free(input); free(saved);
}
int main(void) {
    const uint32_t formats[] = {FOURCC('D','X','T','1'), FOURCC('D','X','T','2'), FOURCC('D','X','T','3'),
        FOURCC('D','X','T','4'), FOURCC('D','X','T','5'), FOURCC('A','T','I','1'), FOURCC('A','T','I','2')};
    const uint32_t dimensions[] = {0,1,2,3,4,5,7,8,9,15,16,17,31,32,33,63};
    for (unsigned f = 0; f < 7; ++f) {
        for (unsigned w = 0; w < 16; ++w) for (unsigned h = 0; h < 16; ++h)
            for (unsigned pattern = 0; pattern < 4; ++pattern)
                one(formats[f], dimensions[w], dimensions[h], pattern * 5, (w * 3 + h * 7 + pattern) & 31, pattern);
        one(formats[f], 257, 513, 19, 1, 0); one(formats[f], 1023, 65, 7, 31, 0);
        one(formats[f], 512, 256, 0, 0, 0);
    }
    for (unsigned i = 0; i < 8000; ++i) {
        uint32_t format = formats[random32() % 7], w = random32() % 98, h = random32() % 98;
        uint32_t padding = random32() % 32; unsigned alignment = random32() % 32;
        one(format, w, h, padding, alignment, 0);
    }
    printf("PASS %u exact converter cases: DXT1/2/3/4/5 ATI1/2; zero/tiny/partial/large, random/equal endpoints, padded pitches, unaligned input/output, guards and immutable sources\n", tests);
    return 0;
}
