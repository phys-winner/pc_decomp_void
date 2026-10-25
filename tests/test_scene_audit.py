"""Pin source-derived scene inventory and disposable read-only VM probes."""
from pathlib import Path
import runpy
import sys
import subprocess
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from gscript_binary import Module
from patch_scripts import method_rows, read_entry
from patch_touch_native import method
from scene_audit import Device, EXPECTED_COMPILER_REJECTION, GPU_ERROR, complete_case, final_probe_script, guard_script, hunter_probe_script, inventory, load_map, observed_ui_state, prepare_battle_view, presented_log, probe_script, query_hunter, script_warnings, self_test, shader_stage_change, ui_feed_script, view_count, wait_cinematic_end, wait_scene, wait_sister_ready

VM = runpy.run_path(str(ROOT / "tests/test_touch_native.py"))["VM"]


def preserved(original, patched):
    """Only frame sizes and complete callback trampolines may replace code."""
    assert patched.contexts == original.contexts and patched.table == original.table
    assert patched.types[:len(original.types)] == original.types
    old = list(original.instructions())
    renders = {f['code_offset'] + 8 for c in original.contexts for f in c['methods'] if f['name'] == 'render'}
    mutable = set()
    for i, row in enumerate(old):
        if row.get('opcode') != 68 and row['offset'] not in renders:
            continue
        owner = next(r for r in reversed(old[:i]) if r.get('header'))
        mutable.update(range(owner['offset'] + 4, owner['offset'] + 8))
        length = 0
        for stolen in old[i:]:
            length += stolen['size']
            if length >= 8:
                break
        mutable.update(range(row['offset'], row['offset'] + length))
    assert all(a == b for i, (a, b) in enumerate(zip(original.code, patched.code)) if i not in mutable)


def latched_poll(module, helpers, targets, guard=None, first_key=0x64, key_codes=None):
    keys, calls = set(), []
    globals = {i: False for i in range(len(module.types))}
    handlers = {helpers[name]: (lambda regs, window, name=name: calls.append(name)) for name in targets}
    if 'audit_hunter_pending' in helpers:
        handlers[helpers['audit_hunter_pending']] = lambda regs, window: None
    if guard:
        handlers[helpers[guard]] = lambda regs, window: calls.append(guard)
    vm = VM(module, globals, {'isKeyPressed': lambda key: key in keys}, handlers)
    callback = helpers['audit_poll']
    vm.run(callback)
    assert calls == ([guard] if guard else [])
    calls.clear()
    for key, name in zip(key_codes or range(first_key, first_key + len(targets)), targets):
        keys.add(key)
        vm.run(callback)
        vm.run(callback)
        assert calls == [name], calls
        calls.clear()
        keys.clear()
        vm.run(callback)
        keys.add(key)
        vm.run(callback)
        assert calls == [name]
        calls.clear()
        keys.clear()
        vm.run(callback)


class HealthVM(VM):
    """Run original HP bytecode, adding its two inclusive comparisons."""
    def run(self, start, regs=None, stops=()):
        regs = dict(regs or {})
        pc = start + 8 if self.rows[start].get('header') else start
        for _ in range(4000):
            if pc in stops:
                return pc, regs
            row = self.rows[pc]
            op, r, args = row['opcode'], row['register'], row['operands']
            following = pc + row['size']
            if op == 65:
                return None, regs
            if op == 54:
                pc = args[0]
            elif op in (55, 56):
                pc = args[0] if bool(regs.get(r)) == (op == 56) else following
            elif op in (49, 51):
                regs[r] = regs[r] <= regs[r + 1] if op == 49 else regs[r] >= regs[r + 1]
                pc = following
            elif op == 47:
                left, right = regs.get(r), regs.get(r + 1)
                assert type(left) is type(right) or (type(left) in (int, float) and type(right) in (int, float)), 'Neq type mismatch'
                regs[r] = left != right
                pc = following
            else:
                _, regs = super().run(pc, regs, stops=(following,))
                pc = following
        raise AssertionError('original hunter HP instruction budget exceeded')


class Thresholds(list):
    @property
    def Count(self):
        return len(self)


