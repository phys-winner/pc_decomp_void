"""Idempotent preparation for the original developer-menu scene routes."""
from patch_native_menu import Assembler
from patch_touch_native import hook, method


def patch_debug_locations(module, lang):
    # /add_girl appends an entity even if that Sister already exists. The menu
    # must be usable repeatedly, so prepare only missing entities and then use
    # the existing /talk_girl or /talk_hunter scene/camera bootstrap.
    start = method(module, "onConsoleCommand") + 8
    assert int.from_bytes(module.code[start - 4:start], "little") >= 5
    rows = list(module.instructions())
    command = next(i for i, r in enumerate(rows) if r.get("text") == "add_hunter")
    assert rows[command + 1]["opcode"] == 46 and rows[command + 2]["opcode"] == 55
    hunter_route = rows[command + 3]["offset"]
    a = Assembler(module)
    for kind, lookup, create in (("girl", "getGirlEntityByName", "addGirl"),
                                 ("hunter", "getHunterEntityByName", "addHunter")):
        a.move(-5, 0)
        a.string(1, "port_ensure_" + kind)
        a.emit(46, 0)
        a.emit(55, 0, "next_" + kind)
        a.clear(0, 1)
        a.move(-4, 1)
        a.member(0, "Count")
        a.integer(1, 1)
        a.emit(46, 0)
        a.emit(55, 0, "done_" + kind)
        a.move(-4, 1)
        a.integer(2, 0)
        a.emit(58, 0, 1)
        a.move(0, 4)
        for name in (lookup, create):
            if name == "addHunter":
                # addHunter accepts the factory's entity tuple, not a name.
                # The original console branch creates that tuple and supplies
                # it to addHunter; reuse the whole branch with its arguments.
                a.clear(0, 1, 2, 3, 4)
                a.emit(54, 0, hunter_route)
                break
            a.global_(2, "World")
            a.member(1, "call")
            a.clear(2)
            a.string(2, name)
            a.move(4, 3)
            a.native(0, 2)
            a.clear(1, 2, 3)
            if name == lookup:
                a.emit(56, 0, "done_" + kind)
        a.label("done_" + kind)
        a.clear(0, 1, 2, 3, 4)
        a.emit(65)
        a.label("next_" + kind)
        a.clear(0, 1)
    hook(module, start, a)
    return dict(sites=[hex(start)], debug_location_hunter_route=hex(hunter_route),
                debug_location_preparation="ensure original entities once; missing hunter uses original factory/add_hunter branch")
