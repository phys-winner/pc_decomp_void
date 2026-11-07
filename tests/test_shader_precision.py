"""Keep full-precision SM3 instructions full precision in production fragment GLSL."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_x86_incremental import compiler_environment


def main():
    out = ROOT / "build/shader-precision-test"
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / "android/host/d3d9_shader.c").read_text()
    helpers = source[source.index("static char *insert_before"):source.index("d3d_shader *d3d_shader_create")]
    warm = re.search(r"^int d3d_shader_warm_bytecode\(.*?^\}", source, re.M | re.S).group()
    repair = re.search(r"    /\* Instructions without _pp.*?^    \}\n", helpers, re.M | re.S).group()
    (out / "probe.c").write_text(r'''
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <ctype.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "mojoshader.h"
#define assert(c) do { if (!(c)) { fprintf(stderr, "failed line %d: %s\n", __LINE__, #c); exit(3); } } while (0)
typedef unsigned GLuint;
#define GL_FRAGMENT_SHADER 1
#define GL_VERTEX_SHADER 2
#define FOURCC(a,b,c,d) ((uint32_t)(a)|((uint32_t)(b)<<8)|((uint32_t)(c)<<16)|((uint32_t)(d)<<24))
typedef struct Buffer Buffer;
typedef struct {
    HRESULT (__stdcall *QueryInterface)(Buffer *, const void *, void **);
    ULONG (__stdcall *AddRef)(Buffer *);
    ULONG (__stdcall *Release)(Buffer *);
    void *(__stdcall *GetBufferPointer)(Buffer *);
    DWORD (__stdcall *GetBufferSize)(Buffer *);
} BufferVtbl;
struct Buffer { const BufferVtbl *v; };
typedef HRESULT (__stdcall *assemble_t)(const char *, UINT, const void *, void *, DWORD, Buffer **, Buffer **);
static FILE *dump;
static GLuint compile(unsigned type, const char *source) {
    assert(type == GL_FRAGMENT_SHADER && source && *source); fputs(source, dump);
    assert(strstr(source, "precision highp float;"));
    assert(!strstr(source, "precision mediump float;"));
    assert(strstr(source, "precision mediump int;"));
    assert(strstr(source, "uniform sampler2D ps_s0;"));
    assert(strstr(source, "in highp vec4 io_5_0;"));
    assert(strstr(source, "ps_r1.x + -ps_v0.z"));
    assert(strstr(source, "void_alpha_test();")); return 1;
}
static void void_log(const char *format, ...) { (void)format; }
#include "production.h"
int main(int argc, char **argv) {
    assert(argc == 2); dump = fopen(argv[1], "wb"); assert(dump);
    HMODULE dll = LoadLibraryA("d3dx9_36.dll");
    assemble_t assemble = dll ? (assemble_t)GetProcAddress(dll, "D3DXAssembleShader") : NULL;
    assert(assemble);
    const char *assembly = "ps_3_0\ndef c0, 0.99, 0, 1, 0\n"
        "dcl_texcoord v0.xyz\ndcl_2d s0\ntexld_pp r1, v0, s0\n"
        "add r0.x, r1.x, -v0.z\ncmp r0.x, r0.x, c0.z, c0.y\nmov oC0, r0.x\n";
    Buffer *shader = NULL, *errors = NULL;
    assert(SUCCEEDED(assemble(assembly, (UINT)strlen(assembly), NULL, NULL, 0, &shader, &errors)) && shader);
    uint32_t *words = shader->v->GetBufferPointer(shader);
    size_t count = shader->v->GetBufferSize(shader) / 4; int full_add = 0, partial_fetch = 0;
    assert(words[0] == 0xFFFF0300u);
    for (size_t i = 1; i < count;) {
        uint32_t opcode = words[i] & 0xffff;
        if (opcode == 0xffff) break;
        if (opcode == 0xfffe) { i += 1 + ((words[i] >> 16) & 0x7fff); continue; }
        if (opcode == 2 && !(words[i + 1] & 0x00200000)) ++full_add;
        if (opcode == 66 && (words[i + 1] & 0x00200000)) ++partial_fetch;
        i += 1 + ((words[i] >> 24) & 0xf);
    }
    assert(full_add == 1 && partial_fetch == 1);
    assert(d3d_shader_warm_bytecode(words, shader->v->GetBufferSize(shader))); fclose(dump);
    shader->v->Release(shader); if (errors) errors->v->Release(errors);
    const char *depth_only = "#version 300 es\nprecision mediump float;\nprecision mediump int;\n"
        "void main() { gl_FragDepth = 0.5; }\n";
    char *fixed = patch_source(depth_only, 1);
    assert(strstr(fixed, "precision highp float;") && strstr(fixed, "precision mediump int;")); free(fixed);
    fixed = patch_source(depth_only, 0); assert(!strcmp(fixed, depth_only)); free(fixed);
    const char *already = "#version 300 es\nprecision highp float;\nvoid main() {}\n";
    fixed = patch_source(already, 1); assert(!strcmp(fixed, already)); free(fixed);
    puts("PASS: mixed full/_pp Microsoft SM3 bytecode translated through production repair; float highp, int/samplers/vertex unchanged; depth-only covered");
    return 0;
}
''')
    compiler, env, _ = compiler_environment()
    mojo = ROOT / "reference/mojoshader"
    sources = [mojo / name for name in ("mojoshader.c", "mojoshader_common.c",
               "profiles/mojoshader_profile_common.c", "profiles/mojoshader_profile_glsl.c")]
    disabled = ["HLSL", "ARB1", "ARB1_NV", "METAL", "SPIRV", "GLSPIRV", "D3D", "BYTECODE", "GLSL120"]
    for name in ("current", "mediump"):
        body = helpers if name == "current" else helpers.replace(repair, "")
        (out / "production.h").write_text(body + "\n" + warm)
        command = [str(compiler), "/nologo", "/O2", "/w", "/std:c11", "/D_CRT_SECURE_NO_WARNINGS",
                   "/DMOJOSHADER_FLIP_RENDERTARGET", "/DMOJOSHADER_DEPTH_CLIPPING",
                   *["/DSUPPORT_PROFILE_" + feature + "=0" for feature in disabled],
                   "/I" + str(mojo), "/I" + str(out), "/I" + str(ROOT / "android/runtime"),
                   *map(str, sources), str(out / "probe.c"), "/Fo" + str(out) + "\\",
                   "/Fe" + str(out / (name + ".exe"))]
        built = subprocess.run(command, env=env, capture_output=True, text=True)
        (out / (name + "-build.log")).write_text(built.stdout + built.stderr)
        assert built.returncode == 0, built.stdout + built.stderr
        run = subprocess.run([str(out / (name + ".exe")), str(out / (name + ".frag"))],
                             capture_output=True, text=True, timeout=20)
        (out / (name + "-result.txt")).write_text(run.stdout + run.stderr)
        assert (run.returncode == 0) == (name == "current"), run.stdout + run.stderr
        print(run.stdout.strip() if name == "current" else "PASS: old mediump regression rejected")


if __name__ == "__main__":
    main()
