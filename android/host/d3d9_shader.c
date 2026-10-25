/* D3D9 shaders through MojoShader (zlib, revision
 * cf2661bcb55d9a8732e86f79922592d7efdf5383, unmodified; built with
 * MOJOSHADER_FLIP_RENDERTARGET and MOJOSHADER_DEPTH_CLIPPING).
 *
 * The generated GLSL ES 3.00 is post-processed here:
 *   - vertex: D3D9's half-pixel rasterization offset (vpHalfPixel), applied
 *     after MojoShader's render-target flip;
 *   - pixel: the fixed-function alpha test (GLES has none) as a uniform test
 *     before every return from main.
 * D3DCOLOR inputs are swizzled by MojoShader itself (MOJOSHADER_swizzle), so a
 * vertex shader is compiled per BGRA-input mask. */
#include "d3d9_internal.h"
#include "hud.h"
#include "shader_warm.h"
#include <ctype.h>
#include <stdatomic.h>
#include <sys/stat.h>

static _Atomic uint32_t compiled_shaders;
uint32_t d3d_shader_compile_count(void) { return atomic_load_explicit(&compiled_shaders, memory_order_relaxed); }
void void_d3dx_shader_failure(uint64_t key, int failed);

uint32_t d3d_shader_bytecode_size(uint32_t va)
{
    uint32_t p = va + 4;                       /* skip the version token */
    for (uint32_t guard = 0; guard < 1u << 20; ++guard) {
        uint32_t token = MEM32(p);
        if (token == 0x0000FFFFu) return p + 4 - va;
        if ((token & 0xFFFF) == 0xFFFE) { p += 4 + 4 * ((token >> 16) & 0x7FFF); continue; }
        uint32_t opcode = token & 0xFFFF;
        uint32_t len = (token >> 24) & 0x0F;
        if (opcode == 0x0051 && !len) len = 5;  /* def in ps_1_x shaders without length */
        p += 4 + 4 * len;
    }
    return 0;
}

static void_com_class shader_class_vs, shader_class_ps;
static void forget_programs(const d3d_shader *s);

static void shader_destroy(void_com_object *o)
{
    d3d_shader *s = (d3d_shader *)o;
    forget_programs(s);
    if (s->parse) MOJOSHADER_freeParseData(s->parse);
    free(s->bytecode);
    free(s->parse_code);
    free(s->source);
    free(s);
}

/* Insert `text` before the first occurrence of `anchor` (or append). */
static char *insert_before(const char *src, const char *anchor, const char *text)
{
    const char *at = strstr(src, anchor);
    size_t head = at ? (size_t)(at - src) : strlen(src), len = strlen(src), n = strlen(text);
    char *out = (char *)malloc(len + n + 1);
    memcpy(out, src, head);
    memcpy(out + head, text, n);
    strcpy(out + head + n, src + head);
    return out;
}

/* MojoShader's GLSL ES for ps_1_x reads texture coordinates through globals
 * initialized from io_ varyings it never declares (`vec4 ps_t0 = io_5_0;`),
 * and GLSL ES wants constant global initializers. Declare every io_ varying
 * the source uses and move such initializers to the start of main. */
static char *fix_pixel_varyings(const char *src)
{
    char decls[2048] = "", moved[2048] = "";
    size_t dn = 0, mn = 0;
    for (const char *p = strstr(src, "io_"); p; p = strstr(p + 3, "io_")) {
        if (p > src && (isalnum((unsigned char)p[-1]) || p[-1] == '_')) continue;
        unsigned u, i;
        if (sscanf(p, "io_%u_%u", &u, &i) != 2) continue;
        char decl[48];
        snprintf(decl, sizeof decl, "in highp vec4 io_%u_%u;", u, i);
        if (strstr(src, decl) || strstr(decls, decl)) continue;
        dn += (size_t)snprintf(decls + dn, sizeof decls - dn, "%s\n", decl);
    }
    size_t len = strlen(src);
    char *body = (char *)malloc(len + 1), *w = body;
    for (const char *line = src; *line;) {
        const char *end = strchr(line, '\n');
        size_t n = end ? (size_t)(end - line + 1) : strlen(line);
        char name[32];
        unsigned u, i;
        if (!strncmp(line, "vec4 ps_", 8) && sscanf(line, "vec4 %31[a-z_0-9] = io_%u_%u;", name, &u, &i) == 3) {
            w += sprintf(w, "vec4 %s;\n", name);
            mn += (size_t)snprintf(moved + mn, sizeof moved - mn, "\t%s = io_%u_%u;\n", name, u, i);
        } else {
            memcpy(w, line, n);
            w += n;
        }
        line += n;
    }
    *w = 0;
    if (!dn && !mn) return body;
    char *with_decls = insert_before(body, "void main()", decls);
    free(body);
    if (!mn) return with_decls;
    const char *mainp = strstr(with_decls, "void main()");
    const char *brace = mainp ? strchr(mainp, '{') : NULL;
    if (!brace) return with_decls;
    size_t at = (size_t)(brace + 1 - with_decls);
    char *out = (char *)malloc(strlen(with_decls) + mn + 2);
    memcpy(out, with_decls, at);
    out[at] = '\n';
    memcpy(out + at + 1, moved, mn);
    strcpy(out + at + 1 + mn, with_decls + at);
    free(with_decls);
    return out;
}

static char *patch_shader(const char *src, int pixel);

/* vs_1_x writes the address register with mov, which MojoShader emits as a
 * plain float-to-int assignment (`vs_a0.x = vs_r0.x;`) that GLSL rejects.
 * D3D floors the value there (Wine does the same); mova keeps its own
 * rounding and is already an int expression. */
static char *fix_address_moves(const char *src)
{
    size_t len = strlen(src);
    char *out = (char *)malloc(len * 2 + 64), *w = out;
    for (const char *line = src; *line;) {
        const char *end = strchr(line, '\n');
        size_t n = end ? (size_t)(end - line + 1) : strlen(line);
        const char *p = line;
        while (*p == '\t' || *p == ' ') ++p;
        char mask[8];
        int prefix = 0;
        if (sscanf(p, "vs_a0.%7[xyzw] = %n", mask, &prefix) == 1 && prefix > 0 &&
            strncmp(p + prefix, "int(", 4) && strncmp(p + prefix, "ivec", 4)) {
            const char *expr = p + prefix, *semi = strchr(expr, ';');
            if (semi && semi < line + n) {
                size_t comps = strlen(mask);
                w += sprintf(w, "%.*s", (int)(p - line), line);
                if (comps == 1) w += sprintf(w, "vs_a0.%s = int(floor(%.*s));\n", mask, (int)(semi - expr), expr);
                else w += sprintf(w, "vs_a0.%s = ivec%zu(floor(%.*s));\n", mask, comps, (int)(semi - expr), expr);
                line += n;
                continue;
            }
        }
        memcpy(w, line, n);
        w += n;
        line += n;
    }
    *w = 0;
    return out;
}

