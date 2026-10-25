"""Run the real restart activity with harmless Android stubs in disposable JVMs."""
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from test_touch_controls import method

ROOT = Path(__file__).resolve().parents[1]
JAVA = Path(os.environ.get("JAVA_HOME", "")) / "bin"
OUT = ROOT / "build/restart-test"
OUT.mkdir(parents=True, exist_ok=True)
activity = (ROOT / "android/app/src/org/thevoid/port/GameActivity.java").read_text(encoding="utf-8")
stubs = {
    "android/os/Bundle.java": "package android.os; public final class Bundle { }",
    "android/os/Process.java": '''package android.os;
public final class Process {
    public static int killed = -1;
    public static int myPid() { return 123; }
    public static void killProcess(int pid) { assert killed == -1; killed = pid; }
}''',
    "android/content/Intent.java": '''package android.content;
public final class Intent {
    public static final int FLAG_ACTIVITY_NEW_TASK = 0x10000000, FLAG_ACTIVITY_CLEAR_TASK = 0x8000;
    public final Class<?> target; public int flags;
    private final java.util.Map<String,Object> values = new java.util.HashMap<>();
    public Intent(Object context, Class<?> target) { this.target = target; }
    public Intent putExtra(String key, String value) { values.put(key,value); return this; }
    public Intent putExtra(String key, int value) { values.put(key,value); return this; }
    public Intent putExtra(String key, boolean value) { values.put(key,value); return this; }
    public Intent addFlags(int value) { flags |= value; return this; }
    public String getStringExtra(String key) { return (String)values.get(key); }
    public int getIntExtra(String key,int fallback) { return values.containsKey(key) ? (Integer)values.get(key) : fallback; }
    public boolean getBooleanExtra(String key,boolean fallback) { return values.containsKey(key) ? (Boolean)values.get(key) : fallback; }
}''',
    "android/app/Activity.java": '''package android.app;
import android.content.Intent;
public class Activity {
    public static Intent incoming, launched;
    public static boolean restarting;
    public static String expected;
    public Intent getIntent() { return incoming; }
    protected void onCreate(android.os.Bundle state) { }
    public void startActivity(Intent value) {
        assert launched == null; launched = value;
        assert value.target.getSimpleName().equals(expected) : value.target;
        assert (value.flags & Intent.FLAG_ACTIVITY_NEW_TASK) != 0;
        if (restarting) {
            assert (value.flags & Intent.FLAG_ACTIVITY_CLEAR_TASK) != 0;
            assert android.os.Process.killed == incoming.getIntExtra("pid", -1);
            assert java.util.Objects.equals(value.getStringExtra("game"), incoming.getStringExtra("game"));
            assert java.util.Objects.equals(value.getStringExtra("userdata"), incoming.getStringExtra("userdata"));
            System.out.println("restart target/extras/PID/flags verified: " + expected);
        }
    }
    public void finish() { assert launched != null; System.out.println("restart finished before process exit"); }
}''',
    "org/thevoid/port/Launcher.java": 'package org.thevoid.port; public final class Launcher { static final String EXTRA_GAME = "game"; }',
    "org/thevoid/port/GameActivity.java": '''package org.thevoid.port;
public final class GameActivity extends android.app.Activity {
''' + method(activity, "void restart()") + "\n" + method(activity, "private void restart(boolean launcher)") + '''
    void chooseRestart(boolean launcher) { restart(launcher); }
}''',
    "org/thevoid/port/RestartProbe.java": '''package org.thevoid.port;
import android.app.Activity;
import android.content.Intent;
public final class RestartProbe {
    static final String GAME = "/sdcard/TheVoid/Игра с пробелами", PROFILE = "/sdcard/TheVoid/userdata-qa20261019";
    static Intent input(boolean launcher, int pid) {
        return new Intent(null, GameActivity.class).putExtra("pid",pid).putExtra("launcher",launcher)
            .putExtra("game",GAME).putExtra("userdata",PROFILE);
    }
    public static void main(String[] args) {
        if (args[0].equals("forward")) {
            for (boolean launcher : new boolean[] {false,true}) {
                Activity.incoming = input(launcher, 321); Activity.launched = null; Activity.expected = "RestartActivity";
                new GameActivity().chooseRestart(launcher);
                Intent i = Activity.launched;
                assert i.getIntExtra("pid",-1) == android.os.Process.myPid();
                assert i.getBooleanExtra("launcher",!launcher) == launcher;
                assert GAME.equals(i.getStringExtra("game")) && PROFILE.equals(i.getStringExtra("userdata"));
            }
            Activity.incoming = null; Activity.launched = null;
            new GameActivity().restart();
            assert !Activity.launched.getBooleanExtra("launcher",true);
            assert Activity.launched.getStringExtra("game") == null && Activity.launched.getStringExtra("userdata") == null;
            System.out.println("GameActivity restart forwarding/default/null-intent PASS");
            return;
        }
        boolean launcher = args[0].equals("launcher");
        int pid = args[0].equals("no-pid") ? -1 : 321;
        Activity.incoming = input(launcher,pid); Activity.restarting = true;
        Activity.expected = launcher ? "Launcher" : "GameActivity";
        new RestartActivity().onCreate(null);
        throw new AssertionError("RestartActivity did not terminate its helper process");
    }
}''',
}
sources = []
for name, text in stubs.items():
    file = OUT / "src" / name
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")
    sources.append(file)
sources.append(ROOT / "android/app/src/org/thevoid/port/RestartActivity.java")
subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(OUT), *map(str,sources)], check=True)
for case in ("forward", "game", "launcher", "no-pid"):
    run = subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(OUT), "org.thevoid.port.RestartProbe",case],
                         check=True, capture_output=True, text=True)
    assert "PASS" in run.stdout if case == "forward" else "restart finished before process exit" in run.stdout, run.stdout
    print(run.stdout.strip())
namespace = "{http://schemas.android.com/apk/res/android}"
restart = next(a for a in ET.parse(ROOT / "android/app/AndroidManifest.xml").iter("activity")
               if a.get(namespace + "name") == ".RestartActivity")
assert restart.get(namespace + "process") == ":restart" and restart.get(namespace + "exported") == "false"
print("PASS: fresh game/launcher targets, original game/profile extras, safe PID handling, task flags, process exit and private helper manifest")
