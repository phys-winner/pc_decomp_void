"""Offline FS/VFS lifts from private rebased inputs; requires the Engine dispatch."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import pefile
from lift_game import ROOT, collect_functions, emit_dispatch, emit_functions
from lift_engine import (MODULE_SHA256 as ENGINE_SHA256, previous_dispatch,
                         rebase_image, relocation_sites)

ORIGINAL_BASE = 0x10000000
MODULES = [
    {"name": "FS", "base": 0x12000000, "span": 0x3C000, "entry_rva": 0x1041F,
     "factory_rva": 0x26180, "fixups": 3915, "padding": 23, "catalog_count": 935,
     "sha256": "36b2d79e15ef5fc35a880e69e4a5f34dda04d4867f9f8d846b505938c8c8636f",
     "catalog_source_sha256": "24f5b5aaca8f28720e138e57818fa0c88c8c68fbb53e7b59cec51261babd6564",
     "catalog_sha256": "f91eebe033e020ef7da2d173f8f55d662a19343da9069ebf523070a9ff33cee2"},
    {"name": "VFS", "base": 0x13000000, "span": 0x33000, "entry_rva": 0xBC01,
     "factory_rva": 0x1EC80, "fixups": 3270, "padding": 18, "catalog_count": 815,
     "sha256": "93d03784e761f64f27d7f6ca4198942f0efe68fa5b758922aeefd5f4f3904f8a",
     "catalog_source_sha256": "729252a4362d54c50ba726d309a93484237ae9ebf012f4eb6b616f6c49643f16",
     "catalog_sha256": "34f70809c4864a305100a9fe02577c6a73ca205ee55b55b673d741fe90c37c0a"},
]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def parse_catalog(spec, text):
    rows = json.loads(text)
    if sha256((json.dumps(rows, indent=1) + "\n").encode()) != spec["catalog_sha256"]:
        raise ValueError(f"{spec['name']}: normalized catalog hash mismatch")
    if len(rows) != spec["catalog_count"] or len({r["address"] for r in rows}) != len(rows):
        raise ValueError(f"{spec['name']}: catalog count/unique-address mismatch")
    return rows


def load_catalog(spec):
    path = ROOT / f"config/{spec['name']}.functions.json"
    return parse_catalog(spec, path.read_text()), sha256(path.read_bytes())


def check_ranges():
    ranges = [(0x400000, 0x60000, "Game"), (0x10000000, 0x331000, "GameModule"),
              (0x11000000, 0x167000, "Engine"), (0x70000000, 0x4000000, "host reservation")]
    ranges += [(s["base"], s["span"], s["name"]) for s in MODULES]
    for i, (base, span, name) in enumerate(ranges):
        for other, size, label in ranges[i + 1:]:
            if base < other + size and other < base + span:
                raise ValueError(f"Planned module ranges overlap: {name}/{label}")


def prepare_input(spec, game_directory):
    source = Path(game_directory) / f"bin/win32/{spec['name']}.dll"
    raw = source.read_bytes()
    if sha256(raw) != spec["sha256"]:
        raise ValueError(f"{spec['name']}: original binary hash mismatch")
    pe = pefile.PE(data=raw)
    oh = pe.OPTIONAL_HEADER
    if (oh.ImageBase != ORIGINAL_BASE or oh.SizeOfImage != spec["span"] or
            oh.AddressOfEntryPoint != spec["entry_rva"] or not pe.FILE_HEADER.Characteristics & 0x2000):
        raise ValueError(f"{spec['name']}: unexpected DLL/base/span/entry")
    if any(oh.DATA_DIRECTORY[i].VirtualAddress or oh.DATA_DIRECTORY[i].Size for i in (9, 13)):
        raise ValueError(f"{spec['name']}: unsupported PE TLS or delay imports")
    exports = pe.DIRECTORY_ENTRY_EXPORT.symbols
    expected_exports = spec.get("exports", [("_createFactory@0", 1, spec["factory_rva"])])
    actual_exports = [(row.name.decode() if row.name else None, row.ordinal, row.address) for row in exports]
    if actual_exports != expected_exports or any(row.forwarder for row in exports):
        raise ValueError(f"{spec['name']}: unexpected exports/forwarder")
    rebased, proof = rebase_image(raw, spec["base"])
    if proof["highlow_fixups"] != spec["fixups"] or proof["absolute_padding"] != spec["padding"]:
        raise ValueError(f"{spec['name']}: unexpected relocation profile")
    if rebase_image(rebased, ORIGINAL_BASE)[0] != raw:
        raise ValueError(f"{spec['name']}: reverse rebase differs from original")
    parsed, sites, _ = relocation_sites(raw)
    base_offset = parsed.OPTIONAL_HEADER.get_field_absolute_offset("ImageBase")
    allowed = {i for _, off in sites for i in range(off, off + 4)} | set(range(base_offset, base_offset + 4))
    if len(raw) != len(rebased) or any(a != b and i not in allowed for i, (a, b) in enumerate(zip(raw, rebased))):
        raise ValueError(f"{spec['name']}: unexpected rebase byte changes")
    proof["changed_bytes"] = sum(a != b for a, b in zip(raw, rebased))
    proof["roundtrip"] = "PASS"
    proof["pe_tls"] = "ABSENT"
    proof["delay_imports"] = "ABSENT"
    proof["exports"] = [{"name": name, "ordinal": ordinal, "rva": hex(rva),
                         "address": hex(spec["base"] + rva)} for name, ordinal, rva in expected_exports]
    proof["imports"] = [{"dll": row.dll.decode(), "count": len(row.imports)}
                        for row in pe.DIRECTORY_ENTRY_IMPORT]
    return source, raw, rebased, proof


def engine_dispatch(revision):
    previous, _ = previous_dispatch()
    report_path = ROOT / "generated/engine-x86/report.json"
    report = json.loads(report_path.read_text())
    if (report.get("status") != "GENERATED" or report.get("binary_sha256") != ENGINE_SHA256 or
            report.get("base") != "0x11000000" or report.get("pcrecomp_revision") != revision):
        raise ValueError("Generate the pinned Engine stage before FS/VFS")
    source_path = report_path.parent / "recomp_dispatch.c"
    source = source_path.read_text()
    matches = re.findall(r"^\s*\{0x([0-9A-F]+)u, sub_([0-9A-F]+)\},$", source, re.MULTILINE)
    addresses = [int(a, 16) for a, _ in matches]
    if (any(a != b for a, b in matches) or addresses != sorted(set(addresses)) or
            len(addresses) != report["merged_dispatch_entries"] or not set(previous) <= set(addresses)):
        raise ValueError("Engine dispatch count/order/symbol/previous-stage mismatch")
    return addresses, {"report_sha256": sha256(report_path.read_bytes()),
                       "dispatch_sha256": sha256(source_path.read_bytes()),
                       "entries": len(addresses)}


def generate_module(spec, game_directory, entries, headers, revision, prior):
    name = spec["name"]
    prefix = name.lower()
    generated = ROOT / f"generated/{prefix}-x86"
    generated.mkdir(parents=True, exist_ok=True)
    report_path = generated / "report.json"
    report = {"status": "GENERATING", "module": f"{name}.dll", "base": hex(spec["base"]),
              "whole_game": "UNVERIFIED", "execution_coverage": "UNVERIFIED",
              "runtime_integration": "NOT_ATTEMPTED"}
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    try:
        source, original, rebased, proof = prepare_input(spec, game_directory)
        catalog, catalog_sha = load_catalog(spec)
        input_path = ROOT / f"generated/input/{name}.dll"
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_bytes(rebased)
        delta = spec["base"] - ORIGINAL_BASE
        rows = json.loads((ROOT / f"config/{name}.jump-tables.json").read_text())
        tables = {int(row["address"], 0) + delta: (row["first_index"], row["count"]) for row in rows}
        if len(tables) != len(rows):
            raise ValueError(f"{name}: duplicate declared jump-table address")
        live_catalog = [{"address": row["address"] + delta, "size": row["size"]} for row in catalog]
        info, imports, decoder, functions, rejected = collect_functions(input_path, live_catalog,
            extra_entries=[spec["base"] + spec["factory_rva"]], label=name, jump_tables=tables)
        if info.image_base != spec["base"] or set(entries) & set(functions):
            raise ValueError(f"{name}: decode base or dispatch overlap invalid")
        emitted = emit_functions(generated, imports, decoder, functions, label=name,
            header_name=f"{prefix}_funcs.h", chunk_prefix=prefix, additional_entries=entries)
        merged = sorted([*entries, *functions])
        emit_dispatch(generated / "recomp_dispatch.c", merged, headers + [f"{prefix}_funcs.h"])
        (generated / f"{prefix}_entry.h").write_text(
            f"#define {name}_BASE 0x{spec['base']:08X}u\n"
            f"#define {name}_ENTRY 0x{spec['base'] + spec['entry_rva']:08X}u\n"
            f"#define {name}_FACTORY 0x{spec['base'] + spec['factory_rva']:08X}u\n"
            f"#define {name}_SIZE 0x{spec['span']:08X}u\n")
        if sha256(source.read_bytes()) != spec["sha256"]:
            raise ValueError(f"{name}: original input changed during generation")
        report.update(status="GENERATED", binary_sha256=spec["sha256"], **proof,
            entry=hex(spec["base"] + info.entry_point_rva), **emitted,
            catalog_source=f"IDA 9.1, {spec['catalog_count']} unique original function entries",
            catalog_source_sha256=spec["catalog_source_sha256"], catalog_input=f"config/{name}.functions.json",
            catalog_sha256=catalog_sha, pcrecomp_revision=revision, pefile_version=pefile.__version__,
            input_image=f"generated/input/{name}.dll", declared_jump_tables=len(tables),
            rejected_non_catalog_entries=rejected, prior_stage=prior, prior_dispatch_entries=len(entries),
            merged_dispatch_entries=len(merged), dispatch_source="recomp_dispatch.c",
            dll_mode=f"{name} private base, physically relocated input; offline generation only")
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({k: report[k] for k in ("module", "status", "base", "entry", "functions",
            "emitted_instructions_with_overlap", "merged_dispatch_entries", "highlow_fixups")}), flush=True)
        return merged, {"report_sha256": sha256(report_path.read_bytes()),
                        "dispatch_sha256": sha256((generated / "recomp_dispatch.c").read_bytes()),
                        "entries": len(merged)}
    except Exception as error:
        report.update(status="FAILED", error=str(error))
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        raise


def main():
    check_ranges()
    dependency = json.loads((ROOT / "dependencies.json").read_text())["pcrecomp"]
    revision = subprocess.check_output(["git", "-C", str(ROOT / dependency["directory"]),
        "rev-parse", "HEAD"], text=True).strip()
    if revision != dependency["revision"]:
        raise ValueError("pcrecomp revision mismatch")
    entries, prior = engine_dispatch(revision)
    game_directory = json.loads((ROOT / "port.json").read_text())["game_directory"]
    headers = ["../game-x86/recomp_funcs.h", "../gamemodule-x86/gamemodule_funcs.h", "../engine-x86/engine_funcs.h"]
    for spec in MODULES:
        entries, prior = generate_module(spec, game_directory, entries, headers, revision, prior)
        headers.append(f"../{spec['name'].lower()}-x86/{spec['name'].lower()}_funcs.h")


if __name__ == "__main__":
    main()