static char *patch_source(const char *original, int pixel)
{
    if (!pixel) {
        char *fixed = fix_address_moves(original);
        char *out = patch_shader(fixed, 0);
        free(fixed);
        return out;
    }
    char *fixed = fix_pixel_varyings(original);
    char *out = patch_shader(fixed, 1);
    free(fixed);
    return out;
}

static char *patch_shader(const char *src, int pixel)
{
    size_t len = strlen(src);
    char *out = (char *)malloc(len * 2 + 2048);
    char *w = out;
    if (!pixel) {
        const char *decl = strstr(src, "uniform float vpFlip;");
        const char *flip = strstr(src, "gl_Position.y = gl_Position.y * vpFlip;");
        if (!decl || !flip) { strcpy(out, src); return out; }
        size_t a = (size_t)(decl - src) + strlen("uniform float vpFlip;");
        memcpy(w, src, a); w += a;
        w += sprintf(w, "\nuniform vec2 vpHalfPixel;");
        size_t b = (size_t)(flip - src) + strlen("gl_Position.y = gl_Position.y * vpFlip;");
        memcpy(w, src + a, b - a); w += b - a;
        w += sprintf(w, "\n\tgl_Position.xy += vpHalfPixel * gl_Position.w;");
        strcpy(w, src + b);
        return out;
    }
    /* Pixel: find colour output 0 and main's body. */
    const char *mainp = strstr(src, "void main()");
    const char *out0 = strstr(src, "ps_oC0");
    if (!mainp || !out0) { strcpy(out, src); return out; }
    size_t head = (size_t)(mainp - src);
    memcpy(w, src, head); w += head;
    w += sprintf(w,
        "uniform int vpAlphaFunc;\nuniform float vpAlphaRef;\n"
        "void void_alpha_test() {\n"
        "\tfloat a = floor(clamp(ps_oC0.a, 0.0, 1.0) * 255.0 + 0.5);\n"
        "\tbool pass = true;\n"
        "\tif (vpAlphaFunc == 1) pass = false;\n"
        "\telse if (vpAlphaFunc == 2) pass = a < vpAlphaRef;\n"
        "\telse if (vpAlphaFunc == 3) pass = a == vpAlphaRef;\n"
        "\telse if (vpAlphaFunc == 4) pass = a <= vpAlphaRef;\n"
        "\telse if (vpAlphaFunc == 5) pass = a > vpAlphaRef;\n"
        "\telse if (vpAlphaFunc == 6) pass = a != vpAlphaRef;\n"
        "\telse if (vpAlphaFunc == 7) pass = a >= vpAlphaRef;\n"
        "\tif (!pass) discard;\n}\n");
    /* Copy main, rewriting each `return;` at any depth inside it. */
    const char *p = mainp;
    const char *brace = strchr(p, '{');
    if (!brace) { strcpy(w, p); return out; }
    memcpy(w, p, (size_t)(brace - p + 1)); w += brace - p + 1;
    int depth = 1;
    p = brace + 1;
    while (*p && depth > 0) {
        if (*p == '{') ++depth;
        else if (*p == '}') { if (--depth == 0) break; }
        if (!strncmp(p, "return;", 7) && (p == src || !isalnum((unsigned char)p[-1]))) {
            w += sprintf(w, "{ void_alpha_test(); return; }");
            p += 7;
            continue;
        }
        *w++ = *p++;
    }
    /* A main without a trailing return still needs the test. */
    w += sprintf(w, "\tvoid_alpha_test();\n");
    strcpy(w, p);
    return out;
}

/* Whether ps_<t|v>M names a TEXCOORD input in this GLSL (MojoShader:
 * "#define ps_v0 io_5_0", or ps_1_x's "ps_t0 = io_5_0;" at main's start). */
static int texcoord_input(const char *src, char kind, unsigned m)
{
    char a[40], b[40];
    snprintf(a, sizeof a, "#define ps_%c%u io_5_", kind, m);
    snprintf(b, sizeof b, "ps_%c%u = io_5_", kind, m);
    return strstr(src, a) || strstr(src, b);
}

/* The samplers a pixel shader reads only at an interpolated texture
 * coordinate as the vertices gave it: every texture2D(ps_sN, ps_tM.xy) or
 * ps_vM.xy of a TEXCOORD input. A sampler also read at a computed
 * coordinate (bump offsets, scaled or scrolled ones) is left out. Where the
 * host enlarges 2D drawing, such a picture keeps its own edge texels
 * (d3d9_gl.c, keep_edges). */
static uint32_t find_direct_samplers(const char *src)
{
    uint32_t direct = 0, other = 0;
    for (const char *p = strstr(src, "texture"); p; p = strstr(p + 7, "texture")) {
        if (p > src && (isalnum((unsigned char)p[-1]) || p[-1] == '_')) continue;
        const char *q = p + 7;
        while (isalnum((unsigned char)*q) || *q == '_') ++q;
        size_t name = (size_t)(q - p);
        while (*q == ' ') ++q;
        if (*q != '(') continue;
        unsigned n, m;
        int used = 0;
        if (sscanf(q + 1, " ps_s%u ,%n", &n, &used) != 1 || !used || n >= 16) continue;
        const char *arg = q + 1 + used;
        while (*arg == ' ') ++arg;
        char kind = 0;
        int after = 0;
        int simple = name == 9 && !strncmp(p, "texture2D", 9) &&
            sscanf(arg, "ps_%c%u.xy%n", &kind, &m, &after) == 2 && after && (kind == 't' || kind == 'v');
        if (simple) {
            const char *end = arg + after;
            while (*end == ' ') ++end;
            simple = *end == ')' && texcoord_input(src, kind, m);
        }
        if (simple) direct |= 1u << n; else other |= 1u << n;
    }
    return direct & ~other;
}

