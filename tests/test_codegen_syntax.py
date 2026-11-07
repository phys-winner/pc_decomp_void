"""Compile real shipping translation units, including their original include order."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_android as build


def main():
    out = ROOT / "build/codegen-syntax-test"
    out.mkdir(parents=True, exist_ok=True)
    saved = {name: getattr(build, name) for name in ("RELEASE", "GENERATED", "NATIVE_OVERRIDES", "MODULE_IMAGES", "OUT", "_images")}
    functions = {"engine": (0x1105E810,), "renderer": (0x160D6ED0, 0x160902D0),
                 "physxcore": (0x18064830, 0x1819AF40, 0x181F1F80)}
    results = []
    try:
        for release in ("void", "tension"):
            build.OUT = out / release
            build.OUT.mkdir(parents=True, exist_ok=True)
            build._images = {}
            if release == "tension":
                build.GENERATED = ROOT / "generated/tension"
                build.RELEASE = json.loads((build.GENERATED / "release.json").read_text())
                assert build.RELEASE.get("compile_transforms"), "run tools/lift_release.py tension --finish first"
                build.NATIVE_OVERRIDES = tuple(build.RELEASE["native_overrides"])
                build.MODULE_IMAGES = build.RELEASE["images"]
            else:
                for name in ("RELEASE", "GENERATED", "NATIVE_OVERRIDES", "MODULE_IMAGES"):
                    setattr(build, name, saved[name])
            for module, canonical in functions.items():
                targets = [b"\nvoid sub_%08X(void) {" % build.compile_address(address) for address in canonical]
                sources = [p for p in build.module_dir(module).glob("*.c") if any(token in p.read_bytes() for token in targets)]
                assert len(sources) == len(canonical), (release, module, sources)
                for source in sources:
                    before = hashlib.sha256(source.read_bytes()).hexdigest()
                    patched, flags = build.override_source(source, True)
                    assert patched != source and b"double l_st[8]" in patched.read_bytes(), source
                    command = [str(build.CLANG), *build.GENERATED_FLAGS, "-DRECOMP_LOCAL_REGS", "-DRECOMP_PLAIN_MEMORY",
                               *flags, "-fsyntax-only", str(patched)]
                    compiled = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
                    log = build.OUT / (source.stem + ".syntax.log")
                    log.write_text(compiled.stdout + compiled.stderr)
                    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
                    if module == "engine":
                        # The differential harness includes its runtime first;
                        # this shipping-TU negative control catches that blind spot.
                        text = patched.read_bytes()
                        assert text.startswith(b"#include <stdint.h>\n")
                        regressed = patched.with_name(source.stem + "-missing-stdint.c")
                        regressed.write_bytes(text.removeprefix(b"#include <stdint.h>\n"))
                        rejected = subprocess.run(command[:-1] + [str(regressed)], cwd=ROOT, capture_output=True, text=True)
                        (build.OUT / "missing-stdint.syntax.log").write_text(rejected.stdout + rejected.stderr)
                        assert rejected.returncode and "uint32_t" in rejected.stderr, "negative control compiled"
                    assert before == hashlib.sha256(source.read_bytes()).hexdigest()
                    print(f"{release}/{source.name}: NDK shipping TU syntax PASS", flush=True)
                    results.append(dict(release=release, source=str(source.relative_to(ROOT)), source_sha256=before,
                                        patched_sha256=hashlib.sha256(patched.read_bytes()).hexdigest(), command=command))
    finally:
        for name, value in saved.items():
            setattr(build, name, value)
    (out / "result.json").write_text(json.dumps(dict(status="PASS", results=results,
        negative_control="Removing the first stdint include fails on uint32_t in both real Engine translation units"), indent=2) + "\n")


if __name__ == "__main__":
    main()
