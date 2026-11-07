"""Oracle the checked CRT FNSAVE/FRSTOR boundary against original x86 opcodes."""
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import unittest

from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EFLAGS, UC_X86_REG_FPCW,
                              UC_X86_REG_FPSW, UC_X86_REG_FPTAG, UC_X86_REG_FP0)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_android import CLANG
from build_x86_incremental import compiler_environment
from fpu_state import STATE_NOP, patch_fpu_state, state_instruction


def function(text, prefix):
    begin = text.index(prefix)
    return text[begin:text.index("\n}", begin) + 2]


class FpuStateTest(unittest.TestCase):
    def test_all_pinned_android_sites_and_legacy_bypass(self):
        import build_android as builder
        sites = []
        for source in builder.generated_sources():
            text = source.read_bytes()
            matches = list(STATE_NOP.finditer(text))
            if not matches:
                continue
            module = source.parent.name[:-len("-x86")]
            patched = patch_fpu_state(text, builder.module_image(module))
            self.assertNotRegex(patched, STATE_NOP)
            self.assertEqual(patched.count(b"void_fpu_state((uint32_t)"), len(matches))
            sites.extend(dict(source=source.relative_to(ROOT).as_posix(), address=m[2].decode(),
                              instruction=m[1].decode()) for m in matches)
        self.assertTrue(any(s["address"] == "16259D8D" for s in sites))
        self.assertTrue(any(s["address"] == "16259D99" for s in sites))
        folder = ROOT / "build/fpu-state-test/renderer-x86"
        folder.mkdir(parents=True, exist_ok=True)
        fixture = folder / "fixture.c"
        fixture.write_bytes(b"void sub_12345678(void) {\n"
                            b"/* fnsave: FPU state is not a memory image here */ /* 0x16259D8D: fnsave */\n}\n")
        release, out = builder.RELEASE, builder.OUT
        try:
            builder.OUT = folder.parent / "override"
            builder.RELEASE = {"name": "tension"}
            unchanged, flags = builder.override_source(fixture, False)
            self.assertEqual(unchanged, fixture)
            self.assertEqual(flags, [])
            builder.RELEASE = None
            patched, _ = builder.override_source(fixture, False)
            self.assertIn(b"void_fpu_state((uint32_t)(ecx + 0x8)", patched.read_bytes())
        finally:
            builder.RELEASE, builder.OUT = release, out
        (folder.parent / "sites.json").write_text(json.dumps(sites, indent=2) + "\n")
        print(f"PASS {len(sites)} pinned 2009 Android state sites; Tension bypass unchanged")

    def test_original_opcodes_and_lifter(self):
        import build_android as builder
        image = builder.module_image("renderer")
        decoder = Cs(CS_ARCH_X86, CS_MODE_32)
        decoder.detail = True
        for address, opcode, restore in ((0x16259D8D, "dd7108", 0), (0x16259D99, "dd6108", 1)):
            raw = image.u32(address).to_bytes(4, "little")[:3]
            self.assertEqual(raw, bytes.fromhex(opcode))
            text = state_instruction(next(decoder.disasm(raw, address))).decode()
            self.assertIn(f"void_fpu_state((uint32_t)(ecx + 0x8), 0x{address:08X}u, {restore}, 0)", text)
            old = (f"/* {'frstor' if restore else 'fnsave'}: FPU state is not a memory image here */ "
                   f"/* 0x{address:08X}: ignored */").encode()
            self.assertEqual(patch_fpu_state(old, image), text.encode())
        for opcode in ("66dd30", "66dd20"):
            text = state_instruction(next(decoder.disasm(bytes.fromhex(opcode), 0x10000))).decode()
            self.assertIn(", 1);", text)
        with self.assertRaises(ValueError):
            state_instruction(next(decoder.disasm(bytes.fromhex("67dd30"), 0x10000)))
        with self.assertRaises(ValueError):
            patch_fpu_state(b"/* frstor: FPU state is not a memory image here */ /* 0x16259D8D: wrong opcode */", image)

    def test_production_images_reset_restore_and_boundaries(self):
        header = (ROOT / "android/runtime/recomp_types.h").read_text(encoding="utf-8")
        helpers = function(header, "static inline double fp_ld80(") + "\n" + function(header, "static inline void fp_st80(")
        production = (ROOT / "android/host/fpu_state.c").read_text(encoding="utf-8").replace('#include "host.h"', "")
        program = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <setjmp.h>
