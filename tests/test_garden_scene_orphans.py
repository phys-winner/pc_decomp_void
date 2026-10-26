"""Exact scene-only repair of the two authored empty RU/EN garden triggers."""
import copy
from pathlib import Path
import sys
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from patch_scripts import GARDEN_ORPHANS, garden_scene_overrides, patch_garden_orphan_trigger, read_entry


def structural(node, offsets=True):
    return (node.tag, {k: v for k, v in node.attrib.items() if offsets or k != "BinOffset"},
            tuple(structural(child, offsets) for child in node))


def main():
    actual = {}
    for lang in ("", ".english", ".german", ".polish"):
        index = "research/vfs-index" + lang + ".json"
        proposals = list(garden_scene_overrides(index))
        assert len(proposals) == (2 if lang in ("", ".english") else 0)
        for name, original, patched in proposals:
            scene = Path(name.replace("\\", "/")).stem
            before, after = ET.fromstring(original), ET.fromstring(patched)
            target, = [a for a in before.find("Actors") if a.get("Name") == "t_butterfly_trunk"]
            expected = copy.deepcopy(before)
            expected.find("Actors").remove(next(a for a in expected.find("Actors") if a.get("Name") == "t_butterfly_trunk"))
            assert structural(after) == structural(expected), "unrelated scene nodes or properties changed"
            assert target.get("Type") == "trigger" and not list(target.find("Physics"))
            assert not target.find("Physics").attrib
            binary = read_entry(index, name[:-4] + ".s")
            assert int(target.get("BinOffset")) == len(binary)
            assert read_entry(index, "Scripts\\" + target.find("Script").get("Filename").replace("/", "\\") + ".bin") is None
            # Exactly one actor is removed; all other scene bytes stay untouched.
            start = original.index(b'\t\t<Actor Type="trigger" Name="t_butterfly_trunk"')
            end = original.index(b'\t\t</Actor>\n', start) + len(b'\t\t</Actor>\n')
            assert patched == original[:start] + original[end:]
            german = ET.fromstring(read_entry("research/vfs-index.german.json", name))
            german_actors = {a.get("Name"): a for a in german.find("Actors")}
            assert "t_butterfly_trunk" not in german_actors
            assert len(before.find("Actors")) - 1 == len(after.find("Actors")) == len(german_actors)
            for actor in after.find("Actors"):
                if scene == "trunk" and actor.get("Name") == "plants":
                    continue  # DE also edits plant locators; retain RU/EN plant data.
                assert structural(actor, False) == structural(german_actors[actor.get("Name")], False)
            assert actual.setdefault(scene, patched) == patched
            for bad_data, bad_size in ((original + b"\n", len(binary)), (original, len(binary) - 1),
                                       (original.replace(b"<Physics />", b'<Physics Enabled="1" />'), len(binary))):
                try:
                    patch_garden_orphan_trigger(bad_data, scene, bad_size)
                except AssertionError:
                    pass
                else:
                    raise AssertionError("changed source, geometry or EOF boundary accepted")
    assert set(GARDEN_ORPHANS) == {"trunk", "trunkbright"}, "do not include gorge or unrelated assets"
    print("PASS: exact RU/EN garden-trigger removals, DE2009 structure, all other bytes/geometry and 2008 preserved; 12 rejection controls")


if __name__ == "__main__":
    main()
