"""Run the actual mobile button rules and body overlay drawing on the JVM."""
import os
from pathlib import Path
import subprocess

from test_touch_controls import method

ROOT = Path(__file__).resolve().parents[1]
JAVA = Path(os.environ.get("JAVA_HOME", "")) / "bin"
OUT = ROOT / "build/mobile-hud-test"
OUT.mkdir(parents=True, exist_ok=True)
source = (ROOT / "android/app/src/org/thevoid/port/Controls.java").read_text(encoding="utf-8")
constants = source[source.index("    private static final int HUD_CURSOR"):source.index("    private static final String[] SCREEN_NAMES")]
buttons = OUT / "MobileButtonsProbe.java"
buttons.write_text('''public class MobileButtonsProbe {
    static class GameActivity { static int brush = -1; static int nativeBrushColour() { return brush; } }
    static final int WORLD = 0, UI = 1, PAINT = 2;
    static class View { boolean shown, dim; void setDim(boolean on) { dim = on; } }
    static class Settings { boolean showMenuButton = true, showActionButton, showBodyButton = true, touchAdaptations = true; }
    static class Picker { boolean fan; void setFan(boolean on) { fan = on; } }
    static class Touch { boolean stickShown, bodyStatsHeld; void invalidate() { } }
    final Settings settings = new Settings(); final Picker picker = new Picker(); final Touch touch = new Touch();
    final View menuB = new View(), bodyB = new View(), journalB = new View(), mapB = new View(),
        jumpB = new View(), skipB = new View(), useB = new View(), locateB = new View(), paintB = new View(),
        slowB = new View(), fastB = new View(), bodyBackB = new View(), gamepadHelp = new View();
    final View[] buttons = {menuB, bodyB, journalB, mapB, jumpB, skipB, useB, locateB, paintB, slowB, fastB, bodyBackB};
    boolean paintMode, padActive, nativeMenu = true, videoSkipVisible, heroKnown;
    int screen = -1, hud, mode = WORLD; boolean menuSeen; Runnable fanShow;
    void removeCallbacks(Runnable r) { }
    void show(View view, boolean on) { view.shown = on; }
    boolean shown(int mask, long age) { return (hud & mask) != 0; }
''' + constants + method(source, "private void updateButtons()") + method(source, "private int screen()") + '''
    public static void main(String[] args) {
        MobileButtonsProbe p = new MobileButtonsProbe();
        // No screen seen yet (the layer has just come up): no button at all.
        p.updateButtons();
        for (View button : p.buttons) assert !button.shown;
        assert p.screen() == S_INTRO;
        GameActivity.brush = 2; assert p.screen() == S_WORLD && p.menuSeen;
        GameActivity.brush = -1; p.menuSeen = false; p.hud = HUD_MAP3D;
        assert p.screen() == S_MAP && p.menuSeen;
        p.hud = 0;
        p.screen = S_WORLD; p.updateButtons();
        assert p.menuB.shown && p.jumpB.shown && p.bodyB.shown && !p.useB.shown && !p.journalB.shown;
        p.settings.showMenuButton = false; p.settings.showActionButton = true; p.updateButtons();
        assert !p.menuB.shown && p.useB.shown;
        p.settings.showMenuButton = true;
        p.settings.showBodyButton = false; p.updateButtons(); assert !p.bodyB.shown;
        p.screen = S_MAP; p.updateButtons(); assert !p.bodyB.shown;
        p.settings.showBodyButton = true; p.updateButtons(); assert p.bodyB.shown;
        // A line the hero says as he walks leaves him every button.
        p.screen = S_SCENE; p.hud = HUD_SUBTITLE; p.updateButtons();
        assert p.jumpB.shown && p.bodyB.shown && p.useB.shown && p.paintB.shown;
        // A brother's talk or coming locks the controls: no jump, heart, hand or brush; the menu stays.
        p.hud |= HUD_CONTROL_LOCKED; p.updateButtons();
        assert !p.jumpB.shown && !p.bodyB.shown && !p.useB.shown && !p.paintB.shown && p.menuB.shown;
        p.screen = S_WORLD; p.hud = HUD_CONTROL_LOCKED; p.updateButtons();
        assert !p.jumpB.shown && !p.paintB.shown && p.menuB.shown;
        // A Sister speaking in her obscura: neither the menu nor the brush; silent, both again.
        p.screen = S_OBSCURA; p.hud = HUD_OBSCURA | HUD_SUBTITLE | HUD_CONTROL_LOCKED; p.updateButtons();
        assert !p.menuB.shown && !p.paintB.shown && !p.jumpB.shown;
        p.hud = HUD_OBSCURA | HUD_CURSOR | HUD_CONTROL_LOCKED | HUD_BACK; p.updateButtons();
        assert p.menuB.shown && p.paintB.shown;
        p.hud = 0;
        for (int screen = S_WORLD; screen <= S_VIDEO; ++screen) {
            p.screen = screen; p.updateButtons();
            assert p.journalB.shown == (screen == S_BODY) : screen;
        }
        p.screen = S_BODY; p.updateButtons(); assert p.menuB.shown && p.journalB.shown && p.bodyBackB.shown;
        p.screen = S_VIDEO; p.hud = HUD_VIDEO | HUD_JOURNAL | HUD_JOURNAL_VIDEO; p.videoSkipVisible = true;
        p.updateButtons(); for (View button : p.buttons) assert !button.shown;
        assert p.screen() == S_VIDEO;
        p.screen = S_MAP; p.heroKnown = true; p.updateButtons();
        assert p.locateB.shown && p.slowB.shown && p.fastB.shown && !p.jumpB.shown;
        p.screen = S_WORLD; p.padActive = true; p.updateButtons();
        for (View button : p.buttons) assert !button.shown;
        p.padActive = false; p.paintMode = true; p.picker.fan = true; p.updateButtons(); assert p.picker.fan;
        p.settings.touchAdaptations = false; p.updateButtons(); assert !p.picker.fan;
        System.out.println("mobile buttons: none before a screen, defaults, switches (the hearts too), locked scenes, a Sister speaking, body-only guide, map, controller PASS");
    }
}
''', encoding="utf-8")
subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(OUT), str(buttons)], check=True)
subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(OUT), "MobileButtonsProbe"], check=True)

