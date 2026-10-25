"""Lift the pinned character-controller DLL after the eight-module renderer stage."""
import json
import re
import subprocess

from lift_game import ROOT
from lift_filesystems import generate_module, sha256
from lift_renderer import SPEC as RENDERER, media_dispatch, prior_hashes

SPEC = {
    "name": "NxCharacter", "base": 0x17000000, "span": 0x1F000,
    "entry_rva": 0x9413, "factory_rva": 0x8380, "crt_counter_rva": 0x19690,
    "fixups": 1706, "padding": 12, "catalog_count": 382,
    "sha256": "25eaa8dd115354c5cb83f4b5a09b0f234df163861bc88d0f9a710521c574c7bf",
    "catalog_source_sha256": "2321c4e591d54042467d5628220f078bdac35f8e8c553677ef74bba9382bf3bf",
    "catalog_sha256": "f0453f34bec4e8937f06e2de26dc121b6c9ea0d382615a4ac76d9bde62b60dd6",
    "exports": [
        ("??0NxControllerManager@@IAE@XZ", 1, 0x3CE0),
        ("??0NxControllerManager@@QAE@ABV0@@Z", 2, 0x3D00),
        ("??1NxControllerManager@@MAE@XZ", 3, 0x3CF0),
        ("??4NxControllerManager@@QAEAAV0@ABV0@@Z", 4, 0x3D10),
        ("??_7NxControllerManager@@6B@", 5, 0x14400),
        ("NxCreateControllerManager", 6, 0x8380),
        ("NxReleaseControllerManager", 7, 0x8100),
    ],
}
PRIOR_NAMES = ("game", "gamemodule", "engine", "fs", "vfs", "sound", "video", "renderer")


def renderer_dispatch(revision):
    previous, _ = media_dispatch(revision)
    directory = ROOT / "generated/renderer-x86"
    report_path, dispatch_path = directory / "report.json", directory / "recomp_dispatch.c"
    report = json.loads(report_path.read_text())
    if (report.get("status") != "GENERATED" or report.get("binary_sha256") != RENDERER["sha256"] or
            report.get("base") != hex(RENDERER["base"]) or report.get("pcrecomp_revision") != revision or
            report.get("prior_dispatch_entries") != len(previous)):
        raise ValueError("Complete the pinned eight-module renderer generation before NxCharacter")
    matches = re.findall(r"^\s*\{0x([0-9A-F]+)u, sub_([0-9A-F]+)\},$", dispatch_path.read_text(), re.M)
    entries = [int(a, 16) for a, _ in matches]
    if (any(a != b for a, b in matches) or entries != sorted(set(entries)) or
            len(entries) != report["merged_dispatch_entries"] or not set(previous) <= set(entries) or
            len(entries) - len(previous) != report["functions"]):
        raise ValueError("Renderer dispatch count/order/symbol mismatch")
    return entries, {"report_sha256": sha256(report_path.read_bytes()),
                     "dispatch_sha256": sha256(dispatch_path.read_bytes()), "entries": len(entries)}


def main():
    dependency = json.loads((ROOT / "dependencies.json").read_text())["pcrecomp"]
    revision = subprocess.check_output(["git", "-C", str(ROOT / dependency["directory"]),
        "rev-parse", "HEAD"], text=True).strip()
    if revision != dependency["revision"]:
        raise ValueError("pcrecomp revision mismatch")
    if RENDERER["base"] + RENDERER["span"] > SPEC["base"] or SPEC["base"] + SPEC["span"] >= 0x70000000:
        raise ValueError("NxCharacter private range overlaps another module")
    entries, prior = renderer_dispatch(revision)
    before = prior_hashes()
    renderer_files = {str(p.relative_to(ROOT)): sha256(p.read_bytes())
        for p in (ROOT / "generated/renderer-x86").iterdir() if p.suffix in (".c", ".h") or p.name == "report.json"}
    headers = [f"../{name}-x86/{'recomp' if name == 'game' else name}_funcs.h" for name in PRIOR_NAMES]
    game_directory = json.loads((ROOT / "port.json").read_text())["game_directory"]
    merged, _ = generate_module(SPEC, game_directory, entries, headers, revision, prior)
    directory = ROOT / "generated/nxcharacter-x86"
    (directory / "nxcharacter_entry.h").write_text(
        "#define NXCHARACTER_BASE 0x17000000u\n"
        "#define NXCHARACTER_ENTRY 0x17009413u\n"
        "#define NXCHARACTER_FACTORY 0x17008380u\n"
        "#define NXCHARACTER_RELEASE 0x17008100u\n"
        "#define NXCHARACTER_SIZE 0x0001F000u\n"
        "#define NXCHARACTER_CRT_COUNT 0x17019690u\n")
    report_path = directory / "report.json"
    report = json.loads(report_path.read_text())
    traps, direct = {}, set()
    for filename in report["sources"]:
        source = (directory / filename).read_text()
        direct.update(int(a, 16) for a in re.findall(r"RECOMP_CALL\(sub_([0-9A-F]+)\)", source))
        for address, instruction in re.findall(r'void_lift_trap\(0x([0-9A-F]+)u, ("(?:[^"\\]|\\.)*")\);', source):
            traps[address] = json.loads(instruction)
    if direct - set(merged):
        raise ValueError("NxCharacter has undefined direct symbols")
    if prior_hashes() != before or any(sha256((ROOT / p).read_bytes()) != h for p, h in renderer_files.items()):
        raise ValueError("Prior generated modules changed during NxCharacter generation")
    (directory / "static-traps.json").write_text(json.dumps([
        {"address": "0x" + a, "instruction": text} for a, text in sorted(traps.items())], indent=2) + "\n")
    report.update(prior_stages=list(PRIOR_NAMES), crt_counter=hex(SPEC["base"] + SPEC["crt_counter_rva"]),
        unique_static_trap_sites=len(traps), undefined_direct_symbols=0, static_trap_source="static-traps.json")
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"PASS: NxCharacter generation; {len(merged)} combined dispatch entries; original/prior inputs unchanged")


if __name__ == "__main__":
    main()
