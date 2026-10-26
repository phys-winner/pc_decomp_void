"""Build the ARM64 Android stage: generated x86 C for all lifted modules plus
the Win32 HLE host, compiled with the NDK clang and linked into either a
command-line executable (adb shell bring-up) or the shared library for the APK.

Objects are reused only when the source, every header the generated code can
see, the compiler and the options are byte-identical (SHA-256 fingerprint).
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time

from toolchain import NDK

ROOT = Path(__file__).resolve().parents[1]
MODULES = ("game", "gamemodule", "engine", "fs", "vfs", "sound", "video", "renderer", "nxcharacter",
           "physxcore", "physxcooking", "d3dxcompiler")
TOOLCHAIN = NDK / "toolchains/llvm/prebuilt/windows-x86_64"
CLANG = TOOLCHAIN / "bin/clang.exe"
API = 30
TARGET = f"aarch64-linux-android{API}"
OUT = ROOT / "build/arm64"
COMMON = ["--target=" + TARGET, "-fno-strict-aliasing", "-fwrapv", "-fvisibility=hidden", "-fPIC",
          "-ffp-contract=off", "-fno-math-errno", "-g0"]
# Fold repeated AArch64 instruction sequences without lowering hot-code optimisation.
GENERATED_FLAGS = COMMON + ["-O2", "-mllvm", "-enable-machine-outliner=always",
                            "-mllvm", "-machine-outliner-reruns=2",
                            "-w", "-DRECOMP_GENERATED_CODE", "-DRECOMP_TRACE", "-Iandroid/runtime"]
HOST_FLAGS = COMMON + ["-O2", "-std=gnu11", "-Wall", "-Wno-unused-function", "-Wno-unused-variable",
                       "-DRECOMP_TRACE", "-Iandroid/runtime", "-Iandroid/host"]
# MojoShader (zlib), pinned in dependencies.json; only the profiles the host uses.
MOJO_DIR = "reference/mojoshader"
MOJO_SOURCES = ["mojoshader.c", "mojoshader_common.c", "mojoshader_assembler.c", "mojoshader_preprocessor.c",
                "mojoshader_lexer.c", "profiles/mojoshader_profile_common.c", "profiles/mojoshader_profile_glsl.c",
                "profiles/mojoshader_profile_d3d.c", "profiles/mojoshader_profile_bytecode.c"]
MOJO_FLAGS = COMMON + ["-O2", "-w", "-DMOJOSHADER_FLIP_RENDERTARGET", "-DMOJOSHADER_DEPTH_CLIPPING",
                       "-DSUPPORT_PROFILE_HLSL=0", "-DSUPPORT_PROFILE_ARB1=0", "-DSUPPORT_PROFILE_ARB1_NV=0",
                       "-DSUPPORT_PROFILE_METAL=0", "-DSUPPORT_PROFILE_SPIRV=0", "-DSUPPORT_PROFILE_GLSPIRV=0",
                       "-DSUPPORT_PROFILE_GLSL120=0", "-I" + MOJO_DIR, "-Iandroid/runtime"]


# Lifted functions the host implements natively (android/host/*.c). Their
# generated definitions are compiled from a patched copy as <name>_lifted, so
# every call and the dispatch table bind to the native version while the host
# can still run the lifted body for differential checks.
NATIVE_OVERRIDES = (
    "sub_101BF450",   # GameModule.dll: observe ControlsLocked for touch controls (hud.c)
    "sub_101C61C0", "sub_1017E0F0",  # player analog force and original-console bridge (touch_native.c)
    "sub_14018AB0",   # Sound.dll: libvorbis mdct_backward (android/host/sound_native.c)
    # Sound.dll: libvorbisfile's open, read, clear, pcm_total and pcm_seek
    # (android/host/vorbis_native.c).
    "sub_1400F440", "sub_1400F540", "sub_14010500", "sub_1400F590", "sub_1400F6D0", "sub_140101D0",
    # Engine.dll: the polygons of a navigation mesh leaf under a point
    # (android/host/navmesh_native.c).
    "sub_110EC930",
    # Video.dll: libtheora 1.0's fragment reconstruction and loop filter
    # (android/host/theora_native.c).
    "sub_15018800", "sub_15018ED0",
    "sub_16082260",   # RendererD3D: reserved 12-byte triangle append (renderer_native.c)
    "sub_16013760",   # RendererD3D: weighted region lighting (renderer_region_native.c)
    "sub_16120040",   # RendererD3D: guarded Adler32 through system libz (renderer_adler_native.c)
    # Main RendererD3D: persistent default-allocator inflate lifecycle (renderer_inflate_native.c).
    "sub_1611E830", "sub_1611E7D0", "sub_1611E9F0", "sub_1611FFF0",
    "sub_160D6ED0",   # RendererD3D: bounded SAT with native scratch (renderer_region_native.c)
    "sub_1105E810",   # Engine: identical SAT, guarded by its own live epsilon
    "sub_181802C0",   # PhysX: reserved debug-line append (physics_native.c)
    "sub_110014F0",   # Engine: debug-vector append, preserving ECX (physics_native.c)
    # The CRT memcpy/memmove body of every module (android/host/crt_native.c).
    "sub_0041C740", "sub_004208C0", "sub_10128710", "sub_101292D0", "sub_11074800", "sub_11076D60",
    "sub_12014140", "sub_12015110", "sub_1300E530", "sub_1300F830", "sub_14047F80", "sub_140484C0",
    "sub_15006CE0", "sub_150093F0", "sub_16124050", "sub_1612A0F0", "sub_1700DCC0", "sub_1700FD90",
    "sub_182CDDA0", "sub_182CE260", "sub_190341E0", "sub_19034550",
)


# With RECOMP_LOCAL_REGS a lifted body that uses the SSE file keeps it in a
# local copy as well (recomp_types.h: RECOMP_XMM_OUT/IN ride on the register
# transfers at every call, tail, yield and exit). The generated sources stay
# shared with the Windows build; these definitions go round each such body in
# the Android copy.
FUNCTION_START = re.compile(rb"^void sub_\w+\(void\) \{\r?$", re.M)   # generated files use CRLF
FUNCTION_END = re.compile(rb"\n\}\r?\n")
# LLVM 18 excludes explicit sections from machine outlining; retain hot loops inline.
HOT_FUNCTIONS = (b"sub_16014290", b"sub_160016C0", b"sub_160902D0", b"sub_1608F790",
                 b"sub_11034940", b"sub_1105E810")
HOT_FUNCTION_START = re.compile(rb"^void (?:" + b"|".join(HOT_FUNCTIONS) + rb")\(void\) \{", re.M)
XMM_LOCAL = (b"#undef _xmm\n#undef RECOMP_XMM_OUT\n#undef RECOMP_XMM_IN\n#define _xmm l_xmm\n"
             b"#define RECOMP_XMM_OUT() memcpy(g_xmm, l_xmm, sizeof l_xmm)\n"
             b"#define RECOMP_XMM_IN() memcpy(l_xmm, g_xmm, sizeof l_xmm)\n")
XMM_GLOBAL = (b"#undef _xmm\n#undef RECOMP_XMM_OUT\n#undef RECOMP_XMM_IN\n#define _xmm g_xmm\n"
              b"#define RECOMP_XMM_OUT() ((void)0)\n#define RECOMP_XMM_IN() ((void)0)\n")


def localize_sse(text):
    parts, pos = [], 0
    for match in FUNCTION_START.finditer(text):
        end = FUNCTION_END.search(text, match.end())
        if not end or match.start() < pos:
            continue
        if b"_xmm" not in text[match.end():end.end()]:
            continue
        parts += [text[pos:match.start()], XMM_LOCAL, match.group(0),
                  b"\n    xmm_t l_xmm[8]; memcpy(l_xmm, g_xmm, sizeof l_xmm);", text[match.end():end.end()], XMM_GLOBAL]
        pos = end.end()
    return b"".join(parts + [text[pos:]]) if parts else text


# Measured SAT and PhysX leaves: keep the exact operations while clang removes
# the eight-slot global shifts at every x87 push/pop.
LOCAL_FPU_FUNCTIONS = (b"sub_160D6ED0", b"sub_1105E810", b"sub_18064830", b"sub_160902D0")
FPU_LOCAL = (b"#undef _st\n#undef _fp_top\n#define _st l_st\n#define _fp_top l_fp_top\n"
             b"#undef fp_push\n#undef fp_pop\n#undef fp_xch\n"
             b"#define fp_push(v) fp_push_local_impl(l_st, l_st_i64, &l_fp_top, (v))\n"
             b"#define fp_pop() fp_pop_local_impl(l_st, l_st_i64, &l_fp_top)\n"
             b"#define fp_xch(i) fp_xch_local_impl(l_st, l_st_i64, (i))\n"
             b"#undef RECOMP_FP_OUT\n#undef RECOMP_FP_IN\n"
             b"#define RECOMP_FP_OUT() (memcpy(g_st, l_st, sizeof l_st), "
             b"memcpy(g_st_i64, l_st_i64, sizeof l_st_i64), g_fp_top = l_fp_top)\n"
             b"#define RECOMP_FP_IN() (memcpy(l_st, g_st, sizeof l_st), "
             b"memcpy(l_st_i64, g_st_i64, sizeof l_st_i64), l_fp_top = g_fp_top)\n")
FPU_GLOBAL = (b"#undef _st\n#undef _fp_top\n#define _st g_st\n#define _fp_top g_fp_top\n"
              b"#undef fp_push\n#undef fp_pop\n#undef fp_xch\n"
              b"#define fp_push(v) fp_push_impl(_st, &_fp_top, (v))\n"
              b"#define fp_pop() fp_pop_impl(_st, &_fp_top)\n"
              b"#define fp_xch(i) do { double _t = _st[0]; _st[0] = _st[i]; _st[i] = _t; "
              b"int64_t _ti = g_st_i64[0]; g_st_i64[0] = g_st_i64[i]; g_st_i64[i] = _ti; } while (0)\n"
              b"#undef RECOMP_FP_OUT\n#undef RECOMP_FP_IN\n"
              b"#define RECOMP_FP_OUT() ((void)0)\n#define RECOMP_FP_IN() ((void)0)\n")


def localize_fpu(text):
    parts, pos = [], 0
    for match in FUNCTION_START.finditer(text):
        name = match.group(0).split(b"(", 1)[0].split()[-1]
        if name.removesuffix(b"_lifted") not in LOCAL_FPU_FUNCTIONS:
            continue
        end = FUNCTION_END.search(text, match.end())
        assert end and match.start() >= pos
        body = text[match.end():end.end()]
        assert not any(x in body for x in (b"RECOMP_CALL(", b"RECOMP_ICALL(", b"fp_push_i64("))
        assert b"fp_push(" in body and b"fp_pop()" in body
        baseline = b"static __attribute__((noinline)) " + match.group(0).replace(name, name + b"_fp_global") + body
        localized = body.replace(b"g_st_i64", b"l_st_i64")
        epsilon = b"0x11122CE0" if name.removesuffix(b"_lifted") == b"sub_1105E810" else b"0x162D2A64"
        guard = (b"!void_physics_sweep_finite()" if name == b"sub_18064830" else
                 b"!void_renderer_particle_finite()" if name == b"sub_160902D0" else
                 b"!void_renderer_native_enabled() || MEM32(" + epsilon + b") != 0x3f7fffefu || "
                 b"!recomp_sat_finite(g_edx, MEM32(g_esp + 4))")
        start = (b"\n    if (" + guard + b") { " + name + b"_fp_global(); return; }\n"
                 b"    double l_st[8]; int64_t l_st_i64[8]; int l_fp_top = g_fp_top;\n"
                 b"    memcpy(l_st, g_st, sizeof l_st); memcpy(l_st_i64, g_st_i64, sizeof l_st_i64);")
        parts += [text[pos:match.start()], baseline, b"\n", FPU_LOCAL, match.group(0), start, localized, FPU_GLOBAL]
        pos = end.end()
    if not parts:
        return text
    return (b"int void_renderer_native_enabled(void);\nint void_physics_sweep_finite(void);\n"
            b"int void_renderer_particle_finite(void);\n" + b"".join(parts + [text[pos:]]))


def localize_physics_tree(text):
    """Local x87 only during each ray/tree node's pure rejection arithmetic."""
    entry = b"void sub_1819AF40(void) {"
    if entry not in text:
        return text
    start = text.index(entry)
    end = FUNCTION_END.search(text, start).end()
    body = text[start:end]
    first, after = b"L_1819AF5B:", b"L_1819B075:"
    a, b = body.index(first), body.index(after)
    block = body[a:b]
    assert not any(x in block for x in (b"RECOMP_CALL(", b"RECOMP_ICALL(", b"RECOMP_BACKEDGE", b"fp_push_i64("))
    fast = block.replace(b"g_st_i64", b"l_st_i64")
    for label in set(re.findall(rb"^(L_[0-9A-F]+):", block, re.M)):
        fast = fast.replace(label, label.replace(b"L_", b"F_"))
    exits = set(re.findall(rb"goto (L_[0-9A-F]+);", fast))
    assert exits == {b"L_1819B1F2", b"L_1819B207", b"L_1819B21A", b"L_1819B22F", b"L_1819B235"}
    for label in exits:
        fast = fast.replace(b"goto " + label + b";", b"{ RECOMP_FP_OUT(); goto " + label + b"; }")
    setup = (first + b"\n    if (void_physics_tree_node_finite(esi, edi, ebp)) {\n"
             b"        double l_st[8]; int64_t l_st_i64[8]; int l_fp_top = g_fp_top;\n"
             b"        memcpy(l_st, g_st, sizeof l_st); memcpy(l_st_i64, g_st_i64, sizeof l_st_i64);\n")
    # Recursion, callbacks and their later mutable-query math keep the original
    # global state; every visit through the loop validates its current node.
    patched = (body[:a] + setup + FPU_LOCAL + fast + b"    RECOMP_FP_OUT(); goto " + after[:-1] + b";\n    }\n" +
               FPU_GLOBAL + block[len(first):] + body[b:])
    return (text[:start] + b"int void_physics_tree_node_finite(uint32_t, uint32_t, uint32_t);\n" +
            patched + text[end:])


