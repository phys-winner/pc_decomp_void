/* The GL side of Direct3D 9: EGL, render targets, state, draws, blits, present. */
#define _GNU_SOURCE
#include "d3d9_internal.h"
#include "hud.h"
#include "shader_warm.h"
#include <time.h>
#include <stdatomic.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <math.h>
#include <sys/stat.h>

#ifndef VOID_ANDROID_APP
extern int void_shader_warming;
#endif

static EGLDisplay egl_display = EGL_NO_DISPLAY;
static EGLContext egl_context = EGL_NO_CONTEXT;
static EGLSurface egl_surface = EGL_NO_SURFACE;
static int window_mode;
static int dump_every;
d3d_gl_limits_t d3d_gl_limits;
d3d_gl_caps_t d3d_gl_caps;
static uint32_t trace_frame;   /* defined with the tracing helpers */
static GLuint vao;
static GLuint upload_unit = 31;   /* texture uploads bind here, away from the sampler units */
#define FB_UNKNOWN 0xFFFFFFFFu
/* Binding caches (see bind_texture and d3d_gl_bind_targets). */
static GLuint unit_tex[32], unit_sampler[32];
static GLenum unit_target[32];
static int active_unit = -1;
typedef struct { GLuint buffer; GLint size; GLenum type; GLboolean norm; GLsizei stride; uintptr_t offset; GLuint divisor; } attr_state;
static attr_state attr_cache[16];
static GLuint elem_buffer = FB_UNKNOWN;
static int attr_cache_ready;
extern uint32_t d3d_constant_generation;

/* The Android activity provides the window; the shell build has none. */
__attribute__((weak)) void *void_android_window(void) { return NULL; }
__attribute__((weak)) void void_android_frame_presented(void) {}
__attribute__((weak)) void *void_android_window_current(uint32_t *serial, int wait) { (void)wait; *serial = 0; return NULL; }
__attribute__((weak)) void void_android_window_ack(uint32_t serial) { (void)serial; }

/* The window surface follows the activity's (android_main.c): the context
 * stays current on a 1x1 pbuffer while there is none. */
static EGLConfig egl_config;
static EGLSurface egl_pbuffer = EGL_NO_SURFACE;
static uint32_t egl_window_serial;

/* Take up the activity's current window if it changed since the last frame.
 * Without one (the app in the background) the game waits here, letting the
 * other guest threads run, until the activity has a surface again. */
static uint32_t period_logged;   /* the still menu's frame period last logged (0: full rate) */

/* The player's frame limit (Settings.fpsLimit) against the display's present
 * refresh, both from the activity (android_main.c). A display at the limit
 * (the mode the activity asked for) keeps it by itself; one at a whole
 * multiple of it shows a frame every n-th refresh (swap interval n); any
 * other is paced by the clock, the swap then meeting the next refresh. */
static _Atomic uint32_t frame_limit_hz, display_refresh_mhz;
static int swap_interval_set = 1;   /* the window surface's swap interval */
void d3d_gl_set_frame_limit(uint32_t hz) { atomic_store(&frame_limit_hz, hz); }
void d3d_gl_set_display_refresh(float hz) { atomic_store(&display_refresh_mhz, hz > 0 ? (uint32_t)(hz * 1000.0f) : 0u); }

/* The swap interval the limit asks for; *period_us: the frame period the
 * clock keeps instead (0: none). */
static int frame_limit_plan(uint32_t *period_us)
{
    uint32_t limit = atomic_load(&frame_limit_hz);
    double refresh = atomic_load(&display_refresh_mhz) / 1000.0;
    *period_us = 0;
    if (!limit || refresh <= limit * 1.03) return 1;
    double ratio = refresh / limit;
    int n = (int)(ratio + 0.5);
    if (n >= 2 && fabs(ratio - n) <= 0.03 * n) return n;
    *period_us = (uint32_t)(1000000.0 / limit);
    return 1;
}

static void follow_window(void)
{
    uint32_t serial;
    void *window = void_android_window_current(&serial, 0);
    if (serial == egl_window_serial) return;
    eglMakeCurrent(egl_display, egl_pbuffer, egl_pbuffer, egl_context);
    if (egl_surface != EGL_NO_SURFACE) eglDestroySurface(egl_display, egl_surface);
    egl_surface = EGL_NO_SURFACE;
    egl_window_serial = serial;
    void_android_window_ack(serial);
    if (!window) {
        void_log("[gl] surface gone: the game waits for the activity");
        void_blocking_begin();
        window = void_android_window_current(&serial, 1);
        void_blocking_end();
        egl_window_serial = serial;
    }
    egl_surface = eglCreateWindowSurface(egl_display, egl_config, (EGLNativeWindowType)window, NULL);
    if (egl_surface == EGL_NO_SURFACE || !eglMakeCurrent(egl_display, egl_surface, egl_surface, egl_context)) {
        void_log("[gl] new window surface failed %04X", eglGetError());
        eglMakeCurrent(egl_display, egl_pbuffer, egl_pbuffer, egl_context);
        egl_surface = EGL_NO_SURFACE;
    } else {
        eglSwapInterval(egl_display, 1);
        swap_interval_set = 1;   /* the frame limit sets its own again (d3d_gl_present) */
        void_log("[gl] presenting into a new window surface");
    }
    void_android_window_ack(serial);
}

int d3d_gl_init(void)
{
    if (egl_context != EGL_NO_CONTEXT) return 1;
    egl_display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    if (!eglInitialize(egl_display, NULL, NULL)) { void_log("[gl] eglInitialize failed %04X", eglGetError()); return 0; }
    void *window = void_android_window_current(&egl_window_serial, 1);   /* NULL in the shell build */
    window_mode = window != NULL;
    const EGLint attrs[] = {
        EGL_SURFACE_TYPE, window_mode ? EGL_WINDOW_BIT | EGL_PBUFFER_BIT : EGL_PBUFFER_BIT,
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT_KHR,
        EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8,
        EGL_DEPTH_SIZE, 0, EGL_STENCIL_SIZE, 0, EGL_NONE };
    EGLConfig config;
    EGLint n = 0;
    if (!eglChooseConfig(egl_display, attrs, &config, 1, &n) || !n) { void_log("[gl] no EGL config"); return 0; }
    egl_config = config;
    const EGLint ctx_attrs[] = { EGL_CONTEXT_CLIENT_VERSION, 3, EGL_CONTEXT_MINOR_VERSION_KHR, 2, EGL_NONE };
    egl_context = eglCreateContext(egl_display, config, EGL_NO_CONTEXT, ctx_attrs);
    if (egl_context == EGL_NO_CONTEXT) { void_log("[gl] eglCreateContext failed %04X", eglGetError()); return 0; }
    const EGLint pb[] = { EGL_WIDTH, 16, EGL_HEIGHT, 16, EGL_NONE };
    if (window_mode) {
        egl_surface = eglCreateWindowSurface(egl_display, config, (EGLNativeWindowType)window, NULL);
        egl_pbuffer = eglCreatePbufferSurface(egl_display, config, pb);
    } else {
        egl_surface = eglCreatePbufferSurface(egl_display, config, pb);
    }
    if (egl_surface == EGL_NO_SURFACE || !eglMakeCurrent(egl_display, egl_surface, egl_surface, egl_context)) {
        void_log("[gl] EGL surface/current failed %04X", eglGetError());
        return 0;
    }
    if (window_mode) eglSwapInterval(egl_display, 1);
    void_log("[gl] %s / %s / %s (%s)", glGetString(GL_VENDOR), glGetString(GL_RENDERER), glGetString(GL_VERSION),
        window_mode ? "window" : "pbuffer");
    GLint value = 0;
    glGetIntegerv(GL_MAX_TEXTURE_SIZE, &value); d3d_gl_limits.max_texture = (uint32_t)value;
    glGetIntegerv(GL_MAX_3D_TEXTURE_SIZE, &value); d3d_gl_limits.max_3d_texture = (uint32_t)value;
    glGetIntegerv(GL_MAX_DRAW_BUFFERS, &value); d3d_gl_limits.max_draw_buffers = (uint32_t)value;
    void_log("[gl] limits: texture %u, 3D texture %u, draw buffers %u", d3d_gl_limits.max_texture,
        d3d_gl_limits.max_3d_texture, d3d_gl_limits.max_draw_buffers);
    /* The game's DXT blocks go to a GPU with S3TC as they are; elsewhere they
     * are decoded, unless the launcher converted them (d3dx9.c, tvtx.h).
     * VOID_NO_S3TC=1 decodes them all the same (comparisons). */
    GLint extensions = 0;
    glGetIntegerv(GL_NUM_EXTENSIONS, &extensions);
    int dxt1 = 0, dxt3 = 0, dxt5 = 0;
    for (GLint i = 0; i < extensions; ++i) {
        const char *e = (const char *)glGetStringi(GL_EXTENSIONS, (GLuint)i);
        if (!e) continue;
        if (!strcmp(e, "GL_EXT_texture_compression_s3tc")) dxt1 = dxt3 = dxt5 = 1;
        else if (!strcmp(e, "GL_EXT_texture_compression_dxt1")) dxt1 = 1;
        else if (!strcmp(e, "GL_ANGLE_texture_compression_dxt3")) dxt3 = 1;
        else if (!strcmp(e, "GL_ANGLE_texture_compression_dxt5")) dxt5 = 1;
        else if (!strcmp(e, "GL_KHR_texture_compression_astc_ldr")) d3d_gl_caps.astc = 1;
    }
    const char *no_s3tc = getenv("VOID_NO_S3TC");
    d3d_gl_caps.s3tc = dxt1 && dxt3 && dxt5 && !(no_s3tc && *no_s3tc == '1');
    void_log("[gl] block textures: DXT %s, ASTC %s, ETC2 yes", d3d_gl_caps.s3tc ? "sampled as they are" : "decoded",
        d3d_gl_caps.astc ? "yes" : "no");
    const char *dump = getenv("VOID_DUMP_FRAMES");
    dump_every = dump ? atoi(dump) : 0;
    const char *trace = getenv("VOID_TRACE_FRAME");
    if (trace) trace_frame = (uint32_t)strtoul(trace, NULL, 10);
    glGetIntegerv(GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS, &value);
    upload_unit = value > 32 ? 31u : (GLuint)(value > 21 ? value - 1 : 21);
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    return 1;
}

/* ------------------------------------------------------------- targets */
static GLuint fbo, read_fbo, draw_fbo;

static void attach(GLenum fb_target, GLenum attachment, d3d_surface *s)
{
    if (!s) { glFramebufferTexture2D(fb_target, attachment, GL_TEXTURE_2D, 0, 0); return; }
    GLenum target;
    GLint level, layer;
    GLuint tex = d3d_surface_gl_texture(s, &target, &level, &layer);
    if (target == GL_TEXTURE_3D) glFramebufferTextureLayer(fb_target, attachment, tex, level, layer);
    else glFramebufferTexture2D(fb_target, attachment, target, tex, level);
}

static GLenum depth_attachment(const d3d_surface *s)
{
    return s && s->fmt && s->fmt->stencil ? GL_DEPTH_STENCIL_ATTACHMENT : GL_DEPTH_ATTACHMENT;
}

/* The bound target's GL texels per game pixel (d3d_set_physical_size):
 * viewports, scissors and clears are given in game pixels. */
static float target_kx = 1.0f, target_ky = 1.0f;

static void scale_rect(int *x, int *y, int *w, int *h)
{
    if (target_kx == 1.0f && target_ky == 1.0f) return;
    int x0 = (int)lroundf((float)*x * target_kx), x1 = (int)lroundf((float)(*x + *w) * target_kx);
    int y0 = (int)lroundf((float)*y * target_ky), y1 = (int)lroundf((float)(*y + *h) * target_ky);
    *x = x0; *y = y0; *w = x1 - x0; *h = y1 - y0;
}

