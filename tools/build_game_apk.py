"""Package the ARM64 game library into an APK (no Gradle) and optionally install it.

    python tools/build_game_apk.py [--install] [--serial SERIAL]
                                   [--release-only NAME] [--java-only] [--push-lib]
The library comes from tools/build_android.py --shared, packed as an xz
stream per 32 MiB chunk in assets/native (unpacked on the first start by
lib/libvoidxz.so, NativeLibrary.java), with the PE images it was lifted from (assets/lifted, assets/lifted-<release>: Images.java
copies them into the app's files unless /sdcard/TheVoid holds them, as
tools/push_game_data.py puts them); the game's own files are where the
launcher found or unpacked them, the writable profile in that folder's userdata.
--release-only packs one library (void for the 2009 build, or a release
name such as tension); --java-only packs none and no images: the activity
then loads the library pushed into its own files by --push-lib (run-as,
debuggable APK), which keeps iterations on the touch layer to a small install.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from xml.etree import ElementTree as ET

from build_android import TOOLCHAIN
from push_game_data import GAMEMODULE_SHA256, LIFTED, sha256

from toolchain import SDK, JAVA_HOME, ADB

ROOT = Path(__file__).resolve().parents[1]
TOOLS = SDK / "build-tools/36.1.0"
ANDROID_JAR = SDK / "platforms/android-36/android.jar"
OUT = ROOT / "build/android-game"


def run(*args, **kwargs):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True, **kwargs)
    if result.returncode:
        print(result.stdout[-3000:], result.stderr[-3000:])
        raise SystemExit(f"{Path(str(args[0])).name} failed ({result.returncode})")
    return result


XZ_EMBEDDED = ROOT / "reference/xz-embedded"   # dependencies.json (0BSD)
NATIVE_XZ = ROOT / "build/native-xz"


def xz_tool():
    """XZ Utils 5.4+ (the ARM64 branch filter; Python's lzma module lacks it):
    $XZ, the PATH, else Git for Windows' copy."""
    for candidate in (os.environ.get("XZ"), shutil.which("xz"), Path(os.environ.get("ProgramFiles", "")) / "Git/mingw64/bin/xz.exe"):
        if candidate and Path(candidate).is_file():
            version = run(candidate, "--robot", "--version").stdout
            number = int(next(line for line in version.splitlines() if line.startswith("XZ_VERSION=")).split("=")[1])
            if number >= 50040002:
                return candidate
    raise SystemExit("xz 5.4 or newer is needed (XZ Utils; Git for Windows has one in mingw64/bin)")


CHUNK = 32 << 20   # NativeLibrary.java / android/unpack/unpack.c take it from assets/native/index.txt


def compress_library(stripped):
    """The stripped library as xz: LZMA2 at preset 9e behind the ARM64 branch
    filter, CRC32 checked. Deflate's 32 KiB window misses the lifted code's
    long repeats (libvoid.so: 126 MB deflated, 60 MB this way). It is cut in
    CHUNK pieces packed as streams of their own, one after another: the
    phone unpacks them on all cores at once (about 7 % larger than one
    stream). Made once per library content. Returns (path, sha256, sizes)."""
    digest = sha256(stripped)
    out = NATIVE_XZ / f"{stripped.name}.{digest[:16]}.{CHUNK >> 20}m.xz"
    table = out.with_suffix(".sizes")
    if not (out.is_file() and table.is_file()):
        NATIVE_XZ.mkdir(parents=True, exist_ok=True)
        for old in NATIVE_XZ.glob(f"{stripped.name}.*"):
            old.unlink()
        data = stripped.read_bytes()
        tool = xz_tool()

        def pack(at):
            return subprocess.run([tool, "--stdout", "--arm64", "--lzma2=preset=9e", "--check=crc32", "--threads=1"],
                                  input=data[at:at + CHUNK], capture_output=True, check=True).stdout

        with ThreadPoolExecutor(max_workers=max(1, (os.cpu_count() or 4) - 2)) as pool:
            streams = list(pool.map(pack, range(0, len(data), CHUNK)))
        part = out.with_suffix(".part")
        part.write_bytes(b"".join(streams))
        table.write_text(",".join(str(len(s)) for s in streams))
        part.replace(out)
    return out, digest, table.read_text()


def build_unpacker():
    """libvoidxz.so: XZ Embedded and its JNI entry (android/unpack/unpack.c),
    which unpacks a library from assets/native on the first start."""
    if not (XZ_EMBEDDED / "linux/include/linux/xz.h").is_file():
        raise SystemExit("reference/xz-embedded is missing: tools/fetch_dependencies.ps1")
    out = OUT / "libvoidxz.so"
    xz = XZ_EMBEDDED / "linux/lib/xz"
    run(TOOLCHAIN / "bin/clang.exe", "--target=aarch64-linux-android26", "-O2", "-std=gnu11", "-fPIC", "-shared",
        "-Wall", "-Wextra", "-DXZ_DEC_ARM64", "-DXZ_USE_CRC64", "-DXZ_DEC_SINGLE",
        "-I" + str(XZ_EMBEDDED / "linux/include/linux"), "-I" + str(XZ_EMBEDDED / "userspace"),
        ROOT / "android/unpack/unpack.c", *(xz / name for name in ("xz_crc32.c", "xz_crc64.c", "xz_dec_stream.c",
                                                                  "xz_dec_lzma2.c", "xz_dec_bcj.c")),
        "-Wl,-z,max-page-size=16384", "-Wl,--build-id=sha1", "-Wl,-s", "-pthread", "-landroid", "-llog", "-o", out)
    return out


def lifted_images(release):
    """The images a library was lifted from, as tools/push_game_data.py puts
    them on a phone: the 2009 build's (generated/input and its GameModule.dll)
    or a release's (generated/<release>/input)."""
    if release is None:
        files = [ROOT / "generated/input" / name for name in LIFTED + ["GameModule.dll"]]
        if sha256(files[-1]) != GAMEMODULE_SHA256:
            raise SystemExit("generated/input/GameModule.dll is not the lifted build's (tools/push_game_data.py)")
        return "lifted", files
    return f"lifted-{release}", sorted(p for p in (ROOT / "generated" / release / "input").iterdir() if p.is_file())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL") or os.environ.get("VOID_SERIAL"))
    parser.add_argument("--skip-native", action="store_true")
    parser.add_argument("--global-regs", action="store_true", help="build_android.py upstream mode (see there)")
    parser.add_argument("--volatile-memory", action="store_true", help="build_android.py upstream mode (see there)")
    parser.add_argument("--release-only", help="pack only this library: void (2009 build) or a release name")
    parser.add_argument("--java-only", action="store_true", help="no native library in the APK (see --push-lib)")
    parser.add_argument("--push-lib", action="store_true",
                        help="copy the built libraries into the installed app's files (development)")
    args = parser.parse_args()
    if (args.install or args.push_lib) and not args.serial:
        parser.error("deployment requires --serial SERIAL or ANDROID_SERIAL")
    if not os.environ.get("JAVA_HOME"):
        parser.error("set JAVA_HOME to a JDK installation")
    for tool in (TOOLS / "aapt2.exe", TOOLS / "d8.bat", TOOLS / "zipalign.exe",
                 TOOLS / "apksigner.bat", ANDROID_JAR, JAVA_HOME / "bin/javac.exe",
                 JAVA_HOME / "bin/keytool.exe", TOOLCHAIN / "bin/clang.exe"):
        if not tool.is_file():
            parser.error(f"missing build tool: {tool}; check ANDROID_HOME, ANDROID_NDK and JAVA_HOME")
    if args.release_only not in (None, "void") and not (ROOT / "generated" / args.release_only / "release.json").is_file():
        parser.error("requested release is not prepared; run tools/prepare_android.py --tension first")
    if args.java_only:
        args.skip_native = True
    modes = [(flag, name) for flag, name, on in (("--global-regs", "globalregs", args.global_regs),
                                                 ("--volatile-memory", "volatilemem", args.volatile_memory)) if on]
    want_2009 = args.release_only in (None, "void")
    if want_2009:
        run(sys.executable, ROOT / "tools/build_shader_cache.py")
    if not args.skip_native and want_2009:
        subprocess.run([sys.executable, str(ROOT / "tools/build_android.py"), "--shared", "--jobs", "12",
                        *(flag for flag, _ in modes)], check=True)
    library = ROOT / ("build/arm64-" + "-".join(name for _, name in modes) if modes else "build/arm64") / "libvoid.so"
    # Other releases lifted by tools/lift_release.py (the 2008 Polish "Tension"):
    # each runs its own library, which the activity picks for that release.
    releases, release_names = [], []
    for config in sorted((ROOT / "config/releases").glob("*.json")):
        name = config.stem
        if not (ROOT / "generated" / name / "release.json").is_file():
            continue
        if args.release_only not in (None, name):
            continue
        if not args.skip_native:
            subprocess.run([sys.executable, str(ROOT / "tools/build_android.py"), "--shared", "--jobs", "12",
                            "--release", name], check=True)
        releases.append(ROOT / f"build/arm64-{name}" / f"libvoid_{name}.so")
        release_names.append(name)
    if OUT.exists():
        OUT.resolve().relative_to(ROOT.resolve())
        shutil.rmtree(OUT)
    (OUT / "classes").mkdir(parents=True)
    (OUT / "dex").mkdir()
    # Resources: the launcher's adaptive icon (android/app/res).
    run(TOOLS / "aapt2.exe", "compile", "--dir", ROOT / "android/app/res", "-o", OUT / "res.zip")
    run(TOOLS / "aapt2.exe", "link", "-I", ANDROID_JAR, "--manifest", ROOT / "android/app/AndroidManifest.xml",
        "-o", OUT / "base.apk", OUT / "res.zip")
    sources = sorted((ROOT / "android/app/src").rglob("*.java"))
    run(JAVA_HOME / "bin/javac.exe", "--release", "8", "-cp", ANDROID_JAR, "-d", OUT / "classes", *sources)
    classes = sorted((OUT / "classes").rglob("*.class"))
    run(TOOLS / "d8.bat", "--lib", ANDROID_JAR, "--min-api", "26", "--output", OUT / "dex", *classes, shell=False)
    # The port's patched game scripts (tools/patch_scripts.py): the activity
    # installs those made from the running release's originals.
    run(sys.executable, ROOT / "tools/patch_scripts.py")
    overrides = ROOT / "build/overrides"
    unsigned = OUT / "unsigned.apk"
    shutil.copy(OUT / "base.apk", unsigned)
    with zipfile.ZipFile(unsigned, "a", zipfile.ZIP_DEFLATED, compresslevel=9) as apk:
        apk.write(OUT / "dex/classes.dex", "classes.dex")
        apk.write(ROOT / "LICENSE", "assets/licenses/GPL-3.0.txt")
        apk.write(ROOT / "THIRD_PARTY_NOTICES.md", "assets/licenses/THIRD_PARTY_NOTICES.md")
        for f in sorted(overrides.rglob("*")):
            if f.is_file():
                apk.write(f, "assets/overrides/" + f.relative_to(overrides).as_posix())
        # The D3DX shader cache made on the PC (tools/shader_service.py): the
        # device cannot compile HLSL, so every profile gets what is known
        # (ShaderCache.java) - a fresh profile, full HDR's shaders. About two
        # thirds of the results are byte-identical (distinct shader keys that
        # compile to the same bytecode), so each unique content ships once and
        # the rest become symbolic links on the device (ShaderCache.java). The index
        # names every shader; an alias carries a fourth field, the name whose
        # bytes were shipped. Content is grouped within an extension so a .bin
        # never aliases an .err.
        shaders = sorted(p for p in (ROOT / "build/shadercache/results").glob("*") if p.suffix in (".bin", ".err"))
        canonical = {}
        index = []
        for f in shaders:
            digest = sha256(f)
            key = (f.suffix, digest)
            master = canonical.get(key)
            line = f"{f.name} {f.stat().st_size} {digest}"
            if master is None:
                canonical[key] = f.name
                apk.write(f, "assets/shadercache/" + f.name)
                index.append(line + "\n")
            else:
                index.append(f"{line} {master}\n")
        apk.writestr("assets/shadercache/index.txt", "".join(index))
        recipes = sorted((ROOT / "build/shaderwarm").glob("*.bin"))
        for f in recipes:
            apk.write(f, "assets/shaderwarm/" + f.name)
        apk.writestr("assets/shaderwarm/index.txt", "".join(f"{f.name} {f.stat().st_size} {sha256(f)}\n" for f in recipes))
        # The unpacker of the libraries below (NativeLibrary.java): a few KB.
        apk.write(build_unpacker(), "lib/arm64-v8a/libvoidxz.so")
        if not args.java_only:
            # Keep the build's symbols for diagnostics; only strip APK copies.
            # The libraries go as xz streams, stored (no deflate on top), with
            # their unpacked size and SHA-256 (NativeLibrary.java).
            stripped = []
            for native in ([library] if want_2009 else []) + releases:
                stripped.append(OUT / native.name)
                run(TOOLCHAIN / "bin/llvm-strip.exe", "--strip-unneeded", "-o", stripped[-1], native)
            packed = [compress_library(lib) for lib in stripped]
            index = []
            for lib, (xz, digest, sizes) in zip(stripped, packed):
                apk.write(xz, f"assets/native/{lib.name}.xz", compress_type=zipfile.ZIP_STORED)
                index.append(f"{lib.name} {lib.stat().st_size} {digest} {CHUNK} {sizes}\n")
                print(f"{lib.name}: {lib.stat().st_size / 1e6:.1f} MB, packed {xz.stat().st_size / 1e6:.1f} MB")
                lib.unlink()
            apk.writestr("assets/native/index.txt", "".join(index))
            # Each library's images, so that a phone needs only the game's files.
            for folder, files in ([lifted_images(None)] if want_2009 else []) + [lifted_images(n) for n in release_names]:
                index = []
                for f in files:
                    apk.write(f, f"assets/{folder}/{f.name}")
                    index.append(f"{f.name} {f.stat().st_size} {sha256(f)}\n")
                apk.writestr(f"assets/{folder}/index.txt", "".join(index))
    aligned = OUT / "aligned.apk"
    run(TOOLS / "zipalign.exe", "-f", "-P", "16", "4", unsigned, aligned)   # stored .so entries on 16 KB pages
    keystore = ROOT / "build/android/debug.keystore"
    if not keystore.exists():
        keystore.parent.mkdir(parents=True, exist_ok=True)
        run(JAVA_HOME / "bin/keytool.exe", "-genkeypair", "-keystore", keystore, "-storepass", "android",
            "-keypass", "android", "-alias", "androiddebugkey", "-keyalg", "RSA", "-keysize", "2048",
            "-validity", "10000", "-dname", "CN=The Void Port")
    apk = OUT / "the-void.apk"
    run(TOOLS / "apksigner.bat", "sign", "--ks", keystore, "--ks-pass", "pass:android", "--key-pass", "pass:android",
        "--out", apk, aligned)
    run(TOOLS / "apksigner.bat", "verify", "--verbose", apk)
    run(TOOLS / "zipalign.exe", "-c", "-P", "16", "4", apk)
    print(f"APK: {apk} ({apk.stat().st_size / 1e6:.1f} MB)")
    if not args.java_only and args.release_only is None and not modes:
        version = ET.parse(ROOT / "android/app/AndroidManifest.xml").getroot().get(
            "{http://schemas.android.com/apk/res/android}versionName")
        published = ROOT / "pub" / f"the-void-{version}-{sha256(apk)[:8]}.apk"
        published.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(apk, published)
        print(f"Release: {published}")
    if args.install:
        run(ADB, "-s", args.serial, "install", "-r", "-g", apk)
        print("installed")
        if not args.java_only and not args.push_lib:
            # A full APK runs its own libraries: drop development copies (they would win).
            subprocess.run([str(ADB), "-s", args.serial, "shell", "run-as org.thevoid.port sh -c 'rm -f files/lib*.so'"],
                           capture_output=True)
    if args.push_lib:
        for lib in ([library] if want_2009 else []) + releases:
            run(ADB, "-s", args.serial, "push", lib, f"/data/local/tmp/void/{lib.name}")
            run(ADB, "-s", args.serial, "shell", f"run-as org.thevoid.port sh -c 'mkdir -p files && "
                f"cp /data/local/tmp/void/{lib.name} files/{lib.name}.new && mv files/{lib.name}.new files/{lib.name}'")
            print(f"pushed {lib.name} into the app's files")


if __name__ == "__main__":
    main()
