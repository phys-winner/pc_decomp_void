package port.launcher;

import android.content.Context;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/** Files of a game folder the port never reads (installers, editors, manuals — the categories of
 *  port.json). The preview is exactly what deletion removes; links are never followed, and if any
 *  previewed file changed since, nothing is deleted. */
final class Cleanup {
    static final class Entry {
        final File file;
        final long size, modified;
        final Object key;     /* the file system's identity of the file, when it has one */

        Entry(File file, BasicFileAttributes attributes) {
            this.file = file;
            this.size = attributes.size();
            this.modified = attributes.lastModifiedTime().toMillis();
            this.key = attributes.fileKey();
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
            for (Entry e : files) sum += e.size;
            bytes = sum;
        }
    }

    private Cleanup() { }

    /** What the categories of one part match in its folder. */
    static Plan scan(File root, List<Spec.Category> categories) throws IOException {
        List<Glob> globs = new ArrayList<>();
        for (Spec.Category c : categories) globs.addAll(c.globs);
        List<Entry> files = new ArrayList<>();
        if (!globs.isEmpty() && root.isDirectory()) walk(root, "", globs, files);
        return new Plan(root, files);
    }

    private static void walk(File folder, String prefix, List<Glob> globs, List<Entry> out) throws IOException {
        File[] children = folder.listFiles();
        if (children == null) throw new IOException("Cannot read " + folder);
        Arrays.sort(children, (a, b) -> a.getName().compareToIgnoreCase(b.getName()));
        for (File child : children) {
            String path = prefix + child.getName();
            BasicFileAttributes a = Files.readAttributes(child.toPath(), BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            if (a.isSymbolicLink() || a.isOther()) continue;
            if (a.isDirectory()) {
                boolean reachable = false;
                for (Glob g : globs) if (g.mayMatchBelow(path)) { reachable = true; break; }
                if (reachable) walk(child, path + "/", globs, out);
            } else if (a.isRegularFile()) {
                for (Glob g : globs) if (g.matches(path)) { out.add(new Entry(child, a)); break; }
            }
        }
    }

    static final class Job extends Work.Job {
        final Plan plan;

        Job(Context context, Plan plan) {
            super(Texts.SPACE, Texts.t(context, Texts.JOB_CLEAN), plan.root);
            this.plan = plan;
            total = plan.bytes;
            itemsTotal = plan.files.size();
        }

        /** All or nothing: every file is checked first, then the files go, then emptied folders. */
        @Override void work() throws IOException {
            String root = plan.root.getCanonicalPath() + File.separator;
            for (Entry e : plan.files) {
                BasicFileAttributes a;
                try {
                    a = Files.readAttributes(e.file.toPath(), BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
                } catch (IOException gone) {
                    throw new Failure(Failure.CHANGED, e.file.getPath());
                }
                if (!a.isRegularFile() || a.size() != e.size || a.lastModifiedTime().toMillis() != e.modified
                        || (e.key != null && !e.key.equals(a.fileKey())) || !e.file.getCanonicalPath().startsWith(root))
                    throw new Failure(Failure.CHANGED, e.file.getPath());
            }
            List<File> folders = new ArrayList<>();
            for (Entry e : plan.files) {
                file = e.file.getName();
                if (e.file.delete()) done += e.size;
                ++itemsDone;
                for (File parent = e.file.getParentFile(); parent != null && !parent.equals(plan.root); parent = parent.getParentFile())
                    if (!folders.contains(parent)) folders.add(parent);
            }
            Collections.sort(folders, (a, b) -> b.getAbsolutePath().length() - a.getAbsolutePath().length());
            for (File folder : folders) {
                String[] left = folder.list();
                if (left != null && left.length == 0) folder.delete();
            }
        }
    }
}
