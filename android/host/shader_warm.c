/* Compile shipped stages and replay observed, successful program recipes in
 * the main menu. Recipes contain GLSL, never device-specific driver binaries;
 * the programs linked from them are kept in the driver's own form in the
 * app's files (programcache), so a later start loads them instead. */
#include "d3d9_internal.h"
#include "hud.h"
#include "shader_warm.h"
#include <dirent.h>
#include <pthread.h>
#include <stdatomic.h>
#include <sys/stat.h>
#include <unistd.h>

#define RECIPE_MAGIC 0x31575356u
#define SOURCE_LIMIT (256u * 1024u)
typedef struct {
    uint32_t magic, vertex_size, pixel_size, count;
    char names[16][64];
} recipe_header;
typedef struct warm_entry {
    uint64_t hash;
    uint32_t size;
    int recipe;
    GLuint gl;
    void *bytes;
    struct warm_entry *next;
} warm_entry;
static warm_entry *queue, *pending, *warmed;
static _Atomic uint32_t warm_total, warm_done, linked_programs, reused_programs, failed, loaded_programs;
static int scanned;
static uint32_t queued;
/* The scan of the caches runs on its own thread: tens of thousands of small
 * files (the profile's on shared storage) must not hold the frame, nor the
 * machine the sound's streaming thread waits for. */
static pthread_t scan_thread;
static int scan_started;
static atomic_int scan_finished;

static uint64_t warm_hash(const void *bytes, size_t size)
{
    uint64_t hash = UINT64_C(0xcbf29ce484222325);
    const unsigned char *data = bytes;
    for (size_t i = 0; i < size; ++i) hash = (hash ^ data[i]) * UINT64_C(0x100000001b3);
    return hash;
}

static void recipe_directory(char path[1200])
{
    const char *base = void_d3dx_packaged_cache_dir();
    if (base[0]) snprintf(path, 1200, "%s/../shaderwarm", base);
    else snprintf(path, 1200, "%s/shaderwarm", void_data_dir());
}

static int valid_recipe(const void *bytes, size_t size)
{
    if (size < sizeof(recipe_header)) return 0;
    const recipe_header *h = bytes;
    if (h->magic != RECIPE_MAGIC || !h->vertex_size || !h->pixel_size || h->count > 16 ||
        h->vertex_size > SOURCE_LIMIT || h->pixel_size > SOURCE_LIMIT ||
        sizeof *h + (size_t)h->vertex_size + h->pixel_size != size) return 0;
    for (uint32_t i = 0; i < h->count; ++i)
        if (!h->names[i][0] || !memchr(h->names[i], 0, sizeof h->names[i])) return 0;
    const char *v = (const char *)(h + 1), *p = v + h->vertex_size;
    return v[h->vertex_size - 1] == 0 && p[h->pixel_size - 1] == 0 &&
        strlen(v) + 1 == h->vertex_size && strlen(p) + 1 == h->pixel_size;
}

/* Linked programs as the driver gives them back (glGetProgramBinary), one
 * file a recipe, under the driver's identity: a start after the first, or a
 * scene entered again, loads them instead of compiling and linking (the
 * system's own shader cache holds 32 MB and Android updates empty it). A
 * program the driver no longer takes is linked again and replaced. */
#define BINARY_MAGIC 0x42505356u
#define BINARY_LIMIT (16u * 1024u * 1024u)
#define BINARY_BUDGET (384ull * 1024u * 1024u)
typedef struct { uint32_t magic, format, length, reserved; uint64_t driver, recipe; } binary_header;
static uint64_t driver_id;
static _Atomic uint64_t binary_bytes;

static void binary_path(uint64_t recipe, char path[1200])
{
    const char *base = void_d3dx_packaged_cache_dir();
    char dir[1100];
    if (base[0]) snprintf(dir, sizeof dir, "%s/../programcache", base);
    else snprintf(dir, sizeof dir, "%s/programcache", void_data_dir());
    static int made;
    if (!made) { mkdir(dir, 0775); made = 1; }
    snprintf(path, 1200, "%s/%016llx.bin", dir, (unsigned long long)recipe);
}

static uint64_t driver(void)
{
    if (driver_id) return driver_id;
    uint64_t h = UINT64_C(0xcbf29ce484222325);
    const GLenum names[] = {GL_VENDOR, GL_RENDERER, GL_VERSION, GL_SHADING_LANGUAGE_VERSION};
    for (unsigned i = 0; i < 4; ++i) {
        const char *s = (const char *)glGetString(names[i]);
        for (; s && *s; ++s) h = (h ^ (unsigned char)*s) * UINT64_C(0x100000001b3);
        h = (h ^ 0xff) * UINT64_C(0x100000001b3);
    }
    return driver_id = h;
}

