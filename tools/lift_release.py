"""Lift every module of another release of the game (another build of the
binaries) the way the 2009 build was lifted, into generated/<release>/.

    python tools/lift_release.py tension [--only Sound,Video] [--finish] [--catalogs-only]

config/releases/<release>.json names the game directory and, per module, the
file, its SHA-256 and the private base (the same bases as the 2009 build, so
the Android host's loader and memory map apply unchanged). Function catalogs
come from pcrecomp's Capstone recursive descent (disasm32.py) over the
original, unrebased image, as for RendererD3D and PhysX in the 2009 build
(research/ida/<release>/<Name>.capstone.json; written when missing; the live
catalog goes to config/releases/<release>/<Name>.functions.json).

What the 2009 lifters pinned by address is found by content here:
- the CRT memcpy/memmove bodies (opening sequence push ebp / mov ebp,esp /
  push edi / push esi / mov esi,[ebp+0Ch] / mov ecx,[ebp+10h] /
  mov edi,[ebp+8]) and libvorbis mdct_backward in Sound.dll: native
  overrides (android/host/crt_native.c, sound_native.c);
- Sound.dll's Vorbis read callback, which ignores fread's nmemb: replaced
  by void_sound_bulk_read (android/host/hooks.c), as tools/lift_media.py does.
They go to generated/<release>/release.json and release_overrides.h, which
tools/build_android.py --release <release> compiles into the host.
The 2009 Game.exe isFirstRun gate (0x00436A10) is not patched: the host's
registry answers FirstRun=0 for any Ice-pick Lodge title.
"""
import argparse
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

import pefile
from lift_game import ROOT, collect_functions, emit_dispatch, emit_functions
from lift_engine import rebase_image, relocation_sites, sha256

CRT_COPY = bytes.fromhex("558bec57568b750c8b4d108b7d08")
# libvorbis mdct_backward (LTCG: ecx = lookup, eax = in, [esp+4] = out); 2009 Sound.dll 0x10018AB0.
MDCT_BACKWARD = bytes.fromhex("83ec0853558b6c2414568bd9578bf88b038bf0c1f802d1fe8d14308d5495008d2c85000000008b43088d4cb7e4895424")
VORBIS_READ = bytes.fromhex("8b4424108b088b4424088b118b5224508b44240850ffd2c3")


def load_release(name):
    spec = json.loads((ROOT / f"config/releases/{name}.json").read_text())
    local = json.loads((ROOT / "port.json").read_text()).get("releases", {}).get(name, {})
    game = (ROOT / local.get("game_directory", spec["game_directory"])).resolve()
    physx = (ROOT / local.get("physx_directory", spec["physx_directory"])).resolve()
    for module in spec["modules"]:
        module["path"] = Path(module["file"].format(game=game, physx=physx))
        module["base"] = int(module["base"], 0)
    return spec


def capstone_catalog(release, module):
    """Use the pinned Capstone catalog shipped with the port."""
    config = ROOT / f"config/releases/{release}/{module['name']}.functions.json"
    rows = json.loads(config.read_text())
    if len({r["address"] for r in rows}) != len(rows):
        raise ValueError(f"{module['name']}: duplicate catalog addresses")
    return rows, {}


def prepare(module, generated):
    raw = module["path"].read_bytes()
    if sha256(raw) != module["sha256"]:
        raise ValueError(f"{module['name']}: {module['path']} hash mismatch")
    pe = pefile.PE(data=raw, fast_load=True)
    oh = pe.OPTIONAL_HEADER
    if pe.FILE_HEADER.Machine != 0x14C or oh.Magic != 0x10B:
        raise ValueError(f"{module['name']}: not a PE32 i386 image")
    pe.parse_data_directories(directories=[0, 1, 9, 13])
    if any(oh.DATA_DIRECTORY[i].VirtualAddress or oh.DATA_DIRECTORY[i].Size for i in (9, 13)):
        raise ValueError(f"{module['name']}: PE TLS or delay imports")
    proof = {"original_base": hex(oh.ImageBase), "base": hex(module["base"]), "span": hex(oh.SizeOfImage),
             "entry_rva": oh.AddressOfEntryPoint, "original_sha256": module["sha256"]}
    if module["base"] == oh.ImageBase:
        image = raw
    else:
        image, rebase = rebase_image(raw, module["base"])
        if rebase_image(image, oh.ImageBase)[0] != raw:
            raise ValueError(f"{module['name']}: reverse rebase differs")
        parsed, sites, _ = relocation_sites(raw)
        base_offset = parsed.OPTIONAL_HEADER.get_field_absolute_offset("ImageBase")
        allowed = {i for _, off in sites for i in range(off, off + 4)} | set(range(base_offset, base_offset + 4))
        if any(a != b and i not in allowed for i, (a, b) in enumerate(zip(raw, image))):
            raise ValueError(f"{module['name']}: unexpected rebase byte changes")
        proof.update(highlow_fixups=rebase["highlow_fixups"])
    exports = []
    if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
        exports = [(e.name.decode() if e.name else None, e.ordinal, e.address)
                   for e in pe.DIRECTORY_ENTRY_EXPORT.symbols if not e.forwarder]
    proof["exports"] = [{"name": n, "ordinal": o, "address": hex(module["base"] + rva)} for n, o, rva in exports]
    input_path = generated / "input" / module["path"].name
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_bytes(image)
    proof["rebased_sha256"] = sha256(image)
    # Data exports (NxCharacter's NxControllerManager vtable) are not entries.
    code = [(s.VirtualAddress, s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData))
            for s in pe.sections if s.Characteristics & 0x20000000]
    entries = [module["base"] + rva for _, _, rva in exports if any(a <= rva < b for a, b in code)]
    return input_path, image, proof, entries


