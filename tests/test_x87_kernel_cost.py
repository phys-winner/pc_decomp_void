"""Measure isolated physical-x87 state switching; not game performance."""
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
from test_memmove import compiler_environment

ROOT=Path(__file__).resolve().parents[1]


def main():
    source=ROOT/'tests/x87_kernel_cost_probe.c'; before=hashlib.sha256(source.read_bytes()).hexdigest()
    output=ROOT/'build/x87-kernel-cost'; output.mkdir(parents=True,exist_ok=True)
    compiler,environment,sdk=compiler_environment(); executable=output/'probe.exe'
    arguments=[str(compiler),'/nologo','/O2','/std:c11','/W3',str(source),
               f'/Fo{output}\\',f'/Fe{executable}','/link','/MACHINE:X86','/NXCOMPAT']
    compiled=subprocess.run(arguments,cwd=ROOT,env=environment,text=True,capture_output=True)
    (output/'compile.log').write_text(compiled.stdout+compiled.stderr)
    assert compiled.returncode==0,compiled.stdout+compiled.stderr
    result=subprocess.run([str(executable)],cwd=ROOT,text=True,capture_output=True,timeout=20)
    assert result.returncode==0,(result.returncode,result.stdout,result.stderr)
    rows=[json.loads(line)for line in result.stdout.splitlines()]
    assert len(rows)==10 and hashlib.sha256(source.read_bytes()).hexdigest()==before
    medians={mode:statistics.median(r['ns_per_add']for r in rows if r['mode']==mode)
             for mode in ('full-switch-per-add','block-resident')}
    receipt={'status':'ISOLATED_COST_MEASURED','compiler':str(compiler),'sdk':sdk,
             'source_sha256':before,'arguments':arguments,'samples':rows,'median_ns_per_add':medians,
             'original_game_code_executed':False,'backend_implemented':False,'game_performance_measured':False,
             'guest_FIP_FDP_FOP_rewritten':False,'exceptions_or_callbacks_tested':False}
    (output/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(medians))


if __name__=='__main__':main()
