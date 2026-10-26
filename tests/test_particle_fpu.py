"""Differential the real particle body, independent global helpers, and production guard."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from build_android import CLANG, HOST_FLAGS, Image, localize_fpu, localize_sse
from build_x86_incremental import compiler_environment
from test_local_fpu import function


def main():
    out=ROOT/'build/particle-fpu-test';out.mkdir(parents=True,exist_ok=True)
    paths=[ROOT/'generated/renderer-x86/renderer_0052.c',ROOT/'generated/input/RendererD3D.dll',
           ROOT/'android/host/renderer_particle_native.c',ROOT/'android/runtime/recomp_types.h',
           ROOT/'tools/build_android.py',ROOT/'reference/pcrecomp/runtime/recomp32/recomp_types.h']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    for plain in (False,True):
        macros=subprocess.run([str(CLANG),*HOST_FLAGS,*(['-DRECOMP_PLAIN_MEMORY'] if plain else []),
            '-E','-dM',str(paths[2])],cwd=ROOT,capture_output=True,text=True,check=True).stdout.splitlines()
        assert ('#define RECOMP_MEM_QUAL' if plain else '#define RECOMP_MEM_QUAL volatile') in [m.rstrip() for m in macros]
    body=function(paths[0],'sub_160902D0').encode()+b'\n'
    upstream=paths[-1].read_text(encoding='utf-8')
    helpers='\n'.join(re.search(r'^static inline '+result+' '+name+r'\([^)]*\) \{.*?^\}',upstream,re.M|re.S)[0].replace(name,renamed,1)
        for result,name,renamed in [('void','fp_push_impl','oracle_fp_push'),('double','fp_pop_impl','oracle_fp_pop')])
    oracle_prefix=helpers+'\n#undef fp_push\n#undef fp_pop\n#define fp_push(v) oracle_fp_push(_st, &_fp_top, (v))\n#define fp_pop() oracle_fp_pop(_st, &_fp_top)\n'
    oracle_suffix='\n#undef fp_push\n#undef fp_pop\n#define fp_push(v) fp_push_impl(_st, &_fp_top, (v))\n#define fp_pop() fp_pop_impl(_st, &_fp_top)\n'
    header=paths[3].read_text(encoding='utf-8')
    header=header.replace('#if defined(_MSC_VER) || !defined(__aarch64__)','#if 0',1)
    header,count=re.subn(r'static inline uint64_t __rdtsc\(void\) \{.*?\n\}','',header,flags=re.S);assert count==1
    header,count=re.subn(r'^#define ADDR\(va\).+$','static void *guest_address(uint32_t va);\n#define ADDR(va) ((uintptr_t)guest_address((uint32_t)(va)))',header,flags=re.M);assert count==1
    (out/'runtime-fixture.h').write_text(header,encoding='utf-8')
    image=Image(paths[1]);constants=bytearray()
    for at in range(0x162d0000,0x16370000,4):
        value=image.u32(at);constants.extend((value or 0).to_bytes(4,'little'))
    constants_file=out/'renderer-constants.bin';constants_file.write_bytes(constants)
    common=(ROOT/'tests/local_fpu_probe.c').read_text(encoding='utf-8')
    declarations=common[:common.index('#define BASE')]
    snapshots=common[common.index('#undef eax'):common.index('static snapshot observed_yields')]
    guard=re.sub(r'^#include .*\n','',paths[2].read_text(encoding='utf-8'),flags=re.M)
    fixture=(ROOT/'tests/particle_fpu_probe.c').read_text(encoding='utf-8')
    _,env,_=compiler_environment();env['LIB']=env['LIB'].replace('\\x86','\\x64')
    results=[]
    for local,sse,plain in [(local,sse,plain) for plain in (False,True) for local in (False,True)
                            for sse in ((False,True) if local else (False,))]:
        combined=localize_sse(body) if sse else body
        original=oracle_prefix+combined.decode().replace('void sub_160902D0(void)','void original_particle(void)',1)+oracle_suffix
        fast=localize_fpu(combined).decode();assert 'double l_st[8]' in fast and 'void_renderer_particle_finite()' in fast
        source=out/('probe-reg%d-sse%d-plain%d.c'%(local,sse,plain))
        source.write_text(fixture.replace('/* DECLARATIONS */',declarations).replace('/* GUARD */',guard)
            .replace('/* ORIGINALS */',original).replace('/* LOCALIZED */',fast).replace('/* SNAPSHOTS */',snapshots),encoding='utf-8')
        exe=source.with_suffix('.exe')
        command=[str(CLANG),'--target=x86_64-pc-windows-msvc','-fuse-ld=link','-O2','-std=c11',
                 '-fno-strict-aliasing','-fwrapv','-ffp-contract=off','-DRECOMP_TRACE','-DRECOMP_YIELD_EVERY=1',
                 *(['-DRECOMP_LOCAL_REGS'] if local else []),*(['-DRECOMP_PLAIN_MEMORY'] if plain else []),str(source),'-o',str(exe)]
        built=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True)
        source.with_suffix('.compile.log').write_text(built.stdout+built.stderr,encoding='utf-8')
        assert built.returncode==0,built.stdout+built.stderr
        checked=subprocess.run([str(exe),str(constants_file)],cwd=ROOT,capture_output=True,text=True,timeout=60)
        assert checked.returncode==0,checked.stdout+checked.stderr
        print(f'regs={local} sse={sse} plain={plain}: {checked.stdout.strip()}',flush=True)
        results.append(dict(local_registers=local,local_sse=sse,plain_memory=plain,result=checked.stdout.strip()))
    assert hashes=={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (out/'result.json').write_text(json.dumps(dict(status='PASS',source_hashes=hashes,results=results,
        oracle='exact emitted body with pinned upstream global x87 helpers; actual production guard',
        original_pe_executed=False,fixture_adaptations=['architecture guard','unused ARM timer removed','bounded guest address mapping'],
        constants_image_sha256=hashlib.sha256(constants).hexdigest()),indent=2),encoding='utf-8')


if __name__=='__main__':main()
