"""Decode the delivered menu bytes and exercise the appended instruction paths.

This bounded VM model checks the data/control transfer of the new bytecode. It
does not replace the mandatory real game rendering/input smoke test.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from gscript_binary import Module, read_asset
from patch_native_menu import ORIGINAL_SHA256, CONFIG_ROWS, MINIMUM_VIDEO, DYNAMIC_COMMANDS, PROFILES_SHA256


def signed(value, bits=32):
    return value if value < 1 << (bits-1) else value - (1 << bits)


original_bytes, provenance = read_asset('Scripts\\ui\\main_menu.bin')
original = Module(original_bytes)
payload = (ROOT/'build/runtime-assets/Scripts/ui/main_menu.bin').read_bytes()
module = Module(payload)
receipt = json.loads((ROOT/'build/native-ui/patch-receipt.json').read_text())
rows = {r['offset']:r for r in module.instructions()}
old_rows = {r['offset']:r for r in original.instructions()}
assert provenance['sha256'] == ORIGINAL_SHA256
assert hashlib.sha256(payload).hexdigest() == receipt['sha256']
assert '#define VOID_MENU_ASSET_SHA256 "'+receipt['sha256']+'"' in (ROOT/'build/native-ui/menu_asset.h').read_text()
profiles=json.loads((ROOT/'build/native-ui/profiles.json').read_text())
assert profiles['sha256']==PROFILES_SHA256
assert module.pool[:len(original.pool)] == original.pool
assert module.debug == original.debug
assert module.contexts[:18] == original.contexts
patches = {int(p['offset'],16):p for p in receipt['original_code_preserved_except']}
changed = {p+n for p in patches for n in range(8)}
assert all(i in changed or b==original.code[i] for i,b in enumerate(module.code[:len(original.code)]))
for p, description in patches.items():
    assert bytes(original.code[p:p+8]).hex() == description['original']
    assert rows[p]['opcode'] == 54
    # No original jump is permitted to enter a replaced instruction's interior.
    assert not any(r.get('opcode') in [54,55,56] and p<r['operands'][0]<p+8
                   for r in old_rows.values())

for row in rows.values():
    op = row.get('opcode')
    if op in [54,55,56]:
        target = row['operands'][0]
        assert target in rows and not rows[target].get('header'), row
    if op in [63,66,67]:
        assert rows[row['operands'][0]].get('header'), row
for context in module.contexts:
    for method in context['methods']:
        assert rows[method['code_offset']].get('header'), method
    for target in struct.iter_unpack('<I',bytes.fromhex(context['extra'])):
        assert rows[target[0]].get('header')

def owner_frame(instructions, offset):
    """Inline fragments inherit the actual caller's frame, not Assembler.slots."""
    header = max((row for row in instructions.values() if row.get('header') and row['offset'] <= offset),
                 key=lambda row:row['offset'])
    return header['frame_slots']


fragments = {rows[p]['operands'][0]:owner_frame(old_rows,p) for p in patches}
assert {p:owner_frame(old_rows,p) for p in patches} == {
    0x943c:8,0x4f38:6,0xc894:10,0xaf98:10,0xb3a0:4}


def local_registers(row):
    op,r,args = row['opcode'],row['register'],row['operands']
    local = []
    if op in [0,1,2,3,16,18,20,36,46,50,55,56,57,58,60,68,71,74,75,76,77,78]: local.append(r)
    if op in [36,46,50]: local.append(r+1)
    if op in [57,58]: local += list(range(r+1,r+2+args[0]))
    if op == 60: local.append(r+1)
    if op == 10: local += [r,signed(args[0])]
    if op == 11: local.append(r)
    if op in [12,14]: local.append(args[0])
    if op == 59: local += [r,r-1,signed(args[0]>>8)]
    if op == 75: local.append(signed(args[0],16))
    if op in [76,77,78]:
        local += [signed(args[0]&65535,16),signed(args[0]>>16,16)]
    if op in [77,78]: local.append(signed(args[1]&65535,16))
    if op == 78: local.append(signed(args[1]>>16,16))
    return local


