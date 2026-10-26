"""Actual Reset/program/uniform regression, with the old missing invalidation as a negative control."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/reset-shader-constants-test"
sys.path.insert(0, str(ROOT / "tools"))
from build_x86_incremental import compiler_environment


def sha(data):
    return hashlib.sha256(data).hexdigest()


def function(source, pattern):
    match = re.search(pattern, source, re.M)
    assert match, pattern
    start = match.start()
    brace = source.index("{", match.end())
    depth = 1
    pos = brace + 1
    while depth:
        depth += (source[pos] == "{") - (source[pos] == "}")
        pos += 1
    return source[start:pos]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    paths = [ROOT / "android/host" / name for name in
             ("d3d9_device.c", "d3d9_shader.c", "d3d9_gl.c", "d3d9_internal.h", "d3d9_ff.c", "com.h")]
    before = {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in paths}
    dev, shader, gl, internal, ff, com = [p.read_text(encoding="utf-8") for p in paths]
    increment = "    ++d3d_constant_generation;   /* Reset clears the register files cached by programs. */\n"
    assert dev.count(increment) == 1
    original = dev.replace(increment, "", 1)

    types = "\n".join(re.search(pattern, internal, re.S).group() for pattern in (
        r"typedef struct d3d_state \{.*?\} d3d_state;",
        r"typedef struct d3d_stateblock \{.*?\} d3d_stateblock;",
        r"struct d3d_device \{.*?\n\};"))
    program = shader[shader.index("typedef struct { int type, index, count; } umap_t;"):
                     shader.index("static void shader_draw_result")]
    ff_types = ff[ff.index("typedef struct {"):ff.index("static ff_vs *vs_cache;")]
    (OUT / "types.h").write_text(types + "\n" + program + "\n" + ff_types, encoding="utf-8")
    methods = ("SetVertexShader", "SetPixelShader", "SetVertexShaderConstantF", "SetVertexShaderConstantI",
               "SetVertexShaderConstantB", "SetPixelShaderConstantF", "SetPixelShaderConstantI", "SetPixelShaderConstantB", "Reset")
    shared = [function(dev, r"^static uint32_t f2u\("),
              function(dev, r"^static void set_default_viewport\("),
              function(dev, r"^void d3d_ref_set\("), "#define bind_ref d3d_ref_set",
              function(dev, r"^static void \*host_or_null\("),
              function(dev, r"^static int bind_surface\("),
              function(dev, r"^static void make_backbuffer\("),
              function(dev, r"^static d3d_state \*target_state\(")]
    shared += [dev[dev.index("#define CONST_SET"):dev.index("COM_METHOD(dev, SetVertexShaderConstantF")],
               com[com.index("#define COM_METHOD"):com.index("/* An unimplemented slot")]]
    shared += [function(dev, r"^COM_METHOD\(dev, " + name + r", \d+\)") for name in methods]
    shared += [function(shader, r"^static int shader_type_ok\("),
               function(shader, r"^static void pack\("), function(shader, r"^static void upload_vec4\("),
               function(shader, r"^static void upload_ints\("), function(shader, r"^void d3d_shader_upload\("),
               function(shader, r"^int d3d_shader_bind2\("),
               function(shader, r"^void d3d_shader_forget_current\("),
               function(gl, r"^void d3d_gl_invalidate_state\("),
               function(ff, r"^void d3d_ff_attributes\("), function(ff, r"^int d3d_ff_bind\(")]
    for label, source in (("original", original), ("fixed", dev)):
        fragments = [shared[0], function(source, r"^static void default_state\("), *shared[1:]]
        (OUT / (label + "-fragments.h")).write_text("\n\n".join(fragments), encoding="utf-8")
    compiler, env, toolchain = compiler_environment()
    runs = {}
    for label in ("original", "fixed"):
        exe = OUT / (label + ".exe")
        command = [str(compiler), "/nologo", "/O2", "/W4", "/WX", "/wd4505", "/wd4204", "/std:c11",
                   "/D_CRT_SECURE_NO_WARNINGS", '/DTEST_SOURCE="' + label + '-fragments.h"',
                   "/I" + str(OUT), "/I" + str(ROOT / "reference/mojoshader"), str(ROOT / "tests/reset_shader_constants_probe.c"),
                   "/Fo" + str(OUT / (label + ".obj")), "/Fe" + str(exe)]
        build = subprocess.run(command, env=env, capture_output=True, text=True)
        (OUT / (label + "-build.log")).write_text(build.stdout + build.stderr)
        assert build.returncode == 0, build.stdout + build.stderr
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        (OUT / (label + ".log")).write_text(run.stdout + run.stderr)
        assert (run.returncode == 0) == (label == "fixed"), run.stdout + run.stderr
        runs[label] = dict(exit_code=run.returncode, log=str(OUT / (label + ".log")),
                           summary=run.stdout.splitlines()[-1])
        print(label + ": " + runs[label]["summary"])
    after = {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in paths}
    assert before == after, "canonical input changed while staging proposal"
    receipt = dict(status="PASS; missing-invalidation negative control FAIL and production PASS on extracted real code",
                   canonical_inputs_unchanged=True, canonical_inputs=before, production_device_sha256=sha(dev.encode()),
                   test_source_sha256=sha((ROOT / "tests/reset_shader_constants_probe.c").read_bytes()), toolchain=toolchain, runs=runs,
                   coverage=["Actual COM wrappers/setters, Reset/default_state/backbuffer and viewport call path",
                             "Actual shader program lookup, pack, all six constant uploads and cached program reuse",
                             "Actual FF bind and forget-current path; shader generator and GL/resource driver edges stubbed",
                             "Two cached shader programs, repeated reset, all float/int/bool VS+PS registers and warm no-change control"],
                   failed_reset="Not applicable: the current Reset implementation has no failure return and unconditionally returns D3D_OK.",
                   claim="Correctness only. No CPU benefit or hardware-render proof claimed.")
    (OUT / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
