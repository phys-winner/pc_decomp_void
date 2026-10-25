"""Exercise the real touch force adapter and appended body bytecode.

The bounded VM checks transfer arithmetic and branching against the original
asset. Device rendering and hit geometry still require the real game smoke test.
"""
from pathlib import Path
import math
import re
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_x86_incremental import compiler_environment
from gscript_binary import Module, read_asset
from patch_touch_native import patch_body, patch_body_sources, patch_body_counts, patch_body_details, patch_body_progress, patch_stat_details, patch_player, patch_stats, patch_map, patch_map_rearm, patch_vein, patch_harvest_stop, patch_brush_live, patch_brush_capacity, method, PATCHES
from patch_scripts import read_entry


def function(source, name):
    begin = re.search(r'(?:void|int|uint32_t) ' + name + r'\([^;]*?\)\s*\{', source).start()
    depth = 0
    for end in range(source.index('{', begin), len(source)):
        depth += (source[end] == '{') - (source[end] == '}')
        if not depth:
            return source[begin:end + 1]
    raise AssertionError(name)


def native_probe():
    source = (ROOT / 'android/host/touch_native.c').read_text()
    out = ROOT / 'build/native-analysis/touch-selfcheck'
    out.mkdir(parents=True, exist_ok=True)
    code = r'''#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define void_log(...) ((void)0)
#define pthread_mutex_lock(p) ((void)0)
#define pthread_mutex_unlock(p) ((void)0)
#define atomic_store(p,v) (*(p)=(v))
#define atomic_load(p) (*(p))
static int exchange(int *p,int v) {int old=*p; *p=v; return old;}
#define atomic_exchange(p,v) exchange((p),(v))
#define GPTR(p) (memory+(p))
#define MEM32(p) (*(uint32_t*)GPTR(p))
#define MEM8(p) (*GPTR(p))
static unsigned char memory[4096];
static uint32_t g_esp,g_ecx,g_eax;
static float move_x,move_y,chosen_fov=55,chosen_veins=1;
static int touch_lock,move_active,move_walking,movement_force_armed,options_pending;
static int keys[256],presses[256],find_console;
static char commands[32][512];
static unsigned command_first,command_count;
static float observed[3];
static float body_amounts[28];
static unsigned body_amounts_known;
static float body_details[14] = {-1,-1,-1,-1,-1,0,0,0,0,0,0,0,-1};
static char body_stat_names[7][256];
static char hint_texts[56][256];
typedef struct { int x, y; unsigned current, maximum; uint64_t at; } zone_label;
static zone_label zone_labels[21];
static int hints_ready;
static int body_target=-1;
static char *guest_text;
static unsigned unknown_commands;
static void void_touch_observe_context(uint32_t value) {}
static char *void_wstr_utf8(uint32_t value) {return _strdup(guest_text);}
static void void_hud_path_ready(void) {}
enum { HUD_VIDEO=1u<<23, HUD_JOURNAL_VIDEO=1u<<30 };
static unsigned hud_drawn;
static void void_hud_draw(unsigned tags) {hud_drawn |= tags;}
static void void_touch_harvest_stop(void) {}
static void sub_1017E0F0_lifted(void) {unknown_commands++;}
static int brush_colour=-1;
static int body_transfer_colour=-1;
static uint32_t console_object;
static uint64_t cancel_until;
static uint64_t now_ns=1;
static uint64_t void_monotonic_ns(void) {return now_ns;}
static int void_vm_find(const uint8_t *p,unsigned n,uint32_t *out,unsigned size) {return 0;}
typedef struct {int placeholder;} void_regs;
static void void_regs_save(void_regs *r) {}
static void void_regs_load(const void_regs *r) {}
static char executed[4][512];
static unsigned executed_count;
static void execute_command(uint32_t console,const char *text) {
    assert(console==1000 && executed_count<4);
    strcpy(executed[executed_count++],text);
}
static int void_vm_writable(uint32_t p,uint32_t n) {return p && p+n<=sizeof memory;}
static int void_vm_readable(uint32_t p,uint32_t n) {return void_vm_writable(p,n);}
static void void_input_key(unsigned key,int down) {keys[key]=down; presses[key]++;}
static void sub_101C61C0_lifted(void) {
    memcpy(observed,GPTR(MEM32(g_esp+4)),sizeof observed); g_esp+=8;
}
static void near(float x,float y) {assert(fabsf(x-y)<.0001f);}
'''
    for name in ('void_touch_movement', 'void_touch_gameplay_options', 'void_touch_console', 'sub_101C61C0', 'console_candidate', 'console_usable', 'void_touch_commands_pump', 'void_touch_body_amounts', 'void_touch_body_details', 'void_touch_body_stat_name', 'void_touch_hint_texts', 'void_touch_brush_colour', 'void_touch_body_transfer_colour', 'void_touch_zone_labels', 'sub_1017E0F0'):
        code += function(source, name) + '\n'
    script = (ROOT / 'android/host/script.c').read_text()
    code += re.search(r'typedef struct \{[^}]+\} script_event;', script).group() + '\n'
    code += re.search(r'typedef struct \{[^}]+\} script_line_buffer;', script).group() + '\n'
    code += function(script, 'parse_line') + '\n' + function(script, 'script_line_byte') + '\n'
    code += function((ROOT / 'android/host/input.c').read_text(), 'void_vk_to_dik') + '\n'
    code += r'''
static void force(float x,float y,int arm,float original_y) {
    void_touch_movement(x,y);
    float v[3]={0,original_y,10}; memcpy(GPTR(100),v,sizeof v);
    g_esp=200; MEM32(204)=100; movement_force_armed=arm;
    sub_101C61C0();
    assert(g_esp==208 && !movement_force_armed);
    assert(!memcmp(v,GPTR(100),sizeof v)); near(observed[1],original_y);
}
int main(void) {
    for (unsigned vk=0x7c; vk<=0x81; ++vk) assert(void_vk_to_dik(vk)==0x64+vk-0x7c);
    g_esp=300; MEM32(304)=500; MEM32(500)=600;
    guest_text="port_body_heart 2 45741 75000 4"; sub_1017E0F0();
    float details[14]; void_touch_body_details(details);
    assert(details[0]==2 && details[12]==4); near(details[1],45.741f); near(details[2],75);
    g_esp=300; guest_text="port_body_progress 88 525"; sub_1017E0F0();
    g_esp=300; guest_text="port_body_stat 2 64 Effect name with spaces"; sub_1017E0F0();
    void_touch_body_details(details); assert(details[3]==88 && details[4]==525 && details[7]==64);
    char name[256]; void_touch_body_stat_name(2,name); assert(!strcmp(name,"Effect name with spaces"));
    void_touch_body_stat_name(-1,name); assert(!*name);
    g_esp=300; guest_text="port_body_heart 7 0 75000 4"; sub_1017E0F0();
    assert(unknown_commands==1); void_touch_body_details(details); assert(details[0]==2);
    g_esp=300; guest_text="port_body_stat 2 101 Invalid percentage"; sub_1017E0F0();
    assert(unknown_commands==2); void_touch_body_details(details); assert(details[7]==64);
    char hints[56][256]; assert(!void_touch_hint_texts(hints));
    g_esp=300; guest_text="port_journal_video"; sub_1017E0F0();
    assert(hud_drawn==(HUD_VIDEO|HUD_JOURNAL_VIDEO) && g_esp==308);
    g_esp=300; guest_text="port_hint 2 Translated amber"; sub_1017E0F0();
    g_esp=300; guest_text="port_hint 7 "; sub_1017E0F0();
    g_esp=300; guest_text="port_hints_ready"; sub_1017E0F0();
    assert(void_touch_hint_texts(hints) && !strcmp(hints[2],"Translated amber") && !*hints[7]);
    /* The hearts a carried Memory colour can go into: their places and amounts, while fresh. */
    float labels[21*5]; assert(void_touch_zone_labels(labels)==0);
    g_esp=300; guest_text="port_zone_label 3 512 233 9 25"; sub_1017E0F0(); assert(g_esp==308);
    g_esp=300; guest_text="port_zone_label 20 -4 700 0 75"; sub_1017E0F0();
    g_esp=300; guest_text="port_zone_label 21 1 1 0 75"; sub_1017E0F0(); assert(unknown_commands==3);
    assert(void_touch_zone_labels(labels)==2);
    assert(labels[0]==3 && labels[1]==512 && labels[2]==233 && labels[3]==9 && labels[4]==25);
    assert(labels[5]==20 && labels[6]==-4 && labels[7]==700 && labels[8]==0 && labels[9]==75);
    now_ns+=150000000; g_esp=300; guest_text="port_zone_label 3 520 240 10 25"; sub_1017E0F0();
    now_ns+=100000000; assert(void_touch_zone_labels(labels)==1 && labels[0]==3 && labels[1]==520);
    now_ns+=300000000; assert(void_touch_zone_labels(labels)==0);
    now_ns=1;
    force(0,1,1,7); near(observed[0],0); near(observed[2],10);
    assert(keys['W'] && !keys[0xa0]);
    force(.6f,.8f,1,-8); near(observed[0],6); near(observed[2],8);
    force(1,0,1,3); near(observed[0],10); near(observed[2],0);
    force(0,-1,1,4); near(observed[2],-10);
    force(0,.25f,1,5); near(observed[2],5); assert(keys[0xa0]);
    force(0,.5f,1,5); near(observed[2],6.6f); assert(!keys[0xa0]);
    force(6,8,1,3); near(observed[0],6); near(observed[2],8);
    force(.3f,.4f,0,9); near(observed[0],0); near(observed[2],10);
    force(0,0,1,2); near(observed[2],10); assert(!keys['W'] && !keys[0xa0]);
    void_touch_movement(NAN,1); assert(!move_active && !keys['W']);
    void_touch_movement(1,INFINITY); assert(!move_active);
    void_touch_gameplay_options(70,3); assert(chosen_fov==70 && chosen_veins==3 && options_pending);
    void_touch_gameplay_options(101,1); assert(chosen_fov==70);
    void_touch_gameplay_options(50,NAN); assert(chosen_veins==3);
    assert(!void_touch_console(NULL) && !void_touch_console(""));
    assert(!void_touch_console("/go 1\n/god") && !void_touch_console("/go 1\r/god"));
    char long_command[513]; memset(long_command,'a',512); long_command[512]=0;
    assert(!void_touch_console(long_command));
    long_command[511]=0; assert(void_touch_console(long_command));
    assert(strlen(commands[0])==511 && find_console);
    for(int i=1;i<32;i++) assert(void_touch_console("/go 1"));
    assert(!void_touch_console("/god") && command_count==32);
    command_first=31; command_count=0;
    assert(void_touch_console("/go 35") && !strcmp(commands[31],"/go 35"));
    assert(void_touch_console("/god") && !strcmp(commands[0],"/god"));
    MEM32(1000)=0x1111f74c; assert(!console_candidate(1000));
    MEM32(1000+0x2c)=1100; MEM32(1000+0x38)=1200;
    MEM8(1100+0x19)=1; MEM8(1200+0x1d)=1; assert(console_candidate(1000));
    MEM8(1200+0x1d)=0; assert(!console_candidate(1000));
    script_line_buffer line={0}; script_event event;
    const char *prefix="console ";
    for(int i=0;prefix[i];i++) assert(!script_line_byte(&line,prefix[i]));
    for(int i=0;i<511;i++) assert(!script_line_byte(&line,'x'));
    assert(script_line_byte(&line,'\n') && parse_line(line.text,&event,0));
    assert(strlen(event.text)==511 && event.text[510]=='x');
    for(int i=0;prefix[i];i++) script_line_byte(&line,prefix[i]);
    for(int i=0;i<512;i++) script_line_byte(&line,'x');
    assert(script_line_byte(&line,'\n') && !parse_line(line.text,&event,0));
    for(int i=0;i<2048;i++) assert(!script_line_byte(&line,'x'));
    assert(!script_line_byte(&line,'\n'));
    const char *next="move 1 2 99";
    for(int i=0;next[i];i++) script_line_byte(&line,next[i]);
    assert(script_line_byte(&line,'\n') && parse_line(line.text,&event,0) && event.c==99);
    script_line_byte(&line,'a'); script_line_byte(&line,0);
    assert(!script_line_byte(&line,'\n'));
    const char *timed="1.5 console /go 35";
    for(int i=0;timed[i];i++) script_line_byte(&line,timed[i]);
    assert(script_line_byte(&line,'\n') && parse_line(line.text,&event,1));
    assert(event.at==1.5 && !strcmp(event.text,"/go 35"));
    char body_probe[]="hud body";
    assert(parse_line(body_probe,&event,0) && !strcmp(event.action,"hud") && !strcmp(event.text,"body"));
    float amounts[28]; void_touch_body_amounts(amounts);
    for(int i=0;i<28;i++) assert(amounts[i]==-1);
    body_amounts_known=1; void_touch_body_amounts(amounts);
    assert(amounts[0]==0 && amounts[1]==0 && amounts[2]==-1);
    assert(void_touch_brush_colour()==-1); brush_colour=5;
    assert(void_touch_brush_colour()==5);
    assert(void_touch_body_transfer_colour()==-1); body_transfer_colour=2;
    assert(void_touch_body_transfer_colour()==2 && void_touch_body_transfer_colour()==-1);
#ifndef VOID_RELEASE
    console_object=1000; MEM32(1000)=1100; MEM32(1100+0x34)=0x110F0370u;
    find_console=0; command_count=0; executed_count=0;
    void_touch_gameplay_options(55,1); void_touch_commands_pump();
    assert(executed_count==2 && !strcmp(executed[0],"setting PortFOV 55"));
    assert(!strcmp(executed[1],"setting PortVeinBrightness 100"));
    void_touch_commands_pump(); assert(executed_count==2);
    executed_count=0; void_touch_gameplay_options(70.6f,4.256f); void_touch_commands_pump();
    assert(executed_count==2 && !strcmp(executed[0],"setting PortFOV 71"));
    assert(!strcmp(executed[1],"setting PortVeinBrightness 426"));
#endif
    return 0;
}
'''
    probe = out / 'probe.c'
    probe.write_text(code)
    compiler, env, _ = compiler_environment()
    for variant, defines in (('2009', []), ('2008', ['/DVOID_RELEASE'])):
        exe = out / ('probe-' + variant + '.exe')
        subprocess.run([str(compiler), '/nologo', '/O2', '/std:c11', *defines, str(probe),
                        '/Fe' + str(exe), '/Fo' + str(out / ('probe-' + variant + '.obj'))],
                       env=env, check=True, capture_output=True)
        subprocess.run([str(exe)], check=True)


