"""Append native gscript menu states to a pinned, locally owned game asset."""
import copy
import hashlib
import json
import struct
from xml.etree import ElementTree as ET
from pathlib import Path

from gscript_binary import Module, read_asset, p32

ORIGINAL_SHA256 = 'f2abbdc15d9fefbd9b7b974e8980f66f15026438eb99bb556225696abe205169'
DEBUG_CONTEXT = 18
CONFIG_CONTEXT = 19
DEBUG_KEY = 'DebugInterface'
PROFILES_SHA256 = '9059f1eee5687a25ca116365a70939175d93dbc387a113043427a14de037ca5f'
MINIMUM_VIDEO = {'PortWidth':800, 'PortHeight':600, 'PortRefreshRate':0,
    'PortVSync':0, 'PortHDR':1, 'PortAntialiasing':0, 'PortAnisotropy':0,
    'PortTextureQuality':1, 'PortLightmapQuality':2}

# Values are the original Config.exe XML values. TextureQuality is bounded to
# 0..1 at 00454669; LightmapQuality to 0..2 at 004546B4.
CONFIG_ROWS = [
    ('Resolution', 'PortWidth', [], None),
    ('Refresh rate', 'PortRefreshRate', [], None),
    ('VSync', 'PortVSync', [0, 1], ['Off', 'On']),
    ('HDR', 'PortHDR', [0, 1, 2], ['Disabled', 'Simplified', 'Full']),
    ('Antialiasing', 'PortAntialiasing', [], None),
    ('Anisotropic filtering', 'PortAnisotropy', [], None),
    ('Texture quality', 'PortTextureQuality', [0, 1], ['High', 'Low']),
    ('Lightmap quality', 'PortLightmapQuality', [0, 1, 2], ['High', 'Medium', 'Low']),
    ('Audio quality', 'PortSoundRate', [22, 44], ['Low (22 kHz)', 'High (44 kHz)']),
]
DYNAMIC_COMMANDS = {0:'NextResolution',1:'NextRefresh',4:'NextAA',5:'NextAF'}


def generate_profiles():
    directory = Path(json.loads(Path('research/vfs-index.json').read_text())['source'])
    raw = (directory/'profiles.xml').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == PROFILES_SHA256
    root = ET.fromstring(raw)
    assert root.tag == 'Profiles'
    profiles = []
    for entry in root:
        assert entry.find('Memory') is None, 'Shipped table has no memory tiers'
        values = dict(name=entry.tag, vendor=int(entry.findtext('Vendor'),10),
            models=entry.findtext('Model'), search=entry.findtext('Search'),
            width=int(entry.findtext('Resolution/Width','800')),
            height=int(entry.findtext('Resolution/Height','600')),
            vsync=int(entry.find('VSync') is not None),
            hdr=0 if entry.find('HDR') is None else 1+int(bool(int(entry.findtext('HDR')))),
            aa=int(entry.findtext('Antialiasing','0')),af=int(entry.findtext('Anisotropy','0')),
            texture=min(1,int(entry.findtext('TextureQuality','1'))),
            lightmap=min(2,int(entry.findtext('LightmapQuality','2'))))
        profiles.append(values)
    lines = ['#ifndef VOID_MENU_PROFILES_H','#define VOID_MENU_PROFILES_H',
        'typedef struct VoidGPUProfile { const char *name; unsigned vendor; const char *models, *search;',
        '  int width,height,vsync,hdr,aa,af,texture,lightmap; } VoidGPUProfile;',
        'static const VoidGPUProfile void_gpu_profiles[] = {']
    for p in profiles:
        strings=[json.dumps(p[k],ensure_ascii=True) for k in ['name','models','search']]
        values=','.join(str(p[k]) for k in ['width','height','vsync','hdr','aa','af','texture','lightmap'])
        lines.append('{'+strings[0]+','+str(p['vendor'])+','+strings[1]+','+strings[2]+','+values+'},')
    lines += ['};', '#define VOID_GPU_PROFILE_COUNT '+str(len(profiles)),
        '#define VOID_GPU_PROFILE_SHA256 "'+PROFILES_SHA256+'"',
        'static const char void_gpu_profiles_source[] =']
    lines += [json.dumps(raw[n:n+512].decode('ascii')) for n in range(0,len(raw),512)]
    lines += [';', '#endif']
    Path('build/native-ui').mkdir(parents=True,exist_ok=True)
    Path('build/native-ui/menu_profiles.h').write_text('\n'.join(lines)+'\n',encoding='ascii')
    Path('build/native-ui/profiles.json').write_text(json.dumps(dict(source=str(directory/'profiles.xml'),
        sha256=PROFILES_SHA256,profiles=profiles),indent=2))
    return profiles


