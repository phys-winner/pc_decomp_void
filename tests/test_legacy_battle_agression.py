"""Two original2008 full-caption topics enter the same battle callback."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
from generate_debug_levels import scene_catalog
from gscript_binary import Module
from patch_scripts import read_entry
from test_subtitle_timing import voiceover
from test_touch_native import VM


class Vector(list):
    @property
    def Count(self): return len(self)
    def add(self, value): self.append(value)


legacy = scene_catalog("research/vfs-index.polish.json")
strings = dict(voiceover("research/vfs-index.polish.json"))
owner = object()
for name in ("driller", "hole"):
    case = next(row for row in legacy["extras"] if row["id"] == "battle-" + name)
    assert case["commands"] == ["/port_ensure_hunter " + name, "/talk_hunter " + name + " agression"]
    assert "agression_" + name in strings and "process_agression_" + name not in strings
    path = "Scripts\\" + case["proof"].split(".bin:", 1)[0].replace("/", "\\") + ".bin"
    module = Module(read_entry("research/vfs-index.polish.json", path), legacy=True)
    rows = list(module.instructions())
    branches = {}
    for topic in ("agression", "process_agression"):
        index = next(i for i, row in enumerate(rows) if row.get("text") == topic)
        end = rows[index + 2]["operands"][0]
        branches[topic] = [row for row in rows[index:] if row["offset"] < end and row.get("opcode") == 69]
    # agression optionally adds its real monologue+flag setter; its last
    # callback is unconditional, including when that flag already exists.
    assert len(branches["agression"]) == 3 and len(branches["process_agression"]) == 2
    callback = branches["agression"][-1]
    assert callback["operands"] == branches["process_agression"][-1]["operands"]
    index = next(i for i, row in enumerate(rows) if row.get("text") == "agression")
    entry = max(row["offset"] for row in rows[:index] if row.get("header"))
    for existing in (None, False, True):
        flags = {} if existing is None else {"was_agression_monolog_" + name: existing}
        vm = VM(module, globals={0: {"Properties": {"name": name}}},
                named={"!vector": Vector, "self": owner, "World": {"Vars": flags}})
        stop = branches["agression"][0 if existing is None else -1]["offset"]
        end, registers = vm.run(entry, {-4: "agression"}, stops=(stop,))
        assert end == stop
        if existing is None:
            assert registers[5] == "agression_" + name
        else:
            assert registers[5] is False, "repeat entry still appends its unconditional original callback"

    target = callback["operands"][1]
    tail = [row for row in rows if target < row["offset"] < target + 128]
    send = next(row["offset"] for row in tail if row.get("symbol") == "sendGenericEventToWorld")
    call = next(row["offset"] for row in tail if row["offset"] > send and row.get("opcode") == 57)
    captured = []
    vm = VM(module, named={"World": owner, "sendGenericEventToWorld": lambda *args: captured.append(args)})
    end, _ = vm.run(send, {-4: False}, stops=(call + 8,))
    assert end == call + 8 and captured == [(owner, "onLocationExit", True, False)]

for case in legacy["extras"]:
    if case["kind"] == "battle" and case["id"] not in ("battle-driller", "battle-hole"):
        assert case["commands"][-1].endswith(" process_agression")
assert len(legacy["map_entries"]) == 29 and len(legacy["extras"]) == 50
print("PASS: actual2008 agression captions/flag-absent and flag-present paths; identical unconditional battle callback; other8 battles unchanged")
