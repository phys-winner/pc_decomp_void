"""System-libz streaming adapter versus the emitted original; --android builds CLI oracles."""
import gzip
import shlex
import struct
import tarfile
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "build/inflate-native-test"
HELPER = ROOT / "android/host/renderer_inflate_native.c"
sys.path.insert(0, str(ROOT / "tools"))
from build_android import CLANG, HOST_FLAGS
import build_android as build
from build_x86_incremental import compiler_environment
from patch_scripts import read_entry
import pefile


def body(source, name):
    match = re.search(r"^void " + name + r"\(void\) \{.*?^\}", source, re.M | re.S)
    assert match, name
    return match[0]


def android_elf(path):
    data = path.read_bytes()
    h = struct.unpack_from("<16sHHIQQQIHHHHHH", data)
    assert h[0][:6] == b"\x7fELF\x02\x01" and h[1] == 3 and h[2] == 183
    loads = []
    for i in range(h[10]):
        p = struct.unpack_from("<IIQQQQQQ", data, h[5] + i * h[9])
        if p[0] == 1:
            assert p[7] >= 16384 and (p[3] - p[2]) % 16384 == 0
            loads.append(p[7])
    assert loads
    text = subprocess.run([str(build.TOOLCHAIN / "bin/llvm-readelf.exe"), "-d", "-n", str(path)],
                          capture_output=True, text=True, check=True).stdout
    assert "libz.so" in text
    return dict(path=path.name, sha256=hashlib.sha256(data).hexdigest(),
                bytes=len(data), load_alignment=loads,
                build_id=re.search(r"Build ID: ([0-9a-f]+)", text)[1])


