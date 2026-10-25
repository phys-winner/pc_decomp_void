"""Compare original FirstRun x86 with generated C when native readiness is0."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "reference/pcrecomp"))
from tools.pe.pe_analyze import analyze_pe
from tools.disasm.disasm32 import Disassembler
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX,
    UC_X86_REG_EBX, UC_X86_REG_ESP, UC_X86_REG_EBP, UC_X86_REG_ESI,
    UC_X86_REG_EDI, UC_X86_REG_EIP, UC_X86_REG_EFLAGS)

ENTRY, SIZE, BASE = 0x436A10, 0x8D, 0x400000
STACK, RETURN, API = 0x20000000, 0x30000000, 0x31000000
KEY, GLOBAL = BASE + 0x200, 0x44B94C
REGS = [UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EBX,
        UC_X86_REG_ESP, UC_X86_REG_EBP, UC_X86_REG_ESI, UC_X86_REG_EDI]
INITIAL = [0x76543210, 0x10203040, 0x50607080, 0x11223344,
           STACK + 0x8000, 0x55667788, 0x99AABBCC, 0xDDEEFF00]


def original(image, scenario):
    opened, queried, kind, value, closed, initial_global = scenario
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(BASE, len(image)); uc.mem_write(BASE, bytes(image))
    uc.mem_map(STACK, 0x10000); uc.mem_map(RETURN, 0x1000); uc.mem_map(API, 0x3000)
    uc.mem_write(STACK, bytes([0xA5]) * 0x10000)
    uc.mem_write(INITIAL[4], struct.pack('<II', RETURN, KEY))
    uc.mem_write(GLOBAL, struct.pack('<I', initial_global))
    calls = []

    def read32(address):
        return struct.unpack('<I', uc.mem_read(address, 4))[0]

    def write32(address, value):
        uc.mem_write(address, struct.pack('<I', value))

    def hook(machine, address, size, user):
        if address not in (API, API + 0x1000, API + 0x2000):
            return
        sp = uc.reg_read(UC_X86_REG_ESP)
        args = [read32(sp + 4 + i * 4) for i in range(6)]
        if address == API:
            assert args[:4] == [0x80000002, KEY, 0, 1]
            calls.append('open')
            if opened == 0: write32(args[4], 0xBEEF)
            status, argc = opened, 5
        elif address == API + 0x1000:
            assert args[0] == 0xBEEF and args[1] == 0x441E78 and args[2] == 0
            assert read32(args[5]) == 4
            calls.append('query')
            if queried == 0:
                write32(args[3], kind); write32(args[4], value)
            status, argc = queried, 6
        else:
            assert args[0] == 0xBEEF
            calls.append('close')
            status, argc = closed, 1
        uc.reg_write(UC_X86_REG_EAX, status)
        uc.reg_write(UC_X86_REG_ESP, sp + 4 + argc * 4)
        uc.reg_write(UC_X86_REG_EIP, read32(sp))

    uc.hook_add(UC_HOOK_CODE, hook)
    for reg, register_value in zip(REGS, INITIAL): uc.reg_write(reg, register_value)
    uc.reg_write(UC_X86_REG_EFLAGS, 2)
    uc.emu_start(ENTRY, RETURN, count=1000)
    assert uc.reg_read(UC_X86_REG_EIP) == RETURN
    return [uc.reg_read(reg) for reg in REGS] + [uc.reg_read(UC_X86_REG_EFLAGS) & 0x8D5,
                                               read32(GLOBAL), len(calls)]


DRIVER = r'''
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#define RECOMP_GENERATED_CODE
#include "recomp_types.h"
uint32_t g_eax,g_ecx,g_edx,g_esp,g_ebx,g_esi,g_edi,g_ebp,g_fs_base,g_gs_base,g_cur_func;
ptrdiff_t g_mem_base;
double g_st[8]; int g_fp_top; uint16_t g_fpu_cw;
uint16_t g_seg_cs,g_seg_ds,g_seg_es,g_seg_fs,g_seg_gs,g_seg_ss;
uint64_t g_mm[8]; xmm_t g_xmm[8]; uint32_t g_mxcsr;
uint32_t g_icall_trace[ICALL_TRACE_SIZE],g_icall_from[ICALL_TRACE_SIZE],g_icall_trace_idx,g_icall_count;
const recomp_dispatch_entry_t recomp_dispatch_table[]={{0,NULL}};
const uint32_t recomp_dispatch_count=0;
static uint32_t opened,queried,kind,value,closed,calls;
int void_native_config_ready(void) { return 0; }
static void api_open(void) {
    uint32_t *a=(uint32_t *)ADDR(g_esp+4);
    if(a[0]!=0x80000002u || a[1]!=0x400200u || a[2]!=0 || a[3]!=1) exit(90);
    calls++; if(!opened) MEM32(a[4])=0xBEEF; g_eax=opened;g_esp+=24;
}
static void api_query(void) {
    uint32_t *a=(uint32_t *)ADDR(g_esp+4);
    if(a[0]!=0xBEEF || a[1]!=0x441E78u || a[2]!=0 || MEM32(a[5])!=4) exit(91);
    calls++; if(!queried){MEM32(a[3])=kind;MEM32(a[4])=value;}g_eax=queried;g_esp+=28;
}
static void api_close(void) {
    if(MEM32(g_esp+4)!=0xBEEF) exit(92);
    calls++;g_eax=closed;g_esp+=8;
}
recomp_func_t recomp_lookup_manual(uint32_t va) {
    if(va==0x31000000u)return api_open;
    if(va==0x31001000u)return api_query;
    if(va==0x31002000u)return api_close;
    return NULL;
}
recomp_func_t recomp_lookup(uint32_t va){(void)va;return NULL;}
recomp_func_t recomp_lookup_import(uint32_t va){(void)va;return NULL;}
/* BODY */
#undef eax
#undef ecx
#undef edx
#undef ebx
#undef esp
#undef ebp
#undef esi
#undef edi
int main(int argc,char **argv){
    if(argc!=8)return 93;
    FILE *f=fopen(argv[1],"rb");if(!f)return 94;fseek(f,0,SEEK_END);long span=ftell(f);rewind(f);
    void *im=VirtualAlloc(NULL,span,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
    if(!im)return 95;
    g_mem_base=(ptrdiff_t)((uint32_t)(uintptr_t)im-0x400000u);
    void *stack=VirtualAlloc((void*)ADDR(0x20000000u),0x10000,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
    if(stack!=(void*)ADDR(0x20000000u))return 95;
    if(fread(im,1,span,f)!=(size_t)span)return 96;fclose(f);memset(stack,0xA5,0x10000);
    opened=strtoul(argv[2],NULL,0);queried=strtoul(argv[3],NULL,0);kind=strtoul(argv[4],NULL,0);
    value=strtoul(argv[5],NULL,0);closed=strtoul(argv[6],NULL,0);MEM32(0x44B94C)=strtoul(argv[7],NULL,0);
    g_eax=0x76543210;g_ecx=0x10203040;g_edx=0x50607080;g_ebx=0x11223344;g_esp=0x20008000;
    g_ebp=0x55667788;g_esi=0x99AABBCC;g_edi=0xDDEEFF00;
    MEM32(g_esp)=0x30000000;MEM32(g_esp+4)=0x400200;
    sub_00436A10();
    printf("%u %u %u %u %u %u %u %u %u %u %u\n",g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi,
           recomp_eflags(g_flag_k,g_flag_a,g_flag_b,g_flag_cf,1)&0x8D5,MEM32(0x44B94C),calls);
    return 0;
}
'''


def main():
    binary = ROOT / 'generated/input/Game.exe'
    expected_hash = json.loads((ROOT / 'port.json').read_text())['game_exe']['recovered_sha256']
    raw = binary.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == expected_hash
    info = analyze_pe(str(binary)); reader = Disassembler(raw, info.image_base, info.sections)
    assert info.image_base == BASE
    span = (max(s.va_end for s in info.sections) + 0xFFF) & ~0xFFF
    image = bytearray(span)
    for section in info.sections:
        image[section.virtual_address:section.virtual_address+section.raw_size] = raw[section.raw_offset:section.raw_offset+section.raw_size]
    for slot, target in ((0x43F004,API),(0x43F008,API+0x1000),(0x43F000,API+0x2000)):
        struct.pack_into('<I',image,slot-BASE,target)
    source = next(p for p in (ROOT/'generated/game-x86').glob('recomp_*.c')
                  if 'void sub_00436A10(void)' in p.read_text())
    full = source.read_text(); start = full.index('void sub_00436A10(void)')
    end = full.find('\nvoid ',start+1); body = full[start:end if end >= 0 else len(full)]
    assert 'void_lift_trap' not in body
    vswhere = str(Path(os.environ["ProgramFiles(x86)"]) / "Microsoft Visual Studio/Installer/vswhere.exe")
    vs = Path(subprocess.check_output([vswhere,'-latest','-products','*','-property','installationPath'],text=True).strip())
    msvc = sorted((vs/'VC/Tools/MSVC').iterdir(),reverse=True)[0]
    sdk = Path(os.environ["ProgramFiles(x86)"]) / "Windows Kits/10"
    version = sorted((sdk/'Lib').iterdir(),reverse=True)[0].name
    compiler = msvc/'bin/Hostx64/x86/cl.exe'; env=os.environ.copy()
    env['PATH']=str(compiler.parent)+os.pathsep+env['PATH']
    env['INCLUDE']=';'.join(str(p) for p in (msvc/'include',sdk/f'Include/{version}/ucrt',sdk/f'Include/{version}/shared',sdk/f'Include/{version}/um'))
    env['LIB']=';'.join(str(p) for p in (msvc/'lib/x86',sdk/f'Lib/{version}/ucrt/x86',sdk/f'Lib/{version}/um/x86'))
    scenarios=[(opened,queried,kind,value,closed,flag)
               for opened,queried,kind,value,closed in ((0,2,4,0,0),(0,0,4,0,0),(0,0,4,1,0),
                   (0,0,4,0xFFFFFFFF,0),(0,0,1,0,0),(0,5,4,0,0),(2,0,4,0,0),(5,0,4,0,0),
                   (0,0,4,0,5),(0,0,4,1,5)) for flag in (0,1,2)]
    rows=[]
    with tempfile.TemporaryDirectory(prefix='void-first-run-') as directory:
        tmp=Path(directory); c=tmp/'check.c'; exe=tmp/'check.exe'; mapped=tmp/'image.bin'
        c.write_text(DRIVER.replace('/* BODY */',body));mapped.write_bytes(image)
        built=subprocess.run([str(compiler),'/nologo','/O2','/std:c11','/D_CRT_SECURE_NO_WARNINGS',
            '/I'+str(ROOT/'native'),'/I'+str(ROOT/'reference/pcrecomp/runtime/recomp32'),str(c),'/Fo'+str(tmp/'check.obj'),
            '/Fe'+str(exe),'/link','/BASE:0x70000000','/DYNAMICBASE:NO','/STACK:262144'],
            env=env,cwd=tmp,text=True,capture_output=True)
        if built.returncode:raise RuntimeError(built.stdout+built.stderr)
        for scenario in scenarios:
            expected=original(image,scenario)
            actual=list(map(int,subprocess.check_output([str(exe),str(mapped),*map(str,scenario)],text=True).split()))
            assert actual==expected,(scenario,expected,actual)
            boolean=expected[0]&0xFF
            wanted=int(bool(scenario[0] or scenario[1] or scenario[2]!=4 or scenario[3]))
            assert boolean==wanted,(scenario,boolean,wanted)
            rows.append({'open':scenario[0],'query':scenario[1],'type':scenario[2],'value':scenario[3],
                         'close':scenario[4],'global_before':scenario[5],'AL':boolean,'global_after':actual[9]})
    report=['# isFirstRun differential test','',f'PASS: {len(rows)} scenarios. Original x86 in Unicorn and current generated C compiled with MSVC x86 /O2 match all eight GPRs, six arithmetic flags, global mutation and API call counts.',
            '', 'The native configuration readiness getter is stubbed to0, so this checks the preserved original predicate. The enabled configuration gate has its own actual-host-getter ABI test in tests/test_native_config_first_run.py.',
            '',f'Original image SHA-256: `{expected_hash}`.',
            f'Generated function SHA-256: `{hashlib.sha256(body.encode()).hexdigest()}`.',
            '', 'Function: `?isFirstRun@@YA_NPB_W@Z`, VA `0x00436A10`, 141 bytes.',
            '', 'Result: missing FirstRun returns true in both original and generated code. A successful REG_DWORD zero returns false. A nonzero DWORD, wrong type, failed open or failed query returns true. RegCloseKey status does not change a successfully read DWORD result.',
            '', 'The window-global value at 0x0044B94C is cleared only when its initial value is 1. This happens identically in both executions.',
            '', 'Registry APIs are deterministic stubs; no real registry values or game configuration were changed. Generated C uses the existing runtime g_mem_base offset for its standalone image/stack allocation; guest addresses and tested body are unchanged. This tests this function and its flag branches, not its caller, destructor coverage, Config.exe writes or DLL initialization.', '',
            '| Open status | Query status | Type | DWORD | Close status | AL |','|---:|---:|---:|---:|---:|---:|']
    report += [f"| {r['open']} | {r['query']} | {r['type']} | {r['value']} | {r['close']} | {r['AL']} |" for r in rows if r['global_before']==0]
    (ROOT/'research/first-run-differential.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
    print(f'PASS: {len(rows)} FirstRun scenarios; original and generated x86 registers/flags/global/API calls match')


if __name__=='__main__':main()