/* Shaders stored without a constant table cannot use relative constant
 * addressing in MojoShader (it sizes the uniform array from the CTAB). Give
 * such bytecode a synthetic CTAB declaring one float4 array over every
 * register the stage has; the instructions are untouched. */
static uint8_t *with_synthetic_ctab(const uint8_t *code, uint32_t size, int pixel, uint32_t *out_size)
{
    uint32_t regs = pixel ? 224 : 256;
    uint8_t blob[128];
    memset(blob, 0, sizeof blob);
    uint32_t *w = (uint32_t *)blob;
    const char *target = pixel ? "ps_3_0" : "vs_3_0";
    /* D3DXSHADER_CONSTANTTABLE */
    w[0] = 28; w[1] = 80; w[2] = *(const uint32_t *)code; w[3] = 1; w[4] = 28; w[5] = 0; w[6] = 96;
    /* D3DXSHADER_CONSTANTINFO at 28: Name, RegisterSet|Index, Count|Reserved, TypeInfo, DefaultValue */
    w[7] = 72; w[8] = 2u | (0u << 16); w[9] = regs; w[10] = 48; w[11] = 0;
    /* D3DXSHADER_TYPEINFO at 48: Class|Type, Rows|Columns, Elements|StructMembers, StructMemberInfo */
    w[12] = 1u | (3u << 16); w[13] = 1u | (4u << 16); w[14] = regs; w[15] = 0;
    memcpy(blob + 72, "void_c", 7);
    memcpy(blob + 80, "void host", 10);
    memcpy(blob + 96, target, 7);
    uint32_t data_dwords = 104 / 4;
    uint32_t comment_dwords = 1 + data_dwords;              /* 'CTAB' + data */
    *out_size = size + 4 * (1 + comment_dwords);
    uint8_t *out = (uint8_t *)malloc(*out_size);
    memcpy(out, code, 4);                                    /* version token */
    uint32_t token = 0xFFFEu | (comment_dwords << 16), fourcc = FOURCC('C','T','A','B');
    memcpy(out + 4, &token, 4);
    memcpy(out + 8, &fourcc, 4);
    memcpy(out + 12, blob, 104);
    memcpy(out + 12 + 104, code + 4, size - 4);
    return out;
}

d3d_shader *d3d_shader_create(d3d_device *dev, int pixel, uint32_t bytecode)
{
    uint32_t size = d3d_shader_bytecode_size(bytecode);
    if (!size) { void_log("[d3d9] shader bytecode without end token"); return NULL; }
    d3d_shader *s = (d3d_shader *)calloc(1, sizeof *s);
    s->dev = dev;
    s->pixel = pixel;
    s->size = size;
    s->bytecode = (uint8_t *)malloc(size);
    memcpy(s->bytecode, GPTR(bytecode), size);
    if (pixel) s->hud_tag = void_hud_shader_tag_for(s->bytecode, size);
    s->parse = MOJOSHADER_parse(MOJOSHADER_PROFILE_GLSLES3, "main", s->bytecode, size, NULL, 0, NULL, 0, NULL, NULL, NULL);
    if (s->parse && s->parse->error_count && strstr(s->parse->errors[0].error, "without a CTAB")) {
        MOJOSHADER_freeParseData(s->parse);
        uint32_t patched_size;
        uint8_t *patched = with_synthetic_ctab(s->bytecode, size, pixel, &patched_size);
        s->parse = MOJOSHADER_parse(MOJOSHADER_PROFILE_GLSLES3, "main", patched, patched_size, NULL, 0, NULL, 0, NULL, NULL, NULL);
        s->parse_code = patched;
        s->parse_size = patched_size;
        VLOG("[d3d9] %s shader given a synthetic CTAB for relative addressing", pixel ? "pixel" : "vertex");
    }
    if (!s->parse || s->parse->error_count) {
        const uint32_t *w = (const uint32_t *)s->bytecode;
        uint32_t k = (g_icall_trace_idx - 1) & (ICALL_TRACE_SIZE - 1);   /* this COM call */
        /* RendererD3D's shader database loader (16255330) keeps its key at [ebp + 0xC]. */
        uint32_t key = MEM32(g_ebp + 0xC);
        if (void_vm_readable(key, 16))
            void_log("[d3d9] caller frame key %08X: %08X %08X %08X %08X", key, MEM32(key), MEM32(key + 4), MEM32(key + 8), MEM32(key + 12));
        else
            void_log("[d3d9] caller frame key value %08X", key);
        void_log("[d3d9] MojoShader failed on %s shader at %08X (caller %08X, %u bytes: %08X %08X %08X %08X): %s",
            pixel ? "pixel" : "vertex", bytecode, g_icall_from[k], size, w[0], size > 4 ? w[1] : 0, size > 8 ? w[2] : 0,
            size > 12 ? w[3] : 0, s->parse && s->parse->error_count ? s->parse->errors[0].error : "no parse data");
        if (s->parse) MOJOSHADER_freeParseData(s->parse);
        free(s->bytecode);
        free(s);
        return NULL;
    }
    /* Diagnostics: inputs that collapse onto one varying name. */
    for (int i = 0; i < s->parse->attribute_count; ++i)
        for (int j = i + 1; j < s->parse->attribute_count; ++j)
            if (s->parse->attributes[i].usage == s->parse->attributes[j].usage &&
                s->parse->attributes[i].index == s->parse->attributes[j].index) {
                static int dumped;
                if (dumped++ < 4) {
                    char path[1100];
                    snprintf(path, sizeof path, "%s/shaderdump", void_data_dir());
                    mkdir(path, 0775);
                    snprintf(path, sizeof path, "%s/shaderdump/%s_%08X.bin", void_data_dir(), pixel ? "ps" : "vs", bytecode);
                    FILE *f = fopen(path, "wb");
                    if (f) { fwrite(s->bytecode, 1, size, f); fclose(f); }
                    uint32_t k = (g_icall_trace_idx - 1) & (ICALL_TRACE_SIZE - 1);
                    void_log("[d3d9] %s shader at %08X (caller %08X) has inputs sharing usage %d index %d: dumped to %s",
                        pixel ? "pixel" : "vertex", bytecode, g_icall_from[k], s->parse->attributes[i].usage,
                        s->parse->attributes[i].index, path);
                }
                i = j = s->parse->attribute_count;
            }
    s->source = patch_source(s->parse->output, pixel);
    if (pixel) s->direct_samplers = find_direct_samplers(s->source);
    return s;
}