class Assembler:
    def __init__(self, module, slots=16):
        self.module = module
        self.slots = slots
        self.data = bytearray()
        self.labels = {}
        self.fixups = []

    def emit(self, op, reg=0, *args):
        offset = len(self.data)
        self.data += p32((reg << 8) | self.module.opcode(op))
        for arg in args:
            if isinstance(arg, str):
                self.fixups.append((len(self.data), arg))
                self.data += p32(0)
            else:
                self.data += p32(arg)
        return offset

    def label(self, name):
        assert name not in self.labels
        self.labels[name] = len(self.data)

    def finish(self, base):
        for offset, label in self.fixups:
            struct.pack_into('<I', self.data, offset, base + self.labels[label])
        return bytes(self.data)

    def raw(self, data):
        self.data += data

    def pool(self, text, wide=False):
        data = text.encode('utf-16le' if wide else 'ascii')
        if not wide:
            data += b'\0'
        offset = len(self.module.pool)
        self.module.pool += data
        return offset

    def string(self, reg, value):
        self.emit(3, reg, len(value), self.pool(value, True))

    def integer(self, reg, value):
        self.emit(1, reg, value)

    def move(self, source, dest):
        self.emit(10, source, dest)

    def clear(self, *regs):
        for reg in regs:
            self.emit(74, reg)

    def global_(self, reg, name):
        self.emit(71, reg, self.pool(name))

    def member(self, reg, name):
        self.emit(60, reg, self.pool(name))

    def native(self, reg, count):
        self.emit(57, reg, count)

    def vec2(self, reg, x, y):
        self.global_(reg + 1, '!vec2')
        self.integer(reg + 2, x)
        self.integer(reg + 3, y)
        self.native(reg, 2)
        self.clear(reg + 1, reg + 2, reg + 3)

    def helper_begin(self, name):
        self.emit(14, 17, 2)
        self.member(1, 'call')
        self.clear(2)
        self.string(2, name)

    def helper_end(self, count, keep=False):
        self.native(0, count + 1)
        self.clear(*range(1, self.slots))
        if not keep:
            self.clear(0)

    def helper(self, name):
        self.helper_begin(name)
        self.helper_end(0)

    def log_marker(self, text, slot=0):
        # A native call uses these three slots only. Script CALL would place
        # metadata into the register window and overwrite neighboring values.
        assert slot + 3 <= self.slots
        self.global_(slot + 1, 'logInfo')
        self.string(slot + 2, '[void-menu] ' + text)
        self.native(slot, 1)
        self.clear(slot, slot + 1, slot + 2)

    def get_setting(self, key, dest=0, conversion='asInt'):
        self.global_(dest + 2, 'Settings')
        self.string(dest + 3, key)
        self.emit(58, dest + 1, 1)
        self.clear(dest + 3)
        self.member(dest, conversion)
        self.clear(dest + 1, dest + 2)

    def set_setting(self, key):
        self.emit(20, 0)
        self.global_(1, 'Settings')
        self.string(2, key)
        self.emit(59, 1, 1)
        self.clear(0, 1, 2)

    def execute(self, command):
        self.global_(1, 'executeConsoleCommand')
        self.string(2, command)
        self.native(0, 1)
        self.clear(0, 1, 2)

    def formatted_command(self, pattern, keys):
        self.join_values(pattern, keys)
        self.move(0, 2)
        self.global_(1, 'executeConsoleCommand')
        self.native(0, 1)
        self.clear(*range(12))

    def join_values(self, pattern, keys):
        # Use the VM's original string conversion/concatenation instructions.
        # No formatter grammar or variadic native binding is needed here.
        parts = pattern.split('%d')
        assert len(parts) == len(keys) + 1
        self.string(0, parts[0])
        for key, suffix in zip(keys, parts[1:]):
            self.get_setting(key, 1)
            self.emit(20, 1)
            self.emit(36, 0)
            self.string(1, suffix)
            self.emit(36, 0)
        self.clear(1)

    def save(self):
        self.global_(1, 'saveSettings')
        self.native(0, 0)
        self.clear(0, 1)

    def map_init(self):
        self.global_(1, '!vector')
        self.native(0, 0)
        self.emit(18, 0)
        self.emit(11, 0, 0, 1)
        self.clear(0, 1)

    def map_add(self, action):
        self.emit(12, 0, 2, 1)
        self.member(1, 'add')
        self.clear(2)
        self.integer(2, action)
        self.native(0, 1)
        self.clear(0, 1, 2)

    def label_text(self, text, x, y, anchor=1):
        self.helper_begin('createLabel')
        self.string(3, text)
        self.vec2(4, x, y)
        self.integer(5, anchor)
        self.helper_end(3)

    def label_setting(self, title, key, x, y, values=None, names=None):
        if names:
            self.get_setting(key)
            for i, (value, name) in enumerate(zip(values, names)):
                self.move(0, 1)
                self.integer(2, value)
                self.emit(46, 1)
                self.emit(55, 1, f'choice_next_{key}_{i}')
                self.label_text(f'{title}: {name}', x, y)
                self.emit(54, 0, f'choice_end_{key}')
                self.label(f'choice_next_{key}_{i}')
            self.label_text(f'{title}: Default', x, y)
            self.label(f'choice_end_{key}')
            self.clear(0, 1, 2)
            return
        self.join_values(title + ': %d', [key])
        self.move(0, 3)
        self.helper_begin('createLabel')
        self.vec2(4, x, y)
        self.integer(5, 1)
        self.helper_end(3)

    def button(self, action, x, y, tooltip, image='ui/diary_quest_arrow_up', scale=.5, anchor=1):
        self.helper_begin('createButton')
        self.string(3, image)
        self.vec2(4, x, y)
        self.integer(5, anchor)
        self.emit(2, 6, struct.unpack('<I', struct.pack('<f', scale))[0])
        self.string(7, tooltip)
        self.helper_end(5)
        self.map_add(action)

    def page_loop(self):
        self.label('loop')
        self.emit(68)
        self.emit(16)
        self.move(0, 2)
        self.emit(63, 3, 0x416c)
        self.emit(14, 17, 2)
        self.emit(55, 2, 'loop')
        self.emit(14, 17, 3)
        self.move(0, 4)
        self.native(2, 1)
        self.clear(2, 3, 4)
        self.emit(54, 0, 'loop')

    def cycle(self, key, values):
        self.get_setting(key)
        for i, value in enumerate(values):
            self.move(0, 1)
            self.integer(2, value)
            self.emit(46, 1)
            self.emit(55, 1, f'cycle_next_{key}_{i}')
            self.integer(0, values[(i + 1) % len(values)])
            self.emit(54, 0, f'cycle_done_{key}')
            self.label(f'cycle_next_{key}_{i}')
        self.integer(0, values[0])
        self.label(f'cycle_done_{key}')
        self.set_setting(key)


