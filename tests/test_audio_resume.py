"""Run the Android audio backend with AAudio failures and lifecycle changes."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_android import CLANG
from build_x86_incremental import compiler_environment


def main():
    out = ROOT / "build/audio-resume-test"
    out.mkdir(exist_ok=True)
    source = (ROOT / "android/host/android_main.c").read_text(encoding="utf-8")
    audio = source[source.index("static AAudioStream *stream;"):source.rindex("#endif")]
    sound = (ROOT / "android/host/dsound.c").read_text(encoding="utf-8")
    mixer = sound[sound.index("struct dsbuf {"):sound.index("\n/* VOID_DSOUND_TRACE")]
    mixer += sound[sound.index("static float sample_at"):sound.index("static void *mixer_main")]
    mixer += "\n".join(re.search(r"COM_METHOD\(lst, " + method + r", \d\).*?^\}", sound, re.M | re.S).group()
                       for method in ("GetAllParameters", "SetAllParameters"))
    trace = sound[sound.index('    const char *trace = getenv("VOID_DSOUND_TRACE");'):]
    trace = trace[:trace.index("    MEM32(ARG(1))")]
    mixer += "\nstatic int trace_enabled(void) { int dstrace;\n" + trace + "return dstrace; }\n"
    mixer = "int void_audio_is_paused(void) { return audio_paused; }\n" + mixer
    fixture = (ROOT / "tests/audio_resume_probe.c").read_text(encoding="utf-8")
    generated = out / "probe.c"
    generated.write_text(fixture.replace("/* PRODUCTION */", audio + "\n" + mixer), encoding="utf-8")
    _, env, _ = compiler_environment()
    env["LIB"] = env["LIB"].replace("\\x86", "\\x64")
    exe = out / "probe.exe"
    built = subprocess.run([str(CLANG), "--target=x86_64-pc-windows-msvc", "-fuse-ld=link",
                            "-O2", "-std=c11", str(generated), "-o", str(exe)],
                           env=env, capture_output=True, text=True)
    (out / "build.log").write_text(built.stdout + built.stderr)
    assert built.returncode == 0, built.stdout + built.stderr
    with tempfile.TemporaryDirectory(prefix="profile-", dir=out) as profile:
        tested = subprocess.run([str(exe), profile], capture_output=True, text=True)
    (out / "run.log").write_text(tested.stdout + tested.stderr)
    assert tested.returncode == 0, tested.stdout + tested.stderr
    print(tested.stdout, end="")


if __name__ == "__main__":
    main()
