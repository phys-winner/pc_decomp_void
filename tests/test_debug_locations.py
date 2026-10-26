"""Check every source scene's classification and execute actual bootstrap bytecode."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
from generate_debug_levels import scene_catalog
from gscript_binary import Module
from patch_debug_locations import patch_debug_locations
from patch_scripts import read_entry, method_rows
from patch_touch_native import method
from test_touch_native import VM
from test_touch_controls import method as java_method
from build_game_apk import JAVA_HOME


class Arguments(list):
    @property
    def Count(self):
        return len(self)


for year, index, expected in (("2009", "research/vfs-index.json", (66, 53, 13, 43)),
                               ("2008", "research/vfs-index.polish.json", (58, 50, 8, 50))):
    data = scene_catalog(index)
    assert json.loads((ROOT / "research" / ("debug-scenes-" + year + ".json")).read_text(encoding="utf-8")) == data
    assert (data["total_scenes"], len(data["covered_scenes"]), len(data["excluded"]), len(data["extras"])) == expected
    assert not {e["scene"].lower() for e in data["excluded"]} & {s.lower() for s in data["covered_scenes"]}
    assert len({e["scene"].lower() for e in data["excluded"]} | {s.lower() for s in data["covered_scenes"]}) == data["total_scenes"]
    assert data["extras"][-1]["kind"] == "easter_egg" and data["extras"][-1]["commands"] == ["/backyard"]
    assert all(e["label"].startswith("[*] ") for e in data["extras"][:-1])
    for entry in data["extras"]:
        assert entry["commands"] and entry["proof"] and entry["camera"]
        for scene in [entry["scene"], *entry["follows"]]:
            assert read_entry(index, "Scenes\\" + scene.replace("/", "\\"))
    assert all(e["reason"] for e in data["excluded"])
    legacy = year == "2008"
    module = Module(read_entry(index, "Scripts\\world\\world.bin"), legacy=legacy)
    original_entry = method(module, "onConsoleCommand") + 8
    first = next(r for r in module.instructions() if r["offset"] == original_entry)
    assert first["size"] == 8
    patch_debug_locations(module, "pl" if legacy else "ru")
    # Reparse the actual serialized output, including the legacy opcode mapping.
    module = Module(module.encode(), legacy=legacy)
    entities = {"girl": {}, "hunter": {}}
    calls = []
    console = method_rows(module, "onConsoleCommand")
    at = next(i for i, row in enumerate(console) if row.get("text") == "add_hunter")
    end = console[at + 2]["operands"][0]
    factory, add = [row["operands"][0] for row in console[at:] if row["offset"] < end and row["opcode"] == 63]
    assert add == next(m["code_offset"] for c in module.contexts for m in c["methods"] if m["name"] == "addHunter" and m["args"] == 1)

    class Text(str):
        @property
        def asString(self): return str(self)

    def factory_call(regs, slot):
        name = regs[1]
        assert name == "kolesnik" and slot == 2
        calls.append(("originalFactory", name))
        regs[0] = ({"Properties": {"name": name, "girl": "una"}, "setLocation": lambda *args: None}, object())

    def add_call(regs, slot):
        entity = regs[1]
        assert slot == 2 and type(entity) is tuple and isinstance(entity[0]["Properties"], dict)
        assert entity[0]["Properties"]["name"] == "kolesnik"
        body = method_rows(module, "addHunter", args=1)
        # Execute the real production argument dereference: 2009 reads
        # tuple[0].Properties.girl; 2008 first indexes tuple[0] for setLocation.
        stop = next(row["offset"] for row in body if row.get("symbol") == "setLocation") if legacy else next(
            row["offset"] for row in body if row["opcode"] == 0 and row["register"] == 2)
        vm = VM(module, globals={35: -1}, named={"Map": {"LocationCount": 1}, "irandMax": lambda count: 0})
        reached, state = vm.run(add, {-4: entity}, stops=(stop,))
        assert reached == stop
        assert state[3] is entity[0] if legacy else state[1] == "una"
        try:
            # The old helper's name argument must fail the original method's
            # actual dereference, rather than being accepted by our model.
            vm.run(add, {-4: "kolesnik"}, stops=(stop + (8 if legacy else 0),))
        except (AttributeError, TypeError, KeyError, IndexError):
            pass
        else:
            raise AssertionError("original addHunter unexpectedly accepted a name instead of a tuple")
        calls.append(("originalAddHunterTuple", "kolesnik"))
        assert "kolesnik" not in entities["hunter"]
        entities["hunter"]["kolesnik"] = entity

    def call(name, target):
        calls.append((name, target))
        if name.startswith("get"):
            kind = "girl" if "Girl" in name else "hunter"
            return entities[kind].get(target)
        assert name == "addGirl", "addHunter requires the original console factory flow, never a name argument"
        kind = "girl"
        body = method_rows(module, "addGirl", args=1)
        stop = next(row["offset"] for row in body if row.get("symbol") == "Map")
        properties = {"get": lambda path: {"Location": Text("2")} if path == "Girl/" + target else None}
        reached, state = VM(module, named={"logInfo": lambda text: None, "Properties": properties}).run(
            method(module, "addGirl"), {-4: target}, stops=(stop,))
        assert reached == stop and state[0] == "2", "the original addGirl accepts a name and resolves Girl/name properties"
        assert target not in entities[kind], "repeated menu entry must not duplicate entities"
        entities[kind][target] = object()

    def run(command, args):
        before = len(calls)
        vm = VM(module, named={"World": {"call": call}}, calls={factory: factory_call, add: add_call})
        stop, regs = vm.run(original_entry, {-5: command, -4: Arguments(args)}, stops=(original_entry + 8,))
        assert -5 not in regs or regs[-5] == command
        assert -4 not in regs or regs[-4] == args
        return stop, calls[before:]

    for kind, lookup, create in (("girl", "getGirlEntityByName", "addGirl"), ("hunter", "getHunterEntityByName", "addHunter")):
        command = "port_ensure_" + kind
        target = "sister" if kind == "girl" else "kolesnik"
        stop, seen = run(command, [target])
        assert stop is None and seen == ([(lookup, target), (create, target)] if kind == "girl" else
                                        [(lookup, target), ("originalFactory", target), ("originalAddHunterTuple", target)])
        stop, seen = run(command, [target])
        assert stop is None and seen == [(lookup, target)]
        for invalid in ([], [target, "extra"]):
            stop, seen = run(command, invalid)
            assert stop is None and not seen
    # All original commands and look-alikes resume at the original body with
    # their arguments intact. No original branch is replaced by the helpers.
    for command in ("go", "talk_girl", "backyard", "port_ensure_girls", "port_ensure_hunter_extra"):
        stop, seen = run(command, ["unchanged"])
        assert stop == original_entry + 8 and not seen
    print(year + ": every source scene accounted for; actual idempotent bootstrap bytecode PASS")

# Execute Controls' production batch dispatcher. Repeated runDebugCommand calls
# used to send Escape twice for a two-command route while the HUD still paused.
source = (ROOT / "android/app/src/org/thevoid/port/Controls.java").read_text(encoding="utf-8")
out = ROOT / "build/debug-command-test/batch"
out.mkdir(parents=True, exist_ok=True)
probe = out / "DebugBatchProbe.java"
probe.write_text('''import java.util.*;
public class DebugBatchProbe {
    static final int S_PAUSE=1, HUD_PAUSE=1;
    int panels=2, releases, escapes, screen=S_PAUSE;
    boolean panelVisible() {return panels>0;} void closePanel() {--panels;}
    void releaseAll() {++releases;} boolean shown(int flag,int age) {return screen==S_PAUSE;}
    Object getContext() {return this;}
    static class Input {static final int ESC=27;}
    class In {void tapKey(int key) {assert key==Input.ESC; ++escapes;}}
    final In in=new In();
    static class Handler {Runnable pending; int posts; void postDelayed(Runnable task,int ms) {assert ms==180; pending=task; ++posts;}}
    final Handler handler=new Handler();
    static class GameActivity {
        static final List<String> commands=new ArrayList<>(); static String reject;
        static boolean nativeConsoleCommand(String command) {commands.add(command); return !command.equals(reject);}
    }
    static class android {static class widget {static class Toast {
        static final int LENGTH_LONG=1; static int errors;
        static Toast makeText(Object context,String message,int duration) {++errors; return new Toast();} void show() {}
    }}}
''' + java_method(source, "void runDebugCommand(String command)") + "\n" +
    java_method(source, "void runDebugCommands(String[] commands)") + '''
    public static void main(String[] args) {
        DebugBatchProbe p=new DebugBatchProbe();
        p.runDebugCommands(new String[]{"/port_ensure_hunter hole","/talk_hunter hole"});
        assert p.panels==0 && p.releases==1 && p.escapes==1 && p.handler.posts==1;
        assert GameActivity.commands.isEmpty(); p.handler.pending.run();
        assert GameActivity.commands.equals(Arrays.asList("/port_ensure_hunter hole","/talk_hunter hole"));
        GameActivity.commands.clear(); GameActivity.reject="/port_ensure_hunter hole";
        p.runDebugCommands(new String[]{GameActivity.reject,"/talk_hunter hole"}); p.handler.pending.run();
        assert GameActivity.commands.equals(Arrays.asList(GameActivity.reject)) && android.widget.Toast.errors==1;
        GameActivity.commands.clear(); GameActivity.reject=null; p.screen=0;
        p.runDebugCommand("/backyard"); p.handler.pending.run();
        assert GameActivity.commands.equals(Arrays.asList("/backyard")) && p.escapes==2;
        System.out.println("actual debug batch: one unpause, ordered queue, failure stops route PASS");
    }
}
''', encoding="utf-8")
subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-d", str(out), str(probe)], check=True)
subprocess.run([str(JAVA_HOME / "bin/java.exe"), "-ea", "-cp", str(out), "DebugBatchProbe"], check=True)
