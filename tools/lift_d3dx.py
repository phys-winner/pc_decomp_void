"""Lift Microsoft's D3DX HLSL compiler (d3dx9_36.dll, November 2007 redist) as a
private module after the twelve-module game stage, so the phone compiles the
shaders the renderer asks for itself (android/host/d3dx9.c calls the lifted
D3DXCompileShader on a cache miss and saves the bytecode into the profile).

The DLL is the game's own redistributable (DirectX/Nov2007_d3dx9_36_x86.cab,
expanded to research/ida/d3dx9_36.dll). The catalog is pcrecomp's Capstone
recursive descent, as for PhysX:
    python reference/pcrecomp/tools/disasm/disasm32.py research/ida/d3dx9_36.dll \
        --output research/ida/d3dx9_36.capstone.json

Only the subtree the shader entry points reach is lifted (D3DXCompileShader,
D3DXAssembleShader, D3DXDisassembleShader and the CRT's DllMain): the whole DLL
is ~7,200 functions of textures, meshes, effects and image codecs the port
never calls, and the renderer only ever asks for HLSL. The scope is the call
graph closed from those roots over the same edges the lifter follows -- direct
calls, code pointers loaded by lea/imm, jump tables and the C++ vtables those
functions reference -- computed in IDA (config/D3DXCompiler.reachable.json) and
passed as the catalog with scan_data=False, so the closure stays the subtree
and a kept body never calls a dropped one. The module keeps a PRIVATE Windows
name (d3dxcompiler_void.dll), not d3dx9_36.dll, so the game's own d3dx9_36
imports still bind to the host shims in android/host/d3dx9.c; this image answers
only when the host resolves its exports.
"""
import json
from pathlib import Path
import re
import subprocess

import pefile
from lift_game import ROOT, collect_functions, emit_dispatch, emit_functions
from lift_engine import rebase_image, relocation_sites, sha256

ORIGINAL_BASE = 0x00400000
SPEC = {
    "name": "D3DXCompiler", "win_name": "d3dxcompiler_void.dll", "file": "d3dx9_36.dll",
    "base": 0x1A000000, "span": 0x3A9000,
    "sha256": "c12f0ab0338eb5031d3d04beaf7208ac848f7e037d21ff963d2af90221cbe935",
    # Exports the host calls, and DllMain (the CRT start the roots need).
    "exports": {"D3DXCompileShader": 0x20DAE4, "D3DXAssembleShader": 0x20D271,
                "D3DXDisassembleShader": 0x21357C},
    "dllmain_rva": 0x350D21,
}
# All twelve lifted stages, in the Windows build's order.
PRIOR = ("game", "gamemodule", "engine", "fs", "vfs", "sound", "video", "renderer", "nxcharacter",
         "physxcore", "physxcooking")


def dispatch_entries(directory):
    source = (directory / "recomp_dispatch.c").read_text()
    matches = re.findall(r"^\s*\{0x([0-9A-F]+)u, sub_([0-9A-F]+)\},$", source, re.M)
    entries = [int(a, 16) for a, _ in matches]
    if any(a != b for a, b in matches) or entries != sorted(set(entries)):
        raise ValueError(f"{directory.name}: dispatch order/symbol mismatch")
    return entries


