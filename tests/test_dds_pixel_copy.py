"""Exact DDS converter differential, corrupt-copy negative control and ARM64 call-site proof."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/dds-pixel-copy-test"
sys.path.insert(0, str(ROOT / "tools"))
from build_android import CLANG, HOST_FLAGS, TOOLCHAIN
from build_x86_incremental import compiler_environment


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source_path = ROOT / "android/host/d3d9_format.c"
    internal_path = ROOT / "android/host/d3d9_internal.h"
    inputs = [source_path, internal_path]
    before = {str(p.relative_to(ROOT)): sha(p) for p in inputs}
    fixed = source_path.read_text(encoding="utf-8")
    old = "                    for (uint32_t c = 0; c < channels; ++c) d[c] = texels[y * 4 + x][c];"
    new = """                    const uint8_t *s = texels[y * 4 + x];
                    if (channels == 4) memcpy(d, s, 4);
                    else if (channels == 2) memcpy(d, s, 2);
                    else d[0] = s[0];"""
    assert fixed.count(new) == 1
    original = fixed.replace(new, old)
    assert re.findall(r"decode_blocks\(conv, src, width, height, pitch, out, (\d+)\)", fixed) == ["4", "1", "2"]
    gl_path = TOOLCHAIN / "sysroot/usr/include/GLES3/gl32.h"
    gl = gl_path.read_text()
    values = dict(re.findall(r"^#define\s+(GL_\w+)\s+(0[xX][0-9a-fA-F]+|\d+)\b", gl, re.M))
    needed = sorted(set(re.findall(r"\bGL_[A-Z0-9_]+\b", original)))
    assert all(name in values for name in needed)
    internal = internal_path.read_text()
    types = internal[internal.index("enum {\n    CONV_NONE"):internal.index("const d3d_format *d3d_format_find")]
    header = "#ifndef QA_FORMAT_TYPES\n#define QA_FORMAT_TYPES\n#include <stdint.h>\n#include <stdlib.h>\n#include <string.h>\n"
    header += "typedef unsigned GLenum;\ntypedef int GLint;\n"
    header += "#define FOURCC(a,b,c,d) ((uint32_t)(a)|((uint32_t)(b)<<8)|((uint32_t)(c)<<16)|((uint32_t)(d)<<24))\n"
    header += "\n".join("#define " + name + " " + values[name] for name in needed) + "\n" + types
    exports = ("d3d_format_find", "d3d_format_pitch", "d3d_format_rows", "d3d_format_convert")
    for label in ("original", "fixed"):
        header += f"void *{label}_alloc(size_t size);\n"
        header += f"const d3d_format *{label}_d3d_format_find(uint32_t format);\n"
        header += f"uint32_t {label}_d3d_format_pitch(const d3d_format *f,uint32_t width);\n"
        header += f"uint32_t {label}_d3d_format_rows(const d3d_format *f,uint32_t height);\n"
        header += f"const void *{label}_d3d_format_convert(const d3d_format *f,const uint8_t *src,uint32_t w,uint32_t h,uint32_t pitch,void **owned,size_t *size,int rt);\n"
    (OUT / "format-types.h").write_text(header + "#endif\n")
    compiler, env, msvc = compiler_environment()
    objects, asm_proof = [], {}
    for label, text in (("original", original), ("fixed", fixed)):
        native_source = OUT / (label + "-native.c")
        native_source.write_text(text, encoding="utf-8", newline="\n")
        native_object = OUT / (label + "-arm64.o")
        subprocess.run([str(CLANG), *HOST_FLAGS, "-DVOID_ANDROID_APP", "-c", str(native_source), "-o", str(native_object)],
                       cwd=ROOT, check=True, capture_output=True, text=True)
        asm = subprocess.check_output([str(TOOLCHAIN / "bin/llvm-objdump.exe"), "-dr", str(native_object)], text=True)
        (OUT / (label + "-arm64.txt")).write_text(asm)
        start = re.search(r"^[0-9a-f]+ <decode_blocks>:", asm, re.M)
        assert start, "decode_blocks disappeared; review assembly manually"
        following = re.search(r"^[0-9a-f]+ <[^>]+>:", asm[start.end():], re.M)
        body = asm[start.start():start.end() + following.start()] if following else asm[start.start():]
        copies = re.findall(r"R_AARCH64_CALL26\s+memcpy\b", body)
        asm_proof[label] = dict(decode_blocks_memcpy_call_sites=len(copies), object_sha256=sha(native_object))
        assert (len(copies) > 0) == (label == "original"), body
        host_source = OUT / (label + "-oracle.c")
        prefix = '#include "format-types.h"\n#define malloc ' + label + '_alloc\n'
        prefix += "\n".join("#define " + name + " " + label + "_" + name for name in exports) + "\n"
        host_source.write_text(prefix + text.replace('#include "d3d9_internal.h"', ""), encoding="utf-8")
        obj = OUT / (label + ".obj")
        build = subprocess.run([str(compiler), "/nologo", "/O2", "/W4", "/WX", "/std:c11", "/c", str(host_source),
                                "/Fo" + str(obj)], env=env, capture_output=True, text=True)
        assert build.returncode == 0, build.stdout + build.stderr
        objects.append(obj)
    mutant = OUT / "mutant-oracle.c"
    mutant.write_text((OUT / "fixed-oracle.c").read_text().replace("if (channels == 4) memcpy(d, s, 4);",
                                                                 "if (channels == 4) memcpy(d, s, 3);", 1))
    mutant_obj = OUT / "mutant.obj"
    build = subprocess.run([str(compiler), "/nologo", "/O2", "/W4", "/WX", "/std:c11", "/c", str(mutant),
                            "/Fo" + str(mutant_obj)], env=env, capture_output=True, text=True)
    assert build.returncode == 0, build.stdout + build.stderr
    outcomes = {}
    for name, selected in (("oracle", objects[1]), ("negative", mutant_obj)):
        exe = OUT / (name + ".exe")
        build = subprocess.run([str(compiler), "/nologo", "/O2", "/W4", "/WX", "/std:c11",
                                "/I" + str(OUT),
                                str(ROOT / "tests/dds_pixel_copy_probe.c"), str(objects[0]), str(selected),
                                "/Fo" + str(OUT / (name + "-probe.obj")), "/Fe" + str(exe)],
                               env=env, capture_output=True, text=True)
        assert build.returncode == 0, build.stdout + build.stderr
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        (OUT / (name + ".log")).write_text(run.stdout + run.stderr)
        assert (run.returncode == 0) == (name == "oracle"), run.stdout + run.stderr
        outcomes[name] = dict(exit_code=run.returncode, result=run.stdout.strip())
    assert before == {str(p.relative_to(ROOT)): sha(p) for p in inputs}, "canonical inputs changed"
    receipt = dict(status="PASS; actual converter differential and corrupted-pixel negative control", canonical_inputs_unchanged=True,
                   canonical_inputs=before, production_sha256=sha(source_path),
                   ndk_compiler=str(CLANG), ndk_flags=HOST_FLAGS + ["-DVOID_ANDROID_APP"], msvc=msvc,
                   gl_definitions_source=str(gl_path), gl_definitions_sha256=sha(gl_path), assembly=asm_proof,
                   oracle=outcomes, claim="CPU mechanism only; no hardware speedup or all-6.93%-removal claim.")
    (OUT / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(outcomes["oracle"]["result"])
    print("PASS negative control: a three-byte RGBA copy was rejected")
    print(json.dumps(asm_proof))


if __name__ == "__main__":
    main()
