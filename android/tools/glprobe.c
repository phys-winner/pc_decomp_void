/* Headless EGL/GLES capability probe for the bring-up device. */
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl32.h>
#include <GLES2/gl2ext.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
    EGLDisplay d = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    EGLint major, minor;
    if (!eglInitialize(d, &major, &minor)) { printf("eglInitialize failed %x\n", eglGetError()); return 1; }
    printf("EGL %d.%d vendor=%s\nEGL extensions: %s\n", major, minor, eglQueryString(d, EGL_VENDOR), eglQueryString(d, EGL_EXTENSIONS));
    const EGLint attrs[] = { EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT_KHR,
        EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8, EGL_DEPTH_SIZE, 24, EGL_STENCIL_SIZE, 8, EGL_NONE };
    EGLConfig config; EGLint n = 0;
    if (!eglChooseConfig(d, attrs, &config, 1, &n) || !n) { printf("no config\n"); return 1; }
    const EGLint pb[] = { EGL_WIDTH, 64, EGL_HEIGHT, 64, EGL_NONE };
    EGLSurface s = eglCreatePbufferSurface(d, config, pb);
    const EGLint ctx_attrs[] = { EGL_CONTEXT_CLIENT_VERSION, 3, EGL_CONTEXT_MINOR_VERSION_KHR, 2, EGL_NONE };
    EGLContext c = eglCreateContext(d, config, EGL_NO_CONTEXT, ctx_attrs);
    if (c == EGL_NO_CONTEXT) { printf("no ES 3.2 context %x\n", eglGetError()); return 1; }
    eglMakeCurrent(d, s, s, c);
    printf("GL_VENDOR=%s\nGL_RENDERER=%s\nGL_VERSION=%s\nGLSL=%s\n", glGetString(GL_VENDOR), glGetString(GL_RENDERER),
        glGetString(GL_VERSION), glGetString(GL_SHADING_LANGUAGE_VERSION));
    GLint num = 0; glGetIntegerv(GL_NUM_EXTENSIONS, &num);
    printf("extensions (%d):", num);
    for (GLint i = 0; i < num; ++i) printf(" %s", glGetStringi(GL_EXTENSIONS, (GLuint)i));
    printf("\n");
    GLint v[4];
#define Q(e) glGetIntegerv(e, v); printf(#e "=%d\n", v[0]);
    Q(GL_MAX_TEXTURE_SIZE) Q(GL_MAX_CUBE_MAP_TEXTURE_SIZE) Q(GL_MAX_3D_TEXTURE_SIZE) Q(GL_MAX_TEXTURE_IMAGE_UNITS)
    Q(GL_MAX_VERTEX_TEXTURE_IMAGE_UNITS) Q(GL_MAX_VERTEX_ATTRIBS) Q(GL_MAX_VERTEX_UNIFORM_VECTORS) Q(GL_MAX_FRAGMENT_UNIFORM_VECTORS)
    Q(GL_MAX_DRAW_BUFFERS) Q(GL_MAX_COLOR_ATTACHMENTS) Q(GL_MAX_SAMPLES) Q(GL_MAX_VARYING_VECTORS) Q(GL_MAX_UNIFORM_BLOCK_SIZE)
    GLint formats = 0; glGetIntegerv(GL_NUM_COMPRESSED_TEXTURE_FORMATS, &formats);
    GLint list[256]; glGetIntegerv(GL_COMPRESSED_TEXTURE_FORMATS, list);
    printf("compressed formats (%d):", formats);
    for (GLint i = 0; i < formats && i < 256; ++i) printf(" 0x%04X", list[i]);
    printf("\n");
    return 0;
}
