"""Offline RendererD3D lift at 0x16000000; consumes the completed seven-module stage."""
import json
from pathlib import Path
import re
import subprocess

import pefile
from lift_game import ROOT, collect_functions, emit_dispatch, emit_functions
from lift_engine import rebase_image, relocation_sites, sha256
from lift_filesystems import parse_catalog
from lift_media import MODULES as MEDIA_MODULES, filesystem_dispatch

ORIGINAL_BASE, RENDERER_BASE = 0x10000000, 0x16000000
SPEC = {
    "name": "RendererD3D", "base": RENDERER_BASE, "span": 0x39C000,
    "entry_rva": 0x125D65, "factory_rva": 0x16F640, "crt_counter_rva": 0x357CA8,
    "fixups": 87280, "padding": 398, "catalog_count": 28251,
    "sha256": "a58ee315725502cd295600841accbd2a0df750443aefdd0dd4d9cc709604dbf3",
    "catalog_source_sha256": "5fc82f543eea0df01327af1dae6bfd36c4811591b343ccba7cd958a398ab1dd8",
    "catalog_sha256": "10670bc3923657eb8540fe1cbf0c68cc3c2a1e35757e0e48f8535a5dd5284fbb",
}
EXPORTS = [("_createFactory@0", 1, 0x16F640), ("shcode", 2, 0x16F680),
           ("sphereMap", 3, 0x16FC60), ("test", 4, 0x16F630)]
PRIOR_NAMES = ("game", "gamemodule", "engine", "fs", "vfs", "sound", "video")


def check_ranges():
    ranges = [(0x400000, 0x60000, "Game"), (0x10000000, 0x331000, "GameModule"),
              (0x11000000, 0x167000, "Engine"), (0x12000000, 0x3C000, "FS"),
              (0x13000000, 0x33000, "VFS"), (0x14000000, 0xDF000, "Sound"),
              (0x15000000, 0x50000, "Video"), (0x50000000, 0x10000000, "host"),
              (0x17000000, 0x1000000, "NxCharacter reservation")]
    for base, span, name in ranges:
        if RENDERER_BASE < base + span and base < RENDERER_BASE + SPEC["span"]:
            raise ValueError(f"Renderer range overlaps {name}")


def load_catalog():
    path = ROOT / "config/RendererD3D.functions.json"
    rows = parse_catalog(SPEC, path.read_text())
    counts = {kind: sum(row["entry_kind"] == kind for row in rows) for kind in ("start", "alias")}
    if counts != {"start": 12009, "alias": 16242}:
        raise ValueError("Renderer Capstone entry-kind provenance mismatch")
    return rows, sha256(path.read_bytes())


def prepare_input(game_directory):
    source = Path(game_directory) / "bin/win32/RendererD3D.dll"
    raw = source.read_bytes()
    if sha256(raw) != SPEC["sha256"]:
        raise ValueError("Renderer original hash mismatch")
    pe = pefile.PE(data=raw)
    oh = pe.OPTIONAL_HEADER
    exports = [(e.name.decode() if e.name else None, e.ordinal, e.address)
               for e in pe.DIRECTORY_ENTRY_EXPORT.symbols]
    if (pe.FILE_HEADER.Machine != 0x14C or oh.Magic != 0x10B or
            not pe.FILE_HEADER.Characteristics & 0x2000 or oh.ImageBase != ORIGINAL_BASE or
            oh.SizeOfImage != SPEC["span"] or oh.AddressOfEntryPoint != SPEC["entry_rva"] or
            exports != EXPORTS or any(e.forwarder for e in pe.DIRECTORY_ENTRY_EXPORT.symbols)):
        raise ValueError("Unexpected Renderer PE or exports")
    if any(oh.DATA_DIRECTORY[i].VirtualAddress or oh.DATA_DIRECTORY[i].Size for i in (9, 13)):
        raise ValueError("Unsupported Renderer PE TLS/delay imports")
    rebased, proof = rebase_image(raw, RENDERER_BASE)
    if proof["highlow_fixups"] != SPEC["fixups"] or proof["absolute_padding"] != SPEC["padding"]:
        raise ValueError("Renderer relocation profile mismatch")
    if rebase_image(rebased, ORIGINAL_BASE)[0] != raw:
        raise ValueError("Renderer reverse relocation mismatch")
    parsed, sites, _ = relocation_sites(raw)
    imagebase_offset = parsed.OPTIONAL_HEADER.get_field_absolute_offset("ImageBase")
    allowed = {i for _, offset in sites for i in range(offset, offset + 4)} | set(range(imagebase_offset, imagebase_offset + 4))
    if len(raw) != len(rebased) or any(a != b and i not in allowed for i, (a, b) in enumerate(zip(raw, rebased))):
        raise ValueError("Unexpected Renderer rebase byte changes")
    proof.update(changed_bytes=sum(a != b for a, b in zip(raw, rebased)), roundtrip="PASS",
                 pe_tls="ABSENT", delay_imports="ABSENT",
                 exports=[{"name": name, "ordinal": ordinal, "rva": hex(rva), "address": hex(RENDERER_BASE + rva)}
                          for name, ordinal, rva in EXPORTS],
                 imports=[{"dll": row.dll.decode(), "count": len(row.imports)} for row in pe.DIRECTORY_ENTRY_IMPORT])
    return source, raw, rebased, proof