static int shader_type_ok(const d3d_shader *s, int pixel) { return s && s->pixel == pixel; }

COM_METHOD(shd, QueryInterface, 3)
{
    d3d_shader *s = (d3d_shader *)void_com_host(THIS_);
    if (void_guid_equal(ARG(1), s->pixel ? IID_IDirect3DPixelShader9 : IID_IDirect3DVertexShader9) ||
        void_guid_equal(ARG(1), IID_IUnknown)) {
        void_com_addref(&s->com); MEM32(ARG(2)) = THIS_; return 0;
    }
    MEM32(ARG(2)) = 0;
    return E_NOINTERFACE_;
}
COM_METHOD(shd, AddRef, 1) { return void_com_addref((void_com_object *)void_com_host(THIS_)); }
COM_METHOD(shd, Release, 1) { return void_com_release((void_com_object *)void_com_host(THIS_)); }
COM_METHOD(shd, GetDevice, 2)
{
    d3d_shader *s = (d3d_shader *)void_com_host(THIS_);
    void_com_addref(&s->dev->com);
    MEM32(ARG(1)) = s->dev->com.guest;
    return D3D_OK;
}
COM_METHOD(shd, GetFunction, 3)
{
    d3d_shader *s = (d3d_shader *)void_com_host(THIS_);
    if (ARG(1)) memcpy(GPTR(ARG(1)), s->bytecode, s->size);
    MEM32(ARG(2)) = s->size;
    return D3D_OK;
}
static const void_fn shader_methods[] = { shd_QueryInterface, shd_AddRef, shd_Release, shd_GetDevice, shd_GetFunction };
static void_com_class shader_class_vs = { "IDirect3DVertexShader9", 5, shader_methods, 0 };
static void_com_class shader_class_ps = { "IDirect3DPixelShader9", 5, shader_methods, 0 };

uint32_t d3d_wrap_shader(d3d_shader *s)
{
    uint32_t guest = void_com_wrap(&s->com, s->pixel ? &shader_class_ps : &shader_class_vs, 0);
    s->com.destroy = shader_destroy;
    return guest;
}

/* ------------------------------------------------------------- programs */
typedef struct { int type, index, count; } umap_t;

typedef struct program {
    d3d_shader *vs, *ps;          /* either may be NULL: a generated fixed-function half stands in */
    uint32_t bgra_mask;
    uint32_t ff_id;               /* the generated half (d3d9_ff.c), 0 for none */
    GLuint gl, vs_gl, ps_gl;
    GLint loc_vs_f, loc_vs_i, loc_vs_b, loc_ps_f, loc_ps_i, loc_ps_b;
    GLint loc_flip, loc_half, loc_alpha_func, loc_alpha_ref;
    umap_t vs_map[256], ps_map[256];
    int vs_map_count, ps_map_count;
    int vs_f_count, vs_i_count, vs_b_count, ps_f_count, ps_i_count, ps_b_count;
    float *vs_f, *ps_f;           /* what the GL program holds (GL starts uniforms at zero, as calloc does) */
    int32_t *vs_i, *ps_i, *vs_b, *ps_b;
    GLint *vs_f_loc, *ps_f_loc;   /* element locations, queried on first use (-2: not yet) */
    int attr_count;
    int attr_usage[16], attr_index[16];
    uint32_t vs_sampler_mask, ps_sampler_mask;
    int ps_sampler_type[16], vs_sampler_type[4];
    float last_half[2];
    int last_alpha_func;
    float last_alpha_ref;
    uint32_t uploaded_generation;
    struct program *next;
} program_t;

static program_t *programs[1024];
static program_t *current_program;
static d3d_shader *failed_vs, *failed_ps;
static uint64_t failed_program;
uint32_t d3d_constant_generation = 1;

static void shader_draw_result(d3d_shader *vs, d3d_shader *ps, int failed)
{
    if (!failed) {
        if (failed_program && vs == failed_vs && ps == failed_ps) {
            void_d3dx_shader_failure(failed_program, 0);
            failed_program = 0;
        }
        return;
    }
    uint64_t key = UINT64_C(0xcbf29ce484222325);
    const d3d_shader *stages[] = {vs, ps};
    for (unsigned stage = 0; stage < 2; ++stage) {
        key = (key ^ stage) * UINT64_C(0x100000001b3);
        const d3d_shader *shader = stages[stage];
        for (uint32_t i = 0; shader && i < shader->size; ++i)
            key = (key ^ shader->bytecode[i]) * UINT64_C(0x100000001b3);
    }
    failed_vs = vs; failed_ps = ps; failed_program = key;
    void_d3dx_shader_failure(key, 1);
}

/* Programs are found by their shaders' addresses: a released shader's must
 * go with it, or a shader created later at the same address (the game
 * reloads its post-processing shaders around the body screen) would draw
 * with the old one's program, samplers and constant map. */
static void forget_programs(const d3d_shader *s)
{
    for (unsigned h = 0; h < 1024; ++h)
        for (program_t **link = &programs[h]; *link;) {
            program_t *p = *link;
            if (p->vs != s && p->ps != s) { link = &p->next; continue; }
            *link = p->next;
            if (current_program == p) current_program = NULL;
            d3d_ff_forget_program(p->gl);
            glDeleteProgram(p->gl);
            free(p->vs_f); free(p->ps_f); free(p->vs_i); free(p->ps_i); free(p->vs_b); free(p->ps_b);
            free(p->vs_f_loc); free(p->ps_f_loc);
            free(p);
        }
    if (failed_vs == s || failed_ps == s) { failed_vs = failed_ps = NULL; failed_program = 0; }
}

typedef struct compiled_stage {
    GLenum type;
    GLuint gl;
    uint64_t hash;
    char *source;
    struct compiled_stage *next;
} compiled_stage;
static compiled_stage *stages[1024];

