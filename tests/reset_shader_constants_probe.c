/* Real production functions are extracted by prepare.py. GL, COM handles and
 * surface allocation edges are deterministic test adapters, not a GPU oracle. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#define MOJOSHADER_NO_VERSION_INCLUDE
#include "mojoshader.h"

typedef unsigned GLuint;
typedef int GLint;
typedef struct void_com_object { uint32_t guest; int refs; } void_com_object;
typedef struct d3d_device d3d_device;
typedef struct d3d_surface { void_com_object com; uint32_t width, height; } d3d_surface;
typedef struct d3d_shader { void_com_object com; int pixel; const MOJOSHADER_parseData *parse; const char *source; } d3d_shader;
#define D3D_OK 0u
#define D3DERR_INVALIDCALL 0x8876086Cu
#define D3DUSAGE_RENDERTARGET 1u
#define D3DUSAGE_DEPTHSTENCIL 2u
#define D3DPOOL_DEFAULT 0u
#include "types.h"

static uint32_t args[4], g_eax, g_esp;
static uint32_t guest_memory[1024];
static void *objects[8];
static d3d_device *fixture_device;
static unsigned active_program, uniform_calls, draw_calls, relinks, state_dirty, unexpected_uniform;
static uint32_t g_icall_trace_idx, g_icall_from[8];
#define ICALL_TRACE_SIZE 8
#define ARG(n) args[n]
#define THIS_ ARG(0)
#define DEV fixture_device
#define GPTR(n) ((uint8_t *)guest_memory + (n))
#define MEM32(n) (*(uint32_t *)GPTR(n))
#define CHECK(x) do { if (!(x)) { printf("FAIL line %d: %s\n", __LINE__, #x); return 1; } } while (0)

typedef struct gpu_constants { float f[2][8]; int32_t i[2][4], b[2]; } gpu_constants;
static gpu_constants gpu[4];
static ff_prog *prog_cache;
static void *void_com_host(uint32_t handle) { if (handle >= 8) abort(); return objects[handle]; }
static uint32_t void_com_addref(void_com_object *o) { return (uint32_t)++o->refs; }
static uint32_t void_com_release(void_com_object *o) { return (uint32_t)--o->refs; }
static void_com_object *d3d_surface_owner(d3d_surface *s) { return &s->com; }
static void void_window_client_size(uint32_t window, int *w, int *h) { (void)window; *w = 640; *h = 480; }
static void d3d_set_logical_size(uint32_t w, uint32_t h) { if (!w || !h) abort(); }
static void void_input_set_screen_size(int w, int h) { if (w <= 0 || h <= 0) abort(); }
void d3d_gl_invalidate_state(void);
static d3d_surface *d3d_surface_new(d3d_device *d, uint32_t w, uint32_t h, uint32_t format,
                                 uint32_t usage, uint32_t pool, uint32_t multisample) {
    (void)d; (void)format; (void)usage; (void)pool; (void)multisample;
    d3d_surface *s = calloc(1, sizeof *s);
    if (!s) abort();
    s->width = w; s->height = h; s->com.refs = 1; return s;
}
static void void_log(const char *format, ...) { (void)format; }
static void void_fatal(const char *format, ...) { (void)format; abort(); }
static int d3d_trace_active(void) { return 0; }
static void glUseProgram(GLuint id) { if (id < 1 || id > 3) abort(); active_program = id; }
static GLint glGetUniformLocation(GLuint id, const char *name) {
    (void)id;
    int index = 0;
    const char *bracket = strchr(name, '[');
    if (bracket) index = atoi(bracket + 1);
    return (name[0] == 'v' ? 100 : 200) + index * 7;
}
static void glUniform4fv(GLint loc, int count, const float *value) {
    unsigned stage = loc >= 200, index = (unsigned)(loc - (stage ? 200 : 100)) / 7;
    if (active_program > 2 || index + (unsigned)count > 2) abort();
    memcpy(gpu[active_program].f[stage] + index * 4, value, (size_t)count * 16); ++uniform_calls;
}
static void glUniform4iv(GLint loc, int count, const int32_t *value) {
    unsigned stage = loc == 400;
    if (active_program > 2 || count != 1 || (loc != 300 && loc != 400)) abort();
    memcpy(gpu[active_program].i[stage], value, 16); ++uniform_calls;
}
static void glUniform1iv(GLint loc, int count, const int32_t *value) {
    unsigned stage = loc == 600;
    if (active_program > 2 || count != 1 || (loc != 500 && loc != 600)) abort();
    gpu[active_program].b[stage] = value[0]; ++uniform_calls;
}
static void glUniform2f(GLint loc, float x, float y) { (void)loc; (void)x; (void)y; ++unexpected_uniform; }
static void glUniform1i(GLint loc, int value) { (void)loc; (void)value; ++unexpected_uniform; }
static void glUniform1f(GLint loc, float value) { (void)loc; (void)value; ++unexpected_uniform; }
static void shader_draw_result(d3d_shader *vs, d3d_shader *ps, int failed) { (void)vs; (void)ps; if (failed) abort(); }
static program_t *link_program(d3d_shader *vs, d3d_shader *ps, uint32_t mask, GLuint ff, uint32_t id, uint32_t samplers) {
    (void)vs; (void)ps; (void)mask; (void)ff; (void)id; (void)samplers; ++relinks; return NULL;
}
static GLuint d3d_ff_vertex_stage(d3d_device *d, const char *s, uint32_t *id) { (void)d; (void)s; (void)id; abort(); }
static GLuint d3d_ff_pixel_stage(d3d_device *d, const char *s, uint32_t *id, uint32_t *mask) {
    (void)d; (void)s; (void)id; (void)mask; abort();
}
static void d3d_ff_uniforms(d3d_device *d, GLuint gl, int vs, int ps) { (void)d; (void)gl; (void)vs; (void)ps; abort(); }
static void pixel_key(d3d_device *d, ff_fkey *k, uint32_t available, int shader) {
    (void)d; (void)available; (void)shader; memset(k, 0, sizeof *k);
}
static int vertex_key(d3d_device *d, ff_vkey *k, const uint32_t *outputs, uint32_t count) {
    (void)d; (void)outputs; (void)count; memset(k, 0, sizeof *k); return 1;
}
static ff_vs *vertex_half(const ff_vkey *k) { static ff_vs v; (void)k; v.id = 1; v.gl = 11; return &v; }
static ff_fs *pixel_half(const ff_fkey *k) { static ff_fs f; (void)k; f.id = 2; f.gl = 12; return &f; }
static GLuint d3d_warm_program(GLuint vs, GLuint ps, int count, const char *const *names) {
    if (vs != 11 || ps != 12 || count || names) abort(); return 3;
}
static const ff_locs *locations(GLuint gl) { static ff_locs l; if (gl != 3) abort(); return &l; }
static void vertex_uniforms(d3d_device *d, const ff_locs *l) { (void)d; (void)l; }
static void pixel_uniforms(d3d_device *d, const ff_locs *l, int alpha) { (void)d; (void)l; (void)alpha; }

#include TEST_SOURCE

static int no_bgra(d3d_device *d, int usage, int index) { (void)d; (void)usage; (void)index; return 0; }
static int draw(d3d_device *d) {
    int count, usage[16], index[16];
    uint32_t ps_samplers, vs_samplers;
    if (!d->st.vs && !d->st.ps) {
        CHECK(d3d_ff_bind(d, &count, usage, index, &ps_samplers));
        CHECK(!current_program && active_program == 3);
    } else {
        const int *au, *ai, *pt, *vt;
        CHECK(d3d_shader_bind2(d, d->st.vs, d->st.ps, no_bgra, &count, &au, &ai,
                             &ps_samplers, &vs_samplers, &pt, &vt));
        d3d_shader_upload(d, 0.0f, 0.0f, 8, 0.0f);
    }
    ++draw_calls;
    return 0;
}
static void bind_pair(unsigned pair) {
    args[0] = 1; args[1] = pair ? 4 : 2; dev_SetVertexShader();
    args[0] = 1; args[1] = pair ? 5 : 3; dev_SetPixelShader();
}
static void program_fixture(program_t *p, d3d_shader *vs, d3d_shader *ps, GLuint gl) {
    memset(p, 0, sizeof *p);
    p->vs = vs; p->ps = ps; p->gl = gl;
    p->loc_vs_f = 100; p->loc_ps_f = 200; p->loc_vs_i = 300; p->loc_ps_i = 400; p->loc_vs_b = 500; p->loc_ps_b = 600;
    p->loc_half = p->loc_alpha_func = -1;
    p->vs_map_count = p->ps_map_count = 3;
    p->vs_map[0] = p->ps_map[0] = (umap_t){MOJOSHADER_UNIFORM_FLOAT, 0, 2};
    p->vs_map[1] = p->ps_map[1] = (umap_t){MOJOSHADER_UNIFORM_INT, 1, 1};
    p->vs_map[2] = p->ps_map[2] = (umap_t){MOJOSHADER_UNIFORM_BOOL, 2, 1};
    p->vs_f_count = p->ps_f_count = 2; p->vs_i_count = p->ps_i_count = p->vs_b_count = p->ps_b_count = 1;
    p->vs_f = calloc(8, sizeof(float)); p->ps_f = calloc(8, sizeof(float));
    p->vs_i = calloc(4, sizeof(int32_t)); p->ps_i = calloc(4, sizeof(int32_t));
    p->vs_b = calloc(1, sizeof(int32_t)); p->ps_b = calloc(1, sizeof(int32_t));
    p->vs_f_loc = malloc(3 * sizeof(GLint)); p->ps_f_loc = malloc(3 * sizeof(GLint));
    for (int i = 0; i < 3; ++i) p->vs_f_loc[i] = p->ps_f_loc[i] = -2;
    uintptr_t h = ((uintptr_t)vs * 31u + (uintptr_t)ps * 17u) % 1024u;
    p->next = programs[h]; programs[h] = p;
}
static int zero(const void *data, size_t length) {
    const uint8_t *bytes = data;
    for (size_t i = 0; i < length; ++i) if (bytes[i]) return 0;
    return 1;
}
static int run_case(int mode) {
    static MOJOSHADER_parseData pd;
    d3d_device d = {0};
    d3d_shader shaders[4] = {0};
    program_t p[2];
    fixture_device = &d;
    memset(programs, 0, sizeof programs); current_program = NULL;
    memset(gpu, 0, sizeof gpu); uniform_calls = draw_calls = relinks = state_dirty = unexpected_uniform = 0;
    d3d_constant_generation = 0x123400u + (uint32_t)mode * 100;
    d.pp[0] = 640; d.pp[1] = 480; d.pp[2] = 22;
    make_backbuffer(&d); default_state(&d, &d.st); set_default_viewport(&d, d.backbuffer);
    objects[1] = &d;
    for (int i = 0; i < 4; ++i) { shaders[i].pixel = i & 1; shaders[i].parse = &pd; objects[i + 2] = &shaders[i]; }
    program_fixture(&p[0], &shaders[0], &shaders[1], 1);
    program_fixture(&p[1], &shaders[2], &shaders[3], 2);
    const float values[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    const int32_t integers[4] = {9, 10, 11, 12};
    memcpy(GPTR(0x100), values, sizeof values); memcpy(GPTR(0x140), integers, sizeof integers); MEM32(0x160) = 7;
    void (*setters[])(void) = {dev_SetVertexShaderConstantF, dev_SetPixelShaderConstantF,
                              dev_SetVertexShaderConstantI, dev_SetPixelShaderConstantI,
                              dev_SetVertexShaderConstantB, dev_SetPixelShaderConstantB};
    for (int i = 0; i < 6; ++i) {
        args[0] = 1; args[1] = i < 2 ? 0 : i < 4 ? 1 : 2;
        args[2] = i < 2 ? 0x100 : i < 4 ? 0x140 : 0x160; args[3] = i < 2 ? 2 : 1; setters[i]();
    }
    bind_pair(0); CHECK(!draw(&d)); CHECK(uniform_calls == 6 && !zero(&gpu[1], sizeof gpu[1]));
    bind_pair(1); CHECK(!draw(&d)); CHECK(uniform_calls == 12 && !zero(&gpu[2], sizeof gpu[2]));
    bind_pair(0); CHECK(!draw(&d)); CHECK(uniform_calls == 12); /* Warm rebind must remain cached. */
    if (mode == 1) {
        args[0] = 1; args[1] = 0; dev_SetVertexShader(); dev_SetPixelShader();
        CHECK(!draw(&d)); bind_pair(0); CHECK(!draw(&d)); CHECK(uniform_calls == 12);
    }
    int failures = 0;
    for (int round = 0; round < 2; ++round) {
        memcpy(GPTR(0x300), d.pp, sizeof d.pp);
        args[0] = 1; args[1] = 0x300; g_esp = 0x800; dev_Reset();
        CHECK(g_eax == D3D_OK && g_esp == 0x80c && state_dirty);
        CHECK(!d.st.vs && !d.st.ps);
        CHECK(zero(d.st.vs_f, sizeof d.st.vs_f) && zero(d.st.ps_f, sizeof d.st.ps_f));
        CHECK(zero(d.st.vs_i, sizeof d.st.vs_i) && zero(d.st.ps_i, sizeof d.st.ps_i));
        CHECK(zero(d.st.vs_b, sizeof d.st.vs_b) && zero(d.st.ps_b, sizeof d.st.ps_b));
        if (mode == 1) CHECK(!draw(&d)); /* Actual FF bind forgets only the current program. */
        for (unsigned pair = 0; pair < (mode == 2 ? 2u : 1u); ++pair) {
            bind_pair(pair); CHECK(!draw(&d)); CHECK(current_program == &p[pair] && !relinks);
            if (!zero(&gpu[pair + 1], sizeof gpu[pair + 1])) {
                printf("FAIL mode=%d reset=%d program=%u: guest constants zero, GL still nonzero (generation=%u uploaded=%u)\n",
                       mode, round, pair + 1, d3d_constant_generation, p[pair].uploaded_generation);
                ++failures;
            }
        }
    }
    printf("mode=%d %s: direct/FF/switch cached programs; two Resets; six constant types; no-change control\n",
           mode, failures ? "FAIL" : "PASS");
    CHECK(!unexpected_uniform);
    return failures;
}
int main(void) {
    int failures = run_case(0) + run_case(1) + run_case(2);
    printf("%s: %d stale-uniform failures across direct, actual FF and two-program Reset paths\n",
           failures ? "FAIL" : "PASS", failures);
    return failures ? 1 : 0;
}