def media_dispatch(revision):
    entries, _ = filesystem_dispatch(revision)
    for spec in MEDIA_MODULES:
        directory = ROOT / f"generated/{spec['name'].lower()}-x86"
        report_path, dispatch_path = directory / "report.json", directory / "recomp_dispatch.c"
        report = json.loads(report_path.read_text())
        if (report.get("status") != "GENERATED" or report.get("binary_sha256") != spec["sha256"] or
                report.get("base") != hex(spec["base"]) or report.get("pcrecomp_revision") != revision or
                report.get("prior_dispatch_entries") != len(entries)):
            raise ValueError("Complete pinned seven-module media generation before Renderer")
        matches = re.findall(r"^\s*\{0x([0-9A-F]+)u, sub_([0-9A-F]+)\},$", dispatch_path.read_text(), re.MULTILINE)
        merged = [int(a, 16) for a, _ in matches]
        if (any(a != b for a, b in matches) or merged != sorted(set(merged)) or
                len(merged) != report["merged_dispatch_entries"] or not set(entries) <= set(merged) or
                len(merged) - len(entries) != report["functions"]):
            raise ValueError("Media dispatch count/order/symbol mismatch")
        entries = merged
    return entries, {"report_sha256": sha256(report_path.read_bytes()),
                     "dispatch_sha256": sha256(dispatch_path.read_bytes()), "entries": len(entries)}


def prior_hashes():
    return {str(p.relative_to(ROOT)): sha256(p.read_bytes()) for name in PRIOR_NAMES
            for p in sorted((ROOT / f"generated/{name}-x86").iterdir())
            if p.suffix in (".c", ".h") or p.name == "report.json"}


