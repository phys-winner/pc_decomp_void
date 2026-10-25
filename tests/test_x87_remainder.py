"""Differential-test actual emitted remainder and shared conditions against x87."""
import hashlib
import json
import math
from pathlib import Path
import random
import struct
import subprocess
import sys
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from lift_game import BoundedDisassembler,CheckedLifter,lift_function_linear
from tools.lift.generate import lift_function_linear as vendor_function
from tools.lift.lift32 import Lifter
from prepare_native_runtime import prepare
from test_memmove import compiler_environment


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def bits(value):return struct.unpack('<Q',struct.pack('<d',value))[0]


def ext64(raw):
    sign,exponent,fraction=raw>>63,(raw>>52)&0x7FF,raw&((1<<52)-1)
    if exponent==0x7FF:significand,extended=(1<<63)|(fraction<<11),0x7FFF
    elif not exponent:
        if not fraction:significand,extended=0,0
        else:
            high=fraction.bit_length()-1; significand=fraction<<(63-high); extended=high-1074+16383
    else:significand,extended=(1<<63)|(fraction<<11),exponent-1023+16383
    return struct.pack('<QH',significand,extended|(sign<<15))


def raw_state(left,right,cw):
    values=(ext64(left),ext64(right)); tags=0xFFFF
    for index,value in enumerate(values):
        significand,exponent=struct.unpack('<QH',value); exponent&=0x7FFF
        tag=1 if not significand and not exponent else 2 if exponent==0x7FFF else 0
        physical=(6+index)%8; tags=(tags&~(3<<(2*physical)))|(tag<<(2*physical))
    return struct.pack('<7I',cw,6<<11,tags,0,0,0,0)+b''.join(values)+bytes(60)


def fixtures(output):
    base=0x22001000; definitions={
        0x22001000:bytes.fromhex('d9f8c3'),0x22002000:bytes.fromhex('d9f5c3'),
        0x22006000:bytes.fromhex('d8d1c3'),0x22008000:bytes.fromhex('d9e5c3'),
        0x2200A000:bytes.fromhex('dd3fc3'),0x2200B000:bytes.fromhex('ffd2dfe0c3')}
    def direct(source,target,tail=False):
        return (b'\xe9'if tail else b'\xe8')+struct.pack('<i',target-source-5)+(b''if tail else bytes.fromhex('dfe0c3'))
    definitions.update({0x22003000:direct(0x22003000,0x22001000),
        0x22004000:direct(0x22004000,0x22001000,True),0x22005000:direct(0x22005000,0x22004000),
        0x22007000:direct(0x22007000,0x22006000),0x22009000:direct(0x22009000,0x22008000),
        0x2200C000:direct(0x2200C000,0x22006000,True),0x2200D000:direct(0x2200D000,0x2200C000)})
    raw=bytearray(0xC008)
    for address,code in definitions.items():raw[address-base:address-base+len(code)]=code
    section=SimpleNamespace(name='.text',virtual_address=0,raw_offset=0,raw_size=len(raw),virtual_size=len(raw),is_code=True)
    decoder=BoundedDisassembler(bytes(raw),base,[section]); addresses=set(definitions)
    header='#pragma once\n#define RECOMP_GENERATED_CODE\n#include "recomp_types.h"\n'
    header+='\n'.join(f'void sub_{a:08X}(void);'for a in sorted(addresses))+'\n'
    (output/'x87-rem-functions.h').write_text(header)
    for current in (False,True):
        functions=[]
        for address in sorted(addresses):
            body=decoder.disassemble_function(address,{})
            instructions=sorted({i.address:i for b in body.blocks.values()for i in b.instructions}.values(),key=lambda i:i.address)
            lifter=(CheckedLifter if current else Lifter)(lifted=addresses)
            generator=lift_function_linear if current else vendor_function
            functions.append(generator(lifter,f'sub_{address:08X}',instructions,set(body.blocks),address,
                                       indirect_targets=body.jump_targets,eh_resume=None))
        destination=output/('functions-current.c'if current else'functions-control.c')
        destination.write_text('#include "x87-rem-functions.h"\n'+'\n\n'.join(functions)+'\n')
    return {f'{a:08X}':code.hex()for a,code in sorted(definitions.items())}