def signed(n):
    return n - 2**32 if n >= 2**31 else n


class VM:
    def __init__(self, module, globals=None, named=None, calls=None):
        self.module = module
        self.rows = {x['offset']: x for x in module.instructions()}
        self.globals, self.named, self.calls = globals or {}, named or {}, calls or {}

    def run(self, start, regs=None, stops=()):
        regs = dict(regs or {})
        pc = start + 8 if self.rows[start].get('header') else start
        for _ in range(10000):
            if pc in stops:
                return pc, regs
            row = self.rows[pc]
            op, r, a = row['opcode'], row['register'], row['operands']
            pc += row['size']
            get = lambda n: regs.get(n)
            if op == 0: regs[r] = bool(a[0])
            elif op == 1: regs[r] = signed(a[0])
            elif op == 2: regs[r] = struct.unpack('<f', struct.pack('<I', a[0]))[0]
            elif op == 3: regs[r] = self.module.wide(a[1], a[0])
            elif op == 4: regs[r] = None
            elif op == 6: regs[r] = 0
            elif op == 10: regs[signed(a[0])] = get(r)
            elif op == 11: self.named['__externals__'][a[1], a[0]] = get(r)
            elif op == 12: regs[a[0]] = self.named['__externals__'][a[1], r]
            elif op == 13: self.globals[a[0]] = get(r)
            elif op == 14: regs[a[0]] = self.globals[r]
            elif op == 16: regs[r] = int(get(r))
            elif op == 17: regs[r] = float(get(r))
            elif op == 18: pass
            elif op == 20: regs[r] = str(get(r))
            elif op == 21: regs[r] = get(r) + 1
            elif op == 23: regs[r] = not get(r)
            elif op == 36: regs[r] = get(r) + get(r + 1)
            elif op == 37: regs[r] = get(r) - get(r + 1)
            elif op == 38: regs[r] = get(r) * get(r + 1)
            elif op == 39:
                value = get(r) / get(r + 1)
                regs[r] = int(value) if type(get(r)) is type(get(r + 1)) is int else value
            elif op == 41: regs[r] = get(r) & get(r + 1)
            elif op == 46: regs[r] = get(r) == get(r + 1)
            elif op == 47: regs[r] = get(r) != get(r + 1)
            elif op == 48: regs[r] = get(r) < get(r + 1)
            elif op == 50: regs[r] = get(r) > get(r + 1)
            elif op == 54: pc = a[0]
            elif op in (55, 56):
                if bool(get(r)) == (op == 56): pc = a[0]
            elif op == 57: regs[r] = get(r + 1)(*[get(r + 2 + n) for n in range(a[0])])
            elif op == 58:
                regs[r] = get(r + 1)[get(r + 2)]
                regs.pop(r + 1, None)
            elif op == 59:
                assert a[0] & 255 == 1
                # Original dispatcher 1014B58D: value is operand >> 8;
                # its first key is value + 2, independently of the receiver.
                source = signed(a[0]) >> 8
                get(r)[get(source + 2)] = get(source)
                regs.pop(r, None)
            elif op == 60:
                name = self.module.ascii(a[0]); value = get(r + 1)
                if isinstance(value, dict) and name == 'has': regs[r] = lambda key, value=value: key in value
                else: regs[r] = value[name] if isinstance(value, dict) else getattr(value, name)
                regs.pop(r + 1, None)
            elif op == 61:
                name = self.module.ascii(a[0]); value = get(r + 1)
                regs[r] = name in value if isinstance(value, dict) else hasattr(value, name)
                regs.pop(r + 1, None)
            elif op == 63:
                for n in range(r, r + 3): regs[n] = '<CALL metadata>'
                self.calls[a[0]](regs, r)
            elif op == 65: return None, regs
            elif op in (66, 67):
                first, count = signed(a[1]) >> 8, a[1] & 255
                self.transition = (r, a[0], tuple(get(first + n) for n in range(count)))
                for n in range(count): regs.pop(first + n, None)
                if op == 66: return None, regs
            elif op == 71: regs[r] = self.named[self.module.ascii(a[0])]
            elif op == 73: self.named[self.module.ascii(a[0])] = get(r)
            elif op == 74: regs.pop(r, None)
            elif op in (75, 76, 77, 78):
                packed = [signed((word & 65535) | (0xffff0000 if word & 32768 else 0))
                          for value in a for word in (value, value >> 16)]
                for slot in [r, *packed[:op - 74]]: regs.pop(slot, None)
            else: raise AssertionError((hex(row['offset']), row))
        raise AssertionError('Instruction budget exceeded')