/* ------------------------------------------------------------- tracing
 * VOID_TRACE_FRAME=N logs every target change, clear, draw and blit of frame
 * N and dumps each render target when the frame leaves it (and the back
 * buffer at present) to <data>/frames/trace_N_SEQ.bmp, clamped to [0, 1]. */
static uint32_t trace_frame = 0xFFFFFFFFu;
static unsigned trace_seq;
static d3d_surface *trace_rt;

static int tracing(d3d_device *d) { return d->frame == trace_frame; }
void d3d_shader_trace(void);

/* VOID_TRACE_DIFF: render target 0 before each traced draw, to report what
 * the draw changed. */
static uint8_t *trace_before;
static uint32_t trace_before_w, trace_before_h;

static int trace_read_rt0(d3d_device *d, uint8_t **out, uint32_t *w, uint32_t *h)
{
    d3d_surface *s = d->rt[0];
    if (!s || !s->fmt || s->fmt->is_float || s->fmt->depth) return 0;
    d3d_surface_gl_size(s, w, h);
    *out = (uint8_t *)malloc((size_t)*w * *h * 4);
    glReadBuffer(GL_COLOR_ATTACHMENT0);
    glReadPixels(0, 0, (GLsizei)*w, (GLsizei)*h, GL_RGBA, GL_UNSIGNED_BYTE, *out);
    return glGetError() == GL_NO_ERROR;
}

/* Whether the current frame is being traced (for the other D3D9 files). */
int d3d_trace_active(void) { return g_d3d_device && tracing(g_d3d_device); }

/* Trace the next frame (scripted "trace"). */
void d3d_request_trace(void) { if (g_d3d_device) trace_frame = g_d3d_device->frame + 1; }

/* Live "camera N": for N frames, the first 3D draw's view-projection
 * translation (vertex constants c0..c3, w) and when the frame was
 * presented - whether the picture moves every frame. */
static volatile int camera_frames;
static int camera_taken;
static float camera_w[4];
void d3d_request_camera_log(int frames) { camera_frames = frames; }

static uint32_t shader_tag(const void *shader)
{
    if (!shader) return 0;
    const d3d_shader *sh = (const d3d_shader *)shader;
    uint32_t h = 2166136261u;
    for (uint32_t i = 0; i < sh->size; ++i) h = (h ^ sh->bytecode[i]) * 16777619u;
    return h;
}

static void trace_dump(d3d_device *d, d3d_surface *s, const char *why)
{
    if (!s || !s->fmt || s->fmt->depth) return;
    uint32_t w = s->width, h = s->height, rect[4] = { 0, 0, w, h };
    float *px = (float *)malloc((size_t)w * h * 16);
    if (!d3d_gl_read_rgba(s, rect, px)) {
        void_log("[trace] %s: surface %ux%u fmt %u unreadable", why, w, h, s->format);
        free(px);
        return;
    }
    float lo[4] = { 1e30f, 1e30f, 1e30f, 1e30f }, hi[4] = { -1e30f, -1e30f, -1e30f, -1e30f };
    size_t nans = 0, infs = 0;
    for (size_t i = 0; i < (size_t)w * h; ++i)
        for (int k = 0; k < 4; ++k) {
            float v = px[4 * i + k];
            if (isnan(v)) { ++nans; continue; }
            if (isinf(v)) ++infs;
            if (v < lo[k]) lo[k] = v;
            if (v > hi[k]) hi[k] = v;
        }
    char path[1100];
    snprintf(path, sizeof path, "%s/frames", void_data_dir());
    mkdir(path, 0775);
    snprintf(path, sizeof path, "%s/frames/trace_%u_%03u.bmp", void_data_dir(), d->frame, trace_seq++);
    FILE *f = fopen(path, "wb");
    if (f) {
        uint32_t row = w * 3, pad = (4 - row % 4) % 4, size = 54 + (row + pad) * h;
        uint8_t header[54] = { 'B', 'M' };
        memcpy(header + 2, &size, 4);
        uint32_t v = 54; memcpy(header + 10, &v, 4);
        v = 40; memcpy(header + 14, &v, 4);
        memcpy(header + 18, &w, 4); memcpy(header + 22, &h, 4);
        header[26] = 1; header[28] = 24;
        fwrite(header, 1, 54, f);
        uint8_t zero[4] = {0};
        for (uint32_t y = h; y-- > 0;) {
            for (uint32_t x = 0; x < w; ++x) {
                const float *c = px + 4 * ((size_t)y * w + x);
                uint8_t bgr[3];
                for (int k = 0; k < 3; ++k) {
                    float t = c[2 - k];
                    bgr[k] = (uint8_t)(t <= 0.0f ? 0 : t >= 1.0f ? 255 : t * 255.0f + 0.5f);
                }
                fwrite(bgr, 1, 3, f);
            }
            fwrite(zero, 1, pad, f);
        }
        fclose(f);
    }
    void_log("[trace] %s: %ux%u fmt %u -> %s  r[%g,%g] g[%g,%g] b[%g,%g] a[%g,%g]", why, w, h, s->format, path,
        lo[0], hi[0], lo[1], hi[1], lo[2], hi[2], lo[3], hi[3]);
    if (nans || infs) void_log("[trace]   %zu NaN and %zu infinite components", nans, infs);
    free(px);
}

/* What the render framebuffer object has attached. Re-attaching the very same
 * texture still ends a tiler's render pass (Mali stores and reloads every
 * tile), and the map set its depth surface ~290 times a frame: only real
 * changes reach GL. A deleted texture's name can come back, so deletion
 * forgets it (d3d_gl_forget_texture). */
typedef struct { GLuint tex; GLenum target; GLint level, layer; } fb_attachment;
static fb_attachment fb_color[4] = { { FB_UNKNOWN, 0, 0, 0 }, { FB_UNKNOWN, 0, 0, 0 }, { FB_UNKNOWN, 0, 0, 0 },
                                     { FB_UNKNOWN, 0, 0, 0 } };
static fb_attachment fb_depth = { FB_UNKNOWN, 0, 0, 0 };
static GLenum fb_depth_point = FB_UNKNOWN, fb_bufs[4];
static uint32_t fb_depth_w, fb_depth_h;
static GLsizei fb_buf_count = -1;

static fb_attachment attachment_of(d3d_surface *s)
{
    fb_attachment a = { 0, GL_TEXTURE_2D, 0, 0 };
    if (s) a.tex = d3d_surface_gl_texture(s, &a.target, &a.level, &a.layer);
    return a;
}

static int same_attachment(fb_attachment a, fb_attachment b)
{
    return a.tex == b.tex && a.target == b.target && a.level == b.level && a.layer == b.layer;
}

static void put_attachment(GLenum point, fb_attachment a)
{
    if (!a.tex) glFramebufferTexture2D(GL_FRAMEBUFFER, point, GL_TEXTURE_2D, 0, 0);
    else if (a.target == GL_TEXTURE_3D) glFramebufferTextureLayer(GL_FRAMEBUFFER, point, a.tex, a.level, a.layer);
    else glFramebufferTexture2D(GL_FRAMEBUFFER, point, a.target, a.tex, a.level);
}

void d3d_gl_forget_texture(GLuint tex)
{
    for (int i = 0; i < 32; ++i) if (unit_tex[i] == tex) unit_tex[i] = 0;   /* deletion unbinds it everywhere */
    for (int i = 0; i < 4; ++i) if (fb_color[i].tex == tex) fb_color[i].tex = FB_UNKNOWN;
    if (fb_depth.tex == tex) { fb_depth.tex = FB_UNKNOWN; fb_depth_point = FB_UNKNOWN; }
}

void d3d_gl_bind_targets(d3d_device *dev)
{
    if (!fbo) glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    if (!dev->fbo_dirty) return;
    if (tracing(dev) && trace_rt != dev->rt[0]) {
        if (trace_rt) trace_dump(dev, trace_rt, "target done");
        trace_rt = dev->rt[0];
        void_log("[trace] target rt0 %p %ux%u fmt %u%s, rt1 %p, ds %p %ux%u fmt %u", (void *)dev->rt[0],
            dev->rt[0] ? dev->rt[0]->width : 0, dev->rt[0] ? dev->rt[0]->height : 0, dev->rt[0] ? dev->rt[0]->format : 0,
            dev->rt[0] == dev->backbuffer ? " (back buffer)" : "", (void *)dev->rt[1], (void *)dev->ds,
            dev->ds ? dev->ds->width : 0, dev->ds ? dev->ds->height : 0, dev->ds ? dev->ds->format : 0);
    }
    GLenum bufs[4];
    int last = 0, changed = 0;
    for (int i = 0; i < 4; ++i) {
        d3d_surface *s = dev->rt[i];
        int usable = s && s->fmt && s->fmt->internal;
        /* A texture that keeps its own mip chain (AUTOGENMIPMAP) is drawn
         * into: its levels follow before it is next sampled (full HDR's
         * bloom reads level 2 of the scene). */
        if (usable && s->container && s->level == 0 && (s->container->usage & D3DUSAGE_AUTOGENMIPMAP))
            s->container->mips_dirty = 1;
        fb_attachment a = attachment_of(usable ? s : NULL);
        if (!same_attachment(a, fb_color[i])) {
            put_attachment(GL_COLOR_ATTACHMENT0 + (GLenum)i, a);
            fb_color[i] = a;
            changed = 1;
        }
        bufs[i] = usable ? GL_COLOR_ATTACHMENT0 + (GLenum)i : GL_NONE;
        if (usable) last = i + 1;
    }
    GLsizei count = last ? last : 1;
    if (count != fb_buf_count || memcmp(bufs, fb_bufs, sizeof(GLenum) * (size_t)count)) {
        glDrawBuffers(count, bufs);
        memcpy(fb_bufs, bufs, sizeof bufs);
        fb_buf_count = count;
    }
    fb_attachment z = attachment_of(dev->ds);
    GLenum point = dev->ds ? depth_attachment(dev->ds) : 0;
    d3d_surface *rt0 = dev->rt[0];
    uint32_t rt0_w = 0, rt0_h = 0;
    if (rt0) d3d_surface_gl_size(rt0, &rt0_w, &rt0_h);
    if (!dev->ds && fb_depth_point != FB_UNKNOWN && fb_depth_point && fb_depth.tex != FB_UNKNOWN && rt0 &&
        fb_depth_w >= rt0_w && fb_depth_h >= rt0_h) {
        /* No depth surface: keep the last one attached while it covers the
         * colour target. Depth and stencil tests and clears all check d->ds,
         * so it is neither read nor written; detaching it would end the
         * render pass at every NULL <-> surface toggle (the map toggles
         * between passes ~10 times a frame). */
        z = fb_depth;
        point = fb_depth_point;
    }
    if (point != fb_depth_point || !same_attachment(z, fb_depth)) {
        if (fb_depth_point == FB_UNKNOWN) {
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT, GL_TEXTURE_2D, 0, 0);
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_TEXTURE_2D, 0, 0);
        } else if (fb_depth_point && fb_depth_point != point) {
            glFramebufferTexture2D(GL_FRAMEBUFFER, fb_depth_point, GL_TEXTURE_2D, 0, 0);
        }
        if (point) put_attachment(point, z);
        if (tracing(dev)) void_log("[trace] depth attachment %u -> %u (ds %p)", fb_depth.tex, z.tex, (void *)dev->ds);
        fb_depth = z;
        fb_depth_point = point;
        if (dev->ds) d3d_surface_gl_size(dev->ds, &fb_depth_w, &fb_depth_h);
        changed = 1;
    }
    d3d_surface *sized = dev->rt[0] ? dev->rt[0] : dev->ds;
    target_kx = target_ky = 1.0f;
    if (sized) {
        uint32_t gw, gh;
        d3d_surface_gl_size(sized, &gw, &gh);
        if (gw != sized->width || gh != sized->height) {
            target_kx = (float)gw / (float)sized->width;
            target_ky = (float)gh / (float)sized->height;
        }
    }
    GLenum status = changed ? glCheckFramebufferStatus(GL_FRAMEBUFFER) : GL_FRAMEBUFFER_COMPLETE;
    if (status != GL_FRAMEBUFFER_COMPLETE) {
        static int warned;
        if (warned++ < 20)
            void_log("[gl] framebuffer incomplete %04X: rt0 %ux%u fmt %u, ds %ux%u fmt %u", status,
                dev->rt[0] ? dev->rt[0]->width : 0, dev->rt[0] ? dev->rt[0]->height : 0, dev->rt[0] ? dev->rt[0]->format : 0,
                dev->ds ? dev->ds->width : 0, dev->ds ? dev->ds->height : 0, dev->ds ? dev->ds->format : 0);
    }
    dev->fbo_dirty = 0;
}

