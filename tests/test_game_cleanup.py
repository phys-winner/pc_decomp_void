"""Run the launcher's cleanup policy on generated fixtures, never installed game data."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
JAVA = Path(os.environ.get("JAVA_HOME", "")) / "bin"
OUT = ROOT / "build/cleanup-test"
OUT.mkdir(parents=True, exist_ok=True)
sources = [ROOT / "android/app/src/org/thevoid/port" / name
           for name in ("Zip.java", "Deflate64.java", "Unpacker.java", "GameCleanup.java")]
subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(OUT),
                *map(str, sources), str(ROOT / "tests/GameCleanupTest.java")], check=True)
fixtures = []
if os.name == "nt":
    import _winapi
    linked_root = Path(tempfile.mkdtemp(prefix="junction-game-", dir=OUT))
    outside = Path(tempfile.mkdtemp(prefix="junction-outside-", dir=OUT))
    (outside / "outside.bin").write_bytes(b"keep")
    (linked_root / "bin/win32").mkdir(parents=True)
    (linked_root / "bin/win32/Game.exe").write_bytes(b"MZ")
    (linked_root / "data").mkdir()
    (linked_root / "data/info.xml").write_text("<Info/>")
    _winapi.CreateJunction(str(outside), str(linked_root / "external-link"))
    fixtures.append(str(linked_root))
subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(OUT), "org.thevoid.port.GameCleanupTest", str(OUT), *fixtures], check=True)
