"""Original Video VLC constructor versus its exact generated C; no game/device."""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX,
    UC_X86_REG_EBX, UC_X86_REG_ESP, UC_X86_REG_EBP, UC_X86_REG_ESI,
    UC_X86_REG_EDI, UC_X86_REG_EIP, UC_X86_REG_EFLAGS)
from test_memmove import compiler_environment

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from lift_game import BoundedDisassembler, CheckedLifter, analyze_pe, lift_function_linear
SHA = "9500d18964bbbfe02c022c8d4594807f0082c0fd750af9c29ca226752ea63957"
BASE, ENTRY, ALLOC = 0x10000000, 0x10019760, 0x10017440
STACK, DATA, HEAP, RETURN = 0x20000000, 0x20010000, 0x21000000, 0x30000000
SPAN = 0x4000
REGS = (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EBX,
        UC_X86_REG_ESP, UC_X86_REG_EBP, UC_X86_REG_ESI, UC_X86_REG_EDI)
INITIAL = (0x76543210, 0x10203040, 0x50607080, 0x11223344,
           STACK + 0x800, 0x55667788, 0x99AABBCC, 0xDDEEFF00)

DRIVER = r'''
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <io.h>
#include <fcntl.h>
#define RECOMP_GENERATED_CODE
#include "recomp_types.h"
uint32_t g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi,g_cur_func;
ptrdiff_t g_mem_base;
static uint32_t allocated,calls;
void sub_15017440(void) {
    uint32_t amount=g_eax*MEM32(g_esp+4);
    if(amount<16)amount=16;
    amount=(amount+15)&~15u;
    if(allocated+amount>0x4000)exit(91);
    g_eax=0x21000000u+allocated;
    memset((void*)ADDR(g_eax),0,amount); allocated+=amount;calls++;
    g_esp+=4;
    g_flag_k=FK_EFLAGS;g_flag_a=2;g_flag_b=g_flag_cf=0;
}
/* BODY */
#undef eax
#undef ecx
#undef edx
#undef ebx
#undef esp
#undef ebp
#undef esi
#undef edi
int main(int argc,char **argv) {
    if(argc!=2)return 90;
    void *stack=VirtualAlloc((void*)0x20000000u,0x1000,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
    void *data=VirtualAlloc((void*)0x20010000u,0x1000,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
    void *heap=VirtualAlloc((void*)0x21000000u,0x4000,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
    if(stack!=(void*)0x20000000u||data!=(void*)0x20010000u||heap!=(void*)0x21000000u)return 92;
    FILE *input=fopen(argv[1],"rb");if(!input)return 93;
    if(_setmode(_fileno(stdout),_O_BINARY)==-1)return 94;
    while(fread(data,0x1000,1,input)==1) {
        memset(stack,0xA5,0x1000);memset(heap,0xCC,0x4000);allocated=calls=0;
        g_eax=0x76543210;g_ecx=0x10203040;g_edx=0x50607080;g_ebx=0x11223344;
        g_esp=0x20000800;g_ebp=0x55667788;g_esi=0x99AABBCC;g_edi=0xDDEEFF00;
        g_flag_k=FK_EFLAGS;g_flag_a=2;g_flag_b=g_flag_cf=0;
        MEM32(g_esp)=0x30000000u;MEM32(g_esp+4)=0x20010000u;
        sub_15019760();
        uint32_t state[]={g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi,allocated,calls};
        if(fwrite(state,sizeof state,1,stdout)!=1||fwrite(heap,0x4000,1,stdout)!=1)return 95;
    }
    return ferror(input)||fflush(stdout)?96:0;
}
'''