def load_race():
    class LoadingDevice:
        def __init__(self):
            self.commands, self.frames, self.guards, self.text = [], iter((100, 101, 101, 103, 104, 105, 106)), 0, ''

        def status(self, lines=()):
            self.commands.append(list(lines))
            frame = next(self.frames)
            if '/audit_guard' in ' '.join(lines):
                assert frame > 102, 'guard sent against the old stalled map'
                self.guards += 1
                if self.guards == 2:
                    self.text += '[scene-audit] World.Vars.god_mode=1\n'
            return {'frame': frame, 'tags': 0x1000400}

        def game_log(self):
            return self.text

    device = LoadingDevice()
    load_map(device, '5.sav', 15)
    assert device.commands[0] == ['console /load 5.sav'] and device.commands[1] == ['sleep 3']
    assert device.guards == 2, 'discarded final-loading-tick guard was not retried'


def sister_readiness():
    class ReadinessDevice:
        def __init__(self):
            self.text, self.queries, self.nexts = '', 0, 0

        def game_log(self):
            return self.text

        def status(self, lines):
            if lines[0] == 'key 7c':
                self.queries += 1
                if self.queries > 1:
                    self.text += f'[scene-audit] girl=ole limfa=1400000 ready={int(self.queries == 3)} donor=1\n'
            else:
                assert lines[0] == 'key 0d'
                self.nexts += 1

    device = ReadinessDevice()
    case = next(c for c in inventory()['cases'] if c['id'] == 'sister-ole')
    assert wait_sister_ready(device, case, 15) == dict(stage=3, girl_limfa=1400000, ready=True, donor_active=True)
    assert device.queries == 3 and device.nexts == 1, 'absent pulse or original busy dialogue was not handled'

    class BufferedScene:
        def status(self, timeout):
            return {'tags': 0x8000}

        def log(self):
            return r'[void] C:\Games\The Void\data\Scripts\scene\obscure_ole.bin: QA override'

        def game_log(self):
            return ''  # The original init message is still in its 4 KiB buffer.

    assert wait_scene(BufferedScene(), case, 0, 0, 15)['tags'] == 0x8000


def brother_readiness():
    class OriginalTalk:
        def __init__(self): self.text, self.views = '', 0
        def game_log(self): return self.text
        def log(self): return ''  # Original, non-overridden module loads silently.
        def status(self, lines=(), timeout=35):
            if 'console /views' in lines:
                self.views += 1
                # The placeholder node and a zero-view room do not prove a
                # live instance of the requested actual Brother conversation.
                self.text += ('Arena/talkloc.xml : 1 view(s)\n' if self.views == 1 else
                              f'Arena/huntertalk_B.xml : {int(self.views > 2)} view(s)\n')
            return {'frame': self.views + 1, 'tags': 0x8000001}
    case = next(c for c in inventory()['cases'] if c['id'] == 'location-32')
    device = OriginalTalk()
    with patch('scene_audit.time.sleep'):
        assert wait_scene(device, case, 0, 0, 15)['tags'] == 0x8000001
    assert device.views == 3


