"""Run the release detector against the user's loose Russian translation."""
import subprocess
import sys
import zipfile
from pathlib import Path

from test_touch_controls import method

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_game_apk import JAVA_HOME


def main():
    out = ROOT / "build/touch-fixes/localization-test"
    game = out / "game"
    menu = game / "data/PROPERTIES/Strings/menu.txt"
    menu.parent.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) > 1:
        with zipfile.ZipFile(sys.argv[1]) as archive:
            menu.write_bytes(archive.read("PROPERTIES/Strings/menu.txt"))
    else:
        menu.write_bytes(b"\xff\xfe" + "@nstring main_menu_new_game\r\nНовая игра\r\n".encode("utf-16le"))
    activity = (ROOT / "android/app/src/org/thevoid/port/GameActivity.java").read_text(encoding="utf-8")
    overrides = (ROOT / "android/app/src/org/thevoid/port/ScriptOverrides.java").read_text(encoding="utf-8")
    source = out / "LocalizationProbe.java"
    source.write_text('''import java.io.File;
public class LocalizationProbe {
    static class ScriptOverrides {
''' + method(overrides, "static File file(") + '''
    }
''' + method(activity, "static final class Release") + r'''
    public static void main(String[] args) {
        File game = new File(args[0]);
        String info = "<Info EngTitle=\"Tension\" Title=\"Tension\" />";
        String languages = "<Language Name=\"Polish\" />";
        Release translated = new Release(game, info, languages);
        assert translated.language.equals("Russian");
        assert translated.library.equals("void_tension") && translated.images.equals("lifted-tension");
        File menu = ScriptOverrides.file(game, "data/properties/strings/menu.txt");
        assert menu.isFile() && Release.read(menu).codePoints().anyMatch(c -> c >= 0x0400 && c <= 0x04ff);
        Release original = new Release(new File(game, "absent"), info, languages);
        assert original.language.equals("Polish") && original.library.equals("void_tension");
        Release modern = new Release(new File(game, "absent"), "<Info EngTitle=\"Void\" />", languages);
        assert modern.library.equals("void");
        System.out.println("PASS: actual Russian ZIP text, case-insensitive loose paths, language and executable are independent");
    }
}
''', encoding="utf-8")
    subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(out), str(source)], check=True)
    subprocess.run([str(JAVA_HOME / "bin/java.exe"), "-ea", "-cp", str(out), "LocalizationProbe", str(game)], check=True)


if __name__ == "__main__":
    main()
