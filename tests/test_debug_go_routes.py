"""Exclude unsupported commands, retaining complete scene/conversation coverage."""
import json
from pathlib import Path
import sys
from xml.etree import ElementTree as ET
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from generate_debug_levels import catalog, menu_catalog, scene_catalog, UNENTERABLE_HUNTER_GO_2009, UNRESOLVED_HUNTER_ENTRY_2009
from gscript_binary import Module
from patch_scripts import read_entry

for year, index, raw_count, menu_count, bad_count in (("2009", "research/vfs-index.json", 35, 26, 9),
                                                     ("2008", "research/vfs-index.polish.json", 29, 29, 0)):
    raw_ids, raw_scenes, raw_names = catalog(index)
    ids, scenes, names = menu_catalog(index)
    data = scene_catalog(index)
    assert len(raw_ids) == raw_count and len(ids) == menu_count
    excluded = data["excluded_routes"]
    assert len(excluded) == bad_count
    assert set(raw_ids) == set(ids) | {row["id"] for row in excluded}
    assert not set(ids) & {row["id"] for row in excluded}
    for language, labels in names.items():
        assert labels == [raw_names[language][raw_ids.index(number)] for number in ids]
    assert [(row["id"], row["scene"]) for row in data["map_entries"]] == list(zip(ids, scenes))
    for row in [*data["map_entries"], *excluded]:
        assert row["commands"] == ["/go " + str(row["id"])], "do not rewrite a /go proof as a conversation"
    source = json.loads((ROOT / index).read_text())
    all_xml = {row["name"][7:].replace("\\", "/").lower() for c in source["containers"] for row in c["entries"]
               if row["name"].lower().startswith("scenes\\") and row["name"].lower().endswith(".xml")}
    covered = {scene.lower() for scene in data["covered_scenes"]}
    excluded_xml = {row["scene"].lower() for row in data["excluded"]}
    assert not covered & excluded_xml and covered | excluded_xml == all_xml
    assert ("arena/talkloc.xml" in covered) == (year == "2008")
    brothers = {row["id"]: row for row in data["extras"] if row["kind"] == "brother"}
    assert len(brothers) == (5 if year == "2009" else 10) and data["extras"][-1]["kind"] == "easter_egg"
    original_brothers = dict(brothers)
    original_brothers.update((row["id"], row) for row in data.get("excluded_extra_routes", []) if row["kind"] == "brother")
    assert len(original_brothers) == 10
    for row in brothers.values():
        name = row["id"][8:]
        assert row["commands"] == ["/port_ensure_hunter " + name, "/talk_hunter " + name + (" meeting" if year == "2008" else "")]
    if year == "2009":
        aliases = [row for row in excluded if row["kind"] == "unsupported_original_go"]
        assert {row["id"] for row in aliases} == set(UNENTERABLE_HUNTER_GO_2009)
        assert {row["id"] for row in excluded} == set(UNENTERABLE_HUNTER_GO_2009) | {26}
        assert next(row for row in excluded if row["id"] == 26)["kind"] == "unresolved_original_dependency"
        domains = ET.fromstring(read_entry(index, "Properties\\World\\domain.xml"))
        mapping = {int(next(p.get("value") for p in domain if p.get("name") == "BrotherLocation")):
                   next(p.get("value") for p in domain if p.get("name") == "Brother") for domain in domains}
        root_script = ET.fromstring(read_entry(index, "Scenes\\Arena\\talkloc.xml")).find("Script").get("Filename")
        assert root_script == "scene/hunter_talk"
        assert read_entry(index, "Scripts\\" + root_script.replace("/", "\\") + ".bin") is None
        for row in aliases:
            assert row["scene"] == "Arena/talkloc.xml" and row["brother"] == mapping[row["id"]]
            field = "excluded_entry" if row["brother"] in UNRESOLVED_HUNTER_ENTRY_2009 else "retained_entry"
            assert row[field] == "brother-" + row["brother"]
            assert (row[field] in brothers) == (field == "retained_entry")
            script = original_brothers[row[field]]["proof"].split(".bin:", 1)[0]
            module = Module(read_entry(index, "Scripts\\" + script.replace("/", "\\") + ".bin"))
            methods = {(m["name"], m["args"]) for c in module.contexts for m in c["methods"]}
            assert ("initTalk", 2) in methods and not any(name == "initLocation" for name, _ in methods)
        assert 33 in ids and raw_scenes[raw_ids.index(33)] == "Exit/exit_shaft.xml"
    else:
        assert not excluded and not any(scene.lower() == "arena/talkloc.xml" for scene in raw_scenes)
        assert all(number in ids and raw_scenes[raw_ids.index(number)] == "Exit/exit_shaft.xml" for number in (32, 33, 34))
        assert ET.fromstring(read_entry(index, "Scenes\\Arena\\talkloc.xml")).find("Script").get("Filename") == ""
        exit_root = ET.fromstring(read_entry(index, "Scenes\\Exit\\exit_shaft.xml")).find("Script").get("Filename")
        module = Module(read_entry(index, "Scripts\\" + exit_root.replace("/", "\\") + ".bin"), legacy=True)
        assert ("initLocation", 1) in {(m["name"], m["args"]) for c in module.contexts for m in c["methods"]}
print("PASS: 2009 eight unsupported aliases/Gorge +26 unchanged /go; 2008 all29 retained; filtered Brother routes, localized labels and full XML accounting preserved")
