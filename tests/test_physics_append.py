"""Compare PhysX's debug line fast path with its emitted x86 body."""
from pathlib import Path
import json, re, subprocess, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from build_x86_incremental import compiler_environment

def main():
    out=ROOT/'build/physics-append-test';out.mkdir(parents=True,exist_ok=True)
    original=(ROOT/'generated/physxcore-x86/physxcore_0067.c').read_text()
    original=re.search(r'^void sub_181802C0\(void\) \{.*?^\}',original,re.M|re.S)[0].replace('void sub_181802C0(void)','void original_append(void)')
    native=(ROOT/'android/host/physics_native.c').read_text().replace('#include "host.h"','')
    driver=(ROOT/'tests/physics_append_probe.c').read_text().replace('/* EMITTED */',original).replace('/* NATIVE */',native)
    (out/'probe.c').write_text(driver)
    compiler,env,_=compiler_environment()
    results=[]
    for local in (False,True):
        exe=out/('probe-%d.exe'%local)
        built=subprocess.run([str(compiler),'/nologo','/O2','/W3','/std:c11','/DRECOMP_TRACE',*(['/DRECOMP_LOCAL_REGS'] if local else []),'/Inative','/Ireference/pcrecomp/runtime/recomp32',str(out/'probe.c'),'/Fe'+str(exe),'/Fo'+str(out/('probe-%d.obj'%local))],env=env,cwd=ROOT,capture_output=True,text=True)
        assert built.returncode==0,built.stdout+built.stderr
        tested=subprocess.run([str(exe)],capture_output=True,text=True)
        assert tested.returncode==0,tested.stdout+tested.stderr
        print(tested.stdout.strip());results.append(dict(local=local,output=tested.stdout.strip()))
    (out/'result.json').write_text(json.dumps(dict(status='PASS',results=results),indent=2))

if __name__=='__main__': main()
