"""Differential-test scalar GameModule memmove; original code runs only in Unicorn.

The accelerated/SSE entrance is disabled and traps in both executions. Incoming
DF is clear, as required by the x86 CRT ABI. Only CF/PF/ZF/SF/DF are compared:
OF and AF can be undefined after the original SHR instructions.
"""
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "reference/pcrecomp"))
from tools.pe.pe_analyze import analyze_pe
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX,
    UC_X86_REG_EBX, UC_X86_REG_ESP, UC_X86_REG_EBP, UC_X86_REG_ESI,
    UC_X86_REG_EDI, UC_X86_REG_EIP, UC_X86_REG_EFLAGS)

ORIGINAL_SHA256 = "a0075c2316bdb658724aaec595339a8ad2459832620b0a9dac3c7359a4330562"
BASE, ENTRY, ACCELERATED, GLOBAL = 0x10000000, 0x10128710, 0x10136437, 0x102EC6C0
STACK, BUFFER, RETURN = 0x20000000, 0x20010000, 0x30000000
PAGE = 0x1000
FLAGS_MASK = 0x4C5
SIZES = tuple(range(65)) + (127, 128, 255, 256, 257)
REG_NAMES = ("EAX", "ECX", "EDX", "EBX", "ESP", "EBP", "ESI", "EDI")
REGS = (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EBX,
        UC_X86_REG_ESP, UC_X86_REG_EBP, UC_X86_REG_ESI, UC_X86_REG_EDI)
INITIAL = (0x76543210, 0x10203040, 0x50607080, 0x11223344,
           STACK + 0x800, 0x55667788, 0x99AABBCC, 0xDDEEFF00)
PATTERN = bytes(((i * 37 + (i >> 3) * 19 + 0x5B) ^ (i >> 8)) & 255
                for i in range(PAGE))
STATE_BYTES = 9 * 4 + PAGE * 2


@dataclass(frozen=True)
class Case:
    group: str
    dst: int
    src: int
    size: int

    def description(self):
        return {"group": self.group, "size": self.size,
                "dst": f"0x{self.dst:08X}", "src": f"0x{self.src:08X}",
                "dst_mod4": self.dst % 4, "src_mod4": self.src % 4,
                "distance": self.dst - self.src}


