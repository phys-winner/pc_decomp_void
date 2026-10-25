"""Lift NVIDIA PhysX 2.8.1 (PhysXCore.dll, PhysXCooking.dll) after the nine-module stage.

The engine DLLs are the user's installed PhysX system software (read-only
inputs under Program Files). Catalogs come from pcrecomp's Capstone recursive
descent (disasm32.py), as for RendererD3D:
    python reference/pcrecomp/tools/disasm/disasm32.py research/ida/<dll> --output research/ida/<name>.capstone.json
PhysXLoader.dll is not lifted: the host reproduces its forwarding (android/host/physx.c).
"""
import json
from pathlib import Path
import re
import subprocess

import pefile
from lift_game import ROOT, collect_functions, emit_dispatch, emit_functions
from lift_engine import rebase_image, relocation_sites, sha256

ORIGINAL_BASE = 0x10000000
MODULES = [
    {"name": "PhysXCore", "base": 0x18000000, "span": 0x5A7000,
     "sha256": "df8d6bf07d024b8dce846a4bfcc5fdf4c42afc5e67acd43afb66cf28bfffff88"},
    {"name": "PhysXCooking", "base": 0x19000000, "span": 0x5F000,
     "sha256": "c6fd154743ff39427a22aef0c41592ee2b555c046aa32121eeb5fc9e24bc2494"},
]
PRIOR = ("game", "gamemodule", "engine", "fs", "vfs", "sound", "video", "renderer", "nxcharacter")


def dispatch_entries(directory):
    source = (directory / "recomp_dispatch.c").read_text()
    matches = re.findall(r"^\s*\{0x([0-9A-F]+)u, sub_([0-9A-F]+)\},$", source, re.M)
    entries = [int(a, 16) for a, _ in matches]
    if any(a != b for a, b in matches) or entries != sorted(set(entries)):
        raise ValueError(f"{directory.name}: dispatch order/symbol mismatch")
    return entries


def prepare(spec):
    config = json.loads((ROOT / "port.json").read_text())
    source = ROOT / config["physx_directory"] / f"{spec['name']}.dll"
    raw = source.read_bytes()
    if sha256(raw) != spec["sha256"]:
        raise ValueError(f"{spec['name']}: installed PhysX binary hash mismatch")
    pe = pefile.PE(data=raw)
    oh = pe.OPTIONAL_HEADER
    if oh.ImageBase != ORIGINAL_BASE or oh.SizeOfImage != spec["span"] or not pe.FILE_HEADER.Characteristics & 0x2000:
        raise ValueError(f"{spec['name']}: unexpected base/span")
    if any(oh.DATA_DIRECTORY[i].VirtualAddress or oh.DATA_DIRECTORY[i].Size for i in (9, 13)):
        raise ValueError(f"{spec['name']}: PE TLS or delay imports")
    rebased, proof = rebase_image(raw, spec["base"])
    if rebase_image(rebased, ORIGINAL_BASE)[0] != raw:
        raise ValueError(f"{spec['name']}: reverse rebase differs")
    parsed, sites, _ = relocation_sites(raw)
    base_offset = parsed.OPTIONAL_HEADER.get_field_absolute_offset("ImageBase")
    allowed = {i for _, off in sites for i in range(off, off + 4)} | set(range(base_offset, base_offset + 4))
    if any(a != b and i not in allowed for i, (a, b) in enumerate(zip(raw, rebased))):
        raise ValueError(f"{spec['name']}: unexpected rebase byte changes")
    exports = [(e.name.decode() if e.name else None, e.ordinal, e.address) for e in pe.DIRECTORY_ENTRY_EXPORT.symbols]
    proof.update(entry_rva=oh.AddressOfEntryPoint, exports=exports,
                 imports=[{"dll": row.dll.decode(), "count": len(row.imports)} for row in pe.DIRECTORY_ENTRY_IMPORT])
    return raw, rebased, proof


