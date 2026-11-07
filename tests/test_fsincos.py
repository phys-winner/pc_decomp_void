"""Check both releases' project lift against the original x87 instruction."""
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import sys
import unittest

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import UC_X86_REG_EFLAGS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from lift_game import CheckedLifter
import build_android as builder
from test_memmove import compiler_environment

OLD = b"_st[0] = cos(_a); fp_push(sin(_a));"
NEW = b"_st[0] = sin(_a); fp_push(cos(_a));"


class FsincosTest(unittest.TestCase):
    def test_stack_order_against_original_x86(self):
        pe = pefile.PE(str(ROOT / "generated/input/PhysXCore.dll"), fast_load=True)
        original = pe.get_data(0x180B7C81 - pe.OPTIONAL_HEADER.ImageBase, 2)
        self.assertEqual(original, bytes.fromhex("d9fb"))
        decoder = Cs(CS_ARCH_X86, CS_MODE_32)
        decoder.detail = True
        lifted = "\n".join(CheckedLifter().lift_instruction(next(decoder.disasm(original, 0x180B7C81))))
        legacy = lifted.replace(NEW.decode(), OLD.decode())
        self.assertNotEqual(lifted, legacy)
        header = (ROOT / "android/runtime/recomp_types.h").read_text()
        push = "\n".join(re.search(r"static inline void " + name + r"\(.*?\n\}", header, re.S)[0]
                         for name in ("fp_push_local_impl", "fp_push_impl"))
        angles = (0.0, 1e-6, -1e-6, .01, -.01, math.pi / 180, -math.pi / 180,
                  math.pi / 4, -math.pi / 4, math.pi / 2, math.pi, 2 * math.pi, 10.0, -10.0)
        out = ROOT / "build/fsincos-test"
        out.mkdir(parents=True, exist_ok=True)
        source = out / "check.c"
        source.write_text("#include <assert.h>\n#include <math.h>\n#include <stdio.h>\n#include <stdint.h>\n"
            "int64_t g_st_i64[8];\n" + push + "\n#define fp_push(v) fp_push_impl(_st,&_fp_top,(v))\n"
            "int main(void) {\ndouble angles[]={" + ",".join(repr(a) for a in angles) + "};\n"
            "for(unsigned i=0;i<sizeof angles/sizeof *angles;++i) {\n"
            "double angle=angles[i], lower=9.125, bottom=-6.75, native[4];\n"
            "unsigned char host_state[108]; unsigned before_flags,after_flags;\n"
            "__asm {\nlea eax,host_state\nfnsave [eax]\nfld bottom\nfld lower\nfld angle\n"
            "pushfd\npop eax\nmov before_flags,eax\n__emit 0xd9\n__emit 0xfb\n"
            "pushfd\npop eax\nmov after_flags,eax\n"
            "fstp qword ptr native\nfstp qword ptr native[8]\n"
            "fstp qword ptr native[16]\nfstp qword ptr native[24]\n"
            "lea eax,host_state\nfrstor [eax]\n}\n"
            "assert(before_flags==after_flags && native[2]==lower && native[3]==bottom);\n"
            "for(int old=0;old<2;++old) {double _st[8]={angle,lower,bottom};"
            "int _fp_top=2,_fpu_cmp=0;g_st_i64[1]=123;g_st_i64[2]=-456;\n"
            "if(old) {" + legacy + "} else {" + lifted + "}\n"
            "assert(_fp_top==3 && _fpu_cmp==1 && _st[2]==lower && _st[3]==bottom);\n"
            "assert(g_st_i64[2]==123 && g_st_i64[3]==-456);\n"
            'printf("%.17g %.17g %.17g %.17g\\n",_st[0],_st[1],native[0],native[1]);\n'
            "}} return 0;}\n")
        compiler, env, _ = compiler_environment()
        compiled = subprocess.run([str(compiler), "/nologo", "/O2", "/std:c11", "/W4", "/WX",
            str(source), "/Fo" + str(out) + "\\", "/Fe" + str(out / "check.exe"), "/link", "/MACHINE:X86"],
            env=env, capture_output=True, text=True, check=True)
        actual = subprocess.run([str(out / "check.exe")], capture_output=True, text=True, check=True)
        rows = [tuple(map(float, line.split())) for line in actual.stdout.splitlines()]
        self.assertEqual(len(rows), 2 * len(angles))
        failures = 0
        for index, angle in enumerate(angles):
            uc = Uc(UC_ARCH_X86, UC_MODE_32)
            uc.mem_map(0x10000, 4096)
            code = bytes.fromhex("dbe3dd05") + struct.pack("<I", 0x10308)
            code += bytes.fromhex("dd05") + struct.pack("<I", 0x10300) + original
            for address in (0x10400, 0x10408, 0x10410):
                code += bytes.fromhex("dd1d") + struct.pack("<I", address)
            uc.mem_write(0x10000, code)
            uc.mem_write(0x10300, struct.pack("<dd", angle, 9.125))
            uc.reg_write(UC_X86_REG_EFLAGS, 0x202)
            uc.emu_start(0x10000, 0x10000 + len(code), count=20)
            cosine, sine, sentinel = struct.unpack("<ddd", uc.mem_read(0x10400, 24))
            self.assertEqual(sentinel, 9.125)
            self.assertEqual(uc.reg_read(UC_X86_REG_EFLAGS), 0x202)
            fixed, legacy = rows[index * 2:index * 2 + 2]
            for actual_value, expected in zip(fixed, (cosine, sine, cosine, sine), strict=True):
                self.assertAlmostEqual(actual_value, expected, places=12, msg=f"angle {angle}")
            failures += abs(legacy[0] - cosine) > 1e-12 or abs(legacy[1] - sine) > 1e-12
        self.assertGreaterEqual(failures, 12)
        self.assertEqual(compiled.returncode, 0)

    def test_generated_sites_match_pinned_images(self):
        decoder = Cs(CS_ARCH_X86, CS_MODE_32)
        decoder.detail = True
        counts = {}
        for relative, expected in (("physxcore-x86", 113), ("physxcooking-x86", 2),
                                   ("d3dxcompiler-x86", 15), ("tension/physxcore-x86", 108),
                                   ("tension/physxcooking-x86", 2)):
            directory = ROOT / "generated" / relative
            report = json.loads((directory / "report.json").read_text())
            image = ROOT / report["input_image"]
            self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(), report["rebased_sha256"])
            pe = pefile.PE(str(image), fast_load=True)
            count = 0
            for name in report["sources"]:
                for line in (directory / name).read_bytes().splitlines():
                    if b": fsincos " not in line:
                        continue
                    match = re.search(rb"/\* 0x([0-9A-F]+): fsincos\s+\*/", line)
                    self.assertIsNotNone(match)
                    address = int(match[1], 16)
                    raw = pe.get_data(address - pe.OPTIONAL_HEADER.ImageBase, 2)
                    self.assertEqual(raw, bytes.fromhex("d9fb"))
                    emitted = CheckedLifter().lift_instruction(next(decoder.disasm(raw, address)))[0]
                    self.assertEqual(line.strip().decode(), emitted)
                    count += 1
            self.assertEqual(count, expected, relative)
            counts[relative] = count
        self.assertEqual(sum(counts.values()), 240)

    def test_tension_shared_compiler_keeps_correct_order(self):
        out = ROOT / "build/fsincos-test/release"
        previous_out, previous_release = builder.OUT, builder.RELEASE
        try:
            builder.RELEASE = json.loads((ROOT / "generated/tension/release.json").read_text())
            count = 0
            for current in sorted((ROOT / "generated/d3dxcompiler-x86").glob("*.c")):
                raw = current.read_bytes()
                if NEW not in raw:
                    continue
                count += 1
                for local_xmm in (False, True):
                    builder.OUT = out
                    new_source, _ = builder.override_source(current, local_xmm)
                    compiled = new_source.read_bytes()
                    self.assertNotIn(OLD, compiled, current.name)
                    self.assertEqual(compiled.count(NEW), raw.count(NEW), current.name)
            self.assertEqual(count, 2)
        finally:
            builder.OUT, builder.RELEASE = previous_out, previous_release


if __name__ == "__main__":
    unittest.main()
