"""Keep Android debug pickers aligned with shipped map, scripts and scene targets."""
import json
import hashlib
from pathlib import Path
import re
import struct
from xml.etree import ElementTree as ET

from patch_scripts import ROOT, read_entry
from gscript_binary import Module

OUT = ROOT / "android/app/src/org/thevoid/port/DebugLevels.java"

# These raw 2009 map aliases need the original conversation loader, not /go.
UNENTERABLE_HUNTER_GO_2009 = {32: "lattice", 34: "driller", 35: "stiltman", 36: "whaler",
                              37: "kolesnik", 38: "dudochnik", 39: "ironclad", 40: "caterpillar"}


# Fresh-save device entry fails before talk/battle: the original map AI asks
# for a path from the newly spawned Brother's fixed home to that same home.
# Map.findPathToLocation deliberately returns null for this zero-distance case.
UNRESOLVED_HUNTER_ENTRY_2009 = {"ironclad", "driller", "caterpillar", "dudochnik", "lattice"}
UNRESOLVED_MAP_2009 = {26: "The authored Gorge has six real trap volumes requiring monster/worm_trap_trigger_center.bin, absent from every shipped 2009 language archive; entry renders but encounter logic is incomplete."}
UNRESOLVED_TWIN_DEMO = "The original Twin appearance requests sound/snd_hunter_11_doppleganger_appear#44.ogg, absent from all available shipped language archives and loose sound assets; geometry renders but the authored audio is incomplete."


def menu_catalog(index="research/vfs-index.json", *, names=True):
    ids, scenes, languages = catalog(index, names=names)
    legacy = "polish" in index
    excluded = set() if legacy else set(UNENTERABLE_HUNTER_GO_2009) | set(UNRESOLVED_MAP_2009)
    assert legacy or all(number in ids and scenes[ids.index(number)].lower() == "arena/talkloc.xml"
                         for number in UNENTERABLE_HUNTER_GO_2009)
    assert legacy or scenes[ids.index(26)].lower() == "park/gorge.xml"
    keep = [i for i, number in enumerate(ids) if number not in excluded]
    return ([ids[i] for i in keep], [scenes[i] for i in keep],
            {lang: [names[i] for i in keep] for lang, names in languages.items()})