methods = "\n".join(method(source, declaration) for declaration in (
    "private String amount(", "private void bodyCard(", "private void bodyLine(",
    "private void layoutStats()", "private void drawBodyDetails(", "private void bar(", "private void drawHeartGuide(",
    "private void drawHeartCard(", "private void drawHandDrop(", "private void sideCards(", "private void sideCard(",
    "private void drawZoneLabels(", "private boolean heartShown("))
fields = source[source.index("        private final String[] statLines"):source.index("        private void layoutStats()")]
hand = source[source.index("        private static final int HAND_NONE"):source.index("        private float handSource()")]
labels = source[source.index("        /* The heart labels as drawn"):source.index("        private Bitmap bodyGlyph(")]
overlay = OUT / "BodyOverlayProbe.java"
overlay.write_text(r''' import java.util.*;
public class BodyOverlayProbe {
    static class Settings {
        float textSize = 1; boolean textContrast = true;
        static String gameLanguage = "english";
        static final int T_COLOUR_FIRST=0,T_HEART=7,T_PALETTE=8,T_MEMORY=9,T_TAP_PUT=10,T_TAP_RETURN=11,T_IN_HAND=12;
        static String gameText(int id) { return new String[] {"Silver","Purple","Amber","Azure","Lilac","Emerald","Gold","Heart","Palette","Memory","Tap - put","Tap - return","in hand"}[id]; }
    }
    static class SystemClock { static long now=550; static long uptimeMillis() { return now; } }
    static class Color { static final int WHITE=-1, BLACK=0xff000000; static int argb(int a,int r,int g,int b) { return a<<24|r<<16|g<<8|b; } }
    static class Paint {
        static class Style { static final int FILL=0,STROKE=1; }
        static class Align { static final int LEFT=0,CENTER=1; }
        static class Cap { static final int BUTT=0,ROUND=1; }
        int colour,align,style; float textSize=16; static int measures;
        void setStyle(int v) { style=v; } void setColor(int v) { colour=v; } void setStrokeWidth(float v) {}
        void setStrokeCap(int v) {} void setTextAlign(int v) { align=v; }
        void setTextSize(float v) { textSize=v; } float getTextSize() { return textSize; }
        float measureText(String text) { ++measures; return textSize*text.length()*.5f; }
        void setShadowLayer(float r,float x,float y,int c) {} void clearShadowLayer() {}
        static class FontMetrics { float ascent,descent; }
        FontMetrics getFontMetrics() { FontMetrics m=new FontMetrics(); m.ascent=-textSize*.8f; m.descent=textSize*.2f; return m; }
    }
    static class Bitmap { final int zone; Bitmap(int zone) { this.zone=zone; } }
    static class PalettePicker { static final int COLOURS=7; }
    static class android { static class util { static class Log { static void i(String t,String m) { } } } }
    static class Input { static final int LEFT=0,RIGHT=1; }
    static class GameActivity {
        static int requests; static boolean accept=true; static String command;
        static boolean nativeConsoleCommand(String text) { ++requests; command=text; return accept; }
    }
    static class Haptics { int ticks; void tick() { ++ticks; } }
    final Haptics haptics=new Haptics();
    final ArrayDeque<Runnable> later=new ArrayDeque<>();
    void postDelayed(Runnable r,long ms) { later.add(r); } void removeCallbacks(Runnable r) { later.remove(r); }
    void runLater() { for (int n=0;n<50&&!later.isEmpty();++n) later.poll().run(); }
    static final int S_BODY=3; int screen=S_BODY,cleared; boolean holding=true;
    boolean handHolds() { return holding; } void clearHand() { ++cleared; handFrom=HAND_NONE; holding=false; }
    void invalidate() {}
    static class RectF {
        float left,top,right,bottom;
        RectF() {} RectF(float l,float t,float r,float b) { set(l,t,r,b); }
        void set(float l,float t,float r,float b) { left=l;top=t;right=r;bottom=b; }
    }
    class Picker {
        boolean memory; Picker(boolean memory) { this.memory=memory; }
        int colour(int i) { return 0xffcccc00+i; }
        boolean dotShown(int i) { return true; } float dotY(int i) { return getHeight()*(.15f+.1f*i); }
        float dotX(int i) { return memory ? getWidth()-dp(34) : dp(34); } float dotRadius() { return dp(19); }
    }
    static class Canvas {
        final List<float[]> cards=new ArrayList<>(); final List<String> texts=new ArrayList<>(); int lines,glyph=-1;
        void drawRoundRect(float l,float t,float r,float b,float rx,float ry,Paint p) { if (p.style==Paint.Style.FILL) cards.add(new float[]{l,t,r,b}); }
        final List<float[]> rects=new ArrayList<>(); final List<Integer> rectColours=new ArrayList<>();
        void drawRect(float l,float t,float r,float b,Paint p) { rects.add(new float[]{l,t,r,b}); rectColours.add(p.colour); }
        final List<float[]> circles=new ArrayList<>();
        void drawCircle(float x,float y,float r,Paint p) { circles.add(new float[]{x,y,r}); }
        /* The one bar drawn: [whole, held, lighter] lengths over the whole one. */
        float[] bar(int rgb) {
            float whole=0,held=0,more=0,end=-1,start=-2;
            for (int i=0;i<rects.size();++i) {
                float[] r=rects.get(i); int col=rectColours.get(i);
                if (col==Color.argb(100,255,255,255)) whole=r[2]-r[0];
                else if (col==rgb) { held=r[2]-r[0]; end=r[2]; }
                else if (col==((rgb&0xffffff)|0x90000000)) { more=r[2]-r[0]; start=r[0]; }
            }
            assert more==0 || Math.abs(start-end)<.001f : "the lighter part follows the held one";
            return new float[]{held/whole, more/whole};
        }
        void drawLine(float x,float y,float xx,float yy,Paint p) { ++lines; }
        void drawBitmap(Bitmap image,Object source,RectF dest,Paint p) { glyph=image.zone; }
        void save() {} void restore() {} void clipRect(float l,float t,float r,float b) {}
        void drawText(String text,float x,float y,Paint p) { texts.add(text); }
        void check(float width,float height) {
            for (float[] r:cards) assert r[0]>=0 && r[1]>=0 && r[2]<=width && r[3]<=height : Arrays.toString(r);
        }
    }
    final Settings settings=new Settings(); final Paint paint=new Paint();
    final Picker picker=new Picker(false),memoryPicker=new Picker(true);
    final float[] bodyDetails={2,12.01f,99.02f,3.2f,21,1,2,3,4,5,6,7,4,17.2f};
    final float[] bodyAmounts=new float[28];
    final String[] bodyStatNames={"stat0","stat1","stat2","stat3","stat4","stat5","stat6"};
    boolean bodyStatsHeld,bodyTransferHeld,lymphHearts,twoFinger,heartTicked=true,depositHint,dragging;
    int dragButton;
    long guideUntil;
    final float[] zoneLabels=new float[21*5]; int zoneLabelCount, renderW=1346, renderH=600;
    int bodyTarget=8,uiId=1; float uiDownX=500,uiDownY=900,guideX,guideY,heartCardTop=-1,heartCardBottom=-1;
    int width,height; float density,bodyTextWidth,bodyTextRight;
    int getWidth() { return width; } int getHeight() { return height; } float dp(float v) { return v*density; }
    Bitmap bodyGlyph(int zone) { return new Bitmap(zone); }
''' + fields + hand + labels + methods + r'''
    public static void main(String[] args) {
        for (float[] screen:new float[][]{{1920,1080,3},{800,360,1},{2400,1080,3}}) {
            for (float scale:new float[]{1,1.5f}) {
                BodyOverlayProbe p=new BodyOverlayProbe(); p.width=(int)screen[0];p.height=(int)screen[1];p.density=screen[2];p.settings.textSize=scale;
                p.bodyAmounts[4]=30;p.bodyAmounts[5]=140;p.bodyAmounts[18]=32;p.bodyAmounts[19]=140;
                p.bodyStatsHeld=true;Canvas c=new Canvas();p.drawBodyDetails(c);c.check(p.width,p.height);
                assert c.texts.size()==8 && c.texts.get(0).contains("4 / 21");
                p.bodyStatsHeld=false;p.uiDownY=p.height*.8f;c=new Canvas();p.drawBodyDetails(c);c.check(p.width,p.height);
                assert c.cards.size()==2 && c.glyph==4 && c.texts.contains("♡  13 / 100");
                assert c.texts.stream().noneMatch(t->t.startsWith("Palette"));
                c=new Canvas();p.drawHeartGuide(c,2);assert c.lines==6 : "2009 has only right arrows";
                p.lymphHearts=true;c=new Canvas();p.drawBodyDetails(c);c.check(p.width,p.height);
                assert c.cards.size()==3 && c.texts.contains("↳  18");
                c=new Canvas();p.drawHeartGuide(c,2);assert c.lines==12 : "2008 exposes both original sources";
                p.uiId=-1;p.bodyTarget=-1;p.handFrom=p.HAND_MEMORY;p.handColour=2;p.handTaken=12;p.handPeak=44;p.handDrawing=false;
                c=new Canvas();p.drawBodyDetails(c);c.check(p.width,p.height);
                assert c.cards.size()==1 && !c.texts.contains("+12") : "Memory release hides the central hint";
                assert c.texts.contains("Amber → 12") && !c.texts.contains("↩");
                assert p.memoryCard.left > p.width/2 && p.memoryCardAction==p.CARD_NONE : "the Memory's card, by its drop";
                // What the Memory holds and, lighter, what it would hold with the hand's colour back (as a heart's colour shows there).
                assert c.texts.contains("32 → 44 / 140") : "the Memory's amount with the colour taken back";
                float[] bar=c.bar(p.picker.colour(2));
                assert Math.abs(bar[0]-32f/140)<.001f && Math.abs(bar[1]-12f/140)<.001f : Arrays.toString(bar);
                p.handDrawing=true;c=new Canvas();p.drawBodyDetails(c);c.check(p.width,p.height);
                assert !c.texts.contains("+12") && c.texts.contains("Amber → 12") : "Memory amount stays in its card";
                assert p.memoryCard.left > p.width/2 && c.texts.contains("32 → 44 / 140") : "while drawing too";
                bar=c.bar(p.picker.colour(2)); assert Math.abs(bar[1]-12f/140)<.001f;
                // The hearts that can take it: a number above each, backed, kept on the screen.
                float[] labels={0,673,300,9,25, 1,1330,1,0,75};   // the second's heart by the top right corner
                System.arraycopy(labels,0,p.zoneLabels,0,labels.length); p.zoneLabelCount=2;
                c=new Canvas();p.drawBodyDetails(c);c.check(p.width,p.height);
                assert c.texts.contains("9 / 25") && c.texts.contains("0 / 75") && c.cards.size()==3;
                assert c.circles.size()==2 : "each eligible heart has a transfer circle";
                float[] centre=c.cards.get(0);
                // A tap on a label puts the hand's colour into its heart: where the game's hit test says that heart is.
                assert p.labelsDrawn==2 && p.labelAt((centre[0]+centre[2])/2,(centre[1]+centre[3])/2)==0 && p.labelAt(5,p.height-5)<0;
                for (int i=0;i<2;++i) {
                    float[] ring=c.circles.get(i);
                    assert p.labelAt(ring[0],ring[1])==i : "a tap on the circle targets its heart";
                    assert ring[0]-ring[2]>=0 && ring[0]+ring[2]<=p.width && ring[1]-ring[2]>=0 && ring[1]+ring[2]<=p.height;
                }
                p.labelCircles[2]=p.labelCircles[0]+p.dp(20);p.labelCircles[3]=p.labelCircles[1];
                assert p.labelAt(p.labelCircles[2],p.labelCircles[3])==1 : "overlapping rings choose the nearest heart";
                p.labelCircles[2]=c.circles.get(1)[0];p.labelCircles[3]=c.circles.get(1)[1];
                for (int zone:new int[]{0,1,20}) {
                    p.handFrom=p.HAND_MEMORY;p.holding=true;SystemClock.now=550;
                    GameActivity.requests=0;p.cleared=0;p.labelZones[0]=zone;p.zoneLabelCount=2;
                    float oldZone=p.bodyDetails[12];
                    p.depositInto(0);p.later.poll().run();
                    assert GameActivity.requests==1 && GameActivity.command.equals("setting PortBodyPut "+(zone+1));
                    assert p.depositZone==zone && p.cleared==0 : "wait for the game's transfer and current status";
                    p.zoneLabelCount=0;p.bodyDetails[12]=zone;
                    p.depositInto(0);p.runLater();
                    assert GameActivity.requests==1&&p.cleared==1&&p.depositZone<0 : "one request despite a second tap";
                    assert p.depositHint && p.guideUntil==SystemClock.now+3000;
                    p.lymphHearts=false;c=new Canvas();p.drawBodyDetails(c);c.check(p.width,p.height);
                    assert c.cards.size()==1 && c.lines==0 && p.labelsDrawn==0 : "after transfer only the current heart's status remains";
                    assert c.texts.contains("♡  13 / 100");
                    SystemClock.now=p.guideUntil-1;assert p.heartShown();
                    SystemClock.now=p.guideUntil;assert !p.heartShown();
                    p.bodyDetails[12]=oldZone;
                }
                p.handFrom=p.HAND_MEMORY;p.holding=true;
                GameActivity.requests=0;GameActivity.accept=false;p.depositInto(0);p.runLater();
                assert p.depositZone<0&&p.holding : "a full command queue leaves the colour in the hand";
                GameActivity.accept=true;GameActivity.requests=0;
                p.holding=false;p.depositInto(0);p.runLater();
                assert GameActivity.requests==0 : "nothing in the hand: nothing to put";
                p.holding=true;
                p.screen=0;p.depositInto(0);p.runLater();
                assert GameActivity.requests==0 : "leaving the body prevents a transfer";
                p.screen=S_BODY;p.zoneLabelCount=2;p.guideUntil=0;p.depositHint=false;
                p.depositInto(0);p.later.poll().run();
                p.screen=0;p.runLater();
                assert p.depositZone<0 && !p.depositHint && p.guideUntil==0 : "cancelling never shows a stale hint";
                p.screen=S_BODY;
                // Right above its heart (35 game pixels below and 12 right of the game's point).
                assert Math.abs((centre[0]+centre[2])/2-(673f+12)/1346*p.width)<1 && Math.abs(centre[3]-((300f+35)/600*p.height-p.dp(34)))<1 : Arrays.toString(centre);
                p.zoneLabelCount=0;
                // A heart's colour drawn into the hand: the Memory's card offers it, without "→ ◯".
                p.handFrom=p.HAND_HEART;p.handDrawing=false;p.handTaken=12;c=new Canvas();p.drawBodyDetails(c);c.check(p.width,p.height);
                assert p.memoryCardAction==p.CARD_PUT && !c.texts.contains("→ ◯") && c.texts.contains("+12");
            }
        }
        System.out.println("PASS body overlay: stats, guides, Memory amount/return, heart labels and transfer circles, single-tap deposit, 3-second status, cancellation, viewport bounds");
    }
}
''',encoding="utf-8")
subprocess.run([str(JAVA / "javac.exe"),"--release","8","-encoding","UTF-8","-d",str(OUT),str(overlay)],check=True)
subprocess.run([str(JAVA / "java.exe"),"-ea","-cp",str(OUT),"BodyOverlayProbe"],check=True)
