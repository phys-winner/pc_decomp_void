"""Record known defects in the current x87 model without editing the runtime."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from lift_game import BoundedDisassembler,CheckedLifter,lift_function_linear
from prepare_native_runtime import prepare
from test_memmove import compiler_environment


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output=ROOT/'build/x87-state-audit'; output.mkdir(parents=True,exist_ok=True)
    raw=bytearray(0x5003)
    raw[0:3]=bytes.fromhex('d9f5c3')
    raw[0x1000:0x1008]=b'\xe8'+struct.pack('<i',0x1000-5)+bytes.fromhex('dfe0c3')
    raw[0x2000:0x2003]=bytes.fromhex('d9f8c3')
    raw[0x4000:0x4003]=bytes.fromhex('df29c3')
    raw[0x5000:0x5003]=bytes.fromhex('df3ac3')
    section=SimpleNamespace(name='.text',virtual_address=0,raw_offset=0,raw_size=len(raw),virtual_size=len(raw),is_code=True)
    decoder=BoundedDisassembler(bytes(raw),0x21001000,[section]); imports={}
    addresses=(0x21001000,0x21002000,0x21003000,0x21005000,0x21006000)
    functions=[]
    for address in addresses:
        body=decoder.disassemble_function(address,imports)
        instructions=sorted({i.address:i for b in body.blocks.values()for i in b.instructions}.values(),key=lambda i:i.address)
        functions.append(lift_function_linear(CheckedLifter(lifted=set(addresses)),f'sub_{address:08X}',instructions,
            set(body.blocks),address,indirect_targets=body.jump_targets,eh_resume=None))
    header='#pragma once\n#define RECOMP_GENERATED_CODE\n#include "recomp_types.h"\n'
    header+='\n'.join(f'void sub_{a:08X}(void);'for a in addresses)+'\n'
    (output/'x87-audit-functions.h').write_text(header)
    (output/'x87-audit-functions.c').write_text('#include "x87-audit-functions.h"\n'+'\n\n'.join(functions)+'\n')
    prepare(check=True)
    runtime=(ROOT/'native/void_runtime.c').read_text()
    private_include='#include "../generated/native-runtime/native32.c"'
    assert runtime.count(private_include)==1
    original_runtime=runtime.replace(private_include,
        '#include "'+(ROOT/'reference/pcrecomp/runtime/native32/native32.c').as_posix()+'"')
    baseline=output/'void-runtime-baseline.c'; baseline.write_text(original_runtime)
    watched=[ROOT/'tools/lift_game.py',ROOT/'native/void_runtime.c',ROOT/'native/recomp_types.h',
        ROOT/'tools/prepare_native_runtime.py',ROOT/'generated/native-runtime/native32.c',
        ROOT/'generated/native-runtime/runtime-receipt.json',
        ROOT/'tests/x87_state_audit_probe.c',ROOT/'tests/test_x87_state_audit.py']
    for directory in ('reference/pcrecomp/runtime/native32','reference/pcrecomp/runtime/recomp32'):
        watched += [p for p in (ROOT/directory).iterdir()if p.suffix in('.c','.h')]
    before={str(p.relative_to(ROOT)):sha(p)for p in watched}
    compiler,env,sdk=compiler_environment()
    args=[str(compiler),'/nologo','/O2','/std:c11','/W3','/D_CRT_SECURE_NO_WARNINGS','/DRECOMP_TRACE','/Inative',
        '/Ireference/pcrecomp/runtime/recomp32','/Ireference/pcrecomp/runtime/native32',f'/I{output}',
        'tests/x87_state_audit_probe.c',str(output/'x87-audit-functions.c'),
        'reference/pcrecomp/runtime/recomp32/image_loader.c','reference/pcrecomp/runtime/recomp32/recomp_trace.c',
        f'/Fo{output}\\']
    results=[]
    for fixed in (False,True):
        executable=output/('probe-fixed.exe'if fixed else'probe-baseline.exe')
        mode=['/DEXPECT_SNAPSHOT_FIXED='+str(int(fixed))]
        if not fixed: mode+=['/DVOID_AUDIT_RUNTIME_PATH="'+baseline.as_posix()+'"']
        command=args+mode+[f'/Fe{executable}','/link','/MACHINE:X86','/NXCOMPAT']
        compiled=subprocess.run(command,cwd=ROOT,env=env,text=True,capture_output=True)
        (output/('compile-fixed.log'if fixed else'compile-baseline.log')).write_text(compiled.stdout+compiled.stderr)
        if compiled.returncode: raise RuntimeError(compiled.stdout+compiled.stderr)
        tested=subprocess.run([str(executable)],cwd=ROOT,text=True,capture_output=True,timeout=20)
        results.append(dict(snapshot_fixed=fixed,output=tested.stdout+tested.stderr,exit=tested.returncode))
        print(tested.stdout+tested.stderr,end='')
    unchanged=before=={str(p.relative_to(ROOT)):sha(p)for p in watched}
    receipt=dict(status='DOUBLE_REMAINDER_AND_SNAPSHOT_PASS'if all(r['exit']==0 for r in results)and unchanged else 'FAILED',
        compiler=str(compiler),sdk=sdk,source_hashes=before,source_hashes_unchanged=unchanged,
        results=results,original_game_dll_executed=False,vendor_modified=False,
        user_interface_or_game_images=False,repair_implemented='exact-int64 and condition snapshots; double-input remainder',
        fprem1_and_cross_call_status_repaired=True,raw80_or_full_x87_environment_implemented=False)
    (output/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')
    assert receipt['status']=='DOUBLE_REMAINDER_AND_SNAPSHOT_PASS',receipt


if __name__=='__main__': main()