def descriptor(width, consumed):
    data = bytearray(0x1000)
    data[0] = width
    group = 1 << (width - consumed)
    for i in range(1 << width):
        leaf = 0x800 + (i // group) * 4
        struct.pack_into("<I", data, 4 + i * 4, DATA + leaf)
        data[leaf:leaf + 3] = bytes((0, (i // group + 1) & 255, consumed))
    return bytes(data)


class Oracle:
    def __init__(self, image):
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc.mem_map(BASE, 0x50000); self.uc.mem_write(BASE, image)
        for address, size in ((STACK, 0x1000), (DATA, 0x1000), (HEAP, SPAN), (RETURN, 0x1000)):
            self.uc.mem_map(address, size)
        self.uc.hook_add(UC_HOOK_CODE, self.allocate, begin=ALLOC, end=ALLOC)

    def allocate(self, uc, address, size, context):
        esp = uc.reg_read(UC_X86_REG_ESP)
        result, count = struct.unpack("<II", uc.mem_read(esp, 8))
        amount = uc.reg_read(UC_X86_REG_EAX) * count
        amount = (max(16, amount) + 15) & ~15
        assert self.allocated + amount <= SPAN
        pointer = HEAP + self.allocated
        uc.mem_write(pointer, bytes(amount)); self.allocated += amount; self.calls += 1
        uc.reg_write(UC_X86_REG_EAX, pointer); uc.reg_write(UC_X86_REG_ESP, esp + 4)
        uc.reg_write(UC_X86_REG_EFLAGS, 2); uc.reg_write(UC_X86_REG_EIP, result)

    def run(self, data, width):
        uc = self.uc; self.allocated = self.calls = 0
        uc.mem_write(STACK, b"\xA5" * 0x1000); uc.mem_write(DATA, data)
        uc.mem_write(HEAP, b"\xCC" * SPAN)
        uc.mem_write(INITIAL[4], struct.pack("<II", RETURN, DATA))
        for reg, value in zip(REGS, INITIAL): uc.reg_write(reg, value)
        uc.reg_write(UC_X86_REG_EFLAGS, 2)
        uc.emu_start(ENTRY, RETURN, count=200000)
        assert uc.reg_read(UC_X86_REG_EIP) == RETURN
        state = [uc.reg_read(reg) for reg in REGS] + [self.allocated, self.calls]
        heap = bytes(uc.mem_read(HEAP, SPAN))
        children = struct.unpack_from("<" + "I" * (1 << width), heap, 4)
        assert all(HEAP <= child < HEAP + self.allocated for child in children)
        assert state[4] == INITIAL[4] + 4
        assert tuple(state[i] for i in (3, 5, 6, 7)) == tuple(INITIAL[i] for i in (3, 5, 6, 7))
        return struct.pack("<10I", *state) + heap


def main():
    temporary_emit = sys.argv[1:] == ["--emitter"]
    if sys.argv[1:] and not temporary_emit: raise ValueError("Only --emitter is accepted")
    output = ROOT / ("build/video-vlc/emitter" if temporary_emit else "build/video-vlc")
    output.mkdir(parents=True, exist_ok=True)
    binary = ROOT / "research/ida/Video.dll"; raw = binary.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SHA
    pe = pefile.PE(data=raw, fast_load=True)
    image = pe.get_memory_mapped_image()
    assert image[0x197EA:0x197EC] == bytes.fromhex("f3a5")
    found = []
    for source in (ROOT / "generated/video-x86").glob("video_*.c"):
        m = re.search(r'^void sub_15019760\(void\) \{\n.*?^\}', source.read_text(), re.M | re.S)
        if m: found.append((source, m.group()))
    assert len(found) == 1
    source, body = found[0]
    if temporary_emit:
        image_path = ROOT / "generated/input/Video.dll"
        private = image_path.read_bytes()
        assert hashlib.sha256(private).hexdigest() == "1640c137addbb914b3e10181751e950205968b025763f4a19bd6819bbd1afb31"
        info = analyze_pe(str(image_path))
        decoder = BoundedDisassembler(private, 0x15000000, info.sections)
        function = decoder.disassemble_function(0x15019760, {})
        instructions = sorted({i.address: i for b in function.blocks.values()
                               for i in b.instructions}.values(), key=lambda i: i.address)
        lifter = CheckedLifter(lifted={0x15019760, 0x15017440}, precise_sbb=True, precise_carry=True)
        body = lift_function_linear(lifter, "sub_15019760", instructions,
                                   set(function.blocks), 0x15019760, indirect_targets=function.jump_targets)
    assert set(re.findall(r"RECOMP_CALL\(sub_([0-9A-F]+)\)", body)) == {"15017440", "15019760"}
    driver = output / "probe.c"; driver.write_text(DRIVER.replace("/* BODY */", body))
    scenarios = [(width, consumed) for width in range(1, 9) for consumed in range(1, width + 1)]
    cases = output / "cases.bin"; cases.write_bytes(b"".join(descriptor(*case) for case in scenarios))
    compiler, env, sdk = compiler_environment(); exe = output / "probe.exe"
    compiled = subprocess.run([str(compiler), "/nologo", "/O2", "/W3", "/std:c11",
        "/D_CRT_SECURE_NO_WARNINGS", "/I" + str(ROOT / "native"), str(driver),
        f"/Fo{output}\\", f"/Fe{exe}"], cwd=ROOT, env=env, capture_output=True, text=True)
    (output / "compile.log").write_text(compiled.stdout + compiled.stderr)
    if compiled.returncode: raise RuntimeError(compiled.stdout + compiled.stderr)
    translated = subprocess.run([str(exe), str(cases)], capture_output=True, timeout=30)
    if translated.returncode: raise RuntimeError(f"C probe exit {translated.returncode}: {translated.stderr!r}")
    record_size = 40 + SPAN
    assert len(translated.stdout) == len(scenarios) * record_size
    oracle = Oracle(image); results = []
    for index, (width, consumed) in enumerate(scenarios):
        expected = oracle.run(descriptor(width, consumed), width)
        actual = translated.stdout[index * record_size:(index + 1) * record_size]
        a, b = expected[40:], actual[40:]
        slots = [i for i in range(1 << width) if a[4+i*4:8+i*4] != b[4+i*4:8+i*4]]
        row = {"width": width, "child_consumed_bits": consumed, "identical": expected == actual,
               "registers_and_allocator_match": expected[:40] == actual[:40], "different_child_slots": slots,
               "null_children_in_C": sum(struct.unpack_from("<I", b, 4 + i*4)[0] == 0 for i in range(1 << width))}
        results.append(row)
    failures = sum(not row["identical"] for row in results)
    receipt = {"status": "FAIL" if failures else "PASS", "original_sha256": SHA,
        "source_function": "0x10019760", "rep_source_instruction": "0x100197EA: F3 A5",
        "generated_source": str(source.relative_to(ROOT)), "generated_body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "temporary_actual_emitter": temporary_emit,
        "project_lifter_sha256": hashlib.sha256((ROOT / "tools/lift_game.py").read_bytes()).hexdigest(),
        "compiler": str(compiler), "sdk": sdk, "allocation": "same deterministic zero allocator stub at original calloc entry",
        "original_EXECUTION": "Unicorn x86", "C_EXECUTION": "MSVC x86 /O2; exact generated constructor",
        "no_ui_or_devices_or_original_native_code_execution": True, "cases": len(results), "failures": failures, "results": results}
    (output / "result.json").write_text(json.dumps(receipt, indent=2))
    print(f"Video VLC original/generated differential: {len(results)} cases, {failures} failures")
    for row in results:
        if not row["identical"]: print(row); break
    assert failures == 0, "Original REP MOVSD child-pointer propagation differs from generated C"


if __name__ == "__main__": main()
