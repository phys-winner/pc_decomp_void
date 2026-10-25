"""Generate GameModule at its preferred x86 base and merge its Game dispatch."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from lift_game import ROOT, collect_functions, emit_dispatch, emit_functions, generate_game

MODULE_SHA256 = "a0075c2316bdb658724aaec595339a8ad2459832620b0a9dac3c7359a4330562"
CATALOG_SOURCE_SHA256 = "1ef2e9ccf6fb002552ee1b933b04726407c5f7ac923551c73bf4dc9f86dac079"
CATALOG_SHA256 = "f1bebc84321efb246894e1ab2d87588cb2d0154699ee989dee54f58db1ca64be"
MODULE_BASE = 0x10000000
DLL_MODE = "GameModule manually mapped at fixed base, entire image NX; other DLLs native"
STARTUP_MODE = "Lifted GameModule PE entry, CRT constructors and process attach/detach"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_catalog():
    source = ROOT / "config/GameModule.functions.json"
    catalog = json.loads(source.read_text())
    # Git checkouts may change LF/CRLF; pin the same decoded catalog contents.
    canonical = (json.dumps(catalog, indent=1) + "\n").encode()
    if hashlib.sha256(canonical).hexdigest() != CATALOG_SHA256:
        raise ValueError("Normalized GameModule catalog hash mismatch")
    return catalog, sha256(source)


def main():
    config = json.loads((ROOT / "port.json").read_text())
    binary = Path(config["game_directory"]) / "bin/win32/GameModule.dll"
    if sha256(binary) != MODULE_SHA256:
        raise ValueError("Original GameModule.dll hash mismatch")
    catalog, catalog_sha256 = load_catalog()
    dependency = json.loads((ROOT / "dependencies.json").read_text())["pcrecomp"]
    revision = subprocess.check_output(["git", "-C", str(ROOT / dependency["directory"]),
                                        "rev-parse", "HEAD"], text=True).strip()
    if revision != dependency["revision"]:
        raise ValueError("pcrecomp revision mismatch")
    generated = ROOT / "generated/gamemodule-x86"
    generated.mkdir(parents=True, exist_ok=True)
    report = {"status": "GENERATING", "binary_sha256": MODULE_SHA256,
              "catalog_source": "IDA 9.1, 13554 unique function entries",
              "catalog_source_sha256": CATALOG_SOURCE_SHA256,
              "catalog_input": "config/GameModule.functions.json", "catalog_sha256": catalog_sha256,
              "pcrecomp_revision": revision, "base": hex(MODULE_BASE),
              "whole_game": "UNVERIFIED"}
    (generated / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print("GameModule: pinned inputs verified; generating Game and GameModule", file=sys.stderr, flush=True)
    game_functions, game_report = generate_game()
    (ROOT / "generated/input/GameModule.dll").write_bytes(binary.read_bytes())
    tables = json.loads((ROOT / "config/GameModule.jump-tables.json").read_text())
    jump_tables = {int(row["address"], 0): (row.get("first_index", 0), row["count"]) for row in tables}
    if len(jump_tables) != len(tables):
        raise ValueError("Duplicate declared GameModule jump tables")
    info, imports, decoder, functions, rejected = collect_functions(
        binary, catalog, label="GameModule", jump_tables=jump_tables)
    if info.image_base != MODULE_BASE:
        raise ValueError("GameModule fixed-base proof requires image base 0x10000000")
    duplicates = set(game_functions) & set(functions)
    if duplicates:
        raise ValueError(f"Duplicate live VAs between Game and GameModule: {sorted(duplicates)}")
    emitted = emit_functions(generated, imports, decoder, functions, label="GameModule",
                             header_name="gamemodule_funcs.h", chunk_prefix="gamemodule",
                             additional_entries=game_functions)
    emit_dispatch(generated / "recomp_dispatch.c", [*game_functions, *functions],
                  ["../game-x86/recomp_funcs.h", "gamemodule_funcs.h"])
    (generated / "module_entry.h").write_text(
        f"#define GAMEMODULE_BASE 0x{MODULE_BASE:08X}u\n"
        f"#define GAMEMODULE_ENTRY 0x{info.image_base + info.entry_point_rva:08X}u\n")
    report.update({"status": "GENERATED", "entry": hex(info.image_base + info.entry_point_rva),
                   **emitted, "rejected_non_catalog_entries": rejected,
                   "game_functions": game_report["functions"],
                   "merged_dispatch_entries": len(game_functions) + len(functions),
                   "game_sources": [f"../game-x86/{name}" for name in game_report["sources"]],
                   "dispatch_source": "recomp_dispatch.c",
                   "dll_mode": DLL_MODE,
                   "startup_mode": STARTUP_MODE,
                   "execution_coverage": "UNVERIFIED"})
    (generated / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        report_path = ROOT / "generated/gamemodule-x86/report.json"
        if report_path.exists():
            report = json.loads(report_path.read_text())
            if report.get("status") == "GENERATING":
                report.update(status="FAILED", error=str(error))
                report_path.write_text(json.dumps(report, indent=2) + "\n")
        raise