def find_code(image, pattern, base):
    """Live VAs where `pattern` starts inside an executable section."""
    pe = pefile.PE(data=image, fast_load=True)
    hits = []
    for section in pe.sections:
        if not section.Characteristics & 0x20000000:
            continue
        data = section.get_data()
        for match in re.finditer(re.escape(pattern), data):
            hits.append(base + section.VirtualAddress + match.start())
    return hits


def patch_vorbis_read(directory, report, address):
    pattern = re.compile(rf"^void sub_{address:08X}\(void\) \{{\n.*?^\}}", re.M | re.S)
    matched = [(name, (directory / name).read_text()) for name in report["sources"]
               if pattern.search((directory / name).read_text())]
    if len(matched) != 1:
        raise ValueError("Missing or duplicate Sound read callback definition")
    name, source = matched[0]
    (directory / name).write_text(pattern.sub(
        f"void sub_{address:08X}(void) {{\n    extern void void_sound_bulk_read(void);\n    void_sound_bulk_read();\n}}",
        source))
    report["bulk_read_callback"] = {"address": hex(address), "source": name, "implementation": "void_sound_bulk_read"}


def static_traps(directory, sources):
    traps = {}
    for name in sources:
        text = (directory / name).read_text()
        for address, instruction in re.findall(r'void_lift_trap\(0x([0-9A-F]+)u, ("(?:[^"\\]|\\.)*")\);', text):
            traps[address] = json.loads(instruction)
    return [{"address": "0x" + a, "instruction": t} for a, t in sorted(traps.items())]


def lift_module(release, module, generated, revision):
    """Lift one module on its own: other modules are reached through the
    dispatch table (PE modules only call each other through imports)."""
    name, prefix = module["name"], module["prefix"]
    directory = generated / f"{prefix}-x86"
    directory.mkdir(parents=True, exist_ok=True)
    report = {"status": "GENERATING", "module": module["path"].name, "release": release}
    (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    input_path, image, proof, export_entries = prepare(module, generated)
    rows, stats = capstone_catalog(release, module)
    delta = module["base"] - int(proof["original_base"], 0)
    catalog = [{"address": r["address"] + delta, "size": r["size"]} for r in rows]
    tables_path = ROOT / f"config/releases/{release}/{name}.jump-tables.json"
    tables = {}
    if tables_path.exists():
        tables = {int(r["address"], 0) + delta: (r.get("first_index", 0), r["count"])
                  for r in json.loads(tables_path.read_text())}
    seeds_path = ROOT / f"config/releases/{release}/{name}.seeds.json"
    seeds = [int(a, 0) for a in json.loads(seeds_path.read_text())] if seeds_path.exists() else []
    info, imports, decoder, functions, rejected = collect_functions(
        input_path, catalog, [*export_entries, *seeds], label=name, jump_tables=tables)
    if info.image_base != module["base"]:
        raise ValueError(f"{name}: decode base")
    emitted = emit_functions(directory, imports, decoder, functions, label=name,
                             header_name=f"{prefix}_funcs.h", chunk_prefix=prefix, firstrun_gate=None)
    entry = module["base"] + proof["entry_rva"]
    overrides = {"crt_memmove": [hex(a) for a in find_code(image, CRT_COPY, module["base"]) if a in functions]}
    if name == "Sound":
        mdct = [a for a in find_code(image, MDCT_BACKWARD, module["base"]) if a in functions]
        reads = [a for a in find_code(image, VORBIS_READ, module["base"]) if a in functions]
        if len(mdct) != 1:
            raise ValueError(f"Sound: mdct_backward found {len(mdct)} times (android/host/sound_native.c needs it)")
        if len(reads) != 1:
            raise ValueError(f"Sound: Vorbis read callback found {len(reads)} times")
        overrides.update(mdct_backward=hex(mdct[0]), vorbis_read=hex(reads[0]))
        patch_vorbis_read(directory, emitted, reads[0])
    traps = static_traps(directory, emitted["sources"])
    (directory / "static-traps.json").write_text(json.dumps(traps, indent=2) + "\n")
    (directory / "functions.json").write_text(json.dumps(sorted(functions)) + "\n")
    report.update(status="GENERATED", **proof, entry=hex(entry), **emitted, overrides=overrides,
                  catalog_source="Capstone 5.0.7 recursive descent (pcrecomp disasm32.py)",
                  catalog_stats=stats, catalog_input=f"config/releases/{release}/{name}.functions.json",
                  pcrecomp_revision=revision, input_image=str(input_path.relative_to(ROOT)),
                  rejected_non_catalog_entries=len(rejected), function_list="functions.json",
                  unique_static_trap_sites=len(traps), whole_game="UNVERIFIED")
    (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("module", "base", "entry", "functions", "unique_static_trap_sites")}),
          flush=True)