def append(module, assembler, slots=None):
    offset = len(module.code)
    if slots is not None:
        module.code += p32(0xffffffff) + p32(slots)
    module.code += assembler.finish(len(module.code))
    return offset


def make_page(module, kind, profiles):
    a = Assembler(module)
    a.helper('destroyControls')
    a.map_init()
    if kind == 'debug':
        a.label_text('Debug', 170, 75)
        a.label_setting('Colour', 'PortDebugColour', 170, 150,
            list(range(7)), ['Silver', 'Crimson', 'Amber', 'Azure', 'Violet', 'Emerald', 'Gold'])
        a.button(0, 100, 140, 'Choose colour')
        a.label_setting('Amount', 'PortDebugAmount', 170, 220)
        a.button(1, 100, 210, 'Choose amount')
        for action, text in [(2, 'Add colour to Memory'), (3, 'Add colour to Palette'),
                             (4, 'Open all hearts / give colour'), (5, 'Toggle god mode'),
                             (6, 'Open all chambers')]:
            y = 290 + 70*(action-2)
            a.label_text(text, 170, y)
            a.button(action, 100, y-10, text)
    else:
        a.label_text('Graphics and audio', 170, 65)
        a.label_text('Changes apply on next launch', 170, 110)
        a.get_setting('PortAAModeCount')
        a.integer(1,-1)
        a.emit(46,0)
        a.emit(55,0,'capabilities_available')
        a.label_text('GPU capabilities unavailable',170,140)
        a.label('capabilities_available')
        for action, (title, key, values, names) in enumerate(CONFIG_ROWS):
            y = 170 + action*65
            if action == 0:
                a.join_values('Resolution: %d x %d (%d supported)', ['PortWidth', 'PortHeight','PortModeCount'])
                a.move(0, 3)
                a.helper_begin('createLabel')
                a.vec2(4, 170, y)
                a.integer(5, 1)
                a.helper_end(3)
            else:
                a.label_setting(title, key, 170, y, values, names)
            a.button(action, 100, y-10, 'Change '+title)
        a.label_text('Autodetect', 170, 755)
        a.button(9, 100, 745, 'Detect original GPU profile')
        a.label_setting('Detected profile','PortAutoProfile',170,805,
            [-1,0]+list(range(1,len(profiles)+1)),
            ['Minimum (unlisted GPU)','Not detected']+[p['name'] for p in profiles])
    a.label_text('Return', 170, 840)
    a.button(99, 100, 830, 'Return to menu')
    a.page_loop()
    return append(module, a, 16)