/* --------------------------------------------------------------- state */
static GLenum compare(uint32_t f)
{
    static const GLenum map[] = { GL_ALWAYS, GL_NEVER, GL_LESS, GL_EQUAL, GL_LEQUAL, GL_GREATER, GL_NOTEQUAL, GL_GEQUAL, GL_ALWAYS };
    return f < 9 ? map[f] : GL_ALWAYS;
}

static GLenum blend_factor(uint32_t b, int alpha)
{
    switch (b) {
    case 1: return GL_ZERO;
    case 2: return GL_ONE;
    case 3: return alpha ? GL_SRC_ALPHA : GL_SRC_COLOR;
    case 4: return alpha ? GL_ONE_MINUS_SRC_ALPHA : GL_ONE_MINUS_SRC_COLOR;
    case 5: return GL_SRC_ALPHA;
    case 6: return GL_ONE_MINUS_SRC_ALPHA;
    case 7: return GL_DST_ALPHA;
    case 8: return GL_ONE_MINUS_DST_ALPHA;
    case 9: return alpha ? GL_DST_ALPHA : GL_DST_COLOR;
    case 10: return alpha ? GL_ONE_MINUS_DST_ALPHA : GL_ONE_MINUS_DST_COLOR;
    case 11: return GL_SRC_ALPHA_SATURATE;
    case 14: return alpha ? GL_CONSTANT_ALPHA : GL_CONSTANT_COLOR;
    case 15: return alpha ? GL_ONE_MINUS_CONSTANT_ALPHA : GL_ONE_MINUS_CONSTANT_COLOR;
    default: return GL_ONE;
    }
}

static GLenum blend_op(uint32_t op)
{
    switch (op) {
    case 2: return GL_FUNC_SUBTRACT;
    case 3: return GL_FUNC_REVERSE_SUBTRACT;
    case 4: return GL_MIN;
    case 5: return GL_MAX;
    default: return GL_FUNC_ADD;
    }
}

static GLenum stencil_op(uint32_t op)
{
    static const GLenum map[] = { GL_KEEP, GL_KEEP, GL_ZERO, GL_REPLACE, GL_INCR, GL_DECR, GL_INVERT, GL_INCR_WRAP, GL_DECR_WRAP };
    return op < 9 ? map[op] : GL_KEEP;
}

static float u2f(uint32_t u) { float f; memcpy(&f, &u, 4); return f; }

/* GL render state is re-sent only when it changes: apply_state runs for every
 * draw (hundreds a frame on the map) but consecutive draws usually share state.
 * The shadow holds the exact inputs read below; clears, blits, fills and the
 * present all change some of these states, so each calls
 * d3d_gl_invalidate_state() to force the next apply. One GL context on the
 * render thread, so one shadow. */
static struct {
    uint32_t rs[256], viewport[4], scissor[4];
    float viewport_z[2];
    const void *ds;
    int ds_present, ds_stencil, ds_bits16;
} state_shadow;
static int state_dirty = 1;

void d3d_gl_invalidate_state(void) { state_dirty = 1; }

void d3d_gl_apply_state(d3d_device *d)
{
    const uint32_t *rs = d->st.rs;
    int ds_present = d->ds != NULL;
    int ds_stencil = d->ds && d->ds->fmt && d->ds->fmt->stencil;
    int ds_bits16 = d->ds && d->ds->fmt && d->ds->fmt->bits == 16;
    if (!state_dirty && state_shadow.ds == d->ds && state_shadow.ds_present == ds_present
            && state_shadow.ds_stencil == ds_stencil && state_shadow.ds_bits16 == ds_bits16
            && !memcmp(state_shadow.rs, rs, sizeof state_shadow.rs)
            && !memcmp(state_shadow.viewport, d->st.viewport, sizeof state_shadow.viewport)
            && !memcmp(state_shadow.scissor, d->st.scissor, sizeof state_shadow.scissor)
            && !memcmp(state_shadow.viewport_z, d->st.viewport_z, sizeof state_shadow.viewport_z))
        return;
    /* Depth */
    if (rs[7] && d->ds) glEnable(GL_DEPTH_TEST); else glDisable(GL_DEPTH_TEST);
    glDepthFunc(compare(rs[23]));
    glDepthMask(rs[14] ? GL_TRUE : GL_FALSE);
    /* Blend */
    if (rs[27]) {
        glEnable(GL_BLEND);
        uint32_t src = rs[19], dst = rs[20];
        if (src == 12) { src = 5; dst = 6; } else if (src == 13) { src = 6; dst = 5; }
        uint32_t asrc = src, adst = dst, aop = rs[171];
        if (rs[206]) {
            asrc = rs[207]; adst = rs[208]; aop = rs[209];
            if (asrc == 12) { asrc = 5; adst = 6; } else if (asrc == 13) { asrc = 6; adst = 5; }
        }
        glBlendFuncSeparate(blend_factor(src, 0), blend_factor(dst, 0), blend_factor(asrc, 1), blend_factor(adst, 1));
        glBlendEquationSeparate(blend_op(rs[171]), blend_op(aop));
        uint32_t bf = rs[193];
        glBlendColor(((bf >> 16) & 255) / 255.0f, ((bf >> 8) & 255) / 255.0f, (bf & 255) / 255.0f, (bf >> 24) / 255.0f);
    } else {
        glDisable(GL_BLEND);
    }
    /* Cull: D3D clockwise is GL counter-clockwise in the flipped targets. */
    glFrontFace(GL_CCW);
    if (rs[22] == 1) glDisable(GL_CULL_FACE);
    else { glEnable(GL_CULL_FACE); glCullFace(rs[22] == 2 ? GL_FRONT : GL_BACK); }
    /* Stencil */
    if (rs[52] && d->ds && d->ds->fmt && d->ds->fmt->stencil) {
        glEnable(GL_STENCIL_TEST);
        glStencilFuncSeparate(GL_FRONT, compare(rs[56]), (GLint)rs[57], rs[58]);
        glStencilOpSeparate(GL_FRONT, stencil_op(rs[53]), stencil_op(rs[54]), stencil_op(rs[55]));
        if (rs[185]) {
            glStencilFuncSeparate(GL_BACK, compare(rs[189]), (GLint)rs[57], rs[58]);
            glStencilOpSeparate(GL_BACK, stencil_op(rs[186]), stencil_op(rs[187]), stencil_op(rs[188]));
        } else {
            glStencilFuncSeparate(GL_BACK, compare(rs[56]), (GLint)rs[57], rs[58]);
            glStencilOpSeparate(GL_BACK, stencil_op(rs[53]), stencil_op(rs[54]), stencil_op(rs[55]));
        }
        glStencilMask(rs[59]);
    } else {
        glDisable(GL_STENCIL_TEST);
    }
    /* Colour write masks */
    static const int mask_state[4] = { 168, 190, 191, 192 };
    for (int i = 0; i < 4; ++i) {
        uint32_t m = rs[mask_state[i]];
        glColorMaski((GLuint)i, (m & 1) != 0, (m & 2) != 0, (m & 4) != 0, (m & 8) != 0);
    }
    /* Scissor */
    if (rs[174]) {
        glEnable(GL_SCISSOR_TEST);
        int sx = (int)d->st.scissor[0], sy = (int)d->st.scissor[1], sw = (int)d->st.scissor[2], sh = (int)d->st.scissor[3];
        scale_rect(&sx, &sy, &sw, &sh);
        glScissor(sx, sy, sw, sh);
    } else {
        glDisable(GL_SCISSOR_TEST);
    }
    /* Depth bias */
    float bias = u2f(rs[195]), slope = u2f(rs[175]);
    if (bias != 0.0f || slope != 0.0f) {
        glEnable(GL_POLYGON_OFFSET_FILL);
        float scale = (d->ds && d->ds->fmt && d->ds->fmt->bits == 16) ? 65535.0f : 16777215.0f;
        glPolygonOffset(slope, bias * scale);
    } else {
        glDisable(GL_POLYGON_OFFSET_FILL);
    }
    /* Viewport */
    int vx = (int)d->st.viewport[0], vy = (int)d->st.viewport[1], vw = (int)d->st.viewport[2], vh = (int)d->st.viewport[3];
    scale_rect(&vx, &vy, &vw, &vh);
    glViewport(vx, vy, vw, vh);
    glDepthRangef(d->st.viewport_z[0], d->st.viewport_z[1]);
    memcpy(state_shadow.rs, rs, sizeof state_shadow.rs);
    memcpy(state_shadow.viewport, d->st.viewport, sizeof state_shadow.viewport);
    memcpy(state_shadow.scissor, d->st.scissor, sizeof state_shadow.scissor);
    memcpy(state_shadow.viewport_z, d->st.viewport_z, sizeof state_shadow.viewport_z);
    state_shadow.ds = d->ds;
    state_shadow.ds_present = ds_present;
    state_shadow.ds_stencil = ds_stencil;
    state_shadow.ds_bits16 = ds_bits16;
    state_dirty = 0;
}

/* ------------------------------------------------------------- samplers */
typedef struct { uint32_t key[9]; GLuint sampler; } sampler_entry;
static sampler_entry sampler_cache[512];
static int sampler_count;

static GLenum address(uint32_t a)
{
    switch (a) {
    case 2: return GL_MIRRORED_REPEAT;
    case 3: return GL_CLAMP_TO_EDGE;
    case 4: return GL_CLAMP_TO_BORDER_EXT;
    case 5: return GL_MIRRORED_REPEAT;          /* MIRRORONCE: closest available */
    default: return GL_REPEAT;
    }
}

static GLuint sampler_for(const uint32_t *ss, int no_filter, uint32_t levels, uint32_t lod)
{
    uint32_t key[9] = { ss[1], ss[2], ss[3], ss[4], no_filter ? 1 : ss[5], no_filter ? 1 : ss[6],
        no_filter ? (ss[7] ? 1u : 0u) : ss[7], ss[10], ss[9] > lod ? ss[9] : lod };
    (void)levels;
    for (int i = 0; i < sampler_count; ++i) if (!memcmp(sampler_cache[i].key, key, sizeof key)) return sampler_cache[i].sampler;
    GLuint s;
    glGenSamplers(1, &s);
    glSamplerParameteri(s, GL_TEXTURE_WRAP_S, (GLint)address(key[0]));
    glSamplerParameteri(s, GL_TEXTURE_WRAP_T, (GLint)address(key[1]));
    glSamplerParameteri(s, GL_TEXTURE_WRAP_R, (GLint)address(key[2]));
    uint32_t bc = key[3];
    GLfloat border[4] = { ((bc >> 16) & 255) / 255.0f, ((bc >> 8) & 255) / 255.0f, (bc & 255) / 255.0f, (bc >> 24) / 255.0f };
    glSamplerParameterfv(s, GL_TEXTURE_BORDER_COLOR_EXT, border);
    uint32_t mag = key[4], min = key[5], mip = key[6];
    glSamplerParameteri(s, GL_TEXTURE_MAG_FILTER, mag >= 2 ? GL_LINEAR : GL_NEAREST);
    GLenum minf;
    int linear = min >= 2;
    if (mip == 0) minf = linear ? GL_LINEAR : GL_NEAREST;
    else if (mip == 1) minf = linear ? GL_LINEAR_MIPMAP_NEAREST : GL_NEAREST_MIPMAP_NEAREST;
    else minf = linear ? GL_LINEAR_MIPMAP_LINEAR : GL_NEAREST_MIPMAP_LINEAR;
    glSamplerParameteri(s, GL_TEXTURE_MIN_FILTER, (GLint)minf);
    float aniso = (min == 3 || mag == 3) ? (float)(key[7] ? key[7] : 1) : 1.0f;
    if (aniso > 16.0f) aniso = 16.0f;
    glSamplerParameterf(s, GL_TEXTURE_MAX_ANISOTROPY_EXT, aniso);
    glSamplerParameterf(s, GL_TEXTURE_MIN_LOD, (float)key[8]);
    if (sampler_count < 512) {
        memcpy(sampler_cache[sampler_count].key, key, sizeof key);
        sampler_cache[sampler_count++].sampler = s;
    } else {
        /* Full: evict round-robin and delete the old object, so a working set
         * past 512 states does not leak a new sampler object on every draw. */
        static int evict_next;
        glDeleteSamplers(1, &sampler_cache[evict_next].sampler);
        memcpy(sampler_cache[evict_next].key, key, sizeof key);
        sampler_cache[evict_next].sampler = s;
        evict_next = (evict_next + 1) % 512;
    }
    return s;
}