def vectors(output):
    finite=[(bits(a),bits(b))for a,b in ((5.5,2),(7,2),(9,2),(-5.5,2),(5.5,-2),(-5.5,-2),
        (0.0,2),(-0.0,2),(1.0,1.5),(1.5,1),(2.5,1),(3.5,1),(4.5,1),(-2.5,1),
        (5e-324,1.5e-323),(1.5e-323,5e-324),(-5e-324,1.5e-323),
        (math.ldexp(1.75,1023),math.ldexp(1.5,-1022)))]
    for gap in (0,1,31,32,62,63,64,65,127,255,511,1023):
        finite.append((bits(math.ldexp(1.375,gap)),bits(1.75)))
    rng=random.Random(0x46505245)
    for _ in range(96):
        pair=[]
        for __ in range(2):
            raw=rng.getrandbits(64)
            if (raw>>52)&0x7FF==0x7FF:raw^=1<<52
            if raw&0x7FFFFFFFFFFFFFFF==0:raw|=1
            pair.append(raw)
        finite.append(tuple(pair))
    specials=[(bits(1),0x7FF0000000000000),(bits(-1),0xFFF0000000000000),
              (0x7FF0000000000000,bits(2)),(bits(7),0),(bits(7),1<<63),
              (0x7FF8000000001234,bits(2)),(bits(2),0x7FF8000000005678),
              (0x7FF0000000001234,bits(2))]
    cases=[]; payload=bytearray()
    for precision in (0,0x0200,0x0300):
        for rounding in (0,0x0400,0x0800,0x0C00):
            cw=0x007F|precision|rounding
            for nearest in (0,1):
                for left,right in finite+specials:
                    guard=any(((v>>52)&0x7FF)==0x7FF and v&((1<<52)-1) and not v&(1<<51)for v in (left,right))
                    payload.extend(struct.pack('<QQIII',left,right,cw,nearest,int(guard))+raw_state(left,right,cw))
                    cases.append({'left':f'{left:016X}','right':f'{right:016X}','cw':cw,'nearest':nearest,'guard':bool(guard)})
    for nearest in (0,1):
        for left,right in ((bits(7),0),(0x7FF0000000000000,bits(2))):
            cw=0x037E
            payload.extend(struct.pack('<QQIII',left,right,cw,nearest,0)+raw_state(left,right,cw))
            cases.append({'left':f'{left:016X}','right':f'{right:016X}','cw':cw,'nearest':nearest,'guard':False})
        for cw in (0x037E,0x037D,0x036F,0x0340):
            for left,right in ((bits(5.5),bits(2)),(bits(5e-324),bits(1.5e-323)),
                               (bits(math.ldexp(1.75,1023)),bits(math.ldexp(1.5,-1022)))):
                payload.extend(struct.pack('<QQIII',left,right,cw,nearest,0)+raw_state(left,right,cw))
                cases.append({'left':f'{left:016X}','right':f'{right:016X}','cw':cw,'nearest':nearest,'guard':False})
    path=output/'vectors.bin'; path.write_bytes(payload)
    return path,cases


