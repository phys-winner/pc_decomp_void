"""Offline Sound/Video lifts from pinned rebased inputs and the five-module dispatch."""
import json
from pathlib import Path
import re
import subprocess
import pefile

from lift_game import ROOT
from lift_filesystems import (MODULES as FILE_MODULES, engine_dispatch,
    generate_module, load_catalog, parse_catalog, prepare_input, sha256)
from lift_engine import rebase_image, relocation_sites

ORIGINAL_BASE = 0x10000000
MODULES = [
    {"name": "Sound", "base": 0x14000000, "span": 0xDF000, "entry_rva": 0x440FF,
     "factory_rva": 0x61AB0, "crt_counter_rva": 0xCC47C,
     "fixups": 23411, "padding": 51, "catalog_count": 1358,
     "sha256": "855c2b0cd392b7d4faf82bc62bd9d3db211c5a7b34cd273db60617fc657de6f9",
     "catalog_source_sha256": "8d20c04047a8a2cfbda8347ca01ee7052430497f90b267eb28958bed8349c67d",
     "catalog_sha256": "27b2346006a85668c08f05f3c3eecb74e3b2d5d504ccf8450aeded132a28d9e9"},
    {"name": "Video", "base": 0x15000000, "span": 0x50000, "entry_rva": 0x6CBF,
     "factory_rva": 0x2F250, "crt_counter_rva": 0x47F68,
     "fixups": 6151, "padding": 31, "catalog_count": 1327,
     "sha256": "9500d18964bbbfe02c022c8d4594807f0082c0fd750af9c29ca226752ea63957",
     "catalog_source_sha256": "fdfb723b8502c94c5bc704b7dd570fda77d7910a2d9967b8f49ef33d3e8624b2",
     "catalog_sha256": "e38794873ba69b6264215308a28799d54d0f30bbc9735ef064fa53d3a20cad98"},
]
PRIOR_NAMES = ("game", "gamemodule", "engine", "fs", "vfs")


def check_ranges():
    ranges = [(0x400000, 0x60000, "Game"), (0x10000000, 0x331000, "GameModule"),
              (0x11000000, 0x167000, "Engine"), (0x12000000, 0x3C000, "FS"),
              (0x13000000, 0x33000, "VFS"), (0x70000000, 0x4000000, "host"),
              (0x16000000, 0x1000000, "Renderer reservation"),
              (0x17000000, 0x1000000, "NxCharacter reservation")]
    ranges += [(s["base"], s["span"], s["name"]) for s in MODULES]
    for i, (base, span, name) in enumerate(ranges):
        for other, size, label in ranges[i + 1:]:
            if base < other + size and other < base + span:
                raise ValueError(f"Media private range overlaps: {name}/{label}")


def filesystem_dispatch(revision):
    entries, _ = engine_dispatch(revision)
    for spec in FILE_MODULES:
        directory = ROOT / f"generated/{spec['name'].lower()}-x86"
        report_path, dispatch_path = directory / "report.json", directory / "recomp_dispatch.c"
        report = json.loads(report_path.read_text())
        if (report.get("status") != "GENERATED" or report.get("binary_sha256") != spec["sha256"] or
                report.get("base") != hex(spec["base"]) or report.get("pcrecomp_revision") != revision or
                report.get("prior_dispatch_entries") != len(entries)):
            raise ValueError("Generate the pinned five-module filesystem stage before media")
        matches = re.findall(r"^\s*\{0x([0-9A-F]+)u, sub_([0-9A-F]+)\},$",
                             dispatch_path.read_text(), re.MULTILINE)
        merged = [int(a, 16) for a, _ in matches]
        if (any(a != b for a, b in matches) or merged != sorted(set(merged)) or
                len(merged) != report["merged_dispatch_entries"] or not set(entries) <= set(merged) or
                len(merged) - len(entries) != report["functions"]):
            raise ValueError(f"{spec['name']}: dispatch count/order/symbol/previous-stage mismatch")
        entries = merged
    return entries, {"report_sha256": sha256(report_path.read_bytes()),
                     "dispatch_sha256": sha256(dispatch_path.read_bytes()), "entries": len(entries)}


def prior_hashes():
    return {str(path.relative_to(ROOT)): sha256(path.read_bytes()) for name in PRIOR_NAMES
            for path in sorted((ROOT / f"generated/{name}-x86").iterdir())
            if path.suffix in (".c", ".h") or path.name == "report.json"}


