#include <assert.h>
#include <direct.h>
#include <io.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/stat.h>
#define _Atomic
typedef int atomic_int;
#define F_OK 0
#define access _access
#define atomic_load_explicit(p, order) (*(p))
#define atomic_store_explicit(p, value, order) (*(p) = (value))
#define atomic_fetch_add_explicit(p, value, order) ((*(p) += (value)) - (value))
#define atomic_load(p) (*(p))
#define atomic_store(p, value) (*(p) = (value))
#define mkdir(path, mode) _mkdir(path)
typedef unsigned GLuint;
typedef unsigned GLenum;
typedef int GLint;
typedef int GLsizei;
#define GL_VERTEX_SHADER 1
#define GL_FRAGMENT_SHADER 2
#define GL_COMPILE_STATUS 3
#define GL_LINK_STATUS 4
#define GL_PROGRAM_BINARY_LENGTH 5
#define GL_PROGRAM_BINARY_RETRIEVABLE_HINT 6
#define GL_TRUE 1
#define GL_VENDOR 7
#define GL_RENDERER 8
#define GL_VERSION 9
#define GL_SHADING_LANGUAGE_VERSION 10
/* The scan runs where it was asked, here: its own thread on the device. */
typedef int pthread_t;
static unsigned scans;
static int pthread_create(pthread_t *t, void *attr, void *(*run)(void *), void *arg) { (void)attr; *t = 1; ++scans; run(arg); return 0; }
static int pthread_detach(pthread_t t) { (void)t; return 0; }
#define HUD_MAINMENU (1u << 20)
static unsigned shader_count, program_count, stage_count, tags, binaries_loaded, retrievable;
static const char *driver_version = "driver 1";
static int reject_binaries;   /* the driver takes no program binary (an update) */
static GLuint binary_program;  /* the program last given a binary */
static uint32_t compiled_shaders;
uint32_t d3d_shader_compile_count(void) { return compiled_shaders; }
uint32_t void_d3dx_cache_responses(void) { return 7; }
static char shared[1200], profile[1200];
static void void_log(const char *fmt, ...) { (void)fmt; }
static uint32_t void_hud_state(void *unused) { (void)unused; return tags; }
static uint64_t void_monotonic_ns(void) { static uint64_t now; now += 4000000; return now; }
static const char *void_d3dx_packaged_cache_dir(void) { return shared; }
static const char *void_data_dir(void) { return profile; }
static GLuint glCreateShader(GLenum type) { (void)type; return ++shader_count; }
static void glShaderSource(GLuint gl, int count, const char *const *source, const int *length) { (void)gl; (void)length; assert(count == 1 && source && *source); }
static void glCompileShader(GLuint gl) { assert(gl); }
static void glGetShaderiv(GLuint gl, GLenum field, GLint *out) { assert(gl && field == GL_COMPILE_STATUS); *out = 1; }
static void glGetShaderInfoLog(GLuint gl, int size, void *length, char *out) { (void)gl; (void)size; (void)length; *out = 0; }
static void glDeleteShader(GLuint gl) { (void)gl; }
static GLuint glCreateProgram(void) { return ++program_count; }
static void glAttachShader(GLuint program, GLuint shader) { assert(program && shader); }
static void glBindAttribLocation(GLuint program, GLuint index, const char *name) { assert(program && index < 16 && name && *name); }
static void glLinkProgram(GLuint program) { assert(program); }
static void glGetProgramiv(GLuint gl, GLenum field, GLint *out)
{
    assert(gl && (field == GL_LINK_STATUS || field == GL_PROGRAM_BINARY_LENGTH));
    if (field == GL_PROGRAM_BINARY_LENGTH) *out = 16;
    else *out = gl == binary_program && reject_binaries ? 0 : 1;
}
static void glProgramParameteri(GLuint gl, GLenum name, GLint value) { assert(gl && name == GL_PROGRAM_BINARY_RETRIEVABLE_HINT && value == GL_TRUE); ++retrievable; }
static void glGetProgramBinary(GLuint gl, GLsizei size, GLsizei *length, GLenum *format, void *out)
{
    assert(gl && size >= 16); memset(out, 0, 16); snprintf(out, 16, "binary %u", gl); *length = 16; *format = 0x8741;
}
static void glProgramBinary(GLuint gl, GLenum format, const void *data, GLsizei length)
{
    assert(gl && format == 0x8741 && length == 16 && !memcmp(data, "binary ", 7)); binary_program = gl; ++binaries_loaded;
}
static const unsigned char *glGetString(GLenum name)
{
    return (const unsigned char *)(name == GL_VERSION ? driver_version : name == GL_VENDOR ? "vendor" : "renderer");
}
static void glGetProgramInfoLog(GLuint gl, int size, void *length, char *out) { (void)gl; (void)size; (void)length; *out = 0; }
static void glDeleteProgram(GLuint gl) { (void)gl; }
typedef struct { intptr_t handle; struct _finddata_t file; int first; } DIR;
struct dirent { char d_name[260]; };
static DIR *opendir(const char *path)
{
    char pattern[1300]; snprintf(pattern, sizeof pattern, "%s/*", path);
    DIR *d = calloc(1, sizeof *d); d->handle = _findfirst(pattern, &d->file);
    if (d->handle == -1) { free(d); return NULL; }
    d->first = 1; return d;
}
static struct dirent *readdir(DIR *d)
{
    static struct dirent e;
    if (!d->first && _findnext(d->handle, &d->file)) return NULL;
    d->first = 0; strcpy(e.d_name, d->file.name); return &e;
}
static int closedir(DIR *d) { int result = _findclose(d->handle); free(d); return result; }
static int d3d_shader_warm_bytecode(const void *bytes, uint32_t size) { assert(bytes && size >= 8); ++stage_count; return 1; }
#include "stage-cache.h"
#include "shader-warm.h"