def localize_physics_worker(text):
    """Local x87 for the worker's bounded, call-free transform preparation."""
    entry = b"void sub_181F1F80(void) {"
    if entry not in text:
        return text
    start = text.index(entry)
    end = FUNCTION_END.search(text, start).end()
    body = text[start:end]
    first, call = b"L_181F1F80:", b"    RECOMP_CALL(sub_181E7720);"
    a, b = body.index(first), body.index(call)
    block = body[a:b]
    assert re.findall(rb"^(L_[0-9A-F]+):", block, re.M) == [b"L_181F1F80"]
    assert not any(x in block for x in (b"RECOMP_CALL(", b"RECOMP_ICALL(", b"RECOMP_BACKEDGE",
                                       b"fp_push_i64(", b"goto ", b"/=", b" / ", b"sqrt("))
    fast = block.replace(first, b"F_181F1F80:").replace(b"g_st_i64", b"l_st_i64")
    setup = (first + b"\n    if (void_physics_worker_pair_finite()) {\n"
             b"        double l_st[8]; int64_t l_st_i64[8]; int l_fp_top = g_fp_top;\n"
             b"        memcpy(l_st, g_st, sizeof l_st); memcpy(l_st_i64, g_st_i64, sizeof l_st_i64);\n")
    # Flush before the original first call; its entire continuation and all
    # callbacks, loop backedges and later mutable inputs retain global x87.
    patched = (body[:a] + setup + FPU_LOCAL + fast +
               b"    RECOMP_FP_OUT(); goto L_181F2824_LOCAL_DONE;\n    }\n" +
               FPU_GLOBAL + block[len(first):] + b"L_181F2824_LOCAL_DONE:\n" + body[b:])
    return (text[:start] + b"int void_physics_worker_pair_finite(void);\n" + patched + text[end:])