def make_return(module):
    a = Assembler(module, 12)
    a.helper('destroyControls')
    a.emit(67, 1, 0x8c48, 0)
    a.emit(65)
    return append(module, a, 12)


def make_key(module, back):
    a = Assembler(module)
    a.move(-5, 0)
    a.integer(1, 27)
    a.emit(46, 0)
    a.emit(55, 0, 'end')
    a.move(-4, 0)
    a.emit(56, 0, 'end')
    a.emit(63, 0, back)
    a.label('end')
    a.emit(65)
    return append(module, a, 4)


def make_click(module, context, constructor, back, kind):
    a = Assembler(module)
    a.move(-4, 0)
    a.emit(55, 0, 'end')
    a.helper_begin('handleMouseButtonLeft')
    a.move(-6, 3)
    a.move(-5, 4)
    a.move(-4, 5)
    a.helper_end(3, keep=True)
    a.emit(16, 0)
    a.move(0, 12)
    a.integer(1, -1)
    a.emit(50, 0)
    a.emit(55, 0, 'end')
    a.move(12, 0)
    a.emit(12, 0, 2, 1)
    a.move(0, 3)
    a.emit(58, 1, 1)
    a.emit(16, 1)
    a.move(1, 12)
    a.clear(*range(12))
    for action in [99] + list(range(7 if kind == 'debug' else len(CONFIG_ROWS)+1)):
        a.move(12, 0)
        a.integer(1, action)
        a.emit(46, 0)
        a.emit(55, 0, f'next_{action}')
        if action == 99:
            a.emit(63, 0, back)
        elif kind == 'debug':
            if action == 0:
                a.cycle('PortDebugColour', list(range(7)))
            elif action == 1:
                a.cycle('PortDebugAmount', [50, 100, 200, 500])
            elif action in [2, 3]:
                a.formatted_command('/add_fl %d %d' if action == 2 else '/add_al %d %d',
                                    ['PortDebugColour', 'PortDebugAmount'])
            else:
                a.execute({4: '/giveall', 5: '/god', 6: '/openall'}[action])
            a.save()
            a.emit(67, context, constructor, 0)
        else:
            if action == len(CONFIG_ROWS):
                a.execute('port_config Autodetect 1')
            elif action in DYNAMIC_COMMANDS:
                a.execute('port_config '+DYNAMIC_COMMANDS[action]+' 1')
            else:
                title, key, values, names = CONFIG_ROWS[action]
                a.cycle(key, values)
                command_key = 'SoundRate' if key == 'PortSoundRate' else key[4:]
                a.formatted_command('port_config '+command_key+' %d', [key])
            a.save()
            a.emit(67, context, constructor, 0)
        a.emit(54, 0, 'end')
        a.label(f'next_{action}')
    a.label('end')
    a.clear(12)
    a.emit(65)
    return append(module, a, 16)


