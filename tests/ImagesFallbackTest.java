package org.thevoid.port;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

/** Images.dir: a pushed images folder is used only while it has every image the APK carries. */
public final class ImagesFallbackTest {
    private static void write(File f, String text) throws IOException {
        f.getParentFile().mkdirs();
        try (FileOutputStream o = new FileOutputStream(f)) { o.write(text.getBytes(StandardCharsets.UTF_8)); }
    }

    private static void check(boolean ok, String what) {
        if (!ok) throw new AssertionError(what);
    }

    public static void main(String[] args) throws IOException {
        File root = new File(args[0]);
        File assets = new File(root, "assets"), files = new File(root, "files"), base = new File(root, "sdcard");
        String[] names = {"Game.exe", "Engine.dll", "d3dx9_36.dll"};
        StringBuilder index = new StringBuilder();
        for (String n : names) {
            write(new File(assets, "lifted/" + n), "apk " + n);
            index.append(n).append(" 4 0\n");
        }
        write(new File(assets, "lifted/index.txt"), index.toString());
        android.content.Context c = new android.content.Context(assets, files);
        File shared = new File(base, "lifted");

        /* No pushed folder: the APK's images, copied once. */
        File dir = Images.dir(c, base, "lifted");
        check(dir.equals(new File(files, "lifted")), "no pushed folder: " + dir);
        check(new File(dir, "d3dx9_36.dll").isFile(), "APK images installed");

        /* A complete pushed folder stays first (development). */
        for (String n : names) write(new File(shared, n), "pushed " + n);
        check(Images.dir(c, base, "lifted").equals(shared), "complete pushed folder used");

        /* One pushed before the compiler's image existed: the APK's copy instead. */
        check(new File(shared, "d3dx9_36.dll").delete(), "fixture");
        dir = Images.dir(c, base, "lifted");
        check(dir.equals(new File(files, "lifted")), "stale pushed folder ignored: " + dir);
        check(new File(dir, "d3dx9_36.dll").isFile(), "compiler image present");

        /* A pushed folder without Game.exe is no images folder at all. */
        write(new File(shared, "d3dx9_36.dll"), "pushed");
        check(new File(shared, "Game.exe").delete(), "fixture");
        check(!Images.dir(c, base, "lifted").equals(shared), "pushed folder without Game.exe");

        /* A build without images (no index): whatever was pushed is all there is. */
        write(new File(shared, "Game.exe"), "pushed");
        check(new File(assets, "lifted/index.txt").delete(), "fixture");
        check(Images.dir(c, base, "lifted").equals(shared), "no APK index: pushed folder used");

        /* Tension's images (lifted-tension) take the same check. */
        String[] tension = {"Game.exe", "Engine.dll", "RendererD3D.dll"};
        index.setLength(0);
        for (String n : tension) {
            write(new File(assets, "lifted-tension/" + n), "apk " + n);
            index.append(n).append(" 4 0\n");
        }
        write(new File(assets, "lifted-tension/index.txt"), index.toString());
        File sharedTension = new File(base, "lifted-tension");
        for (String n : tension) write(new File(sharedTension, n), "pushed " + n);
        check(Images.dir(c, base, "lifted-tension").equals(sharedTension), "complete pushed Tension folder used");
        check(new File(sharedTension, "RendererD3D.dll").delete(), "fixture");
        dir = Images.dir(c, base, "lifted-tension");
        check(dir.equals(new File(files, "lifted-tension")), "stale pushed Tension folder ignored: " + dir);
        check(new File(dir, "RendererD3D.dll").isFile(), "Tension APK images installed");
        System.out.println("PASS: Images.dir prefers a complete pushed folder, else the APK's images (both games)");
    }
}