def prepare():
    config = json.loads((ROOT / "port.json").read_text())
    source = ROOT / config["d3dx_compiler"]
    raw = source.read_bytes()
    if sha256(raw) != SPEC["sha256"]:
        raise ValueError("d3dx9_36.dll hash mismatch (expand DirectX/Nov2007_d3dx9_36_x86.cab)")
    pe = pefile.PE(data=raw)
    oh = pe.OPTIONAL_HEADER
    if oh.ImageBase != ORIGINAL_BASE or oh.SizeOfImage != SPEC["span"] or not pe.FILE_HEADER.Characteristics & 0x2000:
        raise ValueError("d3dx9_36.dll: unexpected base/span/characteristics")
    if any(oh.DATA_DIRECTORY[i].VirtualAddress or oh.DATA_DIRECTORY[i].Size for i in (9, 13)):
        raise ValueError("d3dx9_36.dll: PE TLS or delay imports are not supported")
    exports = {e.name.decode(): e.address for e in pe.DIRECTORY_ENTRY_EXPORT.symbols if e.name}
    for name, rva in SPEC["exports"].items():
        if exports.get(name) != rva:
            raise ValueError(f"d3dx9_36.dll: export {name} at {exports.get(name)} != {rva:#x}")
    if oh.AddressOfEntryPoint != SPEC["dllmain_rva"]:
        raise ValueError("d3dx9_36.dll: unexpected entry point")
    rebased, proof = rebase_image(raw, SPEC["base"])
    if rebase_image(rebased, ORIGINAL_BASE)[0] != raw:
        raise ValueError("d3dx9_36.dll: reverse rebase differs")
    parsed, sites, _ = relocation_sites(raw)
    base_offset = parsed.OPTIONAL_HEADER.get_field_absolute_offset("ImageBase")
    allowed = {i for _, off in sites for i in range(off, off + 4)} | set(range(base_offset, base_offset + 4))
    if any(a != b and i not in allowed for i, (a, b) in enumerate(zip(raw, rebased))):
        raise ValueError("d3dx9_36.dll: unexpected rebase byte changes")
    proof.update(entry_rva=oh.AddressOfEntryPoint,
                 imports=[{"dll": row.dll.decode(), "count": len(row.imports)} for row in pe.DIRECTORY_ENTRY_IMPORT])
    return source, raw, rebased, proof


def scoped_catalog():
    """Use the checked-in shader-compiler subtree; no local analysis is needed."""
    reachable = {int(x, 16) for x in json.loads((ROOT / "config/D3DXCompiler.reachable.json").read_text())}
    catalog = ROOT / "config/D3DXCompiler.functions.json"
    rows = json.loads(catalog.read_text())
    if {r["address"] for r in rows} != reachable or len(rows) != len(reachable):
        raise ValueError("D3DXCompiler catalog differs from the reachable set")
    return rows, sha256(catalog.read_bytes())


