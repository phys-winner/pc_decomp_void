"""Verify Engine's ECX-preserving append against its own emitted body/helper."""
from pathlib import Path
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_x86_incremental import compiler_environment
from test_renderer_append import function


def main():
    out = ROOT / "build/engine-append-test"
    out.mkdir(parents=True, exist_ok=True)
    engine = ROOT / "generated/engine-x86/engine_0000.c"
    original = function(engine, "sub_110026D0") + "\n" + function(engine, "sub_110014F0").replace(
        "void sub_110014F0(void)", "void original_append(void)")
    native = (ROOT / "android/host/renderer_native.c").read_text().replace('#include "host.h"', '')
    # The append alone: the passes after it call into the host.
    native = native[:native.index("/* RendererD3D's scene-render pass")]
    native, count = re.subn(r'^void RENDERER_APPEND12\(void\).*$', '', native, flags=re.M)
    assert count == 1
    wrapper = re.search(r'^void ENGINE_DEBUG_VECTOR\(void\)\n\{.*?^\}',
                        (ROOT / "android/host/physics_native.c").read_text(), re.M | re.S).group()
    wrapper = wrapper.replace("ENGINE_DEBUG_VECTOR_LIFTED", "sub_110014F0_lifted").replace("ENGINE_DEBUG_VECTOR", "sub_110014F0")
    native += '\nstatic int physics_native_enabled = 1;\n' + wrapper
    driver = (ROOT / "tests/renderer_append_probe.c").read_text()
    driver = driver.replace("sub_16082260", "sub_110014F0").replace("sub_16082390", "sub_11001830")
    driver = driver.replace("/* EMITTED */", original).replace("/* NATIVE */", native)
    driver = driver.replace('    printf("PASS triangle',
                            '    initialize(1,3,BASE+0x4000); physics_native_enabled=0; differential(1);\n'
                            '    printf("PASS triangle')
    (out / "probe.c").write_text(driver)
    compiler, env, _ = compiler_environment()
    results = []
    for local in (False, True):
        exe = out / ("probe-local%d.exe" % local)
        built = subprocess.run([str(compiler), "/nologo", "/O2", "/W3", "/std:c11", "/DRECOMP_TRACE",
                                *(["/DRECOMP_LOCAL_REGS"] if local else []), "/Inative",
                                "/Ireference/pcrecomp/runtime/recomp32", str(out / "probe.c"),
                                "/Fe" + str(exe), "/Fo" + str(out / ("probe-local%d.obj" % local))],
                               env=env, cwd=ROOT, capture_output=True, text=True)
        assert built.returncode == 0, built.stdout + built.stderr
        tested = subprocess.run([str(exe)], capture_output=True, text=True)
        assert tested.returncode == 0, tested.stdout + tested.stderr
        print("Engine ECX preserved: " + tested.stdout.strip())
        results.append(dict(local_registers=local, output=tested.stdout.strip()))
    (out / "result.json").write_text(json.dumps(dict(status="PASS", results=results), indent=2))


if __name__ == "__main__":
    main()
