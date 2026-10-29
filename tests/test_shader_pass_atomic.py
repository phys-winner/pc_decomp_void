"""Both releases must finish a cold shader build before consuming its passes."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/shader-pass-atomic-test"
sys.path.insert(0, str(ROOT / "tools"))
from build_x86_incremental import compiler_environment


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source = (ROOT / "android/host/renderer_native.c").read_text()
    mappings = source[source.index("#ifdef VOID_RELEASE"):source.index("static int renderer_native_enabled")]
    source = re.search(r"^void RENDERER_PASS_BUILD\(void\)\s*\{.*?^\}", source, re.M | re.S)[0]
    assert source.count("    RENDERER_PASS_BUILD_LIFTED();") == 1
    fixture = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
/* RELEASE MAPPINGS */
static uint32_t memory[2048];
#define GPTR(a) ((uint8_t *)memory + (a))
#define MEM32(a) (*(uint32_t *)GPTR(a))
#define MEM8(a) (*GPTR(a))
static uint32_t g_eax, g_ecx, g_esp;
static unsigned active, handed, pending, calls, ready_passes, partial_passes;
static void void_d3dx_async_begin(uint32_t esp) { assert(esp == g_esp); active = 1; }
static uint64_t void_d3dx_async_end(void) { active = 0; return handed; }
/* The original build publishes output before a later split needs a cold shader.
 * Its caller consumes that output even when AL says the build failed. */
static void RENDERER_PASS_BUILD_LIFTED(void) {
    ++calls;
    if (active && pending) { handed = 1; ++partial_passes; g_eax = 0; }
    else { ++ready_passes; g_eax = 1; }
    g_esp += 4;
}
#include "production.h"
static void invoke(void) { g_ecx = 0x400; g_esp = 0x800; RENDERER_PASS_BUILD(); assert(g_esp == 0x804); }
int main(void) {
    unsigned slot, count, cold;
    MEM32(0x804) = 7;
    MEM32(0x808) = 0x1000;
    MEM8(0x80c) = 0;
    memcpy(GPTR(0x1004), "cold firework", 14);
    for (cold = 0; cold < 2; ++cold) {
      pending = cold;
      for (slot = 0; slot < 4; ++slot) for (count = 0; count < 5; ++count) {
        memset(GPTR(0x400), 0, 60);
        MEM32(0x400 + 44 + slot * 4) = count;
        invoke();
        assert(g_eax == 1 && ready_passes == calls && partial_passes == 0 && !active && !handed);
      }
    }
    assert(calls == 40 && ready_passes == 40);
    puts("PASS: 40 cold/warm builds, all light-count slots, complete passes, stack cleanup");
    return 0;
}
'''
    (OUT / "probe.c").write_text(fixture.replace("/* RELEASE MAPPINGS */", mappings))
    compiler, env, _ = compiler_environment()
    for name in ("void", "tension", "regressed-void", "regressed-tension"):
        flags = ["/DVOID_RELEASE"] if name.endswith("tension") else []
        regressed = name.startswith("regressed-")
        # A negative control reintroduces the deferred build which published partial passes.
        header = source.replace("    RENDERER_PASS_BUILD_LIFTED();",
                                "    void_d3dx_async_begin(g_esp);\n"
                                "    RENDERER_PASS_BUILD_LIFTED();\n"
                                "    void_d3dx_async_end();") if regressed else source
        (OUT / "production.h").write_text(header)
        exe = OUT / (name + ".exe")
        built = subprocess.run([str(compiler), "/nologo", "/O2", "/std:c11", "/D_CRT_SECURE_NO_WARNINGS",
                                "/I" + str(ROOT / "generated/tension"), *flags,
                                str(OUT / "probe.c"), "/Fo" + str(OUT / (name + ".obj")),
                                "/Fe" + str(exe)], env=env, capture_output=True, text=True)
        assert built.returncode == 0, built.stdout + built.stderr
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        assert (run.returncode == 0) != regressed, run.stdout + run.stderr
        print(name + ": " + (run.stdout.strip() if run.returncode == 0 else "old deferred path rejected"))


if __name__ == "__main__":
    main()
