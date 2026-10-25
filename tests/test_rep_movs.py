"""REP MOVS is ordered element copying, including propagating overlaps."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
from types import SimpleNamespace

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX,
    UC_X86_REG_EBX, UC_X86_REG_ESP, UC_X86_REG_EBP, UC_X86_REG_ESI,
    UC_X86_REG_EDI, UC_X86_REG_EIP, UC_X86_REG_EFLAGS)
from test_memmove import compiler_environment

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from lift_game import BoundedDisassembler, CheckedLifter

CODE, STACK, DATA, RETURN = 0x10000000, 0x20000000, 0x20010000, 0x30000000
PAGE, FLAGS_MASK = 0x1000, 0xCD5
REGS = (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EBX,
        UC_X86_REG_ESP, UC_X86_REG_EBP, UC_X86_REG_ESI, UC_X86_REG_EDI)
PATTERN = bytes(((i * 37 + (i >> 3) * 19 + 0x5B) ^ (i >> 8)) & 255 for i in range(PAGE))
RAW = {1: bytes.fromhex("f3a4"), 2: bytes.fromhex("f366a5"), 4: bytes.fromhex("f3a5")}

DRIVER = r'''
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <io.h>
#include <fcntl.h>
#define RECOMP_GENERATED_CODE
#include "recomp_types.h"
uint32_t g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi,g_cur_func;
ptrdiff_t g_mem_base;
static int returned_df;
/* BODIES */
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
    if(stack!=(void*)0x20000000u||data!=(void*)0x20010000u)return 91;
    FILE *input=fopen(argv[1],"rb");if(!input)return 92;
    if(_setmode(_fileno(stdout),_O_BINARY)==-1)return 93;
    uint32_t args[6];uint8_t pattern[0x1000];
    for(uint32_t i=0;i<0x1000;i++)pattern[i]=(uint8_t)((i*37+(i>>3)*19+0x5B)^(i>>8));
    while(fread(args,sizeof args,1,input)==1) {
        memset(stack,0xA5,0x1000);memcpy(data,pattern,0x1000);
        g_eax=0x76543210;g_ecx=args[4];g_edx=0x50607080;g_ebx=0x11223344;
        g_esp=0x20000800;g_ebp=0x55667788;g_esi=args[2];g_edi=args[3];
        g_flag_k=FK_EFLAGS;g_flag_a=args[5];g_flag_b=0;g_flag_cf=args[5]&1;
        MEM32(g_esp)=0x30000000u;
        /* DISPATCH */
        uint32_t state[]={g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi,
            recomp_eflags(g_flag_k,g_flag_a,g_flag_b,g_flag_cf,returned_df)&0xCD5};
        if(fwrite(state,sizeof state,1,stdout)!=1||fwrite(stack,0x1000,1,stdout)!=1||fwrite(data,0x1000,1,stdout)!=1)return 94;
    }
    return ferror(input)||fflush(stdout)?95:0;
}
'''


def instruction_lines(raw):
    section = SimpleNamespace(name=".text", virtual_address=0, raw_offset=0,
        raw_size=len(raw), virtual_size=len(raw), is_code=True)
    decoder = BoundedDisassembler(raw, CODE, [section])
    decoder._windows, decoder._start = 0, CODE
    instructions = list(decoder.disassemble_at(CODE, len(raw)))
    lifter = CheckedLifter()
    return "\n".join(line for instruction in instructions for line in lifter.lift_instruction(instruction))


def cases():
    result = []
    for width in (1, 2, 4):
        for direction in (1, -1):
            for count in (0, 1, 2, 3, 8, 17, 64):
                distances = {0, -0x300, 0x300, -1, 1, -width, width,
                    -(width + 1), width + 1, -(width - 1), width - 1}
                if count:
                    distances |= {-(width * count - 1), width * count - 1,
                                  -width * count, width * count}
                for alignment in range(4):
                    for distance in sorted(distances):
                        source = DATA + 0x800 + alignment
                        destination = source + distance
                        seed = (2, 0x8D7, 0x843, 0x897)[len(result) % 4]
                        result.append((width, direction, source, destination, count, seed))
            result.append((width, direction, 0, 0xFFFFFFFF, 0, 0x8D7))
    return result


class Oracle:
    def __init__(self):
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        for address in (CODE, STACK, DATA, RETURN): self.uc.mem_map(address, PAGE)

    def run(self, case):
        width, direction, source, destination, count, flags = case
        uc = self.uc
        uc.mem_write(CODE, (b"\xFC" if direction > 0 else b"\xFD") + RAW[width] + b"\xC3")
        uc.ctl_remove_cache(CODE, CODE + PAGE)
        uc.mem_write(STACK, b"\xA5" * PAGE); uc.mem_write(DATA, PATTERN)
        initial = (0x76543210, count, 0x50607080, 0x11223344,
                   STACK + 0x800, 0x55667788, source, destination)
        uc.mem_write(initial[4], struct.pack("<I", RETURN))
        for reg, value in zip(REGS, initial): uc.reg_write(reg, value)
        uc.reg_write(UC_X86_REG_EFLAGS, flags)
        uc.emu_start(CODE, RETURN, count=4096)
        assert uc.reg_read(UC_X86_REG_EIP) == RETURN
        state = [uc.reg_read(reg) for reg in REGS] + [uc.reg_read(UC_X86_REG_EFLAGS) & FLAGS_MASK]
        wanted = bytearray(PATTERN)
        src, dst = source - DATA, destination - DATA
        for i in range(count):
            offset = i * width * direction
            wanted[dst + offset:dst + offset + width] = bytes(wanted[src + offset:src + offset + width])
        observed = bytes(uc.mem_read(DATA, PAGE))
        assert observed == wanted, "Original did not follow independent ordered element model"
        assert state[1] == 0 and state[4] == initial[4] + 4
        assert state[6:8] == [(source + direction * width * count) & 0xFFFFFFFF,
                              (destination + direction * width * count) & 0xFFFFFFFF], (case, state)
        return struct.pack("<9I", *state) + bytes(uc.mem_read(STACK, PAGE)) + observed


def main():
    output = ROOT / "build/rep-movs"; output.mkdir(parents=True, exist_ok=True)
    guards = {}
    for raw in ("f367a5", "f364a5", "f365a5"):
        lines = instruction_lines(bytes.fromhex(raw))
        assert "unsupported REP MOVS address/segment" in lines and "while (ecx)" not in lines
        guards[raw] = "REJECTED"
    scalar_sse = instruction_lines(bytes.fromhex("f20f10c1"))
    assert "_xmm[" in scalar_sse and "while (ecx)" not in scalar_sse and "void_lift_trap" not in scalar_sse
    guards["f20f10c1"] = "SSE scalar MOVSD preserved"
    bodies, dispatch = [], []
    for width in (1, 2, 4):
        for direction in (1, -1):
            name = f"rep_{width}_{'fwd' if direction > 0 else 'bwd'}"
            lines = instruction_lines((b"\xFC" if direction > 0 else b"\xFD") + RAW[width])
            bodies.append(f"__declspec(noinline) static void {name}(void) {{\n"
                "uint32_t _flag_k=g_flag_k,_flag_a=g_flag_a,_flag_b=g_flag_b,_cf=g_flag_cf;int _df=1;\n"
                "RECOMP_REGS_LOCALS\n" + lines + "\nRECOMP_FLAGS_OUT();returned_df=_df;esp+=4;RECOMP_REGS_OUT();\n}")
            dispatch.append(f"if(args[0]=={width}&&args[1]=={direction}u) {name}();")
    source = output / "probe.c"
    source.write_text(DRIVER.replace("/* BODIES */", "\n".join(bodies)).replace("/* DISPATCH */", "\n".join(dispatch)))
    scenarios = cases(); input_file = output / "cases.bin"
    input_file.write_bytes(b"".join(struct.pack("<6I", *(v & 0xFFFFFFFF for v in case)) for case in scenarios))
    compiler, env, sdk = compiler_environment(); oracle = Oracle(); record = 36 + PAGE * 2
    expected = [oracle.run(case) for case in scenarios]
    modes = []
    for local in (False, True):
        mode = "local" if local else "global"; exe = output / (mode + ".exe")
        command = [str(compiler), "/nologo", "/O2", "/W3", "/std:c11", "/D_CRT_SECURE_NO_WARNINGS",
                   "/I" + str(ROOT / "native"), str(source), f"/Fo{output}\\", f"/Fe{exe}"]
        if local: command.insert(1, "/DRECOMP_LOCAL_REGS")
        built = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
        (output / (mode + "-compile.log")).write_text(built.stdout + built.stderr)
        if built.returncode: raise RuntimeError(built.stdout + built.stderr)
        tested = subprocess.run([str(exe), str(input_file)], capture_output=True, timeout=30)
        assert tested.returncode == 0, tested.stderr
        assert len(tested.stdout) == len(scenarios) * record
        failures = []
        for i, case in enumerate(scenarios):
            actual = tested.stdout[i * record:(i + 1) * record]
            if actual != expected[i]:
                failures.append({"case": case, "registers_flags_match": actual[:36] == expected[i][:36],
                                 "stack_match": actual[36:36+PAGE] == expected[i][36:36+PAGE],
                                 "different_buffer_bytes": sum(a != b for a,b in zip(actual[36+PAGE:],expected[i][36+PAGE:]))})
        modes.append({"mode": mode, "failures": len(failures), "first_failure": failures[0] if failures else None})
        print(f"REP MOVS {mode}: {len(scenarios)} cases, {len(failures)} failures")
    (output / "result.json").write_text(json.dumps({"status": "FAIL" if any(m["failures"] for m in modes) else "PASS",
        "compiler": str(compiler), "sdk": sdk, "optimization": "/O2", "element_widths": [1,2,4],
        "directions": [1,-1], "flags_mask": hex(FLAGS_MASK), "cases_per_mode": len(scenarios),
        "address_segment_and_sse_guards": guards,
        "generated_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "project_lifter_sha256": hashlib.sha256((ROOT/'tools/lift_game.py').read_bytes()).hexdigest(),
        "original": "authored x86 bytes in Unicorn plus independent ordered element model",
        "modes": modes, "no_game_or_device_or_ui": True}, indent=2))
    assert all(mode["failures"] == 0 for mode in modes), "REP MOVS overlap semantics differ"


if __name__ == "__main__": main()
