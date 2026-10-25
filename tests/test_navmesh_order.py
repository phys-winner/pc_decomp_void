"""Compare native volatile/plain guest memory with the emitted navmesh leaf."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_android import CLANG, HOST_FLAGS
from build_x86_incremental import compiler_environment


def main():
    out = ROOT / "build/navmesh-order-test"
    out.mkdir(parents=True, exist_ok=True)
    for plain in (False, True):
        processed = subprocess.run([str(CLANG), *HOST_FLAGS,
            *(["-DRECOMP_PLAIN_MEMORY"] if plain else []), "-E", "-dM",
            str(ROOT / "android/host/navmesh_native.c")], cwd=ROOT, capture_output=True, text=True)
        assert processed.returncode == 0, processed.stderr
        (out / ("production-macros-plain%d.txt" % plain)).write_text(processed.stdout, encoding="utf-8")
        qualifier = re.search(r"^#define RECOMP_MEM_QUAL(?:[ \t]+(.*))?$", processed.stdout, re.M)
        assert qualifier, "production memory qualifier missing"
        assert (qualifier[1] or "").strip() == ("" if plain else "volatile"), qualifier[0]
        assert not re.search(r"^#define RECOMP_GENERATED_CODE\b", processed.stdout, re.M)
    print("PASS production HOST_FLAGS preprocessing: plain selects ordinary memory, disabled selects volatile, no GENERATED_CODE")
    originals = []
    paths = [ROOT / "generated/engine-x86" / name for name in
             ("engine_0000.c", "engine_0007.c", "engine_0048.c")]
    sources = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    for name in ("sub_11002FF0", "sub_1101BC60", "sub_110EC300", "sub_110EC930"):
        body = re.search(r"^void " + name + r"\(void\) \{.*?^\}", sources, re.M | re.S)
        assert body, name
        originals.append(body[0].replace("void sub_110EC930(void)", "void original_leaf(void)"))
    header = (ROOT / "android/runtime/recomp_types.h").read_text(encoding="utf-8")
    guard = "#if defined(_MSC_VER) || !defined(__aarch64__)"
    assert header.count(guard) == 1
    header = header.replace(guard, "#if 0", 1)
    header, count = re.subn(r"static inline uint64_t __rdtsc\(void\) \{.*?\n\}", "", header, flags=re.S)
    assert count == 1
    header, count = re.subn(r"^#define ADDR\(va\).+$",
        "static void *guest_address(uint32_t va);\n#define ADDR(va) ((uintptr_t)guest_address((uint32_t)(va)))",
        header, flags=re.M)
    assert count == 1
    (out / "runtime-fixture.h").write_text(header, encoding="utf-8")
    native = (ROOT / "android/host/navmesh_native.c").read_text(encoding="utf-8").replace('#include "host.h"', "")
    native, count = re.subn(r"#define ENGINE_EPSILON 0x11122974u", "#define ENGINE_EPSILON (BASE+0x500u)", native)
    assert count == 1
    native, count = re.subn(r"#define ENGINE_FIXED_TO_UNITS 0x11122D0Cu", "#define ENGINE_FIXED_TO_UNITS (BASE+0x504u)", native)
    assert count == 1
    driver = (ROOT / "tests/navmesh_order_probe.c").read_text(encoding="utf-8")
    source = out / "probe.c"
    source.write_text(driver.replace("/* EMITTED */", "\n".join(originals)).replace("/* NATIVE */", native), encoding="utf-8")
    _, env, _ = compiler_environment()
    env["LIB"] = env["LIB"].replace("\\x86", "\\x64")
    results = []
    for local, plain in [(local, plain) for local in (False, True) for plain in (False, True)]:
        exe = out / ("probe-local%d-plain%d.exe" % (local, plain))
        command = [str(CLANG), "--target=x86_64-pc-windows-msvc", "-fuse-ld=link", "-O2", "-std=c11",
                   "-fno-strict-aliasing", "-fwrapv", "-ffp-contract=off", "-DRECOMP_TRACE",
                   *(["-DRECOMP_LOCAL_REGS"] if local else []), "-DNAVMESH_PLAIN_MEMORY=%d" % plain, str(source), "-o", str(exe)]
        built = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
        (out / ("compile-local%d-plain%d.log" % (local, plain))).write_text(built.stdout + built.stderr, encoding="utf-8")
        assert built.returncode == 0, built.stdout + built.stderr
        checked = subprocess.run([str(exe), *(["benchmark"] if "--benchmark" in sys.argv else [])], cwd=ROOT, capture_output=True, text=True, timeout=60)
        assert checked.returncode == 0, checked.stdout + checked.stderr
        print("local=%s plain=%s: %s" % (local, plain, checked.stdout.strip()))
        results.append(dict(local_registers=local, plain_native_memory=plain, output=checked.stdout.strip()))
    paths += [ROOT / "android/host/navmesh_native.c", ROOT / "android/runtime/recomp_types.h"]
    (out / "result.json").write_text(json.dumps(dict(status="PASS", results=results,
        source_hashes={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
        oracle="exact emitted leaf and its three exact emitted helpers",
        compared="distance bits, selected polygon, ray inputs, all mesh/point/leaf memory outside original stack",
        fixture_adaptations=["ARM architecture guard and unused timer", "bounded oracle guest mapping",
                             "native direct guest-base mapping with relocated read-only epsilon/scale constants"],
        original_pe_executed=False), indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