def table_store_encoding():
    # Pin the independent receiver/value/key windows from the original STORE
    # dispatcher, using a value register deliberately different from receiver-1.
    from patch_native_menu import Assembler
    module = Module(read_asset('Scripts\\player.bin')[0])
    start = len(module.code)
    a = Assembler(module)
    a.emit(59, 7, (2 << 8) | 1)
    a.emit(65)
    module.code += a.finish(start)
    table = {}
    VM(module).run(start, {2: 123, 4: 'selected', 6: 999, 7: table, 8: 'decoy'})
    assert table == {'selected': 123}


def body_hit_publication():
    for lang, index in (('ru', 'research/vfs-index.json'), ('de', 'research/vfs-index.german.json')):
        module = Module(read_entry(index, 'Scripts\\ui\\body.bin'))
        info = patch_body(module, lang)
        selected, enabled, published = [-1], [True], []
        zone = {str(i): [7000, 4000, 2, True] for i in range(21)}
        world = {'call': lambda method: {'Properties': {'ZoneLimfa': zone}}}
        def hit_test(method, origin, ray):
            assert method == 'hitTest' and origin == 'eye' and ray == (1290, 265)
            return selected[0]
        globals = {7: world, 8: {'call': hit_test},
                   9: {'calcVector': lambda x, y: (x, y)}, 11: {'Position': 'eye'}}
        vm = VM(module, globals, {'executeConsoleCommand': published.append})
        for selected[0] in (-1, 0, 1, 8, 9, 40, 41):
            for enabled[0] in (False, True):
                for value in zone.values(): value[3] = enabled[0]
                _, regs = vm.run(module._touch_body_hit, {-5: 1290, -4: 265})
                expected = selected[0] if selected[0] >= 0 and enabled[0] else -1
                assert regs[-6] == expected
                # This path is the existing per-frame tooltip hit, with no
                # synthetic onMouseMove. It must retain the original result.
                _, regs = vm.run(info['body_hover_publish'], {0: expected},
                                 stops=(info['body_hover_publish'] + 8,))
                assert published[-1] == 'port_body_target ' + str(expected)
                assert regs[0] == expected and regs[4] is world
        call = next(x for x in module.instructions() if x['offset'] == info['body_hover_hit'])
        assert call['operands'] == [module._touch_body_hit]