def catalog_for(spec):
    config = ROOT / f"config/{spec['name']}.functions.json"
    rows = json.loads(config.read_text())
    if len({r["address"] for r in rows}) != len(rows):
        raise ValueError(f"{spec['name']}: duplicate catalog addresses")
    return rows


def main():
    revision = subprocess.check_output(["git", "-C", str(ROOT / "reference/pcrecomp"), "rev-parse", "HEAD"], text=True).strip()
    entries = dispatch_entries(ROOT / "generated/nxcharacter-x86")
    headers = [f"../{n}-x86/{'recomp' if n == 'game' else n}_funcs.h" for n in PRIOR]
    for spec in MODULES:
        name, prefix = spec["name"], spec["name"].lower()
        generated = ROOT / f"generated/{prefix}-x86"
        generated.mkdir(parents=True, exist_ok=True)
        raw, rebased, proof = prepare(spec)
        input_path = ROOT / f"generated/input/{name}.dll"
        input_path.write_bytes(rebased)
        delta = spec["base"] - ORIGINAL_BASE
        catalog = [{"address": r["address"] + delta, "size": r["size"]} for r in catalog_for(spec)]
        tables_path = ROOT / f"config/{name}.jump-tables.json"
        if not tables_path.exists():
            tables_path.write_text("[]\n")
        tables = {int(r["address"], 0) + delta: (r["first_index"], r["count"]) for r in json.loads(tables_path.read_text())}
        export_entries = [spec["base"] + rva for _, _, rva in proof["exports"]]
        info, imports, decoder, functions, rejected = collect_functions(input_path, catalog, extra_entries=export_entries,
            label=name, jump_tables=tables)
        if info.image_base != spec["base"] or set(entries) & set(functions):
            raise ValueError(f"{name}: decode base or dispatch overlap")
        emitted = emit_functions(generated, imports, decoder, functions, label=name,
            header_name=f"{prefix}_funcs.h", chunk_prefix=prefix, additional_entries=entries)
        merged = sorted([*entries, *functions])
        headers.append(f"{prefix}_funcs.h")
        emit_dispatch(generated / "recomp_dispatch.c", merged, headers)
        headers[-1] = f"../{prefix}-x86/{prefix}_funcs.h"
        (generated / f"{prefix}_entry.h").write_text(
            f"#define {name.upper()}_BASE 0x{spec['base']:08X}u\n"
            f"#define {name.upper()}_ENTRY 0x{spec['base'] + proof['entry_rva']:08X}u\n"
            f"#define {name.upper()}_SIZE 0x{spec['span']:08X}u\n")
        traps = {}
        for filename in emitted.get("sources", []):
            text = (generated / filename).read_text()
            for address, instruction in re.findall(r'void_lift_trap\(0x([0-9A-F]+)u, ("(?:[^"\\]|\\.)*")\);', text):
                traps[address] = json.loads(instruction)
        (generated / "static-traps.json").write_text(json.dumps(
            [{"address": "0x" + a, "instruction": t} for a, t in sorted(traps.items())], indent=2) + "\n")
        report = {"status": "GENERATED", "module": f"{name}.dll", "base": hex(spec["base"]),
                  "binary_sha256": spec["sha256"], "rebased_sha256": sha256(rebased),
                  "entry": hex(spec["base"] + proof["entry_rva"]), **emitted,
                  "catalog_source": "Capstone 5.0.7 recursive descent (pcrecomp disasm32.py)",
                  "catalog_input": f"config/{name}.functions.json", "pcrecomp_revision": revision,
                  "input_image": f"generated/input/{name}.dll", "rejected_non_catalog_entries": len(rejected),
                  "prior_dispatch_entries": len(entries), "merged_dispatch_entries": len(merged),
                  "dispatch_source": "recomp_dispatch.c", "unique_static_trap_sites": len(traps),
                  "highlow_fixups": proof["highlow_fixups"], "whole_game": "UNVERIFIED"}
        (generated / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({k: report[k] for k in ("module", "base", "entry", "functions", "merged_dispatch_entries",
                                                  "unique_static_trap_sites")}), flush=True)
        entries = merged


if __name__ == "__main__":
    main()