def cases():
    """All scalar alignments; close and far overlap distances for each residue."""
    result = []
    for size in SIZES:
        for src_align in range(4):
            pointer = BUFFER + 0x400 + src_align
            result.append(Case("identity", pointer, pointer, size))
            if size:
                result.append(Case("adjacent_dst_after", pointer + size, pointer, size))
                result.append(Case("adjacent_dst_before", pointer - size, pointer, size))
            for dst_align in range(4):
                src = BUFFER + 0x200 + src_align
                dst = BUFFER + 0x800 + dst_align
                result.append(Case("nonoverlap_dst_after", dst, src, size))
                result.append(Case("nonoverlap_dst_before", src, dst, size))
                for direction, residue, group in (
                    (1, (dst_align - src_align) % 4, "overlap_dst_after"),
                    (-1, (src_align - dst_align) % 4, "overlap_dst_before"),
                ):
                    nearest = residue or 4
                    if nearest >= size:
                        continue
                    farthest = nearest + ((size - 1 - nearest) // 4) * 4
                    for distance in sorted({nearest, farthest}):
                        result.append(Case(group, pointer + direction * distance,
                                           pointer, size))
    return result


def check_coverage(scenarios):
    assert len(SIZES) == 70
    assert len(scenarios) == len(set(scenarios))
    for case in scenarios:
        assert BUFFER <= min(case.src, case.dst)
        assert max(case.src, case.dst) + case.size <= BUFFER + PAGE
        if case.group.startswith("overlap"):
            assert 0 < abs(case.dst - case.src) < case.size
    for size in SIZES:
        selected = [case for case in scenarios if case.size == size]
        assert len([case for case in selected if case.group == "identity"]) == 4
        for group in ("nonoverlap_dst_before", "nonoverlap_dst_after"):
            covered = {(case.dst % 4, case.src % 4) for case in selected
                       if case.group == group}
            assert covered == {(dst, src) for dst in range(4) for src in range(4)}
        for group in ("overlap_dst_before", "overlap_dst_after"):
            covered = {(case.dst % 4, case.src % 4) for case in selected
                       if case.group == group}
            wanted = {(dst, src) for dst in range(4) for src in range(4)
                      if (((dst - src) if group.endswith("after") else
                            (src - dst)) % 4 or 4) < size}
            assert covered == wanted, (size, group, covered, wanted)


def mapped_original():
    config = json.loads((ROOT / "port.json").read_text())
    binary = Path(config["game_directory"]) / "bin/win32/GameModule.dll"
    raw = binary.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != ORIGINAL_SHA256:
        raise ValueError(f"Original GameModule.dll hash mismatch: {digest}")
    info = analyze_pe(str(binary))
    assert info.image_base == BASE
    span = (max(section.va_end for section in info.sections) + PAGE - 1) & ~(PAGE - 1)
    image = bytearray(span)
    for section in info.sections:
        image[section.virtual_address:section.virtual_address + section.raw_size] = \
            raw[section.raw_offset:section.raw_offset + section.raw_size]
    struct.pack_into("<I", image, GLOBAL - BASE, 0)
    return bytes(image), binary


class Oracle:
    def __init__(self, image):
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc.mem_map(BASE, len(image))
        self.uc.mem_write(BASE, image)
        self.uc.mem_map(STACK, PAGE)
        self.uc.mem_map(BUFFER, PAGE)
        self.uc.mem_map(RETURN, PAGE)
        self.uc.hook_add(UC_HOOK_CODE, self.accelerated, begin=ACCELERATED,
                         end=ACCELERATED)

    @staticmethod
    def accelerated(machine, address, size, context):
        raise AssertionError(f"Unverified accelerated original path reached: 0x{address:08X}")

    def run(self, case):
        uc = self.uc
        uc.mem_write(STACK, bytes([0xA5]) * PAGE)
        uc.mem_write(BUFFER, PATTERN)
        uc.mem_write(GLOBAL, struct.pack("<I", 0))
        uc.mem_write(INITIAL[4], struct.pack("<IIII", RETURN, case.dst, case.src, case.size))
        for register, value in zip(REGS, INITIAL):
            uc.reg_write(register, value)
        uc.reg_write(UC_X86_REG_EFLAGS, 2)
        uc.emu_start(ENTRY, RETURN, count=10000)
        assert uc.reg_read(UC_X86_REG_EIP) == RETURN, "Original did not return"
        registers = [uc.reg_read(register) for register in REGS]
        flags = uc.reg_read(UC_X86_REG_EFLAGS) & FLAGS_MASK
        stack = bytes(uc.mem_read(STACK, PAGE))
        buffer = bytes(uc.mem_read(BUFFER, PAGE))
        # Also check the independent high-level contract, including all guards.
        wanted = bytearray(PATTERN)
        offset_dst, offset_src = case.dst - BUFFER, case.src - BUFFER
        wanted[offset_dst:offset_dst + case.size] = PATTERN[offset_src:offset_src + case.size]
        assert buffer == wanted, ("Original violated memmove contract", case.description())
        assert registers[0] == case.dst, ("Original returned wrong pointer", case.description())
        assert not flags & 0x400, "Original returned with DF set"
        return struct.pack("<9I", *registers, flags) + stack + buffer


DRIVER = r'''
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <io.h>
#include <fcntl.h>
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
static int returned_df;
/* Observe the original local DF at RET; do not change its semantics. */
#undef RECOMP_FLAGS_OUT
#define RECOMP_FLAGS_OUT() (g_flag_k=_flag_k,g_flag_a=_flag_a,g_flag_b=_flag_b,g_flag_cf=_cf,returned_df=_df)
static void unverified(uint32_t address) {
    fprintf(stderr,"Unverified accelerated/indirect path reached: 0x%08X\n",address);
    exit(97);
}
void sub_101363B0(void) {unverified(0x101363B0u);}
void sub_10136437(void) {unverified(0x10136437u);}
recomp_func_t recomp_lookup_manual(uint32_t address) {unverified(address);return NULL;}
recomp_func_t recomp_lookup(uint32_t address) {unverified(address);return NULL;}
recomp_func_t recomp_lookup_import(uint32_t address) {unverified(address);return NULL;}
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
    if(argc!=3)return 90;
    FILE *image_file=fopen(argv[1],"rb");if(!image_file)return 91;
    fseek(image_file,0,SEEK_END);long span=ftell(image_file);rewind(image_file);
    void *image=VirtualAlloc(NULL,span,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
    if(!image)return 92;
    g_mem_base=(ptrdiff_t)((uint32_t)(uintptr_t)image-0x10000000u);
    void *stack=VirtualAlloc((void*)ADDR(0x20000000u),0x1000,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
    void *buffer=VirtualAlloc((void*)ADDR(0x20010000u),0x1000,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
    if(stack!=(void*)ADDR(0x20000000u)||buffer!=(void*)ADDR(0x20010000u))return 93;
    if(fread(image,1,span,image_file)!=(size_t)span)return 94;fclose(image_file);
    FILE *case_file=fopen(argv[2],"rb");if(!case_file)return 95;
    if(_setmode(_fileno(stdout),_O_BINARY)==-1)return 96;
    uint8_t pattern[0x1000];
    for(uint32_t i=0;i<0x1000;i++)pattern[i]=(uint8_t)((i*37+(i>>3)*19+0x5B)^(i>>8));
    uint32_t args[3],index=0;
    while(fread(args,sizeof(args),1,case_file)==1) {
        memset(stack,0xA5,0x1000);memcpy(buffer,pattern,0x1000);
        MEM32(0x102EC6C0u)=0;
        g_eax=0x76543210;g_ecx=0x10203040;g_edx=0x50607080;g_ebx=0x11223344;
        g_esp=0x20000800;g_ebp=0x55667788;g_esi=0x99AABBCC;g_edi=0xDDEEFF00;
        g_flag_k=FK_EFLAGS;g_flag_a=2;g_flag_b=0;g_flag_cf=0;returned_df=1;
        MEM32(g_esp)=0x30000000;MEM32(g_esp+4)=args[0];
        MEM32(g_esp+8)=args[1];MEM32(g_esp+12)=args[2];
        sub_10128710();
        uint32_t state[9]={g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi,
            recomp_eflags(g_flag_k,g_flag_a,g_flag_b,g_flag_cf,returned_df)&0x4C5};
        if(fwrite(state,sizeof(state),1,stdout)!=1 || fwrite(stack,0x1000,1,stdout)!=1 ||
           fwrite(buffer,0x1000,1,stdout)!=1)return 98;
        index++;
    }
    if(ferror(case_file))return 99;
    fclose(case_file);fprintf(stderr,"Completed %u scalar cases\n",index);
    return fflush(stdout)==0?0:100;
}
'''


def generated_body():
    report = json.loads((ROOT / "generated/gamemodule-x86/report.json").read_text())
    if report["status"] != "GENERATED":
        raise ValueError("GameModule generation must finish before testing")
    symbol = "void sub_10128710(void)"
    for path in sorted((ROOT / "generated/gamemodule-x86").glob("gamemodule_*.c")):
        source = path.read_text()
        if symbol not in source:
            continue
        start = source.index(symbol)
        end = source.find("\nvoid ", start + 1)
        body = source[start:end if end >= 0 else len(source)]
        assert "void_lift_trap" not in body, "Generated memmove still contains lift traps"
        calls = set(re.findall(r"RECOMP_CALL\((sub_[0-9A-Fa-f]+)\)", body))
        assert calls <= {"sub_101363B0", "sub_10136437"}, calls
        assert body.count("L_10136437:\n") == 1
        observed_body = body.replace("L_10136437:\n",
                                     "L_10136437:\n    unverified(0x10136437u);\n")
        return body, observed_body, path, report
    raise ValueError("Generated scalar memmove body not found")


def compiler_environment():
    vswhere = str(Path(os.environ["ProgramFiles(x86)"]) / "Microsoft Visual Studio/Installer/vswhere.exe")
    vs = Path(subprocess.check_output([vswhere, "-latest", "-products", "*",
                                      "-property", "installationPath"], text=True).strip())
    msvc = sorted((vs / "VC/Tools/MSVC").iterdir(), reverse=True)[0]
    sdk = Path(os.environ["ProgramFiles(x86)"]) / "Windows Kits/10"
    version = sorted((sdk / "Lib").iterdir(), reverse=True)[0].name
    compiler = msvc / "bin/Hostx64/x86/cl.exe"
    env = os.environ.copy()
    env["PATH"] = str(compiler.parent) + os.pathsep + env["PATH"]
    env["INCLUDE"] = ";".join(str(path) for path in (msvc / "include",
        sdk / f"Include/{version}/ucrt", sdk / f"Include/{version}/shared",
        sdk / f"Include/{version}/um"))
    env["LIB"] = ";".join(str(path) for path in (msvc / "lib/x86",
        sdk / f"Lib/{version}/ucrt/x86", sdk / f"Lib/{version}/um/x86"))
    return compiler, env, version


def read_exact(stream, size):
    output = bytearray()
    while len(output) < size:
        chunk = stream.read(size - len(output))
        if not chunk:
            break
        output.extend(chunk)
    return bytes(output)


def first_memory_difference(expected, actual, address):
    for offset, (wanted, observed) in enumerate(zip(expected, actual)):
        if wanted != observed:
            lo, hi = max(0, offset - 8), min(len(expected), offset + 9)
            return {"address": f"0x{address + offset:08X}", "offset": offset,
                    "expected_byte": wanted, "actual_byte": observed,
                    "context_start": f"0x{address + lo:08X}",
                    "expected_context": expected[lo:hi].hex(),
                    "actual_context": actual[lo:hi].hex()}
    return None


def difference(expected, actual):
    wanted = struct.unpack("<9I", expected[:36])
    observed = struct.unpack("<9I", actual[:36])
    changed = {name: {"expected": f"0x{a:08X}", "actual": f"0x{b:08X}"}
               for name, a, b in zip((*REG_NAMES, "flags_0x4C5"), wanted, observed)
               if a != b}
    return {"registers_or_flags": changed,
            "stack": first_memory_difference(expected[36:36 + PAGE],
                                              actual[36:36 + PAGE], STACK),
            "buffer": first_memory_difference(expected[36 + PAGE:],
                                               actual[36 + PAGE:], BUFFER)}


def main():
    scenarios = cases()
    check_coverage(scenarios)
    if sys.argv[1:] == ["--coverage-only"]:
        print(json.dumps({"cases": len(scenarios), "groups": dict(Counter(
            case.group for case in scenarios)), "sizes": SIZES}, indent=2))
        return
    if sys.argv[1:]:
        raise ValueError("Only optional --coverage-only is accepted")
    started = time.monotonic()
    image, original_path = mapped_original()
    body, observed_body, source, generated_report = generated_body()
    compiler, env, sdk_version = compiler_environment()
    runtime = ROOT / "reference/pcrecomp/runtime/recomp32/recomp_types.h"
    overlay = ROOT / "native/recomp_types.h"
    evidence = {"original_sha256": ORIGINAL_SHA256,
                "generated_function_sha256": hashlib.sha256(body.encode()).hexdigest(),
                "runtime_header_sha256": hashlib.sha256(runtime.read_bytes()).hexdigest(),
                "project_overlay_sha256": hashlib.sha256(overlay.read_bytes()).hexdigest(),
                "generated_source": str(source.relative_to(ROOT)), "compiler": str(compiler),
                "sdk": sdk_version, "generated_instructions":
                    generated_report["emitted_instructions_with_overlap"],
                "cases": len(scenarios), "flags_mask": "0x4C5"}
    oracle = Oracle(image)
    failures = ROOT / "build/tests"
    failures.mkdir(parents=True, exist_ok=True)
    passed = Counter()
    with tempfile.TemporaryDirectory(prefix="void-memmove-") as directory:
        tmp = Path(directory)
        driver, exe = tmp / "check.c", tmp / "check.exe"
        mapped, inputs = tmp / "image.bin", tmp / "cases.bin"
        stderr_path = tmp / "driver.log"
        driver.write_text(DRIVER.replace("/* BODY */", observed_body))
        mapped.write_bytes(image)
        inputs.write_bytes(b"".join(struct.pack("<III", case.dst, case.src, case.size)
                                    for case in scenarios))
        command = [str(compiler), "/nologo", "/O2", "/std:c11",
                   "/D_CRT_SECURE_NO_WARNINGS", "/I" + str(overlay.parent), "/I" + str(runtime.parent),
                   str(driver), "/Fo" + str(tmp / "check.obj"), "/Fe" + str(exe),
                   "/link", "/BASE:0x70000000", "/DYNAMICBASE:NO", "/STACK:262144"]
        built = subprocess.run(command, env=env, cwd=tmp, text=True, capture_output=True)
        if built.returncode:
            raise RuntimeError(built.stdout + built.stderr)
        with stderr_path.open("wb") as stderr:
            process = subprocess.Popen([str(exe), str(mapped), str(inputs)],
                                       stdout=subprocess.PIPE, stderr=stderr)
            try:
                for index, case in enumerate(scenarios):
                    expected = oracle.run(case)
                    actual = read_exact(process.stdout, STATE_BYTES)
                    if len(actual) != STATE_BYTES:
                        code = process.wait(timeout=10)
                        raise RuntimeError(f"Native driver stopped at case {index}, code {code}: "
                                           + stderr_path.read_text())
                    if actual != expected:
                        failure = {**evidence, "case_index": index,
                                   "case": case.description(),
                                   "difference": difference(expected, actual)}
                        (failures / "memmove-failure.json").write_text(
                            json.dumps(failure, indent=2) + "\n")
                        raise AssertionError(json.dumps(failure, indent=2))
                    passed[case.group] += 1
                assert process.stdout.read(1) == b"", "Driver emitted unexpected extra state"
                assert process.wait(timeout=10) == 0, stderr_path.read_text()
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
                process.stdout.close()
        evidence["driver_log"] = stderr_path.read_text().strip()
    evidence["elapsed_seconds"] = round(time.monotonic() - started, 2)
    evidence["status"] = "PASS"
    evidence["groups"] = dict(passed)
    (failures / "memmove-results.json").write_text(json.dumps(evidence, indent=2) + "\n")
    report = ["# Scalar GameModule memmove differential", "",
        f"PASS: {len(scenarios)} cases. Original x86 bytes in Unicorn and the current generated global C compiled with MSVC x86 `/O2` match all eight GPRs, CF/PF/ZF/SF/DF (`0x4C5`), all 4096 stack bytes and all 4096 buffer bytes after each call.",
        "", f"Function entry: `0x{ENTRY:08X}`. Original: `{original_path}`.",
        f"Original PE SHA-256: `{ORIGINAL_SHA256}`.",
        f"Generated function SHA-256: `{evidence['generated_function_sha256']}`.",
        f"Runtime header SHA-256: `{evidence['runtime_header_sha256']}`.",
        f"Project TLS flag overlay SHA-256: `{evidence['project_overlay_sha256']}`.",
        f"Source: `{evidence['generated_source']}`; generated instruction count: {evidence['generated_instructions']}.",
        f"Compiler: `{compiler}`; Windows SDK: `{sdk_version}`.",
        "", "Sizes: every integer 0 through 64, then 127, 128, 255, 256 and 257. All 4×4 source/destination alignments modulo four are covered for both non-overlap directions. Both overlap directions cover each feasible alignment pair at its nearest positive distance (1..4) and farthest distance below the copy size with the same residue, including single-byte overlaps. Identity and exact adjacency in both directions are covered at all four source alignments. Zero-size cases retain distinct source/destination addresses.",
        "", "| Case group | Passed |", "|---|---:|"]
    report += [f"| {group} | {count} |" for group, count in passed.items()]
    report += ["", "Both implementations start with DF clear, as required by the x86 CRT ABI; backward copies must return with DF clear. AF and OF are deliberately excluded because original SHR by two makes them undefined. Every original result also satisfies an independent Python memmove contract, including the entire buffer guards and returned destination pointer.",
        "", "The original global at `0x102EC6C0` is zero for every case. The accelerated entrance `0x10136437` traps in Unicorn and in a test-only generated label gate; external accelerated helper stubs also fail if called. This test therefore makes no SSE claim. The test-only `RECOMP_FLAGS_OUT` override observes the function-local DF without changing its value. The extracted scalar body and existing runtime are otherwise unchanged, using the global register model and existing `g_mem_base` address translation.",
        "", "The original DLL is read and hash-checked; it is never loaded or executed natively. Only a temporary standalone MSVC test EXE runs on Windows. The game, original configuration, registry and save files are not touched. This verifies scalar memmove semantics, not GameModule startup, the SSE path or full gameplay.",
        "", f"Command: `python tests/test_memmove.py`. Elapsed: {evidence['elapsed_seconds']} seconds.", ""]
    (ROOT / "research/memmove-differential.md").write_text("\n".join(report), encoding="utf-8")
    print(f"PASS: {len(scenarios)} scalar memmove cases, all 8 GPRs / flags 0x4C5 / full stack+buffer; SSE unverified")


if __name__ == "__main__":
    main()