# `jmp [reg*4 + table]` reaches its target through the body's `_ljump`
# switch over guest addresses; with a few hundred sparse cases clang emits a
# binary search (the script VM's opcode dispatch spent most of its time
# there). Each such jump gets a table of label addresses built from the jump
# table in the image the code was lifted from; an index past it, or an entry
# that is not a label of the body, still goes through the switch.
JUMP_TABLE = re.compile(rb"\{ _itail_tgt = \(uint32_t\)\(MEM32\((e[a-d]x|e[sd]i|ebp|esp) \* 4 \+ 0x([0-9A-F]{8})\)\); "
                        rb"goto _ljump; \}")
LABEL = re.compile(rb"^L_([0-9A-F]{8}):", re.M)
MODULE_IMAGES = {"game": "generated/input/Game.exe", "gamemodule": "generated/input/GameModule.dll",
                 "engine": "generated/input/Engine.dll", "fs": "generated/input/FS.dll",
                 "vfs": "generated/input/VFS.dll", "sound": "generated/input/Sound.dll",
                 "video": "generated/input/Video.dll", "renderer": "generated/input/RendererD3D.dll",
                 "nxcharacter": "generated/input/NxCharacter.dll", "physxcore": "generated/input/PhysXCore.dll",
                 "physxcooking": "generated/input/PhysXCooking.dll", "d3dxcompiler": "generated/input/d3dx9_36.dll"}


