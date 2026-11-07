"""Execute the shipping program-cache code on isolated files, including an old-code control."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_x86_incremental import compiler_environment


def main():
    out = ROOT / "build/program-cache-test"
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / "android/host/shader_warm.c").read_text(encoding="utf-8")
    stage = (ROOT / "android/host/d3d9_shader.c").read_text(encoding="utf-8")
    cache = re.search(r"^typedef struct compiled_stage \{.*?^#define compile d3d_shader_compile_source", stage, re.M | re.S).group()
    (out / "stage-cache.h").write_text(cache)
    compiler, env, _ = compiler_environment()

    def compile_source(text, name, flags=()):
        (out / "shader-warm.h").write_text(re.sub(r"^#include .*\n", "", text, flags=re.M))
        exe = out / (name + ".exe")
        result = subprocess.run([str(compiler), "/nologo", "/O2", "/W4", "/D_CRT_SECURE_NO_WARNINGS",
                                 "/I" + str(out), "/I" + str(ROOT / "tests"), *flags,
                                 str(ROOT / "tests/program_cache_probe.c"), "/Fo" + str(out / (name + ".obj")),
                                 "/Fe" + str(exe)], env=env, capture_output=True, text=True)
        (out / (name + "-build.log")).write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
        return exe

    for name, flags in (("current", ()), ("tension", ("/DVOID_RELEASE",))):
        exe = compile_source(source, name, flags)
        for case in ("clean", "budget", "trim", "boundary"):
            with tempfile.TemporaryDirectory(prefix="void-program-cache-") as folder:
                link = None
                if case == "clean":
                    directory = Path(folder) / "programcache"
                    directory.mkdir()
                    target = Path(folder) / "link-target.bin"
                    target.write_bytes(b"keep target")
                    candidate = directory / "0000000000000007.bin"
                    try:
                        candidate.symlink_to(target)
                        link = candidate
                    except OSError:
                        print("SKIP: symbolic-link fixture requires Windows symlink permission")
                result = subprocess.run([str(exe), folder, case], capture_output=True, text=True)
                assert result.returncode == 0, result.stdout + result.stderr
                if link is not None:
                    assert link.is_symlink() and target.read_bytes() == b"keep target"
                    print("PASS: canonical symbolic link and its external target retained")
                print(name + ": " + result.stdout, end="")
    # Removing housekeeping and header accounting recreates the old policy.
    old_source = source
    for before, after, count in (("    binary_housekeeping();\n", "", 2),
        ("sizeof(binary_header) + (uint64_t)length", "(uint64_t)length", 1),
        ("sizeof h + (uint64_t)got, memory_order_relaxed", "(uint64_t)got, memory_order_relaxed", 1)):
        assert old_source.count(before) == count
        old_source = old_source.replace(before, after)
    old = compile_source(old_source, "old-policy")
    for case in ("clean", "budget", "trim"):
        with tempfile.TemporaryDirectory(prefix="void-program-cache-control-") as folder:
            result = subprocess.run([str(old), folder, case], capture_output=True, text=True)
            assert result.returncode != 0, "old policy unexpectedly passed " + case
    print("PASS: old-policy controls fail at runtime for stale-file retention, header budget and missing eviction")


if __name__ == "__main__":
    main()
