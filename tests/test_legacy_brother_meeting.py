"""Use the actual 2008 console/natural-encounter topic and dialogue branch."""
from pathlib import Path
import json
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


world = Module(read_entry("research/vfs-index.polish.json", "Scripts\\world\\world.bin"), legacy=True)
entity, owner, seen = object(), object(), []


def lookup(regs, slot):
    assert slot == 2 and regs[1] == "kolesnik"
    regs[0] = entity


# Execute both actual console branches, including argument-count checking and
# entity lookup. The advertised optional topic defaults to an empty string.
for arguments, stop, topic in ((["kolesnik"], 94880, ""), (["kolesnik", "meeting"], 95128, "meeting")):
    vm = VM(world, named={"self": owner, "sendGenericEventToWorld": lambda *args: seen.append(args)}, calls={71336: lookup})
    end, _ = vm.run(94672, {0: "talk_hunter", -4: Vector(arguments)}, stops=(stop,))
    assert end == stop and seen[-1] == (owner, "onHunterPlayerTalk", entity, topic)

# The ordinary world encounter itself supplies exactly the same meeting topic.
vm = VM(world, named={"self": owner, "sendGenericEventToWorld": lambda *args: seen.append(args),
                      "__externals__": {(43, 0): entity}})
end, _ = vm.run(114496, {}, stops=(114556,))
assert end == 114556 and seen[-1] == (owner, "onHunterPlayerTalk", entity, "meeting")

legacy = scene_catalog("research/vfs-index.polish.json")
strings = dict(voiceover("research/vfs-index.polish.json"))
brothers = [row for row in legacy["extras"] if row["kind"] == "brother"]
assert len(brothers) == 10
for case in brothers:
    name = case["id"].removeprefix("brother-")
    assert case["commands"] == ["/port_ensure_hunter " + name, "/talk_hunter " + name + " meeting"]
    path = "Scripts\\" + case["proof"].split(".bin:", 1)[0].replace("/", "\\") + ".bin"
    module = Module(read_entry("research/vfs-index.polish.json", path), legacy=True)
    rows = list(module.instructions())
    at = next(i for i, row in enumerate(rows) if row.get("text") == "meeting")
    entry = max(row["offset"] for row in rows[:at] if row.get("header"))
    key_at = next(i for i in range(at + 1, len(rows)) if rows[i].get("text") == "meeting_")
    constructor = next(row["offset"] for row in rows[key_at:] if row.get("opcode") == 69)
    vm = VM(module, globals={0: {"Properties": {"name": name}}}, named={"!vector": Vector, "self": owner})
    end, registers = vm.run(entry, {-4: "meeting"}, stops=(constructor,))
    assert end == constructor and registers[5] == "meeting_" + name and strings[registers[5]]

    # Original empty-topic input yields no dialogue. This is the actual vector
    # subsequently indexed by talk_base, not a stub accepting a made-up topic.
    next_header = next(row["offset"] for row in rows if row.get("header") and row["offset"] > entry)
    end_at = max(row["offset"] for row in rows if entry < row["offset"] < next_header and row.get("opcode") == 65)
    vm = VM(module, globals={0: {"Properties": {"name": name}}}, named={"!vector": Vector, "self": owner})
    end, registers = vm.run(entry, {-4: ""}, stops=(end_at,))
    assert end == end_at and registers[-5] == [], name

for case in scene_catalog()["extras"]:
    if case["kind"] == "brother":
        name = case["id"].removeprefix("brother-")
        assert case["commands"] == ["/port_ensure_hunter " + name, "/talk_hunter " + name]
for case in legacy["extras"]:
    if case["kind"] == "battle":
        topic = "agression" if case["id"] in ("battle-driller", "battle-hole") else "process_agression"
        assert case["commands"][-1].endswith(" " + topic)
print("PASS: original2008 console/natural encounter, all10 actual dialogue branches+shipped captions, empty-topic failure contract; Main topics and separately verified battle topics preserved")