def source_transfer():
    for lang, index in (('ru', 'research/vfs-index.json'), ('de', 'research/vfs-index.german.json')):
        source_transfer_release(lang, index)


def memory_colour_event():
    for lang, index in (('ru', 'research/vfs-index.json'), ('de', 'research/vfs-index.german.json')):
        module = Module(read_entry(index, 'Scripts\\ui\\body_free_limfa.bin'))
        patch_body_counts(module, lang, 1)
        for colour in range(7):
            for down in (False, True):
                events, original_calls = [], []
                vm = VM(module, {4: colour}, {'Settings': {'PortTouchInput': type('Value', (), {'asBool': True})()}, 'isKeyPressed': lambda key: key == 0x69, 'executeConsoleCommand': events.append,
                         'Window': {'call': lambda *args: original_calls.append(args)}})
                vm.run(method(module, 'onMouseButtonLeft'), {-4: down})
                assert events == ([f'port_body_transfer_colour {colour}'] if down else [])
                assert original_calls == ([('onFreeLimfa', colour)] if down else [])


def paint_colour_widget():
    # The same guarded publisher patches body AND painting widgets. Exercise
    # the complete original select callback, not just a simulated mouse click.
    from types import SimpleNamespace
    class Mobile:
        asBool = True
    for lang, index in (('ru', 'research/vfs-index.json'), ('de', 'research/vfs-index.german.json')):
        widget = Module(read_entry(index, 'Scripts\\ui\\paint_limfa.bin'))
        patch_body_counts(widget, lang, 0)
        paint = Module(read_entry(index, 'Scripts\\ui\\paint.bin'))
        select = method(paint, 'onSetLimfa')
        highlight = next(x['operands'][0] for x in paint.instructions()
                         if x['offset'] > select and x.get('opcode') == 63)
        mobile, synthetic = Mobile(), [False]
        controls = [VM(widget, {4: i, 6: i == 0, 8: SimpleNamespace(Count=0)}) for i in range(7)]
        variables = {'LastChoosenLimfa': 0}
        callbacks = []
        def find_control(name):
            control = controls[int(name.removeprefix('alimfa'))]
            def call(method_name, active):
                assert method_name == 'setAsActive'
                control.run(method(widget, method_name), {-4: active})
            return {'call': call}
        paint_vm = VM(paint, {6: 0}, {'findControl': find_control,
                                    '__externals__': {(3, 0): {'Vars': variables}}})
        paint_vm.calls[highlight] = lambda regs, n: paint_vm.run(highlight)
        def select_colour(method_name, colour):
            assert method_name == 'onSetLimfa'
            callbacks.append(colour)
            paint_vm.run(select, {-4: colour})
        for colour in (2, 3, 0, 6, 1, 5, 4):
            control = VM(widget, {4: colour}, {
                'Settings': {'PortTouchInput': mobile},
                'isKeyPressed': lambda key: synthetic[0] and key == 0x69,
                'Window': {'call': select_colour}})
            for mobile.asBool, synthetic[0] in ((True, False), (True, True), (False, False)):
                before = len(callbacks)
                control.run(method(widget, 'onMouseButtonLeft'), {-4: True})
                allowed = not mobile.asBool or synthetic[0]
                assert len(callbacks) == before + allowed
                if allowed:
                    assert variables['LastChoosenLimfa'] == paint_vm.globals[6] == colour
                    assert [c.globals[6] for c in controls] == [i == colour for i in range(7)]
                control.run(method(widget, 'onMouseButtonLeft'), {-4: False})
                assert len(callbacks) == before + allowed


