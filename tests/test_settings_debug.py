"""Real Win32 backend file transactions in a throwaway owned profile."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

root = Path(__file__).resolve().parents[1]
original = Path(os.environ["ProgramData"]) / "Ice-pick Lodge/Void"
sources = {n: (original/n).read_bytes() for n in ['rcfg.xml','scfg.xml']}
source_hashes = {n: hashlib.sha256(b).hexdigest() for n,b in sources.items()}
profile = Path(tempfile.mkdtemp(prefix='fixture-',dir=root/'build/native-ui/backend'))
common = profile/'CommonAppData'
config = common/'Ice-pick Lodge'/'Void'
config.mkdir(parents=True)
for name,data in sources.items(): (config/name).write_bytes(data)
exe = root/'build/native-ui/backend/settings-debug-probe.exe'
data_source=Path(json.loads((root/'research/vfs-index.json').read_text())['source'])
profiles_raw=(data_source/'profiles.xml').read_bytes()
assert hashlib.sha256(profiles_raw).hexdigest()=='9059f1eee5687a25ca116365a70939175d93dbc387a113043427a14de037ca5f'
gpu_profiles=list(ET.fromstring(profiles_raw))
env = dict(os.environ,VOID_PROFILE_ROOT=str(profile),VOID_ORIGINAL_DATA_ROOT=str(data_source),VOID_TEST_ADAPTER='1')
cases = []
last_snapshot={}

def run(command=None, common_path=common, extra_env=None):
    global last_snapshot
    args = [str(exe),str(common_path)]
    if command is not None: args.append(command)
    result = subprocess.run(args,env=dict(env,**(extra_env or {})),text=True,capture_output=True,check=True)
    lines=result.stdout.splitlines()
    assert lines[0].startswith('INIT '),result.stdout
    last_snapshot={line.split()[1]:int(line.split()[2]) for line in lines if line.startswith('SNAPSHOT ')}
    if command is not None:
        code=int(next(line for line in lines if line.startswith('COMMAND ')).split()[1])
        cases.append(dict(command=command,result=code,snapshot=dict(last_snapshot),stdout=result.stdout))
        return code
    return int(lines[0].split()[1])

assert run()==1
settings=ET.parse(config/'settings.xml').getroot()
props={e.get('name'):e.get('value') for e in settings.findall('prop')}
assert len(props)==28
assert props['DebugInterface']=='0' and props['PortDebugAmount']=='100'
for command,tag,text in [
    ('port_config Resolution 1024 768','Width','1024'),
    ('port_config RefreshRate 0','RefreshRate','0'),
    ('port_config Antialiasing 4','Antialiasing','4'),
    ('port_config Anisotropy 8','Anisotropy','8'),
    ('port_config TextureQuality 0','TextureQuality','0'),
    ('port_config LightmapQuality 1','LightmapQuality','1')]:
    assert run(command)==1
    assert ET.parse(config/'rcfg.xml').getroot().findtext(tag)==text
assert run('port_config HDR 2')==1
assert ET.parse(config/'rcfg.xml').getroot().find('HDR').get('simple')=='0'
assert run('port_config VSync 1')==1
assert ET.parse(config/'rcfg.xml').getroot().find('VSync') is not None
assert run('port_config SoundRate 22')==1
assert run('port_config Memory 128')==1
sound=ET.parse(config/'scfg.xml').getroot()
assert sound.find('Quality').get('rate')=='22' and sound.find('Memory').get('size')=='128'

for command in ['port_config','port_config Unknown 1','port_config HDR 3',
    'port_config TextureQuality 2','port_config VSync -1','port_config SoundRate 48',
    'port_config Resolution 1024','port_config Resolution 1024 768 extra',
    'port_config HDR 1 garbage','port_config HDR 1 2','port_config HDR 99999999999999999999',
    'port_config HDR +1','port_config HDR 1\n','port_config HDR 0; /god',
    'port_config Minimum 0','port_config Minimum 1 extra']:
    before={p.name:p.read_bytes() for p in config.glob('*.xml')}
    assert run(command)==-1,command
    assert {p.name:p.read_bytes() for p in config.glob('*.xml')}==before,command
assert run('/god')==0
assert run('port_configuration HDR 1')==0
assert run(common_path=original)==0
assert source_hashes=={n:hashlib.sha256((original/n).read_bytes()).hexdigest() for n in sources}

# The backend reloads native fields, preserves unrelated in-game properties and
# a user's visibility choice, and refreshes the port's cached displayed values.
xml=(config/'settings.xml').read_text().replace('name="DebugInterface" value="0"',
                                              'name="DebugInterface" value="1"')
(config/'settings.xml').write_text(xml)
assert run()==1
props={e.get('name'):e.get('value') for e in ET.parse(config/'settings.xml').getroot().findall('prop')}
assert props['DebugInterface']=='1' and props['Gamma']=='1' and props['PortWidth']=='1024'
assert props['PortSoundRate']=='22'
sound_before=(config/'scfg.xml').read_bytes()
assert run('port_config Minimum 1')==1
renderer=ET.parse(config/'rcfg.xml').getroot()
for tag,value in {'Width':'800','Height':'600','RefreshRate':'0','Antialiasing':'0',
    'Anisotropy':'0','TextureQuality':'1','LightmapQuality':'2'}.items():
    assert renderer.findtext(tag)==value
assert renderer.find('HDR').get('simple')=='1' and renderer.find('VSync') is None
assert (config/'scfg.xml').read_bytes()==sound_before
assert run()==1
props={e.get('name'):e.get('value') for e in ET.parse(config/'settings.xml').getroot().findall('prop')}
assert props['PortWidth']=='800' and props['PortHeight']=='600' and props['DebugInterface']=='1'

# Mode enumeration excludes the duplicate and too-small fixture modes, and
# cycles dimensions/rates independently, selecting original maximum refresh.
assert last_snapshot['PortModeCount']==3 and last_snapshot['PortRefreshCount']==3
for width,height,rate in [(1024,768,75),(1280,1024,60),(800,600,75)]:
    assert run('port_config NextResolution 1')==1
    assert tuple(last_snapshot[k] for k in ['PortWidth','PortHeight','PortRefreshRate'])==(width,height,rate)
for rate in [0,60,75]:
    assert run('port_config NextRefresh 1')==1 and last_snapshot['PortRefreshRate']==rate
for command in ['port_config Resolution 1920 1080','port_config RefreshRate 144',
    'port_config Antialiasing 3','port_config Anisotropy 16','port_config Autodetect 0',
    'port_config NextResolution 2','port_config NextRefresh 1 extra']:
    assert run()==1
    before={p.name:p.read_bytes() for p in config.glob('*.xml')}
    assert run(command)==-1
    assert {p.name:p.read_bytes() for p in config.glob('*.xml')}==before
assert run('port_config Antialiasing 0')==1
for value in [1,2,4,8,0]:
    assert run('port_config NextAA 1')==1 and last_snapshot['PortAntialiasing']==value
assert run('port_config HDR 2')==1
for value in [2,0]:
    assert run('port_config NextAA 1')==1 and last_snapshot['PortAntialiasing']==value
assert run('port_config Anisotropy 0')==1
for value in list(range(1,9))+[0]:
    assert run('port_config NextAF 1')==1 and last_snapshot['PortAnisotropy']==value

def select_profile(vendor,device,description):
    for i,p in enumerate(gpu_profiles):
        if int(p.findtext('Vendor'))==vendor and device in [int(s,16) for s in p.findtext('Model').split(',')]:
            return i,p
    for i,p in enumerate(gpu_profiles):
        try:
            if re.search(p.findtext('Search')+'$',description):return i,p
        except re.error: pass
    return -1,None

def expected_config(p):
    if p is None:return dict(PortWidth=800,PortHeight=600,PortHDR=1,PortAntialiasing=0,
        PortAnisotropy=0,PortTextureQuality=1,PortLightmapQuality=2,PortVSync=0)
    hdr=0 if p.find('HDR') is None else 1+int(bool(int(p.findtext('HDR'))))
    aa=int(p.findtext('Antialiasing','0'))
    aa_choices=[0,2] if hdr==2 else [0,1,2,4,8]
    return dict(PortWidth=int(p.findtext('Resolution/Width','800')),PortHeight=int(p.findtext('Resolution/Height','600')),
        PortVSync=int(p.find('VSync') is not None),PortHDR=hdr,
        PortAntialiasing=max(v for v in aa_choices if v<=aa),PortAnisotropy=min(8,int(p.findtext('Anisotropy','0'))),
        PortTextureQuality=min(1,int(p.findtext('TextureQuality','1'))),PortLightmapQuality=min(2,int(p.findtext('LightmapQuality','2'))))

gpu_cases=[]
for p in gpu_profiles:
    for identifier in p.findtext('Model').split(','):
        gpu_cases.append((int(p.findtext('Vendor')),int(identifier,16),'Wrong description to prove ID precedence'))
gpu_cases += [(4318,0x2882,'NVIDIA GeForce RTX 4060'),(4098,0xffff,'ATI Radeon 9600'),
    (4318,0xffff,'Prefix NVIDIA GeForce 6600 GT'),(4318,0xffff,'NVIDIA GeForce 66000'),
    (4318,0xffff,'nvidia geforce 6600'),(4098,0xffff,'Radeon HD 2400')]
for vendor,device,description in gpu_cases:
    selected,p=select_profile(vendor,device,description)
    expected=expected_config(p)
    assert run('port_config Autodetect 1',extra_env=dict(VOID_TEST_VENDOR=str(vendor),VOID_TEST_DEVICE=str(device),
        VOID_TEST_DESCRIPTION=description))==1
    assert last_snapshot['PortAutoProfile']==(-1 if selected<0 else selected+1)
    assert all(last_snapshot[k]==v for k,v in expected.items()),(vendor,device,description,p,last_snapshot,expected)
    assert last_snapshot['PortRefreshRate']==(75 if (expected['PortWidth'],expected['PortHeight']) in [(800,600),(1024,768)] else 60)

# Locked/unknown caps still allow init and sound/settings; GPU-dependent
# commands reject without altering either configuration file.
unknown=dict(VOID_TEST_AF='4294967295')
assert run(extra_env=unknown)==1 and last_snapshot['PortMaxAnisotropy']==-1 and last_snapshot['PortAAModeCount']==-1
for command in ['port_config Autodetect 1','port_config NextAA 1','port_config NextAF 1','port_config HDR 2']:
    before={n:(config/n).read_bytes() for n in ['rcfg.xml','scfg.xml']}
    assert run(command,extra_env=unknown)==-1
    assert before=={n:(config/n).read_bytes() for n in before}

# Same real Win32 code, no fixture adapter: identifier/mode/caps queries only.
native_env=dict(env);native_env.pop('VOID_TEST_ADAPTER')
native=subprocess.run([str(exe),str(common)],env=native_env,text=True,capture_output=True,check=True)
assert native.stdout.startswith('INIT 1 '),native.stdout
native_snapshot={line.split()[1]:int(line.split()[2]) for line in native.stdout.splitlines() if line.startswith('SNAPSHOT ')}

# Test every shipped expression against a broad original-description corpus,
# plus prefix/suffix/case/grouping cases. Invalid HD2400 remains a skipped error.
descriptions=['NVIDIA GeForce '+model+suffix for model in ['6600','66000','6800','6800 LE','8500 GT','8800','9500','GTX 260']
    for suffix in ['', ' GT',' tail7']]+['ATI Radeon '+m for m in ['9600','HD 2400','HD 2600 XT','HD 3850','X1600 XT']]
descriptions += ['Prefix NVIDIA GeForce 6600 GT','nvidia geforce 6600','NVIDIA GeForce 6600 7','GeForce(6600)']
regex_cases=[(p.findtext('Search'),d) for p in gpu_profiles for d in descriptions]
regex_cases += [(r'GeForce\(6600\)',d) for d in ['GeForce(6600)','prefix GeForce(6600)','GeForce6600','GeForce(6600) tail']]
expected=[]
for pattern,description in regex_cases:
    try:expected.append(int(re.search(pattern+'$',description) is not None))
    except re.error:expected.append(-1)
regex_input=root/'build/native-ui/backend/regex-corpus.tsv'
regex_input.write_text('\n'.join(p+'\t'+d for p,d in regex_cases)+'\n',encoding='ascii')
regex_output=subprocess.run([str(root/'build/native-ui/backend/settings-regex-probe.exe'),str(regex_input)],
    text=True,capture_output=True,check=True)
actual=[int(s) for s in regex_output.stdout.splitlines()]
assert actual==expected
assert source_hashes=={n:hashlib.sha256((original/n).read_bytes()).hexdigest() for n in sources}
assert hashlib.sha256((data_source/'profiles.xml').read_bytes()).hexdigest()==hashlib.sha256(profiles_raw).hexdigest()
assert not list(config.glob('vui*.tmp'))
receipt=dict(status='PASS',profile=str(profile),cases=cases,source_hashes=source_hashes,
    original_files_unchanged=True,real_win32_atomic_writes=True,profiles_sha256=hashlib.sha256(profiles_raw).hexdigest(),
    id_profile_cases=len(gpu_cases),regex_cases=len(regex_cases),native_adapter_snapshot=native_snapshot,
    native_adapter_stdout=native.stdout,locked_caps_init_and_unchanged_rejection='PASS')
(root/'build/native-ui/backend/selftest.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps(dict(status='PASS',cases=len(cases),profile=str(profile))))