def scene_catalog(index="research/vfs-index.json"):
    """Every shipped scene, with its authored entry route or an explicit exclusion.

    A scene XML is not a level loader: obscuras, arenas and movies require their
    original world coroutine to create the player, actors and camera.
    """
    legacy = "polish" in index
    ids, map_scenes, _ = menu_catalog(index)
    entries = [e["name"] for c in json.loads((ROOT / index).read_text())["containers"] for e in c["entries"]]
    scenes = {p[7:].replace("\\", "/").lower(): p[7:].replace("\\", "/")
              for p in entries if p.lower().startswith("scenes\\") and p.lower().endswith(".xml")}
    world = Module(read_entry(index, "Scripts\\world\\world.bin"), legacy=legacy)
    rows = list(world.instructions())
    extras = []

    def add(key, label, scene, commands, kind, proof, follows=()):
        assert scene.lower() in scenes, scene
        extras.append(dict(id=key, label=("[?] " if kind == "easter_egg" else "[*] ") + label,
                           scene=scenes[scene.lower()], commands=commands, kind=kind, proof=proof,
                           follows=[scenes[s.lower()] for s in follows],
                           camera="player" if kind in ("location", "easter_egg", "surface", "battle") else
                                  "interactive authored camera" if kind in ("sister", "brother") else "authored cinematic"))

    for girl in ET.fromstring(read_entry(index, "Properties\\World\\girl.xml")).findall("Category"):
        name = girl.get("Name")
        add("sister-" + name, "Obscura: " + name, "Map/obscure_" + name + ".xml",
            ["/open_zone 4", "/port_ensure_girl " + name, "/talk_girl " + name], "sister",
            "World.onGirlPlayerObscure -> original ui/obscure.initObscure(name); original Sister entity ensured once")
    for i, row in enumerate(rows):
        if not row.get("text", "").startswith("Creating hunter: "):
            continue
        end = next((j for j in range(i + 1, len(rows)) if rows[j].get("header")), len(rows))
        texts = [r["text"] for r in rows[i:end] if r.get("text")]
        name = texts[2]
        script = next(t for t in texts if t.startswith("scene/"))
        if read_entry(index, "Scripts\\" + script.replace("/", "\\") + ".bin") is None:
            continue  # The shipped doppleganger factory has no talk/fight implementation.
        assert "process_agression" in [r.get("text") for r in Module(read_entry(index, "Scripts\\" + script.replace("/", "\\") + ".bin"), legacy=legacy).instructions()]
        talk = "Arena/talkloc.xml" if legacy else "Arena/huntertalk_A.xml" if name in ("stiltman", "whaler") else "Arena/huntertalk_B.xml" if name in ("kolesnik", "lattice") else "Arena/huntertalk_C.xml" if name in ("driller", "hole", "mongolfier") else "Arena/talkloc.xml"
        add("brother-" + name, "Brother: " + name, talk,
            ["/port_ensure_hunter " + name, "/talk_hunter " + name + (" meeting" if legacy else "")], "brother",
            script + ".bin: original onHunterPlayerTalk" + ("; 2008 natural encounter topic=meeting (empty debug topic has no dialogue)" if legacy else ""))
        arena = next(t for t in texts if t.startswith("arena/")) + ".xml"
        battle_topic = "agression" if legacy and name in ("driller", "hole") else "process_agression"
        add("battle-" + name, "Battle: " + name, arena,
            ["/port_ensure_hunter " + name, "/talk_hunter " + name + " " + battle_topic], "battle",
            script + ".bin: " + battle_topic + " -> original arena gameplay coroutine")
    add("plot", "Plot", "Garden/plot.xml", ["/plot"], "location", "World.onPlot -> original scene/std loader")
    for number in range(3):
        add("surface-" + str(number), "Surface: " + str(number), "up_level/up_level.xml", ["/surface_exit " + str(number)], "surface",
            "Original /surface_exit selects a complete authored entrance and surface gameplay coroutine")
    for name in sorted(g.get("Name") for g in ET.fromstring(read_entry(index, "Properties\\World\\girl.xml")).findall("Category")):
        assert read_entry(index, "Properties\\Actors\\" + name + "_exit.xml") is not None, name
        add("final-" + name, "Finale: " + name, "Exit/exit_shaft_dark.xml", ["/final " + name], "cinematic",
            "Original /final creates its exit actor/camera, then surface camera and credits",
            ["up_level/up_level.xml", "Map/main_menu.xml"])
    add("sister-death", "Sister's death", "Map/obscure_sister_death.xml", ["/port_ensure_girl sister", "/sister_die"], "cinematic",
        "Original /sister_die coroutine; requires Sister entity, intentionally changes her debug state")
    add("sister-respawn", "Sister's return", "Map/obscure_sister_respawn.xml", ["/respawn_sister"], "cinematic",
        "Original /respawn_sister creates actor and camera; does not require a preceding death")
    add("hunter-appearance", "Brother's appearance", "Map/triumph.xml", ["/hunter_demo kolesnik"], "cinematic",
        "Original onHunterDemo(kolesnik) creates appearance actor and camera")
    add("hunter-twin", "Twin's appearance", "Map/triumph_ending.xml", ["/hunter_demo twin"], "cinematic",
        "Original onHunterDemo(twin) uses complete cinematic, distinct from the unfinished doppleganger battle")
    if not legacy:
        add("void-death", "Death of the Void", "Map/map_death.xml", ["/void"], "cinematic", "Original /void camera/effect coroutine")
        add("hero-finale", "Hero's finale", "Map/obscure_final.xml", ["/end"], "cinematic",
            "Original /end; first phase waits for the player's breach gesture, then void death, surface and credits",
            ["Map/map_death.xml", "up_level/up_level.xml", "Map/main_menu.xml"])
        add("ole-birth", "Ole's birth", "Map/obscure_ole.xml", ["/ole_born"], "cinematic", "Original /ole_born movie, separate from normal Ole obscura")
    # This is explicitly recorded as an Easter egg by map_exit_zew, rather than
    # inferred merely because a finished location is absent from the world map.
    egg = Module(read_entry(index, "Scripts\\map_exit_zew.bin"), legacy=legacy)
    assert {"easter_egg_backyard", "onBackyard"} <= {r.get("text") for r in egg.instructions()}
    add("backyard", "Backyard", "Map/backyard.xml", ["/backyard"], "easter_egg",
        "map_exit_zew sets World.Vars.easter_egg_backyard then onBackyard; /backyard uses the same original scene/backyard coroutine")
    excluded_extra_routes = [dict(e, reason=UNRESOLVED_TWIN_DEMO if e["id"] == "hunter-twin" else
                                 "Original fixed-home map-AI bootstrap emits monsterAI_followPath : null path before this conversation/battle; no complete fresh-save route has been verified.")
                             for e in extras if e["id"] == "hunter-twin" or not legacy and
                             e["kind"] in ("brother", "battle") and e["id"].split("-", 1)[1] in UNRESOLVED_HUNTER_ENTRY_2009]
    excluded_ids = {e["id"] for e in excluded_extra_routes}
    extras = [e for e in extras if e["id"] not in excluded_ids]
    covered = {s.lower() for s in map_scenes}
    covered.update(s.lower() for e in extras for s in [e["scene"], *e["follows"]])
    reasons = {
        "park/gorge.xml": UNRESOLVED_MAP_2009[26],
        "arena/talkloc.xml": "The generic /go loader lacks scene/hunter_talk; all three 2009 factory-specific conversation routes selecting this room also fail their original fixed-home map-AI bootstrap.",
        "map/triumph_ending.xml": UNRESOLVED_TWIN_DEMO,
        "test.xml": "Developer test entry, a copy of the Flache arena with test script; not an additional authored game location",
        "newgame.xml": "Legacy isolated newgame/* prototype, not the live game.bin -> world.initWorld -> Girl/sister.xml tutorial",
        "arena/kolesnik.xml": "Unused early arena; no shipped hunter factory selects it (Kolesnik uses Arena/dudochnik.xml)",
        "girl/sister_dark.xml": "Unused tutorial variant, no live script activation; actual tutorial selects Girl/sister.xml",
        "map/obscure_yani_old.xml": "Unused older Yani variant; original obscura loader selects Map/obscure_yani.xml",
        "map/obscure.xml": "Uninstantiated generic obscura template; original loader selects the named Sister's complete scene",
        "map/body.xml": "Body UI helper, requires its owning ui/body actor and body camera; reached by the existing Body control",
        "map/map.xml": "World-map UI helper, requires the live map state/camera; reached by existing Map/Back controls",
        "map/objectscreen.xml": "Object inspection UI helper; ui/show_glotok constructs the inspected actor and camera",
        "map/textscreen.xml": "Credits/text UI helper; world/main_menu constructs and owns the text state",
    }
    excluded = [dict(scene=value, reason=reasons[key], kind="incomplete/test-stub" if key in
                    ("test.xml", "newgame.xml", "arena/kolesnik.xml", "girl/sister_dark.xml", "map/obscure_yani_old.xml") else "unresolved_original_dependency" if key in ("park/gorge.xml", "arena/talkloc.xml", "map/triumph_ending.xml") else "ui_or_template")
                for key, value in scenes.items() if key not in covered]
    raw_ids, raw_scenes, _ = catalog(index)
    excluded_routes = [dict(id=number, scene=scene, commands=["/go " + str(number)],
                            kind="unsupported_original_go", brother=UNENTERABLE_HUNTER_GO_2009[number],
                            **({"retained_entry": "brother-" + UNENTERABLE_HUNTER_GO_2009[number]}
                               if UNENTERABLE_HUNTER_GO_2009[number] not in UNRESOLVED_HUNTER_ENTRY_2009 else
                               {"excluded_entry": "brother-" + UNENTERABLE_HUNTER_GO_2009[number]}),
                            reason="The original /go uses loadScene then initLocation; talkloc's generic scene/hunter_talk script is absent. The complete Brother route uses loadSceneS with an explicit talk_scene_script and initTalk.")
                       for number, scene in zip(raw_ids, raw_scenes) if number not in ids and number in UNENTERABLE_HUNTER_GO_2009]
    if not legacy:
        excluded_routes += [dict(id=number, scene=raw_scenes[raw_ids.index(number)], commands=["/go " + str(number)],
                                 kind="unresolved_original_dependency", reason=reason)
                            for number, reason in UNRESOLVED_MAP_2009.items()]
    return dict(source=index, source_world_sha256=hashlib.sha256(world.original).hexdigest(),
                status="STATIC_ROUTES_VERIFIED; device acceptance recorded separately", total_scenes=len(scenes),
                map_entries=[dict(id=number, scene=scene, commands=["/go " + str(number)]) for number, scene in zip(ids, map_scenes)],
                extras=extras, excluded=excluded, excluded_routes=excluded_routes, **({"excluded_extra_routes": excluded_extra_routes} if excluded_extra_routes else {}), covered_scenes=sorted(scenes[s] for s in covered))