class Image:
    """A PE image's bytes by virtual address (the lifted, possibly rebased, copy)."""
    def __init__(self, path):
        data = Path(path).read_bytes()
        pe = int.from_bytes(data[0x3C:0x40], "little")
        count = int.from_bytes(data[pe + 6:pe + 8], "little")
        optional = pe + 24
        self.base = int.from_bytes(data[optional + 28:optional + 32], "little")
        table = optional + int.from_bytes(data[pe + 20:pe + 22], "little")
        self.sections = []
        for i in range(count):
            at = table + 40 * i
            vsize, va, raw_size, raw = (int.from_bytes(data[at + o:at + o + 4], "little") for o in (8, 12, 16, 20))
            self.sections.append((self.base + va, max(vsize, raw_size), raw, raw_size))
        self.data = data
        self.sha256 = hashlib.sha256(data).hexdigest()

    def u32(self, va):
        for start, size, raw, raw_size in self.sections:
            if start <= va and va + 4 <= start + size:
                offset = va - start
                return int.from_bytes(self.data[raw + offset:raw + offset + 4], "little") if offset + 4 <= raw_size else 0
        return None


_images = {}


# Another release (tools/lift_release.py) builds from generated/<release>/
# into build/arm64-<release>; set by --release.
GENERATED = ROOT / "generated"
RELEASE = None


def module_image(module):
    """The image a generated module was lifted from, checked against its report."""
    if module not in _images:
        game = json.loads((ROOT / "port.json").read_text())["game_directory"]
        image = Image(MODULE_IMAGES[module].format(game=game))
        report = json.loads((GENERATED / f"{module}-x86/report.json").read_text())
        expected = report.get("rebased_sha256") or report.get("binary_sha256")
        if expected and expected != image.sha256:
            raise SystemExit(f"{module}: image {MODULE_IMAGES[module]} does not match report.json")
        _images[module] = image
    return _images[module]