GLuint d3d_shader_compile_source(GLenum type, const char *source)
{
    uint64_t hash = type;
    for (const unsigned char *p = (const unsigned char *)source; *p; ++p)
        hash = (hash ^ *p) * UINT64_C(0x100000001b3);
    unsigned bucket = hash % 1024;
    for (compiled_stage *p = stages[bucket]; p; p = p->next)
        if (p->hash == hash && p->type == type && !strcmp(p->source, source)) return p->gl;
    GLuint sh = glCreateShader(type);
    glShaderSource(sh, 1, &source, NULL);
    glCompileShader(sh);
    GLint ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[2048];
        glGetShaderInfoLog(sh, sizeof log, NULL, log);
        void_log("[d3d9] GLSL compile failed: %s", log);
        void_log("[d3d9] source:\n%s", source);
        glDeleteShader(sh);
        return 0;
    }
    atomic_fetch_add_explicit(&compiled_shaders, 1, memory_order_relaxed);
    compiled_stage *entry = calloc(1, sizeof *entry);
    entry->type = type; entry->gl = sh; entry->hash = hash; entry->source = strdup(source);
    entry->next = stages[bucket]; stages[bucket] = entry;
    return sh;
}

const char *d3d_shader_source_for(GLuint shader)
{
    for (unsigned i = 0; i < 1024; ++i)
        for (compiled_stage *p = stages[i]; p; p = p->next)
            if (p->gl == shader) return p->source;
    return NULL;
}

#define compile d3d_shader_compile_source

int d3d_shader_warm_bytecode(const void *bytes, uint32_t size)
{
    uint32_t version = 0;
    memcpy(&version, bytes, 4);
    int pixel = (version >> 16) == 0xffff;
    const MOJOSHADER_parseData *pd = MOJOSHADER_parse(MOJOSHADER_PROFILE_GLSLES3, "main", bytes, size,
        NULL, 0, NULL, 0, NULL, NULL, NULL);
    uint8_t *patched = NULL;
    if (pd && pd->error_count && strstr(pd->errors[0].error, "without a CTAB")) {
        MOJOSHADER_freeParseData(pd);
        uint32_t patched_size = 0;
        patched = with_synthetic_ctab(bytes, size, pixel, &patched_size);
        pd = MOJOSHADER_parse(MOJOSHADER_PROFILE_GLSLES3, "main", patched, patched_size,
            NULL, 0, NULL, 0, NULL, NULL, NULL);
    }
    GLuint gl = 0;
    if (pd && !pd->error_count) {
        char *source = patch_source(pd->output, pixel);
        gl = compile(pixel ? GL_FRAGMENT_SHADER : GL_VERTEX_SHADER, source);
        free(source);
    } else void_log("[shaderwarm] bytecode translation failed: %s", pd && pd->error_count ? pd->errors[0].error : "no parse data");
    if (pd) MOJOSHADER_freeParseData(pd);
    free(patched);
    return gl != 0;
}

static void build_map(const MOJOSHADER_parseData *pd, umap_t *map, int *map_count, int *fc, int *ic, int *bc)
{
    *map_count = *fc = *ic = *bc = 0;
    for (int i = 0; i < pd->uniform_count; ++i) {
        const MOJOSHADER_uniform *u = &pd->uniforms[i];
        if (u->constant) continue;
        int count = u->array_count ? u->array_count : 1;
        map[*map_count].type = u->type;
        map[*map_count].index = u->index;
        map[*map_count].count = count;
        ++*map_count;
        if (u->type == MOJOSHADER_UNIFORM_FLOAT) *fc += count;
        else if (u->type == MOJOSHADER_UNIFORM_INT) *ic += count;
        else *bc += count;
    }
}

/* The vertex shader variant whose D3DCOLOR inputs are swizzled to RGBA. */
/* Patched GLSL of the vertex shader variant for a BGRA-input mask. */
static char *vertex_source(d3d_shader *vs, uint32_t mask)
{
    if (!mask) return strdup(vs->source);
    MOJOSHADER_swizzle swiz[16];
    unsigned n = 0;
    for (int i = 0; i < vs->parse->attribute_count && i < 16; ++i) {
        if (!(mask & (1u << i))) continue;
        swiz[n].usage = vs->parse->attributes[i].usage;
        swiz[n].index = (unsigned)vs->parse->attributes[i].index;
        swiz[n].swizzles[0] = 2; swiz[n].swizzles[1] = 1; swiz[n].swizzles[2] = 0; swiz[n].swizzles[3] = 3;
        ++n;
    }
    const MOJOSHADER_parseData *pd = MOJOSHADER_parse(MOJOSHADER_PROFILE_GLSLES3, "main",
        vs->parse_code ? vs->parse_code : vs->bytecode, vs->parse_code ? vs->parse_size : vs->size,
        swiz, n, NULL, 0, NULL, NULL, NULL);
    char *src = NULL;
    if (pd && !pd->error_count) src = patch_source(pd->output, 0);
    if (pd) MOJOSHADER_freeParseData(pd);
    return src;
}

static GLuint vertex_variant(d3d_shader *vs, uint32_t mask)
{
    if (!mask) {
        if (!vs->gl_plain) vs->gl_plain = compile(GL_VERTEX_SHADER, vs->source);
        return vs->gl_plain;
    }
    char *src = vertex_source(vs, mask);
    GLuint sh = src ? compile(GL_VERTEX_SHADER, src) : 0;
    free(src);
    return sh;
}

/* D3D links a pixel input to a vertex output by semantic even when the
 * vertex shader never writes it; GLSL refuses. A POSITION input reads the
 * clip-space position the vertex shader wrote (before the GL fixups), an
 * unwritten colour reads 1 and anything else 0. Returns the patched sources
 * (NULL when that stage needs no change). */
static void reconcile_varyings(const char *vs_src, const char *ps_src, char **vs_out, char **ps_out)
{
    *vs_out = *ps_out = NULL;
    const char *needle = "in highp vec4 io_";
    char *ps = NULL, *vs = NULL;
    for (const char *p = strstr(ps_src, needle); p; p = strstr(p + 1, needle)) {
        unsigned u, i;
        if (sscanf(p + strlen(needle), "%u_%u", &u, &i) != 2) continue;
        char out_decl[48];
        snprintf(out_decl, sizeof out_decl, "out highp vec4 io_%u_%u;", u, i);
        if (strstr(vs_src, out_decl)) continue;
        if (u == 0 && i == 0 && strstr(vs_src, "gl_Position.y = gl_Position.y * vpFlip;")) {
            const char *base = vs ? vs : vs_src;
            char *a = insert_before(base, "void main()", "out highp vec4 io_0_0;\n");
            char *b = insert_before(a, "\tgl_Position.y = gl_Position.y * vpFlip;", "\tio_0_0 = gl_Position;\n");
            free(a);
            free(vs);
            vs = b;
            continue;
        }
        char in_decl[48], constant[80];
        snprintf(in_decl, sizeof in_decl, "in highp vec4 io_%u_%u;", u, i);
        snprintf(constant, sizeof constant, "const highp vec4 io_%u_%u = vec4(%s);", u, i, u == 10 ? "1.0" : "0.0");
        const char *base = ps ? ps : ps_src;
        const char *at = strstr(base, in_decl);
        if (!at) continue;
        size_t head = (size_t)(at - base), len = strlen(base);
        char *next = (char *)malloc(len + strlen(constant) + 1);
        memcpy(next, base, head);
        strcpy(next + head, constant);
        strcat(next, base + head + strlen(in_decl));
        free(ps);
        ps = next;
    }
    *vs_out = vs;
    *ps_out = ps;
}

