"""All graphics-quality choices retain SM3; original shadow controls still work."""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "tests")]
from build_game_apk import JAVA_HOME
from gscript_binary import Module
from patch_options import function_of, function_rows, patch_options
from patch_scripts import INDEXES, read_entry
from test_touch_native import VM


def video_menu():
    for index, language in INDEXES.items():
        module = Module(read_entry(index, "Scripts\\ui\\main_menu.bin"), legacy=language == "pl")
        original = list(module.instructions())
        ctor = function_of(module, next(r for r in original if r.get("text") == "Video Options State")["offset"])
        body = function_rows(module, ctor)
        context = next(r["register"] for r in original if r.get("opcode") == 67 and r["operands"][0] == ctor)
        apply, default, _ = struct.unpack("<3I", bytes.fromhex(module.contexts[context]["extra"]))
        patch_options(module, language)
        controls, actions = [], []

        def control(name, *args):
            controls.append((name, args))
            if name == "getSliderValue":
                return 0.2
            if name == "getCheckBoxState": return args[0] == selected
            return 0

        class Numeric(str):
            @property
            def asInt(self): return int(self)
        selected = 0
        globals = {r["register"]: {"call": control} for r in body if r["opcode"] == 14}
        named = {"logInfo": lambda *a: None, "getNamedString": lambda key: key,
                 "!vec2": lambda x, y: (x, y), "GammaCorrection": 1.,
                 "Settings": {"Shadows": Numeric("0")}, "saveSettings": lambda: None,
                 "__externals__": {(r["operands"][1], r["register"]): {"add": actions.append}
                                   for r in body if r["opcode"] == 12}}
        calls = {r["operands"][0]: lambda regs, slot: None for r in body if r["opcode"] == 63}
        vm = VM(module, globals, named, calls)
        vm.run(ctor, stops=(next(r["offset"] for r in body if r["opcode"] == 68),))
        assert sum(name == "createCheckbox" for name, args in controls) == 3
        assert any(name == "createLabel" and args[0] == "options_menu_gamma" for name, args in controls)
        assert actions == [3, 4, 5, 6]
        # No world view in the main menu; each original shadow value still saves.
        apply_body = function_rows(module, apply)
        world = next(r["register"] for r in apply_body if r["opcode"] == 14
                     and r["register"] not in globals)
        vm.globals[world] = None
        for selected in (0, 1, 2):
            vm.run(apply)
            assert str(named["Settings"]["Shadows"]) == str(selected)
            assert abs(named["GammaCorrection"] - 0.6) < 1e-6
        controls.clear()
        vm.run(default, stops=(next(r["offset"] for r in function_rows(module, default) if r["opcode"] == 64),))
        assert sum(name == "setCheckBoxState" for name, args in controls) == 3
        assert abs(next(args[1] for name, args in controls if name == "setSliderValue") - 0.33) < 1e-5
        print(f"PASS {language}: original shadows 0/1/2 and gamma controls, apply and default preserved")