def hunter_phases(index, case):
    original = Module(read_entry(index, case['hunter_script'].replace('/', '\\')))
    helpers = {}
    patched = Module(hunter_probe_script(original.original, case, helpers))
    preserved(original, patched)
    targets = ['audit_hunter', *['audit_hunter_phase' + str(i) for i in range(2, case['phase_count'] + 1)], 'audit_hunter_defeat']
    latched_poll(patched, helpers, targets, key_codes=[*range(0x64, 0x64 + case['phase_count']), 0x68])
    # Exercise both exactly divisible and uneven authored health thresholds,
    # and both original damage-colour multipliers. No HP arithmetic is mocked.
    for maximum in (1000000, 750003):
        for selected_colour in (0, 1):
            count = case['phase_count']
            hp_slot = next(r['register'] for r in method_rows(original, 'getHunterHP') if r['opcode'] == 14)
            stage_slot = next(r['register'] for r in method_rows(original, 'getHunterStage') if r['opcode'] == 14)
            assert stage_slot == hp_slot + 3
            globals = {i: False for i in range(len(patched.types))}
            pending_slot = len(original.types)
            globals[pending_slot] = 0
            globals.update({hp_slot: maximum, hp_slot + 1: maximum, hp_slot + 2: True,
                            stage_slot: 0, stage_slot + 1: count, stage_slot + 2: False,
                            stage_slot + 3: Thresholds([int((count - i - 1) * maximum / count) for i in range(count)] + [-100])})
            logs = []
            vm = HealthVM(patched, globals, {'Scene': {'call': lambda name, stage: selected_colour}, 'logInfo': logs.append})

            def original_call(target):
                def call(regs, window):
                    arguments = {slot - window - 3: value for slot, value in regs.items() if slot < window}
                    _, result = vm.run(target, arguments)
                    if -4 in result:
                        regs[window - 1] = result[-4]
                return call

            names = ('damageHunter', 'setHunterHealth', 'isHunterDead', 'isHunterVulnerable', 'getHunterStage', 'getHunterHP', 'getHunterMaxStage')
            vm.calls = {method(patched, name): original_call(method(patched, name)) for name in names}
            vm.calls[helpers['audit_hunter_pending']] = original_call(helpers['audit_hunter_pending'])
            vm.calls[helpers['audit_hunter']] = original_call(helpers['audit_hunter'])
            vm.calls[method(patched, 'playDamageSound')] = lambda regs, window: None
            # Actual Stiltman/Whaler/Mongolfier/Driller can reject an instant
            # press. The QA request must survive without changing any game
            # HP/stage/vulnerability/transition field, then service once when
            # the ORIGINAL AI opens its real vulnerability window.
            globals[hp_slot + 2] = False
            target = 'audit_hunter_phase2' if count > 1 else 'audit_hunter_defeat'
            vm.run(helpers[target])
            for _ in range(3):
                vm.run(helpers['audit_hunter_pending'])
                assert globals[hp_slot] == maximum and globals[stage_slot] == 0
                assert globals[hp_slot + 2] is False and globals[stage_slot + 2] is False
                assert globals[pending_slot] == 2
            globals[hp_slot + 2] = True  # Simulate the authored AI's setter.
            vm.run(helpers['audit_hunter_pending'])
            assert globals[stage_slot] == 1 and globals[stage_slot + 2] is True
            assert globals[pending_slot] == 0
            hp = globals[hp_slot]
            globals[stage_slot + 2] = False
            vm.run(helpers['audit_hunter_pending'])
            assert globals[hp_slot] == hp and globals[stage_slot] == 1 and globals[stage_slot + 2] is False
            globals.update({hp_slot: maximum, stage_slot: 0, stage_slot + 2: False})
            if count > 1:
                vm.run(helpers['audit_hunter_defeat'])
                assert globals[stage_slot] == 0 and globals[hp_slot] == maximum and not globals[stage_slot + 2]
            vm.run(helpers['audit_hunter'])
            assert f'hunter={case["name"]} stage=0 hp={int(maximum * .001)} max_stage={count}' in logs[-1], repr(logs[-1][:160])
            for phase in range(2, count + 1):
                vm.run(helpers['audit_hunter_phase' + str(phase)])
                assert globals[stage_slot] == phase - 1 and globals[hp_slot] > 0 and globals[stage_slot + 2] is True
                hp = globals[hp_slot]
                globals[stage_slot + 2] = False  # The original AI consumes this transition flag.
                vm.run(helpers['audit_hunter_phase' + str(phase)])
                assert globals[stage_slot] == phase - 1 and globals[hp_slot] == hp and globals[stage_slot + 2] is False
                vm.run(helpers['audit_hunter'])
                assert f'stage={phase - 1} hp=' in logs[-1]
            vm.calls[helpers['audit_hunter']] = original_call(helpers['audit_hunter'])
            vm.run(helpers['audit_hunter_defeat'])
            assert globals[stage_slot] == count and globals[hp_slot] == 0 and globals[stage_slot + 2] is True
            assert f'stage={count} hp=0 max_stage={count}' in logs[-1]
            globals[stage_slot + 2] = False
            vm.run(helpers['audit_hunter_defeat'])
            assert globals[stage_slot] == count and globals[hp_slot] == 0 and globals[stage_slot + 2] is False