static void put(const char *dir, const char *name, const void *bytes, size_t size)
{
    char path[1300]; snprintf(path, sizeof path, "%s/%s", dir, name);
    FILE *f = fopen(path, "wb"); assert(f && fwrite(bytes, 1, size, f) == size && !fclose(f));
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    snprintf(shared, sizeof shared, "%s/cache", argv[1]); assert(!_mkdir(shared));
    snprintf(profile, sizeof profile, "%s/profile", argv[1]); assert(!_mkdir(profile));
    uint32_t vs[] = {0xfffe0300, 0x0000ffff}, ps[] = {0xffff0300, 0x0000ffff};
    put(shared, "0000000000000001.bin", vs, sizeof vs);
    put(shared, "0000000000000002.bin", vs, sizeof vs);
    put(shared, "0000000000000003.bin", ps, sizeof ps);
    put(shared, "0000000000000004.bin", "not-code", 8);
    put(shared, "0000000000000005.bin", ps, 7);
    GLuint v = d3d_shader_compile_source(GL_VERTEX_SHADER, "vertex-source"), p = d3d_shader_compile_source(GL_FRAGMENT_SHADER, "pixel-source");
    assert(d3d_shader_compile_source(GL_VERTEX_SHADER, "vertex-source") == v && shader_count == 2 && compiled_shaders == 2);
    const char *names[] = {"vs_v0", "vs_v1"};
    GLuint original = d3d_warm_program(v, p, 2, names);
    assert(original && program_count == 1 && retrievable == 1 && binaries_loaded == 0);
    assert(!d3d_warm_program(v, p, 17, names));
    d3d_shader_warm_step(); assert(!d3d_shader_warm_progress());
    tags = HUD_MAINMENU;
    do { d3d_shader_warm_step(); } while ((uint32_t)d3d_shader_warm_progress() < (uint32_t)(d3d_shader_warm_progress() >> 32));
    uint64_t progress = d3d_shader_warm_progress();
    assert((progress >> 32) == 3 && (uint32_t)progress == 3 && stage_count == 2 && program_count == 2);
    assert(shader_count == 2 && compiled_shaders == 2 && scans == 1);
    /* The menu's recipe came from the program kept by the first link: loaded, not linked. */
    assert(binaries_loaded == 1 && atomic_load(&linked_programs) == 1 && retrievable == 1);
    GLuint reused = d3d_warm_program(v, p, 2, names);
    assert(reused != original && program_count == 2);
    GLuint separate_owner = d3d_warm_program(v, p, 2, names);
    assert(separate_owner != reused && program_count == 3 && binaries_loaded == 2);
    assert(atomic_load(&linked_programs) == 1 && atomic_load(&reused_programs) == 2 && atomic_load(&loaded_programs) == 2);
    /* Another driver (an update): its programs are linked again and kept anew. */
    driver_id = 0; driver_version = "driver 2";
    GLuint relinked = d3d_warm_program(v, p, 2, names);
    assert(relinked && atomic_load(&linked_programs) == 2 && binaries_loaded == 2 && retrievable == 2);
    GLuint kept = d3d_warm_program(v, p, 2, names);
    assert(kept && atomic_load(&linked_programs) == 2 && binaries_loaded == 3);
    /* A binary the driver refuses (damaged): linked again, then loaded again. */
    reject_binaries = 1;
    GLuint refused = d3d_warm_program(v, p, 2, names);
    assert(refused && atomic_load(&linked_programs) == 3 && binaries_loaded == 4);
    reject_binaries = 0;
    assert(d3d_warm_program(v, p, 2, names) && atomic_load(&linked_programs) == 3 && binaries_loaded == 5);
    d3d_shader_warm_stats();
    for (warm_entry *e = warmed; e; e = e->next) {
        assert(valid_recipe(e->bytes, e->size));
        assert(!valid_recipe(e->bytes, e->size - 1));
        recipe_header *h = e->bytes;
        uint32_t saved = h->count; h->count = 17; assert(!valid_recipe(h, e->size)); h->count = saved;
        saved = h->vertex_size; h->vertex_size = UINT32_MAX; assert(!valid_recipe(h, e->size)); h->vertex_size = saved;
        char first = h->names[0][0]; h->names[0][0] = 0; assert(!valid_recipe(h, e->size)); h->names[0][0] = first;
        char *vertex = (char *)(h + 1), end = vertex[h->vertex_size - 1]; vertex[h->vertex_size - 1] = 'x'; assert(!valid_recipe(h, e->size)); vertex[h->vertex_size - 1] = end;
    }
    assert(!valid_recipe("tiny", 4));
    puts("PASS: exact GPU-stage reuse, unique stages, real recipe replay/reuse, one uniform owner, bounded corrupt input, measured main-menu completion, kept program binaries (loaded, refused, another driver)");
    return 0;
}