/* d3d9_ff.c */
void d3d_ff_attributes(int *attr_count, int *usage, int *index);
GLuint d3d_ff_vertex_stage(d3d_device *d, const char *ps_source, uint32_t *id);
GLuint d3d_ff_pixel_stage(d3d_device *d, const char *vs_source, uint32_t *id, uint32_t *stage_mask);
void d3d_ff_uniforms(d3d_device *d, GLuint program, int vertex, int pixel);

/* Link vs and ps; a missing one is replaced by the generated shader object
 * ff_gl (named by ff_id), whose samplers are the stages in ff_samplers. */
static program_t *link_program(d3d_shader *vs, d3d_shader *ps, uint32_t bgra_mask, GLuint ff_gl, uint32_t ff_id,
    uint32_t ff_samplers)
{
    program_t *p = (program_t *)calloc(1, sizeof *p);
    p->vs = vs; p->ps = ps; p->bgra_mask = bgra_mask; p->ff_id = ff_id;
    char *vs_fixed = NULL, *ps_fixed = NULL;
    if (vs && ps) reconcile_varyings(vs->source, ps->source, &vs_fixed, &ps_fixed);
    if (vs_fixed) {
        /* The same fix applied to the BGRA variant's source. */
        char *variant = vertex_source(vs, bgra_mask), *ignored = NULL, *fixed = NULL;
        if (variant) reconcile_varyings(variant, ps->source, &fixed, &ignored);
        p->vs_gl = fixed ? compile(GL_VERTEX_SHADER, fixed) : 0;
        free(variant); free(ignored); free(fixed); free(vs_fixed);
    } else {
        p->vs_gl = vs ? vertex_variant(vs, bgra_mask) : ff_gl;
    }
    if (ps_fixed) {
        p->ps_gl = compile(GL_FRAGMENT_SHADER, ps_fixed);
        free(ps_fixed);
    } else {
        if (ps && !ps->gl_plain) ps->gl_plain = compile(GL_FRAGMENT_SHADER, ps->source);
        p->ps_gl = ps ? ps->gl_plain : ff_gl;
    }
    if (!p->vs_gl || !p->ps_gl) { free(p); return NULL; }
    const char *names[16] = {0};
    if (vs) {
        const MOJOSHADER_parseData *vpd = vs->parse;
        p->attr_count = vpd->attribute_count < 16 ? vpd->attribute_count : 16;
        for (int i = 0; i < p->attr_count; ++i) {
            names[i] = vpd->attributes[i].name;
            p->attr_usage[i] = vpd->attributes[i].usage;
            p->attr_index[i] = vpd->attributes[i].index;
        }
    } else {
        d3d_ff_attributes(&p->attr_count, p->attr_usage, p->attr_index);   /* fixed layout locations */
    }
    p->gl = d3d_warm_program(p->vs_gl, p->ps_gl, vs ? p->attr_count : 0, names);
    if (!p->gl) {
        void_log("[d3d9] vs:\n%s\nps:\n%s", vs ? vs->source : "(fixed function)", ps ? ps->source : "(fixed function)");
        free(p);
        return NULL;
    }
    glUseProgram(p->gl);
    p->loc_vs_f = glGetUniformLocation(p->gl, "vs_uniforms_vec4");
    p->loc_vs_i = glGetUniformLocation(p->gl, "vs_uniforms_ivec4");
    p->loc_vs_b = glGetUniformLocation(p->gl, "vs_uniforms_bool");
    p->loc_ps_f = glGetUniformLocation(p->gl, "ps_uniforms_vec4");
    p->loc_ps_i = glGetUniformLocation(p->gl, "ps_uniforms_ivec4");
    p->loc_ps_b = glGetUniformLocation(p->gl, "ps_uniforms_bool");
    p->loc_flip = glGetUniformLocation(p->gl, "vpFlip");
    p->loc_half = glGetUniformLocation(p->gl, "vpHalfPixel");
    p->loc_alpha_func = glGetUniformLocation(p->gl, "vpAlphaFunc");
    p->loc_alpha_ref = glGetUniformLocation(p->gl, "vpAlphaRef");
    if (p->loc_flip >= 0) glUniform1f(p->loc_flip, -1.0f);
    p->last_alpha_func = -1;
    if (vs) build_map(vs->parse, p->vs_map, &p->vs_map_count, &p->vs_f_count, &p->vs_i_count, &p->vs_b_count);
    if (ps) build_map(ps->parse, p->ps_map, &p->ps_map_count, &p->ps_f_count, &p->ps_i_count, &p->ps_b_count);
    p->vs_f = (float *)calloc((size_t)p->vs_f_count * 4 + 4, sizeof(float));
    p->ps_f = (float *)calloc((size_t)p->ps_f_count * 4 + 4, sizeof(float));
    p->vs_i = (int32_t *)calloc((size_t)p->vs_i_count * 4 + 4, sizeof(int32_t));
    p->ps_i = (int32_t *)calloc((size_t)p->ps_i_count * 4 + 4, sizeof(int32_t));
    p->vs_b = (int32_t *)calloc((size_t)p->vs_b_count + 1, sizeof(int32_t));
    p->ps_b = (int32_t *)calloc((size_t)p->ps_b_count + 1, sizeof(int32_t));
    p->vs_f_loc = (GLint *)malloc(((size_t)p->vs_f_count + 1) * sizeof(GLint));
    p->ps_f_loc = (GLint *)malloc(((size_t)p->ps_f_count + 1) * sizeof(GLint));
    for (int i = 0; i <= p->vs_f_count; ++i) p->vs_f_loc[i] = -2;
    for (int i = 0; i <= p->ps_f_count; ++i) p->ps_f_loc[i] = -2;
    /* Samplers: pixel sampler n -> unit n, vertex sampler n -> unit 16 + n. */
    if (!ps) p->ps_sampler_mask = ff_samplers;
    for (int i = 0; ps && i < ps->parse->sampler_count; ++i) {
        const MOJOSHADER_sampler *sm = &ps->parse->samplers[i];
        GLint loc = glGetUniformLocation(p->gl, sm->name);
        if (loc >= 0 && sm->index < 16) {
            glUniform1i(loc, sm->index);
            p->ps_sampler_mask |= 1u << sm->index;
            p->ps_sampler_type[sm->index] = sm->type;
        }
    }
    for (int i = 0; vs && i < vs->parse->sampler_count; ++i) {
        const MOJOSHADER_sampler *sm = &vs->parse->samplers[i];
        GLint loc = glGetUniformLocation(p->gl, sm->name);
        if (loc >= 0 && sm->index < 4) {
            glUniform1i(loc, 16 + sm->index);
            p->vs_sampler_mask |= 1u << sm->index;
            p->vs_sampler_type[sm->index] = sm->type;
        }
    }
    return p;
}

