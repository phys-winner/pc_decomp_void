"""Build the generated nine-module x86 stage with hash-validated object reuse.

Generation remains separate. Use --generated-only while native UI sources are
being edited; a later full run compiles native sources and links the game.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
MODULES = ("game", "gamemodule", "engine", "fs", "vfs", "sound", "video", "renderer", "nxcharacter")
OUTPUT = ROOT / "build/x86/incremental-stage"
BASE_OPTIONS = ["/nologo", "/O2", "/W0", "/std:c11", "/MP2", "/DRECOMP_TRACE", "/D_CRT_SECURE_NO_WARNINGS",
    "/Inative", "/Ireference/pcrecomp/runtime/recomp32", "/Ireference/pcrecomp/runtime/native32"]
DEFINES = ["/DVOID_LIFT_" + name for name in
    ("GAMEMODULE", "ENGINE", "FILESYSTEMS", "SOUND", "MEDIA", "RENDERER", "NXCHARACTER")]


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def key(path):
    return path.relative_to(ROOT).as_posix()


def fingerprint(source_hash, headers, compiler, options):
    value = dict(source_sha256=source_hash, headers=headers, compiler=compiler, options=options)
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def valid_object(entry, expected):
    if (not isinstance(entry, dict) or entry.get("fingerprint") != expected or
            not entry.get("object_sha256") or not isinstance(entry.get("object"), str)):
        return False
    path = (ROOT / entry["object"]).resolve()
    return (path.is_relative_to((ROOT / "build/x86").resolve()) and path.suffix == ".obj"
            and path.is_file() and sha(path) == entry["object_sha256"])


def renderer_import(source, source_hash, headers, compiler, options, receipt):
    if (receipt.get("status") != "COMPILED" or not receipt.get("source_hashes_unchanged") or
            receipt.get("mode") != "global-offset" or receipt.get("options") != options or
            receipt.get("compiler") != compiler["path"] or receipt.get("compiler_sha256") != compiler["sha256"] or
            receipt.get("sdk") != compiler["sdk"]):
        return None
    previous = {name.replace("\\", "/"): digest.lower() for name, digest in receipt["source_hashes"].items()}
    if previous.get(source) != source_hash or any(previous.get(name) != digest for name, digest in headers.items()):
        return None
    for row in receipt["results"]:
        if row["source"].replace("\\", "/") == source and row["exit"] == 0 and row["optimization"] == "/O2":
            entry = {"fingerprint": fingerprint(source_hash, headers, compiler, options),
                "object": row["object"].replace("\\", "/"), "object_sha256": row["object_sha256"]}
            if valid_object(entry, entry["fingerprint"]):
                return entry
    return None


def compiler_environment():
    vswhere = str(Path(os.environ["ProgramFiles(x86)"]) / "Microsoft Visual Studio/Installer/vswhere.exe")
    visual_studio = Path(subprocess.check_output([vswhere, "-latest", "-products", "*", "-property", "installationPath"], text=True).strip())
    msvc = sorted((visual_studio / "VC/Tools/MSVC").iterdir(), reverse=True)[0]
    sdk_root = Path(os.environ["ProgramFiles(x86)"]) / "Windows Kits/10"
    sdk = sorted((sdk_root / "Lib").iterdir(), reverse=True)[0].name
    compiler = msvc / "bin/Hostx64/x86/cl.exe"
    env = os.environ.copy()
    if env.get("CL") or env.get("_CL_"):
        raise ValueError("CL/_CL_ overrides are incompatible with pinned compilation options")
    env["PATH"] = str(sdk_root / f"bin/{sdk}/x64") + os.pathsep + str(compiler.parent) + os.pathsep + env["PATH"]
    env["INCLUDE"] = ";".join(str(p) for p in (msvc / "include", sdk_root / f"Include/{sdk}/ucrt",
        sdk_root / f"Include/{sdk}/shared", sdk_root / f"Include/{sdk}/um"))
    env["LIB"] = ";".join(str(p) for p in (msvc / "lib/x86", sdk_root / f"Lib/{sdk}/ucrt/x86", sdk_root / f"Lib/{sdk}/um/x86"))
    return compiler, env, dict(path=str(compiler), sha256=sha(compiler), sdk=sdk)


def project_headers(names):
    paths = [ROOT / "native/recomp_types.h"]
    for directory in ("reference/pcrecomp/runtime/recomp32", "reference/pcrecomp/runtime/native32"):
        paths += sorted((ROOT / directory).glob("*.h"))
    for name in names:
        paths += sorted((ROOT / f"generated/{name}-x86").glob("*.h"))
    return paths


def menu_inputs():
    receipt_path = ROOT / "build/native-ui/patch-receipt.json"
    header = ROOT / "build/native-ui/menu_asset.h"
    receipt = json.loads(receipt_path.read_text())
    payload = Path(receipt["payload"]).resolve()
    expected = (ROOT / "build/runtime-assets/Scripts/ui/main_menu.bin").resolve()
    match = re.findall(r'^#define VOID_MENU_ASSET_SHA256 "([0-9a-fA-F]{64})"$', header.read_text(), re.M)
    if payload != expected or len(match) != 1 or sha(payload) != receipt["sha256"] or match[0].lower() != receipt["sha256"]:
        raise ValueError("Native menu header/payload/receipt hash mismatch")
    return [receipt_path, header, payload]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated-only", action="store_true", help="Prepare generated objects without native UI sources or linking")
    parser.add_argument("--plan", action="store_true", help="Print validated reuse/compile decisions without building")
    arguments = parser.parse_args()
    os.chdir(ROOT)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    compiler, environment, identity = compiler_environment()
    reports, sources = [], []
    for name in MODULES:
        report_path = ROOT / f"generated/{name}-x86/report.json"
        report = json.loads(report_path.read_text())
        if report.get("status", "GENERATED") != "GENERATED":
            raise ValueError(f"Finish {name} generation before building")
        reports.append(report_path)
        files = report.get("sources")
        if files is None and name in ("game", "gamemodule"):
            prefix = "recomp" if name == "game" else name
            files = [f"{prefix}_{i:04d}.c" for i in range((report["functions"] + 99) // 100)]
        if not files or any(Path(filename).name != filename or not filename.endswith(".c") for filename in files):
            raise ValueError(f"Invalid {name} generated source list")
        sources += [ROOT / f"generated/{name}-x86" / filename for filename in files]
    sources += [ROOT / "generated/nxcharacter-x86/recomp_dispatch.c"]
    menu = []
    if not arguments.generated_only:
        subprocess.run([sys.executable, str(ROOT / "tools/prepare_native_runtime.py")], check=True)
        menu = menu_inputs()
        sources += [ROOT / path for path in ("native/windows_host.c", "native/window_policy.c", "native/void_runtime.c", "native/asset_overrides.c",
            "native/settings_debug.c", "native/settings_regex.cpp", "reference/pcrecomp/runtime/recomp32/image_loader.c",
            "reference/pcrecomp/runtime/recomp32/recomp_trace.c")]
    if len({path.stem for path in sources}) != len(sources):
        raise ValueError("Source/object basename collision")
    renderer_headers = project_headers(MODULES[:-1])
    generated_headers = project_headers(MODULES)
    native_headers = []
    if menu:
        native_headers = generated_headers + sorted((ROOT / "native").glob("*.h")) + menu
        native_headers += sorted((ROOT / "build/native-ui").glob("*.h"))
        native_headers += sorted((ROOT / "reference/pcrecomp/runtime/native32").glob("*.c"))
        native_headers += [ROOT / "generated/native-runtime/native32.c", ROOT / "tools/prepare_native_runtime.py"]
    headers = {group: {key(path): sha(path) for path in paths} for group, paths in
        (("renderer", renderer_headers), ("generated", generated_headers), ("native", native_headers))}
    watched = set(sources + reports + renderer_headers + generated_headers + (native_headers if menu else []))
    before = {key(path): sha(path) for path in watched}
    cache_path = OUTPUT / "object-receipt.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    legacy_path = ROOT / "build/x86/renderer-stage/build-receipt.json"
    legacy = json.loads(legacy_path.read_text()) if legacy_path.exists() else {}
    entries, compile_jobs, reused = {}, [], []
    for path in sources:
        source = key(path)
        group = "renderer" if source.startswith("generated/renderer-x86/") else "generated" if source.startswith("generated/") else "native"
        includes = MODULES[:-1] if group == "renderer" else MODULES
        options = BASE_OPTIONS + [f"/Igenerated/{name}-x86" for name in includes]
        if group == "native": options += DEFINES + ["/Ibuild/native-ui"]
        if source == "generated/engine-x86/engine_0026.c":
            options = ["/O1" if option == "/O2" else option for option in options]
        if path.suffix == ".cpp":
            options = ["/std:c++17" if option == "/std:c11" else option for option in options] + ["/EHsc"]
        digest = fingerprint(before[source], headers[group], identity, options)
        entry = cache.get(source)
        origin = "incremental-receipt"
        if not valid_object(entry, digest) and group == "renderer":
            entry = renderer_import(source, before[source], headers[group], identity, options, legacy)
            origin = "renderer-stage-receipt"
        if valid_object(entry, digest):
            entries[source] = entry
            reused.append(dict(source=source, origin=origin, object=entry["object"]))
        else:
            compile_jobs.append((path, options, digest))
    plan = dict(source_count=len(sources), reused_count=len(reused), compile_count=len(compile_jobs),
        reused=reused, compile=[key(path) for path, _, _ in compile_jobs], generated_only=arguments.generated_only)
    (OUTPUT / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    print(json.dumps({name: plan[name] for name in ("source_count", "reused_count", "compile_count", "generated_only")}), flush=True)
    if arguments.plan: return
    started = time.monotonic()

    def compile_source(job):
        path, options, digest = job
        object_path = OUTPUT / (path.stem + ".obj")
        started_source = time.monotonic()
        with (OUTPUT / (path.stem + ".log")).open("w") as log:
            result = subprocess.run([str(compiler), *options, "/c", key(path), f"/Fo{object_path}"], cwd=ROOT,
                env=environment, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode: raise RuntimeError(f"Compilation failed: {key(path)}; see {path.stem}.log")
        return key(path), dict(fingerprint=digest, object=key(object_path), object_sha256=sha(object_path),
            options=options, seconds=time.monotonic() - started_source)

    with ThreadPoolExecutor(max_workers=2) as pool:
        for number, future in enumerate(as_completed([pool.submit(compile_source, job) for job in compile_jobs]), 1):
            source, entry = future.result()
            entries[source] = entry
            if number % 20 == 0 or number == len(compile_jobs): print(f"Compiled {number}/{len(compile_jobs)}", flush=True)
    if before != {key(path): sha(path) for path in watched} or sha(compiler) != identity["sha256"]:
        raise RuntimeError("Build input changed during compilation; cache was not committed")
    if not all(valid_object(entry, entry["fingerprint"]) for entry in entries.values()):
        raise RuntimeError("Object changed during compilation; cache was not committed")
    cache.update(entries)
    pending_cache = cache_path.with_suffix(".pending.json")
    pending_cache.write_text(json.dumps(cache, indent=2) + "\n")
    os.replace(pending_cache, cache_path)
    receipt = dict(status="COMPILED", **plan, compiler=identity, source_hashes=before,
        object_hashes={source: entry["object_sha256"] for source, entry in entries.items()}, seconds=time.monotonic() - started,
        source_hashes_unchanged=True, execution="UNVERIFIED")
    if not arguments.generated_only:
        pending = OUTPUT / "void-x86-nxcharacter.pending.exe"
        pdb = pending.with_suffix(".pdb")
        link = ["/nologo", *[str(ROOT / entries[key(path)]["object"]) for path in sources], f"/OUT:{pending}",
            "/MACHINE:X86", "/BASE:0x50000000", "/DYNAMICBASE:NO", "/STACK:262144", "/MANIFEST:EMBED", "/MANIFESTUAC:NO", "/DEBUG", f"/PDB:{pdb}"]
        response = OUTPUT / "link.rsp"
        response.write_text("\n".join(subprocess.list2cmdline([argument]) for argument in link))
        with (OUTPUT / "link.log").open("w") as log:
            result = subprocess.run([str(compiler.with_name("link.exe")), "@" + str(response)], cwd=ROOT,
                env=environment, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode: raise RuntimeError("Link failed; see build/x86/incremental-stage/link.log")
        if (before != {key(path): sha(path) for path in watched} or
                not all(valid_object(entry, entry["fingerprint"]) for entry in entries.values())):
            raise RuntimeError("Build input changed during linking; canonical executable was not replaced")
        with pending.open("rb") as handle:
            dos = handle.read(64)
            if dos[:2] != b"MZ": raise RuntimeError("Linked executable has no DOS header")
            handle.seek(struct.unpack_from("<I", dos, 60)[0])
            pe = handle.read(60)
            if (pe[:4] != b"PE\0\0" or struct.unpack_from("<H", pe, 4)[0] != 0x14C or
                    struct.unpack_from("<H", pe, 24)[0] != 0x10B or struct.unpack_from("<I", pe, 52)[0] != 0x50000000):
                raise RuntimeError("Linked executable is not x86 PE32 at base 0x50000000")
        destination = ROOT / "build/x86/void-x86-nxcharacter.exe"
        os.replace(pdb, destination.with_suffix(".pdb"))
        os.replace(pending, destination)
        receipt.update(status="LINKED", executable_sha256=sha(destination), link_options=link)
    (OUTPUT / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"{receipt['status']}: {len(compile_jobs)} compiled, {len(reused)} validated objects reused", flush=True)


if __name__ == "__main__":
    main()
