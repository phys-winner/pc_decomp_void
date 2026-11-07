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

    private static String entry(String name, String bytes, String source) throws IOException {
        try {
            byte[] data = bytes.getBytes(StandardCharsets.UTF_8);
            byte[] digest = java.security.MessageDigest.getInstance("SHA-256").digest(data);
            StringBuilder hex = new StringBuilder();
            for (byte b : digest) hex.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
            return name + " " + data.length + " " + hex + (source.isEmpty() ? "" : " " + source) + "\n";
        } catch (java.security.NoSuchAlgorithmException e) { throw new AssertionError(e); }
    }

    public static void main(String[] args) throws IOException {
        File root = new File(args[0]);
        File assets = new File(root, "assets"), files = new File(root, "files"), base = new File(root, "sdcard");
        String[] names = {"Game.exe", "Engine.dll", "d3dx9_36.dll"};
        StringBuilder index = new StringBuilder();
        for (String n : names) {
            write(new File(assets, "lifted/" + n), "apk " + n);
            index.append(entry(n, "apk " + n, ""));
        }
        write(new File(assets, "lifted/index.txt"), index.toString());
        android.content.Context c = new android.content.Context(assets, files);
        File shared = new File(base, "lifted");
        File game = new File(root, "game");

        /* No pushed folder: the APK's images, copied once. */
        File dir = Images.dir(c, base, "lifted", game);
        check(dir.equals(new File(files, "lifted")), "no pushed folder: " + dir);
        check(new File(dir, "d3dx9_36.dll").isFile(), "APK images installed");

        /* A complete pushed folder stays first (development). */
        for (String n : names) write(new File(shared, n), "pushed " + n);
        check(Images.dir(c, base, "lifted", game).equals(shared), "complete pushed folder used");

        /* One pushed before the compiler's image existed: the APK's copy instead. */
        check(new File(shared, "d3dx9_36.dll").delete(), "fixture");
        dir = Images.dir(c, base, "lifted", game);
        check(dir.equals(new File(files, "lifted")), "stale pushed folder ignored: " + dir);
        check(new File(dir, "d3dx9_36.dll").isFile(), "compiler image present");

        /* A pushed folder without Game.exe is no images folder at all. */
        write(new File(shared, "d3dx9_36.dll"), "pushed");
        check(new File(shared, "Game.exe").delete(), "fixture");
        check(!Images.dir(c, base, "lifted", game).equals(shared), "pushed folder without Game.exe");

        /* A build without images (no index): whatever was pushed is all there is. */
        write(new File(shared, "Game.exe"), "pushed");
        check(new File(assets, "lifted/index.txt").delete(), "fixture");
        check(Images.dir(c, base, "lifted", game).equals(shared), "no APK index: pushed folder used");

        /* Tension's images (lifted-tension) take the same check. */
        String[] tension = {"Game.exe", "Engine.dll", "RendererD3D.dll"};
        index.setLength(0);
        for (String n : tension) {
            write(new File(assets, "lifted-tension/" + n), "apk " + n);
            index.append(entry(n, "apk " + n, ""));
        }
        write(new File(assets, "lifted-tension/index.txt"), index.toString());
        File sharedTension = new File(base, "lifted-tension");
        for (String n : tension) write(new File(sharedTension, n), "pushed " + n);
        check(Images.dir(c, base, "lifted-tension", game).equals(sharedTension), "complete pushed Tension folder used");
        check(new File(sharedTension, "RendererD3D.dll").delete(), "fixture");
        dir = Images.dir(c, base, "lifted-tension", game);
        check(dir.equals(new File(files, "lifted-tension")), "stale pushed Tension folder ignored: " + dir);
        check(new File(dir, "RendererD3D.dll").isFile(), "Tension APK images installed");
        /* Full Tension originals are required only when the private images are absent. */
        String exe = "original Game.exe", module = "original GameModule.dll";
        String external = entry("Game.exe", exe, "game:bin/win32/Game.exe")
            + entry("GameModule.dll", module, "game:bin/win32/GameModule.dll")
            + entry("d3dx9_36.dll", "apk d3dx9_36.dll", "apk:lifted/d3dx9_36.dll");
        write(new File(assets, "lifted-tension/index.txt"), external);
        android.content.Context externalContext = new android.content.Context(assets, new File(root, "external-files"));
        File exeFile = new File(game, "BIN/Win32/game.exe"), moduleFile = new File(game, "BIN/Win32/GAMEMODULE.DLL");
        File stamp = new File(root, "external-files/lifted-tension/apk.txt");
        try { Images.dir(externalContext, base, "lifted-tension", game); throw new AssertionError("missing originals accepted"); }
        catch (Images.OriginalRequired expected) { check(expected.getMessage().equals("bin/win32/Game.exe"), "missing image named"); }
        check(!stamp.exists(), "missing input published a completed install");
        write(exeFile, new String(new char[exe.length()]).replace('\0', 'x'));
        write(moduleFile, module);
        try { Images.dir(externalContext, base, "lifted-tension", game); throw new AssertionError("wrong original hash accepted"); }
        catch (Images.OriginalRequired expected) { }
        check(!stamp.exists(), "wrong input published a completed install");
        check(!new File(root, "external-files/lifted-tension/Game.exe").exists(), "wrong original installed");
        write(exeFile, exe);
        dir = Images.dir(externalContext, base, "lifted-tension", game);
        check(new String(java.nio.file.Files.readAllBytes(new File(dir, "Game.exe").toPath()), StandardCharsets.UTF_8).equals(exe), "original Game.exe copied exactly");
        check(new String(java.nio.file.Files.readAllBytes(new File(dir, "GameModule.dll").toPath()), StandardCharsets.UTF_8).equals(module), "original GameModule copied exactly");
        check(new String(java.nio.file.Files.readAllBytes(new File(dir, "d3dx9_36.dll").toPath()), StandardCharsets.UTF_8).equals("apk d3dx9_36.dll"), "cross-release asset alias");
        check(stamp.isFile(), "completed install noted");
        check(exeFile.delete() && moduleFile.delete() && stamp.delete(), "cache reuse fixture");
        check(Images.dir(externalContext, base, "lifted-tension", game).equals(dir), "valid private images reused on upgrade");
        check(stamp.isFile(), "reused images noted");
        System.out.println("PASS: complete pushed folders, APK fallback, original-only images with SHA-256, case-insensitive paths, missing/wrong input rejection, retry, cached upgrade and shared asset alias");
    }
}
