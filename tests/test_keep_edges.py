"""Enlarged 2D pictures keep their edges: the shipping sampler analysis and
texture-coordinate check (android/host/d3d9_shader.c, d3d9_gl.c) decide which
samplers clamp to the edge. Pixel shaders are the GLSL MojoShader made for
the hearts screen's own draws (trace of 2026-10-25) and constructed cases."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_x86_incremental import compiler_environment


def function(source, name):
    return re.search(r"^static (?:int|uint32_t) " + name + r"\([^)]*\)\n\{.*?^\}", source, re.M | re.S).group()


HEADER = r'''
#include <ctype.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef struct { uint16_t stream, offset; uint8_t type, method, usage, usage_index; } d3d_vertex_element;
typedef struct { int count; d3d_vertex_element elements[64]; } d3d_decl;
typedef struct { uint32_t size, format, shadow; } d3d_buffer;
typedef struct { struct { void *decl, *streams[16], *indices; uint32_t stream_offset[16], stream_stride[16];
    uint32_t tss[8][33]; } st; } d3d_device;
static uint8_t guest[1 << 16];
#define GPTR(a) ((void *)(guest + (a)))
'''

TESTS = r'''
#define CHECK(x) do { if (!(x)) { printf("failed line %d: %s\n", __LINE__, #x); return 1; } } while (0)
static const char ui_413[] = "uniform sampler2D ps_s0;\nin highp vec4 io_5_0;\n#define ps_v0 io_5_0\n"
    "void main()\n{\n\tps_r0 = texture2D(ps_s0, ps_v0.xy);\n\tps_oC0.xyz = ps_r0.xyz * ps_c1.xyz;\n}\n";
static const char ui_110[] = "#define texture2D texture\n#define texture2DLod textureLod\n"
    "in highp vec4 io_5_0;\n#define ps_v0 io_5_0\nin highp vec4 io_5_1;\n#define ps_v1 io_5_1\n"
    "void main()\n{\n\tps_r0 = texture2D(ps_s0, ps_v0.xy);\n\tps_r1 = texture2D(ps_s1, ps_v1.xy);\n}\n";
static const char ps11_31[] = "in highp vec4 io_5_0;\nvec4 ps_t0;\nvoid main()\n{\n\tps_t0 = io_5_0;\n\n"
    "\tps_t0 = texture2D(ps_s0, ps_t0.xy);\n\tps_r0 = ps_t0;\n}\n";
/* The distortion pass: s1 at a computed coordinate, s0 also at a clamped copy. */
static const char post_3481[] = "in highp vec4 io_5_0;\n#define ps_v0 io_5_0\nin highp vec4 io_5_1;\n#define ps_v1 io_5_1\n"
    "void main()\n{\n\tps_r0 = texture2D(ps_s2, ps_v1.xy);\n\tps_r1 = texture2D(ps_s0, ps_v0.xy);\n"
    "\tps_r0.xy = clamp((ps_r0.xy * ps_c0.zz) + ps_v0.xy, vec2(0.0), vec2(1.0));\n"
    "\tps_r0 = texture2D(ps_s1, ps_r0.xy);\n\tps_r1.xy = clamp(ps_v0.xy, vec2(0.0), vec2(1.0));\n"
    "\tps_r1 = texture2D(ps_s0, ps_r1.xy);\n}\n";
static const char computed[] = "in highp vec4 io_5_0;\n#define ps_v0 io_5_0\nin highp vec4 io_10_0;\n#define ps_v1 io_10_0\n"
    "void main()\n{\n\ta = texture2D(ps_s0, ps_v0.xy * 4.0);\n\tb = texture2D(ps_s1, ps_v0.zw);\n"
    "\tc = texture2DLod(ps_s2, ps_v0.xy, 0.0);\n\td = texture2D(ps_s3, ps_v1.xy);\n\te = textureCube(ps_s4, ps_v0.xyz);\n"
    "\tf = texture2D( ps_s5 , ps_v0.xy );\n\tg = texture2D(ps_s12, ps_v0.xy);\n}\n";

static d3d_buffer vb, ib;
static d3d_decl decl;
static d3d_device dev;

/* A quad of 4 vertices, POSITIONT + TEXCOORD0 (+ TEXCOORD1), u and v from lo to hi. */
static void quad(float lo, float hi, int second, float lo2, float hi2)
{
    memset(&dev, 0, sizeof dev);
    memset(&decl, 0, sizeof decl);
    decl.count = second ? 3 : 2;
    decl.elements[0] = (d3d_vertex_element){0, 0, 3, 0, 9, 0};
    decl.elements[1] = (d3d_vertex_element){0, 16, 1, 0, 5, 0};
    decl.elements[2] = (d3d_vertex_element){0, 24, 1, 0, 5, 1};
    vb.size = 4 * 32; vb.shadow = 0x1000;
    float corners[4][2] = {{0, 0}, {1, 0}, {0, 1}, {1, 1}};
    for (int i = 0; i < 4; ++i) {
        float v[8] = {0, 0, 0, 1, lo + (hi - lo) * corners[i][0], lo + (hi - lo) * corners[i][1],
                      lo2 + (hi2 - lo2) * corners[i][0], lo2 + (hi2 - lo2) * corners[i][1]};
        memcpy(guest + 0x1000 + 32 * i, v, sizeof v);
    }
    dev.st.decl = &decl;
    dev.st.streams[0] = &vb;
    dev.st.stream_stride[0] = 32;
}

static int inside(uint32_t start, uint32_t count) { return texcoords_inside(&dev, NULL, 0, start, count, 0, 0, 0, NULL, 0); }

int main(void) {
    CHECK(find_direct_samplers(ui_413) == 0x1);
    CHECK(find_direct_samplers(ui_110) == 0x3);
    CHECK(find_direct_samplers(ps11_31) == 0x1);
    CHECK(find_direct_samplers(post_3481) == 0x4);
    CHECK(find_direct_samplers(computed) == ((1u << 5) | (1u << 12)));

    quad(0, 1, 0, 0, 0);            CHECK(inside(0, 4));
    quad(0.0005f, 1.0009f, 0, 0, 0); CHECK(inside(0, 4));
    quad(0, 2, 0, 0, 0);            CHECK(!inside(0, 4));       /* tiled */
    quad(-0.25f, 0.75f, 0, 0, 0);   CHECK(!inside(0, 4));       /* scrolled */
    quad(0, 1, 1, 0, 3);            CHECK(!inside(0, 4));       /* the second set tiles */
    quad(0, 1, 1, 0.25f, 0.5f);     CHECK(inside(0, 4));
    quad(0, 1, 0, 0, 0);            CHECK(!inside(1, 4));       /* past the buffer */
    float nan; uint32_t bits = 0x7fc00000; memcpy(&nan, &bits, 4);
    memcpy(guest + 0x1000 + 32 * 2 + 16, &nan, 4);       CHECK(!inside(0, 4));
    quad(0, 1, 0, 0, 0);
    decl.count = 1;                 CHECK(!inside(0, 4));       /* no texture coordinates */
    decl.count = 2;
    vb.size = 4096 * 32;            CHECK(!inside(0, 2000));    /* too many to read */
    vb.size = 4 * 32;
    /* Indexed: 16-bit indices 0 1 2 / 2 1 3 at start 2, base vertex 0, and 32-bit ones. */
    uint16_t idx16[8] = {9, 9, 0, 1, 2, 2, 1, 3};
    memcpy(guest + 0x4000, idx16, sizeof idx16);
    ib.size = sizeof idx16; ib.shadow = 0x4000; ib.format = 101;
    dev.st.indices = &ib;
    CHECK(texcoords_inside(&dev, NULL, 0, 0, 6, 1, 0, 2, NULL, 0));
    CHECK(!texcoords_inside(&dev, NULL, 0, 0, 6, 1, 1, 2, NULL, 0));   /* base 1: vertex 4 is past the buffer */
    CHECK(!texcoords_inside(&dev, NULL, 0, 0, 8, 1, 0, 2, NULL, 0));   /* indices past the index buffer */
    uint32_t idx32[6] = {0, 1, 2, 2, 1, 3};
    CHECK(texcoords_inside(&dev, NULL, 0, 0, 6, 1, 0, 0, idx32, 1));
    /* Vertices from memory (DrawPrimitiveUP). */
    float up[4][6];
    for (int i = 0; i < 4; ++i) { float v[6] = {0, 0, 0, 1, (float)(i & 1), (float)(i >> 1)}; memcpy(up[i], v, sizeof v); }
    decl.elements[1].offset = 16;
    CHECK(texcoords_inside(&dev, up, 24, 0, 4, 0, 0, 0, NULL, 0));
    up[3][4] = 1.5f;
    CHECK(!texcoords_inside(&dev, up, 24, 0, 4, 0, 0, 0, NULL, 0));

    memset(&dev, 0, sizeof dev);
    dev.st.tss[0][11] = 0; dev.st.tss[1][11] = 1; dev.st.tss[2][11] = 0x10000; dev.st.tss[3][24] = 2;
    CHECK(ff_direct_samplers(&dev, 0xF) == 0x3);
    CHECK(ff_direct_samplers(&dev, 0x2) == 0x2);
    puts("PASS: direct samplers of 5 shaders (hearts-screen UI, ps_1_x, distortion, computed/Lod/cube/colour cases); "
         "texture coordinates inside/outside for plain, indexed (16/32-bit), memory and bounds cases; fixed-function stages");
    return 0;
}
'''


def main():
    shader = (ROOT / "android/host/d3d9_shader.c").read_text(encoding="utf-8")
    gl = (ROOT / "android/host/d3d9_gl.c").read_text(encoding="utf-8")
    source = HEADER + "\n".join([function(shader, "texcoord_input"), function(shader, "find_direct_samplers"),
                                 function(gl, "texcoords_inside"), function(gl, "ff_direct_samplers")]) + TESTS
    out = ROOT / "build/keep-edges-test"
    out.mkdir(parents=True, exist_ok=True)
    compiler, env, _ = compiler_environment()
    c = out / "keep_edges.c"
    c.write_text(source, encoding="utf-8")
    exe = out / "keep_edges.exe"
    build = subprocess.run([str(compiler), "/nologo", "/W4", "/O2", "/std:c11", "/wd4996", str(c),
                            "/Fo" + str(out / "keep_edges.obj"), "/Fe" + str(exe)], env=env, capture_output=True, text=True)
    assert build.returncode == 0, build.stdout + build.stderr
    run = subprocess.run([str(exe)], capture_output=True, text=True)
    (out / "keep_edges.log").write_text(run.stdout + run.stderr)
    assert run.returncode == 0, run.stdout + run.stderr
    print(run.stdout.strip())


if __name__ == "__main__":
    main()