def sister_ui_dispatch(index, cases):
    original = Module(read_entry(index, 'Scripts\\ui\\obscure.bin'))
    helpers = {}
    patched = Module(ui_feed_script(original.original, cases, helpers))
    preserved(original, patched)
    latched_poll(patched, helpers, ['audit_ui_state', *['audit_feed' + str(i) for i in range(1, 5)]])
    for case in cases:
        scene = Module(read_entry(index, 'Scripts\\scene\\obscure_' + case['name'] + '.bin'))
        # The original UI calls the registered native Scene ScriptObject, which
        # binds context4's integer stage. A private static CALL from the help
        # context would instead read that coroutine's object slot and fail.
        on_gesture = next(f for f in scene.contexts[4]['methods'] if f['name'] == 'OnGesture')
        assert on_gesture['signature'] == [1, 1, 2]
        rows = list(scene.instructions())
        start = on_gesture['code_offset']
        end = next(r['offset'] for r in rows if r.get('header') and r['offset'] > start)
        i = next(i for i, r in enumerate(rows) if start < r['offset'] < end and r.get('opcode') == 12 and rows[i + 1].get('opcode') == 47)
        before, external, compare, following = rows[i - 1:i + 3]
        assert before['opcode'] == 10 and scene.contexts[external['operands'][1]]['types'][external['register']] == 1
        binding = (external['operands'][1], external['register'])
        strict = HealthVM(scene, named={'__externals__': {binding: 0}})
        strict.run(before['offset'], {before['register']: 1}, stops=(following['offset'],))
        strict.named['__externals__'][binding] = {'help': 'object'}
        try:
            strict.run(before['offset'], {before['register']: 1}, stops=(following['offset'],))
        except AssertionError as error:
            assert str(error) == 'Neq type mismatch'
        else:
            raise AssertionError('old cross-context feeding defect was not reproduced')
        calls = []

        def base_gesture(regs, window):
            donor, colour, amount = (regs[window - n] for n in (3, 2, 1))
            assert type(donor) is type(colour) is int and type(amount) is float
            calls.append((donor, colour, amount))

        console = VM(scene, named={'toInt': lambda text: (int(text),)},
                     calls={on_gesture['code_offset']: base_gesture})

        def bound_gesture(name, donor, colour, amount):
            assert name == 'OnGesture' and type(donor) is type(colour) is int and type(amount) is float
            calls.append((donor, colour, amount))

        logged = []
        vm = VM(patched, {27: {'call': bound_gesture}, 34: case['name']}, {'logInfo': logged.append})
        limfa, ready, donor = 0, False, False

        def world_call(name, *arguments):
            if name == 'getGirlEntityByName':
                assert arguments == (case['name'],)
                return {'Properties': {'limfa': limfa}}
            assert name == 'isGestureActive' and arguments == (1,)
            return donor

        def ui_call(default, name):
            assert default is False and name == 'IsActive'
            return ready

        query = VM(patched, {26: {'call': world_call}, 34: case['name']},
                   {'self': {'callDef': ui_call}, 'logInfo': logged.append})
        for stage, amount in enumerate([0, *case['stage_donations']]):
            limfa += amount * 1000
            for ready, donor in ((False, False), (False, True), (True, True)):
                query.run(helpers['audit_ui_state'])
                assert observed_ui_state(logged[-1], case) == dict(stage=stage, girl_limfa=limfa, ready=ready, donor_active=donor)
        for stage, donation in enumerate(case['stage_donations'], 1):
            vm.run(helpers['audit_feed' + str(stage)])
            assert calls[-1] == (1, case['good_colour'], float(donation * 1000))
            assert f'ui_feed stage={stage} dispatched={case["name"]}' in logged[-1]
            # The developer console's original parser reaches the same typed
            # base donor arguments; its event cannot be invoked via native call.
            console.run(method(scene, 'onConsoleCommand'), {-5: 'give', -4: (str(case['good_colour']), str(donation))})
            assert calls[-1] == (1, case['good_colour'], float(donation * 1000))
    vm = VM(patched, {34: 'not_a_sister'}, {'logInfo': lambda line: None})
    for stage in range(1, 5):
        vm.run(helpers['audit_feed' + str(stage)])


self_test()
compiler_rejection = '[d3dx] D3DXCompileShader main/ps_3_0 fails as on Windows: memory(204,36): error X5300: Invalid register number: 10.'
assembler_rejection = '[d3dx] D3DXAssembleShader fails as on Windows: error X1234: invalid input'
negative_response = '[d3dx] fd897abdd9f23126 served by the live compile service (error)'
assert not GPU_ERROR.search(compiler_rejection + '\n' + assembler_rejection + '\n' + negative_response)
assert len(EXPECTED_COMPILER_REJECTION.findall(compiler_rejection + '\n' + assembler_rejection + '\n' + negative_response)) == 3
for failure in ('[d3d9] GLSL compile failed: source error', '[d3d9] program link failed', '[gl] compile failed', '[d3dx] compiler service error', '[d3dx] D3DXCompileShader unexpected error', negative_response + ' unexpected service failure', '[d3dx] fd897abdd9f23126 served by the live compile service (unknown error)'):
    assert GPU_ERROR.search(failure), failure
