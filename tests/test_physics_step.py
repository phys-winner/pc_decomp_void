"""The physics step's choice (android/host/physx.c physics_wanted_step), compiled from the
shipping source with stubs for the shown rate, the clock and the Engine float."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/physics-step-test"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source = (ROOT / "android/host/physx.c").read_text()
    body = re.search(r"^static float physics_wanted_step\(void\)\n\{.*?^\}", source, re.M | re.S)
    assert body, "physics_wanted_step not found in physx.c"
    (OUT / "physics-step.h").write_text(body.group() + "\n")
    sys.path.insert(0, str(ROOT / "tools"))
    from build_x86_incremental import compiler_environment
    compiler, env, _ = compiler_environment()
    subprocess.run([str(compiler), "/nologo", "/O2", "/W4", "/I" + str(OUT), str(ROOT / "tests/physics_step_probe.c"),
                    "/Fo" + str(OUT / "probe.obj"), "/Fe" + str(OUT / "probe.exe")], env=env, check=True,
                   capture_output=True)
    subprocess.run([str(OUT / "probe.exe")], check=True)


if __name__ == "__main__":
    main()
