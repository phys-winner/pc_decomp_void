"""Execute the actual menu/video/carry/cancel bytecode for both game generations."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from gscript_binary import Module
from patch_scripts import INDEXES, read_entry
from patch_touch_native import (patch_menu_map_hint, patch_journal_video,
                                patch_body, patch_body_sources, patch_body_details, patch_body_memory_counts, patch_cancel)
from test_touch_native import VM


for index, lang in INDEXES.items():
    def load(name):
        return Module(read_entry(index, "Scripts\\ui\\" + name + ".bin"), legacy=lang == "pl")

    menu = load("main_menu")
    info = patch_menu_map_hint(menu, lang)
    site = info["disabled_save_hint"]
    call = next(x for x in load("main_menu").instructions() if x["offset"] == site)
    for translated in ("Only on the map!", "Только на карте!", "Nur auf der Karte!", "Custom translation"):
        called = []
        _, regs = VM(menu).run(site, {call["register"] + 1: lambda *a: called.append(a),
                                     call["register"] + 2: translated}, stops=(site + 8,))
        assert not called and regs[call["register"]] == ""

    journal = load("database")
    info = patch_journal_video(journal, lang)
    events = []
    start = info["journal_video_render"]
    VM(journal, named={"executeConsoleCommand": events.append}).run(start, {-4: {}}, stops=(start + 16,))
    assert events == ["port_journal_video"]

    body = load("body")
    patch_body(body, lang)
    sources = patch_body_sources(body, lang)
    details = patch_body_details(body, lang)
    info = patch_body_memory_counts(body, lang)
    zone = {str(i): [0, 0, 0, False] for i in range(21)}
    zone["0"] = [0, 0, 1, True]  # Empty hearts accept any carried colour.
    zone["1"] = [12301, 0, 3, True]
    zone["2"] = [5000, 0, 5, True]  # Another colour must have no label.
    zone["3"] = [0, 0, 3, False]  # Locked hearts must have no label.
    drawn = []

    # The camera's projection gives float pixels; the published place is whole pixels.
    hero = {"makeAttachPoint": lambda name: {"Position": (100.75 + int(name[7:]) * 50, 200.5)}}
    class Request:
        asInt = 0
    request = Request()
    world = {"call": lambda name: {"Properties": {"ZoneLimfa": zone}},
             "Properties": {"get": lambda name: {"MaxLimfa": {"asInt": 75}}}}
    state = {2: None, 3: None, 7: world, 8: {"call": lambda name: hero}, 9: {"pointToScreenSpace": lambda p: {"x": p[0], "y": p[1]}},
             13: "font", info["memory_counts_global"]: 4}
    def execute(command):
        if command == 'setting PortBodyPut 0': request.asInt = 0
        else: drawn.append(command)
    named = {"Settings": {"PortTouchInput": {"asBool": True}, "PortBodyPut": request},
             "format": lambda fmt, *a: fmt % a, "executeConsoleCommand": execute}
    VM(body, state, named).run(info["memory_counts_render"], {-4: {}})
    assert drawn == ["port_zone_label 0 100 200 0 75", "port_zone_label 1 150 200 13 75"], drawn
    for z in zone.values(): z[:] = [0, 0, 1, True]
    drawn.clear()
    VM(body, state, named).run(info["memory_counts_render"], {-4: {}})
    assert drawn == [f"port_zone_label {i} {100 + 50 * i} 200 0 75" for i in range(21)], drawn
    requests, published = [], []
    def put(regs, base):
        assert tuple(regs[base - n] for n in (3, 2, 1)) == (0, 0, True)
        assert request.asInt == 0
        _, hit = VM(body, state, named).run(sources['memory_put_start'], {0: -1},
                                           stops=(sources['memory_put_start'] + 8,))
        requests.append(hit[0] // 2)
        assert state[sources['forced_zone_global']] == 0
    def publish(regs, base): published.append(regs[base - 1])
    calls = {body._touch_body_put: put, details['body_publisher']: publish}
    for target in range(21):
        request.asInt = target + 1
        VM(body, state, named, calls).run(info['memory_counts_render'], {-4: {}})
        assert requests[-1] == published[-1] == target
        assert request.asInt == 0
    for value in (-2, 0, 22, 100):
        request.asInt = value
        VM(body, state, named, calls).run(info['memory_counts_render'], {-4: {}})
        assert len(requests) == 21 and request.asInt == 0
    for value in ([1000, 0, 5, True], [0, 0, 3, False]):
        zone['4'] = value
        request.asInt = 5
        VM(body, state, named, calls).run(info['memory_counts_render'], {-4: {}})
        assert len(requests) == 21 and request.asInt == 0
    zone['4'] = [75000, 0, 3, True]  # Full matching hearts use the game's normal refund.
    request.asInt = 5
    VM(body, state, named, calls).run(info['memory_counts_render'], {-4: {}})
    assert len(requests) == 22 and requests[-1] == 4
    VM(body, state, named).run(info["memory_counts_carry"], {-4: 5}, stops=(info["memory_counts_carry"] + 16,))
    assert state[info["memory_counts_global"]] == 6
    VM(body, state, named).run(info["memory_counts_reset"], stops=(info["memory_counts_reset"] + 16,))
    assert state[info["memory_counts_global"]] == 0
    state[info["memory_counts_global"]] = 0
    drawn.clear()
    VM(body, state, named).run(info["memory_counts_render"], {-4: {}})
    assert not drawn
    state[info["memory_counts_global"]] = 4
    named["Settings"]["PortTouchInput"]["asBool"] = False
    VM(body, state, named).run(info["memory_counts_render"], {-4: {}})
    assert not drawn
    assert Module(body.encode(), legacy=lang == "pl").encode() == body.encode()

    for name in ("paint", "tree", "hunter", "obscure", "obscure_final"):
        if read_entry(index, "Scripts\\ui\\" + name + ".bin") is None:
            continue
        module = load(name)
        info = patch_cancel(module, lang)
        release = info["cancel_release"]
        cleaned = []
        calls = {row["operands"][0]: lambda regs, base: cleaned.append(True)
                 for row in module.instructions() if row.get("opcode") == 63}
        VM(module, named={"isKeyPressed": lambda key: key == 0x65}, calls=calls).run(release, {-4: False})
        assert cleaned == [True, True], (lang, name, cleaned)
        cleaned.clear()
        VM(module, named={"isKeyPressed": lambda key: False}, calls=calls).run(
            release, {-4: False}, stops=(release + 16,))
        assert not cleaned
    print(f"PASS {lang}: translation-independent hint, journal video marker, eligible heart counts, cancel before mouse-up")


from test_touch_controls import method
from build_game_apk import JAVA_HOME
import subprocess

source = (ROOT / "android/app/src/org/thevoid/port/Controls.java").read_text(encoding="utf-8")
out = ROOT / "build/ui-refinements/body-input-test"
out.mkdir(parents=True, exist_ok=True)
probe = out / "BodyInputProbe.java"
probe.write_text('''public class BodyInputProbe {
    static class Input { static final int BODY_RETURN=0x67,BODY_WIDGET=0x69; }
    static class Sink { int returns,widget; void tapKey(int key) { assert key==Input.BODY_RETURN; ++returns; }
        void key(int key,boolean down) { assert key==Input.BODY_WIDGET; widget+=down?1:-1; } }
    final Sink in=new Sink(); final float[] bodyAmounts=new float[28];
    static final int HAND_MEMORY=3,HAND_PALETTE=4,CARD_PUT=1;
    int handFrom=HAND_MEMORY,handColour=2,bodyTransferColour=-1,started,cancelled,cards;
    long guideUntil; boolean holding=true,heartTicked,memoryPour;
    boolean handHolds() { return holding; }
    void stopPouring() {} void releaseHand() {} void clearHand() { holding=false; }
    void cancel() { ++cancelled; clearHand(); } void resetBodyTransferColour() { bodyTransferColour=-1; }
    void useCard(int card) { cards=card; clearHand(); }
    void startHand(int from,int colour,int zone) { handFrom=from;handColour=colour; }
    void startBodyColour(boolean memory,int colour) { ++started; }
''' + method(source, "private void bodyColour(") + '''
    public static void main(String[] args) {
        for(float remaining:new float[]{0,0.4f,20}) {
            BodyInputProbe p=new BodyInputProbe();p.bodyAmounts[18]=remaining;
            p.bodyColour(true,2,true);
            assert p.in.returns==1&&!p.holding&&p.started==0&&p.cancelled==0;
            p.bodyColour(true,2,false);assert p.in.returns==1;
        }
        BodyInputProbe p=new BodyInputProbe();p.handFrom=1;p.bodyColour(true,2,true);
        assert p.cards==(CARD_PUT|0x20)&&p.in.returns==0:"heart colour still deposits into empty Memory";
        p=new BodyInputProbe();p.holding=false;p.bodyColour(true,2,true);assert p.started==0;
        p=new BodyInputProbe();p.holding=false;p.bodyAmounts[18]=20;p.bodyColour(true,2,true);
        assert p.started==1&&p.memoryPour&&p.bodyTransferColour==2;
        System.out.println("PASS: empty/partial Memory circles return carried colour; heart deposits and extraction preserved");
    }
}
''', encoding="utf-8")
subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-d", str(out), str(probe)], check=True, capture_output=True)
subprocess.run([str(JAVA_HOME / "bin/java.exe"), "-ea", "-cp", str(out), "BodyInputProbe"], check=True)