load_race()
sister_readiness()
brother_readiness()
cached = Device('test', 'userdata-test', incremental_logs=True)
transient = subprocess.CalledProcessError(1, ['adb', 'shell', 'pidof'], stderr=b'error: closed')
with patch('scene_audit.subprocess.check_output', side_effect=[transient, b'123\n']) as output, patch('scene_audit.time.sleep'), patch('scene_audit.sys.stderr'):
    assert cached.shell('pidof org.thevoid.port || true') == '123\n'
    assert output.call_count == 2
with patch('scene_audit.subprocess.check_output', side_effect=[transient] * 3) as output, patch('scene_audit.time.sleep'), patch('scene_audit.sys.stderr'):
    try:
        cached.shell('pidof org.thevoid.port || true')
    except subprocess.CalledProcessError:
        assert output.call_count == 3
    else:
        raise AssertionError('persistent transport failure hidden')
with patch('scene_audit.subprocess.check_output', side_effect=[transient, b'prefix', b' tail']) as output, patch('scene_audit.time.sleep'), patch('scene_audit.sys.stderr'):
    assert cached._read_log('retry') == 'prefix'
    assert cached._read_log('retry') == 'prefix tail'
    assert output.call_args_list[0].args[0] == output.call_args_list[1].args[0]
    assert output.call_args_list[2].args[0][-1].startswith('tail -c +7 ')
with patch('scene_audit.subprocess.check_output', side_effect=[b'A\xc3', b'\xa9\r\nB', b'other', b'A\xe2\x82', b'\xacB']) as output:
    assert cached.log() == 'A' and cached.log() == 'A\u00e9\nB' and cached.game_log() == 'other'
    assert cached._read_log('threebyte') == 'A' and cached._read_log('threebyte') == 'A\u20acB'
    commands = [c.args[0][-1] for c in output.call_args_list]
    assert commands[0].startswith('tail -c +1 ') and commands[1].startswith('tail -c +3 ') and commands[2].startswith('tail -c +1 ')
    assert commands[4].startswith('tail -c +4 ')
    assert all(c.args[0][3] == 'exec-out' for c in output.call_args_list), 'shell CRLF translation invalidates raw byte offsets'
class PendingPresent:
    def __init__(self):
        self.lines = iter(('[live] camera 1 0 0\n[camera] frame 10 at 100.00 ms:\n[live] camera 1 0 0\n',
                           '[live] camera 1 0 0\n[camera] frame 10 at 100.00 ms:\n[live] camera 1 0 0\n[camera] frame 20 at 200.00 ms:\n'))
    def log(self):
        return next(self.lines)
assert presented_log(PendingPresent(), 0).endswith('[camera] frame 20 at 200.00 ms:\n')
base = '[shaderwork] stages=10 programs=20 reused=100 hlsl=40\n'
assert shader_stage_change(base, '[shaderwork] stages=10 programs=30 reused=200 hlsl=90')['shader_stage_growth'] == 0
assert shader_stage_change(base, '[shaderwork] stages=11 programs=20 reused=100 hlsl=40')['shader_stage_growth'] == 1
assert view_count('Loaded Map/map_death.xml', 'Map/map_death.xml') == 0
assert view_count('Map/map_death.xml: 1 view(s)\nMap/map_death.xml: 0 view(s)', 'Map/map_death.xml') == 0
assert view_count(r'Scenes\Map\map_death.xml: 2 view(s)', 'Map/map_death.xml') == 2
class NaturalMovie:
    def __init__(self):
        self.output, self.calls = '', []
        self.chunks = iter(('up_level/up_level.xml: 1 view(s)\n',
                            'up_level/up_level.xml: 1 view(s)\nMap/main_menu.xml: 1 view(s)\n',
                            'Map/main_menu.xml: 1 view(s)\n'))
    def game_log(self):
        return self.output
    def status(self, lines):
        self.calls.append(lines)
        self.output += next(self.chunks)
        return {'tags': 0, 'frame': len(self.calls)}
