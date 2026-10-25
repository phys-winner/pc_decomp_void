"""Inventory and benchmark shipped locations, Sister obscuras and player/Brother arenas.

Run --manifest or --self-test offline. Device runs require an already running game,
the exported profile probes, and a copied save in the explicitly isolated profile. No saves are overwritten,
the live input file is append-only, and every case reloads the same copied save.
"""
import argparse
import codecs
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shlex
import statistics
import subprocess
import sys
import time
from xml.etree import ElementTree as ET

from benchmark_locations import CAMERA, HUD, HUD_BLOCKED, HUD_CONTROL_LOCKED, HUD_LOADING, PIXELS_PER_DEGREE, accepted_location, full_turn_rate, marker_status, samples, turn_events
from generate_debug_levels import catalog
from gscript_binary import Module, p32
from patch_native_menu import Assembler
from patch_scripts import ROOT, read_entry
from patch_touch_native import float_, hook, method, poll

INDEX = "research/vfs-index.json"
DEFAULT_OUT = ROOT / "build/scene-audit-20261019"
SHADER_WORK = re.compile(r"\[d3dx\].*(?:cache miss|live compile service)")
_D3DX_NEGATIVE = r"(?:D3DX(?:CompileShader [^\s]+|AssembleShader) fails as on Windows:|[0-9a-f]{16} served by the live compile service \(error\)(?=\r?$))"
EXPECTED_COMPILER_REJECTION = re.compile(r"\[d3dx\] " + _D3DX_NEGATIVE + r"[^\n]*", re.I | re.M)
GPU_ERROR = re.compile(r"(?:\[(?:gl|d3d9)\].*(?:compile failed|link failed)|\[d3dx\](?! " + _D3DX_NEGATIVE + r").*(?:failed|error))", re.I | re.M)
ARENA_LABELS = {"caterpillar": "Catterpillar", "dudochnik": "Piper"}


def inventory():
    ids, scenes, languages = catalog()
    cases = [dict(id=f"location-{number}", kind="location", location=number, scene=scene,
                  ru=languages["ru"][i], de=languages["de"][i], commands=[f"/go {number}"],
                  shared_talk_location=scene.lower() == "arena/talkloc.xml")
             for i, (number, scene) in enumerate(zip(ids, scenes))]
    girl_data = ET.fromstring(read_entry(INDEX, "Properties\\World\\girl.xml"))
    gameplay_data = ET.fromstring(read_entry(INDEX, "Properties\\World\\gameplay.xml").decode("cp1251"))
    defaults = {p.get("name"): p.get("value") for p in gameplay_data.iter("property")}
    for girl in girl_data.findall("Category"):
        name = girl.get("Name")
        props = {p.get("name"): p.get("value") for p in girl.findall("property")}
        scene = f"Map/obscure_{name}.xml"
        assert read_entry(INDEX, "Scenes\\" + scene.replace("/", "\\")), scene
        camera_data = read_entry(INDEX, "Animations\\camera_girl_" + name + ".ase")
        camera_names = sorted({m[0].decode("ascii") for m in re.finditer(rb"camera_girl_(?:talk|dance)[1-5]_[0-9]+", camera_data)})
        stages = [dict(stage=stage, talk_cameras=[n for n in camera_names if n.startswith(f"camera_girl_talk{stage + 1}_")],
                       dance_cameras=[n for n in camera_names if n.startswith(f"camera_girl_dance{stage + 1}_")])
                  for stage in range(5)]
        donations = [int(props.get(f"SisterStage{i}Limit", defaults[f"SisterStage{i}Limit"])) for i in range(1, 5)]
        cases.append(dict(id="sister-" + name, kind="sister", name=name, scene=scene, stages=stages,
                          stage_donations=donations,
                          location=int(props["Location"]), good_colour=int(props["GoodColor1"]),
                          preparation_commands=["/open_zone 4"],
                          commands=(["/add_girl " + name] if name in ("ole", "echo", "aya") else []) + ["/talk_girl " + name],
                          proof="initObscure with girl: " + name))
    world = Module(read_entry(INDEX, "Scripts\\world\\world.bin"))
    hunter_props = ET.fromstring(read_entry(INDEX, "Properties\\World\\hunter.xml"))
    arena_rows = list(Module(read_entry(INDEX, "Scripts\\scene\\arena_gameplay.bin")).instructions())
    rows = list(world.instructions())
    placeholders, brothers = [], []
    for i, row in enumerate(rows):
        if not row.get("text", "").startswith("Creating hunter: "):
            continue
        end = next((r["offset"] for r in rows[i + 1:] if r.get("header")), len(world.code))
        strings = [r["text"] for r in rows[i:] if r["offset"] < end and r.get("text")]
        name = strings[2]
        assert re.fullmatch(r"[a-z]+", name), (name, strings[:5])
        arena = next(s for s in strings if s.startswith("arena/")) + ".xml"
        talk = next(s for s in strings if s.startswith("scene/"))
        data = read_entry(INDEX, "Scripts\\" + talk.replace("/", "\\") + ".bin")
        if data is None:
            placeholders.append(dict(name=name, arena=arena, missing_talk_script=talk,
                                     reason="Original catalog placeholder; no shipped talk script"))
            continue
        talk_text = [r.get("text") for r in Module(data).instructions()]
        assert "process_agression" in talk_text, talk
        label = "arena_general.sc: creating hunter " + ARENA_LABELS.get(name, name.capitalize()) + "."
        begin = next(i for i, r in enumerate(arena_rows) if r.get("text") == label)
        hunter_script = "Scripts/" + next(r["text"] for r in arena_rows[begin:] if r.get("text", "").startswith("hunter/")) + ".bin"
        number = re.search(r"hunter_(\d+)_", hunter_script)[1]
        properties = next(c for c in hunter_props.findall("Category") if c.get("Name").startswith("hunter_" + number + "_"))
        phase_count = int(next(p.get("value") for p in properties.findall("property") if p.get("name") == "MaxStage"))
        talk_scene = "Arena/huntertalk_A.xml" if name in ("stiltman", "whaler") else "Arena/huntertalk_B.xml" if name in ("kolesnik", "lattice") else "Arena/huntertalk_C.xml" if name in ("driller", "hole", "mongolfier") else "Arena/talkloc.xml"
        brothers.append(dict(id="brother-" + name, kind="brother", name=name, scene=talk_scene,
                             talk_script="Scripts/" + talk + ".bin",
                             commands=["/add_hunter " + name, "/talk_hunter " + name]))
        cases.append(dict(id="battle-" + name, kind="battle", name=name, scene=arena,
                          hunter_script=hunter_script, phase_count=phase_count,
                          vulnerability_windows=name in ("stiltman", "mongolfier", "whaler", "driller"),
                          arena_setup_point="pt_driller_4" if name == "stiltman" else None,
                          commands=["/add_hunter " + name, "/talk_hunter " + name + " process_agression"],
                          proof=label))
    assert len(cases) == 56 and len(placeholders) == 1, (len(cases), placeholders)
    domains = ET.fromstring(read_entry(INDEX, "Properties\\World\\domain.xml"))
    by_location = {}
    for domain in domains.findall("Category"):
        props = {p.get("name"): p.get("value") for p in domain.findall("property")}
        if int(props["BrotherLocation"]) >= 0:
            by_location[int(props["BrotherLocation"])] = props["Brother"]
    for case in cases:
        if not case.get("shared_talk_location"):
            continue
        brother = next(b for b in brothers if b["name"] == by_location[case["location"]])
        case.update(conversation=brother["name"], talk_script=brother["talk_script"], conversation_scene=brother["scene"],
                    conversation_commands=brother["commands"])
    covered = {case["scene"].lower() for case in cases}
    extra_routes = {
        "newgame.xml": ("legacy_intro", "Unselected legacy newgame/* scripts; actual New Game initializes world.xml and Girl/sister.xml"),
        "girl/sister_dark.xml": ("legacy_tutorial", "No reference in any of the 483 shipped scripts; actual tutorial is map location 2, Girl/sister.xml"),
        "exit/exit_shaft_dark.xml": ("ending_cinematic", "/final SISTER"),
        "garden/plot.xml": ("playable_debug_location", "/plot"),
        "map/backyard.xml": ("playable_debug_location", "/backyard"),
        "map/map_death.xml": ("ending_cinematic", "/void"),
        "map/obscure_final.xml": ("ending_cinematic", "/end"),
        "map/obscure_sister_death.xml": ("sister_cinematic", "/sister_die"),
        "map/obscure_sister_respawn.xml": ("sister_cinematic", "/respawn_sister"),
        "up_level/up_level.xml": ("playable_surface", "/surface_exit 0, /surface_exit 1, /surface_exit 2"),
        "arena/kolesnik.xml": ("legacy_arena", "No 2009 hunter factory references this arena"),
        "test.xml": ("developer_test", "Not referenced by the 2009 world routes"),
        "map/obscure_yani_old.xml": ("legacy_scene", "No 2009 world route references this older obscura"),
    }
    non_map = []
    index = json.loads((ROOT / INDEX).read_text(encoding="utf-8"))
    for container in index["containers"]:
        for entry in container["entries"]:
            path = entry["name"]
            if not path.lower().startswith("scenes\\") or not path.lower().endswith(".xml"):
                continue
            scene = path[7:].replace("\\", "/")
            if scene.lower() in covered:
                continue
            root = ET.fromstring(read_entry(INDEX, path))
            scripts = sorted({e.get("Filename") for e in root.iter("Script") if e.get("Filename")})
            kind, route = extra_routes.get(scene.lower(), ("ui_or_encounter_helper", "Loaded by its owning UI or encounter"))
            non_map.append(dict(scene=scene, kind=kind, route=route, scripts=scripts))
    extras = [dict(id="extra-backyard", kind="extra", scene="Map/backyard.xml", commands=["/backyard"]),
              dict(id="extra-plot", kind="extra", scene="Garden/plot.xml", commands=["/plot"]),
              *[dict(id=f"extra-surface-{i}", kind="extra", scene="up_level/up_level.xml", commands=[f"/surface_exit {i}"])
                for i in range(3)]]
    movies = json.loads((ROOT / "research/scene-audit-cinematics.json").read_text(encoding="utf-8"))
    cinematics = []
    for route in movies["cases"]:
        if not route["commands"]:
            continue  # Actual New Game tutorial requires the original menu.
        if route["id"] == "cinematic-hunter-appearance":
            for brother in brothers:
                cinematics.append(dict(route, id=route["id"] + "-" + brother["name"], kind="cinematic",
                                       scene=route["scenes_in_order"][0], commands=["/hunter_demo " + brother["name"]]))
        else:
            cinematics.append(dict(route, kind="cinematic", scene=route["scenes_in_order"][0],
                                   original_breakthrough=route["id"] == "cinematic-end-self"))
    for variant in movies["final_variants"]:
        cinematics.append(dict(variant, id="cinematic-final-" + variant["name"], kind="cinematic",
                               scene=variant["scenes_in_order"][0]))
    return dict(source=INDEX, source_world_sha256=hashlib.sha256(world.original).hexdigest(), cases=cases,
                brother_conversations=brothers, extra_cases=extras, cinematic_cases=cinematics,
                placeholders=placeholders, additional_scenes=non_map,
                scope="35 shipped map entries (8 include their actual Brother talk), 11 Sister obscuras with 5 authored camera stages, 10 player/Brother battles, 10 Brother talks and 5 playable non-map cases; cinematic and helper scenes listed separately")


