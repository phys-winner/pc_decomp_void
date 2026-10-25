"""Exercise no-activation native Win32 policy using only an owned offscreen window."""
import hashlib
import json
from pathlib import Path
import subprocess
from test_memmove import compiler_environment

ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output=ROOT/'build/window-policy';output.mkdir(parents=True,exist_ok=True)
    sources=[ROOT/path for path in ('native/window_policy.c','native/window_policy.h',
        'tests/window_policy_probe.c','tests/test_window_policy.py')]
    before={str(p.relative_to(ROOT)):sha(p)for p in sources}
    compiler,environment,sdk=compiler_environment();executable=output/'probe.exe'
    command=[str(compiler),'/nologo','/O2','/std:c11','/W3','/Inative','native/window_policy.c',
        'tests/window_policy_probe.c',f'/Fo{output}\\',f'/Fe{executable}','/link','/MACHINE:X86','/NXCOMPAT']
    compiled=subprocess.run(command,cwd=ROOT,env=environment,text=True,capture_output=True)
    (output/'compile.log').write_text(compiled.stdout+compiled.stderr)
    assert compiled.returncode==0,compiled.stdout+compiled.stderr
    startup=subprocess.STARTUPINFO();startup.dwFlags=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=1
    tested=subprocess.run([str(executable)],cwd=ROOT,text=True,capture_output=True,timeout=10,startupinfo=startup,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    unchanged=before=={str(p.relative_to(ROOT)):sha(p)for p in sources}
    receipt={'status':'PASS'if tested.returncode==0 and unchanged else'FAILED','exit':tested.returncode,
        'output':tested.stdout+tested.stderr,'compiler':str(compiler),'sdk':sdk,'command':command,
        'source_hashes':before,'source_hashes_unchanged':unchanged,'startup_show_window':1,
        'process_creation_flags':'CREATE_NO_WINDOW',
        'owned_window_only':True,'SetForegroundWindow_SetActiveWindow_SetFocus_called':False,
        'original_game_code_executed':False,'gameplay_tested':False}
    (output/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(tested.stdout+tested.stderr,end='');assert receipt['status']=='PASS',receipt


if __name__=='__main__':main()
