"""Exercise production sampler creation and caps against optional anisotropy GL."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_x86_incremental import compiler_environment


def main():
    out = ROOT / "build/sampler-limits-test"
    out.mkdir(parents=True, exist_ok=True)
    gl = (ROOT / "android/host/d3d9_gl.c").read_text()
    device = (ROOT / "android/host/d3d9_device.c").read_text()
    internal = (ROOT / "android/host/d3d9_internal.h").read_text()
    limits = re.search(r"^typedef struct .* d3d_gl_limits_t;$", internal, re.M).group()
    init = gl[gl.index("    GLint extensions = 0;"):gl.index("    const char *no_s3tc")]
    samplers = gl[gl.index("typedef struct { uint32_t key[9];"):gl.index("/* What each texture unit")]
    caps = re.search(r"static const char pc_caps_hex\[\] =.*?;", device, re.S).group()
    caps += "\n" + re.search(r"static int hex_digit.*?\n", device).group()
    caps += "\n" + re.search(r"static void fill_caps\(.*?\n\}", device, re.S).group()
    (out / "production.h").write_text(limits + "\nstatic d3d_gl_limits_t d3d_gl_limits;\n"
        + "static struct { int astc; } d3d_gl_caps;\nstatic void init_limits(void) {\n" + init + "}\n"
        + samplers + "\n" + caps)
    (out / "probe.c").write_text(r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef unsigned GLuint, GLenum;
typedef int GLint;
typedef float GLfloat;
#define GL_REPEAT 0x2901
#define GL_MIRRORED_REPEAT 0x8370
#define GL_CLAMP_TO_EDGE 0x812F
#define GL_CLAMP_TO_BORDER_EXT 0x812D
#define GL_TEXTURE_WRAP_S 0x2802
#define GL_TEXTURE_WRAP_T 0x2803
#define GL_TEXTURE_WRAP_R 0x8072
#define GL_TEXTURE_BORDER_COLOR_EXT 0x1004
#define GL_TEXTURE_MAG_FILTER 0x2800
#define GL_TEXTURE_MIN_FILTER 0x2801
#define GL_NEAREST 0x2600
#define GL_LINEAR 0x2601
#define GL_NEAREST_MIPMAP_NEAREST 0x2700
#define GL_LINEAR_MIPMAP_NEAREST 0x2701
#define GL_NEAREST_MIPMAP_LINEAR 0x2702
#define GL_LINEAR_MIPMAP_LINEAR 0x2703
#define GL_TEXTURE_MAX_ANISOTROPY_EXT 0x84FE
#define GL_MAX_TEXTURE_MAX_ANISOTROPY_EXT 0x84FF
#define GL_TEXTURE_MIN_LOD 0x813A
#define GL_NUM_EXTENSIONS 0x821D
#define GL_EXTENSIONS 0x1F03
static uint32_t caps[76];
#define MEM8(a) (((uint8_t *)caps)[a])
#define MEM32(a) (caps[(a) / 4])
static int supported, queries, parameters;
static float driver_max, parameter;
static void glGetIntegerv(GLenum name, GLint *value) { assert(name == GL_NUM_EXTENSIONS); *value = 2; }
static const unsigned char *glGetStringi(GLenum name, GLuint i) {
    assert(name == GL_EXTENSIONS && i < 2);
    return (const unsigned char *)(i ? "GL_EXT_texture_border_clamp" : supported
        ? "GL_EXT_texture_filter_anisotropic" : "GL_EXT_texture_filter_anisotropic2");
}
static void glGetFloatv(GLenum name, GLfloat *value) {
    assert(supported && name == GL_MAX_TEXTURE_MAX_ANISOTROPY_EXT); ++queries; *value = driver_max;
}
static void glGenSamplers(GLint n, GLuint *sampler) { static GLuint next; assert(n == 1); *sampler = ++next; }
static void glDeleteSamplers(GLint n, const GLuint *sampler) { assert(n == 1 && *sampler); }
static void glSamplerParameteri(GLuint sampler, GLenum name, GLint value) { assert(sampler && name && value); }
static void glSamplerParameterfv(GLuint sampler, GLenum name, const GLfloat *value) {
    assert(sampler && name == GL_TEXTURE_BORDER_COLOR_EXT && value);
}
static void glSamplerParameterf(GLuint sampler, GLenum name, GLfloat value) {
    assert(sampler);
    if (name == GL_TEXTURE_MAX_ANISOTROPY_EXT) {
        assert(supported && value >= 1 && value <= driver_max); ++parameters; parameter = value;
    } else assert(name == GL_TEXTURE_MIN_LOD);
}
#include "production.h"
static void reset_driver(int support, float maximum) {
    supported = support; driver_max = maximum; queries = parameters = sampler_count = 0;
    memset(&d3d_gl_limits, 0, sizeof d3d_gl_limits); init_limits(); fill_caps(0);
}
static void sample(uint32_t min, uint32_t mag, uint32_t requested, int no_filter) {
    uint32_t ss[14] = {0}; ss[1] = ss[2] = ss[3] = 1; ss[5] = mag; ss[6] = min; ss[10] = requested;
    assert(sampler_for(ss, no_filter, 1, 0));
}
int main(void) {
    fill_caps(0); assert(MEM32(108) == 16);
    reset_driver(0, 4); assert(!queries && MEM32(108) == 1);
    sample(3, 3, 16, 0); sample(2, 2, 4, 0); assert(!parameters);
    reset_driver(1, 4); assert(queries == 1 && MEM32(108) == 4);
    sample(3, 3, 16, 0); assert(parameters == 1 && parameter == 4);
    sample(3, 3, 2, 0); assert(parameter == 2);
    sample(2, 3, 4, 0); assert(parameter == 4);
    sample(2, 2, 16, 0); assert(parameter == 1);
    sample(3, 3, 0, 0); assert(parameter == 1);
    sample(3, 3, 16, 1); assert(parameters == 6 && parameter == 1);
    sample(3, 3, 16, 1); assert(parameters == 6);
    reset_driver(1, 32); sample(3, 3, 32, 0); assert(parameter == 32 && MEM32(108) == 16);
    puts("PASS: optional anisotropy enum/query, driver clamp, linear fallback, sampler reuse and D3D caps");
    return 0;
}
''')
    compiler, env, _ = compiler_environment()
    build = subprocess.run([str(compiler), "/nologo", "/O2", "/W3", "/std:c11", str(out / "probe.c"),
                            "/Fo" + str(out / "probe.obj"), "/Fe" + str(out / "probe.exe")],
                           env=env, capture_output=True, text=True)
    (out / "build.log").write_text(build.stdout + build.stderr)
    assert build.returncode == 0, build.stdout + build.stderr
    run = subprocess.run([str(out / "probe.exe")], capture_output=True, text=True, timeout=15)
    (out / "result.txt").write_text(run.stdout + run.stderr)
    assert run.returncode == 0, run.stdout + run.stderr
    print(run.stdout, end="")


if __name__ == "__main__":
    main()
