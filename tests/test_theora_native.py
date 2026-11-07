"""Production Theora reconstruction versus each release's original x86 C decoder."""
import hashlib
import json
from pathlib import Path
import random
import struct
import subprocess
import sys
import zipfile

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX,
    UC_X86_REG_EBX, UC_X86_REG_ESP, UC_X86_REG_EBP, UC_X86_REG_ESI,
    UC_X86_REG_EDI, UC_X86_REG_EIP, UC_X86_REG_EFLAGS)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_x86_incremental import compiler_environment
from build_android import CLANG, HOST_FLAGS, TOOLCHAIN

BASE, SPAN, STATE, FRAGS = 0x20000000, 0x20000, 0x20001000, 0x20002000
COEFF, QUANT, BOUND, FRAMES = 0x20003000, 0x20003100, 0x20004000, 0x20005000
RETURN, ESP, FRAME_BYTES = 0x30000000, BASE + 0x800, 0x9000
RELEASES = {
    "void": ("the-void-english", "9500d18964bbbfe02c022c8d4594807f0082c0fd750af9c29ca226752ea63957",
             0x10020540, 0x10020390, 1, 127),
    "tension": ("the-void-polish", "5419c0ceb31b0ec236353452403188d5c5463257092bbea61ba5341ce22f5ebd",
                0x100068D0, 0x100070C0, 0, 256),
}
REGS = (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EBX,
        UC_X86_REG_ESP, UC_X86_REG_EBP, UC_X86_REG_ESI, UC_X86_REG_EDI)
INITIAL = (0x12345678, 0x23456789, 0x3456789A, 0x456789AB,
           ESP, 0x56789ABC, 0x6789ABCD, 0x789ABCDE)

DRIVER = r'''
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <io.h>
#include <fcntl.h>
#include <stdarg.h>
uint32_t g_esp;
#define GPTR(a) ((void *)(uintptr_t)(uint32_t)(a))
#define MEM8(a) (*(uint8_t *)GPTR(a))
#define MEM16(a) (*(uint16_t *)GPTR(a))
#define MEM32(a) (*(uint32_t *)GPTR(a))
static void void_log(const char *fmt, ...) { (void)fmt; }
static void void_hud_video_frame(void) {}
/* RELEASE */
/* NATIVE */
void THEORA_FRAG_RECON_LIFTED(void) { abort(); }
void THEORA_LOOP_FILTER_LIFTED(void) { abort(); }
int main(int argc, char **argv) {
    if (argc != 2) return 90;
    void *data = VirtualAlloc((void *)0x20000000u,0x20000,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
    if (data != (void *)0x20000000u) return 91;
    FILE *in = fopen(argv[1], "rb"); if (!in) return 92;
    if (_setmode(_fileno(stdout), _O_BINARY) == -1) return 93;
    uint32_t kind;
    while (fread(&kind, sizeof kind, 1, in) == 1) {
        if (fread(data, 0x20000, 1, in) != 1) return 94;
        g_esp = 0x20000800;
        if (kind) THEORA_LOOP_FILTER(); else THEORA_FRAG_RECON();
        if (fwrite(&g_esp, sizeof g_esp, 1, stdout) != 1 ||
            fwrite((unsigned char *)data + 0x5000, 0x9000, 1, stdout) != 1) return 95;
    }
    return ferror(in) || fflush(stdout) ? 96 : 0;
}
'''