movie = NaturalMovie()
assert wait_cinematic_end(movie, 'up_level/up_level.xml', 'Map/main_menu.xml', 10)['frame'] == 3
assert all(len(lines) == 16 and set(lines) == {'console /views', 'sleep 0.05'} for lines in movie.calls)
for c in inventory()['cinematic_cases']:
    assert c['completion_scene'] == ('Map/main_menu.xml' if c['id'].startswith('cinematic-final-') or c.get('original_breakthrough') else 'Map/map.xml')
    assert not complete_case({'status': 'measured'}, c, False)
    receipt = dict(status='measured', phases=[dict(scene=s, live_view_verified=True) for s in c['scenes_in_order']],
                   natural_completion=dict(original_return_verified=True, former_view_gone=True, endpoint=c['completion_scene']))
    assert complete_case(receipt, c, False)
    receipt['natural_completion']['endpoint'] = 'incorrect.xml'
    assert not complete_case(receipt, c, False)
    receipt['natural_completion']['endpoint'] = c['completion_scene']
    receipt['phases'].pop()
    assert not complete_case(receipt, c, False)
    if c['id'].startswith('cinematic-final-'):
        assert c['commands'] == ['/final ' + c['name']]
warning_log = '\n'.join(f'00:00:01 [{1000 + i}]: <Error> null path' for i in range(60))
warning_log += '\n00:00:01 [1100]: <Error> Error during execution of the script "bad": type mismatch'
warning_log += '\n00:00:01 [1100]: <Error>   at source.sc(10)'
warnings = script_warnings(warning_log)
assert warnings['total'] == 61 and warnings['execution_errors'] == 1 and warnings['callback_errors'] == 0
assert warnings['messages'][0]['count'] == 60 and warnings['messages'][0]['max_in_one_second'] == 60
assert not complete_case({'status': 'measured'}, {'kind': 'battle', 'phase_count': 3}, False)
assert not complete_case({'status': 'measured', 'phases': [{'phase': 1}, {'phase': 3}]}, {'kind': 'battle', 'phase_count': 3}, False)
assert complete_case({'status': 'measured', 'phases': [{'phase': i} for i in range(1, 4)]}, {'kind': 'battle', 'phase_count': 3}, False)
assert not complete_case({'status': 'measured', 'phases': [{'phase': i} for i in range(1, 4)]}, {'kind': 'battle', 'phase_count': 3}, False, True)
assert not complete_case({'status': 'measured', 'phases': [{'phase': i} for i in range(1, 4)], 'aftermath': {'original_death_verified': True}}, {'kind': 'battle', 'phase_count': 3}, False, True)
assert complete_case({'status': 'measured', 'phases': [{'phase': i} for i in range(1, 4)], 'aftermath': {'original_death_verified': True, 'shader_stage_growth': 0}}, {'kind': 'battle', 'phase_count': 3}, False, True)
assert not complete_case({'status': 'measured', 'phases': [{'phase': i} for i in range(1, 4)], 'aftermath': {'original_death_verified': True, 'shader_stage_growth': 0, 'shaders_prepared_during_aftermath': True}}, {'kind': 'battle', 'phase_count': 3}, False, True)
assert not complete_case({'status': 'measured', 'phases': [{'phase': i} for i in range(1, 4)], 'aftermath': {'original_death_verified': True, 'shader_stage_growth': 1}}, {'kind': 'battle', 'phase_count': 3}, False, True)
assert not complete_case({'status': 'measured'}, {'kind': 'sister'}, True)
assert complete_case({'status': 'measured', 'stages': [{'stage': i} for i in range(5)]}, {'kind': 'sister'}, True)
stiltman = next(c for c in inventory()['cases'] if c['id'] == 'battle-stiltman')
assert stiltman['arena_setup_point'] == 'pt_driller_4'
arena = read_entry('research/vfs-index.json', 'Scenes\\arena\\flache.xml').decode('cp1251')
assert 'pt_driller_4' in arena and '51.8532' in arena and '13.3423' in arena
class BattleSetup:
    def __init__(self): self.commands = []
    def status(self, commands): self.commands.extend(commands)