/* What each texture unit and vertex attribute holds, so a draw only sends GL
 * the bindings that changed: Mali revalidates at the draw for every binding
 * call, changed or not. Texture uploads bind on a unit of their own
 * (d3d_gl_upload_unit); deleted textures and buffers are forgotten. */

static void activate_unit(GLuint unit)
{
    if ((int)unit == active_unit) return;
    glActiveTexture(GL_TEXTURE0 + unit);
    active_unit = (int)unit;
}

void d3d_gl_upload_unit(void) { activate_unit(upload_unit); }

void d3d_gl_forget_buffer(GLuint buffer)
{
    for (int i = 0; i < 16; ++i) if (attr_cache[i].buffer == buffer) attr_cache[i].buffer = FB_UNKNOWN;
    if (elem_buffer == buffer) elem_buffer = FB_UNKNOWN;
}

/* smooth: the image is drawn larger than the game meant (its picture drawn
 * at a larger size, d3d_set_physical_size): magnified, it filters.
 * keep_edge: so magnified, a picture's outermost screen pixels fall within
 * half a texel of its border, where filtering would mix in the texels
 * across it (the opposite edge when wrapping, the border colour): thin lines
 * at a picture's sides, never seen at the game's own size, where pixel
 * centres meet texel centres. Clamped to the edge it keeps its own texels. */
static void bind_texture(d3d_device *d, int slot, GLuint unit, int smooth, int keep_edge)
{
    d3d_texture *t = (d3d_texture *)d->st.textures[slot];
    if (!t || !t->gl) {
        if (unit_tex[unit]) {
            activate_unit(unit);
            glBindTexture(GL_TEXTURE_2D, 0);
            glBindTexture(GL_TEXTURE_CUBE_MAP, 0);
            unit_tex[unit] = 0;
        }
        return;
    }
    if (t->mips_dirty) d3d_generate_mips(t);
    if (unit_tex[unit] != t->gl || unit_target[unit] != t->target) {
        activate_unit(unit);
        glBindTexture(t->target, t->gl);
        unit_tex[unit] = t->gl;
        unit_target[unit] = t->target;
    }
    int no_filter = t->fmt->depth || (t->fmt->is_float && t->fmt->gl_bits / (t->fmt->format == GL_RED ? 1 : t->fmt->format == GL_RG ? 2 : 4) >= 32);
    uint32_t ss[14];
    memcpy(ss, d->st.ss[slot], sizeof ss);
    if (t->levels < 2) ss[7] = 0;   /* no mip chain: D3D samples level 0 whatever MIPFILTER says */
    if (smooth && ss[5] < 2) ss[5] = 2;
    if (keep_edge && t->target == GL_TEXTURE_2D) ss[1] = ss[2] = 3;   /* D3DTADDRESS_CLAMP */
    GLuint sampler = sampler_for(ss, no_filter, t->levels, t->lod);
    if (unit_sampler[unit] != sampler) { glBindSampler(unit, sampler); unit_sampler[unit] = sampler; }
}

/* ------------------------------------------------------------ attributes */
typedef struct { GLint size; GLenum type; GLboolean norm; } attr_format;
static const attr_format attr_formats[] = {
    {1, GL_FLOAT, GL_FALSE}, {2, GL_FLOAT, GL_FALSE}, {3, GL_FLOAT, GL_FALSE}, {4, GL_FLOAT, GL_FALSE},
    {4, GL_UNSIGNED_BYTE, GL_TRUE}, {4, GL_UNSIGNED_BYTE, GL_FALSE}, {2, GL_SHORT, GL_FALSE}, {4, GL_SHORT, GL_FALSE},
    {4, GL_UNSIGNED_BYTE, GL_TRUE}, {2, GL_SHORT, GL_TRUE}, {4, GL_SHORT, GL_TRUE}, {2, GL_UNSIGNED_SHORT, GL_TRUE},
    {4, GL_UNSIGNED_SHORT, GL_TRUE}, {4, GL_UNSIGNED_INT_2_10_10_10_REV, GL_FALSE}, {4, GL_INT_2_10_10_10_REV, GL_TRUE},
    {2, GL_HALF_FLOAT, GL_FALSE}, {4, GL_HALF_FLOAT, GL_FALSE},
};

static const d3d_vertex_element *find_element(d3d_device *d, int usage, int index)
{
    d3d_decl *decl = (d3d_decl *)d->st.decl;
    if (!decl) return NULL;
    for (int i = 0; i < decl->count; ++i)
        if (decl->elements[i].usage == usage && decl->elements[i].usage_index == index && decl->elements[i].type < 17)
            return &decl->elements[i];
    /* POSITIONT feeds a POSITION input, as for pre-transformed vertices. */
    if (usage == 0) for (int i = 0; i < decl->count; ++i)
        if (decl->elements[i].usage == 9 && decl->elements[i].usage_index == index) return &decl->elements[i];
    return NULL;
}

/* The part of the viewport a 2D draw covers (pre-transformed positions,
 * corners at -0.5) as [x0, y0, x1, y1] in 0..1, for the touch layer's HUD
 * slots; 0 for other draws. */
static int draw_rect(d3d_device *d, const void *up_vertices, uint32_t up_stride, uint32_t start_vertex,
    uint32_t vertex_count, int indexed, float rect[4])
{
    const d3d_vertex_element *pe = find_element(d, 0, 0);
    if (indexed || !pe || pe->usage != 9 || pe->type != 3) return 0;
    const uint8_t *vb = NULL;
    uint32_t stride = 0;
    if (up_vertices && pe->stream == 0) { vb = (const uint8_t *)up_vertices; stride = up_stride; }
    else if (d->st.streams[pe->stream]) {
        d3d_buffer *b = (d3d_buffer *)d->st.streams[pe->stream];
        vb = (const uint8_t *)GPTR(b->shadow + d->st.stream_offset[pe->stream]);
        stride = d->st.stream_stride[pe->stream];
    }
    float vw = (float)d->st.viewport[2], vh = (float)d->st.viewport[3];
    if (!vb || !stride || !vertex_count || vw <= 0 || vh <= 0) return 0;
    float x0 = 1e9f, y0 = 1e9f, x1 = -1e9f, y1 = -1e9f;
    for (uint32_t i = 0; i < vertex_count && i < 64; ++i) {
        const float *v = (const float *)(vb + (size_t)(start_vertex + i) * stride + pe->offset);
        if (v[0] < x0) x0 = v[0];
        if (v[0] > x1) x1 = v[0];
        if (v[1] < y0) y0 = v[1];
        if (v[1] > y1) y1 = v[1];
    }
    rect[0] = (x0 + 0.5f - (float)d->st.viewport[0]) / vw;
    rect[1] = (y0 + 0.5f - (float)d->st.viewport[1]) / vh;
    rect[2] = (x1 + 0.5f - (float)d->st.viewport[0]) / vw;
    rect[3] = (y1 + 0.5f - (float)d->st.viewport[1]) / vh;
    return 1;
}

/* Whether every texture coordinate a 2D draw gives its vertices (the float
 * TEXCOORD sets) lies within the texture, [0, 1] give or take a rounding:
 * its pictures are whole textures or parts of them, not tiled across the
 * quad. Indexed draws are read through their indices; past 1024 vertices
 * the answer is no. */
static int texcoords_inside(d3d_device *d, const void *up_vertices, uint32_t up_stride, uint32_t start_vertex,
    uint32_t vertex_count, int indexed, uint32_t base_vertex, uint32_t start_index, const void *up_indices, int up_index32)
{
    d3d_decl *decl = (d3d_decl *)d->st.decl;
    if (!decl || !vertex_count) return 0;
    uint32_t first = start_vertex, count = vertex_count;
    if (indexed) {
        const uint8_t *ib = (const uint8_t *)up_indices;
        int wide = up_index32;
        if (!ib) {
            d3d_buffer *b = (d3d_buffer *)d->st.indices;
            if (!b || (uint64_t)(start_index + vertex_count) * (b->format == 102 ? 4u : 2u) > b->size) return 0;
            ib = (const uint8_t *)GPTR(b->shadow);
            wide = b->format == 102;
        }
        uint32_t lo = UINT32_MAX, hi = 0;
        for (uint32_t i = 0; i < vertex_count; ++i) {
            uint32_t k = start_index + i, v;
            if (wide) memcpy(&v, ib + 4u * k, 4); else { uint16_t h; memcpy(&h, ib + 2u * k, 2); v = h; }
            if (v < lo) lo = v;
            if (v > hi) hi = v;
        }
        first = base_vertex + lo;
        count = hi - lo + 1;
    }
    if (count > 1024) return 0;
    int checked = 0;
    for (int e = 0; e < decl->count; ++e) {
        const d3d_vertex_element *el = &decl->elements[e];
        if (el->usage != 5 || el->type > 3) continue;
        const uint8_t *vb = NULL;
        uint32_t stride = 0, limit = UINT32_MAX;
        if (up_vertices && el->stream == 0) { vb = (const uint8_t *)up_vertices; stride = up_stride; }
        else if (el->stream < 16 && d->st.streams[el->stream]) {
            d3d_buffer *b = (d3d_buffer *)d->st.streams[el->stream];
            if (d->st.stream_offset[el->stream] >= b->size) return 0;
            vb = (const uint8_t *)GPTR(b->shadow + d->st.stream_offset[el->stream]);
            stride = d->st.stream_stride[el->stream];
            limit = b->size - d->st.stream_offset[el->stream];
        }
        if (!vb || !stride) return 0;
        uint32_t comps = el->type >= 1 ? 2 : 1;
        if ((uint64_t)(first + count - 1) * stride + el->offset + 4u * comps > limit) return 0;
        for (uint32_t i = 0; i < count; ++i) {
            float uv[2];
            memcpy(uv, vb + (size_t)(first + i) * stride + el->offset, 4u * comps);
            for (uint32_t c = 0; c < comps; ++c)
                if (!(uv[c] >= -0.001f && uv[c] <= 1.001f)) return 0;
        }
        checked = 1;
    }
    return checked;
}

/* Fixed function: the stages that sample at their vertex coordinates as
 * they came (pass-through index, no texture transform). */
static uint32_t ff_direct_samplers(d3d_device *d, uint32_t samplers)
{
    uint32_t direct = 0;
    for (int s = 0; s < 8; ++s)
        if ((samplers & (1u << s)) && !(d->st.tss[s][11] >> 16) && !d->st.tss[s][24]) direct |= 1u << s;
    return direct;
}

static int bgra_of(d3d_device *d, int usage, int index)
{
    const d3d_vertex_element *e = find_element(d, usage, index);
    return e && e->type == 4;
}