def source_transfer_release(lang, index):
    class Switch:
        def __init__(self, enabled=True): self.asBool = enabled
    module = Module(read_entry(index, 'Scripts\\ui\\body.bin'))
    original = list(module.instructions())
    patch_body(module, lang)
    info = patch_body_sources(module, lang)
    start, stop = info['source_start'], info['source_start'] + 8
    for initial_hit in (-1, 0, 1, 6, 7, 40, 41):
        for mobile in (False, True):
            for entry in (start, info['memory_put_start']):
                vm = VM(module, {info['forced_zone_global']: 0}, named={'Settings': {'PortTouchInput': Switch(mobile)}})
                end, regs = vm.run(entry, {0: initial_hit}, stops=(entry + 8,))
                expected = initial_hit // 2 * 2 if mobile and initial_hit >= 0 else initial_hit
                assert end == entry + 8 and regs[0] == expected
    # Both swipes use the original heart debit, never ActiveLimfa (the shared
    # palette). Execute the original STORE and Escape refund without modeling
    # another resource at Zone[1], which is only a recomputed capacity.
    ctor = info['heart_entry']
    debit = next(x for x in original if x['offset'] > ctor and x.get('opcode') == 59)
    debit_start = next(x['offset'] for x in reversed(original) if x['offset'] < debit['offset'] and x.get('opcode') == 10 and x['register'] == 0)
    # Start before the actual reserve read/subtract/store window.
    debit_start = debit['offset'] - 52
    update = next(x for x in original if x['offset'] > debit['offset'] and x.get('opcode') == 63)
    refund = next(m['code_offset'] for m in module.contexts[7]['methods'] if m['name'] == 'onWinKeyDown')
    for current in (0, 4000, 45741, 140000):
        taken = min(current, 12000)
        props = {'ZoneLimfa': {'4': [current, 55795, 2, True]},
                 'ActiveLimfa': {'2': 101536}, 'FreeLimfa': {'2': 108116}}
        world = {'call': lambda name: {'Properties': props}}
        externals = {(7, 0): 4, (7, 1): taken}
        vm = VM(module, {7: world}, {'__externals__': externals},
                {update['operands'][0]: lambda regs, n: None})
        vm.run(debit_start, {0: props['ZoneLimfa']['4'], 4: taken}, stops=(update['offset'],))
        assert props['ZoneLimfa']['4'][0] == current - taken
        vm.run(refund, {-5: 27, -4: False})
        assert props == {'ZoneLimfa': {'4': [current, 55795, 2, True]},
                         'ActiveLimfa': {'2': 101536}, 'FreeLimfa': {'2': 108116}}
    assert not any(m['name'] == 'onActiveLimfa' for c in module.contexts for m in c['methods']), "2009 hearts cannot feed the Palette"