def main():
    revision = subprocess.check_output(["git", "-C", str(ROOT / "reference/pcrecomp"), "rev-parse", "HEAD"], text=True).strip()
    prior = dispatch_entries(ROOT / "generated/physxcooking-x86")
    source, raw, rebased, proof = prepare()
    name, prefix = SPEC["name"], SPEC["name"].lower()
    generated = ROOT / f"generated/{prefix}-x86"
    generated.mkdir(parents=True, exist_ok=True)
    input_path = ROOT / f"generated/input/{SPEC['file']}"
    input_path.write_bytes(rebased)
    catalog, catalog_sha = scoped_catalog()
    delta = SPEC["base"] - ORIGINAL_BASE
    live_catalog = [{"address": r["address"] + delta, "size": r["size"]} for r in catalog]
    reloc_targets = [int(x, 16) + delta for x in
                     json.loads((ROOT / "config/D3DXCompiler.reloc-targets.json").read_text())]
    roots = [SPEC["base"] + rva for rva in SPEC["exports"].values()] + [SPEC["base"] + SPEC["dllmain_rva"]]
    tables_path = ROOT / f"config/{name}.jump-tables.json"
    if not tables_path.exists():
        tables_path.write_text("[]\n")
    rows = json.loads(tables_path.read_text())
    tables = {int(r["address"], 0) + delta: (r["first_index"], r["count"]) for r in rows}
    # The seed set (config/D3DXCompiler.reachable.json) is the direct-call
    # closure from the roots PLUS every relocation-pointer target that is a real
    # function entry -- the functions the CRT and compiler reach through
    # indirect `call [slot]`, which no static call/jump edge reveals. With those
    # seeded, discover=False suffices: the ungated dispatch pass still follows
    # direct calls, while the lea/imm scan (which would decode d3dx9's
    # .text-embedded string tables as runaway functions) stays off. scan_data
    # keeps the blanket vtable scan (whole-DLL) off.
    info, imports, decoder, functions, rejected = collect_functions(input_path, live_catalog,
        extra_entries=roots, label=name, jump_tables=tables, scan_data=False, discover=False,
        optional_entries=reloc_targets)
    if info.image_base != SPEC["base"] or set(prior) & set(functions):
        raise ValueError("d3dx9_36: decode base or dispatch overlap invalid")
    seeded = {r["address"] + delta for r in catalog} | set(roots) | set(reloc_targets)
    extra = sorted(a for a in functions if a not in seeded)
    if extra:
        print(f"{name}: {len(extra)} functions reached beyond the IDA set "
              f"(first {', '.join(hex(a) for a in extra[:8])})", flush=True)
    merged = sorted([*prior, *functions])
    emitted = emit_functions(generated, imports, decoder, functions, label=name,
        header_name=f"{prefix}_funcs.h", chunk_prefix=prefix, additional_entries=prior)
    headers = [f"../{n}-x86/{'recomp' if n == 'game' else n}_funcs.h" for n in PRIOR] + [f"{prefix}_funcs.h"]
    emit_dispatch(generated / "recomp_dispatch.c", merged, headers)
    (generated / f"{prefix}_entry.h").write_text(
        f"#define D3DXCOMPILER_BASE 0x{SPEC['base']:08X}u\n"
        f"#define D3DXCOMPILER_SIZE 0x{SPEC['span']:08X}u\n"
        + "".join(f"#define D3DXCOMPILER_{n.upper()} 0x{SPEC['base'] + rva:08X}u\n"
                  for n, rva in SPEC["exports"].items()))
    if sha256(source.read_bytes()) != SPEC["sha256"]:
        raise ValueError("d3dx9_36.dll changed during generation")
    traps = {}
    for filename in emitted.get("sources", []):
        text = (generated / filename).read_text()
        for address, instruction in re.findall(r'void_lift_trap\(0x([0-9A-F]+)u, ("(?:[^"\\]|\\.)*")\);', text):
            traps[address] = json.loads(instruction)
    (generated / "static-traps.json").write_text(json.dumps(
        [{"address": "0x" + a, "instruction": t} for a, t in sorted(traps.items())], indent=2) + "\n")
    report = {"status": "GENERATED", "module": SPEC["win_name"], "image_name": SPEC["file"],
              "base": hex(SPEC["base"]), "binary_sha256": SPEC["sha256"], "rebased_sha256": sha256(rebased),
              "entry": hex(SPEC["base"] + SPEC["dllmain_rva"]),
              "exports": {n: hex(SPEC["base"] + rva) for n, rva in SPEC["exports"].items()}, **emitted,
              "catalog_source": "Capstone 5.0.7 recursive descent (pcrecomp disasm32.py); IDA reachability scope",
              "catalog_input": "config/D3DXCompiler.functions.json", "catalog_sha256": catalog_sha,
              "pcrecomp_revision": revision, "pefile_version": pefile.__version__,
              "input_image": f"generated/input/{SPEC['file']}", "declared_jump_tables": len(tables),
              "scope": "shader compiler subtree (D3DXCompileShader/Assemble/Disassemble + DllMain)",
              "scoped_functions": len(functions), "reachable_seeds": len(catalog),
              "rejected_non_catalog_entries": len(rejected), "prior_dispatch_entries": len(prior),
              "merged_dispatch_entries": len(merged), "dispatch_source": "recomp_dispatch.c",
              "unique_static_trap_sites": len(traps), "highlow_fixups": proof["highlow_fixups"],
              "whole_game": "UNVERIFIED",
              "dll_mode": "d3dxcompiler_void.dll private name and base; host calls its exports on a cache miss"}
    (generated / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("module", "base", "scoped_functions", "reachable_seeds",
        "merged_dispatch_entries", "unique_static_trap_sites")}), flush=True)


if __name__ == "__main__":
    main()
