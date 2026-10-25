package org.thevoid.port;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Files outside the installation roots consumed by push_game_data.py and files.c.
 *  Never follows links; the preview is the exact immutable set deletion can use. */
final class GameCleanup {
    static final class Entry {
        final File file;
        final long size, modified;
        final Object key;

        Entry(File file, BasicFileAttributes attributes) {
            this.file = file;
            size = attributes.size();
            modified = attributes.lastModifiedTime().toMillis();
            key = attributes.fileKey();
        }
    }

    static final class Plan {
        final File root;
        final List<Entry> files;
        final long bytes;

        Plan(File root, List<Entry> files) {
            this.root = root;
            this.files = Collections.unmodifiableList(files);
            long sum = 0;
            for (Entry entry : files) sum += entry.size;
            bytes = sum;
        }
    }

    private GameCleanup() { }

    static Plan scan(File folder) throws IOException {
        File root = folder.getAbsoluteFile();
        if (!safe(root, root) || !Unpacker.isRoot(root) || !Unpacker.isVoid(root))
            throw new IOException("The selected folder is not a complete game installation");
        List<Entry> files = new ArrayList<>();
        collect(root, root, runtimePaths(root), files);
        return new Plan(root, files);
    }

    private static void collect(File root, File folder, List<File> required, List<Entry> out) throws IOException {
        File[] entries = folder.listFiles();
        if (entries == null) throw new IOException("Cannot read " + folder);
        java.util.Arrays.sort(entries, (a, b) -> a.getName().compareToIgnoreCase(b.getName()));
        for (File file : entries) {
            if (!safe(root, file) || keep(root, file, required)) continue;
            BasicFileAttributes attr = attributes(file);
            if (attr.isRegularFile()) out.add(new Entry(file, attr));
            else if (attr.isDirectory()) collect(root, file, required, out);
        }
    }

    private static boolean keep(File root, File file, List<File> required) {
        String path = file.getAbsolutePath().toLowerCase(Locale.ROOT);
        for (File needed : required) {
            String target = needed.getAbsolutePath().toLowerCase(Locale.ROOT);
            if (path.equals(target) || target.startsWith(path + File.separator) || path.startsWith(target + File.separator)) return true;
        }
        String name = file.getName().toLowerCase(Locale.ROOT);
        if (file.getParentFile().equals(root)) {
            if (name.equals("game.txt") || file.isDirectory() && (name.startsWith("lifted") || name.startsWith("game"))) return true;
            // These roots are read at runtime, including loose replacements and caches.
            if (name.equals("bin") || name.equals("data") || name.equals("void") || name.equals("userdata") || name.startsWith("userdata-")
                || name.equals("overrides")
                || name.equals("shadercache") || name.equals("cache") || name.equals(".git")
                || name.equals(".nomedia") || name.equals("appdata") || name.equals("programdata")
                || name.equals("publicdocuments") || name.equals("drive_c") || name.equals("temp")) return true;
        }
        // Player data stays even when an older installation kept it in a different folder.
        if (name.equals("save") || name.equals("saves") || name.equals("savegames") || name.equals("documents")
            || name.equals("screenshots") || name.equals("gallery") || name.equals("profiles") || name.equals("mods")) return true;
        if (file.isDirectory() && Unpacker.isRoot(file)) return true;
        return name.endsWith(".sav") || name.endsWith(".save") || name.endsWith(".xml") || name.endsWith(".cfg")
            || name.endsWith(".ini") || name.endsWith(".rcfg") || name.endsWith(".scfg") || name.endsWith(".json");
    }

    /** Revalidates each previewed file; new or changed files are never removed. */
    static long delete(Plan plan) throws IOException {
        long freed = 0;
        List<File> required = runtimePaths(plan.root);
        for (Entry entry : plan.files) {
            if (!safe(plan.root, entry.file) || keep(plan.root, entry.file, required))
                throw new IOException("Cleanup path changed: " + entry.file);
            BasicFileAttributes now = attributes(entry.file);
            if (!now.isRegularFile() || now.size() != entry.size || now.lastModifiedTime().toMillis() != entry.modified
                || entry.key != null && !entry.key.equals(now.fileKey()))
                throw new IOException("Cleanup file changed: " + entry.file);
        }
        for (Entry entry : plan.files) {
            if (!safe(plan.root, entry.file)) throw new IOException("Cleanup path changed: " + entry.file);
            BasicFileAttributes now = attributes(entry.file);
            if (!now.isRegularFile() || now.size() != entry.size || now.lastModifiedTime().toMillis() != entry.modified
                || entry.key != null && !entry.key.equals(now.fileKey()))
                throw new IOException("Cleanup file changed: " + entry.file);
            Files.delete(entry.file.toPath());
            freed += entry.size;
        }
        return freed;
    }

    private static List<File> runtimePaths(File root) throws IOException {
        List<File> paths = new ArrayList<>();
        File data = Unpacker.child(root, "data"), systems = Unpacker.child(data, "fsystems.xml");
        if (systems == null || !systems.isFile()) return paths;
        if (!safe(root, systems) || systems.length() > 1 << 20) throw new IOException("Unsafe filesystem configuration: " + systems);
        byte[] bytes = Files.readAllBytes(systems.toPath());
        boolean wide = bytes.length > 1 && ((bytes[0] & 255) == 255 && (bytes[1] & 255) == 254
            || bytes[0] == -2 && bytes[1] == -1);
        String xml = new String(bytes, wide ? StandardCharsets.UTF_16 : StandardCharsets.UTF_8);
        Matcher match = Pattern.compile("<Path(?:\\s[^>]*)?>([^<]*)</Path\\s*>", Pattern.CASE_INSENSITIVE).matcher(xml);
        while (match.find()) {
            String value = match.group(1).trim();
            if (value.contains("{") || value.contains("}")) continue;
            if (Pattern.compile("&(?!amp;|lt;|gt;|quot;|apos;)").matcher(value).find())
                throw new IOException("Unresolved filesystem path: " + value);
            value = value.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", "\"").replace("&apos;", "'").replace('\\', '/');
            File path = new File(data, value).getCanonicalFile();
            if (path.equals(root) || path.getPath().startsWith(root.getPath() + File.separator)) paths.add(path);
        }
        return paths;
    }

    private static BasicFileAttributes attributes(File file) throws IOException {
        return Files.readAttributes(file.toPath(), BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
    }

    private static boolean safe(File root, File file) throws IOException {
        String base = root.getAbsolutePath(), path = file.getAbsolutePath();
        if (!path.equals(base) && !path.startsWith(base + File.separator)) return false;
        for (File part = file; part != null; part = part.getParentFile()) {
            BasicFileAttributes attr = attributes(part);
            if (attr.isSymbolicLink() || attr.isOther() || !part.getCanonicalFile().equals(part.getAbsoluteFile())) return false;
        }
        return true;
    }
}
