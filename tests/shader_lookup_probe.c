#include <assert.h>
#include <direct.h>
#include <io.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* bundle_disabled() probes for a POSIX no-bundle marker; none exists here, so
 * the packaged cache stays in play, as these cases expect. */
#define F_OK 0
#define access _access
static void void_log(const char *fmt, ...) { (void)fmt; }

/* Android atomics are compiled by the native build; this checks cache I/O policy. */
#define atomic_fetch_add_explicit(p, value, order) (*(p) += (value))
#define atomic_load_explicit(p, order) (*(p))
#define atomic_store_explicit(p, value, order) (*(p) = (value))
#define atomic_compare_exchange_strong_explicit(p, expected, value, success, failure) \
    ((*(p) == *(expected)) ? (*(p) = (value), 1) : (*(expected) = *(p), 0))
#define E_FAIL_ 0x80004005u
static uint32_t cache_responses;
static uint64_t missing_shader;
static uint64_t missing_family;
typedef struct { uint8_t *bytecode; uint32_t size; } d3d_shader;
static d3d_shader *failed_vs, *failed_ps;
static uint64_t failed_program;
static char packaged_cache_dir[1024], profile_dir[1024], result_data[4096];
typedef struct { uint32_t data; } dxbuffer_t;
static dxbuffer_t result_buffer = { 1 };
#define GPTR(value) (result_data)
static const char *void_data_dir(void) { return profile_dir; }
static void *void_com_host(uint32_t buffer) { assert(buffer == 1); return &result_buffer; }
static uint32_t make_buffer(const void *bytes, uint32_t size)
{
    assert(size < sizeof result_data);
    memcpy(result_data, bytes, size);
    result_data[size] = 0;
    return 1;
}
static char *read_all(const char *path, size_t *size)
{
    FILE *file = fopen(path, "rb");
    if (!file) return NULL;
    assert(!fseek(file, 0, SEEK_END));
    long length = ftell(file);
    assert(length >= 0 && !fseek(file, 0, SEEK_SET));
    char *bytes = malloc((size_t)length + 1);
    assert(bytes && fread(bytes, 1, (size_t)length, file) == (size_t)length);
    bytes[length] = 0;
    assert(!fclose(file));
    *size = (size_t)length;
    return bytes;
}

#include "cache-answer.h"

