"""Use the shipped PL DDS and bytecode to check legacy menu HUD/warm startup."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
from build_x86_incremental import compiler_environment
from gscript_binary import Module
from patch_scripts import read_entry
from test_touch_native import VM, function
from test_touch_controls import method


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def c_function(source, name):
    at = re.search(r'^.*\b'+re.escape(name)+r'\([^;\n]*\)\s*\{', source, re.M).start()
    depth = 0
    for end in range(source.index('{', at), len(source)):
        depth += (source[end] == '{') - (source[end] == '}')
        if not depth:
            return source[at:end+1]
    raise AssertionError(name)


def main():
    out = ROOT / 'build/hud-legacy-menu-test'
    out.mkdir(parents=True, exist_ok=True)
    hud_path = ROOT / 'android/host/hud.c'
    hud = hud_path.read_text(encoding='utf-8')
    index_path = ROOT / 'research/vfs-index.polish.json'
    index = json.loads(index_path.read_text(encoding='utf-8'))
    textures = next(c for c in index['containers'] if c['name'] == 'Textures.vfs')
    archive = ROOT / index['source'] / textures['name']
    entry = next(e for e in textures['entries'] if e['name'].lower() == 'textures\\ui\\mainmenu_new_ru.tex')
    data = read_entry('research/vfs-index.polish.json', entry['name'])
    assert len(data) == 262272 and data[:4] == b'DDS '
    assert hashlib.sha256(data).hexdigest() == '6162fe24d83d84a552f2c0c2a6e102be98fee44fe9b3da3b67f490e27aef3a17'
    # The old menu unconditionally appends _ru to the actual new-button name.
    menu_data = read_entry('research/vfs-index.polish.json', 'Scripts\\ui\\main_menu.bin')
    assert hashlib.sha256(menu_data).hexdigest() == 'edd387f3e73b8e46cabd4bf688201203e8415134fed26d40b82aa81100d85ef6'
    menu = Module(menu_data, legacy=True)
    _, regs = VM(menu).run(0x4b4c, stops=(0x4b58,))
    assert regs[0] == '_ru'
    _, regs = VM(menu).run(0x4c50, {0: regs[0]}, stops=(0x4c68,))
    assert regs[4] == 'ui/mainmenu_new_ru'
    # The original continuation flag alone controls creation of the pause glyph.
    for continuation in (False, True):
        init = VM(menu)
        init.run(0xb0cc, {-7: continuation}, stops=(0xb0dc,))
        assert init.globals[9] is continuation
        stopped, _ = VM(menu, init.globals).run(0x4b58, {0: '_ru'}, stops=(0x4b68, 0x4c30))
        assert stopped == (0x4b68 if continuation else 0x4c30)
    _, regs = VM(menu).run(0x4b88, {0: '_ru'}, stops=(0x4ba0,))
    assert regs[4] == 'ui/mainmenu_continue_ru'
    pause_entry = next(e for e in textures['entries'] if e['name'].lower() == 'textures\\ui\\mainmenu_continue_ru.tex')
    pause_data = read_entry('research/vfs-index.polish.json', pause_entry['name'])
    assert hashlib.sha256(pause_data).hexdigest() == '23a486fd81c681b123940d42e9f7955f2fc73777b6b1e086e72643c95a5ca99f'
    # Full-file identity is unique: neither a mask nor a gameplay image shares it.
    matches, pause_matches = [], []
    with archive.open('rb') as f:
        for e in textures['entries']:
            if e['size'] != len(data):
                continue
            f.seek(e['offset'])
            prefix = f.read(256)
            if prefix not in (data[:256], pause_data[:256]):
                continue
            f.seek(e['offset'])
            actual = f.read(e['size'])
            if actual == data:
                matches.append(e['name'].lower())
            if actual == pause_data:
                pause_matches.append(e['name'].lower())
    assert matches == [entry['name'].lower()], matches
    assert pause_matches == [pause_entry['name'].lower()], pause_matches
    negative_names = ['textures\\ui\\mainmenu_new_ru_mask.tex', 'textures\\ui\\mainmenu_new_mask.tex',
        'textures\\ui\\mainmenu_options_ru.tex', 'textures\\ui\\mainmenu_continue_ru.tex',
        'textures\\cursor_paint.tex', 'textures\\map_hero.tex', 'textures\\ui\\ui_flimfa_right_up.tex']
    negatives = [next(e for e in textures['entries'] if e['name'].lower() == name) for name in negative_names]
    negative_list = out / 'nonmenu-assets.txt'
    negative_list.write_text(''.join(f"{e['offset']} {e['size']} {int(e['name'] == pause_entry['name'])}\n" for e in negatives))
    source_hashes = {str(p.relative_to(ROOT)): digest(p) for p in (
        hud_path, ROOT / 'android/host/hud.h', ROOT / 'android/host/vfs_dir.c',
        ROOT / 'android/host/shader_warm.c', ROOT / 'android/host/files.c',
        ROOT / 'android/app/src/org/thevoid/port/Controls.java')}
    # Keep the real VFS directory walker; Windows offsets emulate Android's 64-bit long.
    vfs = (ROOT / 'android/host/vfs_dir.c').read_text(encoding='utf-8')
    vfs = re.sub(r'^#include .*\n', '', vfs, flags=re.M)
    vfs = vfs[:vfs.index('FILE *void_vfs_open(')] + vfs[vfs.index('int void_vfs_scan('):]
    assert vfs.count('long here = ftell(f);') == 1
    vfs = vfs.replace('long here = ftell(f);', '__int64 here = ftell(f);')
    (out / 'vfs-fixture.h').write_text(vfs)
    paths = (ROOT / 'android/host/files.c').read_text(encoding='utf-8')
    (out / 'path-fixture.h').write_text('\n'.join(c_function(paths, name) for name in (
        'normalize', 'resolve_component', 'override_path', 'to_host_found', 'to_host', 'void_path_to_host')))
    hud = re.sub(r'^#include .*\n', '', hud, flags=re.M)
    # Android long is64bit; MSVC long is32bit (these archives exceed2GB).
    hud = hud.replace('(long)known[i].offset', '(__int64)known[i].offset').replace('(long)offset', '(__int64)offset')
    hud = hud.replace('long size = fseek', '__int64 size = fseek')
    (out / 'hud-fixture.h').write_text(hud)
    warm = (ROOT / 'android/host/shader_warm.c').read_text(encoding='utf-8')
    state = warm[warm.index('typedef struct {'):warm.index('static uint64_t warm_hash')]
    (out / 'warm-state.h').write_text(state)
    (out / 'warm-step.h').write_text(function(warm, 'd3d_shader_warm_step'))
    compiler, env, _ = compiler_environment()
    exe = out / 'probe.exe'
    built = subprocess.run([str(compiler), '/nologo', '/O2', '/std:c11', '/W3',
        '/D_CRT_SECURE_NO_WARNINGS', '/I'+str(ROOT / 'android/host'), '/I'+str(out),
        str(ROOT / 'tests/hud_legacy_menu_probe.c'), '/Fo'+str(out / 'probe.obj'), '/Fe'+str(exe)],
        env=env, capture_output=True, text=True)
    (out / 'build.log').write_text(built.stdout + built.stderr)
    assert built.returncode == 0, built.stdout + built.stderr
    # Valid shipped DDS payloads with distinct pixel/block contents reproduce
    # a loose-file replacement; continuation also changes actual file size.
    def changed(raw, at):
        value = bytearray(raw); value[at] ^= 1; return bytes(value)
    loose_new, override_new = changed(data, 128), changed(data, 129)
    rgba = read_entry('research/vfs-index.polish.json', 'Textures\\UI\\mainmenu_new.tex')
    assert len(rgba) == 1048704
    loose_pause, override_pause = changed(rgba, 128), changed(rgba, 129)
    fixture_root = out / 'effective-fixtures'
    results = []
    for mode in ('archive', 'loose', 'override', 'loose-only'):
        fixture = fixture_root / mode
        (fixture/'game').mkdir(parents=True, exist_ok=True)
        (fixture/'profile').mkdir(parents=True, exist_ok=True)
        expected_new, expected_pause = data, pause_data
        if mode != 'archive':
            loose = fixture/'game/DaTa/tExTuReS/uI'; loose.mkdir(parents=True, exist_ok=True)
            (loose/'MainMenu_New_RU.TeX').write_bytes(loose_new)
            (loose/'mainMENU_continue_RU.tex').write_bytes(loose_pause)
            expected_new, expected_pause = loose_new, loose_pause
        if mode == 'override':
            over = fixture/'profile/overrides/TEXTURES/UI'; over.mkdir(parents=True, exist_ok=True)
            (over/'MAINMENU_NEW_RU.TEX').write_bytes(override_new)
            (over/'MAINMENU_CONTINUE_RU.TEX').write_bytes(override_pause)
            expected_new, expected_pause = override_new, override_pause
        new_input, pause_input = fixture/'expected-new.tex', fixture/'expected-pause.tex'
        new_input.write_bytes(expected_new); pause_input.write_bytes(expected_pause)
        command = [str(exe), str(archive), str(entry['offset']), str(entry['size']), '1', str(negative_list),
                   str(fixture), str(new_input), str(pause_input), str(int(mode=='loose-only'))]
        run = subprocess.run(command, check=True, capture_output=True, text=True)
        results.append(dict(mode=mode, command=command, output=run.stdout.strip(),
            new_sha256=hashlib.sha256(expected_new).hexdigest(), new_size=len(expected_new),
            continue_sha256=hashlib.sha256(expected_pause).hexdigest(), continue_size=len(expected_pause)))
    # The actual screen classifier is independent of nativeMenu (false for 2008).
    controls = (ROOT / 'android/app/src/org/thevoid/port/Controls.java').read_text(encoding='utf-8')
    constants = controls[controls.index('    private static final int HUD_CURSOR'):controls.index('    private static final String[] SCREEN_NAMES')]
    java = '''public class LegacyMenuScreenProbe {
      static class GameActivity { static int nativeBrushColour() { return -1; } }
      static class SystemClock { static long now=1000; static long uptimeMillis() { return now; } }
      static final int WORLD=0, UI=1, PAINT=2;
      boolean menuSeen, nativeMenu; int hud, mode=UI; long[] seen=new long[32];
    ''' + constants + method(controls, 'private boolean shown(') + method(controls, 'private int screen()') + '''
      public static void main(String[] args) {
        for (boolean options : new boolean[]{false,true}) {
          LegacyMenuScreenProbe p=new LegacyMenuScreenProbe(); p.nativeMenu=options;
          p.hud=HUD_CURSOR|HUD_CONTROL_LOCKED; p.seen[0]=1000; assert p.screen()==S_INTRO;
          p.hud|=HUD_MAINMENU; p.seen[20]=1000; assert p.screen()==S_MAIN && p.menuSeen;
          p.hud|=HUD_PAUSE; assert p.screen()==S_PAUSE;
          p.hud=HUD_CURSOR|HUD_OPTIONS; assert p.screen()==S_OPTIONS;
          p.hud=HUD_CURSOR|HUD_MEMORY; assert p.screen()==S_BODY;
          p.hud=HUD_MAP3D; p.seen[24]=1000; p.mode=WORLD; assert p.screen()==S_MAP;
          p.hud=0; SystemClock.now=1500; assert p.screen()==S_WORLD;
          p.mode=UI; SystemClock.now=2600; assert p.screen()==S_OTHER;
          SystemClock.now=1000;
        }
        System.out.println("PASS: actual Java screen classifier, nativeMenu=false/true, intro/menu/pause/options/body/map/world/expiry");
      }
    }'''
    java_path = out / 'LegacyMenuScreenProbe.java'
    java_path.write_text(java, encoding='utf-8')
    java_bin = Path(os.environ.get('JAVA_HOME', '')) / 'bin'
    subprocess.run([str(java_bin/'javac.exe'), '--release', '8', '-d', str(out), str(java_path)], check=True)
    checked = subprocess.run([str(java_bin/'java.exe'), '-ea', '-cp', str(out), 'LegacyMenuScreenProbe'],
                             check=True, capture_output=True, text=True)
    assert source_hashes == {path: digest(ROOT / path) for path in source_hashes}
    receipt = dict(status='PASS', asset=entry, asset_sha256=hashlib.sha256(data).hexdigest(),
        menu_script_sha256=hashlib.sha256(menu_data).hexdigest(), source_hashes=source_hashes,
        exact_content_matches=matches, pause_asset=pause_entry,
        pause_asset_sha256=hashlib.sha256(pause_data).hexdigest(), pause_exact_content_matches=pause_matches,
        nonmenu_asset_controls=negatives,
        native_results=results, java_output=checked.stdout.strip(),
        single_thread_stubs=True, device_tested=False)
    (out / 'result.json').write_text(json.dumps(receipt, indent=2)+'\n')
    for row in results: print(row['mode']+': '+row['output'])
    print(checked.stdout.strip())


if __name__ == '__main__':
    main()