def build(audio_diagnostics=False):
    profiles = generate_profiles()
    data, source = read_asset('Scripts\\ui\\main_menu.bin')
    assert source['sha256'] == ORIGINAL_SHA256
    module = Module(data)
    original_code = bytes(module.code)
    original_pool = bytes(module.pool)
    assert len(module.contexts) == DEBUG_CONTEXT
    assert len(list(module.instructions())) == 9713
    patches = []

    def patch(offset, replacement):
        assert len(replacement) == 8
        old = bytes(module.code[offset:offset+8])
        assert old == original_code[offset:offset+8]
        module.code[offset:offset+8] = replacement
        patches.append(dict(offset=hex(offset), original=old.hex(), replacement=replacement.hex()))

    debug_ctor = make_page(module, 'debug', profiles)
    config_ctor = make_page(module, 'config', profiles)
    back = make_return(module)
    key = make_key(module, back)
    debug_click = make_click(module, DEBUG_CONTEXT, debug_ctor, back, 'debug')
    config_click = make_click(module, CONFIG_CONTEXT, config_ctor, back, 'config')
    for click in [debug_click, config_click]:
        context = copy.deepcopy(module.contexts[1])
        for method in context['methods']:
            if method['name'] == 'onMouseButtonLeft': method['code_offset'] = click
            if method['name'] == 'onWinKeyDown': method['code_offset'] = key
        context['methods'].append(dict(name='onReturn', args=0, signature=[],
                                      link=0xffffffff, code_offset=back))
        module.contexts.append(context)

    # Add a pause-only debug button once, before the original cursor setup.
    a = Assembler(module, 8)
    a.emit(14, 15, 0)
    a.emit(55, 0, 'resume')
    a.get_setting(DEBUG_KEY, conversion='asBool')
    a.emit(55, 0, 'resume')
    a.button(7, 1040, 900, 'Debug', image='ui/diary_quest_arrow_up', scale=.75)
    a.label_text('Debug', 1140, 920)
    a.label('resume')
    a.raw(original_code[0x943c:0x9444])
    a.emit(54, 0, 0x9444)
    patch(0x943c, p32(54)+p32(append(module, a)))

    # Route only new action7; preserve the original action chain.
    a = Assembler(module, 6)
    a.move(1, 2)
    a.integer(3, 7)
    a.emit(46, 2)
    a.emit(55, 2, 'resume')
    a.helper('destroyControls')
    a.emit(67, DEBUG_CONTEXT, debug_ctor, 0)
    a.emit(54, 0, 0x525c)
    a.label('resume')
    a.raw(original_code[0x4f38:0x4f40])
    a.emit(54, 0, 0x4f40)
    patch(0x4f38, p32(54)+p32(append(module, a)))

    # Reuse the original checkbox construction, shift it down one row, and
    # append a Graphics/audio entry to the Audio options page's action map.
    # This is an inline trampoline in original C2B0, whose frame is R0..R9.
    # It must not clear a fictional additional slot beyond that caller frame.
    a = Assembler(module, 10)
    checkbox = bytearray(original_code[0xc738:0xc804])
    # Mode0 positions are measured from the viewport center with upward Y.
    for site, value in [(0xc774+4,135),
                        (0xc798+4,len(DEBUG_KEY)), (0xc798+8,a.pool(DEBUG_KEY,True)),
                        (0xc7ec+4,4)]:
        struct.pack_into('<I', checkbox, site-0xc738, value)
    if audio_diagnostics:
        a.log_marker('Audio extension begin')
        # The copied original geometry leaves R6..R8 dead. The helper callable,
        # sprite, position and anchor in R1..R5 must remain intact.
        a.raw(checkbox[:0xc790-0xc738])
        a.log_marker('Audio checkbox geometry ready', 6)
        a.raw(checkbox[0xc790-0xc738:0xc7b0-0xc738])
        # IndexGet's R7 is live for asBool; preserve it in dead R0 while the
        # native logger uses R7..R9. MOV copies/refcounts the original value.
        a.move(7, 0)
        a.log_marker('Audio DebugInterface index returned', 7)
        a.move(0, 7)
        a.clear(0)
        a.raw(checkbox[0xc7b0-0xc738:0xc7bc-0xc738])
        a.log_marker('Audio DebugInterface asBool ready', 7)
        a.raw(checkbox[0xc7bc-0xc738:])
        a.log_marker('Audio visibility checkbox ready')
    else:
        a.raw(checkbox)
    a.label_text('Show debug menu', 512, 18, anchor=0)
    if audio_diagnostics: a.log_marker('Audio visibility label ready')
    a.helper_begin('createButton')
    a.string(3, 'ui/diary_quest_arrow_up')
    a.vec2(4, 700, 850)
    a.integer(5, 1)
    a.emit(2, 6, struct.unpack('<I', struct.pack('<f', .75))[0])
    a.string(7, 'Graphics and audio settings')
    a.helper_end(5)
    if audio_diagnostics: a.log_marker('Audio Graphics button ready')
    a.emit(12, 0, 2, 7)
    a.member(1, 'add')
    a.clear(2)
    a.integer(2, 5)
    a.native(0, 1)
    a.clear(0, 1, 2)
    a.label_text('Graphics and audio', 820, 895)
    if audio_diagnostics: a.log_marker('Audio extension complete')
    a.raw(original_code[0xc894:0xc89c])
    a.emit(54, 0, 0xc89c)
    patch(0xc894, p32(54)+p32(append(module, a)))

    # New checkbox/action handling runs only after the original pressed-state
    # and hit-test guards in the Audio handler.
    a = Assembler(module, 10)
    for action in [4, 5]:
        a.move(1, 2)
        a.integer(3, action)
        a.emit(46, 2)
        a.emit(55, 2, f'next_{action}')
        if action == 5:
            # Commit the original Audio controls, including the new visibility
            # checkbox, and remove the Options Return/Default child controls.
            a.emit(64, 0, 0)
            cleanup = bytearray(original_code[0xc1e0:0xc270])
            new_base = len(module.code) + len(a.data)
            for site in [0xc1ec+4, 0xc234+4]:
                target = struct.unpack_from('<I', cleanup, site-0xc1e0)[0]
                struct.pack_into('<I', cleanup, site-0xc1e0, new_base+target-0xc1e0)
            a.raw(cleanup)
            a.helper('destroyControls')
            a.emit(67, CONFIG_CONTEXT, config_ctor, 0)
        else:
            original = bytearray(original_code[0xafb4:0xb044])
            new_base = len(module.code) + len(a.data)
            for site in [0xafd4+4, 0xaffc+4]:
                struct.pack_into('<I', original, site-0xafb4, 1)
            for site in [0xb014+4,0xb024+4]:
                target = struct.unpack_from('<I', original, site-0xafb4)[0]
                struct.pack_into('<I', original, site-0xafb4, new_base+target-0xafb4)
            a.raw(original)
        a.emit(54, 0, 0xb044)
        a.label(f'next_{action}')
    a.raw(original_code[0xaf98:0xafa0])
    a.emit(54, 0, 0xafa0)
    patch(0xaf98, p32(54)+p32(append(module, a)))

    # Original apply routine B15C has exactly four local slots, R0..R3.
    a = Assembler(module, 4)
    a.helper_begin('getCheckBoxState')
    a.integer(3, 1)
    a.helper_end(1, keep=True)
    a.emit(16, 0)
    a.set_setting(DEBUG_KEY)
    a.raw(original_code[0xb3a0:0xb3a8])
    a.emit(54, 0, 0xb3a8)
    patch(0xb3a0, p32(54)+p32(append(module, a)))

    payload = module.encode()
    check = Module(payload)
    rows = list(check.instructions())
    assert check.debug == Module(data).debug
    assert check.pool[:len(original_pool)] == original_pool
    allowed = {int(p['offset'],16)+n for p in patches for n in range(8)}
    assert all(i in allowed or value==original_code[i]
               for i,value in enumerate(check.code[:len(original_code)]))
    output = Path('build/runtime-assets/Scripts/ui/main_menu.bin')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    receipt = dict(status='GENERATED_NOT_LIVE_VERIFIED', source=source,
        payload=str(output.resolve()), sha256=hashlib.sha256(payload).hexdigest(),
        original_code_preserved_except=patches, original_pool_prefix='PASS',
        original_debug_tail='PASS', metadata_roundtrip='PASS',
        original_contexts=18, contexts=len(check.contexts), instructions=len(rows),
        debug_context=DEBUG_CONTEXT, config_context=CONFIG_CONTEXT,
        debug_constructor=hex(debug_ctor), config_constructor=hex(config_ctor),
        visibility_setting=DEBUG_KEY, config_rows=CONFIG_ROWS,
        commands=['/add_fl %d %d','/add_al %d %d','/giveall','/god','/openall'],
        apply='Renderer/audio configuration applies on next launch',
        profiles_sha256=PROFILES_SHA256,profile_count=len(profiles),
        autodetect='Original ordered Vendor/Model then case-sensitive suffix Search; native D3D9 caps and modes',
        dynamic_commands=DYNAMIC_COMMANDS,
        audio_diagnostics=audio_diagnostics,
        pending='Actual native VM / UI validation, layout and Config backend integration')
    Path('build/native-ui/patch-receipt.json').write_text(json.dumps(receipt,indent=2))
    Path('build/native-ui/menu_asset.h').write_text(
        '#ifndef VOID_MENU_ASSET_H\n#define VOID_MENU_ASSET_H\n'
        '#define VOID_MENU_ASSET_SHA256 "'+receipt['sha256']+'"\n#endif\n', encoding='ascii')
    print(json.dumps(receipt, indent=2))
    return check, receipt


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--diagnostic-audio', action='store_true',
                        help='Log native Audio extension stages with bounded register use')
    build(audio_diagnostics=parser.parse_args().diagnostic_audio)
