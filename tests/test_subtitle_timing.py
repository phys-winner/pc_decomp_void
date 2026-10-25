"""Execute the shipped subtitle parser with valid and failed optional timings."""
from pathlib import Path
import re
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from gscript_binary import Module
from patch_scripts import PATCHES, patch_subtitle_timing, read_entry, rows_of

VM = runpy.run_path(str(ROOT / "tests/test_touch_native.py"))["VM"]


class Vector(list):
    @property
    def Count(self):
        return len(self)

    def add(self, value):
        self.append(value)

    def remove(self, index):
        self.pop(index)


def voiceover(index):
    data = read_entry(index, "Properties\\Strings\\voiceover.dat")
    offset = 0

    def length():
        nonlocal offset
        value = shift = 0
        while True:
            assert offset < len(data) and shift < 32
            byte = data[offset]
            offset += 1
            value |= (byte & 127) << shift
            if not byte & 128:
                return value
            shift += 7

    while offset < len(data):
        assert data[offset:offset + 4] == b"\xff" * 4
        offset += 4
        count = length()
        assert count <= len(data) - offset
        name = data[offset:offset + count].decode("ascii")
        offset += count
        count = length()
        assert count <= (len(data) - offset) // 2
        text = data[offset:offset + count * 2].decode("utf-16le")
        offset += count * 2
        yield name, text
    assert offset == len(data)


def execute(module, tokens, elapsed, start, stop):
    errors = []
    external = {(3, 2): Vector(), (3, 3): Vector()}

    def to_int(text):
        # Original native1017E240 exposes a tuple on success, null on failure.
        return (int(text),) if re.fullmatch(r"\s*[+-]?[0-9]+\s*", text) else None

    vm = VM(module, named={"toInt": to_int, "logError": errors.append,
                           "__externals__": external})
    end, regs = vm.run(start, {1: elapsed, 3: Vector(tokens)}, stops=(stop,))
    return end, regs, external, errors


def main():
    comparisons = records = 0
    for lang, index in (("ru", "research/vfs-index.json"),
                        ("de", "research/vfs-index.german.json")):
        original = Module(read_entry(index, "Scripts\\ui\\subtitle.bin"))
        patched = Module(original.encode())
        info = patch_subtitle_timing(patched, lang)
        assert patched.contexts == original.contexts
        assert patched.table == original.table and patched.types == original.types
        assert patched.pool == original.pool and patched.debug == original.debug
        site = int(info["sites"][0], 16)
        assert all(a == b for i, (a, b) in enumerate(zip(original.code, patched.code))
                   if not site <= i < site + 8)
        rows = rows_of(original)
        start = next(r["offset"] for r in rows if r.get("symbol") == "toInt")
        # Stop after the original timing and all caption tokens were stored.
        stop = next(r["offset"] for r in rows if r["offset"] > site
                    and r["opcode"] == 75 and r["register"] == 4 and r["operands"] == [3])
        fixtures = []
        for _, text in voiceover(index):
            records += 1
            fixtures.extend(line.split("|") for line in text.split("\n") if line)
        fixtures.extend((["0", "zero"], ["-1", "negative", "second caption"],
                         ["2147483647", "boundary"], ["  +42  ", "whitespace"]))
        for tokens in fixtures:
            before = execute(original, tokens, 17000, start, stop)
            after = execute(patched, tokens, 17000, start, stop)
            assert before == after, (lang, tokens, before, after)
            assert after[0] == stop and not after[3]
            assert after[2][3, 2] == [1000 * int(tokens[0])]
            assert after[2][3, 3] == [tokens[1:]]
            comparisons += 1
        for token in ("", " ", "--1", "10x", "process_agression_kolesnik"):
            for captions in ([], ["caption", "second caption"]):
                try:
                    execute(original, [token, *captions], 17000, start, stop)
                except TypeError as error:
                    assert "NoneType" in str(error)
                else:
                    raise AssertionError("Original malformed timing did not reproduce")
                end, _, external, errors = execute(patched, [token, *captions], 17000, start, stop)
                assert end is None and errors == ["wrong number of timings in subtitles"]
                assert external == {(3, 2): [], (3, 3): []}
                comparisons += 1
        # The actual packaging chain also scales subtitle fonts after this guard.
        combined = Module(original.encode())
        dict(PATCHES)["Scripts\\ui\\subtitle.bin"](combined, lang)
        assert combined.contexts == original.contexts and combined.types == original.types
        list(Module(combined.encode()).instructions())
    print(f"PASS subtitle timing: {records} original RU/DE voice records; "
          f"{comparisons} parser comparisons; malformed optional results exit without dereference; "
          "valid timing/caption bytecode outputs and context metadata preserved")


if __name__ == "__main__":
    main()
