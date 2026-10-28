"""Exercise the real APK cache installer and compile the startup UI/JNI callers."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
JAVA = Path(os.environ.get("JAVA_HOME", "")) / "bin"
ANDROID = Path(os.environ.get("ANDROID_SDK", os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or Path.home() / "AppData/Local/Android/Sdk")) / "platforms/android-36/android.jar"
OUT = ROOT / "build/shader-progress-test"
OUT.mkdir(parents=True, exist_ok=True)

STUBS = {
    "android/content/Context.java": """package android.content;
public final class Context {
    private final android.content.res.AssetManager assets;
    public Context(java.io.File root) { assets = new android.content.res.AssetManager(root); }
    public android.content.res.AssetManager getAssets() { return assets; }
}""",
    "android/content/res/AssetManager.java": """package android.content.res;
public final class AssetManager {
    private final java.io.File root;
    public AssetManager(java.io.File root) { this.root = root; }
    public java.io.InputStream open(String name) throws java.io.IOException {
        return new java.io.FileInputStream(new java.io.File(root, name));
    }
}""",
    "android/util/Log.java": """package android.util;
public final class Log { public static int i(String tag, String message) { return 0; } }""",
}


def native_lookup():
    sys.path.insert(0, str(ROOT / "tools"))
    from build_x86_incremental import compiler_environment
    native = (ROOT / "android/host/d3dx9.c").read_text()
    functions = [re.search(r"^static void error_answer\([^\n]+\)\n\{.*?^\}", native, re.M | re.S).group()]
    for name in ("void_d3dx_set_packaged_cache_dir", "cache_bytecode_valid", "cache_answer_in", "bundle_disabled", "cache_answer"):
        functions.append(re.search(r"^(?:static int|void) " + name + r"\([^\n]+\)\n\{.*?^\}",
                                   native, re.M | re.S).group())
    functions.append(re.search(r"^uint32_t void_d3dx_cache_responses\([^\n]+", native, re.M).group())
    functions.append(re.search(r"^uint64_t void_d3dx_missing_shader\([^\n]+", native, re.M).group())
    functions.append(re.search(r"^static void shader_missing\([^\n]+\)\n\{.*?^\}", native, re.M | re.S).group())
    for name in ("void_d3dx_shader_failure", "shader_family_result"):
        functions.append(re.search(r"^(?:static )?void " + name + r"\([^\n]+\)\n\{.*?^\}", native, re.M | re.S).group())
    shader = (ROOT / "android/host/d3d9_shader.c").read_text()
    functions.append(re.search(r"^static void shader_draw_result\([^\n]+\)\n\{.*?^\}", shader, re.M | re.S).group())
    (OUT / "cache-answer.h").write_text("\n\n".join(functions))
    compiler, env, _ = compiler_environment()
    subprocess.run([str(compiler), "/nologo", "/O2", "/W4", "/D_CRT_SECURE_NO_WARNINGS", "/I" + str(OUT),
                    str(ROOT / "tests/shader_lookup_probe.c"), "/Fo" + str(OUT / "lookup.obj"),
                    "/Fe" + str(OUT / "lookup.exe")], env=env, check=True, capture_output=True)
    with tempfile.TemporaryDirectory(prefix="lookup-", dir=OUT) as fixtures:
        subprocess.run([str(OUT / "lookup.exe"), fixtures], check=True)


def main():
    stubs = []
    for name, text in STUBS.items():
        path = OUT / "stubs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        stubs.append(path)
    sources = [*stubs, ROOT / "android/app/src/org/thevoid/port/ShaderCache.java", ROOT / "tests/ShaderCacheInstallTest.java"]
    subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(OUT / "installer"),
                    *map(str, sources)], check=True)
    with tempfile.TemporaryDirectory(prefix="fixtures-", dir=OUT) as fixtures:
        subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(OUT / "installer"),
                        "org.thevoid.port.ShaderCacheInstallTest", fixtures], check=True)
    sources = sorted((ROOT / "android/app/src").rglob("*.java"))
    subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-cp", str(ANDROID),
                    "-d", str(OUT / "app"), *map(str, sources)], check=True)
    print("PASS: all Android Java sources compile with the real Android API")
    native_lookup()


if __name__ == "__main__":
    main()