def validate_appended_bounds(instructions):
    frame_slots = None
    for offset,row in instructions.items():
        if offset < len(original.code): continue
        if row.get('header'): frame_slots = row['frame_slots']; continue
        if offset in fragments: frame_slots = fragments[offset]
        assert frame_slots is not None
        local = local_registers(row)
        assert all(-10<=n<frame_slots for n in local), (hex(offset),frame_slots,local,row)


validate_appended_bounds(rows)

helper_signatures = {(method['name'],method['args']) for context in original.contexts
                     for method in context['methods']}

# These regressions recreate the delivered Audio R10 and apply R4 overflow.
# The bound comes from the pinned original owner header, not the new fragment.
for patch, bad_register in [(0xc894,10),(0xb3a0,4)]:
    start = rows[patch]['operands'][0]
    following = min((p for p in fragments if p > start),default=len(module.code))
    site = next(offset for offset,row in rows.items() if start <= offset < following
                and row.get('opcode') == 74 and row['register'] == 1)
    mutated = dict(rows)
    mutated[site] = {**rows[site], 'register':bad_register}
    try: validate_appended_bounds(mutated)
    except AssertionError as error:
        assert error.args[0][0] == hex(site)
    else: raise AssertionError(('Out-of-frame CLEAR accepted',hex(patch),bad_register))


class Model:
    def __init__(self):
        self.settings = {key:str(value) for key,value in MINIMUM_VIDEO.items()}
        self.settings.update(PortSoundRate='44',PortDebugColour='0',PortDebugAmount='100',DebugInterface='0')
        self.settings.update(PortModeCount='3',PortRefreshCount='3',PortAutoProfile='0',
                             PortAAModeCount='5',PortMaxAnisotropy='8')
        self.globals = {15:True,17:self}
        self.fields = {(1,0):[],(7,0):[],(7,1):None,(7,2):None}
        self.labels = []
        self.buttons = []
        self.checkboxes = []
        self.commands = []
        self.saved = []
        self.transitions = []
        self.click = -1
        self.calls = []
        self.logs = []
        self.published_snapshot=None
        self.width,self.height = 800,600

    def named(self, name):
        return {'Settings':self.settings,'!vector':lambda:[],
            '!vec2':lambda x,y:(x,y),'executeConsoleCommand':self.execute,
            'saveSettings':lambda:self.saved.append(dict(self.settings)),
            'logInfo':lambda text:self.logs.append(text),
            'Plane':{},'Width':self.width,'Height':self.height}[name]

    def member(self, value, name):
        if name=='call' and value is self: return self.helper
        if name=='asInt': return int(value)
        if name=='asBool': return bool(int(value))
        if name=='add' and isinstance(value,list): return value.append
        if name in ['x','y'] and isinstance(value,tuple): return value[0 if name=='x' else 1]
        raise AssertionError((value,name))

    def execute(self,command):
        self.commands.append(command)
        # This injected host response is separate from the native adapter/
        # profile oracle; it checks that bytecode consumes published values.
        if command.startswith('port_config ') and self.published_snapshot:
            self.settings.update({k:str(v) for k,v in self.published_snapshot.items()})

    def helper(self, name, *args):
        if name != 'removeControl':
            assert (name,len(args)) in helper_signatures, ('Original helper overload absent',name,len(args))
        self.calls.append((name,args))
        if name=='destroyControls':
            self.labels=[]; self.buttons=[]; self.checkboxes=[]
        elif name=='createLabel': self.labels.append(args)
        elif name=='createButton':
            self.buttons.append(args); return len(self.buttons)-1
        elif name=='createCheckbox':
            self.buttons.append(args); self.checkboxes.append(bool(args[3]))
            return len(self.checkboxes)-1
        elif name=='handleMouseButtonLeft': return self.click
        elif name=='getCheckBoxState': return self.checkboxes[args[0]]
        elif name=='setCheckBoxState': self.checkboxes[args[0]]=bool(args[1])
        elif name=='removeControl': pass
        else: raise AssertionError((name,args))

    def run(self, start, values=None, stops=()):
        regs = dict(values or {})
        frame_slots = fragments.get(start,owner_frame(rows if start >= len(original.code) else old_rows,start))
        pc = start+8 if rows[start].get('header') else start
        for _ in range(10000):
            if pc in stops: return ('stop',pc,regs)
            row = rows[pc]
            assert not row.get('header'),hex(pc)
            assert all(-10 <= n < frame_slots for n in local_registers(row)), (hex(pc),frame_slots,row)
            op,r,a = row['opcode'],row['register'],row['operands']
            pc += row['size']
            get = lambda n:regs.get(n,None)
            if op==0: regs[r]=bool(a[0])
            elif op==1: regs[r]=signed(a[0])
            elif op==2: regs[r]=struct.unpack('<f',struct.pack('<I',a[0]))[0]
            elif op==3: regs[r]=module.wide(a[1],a[0])
            elif op==10: regs[signed(a[0])]=get(r)
            elif op==11: self.fields[(a[1],a[0])]=get(r)
            elif op==12: regs[a[0]]=self.fields[(a[1],r)]
            elif op==14: regs[a[0]]=self.globals[r]
            elif op==16: regs[r]=int(get(r))
            elif op==18: pass
            elif op==20: regs[r]=str(int(get(r))) if isinstance(get(r),bool) else str(get(r))
            elif op==36: regs[r]=get(r)+get(r+1)
            elif op==37: regs[r]=get(r)-get(r+1)
            elif op==38: regs[r]=get(r)*get(r+1)
            elif op==46: regs[r]=get(r)==get(r+1)
            elif op==50: regs[r]=get(r)>get(r+1)
            elif op==54: pc=a[0]
            elif op==55:
                if not get(r): pc=a[0]
            elif op==56:
                if get(r): pc=a[0]
            elif op==57: regs[r]=get(r+1)(*[get(n) for n in range(r+2,r+2+a[0])])
            elif op==58: regs[r]=get(r+1)[get(r+2)]
            elif op==59: get(r)[get(a[0]>>8) if a[0]>>8 else get(r+1)]=get(r-1)
            elif op==60: regs[r]=self.member(get(r+1),module.ascii(a[0]))
            elif op==63:
                outcome = self.run(a[0])
                assert outcome[0]=='return',outcome
            elif op==64:
                assert a==[0] and r==0
                # Audio's preceding volume code is unchanged. Exercise the
                # exact patched tail that now stores the visibility checkbox.
                outcome=self.run(0xb3a0)
                assert outcome[0]=='return',outcome
            elif op==65: return ('return',pc,regs)
            elif op==67: self.transitions.append((r,a[0],a[1]))
            elif op==68: return ('yield',pc,regs)
            elif op==71: regs[r]=self.named(module.ascii(a[0]))
            elif op==74: regs[r]=None
            elif op in [75,76,77,78]:
                cleared=[r]
                if op==75: cleared.append(signed(a[0],16))
                else: cleared.extend([signed(a[0]&65535,16),signed(a[0]>>16,16)])
                if op in [77,78]: cleared.append(signed(a[1]&65535,16))
                if op==78: cleared.append(signed(a[1]>>16,16))
                for n in cleared: regs[n]=None
            else: raise AssertionError((hex(row['offset']),row))
        raise AssertionError('instruction budget exhausted')