def fov_and_stats():
    player = Module(read_asset('Scripts\\player.bin')[0])
    patch_player(player, 'ru')
    class Value:
        def __init__(self, value): self.asFloat = float(value)
    for selected in (40, 55, 70, 100):
        vm = VM(player, {35: 55}, {'Settings': {'PortFOV': Value(selected)}})
        _, regs = vm.run(method(player, 'getCameraFOV'))
        assert math.isclose(regs[-4], selected)
    wheel = Module(read_asset('Scripts\\ui\\body_wheel.bin')[0])
    info = patch_stats(wheel, 'ru')
    start = method(wheel, 'updateTooltip')
    original = Module(read_asset('Scripts\\ui\\body_wheel.bin')[0])
    r = [x for x in original.instructions() if x.get('symbol') == 'prepare']
    stop = next(x['offset'] - 8 for x in r if x['offset'] > start)
    values = {i: [i * 100, 1000 if i else 0] for i in range(7)}
    vm = VM(wheel, {13: values, 16: True, 19: {i: 'effect' + str(i) for i in range(7)}},
            {'isKeyPressed': lambda key: True, 'format': lambda fmt, *args: fmt.replace('%u', '%d') % args})
    end, regs = vm.run(start, stops=(stop,))
    assert end == stop
    for i in range(7): assert ('effect%d : %d%%' % (i, i * 10)) in regs[0]
    def get_colour(name, colour):
        assert name == 'getLimfaColor' and colour == 0
        return 'valid-colour'
    vm = VM(wheel, {16: True, 17: {0: 400, 1: 200}, 18: -1, info['stats_active_global']: True}, {'Width': 1920, 'Height': 1080,
            'Window': {'call': get_colour}, 'isKeyPressed': lambda key: True})
    end, regs = vm.run(method(wheel, 'renderTooltip'), stops=(2152,))
    assert regs[0] == 'valid-colour'
    assert regs[-5] == 760 and regs[-4] == 640

    # A stationary hold sends only a key; no hover event has created a tooltip.
    # Execute the real canvas creation and prepare tail instead of supplying a
    # pre-existing canvas, which previously concealed the null dimensions bug.
    for lang, index in (('ru', 'research/vfs-index.json'), ('de', 'research/vfs-index.german.json')):
        wheel = Module(read_entry(index, 'Scripts\\ui\\body_wheel.bin'))
        info = patch_stats(wheel, lang)
        held, created, prepared, updated = [False], [], [], []
        class Canvas:
            def prepare(self, text):
                prepared.append(text)
                return {0: 400, 1: 200}
        def create_canvas(font, width, height):
            created.append((font, width, height))
            return Canvas()
        state = {13: values, 15: 'font', 16: None, 17: None, 18: -1,
                 19: {i: 'effect' + str(i) for i in range(7)}, info['stats_active_global']: False}
        vm = VM(wheel, state, {'Width': 1920, 'Height': 1080,
            'Plane': {'createStringCanvas': create_canvas}, 'Window': {'call': get_colour},
            'isKeyPressed': lambda key: held[0], 'format': lambda fmt, *args: fmt.replace('%u', '%d') % args})
        def update_tooltip(regs, base):
            updated.append(True)
            vm.run(method(wheel, 'updateTooltip'))
        vm.calls[method(wheel, 'updateTooltip')] = update_tooltip
        vm.run(method(wheel, 'renderTooltip'))
        assert not created and not updated
        held[0] = True
        for _ in range(3):
            end, regs = vm.run(method(wheel, 'renderTooltip'), stops=(2152,))
            assert end == 2152 and regs[-5] == 760 and regs[-4] == 640
        assert created == [('font', 512, 320)] and len(updated) == len(prepared) == 1
        for i in range(7): assert ('effect%d : %d%%' % (i, i * 10)) in prepared[0]
        held[0] = False
        vm.run(method(wheel, 'renderTooltip'))
        assert state[16] is None and not state[info['stats_active_global']] and len(updated) == 2
        held[0] = True
        vm.run(method(wheel, 'renderTooltip'), stops=(2152,))
        assert len(created) == len(prepared) == 2 and len(updated) == 3


def published_counts():
    module = Module(read_asset('Scripts\\ui\\body_free_limfa.bin')[0])
    info = patch_body_counts(module, 'ru', 1)
    start = int(info['sites'][1], 16)
    for current, maximum in ((0, 20000), (15000, 20000), (30000, 20000), (0, 0)):
        published = []
        vm = VM(module, {4: 3}, {'format': lambda fmt, *args: fmt % args,
                                 'executeConsoleCommand': published.append})
        vm.run(start, {-5: current, -4: maximum}, stops=(start + 8,))
        assert published == ['port_colour 1 3 %d %d' % (min(current, maximum), maximum)]


def mobile_body_details():
    class Value:
        def __init__(self, value): self.asInt = value
    for lang, index in (('ru', 'research/vfs-index.json'), ('de', 'research/vfs-index.german.json')):
        body = Module(read_entry(index, 'Scripts\\ui\\body.bin'))
        patch_body(body, lang)
        patch_body_sources(body, lang)
        info = patch_body_details(body, lang)
        zone = {str(i): [45741 + i, 55795, i % 7, True] for i in range(21)}
        world = {'call': lambda name: {'Properties': {'ZoneLimfa': zone}},
                 'Properties': {'get': lambda name: {'MaxLimfa': Value(75)}}}
        state = {7: world, info['last_zone_global']: 0,
                 info['last_zone_global'] + 1: False, info['last_zone_global'] + 2: False}
        events = []
        vm = VM(body, state, {'format': lambda fmt, *args: fmt % args,
                             'executeConsoleCommand': events.append})
        vm.run(info['body_publisher'], {-4: 4})
        assert events == ['port_body_heart 4 45745 75000 4']
        # Dragging over another heart must retain the actual source's details.
        state[info['last_zone_global'] + 2] = True
        vm.run(info['body_publisher'], {-4: 5})
        assert len(events) == 1
        zone['4'][0] = 33745
        vm.run(info['body_publisher'], {-4: 4})
        assert events[-1] == 'port_body_heart 4 33745 75000 4'
        state[info['last_zone_global'] + 2] = False
        vm.run(info['body_publisher'], {-4: 5})
        assert events[-1] == 'port_body_heart 5 45746 75000 5'
        health = Module(read_entry(index, 'Scripts\\ui\\health_progress.bin'))
        patch_body_progress(health, lang)
        start = method(health, 'setProgress') + 8
        events.clear()
        VM(health, named={'format': lambda fmt, *args: fmt % args,
                         'executeConsoleCommand': events.append}).run(start, {-6: 88, -5: 0, -4: 525}, stops=(start + 8,))
        assert events == ['port_body_progress 88 525']
        wheel = Module(read_entry(index, 'Scripts\\ui\\body_wheel.bin'))
        patch_stat_details(wheel, lang)
        start = method(wheel, 'setProgress') + 8
        values = {i: [i * .1, 1 if i else 0] for i in range(7)}
        events.clear()
        VM(wheel, {19: {i: 'effect ' + str(i) for i in range(7)}},
           {'format': lambda fmt, *args: fmt % args, 'executeConsoleCommand': events.append}).run(
               start, {-4: values}, stops=(start + 8,))
        assert events == [f'port_body_stat {i} {i * 10} effect {i}' for i in range(7)]
        # The 21 overlay glyphs come directly from the release's own images.
        from tempfile import TemporaryDirectory
        from patch_scripts import dds_rgba
        from patch_touch_native import export_mobile_gestures
        from PIL import Image
        with TemporaryDirectory() as directory:
            export_mobile_gestures(index, Path(directory), read_entry, dds_rgba)
            assert len(list(Path(directory).glob('zone*.png'))) == 21
            with Image.open(Path(directory) / 'zone4.png') as image:
                assert image.mode == 'RGBA' and image.size == (128, 128)
                assert image.getchannel('A').getextrema() == (0, 255)


