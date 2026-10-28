"""Build libtexconv.so, the launcher's texture converter (android/texconv), for arm64.

It links astcenc (reference/astcenc, NEON) and etcpak (reference/etcpak), both
pinned upstream submodules (dependencies.json). Every invocation recompiles and relinks:
the library is small, and stale objects cannot hide a changed header.
tools/build_game_apk.py runs this and packs the library as lib/arm64-v8a.
"""
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_android import CLANG, TARGET  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/arm64-texconv"
LIBRARY = OUT / "libtexconv.so"
CXX = CLANG.with_name("clang++.exe")
ASTC = ["-DASTCENC_NEON=1", "-DASTCENC_SVE=0", "-DASTCENC_SSE=0", "-DASTCENC_AVX=0", "-DASTCENC_POPCNT=0", "-DASTCENC_F16C=0"]
COMMON = ["--target=" + TARGET, "-O2", "-fPIC", "-fvisibility=hidden", "-ffunction-sections", "-fdata-sections", "-std=c++17",
          "-ffile-prefix-map=" + str(ROOT) + "=."]


def units():
    out = [(p, ASTC) for p in sorted((ROOT / "reference/astcenc/Source").glob("astcenc_*.cpp"))]
    out += [(ROOT / "reference/etcpak" / n, ["-DBCDEC_STATIC", "-DBCDEC_IMPLEMENTATION"])
            for n in ("ProcessRGB.cpp", "Tables.cpp", "Dither.cpp", "Decode.cpp")]
    out += [(ROOT / "android/texconv/texconv.cpp", ASTC + ["-Wall", "-Wextra", "-Werror"]),
            (ROOT / "android/texconv/texconv_jni.cpp", ["-Wall", "-Wextra", "-Werror"])]
    return out


def compile_unit(unit):
    source, flags = unit
    obj = OUT / "obj" / (source.parent.name + "_" + source.stem + ".o")
    command = [str(CXX), *COMMON, *flags, "-c", str(source), "-o", str(obj)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f"{source.name}: {result.stdout}{result.stderr}")
    return obj


def main():
    for needed in ("reference/astcenc/Source/astcenc.h", "reference/etcpak/ProcessRGB.hpp"):
        if not (ROOT / needed).is_file():
            raise SystemExit(f"missing {needed}: run git submodule update --init --recursive")
    (OUT / "obj").mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=12) as pool:
        objects = list(pool.map(compile_unit, units()))
    command = [str(CXX), "--target=" + TARGET, "-shared", "-fuse-ld=lld", "-static-libstdc++", "-Wl,--gc-sections",
               "-Wl,--no-undefined", "-Wl,-z,max-page-size=16384", "-Wl,--build-id=sha1", *map(str, objects),
               "-llog", "-o", str(LIBRARY)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f"link: {result.stdout}{result.stderr}")
    print(f"texconv: {LIBRARY} ({LIBRARY.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
