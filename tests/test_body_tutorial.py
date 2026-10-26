"""Execute the original/manual Body tutorial lifecycle and its modal repair."""
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from gscript_binary import Module
from patch_scripts import read_entry, patch_dialogue_key, patch_named_strings, TOUCH_TEXTS
from patch_touch_native import PATCHES, patch_body_tutorial, method
from test_touch_native import VM


def function_rows(module, entry):
    rows = list(module.instructions())
    end = next((r['offset'] for r in rows if r.get('header') and r['offset'] > entry), len(module.code))
    return [r for r in rows if entry < r['offset'] < end]


def body_pair(index, lang):
    raw = read_entry(index, 'Scripts\\ui\\body.bin')
    module = Module(raw, legacy=lang == 'pl')
    for name, patch in PATCHES:
        if name == 'Scripts\\ui\\body.bin' and patch is not patch_body_tutorial:
            patch(module, lang)
    before = module.encode()
    info = patch_body_tutorial(module, lang)
    return raw, Module(before, legacy=lang == 'pl'), Module(module.encode(), legacy=lang == 'pl'), info


def invoke(module, marker, value, entry, args=None, globals=None, named=None, calls=None):
    state = dict(globals or {})
    state[marker] = value
    vm = VM(module, state, named, calls)
    end, registers = vm.run(entry, args)
    return vm, end, registers


def base_constructor(module, info, state):
    marker, entry = info['marker_global'], info['base_constructor']
    rows = function_rows(module, entry)
    pause = next(r['offset'] for r in rows if r['opcode'] == 68)
    helper_calls = {r['operands'][0] for r in rows if r['opcode'] == 63}
    observed = []
    # These unchanged UI/layout helpers cannot address the newly appended flag.
    calls = {target: (lambda registers, slot, target=target: observed.append((target, state[marker])))
             for target in helper_calls}
    state[2] = object()  # The real constructor restores its original Cursor.
    events = []
    vm = VM(module, state, {'executeConsoleCommand': events.append}, calls)
    stopped, _ = vm.run(entry, stops=(pause,))
    assert stopped == pause and state[marker] is True and observed
    assert all(value is True for _, value in observed)
    return events


def lifecycle(before, after, info):
    marker = info['marker_global']
    assert not any(r.get('opcode') == 13 and r['operands'][0] == marker for r in before.instructions())
    state, calls_seen = {marker: True}, []
    init_rows = function_rows(after, info['init_ui_entry'])
    native_setup = next(r['operands'][0] for r in init_rows if r['opcode'] == 63)
    vm = VM(after, state, calls={native_setup: lambda registers, slot: calls_seen.append(('initUI setup', state[marker]))})
    vm.run(info['init_ui_entry'], {-4: object()})
    assert calls_seen == [('initUI setup', True)] and state[marker] is False
    # Execute the actual demo -> shared initializer call and its argument store;
    # stop only before constructing the unrelated native body scene/view objects.
    initializer = info['demo_initializer']
    stop = next(r['offset'] for r in function_rows(before, initializer) if r.get('symbol') == 'loadScene')
    world = object()
    def setup(registers, slot):
        assert slot == 1 and registers[0] is world and state[marker] is False
        nested = VM(after, state)
        stopped, _ = nested.run(initializer, {-4: registers[0]}, stops=(stop,))
        assert stopped == stop and state[7] is world and state[marker] is False
        calls_seen.append(('demo shared setup', state[marker]))
    demo_rows = function_rows(before, info['demo_entry'])
    layout = [r['operands'][0] for r in demo_rows if r['opcode'] == 63][1]
    vm = VM(after, state, {'Cursor': object()}, {initializer: setup,
        layout: lambda registers, slot: calls_seen.append(('demo layout', state[marker]))})
    vm.run(info['demo_entry'], {-5: world, -4: object()})
    assert state[marker] is True and calls_seen[-2:] == [('demo shared setup', False), ('demo layout', True)]
    assert vm.transition[0] == 11
    base_constructor(after, info, state)
    assert state[marker] is True