def migration():
    out = ROOT / "build/fixed-shader-profile-test"
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "android/content/SharedPreferences.java": '''package android.content;
public interface SharedPreferences {
 float getFloat(String key,float def); int getInt(String key,int def); boolean getBoolean(String key,boolean def);
 Editor edit(); interface Editor {
  Editor putFloat(String key,float value); Editor putInt(String key,int value); Editor putBoolean(String key,boolean value); void apply();
 }
}''',
        "android/content/Context.java": '''package android.content;
public class Context {
 public static final int MODE_PRIVATE=0;
 public final java.util.Map<String,Object> values=new java.util.HashMap<>();
 public SharedPreferences getSharedPreferences(String name,int mode) {
  return new SharedPreferences() {
   public float getFloat(String key,float def) {return ((Number)values.getOrDefault(key,def)).floatValue();}
   public int getInt(String key,int def) {return ((Number)values.getOrDefault(key,def)).intValue();}
   public boolean getBoolean(String key,boolean def) {return (Boolean)values.getOrDefault(key,def);}
   public Editor edit() {return new Editor() {
    public Editor putFloat(String key,float value) {values.put(key,value);return this;}
    public Editor putInt(String key,int value) {values.put(key,value);return this;}
    public Editor putBoolean(String key,boolean value) {values.put(key,value);return this;}
    public void apply() {}
   };}
  };
 }
}''',
        "android/util/Log.java": '''package android.util;
public class Log {public static int w(String tag,String message) {throw new AssertionError(message);}}
''',
        "org/thevoid/port/GameActivity.java": '''package org.thevoid.port;
import java.io.*;
class GameActivity {static String[] nativeHintTexts() {return new String[56];} static class Release {
 static String read(File file) {try {return new String(java.nio.file.Files.readAllBytes(file.toPath()),"UTF-8");}
  catch(IOException e) {return "";}}
 static String attribute(String text,String key) {return "";}
}}
class Keys {static int forName(String name) {return 0;}}
''',
        "org/thevoid/port/FixedProfileProbe.java": r'''package org.thevoid.port;
import java.io.*; import java.nio.file.*; import java.util.*;
public class FixedProfileProbe {
 public static void main(String[] args) throws Exception {
  android.content.Context context=new android.content.Context();
  context.values.put("hdr",0);context.values.put("lightmapQuality",2);
  context.values.put("renderScale",0.7f);context.values.put("textureQuality",1);context.values.put("anisotropy",4);
  Settings settings=new Settings(context);
  assert settings.hdr==0 && settings.lightmapQuality==2;
  File root=new File(args[0]), xml=new File(root,"settings.xml");
  String old="<Settings><prop name=\"PortHDR\" value=\"0\" /><prop name=\"PortLightmapQuality\" value=\"2\" />"
   +"<prop name=\"Shadows\" value=\"0\" /><prop name=\"PortTextureQuality\" value=\"1\" />"
   +"<prop name=\"PortRenderScale\" value=\"80\" /><prop name=\"PortAnisotropy\" value=\"8\" />"
   +"<prop name=\"unrelated\" value=\"keep\" /></Settings>";
  Files.write(xml.toPath(),old.getBytes("UTF-8"));
  settings.loadFromGame(xml);
  assert settings.hdr==0 && settings.lightmapQuality==2 && settings.textureQuality==1;
  assert settings.renderScale==0.8f && settings.anisotropy==8;
  for(int hdr=0;hdr<3;++hdr) for(int light=0;light<3;++light) {
   settings.hdr=hdr; settings.lightmapQuality=light;
   Profile.setProps(xml,settings.gameProps());
   String persisted=GameActivity.Release.read(xml);
   assert Profile.prop(persisted,"PortHDR").equals(Integer.toString(hdr));
   assert Profile.prop(persisted,"PortLightmapQuality").equals(Integer.toString(light));
   assert Profile.prop(persisted,"Shadows").equals("0") && Profile.prop(persisted,"unrelated").equals("keep");
   assert !settings.gameProps().containsKey("Shadows");
   settings.save();
   assert context.values.get("hdr").equals(hdr) && context.values.get("lightmapQuality").equals(light);
   Settings restored=new Settings(context); restored.loadFromGame(xml);
   assert restored.hdr==hdr && restored.lightmapQuality==light;
   Profile.writeRenderer(root,1280,720,restored);
   String renderer=GameActivity.Release.read(new File(root,"rcfg.xml"));
   String strategy=hdr==0 ? "fx_3_0" : hdr==1 ? "fx_3_0hs" : "fx_3_0hf";
   assert renderer.contains("<Profile force=\""+strategy+"\" />");
   assert renderer.contains("<HDR")== (hdr!=0);
   assert renderer.contains("simple=\"1\"")== (hdr==1);
   assert renderer.contains("<LightmapQuality>"+light+"</LightmapQuality>");
   assert renderer.contains("<TextureQuality>1</TextureQuality>") && renderer.contains("<Anisotropy>8</Anisotropy>");
  }
  context.values.put("hdr",-5);context.values.put("lightmapQuality",99);
  Settings bounded=new Settings(context);assert bounded.hdr==0 && bounded.lightmapQuality==2;
  System.out.println("PASS all 9 HDR/lighting choices persist; HDR off/simple/full force original SM3 strategies; shadows and unrelated values preserved");
 }
}''',
    }
    sources = []
    for name, data in files.items():
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="utf-8")
        sources.append(path)
    port = ROOT / "android/app/src/org/thevoid/port"
    sources += [port / "Settings.java", port / "Profile.java"]
    subprocess.run([str(JAVA_HOME / "bin/javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(out), *map(str, sources)], check=True)
    with tempfile.TemporaryDirectory(prefix="profile-", dir=out) as fixture:
        subprocess.run([str(JAVA_HOME / "bin/java.exe"), "-ea", "-cp", str(out), "org.thevoid.port.FixedProfileProbe", fixture], check=True)
    activity = (port / "GameActivity.java").read_text(encoding="utf-8")
    assert "fixedGraphics" not in activity
    assert '!release.library.equals("void_tension") && overrides.contains("Scripts\\\\ui\\\\main_menu.bin")' in activity
    controls = (port / "Controls.java").read_text(encoding="utf-8")
    assert "choice(Settings.T_HDR" in controls and "choice(Settings.T_LIGHTING" in controls


if __name__ == "__main__":
    video_menu()
    migration()
