"""Run the shipping profile migration and launcher settings lookup on temporary files."""
from pathlib import Path
import subprocess
import sys
import tempfile

from test_touch_controls import method

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_game_apk import JAVA_HOME

OUT = ROOT / "build/profile-storage-test"
OUT.mkdir(parents=True, exist_ok=True)
port = ROOT / "android/app/src/org/thevoid/port"
profile = (port / "Profile.java").read_text(encoding="utf-8")
launcher = (port / "Launcher.java").read_text(encoding="utf-8")
activity = (port / "GameActivity.java").read_text(encoding="utf-8")
assert "base = game;" in method(activity, "@Override protected void onCreate(Bundle state)")
assert 'File data = new File(base, userdata);' in method(activity, "private void start(Release release)")
prepare = method(activity, "private void prepareAssets(")
assert prepare.index("Profile.migrate(new File(Launcher.baseDir(), data.getName()), data)") < prepare.index("ScriptOverrides.install(")
assert 'new File(base, "userdata/overrides/settings.xml")' in launcher

probe = OUT / "ProfileStorageProbe.java"
probe.write_text('''import java.io.*;
import java.nio.file.*;
public class ProfileStorageProbe {
    File base, game;
''' + method(profile, "static void migrate(") + "\n" + method(launcher, "private File gameSettings()") + '''
    static void put(File root, String path, String text) throws IOException {
        File file = new File(root, path);
        Files.createDirectories(file.getParentFile().toPath());
        Files.write(file.toPath(), text.getBytes("UTF-8"));
    }
    static String read(File root, String path) throws IOException {
        return new String(Files.readAllBytes(new File(root, path).toPath()), "UTF-8");
    }
    static void overlap(File from, File to) throws IOException {
        try { migrate(from, to); throw new AssertionError("overlap accepted"); }
        catch (IOException expected) { }
    }
    public static void main(String[] args) throws Exception {
        File root = new File(args[0]);
        File old = new File(root, "TheVoid/userdata"), chosen = new File(root, "Chosen Game");
        chosen.mkdirs();
        File target = new File(chosen, "userdata");
        migrate(old, target);
        assert !old.exists() && !target.exists() : "missing profile must not create the old root";
        String[] paths = {"Documents/My Games/Turgor/Savegames/player.sav", "overrides/settings.xml",
            "ProgramData/Ice-pick Lodge/Turgor/rcfg.xml", "PublicDocuments/My Games/Turgor/Cache/effects.hdr",
            "shadercache/0123456789abcdef.bin", "void.log"};
        for (String path : paths) put(old, path, path);
        migrate(old, target);
        assert !old.exists();
        for (String path : paths) assert read(target, path).equals(path) : path;
        migrate(old, target);
        migrate(target, target);
        assert read(target, paths[0]).equals(paths[0]);

        put(old, paths[0], "older-conflicting-save");
        put(old, "Documents/Savegames/missing.sav", "migrate-me");
        put(old, "overrides/new.bin", "override");
        migrate(old, target);
        assert read(target, paths[0]).equals(paths[0]) : "destination save overwritten";
        assert read(old, paths[0]).equals("older-conflicting-save") : "original conflict deleted";
        assert read(target, "Documents/Savegames/missing.sav").equals("migrate-me");
        assert read(target, "overrides/new.bin").equals("override");
        assert !new File(old, "overrides").exists();

        File other = new File(root, "Another Game/userdata");
        other.mkdirs();
        put(other, paths[0], "other-player");
        migrate(new File(root, "missing/userdata"), other);
        assert read(other, paths[0]).equals("other-player");
        overlap(old, new File(old, "nested"));
        overlap(old, old.getParentFile());
        assert read(old, paths[0]).equals("older-conflicting-save");
        put(root, "blocked", "a-file");
        try { migrate(old, new File(root, "blocked/userdata")); throw new AssertionError("blocked move succeeded"); }
        catch (IOException expected) { }
        assert read(old, paths[0]).equals("older-conflicting-save");

        File qa = new File(root, "TheVoid/userdata-qa20261025");
        put(qa, "test.sav", "isolated");
        migrate(qa, new File(chosen, qa.getName()));
        assert read(new File(chosen, qa.getName()), "test.sav").equals("isolated");
        assert read(target, paths[0]).equals(paths[0]);

        ProfileStorageProbe launcher = new ProfileStorageProbe();
        launcher.base = new File(root, "TheVoid");
        launcher.game = chosen;
        assert launcher.gameSettings().equals(new File(target, "overrides/settings.xml"));
        Files.delete(new File(target, "overrides/settings.xml").toPath());
        put(old, "overrides/settings.xml", "old-options-before-migration");
        assert launcher.gameSettings().equals(new File(old, "overrides/settings.xml"));
        migrate(old, target);
        assert launcher.gameSettings().equals(new File(target, "overrides/settings.xml"));
        assert read(target, "overrides/settings.xml").equals("old-options-before-migration");
        System.out.println("PASS profile storage: selected folder, all profile files, merge without overwrite, conflicts retained, retry, overlap/I/O rejection, isolated profiles, launcher options");
    }
}
''', encoding="utf-8")
subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(OUT), str(probe)], check=True)
with tempfile.TemporaryDirectory(prefix="profile-", dir=OUT) as fixtures:
    subprocess.run([str(JAVA_HOME / "bin/java.exe"), "-ea", "-cp", str(OUT), "ProfileStorageProbe", fixtures], check=True)