def direct_jump_tables(text, image):
    parts, pos = [], 0
    for match in FUNCTION_START.finditer(text):
        end = FUNCTION_END.search(text, match.end())
        if not end or match.start() < pos:
            continue
        body = text[match.end():end.end()]
        if b"  _ljump:" not in body or not JUMP_TABLE.search(body):
            continue
        labels = {int(label, 16) for label in LABEL.findall(body)}
        if len(labels) > 2000:
            # Bodies labelled at nearly every instruction (the CRT's memcpy
            # family: 112 tables, ~5,000 labels) took clang over ten minutes
            # with label tables; they keep the switch.
            continue
        low, high = min(labels), max(labels)

        def table_jump(jump):
            register, table = jump.group(1), int(jump.group(2), 16)
            targets = []
            while len(targets) < 1024:
                target = image.u32(table + 4 * len(targets))
                if target is None or not low <= target <= high:
                    break
                targets.append(target)
            if not targets:
                return jump.group(0)
            entries = b", ".join(b"&&L_%08X" % t if t in labels else b"&&_ljump" for t in targets)
            return (b"{ static void *const _jt[%d] = { %s }; uint32_t _jx = %s; "
                    b"_itail_tgt = (uint32_t)(MEM32(%s * 4 + 0x%08X)); if (_jx < %du) goto *_jt[_jx]; goto _ljump; }"
                    % (len(targets), entries, register, register, table, len(targets)))

        parts += [text[pos:match.end()], JUMP_TABLE.sub(table_jump, body)]
        pos = end.end()
    return b"".join(parts + [text[pos:]]) if parts else text


def override_source(source, local_xmm):
    """The file to compile for a generated source and its extra flags: a
    patched copy under build/ when it defines one of NATIVE_OVERRIDES or (with
    local_xmm) a body that uses the SSE file, and with direct jump tables."""
    original = text = source.read_bytes()
    for name in NATIVE_OVERRIDES:
        text = text.replace(b"\nvoid %s(void) {" % name.encode(), b"\nvoid %s_lifted(void) {" % name.encode(), 1)
    if source.name != "recomp_dispatch.c":
        module = source.parent.name[:-len("-x86")]
        if b"goto _ljump; }" in text:
            text = direct_jump_tables(text, module_image(module))
        if local_xmm:
            text = localize_sse(text)
        if RELEASE is None:
            text = localize_fpu(text)
            text = localize_physics_tree(text)
            text = localize_physics_worker(text)
            text = HOT_FUNCTION_START.sub(rb'__attribute__((section(".text.hot"))) \g<0>', text)
    if text == original:
        return source, []
    patched = OUT / "patched" / source.parent.name / source.name
    patched.parent.mkdir(parents=True, exist_ok=True)
    if not patched.is_file() or patched.read_bytes() != text:
        patched.write_bytes(text)
    return patched, ["-I" + source.parent.relative_to(ROOT).as_posix()]


def private_renderer_sat(text):
    """The pinned boolean SAT leaf with native scratch, preserving emitted math."""
    found = re.search(rb"^void sub_160D6ED0\(void\) \{.*?^\}", text, re.M | re.S)
    assert found, "renderer SAT body missing"
    body = found[0].replace(b"\r\n", b"\n")
    assert hashlib.sha256(body).hexdigest() == "17a80228f6cf7d34f08c44fd8b31dc9dcf2a9b21d371f240a645f5bafe943b4a"
    body = body.decode().replace("void sub_160D6ED0(void)",
        "static unsigned region_sat_overlap(const float *a, const float *b, uint32_t *backedges)")
    body = body.replace("    RECOMP_REGS_LOCALS", """    uint32_t frame[40];
    uintptr_t n_eax=0, n_ecx=0, n_edx=(uintptr_t)a, n_ebx=0;
    uintptr_t n_esp=(uintptr_t)(frame+40), n_ebp=0, n_esi=0, n_edi=0;
    double n_st[8]={0}; int64_t n_shadow[8]={0}; int n_top=0;
    xmm_t n_xmm[8];""")
    body = body.replace("    RECOMP_ENTER(0x160D6ED0u);", "")
    body = body.replace("ebp = MEM32(esp + 0x84);", "ebp = (uintptr_t)b;")
    body = body.replace("*(float*)&MEM32(0x162D2A64)", "sse_f32(0x3f7fffefu)")
    body = re.sub(r"PUSH32\(esp, (ebx|ebp|esi|edi)\);", "esp -= 4;", body)
    body = re.sub(r"(edi|esi|ebp|ebx) = POP32_VAL\(esp\);", "esp += 4;", body)
    body = body.replace("RECOMP_FLAGS_OUT();", "").replace("RECOMP_REGS_OUT();", "")
    body = body.replace("return;", "return (unsigned)(n_eax & 255u);")
    body = body.replace("RECOMP_BACKEDGE();", "++*backedges;")
    body = re.sub(r"\b(eax|ecx|edx|ebx|esp|ebp|esi|edi)\b", lambda m: "n_" + m[0], body)
    body = re.sub(r"\b_st\b", "n_st", body).replace("g_st_i64", "n_shadow")
    body = re.sub(r"\b_xmm\b", "n_xmm", body)
    body = body.replace("fp_push(", "fp_push_local_impl(n_st, n_shadow, &n_top, ")
    body = body.replace("fp_pop()", "fp_pop_local_impl(n_st, n_shadow, &n_top)")
    body = body.replace("fp_xch(", "fp_xch_local_impl(n_st, n_shadow, ")
    body = body.replace("MEM32(", "REGION_SAT_MEM32(").replace("ADDR(", "REGION_SAT_ADDR(")
    body = re.sub(r"/\*.*?\*/", "", body)
    assert not any(x in body for x in ("RECOMP_", "POP32", "PUSH32")) and not re.search(r"\bg_", body)
    return ("#define REGION_SAT_ADDR(a) ((uintptr_t)(a))\n"
            "#define REGION_SAT_MEM32(a) (*(uint32_t *)REGION_SAT_ADDR(a))\n" + body +
            "\n#undef REGION_SAT_ADDR\n#undef REGION_SAT_MEM32\n")