def main():
    check_ranges()
    dependency = json.loads((ROOT / "dependencies.json").read_text())["pcrecomp"]
    revision = subprocess.check_output(["git", "-C", str(ROOT / dependency["directory"]), "rev-parse", "HEAD"], text=True).strip()
    if revision != dependency["revision"]:
        raise ValueError("pcrecomp revision mismatch")
    entries, prior = media_dispatch(revision)
    before = prior_hashes()
    generated = ROOT / "generated/renderer-x86"
    generated.mkdir(parents=True, exist_ok=True)
    report_path = generated / "report.json"
    report = {"status": "GENERATING", "module": "RendererD3D.dll", "base": hex(RENDERER_BASE),
              "whole_game": "UNVERIFIED", "execution_coverage": "UNVERIFIED", "runtime_integration": "NOT_ATTEMPTED"}
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    try:
        game_directory = json.loads((ROOT / "port.json").read_text())["game_directory"]
        source, original, rebased, proof = prepare_input(game_directory)
        input_path = ROOT / "generated/input/RendererD3D.dll"
        input_path.write_bytes(rebased)
        catalog, catalog_sha = load_catalog()
        delta = RENDERER_BASE - ORIGINAL_BASE
        live_catalog = [{"address": row["address"] + delta, "size": row["size"]} for row in catalog]
        rows = json.loads((ROOT / "config/RendererD3D.jump-tables.json").read_text())
        tables = {int(row["address"], 0) + delta: (row["first_index"], row["count"]) for row in rows}
        if len(tables) != len(rows):
            raise ValueError("Duplicate Renderer jump-table declarations")
        info, imports, decoder, functions, rejected = collect_functions(input_path, live_catalog,
            extra_entries=[RENDERER_BASE + rva for _, _, rva in EXPORTS], label="RendererD3D", jump_tables=tables)
        if info.image_base != RENDERER_BASE or set(entries) & set(functions):
            raise ValueError("Renderer decode base/dispatch overlap mismatch")
        emitted = emit_functions(generated, imports, decoder, functions, label="RendererD3D",
            header_name="renderer_funcs.h", chunk_prefix="renderer", additional_entries=entries)
        merged = sorted([*entries, *functions])
        headers = [f"../{name}-x86/{'recomp' if name == 'game' else name}_funcs.h" for name in PRIOR_NAMES]
        emit_dispatch(generated / "recomp_dispatch.c", merged, headers + ["renderer_funcs.h"])
        (generated / "renderer_entry.h").write_text(
            f"#define RENDERER_BASE 0x{RENDERER_BASE:08X}u\n"
            f"#define RENDERER_ENTRY 0x{RENDERER_BASE + SPEC['entry_rva']:08X}u\n"
            f"#define RENDERER_FACTORY 0x{RENDERER_BASE + SPEC['factory_rva']:08X}u\n"
            f"#define RENDERER_SIZE 0x{SPEC['span']:08X}u\n"
            f"#define RENDERER_CRT_COUNT 0x{RENDERER_BASE + SPEC['crt_counter_rva']:08X}u\n")
        traps, direct = {}, set()
        for filename in emitted["sources"]:
            text = (generated / filename).read_text()
            direct.update(int(a, 16) for a in re.findall(r"RECOMP_CALL\(sub_([0-9A-F]+)\)", text))
            for address, instruction in re.findall(r'void_lift_trap\(0x([0-9A-F]+)u, ("(?:[^"\\]|\\.)*")\);', text):
                traps[address] = json.loads(instruction)
        if direct - set(merged) or sha256(source.read_bytes()) != SPEC["sha256"] or prior_hashes() != before:
            raise ValueError("Renderer direct symbols, original input or prior-stage immutability check failed")
        (generated / "static-traps.json").write_text(json.dumps([
            {"address": "0x" + a, "instruction": text} for a, text in sorted(traps.items())], indent=2) + "\n")
        report.update(status="GENERATED", binary_sha256=SPEC["sha256"], **proof, **emitted,
            entry=hex(RENDERER_BASE + SPEC["entry_rva"]), crt_counter=hex(RENDERER_BASE + SPEC["crt_counter_rva"]),
            catalog_source="Capstone 5.0.7 recursive descent; 12009 start + 16242 alias seeds; not IDA",
            catalog_source_sha256=SPEC["catalog_source_sha256"], catalog_input="config/RendererD3D.functions.json",
            catalog_sha256=catalog_sha, pcrecomp_revision=revision, pefile_version=pefile.__version__,
            input_image="generated/input/RendererD3D.dll", declared_jump_tables=len(tables),
            rejected_non_catalog_entries=rejected, prior_stage=prior, prior_dispatch_entries=len(entries),
            merged_dispatch_entries=len(merged), dispatch_source="recomp_dispatch.c",
            unique_static_trap_sites=len(traps), undefined_direct_symbols=0,
            unchanged_prior_files=len(before), static_trap_source="static-traps.json")
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({k: report[k] for k in ("status", "functions", "emitted_instructions_with_overlap",
            "merged_dispatch_entries", "unique_static_trap_sites", "unchanged_prior_files")}))
    except Exception as error:
        report.update(status="FAILED", error=str(error))
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        raise


if __name__ == "__main__":
    main()