static void pack(const umap_t *map, int count, const float (*f)[4], const int32_t (*iv)[4], const int32_t *b,
    float *of, int32_t *oi, int32_t *ob)
{
    for (int k = 0; k < count; ++k) {
        const umap_t *m = &map[k];
        if (m->type == MOJOSHADER_UNIFORM_FLOAT) { memcpy(of, f[m->index], 16u * (uint32_t)m->count); of += 4 * m->count; }
        else if (m->type == MOJOSHADER_UNIFORM_INT) { memcpy(oi, iv[m->index], 16u * (uint32_t)m->count); oi += 4 * m->count; }
        else { for (int i = 0; i < m->count; ++i) ob[i] = b[m->index + i] != 0; ob += m->count; }
    }
}

/* Uploads the vec4 range of `fresh` that differs from what the program holds
 * (`held`, updated): a draw usually changes a matrix or two of the hundreds
 * of constants its program declares. A range that starts past element 0 goes
 * to that element's own location (GLSL ES does not promise consecutive ones);
 * when the compiler dropped that element, the whole array goes from the base. */
static void upload_vec4(GLuint prog, const char *name, GLint base, GLint *locs, float *held, const float *fresh,
    int count)
{
    int first = 0, last = count - 1;
    while (first < count && !memcmp(held + 4 * first, fresh + 4 * first, 16)) ++first;
    if (first == count) return;
    while (last > first && !memcmp(held + 4 * last, fresh + 4 * last, 16)) --last;
    memcpy(held + 4 * first, fresh + 4 * first, 16u * (uint32_t)(last - first + 1));
    if (first && locs[first] == -2) {
        char element[64];
        snprintf(element, sizeof element, "%s[%d]", name, first);
        locs[first] = glGetUniformLocation(prog, element);
    }
    if (!first) glUniform4fv(base, last + 1, held);
    else if (locs[first] >= 0) glUniform4fv(locs[first], last - first + 1, held + 4 * first);
    else glUniform4fv(base, last + 1, held);
}

static void upload_ints(GLint loc, int32_t *held, const int32_t *fresh, int count, int vec4)
{
    size_t bytes = (size_t)count * (vec4 ? 16u : 4u);
    if (!memcmp(held, fresh, bytes)) return;
    memcpy(held, fresh, bytes);
    if (vec4) glUniform4iv(loc, count, held);
    else glUniform1iv(loc, count, held);
}

void d3d_shader_upload(d3d_device *dev, float half_x, float half_y, int alpha_func, float alpha_ref)
{
    program_t *p = current_program;
    if (!p) return;
    if (p->uploaded_generation != d3d_constant_generation) {
        /* D3D9 limits: 256 vertex and 224 pixel float registers, 16 int and 16 bool each. */
        static float vs_f[256 * 4 + 4], ps_f[256 * 4 + 4];
        static int32_t vs_i[16 * 4 + 4], ps_i[16 * 4 + 4], vs_b[16 + 1], ps_b[16 + 1];
        if (p->vs_f_count > 256 || p->ps_f_count > 256 || p->vs_i_count > 16 || p->ps_i_count > 16 ||
            p->vs_b_count > 16 || p->ps_b_count > 16)
            void_fatal("shader constants beyond the D3D9 register files (%d/%d/%d, %d/%d/%d)",
                p->vs_f_count, p->vs_i_count, p->vs_b_count, p->ps_f_count, p->ps_i_count, p->ps_b_count);
        pack(p->vs_map, p->vs_map_count, (const float (*)[4])dev->st.vs_f, (const int32_t (*)[4])dev->st.vs_i, dev->st.vs_b, vs_f, vs_i, vs_b);
        pack(p->ps_map, p->ps_map_count, (const float (*)[4])dev->st.ps_f, (const int32_t (*)[4])dev->st.ps_i, dev->st.ps_b, ps_f, ps_i, ps_b);
        if (p->loc_vs_f >= 0 && p->vs_f_count)
            upload_vec4(p->gl, "vs_uniforms_vec4", p->loc_vs_f, p->vs_f_loc, p->vs_f, vs_f, p->vs_f_count);
        if (p->loc_vs_i >= 0 && p->vs_i_count) upload_ints(p->loc_vs_i, p->vs_i, vs_i, p->vs_i_count, 1);
        if (p->loc_vs_b >= 0 && p->vs_b_count) upload_ints(p->loc_vs_b, p->vs_b, vs_b, p->vs_b_count, 0);
        if (p->loc_ps_f >= 0 && p->ps_f_count)
            upload_vec4(p->gl, "ps_uniforms_vec4", p->loc_ps_f, p->ps_f_loc, p->ps_f, ps_f, p->ps_f_count);
        if (p->loc_ps_i >= 0 && p->ps_i_count) upload_ints(p->loc_ps_i, p->ps_i, ps_i, p->ps_i_count, 1);
        if (p->loc_ps_b >= 0 && p->ps_b_count) upload_ints(p->loc_ps_b, p->ps_b, ps_b, p->ps_b_count, 0);
        p->uploaded_generation = d3d_constant_generation;
    }
    if (p->loc_half >= 0 && (p->last_half[0] != half_x || p->last_half[1] != half_y)) {
        glUniform2f(p->loc_half, half_x, half_y);
        p->last_half[0] = half_x; p->last_half[1] = half_y;
    }
    if (p->loc_alpha_func >= 0 && (p->last_alpha_func != alpha_func || p->last_alpha_ref != alpha_ref)) {
        glUniform1i(p->loc_alpha_func, alpha_func);
        glUniform1f(p->loc_alpha_ref, alpha_ref);
        p->last_alpha_func = alpha_func; p->last_alpha_ref = alpha_ref;
    }
}