static void put(const char *dir, const char *suffix, const char *contents)
{
    char path[1200];
    snprintf(path, sizeof path, "%s/0000000000000001.%s", dir, suffix);
    FILE *file = fopen(path, "wb");
    assert(file && fputs(contents, file) >= 0 && !fclose(file));
}
static void erase(const char *dir, const char *suffix)
{
    char path[1200];
    snprintf(path, sizeof path, "%s/0000000000000001.%s", dir, suffix);
    assert(!remove(path));
}
static void put_binary(const char *dir, const void *contents, size_t size)
{
    char path[1200];
    snprintf(path, sizeof path, "%s/0000000000000001.bin", dir);
    FILE *file = fopen(path, "wb");
    assert(file && fwrite(contents, 1, size, file) == size && !fclose(file));
}
static void expect(int answer, uint32_t hr, const char *contents)
{
    uint32_t out = 0, code = 0, previous = void_d3dx_cache_responses();
    assert(cache_answer(1, &out, &code, 0) == answer);
    assert(code == hr);
    assert(void_d3dx_cache_responses() == previous + (answer != 0));
    if (contents) assert(out == 1 && !strcmp(result_data, contents));
    else assert(out == 0);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    char profile_cache[1100], packaged[1100];
    snprintf(profile_dir, sizeof profile_dir, "%s/profile", argv[1]);
    assert(!_mkdir(profile_dir));
    snprintf(profile_cache, sizeof profile_cache, "%s/shadercache", profile_dir);
    assert(!_mkdir(profile_cache));
    snprintf(packaged, sizeof packaged, "%s/packaged", argv[1]);
    assert(!_mkdir(packaged));

    expect(0, 0, NULL);
    put(packaged, "bin", "packaged-bytecode");
    expect(0, 0, NULL); /* CLI never reads an Android cache implicitly. */
    void_d3dx_set_packaged_cache_dir(packaged);
    expect(1, 0, "packaged-bytecode");
    erase(packaged, "bin");
    put(packaged, "err", "hr=8876086c\npackaged-error");
    expect(-1, 0x8876086cu, "packaged-error");
    put(profile_cache, "bin", "profile-bytecode");
    expect(1, 0, "profile-bytecode");
    erase(profile_cache, "bin");
    put(profile_cache, "err", "hr=80004005\nprofile-error");
    erase(packaged, "err");
    put(packaged, "bin", "packaged-bytecode");
    expect(1, 0, "packaged-bytecode"); /* Corrected APK bytecode supersedes stale profile failure. */
    put(profile_cache, "bin", "");
    expect(1, 0, "packaged-bytecode"); /* Incomplete outputs must not count as bytecode. */
    erase(profile_cache, "bin");
    put(profile_cache, "bin", "profile-bytecode");
    expect(1, 0, "profile-bytecode"); /* Existing profile .bin precedes profile .err. */
    erase(profile_cache, "bin");
    erase(profile_cache, "err");
    void_d3dx_set_packaged_cache_dir(NULL);
    expect(0, 0, NULL);
    void_d3dx_set_packaged_cache_dir(packaged);
    snprintf(profile_dir, sizeof profile_dir, "%s/another-profile", argv[1]);
    expect(1, 0, "packaged-bytecode"); /* All profiles share one private APK copy. */
    erase(packaged, "bin");
    expect(0, 0, NULL);
    put(packaged, "bin", "");
    put(packaged, "err", "");
    expect(0, 0, NULL);
    assert(void_d3dx_missing_shader() == 0);
    shader_missing(123, 1); assert(void_d3dx_missing_shader() == 123);
    shader_missing(456, 0); assert(void_d3dx_missing_shader() == 123);
    shader_missing(456, 1); assert(void_d3dx_missing_shader() == 456);
    shader_missing(456, 0); assert(void_d3dx_missing_shader() == 0);
    shader_family_result(123, 90, 1); assert(void_d3dx_missing_shader() == 123);
    shader_family_result(456, 91, 0); assert(void_d3dx_missing_shader() == 123);
    shader_family_result(456, 90, 0); assert(void_d3dx_missing_shader() == 0);
    shader_family_result(123, 90, 1);
    void_d3dx_shader_failure(789, 1);
    shader_family_result(456, 90, 0); assert(void_d3dx_missing_shader() == 789);
    void_d3dx_shader_failure(789, 0); assert(void_d3dx_missing_shader() == 0);
    uint32_t valid[] = {0xffff0300, 0x0000ffff};
    uint32_t truncated[] = {0xffff0300, 0};
    assert(cache_bytecode_valid((const char *)valid, sizeof valid));
    assert(!cache_bytecode_valid((const char *)valid, sizeof valid - 1));
    assert(!cache_bytecode_valid((const char *)truncated, sizeof truncated));
    assert(!cache_bytecode_valid("corrupt!", 8));
    put_binary(packaged, valid, sizeof valid);
    snprintf(profile_dir, sizeof profile_dir, "%s/profile", argv[1]);
    put_binary(profile_cache, truncated, sizeof truncated);
    uint32_t out = 0, hr = 0;
    assert(cache_answer(1, &out, &hr, 1) == 1 && out == 1 && !memcmp(result_data, valid, sizeof valid));
    erase(packaged, "bin");
    assert(cache_answer(1, &out, &hr, 1) == 0);
    d3d_shader vs = {(uint8_t *)valid, sizeof valid}, ps = {(uint8_t *)truncated, sizeof truncated};
    shader_draw_result(&vs, &ps, 1);
    uint64_t failed = void_d3dx_missing_shader(); assert(failed != 0);
    shader_draw_result(&vs, NULL, 0); assert(void_d3dx_missing_shader() == failed);
    shader_draw_result(&vs, &ps, 1); assert(void_d3dx_missing_shader() == failed);
    shader_draw_result(&vs, &ps, 0); assert(void_d3dx_missing_shader() == 0);
    puts("PASS: profile/private cache precedence, bytecode/errors, CLI isolation, shared profiles, exact counters");
    return 0;
}