def catalog(index="research/vfs-index.json", *, names=True):
    world = read_entry(index, "Properties\\World\\world.wmp")
    count = struct.unpack_from("<I", world, 1 + world[0] * 2)[0]
    entries = {}
    pattern = rb"(?:\x01([0-9])|\x02([0-9][0-9]))([\x01-\xff])((?:[\x20-\x7e]\x00){4,})"
    for match in re.finditer(pattern, world):
        number = int(match[1] or match[2])
        scene = match[4].decode("utf-16le")
        assert match[3][0] == len(scene) and scene.endswith(".xml"), (number, scene)
        assert number not in entries
        entries[number] = scene
    assert len(entries) == count, (len(entries), count)
    ids = sorted(entries)
    if not names:
        return ids, [entries[number] for number in ids], {}
    languages = {}
    for language, strings_index in ((("ru", "research/vfs-index.json"), ("de", "research/vfs-index.german.json")) if "polish" not in index else (("pl", index),)):
        raw = read_entry(strings_index, "Properties\\Strings\\map.txt").decode("utf-16")
        names = {int(number): text.strip() for number, text in re.findall(r"@string\s+(\d+)\s*\n(.*?)(?=\n@|\Z)", raw, re.S)}
        assert all(number in names and "Deleted" not in names[number] for number in ids), language
        languages[language] = [names[number] for number in ids]
    return ids, [entries[number] for number in ids], languages