/* Bind the program for (vs, ps, D3DCOLOR inputs). bgra_of(usage, index) says
 * whether that input is fed by a D3DCOLOR element. */
int d3d_shader_bind2(d3d_device *dev, d3d_shader *vs, d3d_shader *ps, int (*bgra_of)(d3d_device *, int, int),
    int *attr_count, const int **attr_usage, const int **attr_index, uint32_t *ps_samplers, uint32_t *vs_samplers,
    const int **ps_types, const int **vs_types)
{
    if ((vs && !shader_type_ok(vs, 0)) || (ps && !shader_type_ok(ps, 1)) || (!vs && !ps)) return 0;
    uint32_t mask = 0, ff_id = 0, ff_samplers = 0;
    GLuint ff_gl = 0;
    for (int i = 0; vs && i < vs->parse->attribute_count && i < 16; ++i)
        if (bgra_of(dev, vs->parse->attributes[i].usage, vs->parse->attributes[i].index)) mask |= 1u << i;
    /* A missing shader is replaced by the fixed-function half for the current state. */
    if (!vs) ff_gl = d3d_ff_vertex_stage(dev, ps->source, &ff_id);
    else if (!ps) ff_gl = d3d_ff_pixel_stage(dev, vs->source, &ff_id, &ff_samplers);
    if ((!vs || !ps) && !ff_gl) { shader_draw_result(vs, ps, 1); return 0; }
    uintptr_t h = ((uintptr_t)vs * 31u + (uintptr_t)ps * 17u + mask + ff_id * 7u) % 1024u;
    program_t *p = programs[h];
    while (p && !(p->vs == vs && p->ps == ps && p->bgra_mask == mask && p->ff_id == ff_id)) p = p->next;
    if (!p) {
        p = link_program(vs, ps, mask, ff_gl, ff_id, ff_samplers);
        if (!p) { shader_draw_result(vs, ps, 1); return 0; }
        p->next = programs[h];
        programs[h] = p;
    }
    if (current_program != p) glUseProgram(p->gl);
    current_program = p;
    if (failed_program) shader_draw_result(vs, ps, 0);
    if (!vs || !ps) d3d_ff_uniforms(dev, p->gl, !vs, !ps);
    *attr_count = p->attr_count;
    *attr_usage = p->attr_usage;
    *attr_index = p->attr_index;
    *ps_samplers = p->ps_sampler_mask;
    *vs_samplers = p->vs_sampler_mask;
    *ps_types = p->ps_sampler_type;
    *vs_types = p->vs_sampler_type;
    return 1;
}

int d3d_shader_bind(d3d_device *dev, d3d_shader *vs, d3d_shader *ps, uint32_t *attribute_mask,
    int *attribute_usage, int *attribute_index, int *attribute_count, int *needs_bgra)
{
    (void)dev; (void)vs; (void)ps; (void)attribute_mask; (void)attribute_usage; (void)attribute_index;
    (void)attribute_count; (void)needs_bgra;
    return 0;
}

void d3d_shader_forget_current(void) { current_program = NULL; }

/* Frame tracing (d3d9_gl.c): the current program's vertex GLSL, once per
 * program, and the packed vertex constants it was given. */
void d3d_shader_trace(void)
{
    program_t *p = current_program;
    if (!p) return;
    static program_t *shown[256];
    static int shown_count;
    int seen = 0;
    for (int i = 0; i < shown_count; ++i) if (shown[i] == p) seen = 1;
    if (!seen && shown_count < 256) {
        shown[shown_count++] = p;
        if (p->vs) void_log("[trace]   vertex GLSL of program %u:\n%s", p->gl, p->vs->source);
        if (p->ps) void_log("[trace]   pixel GLSL of program %u:\n%s", p->gl, p->ps->source);
    }
    char line[1024];
    size_t n = 0;
    line[0] = 0;
    for (int i = 0; i < p->vs_map_count && n < sizeof line - 64; ++i)
        n += (size_t)snprintf(line + n, sizeof line - n, " c%d x%d", p->vs_map[i].index, p->vs_map[i].count);
    void_log("[trace]   vs uniform map:%s", line);
    n = 0;
    line[0] = 0;
    for (int i = 0; i < p->vs_f_count && i < 8; ++i)
        n += (size_t)snprintf(line + n, sizeof line - n, " [%d](%g %g %g %g)", i, p->vs_f[4 * i], p->vs_f[4 * i + 1],
            p->vs_f[4 * i + 2], p->vs_f[4 * i + 3]);
    void_log("[trace]   vs uniforms:%s", line);
    /* Skinned shaders keep their bone palette low and the transforms at
     * c200 and up (RendererD3D's skinning effects): show those too. */
    n = 0;
    line[0] = 0;
    for (int i = 200; i < p->vs_f_count && i < 216 && n < sizeof line - 96; ++i)
        n += (size_t)snprintf(line + n, sizeof line - n, " [%d](%g %g %g %g)", i, p->vs_f[4 * i], p->vs_f[4 * i + 1],
            p->vs_f[4 * i + 2], p->vs_f[4 * i + 3]);
    if (n) void_log("[trace]   vs uniforms c200+:%s", line);
    n = 0;
    line[0] = 0;
    for (int i = 0; i < p->ps_map_count && n < sizeof line - 64; ++i)
        n += (size_t)snprintf(line + n, sizeof line - n, " c%d x%d", p->ps_map[i].index, p->ps_map[i].count);
    void_log("[trace]   ps uniform map:%s", line);
    n = 0;
    line[0] = 0;
    for (int i = 0; i < p->ps_f_count && i < 8; ++i)
        n += (size_t)snprintf(line + n, sizeof line - n, " [%d](%g %g %g %g)", i, p->ps_f[4 * i], p->ps_f[4 * i + 1],
            p->ps_f[4 * i + 2], p->ps_f[4 * i + 3]);
    void_log("[trace]   ps uniforms:%s", line);
}