void d3d_buffer_flush(d3d_buffer *b);
int d3d_shader_bind2(d3d_device *dev, d3d_shader *vs, d3d_shader *ps, int (*bgra)(d3d_device *, int, int),
    int *attr_count, const int **attr_usage, const int **attr_index, uint32_t *ps_samplers, uint32_t *vs_samplers,
    const int **ps_types, const int **vs_types);
void d3d_shader_upload(d3d_device *dev, float half_x, float half_y, int alpha_func, float alpha_ref);

static GLuint up_vbo, up_ibo;
static uint32_t enabled_attribs;

static GLenum gl_mode(uint32_t p)
{
    switch (p) {
    case 1: return GL_POINTS;
    case 2: return GL_LINES;
    case 3: return GL_LINE_STRIP;
    case 5: return GL_TRIANGLE_STRIP;
    case 6: return GL_TRIANGLE_FAN;
    default: return GL_TRIANGLES;
    }
}

static uint64_t draw_calls;   /* for the per-frame statistics */
static uint64_t swap_ns;      /* time in eglSwapBuffers: vsync and the GPU catching up */

int d3d_gl_draw(d3d_device *d, uint32_t primitive, uint32_t start_vertex, uint32_t vertex_count,
    uint32_t prim_count, int indexed, uint32_t base_vertex, uint32_t start_index, uint32_t min_index,
    const void *up_vertices, uint32_t up_stride, const void *up_indices, int up_index32)
{
#ifndef VOID_ANDROID_APP
    if (void_shader_warming) return 1;
#endif
    (void)prim_count; (void)min_index;
    ++draw_calls;
    d3d_shader *vs = (d3d_shader *)d->st.vs, *ps = (d3d_shader *)d->st.ps;
    /* POSITIONT vertices are already transformed: D3D9 runs no vertex shader
     * for them (Wine: use_vs() is false for a position_transformed
     * declaration), only the fixed-function pass-through. */
    if (vs) {
        d3d_decl *decl = (d3d_decl *)d->st.decl;
        for (int i = 0; decl && i < decl->count; ++i)
            if (decl->elements[i].usage == 9 && decl->elements[i].usage_index == 0 && decl->elements[i].type < 17) {
                vs = NULL;
                break;
            }
    }
    d3d_gl_bind_targets(d);
    d3d_gl_apply_state(d);
    int attr_count;
    const int *attr_usage, *attr_index, *ps_types, *vs_types;
    uint32_t ps_samplers, vs_samplers;
    /* No shaders: the generated fixed-function pipeline. One shader: the
     * other half is generated inside d3d_shader_bind2. */
    if (!vs && !ps) {
        static int ff_usage[16], ff_index[16];
        if (!d3d_ff_bind(d, &attr_count, ff_usage, ff_index, &ps_samplers)) return 0;
        attr_usage = ff_usage;
        attr_index = ff_index;
        vs_samplers = 0;
    } else {
        if (!d3d_shader_bind2(d, vs, ps, bgra_of, &attr_count, &attr_usage, &attr_index, &ps_samplers, &vs_samplers,
                              &ps_types, &vs_types))
            return 0;
        float hx = d->st.viewport[2] ? 1.0f / (float)d->st.viewport[2] : 0.0f;
        float hy = d->st.viewport[3] ? 1.0f / (float)d->st.viewport[3] : 0.0f;
        int alpha_func = d->st.rs[15] ? (int)d->st.rs[25] : 8;
        d3d_shader_upload(d, hx, hy, alpha_func, (float)(d->st.rs[24] & 0xFF));
    }
    if (camera_frames && vs && fabsf(d->st.vs_f[0][3]) + fabsf(d->st.vs_f[1][3]) + fabsf(d->st.vs_f[2][3]) > 0.01f) {
        for (int i = 0; i < 4; ++i) camera_w[i] = d->st.vs_f[i][3];   /* the last 3D draw that moves with the camera */
        camera_taken = 1;
    }
    uint32_t hud = ps ? ps->hud_tag : 0, hud_slot = 0;
    /* The interface (pre-transformed images, text) drawn larger than its
     * pixels: magnified smoothly rather than in blocks. */
    int smooth = 0;
    if (target_kx > 1.01f || target_ky > 1.01f) {
        d3d_decl *decl = (d3d_decl *)d->st.decl;
        for (int i = 0; decl && i < decl->count && !smooth; ++i)
            smooth = decl->elements[i].usage == 9 && decl->elements[i].usage_index == 0 && decl->elements[i].type < 17;
    }
    /* Enlarged, a picture keeps its edge (bind_texture): the samplers read
     * at the vertices' own coordinates, when those stay within the texture
     * (a tiled picture wraps on purpose). */
    uint32_t keep_edges = 0;
    if (smooth) {
        uint32_t direct = ps ? ps->direct_samplers & ps_samplers : ff_direct_samplers(d, ps_samplers);
        if (direct && texcoords_inside(d, up_vertices, up_stride, start_vertex, vertex_count, indexed, base_vertex,
                                       start_index, up_indices, up_index32))
            keep_edges = direct;
    }
    for (int s = 0; s < 16; ++s) {
        if (!(ps_samplers & (1u << s))) continue;
        bind_texture(d, s, (GLuint)s, smooth, (keep_edges >> s) & 1);
        if (d->st.textures[s]) {
            hud |= ((d3d_texture *)d->st.textures[s])->hud_tag;
            if (((d3d_texture *)d->st.textures[s])->hud_slot) hud_slot = ((d3d_texture *)d->st.textures[s])->hud_slot;
        }
    }
    if (hud) void_hud_draw(hud);
    if (hud_slot) {
        float rect[4] = { 0, 0, 0, 0 };
        draw_rect(d, up_vertices, up_stride, start_vertex, vertex_count, indexed, rect);
        void_hud_slot_draw(hud_slot, &d->st.ps_f[0][0], &d->st.vs_f[0][0], rect);
        if (tracing(d)) {
            const float *p = &d->st.ps_f[0][0];
            void_log("[trace]   hud slot %u: ps c0 (%g %g %g %g) c1 (%g %g %g %g) c2 (%g %g %g %g) c3 (%g %g %g %g) "
                "c4 (%g %g %g %g) c5 (%g %g %g %g)", hud_slot, p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7],
                p[8], p[9], p[10], p[11], p[12], p[13], p[14], p[15], p[16], p[17], p[18], p[19], p[20], p[21], p[22], p[23]);
        }
    }
    if (hud & void_hud_hidden()) return 1;
    /* The touch layer may hide the game's cursor: a finger needs none. */
    if ((hud & (HUD_CURSOR | HUD_CURSOR_LYMPHA)) && void_hud_cursor_hidden()) return 1;
    for (int s = 0; s < 4; ++s) if (vs_samplers & (1u << s)) bind_texture(d, 16 + s, (GLuint)(16 + s), 0, 0);
    /* UP data */
    uint32_t up_bytes = 0;
    if (up_vertices) {
        uint32_t vertices = vertex_count;
        if (indexed && up_indices) {
            uint32_t max = 0;
            for (uint32_t i = 0; i < vertex_count; ++i) {
                uint32_t v = up_index32 ? ((const uint32_t *)up_indices)[i] : ((const uint16_t *)up_indices)[i];
                if (v > max) max = v;
            }
            vertices = max + 1;
        }
        up_bytes = vertices * up_stride;
        if (!up_vbo) glGenBuffers(1, &up_vbo);
        glBindBuffer(GL_ARRAY_BUFFER, up_vbo);
        glBufferData(GL_ARRAY_BUFFER, up_bytes, up_vertices, GL_STREAM_DRAW);
    }
    uint32_t instances = (d->st.stream_freq[0] & 0x40000000u) ? (d->st.stream_freq[0] & 0x3FFFFFFFu) : 0;
    uint32_t want = 0;
    if (!attr_cache_ready) {
        for (int i = 0; i < 16; ++i) attr_cache[i].buffer = FB_UNKNOWN;
        attr_cache_ready = 1;
    }
    for (int i = 0; i < attr_count; ++i) {
        const d3d_vertex_element *e = find_element(d, attr_usage[i], attr_index[i]);
        if (!e) {
            if (attr_usage[i] == 10) glVertexAttrib4f((GLuint)i, 1, 1, 1, 1);
            else glVertexAttrib4f((GLuint)i, 0, 0, 0, 1);
            continue;
        }
        const attr_format *f = &attr_formats[e->type];
        uintptr_t offset;
        GLsizei stride;
        GLuint buffer;
        if (up_vertices && e->stream == 0) {
            buffer = up_vbo;
            offset = e->offset;
            stride = (GLsizei)up_stride;
        } else {
            d3d_buffer *b = (d3d_buffer *)d->st.streams[e->stream];
            if (!b) { glVertexAttrib4f((GLuint)i, 0, 0, 0, 1); continue; }
            d3d_buffer_flush(b);
            buffer = b->gl;
            offset = d->st.stream_offset[e->stream] + e->offset;
            stride = (GLsizei)d->st.stream_stride[e->stream];
        }
        attr_state *c = &attr_cache[i];
        if (c->buffer != buffer || c->size != f->size || c->type != f->type || c->norm != f->norm || c->stride != stride ||
            c->offset != offset) {
            glBindBuffer(GL_ARRAY_BUFFER, buffer);
            glVertexAttribPointer((GLuint)i, f->size, f->type, f->norm, stride, (const void *)offset);
            c->buffer = buffer; c->size = f->size; c->type = f->type; c->norm = f->norm; c->stride = stride; c->offset = offset;
        }
        GLuint divisor = (instances && (d->st.stream_freq[e->stream] & 0x80000000u)) ? 1u : 0u;
        if (c->divisor != divisor) { glVertexAttribDivisor((GLuint)i, divisor); c->divisor = divisor; }
        want |= 1u << i;
    }
    for (int i = 0; i < 16; ++i) {
        uint32_t bit = 1u << i;
        if ((want & bit) && !(enabled_attribs & bit)) glEnableVertexAttribArray((GLuint)i);
        if (!(want & bit) && (enabled_attribs & bit)) glDisableVertexAttribArray((GLuint)i);
    }
    enabled_attribs = want;
    GLuint trace_query = 0;
    if (tracing(d)) {
        /* The first vertex as the draw reads it, and the transform constants. */
        const d3d_vertex_element *pe = find_element(d, 0, 0);
        uint32_t index = start_vertex;
        if (indexed && !up_indices && d->st.indices) {
            d3d_buffer *ib = (d3d_buffer *)d->st.indices;
            index = ib->format == 102 ? MEM32(ib->shadow + start_index * 4u) : MEM16(ib->shadow + start_index * 2u);
            index += base_vertex;
        }
        float pos[4] = { 0, 0, 0, 0 };
        if (pe && pe->type <= 3) {
            const uint8_t *vb = NULL;
            uint32_t stride = 0;
            if (up_vertices && pe->stream == 0) { vb = (const uint8_t *)up_vertices; stride = up_stride; }
            else if (d->st.streams[pe->stream]) {
                d3d_buffer *b = (d3d_buffer *)d->st.streams[pe->stream];
                vb = (const uint8_t *)GPTR(b->shadow + d->st.stream_offset[pe->stream]);
                stride = d->st.stream_stride[pe->stream];
            }
            if (vb) memcpy(pos, vb + (size_t)index * stride + pe->offset, 4u * (pe->type + 1u));
        }
        const float *c = &d->st.vs_f[0][0];
        void_log("[trace]   v%u pos (%g %g %g %g) usage %u type %d; c0 (%g %g %g %g) c1 (%g %g %g %g) c2 (%g %g %g %g) c3 (%g %g %g %g)",
            index, pos[0], pos[1], pos[2], pos[3], pe ? pe->usage : 99, pe ? pe->type : -1, c[0], c[1], c[2], c[3], c[4], c[5],
            c[6], c[7], c[8], c[9], c[10], c[11], c[12], c[13], c[14], c[15]);
        char tex[256];
        size_t tn = 0;
        tex[0] = 0;
        for (int s2 = 0; s2 < 8; ++s2) {
            d3d_texture *t = (d3d_texture *)d->st.textures[s2];
            if (t && (ps_samplers & (1u << s2)))
                tn += (size_t)snprintf(tex + tn, sizeof tex - tn, " s%d=%ux%u/%u%s f%u%u%u a%u%u%s", s2, t->width, t->height,
                    t->format, t->hud_tag ? " hud" : "", d->st.ss[s2][5], d->st.ss[s2][6], d->st.ss[s2][7], d->st.ss[s2][1],
                    d->st.ss[s2][2], (keep_edges >> s2) & 1 ? " edge" : "");
        }
        if (smooth && tn < sizeof tex - 10) tn += (size_t)snprintf(tex + tn, sizeof tex - tn, " smooth");
        uint32_t ck = (g_icall_trace_idx - 1) & (ICALL_TRACE_SIZE - 1);
        {
            d3d_decl *dd = (d3d_decl *)d->st.decl;
            char dl[256];
            size_t dn = 0;
            dl[0] = 0;
            for (int i = 0; dd && i < dd->count && dn < sizeof dl - 24; ++i)
                dn += (size_t)snprintf(dl + dn, sizeof dl - dn, " %u.%u:t%u@%u", dd->elements[i].usage, dd->elements[i].usage_index,
                    dd->elements[i].type, dd->elements[i].offset);
            void_log("[trace]   decl%s (fvf %X, set vs %08X)", dl, d->st.fvf, shader_tag(d->st.vs));
        }
        void_log("[trace] draw from %08X prim %u count %u%s vs %08X ps %08X%s blend %u(%u,%u) z %u/%u/%u cull %u cw %X vp %u,%u %ux%u%s",
            g_icall_from[ck], primitive, vertex_count, indexed ? " indexed" : "", shader_tag(vs), shader_tag(ps), (!vs && !ps) ? " (ff)" : "",
            d->st.rs[27], d->st.rs[19], d->st.rs[20], d->st.rs[7], d->st.rs[14], d->st.rs[23], d->st.rs[22], d->st.rs[168],
            d->st.viewport[0], d->st.viewport[1], d->st.viewport[2], d->st.viewport[3], tex);
    }
    if (tracing(d)) {
        static int textures_traced;
        if (getenv("VOID_TRACE_TEXTURES") && textures_traced < 24) {
            d3d_texture *tt = (d3d_texture *)d->st.textures[0];
            if (tt && tt->rtype == D3DRTYPE_TEXTURE) {
                ++textures_traced;
                trace_dump(d, (d3d_surface *)void_com_host(d3d_texture_surface(tt, 0, 0)), "stage 0 texture");
            }
        }
        if (vs || ps) d3d_shader_trace();
        if (!vs && !ps) {
            /* Fixed function: the declaration, stage 0 and the first vertices. */
            d3d_decl *decl = (d3d_decl *)d->st.decl;
            char line[512];
            size_t n = 0;
            for (int i = 0; decl && i < decl->count && n < sizeof line - 40; ++i)
                n += (size_t)snprintf(line + n, sizeof line - n, " [s%u+%u t%u u%u.%u]", decl->elements[i].stream,
                    decl->elements[i].offset, decl->elements[i].type, decl->elements[i].usage, decl->elements[i].usage_index);
            const uint32_t *t0 = d->st.tss[0], *t1 = d->st.tss[1];
            void_log("[trace]   ff decl%s fvf %X; ts0 op %u(%X,%X) a %u(%X,%X) tci %X ttf %X; ts1 op %u; lighting %u tf %08X",
                line, d->st.fvf, t0[1], t0[2], t0[3], t0[4], t0[5], t0[6], t0[11], t0[24], t1[1], d->st.rs[137], d->st.rs[60]);
            const uint8_t *vb = NULL;
            uint32_t stride = 0;
            if (up_vertices) { vb = (const uint8_t *)up_vertices; stride = up_stride; }
            else if (d->st.streams[0]) {
                d3d_buffer *b = (d3d_buffer *)d->st.streams[0];
                vb = (const uint8_t *)GPTR(b->shadow + d->st.stream_offset[0]);
                stride = d->st.stream_stride[0];
            }
            static int textures_dumped;
            d3d_texture *t0tex = (d3d_texture *)d->st.textures[0];
            if (t0tex && textures_dumped++ < 2 && t0tex->rtype == D3DRTYPE_TEXTURE)
                trace_dump(d, (d3d_surface *)void_com_host(d3d_texture_surface(t0tex, 0, 0)), "ff stage 0 texture");
            for (uint32_t v = 0; vb && v < 4 && v < vertex_count; ++v) {
                const uint32_t *w = (const uint32_t *)(vb + (size_t)(start_vertex + v) * stride);
                float f[8];
                memcpy(f, w, sizeof f);
                void_log("[trace]   v%u: %g %g %g %g | %08X %08X | %g %g", v, f[0], f[1], f[2], f[3], w[4], w[5], f[6], f[7]);
            }
        }
        GLint view[4], scissor[4], fb = 0, status = 0;
        GLfloat range[2];
        glGetIntegerv(GL_VIEWPORT, view);
        glGetIntegerv(GL_SCISSOR_BOX, scissor);
        glGetFloatv(GL_DEPTH_RANGE, range);
        glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &fb);
        status = (GLint)glCheckFramebufferStatus(GL_DRAW_FRAMEBUFFER);
        void_log("[trace]   gl viewport %d,%d %dx%d depth %g..%g scissor %s %d,%d %dx%d cull %d depth %d stencil %d blend %d fb %d status %04X",
            view[0], view[1], view[2], view[3], range[0], range[1], glIsEnabled(GL_SCISSOR_TEST) ? "on" : "off", scissor[0],
            scissor[1], scissor[2], scissor[3], glIsEnabled(GL_CULL_FACE), glIsEnabled(GL_DEPTH_TEST), glIsEnabled(GL_STENCIL_TEST),
            glIsEnabled(GL_BLEND), fb, status);
        GLint program = 0;
        glGetIntegerv(GL_CURRENT_PROGRAM, &program);
        GLint af = glGetUniformLocation((GLuint)program, "vpAlphaFunc"), ar = glGetUniformLocation((GLuint)program, "vpAlphaRef");
        GLint afv = -1;
        GLfloat arv = -1;
        if (af >= 0) glGetUniformiv((GLuint)program, af, &afv);
        if (ar >= 0) glGetUniformfv((GLuint)program, ar, &arv);
        void_log("[trace]   alpha test rs %u func %u ref %u; program vpAlphaFunc %d vpAlphaRef %g", d->st.rs[15], d->st.rs[25],
            d->st.rs[24], afv, arv);
        if (getenv("VOID_DEBUG_NOALPHA") && af >= 0) glUniform1i(af, 8);
        if (getenv("VOID_DEBUG_NODEPTH")) glDisable(GL_DEPTH_TEST);
        if (getenv("VOID_DEBUG_NOCULL")) glDisable(GL_CULL_FACE);
        if (getenv("VOID_TRACE_DIFF")) {
            free(trace_before);
            trace_before = NULL;
            if (!trace_read_rt0(d, &trace_before, &trace_before_w, &trace_before_h)) { free(trace_before); trace_before = NULL; }
        }
        glGenQueries(1, &trace_query);
        glBeginQuery(GL_ANY_SAMPLES_PASSED, trace_query);
    }
    GLenum mode = gl_mode(primitive);
    if (indexed) {
        if (up_indices) {
            if (!up_ibo) glGenBuffers(1, &up_ibo);
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, up_ibo);
            elem_buffer = up_ibo;
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, vertex_count * (up_index32 ? 4u : 2u), up_indices, GL_STREAM_DRAW);
            glDrawElements(mode, (GLsizei)vertex_count, up_index32 ? GL_UNSIGNED_INT : GL_UNSIGNED_SHORT, NULL);
        } else {
            d3d_buffer *ib = (d3d_buffer *)d->st.indices;
            if (!ib) { void_log("[gl] indexed draw without an index buffer"); return 0; }
            d3d_buffer_flush(ib);
            if (elem_buffer != ib->gl) { glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ib->gl); elem_buffer = ib->gl; }
            int i32 = ib->format == 102;
            const void *ptr = (const void *)(uintptr_t)(start_index * (i32 ? 4u : 2u));
            if (instances)
                glDrawElementsInstancedBaseVertex(mode, (GLsizei)vertex_count, i32 ? GL_UNSIGNED_INT : GL_UNSIGNED_SHORT, ptr,
                    (GLsizei)instances, (GLint)base_vertex);
            else
                glDrawElementsBaseVertex(mode, (GLsizei)vertex_count, i32 ? GL_UNSIGNED_INT : GL_UNSIGNED_SHORT, ptr, (GLint)base_vertex);
        }
    } else {
        if (instances) glDrawArraysInstanced(mode, (GLint)start_vertex, (GLsizei)vertex_count, (GLsizei)instances);
        else glDrawArrays(mode, (GLint)start_vertex, (GLsizei)vertex_count);
    }
    GLenum e = glGetError();
    if (e) {
        static int warned;
        if (warned++ < 20) void_log("[gl] draw error %04X (prim %u count %u indexed %d)", e, primitive, vertex_count, indexed);
    }
    if (trace_query) {
        glEndQuery(GL_ANY_SAMPLES_PASSED);
        GLuint passed = 0;
        glGetQueryObjectuiv(trace_query, GL_QUERY_RESULT, &passed);
        glDeleteQueries(1, &trace_query);
        GLint program = 0;
        glGetIntegerv(GL_CURRENT_PROGRAM, &program);
        void_log("[trace]   samples passed: %s (program %d, error %04X)", passed ? "yes" : "NONE", program, e);
        uint8_t *after = NULL;
        uint32_t w = 0, h = 0;
        if (trace_before && trace_read_rt0(d, &after, &w, &h) && w == trace_before_w && h == trace_before_h) {
            uint32_t changed = 0, x0 = w, y0 = h, x1 = 0, y1 = 0;
            double sum_before = 0, sum_after = 0;
            for (uint32_t y = 0; y < h; ++y)
                for (uint32_t x = 0; x < w; ++x) {
                    const uint8_t *a = trace_before + 4 * ((size_t)y * w + x), *b = after + 4 * ((size_t)y * w + x);
                    if (a[0] != b[0] || a[1] != b[1] || a[2] != b[2]) {
                        ++changed;
                        sum_before += a[0] + a[1] + a[2];
                        sum_after += b[0] + b[1] + b[2];
                        if (x < x0) x0 = x;
                        if (y < y0) y0 = y;
                        if (x > x1) x1 = x;
                        if (y > y1) y1 = y;
                    }
                }
            if (changed)
                void_log("[trace]   changed %u px in (%u,%u)-(%u,%u), mean rgb %.1f -> %.1f", changed, x0, y0, x1, y1,
                    sum_before / (3.0 * changed), sum_after / (3.0 * changed));
            else
                void_log("[trace]   changed nothing");
        }
        free(after);
    }
    return 1;
}

