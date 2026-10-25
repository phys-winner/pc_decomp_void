"""Differential the exact emitted SAT bodies against the Android local-x87 transform."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import build_android
from build_android import CLANG, Image, localize_fpu, localize_sse
from build_x86_incremental import compiler_environment


def function(path,name):
    source=path.read_text(encoding='utf-8')
    found=re.search(r'^void '+name+r'\(void\) \{.*?^\}',source,re.M|re.S)
    assert found,(path,name)
    return found[0]


def main():
    out=ROOT/'build/local-fpu-test';out.mkdir(parents=True,exist_ok=True)
    sources=[ROOT/'generated/engine-x86/engine_0023.c',ROOT/'generated/renderer-x86/renderer_0074.c',
             ROOT/'android/runtime/recomp_types.h',ROOT/'tools/build_android.py',
             ROOT/'reference/pcrecomp/runtime/recomp32/recomp_types.h']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    functions=[function(sources[0],'sub_1105E810'),function(sources[1],'sub_160D6ED0')]
    untouched=b'void sub_1105E800(void) {\n    fp_push(3); fp_pop();\n}\n'
    assert localize_fpu(untouched)==untouched
    for forbidden in ('RECOMP_CALL(sub_11000000);','RECOMP_ICALL(0x11000000);','fp_push_i64(3);'):
        unsupported=functions[0].replace('RECOMP_ENTER(',forbidden+'\n    RECOMP_ENTER(',1).encode()+b'\n'
        try: localize_fpu(unsupported)
        except AssertionError: pass
        else: raise AssertionError('unsupported leaf was localized: '+forbidden)
    fixture=out/'sat_fixture.c';fixture.write_text(functions[0]+'\n',encoding='utf-8')
    previous_release,previous_out=build_android.RELEASE,build_android.OUT
    try:
        build_android.RELEASE={'name':'different-release'}
        build_android.OUT=out/'override'
        unchanged,flags=build_android.override_source(fixture,False)
        assert unchanged==fixture and not flags,'other releases must bypass the target-specific FP transform'
        build_android.RELEASE=None
        patched,_=build_android.override_source(fixture,False)
        assert patched!=fixture and b'double l_st[8]' in patched.read_bytes()
    finally:
        build_android.RELEASE,build_android.OUT=previous_release,previous_out
    assert Image(ROOT/'generated/input/Engine.dll').u32(0x11122ce0)==0x3f7fffef
    assert Image(ROOT/'generated/input/RendererD3D.dll').u32(0x162d2a64)==0x3f7fffef
    upstream=sources[4].read_text(encoding='utf-8')
    helpers='\n'.join(re.search(r'^static inline '+result+' '+name+r'\([^)]*\) \{.*?^\}',
        upstream,re.M|re.S)[0].replace(name,renamed,1)
        for result,name,renamed in (('void','fp_push_impl','oracle_fp_push'),('double','fp_pop_impl','oracle_fp_pop')))
    oracle_prefix=helpers+'''\n#undef fp_push
#undef fp_pop
#define fp_push(v) oracle_fp_push(_st, &_fp_top, (v))
#define fp_pop() oracle_fp_pop(_st, &_fp_top)
'''
    oracle_suffix='''\n#undef fp_push
#undef fp_pop
#define fp_push(v) fp_push_impl(_st, &_fp_top, (v))
#define fp_pop() fp_pop_impl(_st, &_fp_top)
'''
    header=sources[2].read_text(encoding='utf-8')
    guard='#if defined(_MSC_VER) || !defined(__aarch64__)'
    assert header.count(guard)==1
    header=header.replace(guard,'#if 0',1)
    # Only adapt the unused ARM timer for the host compiler. All FP/state
    # helpers and register-transfer macros are the actual Android runtime.
    timer=re.compile(r'static inline uint64_t __rdtsc\(void\) \{.*?\n\}',re.S)
    header,count=timer.subn('',header)
    assert count==1
    header,count=re.subn(r'^#define ADDR\(va\).+$',
        'static void *guest_address(uint32_t va);\n#define ADDR(va) ((uintptr_t)guest_address((uint32_t)(va)))',
        header,flags=re.M)
    assert count==1
    (out/'runtime-fixture.h').write_text(header,encoding='utf-8')
    driver=(ROOT/'tests/local_fpu_probe.c').read_text(encoding='utf-8')
    _,env,_=compiler_environment()
    env['LIB']=env['LIB'].replace('\\x86','\\x64')
    results=[]
    configurations=[(local,sse,plain) for plain in (False,True) for local in (False,True)
                    for sse in ((False,True) if local else (False,))]
    for local,sse,plain in configurations:
        combined=('\n'.join(functions)+'\n').encode()
        if sse: combined=localize_sse(combined)
        originals=combined.decode()
        for name,renamed in (('sub_1105E810','original_engine'),('sub_160D6ED0','original_renderer')):
            originals=originals.replace('void '+name+'(void)','void '+renamed+'(void)',1)
        originals=oracle_prefix+originals+oracle_suffix
        fast=localize_fpu(combined).decode()
        assert fast.count('double l_st[8]')==2 and fast.count('_fp_global(void)')==2
        text=driver.replace('/* ORIGINALS */',originals).replace('/* LOCALIZED */',fast)
        source=out/('probe-reg%d-sse%d-plain%d.c'%(local,sse,plain));source.write_text(text,encoding='utf-8')
        executable=source.with_suffix('.exe')
        cmd=[str(CLANG),'--target=x86_64-pc-windows-msvc','-fuse-ld=link','-O2','-std=c11','-fno-strict-aliasing',
             '-fwrapv','-ffp-contract=off','-DRECOMP_TRACE','-DRECOMP_YIELD_EVERY=1',
             *(['-DRECOMP_LOCAL_REGS'] if local else []),*(['-DRECOMP_PLAIN_MEMORY'] if plain else []),
             str(source),'-o',str(executable)]
        compiled=subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,text=True)
        (source.with_suffix('.compile.log')).write_text(compiled.stdout+compiled.stderr,encoding='utf-8')
        assert compiled.returncode==0,compiled.stdout+compiled.stderr
        checked=subprocess.run([str(executable)],cwd=ROOT,capture_output=True,text=True,timeout=60)
        assert checked.returncode==0,checked.stdout+checked.stderr
        print('regs=%s sse=%s plain=%s: %s'%(local,sse,plain,checked.stdout.strip()))
        results.append(dict(local_registers=local,local_sse=sse,plain_memory=plain,output=checked.stdout.strip()))
    assert hashes=={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    (out/'result.json').write_text(json.dumps(dict(status='PASS',source_hashes=hashes,results=results,
        oracle='exact emitted bodies with pinned original global x87 helpers; same preexisting SSE pass when enabled',original_pe_executed=False,
        fixture_adaptations=['architecture guard','unused ARM RDTSC omitted','bounded guest address mapping']),indent=2),encoding='utf-8')


if __name__=='__main__':main()