static GLuint binary_load(uint64_t recipe)
{
    char path[1200];
    binary_path(recipe, path);
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    binary_header h;
    void *data = NULL;
    GLuint gl = 0;
    if (fread(&h, sizeof h, 1, f) == 1 && h.magic == BINARY_MAGIC && h.driver == driver() && h.recipe == recipe &&
        h.length && h.length <= BINARY_LIMIT && (data = malloc(h.length)) && fread(data, 1, h.length, f) == h.length) {
        gl = glCreateProgram();
        glProgramBinary(gl, h.format, data, (GLsizei)h.length);
        GLint ok = 0;
        glGetProgramiv(gl, GL_LINK_STATUS, &ok);
        if (!ok) { glDeleteProgram(gl); gl = 0; }
    }
    fclose(f);
    free(data);
    if (!gl) remove(path);   /* another driver's, or damaged: linked again and replaced */
    else atomic_fetch_add_explicit(&loaded_programs, 1, memory_order_relaxed);
    return gl;
}

static void binary_save(GLuint gl, uint64_t recipe)
{
    char path[1200];
    binary_path(recipe, path);
    if (!access(path, F_OK)) return;
    GLint length = 0;
    glGetProgramiv(gl, GL_PROGRAM_BINARY_LENGTH, &length);
    if (length <= 0 || (uint32_t)length > BINARY_LIMIT ||
        atomic_load_explicit(&binary_bytes, memory_order_relaxed) + (uint64_t)length > BINARY_BUDGET) return;
    binary_header h = {BINARY_MAGIC, 0, 0, 0, driver(), recipe};
    void *data = malloc((size_t)length);
    GLsizei got = 0;
    GLenum format = 0;
    if (data) glGetProgramBinary(gl, length, &got, &format, data);
    if (data && got > 0) {
        h.format = format;
        h.length = (uint32_t)got;
        char part[1300];
        snprintf(part, sizeof part, "%s.part", path);
        FILE *f = fopen(part, "wb");
        int ok = f && fwrite(&h, sizeof h, 1, f) == 1 && fwrite(data, 1, (size_t)got, f) == (size_t)got;
        if (f && fclose(f)) ok = 0;
        if (ok && !rename(part, path)) atomic_fetch_add_explicit(&binary_bytes, (uint64_t)got, memory_order_relaxed);
        else remove(part);
    }
    free(data);
}

static GLuint link_recipe(GLuint vs, GLuint ps, uint32_t count, const char *const *names)
{
    GLuint gl = glCreateProgram();
    glAttachShader(gl, vs); glAttachShader(gl, ps);
    for (uint32_t i = 0; i < count; ++i) glBindAttribLocation(gl, i, names[i]);
    glProgramParameteri(gl, GL_PROGRAM_BINARY_RETRIEVABLE_HINT, GL_TRUE);
    glLinkProgram(gl);
    GLint ok = 0;
    glGetProgramiv(gl, GL_LINK_STATUS, &ok);
    if (!ok) {
        char log[2048];
        glGetProgramInfoLog(gl, sizeof log, NULL, log);
        void_log("[d3d9] program link failed: %s", log);
        glDeleteProgram(gl);
        return 0;
    }
    atomic_fetch_add_explicit(&linked_programs, 1, memory_order_relaxed);
    return gl;
}