debug_ctor=int(receipt['debug_constructor'],16)
config_ctor=int(receipt['config_constructor'],16)
debug_click=next(m['code_offset'] for m in module.contexts[18]['methods'] if m['name']=='onMouseButtonLeft')
config_click=next(m['code_offset'] for m in module.contexts[19]['methods'] if m['name']=='onMouseButtonLeft')
key=next(m['code_offset'] for m in module.contexts[19]['methods'] if m['name']=='onWinKeyDown')
cases=[]

def note(name): cases.append(name)

note('Audio inline frame comes from original C2B0; synthetic R10 CLEAR rejected')
note('Apply inline frame comes from original B15C; synthetic R4 CLEAR rejected')

for in_game,visible in [(False,False),(False,True),(True,False),(True,True)]:
    m=Model();m.globals[15]=in_game;m.settings['DebugInterface']=str(int(visible))
    m.run(0x943c,stops=[0x9444])
    assert m.fields[(1,0)]==([7] if in_game and visible else [])
    note(f'visibility in_game={in_game} visible={visible}')

for action in range(8):
    m=Model();m.run(0x4f38,{1:action},stops=[0x4f40,0x525c])
    assert bool(m.transitions)==(action==7)
    if action==7: assert m.transitions==[(18,debug_ctor,0)]
    note(f'original menu route action={action}')

