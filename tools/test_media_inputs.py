"""Validate pinned media rebasing and every declared local CRT table arm offline."""
import json
import struct

import pefile
from lift_media import (MODULES, ORIGINAL_BASE, ROOT, check_ranges, load_catalog,
    parse_catalog, prepare_input, rebase_image, relocation_sites)
from lift_game import BoundedDisassembler, analyze_pe


def reject(operation):
    try:
        operation()
    except ValueError:
        return
    raise AssertionError("Invalid media input was accepted")


def main():
    check_ranges()
    game_directory = json.loads((ROOT / "port.json").read_text())["game_directory"]
    results = []
    for spec in MODULES:
        source, raw, rebased, proof = prepare_input(spec, game_directory)
        oracle = pefile.PE(data=raw, fast_load=True)
        oracle.parse_data_directories(directories=[5])
        oracle.relocate_image(spec["base"])
        assert oracle.write() == rebased
        assert rebase_image(rebased, ORIGINAL_BASE)[0] == raw
        reject(lambda: rebase_image(raw, spec["base"] + 1))
        reloc_pe, sites, _ = relocation_sites(raw)
        first = next(e for block in reloc_pe.DIRECTORY_ENTRY_BASERELOC for e in block.entries if e.type == 3)
        bad_pointer = bytearray(raw)
        struct.pack_into("<I", bad_pointer, sites[0][1], 0)
        bad_type = bytearray(raw)
        offset = first.struct.get_file_offset()
        original = struct.unpack_from("<H", raw, offset)[0]
        struct.pack_into("<H", bad_type, offset, (original & 0xFFF) | 0x1000)
        reject(lambda: rebase_image(bytes(bad_pointer), spec["base"]))
        reject(lambda: rebase_image(bytes(bad_type), spec["base"]))
        catalog, _ = load_catalog(spec)
        assert parse_catalog(spec, json.dumps(catalog, indent=1).replace("\n", "\r\n")) == catalog
        changed = [dict(row) for row in catalog]
        changed[0]["address"] += 1
        reject(lambda: parse_catalog(spec, json.dumps(changed)))
        rows = json.loads((ROOT / f"config/{spec['name']}.jump-tables.json").read_text())
        delta = spec["base"] - ORIGINAL_BASE
        tables = {int(row["address"], 0) + delta: (row["first_index"], row["count"]) for row in rows}
        assert len(tables) == len(rows) == (15 if spec["name"] == "Sound" else 14)
        decoder = BoundedDisassembler(rebased, spec["base"], analyze_pe(str(source)).sections,
                                       jump_tables=tables)
        starts = {int(row["source_function"], 0) + delta for row in rows}
        assert len(starts) == (3 if spec["name"] == "Sound" else 2)
        functions = {start: decoder.disassemble_function(start, {}) for start in starts}
        slots = 0
        for row in rows:
            start = int(row["source_function"], 0) + delta
            instructions = {i.address for b in functions[start].blocks.values() for i in b.instructions}
            for index in range(row["first_index"], row["first_index"] + row["count"]):
                address = int(row["address"], 0) + delta + 4 * index
                target = struct.unpack("<I", decoder.read_bytes(address, 4))[0]
                assert start <= target < start + row.get("source_size", 0x365) and target in instructions
                slots += 1
        assert slots == (132 if spec["name"] == "Sound" else 68)
        assert source.read_bytes() == raw
        results.append({"module": spec["name"], "status": "PASS", "HIGHLOW": spec["fixups"],
            "catalog_entries": len(catalog), "CRT_copy_functions": 2, "bounded_dispatchers": len(starts),
            "bounded_table_slots": slots, "rebased_sha256": proof["rebased_sha256"]})
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