def live_veins():
    class Value:
        asFloat = 100
    option = Value()
    for language, index in (('ru', 'research/vfs-index.json'), ('de', 'research/vfs-index.german.json')):
        for name, patch in PATCHES:
            if patch is not patch_vein:
                continue
            module = Module(read_entry(index, name))
            info = patch_vein(module, language)
            rows = {x['offset']: x for x in module.instructions()}
            initialized, gain = info['initialized_global'], info['gain_global']
            assert list(module.types[initialized:]) == [0, 2]  # No saved channel object.
            for site in info['yield_sites']:
                calls, colors = [], []
                state = {2: 5, initialized: True, gain: 100}
                start = rows[site]['operands'][0]
                stop = next(x['offset'] for x in rows.values() if x['offset'] >= start and x.get('opcode') == 68)
                def getter(regs, n):
                    assert regs[n - 1] == 5
                    fresh_color = object()  # A transient, unserializable channel wrapper.
                    colors.append(fresh_color)
                    regs[n - 2] = fresh_color
                def colour_helper(regs, n):
                    calls.append(regs[n - 1])
                    state[gain] = option.asFloat
                vm = VM(module, state, {'Settings': {'PortVeinBrightness': option}},
                        {info['colour_getter']: getter, info['material_helper']: colour_helper})
                option.asFloat = 100
                for _ in range(3): vm.run(start, stops=(stop,))
                assert not calls and not colors
                option.asFloat = 400
                for _ in range(3): vm.run(start, stops=(stop,))
                assert len(calls) == 1 and calls == colors
                assert type(state[initialized]) is bool and type(state[gain]) in (int, float)
                state[initialized] = False
                option.asFloat = 200
                vm.run(start, stops=(stop,))
                assert len(calls) == len(colors) == 1


def accepted_map_path():
    class Path(list):
        @property
        def Count(self): return len(self)
    for language, index in (('ru', 'research/vfs-index.json'), ('de', 'research/vfs-index.german.json')):
        module = Module(read_entry(index, 'Scripts\\world\\world.bin'))
        original = list(module.instructions())
        start = method(module, 'onSetPath')
        transition = next(x['offset'] for x in original if x['offset'] > start and x.get('opcode') == 67)
        patch_map(module, language)
        for path in ([], [3], [2, 3], [3, 4], [3, 4, 5]):
            events = []
            vm = VM(module, named={'executeConsoleCommand': events.append, '__externals__': {(110, 0): 3}})
            end, regs = vm.run(start, {-7: Path(path), -6: 'points', -5: 7, -4: -1}, stops=(transition,))
            accepted = len(path) >= 2 and path[0] == 3
            assert events == (['port_path_ready'] if accepted else [])
            if accepted:
                assert end == transition and regs[0] == path and regs[1] == 'points' and regs[2] == 7
            else:
                assert end is None


def rejected_map_rearm():
    class StrokeVector:
        pass
    for language, index in (('ru', 'research/vfs-index.json'), ('de', 'research/vfs-index.german.json')):
        module = Module(read_entry(index, 'Scripts\\ui\\map.bin'))
        original = list(module.instructions())
        info = patch_map_rearm(module, language)
        dispatch = next(x for x in original if x['offset'] < info['rearm_tail'] and
                        x.get('opcode') == 57 and x['offset'] > info['rearm_tail'] - 64)
        cleanup = [x['operands'][0] for x in original if dispatch['offset'] < x['offset'] < info['rearm_tail']
                   and x.get('opcode') == 63]
        assert len(cleanup) == 3
        held = [True]
        events, cleaned = [], []
        def clean(regs, n): cleaned.append(True)
        state = {info['pending_global']: False}
        vm = VM(module, state, {'isKeyPressed': lambda key: held[0] if key == 0x1d else False},
                calls={offset: clean for offset in cleanup})
        for down in (True, True, False):
            held[0] = down
            args = {5: None, 6: lambda *args: events.append(args)}
            args.update({7 + n: n for n in range(6)})
            _, remaining = vm.run(dispatch['offset'], args)
            # Deferred opcode67 must keep the original base destination and
            # execute its following cleanup, even when retrying immediately.
            assert vm.transition == (2, info['released_ctor'], ())
            assert 1 not in remaining and 3 not in remaining
            assert state[info['pending_global']] == down
            vm.run(info['rearm_ready'])
            assert vm.transition == ((6, info['armed_ctor'], ()) if down else
                                     (info['base_loop_context'], info['base_loop_ctor'], ()))
            assert not state[info['pending_global']]
        assert len(events) == 3 and len(cleaned) == 9
        # Acceptance/release can arrive between completion and base setup.
        state[info['pending_global']], held[0] = True, False
        vm.run(info['rearm_ready'])
        assert vm.transition == (info['base_loop_context'], info['base_loop_ctor'], ())
        # Reproduce the old crash by executing the original camera-loop branch.
        # Direct stroke8->child6 preserved ctx3.field1 as a stroke vector. The
        # original base2 reconstruction type-initializes its24slots first.
        camera = [x['operands'][0] for x in original if x['offset'] > info['armed_ctor'] and
                  x.get('opcode') == 63][1]
        position = next(x for x in original if x.get('symbol') == 'Position' and
                        x.get('opcode') == 60 and x['offset'] > camera)
        guard = max(x['offset'] for x in original if x['offset'] < position['offset'] and
                    x.get('opcode') == 12 and x['register'] == 1 and x['operands'] == [3, 3])
        skip = next(x['operands'][0] for x in original if x['offset'] == guard + 12)
        externals = {(3, 0): .5, (3, 1): StrokeVector()}
        broken = VM(module, named={'__externals__': externals})
        try:
            broken.run(guard, stops=(skip,))
        except AttributeError as error:
            assert 'Position' in str(error)
        else:
            raise AssertionError('Original tracked-entity.Position crash must reproduce')
        defaults = {0: False, 1: 0, 2: 0., 3: None}
        assert module.contexts[2]['nslots'] == 24
        externals = {(3, n): defaults[t] for n, t in enumerate(module.contexts[2]['types'])}
        player = {'Position': {'x': 1, 'z': 2}}
        world = {'Vars': {'LastChoosenLimfa': 2}, 'call': lambda name: player}
        world_slot = next(x['register'] for x in original if x['offset'] > info['base_initializer'] and
                          x.get('opcode') == 14)
        state = {world_slot: world}
        named = {'__externals__': externals, '!table': dict,
                 'Plane': {'loadImage': lambda name: object(), 'loadFont': lambda name: object()}}
        ctor_vm = VM(module, state, named)
        # Run the complete original parent initializer, not just its transition.
        ctor_vm.run(info['base_initializer'], {-4: False})
        assert externals[3, 1] is None and externals[3, 8] is player
        setup = next(x['operands'][0] for x in original if x['offset'] > info['armed_ctor'] and x.get('opcode') == 63)
        setup_end = next(x['offset'] for x in original if x.get('header') and x['offset'] > setup)
        setup_calls = [x['operands'][0] for x in original if setup < x['offset'] < setup_end and x.get('opcode') == 63]
        ctor_vm.calls = {target: lambda regs, n: None for target in setup_calls}
        ctor_vm.run(setup, {-4: world})
        assert externals[7, 0] is world and externals[7, 1] is player
        # The exact original failing Position branch now takes its null guard.
        end, _ = ctor_vm.run(guard, stops=(skip,))
        assert end == skip