#ifdef _WIN32
#include <io.h>
#include <fcntl.h>
#endif
static uint8_t memory[4096];
static double g_st[8];static int64_t g_st_i64[8];
static int g_fp_top,void_fpu_cmp;
static uint16_t g_fpu_cw;
static int readable=1,writable=1;
static jmp_buf trap;
#define GPTR(a) (memory+(a))
static int span(uint32_t address,uint32_t bytes){return address>=128 && (uint64_t)address+bytes<=sizeof memory;}
static int void_vm_readable(uint32_t address,uint32_t bytes){return readable && span(address,bytes);}
static int void_vm_writable(uint32_t address,uint32_t bytes){return writable && span(address,bytes);}
static void void_lift_trap(uint32_t address,const char *text){(void)address;(void)text;longjmp(trap,1);}
/* HELPERS */
/* PRODUCTION */
int main(int argc,char **argv){
    assert(argc==3);int depth=atoi(argv[1]),small=atoi(argv[2]);
    double values[]={1.25,-0.0,-3.5,INFINITY,-INFINITY,NAN,9007199254740992.0,0x1p-1074};
    for(int i=0;i<depth;++i)g_st[i]=values[i];
    if(depth>6)g_st_i64[6]=9007199254740993ll;
    g_fp_top=depth;g_fpu_cw=0x0B7F;void_fpu_cmp=0x14500;
    double before[8];int64_t shadows[8];memcpy(before,g_st,sizeof before);memcpy(shadows,g_st_i64,sizeof shadows);
    memset(memory,0xA5,sizeof memory);
    void_fpu_state(256,0x16259D8D,0,small);
    unsigned size=small?94:108;
    assert(g_fp_top==0 && g_fpu_cw==0x037F && void_fpu_cmp==0x10000);
    for(unsigned i=0;i<8;++i){unsigned physical=((0u-(unsigned)depth)+i)&7u;assert(!memcmp(&g_st[physical],&before[i],8));assert(g_st_i64[physical]==shadows[i]);}
    assert(memory[255]==0xA5 && memory[256+size]==0xA5);
#ifdef _WIN32
    _setmode(_fileno(stdout),_O_BINARY);
#endif
    fwrite(memory+256,1,size,stdout);
    void_fpu_state(256,0x16259D99,1,small);
    assert(g_fp_top==depth && g_fpu_cw==0x0B7F);
    assert((void_fpu_cmp&0x4700)==0x4500);
    for(int i=0;i<depth;++i){assert(isnan(before[i])?isnan(g_st[i]):!memcmp(&g_st[i],&before[i],8));if(shadows[i])assert(g_st_i64[i]==shadows[i]);}
    uint8_t snapshot[4096];memcpy(snapshot,memory,sizeof memory);int old_depth=g_fp_top;
    if(!setjmp(trap)){void_fpu_state(4096-size+1,0x1234,0,small);assert(0);}
    assert(g_fp_top==old_depth && !memcmp(snapshot,memory,sizeof memory));
    if(!setjmp(trap)){void_fpu_state(4096-size+1,0x1234,1,small);assert(0);}
    assert(g_fp_top==old_depth && !memcmp(snapshot,memory,sizeof memory));
    writable=0;
    if(!setjmp(trap)){void_fpu_state(256,0x1234,0,small);assert(0);}
    void_fpu_state(256,0x1234,1,small);
    writable=1;readable=0;
    if(!setjmp(trap)){void_fpu_state(256,0x1234,1,small);assert(0);}
    readable=1;
    assert(g_fp_top==old_depth && !memcmp(snapshot,memory,sizeof memory));
    if(!setjmp(trap)){void_fpu_state(UINT32_MAX-16,0x1234,1,small);assert(0);}
    if(!setjmp(trap)){void_fpu_state(256,0x1234,2,small);assert(0);}
    if(!setjmp(trap)){void_fpu_state(256,0x1234,0,2);assert(0);}
    double old_values[8];int64_t old_shadows[8];
    memcpy(old_values,g_st,sizeof old_values);memcpy(old_shadows,g_st_i64,sizeof old_shadows);
    int old_cmp=void_fpu_cmp;uint16_t old_cw=g_fpu_cw;
    for(int invalid=0;invalid<2;++invalid){
        uint16_t bad_status=invalid?0:0x0800,bad_tags=invalid?0xFFF3:0xFFFF;
        memcpy(memory+256+(small?2:4),&bad_status,2);memcpy(memory+256+(small?4:8),&bad_tags,2);
        if(!setjmp(trap)){void_fpu_state(256,0x1234,1,small);assert(0);}
        assert(g_fp_top==old_depth && void_fpu_cmp==old_cmp && g_fpu_cw==old_cw);
        assert(!memcmp(old_values,g_st,sizeof old_values) && !memcmp(old_shadows,g_st_i64,sizeof old_shadows));
    }
    memcpy(memory,snapshot,sizeof memory);
    void_fpu_state(4096-size,0x1234,0,small);
    void_fpu_state(4096-size,0x1234,1,small);
    const int conditions[]={-1,0,1,2,0x14500};
    const uint16_t flags[]={0x0100,0x4000,0,0x4500,0x4500};
    for(unsigned i=0;i<5;++i){
        void_fpu_cmp=conditions[i];
        void_fpu_state(256,0x1234,0,small);
        uint16_t status;memcpy(&status,memory+256+(small?2:4),2);
        assert(status==(uint16_t)(flags[i]|(((0u-(unsigned)depth)&7u)<<11)));
        void_fpu_state(256,0x1234,1,small);
    }
    const int64_t integers[]={INT64_MIN,INT64_MAX,9007199254740993ll,-9007199254740993ll,0,1,-1};
    for(unsigned i=0;i<sizeof integers/sizeof integers[0];++i){
        g_fp_top=1;g_st[0]=(double)integers[i];g_st_i64[0]=integers[i];
        void_fpu_state(256,0x1234,0,small);
        void_fpu_state(256,0x1234,1,small);
        assert(g_fp_top==1 && g_st_i64[0]==integers[i] && g_st[0]==(double)integers[i]);
    }
    return 0;
}
'''
        folder = ROOT / "build/fpu-state-test"
        folder.mkdir(parents=True, exist_ok=True)
        probe, binary = folder / "probe.c", folder / "probe.exe"
        probe.write_text(program.replace("/* HELPERS */", helpers).replace("/* PRODUCTION */", production), encoding="utf-8")
        _, env, _ = compiler_environment()
        env["LIB"] = env["LIB"].replace("\\x86", "\\x64")
        command = [str(CLANG), "--target=x86_64-pc-windows-msvc", "-fuse-ld=link", "-O2", "-std=c11", str(probe), "-o", str(binary)]
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for small in (0, 1):
            for depth in range(9):
                result = subprocess.run([str(binary), str(depth), str(small)], capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                image = result.stdout
                environment_bytes = 14 if small else 28
                status = 0x4500 | (((-depth) & 7) << 11)
                tags = 0xFFFF
                top = (status >> 11) & 7
                for index in range(depth):
                    value = (1.25, -0.0, -3.5, math.inf, -math.inf, math.nan, 2**53, 2**-1074)[index]
                    tag = 1 if value == 0 else 0 if math.isfinite(value) else 2
                    shift = 2 * ((top + index) & 7)
                    tags = (tags & ~(3 << shift)) | tag << shift
                uc = Uc(UC_ARCH_X86, UC_MODE_32)
                uc.mem_map(0x10000, 0x3000)
                opcode = bytes.fromhex("66dd30" if small else "dd30")
                uc.mem_write(0x10000, opcode)
                uc.reg_write(UC_X86_REG_EAX, 0x11000)
                uc.reg_write(UC_X86_REG_EFLAGS, 0xAD7)
                for index in range(8):
                    mantissa, exponent = struct.unpack_from("<QH", image, environment_bytes + index * 10)
                    uc.reg_write(UC_X86_REG_FP0 + ((top + index) & 7), (mantissa, exponent))
                uc.reg_write(UC_X86_REG_FPCW, 0x0B7F)
                uc.reg_write(UC_X86_REG_FPSW, status)
                uc.reg_write(UC_X86_REG_FPTAG, tags)
                uc.emu_start(0x10000, 0x10000 + len(opcode), count=1)
                oracle = bytes(uc.mem_read(0x11000, len(image)))
                self.assertEqual(image, oracle, (small, depth, image.hex(), oracle.hex()))
                self.assertEqual(uc.reg_read(UC_X86_REG_EFLAGS), 0xAD7)
                self.assertEqual(uc.reg_read(UC_X86_REG_FPCW), 0x037F)
                self.assertEqual(uc.reg_read(UC_X86_REG_FPSW), 0)
                self.assertEqual(uc.reg_read(UC_X86_REG_FPTAG), 0xFFFF)
                restore = bytes.fromhex("66dd20" if small else "dd20")
                uc.mem_write(0x10020, restore)
                uc.emu_start(0x10020, 0x10020 + len(restore), count=1)
                self.assertEqual(uc.reg_read(UC_X86_REG_FPCW), 0x0B7F)
                self.assertEqual(uc.reg_read(UC_X86_REG_FPSW), status)
                self.assertEqual(uc.reg_read(UC_X86_REG_FPTAG), tags)
                self.assertEqual(uc.reg_read(UC_X86_REG_EFLAGS), 0xAD7)
        print("PASS production FNSAVE/FRSTOR: 18 94/108-byte x86 oracle images, all stack depths/classes, exact int64, reset/restore and span guards")
        legacy = production.replace(function(production, "void void_fpu_state("),
            "void void_fpu_state(uint32_t a,uint32_t i,int r,int o){(void)a;(void)i;(void)r;(void)o;}")
        negative = folder / "probe-noop.c"
        negative.write_text(program.replace("/* HELPERS */", helpers).replace("/* PRODUCTION */", legacy), encoding="utf-8")
        old = folder / "probe-noop.exe"
        result = subprocess.run([*command[:-3], str(negative), "-o", str(old)], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = subprocess.run([str(old), "2", "0"], capture_output=True, timeout=20)
        self.assertNotEqual(result.returncode, 0, "the old no-op must fail this regression")
        (folder / "result.json").write_text(json.dumps(dict(status="PASS", oracle_images=18,
            sizes=[94,108], depths=list(range(9)), permissions_and_spans=True, unsupported_tags_top_rejected=True,
            legacy_noop_rejected=True, comparison_status_modes=5, exact_integer_boundaries=7,
            helper_sha256=hashlib.sha256((ROOT / "android/host/fpu_state.c").read_bytes()).hexdigest()), indent=2)+"\n")


if __name__ == "__main__":
    unittest.main()