/* ---------------------------------------------------------------- clear */
void d3d_gl_clear(d3d_device *d, uint32_t count, uint32_t rects, uint32_t flags, uint32_t color, float z, uint32_t stencil)
{
#ifndef VOID_ANDROID_APP
    if (void_shader_warming) return;
#endif
    d3d_gl_bind_targets(d);
    if (tracing(d)) void_log("[trace] clear flags %X color %08X z %g stencil %u rects %u", flags, color, z, stencil, count);
    GLbitfield mask = 0;
    if ((flags & 1u) && d->rt[0]) {
        mask |= GL_COLOR_BUFFER_BIT;
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        for (int i = 1; i < 4; ++i) glColorMaski((GLuint)i, GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        glClearColor(((color >> 16) & 255) / 255.0f, ((color >> 8) & 255) / 255.0f, (color & 255) / 255.0f, (color >> 24) / 255.0f);
    }
    if ((flags & 2u) && d->ds) { mask |= GL_DEPTH_BUFFER_BIT; glDepthMask(GL_TRUE); glClearDepthf(z); }
    if ((flags & 4u) && d->ds && d->ds->fmt && d->ds->fmt->stencil) { mask |= GL_STENCIL_BUFFER_BIT; glStencilMask(0xFF); glClearStencil((GLint)stencil); }
    if (!mask) return;
    /* The cleared area is the viewport, narrowed by the scissor and rects. */
    int vx = (int)d->st.viewport[0], vy = (int)d->st.viewport[1];
    int vx2 = vx + (int)d->st.viewport[2], vy2 = vy + (int)d->st.viewport[3];
    if (d->st.rs[174]) {
        int sx = (int)d->st.scissor[0], sy = (int)d->st.scissor[1];
        int sx2 = sx + (int)d->st.scissor[2], sy2 = sy + (int)d->st.scissor[3];
        if (sx > vx) vx = sx;
        if (sy > vy) vy = sy;
        if (sx2 < vx2) vx2 = sx2;
        if (sy2 < vy2) vy2 = sy2;
    }
    glEnable(GL_SCISSOR_TEST);
    if (!count || !rects) {
        if (vx2 > vx && vy2 > vy) {
            int cx = vx, cy = vy, cw = vx2 - vx, ch = vy2 - vy;
            scale_rect(&cx, &cy, &cw, &ch);
            glScissor(cx, cy, cw, ch);
            glClear(mask);
        }
    } else {
        for (uint32_t i = 0; i < count; ++i) {
            int x1 = (int)MEM32(rects + 16 * i), y1 = (int)MEM32(rects + 16 * i + 4);
            int x2 = (int)MEM32(rects + 16 * i + 8), y2 = (int)MEM32(rects + 16 * i + 12);
            if (x1 < vx) x1 = vx;
            if (y1 < vy) y1 = vy;
            if (x2 > vx2) x2 = vx2;
            if (y2 > vy2) y2 = vy2;
            if (x2 <= x1 || y2 <= y1) continue;
            int cx = x1, cy = y1, cw = x2 - x1, ch = y2 - y1;
            scale_rect(&cx, &cy, &cw, &ch);
            glScissor(cx, cy, cw, ch);
            glClear(mask);
        }
    }
    glDisable(GL_SCISSOR_TEST);
    d3d_gl_invalidate_state();   /* changed the colour/depth/stencil masks and scissor */
}

/* -------------------------------------------------------- blits and reads */
void d3d_gl_blit(d3d_surface *src, const uint32_t *sr, d3d_surface *dst, const uint32_t *dr, uint32_t filter)
{
#ifndef VOID_ANDROID_APP
    if (void_shader_warming) return;
#endif
    if (g_d3d_device && tracing(g_d3d_device)) {
        GLboolean cm[4];
        glGetBooleanv(GL_COLOR_WRITEMASK, cm);
        void_log("[trace] blit %ux%u fmt %u (%u,%u,%u,%u) -> %ux%u fmt %u (%u,%u,%u,%u) colour mask was %d%d%d%d", src->width,
            src->height, src->format, sr[0], sr[1], sr[2], sr[3], dst->width, dst->height, dst->format, dr[0], dr[1], dr[2], dr[3],
            cm[0], cm[1], cm[2], cm[3]);
        trace_dump(g_d3d_device, src, "blit source");
    }
    if (!read_fbo) { glGenFramebuffers(1, &read_fbo); glGenFramebuffers(1, &draw_fbo); }
    int depth = src->fmt && src->fmt->depth;
    GLenum attachment = depth ? depth_attachment(src) : GL_COLOR_ATTACHMENT0;
    /* A destination the main framebuffer holds is written through it: Mali
     * keeps a clear of that framebuffer pending as the load operation of
     * its render pass and resolves it when the pass ends, after - and over -
     * writes made through other framebuffers (Mali-G76 r26p0). */
    d3d_device *dev = g_d3d_device;
    int slot = -1;
    if (dev) {
        if (depth) slot = dev->ds == dst ? 4 : -1;
        else for (int i = 0; i < 4; ++i) if (dev->rt[i] == dst) slot = i;
    }
    if (slot >= 0) {
        d3d_gl_bind_targets(dev);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, fbo);
        if (slot < 4) {
            GLenum bufs[4] = { GL_NONE, GL_NONE, GL_NONE, GL_NONE };
            bufs[slot] = GL_COLOR_ATTACHMENT0 + (GLenum)slot;
            glDrawBuffers(slot + 1, bufs);
        }
    } else {
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, draw_fbo);
        attach(GL_DRAW_FRAMEBUFFER, depth ? depth_attachment(dst) : GL_COLOR_ATTACHMENT0, dst);
    }
    if (dst->container && dst->level == 0 && (dst->container->usage & D3DUSAGE_AUTOGENMIPMAP)) dst->container->mips_dirty = 1;
    glBindFramebuffer(GL_READ_FRAMEBUFFER, read_fbo);
    attach(GL_READ_FRAMEBUFFER, attachment, src);
    glDisable(GL_SCISSOR_TEST);
    /* StretchRect ignores the write masks; some GL drivers apply them to
     * blits. The next draw re-applies the D3D masks. */
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glDepthMask(GL_TRUE);
    glStencilMask(0xFF);
    d3d_gl_invalidate_state();   /* the next draw re-applies the D3D masks/scissor */
    GLbitfield mask = depth ? (GL_DEPTH_BUFFER_BIT | (src->fmt->stencil ? GL_STENCIL_BUFFER_BIT : 0)) : GL_COLOR_BUFFER_BIT;
    GLint gs[4], gd[4];
    d3d_surface_gl_rect(src, sr, gs);
    d3d_surface_gl_rect(dst, dr, gd);
    /* A rescaling blit filters even where the game asked for none: a
     * picture drawn larger goes into a target that is not, or back. */
    int rescales = (gs[2] - gs[0]) * (int)(dr[2] - dr[0]) != (gd[2] - gd[0]) * (int)(sr[2] - sr[0]) && !depth;
    glBlitFramebuffer(gs[0], gs[1], gs[2], gs[3], gd[0], gd[1], gd[2], gd[3],
        mask, (!depth && (filter >= 2 || rescales)) ? GL_LINEAR : GL_NEAREST);
    GLenum e = glGetError();
    if (e) void_log("[gl] StretchRect %ux%u fmt %u -> %ux%u fmt %u error %04X", src->width, src->height, src->format,
        dst->width, dst->height, dst->format, e);
    if (g_d3d_device && tracing(g_d3d_device)) {
        GLenum rs = glCheckFramebufferStatus(GL_READ_FRAMEBUFFER), ds = glCheckFramebufferStatus(GL_DRAW_FRAMEBUFFER);
        GLint rb = 0, db = 0;
        glGetIntegerv(GL_READ_BUFFER, &rb);
        glGetIntegerv(GL_DRAW_BUFFER0, &db);
        void_log("[trace]   blit read fb %04X buffer %04X, draw fb %04X buffer %04X", rs, rb, ds, db);
        trace_dump(g_d3d_device, dst, "blit result");
    }
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    if (g_d3d_device) g_d3d_device->fbo_dirty = 1;
}