def targets(scenes, index="research/vfs-index.json"):
    """Use shipped identifiers rather than guessing arguments for debug menus."""
    rows = list(Module(read_entry(index, "Scripts\\world\\world.bin"), legacy="polish" in index).instructions())
    result = {"GIRLS": {Path(scene).stem for scene in scenes if scene.lower().startswith("girl/")},
              "HUNTERS": set(), "AUTOMONOLOGS": set(), "VARIABLES": {"show_physics", "god_mode", "Chapter"},
              "EVENTS": set(), "POINTS": set(), "CAMERAS": set(), "ANIMATIONS": set(),
              "THEMES": set(), "STRINGS": set()}
    for i, row in enumerate(rows):
        text = row.get("text", "")
        if text.startswith("Creating hunter: "):
            result["HUNTERS"].add(next(r["text"] for r in rows[i + 1:i + 12]
                                       if r.get("text") and r["text"] != "monster"))
        if text == "onAutomonolog" and rows[i + 1].get("text"):
            result["AUTOMONOLOGS"].add(rows[i + 1]["text"])
        if row.get("symbol") == "Vars" and rows[i + 1].get("text"):
            result["VARIABLES"].add(rows[i + 1]["text"])
        if text.startswith("on") and len(text) > 2 and text[2].isupper():
            result["EVENTS"].add(text)
        if text.startswith("gesture_"):
            result["THEMES"].add(text)
        if row.get("symbol") == "getNamedString" and rows[i + 1].get("text"):
            result["STRINGS"].add(rows[i + 1]["text"])
    for scene in set(scenes) | {"up_level/up_level.xml"}:
        for actor in ET.fromstring(read_entry(index, "Scenes\\" + scene.replace("/", "\\"))).iter("Actor"):
            key = "CAMERAS" if actor.get("Type") == "camera" else "POINTS" if actor.get("Type") in ("locator", "locator-mesh") else None
            if key and actor.get("Name"):
                result[key].add(actor.get("Name"))
    containers = json.loads((ROOT / index).read_text())["containers"]
    result["ANIMATIONS"] = {Path(entry["name"].replace("\\", "/")).stem for container in containers
                            for entry in container["entries"] if entry["name"].lower().endswith(".ase")}
    return [(name, sorted(value for value in values if re.fullmatch(r"[A-Za-z0-9_./-]+", value)))
            for name, values in result.items()]


def source(index="research/vfs-index.json", name="DebugLevels"):
    ids, scenes, languages = menu_catalog(index)
    extra = scene_catalog(index)["extras"]
    lines = ["package org.thevoid.port;", "", "/** Generated by tools/generate_debug_levels.py from the shipped map, scripts and scenes. */",
             "final class " + name + " {", "    private " + name + "() { }",
             "    static final int[] IDS = {" + ", ".join(map(str, ids)) + "};"]
    for name, values in [("SCENES", scenes), *((lang.upper(), names) for lang, names in languages.items()), *targets(catalog(index)[1], index)]:
        lines.append("    static final String[] " + name + " = {")
        lines += ["        " + json.dumps(value, ensure_ascii=False) + "," for value in values]
        lines.append("    };")
    for key, values in (("EXTRA_LABELS", [e["label"] for e in extra]), ("EXTRA_SCENES", [e["scene"] for e in extra])):
        lines.append("    static final String[] " + key + " = {")
        lines += ["        " + json.dumps(value, ensure_ascii=False) + "," for value in values]
        lines.append("    };")
    lines.append("    static final String[][] EXTRA_COMMANDS = {")
    lines += ["        {" + ", ".join(json.dumps(command) for command in e["commands"]) + "}," for e in extra]
    lines.append("    };")
    lines += ["}", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    OUT.write_text(source(), encoding="utf-8")
    OUT.with_name("DebugLevelsTension.java").write_text(source("research/vfs-index.polish.json", "DebugLevelsTension"), encoding="utf-8")
    for year, index in (("2009", "research/vfs-index.json"), ("2008", "research/vfs-index.polish.json")):
        (ROOT / "research" / ("debug-scenes-" + year + ".json")).write_text(json.dumps(scene_catalog(index), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(menu_catalog()[0])} supported map routes -> {OUT}")
