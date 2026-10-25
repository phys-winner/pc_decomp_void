/* Guest string access: UTF-16LE wide strings and code page 1252 ANSI
 * strings (the ANSI code page of the Windows host the build was validated on). */
#include "host.h"

/* Windows-1252 0x80..0x9F; 0 marks the five undefined bytes, which
 * MultiByteToWideChar maps to the same-valued C1 control. */
static const uint16_t cp1252_high[32] = {
    0x20AC, 0x0081, 0x201A, 0x0192, 0x201E, 0x2026, 0x2020, 0x2021,
    0x02C6, 0x2030, 0x0160, 0x2039, 0x0152, 0x008D, 0x017D, 0x008F,
    0x0090, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2013, 0x2014,
    0x02DC, 0x2122, 0x0161, 0x203A, 0x0153, 0x009D, 0x017E, 0x0178,
};

uint16_t void_cp1252_to_u16(uint8_t c)
{
    return (c >= 0x80 && c < 0xA0) ? cp1252_high[c - 0x80] : c;
}

int void_u16_to_cp1252(uint16_t u, uint8_t *out)
{
    if (u < 0x80 || (u >= 0xA0 && u < 0x100)) { *out = (uint8_t)u; return 1; }
    for (int i = 0; i < 32; ++i) if (cp1252_high[i] == u) { *out = (uint8_t)(0x80 + i); return 1; }
    *out = '?';
    return 0;
}

size_t void_utf8_encode(uint32_t cp, char *out)
{
    if (cp < 0x80) { out[0] = (char)cp; return 1; }
    if (cp < 0x800) { out[0] = (char)(0xC0 | (cp >> 6)); out[1] = (char)(0x80 | (cp & 0x3F)); return 2; }
    if (cp < 0x10000) {
        out[0] = (char)(0xE0 | (cp >> 12)); out[1] = (char)(0x80 | ((cp >> 6) & 0x3F));
        out[2] = (char)(0x80 | (cp & 0x3F)); return 3;
    }
    out[0] = (char)(0xF0 | (cp >> 18)); out[1] = (char)(0x80 | ((cp >> 12) & 0x3F));
    out[2] = (char)(0x80 | ((cp >> 6) & 0x3F)); out[3] = (char)(0x80 | (cp & 0x3F));
    return 4;
}

/* Decode one UTF-8 code point; invalid bytes decode as U+FFFD. */
static uint32_t utf8_next(const unsigned char **p)
{
    const unsigned char *s = *p;
    uint32_t c = *s++;
    if (c >= 0x80) {
        int extra = c >= 0xF0 ? 3 : c >= 0xE0 ? 2 : c >= 0xC0 ? 1 : -1;
        if (extra < 0) { *p = s; return 0xFFFD; }
        c &= 0x3Fu >> extra;
        for (int i = 0; i < extra; ++i) {
            if ((*s & 0xC0) != 0x80) { *p = s; return 0xFFFD; }
            c = (c << 6) | (*s++ & 0x3F);
        }
    }
    *p = s;
    return c;
}

size_t void_gstrlen(uint32_t va)
{
    return va ? strlen((const char *)GPTR(va)) : 0;
}

size_t void_gwcslen(uint32_t va)
{
    size_t n = 0;
    if (!va) return 0;
    while (MEM16(va + 2u * (uint32_t)n)) ++n;
    return n;
}

char *void_wstr_utf8(uint32_t va)
{
    if (!va) return NULL;
    size_t n = void_gwcslen(va);
    char *out = (char *)malloc(n * 3 + 1), *w = out;
    for (size_t i = 0; i < n; ++i) {
        uint32_t c = MEM16(va + 2u * (uint32_t)i);
        if (c >= 0xD800 && c < 0xDC00 && i + 1 < n) {
            uint32_t low = MEM16(va + 2u * (uint32_t)(i + 1));
            if (low >= 0xDC00 && low < 0xE000) { c = 0x10000 + ((c - 0xD800) << 10) + (low - 0xDC00); ++i; }
        }
        w += void_utf8_encode(c, w);
    }
    *w = 0;
    return out;
}

char *void_astr_utf8(uint32_t va)
{
    if (!va) return NULL;
    size_t n = void_gstrlen(va);
    const uint8_t *s = (const uint8_t *)GPTR(va);
    char *out = (char *)malloc(n * 3 + 1), *w = out;
    for (size_t i = 0; i < n; ++i) w += void_utf8_encode(void_cp1252_to_u16(s[i]), w);
    *w = 0;
    return out;
}

uint32_t void_utf8_to_gw(const char *s, uint32_t dst, uint32_t cap)
{
    uint32_t need = 0;
    const unsigned char *p = (const unsigned char *)s;
    while (*p) { uint32_t c = utf8_next(&p); need += c >= 0x10000 ? 2 : 1; }
    if (need + 1 > cap) return need + 1;
    uint32_t i = 0;
    p = (const unsigned char *)s;
    while (*p) {
        uint32_t c = utf8_next(&p);
        if (c >= 0x10000) {
            c -= 0x10000;
            MEM16(dst + 2 * i++) = (uint16_t)(0xD800 + (c >> 10));
            MEM16(dst + 2 * i++) = (uint16_t)(0xDC00 + (c & 0x3FF));
        } else {
            MEM16(dst + 2 * i++) = (uint16_t)c;
        }
    }
    MEM16(dst + 2 * i) = 0;
    return i;
}

uint32_t void_utf8_to_ga(const char *s, uint32_t dst, uint32_t cap)
{
    uint32_t need = 0;
    const unsigned char *p = (const unsigned char *)s;
    while (*p) { (void)utf8_next(&p); ++need; }
    if (need + 1 > cap) return need + 1;
    uint32_t i = 0;
    p = (const unsigned char *)s;
    while (*p) {
        uint32_t c = utf8_next(&p);
        uint8_t b;
        void_u16_to_cp1252(c > 0xFFFF ? 0xFFFD : (uint16_t)c, &b);
        MEM8(dst + i++) = b;
    }
    MEM8(dst + i) = 0;
    return i;
}