def fixture(fmt, sign, seed, mode=0, pli=0, mv=(0, 0), dct=1, filter_case=None, center=127):
    rng = random.Random(seed)
    data = bytearray(SPAN)

    def put(address, form, *values):
        struct.pack_into("<" + form, data, address - BASE, *values)

    put(STATE + 4, "II", 32, 32)
    put(STATE + 48, "I", fmt)
    put(STATE + 64, "III", *((0x1000C0F0, 0x1000C260, 0x1000C400) if center == 256 else
                             (0x1001A250, 0x1001A090, 0x10019EC0)))
    put(STATE + 84, "I", 0x10001340 if center == 256 else 0x10020310)
    put(STATE + 196, "I", FRAGS)
    put(STATE + 576, "III", 0, 1, 2)
    put(STATE + 732, "I", FRAMES)
    data[FRAMES - BASE:FRAMES - BASE + FRAME_BYTES] = rng.randbytes(FRAME_BYTES)
    layouts, frag_start, plane_start = [], 0, 0
    for plane in range(3):
        xs, ys = (int(not (fmt & 1)), int(not (fmt & 2))) if plane else (0, 0)
        width, height = 32 >> xs, 32 >> ys
        pw, ph = 64 >> xs, 64 >> ys
        stride = sign * pw
        origin = (16 >> xs) + ((16 >> ys) if sign > 0 else ph - 1 - (16 >> ys)) * pw
        layouts.append((width // 8, height // 8, frag_start, plane_start, stride, origin))
        put(STATE + 96 + 32 * plane, "IIII", width // 8, height // 8, frag_start, width * height // 64)
        frag_start += width * height // 64
        plane_start += pw * ph
    frame_size = plane_start
    for plane, (nh, nv, first, offset, stride, origin) in enumerate(layouts):
        for frame in range(3):
            put(STATE + 588 + 48 * frame + 16 * plane, "III", 32, 32, stride & 0xFFFFFFFF)
        for y in range(nv):
            for x in range(nh):
                frag = FRAGS + 28 * (first + y * nh + x)
                coded = (seed >> ((x + y * nh) % 16)) & 1 if filter_case else 1
                put(frag, "BBh", coded, mode, rng.randrange(-32, 33))
                put(frag + 24, "bb", *mv)
                for frame in range(3):
                    put(frag + 4 + 4 * frame, "I", FRAMES + frame * frame_size + offset + origin + 8 * (y * stride + x))
    nh, nv, first, *_ = layouts[pli]
    frag = FRAGS + 28 * (first + (nv // 2) * nh + nh // 2)
    put(COEFF, "64h", *(rng.randrange(-15, 16) for _ in range(64)))
    put(QUANT, "64H", *(rng.randrange(1, 41) for _ in range(64)))
    for i in range(512):
        f = i - center
        limit = 13
        value = f if abs(f) <= limit else (2 * limit - abs(f)) * (1 if f > 0 else -1) if abs(f) < 2 * limit else 0
        put(BOUND + 4 * i, "i", value)
    if filter_case:
        refi, row0, row1 = filter_case
        args = (STATE, BOUND, refi, pli, row0, min(nv, row1))
    else:
        last, ncoefs = {1: (1, 1), 2: (2, 2), 10: (9, 10), 64: (63, 64)}[dct]
        args = (STATE, frag, pli, COEFF, last, ncoefs, 23, QUANT)
    put(ESP, "I" * (len(args) + 1), RETURN, *args)
    return data


class Oracle:
    def __init__(self, image):
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc.mem_map(0x10000000, 0x50000)
        self.uc.mem_write(0x10000000, image)
        self.uc.mem_map(BASE, SPAN)
        self.uc.mem_map(RETURN, 0x1000)

    def run(self, entry, data):
        uc = self.uc
        uc.mem_write(BASE, bytes(data))
        for reg, value in zip(REGS, INITIAL):
            uc.reg_write(reg, value)
        uc.reg_write(UC_X86_REG_EFLAGS, 2)
        uc.emu_start(entry, RETURN, count=200000)
        assert uc.reg_read(UC_X86_REG_EIP) == RETURN
        assert uc.reg_read(UC_X86_REG_ESP) == ESP + 4
        assert tuple(uc.reg_read(REGS[i]) for i in (3, 5, 6, 7)) == tuple(INITIAL[i] for i in (3, 5, 6, 7))
        return struct.pack("<I", ESP + 4) + bytes(uc.mem_read(FRAMES, FRAME_BYTES))


def main():
    out = ROOT / "build/tension-20261031/theora-agent"
    out.mkdir(parents=True, exist_ok=True)
    production_path = ROOT / "android/host/theora_native.c"
    source_hash = hashlib.sha256(production_path.read_bytes()).hexdigest()
    production = production_path.read_text()
    native = production.replace('#include "host.h"', '').replace('#include "hud.h"', '')
    compiler, env, _ = compiler_environment()
    env = dict(env, VOID_THEORA="native")
    reports = []
    for release, (folder, digest, recon, filt, intra, center) in RELEASES.items():
        path = ROOT / "original" / folder / "bin/win32/Video.dll"
        if path.is_file():
            raw = path.read_bytes()
        else:
            archive = "the-void-2009-english.zip" if release == "void" else "the-void-2008-polish.zip"
            with zipfile.ZipFile(ROOT / "pub" / archive) as original:
                raw = original.read("bin/win32/Video.dll")
        assert hashlib.sha256(raw).hexdigest() == digest
        image = pefile.PE(data=raw).get_memory_mapped_image()
        oracle = Oracle(image)
        obj = out / (release + "-android.o")
        release_flags = [] if release == "void" else ["-DVOID_RELEASE", "-Igenerated/tension"]
        subprocess.run([str(CLANG), *HOST_FLAGS, *release_flags, "-c", str(production_path), "-o", str(obj)],
                       cwd=ROOT, check=True, capture_output=True)
        symbols = subprocess.run([str(TOOLCHAIN / "bin/llvm-nm.exe"), "--defined-only", "--format=posix", str(obj)],
                                 check=True, capture_output=True, text=True).stdout
        wrappers = ("sub_15018800", "sub_15018ED0") if release == "void" else ("sub_150068D0", "sub_150070C0")
        assert set(wrappers) <= {row.split()[0] for row in symbols.splitlines()}, symbols
        definitions = "" if release == "void" else "#define VOID_RELEASE 1"
        source = DRIVER.replace("/* RELEASE */", definitions).replace("/* NATIVE */", native)
        source_path, exe = out / (release + ".c"), out / (release + ".exe")
        source_path.write_text(source)
        subprocess.run([str(compiler), "/nologo", "/O2", "/W3", "/std:c11", "/Iandroid/host", "/Igenerated/tension",
                        str(source_path), "/Fe" + str(exe), "/Fo" + str(out / (release + ".obj"))],
                       cwd=ROOT, env=env, check=True, capture_output=True)
        scenarios = []
        for fmt in range(4):
            for sign in (-1, 1):
                for mode in range(8):
                    for dct in (1, 2, 10, 64):
                        seed = len(scenarios) + 1
                        pli = seed % 3
                        mv = ((seed % 7) * 5 - 15, ((seed // 7) % 7) * 5 - 15)
                        scenarios.append((0, dict(fmt=fmt, sign=sign, seed=seed, mode=mode, pli=pli, mv=mv, dct=dct)))
                for pli in range(3):
                    for dx in (-7, -2, -1, 0, 1, 2, 7):
                        for dy in (-7, -2, -1, 0, 1, 2, 7):
                            scenarios.append((0, dict(fmt=fmt, sign=sign, seed=len(scenarios) + 1,
                                mode=1 - intra, pli=pli, mv=(dx, dy), dct=1)))
                    for seed in (0, 0xFFFF, 0xAAAA, 0x5555, 0x1234):
                        for refi in range(3):
                            for rows in ((0, 4), (1, 4), (0, 1)):
                                scenarios.append((1, dict(fmt=fmt, sign=sign, seed=seed, pli=pli,
                                                         filter_case=(refi, *rows))))
        expected = bytearray()
        input_path = out / (release + ".input")
        with input_path.open("wb") as stream:
            for kind, options in scenarios:
                data = fixture(**options, center=center)
                stream.write(struct.pack("<I", kind)); stream.write(data)
                expected += oracle.run(filt if kind else recon, data)
        actual = subprocess.run([str(exe), str(input_path)], check=True, capture_output=True, env=env).stdout
        if actual != expected:
            first = next((i for i, pair in enumerate(zip(actual, expected)) if pair[0] != pair[1]), min(len(actual), len(expected)))
            case, offset = divmod(first, FRAME_BYTES + 4)
            raise AssertionError((release, scenarios[case], "output offset", offset, "actual/expected", actual[first:first+16].hex(), expected[first:first+16].hex()))
        reports.append(dict(release=release, cases=len(scenarios), original_sha256=digest,
                            native_sha256=source_hash,
                            oracle_reconstruction=hex(recon), oracle_filter=hex(filt), android_defined_wrappers=wrappers))
        input_path.unlink()
        print(f"{release}: {len(scenarios)} Theora pixel/stack cases PASS")
    (out / "result.json").write_text(json.dumps(dict(status="PASS", results=reports), indent=2))


if __name__ == "__main__":
    main()
