"""Private mount XML + typed Win32 wrappers, using immutable installed input."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import uuid
import xml.etree.ElementTree as ET
from test_memmove import compiler_environment

ROOT=Path(__file__).resolve().parents[1]
PINNED="2bc9d3741877f7cc836e6ebef29ed3dd50028e29cc160d0e970601cd9ff0c7f1"
MAX_TEST_PATH=260


def sha(data): return hashlib.sha256(data).hexdigest()


def main():
    config=json.loads((ROOT/'port.json').read_text())
    original_data=Path(config['game_directory'])/'data'
    original=(original_data/'fsystems.xml').read_bytes()
    assert sha(original)==PINNED
    original_settings=(original_data/'settings.xml').read_bytes()
    assert sha(original_settings)=='4ff83f7ef62304faa7fe6123290f19d2ada59940f9dca1cbfe8464393fd19dc6'
    original_settings_attributes=(original_data/'settings.xml').stat().st_file_attributes
    original_config=(original_data/'config.xml').read_bytes()
    assert sha(original_config)=='122f1ec97fe00754f5d67ebb941b9776a2d8bc8f3b6a9f884fd8b32ac4b4b17a'
    assert original_config.count(b'<Fullscreen />')==1
    original_config_attributes=(original_data/'config.xml').stat().st_file_attributes
    allowed=(ROOT/'build/test-profiles').resolve()
    output=(allowed/('asset-overrides-'+str(uuid.uuid4()))).resolve()
    assert output.is_relative_to(allowed)
    # Writes use copied input files, so broken routing cannot write to Steam.
    copied_data=output/'input-data';copied_data.mkdir(parents=True)
    (copied_data/'fsystems.xml').write_bytes(original)
    (copied_data/'settings.xml').write_bytes(original_settings)
    (copied_data/'config.xml').write_bytes(original_config)
    (copied_data/'settings.xml').chmod(stat.S_IREAD)
    copied_settings_attributes=(copied_data/'settings.xml').stat().st_file_attributes
    (copied_data/'unmodified.bin').write_bytes(b'Unmodified file routing sentinel')
    common=output/'CommonAppData';target=common/'Ice-pick Lodge/Void/settings.xml'
    target.parent.mkdir(parents=True)
    private_tree=ET.fromstring(original_settings)
    ET.SubElement(private_tree,'prop',name='DebugInterface',value='0')
    ET.SubElement(private_tree,'prop',name='PortWidth',value='800')
    target.write_bytes(ET.tostring(private_tree,encoding='utf-8',xml_declaration=True))
    assets=output/'runtime & assets Ω'
    scripts=assets/'Scripts'
    (scripts/'ui').mkdir(parents=True)
    payload=b'Private immutable asset routing probe\x00\xFF'
    (scripts/'ui/main_menu.bin').write_bytes(payload)
    compiler,env,sdk=compiler_environment();exe=output/'probe.exe'
    sources=[ROOT/'native/asset_overrides.c',ROOT/'native/asset_overrides.h',ROOT/'tests/asset_overrides_probe.c',Path(__file__)]
    before={str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in sources}
    command=[str(compiler),'/nologo','/O2','/W3','/std:c11','/D_CRT_SECURE_NO_WARNINGS',f'/I{ROOT / "native"}',
        str(sources[0]),str(sources[2]),f'/Fo{output}\\',f'/Fe{exe}','/link','/MACHINE:X86','/NXCOMPAT']
    built=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True)
    (output/'compile.log').write_text(built.stdout+built.stderr)
    if built.returncode:raise RuntimeError(built.stdout+built.stderr)
    results=[]
    def run(label, data=copied_data,root=assets,digest=sha(payload),mode='positive',
            common_path=common,profile=output):
        test_env=env.copy()
        if profile is None:test_env.pop('VOID_PROFILE_ROOT',None)
        else:test_env['VOID_PROFILE_ROOT']=str(profile)
        tested=subprocess.run([str(exe),str(data),str(root),digest,mode,str(common_path)],
            env=test_env,capture_output=True,text=True,timeout=20)
        text=tested.stdout+tested.stderr
        (output/(label+'.txt')).write_text(text)
        results.append({'case':label,'exit':tested.returncode,'output':text})
        assert tested.returncode==0,text
        print(label,text.strip())
    run('valid')
    windowed=(assets/'config.xml').read_bytes()
    assert windowed==original_config.replace(b'<Fullscreen />',b'',1)
    original_nodes=[n for n in ET.fromstring(original_config) if n.tag!='Fullscreen']
    assert [ET.tostring(n) for n in ET.fromstring(windowed)]==[ET.tostring(n) for n in original_nodes]
    saved_settings=target.read_bytes()
    assert {p.attrib['name']:p.attrib['value'] for p in ET.fromstring(saved_settings)}=={
        'DebugInterface':'0','PortWidth':'1024'}
    assert (copied_data/'settings.xml').read_bytes()==original_settings
    assert (copied_data/'settings.xml').stat().st_file_attributes==copied_settings_attributes
    mounted=(assets/'fsystems.xml').read_bytes()
    source_tree=ET.fromstring(original);tree=ET.fromstring(mounted)
    expected_nodes=list(source_tree);observed_nodes=list(tree)
    position=next(i for i,n in enumerate(expected_nodes) if n.tag=='system' and n.get('name')=='script')
    assert len(observed_nodes)==len(expected_nodes)+1
    provider=observed_nodes.pop(position)
    assert provider.tag=='system' and provider.attrib=={'name':'script'}
    assert Path(provider.findtext('Path')).resolve()==scripts.resolve()
    assert [ET.tostring(n) for n in observed_nodes]==[ET.tostring(n) for n in expected_nodes]
    # Removing exactly the insertion must preserve the original byte sequence.
    start=mounted.index(b'<system name="script"><Path>')
    end=mounted.index(b'</Path></system>\r\n  ',start)+len(b'</Path></system>\r\n  ')
    assert mounted[:start]+mounted[end:]==original
    run('wrong_payload_hash',digest='0'*64,mode='reject')
    assert (assets/'fsystems.xml').read_bytes()==mounted
    extra=scripts/'unmodified.bin';extra.write_bytes(b'not authorized for override')
    run('extra_private_script_rejected',mode='reject');extra.unlink()
    corrupt=output/'corrupt-original-data';corrupt.mkdir();(corrupt/'fsystems.xml').write_bytes(b'<FileSystems/>')
    (corrupt/'settings.xml').write_bytes(original_settings)
    (corrupt/'config.xml').write_bytes(original_config)
    run('wrong_xml_hash',data=corrupt,mode='reject')
    assert (assets/'fsystems.xml').read_bytes()==mounted
    run('destination_in_original_denied',root=original_data,mode='reject')
    run('missing_profile_environment',profile=None,mode='reject')
    run('mismatched_common_path',common_path=output/'WrongCommon',mode='reject')
    run('common_under_original_denied',profile=copied_data,common_path=copied_data/'CommonAppData',mode='reject')
    run('overlong_common_path',common_path=str(output)+'\\'+'x'*MAX_TEST_PATH,mode='reject')
    corrupt_settings=output/'corrupt-settings-input';corrupt_settings.mkdir()
    (corrupt_settings/'fsystems.xml').write_bytes(original)
    (corrupt_settings/'settings.xml').write_bytes(b'<Settings/>')
    (corrupt_settings/'config.xml').write_bytes(original_config)
    run('wrong_settings_hash',data=corrupt_settings,mode='reject')
    corrupt_config=output/'corrupt-config-input';corrupt_config.mkdir()
    (corrupt_config/'fsystems.xml').write_bytes(original)
    (corrupt_config/'settings.xml').write_bytes(original_settings)
    for label,content in [('wrong_config_hash',original_config+b' '),
            ('missing_fullscreen_token',original_config.replace(b'<Fullscreen />',b'')),
            ('duplicate_fullscreen_token',original_config.replace(b'<Fullscreen />',b'<Fullscreen /><Fullscreen />'))]:
        (corrupt_config/'config.xml').write_bytes(content)
        run(label,data=corrupt_config,mode='reject')
        assert (assets/'config.xml').read_bytes()==windowed
        assert (assets/'fsystems.xml').read_bytes()==mounted
    target.unlink()
    run('missing_private_settings',mode='reject')
    target.mkdir()
    run('private_settings_directory',mode='reject')
    target.rmdir();target.write_bytes(saved_settings)
    run('normalized_common_equivalent',common_path=str(common).replace('\\','/').upper()+'/',mode='positive')
    run('valid_repeat')
    assert (assets/'fsystems.xml').read_bytes()==mounted
    assert (original_data/'fsystems.xml').read_bytes()==original
    assert (original_data/'settings.xml').read_bytes()==original_settings
    assert (original_data/'config.xml').read_bytes()==original_config
    assert (original_data/'config.xml').stat().st_file_attributes==original_config_attributes
    assert (copied_data/'config.xml').read_bytes()==original_config
    assert (assets/'config.xml').read_bytes()==windowed
    assert (original_data/'settings.xml').stat().st_file_attributes==original_settings_attributes
    assert (copied_data/'settings.xml').read_bytes()==original_settings
    assert (copied_data/'settings.xml').stat().st_file_attributes==copied_settings_attributes
    assert before=={str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in sources}
    (output/'result.json').write_text(json.dumps({'utc':datetime.now(timezone.utc).isoformat(),'status':'PASS',
        'compiler':str(compiler),'sdk':sdk,'source_hashes':before,'original_xml_sha256':PINNED,
        'private_xml_sha256':sha(mounted),'test_payload_sha256':sha(payload),'dedicated_root':str(output),
        'original_settings_sha256':sha(original_settings),'original_settings_attributes':original_settings_attributes,
        'copied_settings_attributes':copied_settings_attributes,'write_tests_use_only_copied_inputs':True,
        'original_config_sha256':sha(original_config),'windowed_config_sha256':sha(windowed),
        'only_one_fullscreen_literal_removed':True,'original_includes_and_other_bytes_preserved':True,
        'original_mounts_byte_preserved_after_insertion_removal':True,'provider_precedes_original_script':True,
        'real_file_handles_verified':True,'original_settings_and_xml_unchanged':True,'no_game_UI_or_registry_changes':True,
        'synthetic_payload_only_not_a_script_execution_test':True,'results':results},indent=2))
    print('PASS immutable original XML/settings; one first-provider insertion; receipt',output/'result.json')


if __name__=='__main__':main()