m=Model();m.fields[(7,0)]=[0,1,2,3];m.buttons=[None]*4;m.checkboxes=[True]
return_control,default_control = object(),object()
m.fields[(7,1)],m.fields[(7,2)] = return_control,default_control
assert m.run(0xc894)[0]=='yield'
assert m.fields[(7,0)]==[0,1,2,3,4,5] and m.checkboxes==[True,False]
assert m.fields[(7,1)] is return_control and m.fields[(7,2)] is default_control
# Original continuation consumes YIELD's R0 and freshly assigned R2..R5;
# it does not read the cleared R6..R9, or mutate captured Options controls.
assert old_rows[0xc894]['opcode'] == 68
assert all(n < 6 for offset,row in old_rows.items() if 0xc898 <= offset < 0xca04
           and not row.get('header') for n in local_registers(row) if n >= 0)
note('Audio constructor appends checkbox/action without replacing original map')
if receipt.get('audio_diagnostics'):
    assert m.logs == ['[void-menu] ' + text for text in [
        'Audio extension begin','Audio checkbox geometry ready',
        'Audio DebugInterface index returned','Audio DebugInterface asBool ready',
        'Audio visibility checkbox ready','Audio visibility label ready',
        'Audio Graphics button ready','Audio extension complete']]
    note('Audio stage logger preserves callable, property and geometry registers')
for state in [False,True]:
    m=Model();m.checkboxes=[True,state]
    m.run(0xaf98,{1:4},stops=[0xb044])
    assert m.checkboxes==[True,not state]
    m.run(0xb3a0)
    assert m.settings['DebugInterface']==str(int(not state)) and m.saved[-1]==m.settings
    note(f'checkbox toggles and persists from {state}')
m=Model();m.checkboxes=[False,True]
m.run(0xaf98,{1:5},stops=[0xb044])
assert m.settings['DebugInterface']=='1' and len(m.saved)==1
assert m.transitions==[(19,config_ctor,0)] and m.checkboxes==[]
note('Audio to Config applies before destroying controls')

for ctor,click,count,context in [(debug_ctor,debug_click,8,18),(config_ctor,config_click,11,19)]:
    m=Model();assert m.run(ctor)[0]=='yield'
    assert len(m.buttons)==count and m.fields[(1,0)]==list(range(count-1))+[99]
    for index in [-1]:
        m.click=index;before=dict(m.settings)
        assert m.run(click,{-6:100,-5:100,-4:True})[0]=='return'
        assert m.settings==before and not m.commands and not m.transitions
    m.click=0
    assert m.run(click,{-6:100,-5:100,-4:False})[0]=='return'
    assert not m.transitions
    note(f'context{context} constructor and no-hit/released click guards')
    m.click=count-1
    m.run(click,{-6:100,-5:100,-4:True})
    assert m.transitions==[(1,0x8c48,0)] and not m.buttons
    note(f'context{context} Return')

for context,ctor,click in [(18,debug_ctor,debug_click),(19,config_ctor,config_click)]:
    for code,pressed,expected in [(27,False,True),(27,True,False),(13,False,False)]:
        m=Model();m.run(ctor)
        m.run(key,{-5:code,-4:pressed})
        assert bool(m.transitions)==expected
        note(f'context{context} key={code} pressed={pressed}')

for colour in range(7):
    for amount in [50,100,200,500]:
        for action,verb in [(2,'add_fl'),(3,'add_al')]:
            m=Model();m.settings.update(PortDebugColour=str(colour),PortDebugAmount=str(amount))
            m.run(debug_ctor);m.click=action
            m.run(debug_click,{-6:100,-5:100,-4:True})
            assert m.commands==[f'/{verb} {colour} {amount}']
            assert m.transitions==[(18,debug_ctor,0)]
note('56 colour/amount command combinations')
for action,command in [(4,'/giveall'),(5,'/god'),(6,'/openall')]:
    m=Model();m.run(debug_ctor);m.click=action
    m.run(debug_click,{-6:100,-5:100,-4:True})
    assert m.commands==[command]
    note(command)

