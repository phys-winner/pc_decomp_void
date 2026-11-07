"""Run the existing full-state x87 fixtures against the actual Tension bodies."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_android as build
from build_x86_incremental import compiler_environment
from lift_release import find_compile_transforms, load_release
from test_local_fpu import function


def main():
    out = ROOT / "build/tension-fpu-test"
    out.mkdir(parents=True, exist_ok=True)
    meta = find_compile_transforms("tension", load_release("tension"), ROOT / "generated/tension")
    previous = build.RELEASE
    build.RELEASE = {"compile_transforms": meta}
    addresses = {int(k, 16): int(v, 16) for values in meta.values() for k, v in values.items()}
    inputs = [ROOT / "tools/build_android.py", ROOT / "tools/lift_release.py",
              ROOT / "android/host/physics_native.c", ROOT / "android/host/renderer_particle_native.c",
              ROOT / "android/runtime/recomp_types.h", Path(__file__),
              *(ROOT / "tests" / name for name in ("local_fpu_probe.c", "particle_fpu_probe.c", "physics_sweep_probe.c",
                                                  "physics_tree_probe.c", "physics_worker_probe.c"))]
    cases = {"sat": (("engine", 0x1105E810), ("renderer", 0x160D6ED0)),
             "particle": (("renderer", 0x160902D0),), "sweep": (("physxcore", 0x18064830),),
             "tree": (("physxcore", 0x1819AF40),), "worker": (("physxcore", 0x181F1F80),)}
    bodies, names = {}, {}
    for kind, entries in cases.items():
        bodies[kind], names[kind] = [], []
        for module, address in entries:
            name = "sub_%08X" % addresses[address]
            matches = [p for p in (ROOT / f"generated/tension/{module}-x86").glob("*.c")
                       if ("void " + name + "(void)").encode() in p.read_bytes()]
            assert len(matches) == 1, (kind, name, matches)
            inputs += matches
            bodies[kind].append(function(matches[0], name))
            names[kind].append(name)

    def remap(text):
        text = re.sub(r"0x([0-9a-fA-F]+)", lambda m: "0x%08X" % addresses[int(m[1], 16)]
                      if int(m[1], 16) in addresses else m[0], text)
        return re.sub(r"sub_([0-9A-F]{8})", lambda m: "sub_%08X" % addresses[int(m[1], 16)]
                      if int(m[1], 16) in addresses else m[0], text)

    runtime = inputs[4].read_text().replace("#if defined(_MSC_VER) || !defined(__aarch64__)", "#if 0", 1)
    runtime, count = re.subn(r"static inline uint64_t __rdtsc\(void\) \{.*?\n\}", "", runtime, flags=re.S)
    assert count == 1
    runtime, count = re.subn(r"^#define ADDR\(va\).+$",
        "static void *guest_address(uint32_t va);\n#define ADDR(va) ((uintptr_t)guest_address((uint32_t)(va)))",
        runtime, flags=re.M)
    assert count == 1
    (out / "runtime-fixture.h").write_text(runtime)
    common = (ROOT / "tests/local_fpu_probe.c").read_text()
    physics = inputs[2].read_text()
    upstream = (ROOT / "reference/pcrecomp/runtime/recomp32/recomp_types.h").read_text()
    helpers = "\n".join(re.search(r"^static inline " + result + " " + name + r"\([^)]*\) \{.*?^\}",
        upstream, re.M | re.S)[0].replace(name, renamed, 1)
        for result, name, renamed in (("void", "fp_push_impl", "oracle_fp_push"),
                                     ("double", "fp_pop_impl", "oracle_fp_pop")))
    oracle_prefix = helpers + "\n#undef fp_push\n#undef fp_pop\n#define fp_push(v) oracle_fp_push(_st, &_fp_top, (v))\n#define fp_pop() oracle_fp_pop(_st, &_fp_top)\n"
    oracle_suffix = "\n#undef fp_push\n#undef fp_pop\n#define fp_push(v) fp_push_impl(_st, &_fp_top, (v))\n#define fp_pop() fp_pop_impl(_st, &_fp_top)\n"
    image = build.Image(ROOT / "generated/tension/input/RendererD3D.dll")
    constants = b"".join((image.u32(at) or 0).to_bytes(4, "little") for at in range(0x162D0000, 0x16370000, 4))
    constant_file = out / "renderer-constants.bin"
    constant_file.write_bytes(constants)
    _, env, _ = compiler_environment()
    env["LIB"] = env["LIB"].replace("\\x86", "\\x64")
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    results = []
    try:
        for kind in cases:
            fixture_name = {"sat": "local_fpu_probe.c", "particle": "particle_fpu_probe.c"}.get(kind, f"physics_{kind}_probe.c")
            driver = remap((ROOT / "tests" / fixture_name).read_text())
            guard = ""
            if kind == "particle":
                guard = re.sub(r"^#include .*\n", "", inputs[3].read_text(), flags=re.M)
                driver = driver.replace("/* DECLARATIONS */", common[:common.index("#define BASE")])
                driver = driver.replace("/* SNAPSHOTS */", common[common.index("#undef eax"):common.index("static snapshot observed_yields")])
            elif kind in ("sweep", "tree", "worker"):
                guard_name = {"sweep": "void_physics_sweep_finite", "tree": "void_physics_tree_node_finite",
                              "worker": "void_physics_worker_pair_finite"}[kind]
                guard = re.search(r"^int " + guard_name + r"\(.*?^\}", physics, re.M | re.S)[0]
                if kind != "sweep":
                    counter = "nodes" if kind == "tree" else "prefixes"
                    arguments, parameters = ("uint32_t c,uint32_t n,uint32_t f", "c,n,f") if kind == "tree" else ("void", "")
                    guard = f"static unsigned fast_{counter},fallback_{counter};\n" + guard.replace(guard_name, "guard_actual", 1)
                    guard += f"\nint {guard_name}({arguments}) {{ int hit=guard_actual({parameters}); if(hit)++fast_{counter};else ++fallback_{counter};return hit;}}\n"
            driver = driver.replace("/* GUARD */", guard)
            for local, plain, sse in ((False, False, False), (False, True, False),
                                      (True, False, False), (True, True, True)):
                combined = ("\n".join(bodies[kind]) + "\n").encode()
                if sse:
                    combined = build.localize_sse(combined)
                original = combined.decode()
                transformed = {"tree": build.localize_physics_tree, "worker": build.localize_physics_worker}.get(kind, build.localize_fpu)(combined).decode()
                assert "double l_st[8]" in transformed, kind
                original_names = {"sat": ("original_engine", "original_renderer"), "particle": ("original_particle",),
                                  "sweep": ("original_leaf",), "tree": ("original_af40",), "worker": ("original_worker",)}[kind]
                for name, renamed in zip(names[kind], original_names):
                    original = original.replace(name, renamed)
                if kind in ("sat", "particle"):
                    original = oracle_prefix + original + oracle_suffix
                if kind in ("tree", "worker"):
                    transformed = transformed.replace(names[kind][0], "candidate_af40" if kind == "tree" else "candidate_worker")
                selected = driver.replace("/* ORIGINALS */", original).replace("/* LOCALIZED */", transformed)
                if kind == "worker":
                    callees = sorted(set(re.findall(r"\bsub_[0-9A-F]+", combined.decode())) - set(names[kind]))
                    first_call = "sub_%08X" % addresses[0x181E7720]
                    stubs = "\n".join(f"void {name}(void);" for name in callees)
                    stubs += "\n" + "\n".join(f"void {name}(void) {{ abort(); }}" for name in callees if name != first_call)
                    selected = selected.replace("/* STUBS */", stubs)
                source = out / f"{kind}-r{int(local)}-p{int(plain)}-s{int(sse)}.c"
                source.write_text(selected)
                executable = source.with_suffix(".exe")
                command = [str(build.CLANG), "--target=x86_64-pc-windows-msvc", "-fuse-ld=link", "-O2", "-std=c11",
                    "-fno-strict-aliasing", "-fwrapv", "-ffp-contract=off", "-DRECOMP_TRACE", "-DRECOMP_YIELD_EVERY=1",
                    *(["-DRECOMP_LOCAL_REGS"] if local else []), *(["-DRECOMP_PLAIN_MEMORY"] if plain else []), str(source), "-o", str(executable)]
                built = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
                source.with_suffix(".compile.log").write_text(built.stdout + built.stderr)
                assert built.returncode == 0, built.stdout + built.stderr
                run = subprocess.run([str(executable), *([str(constant_file)] if kind == "particle" else [])],
                                     cwd=ROOT, capture_output=True, text=True, timeout=120)
                source.with_suffix(".run.log").write_text(run.stdout + run.stderr)
                assert run.returncode == 0, run.stdout + run.stderr
                print(f"{kind} regs={local} plain={plain} sse={sse}: {run.stdout.strip()}", flush=True)
                results.append(dict(kind=kind, local=local, plain=plain, sse=sse, output=run.stdout.strip()))
    finally:
        build.RELEASE = previous
    rejected = subprocess.run([sys.executable, "-B", str(ROOT / "tools/build_android.py"), "--release", "tension",
        "--pgo-use", str(ROOT / "build/pgo/void.profdata"), "--compile-only"], cwd=ROOT, capture_output=True, text=True)
    assert rejected.returncode and "a release needs its own PGO profile" in rejected.stderr
    assert hashes == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    (out / "result.json").write_text(json.dumps(dict(status="PASS", source_hashes=hashes, mappings=meta, results=results,
        oracle="Actual unmodified emitted Tension bodies and existing full-state fixtures; original global x87 helpers for SAT/particle",
        scope="CPU/flags/x87/shadows/memory/yields/fallback; tree callbacks/recursion; worker first-call boundary; rejects the 2009 PGO profile",
        limitations=["No original PE execution or hardware performance claim."]), indent=2) + "\n")


if __name__ == "__main__":
    main()
