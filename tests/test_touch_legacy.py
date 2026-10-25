"""Execute the 2008 body's real bytecode through the normalized bounded VM."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from gscript_binary import Module
from patch_scripts import read_entry, patch_skip_intro
from patch_touch_native import patch_body, patch_body_sources, patch_body_details
from test_touch_native import VM
from patch_database import patch_database


class Switch:
    asBool = True


def main():
    for legacy, index in ((False, "research/vfs-index.json"), (True, "research/vfs-index.polish.json")):
        menu = Module(read_entry(index, "Scripts\\world\\main_menu.bin"), legacy=legacy)
        patch = patch_skip_intro(menu, "pl" if legacy else "ru")
        published = []
        vm = VM(menu, named={"Settings": {"PortSkipIntro": Switch()},
                             "getString": lambda key: "custom colour " + str(key),
                             "getNamedString": lambda key: "custom menu " + key,
                             "format": lambda fmt, *values: fmt % values,
                             "executeConsoleCommand": published.append})
        vm.run(int(patch["trampoline"], 16), stops=(int(patch["skip_to"], 16),))
        assert published[:7] == [f"port_hint {i} custom colour {20009+i}" for i in range(7)]
        assert "port_hint 7 custom menu main_menu_new_game" in published
        assert "port_hint 14 custom menu main_menu_exit_game" in published
        assert "port_hints_ready" in published
        raw = read_entry(index, "Scripts\\ui\\body.bin")
        module = Module(raw, legacy=legacy)
        assert module.encode() == raw
        assert len(list(module.instructions())) > 1000
        patch_body(module, "pl" if legacy else "ru")
        sources = patch_body_sources(module, "pl" if legacy else "ru")
        details = patch_body_details(module, "pl" if legacy else "ru")
        assert not any(m["name"] == "onActiveLimfa" for c in module.contexts for m in c["methods"])
        assert bool(sources["lymph_entry"]) == legacy
        for hit in (-1, 0, 1, 8, 9, 40, 41):
            for lymph in (False, True):
                for entry in (sources["source_start"], sources["memory_put_start"]):
                    vm = VM(module, {sources['forced_zone_global']: 0}, named={"Settings": {"PortTouchInput": Switch()},
                                          "isKeyPressed": lambda key: key == 0x68 and lymph})
                    _, regs = vm.run(entry, {0: hit}, stops=(entry + 8,))
                    expected = hit if hit < 0 else hit // 2 * 2 + int(legacy and lymph and entry == sources["source_start"])
                    assert regs[0] == expected, (legacy, hit, lymph, regs)
        source = next(x for x in Module(raw, legacy=legacy).instructions() if x['offset'] == sources['memory_put_zone'])
        for hit in range(42):
            state = {sources['forced_zone_global']: 0, details['last_zone_global']: -1, details['last_zone_global'] + 1: False,
                     details['last_zone_global'] + 2: False}
            vm = VM(module, state, named={"Settings": {"PortTouchInput": Switch()},
                                          "__externals__": {(source['operands'][1], source['register']): 12000}})
            end, regs = vm.run(sources['memory_put_start'], {0: hit}, stops=(sources['memory_put_zone'] + 12,))
            assert end == sources['memory_put_zone'] + 12
            assert state[details['last_zone_global']] == hit // 2
            assert state[details['last_zone_global'] + 1] is True
            assert state[details['last_zone_global'] + 2] is True
        commands = []
        reserves = {"4": [45000, 12000, 2, True]}
        player = {"Properties": {"ZoneLimfa": reserves}}
        world = {"call": lambda name: player, "Properties": {"get": lambda name: {"MaxLimfa": {"asInt": 75}}}}
        vm = VM(module, {7: world, details["last_zone_global"]: 0, details["last_zone_global"] + 1: False, details["last_zone_global"] + 2: False}, {"format": lambda fmt, *values: fmt % tuple(values),
                                    "executeConsoleCommand": commands.append})
        vm.run(details["body_publisher"], {-4: 4})
        expected = "port_body_heart 2 45000 75000 4" + (" 12000" if legacy else "")
        assert commands == [expected], commands
        if legacy:
            reserves["4"][1] = 7000
            vm.globals[details["last_zone_global"] + 2] = True
            vm.run(details["body_publisher"], {-4: 4})
            assert commands[-1] == "port_body_heart 2 45000 75000 4 7000"
        rebuilt = Module(module.encode(), legacy=legacy)
        assert list(rebuilt.instructions()) == list(module.instructions())
    journal = Module(read_entry("research/vfs-index.polish.json", "Scripts\\ui\\database.bin"), legacy=True)
    original_rows = [r for r in journal.instructions() if not r.get("header")]
    patched = patch_database(journal, "pl")
    for globals_, wheel in zip(patched["legacy_scroll_groups"], patched["legacy_wheels"]):
        canvas, text, height, maximum, offset = globals_
        draws = []
        vm = VM(journal, {canvas: {"prepareWrapped": lambda *args: draws.append(args) or 700},
                          text: "third-party localized text", height: 200, maximum: 500, offset: 0})
        for delta, expected in [(-.5, 60), (-10, 500), (1, 380), (100, 0)]:
            vm.run(wheel, {-6: 50, -5: 50, -4: delta})
            assert vm.globals[offset] == expected
            assert draws[-1] == ("third-party localized text", -expected)
    # Execute a real patched colour-page preparation, including its native result.
    pw = next(i for i, r in enumerate(original_rows) if r.get("symbol") == "prepareWrapped"
              and original_rows[i-1]["opcode"] == 12 and original_rows[i-1]["register"] == 2
              and original_rows[i-1]["operands"][1] == 7)
    member = original_rows[pw]
    call = next(i for i in range(pw+1, len(original_rows)) if original_rows[i]["opcode"] == 57 and original_rows[i]["register"] == 0)
    canvas, text, height, maximum, offset = patched["legacy_scroll_groups"][3]
    native = lambda value, y: 700
    vm = VM(journal, {height: 200})
    _, regs = vm.run(member["offset"], {2: {"prepareWrapped": native}}, stops=(member["offset"]+8,))
    regs.update({2: "localized long text", 3: 0})
    _, regs = vm.run(original_rows[call]["offset"], regs, stops=(original_rows[call+1]["offset"],))
    after = original_rows[call+1]
    _, regs = vm.run(after["offset"], regs, stops=(after["offset"]+after["size"],))
    assert vm.globals[maximum] == 500 and vm.globals[offset] == 0 and regs[0] == 200
    assert vm.globals[text] == "localized long text"
    # The glyph canvas ends above the original sound/video buttons at every scale.
    create = next(i for i, r in enumerate(original_rows) if r.get("symbol") == "createStringCanvas")
    call = next(r for r in original_rows[create+1:] if r["opcode"] == 57 and r["register"] == 0)
    for screen_height in (360, 600, 1200):
        dimensions = []
        vm = VM(journal, named={"Height": screen_height, "__externals__": {(3, 1): screen_height / 1200}})
        vm.run(call["offset"], {1: lambda *args: dimensions.append(args), 2: "font", 3: 200, 4: 999}, stops=(call["offset"]+8,))
        assert abs(dimensions[0][2] - (screen_height * (.5 + 224/1200) - 132)) < .001
    assert Module(journal.encode(), legacy=True).encode() == journal.encode()
    print("PASS: both VM encodings, 2008 heart/lymph gesture selection, independent lymph counts, no 2009 heart-to-Palette deposit; original localized strings; clipped legacy journal scroll")


if __name__ == "__main__":
    main()