def harvest_scripts():
    total = 0
    for index, language in (('research/vfs-index.json', 'ru'), ('research/vfs-index.german.json', 'de')):
        for name, patch in PATCHES:
            if patch is not patch_harvest_stop:
                continue
            module = Module(read_entry(index, name))
            info = patch(module, language)
            instructions = list(module.instructions())
            rows = {x['offset']: x for x in instructions}
            for site in info['harvest_stop_calls']:
                frame = max((x for x in instructions if x.get('header') and x['offset'] < site),
                            key=lambda x: x['offset'])['frame_slots'] - 3
                start = rows[site]['operands'][0]
                stop = next(x['offset'] for x in instructions if x['offset'] >= start and
                            x.get('opcode') == 57 and x['register'] < frame)
                marker = []
                vm = VM(module, named={'executeConsoleCommand': marker.append})
                original = {n: 900 + n for n in range(frame)}
                end, regs = vm.run(site, original, stops=(stop,))
                assert marker == ['port_harvest_stop'] and end == stop
                assert regs == original
                total += 1
    assert total >= 70, total


def live_brush():
    class Table(dict):
        def __setitem__(self, key, value):
            # The real CScriptTable setter rejects a numeric first argument.
            assert isinstance(key, str), ('invalid table key', key)
            super().__setitem__(key, value)
    module = Module(read_asset('Scripts\\player.bin')[0])
    info = patch_brush_live(module, 'ru')
    cache = info['brush_cache_global']
    state = {cache: 0, cache + 1: 0, cache + 2: 0, cache + 3: False}
    variables = Table(LastChoosenLimfa=5)
    active = {str(i): 0 for i in range(7)}
    active['5'] = 35532
    world = {'Vars': variables, 'call': lambda name: {'Properties': {'ActiveLimfa': active}}}
    published, capacities, formats = [], [], []
    maximum = [50000]
    def capacity(regs, n):
        assert regs[n - 1] is world
        capacities.append(True)
        regs[n - 2] = maximum[0]
    def format_(fmt, *args):
        formats.append(args)
        return fmt % args
    vm = VM(module, state, {'World': world, 'format': format_, 'executeConsoleCommand': published.append},
            {info['capacity_helper']: capacity})
    for _ in range(100): vm.run(info['brush_publisher'])
    assert published == ['port_brush 5 35532 50000']
    assert len(capacities) == len(formats) == 1
    assert variables['PortActiveCapacity'] == 50000
    active['5'] = 40000
    vm.run(info['brush_publisher'])
    assert published[-1] == 'port_brush 5 40000 50000' and len(formats) == 2
    variables['LastChoosenLimfa'] = 0
    vm.run(info['brush_publisher'])
    assert published[-1] == 'port_brush 0 0 50000'
    active['0'] = 100000
    vm.run(info['brush_publisher'])
    assert published[-1] == 'port_brush 0 50000 50000'
    variables['PortActiveCapacity'] = 0
    maximum[0] = 75000
    vm.run(info['brush_publisher'])
    assert published[-1] == 'port_brush 0 75000 75000' and len(capacities) == 2
    world_module = Module(read_asset('Scripts\\world\\world.bin')[0])
    original_size = len(world_module.code)
    capacity_info = patch_brush_capacity(world_module, 'ru')
    stop = next(x['offset'] for x in world_module.instructions() if x['offset'] >= original_size and x.get('symbol') == '!vector')
    vm = VM(world_module, named={'Vars': variables})
    vm.run(int(capacity_info['sites'][0], 16), stops=(stop,))
    assert variables['PortActiveCapacity'] == 0


if __name__ == '__main__':
    native_probe()
    table_store_encoding()
    body_hit_publication()
    source_transfer()
    memory_colour_event()
    paint_colour_widget()
    fov_and_stats()
    published_counts()
    mobile_body_details()
    live_veins()
    accepted_map_path()
    rejected_map_rearm()
    harvest_scripts()
    live_brush()
    print('PASS real native analog/ABI/console bounds; heart reserve debit/refund, both destination clamps; body details/progress/statistics/glyphs; FOV/map/veins')