def host_source(source):
    if RELEASE is not None or source.name != "renderer_region_native.c":
        return source
    assert module_image("renderer").u32(0x162D2A64) == 0x3f7fffef
    assert module_image("engine").u32(0x11122CE0) == 0x3f7fffef
    engine = re.search(rb"^void sub_1105E810\(void\) \{.*?^\}",
        (GENERATED / "engine-x86/engine_0023.c").read_bytes(), re.M | re.S)
    assert engine and hashlib.sha256(engine[0].replace(b"\r\n", b"\n")).hexdigest() == "d41140ee11f33afc37f24da52a3f33bde6b4327b036642124a0aa1a00a373a2d"
    helper = private_renderer_sat((GENERATED / "renderer-x86/renderer_0074.c").read_bytes()).encode()
    content = source.read_bytes()
    assert content.count(b"/* GENERATED_REGION_SAT */") == 1
    content = content.replace(b"/* GENERATED_REGION_SAT */", helper)
    patched = OUT / "patched/host" / source.name
    patched.parent.mkdir(parents=True, exist_ok=True)
    if not patched.is_file() or patched.read_bytes() != content:
        patched.write_bytes(content)
    return patched


def sha_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def available_modules():
    """Generated stages present on disk (PhysX joins once tools/lift_physx.py has run)."""
    return [m for m in MODULES if (GENERATED / f"{m}-x86/report.json").exists()]


def generated_sources():
    sources = []
    modules = available_modules()
    for name in modules:
        report = json.loads((GENERATED / f"{name}-x86/report.json").read_text())
        files = report.get("sources")
        if not isinstance(files, list) or not files:
            raise SystemExit(f"{name}: report.json has no source list")
        sources += [GENERATED / f"{name}-x86" / f for f in files]
    dispatch = GENERATED / f"{modules[-1]}-x86/recomp_dispatch.c"
    if dispatch.is_file():   # absent while a release is still being lifted (--compile-only)
        sources.append(dispatch)
    return sources


def host_sources():
    return sorted((ROOT / "android/host").glob("*.c"))


def fix_mojo_ps3_semantics(source):
    """Keep PS3 DCL semantics in our build copy; older pixel models have none."""
    old = b"else if (shader_is_pixel(ctx))  // all other pixel shader types are zero'd."
    new = b"else if (shader_is_pixel(ctx) && !shader_version_atleast(ctx, 3, 0))"
    if source.count(old) != 1:
        raise ValueError("MojoShader pixel DCL assembler source changed")
    return source.replace(old, new)


def header_digest(paths):
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(sha_file(path).encode())
    return digest.hexdigest()


