"""Images.dir on the JVM: a pushed images folder that lacks an image the APK carries
(d3dx9_36.dll, the on-device shader compiler) gives way to the APK's own copy."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
JAVA = Path(os.environ.get("JAVA_HOME", "")) / "bin"
OUT = ROOT / "build/images-fallback-test"

STUBS = {
    "android/content/Context.java": """package android.content;
public final class Context {
    private final android.content.res.AssetManager assets;
    private final java.io.File files;
    public Context(java.io.File assets, java.io.File files) {
        this.assets = new android.content.res.AssetManager(assets);
        this.files = files;
    }
    public android.content.res.AssetManager getAssets() { return assets; }
    public java.io.File getFilesDir() { return files; }
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
public final class Log {
    public static int i(String tag, String message) { return 0; }
    public static int w(String tag, String message) { return 0; }
}""",
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    stubs = []
    for name, text in STUBS.items():
        path = OUT / "stubs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        stubs.append(path)
    sources = [*stubs, ROOT / "android/app/src/org/thevoid/port/Images.java", ROOT / "tests/ImagesFallbackTest.java"]
    subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(OUT / "classes"),
                    *map(str, sources)], check=True)
    with tempfile.TemporaryDirectory(prefix="fixtures-", dir=OUT) as fixtures:
        subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(OUT / "classes"),
                        "org.thevoid.port.ImagesFallbackTest", fixtures], check=True)


if __name__ == "__main__":
    main()