GLuint d3d_warm_program(GLuint vs, GLuint ps, int count, const char *const *names)
{
    const char *vertex = d3d_shader_source_for(vs), *pixel = d3d_shader_source_for(ps);
    if (count < 0 || count > 16) return 0;
    if (!vertex || !pixel) return link_recipe(vs, ps, (uint32_t)count, names);
    size_t vn = strlen(vertex) + 1, pn = strlen(pixel) + 1;
    if (vn > SOURCE_LIMIT || pn > SOURCE_LIMIT) return link_recipe(vs, ps, (uint32_t)count, names);
    size_t size = sizeof(recipe_header) + vn + pn;
    recipe_header *h = calloc(1, size);
    h->magic = RECIPE_MAGIC; h->vertex_size = (uint32_t)vn; h->pixel_size = (uint32_t)pn; h->count = (uint32_t)count;
    for (int i = 0; i < count; ++i) {
        if (strlen(names[i]) >= sizeof h->names[i]) { free(h); return link_recipe(vs, ps, (uint32_t)count, names); }
        strcpy(h->names[i], names[i]);
    }
    memcpy(h + 1, vertex, vn); memcpy((char *)(h + 1) + vn, pixel, pn);
    uint64_t hash = warm_hash(h, size);
    GLuint gl = 0;
    for (warm_entry *e = warmed; e; e = e->next)
        if (e->gl && e->hash == hash && e->size == size && !memcmp(e->bytes, h, size)) {
            gl = e->gl;
            /* A program's uniform-value cache has one owner. */
            e->gl = 0;
            atomic_fetch_add_explicit(&reused_programs, 1, memory_order_relaxed);
            break;
        }
    if (!gl && (gl = binary_load(hash))) atomic_fetch_add_explicit(&reused_programs, 1, memory_order_relaxed);
    if (!gl && (gl = link_recipe(vs, ps, (uint32_t)count, names))) binary_save(gl, hash);
    if (gl) {
        char dir[1200], path[1280];
        recipe_directory(dir); mkdir(dir, 0775);
        snprintf(path, sizeof path, "%s/%016llx.bin", dir, (unsigned long long)hash);
        FILE *f = fopen(path, "rb");
        int matches = 0;
        if (f) {
            char block[4096]; size_t at = 0, n;
            matches = 1;
            while ((n = fread(block, 1, sizeof block, f)) > 0) {
                if (n > size - at || memcmp(block, (const char *)h + at, n)) { matches = 0; break; }
                at += n;
            }
            matches = matches && !ferror(f) && at == size;
            fclose(f);
        }
        if (!matches) {
            char part[1300]; snprintf(part, sizeof part, "%s.part", path);
            f = fopen(part, "wb");
            if (f) {
                int ok = fwrite(h, 1, size, f) == size;
                if (fclose(f)) ok = 0;
                if (ok) rename(part, path);
                else remove(part);
            }
        }
    }
    free(h);
    return gl;
}

static int warm_bytecode_valid(const void *bytes, size_t size)
{
    uint32_t version, end;
    if (size < 8 || size % 4) return 0;
    memcpy(&version, bytes, 4); memcpy(&end, (const char *)bytes + size - 4, 4);
    uint32_t type = version >> 16, major = (version >> 8) & 255;
    return (type == 0xfffe || type == 0xffff) && major >= 1 && major <= 3 && end == 0xffff;
}

static void scan_directory(const char *path, int recipe)
{
    DIR *dir = opendir(path);
    if (!dir) return;
    struct dirent *de;
    while ((de = readdir(dir))) {
        if (strlen(de->d_name) != 20 || strcmp(de->d_name + 16, ".bin") || strspn(de->d_name, "0123456789abcdef") != 16) continue;
        char file[1280]; snprintf(file, sizeof file, "%s/%s", path, de->d_name);
        FILE *f = fopen(file, "rb");
        if (!f) continue;
        if (fseek(f, 0, SEEK_END)) { fclose(f); continue; }
        long length = ftell(f);
        if (length <= 0 || length > (long)(2 * SOURCE_LIMIT + sizeof(recipe_header)) || fseek(f, 0, SEEK_SET)) { fclose(f); continue; }
        void *bytes = malloc((size_t)length);
        int ok = fread(bytes, 1, (size_t)length, f) == (size_t)length;
        fclose(f);
        if (!ok || !(recipe ? valid_recipe(bytes, (size_t)length) : warm_bytecode_valid(bytes, (size_t)length))) { free(bytes); continue; }
        uint64_t hash = warm_hash(bytes, (size_t)length);
        warm_entry *e = queue;
        while (e && !(e->recipe == recipe && e->hash == hash && e->size == (uint32_t)length && !memcmp(e->bytes, bytes, (size_t)length))) e = e->next;
        if (e) { free(bytes); continue; }
        e = calloc(1, sizeof *e); e->hash = hash; e->size = (uint32_t)length; e->bytes = bytes; e->recipe = recipe;
        e->next = queue; queue = e;
        ++queued;
    }
    closedir(dir);
}

uint64_t d3d_shader_warm_progress(void)
{
    return ((uint64_t)atomic_load_explicit(&warm_total, memory_order_acquire) << 32) |
        atomic_load_explicit(&warm_done, memory_order_relaxed);
}

uint32_t d3d_shader_compile_count(void);
uint32_t void_d3dx_cache_responses(void);

