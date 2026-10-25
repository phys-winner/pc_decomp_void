"""Headless prebase/catalog/CRT table checks; never executes native game code."""
import json
import struct

import pefile
from lift_filesystems import (MODULES, ORIGINAL_BASE, ROOT, check_ranges,
    load_catalog, parse_catalog, prepare_input, rebase_image, relocation_sites)
from lift_game import BoundedDisassembler, analyze_pe


def main():
    check_ranges()
    game_directory = json.loads((ROOT / "port.json").read_text())["game_directory"]
    results = []
    for spec in MODULES:
        source, raw, rebased, proof = prepare_input(spec, game_directory)
        # Independent library relocation must match our manually patched copy.
        oracle = pefile.PE(data=raw, fast_load=True)
        oracle.parse_data_directories(directories=[5])
        oracle.relocate_image(spec["base"])
        assert oracle.write() == rebased
        try:
            rebase_image(raw, spec["base"] + 1)
        except ValueError:
            pass
        else:
            raise AssertionError("Unaligned private base accepted")
        reloc_pe, sites, _ = relocation_sites(raw)
        first = next(e for block in reloc_pe.DIRECTORY_ENTRY_BASERELOC for e in block.entries if e.type == 3)
        invalid_pointer = bytearray(raw)
        struct.pack_into("<I", invalid_pointer, sites[0][1], 0)
        invalid_type = bytearray(raw)
        entry_offset = first.struct.get_file_offset()
        value = struct.unpack_from("<H", raw, entry_offset)[0]
        struct.pack_into("<H", invalid_type, entry_offset, (value & 0xFFF) | 0x1000)
        for invalid in (invalid_pointer, invalid_type):
            try:
                rebase_image(bytes(invalid), spec["base"])
            except ValueError:
                pass
            else:
                raise AssertionError("Noninternal pointer/unsupported relocation accepted")
        catalog, _ = load_catalog(spec)
        text = json.dumps(catalog, indent=1) + "\n"
        assert parse_catalog(spec, text.replace("\n", "\r\n")) == catalog
        changed = [dict(row) for row in catalog]
        changed[0]["address"] += 1
        try:
            parse_catalog(spec, json.dumps(changed))
        except ValueError:
            pass
        else:
            raise AssertionError("Tampered normalized catalog accepted")
        rows = json.loads((ROOT / f"config/{spec['name']}.jump-tables.json").read_text())
        delta = spec["base"] - ORIGINAL_BASE
        tables = {int(row["address"], 0) + delta: (row["first_index"], row["count"]) for row in rows}
        assert len(tables) == len(rows) == 14
        sections = analyze_pe(str(source)).sections
        decoder = BoundedDisassembler(rebased, spec["base"], sections, jump_tables=tables)
        starts = {int(row["source_function"], 0) + delta for row in rows}
        assert len(starts) == 2
        functions = {start: decoder.disassemble_function(start, {}) for start in starts}
        slots = 0
        for row in rows:
            function = functions[int(row["source_function"], 0) + delta]
            assert function and function.blocks
            instruction_addresses = {i.address for block in function.blocks.values() for i in block.instructions}
            table = int(row["address"], 0) + delta
            for index in range(row["first_index"], row["first_index"] + row["count"]):
                target = struct.unpack("<I", decoder.read_bytes(table + index * 4, 4))[0]
                assert target in instruction_addresses, f"{spec['name']} local arm missing: {target:#x}"
                slots += 1
        assert slots == 68
        assert source.read_bytes() == raw
        results.append({"module": spec["name"], "status": "PASS", "relocations": spec["fixups"],
            "catalog_entries": len(catalog), "CRT_copy_functions": len(starts), "bounded_table_slots": slots,
            "rebased_sha256": proof["rebased_sha256"]})
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