def close_paths(before, after, info):
    marker = info['marker_global']
    destroy = (info['zone_return_original_state'], info['zone_return_original_constructor'])
    for entry, args in zip(info['close_entries'], ({-5: 'body', -4: True}, {}, {-5: 27, -4: False})):
        original = VM(before); original.run(entry, args)
        assert original.transition[:2] == destroy
        for active in (False, True):
            vm, _, _ = invoke(after, marker, active, entry, args)
            assert (not hasattr(vm, 'transition')) if active else vm.transition == original.transition
            assert vm.globals[marker] is active
    # Other actions and Escape-down retain their original no-close outcome.
    for entry, args in [(info['close_entries'][0], {-5: 'jump', -4: True}),
                        (info['close_entries'][2], {-5: 27, -4: True}),
                        (info['close_entries'][2], {-5: 65, -4: False})]:
        for active in (False, True):
            vm, _, _ = invoke(after, marker, active, entry, args)
            assert not hasattr(vm, 'transition')
    # A legitimate owner destroy still works, even with the modal flag set.
    destroyed = []
    invoke(after, marker, True, destroy[1], named={'destroy': lambda: destroyed.append(True)})
    assert destroyed == [True]
    # The fifth close is the separate automatic AddFreeLimfa animation, unchanged.
    auto = method(before, 'initBodyAddFreeLimfa')
    ctor = next(r['operands'][0] for r in function_rows(before, auto) if r['opcode'] == 67)
    for start in (auto, ctor, destroy[1]):
        old_rows = function_rows(before, start)
        end = old_rows[-1]['offset'] + old_rows[-1]['size']
        assert before.code[start:end] == after.code[start:end]
    final = next(r for r in function_rows(before, ctor) if r['opcode'] == 66 and r['register'] == destroy[0])
    for active in (False, True):
        vm, _, _ = invoke(after, marker, active, final['offset'])
        assert vm.transition[:2] == destroy


def refund_paths(before, after, info):
    marker = info['marker_global']
    # Memory carry Escape refunds45 units, then returns to the real base constructor.
    carry = 0x8db0
    for active in (False, True):
        props = {'FreeLimfa': {'3': 5000}}
        globals = {7: {'call': lambda name: {'Properties': props}}}
        vm, _, _ = invoke(after, marker, active, carry, {-5: 27, -4: False}, globals,
            {'__externals__': {(10, 0): 3, (10, 1): 45000}}, {5748: lambda registers, slot: None})
        assert props['FreeLimfa']['3'] == 50000 and vm.transition[:2] == (info['normal_state'], info['base_constructor'])
        if active:
            base_constructor(after, info, vm.globals)
            blocked, _, _ = invoke(after, marker, True, info['close_entries'][2], {-5: 27, -4: False}, vm.globals)
            assert not hasattr(blocked, 'transition')
    # Zone Return must execute the complete refund and original update callbacks.
    outputs = []
    for module, active in ((before, False), (after, False), (after, True)):
        props = {'ZoneLimfa': {'4': [10000, 0, 3, True]}}
        events = []
        def world_call(name):
            events.append(('world', name))
            return {'Properties': props} if name == 'getPlayerEntity' else None
        state = {marker: active, 7: {'call': world_call}, 8: {'call': lambda name: events.append(('scene', name))}}
        vm = VM(module, state, {'__externals__': {(7, 0): 4, (7, 1): 10000}})
        helper = next(r['operands'][0] for r in function_rows(before, info['zone_return_entry']) if r['opcode'] == 63)
        vm.calls[helper] = lambda registers, slot: VM(module, state).run(helper)
        vm.run(info['zone_return_entry'])
        expected = (info['normal_state'], info['base_constructor']) if active else (info['zone_return_original_state'], info['zone_return_original_constructor'])
        assert vm.transition[:2] == expected and props['ZoneLimfa']['4'][0] == 20000
        assert state[marker] is active
        outputs.append((copy.deepcopy(props), events))
    assert outputs[0] == outputs[1] == outputs[2]
    assert outputs[0][1] == [('world', 'getPlayerEntity'), ('world', 'updateZoneBonuses'), ('scene', 'updateShapes')]