def finish(release, spec, generated):
    """Merge the modules' functions into one dispatch table (in the last
    module's directory, where tools/build_android.py looks) and write the
    host's release_overrides.h and release.json."""
    entries, headers, crt = [], [], []
    overrides = {}
    game_entry = None
    for module in spec["modules"]:
        directory = generated / f"{module['prefix']}-x86"
        report = json.loads((directory / "report.json").read_text())
        if report.get("status") != "GENERATED":
            raise SystemExit(f"{module['name']}: not lifted yet")
        functions = json.loads((directory / "functions.json").read_text())
        if set(entries) & set(functions):
            raise ValueError(f"{module['name']}: dispatch overlap")
        entries += functions
        headers.append(f"../{module['prefix']}-x86/{module['prefix']}_funcs.h")
        crt += [(module["name"], int(a, 16)) for a in report["overrides"]["crt_memmove"]]
        overrides.update({k: v for k, v in report["overrides"].items() if k != "crt_memmove"})
        if module["name"] == "Game":
            game_entry = int(report["entry"], 16)
    last = generated / f"{spec['modules'][-1]['prefix']}-x86"
    emit_dispatch(last / "recomp_dispatch.c", sorted(entries), headers)
    mdct = int(overrides["mdct_backward"], 16)
    lines = ["/* Generated by tools/lift_release.py: what the host overrides in this release. */",
             "#pragma once",
             "#define RELEASE_CRT_MEMMOVES(X) " + " ".join(f"X(sub_{a:08X})" for _, a in crt),
             f"#define SOUND_MDCT_BACKWARD sub_{mdct:08X}",
             f"#define SOUND_MDCT_BACKWARD_LIFTED sub_{mdct:08X}_lifted",
             f"#define SOUND_BULK_READ_VA 0x{int(overrides['vorbis_read'], 16):08X}u",
             f"#define RELEASE_GAME_ENTRY 0x{game_entry:08X}u"]
    (generated / "release_overrides.h").write_text("\n".join(lines) + "\n")
    native = [f"sub_{a:08X}" for _, a in crt] + [f"sub_{mdct:08X}"]
    (generated / "release.json").write_text(json.dumps({
        "release": release, "title": spec["title"], "modules": [m["prefix"] for m in spec["modules"]],
        "images": {m["prefix"]: f"generated/{release}/input/{m['path'].name}" for m in spec["modules"]},
        "native_overrides": native,
        "overrides": {**overrides, "crt_memmove": [{"module": n, "address": hex(a)} for n, a in crt]},
        "game_entry": hex(game_entry), "dispatch_entries": len(entries)}, indent=2) + "\n")
    print(f"{release}: {len(entries)} dispatch entries; native overrides {len(native)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("release")
    parser.add_argument("--catalogs-only", action="store_true")
    parser.add_argument("--only", help="Lift these modules (comma-separated names) without merging")
    parser.add_argument("--finish", action="store_true", help="Only merge the lifted modules")
    args = parser.parse_args()
    spec = load_release(args.release)
    generated = ROOT / "generated" / args.release
    generated.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "-C", str(ROOT / "reference/pcrecomp"), "rev-parse", "HEAD"],
                                       text=True).strip()
    if args.catalogs_only:
        for module in spec["modules"]:
            rows, stats = capstone_catalog(args.release, module)
            print(f"{module['name']}: {len(rows)} catalog entries {stats}", flush=True)
        return
    if not args.finish:
        wanted = set(args.only.split(",")) if args.only else {m["name"] for m in spec["modules"]}
        unknown = wanted - {m["name"] for m in spec["modules"]}
        if unknown:
            raise SystemExit(f"unknown modules {sorted(unknown)}")
        for module in spec["modules"]:
            if module["name"] in wanted:
                lift_module(args.release, module, generated, revision)
        if args.only:
            return
    finish(args.release, spec, generated)


if __name__ == "__main__":
    main()
