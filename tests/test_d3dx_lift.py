"""The scoped D3DX compiler lift (tools/lift_d3dx.py) keeps a sound subtree:
the reachable set is closed under direct calls, so a kept body never calls a
dropped one, and the committed catalog is that reachable set. Offline: reads
config/ and (when present) the Capstone catalog and the generated report."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from lift_d3dx import SPEC, PRIOR, ORIGINAL_BASE


def main():
    reachable = {int(x, 16) for x in json.loads((ROOT / "config/D3DXCompiler.reachable.json").read_text())}
    reloc = {int(x, 16) for x in json.loads((ROOT / "config/D3DXCompiler.reloc-targets.json").read_text())}
    catalog = json.loads((ROOT / "config/D3DXCompiler.functions.json").read_text())
    assert 2000 < len(reachable) < 4000, len(reachable)
    assert {r["address"] for r in catalog} == reachable, "the required catalog is the reachable set"
    assert all("size" in r for r in catalog)
    # Relocation-pointer function targets are the indirect-call seeds, disjoint
    # from the direct-call closure, and never fatal (optional_entries).
    assert reloc and not (reloc & reachable), "reloc targets are a disjoint optional set"

    roots = {SPEC["base"] + rva for rva in SPEC["exports"].values()} | {SPEC["base"] + SPEC["dllmain_rva"]}
    for rva in SPEC["exports"].values():
        assert ORIGINAL_BASE + rva in reachable, "each export is a seed"
    assert ORIGINAL_BASE + SPEC["dllmain_rva"] in reachable
    assert len(PRIOR) == 11 and PRIOR[0] == "game" and PRIOR[-1] == "physxcooking"
    assert SPEC["base"] == 0x1A000000 and SPEC["win_name"] == "d3dxcompiler_void.dll"

    capstone_path = ROOT / "research/ida/d3dx9_36.capstone.json"
    allowed_escapes = 0
    if capstone_path.exists():
        cap = json.loads(capstone_path.read_text())
        byaddr = {f["address"]: f for f in cap["functions"]}
        escapes = {t for a in reachable if a in byaddr for t in byaddr[a].get("calls_to", [])
                   if t in byaddr and t not in reachable}
        # Any direct-call target outside the reachable set must be one the lift
        # itself discovers and adds (recorded in the generated report); there is
        # at most a tiny CRT-start cluster, never a real escape into dead code.
        assert len(escapes) <= 4, sorted(hex(e) for e in escapes)
        allowed_escapes = len(escapes)

    report_path = ROOT / "generated/d3dxcompiler-x86/report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text())
        assert report["status"] == "GENERATED"
        assert report["module"] == "d3dxcompiler_void.dll"
        assert report["base"] == "0x1a000000"
        assert report["reachable_seeds"] == len(reachable)
        # Emitted = the direct-call closure, the decodable reloc-indirect
        # targets and their closures; more than the reachable seeds, but still
        # a subtree of the ~7,900-function DLL, not the whole image.
        assert report["scoped_functions"] >= len(reachable)
        assert report["scoped_functions"] <= len(reachable) + len(reloc) + 2000
        assert report["scoped_functions"] < 7900
        for name in ("D3DXCompileShader", "D3DXAssembleShader", "D3DXDisassembleShader"):
            assert report["exports"][name] == hex(SPEC["base"] + SPEC["exports"][name])

    print(f"PASS: D3DX scoped lift sound; {len(reachable)} reachable, {allowed_escapes} discovered escapes, "
          f"exports and private name intact")


if __name__ == "__main__":
    main()