setup_device = BattleSetup()
setup = prepare_battle_view(setup_device, stiltman, 1)
assert setup_device.commands == ['console /gopt pt_driller_4', 'sleep 0.5', 'move -182 0', 'sleep 0.5']
assert -105 < setup['calibrated_turn_degrees'] < -104
assert prepare_battle_view(setup_device, {'name': 'kolesnik'}, 1) is None
assert len(setup_device.commands) == 4
alternate = prepare_battle_view(setup_device, stiltman, 1, alternate=True)
assert alternate['original_command'] == '/gopt pt_driller_0' and alternate['grounded_locator'] == [-32, 0, 24]
assert -130 < alternate['calibrated_turn_degrees'] < -127
assert prepare_battle_view(setup_device, stiltman, 1, alternate=True)['original_command'] == '/gopt pt_driller_4'
class HunterRead:
    def __init__(self): self.commands = []
    def status(self, commands): self.commands.append(commands)
    def game_log(self):
        return '' if len(self.commands) < 2 else '[scene-audit] hunter=stiltman stage=1 hp=466 max_stage=3 vulnerable=1 pending=0'
reader = HunterRead()
assert query_hunter(reader, stiltman)['phase'] == 2
assert reader.commands == [['key 7c', 'sleep 0.3']] * 2
for index in ("research/vfs-index.json", "research/vfs-index.german.json"):
    player = Module(read_entry(index, 'Scripts\\player.bin'))
    gopt = method(player, 'console_gopt')
    following = [r for r in player.instructions() if r['offset'] >= gopt]
    finish = next((i for i, r in enumerate(following[1:], 1) if r.get('header')), len(following))
    texts = {r.get('symbol', r.get('text')) for r in following[:finish]}
    assert {'getLocatorTransform', 'Position', 'Translation'}.issubset(texts)
    final_original = Module(read_entry(index, 'Scripts\\ui\\obscure_final.bin'))
    final_helpers = {}
    final_patched = Module(final_probe_script(final_original.original, final_helpers))
    preserved(final_original, final_patched)
    latched_poll(final_patched, final_helpers, ['audit_breakthrough'])
    callbacks, final_logs = [], []
    vm = VM(final_patched, named={'self': {'call': lambda *args: callbacks.append(args)}, 'logInfo': final_logs.append})
    vm.run(final_helpers['audit_breakthrough'])
    assert callbacks == [('onBreakthrough',)] and len(final_logs) == 2
    sister_ui_dispatch(index, [c for c in inventory()['cases'] if c['kind'] == 'sister'])
    for case in inventory()["cases"]:
        if case["kind"] == 'battle':
            hunter_phases(index, case)
        if case["kind"] != "sister":
            continue
        original = Module(read_entry(index, "Scripts\\scene\\obscure_" + case["name"] + ".bin"))
        helpers = {}
        patched = Module(probe_script(original.original, case, helpers))
        probe, getter = helpers["audit_obscure"], method(patched, "getLimfa")
        preserved(original, patched)
        latched_poll(patched, helpers, ['audit_obscure'])
        events = []

        def read_limfa(regs, window):
            assert window == 1
            regs[window - 1] = 200000

        vm = VM(patched, named={"logInfo": events.append}, calls={getter: read_limfa})
        _, regs = vm.run(probe)
        expected = "[scene-audit] girl=" + case["name"] + " limfa=200000 " + "." * 4096
        assert events == [expected, expected]
    original = Module(read_entry(index, "Scripts\\world\\world.bin"))
    patched = Module(guard_script(original.original))
    entry = method(original, 'onConsoleCommand') + 8
    assert patched.contexts == original.contexts
    assert patched.table == original.table and patched.types == original.types
    assert patched.code[:entry] == original.code[:entry]
    assert patched.code[entry + 8:len(original.code)] == original.code[entry + 8:]
    variables, logged = {}, []
    vm = VM(patched, named={"World": {"Vars": variables}, "logInfo": logged.append})
    for _ in range(2):
        _, result = vm.run(method(patched, "onConsoleCommand"), {-5: 'audit_guard', -4: ()})
        assert variables == {"god_mode": True} and result[-6] is True
    assert len(logged) == 4 and all(line.startswith('[scene-audit] World.Vars.god_mode=1 ') for line in logged)
    # Unknown commands must execute their unchanged first instruction without
    # touching any native global, initialized World object or QA state.
    vm = VM(patched)
    for command in ('go', 'load', 'views', 'talk_girl', '', '/audit_guard'):
        args = ('argument',)
        pc, result = vm.run(method(patched, 'onConsoleCommand'), {-5: command, -4: args}, stops=(entry + 8,))
        assert pc == entry + 8 and result[0] == command and result[-5] == command and result[-4] == args

print("22 RU/DE Sister queries, 88 typed native UI gifts, reproduced cross-context Neq defect, 20 original hunter damage/getter paths, all HP phases, key latches, load race and preserved metadata PASS")