void d3d_shader_warm_stats(void)
{
    void_log("[shaderwork] stages=%u programs=%u reused=%u kept=%u warm=%u/%u unavailable=%u hlsl=%u",
        d3d_shader_compile_count(), atomic_load_explicit(&linked_programs, memory_order_relaxed),
        atomic_load_explicit(&reused_programs, memory_order_relaxed), atomic_load_explicit(&loaded_programs, memory_order_relaxed),
        atomic_load_explicit(&warm_done, memory_order_relaxed),
        atomic_load_explicit(&warm_total, memory_order_relaxed), atomic_load_explicit(&failed, memory_order_relaxed),
        void_d3dx_cache_responses());
}

static void *scan_caches(void *unused)
{
    (void)unused;
    uint64_t began = void_monotonic_ns();
    char path[1200];
    const char *packaged = void_d3dx_packaged_cache_dir();
    if (packaged[0]) scan_directory(packaged, 0);
    snprintf(path, sizeof path, "%s/shadercache", void_data_dir()); scan_directory(path, 0);
    recipe_directory(path); scan_directory(path, 1);
    /* What the program cache holds already counts against its budget. */
    binary_path(0, path);
    char *slash = strrchr(path, '/');
    if (slash) *slash = 0;
    DIR *dir = opendir(path);
    uint64_t bytes = 0;
    struct dirent *de;
    while (dir && (de = readdir(dir))) {
        char file[1280];
        struct stat st;
        snprintf(file, sizeof file, "%s/%s", path, de->d_name);
        if (de->d_name[0] != '.' && !stat(file, &st)) bytes += (uint64_t)st.st_size;
    }
    if (dir) closedir(dir);
    atomic_fetch_add_explicit(&binary_bytes, bytes, memory_order_relaxed);
    void_log("[shaderwarm] caches scanned in %.0f ms: %u stages/programs; programs kept %.1f MB",
        (double)(void_monotonic_ns() - began) / 1e6, queued, (double)bytes / 1048576.0);
    atomic_store_explicit(&scan_finished, 1, memory_order_release);
    return NULL;
}

void d3d_shader_warm_step(void)
{
    if (!scan_started) {
        scan_started = 1;
        if (pthread_create(&scan_thread, NULL, scan_caches, NULL)) scan_caches(NULL);
        else pthread_detach(scan_thread);
    }
    if (!scanned) {
        if (!(void_hud_state(NULL) & HUD_MAINMENU) || !atomic_load_explicit(&scan_finished, memory_order_acquire)) return;
        driver();
        atomic_store_explicit(&warm_total, queued, memory_order_release);
        pending = queue; scanned = 1;
        if (!pending) { atomic_store(&warm_total, 1); atomic_store(&warm_done, 1); }
        void_log("[shaderwarm] main menu: %u stages/programs", atomic_load(&warm_total));
    }
    uint64_t began = void_monotonic_ns();
    for (unsigned batch = 0; pending && batch < 32; ++batch) {
        warm_entry *e = pending; pending = e->next;
        int ok;
        if (!e->recipe) ok = d3d_shader_warm_bytecode(e->bytes, e->size);
        else {
            const recipe_header *h = e->bytes;
            const char *vertex = (const char *)(h + 1), *pixel = vertex + h->vertex_size, *names[16];
            for (uint32_t i = 0; i < h->count; ++i) names[i] = h->names[i];
            /* A program already in the on-disk cache loads without recompiling
             * its GLSL stages — the dominant per-launch cost — so try the cache
             * first and compile only on a miss (first launch or evicted). */
            e->gl = binary_load(e->hash);
            if (!e->gl) {
                GLuint vs = d3d_shader_compile_source(GL_VERTEX_SHADER, vertex), ps = d3d_shader_compile_source(GL_FRAGMENT_SHADER, pixel);
                if (vs && ps && (e->gl = link_recipe(vs, ps, h->count, names))) binary_save(e->gl, e->hash);
            }
            ok = e->gl != 0;
            e->next = warmed; warmed = e;
        }
        if (!ok) { atomic_fetch_add_explicit(&failed, 1, memory_order_relaxed); void_log("[shaderwarm] unavailable %016llx (%s)", (unsigned long long)e->hash, e->recipe ? "program" : "stage"); }
        uint32_t done = atomic_fetch_add_explicit(&warm_done, 1, memory_order_release) + 1;
        if (!e->recipe) { free(e->bytes); free(e); }
        if (!pending) {
            queue = NULL;
            void_log("[shaderwarm] complete %u/%u, %u unavailable", done, atomic_load(&warm_total), atomic_load(&failed));
        }
        if (void_monotonic_ns() - began >= 6000000u) break;
    }
}