def negative_control(fixture, command, corpus, env):
    line = "MEM32(stream + 20) = (uint32_t)owner->native.total_out;"
    assert fixture.count(line) == 1
    mutant = OUT / "probe-negative.c"
    mutant.write_text(fixture.replace(line, line[:-1] + " + 1u;", 1))
    binary = OUT / "probe-negative.exe"
    command = [str(mutant) if x == str(OUT / "probe.c") else str(binary) if x == command[-1] else x for x in command]
    built = subprocess.run(command, env=env, capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    checked = subprocess.run([str(binary), str(OUT / "renderer-image.bin"), corpus[0]["path"]],
                             capture_output=True, text=True, timeout=30)
    text = checked.stdout + checked.stderr
    (OUT / "negative-control.txt").write_text(text)
    assert checked.returncode == 3 and "MISMATCH" in text and "field+20=" in text, text
    return dict(status="EXPECTED_REJECTION", corrupted_field="total_out+20", returncode=checked.returncode)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    android = "--android" in sys.argv
    assert HELPER in build.host_sources(), "native helper not discovered"
    assert "-DRECOMP_PLAIN_MEMORY" not in HOST_FLAGS
    assert all(n in build.NATIVE_OVERRIDES for n in ("sub_1611E830", "sub_1611E7D0", "sub_1611E9F0", "sub_1611FFF0"))
    names = ["sub_1611E830", "sub_1611E7D0", "sub_1611E9F0", "sub_1611FFF0", "sub_1611CDB0",
             "sub_1611E900", "sub_16120040", "sub_16121D60", "sub_16122220"]
    texts = [(ROOT / f"generated/renderer-x86/renderer_{n}.c").read_text() for n in ("0101", "0102")]
    bodies = {name: body(next(t for t in texts if f"void {name}(void)" in t), name) for name in names}
    header = (ROOT / "android/runtime/recomp_types.h").read_text()
    header = header.replace("#if defined(_MSC_VER) || !defined(__aarch64__)", "#if 0", 1)
    header = re.sub(r"static inline uint64_t __rdtsc\(void\) \{.*?\n\}", "", header, flags=re.S)
    header, n = re.subn(r"^#define ADDR\(va\).+$", "static void *guest_address(uint32_t va);\n#define ADDR(va) ((uintptr_t)guest_address((uint32_t)(va)))", header, flags=re.M)
    assert n == 1
    (OUT / "runtime-fixture.h").write_text(header)
    image = pefile.PE(str(ROOT / "generated/input/RendererD3D.dll")).get_memory_mapped_image()
    (OUT / "renderer-image.bin").write_bytes(image)
    corpus = []
    payloads = [b"", b"a", bytes(range(256)) * 17, b"boundary" * 501,
                read_entry("research/vfs-index.json", "Scenes\\Girl\\ire.xml")]
    for i, payload in enumerate(payloads):
        for wrapper in ("zlib", "gzip", "raw"):
            if wrapper == "zlib":
                packed = zlib.compress(payload)
            elif wrapper == "gzip":
                packed = gzip.compress(payload, mtime=0)
            else:
                encoder = zlib.compressobj(wbits=-15)
                packed = encoder.compress(payload) + encoder.flush()
            variants = [("valid", packed), ("truncated", packed[:-1])]
            if wrapper != "raw":
                corrupt = bytearray(packed)
                corrupt[-8 if wrapper == "gzip" else -1] ^= 1
                variants += [("bad-checksum", bytes(corrupt)), ("bad-header", b"XX" + packed[2:])]
            for label, data in variants:
                p = OUT / f"stream-{i}-{wrapper}-{label}.bin"
                p.write_bytes(data)
                corpus.append(dict(path=str(p), sha256=hashlib.sha256(data).hexdigest(),
                                   wrapper=wrapper, label=label, bytes=len(data)))
    encoder = zlib.compressobj(zdict=b"required original dictionary")
    packed = encoder.compress(b"required original dictionary" * 10) + encoder.flush()
    p = OUT / "stream-dictionary-zlib-valid.bin"
    p.write_bytes(packed)
    corpus.append(dict(path=str(p), sha256=hashlib.sha256(packed).hexdigest(), wrapper="zlib", label="needs-dictionary", bytes=len(packed)))
    for resource in ("Scenes\\Map\\obscure.s", "Scenes\\Map\\obscure_uta.s"):
        data = read_entry("research/vfs-index.json", resource)
        for offset in range(128):
            if data[offset] > 0x78 or data[offset] & 15 != 8 or (data[offset] * 256 + data[offset + 1]) % 31:
                continue
            decoder = zlib.decompressobj()
            try:
                payload = decoder.decompress(data[offset:], 200001)
            except zlib.error:
                continue
            if not decoder.eof or len(payload) > 200000:
                continue
            used = len(data) - offset - len(decoder.unused_data)
            packed = data[offset:offset + used]
            p = OUT / (resource.split("\\")[-1] + "-original-valid.bin")
            p.write_bytes(packed)
            corpus.append(dict(path=str(p), resource=resource, offset=offset,
                               sha256=hashlib.sha256(packed).hexdigest(), bytes=used, output_bytes=len(payload)))
            break
        else:
            raise AssertionError(resource)
    declarations = (ROOT / "tests/local_fpu_probe.c").read_text().split("#define BASE", 1)[0]
    helper_path = HELPER
    helper_bytes = helper_path.read_bytes()
    helper = re.sub(r"^#include .*\n", "", helper_bytes.decode(), flags=re.M)
    emitted = "\n".join(bodies.values())
    for name in names[:4]:
        definition = "void " + name + "(void) {"
        assert emitted.count(definition) == 1
        emitted = emitted.replace(definition, "void " + name + "_lifted(void) {", 1)
    emitted = emitted.replace("void sub_1611E9F0_lifted(void) {", "void sub_1611E9F0_lifted(void) {\nassert(!*inflate_slot(MEM32(g_esp+4)));++original_decode_calls;", 1)
    prototypes = "\n".join("void " + name + ("_lifted" if name in names[:4] else "") + "(void);" for name in names)
    prototypes += "\nvoid sub_1612A0F0(void);void sub_16125D86(void);\n"
    fixture = (HERE / "inflate_native_probe.c").read_text().replace("/* DECLARATIONS */", declarations)
    fixture = fixture.replace("/* PROTOTYPES */", prototypes).replace("/* HELPER */", helper).replace("/* EMITTED */", emitted)
    source = OUT / "probe.c"
    source.write_text(fixture)
    env = None
    if not android:
        _, env, _ = compiler_environment()
        env["LIB"] = env["LIB"].replace("\\x86", "\\x64")
    syntax = subprocess.run([str(CLANG), *HOST_FLAGS, "-DVOID_ANDROID_APP", "-I" + str(ROOT / "android/host"), "-fsyntax-only", str(helper_path)], cwd=ROOT, capture_output=True, text=True)
    (OUT / "android-syntax.txt").write_text(syntax.stdout + syntax.stderr)
    assert syntax.returncode == 0, syntax.stderr
    # Tension (tools/lift_release.py) overrides its twins of these bodies, never the 2009 names.
    release = subprocess.run([str(CLANG), *HOST_FLAGS, "-DVOID_RELEASE", "-I" + str(ROOT / "android/host"),
                              "-I" + str(ROOT / "generated/tension"), "-E", "-P", str(helper_path)],
                             cwd=ROOT, capture_output=True, text=True)
    twins = re.findall(r"^#define RENDERER_INFLATE\w* (sub_[0-9A-F]{8})$", (ROOT / "generated/tension/release_overrides.h").read_text(), re.M)
    assert release.returncode == 0 and all("void " + n + "(void)" not in release.stdout for n in names[:4])
    assert len(twins) == 4 and all("void " + n + "(void)" in release.stdout for n in twins), twins
    selected = corpus[:1] if "--quick" in sys.argv else corpus
    configs = [(0, 0), (0, 1), (1, 0), (1, 1)]
    results = []
    for local, plain in configs:
        binary = OUT / (f"probe-local{local}-plain{plain}" + ("" if android else ".exe"))
        command = [str(CLANG), "--target=x86_64-pc-windows-msvc", "-fuse-ld=link", "-O2", "-std=c11",
                   "-fno-strict-aliasing", "-fwrapv", "-DRECOMP_TRACE", "-DRECOMP_YIELD_EVERY=64",
                   *(["-DRECOMP_LOCAL_REGS"] if local else []), *(["-DRECOMP_PLAIN_MEMORY"] if plain else []),
                   str(source), "-o", str(binary)]
        if android:
            command = [str(CLANG), *build.COMMON, "-O2", "-std=c11", "-fPIE", "-pie",
                       "-DRECOMP_TRACE", "-DRECOMP_YIELD_EVERY=64",
                       *(["-DRECOMP_LOCAL_REGS"] if local else []), *(["-DRECOMP_PLAIN_MEMORY"] if plain else []),
                       str(source), "-Wl,--build-id=sha1", "-Wl,-z,max-page-size=16384", "-lz", "-lm", "-o", str(binary)]
        compiled = subprocess.run(command, env=env, capture_output=True, text=True)
        binary.with_suffix(".compile.txt").write_text(compiled.stdout + compiled.stderr)
        assert compiled.returncode == 0, compiled.stderr[:8000]
        if android:
            results.append(dict(local=local, plain=plain, command=command, returncode=0, elf=android_elf(binary),
                                output="Android CLI built and statically checked; not executed\n"))
            print(local, plain, results[-1]["output"], end="", flush=True)
            continue
        checked = subprocess.run([str(binary), str(OUT / "renderer-image.bin"), *[r["path"] for r in selected]], capture_output=True, text=True, timeout=240)
        binary.with_suffix(".run.txt").write_text(checked.stdout + checked.stderr)
        results.append(dict(local=local, plain=plain, command=command, returncode=checked.returncode,
                            output=checked.stdout + checked.stderr))
        print(local, plain, checked.stdout + checked.stderr, end="", flush=True)
        if checked.returncode:
            break
    control = None if android else negative_control(fixture, command, selected, env)
    result = dict(status=("BUILD_AND_STATIC_CHECK_PASS_NOT_RUN" if android else "PASS") if all(r["returncode"] == 0 for r in results) else "FAIL", results=results,
                  negative_control=control, main_only_release_exclusion=True, helper_host_plain_switch=False,
                  staged_source_sha256=hashlib.sha256(helper_bytes).hexdigest(),
                  fixture_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  zlib_dll_sha256=None if android else hashlib.sha256(Path("C:/Program Files/Git/mingw64/bin/zlib1.dll").read_bytes()).hexdigest(),
                  renderer_image_sha256=hashlib.sha256(image).hexdigest(), corpus=selected,
                  original_emitted_body_sha256={k: hashlib.sha256(v.encode()).hexdigest() for k, v in bodies.items()},
                  scope="Android CLI compilation only" if android else "Windows original-stream differential plus NDK syntax; no phone")
    result_path = OUT / ("android-result.json" if android else "result.json")
    result_path.write_text(json.dumps(result, indent=2))
    if android:
        args = " ".join(shlex.quote(Path(x["path"]).name) for x in selected)
        script = OUT / "run-android.sh"
        script.write_text('#!/system/bin/sh\nset -eu\ncd "$(dirname "$0")"\n' + "".join(
            f'./{r["elf"]["path"]} renderer-image.bin {args} > {r["elf"]["path"]}.run.txt 2>&1\ncat {r["elf"]["path"]}.run.txt\n' for r in results), newline="\n")
        inputs = [OUT / r["elf"]["path"] for r in results] + [OUT / "renderer-image.bin", script, result_path,
                 OUT / "runtime-fixture.h", source, *[Path(x["path"]) for x in selected]]
        manifest = OUT / "android-manifest.json"
        manifest.write_text(json.dumps({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}, indent=2))
        with tarfile.open(OUT / "android-cli.tar", "w", format=tarfile.USTAR_FORMAT) as tar:
            for path in [*inputs, manifest]:
                info = tar.gettarinfo(str(path), arcname=path.name)
                info.mode = 0o755 if path == script or path.name.startswith("probe-local") else 0o644
                with path.open("rb") as content:
                    tar.addfile(info, content)
    assert helper_path.read_bytes() == helper_bytes, "prototype changed during the oracle run"
    assert result["status"] in ("PASS", "BUILD_AND_STATIC_CHECK_PASS_NOT_RUN")
    if control:
        print("Bad total_out public-field negative control: expected rejection PASS", flush=True)


if __name__ == "__main__":
    main()