def compile_one(source, obj, flags, fingerprint, cache):
    rel = source.relative_to(ROOT).as_posix()
    entry = cache.get(rel)
    if entry and entry.get("fingerprint") == fingerprint and obj.is_file() and sha_file(obj) == entry.get("object_sha256"):
        return rel, "reused", 0.0, entry
    obj.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    command = [str(CLANG)] + flags + ["-c", str(source), "-o", str(obj)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    elapsed = time.time() - start
    if result.returncode:
        raise RuntimeError(f"{rel}: clang failed ({result.returncode})\n{result.stderr[-4000:]}")
    if result.stderr.strip():
        print(f"[warn] {rel}:\n{result.stderr.strip()[-3000:]}", flush=True)
    return rel, "compiled", elapsed, {"fingerprint": fingerprint, "object_sha256": sha_file(obj)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) - 4))
    parser.add_argument("--host-only", action="store_true", help="Recompile host sources and relink only")
    parser.add_argument("--shared", action="store_true", help="Link libvoid.so for the APK instead of the executable")
    parser.add_argument("--global-regs", action="store_true",
                        help="Keep the integer registers in globals (upstream model) instead of RECOMP_LOCAL_REGS")
    parser.add_argument("--volatile-memory", action="store_true",
                        help="Volatile guest memory accesses (upstream) instead of RECOMP_PLAIN_MEMORY")
    parser.add_argument("--pgo-generate", action="store_true",
                        help="Instrument the generated code for a profile (build/arm64-pgogen; LLVM_PROFILE_FILE "
                             "names the output, the script command 'profile' writes it)")
    parser.add_argument("--pgo-use", metavar="PROFDATA", default=None,
                        help="Optimise the generated code with a merged profile (llvm-profdata merge); "
                             "default build/pgo/void.profdata when it exists (tools/android_pgo.sh)")
    parser.add_argument("--no-pgo", action="store_true", help="Build without the profile")
    parser.add_argument("--compile-only", action="store_true", help="Compile the objects, do not link")
    parser.add_argument("--release", metavar="NAME",
                        help="Build another release of the game lifted by tools/lift_release.py "
                             "(generated/NAME, build/arm64-NAME, libvoid_NAME.so); never with the 2009 profile")
    args = parser.parse_args()
    global GENERATED, RELEASE, MODULES, MODULE_IMAGES, NATIVE_OVERRIDES
    if args.release:
        GENERATED = ROOT / "generated" / args.release
        if (GENERATED / "release.json").is_file():
            RELEASE = json.loads((GENERATED / "release.json").read_text())
        elif args.compile_only:
            # Still lifting (tools/lift_release.py --only): the modules done so far.
            spec = json.loads((ROOT / "config/releases" / f"{args.release}.json").read_text())
            done = [m for m in spec["modules"] if (GENERATED / f"{m['prefix']}-x86/report.json").is_file()
                    and json.loads((GENERATED / f"{m['prefix']}-x86/report.json").read_text()).get("status") == "GENERATED"]
            reports = [json.loads((GENERATED / f"{m['prefix']}-x86/report.json").read_text()) for m in done]
            native = [f"sub_{int(a, 16):08X}" for r in reports for a in r["overrides"]["crt_memmove"]]
            native += [f"sub_{int(r['overrides']['mdct_backward'], 16):08X}" for r in reports if "mdct_backward" in r["overrides"]]
            RELEASE = {"modules": [m["prefix"] for m in done], "native_overrides": native,
                       "images": {m["prefix"]: r["input_image"] for m, r in zip(done, reports)}}
        else:
            raise SystemExit(f"run tools/lift_release.py {args.release} (or --finish) first")
        MODULES = tuple(RELEASE["modules"])
        MODULE_IMAGES = dict(RELEASE["images"])
        NATIVE_OVERRIDES = tuple(RELEASE["native_overrides"]) + ("sub_1017D3C0", "sub_101C4FC0", "sub_101BE240")
        args.no_pgo = True
    # The first location gains ~12% (42-51 fps against 38-45) from the
    # profile, the map's settled phase more; a build without it is an explicit
    # choice, since it recompiles every generated object.
    if args.pgo_use is None and not args.no_pgo and not args.pgo_generate and (ROOT / "build/pgo/void.profdata").is_file():
        args.pgo_use = str(ROOT / "build/pgo/void.profdata")
    if args.no_pgo:
        args.pgo_use = None
    # The default generated code keeps registers in locals and accesses guest
    # memory plainly (first location on the Redmi Note 8 Pro: 37-43 fps against
    # 33-39 with both off). The upstream modes build in their own directories
    # (build/arm64-globalregs, build/arm64-volatilemem, ...) for A/B runs.
    global OUT, GENERATED_FLAGS
    GENERATED_FLAGS = (GENERATED_FLAGS + ([] if args.global_regs else ["-DRECOMP_LOCAL_REGS"]) +
                       ([] if args.volatile_memory else ["-DRECOMP_PLAIN_MEMORY"]))
    upstream = [name for name, on in (("globalregs", args.global_regs), ("volatilemem", args.volatile_memory),
                                      ("pgogen", args.pgo_generate)) if on]
    if args.release:
        upstream.insert(0, args.release)
    if upstream:
        OUT = ROOT / ("build/arm64-" + "-".join(upstream))
    if args.pgo_generate:
        GENERATED_FLAGS = GENERATED_FLAGS + ["-fprofile-instr-generate"]
    if args.pgo_use:
        profile = Path(args.pgo_use).resolve()
        # The profile's digest joins the flags, so objects follow a new profile.
        GENERATED_FLAGS = GENERATED_FLAGS + ["-fprofile-instr-use=" + profile.as_posix(),
                                             "-DVOID_PGO_PROFILE_" + sha_file(profile)[:16]]
    os.chdir(ROOT)
    OUT.mkdir(parents=True, exist_ok=True)
    cache_path = OUT / "objects.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    compiler_sha = sha_file(CLANG)
    runtime_headers = [ROOT / "android/runtime/recomp_types.h"]
    # A module's sources see the runtime and their own headers; the merged
    # dispatch table (last module) sees every module's headers.
    module_digest = {name: header_digest(runtime_headers + sorted((GENERATED / f"{name}-x86").glob("*.h")))
                     for name in available_modules()}
    gen_digest = header_digest(runtime_headers + sorted(p for name in available_modules()
                                                        for p in (GENERATED / f"{name}-x86").glob("*.h")))
    release_headers = [GENERATED / "release_overrides.h"] if args.release and not args.compile_only else []
    host_digest = header_digest(runtime_headers + sorted((ROOT / "android/host").glob("*.h")) +
                                [ROOT / "reference/dlmalloc/malloc.c"] + release_headers)
    jobs = []
    if not args.host_only:
        for source in generated_sources():
            module = source.parent.name
            obj = OUT / "obj" / module / (source.stem + ".o")
            digest = gen_digest if source.name == "recomp_dispatch.c" else module_digest[module[:-len("-x86")]]
            source, extra = override_source(source, local_xmm=not args.global_regs)
            flags = GENERATED_FLAGS + extra
            fp = hashlib.sha256(json.dumps([sha_file(source), digest, compiler_sha, flags]).encode()).hexdigest()
            jobs.append((source, obj, flags, fp))
    for name in MOJO_SOURCES:
        source = ROOT / MOJO_DIR / name
        obj = OUT / "obj/mojoshader" / (source.stem + ".o")
        if name == "mojoshader_assembler.c":
            patched = OUT / "patched/mojoshader_assembler.c"
            content = fix_mojo_ps3_semantics(source.read_bytes())
            patched.parent.mkdir(parents=True, exist_ok=True)
            if not patched.is_file() or patched.read_bytes() != content:
                patched.write_bytes(content)
            source = patched
        fp = hashlib.sha256(json.dumps([sha_file(source), header_digest(sorted((ROOT / MOJO_DIR).glob("*.h"))),
                                        compiler_sha, MOJO_FLAGS]).encode()).hexdigest()
        jobs.append((source, obj, MOJO_FLAGS, fp))
    host_flags = HOST_FLAGS + (["-DVOID_ANDROID_APP"] if args.shared else [])
    if args.release:
        host_flags = host_flags + ["-DVOID_RELEASE", "-I" + GENERATED.relative_to(ROOT).as_posix()]
    host_dir = "obj/host-app" if args.shared else "obj/host"
    for source in [] if args.compile_only else host_sources():
        obj = OUT / host_dir / (source.stem + ".o")
        source = host_source(source)
        # These computations run inside the guest lock, like generated code.
        flags = host_flags + (["-DRECOMP_PLAIN_MEMORY"] if not args.volatile_memory and
                              source.name in ("navmesh_native.c", "renderer_region_native.c", "renderer_particle_native.c") else [])
        fp = hashlib.sha256(json.dumps([sha_file(source), host_digest, compiler_sha, flags]).encode()).hexdigest()
        jobs.append((source, obj, flags, fp))
    # Largest first keeps the pool busy at the end.
    jobs.sort(key=lambda j: -j[0].stat().st_size)
    start = time.time()
    compiled = reused = 0
    failures = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(compile_one, s, o, f, fp, cache) for s, o, f, fp in jobs]
        for future in as_completed(futures):
            try:
                rel, status, elapsed, entry = future.result()
            except RuntimeError as error:
                failures.append(str(error))
                print(str(error), flush=True)
                continue
            cache[rel] = entry
            if status == "compiled":
                compiled += 1
                if elapsed > 20:
                    print(f"[slow] {rel}: {elapsed:.1f}s", flush=True)
            else:
                reused += 1
            if (compiled + reused) % 50 == 0:
                print(f"[progress] {compiled + reused}/{len(jobs)} ({time.time() - start:.0f}s)", flush=True)
                cache_path.write_text(json.dumps(cache, indent=1))
    cache_path.write_text(json.dumps(cache, indent=1))
    print(f"compiled {compiled}, reused {reused}, failed {len(failures)} in {time.time() - start:.0f}s", flush=True)
    if failures:
        sys.exit(1)
    if args.compile_only:
        return
    if args.host_only:
        skip = "host" if args.shared else "host-app"
        objects = sorted(str(p) for p in (OUT / "obj").rglob("*.o") if p.parent.name != skip)
    else:
        objects = [str(o) for _, o, _, _ in jobs]
    response = OUT / "link.rsp"
    response.write_text("\n".join(o.replace("\\", "/") for o in objects))
    library = f"libvoid_{args.release}.so" if args.release else "libvoid.so"
    output = OUT / (library if args.shared else "void-arm64")
    # LOAD segments on 16 KB boundaries: devices with 16 KB pages (and Android 16+'s
    # compatibility check) require it; 4 KB devices load such images unchanged.
    link = [str(CLANG), "--target=" + TARGET, "-fuse-ld=lld", "-Wl,--gc-sections", "-Wl,-z,nostart-stop-gc", "-Wl,-z,max-page-size=16384",
            "-Wl,--build-id=sha1", "-Wl,--pack-dyn-relocs=android", "@" + str(response), "-o", str(output), "-lm", "-lz", "-llog", "-ldl", "-lEGL", "-lGLESv3"]
    link += ["-shared", "-landroid", "-lOpenSLES", "-laaudio"] if args.shared else ["-pie"]
    if args.pgo_generate:
        link.append("-fprofile-instr-generate")
    start = time.time()
    result = subprocess.run(link, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        print(result.stderr[-6000:])
        sys.exit(1)
    print(f"linked {output} ({output.stat().st_size / 1e6:.1f} MB) in {time.time() - start:.0f}s")


if __name__ == "__main__":
    main()
