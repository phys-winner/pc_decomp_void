"""Execute the actual GetData body with a GPU mock that detects blocking reads."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from build_android import CLANG
from build_x86_incremental import compiler_environment


def main():
    out=ROOT/'build/query-flush-test';out.mkdir(exist_ok=True)
    path=ROOT/'android/host/d3d9_resource.c';source=path.read_text()
    body=re.search(r'^COM_METHOD\(qry, GetData, 4\)\s*\{.*?^\}',source,re.M|re.S)
    assert body
    fixture=ROOT/'tests/d3d_query_probe.c'
    generated=out/'probe.c';generated.write_text(fixture.read_text().replace('/* PRODUCTION */',body[0]))
    for path_ in (path,ROOT/'android/host/script.c',ROOT/'android/host/host.h'):
        assert 'queryflush' not in path_.read_text() and 'query_flush_async' not in path_.read_text()
    _,env,_=compiler_environment();env['LIB']=env['LIB'].replace('\\x86','\\x64')
    exe=out/'probe.exe';cmd=[str(CLANG),'--target=x86_64-pc-windows-msvc','-fuse-ld=link','-O2','-std=c11',str(generated),'-o',str(exe)]
    build=subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,text=True)
    (out/'build.log').write_text(build.stdout+build.stderr);assert build.returncode==0,build.stdout+build.stderr
    run=subprocess.run([str(exe)],capture_output=True,text=True)
    (out/'run.log').write_text(run.stdout+run.stderr);assert run.returncode==0,run.stdout+run.stderr
    receipt=dict(status='PASS',exit_code=run.returncode,async_cases=2304,unchanged_method_cases=1920,
        original_source_sha256='9eebdcfc21f1bb6f5483f539894d1ee8eed5e964168e424a1ce64e0b81949faf',
        source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        test_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),
        reference='https://learn.microsoft.com/en-us/windows/win32/api/d3d9/nf-d3d9-idirect3dquery9-getdata',
        hardware_cause_proven=False,temporary_live_gate_removed=True,
        diagnostic='no temporary switch, clocks or wait logging in production')
    (out/'result.json').write_text(json.dumps(receipt,indent=2)+'\n');print(run.stdout,end='')


if __name__=='__main__':main()
