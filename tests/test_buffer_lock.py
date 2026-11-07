"""Run the shipping buffer Lock against overflow, range and dirty-state cases."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_x86_incremental import compiler_environment


def main():
    resource = (ROOT / "android/host/d3d9_resource.c").read_text()
    internal = (ROOT / "android/host/d3d9_internal.h").read_text()
    lock = re.search(r"^COM_METHOD\(buf, Lock, 5\)\n\{.*?^\}", resource, re.M | re.S).group()
    structure = re.search(r"typedef struct d3d_buffer \{.*?\} d3d_buffer;", internal, re.S).group()
    constants = "\n".join(re.findall(r"^#define (?:D3D_OK|D3DERR_INVALIDCALL|D3DLOCK_\w+) .*", internal, re.M))
    probe = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef struct { uint32_t guest; } void_com_object;
typedef struct d3d_device d3d_device;
typedef unsigned GLuint;
''' + constants + "\n" + structure + r'''
static d3d_buffer buffer;
static uint32_t args[5], output;
#define BUF (&buffer)
#define ARG(n) args[n]
#define MEM32(a) (*((void)(a), &output))
#define COM_METHOD(prefix, name, count) static uint32_t prefix##_##name(void)
#include "production.h"
#define CHECK(x) do { if (!(x)) { printf("failed line %d: %s\n", __LINE__, #x); return 1; } } while (0)
int main(void) {
    const uint32_t capacities[] = {0, 1, 64, UINT32_MAX - 1, UINT32_MAX};
    const uint32_t offsets[] = {0, 1, 31, 32, 63, 64, 65, UINT32_MAX};
    const uint32_t lengths[] = {0, 1, 2, 32, 64, 65, UINT32_MAX - 32, UINT32_MAX};
    const uint32_t flags[] = {0, D3DLOCK_READONLY, D3DLOCK_DISCARD, D3DLOCK_NOOVERWRITE,
        D3DLOCK_READONLY | D3DLOCK_DISCARD, D3DLOCK_READONLY | D3DLOCK_NOOVERWRITE,
        D3DLOCK_DISCARD | D3DLOCK_NOOVERWRITE, D3DLOCK_NOSYSLOCK | D3DLOCK_DONOTWAIT};
    unsigned cases = 0;
    for (unsigned c = 0; c < sizeof capacities / sizeof *capacities; ++c)
    for (unsigned o = 0; o < sizeof offsets / sizeof *offsets; ++o)
    for (unsigned n = 0; n < sizeof lengths / sizeof *lengths; ++n)
    for (unsigned f = 0; f < sizeof flags / sizeof *flags; ++f)
    for (int dirty = 0; dirty < 2; ++dirty) {
        memset(&buffer, 0, sizeof buffer);
        buffer.size = capacities[c]; buffer.shadow = 0x1000;
        buffer.locks = dirty; buffer.dirty_lo = dirty ? 2 : UINT32_MAX;
        buffer.dirty_hi = dirty ? 9 : 0;
        buffer.discard_pending = buffer.overwrite_pending = dirty;
        d3d_buffer expected = buffer;
        args[1] = offsets[o]; args[2] = lengths[n]; args[3] = 0; args[4] = flags[f];
        output = 0xdeadbeef;
        uint32_t wanted_output = output, wanted_result = D3DERR_INVALIDCALL;
        if (offsets[o] <= capacities[c]) {
            uint64_t end = (uint64_t)offsets[o] + lengths[n];
            if (!lengths[n] || end > capacities[c]) end = capacities[c];
            if (!(flags[f] & D3DLOCK_READONLY)) {
                if (offsets[o] < expected.dirty_lo) expected.dirty_lo = offsets[o];
                if (end > expected.dirty_hi) expected.dirty_hi = (uint32_t)end;
                if (flags[f] & D3DLOCK_DISCARD) expected.discard_pending = 1;
                else if (!(flags[f] & D3DLOCK_NOOVERWRITE)) expected.overwrite_pending = 1;
            }
            ++expected.locks;
            wanted_output = buffer.shadow + offsets[o]; wanted_result = D3D_OK;
        }
        CHECK(buf_Lock() == wanted_result);
        CHECK(output == wanted_output);
        CHECK(!memcmp(&buffer, &expected, sizeof buffer));
        ++cases;
    }
    printf("PASS: %u buffer Lock cases; overflow, offsets, read-only and dirty flags\n", cases);
    return 0;
}
'''
    out = ROOT / "build/buffer-lock-test"
    out.mkdir(parents=True, exist_ok=True)
    (out / "probe.c").write_text(probe)
    compiler, env, _ = compiler_environment()
    old_check = "if (!size || offset + size > b->size)"
    regressed = lock.replace("if (!size || size > b->size - offset)", old_check)
    for name, body, flags in [("regressed", regressed, []), ("production", lock, []),
                              ("tension", lock, ["/DVOID_RELEASE"])]:
        (out / "production.h").write_text(body)
        exe = out / (name + ".exe")
        build = subprocess.run([str(compiler), "/nologo", "/O2", "/W4", "/WX", "/std:c11", *flags,
                                str(out / "probe.c"), "/Fo" + str(out / (name + ".obj")), "/Fe" + str(exe)],
                               env=env, capture_output=True, text=True)
        (out / (name + "-build.log")).write_text(build.stdout + build.stderr)
        assert build.returncode == 0, build.stdout + build.stderr
        run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=15)
        (out / (name + ".log")).write_text(run.stdout + run.stderr)
        assert (run.returncode == 0) == (name != "regressed"), run.stdout + run.stderr
        print(name + ": " + run.stdout.strip())


if __name__ == "__main__":
    main()