def finish_media_outputs(spec, entries):
    directory = ROOT / f"generated/{spec['name'].lower()}-x86"
    prefix, constant = spec["name"].lower(), spec["name"].upper()
    # The existing filesystem generator uses the module's case for constants.
    (directory / f"{prefix}_entry.h").write_text(
        f"#define {constant}_BASE 0x{spec['base']:08X}u\n"
        f"#define {constant}_ENTRY 0x{spec['base'] + spec['entry_rva']:08X}u\n"
        f"#define {constant}_FACTORY 0x{spec['base'] + spec['factory_rva']:08X}u\n"
        f"#define {constant}_SIZE 0x{spec['span']:08X}u\n"
        f"#define {constant}_CRT_COUNT 0x{spec['base'] + spec['crt_counter_rva']:08X}u\n")
    report_path = directory / "report.json"
    report = json.loads(report_path.read_text())
    if spec['name'] == 'Sound':
        apply_sound_bulk_read(directory, report)
    traps, direct = {}, set()
    for filename in report["sources"]:
        text = (directory / filename).read_text()
        direct.update(int(address, 16) for address in re.findall(r"RECOMP_CALL\(sub_([0-9A-F]+)\)", text))
        for address, instruction in re.findall(r'void_lift_trap\(0x([0-9A-F]+)u, ("(?:[^"\\]|\\.)*")\);', text):
            traps[address] = json.loads(instruction)
    if direct - set(entries):
        raise ValueError(f"{spec['name']}: undefined emitted direct symbols")
    (directory / "static-traps.json").write_text(json.dumps(
        [{"address": "0x" + address, "instruction": instruction}
         for address, instruction in sorted(traps.items())], indent=2) + "\n")
    report.update(unique_static_trap_sites=len(traps), undefined_direct_symbols=0,
                  crt_counter=hex(spec['base'] + spec['crt_counter_rva']),
                  prior_stages=list(PRIOR_NAMES), static_trap_source="static-traps.json")
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return {"report_sha256": sha256(report_path.read_bytes()),
            "dispatch_sha256": sha256((directory / "recomp_dispatch.c").read_bytes()), "entries": len(entries)}


def apply_sound_bulk_read(directory, report):
    """Replace only the pinned Vorbis read callback, preserving every caller."""
    binary = ROOT / 'generated/input/Sound.dll'
    image = pefile.PE(data=binary.read_bytes(), fast_load=True)
    expected = bytes.fromhex('8b4424108b088b4424088b118b5224508b44240850ffd2c3')
    if image.OPTIONAL_HEADER.ImageBase != 0x14000000 or image.get_data(0x61270, len(expected)) != expected:
        raise ValueError('Sound Vorbis read callback does not match the pinned input')
    pattern = re.compile(r'^void sub_14061270\(void\) \{\n.*?^\}', re.M | re.S)
    matched = []
    for filename in report['sources']:
        path = directory / filename
        source = path.read_text()
        matched.extend((filename, source) for _ in pattern.finditer(source))
    if len(matched) != 1: raise ValueError('Missing or duplicate Sound read callback definition')
    filename, source = matched[0]
    (directory / filename).write_text(pattern.sub(
        'void sub_14061270(void) {\n    extern void void_sound_bulk_read(void);\n    void_sound_bulk_read();\n}', source))
    report['bulk_read_callback'] = {'address': '0x14061270', 'source': filename,
        'original_bytes': expected.hex(), 'implementation': 'void_sound_bulk_read',
        'contract': 'fread: size * nmemb bytes; returns complete items; zero/overflow guarded'}


def main():
    check_ranges()
    dependency = json.loads((ROOT / "dependencies.json").read_text())["pcrecomp"]
    revision = subprocess.check_output(["git", "-C", str(ROOT / dependency["directory"]),
        "rev-parse", "HEAD"], text=True).strip()
    if revision != dependency["revision"]:
        raise ValueError("pcrecomp revision mismatch")
    entries, prior = filesystem_dispatch(revision)
    before = prior_hashes()
    game_directory = json.loads((ROOT / "port.json").read_text())["game_directory"]
    headers = [f"../{name}-x86/{'recomp' if name == 'game' else name}_funcs.h" for name in PRIOR_NAMES]
    for spec in MODULES:
        try:
            entries, _ = generate_module(spec, game_directory, entries, headers, revision, prior)
            prior = finish_media_outputs(spec, entries)
        except Exception as error:
            report_path = ROOT / f"generated/{spec['name'].lower()}-x86/report.json"
            if report_path.exists():
                report = json.loads(report_path.read_text())
                report.update(status="FAILED", error=str(error))
                report_path.write_text(json.dumps(report, indent=2) + "\n")
            raise
        headers.append(f"../{spec['name'].lower()}-x86/{spec['name'].lower()}_funcs.h")
    if prior_hashes() != before:
        raise ValueError("Prior generated stages changed during offline media generation")
    print(f"PASS: media generation; {len(entries)} merged entries; {len(before)} prior files unchanged")


if __name__ == "__main__":
    main()
