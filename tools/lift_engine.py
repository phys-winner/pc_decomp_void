"""Relocate the pinned Engine PE offline, then lift its actual rebased bytes."""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

import pefile
from lift_game import ROOT, collect_functions, emit_dispatch, emit_functions

MODULE_SHA256 = "bb7c9f554e1eb96ef11a99c2bddeb26e73de26680da7ce1a86acd3eb353c5061"
CATALOG_SOURCE_SHA256 = "07bfbdf91a67e584d479a4ba17c1db1f7a2c617476525d599c732d0c296864b0"
CATALOG_SHA256 = "26f501c3fa1cfe566ac6d6e250fe41b65b0f03d67e18a0287cd1d8e26ef9450b"
ORIGINAL_BASE, ENGINE_BASE = 0x10000000, 0x11000000


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def relocation_sites(raw):
    """Parse only relocations: full pefile write also rewrites import thunks."""
    pe = pefile.PE(data=raw, fast_load=True)
    if pe.FILE_HEADER.Machine != 0x14C or pe.OPTIONAL_HEADER.Magic != 0x10B:
        raise ValueError("Engine relocation requires a PE32 i386 image")
    pe.parse_data_directories(directories=[5])
    if not hasattr(pe, "DIRECTORY_ENTRY_BASERELOC"):
        raise ValueError("Missing Engine relocation directory")
    sites, padding = [], 0
    for block in pe.DIRECTORY_ENTRY_BASERELOC:
        for entry in block.entries:
            if entry.type == 0:
                padding += 1
                continue
            if entry.type != 3:
                raise ValueError(f"Unsupported PE32 relocation type {entry.type}")
            section = pe.get_section_by_rva(entry.rva)
            if section is None or entry.rva + 4 > section.VirtualAddress + section.SizeOfRawData:
                raise ValueError("Relocation target is not backed by four section bytes")
            offset = pe.get_offset_from_rva(entry.rva)
            if offset + 4 > len(raw):
                raise ValueError("Truncated relocation target")
            sites.append((entry.rva, offset))
    offsets = sorted(offset for _, offset in sites)
    if any(a + 4 > b for a, b in zip(offsets, offsets[1:])):
        raise ValueError("Duplicate or overlapping relocation targets")
    return pe, sites, padding


def rebase_image(raw, new_base):
    pe, sites, padding = relocation_sites(raw)
    old_base = pe.OPTIONAL_HEADER.ImageBase
    span = pe.OPTIONAL_HEADER.SizeOfImage
    if type(new_base) is not int or new_base < 0 or new_base & 0xFFFF or new_base + span > 0x100000000:
        raise ValueError("Private base must be aligned to 64 KiB and fit PE32")
    output = bytearray(raw)
    delta = new_base - old_base
    for rva, offset in sites:
        value = struct.unpack_from("<I", raw, offset)[0]
        if not old_base <= value < old_base + span:
            raise ValueError(f"Engine relocation {rva:#x} is not an internal pointer: {value:#x}")
        struct.pack_into("<I", output, offset, value + delta)
    base_offset = pe.OPTIONAL_HEADER.get_field_absolute_offset("ImageBase")
    struct.pack_into("<I", output, base_offset, new_base)
    return bytes(output), {"original_base": hex(old_base), "base": hex(new_base),
        "span": hex(span), "delta": delta, "highlow_fixups": len(sites),
        "absolute_padding": padding, "imagebase_file_offset": base_offset,
        "original_sha256": sha256(raw), "rebased_sha256": sha256(output)}


def previous_dispatch():
    report_path = ROOT / "generated/gamemodule-x86/report.json"
    report = json.loads(report_path.read_text())
    if report.get("status") != "GENERATED":
        raise ValueError("Generate Game and GameModule before Engine")
    source = (report_path.parent / "recomp_dispatch.c").read_text()
    matches = re.findall(r"^\s*\{0x([0-9A-F]+)u, sub_([0-9A-F]+)\},$", source, re.MULTILINE)
    if any(a != b for a, b in matches):
        raise ValueError("Previous dispatch contains inconsistent symbol addresses")
    addresses = [int(a, 16) for a, _ in matches]
    if len(addresses) != report["merged_dispatch_entries"] or len(set(addresses)) != len(addresses):
        raise ValueError("Previous dispatch count mismatch")
    return addresses, report