def main():
    prepare(check=True)
    output=ROOT/'build/x87-remainder'; output.mkdir(parents=True,exist_ok=True)
    instructions=fixtures(output); data,cases=vectors(output)
    watched=[ROOT/path for path in ('native/recomp_types.h','native/void_runtime.c','tools/lift_game.py',
        'tools/prepare_native_runtime.py','generated/native-runtime/native32.c','generated/native-runtime/runtime-receipt.json',
        'tests/test_x87_remainder.py','tests/x87_remainder_probe.c')]
    watched += list(output.glob('*.c'))+list(output.glob('*.h'))+[data]
    for directory in ('reference/pcrecomp/runtime/native32','reference/pcrecomp/runtime/recomp32'):
        watched += [p for p in (ROOT/directory).iterdir()if p.suffix in ('.c','.h')]
    before={str(p.relative_to(ROOT)):sha(p)for p in watched}
    compiler,environment,sdk=compiler_environment(); results=[]; native_controls=[]
    for optimization,current in (('/O2',False),('/O1',True),('/O2',True)):
        name=('current'if current else'control')+'-'+optimization[1:]; executable=output/(name+'.exe')
        command=[str(compiler),'/nologo',optimization,'/std:c11','/W3','/D_CRT_SECURE_NO_WARNINGS','/DRECOMP_TRACE',
            '/Inative','/Ireference/pcrecomp/runtime/recomp32','/Ireference/pcrecomp/runtime/native32',f'/I{output}',
            'tests/x87_remainder_probe.c',str(output/('functions-current.c'if current else'functions-control.c')),
            'reference/pcrecomp/runtime/recomp32/image_loader.c','reference/pcrecomp/runtime/recomp32/recomp_trace.c',
            f'/Fo{output}\\',f'/Fe{executable}']
        if not current:command+=['/DCONTROL_ONLY']
        command+=['/link','/MACHINE:X86','/NXCOMPAT']
        compiled=subprocess.run(command,cwd=ROOT,env=environment,text=True,capture_output=True)
        (output/(name+'-compile.log')).write_text(compiled.stdout+compiled.stderr)
        assert compiled.returncode==0,compiled.stdout+compiled.stderr
        if current:
            for scheduled in (False,True):
                control_command=[str(executable),'--identity-scheduled'if scheduled else'--identity']
                control=subprocess.run(control_command,cwd=ROOT,text=True,capture_output=True,timeout=30)
                native_controls.append({'optimization':optimization,'scheduled':scheduled,'command':control_command,
                    'exit':control.returncode,'output':control.stdout+control.stderr})
                print(name,'native-identity',control.stdout+control.stderr,end='',flush=True)
                assert control.returncode==0,native_controls[-1]
        result=subprocess.run([str(executable),str(data)],cwd=ROOT,text=True,capture_output=True,timeout=30)
        results.append({'optimization':optimization,'current':current,'command':command,
                        'exit':result.returncode,'output':result.stdout+result.stderr})
        print(name,result.stdout+result.stderr,end='',flush=True)
        assert result.returncode==0,results[-1]
    unchanged=before=={str(p.relative_to(ROOT)):sha(p)for p in watched}
    assert unchanged
    receipt={'status':'PASS_DOUBLE_INPUT_SCOPE','compiler':str(compiler),'compiler_sha256':sha(compiler),'sdk':sdk,
             'cases':len(cases),'vectors':cases,'synthetic_instructions':instructions,'results':results,
             'native_identity_controls':native_controls,
             'host_image_assertion':'All108bytes identical, except verifiedAMD/ES0/exactlyzeroedbytes12..25 with every other byte identical',
             'host_ES1_metadata_assertion':'All108bytes identical; no exception for metadata',
             'native_metadata_rationale':{'AMD_FXSAVE_ES_condition':'https://www.amd.com/content/dam/amd/en/documents/processor-tech-docs/programmer-references/26569.pdf',
                'Intel_FXSAVE_context_use':'https://www.intel.com/content/dam/www/public/us/en/documents/manuals/64-ia-32-architectures-software-developer-vol-2a-manual.pdf',
                'Windows_save_instruction_identified':False},
             'source_hashes':before,'source_hashes_unchanged':unchanged,'vendor_modified':False,
             'original_game_code_executed':False,'raw80_or_full_environment_implemented':False,
             'guest_sticky_status_or_exception_dispatch_implemented':False}
    (output/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')


if __name__=='__main__':main()
