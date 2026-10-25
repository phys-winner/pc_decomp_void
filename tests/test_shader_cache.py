"""Real static-shader keys/compilation and bounded native effect enumeration."""
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_shader_cache import request, shaders
from shader_service import build_tool
from build_x86_incremental import compiler_environment


def main():
    out = ROOT / "build/shadercache/test"
    requests = out / "requests"
    results = out / "results"
    requests.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    variants = {name: (key, data) for name, key, data in shaders()}
    # Observed on Pixel 10 when entering Ava's obscura, before this fix.
    key, data = variants["static/CompositeObscureAva/ps_3_0"]
    assert key == "db4e109751497ac9"
    obscura = {name: (shader, request_data) for name, (shader, request_data) in variants.items()
               if name.startswith(("static/CompositeObscure", "static/DownsampleObscure"))}
    assert "static/CompositeObscureOle/ps_3_0" in obscura and "static/DownsampleObscureOleAG/ps_3_0" in obscura
    for shader, request_data in obscura.values():
        (requests / (shader + ".req")).write_bytes(request_data)
    bad_keys = ["truncated-macros", "truncated-source"]
    (requests / (bad_keys[0] + ".req")).write_bytes(
        b"function=main\nprofile=ps_3_0\nflags=0\ninclude=no\nmacros=99999\nx")
    (requests / (bad_keys[1] + ".req")).write_bytes(data[:-1])
    run = subprocess.run([str(build_tool()), str(requests), str(results)], capture_output=True, text=True)
    assert run.returncode == 0 and (results / (key + ".bin")).stat().st_size > 4, run.stdout + run.stderr
    for name, (shader, _) in obscura.items():
        assert (results / (shader + ".bin")).stat().st_size > 4, name
    assert "truncated macros" in run.stderr and "truncated source" in run.stderr, run.stderr
    assert not any((results / (key + suffix)).exists() for key in bad_keys for suffix in (".bin", ".err"))

    # Confirm the pregeneration slot against all three real MSVC vtables.
    import pefile
    pe = pefile.PE(str(ROOT / "generated/input/RendererD3D.dll"))
    for vt in (0x162D3624, 0x162D3A34, 0x162D5E64):
        assert struct.unpack("<I", pe.get_data(vt + 60 - pe.OPTIONAL_HEADER.ImageBase, 4))[0] == 0x16203D50
    source = (ROOT / "android/host/script.c").read_text()
    helper = re.search(r"static int library_effects\(.*?\n\}", source, re.S).group()
    (out / "library-effects.h").write_text(helper)
    warm = re.search(r"static void warm_shaders\(.*?\n\}", source, re.S).group()
    (out / "warm-shaders.h").write_text(warm)
    compiler, env, _ = compiler_environment()
    subprocess.run([str(compiler), "/nologo", "/O2", "/std:c11", "/I" + str(out),
                    str(ROOT / "tests/shaderwarm_probe.c"), "/Fe" + str(out / "probe.exe"),
                    "/Fo" + str(out / "probe.obj")], env=env, check=True, capture_output=True)
    subprocess.run([str(out / "probe.exe")], check=True)
    print(f"PASS: {len(variants)} variants; all {len(obscura)} sister compositor/downsample variants; truncated requests rejected; original pregeneration ABI")


if __name__ == "__main__":
    main()
