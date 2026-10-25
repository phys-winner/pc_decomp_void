"""Check Engine fixups against an independent pefile oracle without loading it."""
import json
from pathlib import Path
import struct

from capstone import Cs, CS_ARCH_X86, CS_MODE_32
import pefile
from lift_engine import ROOT, MODULE_SHA256, ORIGINAL_BASE, ENGINE_BASE, rebase_image, relocation_sites, sha256


def imports(pe):
    return [(d.dll.decode(), [(e.name.decode() if e.name else None, e.ordinal,
             e.address - pe.OPTIONAL_HEADER.ImageBase) for e in d.imports])
            for d in pe.DIRECTORY_ENTRY_IMPORT]


def exports(pe):
    return [(e.name.decode() if e.name else None, e.ordinal, e.address, e.forwarder)
            for e in pe.DIRECTORY_ENTRY_EXPORT.symbols]


def rejects(raw, reason):
    try:
        rebase_image(raw, ENGINE_BASE)
    except ValueError:
        return reason
    raise AssertionError(f"Invalid input was accepted: {reason}")


def main():
    config = json.loads((ROOT / "port.json").read_text())
    source = Path(config["game_directory"]) / "bin/win32/Engine.dll"
    raw = source.read_bytes()
    assert sha256(raw) == MODULE_SHA256
    relocated, proof = rebase_image(raw, ENGINE_BASE)
    pe, sites, padding = relocation_sites(raw)
    assert len(sites) == 24454 and padding == 162
    allowed = set()
    delta = ENGINE_BASE - ORIGINAL_BASE
    for rva, offset in sites:
        old = struct.unpack_from("<I", raw, offset)[0]
        new = struct.unpack_from("<I", relocated, offset)[0]
        assert new == old + delta, (hex(rva), old, new)
        allowed.update(range(offset, offset + 4))
    base_offset = proof["imagebase_file_offset"]
    allowed.update(range(base_offset, base_offset + 4))
    changed = {i for i, (a, b) in enumerate(zip(raw, relocated)) if a != b}
    assert len(raw) == len(relocated) and changed <= allowed
    assert rebase_image(relocated, ORIGINAL_BASE)[0] == raw
    assert rebase_image(raw, ORIGINAL_BASE)[0] == raw

    # Parse only directory 5 before pefile.write: full parsing mutates the ILT.
    oracle = pefile.PE(data=raw, fast_load=True)
    oracle.parse_data_directories(directories=[5])
    oracle.relocate_image(ENGINE_BASE)
    assert oracle.write() == relocated
    before, after = pefile.PE(data=raw), pefile.PE(data=relocated)
    assert imports(before) == imports(after)
    assert exports(before) == exports(after)
    assert after.OPTIONAL_HEADER.AddressOfEntryPoint == 0x726C8
    assert after.OPTIONAL_HEADER.SizeOfImage == 0x167000
    assert all(after.OPTIONAL_HEADER.DATA_DIRECTORY[n].VirtualAddress == 0 and
               after.OPTIONAL_HEADER.DATA_DIRECTORY[n].Size == 0 for n in (9, 13))

    decoder = Cs(CS_ARCH_X86, CS_MODE_32)
    absolute = next(decoder.disasm(after.get_data(0xEF209, 6), ENGINE_BASE + 0xEF209))
    assert absolute.op_str == "dword ptr [0x11118008]", absolute.op_str
    iid = next(decoder.disasm(after.get_data(0xEF1F9, 5), ENGINE_BASE + 0xEF1F9))
    assert iid.op_str == "0x111189ec", iid.op_str
    relative = next(decoder.disasm(after.get_data(0xEF210, 5), ENGINE_BASE + 0xEF210))
    assert relative.op_str == "0x11068df6", relative.op_str
    assert before.get_data(0xEF210, 5) == after.get_data(0xEF210, 5)

    unsupported = bytearray(raw)
    first_entry = next(e for b in pe.DIRECTORY_ENTRY_BASERELOC for e in b.entries if e.type == 3)
    entry_offset = first_entry.struct.get_file_offset()
    struct.pack_into("<H", unsupported, entry_offset, (1 << 12) | (first_entry.rva & 0xFFF))
    checks = [rejects(bytes(unsupported), "unsupported relocation type")]
    outside = bytearray(raw)
    struct.pack_into("<I", outside, sites[0][1], 0xDEADBEEF)
    checks.append(rejects(bytes(outside), "non-internal relocation pointer"))
    assert source.read_bytes() == raw
    generated = ROOT / "generated/engine-x86"
    artifact = ROOT / "generated/input/Engine.dll"
    assert artifact.read_bytes() == relocated, "Generated Engine input is stale"
    report = {"status": "PASS", **proof, "changed_byte_count": len(changed),
        "changed_only_declared_fixups_and_imagebase": True, "exact_reverse_roundtrip": True,
        "pefile_relocation_only_oracle": "PASS", "imports_and_exports_unchanged_rvas": True,
        "decoded_absolute_iat": absolute.op_str, "decoded_iid": iid.op_str,
        "decoded_relative_call": relative.op_str, "relative_call_bytes_unchanged": True,
        "invalid_inputs_rejected": checks, "original_unchanged": True,
        "game_execution": "NOT PERFORMED"}
    (generated / "rebase-selfcheck.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"PASS: {len(sites)} HIGHLOW fixups; {len(changed)} changed bytes confined to fixups/ImageBase; "
          "exact reverse roundtrip, independent oracle, imports/exports, absolute+relative decode")


if __name__ == "__main__":
    main()
