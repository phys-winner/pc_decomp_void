"""Execute the native shader warmup/cache with deterministic GL and real files."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_x86_incremental import compiler_environment


def main():
    out = ROOT / "build/shader-warm-test"
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / "android/host/shader_warm.c").read_text(encoding="utf-8")
    (out / "shader-warm.h").write_text(re.sub(r"^#include .*\n", "", source, flags=re.M))
    stage = (ROOT / "android/host/d3d9_shader.c").read_text(encoding="utf-8")
    cache = re.search(r"^typedef struct compiled_stage \{.*?^#define compile d3d_shader_compile_source", stage, re.M | re.S).group()
    (out / "stage-cache.h").write_text(cache)
    compiler, env, _ = compiler_environment()
    run = subprocess.run([str(compiler), "/nologo", "/O2", "/W4", "/D_CRT_SECURE_NO_WARNINGS", "/I" + str(out),
                          str(ROOT / "tests/shader_warm_probe.c"), "/Fo" + str(out / "probe.obj"),
                          "/Fe" + str(out / "probe.exe")], env=env, capture_output=True, text=True)
    (out / "build.log").write_text(run.stdout + run.stderr)
    assert run.returncode == 0, run.stdout + run.stderr
    with tempfile.TemporaryDirectory(prefix="fixtures-", dir=out) as fixtures:
        subprocess.run([str(out / "probe.exe"), fixtures], check=True)
    # Translate every unique shipped stage with the pinned Android parser and
    # the production GLSL repairs before asking a device driver to compile it.
    helpers = stage[stage.index("static char *insert_before"):stage.index("d3d_shader *d3d_shader_create")]
    warm = re.search(r"^int d3d_shader_warm_bytecode\(.*?^\}", stage, re.M | re.S).group()
    (out / "translate.h").write_text(helpers + "\n" + warm)
    (out / "translate.c").write_text(r'''
#include <assert.h>
#include <ctype.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "mojoshader.h"
typedef unsigned GLuint;
#define GL_FRAGMENT_SHADER 1
#define GL_VERTEX_SHADER 2
#define FOURCC(a,b,c,d) ((uint32_t)(a)|((uint32_t)(b)<<8)|((uint32_t)(c)<<16)|((uint32_t)(d)<<24))
static GLuint compile(unsigned type, const char *source) { assert(type && source && *source); return 1; }
static void void_log(const char *format, ...) { va_list args; va_start(args, format); vfprintf(stderr, format, args); fputc('\n', stderr); va_end(args); }
#include "translate.h"
int main(int argc, char **argv) {
    assert(argc == 2); FILE *list = fopen(argv[1], "rb"); assert(list);
    char path[1400]; unsigned count = 0;
    while (fgets(path, sizeof path, list)) {
        path[strcspn(path, "\r\n")] = 0;
        FILE *f = fopen(path, "rb"); assert(f && !fseek(f, 0, SEEK_END));
        long size = ftell(f); assert(size > 4 && !fseek(f, 0, SEEK_SET));
        void *bytes = malloc((size_t)size); assert(fread(bytes, 1, (size_t)size, f) == (size_t)size); fclose(f);
        if (!d3d_shader_warm_bytecode(bytes, (uint32_t)size)) { fprintf(stderr, "failed: %s\n", path); return 1; }
        free(bytes); ++count;
    }
    fclose(list); printf("PASS: %u unique shipped shader stages translated with production GLSL repairs\n", count); return 0;
}''')
    unique = {}
    for path in sorted((ROOT / "build/shadercache/results").glob("*.bin")):
        data = path.read_bytes()
        if len(data) >= 8 and len(data) % 4 == 0 and int.from_bytes(data[:4], "little") >> 16 in (0xfffe, 0xffff) and data[-4:] == b"\xff\xff\x00\x00":
            unique.setdefault(hashlib.sha256(data).digest(), path)
    (out / "stages.txt").write_text("".join(str(path) + "\n" for path in unique.values()))
    mojo = ROOT / "reference/mojoshader"
    disabled = ["HLSL", "ARB1", "ARB1_NV", "METAL", "SPIRV", "GLSPIRV", "D3D", "BYTECODE", "GLSL120"]
    sources = [mojo / name for name in ("mojoshader.c", "mojoshader_common.c", "profiles/mojoshader_profile_common.c", "profiles/mojoshader_profile_glsl.c")]
    run = subprocess.run([str(compiler), "/nologo", "/O2", "/w", "/D_CRT_SECURE_NO_WARNINGS", "/DMOJOSHADER_FLIP_RENDERTARGET", "/DMOJOSHADER_DEPTH_CLIPPING",
                          *["/DSUPPORT_PROFILE_" + name + "=0" for name in disabled], "/I" + str(mojo), "/I" + str(out), "/I" + str(ROOT / "android/runtime"),
                          *map(str, sources), str(out / "translate.c"), "/Fo" + str(out) + "\\", "/Fe" + str(out / "translate.exe")], env=env, capture_output=True, text=True)
    (out / "translate-build.log").write_text(run.stdout + run.stderr)
    assert run.returncode == 0, run.stdout + run.stderr
    subprocess.run([str(out / "translate.exe"), str(out / "stages.txt")], check=True)


if __name__ == "__main__":
    main()
