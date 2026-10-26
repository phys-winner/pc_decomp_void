"""Keep proven failing loaders out of all generated 2009 location choices."""
from pathlib import Path
import json
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import generate_debug_levels as generator
from patch_scripts import read_entry

HUNTERS = {"ironclad", "driller", "caterpillar", "dudochnik", "lattice"}
BAD_EXTRA = {kind + "-" + hunter for kind in ("brother", "battle") for hunter in HUNTERS} | {"hunter-twin"}


def check(module):
    main, old = module.scene_catalog(), module.scene_catalog("research/vfs-index.polish.json")
    assert len(main["map_entries"]) == 26 and len(main["extras"]) == 43
    assert 26 not in module.menu_catalog()[0]
    assert {e["id"] for e in main["excluded_extra_routes"]} == BAD_EXTRA
    assert not {e["id"] for e in main["extras"]} & BAD_EXTRA
    assert len(old["map_entries"]) == 29 and len(old["extras"]) == 50
    assert {e["id"] for e in old["excluded_extra_routes"]} == {"hunter-twin"} and not old["excluded_routes"]
    assert BAD_EXTRA - {"hunter-twin"} <= {e["id"] for e in old["extras"]}, "Main's NPC failures must not hide verified Tension routes"
    assert main["extras"][-1]["id"] == old["extras"][-1]["id"] == "backyard"
    for row in main["excluded_extra_routes"]:
        assert row["reason"] and row["commands"] and row["proof"]
    unresolved = {row["scene"].lower(): row for row in main["excluded"] if row["kind"] == "unresolved_original_dependency"}
    assert set(unresolved) == {"park/gorge.xml", "arena/talkloc.xml", "map/triumph_ending.xml"}
    assert len(main["covered_scenes"]) == 53 and len(main["excluded"]) == 13 and main["total_scenes"] == 66
    return main


main = check(generator)
for index in ("research/vfs-index.json", "research/vfs-index.english.json", "research/vfs-index.german.json"):
    assert read_entry(index, "Scripts\\monster\\worm_trap_trigger_center.bin") is None
    data = json.loads((ROOT / index).read_text())
    assert not any("doppleganger_appear" in row["name"].lower() or "doppelganger_appear" in row["name"].lower()
                   for c in data["containers"] for row in c["entries"])

# Exercise the actual generator after independently re-enabling each rejected
# family. The contract must catch a restored bad map, NPC pair or cinematic.
source = (ROOT / "tools/generate_debug_levels.py").read_text(encoding="utf-8")
line = next(line for line in source.splitlines() if line.startswith("UNRESOLVED_HUNTER_ENTRY_2009 ="))
for old, new in ((line, line.replace(', "lattice"', '')),
                 (' | set(UNRESOLVED_MAP_2009)', ''),
                 ('e["id"] == "hunter-twin" or', 'False or')):
    assert source.count(old) == 1
    broken = types.ModuleType("broken_route_filter")
    exec(compile(source.replace(old, new), "<negative-control>", "exec"), broken.__dict__)
    try:
        check(broken)
    except (AssertionError, KeyError):
        pass
    else:
        raise AssertionError("negative control restored a rejected route")
print("PASS: 69 main/79 legacy, separate route/XML accounting; actual-generator map/NPC/cinematic negative controls rejected")