def parent_gates(index, lang):
    raw = read_entry(index, 'Scripts\\scene\\obscure_sister.bin')
    for patched in (False, True):
        scene = Module(raw)
        if patched: patch_dialogue_key(scene, lang)
        rows = [r for r in scene.instructions() if not r.get('header')]
        captions = {number: next(r['offset'] for r in rows if r['opcode'] == 1 and r['operands'] == [number])
                    for number in (5001, 5002, 5003)}
        def loop_before(caption):
            back = max((r for r in rows if r['offset'] < caption and r['opcode'] == 54), key=lambda r: r['offset'])
            entry = back['operands'][0]
            branch = next(r for r in rows if entry <= r['offset'] < back['offset'] and r['opcode'] == 55)
            return entry, branch['offset']+branch['size'], branch['operands'][0]
        memory_entry, memory_wait, memory_done = loop_before(captions[5002])
        zone_entry, zone_wait, zone_done = loop_before(captions[5003])
        for amount in (0, 4999, 5000, 5001, 49999, 50000):
            pc, _ = VM(scene).run(memory_entry, {0: {'FreeLimfa': {'3': amount}}}, stops=(memory_wait, memory_done))
            assert pc == (memory_wait if amount > 5000 else memory_done)
        for amount in (0, 39999, 40000, 40001, 50000):
            pc, _ = VM(scene).run(zone_entry, {0: {'ZoneLimfa': {'4': [amount, 0, 3, True]}}}, stops=(zone_wait, zone_done))
            assert pc == (zone_wait if amount < 40000 else zone_done)
        saved = [73456, 12345, 6, True]
        props = {'ZoneLimfa': {'4': [0, 40000, 3, True]}, 'ActiveLimfa': {'3': 0}, 'FreeLimfa': {'3': 5000}}
        # The final three stores in this coroutine restore its captured inventory.
        owner = max(r['offset'] for r in scene.instructions() if r.get('header') and r['offset'] < captions[5001])
        body = function_rows(scene, owner)
        restores = [r for r in body if r['opcode'] == 59][-3:]
        start = max(r['offset'] for r in body if r['offset'] < restores[0]['offset'] and r['opcode'] == 10
                    and r['register'] == 2 and r['operands'] == [6])
        stop = next(r['offset'] for r in body if r['offset'] > restores[-1]['offset'] and r['opcode'] == 68)
        VM(scene).run(start, {0: props, 2: saved, 3: 1234, 4: 4567}, stops=(stop,))
        assert props == {'ZoneLimfa': {'4': saved}, 'ActiveLimfa': {'3': 1234}, 'FreeLimfa': {'3': 4567}}


def hints():
    name = 'Properties\\Strings\\tutorial.txt'
    for index, lang in [('research/vfs-index.json', 'ru'), ('research/vfs-index.english.json', 'en'),
                        ('research/vfs-index.german.json', 'de'), ('research/vfs-index.polish.json', 'pl')]:
        raw = read_entry(index, name)
        fixed, info = patch_named_strings(raw, TOUCH_TEXTS[name][lang])
        before, after = raw[2:].decode('utf-16le').split('\r\n'), fixed[2:].decode('utf-16le').split('\r\n')
        assert fixed[:2] == raw[:2] == b'\xff\xfe' and len(before) == len(after)
        changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        assert len(changed) == 2 and [before[i-1] for i in changed] == ['@string 1', '@string 2']
        assert after[changed[0]].count('%s') == before[changed[0]].count('%s') == 1
        assert '%' not in after[changed[1]] and info['strings'] == [5001, 5002]


def main():
    receipts = []
    for index, lang in [('research/vfs-index.json', 'ru'), ('research/vfs-index.german.json', 'de'),
                        ('research/vfs-index.polish.json', 'pl')]:
        raw, before, after, info = body_pair(index, lang)
        if lang == 'pl':
            assert before.encode() == after.encode() and info == {'sites': [], 'tutorial_guard': 'original_2008'}
        else:
            lifecycle(before, after, info)
            close_paths(before, after, info)
            refund_paths(before, after, info)
            parent_gates(index, lang)
        receipts.append(dict(release=lang, original_sha256=hashlib.sha256(raw).hexdigest(), guard=info))
    hints()
    out = ROOT / 'build/body-tutorial-test'; out.mkdir(parents=True, exist_ok=True)
    (out/'result.json').write_text(json.dumps(dict(status='PASS', releases=receipts,
        ordinary_body_unchanged=True, inventory_thresholds_and_restore_unchanged=True,
        native_scene_creation_stubbed=True, device_tested=False), indent=2)+'\n')
    print('PASS: RU/DE actual initUI/demo/base lifecycle, all4 close paths+carry refunds, normal/owner/automatic destroy,22 parent boundaries+2 restores each; PL byte-unchanged; four-language hints only5001/5002')


if __name__ == '__main__':
    main()