def main():
    generated = ROOT / "generated/engine-x86"
    generated.mkdir(parents=True, exist_ok=True)
    report = {"status": "GENERATING", "base": hex(ENGINE_BASE), "execution_coverage": "UNVERIFIED"}
    (generated / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    config = json.loads((ROOT / "port.json").read_text())
    original = Path(config["game_directory"]) / "bin/win32/Engine.dll"
    raw = original.read_bytes()
    if sha256(raw) != MODULE_SHA256:
        raise ValueError("Original Engine.dll hash mismatch")
    rebased, proof = rebase_image(raw, ENGINE_BASE)
    if proof["original_base"] != hex(ORIGINAL_BASE) or proof["highlow_fixups"] != 24454:
        raise ValueError("Unexpected pinned Engine relocation profile")
    if rebase_image(rebased, ORIGINAL_BASE)[0] != raw:
        raise ValueError("Engine reverse rebase does not reproduce the original")
    for base, span, label in [(0x400000, 0x60000, "Game"), (0x10000000, 0x331000, "GameModule"),
                              (0x70000000, 0x4000000, "host reservation")]:
        if ENGINE_BASE < base + span and base < ENGINE_BASE + int(proof["span"], 0):
            raise ValueError(f"Engine private range overlaps {label}")
    input_path = ROOT / "generated/input/Engine.dll"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_bytes(rebased)
    catalog_path = ROOT / "config/Engine.functions.json"
    catalog = json.loads(catalog_path.read_text())
    if sha256((json.dumps(catalog, indent=1) + "\n").encode()) != CATALOG_SHA256:
        raise ValueError("Normalized Engine catalog hash mismatch")
    delta = ENGINE_BASE - ORIGINAL_BASE
    live_catalog = [{"address": row["address"] + delta, "size": row["size"]} for row in catalog]
    dependency = json.loads((ROOT / "dependencies.json").read_text())["pcrecomp"]
    revision = subprocess.check_output(["git", "-C", str(ROOT / dependency["directory"]),
                                       "rev-parse", "HEAD"], text=True).strip()
    if revision != dependency["revision"]:
        raise ValueError("pcrecomp revision mismatch")
    old_entries, old_report = previous_dispatch()
    table_rows = json.loads((ROOT / "config/Engine.jump-tables.json").read_text())
    jump_tables = {int(row["address"], 0) + delta: (row["first_index"], row["count"])
                   for row in table_rows}
    if len(jump_tables) != len(table_rows):
        raise ValueError("Duplicate declared Engine jump tables")
    info, imports, decoder, functions, rejected = collect_functions(
        input_path, live_catalog, label="Engine", jump_tables=jump_tables)
    if info.image_base != ENGINE_BASE or set(old_entries) & set(functions):
        raise ValueError("Engine decode base or dispatch overlap is invalid")
    emitted = emit_functions(generated, imports, decoder, functions, label="Engine",
        header_name="engine_funcs.h", chunk_prefix="engine", additional_entries=old_entries)
    emit_dispatch(generated / "recomp_dispatch.c", [*old_entries, *functions],
        ["../game-x86/recomp_funcs.h", "../gamemodule-x86/gamemodule_funcs.h", "engine_funcs.h"])
    entry = ENGINE_BASE + info.entry_point_rva
    exports = [{"name": e.name, "ordinal": e.ordinal, "rva": hex(e.rva),
                "address": hex(ENGINE_BASE + e.rva)} for e in info.exports]
    factory = next(e for e in exports if e["name"] == "_createFactory@0")
    (generated / "engine_entry.h").write_text(
        f"#define ENGINE_BASE 0x{ENGINE_BASE:08X}u\n#define ENGINE_ENTRY 0x{entry:08X}u\n"
        f"#define ENGINE_FACTORY 0x{int(factory['address'], 0):08X}u\n"
        f"#define ENGINE_SIZE 0x{int(proof['span'], 0):08X}u\n")
    report.update(status="GENERATED", binary_sha256=MODULE_SHA256, **proof,
        catalog_source="IDA 9.1, 4959 unique original function entries",
        catalog_source_sha256=CATALOG_SOURCE_SHA256, catalog_input="config/Engine.functions.json",
        catalog_sha256=sha256(catalog_path.read_bytes()), pcrecomp_revision=revision,
        input_image="generated/input/Engine.dll", entry=hex(entry), exports=exports,
        **emitted, rejected_non_catalog_entries=rejected, declared_jump_tables=len(jump_tables),
        game_functions=old_report["game_functions"], gamemodule_functions=old_report["functions"],
        merged_dispatch_entries=len(old_entries) + len(functions), dispatch_source="recomp_dispatch.c",
        dll_mode="Engine private base, decoded from physically relocated bytes; integration unverified")
    (generated / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ["status", "base", "entry", "functions",
        "emitted_instructions_with_overlap", "merged_dispatch_entries", "highlow_fixups"]}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        path = ROOT / "generated/engine-x86/report.json"
        if path.exists():
            report = json.loads(path.read_text())
            if report.get("status") == "GENERATING":
                report.update(status="FAILED", error=str(error))
                path.write_text(json.dumps(report, indent=2) + "\n")
        raise