for index,(title,name,values,_) in enumerate(CONFIG_ROWS):
    if index in DYNAMIC_COMMANDS:
        m=Model();m.run(config_ctor);m.click=index
        expected={'PortWidth':1024,'PortHeight':768,'PortRefreshRate':75,
                  'PortAntialiasing':4,'PortAnisotropy':2}
        m.published_snapshot=expected
        m.run(config_click,{-6:100,-5:100,-4:True})
        assert m.commands==['port_config '+DYNAMIC_COMMANDS[index]+' 1']
        assert all(m.settings[k]==str(v) for k,v in expected.items())
        assert m.saved[-1]==m.settings and m.transitions==[(19,config_ctor,0)]
        note('Adapter-backed Config action '+DYNAMIC_COMMANDS[index])
        continue
    for old,value in zip(values,values[1:]+values[:1]):
        m=Model();m.settings[name]=str(old);m.run(config_ctor);m.click=index
        m.run(config_click,{-6:100,-5:100,-4:True})
        assert m.settings[name]==str(value),(name,old,m.settings)
        assert len(m.commands)==1 and m.commands[0].startswith('port_config ')
        assert m.transitions==[(19,config_ctor,0)] and len(m.saved)==1
    note('Config cycle '+name)
m=Model();m.run(config_ctor);m.click=9
m.published_snapshot={'PortWidth':1280,'PortHeight':1024,'PortHDR':2,'PortAutoProfile':8}
m.run(config_click,{-6:100,-5:100,-4:True})
assert m.commands==['port_config Autodetect 1']
assert all(m.settings[k]==str(v) for k,v in m.published_snapshot.items())
assert m.settings['PortSoundRate']=='44'
note('Autodetect consumes host snapshot and retains audio quality')
for index,name in [(-1,'Minimum (unlisted GPU)'),(0,'Not detected')]+list(enumerate([p['name'] for p in profiles['profiles']],1)):
    m=Model();m.settings['PortAutoProfile']=str(index);m.run(config_ctor)
    assert any(label[0]=='Detected profile: '+name for label in m.labels)
note('All original detected profile labels plus pending/fallback states')
m=Model();m.settings['PortAAModeCount']='-1';m.run(config_ctor)
assert any(label[0]=='GPU capabilities unavailable' for label in m.labels)
note('Unknown caps explicitly shown without preventing menu construction')

# Run the original position conversion routine, not an invented pixel formula.
# initMainMenu at0418 divides Height by the shipped float1200 and passes that
# scale into helper global6. Mode1 is top-left; mode0 is center/upward-Y.
assert struct.unpack('<f',struct.pack('<I',old_rows[0x418]['operands'][0]))[0]==1200
for width,height in [(800,600),(1024,768),(1280,720),(1920,1080)]:
    for ctor in [debug_ctor,config_ctor]:
        m=Model();m.width,m.height=width,height;m.globals[6]=height/1200
        m.run(ctor)
        for image,pos,anchor,size,tooltip in m.buttons:
            assert anchor==1
            translated=m.run(0x29d0,{-6:None,-5:pos,-4:anchor})[2][-7]
            x,y=translated
            dimension=128*size*height/1200
            assert 0<=x<x+dimension<=width and 0<=y<y+dimension<=height
        for text,pos,anchor in m.labels:
            assert anchor==1
            x,y=m.run(0x29d0,{-6:None,-5:pos,-4:anchor})[2][-7]
            assert 0<=x<width and 0<=y<height
    note(f'original position routine viewport{width}x{height}')
m=Model();m.globals[6]=.5;m.settings['DebugInterface']='1'
m.run(0x943c,stops=[0x9444])
image,pos,anchor,size,tooltip=m.buttons[0]
x,y=m.run(0x29d0,{-6:None,-5:pos,-4:anchor})[2][-7]
assert (x,y)==(520,450) and size==.75 and anchor==1
note('pause Debug button visible at520,450 in800x600')

result=dict(status='PASS',payload_sha256=receipt['sha256'],source_sha256=ORIGINAL_SHA256,
    checks=cases,branch_targets='PASS',frame_register_bounds='PASS',
    original_contexts_code_pool_debug_preserved='PASS',
    limitation='Independent bounded VM model, not real engine UI/rendering/input validation')
(ROOT/'build/native-ui/bytecode-selftest.json').write_text(json.dumps(result,indent=2))
print(json.dumps(dict(status='PASS',checks=len(cases),payload_sha256=receipt['sha256'])))
