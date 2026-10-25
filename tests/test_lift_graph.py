"""Sparse table arms stay local; external tails close the generated graph."""
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import lift_game


def section(rva, offset, size):
    return SimpleNamespace(name=".text", virtual_address=rva, raw_offset=offset,
                           raw_size=size, virtual_size=size, is_code=True)


def main():
    base, table = 0x10000000, 0x10000100
    raw = bytearray(b"\xcc" * 0x400)
    raw[:7] = b"\xff\x24\x95" + struct.pack("<I", table)
    raw[0x20] = raw[0x30] = 0xC3
    values = [base + 0x20] * 80
    values[44:46] = [0, 0]
    values[66] = base + 0x30
    raw[0x100:0x240] = struct.pack("<80I", *values)
    # A valid pointer after the declared bound belongs to another table.
    raw[0x240:0x244] = struct.pack("<I", base + 0x40)
    decoder = lift_game.BoundedDisassembler(bytes(raw), base, [section(0, 0, len(raw))],
                                            jump_tables={table: 80})
    function = decoder.disassemble_function(base, {})
    assert base + 0x30 in function.blocks and base + 0x40 not in function.blocks
    assert function.jump_targets == {base + 0x20, base + 0x30}
    body = lift_game.lift_function_linear(lift_game.CheckedLifter(iat_map={}, lifted={base}),
        f"sub_{base:08X}", sorted({i.address: i for b in function.blocks.values()
                                  for i in b.instructions}.values(), key=lambda i: i.address),
        set(function.blocks), base, indirect_targets=function.jump_targets)
    assert f"case 0x{base + 0x30:08X}u: goto L_{base + 0x30:08X};" in body
    assert base + 0x30 not in lift_game.function_dispatch_targets(function)
    default = lift_game.BoundedDisassembler(bytes(raw), base, [section(0, 0, len(raw))])
    assert base + 0x30 not in default.disassemble_function(base, {}).jump_targets
    # Negative index -1 selects an arm below the displacement, in the same body.
    negative = bytearray(raw)
    biased = table + 7 * 4
    negative[:7] = b"\xff\x24\x95" + struct.pack("<I", biased)
    values = [base + 0x20] * 8
    values[6] = base + 0x30
    negative[0x100:0x120] = struct.pack("<8I", *values)
    negative[0x120:0x124] = struct.pack("<I", base + 0x40)
    biased_decoder = lift_game.BoundedDisassembler(bytes(negative), base,
        [section(0, 0, len(raw))], jump_tables={biased: (-7, 8)})
    biased_function = biased_decoder.disassemble_function(base, {})
    assert base + 0x30 in biased_function.blocks and base + 0x40 not in biased_function.blocks
    assert biased_decoder.jump_table_targets(biased_function.blocks[base].instructions[0]) == values
    assert base + 0x30 not in lift_game.function_dispatch_targets(biased_function)
    positive = bytearray(raw)
    positive[0x100:0x114] = struct.pack("<5I", 0xDEADBEEF, base + 0x20,
        base + 0x30, base + 0x20, base + 0x40)
    positive_decoder = lift_game.BoundedDisassembler(bytes(positive), base,
        [section(0, 0, len(raw))], jump_tables={table: (1, 3)})
    positive_function = positive_decoder.disassemble_function(base, {})
    assert positive_function.jump_targets == {base + 0x20, base + 0x30}
    assert base + 0x40 not in positive_function.blocks
    for bad_count, bad_value in ((80, 0xDEADBEEF), (257, base + 0x30)):
        broken = bytearray(raw)
        struct.pack_into("<I", broken, 0x100 + 66 * 4, bad_value)
        try:
            lift_game.BoundedDisassembler(bytes(broken), base, [section(0, 0, len(raw))],
                                         jump_tables={table: bad_count})
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid declared table passed validation")
    # A direct tail more than 1 MiB away is deliberately outside source CFG.
    tail = base + 0x130000
    binary = b"\xe9" + struct.pack("<i", tail - (base + 5)) + b"\xc3"
    info = SimpleNamespace(image_base=base, entry_point_rva=0,
                           sections=[section(0, 0, 5), section(0x130000, 5, 1)])
    with tempfile.TemporaryDirectory(prefix="lift-graph-check-") as directory:
        path = Path(directory) / "module.bin"
        path.write_bytes(binary)
        with patch.object(lift_game, "analyze_pe", return_value=info), \
             patch.object(lift_game, "build_iat_map", return_value={}):
            _, _, _, functions, rejected = lift_game.collect_functions(path, [{"address": base}], label="Synthetic")
        assert set(functions) == {base, tail} and not rejected
    # Emission tail-transfers both an internal decode gap and a final fallthrough.
    nop = lambda address: SimpleNamespace(address=address, end_address=address + 1,
        mnemonic="nop", is_jump=False, is_ret=False, is_uncond_jump=False)
    sparse = SimpleNamespace(calls_to=set(), jump_targets=set(),
        blocks={base: SimpleNamespace(instructions=[nop(base), nop(base + 16)])})
    assert lift_game.function_dispatch_targets(sparse) == {base + 1, base + 17}
    print("PASS: sparse/negative table bounds and local arms, invalid slot/count, far tail and fallthrough closure")


if __name__ == "__main__":
    main()