/* Logical RGBA of rect (x0, y0, x1, y1) of a GPU surface: storage rows are
 * D3D rows, so the rect reads unchanged. Returns 0 if GL cannot read it. */
int d3d_gl_read_rgba(d3d_surface *s, const uint32_t *r, float *out)
{
    if (!s->fmt || s->fmt->depth || !s->fmt->internal) return 0;
    if (!read_fbo) { glGenFramebuffers(1, &read_fbo); glGenFramebuffers(1, &draw_fbo); }
    glBindFramebuffer(GL_READ_FRAMEBUFFER, read_fbo);
    attach(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, s);
    glReadBuffer(GL_COLOR_ATTACHMENT0);
    GLsizei w = (GLsizei)(r[2] - r[0]), h = (GLsizei)(r[3] - r[1]);
    GLint g[4];
    d3d_surface_gl_rect(s, r, g);
    GLsizei gw = g[2] - g[0], gh = g[3] - g[1];
    int scaled = gw != w || gh != h;
    float *dest = scaled ? (float *)malloc((size_t)gw * (size_t)gh * 16) : out;
    int ok = glCheckFramebufferStatus(GL_READ_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE && gw > 0 && gh > 0;
    if (ok) {
        while (glGetError()) {}
        if (s->fmt->is_float) {
            glReadPixels(g[0], g[1], gw, gh, GL_RGBA, GL_FLOAT, dest);
        } else {
            uint8_t *tmp = (uint8_t *)malloc((size_t)gw * (size_t)gh * 4);
            glReadPixels(g[0], g[1], gw, gh, GL_RGBA, GL_UNSIGNED_BYTE, tmp);
            d3d_gl_layout_to_rgba(GL_RGBA, GL_UNSIGNED_BYTE, tmp, (uint32_t)(gw * gh), dest);
            free(tmp);
        }
        ok = glGetError() == GL_NO_ERROR;
    }
    if (scaled) {
        if (ok) d3d_rgba_resample(dest, (uint32_t)gw, (uint32_t)gh, out, (uint32_t)w, (uint32_t)h);
        free(dest);
    }
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    if (g_d3d_device) g_d3d_device->fbo_dirty = 1;
    if (!ok) return 0;
    /* Standalone GPU surfaces are stored like render targets (d3d_surface_new). */
    uint32_t usage = s->container ? s->container->usage : (s->usage | D3DUSAGE_RENDERTARGET);
    GLint sw[4];
    d3d_storage_swizzle(s->fmt, usage, sw);
    d3d_swizzle_rgba(sw, out, (uint32_t)(w * h));
    return 1;
}

/* A whole GPU surface into guest memory in its own format (LockRect). */
void d3d_gl_read_surface(d3d_surface *src, uint32_t dst_mem, uint32_t dst_pitch)
{
    uint32_t w = src->width, h = src->height, rect[4] = { 0, 0, w, h };
    float *px = (float *)malloc((size_t)w * h * 16);
    if (!d3d_gl_read_rgba(src, rect, px)) {
        void_log("[gl] surface %ux%u format %u cannot be read back", w, h, src->format);
        for (uint32_t y = 0; y < h; ++y) memset(GPTR(dst_mem + y * dst_pitch), 0, dst_pitch);
    } else {
        for (uint32_t y = 0; y < h; ++y)
            if (!d3d_format_encode(src->format, px + (size_t)y * w * 4, w, (uint8_t *)GPTR(dst_mem + y * dst_pitch))) {
                void_log("[gl] read back of format %u unsupported", src->format);
                break;
            }
    }
    free(px);
}

void d3d_gl_fill(d3d_surface *dst, const uint32_t *r, uint32_t color)
{
    if (!read_fbo) { glGenFramebuffers(1, &read_fbo); glGenFramebuffers(1, &draw_fbo); }
    glBindFramebuffer(GL_FRAMEBUFFER, draw_fbo);
    attach(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, dst);
    glEnable(GL_SCISSOR_TEST);
    GLint g[4];
    d3d_surface_gl_rect(dst, r, g);
    glScissor(g[0], g[1], g[2] - g[0], g[3] - g[1]);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glClearColor(((color >> 16) & 255) / 255.0f, ((color >> 8) & 255) / 255.0f, (color & 255) / 255.0f, (color >> 24) / 255.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glDisable(GL_SCISSOR_TEST);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    if (g_d3d_device) g_d3d_device->fbo_dirty = 1;
    d3d_gl_invalidate_state();   /* changed the colour mask and scissor */
}

/* --------------------------------------------------------------- present */
void d3d_gl_dump_frame(d3d_device *dev, const char *path)
{
    d3d_surface *bb = dev->backbuffer;
    uint32_t w, h;
    d3d_surface_gl_size(bb, &w, &h);
    uint8_t *px = (uint8_t *)malloc((size_t)w * h * 4);
    if (!read_fbo) { glGenFramebuffers(1, &read_fbo); glGenFramebuffers(1, &draw_fbo); }
    glBindFramebuffer(GL_READ_FRAMEBUFFER, read_fbo);
    attach(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, bb);
    glReadPixels(0, 0, (GLsizei)w, (GLsizei)h, GL_RGBA, GL_UNSIGNED_BYTE, px);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    dev->fbo_dirty = 1;
    FILE *f = fopen(path, "wb");
    if (f) {
        uint32_t row = w * 3, pad = (4 - row % 4) % 4, size = 54 + (row + pad) * h;
        uint8_t header[54] = { 'B', 'M' };
        memcpy(header + 2, &size, 4);
        uint32_t v = 54; memcpy(header + 10, &v, 4);
        v = 40; memcpy(header + 14, &v, 4);
        memcpy(header + 18, &w, 4); memcpy(header + 22, &h, 4);
        header[26] = 1; header[28] = 24;
        fwrite(header, 1, 54, f);
        uint8_t zero[4] = {0};
        /* BMP rows run bottom-up; the backbuffer's row 0 is the top. */
        for (uint32_t y = h; y-- > 0;) {
            for (uint32_t x = 0; x < w; ++x) {
                uint8_t *p = px + ((size_t)y * w + x) * 4;
                uint8_t bgr[3] = { p[2], p[1], p[0] };
                fwrite(bgr, 1, 3, f);
            }
            fwrite(zero, 1, pad, f);
        }
        fclose(f);
        void_log("[gl] frame %u written to %s", dev->frame, path);
    }
    free(px);
}

static volatile int dump_requested;

/* Dump the next presented frame (scripted "shot"). */
void d3d_request_frame_dump(void) { dump_requested = 1; }

static double present_period_ns;

/* Frames a second the game is shown at (0 before the second frame). */
double void_present_rate(void) { return present_period_ns > 0 ? 1e9 / present_period_ns : 0; }

static uint32_t frames_presented;
uint32_t void_frames_presented(void) { return frames_presented; }

void d3d_gl_present(d3d_device *dev)
{
#ifndef VOID_ANDROID_APP
    if (void_shader_warming) return;
#endif
    if (camera_frames) {
        void_log("[camera] frame %u at %.2f ms: %.4f %.4f %.4f %.4f%s", dev->frame, (double)void_monotonic_ns() / 1e6,
            camera_w[0], camera_w[1], camera_w[2], camera_w[3], camera_taken ? "" : " (no 3D draw)");
        camera_taken = 0;
        --camera_frames;
    }
    static uint64_t frame_draws_start;
    uint32_t this_draws = (uint32_t)(draw_calls - frame_draws_start);
    void_hud_present(this_draws);
    frame_draws_start = draw_calls;
    d3d_shader_warm_step();
    static struct timespec fps_start, cpu_start;
    static uint64_t wait_start, draws_start, swap_start_ns;
    static uint32_t fps_frame;
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    /* A frame shown long after the last one: a page or a scene loading,
     * a hitch in play. */
    static uint64_t last_present_ns, slowest_ns;
    static uint32_t hitches;   /* frames shown 50 ms or more after the last, in this statistics window */
    uint64_t now_ns = (uint64_t)now.tv_sec * 1000000000u + (uint64_t)now.tv_nsec;
    if (last_present_ns) {
        uint64_t interval = now_ns - last_present_ns;
        if (interval > slowest_ns) slowest_ns = interval;
        if (interval >= 50000000u) ++hitches;
    }
    if (last_present_ns && now_ns - last_present_ns >= 250000000u)
        void_log("[gl] long frame %u: %.0f ms, %u draws", dev->frame,
                 (double)(now_ns - last_present_ns) / 1e6, this_draws);
    else if (last_present_ns) {
        /* The rate frames are shown at, smoothed over some ten frames (the
         * physics' step follows it, physx.c); a long frame is no rate. */
        double period = (double)(now_ns - last_present_ns);
        present_period_ns = present_period_ns > 0 ? present_period_ns + (period - present_period_ns) * 0.1 : period;
    }
    last_present_ns = now_ns;
    ++frames_presented;
    /* Every 600 frames, or every 5 s when frames are slow. */
    if (dev->frame - fps_frame >= 600 || !fps_start.tv_sec || now.tv_sec - fps_start.tv_sec >= 5) {
        struct timespec cpu;
        clock_gettime(CLOCK_THREAD_CPUTIME_ID, &cpu);
        uint64_t wait = void_lock_wait_ns();
        double dt = (double)(now.tv_sec - fps_start.tv_sec) + (double)(now.tv_nsec - fps_start.tv_nsec) / 1e9;
        double dcpu = (double)(cpu.tv_sec - cpu_start.tv_sec) + (double)(cpu.tv_nsec - cpu_start.tv_nsec) / 1e9;
        uint32_t frames = dev->frame - fps_frame;
        if (fps_start.tv_sec && frames)
            void_log("[gl] frame %u: %.1f fps; per frame %.1f ms wall, %.1f ms cpu, %.1f ms machine wait, %.0f draws, "
                "%.1f ms swap; slowest %.0f ms, %u over 50 ms", dev->frame, frames / dt, 1000.0 * dt / frames,
                1000.0 * dcpu / frames, (double)(wait - wait_start) / 1e6 / frames,
                (double)(draw_calls - draws_start) / frames, (double)(swap_ns - swap_start_ns) / 1e6 / frames,
                (double)slowest_ns / 1e6, hitches);
        slowest_ns = 0;
        hitches = 0;
        if (fps_start.tv_sec && frames) void_thunk_stats(frames);
        draws_start = draw_calls;
        swap_start_ns = swap_ns;
        fps_start = now;
        cpu_start = cpu;
        wait_start = wait;
        fps_frame = dev->frame;
    }
    if (tracing(dev)) {
        if (trace_rt && trace_rt != dev->backbuffer) trace_dump(dev, trace_rt, "target done");
        trace_dump(dev, dev->backbuffer, "present");
        trace_rt = NULL;
        void_log("[trace] frame %u presented", dev->frame);
    }
    if (dump_requested) {
        dump_requested = 0;
        char path[1100];
        snprintf(path, sizeof path, "%s/frames", void_data_dir());
        mkdir(path, 0775);
        snprintf(path, sizeof path, "%s/frames/shot_%05u.bmp", void_data_dir(), dev->frame);
        d3d_gl_dump_frame(dev, path);
    }
    if (dump_every && dev->frame % (uint32_t)dump_every == 0) {
        char path[1100];
        snprintf(path, sizeof path, "%s/frames", void_data_dir());
        mkdir(path, 0775);
        snprintf(path, sizeof path, "%s/frames/frame_%05u.bmp", void_data_dir(), dev->frame);
        d3d_gl_dump_frame(dev, path);
    }
    if (window_mode) follow_window();
    if (window_mode && egl_surface != EGL_NO_SURFACE && void_hud_picture_held()) {
        /* The window keeps the picture it shows (void_hud_hold_picture); the
         * frame is drawn all the same, paced as a vertical blank would. */
        struct timespec rest = { 0, 8000000 };
        glFlush();
        void_blocking_begin();
        nanosleep(&rest, NULL);
        void_blocking_end();
    } else if (window_mode && egl_surface != EGL_NO_SURFACE) {
        EGLint sw = 0, sh = 0;
        eglQuerySurface(egl_display, egl_surface, EGL_WIDTH, &sw);
        eglQuerySurface(egl_display, egl_surface, EGL_HEIGHT, &sh);
        d3d_surface *bb = dev->backbuffer;
        if (!read_fbo) { glGenFramebuffers(1, &read_fbo); glGenFramebuffers(1, &draw_fbo); }
        glBindFramebuffer(GL_READ_FRAMEBUFFER, read_fbo);
        attach(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, bb);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
        glDisable(GL_SCISSOR_TEST);
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        glClearColor(0, 0, 0, 1);
        glClear(GL_COLOR_BUFFER_BIT);
        /* Fit with the original aspect ratio; flip rows to the window's. */
        uint32_t bw, bh;
        d3d_surface_gl_size(bb, &bw, &bh);
        float scale = fminf((float)sw / (float)bw, (float)sh / (float)bh);
        int dw = (int)((float)bw * scale), dh = (int)((float)bh * scale);
        int dx = (sw - dw) / 2, dy = (sh - dh) / 2;
        glBlitFramebuffer(0, 0, (GLint)bw, (GLint)bh, dx, dy + dh, dx + dw, dy, GL_COLOR_BUFFER_BIT, GL_LINEAR);
        /* A still menu is shown at a lower rate (void_hud_frame_period): the
         * game's loop waits here instead of drawing the same picture again.
         * The wait ends a little before the period is up, so the swap still
         * meets the vertical blank that completes it. */
        static uint64_t paced_end, limit_next;
        uint32_t limit_period;
        int interval = frame_limit_plan(&limit_period);
        if (interval != swap_interval_set) {
            eglSwapInterval(egl_display, interval);
            swap_interval_set = interval;
        }
        static uint32_t limit_logged = UINT32_MAX;
        uint32_t limit_state = (uint32_t)interval << 24 | limit_period;
        if (limit_state != limit_logged && atomic_load(&frame_limit_hz)) {
            limit_logged = limit_state;
            void_log("[gl] frame limit %u on a %.1f Hz display: %s", atomic_load(&frame_limit_hz),
                atomic_load(&display_refresh_mhz) / 1000.0, interval > 1 ? "a frame each few refreshes"
                : limit_period ? "paced by the clock" : "the display's own rate");
        }
        uint32_t period = void_hud_frame_period();
        if (period != period_logged) {
            period_logged = period;
            void_log("[gl] still menu: %s", period ? "a frame each period" : "full rate");
        }
        /* A limit no swap interval keeps: frames a period apart on average,
         * on a timeline the waits do not reset (a slow frame starts it again). */
        if (limit_period && !period) {
            struct timespec now;
            clock_gettime(CLOCK_MONOTONIC, &now);
            uint64_t t = (uint64_t)now.tv_sec * 1000000000ull + (uint64_t)now.tv_nsec, step = (uint64_t)limit_period * 1000ull;
            if (limit_next > t + 1000000ull && limit_next - t < 100000000ull) {
                struct timespec rest = { 0, (long)(limit_next - t - 1000000ull) };
                void_blocking_begin();
                nanosleep(&rest, NULL);
                void_blocking_end();
                t = limit_next - 1000000ull;
            }
            limit_next = limit_next && t < limit_next + step ? limit_next + step : t + step;
        } else {
            limit_next = 0;
        }
        if (period && paced_end) {
            struct timespec now;
            clock_gettime(CLOCK_MONOTONIC, &now);
            uint64_t t = (uint64_t)now.tv_sec * 1000000000ull + (uint64_t)now.tv_nsec;
            uint64_t until = paced_end + (uint64_t)period * 1000ull - 4000000ull;
            if (t < until && until - t < 100000000ull) {
                struct timespec rest = { 0, (long)(until - t) };
                void_blocking_begin();
                nanosleep(&rest, NULL);
                void_blocking_end();
            }
        }
        /* The swap waits for vsync: let other guest threads run meanwhile. */
        struct timespec swap_start, swap_end;
        clock_gettime(CLOCK_MONOTONIC, &swap_start);
        void_blocking_begin();
        eglSwapBuffers(egl_display, egl_surface);
        void_blocking_end();
        clock_gettime(CLOCK_MONOTONIC, &swap_end);
        swap_ns += (uint64_t)(swap_end.tv_sec - swap_start.tv_sec) * 1000000000ull + (uint64_t)swap_end.tv_nsec -
                   (uint64_t)swap_start.tv_nsec;
        paced_end = (uint64_t)swap_end.tv_sec * 1000000000ull + (uint64_t)swap_end.tv_nsec;
        glBindFramebuffer(GL_FRAMEBUFFER, fbo);
        dev->fbo_dirty = 1;
    } else {
        glFlush();
    }
    d3d_gl_invalidate_state();   /* the window blit changed the mask/scissor; the next frame re-applies */
    void_android_frame_presented();
}
