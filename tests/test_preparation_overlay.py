"""Exercise the real game-style progress drawing and menu/input readiness on the JVM."""
import os
from pathlib import Path
import subprocess

from test_touch_controls import method

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/preparation-overlay-test"
JAVA = Path(os.environ.get("JAVA_HOME", "")) / "bin"
activity = (ROOT / "android/app/src/org/thevoid/port/GameActivity.java").read_text(encoding="utf-8")
cache = (ROOT / "android/app/src/org/thevoid/port/ShaderCache.java").read_text(encoding="utf-8")
stubs = {
    "android/R.java": "package android; public class R { public static class style { public static final int Theme_Material_Dialog_Alert=1; } }",
    "android/content/res/ColorStateList.java": "package android.content.res; public class ColorStateList { public static ColorStateList valueOf(int v){return new ColorStateList();} }",
    "android/content/res/Resources.java": "package android.content.res; public class Resources { public static class Metrics {public float density=1.5f;} public Metrics getDisplayMetrics(){return new Metrics();} }",
    "android/graphics/Color.java": "package android.graphics; public class Color {public static final int TRANSPARENT=0;}",
    "android/graphics/drawable/GradientDrawable.java": "package android.graphics.drawable; public class GradientDrawable {public enum Orientation {TOP_BOTTOM} public GradientDrawable(Orientation v,int[] c){assert c.length==2;} public void setStroke(int width,int colour){assert width>0;} }",
    "android/graphics/drawable/ColorDrawable.java": "package android.graphics.drawable; public class ColorDrawable {public ColorDrawable(int colour){} }",
    "android/graphics/drawable/RippleDrawable.java": "package android.graphics.drawable; public class RippleDrawable {public RippleDrawable(android.content.res.ColorStateList c,ColorDrawable d,Object mask){} }",
    "android/widget/LinearLayout.java": """package android.widget; public class LinearLayout extends android.view.View {
        public static final int VERTICAL=1; public java.util.List<android.view.View> children=new java.util.ArrayList<>();
        public LinearLayout(Object c){super(null);} public void setOrientation(int v){assert v==VERTICAL;}
        public void setPadding(int a,int b,int c,int d){assert a>0&&b>0&&c>0&&d>0;} public void addView(android.view.View v){children.add(v);}
    }""",
    "android/widget/TextView.java": """package android.widget; public class TextView extends android.view.View {
        public CharSequence text; public TextView(Object c){super(null);} public void setTypeface(android.graphics.Typeface t){}
        public void setTextColor(int v){} public void setTextSize(float v){} public void setText(CharSequence v){text=v;}
        public void setPadding(int a,int b,int c,int d){}
    }""",
    "android/widget/Button.java": """package android.widget; public class Button extends TextView {
        public Runnable click; public Button(){super(null);} public void setAllCaps(boolean v){assert !v;}
        public void setBackground(android.graphics.drawable.RippleDrawable d){}
    }""",
    "android/view/Window.java": """package android.view; public class Window {
        final View decor=new View(null); public void setBackgroundDrawable(android.graphics.drawable.GradientDrawable d){}
        public View getDecorView(){return decor;}
    }""",
    "android/app/AlertDialog.java": """package android.app;
    public class AlertDialog {
        public static final int BUTTON_POSITIVE=-1,BUTTON_NEGATIVE=-2; public boolean shown,cancelable; public android.widget.LinearLayout content;
        final android.view.Window window=new android.view.Window();
        final android.widget.Button positive=new android.widget.Button(),negative=new android.widget.Button();
        public void show(){shown=true;} public android.view.Window getWindow(){return window;}
        public android.widget.Button getButton(int which){assert shown;return which==BUTTON_POSITIVE?positive:negative;}
        public interface Listener {void onClick(AlertDialog dialog,int which);}
        public static class Builder {
            final AlertDialog dialog=new AlertDialog(); public Builder(Object context,int theme){assert theme==1;}
            public Builder setView(android.widget.LinearLayout view){dialog.content=view;return this;}
            public Builder setCancelable(boolean v){dialog.cancelable=v;return this;}
            public Builder setPositiveButton(String label,Listener callback){dialog.positive.text=label;dialog.positive.click=()->callback.onClick(dialog,-1);return this;}
            public Builder setNegativeButton(String label,Listener callback){dialog.negative.text=label;dialog.negative.click=()->callback.onClick(dialog,-2);return this;}
            public AlertDialog create(){return dialog;}
        }
    }""",
    "android/content/Context.java": "package android.content; public class Context { }",
    "android/os/SystemClock.java": "package android.os; public class SystemClock { public static long now; public static long uptimeMillis(){return now;} public static long elapsedRealtime(){return now;} }",
    "android/graphics/Shader.java": "package android.graphics; public class Shader { public enum TileMode {CLAMP} }",
    "android/graphics/LinearGradient.java": "package android.graphics; public class LinearGradient extends Shader { public LinearGradient(float a,float b,float c,float d,int[] e,float[] f,TileMode g){} }",
    "android/graphics/Typeface.java": "package android.graphics; public class Typeface { public static final int NORMAL=0; public static Typeface create(String family,int style){assert family.equals(\"serif\");return new Typeface();} }",
    "android/graphics/Paint.java": """package android.graphics;
public class Paint {
    public static final int ANTI_ALIAS_FLAG=1; public enum Style{FILL} public enum Align{CENTER}
    public float size; public int colour; public Paint(int flags){} public void setTypeface(Typeface t){}
    public void setShader(Shader s){} public void setStyle(Style s){} public void setTextAlign(Align a){}
    public void setStrokeWidth(float v){} public void setColor(int v){colour=v;} public void setTextSize(float v){size=v;}
    public float measureText(String s){return size*s.length()*.55f;}
}""",
    "android/graphics/Canvas.java": """package android.graphics;
import java.util.*;
public class Canvas {
    public final List<String> text=new ArrayList<>(); public final List<float[]> lines=new ArrayList<>();
    public float width,height;
    public Canvas(float w,float h){width=w;height=h;}
    void point(float x,float y){assert x>=0&&x<=width&&y>=0&&y<=height:x+\",\"+y;}
    public void drawRect(float a,float b,float c,float d,Paint p){point(a,b);point(c,d);}
    public void drawText(String s,float x,float y,Paint p){point(x-p.measureText(s)/2,y);point(x+p.measureText(s)/2,y);text.add(s);}
    public void drawLine(float a,float b,float c,float d,Paint p){point(a,b);point(c,d);lines.add(new float[]{a,b,c,d});}
}""",
    "android/view/View.java": """package android.view;
public class View {
    public static final int IMPORTANT_FOR_ACCESSIBILITY_YES=1,VISIBLE=0,GONE=8;
    public int width=2400,height=1080,visibility=VISIBLE; public boolean clickable; public CharSequence description;
    public View(android.content.Context c){} public void setImportantForAccessibility(int v){assert v==1;}
    public void setClickable(boolean v){clickable=v;} public void setContentDescription(CharSequence v){description=v;}
    public void setSystemUiVisibility(int flags){} public int getSystemUiVisibility(){return 8192;}
    public void invalidate(){} public int getWidth(){return width;} public int getHeight(){return height;}
    public void setVisibility(int v){visibility=v;} public int getVisibility(){return visibility;}
    public void postDelayed(Runnable r,long delay){assert delay>=200;} protected void onDraw(android.graphics.Canvas c){}
}""",
}
stubs["android/util/Log.java"] = """package android.util;
public class Log {
    public static int warnings;
    public static int w(String tag, String text) { ++warnings; return 0; }
    public static int i(String tag, String text) { return 0; }
}"""
probe = """package org.thevoid.port;
import android.view.View;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.app.AlertDialog;
public class PreparationOverlayProbe {
    static class ShaderCache {
""" + method(cache, "static final class NativeWork") + """
    }
    static class Controls {
        int pauses,resumes; void pause(){++pauses;} void resume(){++resumes;}
    }
    static class NativeLibrary { static long[] unpacked; static long[] progress(){return unpacked;} }
    final PreparationOverlay preparationPanel=new PreparationOverlay(new android.content.Context());
    final ShaderCache.NativeWork nativePreparation=new ShaderCache.NativeWork();
    final Controls controls=new Controls();
    final Runnable preparationTick=()->{};
    int preparationPhase=3,cacheCompleted,cacheTotal;
    boolean preparationFailed,startupReady,resumed=true,started=true;
    long reportedMissingShader; boolean preparationBlocking=true;
    android.content.res.Resources getResources(){return new android.content.res.Resources();}
    android.view.Window getWindow(){return new android.view.Window();}
    static long hud,progress,warmup,missing;
    static long nativeHudState(){return hud;} static long nativeShaderProgress(){return progress;}
    static long nativeShaderWarmup(){return warmup;} static long nativeMissingShader(){return missing;}
    boolean isFinishing(){return false;} boolean isDestroyed(){return false;}
    static String startupText(String en,String ru,String de,String pl){return en;}
""" + method(activity, "private void updatePreparation()") + method(activity, "private void setPreparationVisible(") + method(activity, "private AlertDialog showPreparationDialog(") + """
    public static void main(String[] args){
        PreparationOverlay overlay=new PreparationOverlay(new android.content.Context());
        assert overlay.clickable:"the startup overlay holds the screen";
        assert overlay.clickable;
        for(int[] size:new int[][]{{2424,1080},{800,360},{1080,1080},{360,800}}){
            overlay.width=size[0];overlay.height=size[1];
            for(int done:new int[]{-10,0,25,100,999}){
                overlay.update("Подготовка графики в главном меню / Vorbereitung im Hauptmenü", "25%",done,100);
                Canvas c=new Canvas(size[0],size[1]);overlay.onDraw(c);
                assert c.text.size()==1&&overlay.description.toString().contains("25%");
                float[] full=c.lines.get(0),filled=c.lines.get(1);
                assert full[2]-full[0]<=size[0]*.46f:"compact progress width";
                float ratio=Math.max(0,Math.min(100,done))/100f;
                assert Math.abs(filled[2]-(full[0]+(full[2]-full[0])*ratio))<.01;
            }
            for(int now:new int[]{0,300,1200,2300}){
                android.os.SystemClock.now=now;overlay.update("Preparing graphics","Please wait",0,0);
                overlay.onDraw(new Canvas(size[0],size[1]));
            }
        }
        PreparationOverlayProbe p=new PreparationOverlayProbe();
        android.os.SystemClock.now=10000;hud=(100L<<32)|0x100000;warmup=0;
        p.updatePreparation();assert p.startupReady&&p.preparationPanel.getVisibility()==View.VISIBLE;
        warmup=(100L<<32)|25;p.updatePreparation();
        assert p.preparationPanel.description.toString().contains("25%");
        warmup=(100L<<32)|100;p.updatePreparation();
        assert p.preparationPanel.getVisibility()==View.GONE&&p.controls.resumes==1;
        p.updatePreparation();assert p.controls.resumes==1:"no duplicate resume";
        warmup=(200L<<32)|100;p.updatePreparation();
        assert p.preparationPanel.getVisibility()==View.VISIBLE&&p.controls.pauses==0&&!p.preparationPanel.clickable;
        p.resumed=false;warmup=(200L<<32)|200;p.updatePreparation();assert p.controls.resumes==1;
        // In play the badge only informs: the controls stay and touches pass through it.
        int pauses=p.controls.pauses,resumes=p.controls.resumes;
        p.resumed=true;p.setPreparationVisible(true,false);
        assert p.preparationPanel.getVisibility()==View.VISIBLE&&!p.preparationPanel.clickable&&p.controls.pauses==pauses;
        p.setPreparationVisible(false,false);assert p.controls.resumes==resumes:"a badge never paused, so nothing resumes";
        p.setPreparationVisible(true,true);assert p.preparationPanel.clickable&&p.controls.pauses==pauses+1;
        p.setPreparationVisible(false,true);assert p.controls.resumes==resumes+1;
        p.preparationPhase=1;p.cacheCompleted=3;p.cacheTotal=4;p.updatePreparation();
        assert p.preparationPanel.description.toString().contains("75%");
        p.preparationPhase=0;p.updatePreparation();assert p.preparationPanel.description.toString().contains("game files");
        // The first start of a build unpacks the game's code: named, with its share.
        NativeLibrary.unpacked=new long[]{81,324};p.updatePreparation();
        assert p.preparationPanel.description.toString().contains("Unpacking the game's code")
            &&p.preparationPanel.description.toString().contains("25%"):p.preparationPanel.description;
        NativeLibrary.unpacked=null;p.updatePreparation();assert p.preparationPanel.description.toString().contains("game files");
        p=new PreparationOverlayProbe();hud=100L<<32;warmup=0;missing=0;
        android.os.SystemClock.now=20000;p.updatePreparation();
        android.os.SystemClock.now=20200;hud=101L<<32;p.updatePreparation();
        android.os.SystemClock.now=20800;hud=102L<<32;p.updatePreparation();
        assert p.startupReady&&p.preparationPanel.getVisibility()==View.GONE:"direct load can skip main menu";
        android.os.SystemClock.now=21000;hud=(103L<<32)|0x2000;p.updatePreparation();
        assert p.preparationPanel.getVisibility()==View.GONE:"a direct-load pause menu must not wait for main-menu warmup";
        PreparationOverlayProbe loading=new PreparationOverlayProbe();
        android.os.SystemClock.now=30000;hud=(200L<<32)|0x100000;warmup=(100L<<32)|100;progress=25L<<32;loading.updatePreparation();
        android.os.SystemClock.now=30200;hud=201L<<32;progress=(25L<<32)|10;loading.updatePreparation();
        android.os.SystemClock.now=31200;progress=(25L<<32)|20;loading.updatePreparation();
        android.os.SystemClock.now=32400;progress=(25L<<32)|30;loading.updatePreparation();
        assert loading.preparationPanel.getVisibility()==View.GONE:"cached shader replies during long scene loading are not new GPU preparation";
        android.os.SystemClock.now=32600;progress=(26L<<32)|30;loading.updatePreparation();
        assert loading.preparationPanel.getVisibility()==View.VISIBLE:"real new GPU work still shows stalled preparation";
        android.os.SystemClock.now=32800;hud=202L<<32;loading.updatePreparation();
        android.os.SystemClock.now=33400;hud=203L<<32;loading.updatePreparation();
        assert loading.preparationPanel.getVisibility()==View.GONE:"real GPU work dismisses after frames recover";
        progress=0;warmup=0;
        // A shader the cache lacks is noted once; play is never stopped for it (no dialog, no pause).
        pauses=p.controls.pauses;
        missing=44;android.os.SystemClock.now=22000;p.updatePreparation();assert p.reportedMissingShader==44;
        android.os.SystemClock.now=22600;p.updatePreparation();assert android.util.Log.warnings==1;
        missing=45;android.os.SystemClock.now=24800;p.updatePreparation();
        assert p.reportedMissingShader==45&&android.util.Log.warnings==2&&p.controls.pauses==pauses;
        final int[] actions={0,0};
        AlertDialog dialog=p.showPreparationDialog("Ошибка подготовки","Описание","Повторить",()->++actions[0],"Назад",()->++actions[1]);
        assert dialog.shown&&!dialog.cancelable&&dialog.content.children.size()==2;
        assert ((TextView)dialog.content.children.get(0)).text.equals("Ошибка подготовки");
        assert ((TextView)dialog.content.children.get(1)).text.equals("Описание");
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).click.run();assert actions[0]==1&&actions[1]==0;
        dialog.getButton(AlertDialog.BUTTON_NEGATIVE).click.run();assert actions[0]==1&&actions[1]==1;
        assert p.showPreparationDialog("Failed","","Retry",()->{},"Back",()->{}).content.children.size()==1;
        System.out.println("PASS: real ivory/serif overlay draws within all viewports, clamps progress, remains accessible; menu warmup waits, updates, unlocks once and respects pause/failure");
    }
}
"""
stubs["org/thevoid/port/PreparationOverlayProbe.java"] = probe
sources = []
for name, content in stubs.items():
    path = OUT / "src" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    sources.append(path)
sources.append(ROOT / "android/app/src/org/thevoid/port/PreparationOverlay.java")
subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(OUT), *map(str, sources)], check=True)
subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(OUT), "org.thevoid.port.PreparationOverlayProbe"], check=True)
