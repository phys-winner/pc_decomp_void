"""Test native fallback normalization against actual MojoShader and Microsoft D3DX."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_x86_incremental import compiler_environment


def main():
    out = ROOT / "build/shader-disassembly-test"
    out.mkdir(parents=True, exist_ok=True)
    native = (ROOT / "android/host/d3dx9.c").read_text()
    helper = re.search(r"static size_t disassembly_text_size\(.*?^\}", native, re.M | re.S).group()
    (out / "disassembly-size.h").write_text(helper)
    # Use the same pinned parser/profiles as the Android build, compiled for this PC.
    mojo = ROOT / "reference/mojoshader"
    sources = [mojo / name for name in ("mojoshader.c", "mojoshader_common.c", "profiles/mojoshader_profile_common.c",
                                        "profiles/mojoshader_profile_d3d.c")]
    disabled = ["HLSL", "ARB1", "ARB1_NV", "METAL", "SPIRV", "GLSPIRV", "GLSL", "GLSL120", "GLSLES", "GLSLES3", "BYTECODE"]
    compiler, env, _ = compiler_environment()
    command = [str(compiler), "/nologo", "/O2", "/w", "/D_CRT_SECURE_NO_WARNINGS", "/std:c11",
               *["/DSUPPORT_PROFILE_" + name + "=0" for name in disabled], "/I" + str(mojo), "/I" + str(out),
               "/I" + str(ROOT / "android/runtime"),
               *map(str, sources), str(ROOT / "tests/shader_disassembly_probe.c"), "/Fo" + str(out) + "\\",
               "/Fe" + str(out / "probe.exe")]
    built = subprocess.run(command, env=env, cwd=out, capture_output=True, text=True)
    (out / "build.log").write_text(built.stdout + built.stderr)
    assert not built.returncode, built.stdout + built.stderr
    # RendererD3D edits vertex disassembly to generate its skinning variants.
    models = {0xFFFE0101, 0xFFFE0200, 0xFFFE0300}
    chosen = {}
    for path in sorted((ROOT / "build/shadercache/results").glob("*.bin")):
        with path.open("rb") as stream:
            model = int.from_bytes(stream.read(4), "little")
        if model in models:
            chosen.setdefault(model, path)
        if set(chosen) == models:
            break
    assert set(chosen) == models, chosen
    subprocess.run([str(out / "probe.exe"), *map(str, chosen.values())], check=True)


if __name__ == "__main__":
    main()
