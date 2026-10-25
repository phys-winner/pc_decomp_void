package org.thevoid.port;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

public final class GameCleanupTest {
    private static void put(File root, String name, byte[] bytes) throws IOException {
        File file = new File(root, name);
        Files.createDirectories(file.getParentFile().toPath());
        Files.write(file.toPath(), bytes);
    }

    public static void main(String[] args) throws Exception {
        if (args.length > 1) {
            File linkedRoot = new File(args[1]);
            assert GameCleanup.scan(linkedRoot).files.isEmpty() : "followed a junction";
            File linked = new File(linkedRoot, "external-link/outside.bin");
            GameCleanup.Entry entry = new GameCleanup.Entry(linked,
                Files.readAttributes(linked.toPath(), java.nio.file.attribute.BasicFileAttributes.class));
            try { GameCleanup.delete(new GameCleanup.Plan(linkedRoot, Arrays.asList(entry))); throw new AssertionError("junction accepted"); }
            catch (IOException expected) { }
            assert linked.isFile();
            System.out.println("junction scan and deletion confinement: PASS");
        }
        File root = Files.createTempDirectory(new File(args[0]).toPath(), "game-cleanup-").toFile();
        byte[] data = {1, 2, 3};
        String[] keep = {"bin/win32/Game.exe", "bin/win32/Video.dll", "data/info.xml", "data/Scenes.vfs",
            "data/Scenes/loose.bin", "Void/Cache/effects.hdr", "userdata/Documents/Savegames/a.bin",
            "lifted/Engine.dll", "game-german/bin/win32/Game.exe", "game-german/data/info.xml", "overrides/patched.bin",
            "Other/Savegames/a.bin", "Other/user.cfg", "Other/settings.xml", "Documents/picture.png", "game.txt"};
        for (String name : keep) put(root, name, data);
        put(root, "data/fsystems.xml", "<FileSystems><system><Path>../CustomTextures</Path></system></FileSystems>".getBytes("UTF-8"));
        put(root, "CustomTextures/loose.bin", data);
        String[] remove = {"manual.pdf", "PhysX_Setup.exe", "DirectX/DXSETUP.exe", "Other/readme.txt",
            "game_setup.exe", "game_manual.pdf", "lifted_backup.dat"};
        for (String name : remove) put(root, name, data);
        GameCleanup.Plan plan = GameCleanup.scan(root);
        Set<String> found = new HashSet<>();
        for (GameCleanup.Entry entry : plan.files)
            found.add(root.toPath().relativize(entry.file.toPath()).toString().replace(File.separatorChar, '/'));
        assert found.equals(new HashSet<>(Arrays.asList(remove))) : found;
        assert plan.bytes == remove.length * data.length;
        assert new File(root, "manual.pdf").isFile() : "preview deleted a file";

        File changed = plan.files.get(plan.files.size() - 1).file;
        Files.write(changed.toPath(), new byte[] {9});
        try { GameCleanup.delete(plan); throw new AssertionError("changed file accepted"); }
        catch (IOException expected) { }
        for (String name : remove) assert new File(root, name).isFile() : "failed preflight deleted " + name;

        File outside = File.createTempFile("cleanup-outside-", ".bin", new File(args[0]));
        Files.write(outside.toPath(), data);
        GameCleanup.Entry escaped = new GameCleanup.Entry(new File(root, "../" + outside.getName()),
            Files.readAttributes(outside.toPath(), java.nio.file.attribute.BasicFileAttributes.class));
        try { GameCleanup.delete(new GameCleanup.Plan(root, Arrays.asList(escaped))); throw new AssertionError("escape accepted"); }
        catch (IOException expected) { }
        assert outside.isFile();
        assert new File(root, "CustomTextures/loose.bin").isFile() : "removed configured loose filesystem data";

        try {
            Files.createSymbolicLink(new File(root, "external-link").toPath(), outside.toPath());
            assert GameCleanup.scan(root).files.size() == remove.length;
            GameCleanup.Plan beforeSwap = GameCleanup.scan(root);
            File swap = beforeSwap.files.get(0).file;
            Files.delete(swap.toPath());
            Files.createSymbolicLink(swap.toPath(), outside.toPath());
            try { GameCleanup.delete(beforeSwap); throw new AssertionError("link swap accepted"); }
            catch (IOException expected) { }
            Files.delete(swap.toPath());
            Files.write(swap.toPath(), data);
            System.out.println("symlink scan and replacement: PASS");
        } catch (UnsupportedOperationException | java.nio.file.FileSystemException unsupported) {
            System.out.println("symlink creation unavailable: " + unsupported.getClass().getSimpleName());
        }
        GameCleanup.Plan fresh = GameCleanup.scan(root);
        assert GameCleanup.delete(fresh) == fresh.bytes;
        for (String name : remove) assert !new File(root, name).exists();
        for (String name : keep) assert new File(root, name).isFile() : "removed protected " + name;
        assert new File(root, "CustomTextures/loose.bin").isFile() : "removed configured loose filesystem data";
        assert outside.isFile();
        System.out.println("cleanup: selection, exact bytes, preview, data retention, changed-file rejection, confinement PASS");
    }
}
