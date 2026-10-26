"""Native Adler32 versus the emitted leaf and complete original inflater."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zlib
import gzip

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
HELPER = ROOT / "android/host/renderer_adler_native.c"
sys.path.insert(0, str(ROOT / "tools"))
from build_android import CLANG, HOST_FLAGS
from build_x86_incremental import compiler_environment
import pefile


def function(source, name):
    found = re.search(r"^void " + name + r"\(void\) \{.*?^\}", source, re.M | re.S)
    assert found, name
    return found[0]


def main():
    out = ROOT / "build/adler-native-test"
    out.mkdir(parents=True, exist_ok=True)
    paths = [ROOT / ("generated/renderer-x86/renderer_" + n + ".c") for n in ("0101", "0102")]
    texts = [path.read_text() for path in paths]
    names = ["sub_1611E830", "sub_1611E7D0", "sub_1611E9F0", "sub_1611FFF0", "sub_1611CDB0",
             "sub_1611E900", "sub_16120040", "sub_16121D60", "sub_16122220"]
    bodies = {name: function(next(text for text in texts if "void " + name + "(void)" in text), name)
              for name in names}
    bodies["sub_16120040"] = bodies["sub_16120040"].replace("void sub_16120040(void)", "void original_adler(void)", 1)
    header = (ROOT / "android/runtime/recomp_types.h").read_text()
    header = header.replace("#if defined(_MSC_VER) || !defined(__aarch64__)", "#if 0", 1)
    header = re.sub(r"static inline uint64_t __rdtsc\(void\) \{.*?\n\}", "", header, flags=re.S)
    header, count = re.subn(r"^#define ADDR\(va\).+$", "static void *guest_address(uint32_t va);\n#define ADDR(va) ((uintptr_t)guest_address((uint32_t)(va)))", header, flags=re.M)
    assert count == 1
    (out / "runtime-fixture.h").write_text(header)
    image = pefile.PE(str(ROOT / "generated/input/RendererD3D.dll")).get_memory_mapped_image()
    (out / "renderer-image.bin").write_bytes(image)
    # Existing real game resource, plus synthetic compressibility extremes.
    sys.path.insert(0, str(ROOT / "tools"))
    from patch_scripts import read_entry
    actual = read_entry("research/vfs-index.json", "Scenes\\Girl\\ire.xml")
    payloads = [actual, b"", b"a", bytes(range(256)) * 257, b"boundary" * 10000]
    records, originals = [], []
    for i, payload in enumerate(payloads):
        for wrapper, compressor in (("zlib", zlib.compress), ("gzip", gzip.compress)):
            packed = compressor(payload)
            checksum_at = -8 if wrapper == "gzip" else -1
            corrupt = bytearray(packed)
            corrupt[checksum_at] ^= 1
            variants = [("valid", packed), ("truncated", packed[:-1]),
                        ("bad-checksum", bytes(corrupt)), ("bad-header", b"XX" + packed[2:])]
            for label, data in variants:
                path = out / f"stream-{i}-{wrapper}-{label}.bin"
                path.write_bytes(data)
                if label == "valid":
                    path.with_suffix(".expected").write_bytes(payload)
                records.append(str(path))
    # Actual original compressed sub-blocks, not recompressed test substitutes.
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
            path = out / (resource.split("\\")[-1] + "-original-valid.bin")
            path.write_bytes(packed)
            path.with_suffix(".expected").write_bytes(payload)
            records.append(str(path))
            originals.append(dict(resource=resource, offset=offset, compressed_bytes=used, output_bytes=len(payload),
                                  compressed_sha256=hashlib.sha256(packed).hexdigest()))
            break
        else:
            raise AssertionError("no complete original sub-block in " + resource)
    declarations = (ROOT / "tests/local_fpu_probe.c").read_text().split("#define BASE", 1)[0]
    helper = re.sub(r"^#include .*\n", "", HELPER.read_text(), flags=re.M)
    prototypes = "\n".join("void " + name + "(void);" for name in names)
    prototypes += "\nvoid sub_16120040_lifted(void); void sub_1612A0F0(void); void sub_16125D86(void);\n"
    fixture = (HERE / "adler_native_probe.c").read_text().replace("/* DECLARATIONS */", declarations)
    fixture = fixture.replace("/* PROTOTYPES */", prototypes).replace("/* HELPER */", helper)
    fixture = fixture.replace("/* EMITTED */", "\n".join(bodies.values()))
    source = out / "probe.c"
    source.write_text(fixture)
    syntax = subprocess.run([str(CLANG), *HOST_FLAGS, "-fsyntax-only", str(HELPER)],
                            cwd=ROOT, capture_output=True, text=True)
    (out / "android-syntax.txt").write_text(syntax.stdout + syntax.stderr)
    assert syntax.returncode == 0, syntax.stderr
    _, env, _ = compiler_environment()
    env["LIB"] = env["LIB"].replace("\\x86", "\\x64")
    results = []
    for local in (False, True):
        for plain in (False, True):
            binary = out / f"probe-local{int(local)}-plain{int(plain)}.exe"
            command = [str(CLANG), "--target=x86_64-pc-windows-msvc", "-fuse-ld=link", "-O2", "-std=c11",
                       "-fno-strict-aliasing", "-fwrapv", "-DRECOMP_TRACE", "-DRECOMP_YIELD_EVERY=64",
                       *(["-DRECOMP_LOCAL_REGS"] if local else []), *(["-DRECOMP_PLAIN_MEMORY"] if plain else []),
                       str(source), "-o", str(binary)]
            compiled = subprocess.run(command, env=env, capture_output=True, text=True)
            binary.with_suffix(".compile.txt").write_text(compiled.stdout + compiled.stderr)
            assert compiled.returncode == 0, compiled.stderr[:4000]
            checked = subprocess.run([str(binary), str(out / "renderer-image.bin"), *records], capture_output=True, text=True, timeout=60)
            binary.with_suffix(".run.txt").write_text(checked.stdout + checked.stderr)
            assert checked.returncode == 0, checked.stdout + checked.stderr
            print(local, plain, checked.stdout.strip(), flush=True)
            results.append(dict(local=local, plain=plain, output=checked.stdout.strip()))
    (out / "result.json").write_text(json.dumps(dict(status="PASS", results=results,
        original_image_sha256=hashlib.sha256(image).hexdigest(), real_resource_sha256=hashlib.sha256(actual).hexdigest(),
        original_compressed_blocks=originals,
        emitted_bodies_sha256={name: hashlib.sha256(body.encode()).hexdigest() for name, body in bodies.items()},
        native_api="existing Git Windows zlib1.dll adler32; Android candidate links existing system libz",
        scope="ABI return/callee-saved state, guest persistent memory, original inflate status/output/allocator calls; volatile GPR/flags and dead stack scratch are discarded by original callers"), indent=2))


if __name__ == "__main__":
    main()
