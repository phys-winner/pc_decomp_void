"""Check each release's real effect-library ABI and run its bounded collector."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_x86_incremental import compiler_environment
from lift_release import Body


def main():
    out = ROOT / "build/tension-20261031/shaderwarm-agent"
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / "android/host/script.c").read_text()
    for name, signature in (("library-effects", "static int library_effects"),
                            ("warm-shaders", "static void warm_shaders")):
        helper = re.search(re.escape(signature) + r"\(.*?\n\}", source, re.S).group()
        (out / (name + ".h")).write_text(helper)
    run_event = source[source.index("} else if (!strcmp(e->action, \"shaderwarm\"))"):
                       source.index("} else if (!strcmp(e->action, \"profile\"))")]
    assert "#if" not in run_event and "warm_shaders(e->a, e->b);" in run_event
    old = Body(ROOT / "generated/input/RendererD3D.dll",
               json.loads((ROOT / "generated/renderer-x86/report.json").read_text()),
               ROOT / "config/RendererD3D.functions.json")
    compiler, env, _ = compiler_environment()
    evidence = []
    for release, generated, catalog, macros in (
        ("2009", ROOT / "generated", ROOT / "config/RendererD3D.functions.json", source),
        ("tension", ROOT / "generated/tension", ROOT / "config/releases/tension/RendererD3D.functions.json",
         (ROOT / "generated/tension/release_overrides.h").read_text()),
    ):
        body = Body(generated / "input/RendererD3D.dll",
                    json.loads((generated / "renderer-x86/report.json").read_text()), catalog)
        addresses = {}
        for macro in ("RENDERER_EFFECT_PREGENERATE_VA", "RENDERER_EFFECT_LIBRARY_VT"):
            addresses[macro] = int(re.search(r"^#define " + macro + r" (0x[0-9A-Fa-f]+)u$", macros, re.M).group(1), 16)
        pregenerate = addresses["RENDERER_EFFECT_PREGENERATE_VA"]
        rx, _ = old.body(0x16203D50)
        assert body.matches(rx) == [pregenerate] and body.sizes[pregenerate] == old.sizes[0x16203D50]
        assert f"void sub_{pregenerate:08X}(void);" in (generated / "renderer-x86/renderer_funcs.h").read_text()
        # Both the constructor and destructor identify the same library and map layout.
        for address, field in ((0x161F05F0, 0x23), (0x161F1340, 0x36)):
            rx, _ = old.body(address)
            hits = body.matches(rx)
            assert len(hits) == 1 and body.sizes[hits[0]] == old.sizes[address]
            assert body.u32(hits[0] + field) == addresses["RENDERER_EFFECT_LIBRARY_VT"]
            assert hits[0] + field in body.relocs
        tables = [va - 60 for va in body.relocs if body.u32(va) == pregenerate]
        assert len(tables) == 3
        defines = [f"/D{macro}=0x{address:08X}u" for macro, address in addresses.items()]
        build = subprocess.run([str(compiler), "/nologo", "/O2", "/std:c11", *defines, "/I" + str(out),
                                str(ROOT / "tests/shaderwarm_probe.c"), "/Fe" + str(out / (release + ".exe")),
                                "/Fo" + str(out / (release + ".obj"))], env=env, capture_output=True, text=True)
        (out / (release + "-build.log")).write_text(build.stdout + build.stderr)
        assert build.returncode == 0, build.stdout + build.stderr
        run = subprocess.run([str(out / (release + ".exe"))], capture_output=True, text=True)
        assert run.returncode == 0, run.stdout + run.stderr
        evidence.append({"release": release, "image_sha256": hashlib.sha256(body.data).hexdigest(),
                         "addresses": {name: hex(value) for name, value in addresses.items()},
                         "effect_vtables": sorted(map(hex, tables)), "probe": run.stdout.strip()})
    (out / "result.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print("PASS: both releases' original constructor/destructor, pregeneration slot and bounded collector")


if __name__ == "__main__":
    main()