def frame_times(log):
    """Per-present timing sample, separate from five-second aggregate FPS windows."""
    clocks = [(int(m[1]), float(m[2])) for m in CAMERA.finditer(log)]
    durations = [b[1] - a[1] for a, b in zip(clocks, clocks[1:]) if b[0] == a[0] + 1 and b[1] > a[1]]
    if len(durations) < 2:
        raise RuntimeError("fewer than two consecutive rendered frame timings")
    ordered = sorted(durations)
    return dict(timed_frames=len(durations), timing_sample_sufficient=len(durations) >= 30,
                median_frame_ms=round(statistics.median(durations), 3),
                p95_frame_ms=round(ordered[math.ceil(.95 * len(ordered)) - 1], 3),
                max_frame_ms=round(ordered[-1], 3))


def presented_log(device, offset, count=2, timeout=10):
    """A live acknowledgement can precede Present; await its actual clocks."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        log = device.log()[offset:]
        clocks = list(CAMERA.finditer(log))
        if len(clocks) >= count and clocks[-1].start() > log.rfind("[live] camera "):
            return log
        time.sleep(.05)
    raise RuntimeError(f"requested {count} presentation clock records did not arrive before timeout")


def shader_stage_change(before, after):
    def last(log):
        values = re.findall(r"\[shaderwork\] stages=(\d+)", log)
        if not values:
            raise RuntimeError("native GL shader-stage counter is unavailable")
        return int(values[-1])
    start, end = last(before), last(after)
    if end < start:
        raise RuntimeError("native GL shader-stage counter reset during measurement")
    return dict(shader_stages_start=start, shader_stages_end=end, shader_stage_growth=end - start)


def script_warnings(log):
    groups = {}
    for clock, message in re.findall(r"^\S+ \[(\d+)\]: <Error> (.*)$", log, re.M):
        message = message.strip()
        if message.startswith("at "):
            continue  # Stack frames are context, not additional failures.
        groups.setdefault(message, []).append(int(clock))
    messages = []
    for message, clocks in groups.items():
        seconds = {}
        for clock in clocks:
            seconds[clock // 1000] = seconds.get(clock // 1000, 0) + 1
        messages.append(dict(message=message, count=len(clocks), first_ms=min(clocks), last_ms=max(clocks),
                             max_in_one_second=max(seconds.values())))
    return dict(total=sum(m["count"] for m in messages),
                execution_errors=sum(m["count"] for m in messages if "Error during execution of the script" in m["message"]),
                callback_errors=sum(m["count"] for m in messages if "Error during calling function of script" in m["message"]),
                messages=sorted(messages, key=lambda m: (-m["count"], m["message"])))


def append_helper(module, name, assembler):
    """Append callable code without changing inherited native method indices."""
    offset = len(module.code)
    module.code += assembler.finish(offset)
    if not hasattr(module, "_audit_helpers"):
        module._audit_helpers = {}
    assert name not in module._audit_helpers
    module._audit_helpers[name] = offset
    return offset


def attach_poller(module, bindings, guard=None, yield_hooks=True, tick=None):
    """QA-only keys run from real render/coroutine callbacks, not event guesses.

    A shared latch makes one press execute once even when several parallel
    contexts yield in the same frame. The trampoline uses a fresh register
    window and preserves every original instruction and branch destination.
    """
    original = list(module.instructions())
    latches = len(module.types)
    module.types += bytes([0] * (len(bindings) + (guard is not None)))
    a = Assembler(module)
    a.emit(0xffffffff, 0, 6)
    if tick is not None:
        a.emit(63, 3, tick)
    if guard is not None:
        a.emit(14, latches + len(bindings), 0)
        a.emit(56, 0, "guard_done")
        a.emit(0, 0, 1)
        a.emit(13, 0, latches + len(bindings))
        a.emit(63, 3, guard)
        a.label("guard_done")
    for i, (key, target) in enumerate(bindings):
        poll(a, key)
        a.emit(55, 0, f"released_{i}")
        a.emit(14, latches + i, 1)
        a.emit(56, 1, f"next_{i}")
        a.emit(0, 0, 1)
        a.emit(13, 0, latches + i)
        a.emit(63, 3, target)
        a.emit(54, 0, f"next_{i}")
        a.label(f"released_{i}")
        a.emit(0, 0, 0)
        a.emit(13, 0, latches + i)
        a.label(f"next_{i}")
    a.clear(0, 1, 2, 3, 4, 5)
    a.emit(65)
    callback = append_helper(module, "audit_poll", a)
    render_entries = {f["code_offset"] + 8 for c in module.contexts for f in c["methods"] if f["name"] == "render"}
    sites = []
    for i, row in enumerate(original):
        if not (yield_hooks and row.get("opcode") == 68) and row["offset"] not in render_entries:
            continue
        length = 0
        for stolen in original[i:]:
            assert not stolen.get("header")
            length += stolen["size"]
            if length >= 8:
                break
        assert not any(r.get("opcode") in (54, 55, 56) and row["offset"] < r["operands"][0] < row["offset"] + length for r in original)
        owner = next(r for r in reversed(original[:i]) if r.get("header"))
        base = owner["frame_slots"]
        module.code[owner["offset"] + 4:owner["offset"] + 8] = p32(base + 3)
        a = Assembler(module)
        a.emit(63, base, callback)
        a.clear(base, base + 1, base + 2)
        hook(module, row["offset"], a, length)
        sites.append(row["offset"])
    assert sites, "no original recurring callback found"
    return sites


def probe_script(data, case, helpers=None):
    """Read-only Sister query from real callbacks; no cross-context CALLs."""
    module = Module(data)
    name = case["name"]
    limfa = method(module, "getLimfa")
    a = Assembler(module)
    a.emit(0xffffffff, 0, 4)
    a.emit(63, 1, limfa)
    a.emit(20, 0)
    a.move(0, 1)
    a.string(0, "[scene-audit] girl=" + name + " limfa=")
    a.emit(36, 0)
    # The original game logger buffers roughly 4 KiB; force its previous lines
    # out before inspecting a disposable profile without changing its logger.
    a.string(1, " " + "." * 4096)
    a.emit(36, 0)
    a.move(0, 2)
    a.global_(1, "logInfo")
    a.native(0, 1)
    a.native(0, 1)
    a.clear(0, 1, 2)
    a.emit(65)
    bindings = [(0x64, append_helper(module, "audit_obscure", a))]
    attach_poller(module, bindings)
    if helpers is not None:
        helpers.update(module._audit_helpers)
    return module.encode()


def ui_feed_script(data, cases, helpers=None):
    """Use the original UI's public native OnGesture dispatch.

    A static scene onConsoleCommand CALL from gesture-help context uses the
    wrong external-variable binding. Native ScriptObject.call performs the
    original context dispatch. The runner opens the original donor heart first;
    onConsoleCommand is an event binding and is ignored by ScriptObject.call.
    """
    module = Module(data)
    rows = list(module.instructions())
    gesture = next(i for i, r in enumerate(rows) if r.get("text") == "OnGesture")
    scene_slot = next(r["register"] for r in reversed(rows[:gesture]) if r.get("opcode") == 14)
    init = method(module, "initObscure")
    name_read = next(i for i, r in enumerate(rows) if r["offset"] > init and r.get("opcode") == 10 and r["register"] == -7)
    name_store = rows[name_read + 1]
    assert name_store["opcode"] == 13 and name_store["register"] == rows[name_read]["operands"][0]
    name_slot = name_store["operands"][0]
    world_read = next(i for i, r in enumerate(rows) if r["offset"] > init and r.get("opcode") == 10 and r["register"] == -8)
    world_slot = rows[world_read + 1]["operands"][0]
    # The scene's dialogue coroutine can become quiescent while idle. Query
    # the real Girl entity and the UI's original dynamic IsActive getter from
    # this continuously rendered UI instead of depending on a scene yield.
    a = Assembler(module)
    a.emit(0xffffffff, 0, 11)
    a.emit(14, world_slot, 2)
    a.member(1, "call")
    a.string(2, "getGirlEntityByName")
    a.emit(14, name_slot, 3)
    a.native(0, 2)
    a.clear(1, 2, 3)
    a.move(0, 3)
    a.member(2, "Properties")
    a.string(3, "limfa")
    a.emit(58, 1, 1)
    a.emit(16, 1)
    a.move(1, 8)
    a.clear(0, 1, 2, 3)
    a.global_(2, "self")
    a.member(1, "callDef")
    a.emit(0, 2, 0)
    a.string(3, "IsActive")
    a.native(0, 2)
    a.emit(16, 0)
    a.move(0, 9)
    a.clear(0, 1, 2, 3)
    a.emit(14, world_slot, 2)
    a.member(1, "call")
    a.string(2, "isGestureActive")
    a.integer(3, 1)
    a.native(0, 2)
    a.emit(16, 0)
    a.move(0, 10)
    a.clear(0, 1, 2, 3)
    a.string(0, "[scene-audit] girl=")
    a.emit(14, name_slot, 1)
    a.emit(36, 0)
    for label, slot in ((" limfa=", 8), (" ready=", 9), (" donor=", 10)):
        a.string(1, label)
        a.emit(36, 0)
        a.move(slot, 1)
        a.emit(20, 1)
        a.emit(36, 0)
    a.string(1, " " + "." * 4096)
    a.emit(36, 0)
    a.move(0, 2)
    a.global_(1, "logInfo")
    a.native(0, 1)
    a.native(0, 1)
    a.clear(*range(11))
    a.emit(65)
    bindings = [(0x64, append_helper(module, "audit_ui_state", a))]
    for stage in range(1, 5):
        a = Assembler(module)
        a.emit(0xffffffff, 0, 8)
        a.emit(14, name_slot, 0)
        a.emit(20, 0)
        a.move(0, 1)
        a.string(0, f"[scene-audit] ui_feed stage={stage} girl=")
        a.emit(36, 0)
        a.string(1, " " + "." * 4096)
        a.emit(36, 0)
        a.move(0, 2)
        a.global_(1, "logInfo")
        a.native(0, 1)
        a.native(0, 1)
        a.clear(0, 1, 2)
        for case in cases:
            name = case["name"]
            a.emit(14, name_slot, 0)
            a.string(1, name)
            a.emit(46, 0)
            a.emit(55, 0, "next_" + name)
            a.emit(14, scene_slot, 2)
            a.member(1, "call")
            a.string(2, "OnGesture")
            a.integer(3, 1)
            a.integer(4, case["good_colour"])
            float_(a, 5, case["stage_donations"][stage - 1] * 1000)
            a.native(0, 4)
            a.global_(1, "logInfo")
            a.string(2, f"[scene-audit] ui_feed stage={stage} dispatched={name} " + "." * 4096)
            a.native(0, 1)
            a.native(0, 1)
            a.emit(54, 0, "done")
            a.label("next_" + name)
        a.label("done")
        a.clear(0, 1, 2, 3, 4, 5, 6, 7)
        a.emit(65)
        bindings.append((0x64 + stage, append_helper(module, "audit_feed" + str(stage), a)))
    attach_poller(module, bindings)
    if helpers is not None:
        helpers.update(module._audit_helpers)
    return module.encode()


def guard_script(data):
    """Intercept one explicit command through the original bound dispatcher.

    Keep every context, method, variable and original frame size unchanged.
    The guard can execute only after the live runner requests /audit_guard.
    """
    module = Module(data)
    entry = method(module, "onConsoleCommand") + 8
    a = Assembler(module)
    a.move(-5, 0)
    a.string(1, "audit_guard")
    a.emit(46, 0)
    a.emit(55, 0, "original")
    a.emit(0, 0, 1)
    a.global_(2, "World")
    a.member(1, "Vars")
    a.string(2, "god_mode")
    a.emit(59, 1, 1)
    a.clear(0, 1, 2)
    a.global_(1, "logInfo")
    a.string(2, "[scene-audit] World.Vars.god_mode=1 " + "." * 4096)
    a.native(0, 1)
    a.native(0, 1)
    a.clear(0, 1, 2)
    a.emit(0, 0, 1)
    a.move(0, -6)
    a.clear(0)
    a.emit(65)
    a.label("original")
    a.clear(0, 1)
    hook(module, entry, a)
    return module.encode()


def hunter_probe_script(data, case, helpers=None):
    module = Module(data)
    pending_slot = len(module.types)
    module.types += bytes([1])  # QA request only; never a game HP/stage/gate.
    a = Assembler(module)
    a.emit(0xffffffff, 0, 6)
    a.string(0, "[scene-audit] hunter=" + case["name"])
    for field, getter in (("stage", "getHunterStage"), ("hp", "getHunterHP"), ("max_stage", "getHunterMaxStage"),
                          ("vulnerable", "isHunterVulnerable")):
        a.string(1, " " + field + "=")
        a.emit(36, 0)
        a.emit(63, 3, method(module, getter))
        if field == "vulnerable":
            a.emit(16, 2)
        a.emit(20, 2)
        a.move(2, 1)
        a.emit(36, 0)
        a.clear(1, 2, 3, 4, 5)
    a.string(1, " pending=")
    a.emit(36, 0)
    a.emit(14, pending_slot, 2)
    a.emit(20, 2)
    a.move(2, 1)
    a.emit(36, 0)
    a.clear(1, 2)
    a.string(1, " " + "." * 4096)
    a.emit(36, 0)
    a.move(0, 2)
    a.global_(1, "logInfo")
    a.native(0, 1)
    a.native(0, 1)
    a.clear(0, 1, 2)
    a.emit(65)
    bindings = [(0x64, append_helper(module, "audit_hunter", a))]
    # A press can land outside an authored vulnerability window. Retain the
    # QA request, then use the original damage path on the first real window.
    a = Assembler(module)
    a.emit(0xffffffff, 0, 6)
    a.emit(14, pending_slot, 0)
    a.integer(1, 0)
    a.emit(46, 0)
    a.emit(56, 0, "done")
    a.emit(63, 1, method(module, "getHunterStage"))
    a.emit(14, pending_slot, 1)
    a.integer(2, 2)
    a.emit(37, 1)
    a.emit(46, 0)
    a.emit(55, 0, "clear_request")
    a.emit(63, 1, method(module, "isHunterVulnerable"))
    a.emit(55, 0, "done")
    a.integer(0, 0)
    a.integer(1, 100000000)
    a.emit(63, 2, method(module, "damageHunter"))
    a.emit(63, 1, method(module, "getHunterStage"))
    a.emit(14, pending_slot, 1)
    a.integer(2, 2)
    a.emit(37, 1)
    a.emit(46, 0)
    a.emit(56, 0, "done")
    a.emit(63, 1, method(module, "getHunterStage"))
    a.integer(1, case["phase_count"])
    a.emit(46, 0)
    a.emit(55, 0, "clear_request")
    # Death proof must precede the original AI's deferred actor destruction.
    a.emit(63, 3, bindings[0][1])
    a.label("clear_request")
    a.integer(0, 0)
    a.emit(13, 0, pending_slot)
    a.label("done")
    a.clear(*range(6))
    a.emit(65)
    service = append_helper(module, "audit_hunter_pending", a)
    # The original damage path clamps each hit at the current phase boundary
    # and raises its transition flag; setHunterHealth alone skips that flag.
    for phase in range(2, case["phase_count"] + 1):
        a = Assembler(module)
        a.emit(0xffffffff, 0, 6)
        a.emit(63, 1, method(module, "getHunterStage"))
        a.integer(1, phase - 2)
        a.emit(46, 0)
        a.emit(55, 0, "done")
        a.integer(0, phase)
        a.emit(13, 0, pending_slot)
        a.emit(63, 3, service)
        a.label("done")
        a.clear(0, 1, 2, 3, 4, 5)
        a.emit(65)
        bindings.append((0x63 + phase, append_helper(module, "audit_hunter_phase" + str(phase), a)))
    # F17 is independent of the number of living phases. Only the final living
    # phase can take this original lethal hit; the real AI owns its aftermath.
    a = Assembler(module)
    a.emit(0xffffffff, 0, 6)
    a.emit(63, 1, method(module, "getHunterStage"))
    a.integer(1, case["phase_count"] - 1)
    a.emit(46, 0)
    a.emit(55, 0, "done")
    a.integer(0, case["phase_count"] + 1)
    a.emit(13, 0, pending_slot)
    a.emit(63, 3, service)
    a.label("done")
    a.clear(0, 1, 2, 3, 4, 5)
    a.emit(65)
    bindings.append((0x68, append_helper(module, "audit_hunter_defeat", a)))
    attach_poller(module, bindings, tick=service)
    if helpers is not None:
        helpers.update(module._audit_helpers)
    return module.encode()


def final_probe_script(data, helpers=None):
    """F13 invokes the original public final-UI callback through native self."""
    module = Module(data)
    method(module, "onBreakthrough")
    a = Assembler(module)
    a.emit(0xffffffff, 0, 6)
    a.global_(2, "self")
    a.member(1, "call")
    a.string(2, "onBreakthrough")
    a.native(0, 1)
    a.clear(0, 1, 2)
    a.global_(1, "logInfo")
    a.string(2, "[scene-audit] original final onBreakthrough dispatched " + "." * 4096)
    a.native(0, 1)
    a.native(0, 1)
    a.clear(0, 1, 2, 3, 4, 5)
    a.emit(65)
    target = append_helper(module, "audit_breakthrough", a)
    attach_poller(module, [(0x64, target)])
    if helpers is not None:
        helpers.update(module._audit_helpers)
    return module.encode()


def export_probes(out, manifest):
    patches = json.loads((ROOT / "build/overrides/index.json").read_text(encoding="utf-8"))
    for case in manifest["cases"]:
        if case["kind"] not in ("sister", "battle"):
            continue
        name = case["name"]
        path = "Scripts\\scene\\obscure_" + name + ".bin" if case["kind"] == "sister" else case["hunter_script"].replace("/", "\\")
        source = next((p for p in patches if p["path"] == path and p["index"] == INDEX), None)
        data = (ROOT / "build/overrides" / source["file"]).read_bytes() if source else read_entry(INDEX, path)
        if source:
            assert hashlib.sha256(data).hexdigest() == source["sha256"]
        target = out / path.replace("\\", "/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(probe_script(data, case) if case["kind"] == "sister" else hunter_probe_script(data, case))
    source = next(p for p in patches if p["path"] == "Scripts\\world\\world.bin" and p["index"] == INDEX)
    target = out / "Scripts/world/world.bin"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(guard_script((ROOT / "build/overrides" / source["file"]).read_bytes()))
    source = next(p for p in patches if p["path"] == "Scripts\\ui\\obscure.bin" and p["index"] == INDEX)
    target = out / "Scripts/ui/obscure.bin"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(ui_feed_script((ROOT / "build/overrides" / source["file"]).read_bytes(),
                                     [c for c in manifest["cases"] if c["kind"] == "sister"]))
    path = "Scripts\\ui\\obscure_final.bin"
    source = next((p for p in patches if p["path"] == path and p["index"] == INDEX), None)
    data = (ROOT / "build/overrides" / source["file"]).read_bytes() if source else read_entry(INDEX, path)
    (out / "Scripts/ui/obscure_final.bin").write_bytes(final_probe_script(data))


def observed_stage(log, case):
    rows = re.findall(r"\[scene-audit\] girl=" + re.escape(case["name"]) + r" limfa=(\d+)", log)
    if not rows:
        raise RuntimeError("read-only audit_obscure probe absent or scene not active")
    amount, total, stage = int(rows[-1]), 0, 0
    for limit in case["stage_donations"]:
        total += limit * 1000
        if amount < total:
            break
        stage += 1
    return dict(stage=stage, girl_limfa=amount)


def observed_ui_state(log, case):
    rows = re.findall(r"\[scene-audit\] girl=" + re.escape(case["name"]) + r" limfa=(\d+) ready=([01]) donor=([01])", log)
    if not rows:
        raise RuntimeError("original UI amount/readiness query did not run")
    amount, ready, donor = map(int, rows[-1])
    return dict(observed_stage(f"[scene-audit] girl={case['name']} limfa={amount}", case), ready=bool(ready), donor_active=bool(donor))


def wait_sister_ready(device, case, timeout, require_ready=True):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        before = len(device.game_log())
        device.status(["key 7c", "sleep 0.3"])
        try:
            state = observed_ui_state(device.game_log()[before:], case)
        except RuntimeError:
            # A newly encountered shader can block the script frame through
            # the entire native key pulse. Retry the read-only query after it
            # resumes; an absent query is not evidence of a girl-stage value.
            time.sleep(.5)
            continue
        if state["ready"] or not require_ready:
            return state
        # The original Next action advances spoken lines; it does not replace
        # the dancer/level-up state or write any Girl stage variables.
        device.status(["key 0d", "sleep 0.4"])
    raise RuntimeError("Sister UI did not finish its dialogue/dance and become active")


def observed_hunter(log, case):
    rows = re.findall(r"\[scene-audit\] hunter=" + re.escape(case["name"]) + r" stage=(\d+) hp=(\d+) max_stage=(\d+)", log)
    if not rows:
        raise RuntimeError("hunter probe absent or no active original hunter actor")
    stage, hp, count = map(int, rows[-1])
    if count != case["phase_count"] or hp <= 0 or stage >= count:
        raise RuntimeError(f"unexpected hunter state: stage={stage}, hp={hp}, max_stage={count}")
    return dict(phase=stage + 1, actor_stage=stage, hp=hp, max_stage=count)


def query_hunter(device, case, timeout=30):
    """Retry only the read-only query when loading misses a short key pulse."""
    before = len(device.game_log())
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        device.status(["key 7c", "sleep 0.3"])
        fresh = device.game_log()[before:]
        if "[scene-audit] hunter=" + case["name"] + " " in fresh:
            return observed_hunter(fresh, case)
    raise RuntimeError("hunter probe absent after bounded read-only retries")


def screenshot_content(data):
    from PIL import Image, ImageStat
    image = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = image.size
    centre = image.crop((w // 5, h // 5, 4 * w // 5, 4 * h // 5))
    mean = sum(ImageStat.Stat(centre).mean) / 3
    black = sum(max(pixel) <= 2 for pixel in centre.get_flattened_data()) / (centre.width * centre.height)
    return dict(width=w, height=h, centre_mean_rgb=round(mean, 3), centre_black_fraction=round(black, 6),
                centre_has_rendered_content=black < .999)


class Device:
    def __init__(self, serial, profile, incremental_logs=False):
        if not re.fullmatch(r"userdata-[A-Za-z0-9_]+", profile):
            raise ValueError("use an isolated userdata-NAME profile")
        self.adb = ["adb", "-s", serial]
        self.remote = "/sdcard/TheVoid/" + profile
        self.counter = time.time_ns() % 1000000000
        self.incremental_logs = incremental_logs
        self._log_cache = {}

    def shell(self, command):
        return self.read_output([*self.adb, "shell", command]).decode("utf-8", "replace").replace("\r", "")

    def read_output(self, command, timeout=40):
        """Retry transport failures only for reads; never replay live actions."""
        for attempt in range(3):
            try:
                return subprocess.check_output(command, timeout=timeout, stderr=subprocess.PIPE)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                detail = (error.stderr or b"").decode("utf-8", "replace").strip()
                print(f"ADB read failed ({attempt + 1}/3): {command!r}: {error}; stderr={detail!r}", file=sys.stderr, flush=True)
                if attempt == 2:
                    raise
                time.sleep(.25)

    def log(self):
        return self._read_log(self.remote + "/void.log")

    def game_log(self):
        return self._read_log(self.remote + "/Documents/My Games/Turgor/LogFiles/game.log")

    def _read_log(self, path):
        if not self.incremental_logs:
            return self.shell("cat " + shlex.quote(path))
        # A CLI run never restarts the app or truncates these logs. Fetch only
        # appended bytes over USB; repeated 4 KiB proof records otherwise make
        # an hour-long audit transfer the entire growing log on every poll.
        previous = self._log_cache.get(path, b"")
        command = f"tail -c +{len(previous) + 1} " + shlex.quote(path)
        # `adb shell` on this device expands LF to CRLF. Offsets must count
        # actual file bytes, so use the raw exec-out transport for each tail.
        chunk = self.read_output([*self.adb, "exec-out", command])
        self._log_cache[path] = previous + chunk
        return codecs.utf_8_decode(self._log_cache[path], "replace", False)[0].replace("\r", "")

    def live(self, lines):
        subprocess.run([*self.adb, "shell", "cat >> " + self.remote + "/live.txt"],
                       input=("\n".join(lines) + "\n").encode(), check=True, timeout=20)

    def status(self, lines=(), timeout=35):
        self.counter += 1
        token = self.counter
        self.live([*lines, "hud", f"move 0 0 {token}"])
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            log = self.shell("tail -200 " + self.remote + "/void.log")
            status = marker_status(log, token)
            if status:
                return status
            if not self.shell("pidof org.thevoid.port || true").strip():
                raise RuntimeError("game process exited")
            time.sleep(.3)
        raise RuntimeError("live input queue did not finish before timeout")

    def screenshot(self, path):
        data = self.read_output([*self.adb, "exec-out", "screencap", "-p"], timeout=30)
        path.write_bytes(data)
        return screenshot_content(data)


def wait_scene(device, case, offset, game_offset, timeout):
    deadline = time.monotonic() + timeout
    body_returns = 0
    while time.monotonic() < deadline:
        state = device.status(timeout=min(timeout, 35))
        log, game = device.log()[offset:], device.game_log()[game_offset:]
        if case.get("conversation") or case["kind"] == "brother":
            # Original untouched scripts are not printed by the override-file
            # logger. Require their actual live room through original /views.
            views, state = read_views(device)
            scene = case.get("conversation_scene", case["scene"])
            proof = bool(view_count(views, scene))
            ready = not state["tags"] & (0x400 | 0x1000 | HUD_LOADING | 0x300000 | 0x1000000)
        elif case["kind"] == "extra":
            proof = case["scene"].lower() in game.replace("\\", "/").lower()
            ready = not state["tags"] & (HUD_BLOCKED | HUD_CONTROL_LOCKED)
            if not proof:
                device.status(["console /views", "sleep 0.3", "console /audit_guard", "sleep 0.3"])
        elif case["kind"] == "location":
            proof = accepted_location(log, case["location"])
            ready = not state["tags"] & (HUD_BLOCKED | HUD_CONTROL_LOCKED)
        elif case["kind"] == "sister":
            proof = re.search(re.escape(case["proof"]) + r"(?:\s|$)", game) is not None
            proof = proof or ("Scripts/scene/obscure_" + case["name"] + ".bin") in log.replace("\\", "/")
            ready = bool(state["tags"] & 0x8000) and not state["tags"] & (HUD_LOADING | 0x300000)
        else:
            proof = case["proof"] in game and "arena_general.sc: initialising completed successfully." in game
            if not proof:
                # Quiet arenas may leave their final initialization record in
                # the original logger's 4 KiB buffer. The read-only actor
                # query flushes it once the actual hunter starts rendering.
                state = device.status(["key 7c", "sleep 0.2"])
                game = device.game_log()[game_offset:]
                proof = case["proof"] in game and "arena_general.sc: initialising completed successfully." in game
            ready = not state["tags"] & (HUD_BLOCKED | HUD_CONTROL_LOCKED)
            if proof and state["tags"] & 0x1000 and state["tags"] & 0x8000000 and body_returns < 2:
                device.status(["key 1b", "sleep 0.5"])
                body_returns += 1
                continue
        if proof and ready:
            return state
        if case["kind"] == "battle" and not proof:
            device.status(["key 0d", "sleep 0.3"])
        else:
            time.sleep(.5)
    raise RuntimeError("requested scene did not become ready: " + case["id"])


def measure_scene(device, case, out, seconds, timeout, sensitivity, suffix=""):
    seconds = max(seconds, 30) if case["kind"] == "battle" and not suffix else seconds
    row = {}
    for attempt in range(3):
        device.status()
        baseline = device.log()
        measured_from = len(baseline)
        game_from = len(device.game_log())
        turn = case["kind"] in ("location", "extra") and not case.get("conversation")
        events = turn_events(seconds, sensitivity) if turn else [f"sleep {seconds}"]
        state = device.status(["camera 1", "sleep 0.1", *events, "camera 1", "sleep 0.2"], timeout=seconds + timeout)
        measured = presented_log(device, measured_from)
        state = device.status()
        stage_change = shader_stage_change(baseline, device.log()[measured_from:])
        if case.get("conversation") or case["kind"] == "brother":
            if state["tags"] & (0x400 | 0x1000 | HUD_LOADING | 0x300000 | 0x1000000):
                raise RuntimeError("Brother conversation measurement left the dialogue")
        elif case["kind"] in ("location", "battle", "extra"):
            if any(int(h[2], 16) & HUD_BLOCKED for h in HUD.finditer(measured)):
                raise RuntimeError("measurement entered loading, an inventory, a menu or another scene")
        elif state["tags"] & (0x400 | 0x1000000 | HUD_LOADING | 0x300000 | 0x800000):
            raise RuntimeError("Sister measurement left the obscura")
        if SHADER_WORK.search(measured) or stage_change["shader_stage_growth"]:
            continue
        row.update(full_turn_rate(measured), preparation_retries=attempt, **stage_change)
        row["end_hud"] = state["tags"]
        break
    else:
        raise RuntimeError("scene still preparing shaders after three measurement windows")
    for timing_attempt in range(3):
        timing_baseline = device.log()
        timed_from = len(timing_baseline)
        device.status(["camera 121"], timeout=timeout)
        timed = presented_log(device, timed_from, count=121, timeout=min(timeout, 45))
        device.status()
        timing_stages = shader_stage_change(timing_baseline, device.log()[timed_from:])
        if not SHADER_WORK.search(timed) and not timing_stages["shader_stage_growth"]:
            break
    else:
        raise RuntimeError("shader preparation interrupted three frame timing samples")
    row.update(frame_times(timed))
    row["timing_shader_stages"] = timing_stages
    row["timing_preparation_retries"] = timing_attempt
    row.update(device.screenshot(out / (case["id"] + suffix + ".png")))
    if not row["centre_has_rendered_content"]:
        raise RuntimeError("scene centre is black; screenshot needs review")
    row["render_errors"] = GPU_ERROR.findall(measured + timed)
    if case["kind"] in ("sister", "battle"):
        # A read-only actor query also flushes the original buffered logger.
        # This is after both timing windows and the screenshot.
        device.status(["key 7c", "sleep 0.2"])
    row["script_warnings"] = script_warnings(device.game_log()[game_from:])
    row["script_failed"] = row["script_warnings"]["execution_errors"] > 0
    return row


def load_map(device, save, timeout):
    deadline = time.monotonic() + timeout
    submitted = device.status(["console /load " + save])
    # The console acknowledgement precedes the asynchronous save load. HUD
    # snapshots can still describe the previous map while its frame is blocked.
    # Let loading start, then require actual presentation progress before using
    # the new map's script dispatcher.
    device.status(["sleep 3"])
    reached_map = False
    while time.monotonic() < deadline:
        state = device.status()
        if (state["frame"] > submitted["frame"] + 1 and state["tags"] & (0x400 | 0x1000000)
                and not state["tags"] & HUD_LOADING):
            reached_map = True
            before = len(device.game_log())
            device.status(["console /audit_guard", "sleep 0.5"])
            if "[scene-audit] World.Vars.god_mode=1" in device.game_log()[before:]:
                return
            # A command queued on the final loading tick can be discarded by
            # the original dispatcher; retry only after another ready snapshot.
        time.sleep(.5)
    if not reached_map:
        raise RuntimeError("copied base save did not reach the map")
    raise RuntimeError("original-world survival guard probe did not run; push probes after launch while still at the main menu, before loading the copied save")


def measure_aftermath(device, case, out, timeout):
    """Observe original death effects separately from every living AI phase."""
    baseline = device.log()
    before, game_before = len(baseline), len(device.game_log())
    started = time.monotonic()
    deadline = started + min(timeout, 180 if case.get("vulnerability_windows") else 30)
    retreated = False
    relocations = []
    next_relocation = started + 20
    proof = re.compile(r"\[scene-audit\] hunter=" + re.escape(case["name"]) +
                       rf" stage={case['phase_count']} hp=0 max_stage={case['phase_count']}(?:\s|$)")
    while time.monotonic() < deadline:
        device.status(["key 80", "sleep 0.5"])
        if proof.search(device.game_log()[game_before:]):
            break
        if case.get("arena_setup_point") and time.monotonic() >= next_relocation:
            relocations.append(prepare_battle_view(device, case, device.audit_sensitivity, alternate=True))
            next_relocation = time.monotonic() + 20
        if case["name"] == "stiltman" and not case.get("arena_setup_point") and not retreated and time.monotonic() - started > 8:
            device.status(["down 53", "sleep 3", "up 53", "sleep 1"])
            retreated = True
    else:
        raise RuntimeError("original final-phase damage did not prove hunter death")
    measured_from = len(device.log())
    state = device.status(["camera 1", "sleep 10", "camera 1", "sleep 0.2"], timeout=timeout)
    measured = presented_log(device, measured_from)
    stages = shader_stage_change(baseline, device.log()[before:])
    row = dict(actor_stage=case["phase_count"], hp=0, original_death_verified=True,
               end_hud=state["tags"], ordinary_retreat_used=retreated,
               arena_relocations=relocations,
               shaders_prepared_during_aftermath=bool(SHADER_WORK.search(device.log()[before:])) or bool(stages["shader_stage_growth"]),
               **stages)
    row.update(full_turn_rate(measured))
    row.update(device.screenshot(out / (case["id"] + "-aftermath.png")))
    row["render_errors"] = GPU_ERROR.findall(device.log()[before:])
    row["script_warnings"] = script_warnings(device.game_log()[game_before:])
    return row


def view_count(log, scene):
    rows = re.findall(re.escape(scene.replace("\\", "/").lower()) + r"\s*:\s*(\d+) view\(s\)",
                      log.replace("\\", "/").lower())
    return int(rows[-1]) if rows else 0


def read_views(device):
    before = len(device.game_log())
    state = device.status(["console /views", "sleep 0.2", "console /audit_guard", "sleep 0.2"])
    return device.game_log()[before:], state


def wait_view(device, scene, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        log, state = read_views(device)
        if view_count(log, scene):
            return state
        time.sleep(.5)
    raise RuntimeError("original /views did not show a live view of " + scene)


def wait_cinematic_end(device, former_scene, endpoint, timeout):
    """Keep original movies running through their late effects and return."""
    deadline = time.monotonic() + timeout
    offset = len(device.game_log())
    while time.monotonic() < deadline:
        # Credits have their own World script and no QA guard. Plain /views
        # remains an original read-only dispatcher in both World classes.
        state = device.status([line for _ in range(8) for line in ("console /views", "sleep 0.05")])
        log = device.game_log()
        fresh, offset = log[offset:], len(log)
        if view_count(fresh, endpoint) and not view_count(fresh, former_scene):
            return state
    raise RuntimeError(f"original cinematic did not naturally return from {former_scene} to {endpoint}")


def run_cinematic(device, case, out, seconds, timeout, save):
    """Render source-backed movies with original camera/control locks intact."""
    before, game_before = len(device.log()), len(device.game_log())
    row = dict(case=case["id"], kind="cinematic", scene=case["scene"],
               route=["/load " + save, *case["commands"]], phases=[])
    try:
        load_map(device, save, timeout)
        for command in case["commands"]:
            device.status(["console " + command, "sleep 0.4"])
        for index, scene in enumerate(case["scenes_in_order"]):
            wait_view(device, scene, timeout)
            phase = dict(scene=scene, live_view_verified=True)
            for attempt in range(16):
                capture = device.screenshot(out / f"{case['id']}-phase{index + 1}-start.png")
                if capture["centre_has_rendered_content"]:
                    break
                device.status(["sleep 0.5"])
            phase.update(capture)
            if not capture["centre_has_rendered_content"]:
                raise RuntimeError("cinematic remains black after its initial fade: " + scene)
            baseline = device.log()
            measured_from = len(baseline)
            state = device.status(["camera 1", f"sleep {seconds}", "camera 1", "sleep 0.2"], timeout=timeout)
            measured = presented_log(device, measured_from)
            views, _ = read_views(device)
            stages = shader_stage_change(baseline, device.log()[measured_from:])
            phase.update(full_turn_rate(measured), end_hud=state["tags"],
                         shaders_prepared=bool(SHADER_WORK.search(measured)) or bool(stages["shader_stage_growth"]),
                         render_errors=GPU_ERROR.findall(measured), **stages)
            phase["same_scene_at_window_end"] = bool(view_count(views, scene))
            phase["window_includes_authored_transition"] = not phase["same_scene_at_window_end"]
            row["phases"].append(phase)
            if index == 0 and case.get("original_breakthrough"):
                query_from = len(device.game_log())
                for attempt in range(12):
                    device.status(["key 7c", "sleep 0.5"])
                    if "[scene-audit] original final onBreakthrough dispatched" in device.game_log()[query_from:]:
                        break
                else:
                    raise RuntimeError("original final-UI onBreakthrough callback was not dispatched")
                row["original_breakthrough_dispatched"] = True
            # Remaining phases advance through their actual camera/music
            # completion. No timescale changes or synthetic stage variables.
        baseline = device.log()
        completion_from = len(baseline)
        device.status(["camera 1", "sleep 0.1"])
        state = wait_cinematic_end(device, case["scenes_in_order"][-1], case["completion_scene"], timeout)
        device.status(["camera 1", "sleep 0.2"])
        completion_log = presented_log(device, completion_from)
        device.status()
        stages = shader_stage_change(baseline, device.log()[completion_from:])
        row["natural_completion"] = dict(endpoint=case["completion_scene"], original_return_verified=True,
                                         former_view_gone=True, end_hud=state["tags"],
                                         **full_turn_rate(completion_log), **stages,
                                         shaders_prepared=bool(SHADER_WORK.search(completion_log)) or bool(stages["shader_stage_growth"]))
        row["natural_completion"].update(device.screenshot(out / (case["id"] + "-completed.png")))
        row["status"] = "measured"
        row["requested_scene_verified"] = True
    except (RuntimeError, subprocess.SubprocessError) as error:
        row.update(status="unmeasured", error=str(error))
        try:
            row.update(device.screenshot(out / (case["id"] + "-failed.png")))
        except subprocess.SubprocessError:
            pass
    native, game = device.log()[before:], device.game_log()[game_before:]
    row["render_errors"] = GPU_ERROR.findall(native)
    row["compiler_rejections"] = EXPECTED_COMPILER_REJECTION.findall(native)
    row["case_script_warnings"] = script_warnings(game)
    if row["status"] == "measured" and (row["render_errors"] or row["case_script_warnings"]["execution_errors"]):
        row["status"] = "render-error" if row["render_errors"] else "script-error"
    (out / (case["id"] + ".log")).write_text(native, encoding="utf-8")
    (out / (case["id"] + "-game.log")).write_text(game, encoding="utf-8")
    return row


def prepare_battle_view(device, case, sensitivity, alternate=False):
    """Use an original arena locator, leaving authored AI/damage gates intact."""
    point = case.get("arena_setup_point")
    if not point:
        return None
    # The shipped flache arena puts this grounded point far from pt_hunter.
    # Its initial player yaw faces along +Z. Turn toward the arena centre
    # after the original gopt command, so the encounter remains in view.
    previous = getattr(device, "audit_arena_point", None) if alternate else None
    if alternate and previous == "pt_driller_4":
        point, position = "pt_driller_0", [-32, 0, 24]
    else:
        position = [51.8532, 0, 13.3423]
    target_yaw = -math.degrees(math.atan2(position[0], -position[2]))
    old_yaw = getattr(device, "audit_arena_yaw", 0) if alternate else 0
    degrees = (target_yaw - old_yaw + 180) % 360 - 180
    pixels = round(degrees * PIXELS_PER_DEGREE / sensitivity)
    device.status(["console /gopt " + point, "sleep 0.5", f"move {pixels} 0", "sleep 0.5"])
    device.audit_arena_point, device.audit_arena_yaw = point, target_yaw
    return dict(original_command="/gopt " + point, grounded_locator=position,
                mouse_pixels=pixels, calibrated_turn_degrees=pixels * sensitivity / PIXELS_PER_DEGREE,
                purpose="allow original limpha collection beyond close-attack distance, with the arena centre in view")


def run_case(device, case, out, seconds, timeout, sensitivity, save, sister_stages=False, aftermath=False):
    before = len(device.log())
    game_before = len(device.game_log())
    row = dict(case=case["id"], kind=case["kind"], scene=case["scene"], route=["/load " + save, *case.get("preparation_commands", []), *case["commands"]])
    try:
        load_map(device, save, timeout)
        # Keep routing commands apart: the original console runs one command per tick.
        for command in [*case.get("preparation_commands", []), *case["commands"]]:
            device.status(["console " + command, "sleep 0.4"])
        if case.get("conversation"):
            deadline = time.monotonic() + timeout
            while not accepted_location(device.log()[before:], case["location"]):
                if time.monotonic() >= deadline:
                    raise RuntimeError("original map node was not accepted")
                time.sleep(.3)
            load_map(device, save, timeout)
            for command in case["conversation_commands"]:
                device.status(["console " + command, "sleep 0.4"])
            row["route"] += ["/load " + save, *case["conversation_commands"]]
        state = wait_scene(device, case, before, game_before, timeout)
        row["requested_scene_verified"] = True
        if case.get("conversation") or case["kind"] == "brother":
            row["rendered_scene"] = case.get("conversation_scene", case["scene"])
        if case["kind"] == "battle":
            device.audit_sensitivity = sensitivity
            initial_hunter = query_hunter(device, case, min(30, timeout))
            if initial_hunter["phase"] != 1:
                raise RuntimeError("battle did not start at the first authored HP phase")
            setup = prepare_battle_view(device, case, sensitivity)
            if setup:
                row["arena_setup"] = setup
        row.update(measure_scene(device, case, out, seconds, timeout, sensitivity))
        if case["kind"] == "battle":
            row["phases"] = [dict(initial_hunter, **{k: v for k, v in row.items() if k in ("full_turn_fps", "p95_frame_ms", "median_frame_ms", "script_warnings", "script_failed")})]
            for phase in range(2, case["phase_count"] + 1):
                phase_from = len(device.game_log())
                phase_started = time.monotonic()
                deadline = phase_started + min(timeout, 180 if case.get("vulnerability_windows") else 30)
                retreated = False
                next_relocation = phase_started + 20
                while time.monotonic() < deadline:
                    device.status([f"key {0x7b + phase:x}", "sleep 1"])
                    observed = query_hunter(device, case, min(30, timeout))
                    if observed["phase"] == phase:
                        break
                    if observed["phase"] > phase:
                        raise RuntimeError("original damage unexpectedly skipped a hunter phase")
                    if case.get("arena_setup_point") and time.monotonic() >= next_relocation:
                        row.setdefault("phase_setup_inputs", []).append(dict(phase=phase, **prepare_battle_view(device, case, sensitivity, alternate=True)))
                        next_relocation = time.monotonic() + 20
                    if case["name"] == "stiltman" and not case.get("arena_setup_point") and not retreated and time.monotonic() - phase_started > 8:
                        # Its original close-attack branch precedes limpha
                        # collection, which opens vulnerability. Retreat with
                        # the ordinary bound S key; never force that AI gate.
                        device.status(["down 53", "sleep 3", "up 53", "sleep 1"])
                        row.setdefault("phase_setup_inputs", []).append(dict(phase=phase, key="S", action="retreat", seconds=3))
                        retreated = True
                else:
                    raise RuntimeError(f"original hunter damage did not advance to phase {phase}")
                device.status(["sleep 2"])
                phase_row = dict(observed, **measure_scene(device, case, out, max(10, min(15, seconds)), timeout,
                                                          sensitivity, f"-phase{phase}"))
                if query_hunter(device, case, min(30, timeout))["phase"] != phase:
                    raise RuntimeError("hunter left the measured HP phase")
                row["phases"].append(phase_row)
            if aftermath:
                row["aftermath"] = measure_aftermath(device, case, out, timeout)
        if sister_stages and case["kind"] == "sister":
            observed = wait_sister_ready(device, case, timeout)
            if observed["stage"] != 0:
                raise RuntimeError(f"base save starts {case['name']} at stage {observed['stage']}; stage 0 needs a fresh girl")
            row["stages"] = [dict(observed, **{k: v for k, v in row.items() if k in ("full_turn_fps", "p95_frame_ms", "median_frame_ms", "script_warnings", "script_failed")})]
            for target in range(1, 5):
                if target > 1:
                    previous = wait_sister_ready(device, case, timeout)
                    if previous["stage"] != target - 1:
                        raise RuntimeError("Sister stage changed while finishing the previous conversation")
                donation = case["stage_donations"][target - 1]
                device.status([f"console /add_al {case['good_colour']} {donation * 2}", "sleep 0.2"])
                transition_baseline = device.log()
                transition_from = len(transition_baseline)
                stage_from = len(device.game_log())
                device.status(["camera 1", f"key {0x7c + target:x}", "sleep 1"])
                observed = wait_sister_ready(device, case, timeout)
                device.status(["camera 1", "sleep 0.2"])
                transition_log = presented_log(device, transition_from)
                device.status()
                transition_stages = shader_stage_change(transition_baseline, device.log()[transition_from:])
                if observed["stage"] != target:
                    raise RuntimeError(f"expected {case['name']} stage {target}, observed {observed['stage']}")
                transition = dict(full_turn_rate(transition_log), render_errors=GPU_ERROR.findall(transition_log),
                                  script_warnings=script_warnings(device.game_log()[stage_from:]),
                                  includes_original_dance_and_levelup_dialogue=True,
                                  shaders_prepared=bool(SHADER_WORK.search(transition_log)) or bool(transition_stages["shader_stage_growth"]),
                                  **transition_stages)
                stage_row = dict(observed, donation=donation, transition=transition,
                                 **measure_scene(device, case, out, seconds, timeout, sensitivity, f"-stage{target}"))
                row["stages"].append(stage_row)
        errors = list(row["render_errors"])
        for stage in row.get("stages", []):
            errors += stage.get("render_errors", [])
            errors += stage.get("transition", {}).get("render_errors", [])
        for phase in row.get("phases", []):
            errors += phase.get("render_errors", [])
        errors += row.get("aftermath", {}).get("render_errors", [])
        discovery_errors = GPU_ERROR.findall(device.log()[before:])
        row.update(status="measured" if not errors and not discovery_errors else "render-error",
                   discovery_render_errors=discovery_errors,
                   temperature=device.shell("dumpsys battery | grep temperature").strip())
    except (RuntimeError, subprocess.SubprocessError) as error:
        row.update(status="unmeasured", error=str(error))
        try:
            row.update(device.screenshot(out / (case["id"] + "-failed.png")))
        except subprocess.SubprocessError:
            pass
    game = device.game_log()[game_before:]
    row["compiler_rejections"] = EXPECTED_COMPILER_REJECTION.findall(device.log()[before:])
    row["case_script_warnings"] = script_warnings(game)
    row["script_failed"] = row["case_script_warnings"]["execution_errors"] > 0
    if row.get("status") == "measured" and row["script_failed"]:
        row["status"] = "script-error"
    row["state_stalled"] = "invalid camera turn presentation clock interval" in row.get("error", "")
    (out / (case["id"] + ".log")).write_text(device.log()[before:], encoding="utf-8")
    (out / (case["id"] + "-game.log")).write_text(game, encoding="utf-8")
    return row


def self_test():
    manifest = inventory()
    assert [sum(c["kind"] == kind for c in manifest["cases"]) for kind in ("location", "sister", "battle")] == [35, 11, 10]
    assert {c["name"] for c in manifest["cases"] if c["kind"] == "sister"} >= {"aya", "echo", "ole"}
    assert len({c["id"] for c in manifest["cases"]}) == 56
    assert len(manifest["brother_conversations"]) == 10 and len(manifest["extra_cases"]) == 5
    phase_counts = {c["name"]: c["phase_count"] for c in manifest["cases"] if c["kind"] == "battle"}
    assert phase_counts == {name: (4 if name == "hole" else 1 if name == "whaler" else 3) for name in phase_counts}
    assert {c["location"]: c["conversation"] for c in manifest["cases"] if c.get("conversation")} == {
        32: "lattice", 34: "driller", 35: "stiltman", 36: "whaler", 37: "kolesnik", 38: "dudochnik", 39: "ironclad", 40: "caterpillar"}
    for case in manifest["cases"]:
        if case["kind"] != "sister":
            continue
        assert all(stage["talk_cameras"] and stage["dance_cameras"] for stage in case["stages"])
        cumulative = 0
        for expected, amount in enumerate([0, *case["stage_donations"]]):
            cumulative += amount
            result = observed_stage(f"[scene-audit] girl={case['name']} limfa={cumulative * 1000}\n", case)
            assert result["stage"] == expected
    times = "".join(f"[camera] frame {i} at {i * 10:.2f} ms:\n" for i in range(121))
    assert frame_times(times) == dict(timed_frames=120, timing_sample_sufficient=True, median_frame_ms=10, p95_frame_ms=10, max_frame_ms=10)
    try:
        Device("test", "userdata")
    except ValueError:
        pass
    else:
        raise AssertionError("primary profile accepted")
    from PIL import Image
    for colour, expected in (("black", False), ("white", True)):
        output = io.BytesIO()
        Image.new("RGB", (100, 100), colour).save(output, format="PNG")
        assert screenshot_content(output.getvalue())["centre_has_rendered_content"] == expected
    print("scene audit inventory, original routes, timing and profile guards PASS")


def complete_case(row, case, sister_stages, aftermath=False):
    if row["status"] != "measured":
        return False
    if case["kind"] == "cinematic":
        end = row.get("natural_completion", {})
        return (end.get("original_return_verified", False) and end.get("former_view_gone", False)
                and end.get("endpoint") == case["completion_scene"]
                and [p.get("scene") for p in row.get("phases", [])] == case["scenes_in_order"]
                and all(p.get("live_view_verified", False) for p in row["phases"]))
    if case["kind"] == "battle":
        return ([p.get("phase") for p in row.get("phases", [])] == list(range(1, case["phase_count"] + 1))
                and (not aftermath or (row.get("aftermath", {}).get("original_death_verified", False)
                                       and row["aftermath"].get("shader_stage_growth") == 0
                                       and not row["aftermath"].get("shaders_prepared_during_aftermath", False))))
    if sister_stages and case["kind"] == "sister":
        return [s.get("stage") for s in row.get("stages", [])] == list(range(5))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--script-probes", type=Path, help="Export QA-only Sister/hunter key probes and explicit World guard; never package them")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--profile", default="userdata-audit20261019")
    parser.add_argument("--save", default="5.sav")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--case", nargs="+")
    parser.add_argument("--kind", choices=("location", "sister", "battle", "brother", "extra", "cinematic"))
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--load-timeout", type=float, default=120)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--sister-stages", action="store_true", help="Measure all five actual Sister stages with QA UI probes and original donations; use a copied zero-stage seed")
    parser.add_argument("--aftermath", action="store_true", help="After all live Brother phases, observe the original lethal hit and ten seconds of aftermath")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    manifest = inventory()
    if args.script_probes:
        export_probes(args.script_probes, manifest)
        print("11 Sister queries, 10 hunter phase probes, original UI feeding seam and world guard -> " + str(args.script_probes))
        return
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{len(manifest['cases'])} shipped scene cases -> {args.manifest}")
        return
    if not math.isfinite(args.seconds) or args.seconds < 10 or args.load_timeout < 15 or not re.fullmatch(r"[\w.-]+", args.save):
        parser.error("at least ten seconds per scene, fifteen seconds load timeout, and a plain copied save name required")
    all_cases = manifest["cases"] + manifest["brother_conversations"] + manifest["extra_cases"]
    if args.kind == "cinematic" or (args.case and any(c.startswith("cinematic-") for c in args.case)):
        all_cases += manifest["cinematic_cases"]
    cases = [c for c in all_cases if (not args.kind or c["kind"] == args.kind) and (not args.case or c["id"] in args.case)]
    if args.case and set(args.case) != {c["id"] for c in cases}:
        parser.error("unknown case ID or incompatible --kind")
    checkpoint = args.out / "STOP_AFTER_CASE"
    if checkpoint.exists():
        print("Checkpoint requested; no device commands queued. Remove " + str(checkpoint) + " to resume.", flush=True)
        return
    device = Device(args.serial, args.profile, incremental_logs=True)
    settings = device.shell("cat " + device.remote + "/overrides/settings.xml")
    match = re.search(r'name="MouseSensitivity"\s+value="([^"]+)"', settings)
    sensitivity = float(match[1]) if match else 1
    if not math.isfinite(sensitivity) or sensitivity <= 0:
        raise ValueError("invalid MouseSensitivity")
    args.out.mkdir(parents=True, exist_ok=True)
    metadata = dict(manifest, serial=args.serial, profile=args.profile, save=args.save, seconds=args.seconds,
                    kind=args.kind, sister_stages=args.sister_stages, aftermath=args.aftermath,
                    sensitivity=sensitivity, device=device.shell("getprop ro.product.model; wm size"),
                    limitations="All authored Brother HP phases; Sister stages require --sister-stages; camera turn is calibrated input, not observed yaw; authored camera names do not prove every angle rendered; screenshots need visual review")
    (args.out / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out / ("metadata-" + (args.kind or "all") + ".json")).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    result_file = args.out / "results.json"
    results = json.loads(result_file.read_text(encoding="utf-8")) if args.resume and result_file.exists() else []
    by_id = {c["id"]: c for c in cases}
    done = {r["case"] for r in results if r["case"] in by_id and complete_case(r, by_id[r["case"]], args.sister_stages, args.aftermath)}
    for case in cases:
        if checkpoint.exists():
            print("Stopped at a complete case boundary: " + str(checkpoint), flush=True)
            break
        if case["id"] in done:
            continue
        row = (run_cinematic(device, case, args.out, args.seconds, args.load_timeout, args.save)
               if case["kind"] == "cinematic" else
               run_case(device, case, args.out, args.seconds, args.load_timeout, sensitivity, args.save, args.sister_stages, args.aftermath))
        results = [r for r in results if r["case"] != case["id"]] + [row]
        result_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
