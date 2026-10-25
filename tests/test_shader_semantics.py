"""Reproduce lost PS3 semantics and test the exact Android build-copy repair."""
import hashlib
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_android import fix_mojo_ps3_semantics, MOJO_SOURCES
from build_x86_incremental import compiler_environment


def main():
    out = ROOT / "build/shader-semantics-test"
    out.mkdir(parents=True, exist_ok=True)
    mojo = ROOT / "reference/mojoshader"
    original = (mojo / "mojoshader_assembler.c").read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    patched = out / "mojoshader_assembler.c"
    patched.write_bytes(fix_mojo_ps3_semantics(original))
    try:
        fix_mojo_ps3_semantics(original + original)
        raise AssertionError("ambiguous vendor source must be rejected")
    except ValueError:
        pass
    compiler, env, _ = compiler_environment()
    disabled = ["HLSL", "ARB1", "ARB1_NV", "METAL", "SPIRV", "GLSPIRV", "GLSL120"]
    flags = ["/nologo", "/O2", "/w", "/D_CRT_SECURE_NO_WARNINGS", "/std:c11",
             *["/DSUPPORT_PROFILE_" + name + "=0" for name in disabled],
             "/I" + str(mojo), "/I" + str(ROOT / "android/runtime")]
    for name in ("original", "fixed"):
        target = out / name
        target.mkdir(exist_ok=True)
        sources = [patched if name == "fixed" and path == "mojoshader_assembler.c" else mojo / path for path in MOJO_SOURCES]
        command = [str(compiler), *flags, *map(str, sources), str(ROOT / "tests/shader_semantics_probe.c"),
                   "/Fo" + str(target) + "\\", "/Fe" + str(target / "probe.exe")]
        built = subprocess.run(command, env=env, cwd=target, capture_output=True, text=True)
        (target / "build.log").write_text(built.stdout + built.stderr)
        assert not built.returncode, built.stdout + built.stderr
        subprocess.run([str(target / "probe.exe"), name], check=True)
    assert hashlib.sha256((mojo / "mojoshader_assembler.c").read_bytes()).hexdigest() == digest
    print("PASS: pinned vendor unchanged; exact shipping patch; PS3 varying names remain distinct")


if __name__ == "__main__":
    main()
