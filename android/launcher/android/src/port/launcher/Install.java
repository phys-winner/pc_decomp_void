package port.launcher;

import android.content.Context;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.zip.CRC32;

/** Where a distribution's parts are and how they get there: case-insensitive checks of the files a
 *  part needs, discovery in a folder the player points at, a plan of what a ZIP archive holds, and
 *  the jobs that unpack, copy or move a part into place. Every job writes into "<target>.part"
 *  first and swaps it in only when everything arrived whole, so a stopped or failed import leaves
 *  the previous files as they were. */
final class Install {
    static final String PART = ".part", OLD = ".old";

    private Install() { }

    /* ------------------------------------------------------------- paths */

    /** A path inside an archive relative to the part's root, '/' separated; "" for the root itself,
     *  null if it would leave the root. */
    static String relative(String name) {
        String path = name.replace('\\', '/');
        if (path.indexOf('\0') >= 0 || path.startsWith("/") || path.matches("^[A-Za-z]:.*")) return null;
        StringBuilder out = new StringBuilder();
        for (String part : path.split("/")) {
            if (part.isEmpty() || part.equals(".")) continue;
            if (part.equals("..")) return null;
            if (out.length() > 0) out.append('/');
            out.append(part);
        }
        return out.toString();
    }

    static boolean wanted(String path, List<Glob> needed) {
        if (needed.isEmpty()) return true;
        for (Glob g : needed) if (g.matches(path)) return true;
        return false;
    }

    /** root/path with every name matched ignoring case, as Windows games expect; null if absent. */
    static File child(File root, String path) {
        File at = root;
        for (String part : path.split("/")) {
            if (part.isEmpty()) continue;
            if (at == null) return null;
            File direct = new File(at, part);
            if (direct.exists()) { at = direct; continue; }
            File[] children = at.listFiles();
            at = null;
            if (children != null) for (File item : children) if (item.getName().equalsIgnoreCase(part)) { at = item; break; }
        }
        return at;
    }

    static List<String> missing(Spec.Part part, File folder) {
        List<String> result = new ArrayList<>();
        for (String path : part.required) {
            File found = folder != null ? child(folder, path) : null;
            boolean ok = found != null && (path.endsWith("/") ? found.isDirectory() : found.isFile() && found.canRead());
            if (!ok) result.add(path);
            else if (!path.endsWith("/") && found.length() == 0) result.add(path + " (0 B)");
        }
        return result;
    }

    static boolean present(Spec.Part part, File folder) {
        return folder != null && folder.isDirectory() && missing(part, folder).isEmpty();
    }

    /** Only empty, missing content directories; existing content is never replaced. */
    static void createUserFolders(File root, java.util.Collection<String> paths) {
        for (String path : paths) try {
            String clean = relative(path);
            if (clean == null || clean.isEmpty() || !clean.equals(path)) throw new IOException("Invalid user folder: " + path);
            File boundary = root.getCanonicalFile(), target = boundary;
            for (String name : path.split("/")) {
                File existing = child(target, name);
                target = existing != null ? existing : new File(target, name);
                if (isLink(target) || !target.getCanonicalFile().toPath().startsWith(boundary.toPath()))
                    throw new IOException("User folder leaves the game: " + path);
            }
            if (!target.isDirectory() && !target.mkdirs() && !target.isDirectory())
                throw new IOException("Cannot create user folder: " + target);
        } catch (IOException | SecurityException failure) {
            Work.warn("cannot prepare user folder " + path, failure);
        }
    }

    /** Called by the launcher's startup worker, after choices and storage access are available. */
    static void ensureUserFolders(Context context, Spec spec) {
        for (Spec.Distribution d : spec.distributions) for (Spec.Part p : d.parts) {
            if (p.userFolders.isEmpty() || !mount(context, d, p).isEmpty() || ambiguous(context, spec, d, p)) continue;
            File root = folder(context, spec, d, p);
            if ((!Storage.own(context, root) && !Storage.allFiles(context)) || !present(p, root)) continue;
            createUserFolders(root, p.userFolders.keySet());
        }
    }

    /* ------------------------------------------------ where parts live now */

    static String key(Spec.Distribution d, Spec.Part p) { return "part." + (p.folderGroup.isEmpty() ? d.id : p.folderGroup) + "." + p.id; }

    /** Old per-edition choices are kept. A single legacy location is adopted by the shared root;
     * conflicting locations require an explicit choice, without moving or deleting either copy. */
    static List<File> legacyFolders(Context context, Spec spec, Spec.Part part) {
        List<File> result = new ArrayList<>();
        if (part.folderGroup.isEmpty()) return result;
        for (Spec.Distribution d : spec.distributions) for (Spec.Part p : d.parts) if (part.folderGroup.equals(p.folderGroup)) {
            String path = State.get(context, State.CHOICES, "part." + d.id + "." + p.id, "");
            if (path.isEmpty()) continue;
            File file = new File(path);
            boolean duplicate = false;
            for (File previous : result) try { duplicate |= previous.getCanonicalFile().equals(file.getCanonicalFile()); }
                catch (IOException ignored) { duplicate |= previous.equals(file); }
            if (!duplicate) result.add(file);
        }
        return result;
    }

    static boolean ambiguous(Context context, Spec spec, Spec.Distribution d, Spec.Part p) {
        return !p.folderGroup.isEmpty() && State.get(context, State.CHOICES, key(d, p), "").isEmpty()
            && legacyFolders(context, spec, p).size() > 1;
    }

    /** The part's folder: the fixed one, else the player's choice, else the template's default. */
    static File folder(Context context, Spec spec, Spec.Distribution d, Spec.Part p) {
        if (!p.fixed) {
            String chosen = State.get(context, State.CHOICES, key(d, p), "");
            if (!chosen.isEmpty()) return new File(chosen);
            List<File> old = legacyFolders(context, spec, p);
            if (old.size() == 1) return old.get(0);
        }
        return spec.resolve(context, p.folder);
    }

    /** The archive a mounted part is played from (its content URI), "" when it is a folder. */
    static String mount(Context context, Spec.Distribution d, Spec.Part p) {
        return State.get(context, State.CHOICES, key(d, p) + ".mount", "");
    }

    static void choose(Context context, Spec.Distribution d, Spec.Part p, File folder) {
        State.update(context, State.CHOICES, values -> {
            values.setProperty(key(d, p), folder.getAbsolutePath());
            values.remove(key(d, p) + ".mount");
        });
    }

    static boolean ready(Context context, Spec spec, Spec.Distribution d) {
        for (Spec.Part p : d.parts) {
            if (ambiguous(context, spec, d, p)) return false;
            if (!mount(context, d, p).isEmpty() && new File(State.folder(context), "mount-" + d.id + "-" + p.id + ".zmi").isFile()) continue;
            if (!present(p, folder(context, spec, d, p))) return false;
        }
        return true;
    }

    /* ------------------------------------------------------- discovery */

    static final class Found {
        final Spec.Distribution distribution;
        final Spec.Part part;
        final File folder;

        Found(Spec.Distribution distribution, Spec.Part part, File folder) {
            this.distribution = distribution;
            this.part = part;
            this.folder = folder;
        }
    }

    /** Parts in a chosen folder: the folder itself or one of its three parents, else the shallowest
     *  match among at most 512 folders four levels below it. Links never lead outside it. */
    static List<Found> discover(Spec spec, File source) { return discover(spec.distributions, source); }

    /** A folder picked for one edition must never reconfigure the other editions. */
    static List<Found> discover(Spec.Distribution distribution, File source) {
        return discover(java.util.Collections.singletonList(distribution), source);
    }

    static List<Found> discover(List<Spec.Distribution> distributions, Spec.Distribution choosing, File source) {
        if (choosing.parts.size() != 1 || choosing.parts.get(0).folderGroup.isEmpty()) return discover(choosing, source);
        Spec.Part original = choosing.parts.get(0), combined = new Spec.Part();
        combined.id = original.id; combined.marker = original.marker;
        for (Spec.Distribution d : distributions) for (Spec.Part p : d.parts) if (original.folderGroup.equals(p.folderGroup))
            for (String required : p.required) if (!combined.required.contains(required)) combined.required.add(required);
        Spec.Distribution group = new Spec.Distribution(); group.id = choosing.id; group.parts.add(combined);
        List<Found> result = new ArrayList<>();
        for (Found found : discover(group, source)) result.add(new Found(choosing, original, found.folder));
        return result;
    }

    static List<Found> discover(List<Spec.Distribution> distributions, File source) {
        List<Found> result = new ArrayList<>();
        HashSet<String> done = new HashSet<>();
        File up = source;
        for (int i = 0; i <= 3 && up != null; ++i, up = up.getParentFile()) collect(distributions, up, result, done);
        if (source == null || !source.isDirectory()) return result;
        String boundary;
        try { boundary = source.getCanonicalPath(); } catch (IOException unreadable) { return result; }
        String prefix = boundary.endsWith(File.separator) ? boundary : boundary + File.separator;
        ArrayDeque<File> folders = new ArrayDeque<>();
        ArrayDeque<Integer> depths = new ArrayDeque<>();
        HashSet<String> seen = new HashSet<>();
        folders.add(source);
        depths.add(0);
        int count = 0;
        while (!folders.isEmpty() && count++ < 512) {
            File folder = folders.removeFirst();
            int depth = depths.removeFirst();
            String canonical;
            try { canonical = folder.getCanonicalPath(); } catch (IOException unreadable) { continue; }
            if ((!canonical.equals(boundary) && !canonical.startsWith(prefix)) || !seen.add(canonical)) continue;
            collect(distributions, folder, result, done);
            if (depth >= 4) continue;
            File[] children = folder.listFiles(File::isDirectory);
            if (children == null) continue;
            Arrays.sort(children);
            for (File child : children) if (!child.getName().startsWith(".")) { folders.add(child); depths.add(depth + 1); }
        }
        return result;
    }

    private static void collect(List<Spec.Distribution> distributions, File folder, List<Found> result, HashSet<String> done) {
        for (Spec.Distribution d : distributions)
            for (Spec.Part p : d.parts) {
                String id = d.id + "/" + p.id;
                if (!done.contains(id) && present(p, folder)) { done.add(id); result.add(new Found(d, p, folder)); }
            }
    }

    /* ------------------------------------------------------- archives */

    static final class ArchivePart {
        final Spec.Distribution distribution;
        final Spec.Part part;
        final String root;
        final List<Zip.Entry> entries = new ArrayList<>();
        final List<String> paths = new ArrayList<>();
        /** Parts of other distributions in the same folder of the archive, unpacked with this one
         *  into its folder, which they then use too (merge). */
        final List<ArchivePart> also = new ArrayList<>();
        long size, compressed;      /* bytes in all, and in entries that are not stored */

        ArchivePart(Spec.Distribution distribution, Spec.Part part, String root) {
            this.distribution = distribution;
            this.part = part;
            this.root = root;
        }

        /** This part and the ones it is unpacked for. */
        List<ArchivePart> served() {
            List<ArchivePart> all = new ArrayList<>();
            all.add(this);
            all.addAll(also);
            return all;
        }
    }

    /** The parts an archive holds: for each, the shallowest folder where all its required paths are;
     *  parts of several distributions in one folder become one (merge). */
    static List<ArchivePart> plan(Zip zip, Spec spec) throws IOException { return plan(zip, spec.distributions); }

    static List<ArchivePart> plan(Zip zip, List<Spec.Distribution> distributions) throws IOException {
        List<String> names = new ArrayList<>(zip.entries.size());
        for (Zip.Entry e : zip.entries) {
            String path = relative(e.name);
            if (path == null) throw new Failure(Failure.UNSAFE, e.name);
            names.add(path.toLowerCase(Locale.ROOT) + (e.directory() ? "/" : ""));
        }
        List<ArchivePart> result = new ArrayList<>();
        for (Spec.Distribution d : distributions)
            for (Spec.Part p : d.parts) {
                String root = root(names, p);
                if (root == null) continue;
                ArchivePart plan = new ArchivePart(d, p, root);
                for (int i = 0; i < zip.entries.size(); ++i) {
                    Zip.Entry e = zip.entries.get(i);
                    if (e.directory() || !names.get(i).startsWith(root)) continue;
                    String path = strip(relative(e.name), root.split("/", -1).length - 1);
                    if (path.isEmpty() || !wanted(path, p.needed)) continue;
                    if (e.encrypted()) throw new Failure(Failure.ENCRYPTED, e.name);
                    if (!Zip.supported(e.method)) throw new Failure(Failure.METHOD, Zip.methodName(e.method));
                    plan.entries.add(e);
                    plan.paths.add(path);
                    plan.size += e.size;
                    if (e.method != Zip.STORED) plan.compressed += e.size;
                }
                inArchiveOrder(plan);
                result.add(plan);
            }
        return merge(result);
    }

    /** One pass over the archive, in the order its data lies. */
    private static void inArchiveOrder(ArchivePart plan) {
        Integer[] order = new Integer[plan.entries.size()];
        for (int i = 0; i < order.length; ++i) order[i] = i;
        Arrays.sort(order, (a, b) -> Long.compare(plan.entries.get(a).header, plan.entries.get(b).header));
        List<Zip.Entry> entries = new ArrayList<>(plan.entries);
        List<String> paths = new ArrayList<>(plan.paths);
        plan.entries.clear();
        plan.paths.clear();
        for (int i : order) { plan.entries.add(entries.get(i)); plan.paths.add(paths.get(i)); }
    }

    /** Parts of several distributions in the same folder of an archive (Heroes V: Hammers of Fate is
     *  installed over the original game, so its folder holds both) are unpacked once, with what each
     *  of them needs, into the folder of the first; every one of them then uses that folder. A part
     *  the port reads only from its fixed folder keeps its own. */
    static List<ArchivePart> merge(List<ArchivePart> plans) {
        List<ArchivePart> result = new ArrayList<>();
        for (ArchivePart plan : plans) {
            ArchivePart into = null;
            if (!plan.part.fixed) for (ArchivePart r : result) if (!r.part.fixed && r.root.equals(plan.root)) { into = r; break; }
            if (into == null) { result.add(plan); continue; }
            into.also.add(plan);
            HashSet<String> have = new HashSet<>(into.paths);
            for (int i = 0; i < plan.entries.size(); ++i) {
                Zip.Entry e = plan.entries.get(i);
                if (!have.add(plan.paths.get(i))) continue;
                into.entries.add(e);
                into.paths.add(plan.paths.get(i));
                into.size += e.size;
                if (e.method != Zip.STORED) into.compressed += e.size;
            }
            inArchiveOrder(into);
        }
        return result;
    }

    /** One import's targets, each its own: a non-fixed part whose folder another part of the same
     *  import already takes gets the next free name beside it ("game-2"). */
    static List<File> distinct(List<ArchivePart> plans, List<File> targets) {
        List<File> result = new ArrayList<>();
        HashSet<String> taken = new HashSet<>();
        for (int i = 0; i < targets.size(); ++i) {
            File target = targets.get(i);
            if (!plans.get(i).part.fixed && taken.contains(target.getAbsolutePath())) {
                File parent = target.getParentFile();
                String name = target.getName();
                int n = 2;
                do target = new File(parent, name + "-" + n++);
                while (target.exists() || taken.contains(target.getAbsolutePath()));
            }
            taken.add(target.getAbsolutePath());
            result.add(target);
        }
        return result;
    }

    /** The path without its first folders (lower-casing may change a name's length, not its folders). */
    static String strip(String path, int folders) {
        int at = 0;
        for (int i = 0; i < folders; ++i) at = path.indexOf('/', at) + 1;
        return path.substring(at);
    }

    /** The archive folder ("" or "a/b/", lower case) that holds every required path of the part. */
    private static String root(List<String> names, Spec.Part p) {
        String marker = p.marker.toLowerCase(Locale.ROOT);
        List<String> candidates = new ArrayList<>();
        for (String name : names) {
            int at = name.equals(marker) || (marker.endsWith("/") && name.startsWith(marker)) ? 0 : -1;
            if (at < 0) {
                int inner = name.indexOf("/" + marker);
                if (inner >= 0 && (marker.endsWith("/") || name.endsWith("/" + marker))) at = inner + 1;
            }
            if (at >= 0 && !candidates.contains(name.substring(0, at))) candidates.add(name.substring(0, at));
        }
        candidates.sort((a, b) -> Integer.compare(a.split("/", -1).length, b.split("/", -1).length));
        for (String root : candidates) {
            boolean all = true;
            for (String required : p.required) {
                String want = root + required.toLowerCase(Locale.ROOT);
                boolean found = false;
                for (String name : names) {
                    if (required.endsWith("/") ? name.startsWith(want) : name.equals(want)) { found = true; break; }
                }
                if (!found) { all = false; break; }
            }
            if (all) return root;
        }
        return null;
    }

    /* ------------------------------------------------------------ jobs */

    /** The folder a non-fixed part is unpacked into: an empty chosen folder itself, else a new
     *  folder named after the part inside it. */
    static File target(File chosen, String name) {
        String[] inside = chosen.list();
        if (inside == null || inside.length == 0) return chosen;
        File target = new File(chosen, name);
        for (int n = 2; target.exists(); ++n) target = new File(chosen, name + "-" + n);
        return target;
    }

    /** Swaps a finished "<target>.part" in: the old target moves aside first and goes last. */
    static void commit(File staged, File target) throws IOException {
        File old = new File(target.getPath() + OLD);
        if (old.exists()) delete(old);
        boolean had = target.exists();
        if (had && !target.renameTo(old)) throw new Failure(Failure.READ_ONLY, target.getPath());
        if (!staged.renameTo(target)) {
            if (had) old.renameTo(target);
            throw new Failure(Failure.READ_ONLY, target.getPath());
        }
        if (had) delete(old);
    }

    /** What an import interrupted with the process left: the staged copy goes; a target moved aside
     *  but not replaced comes back. true if anything was found. */
    static boolean recover(File target) {
        boolean found = false;
        File staged = new File(target.getPath() + PART), old = new File(target.getPath() + OLD);
        if (staged.exists()) { delete(staged); found = true; }
        if (old.exists()) {
            if (!target.exists()) old.renameTo(target);
            else delete(old);
            found = true;
        }
        return found;
    }

    static void delete(File file) {
        File[] children = file.isDirectory() && !isLink(file) ? file.listFiles() : null;
        if (children != null) for (File child : children) delete(child);
        if (!file.delete() && file.exists()) Work.warn("cannot delete " + file, null);
    }

    static boolean isLink(File file) {
        try {
            return java.nio.file.Files.isSymbolicLink(file.toPath());
        } catch (RuntimeException e) {
            return false;
        }
    }

    static File staging(File target) throws IOException {
        File staged = new File(target.getPath() + PART);
        if (staged.exists()) delete(staged);
        if (!staged.mkdirs()) throw new Failure(Failure.READ_ONLY, staged.getParent());
        return staged;
    }

    /** Unpacks parts of one archive, checking every file's CRC-32; the job owns the archive. */
    static final class UnpackJob extends Work.Job {
        final Context context;
        final Zip zip;
        final List<ArchivePart> plans;
        final List<File> targets;

        UnpackJob(Context context, Zip zip, List<ArchivePart> plans, List<File> targets) {
            super(Texts.t(context, Texts.JOB_UNPACK), targets.get(0));
            this.context = context != null ? context.getApplicationContext() : null;
            this.zip = zip;
            this.plans = plans;
            this.targets = targets;
            for (ArchivePart plan : plans) { total += plan.size; itemsTotal += plan.entries.size(); }
        }

        @Override void work() throws IOException {
            try {
                for (int i = 0; i < plans.size(); ++i) unpack(plans.get(i), targets.get(i));
            } finally {
                try { zip.close(); } catch (IOException ignored) { /* only read */ }
            }
        }

        private void unpack(ArchivePart plan, File target) throws IOException {
            String problem = context != null ? PortHooks.of(context).installationProblem(context, plan.distribution.id, plan.part.id, target) : null;
            if (problem != null) throw new IOException(problem);
            long free = Storage.free(target.getParentFile()), required = plan.size + (64L << 20);
            if (free < required) throw new Failure(Failure.FULL, null, required, free);
            File staged = staging(target);
            try {
                byte[] buffer = new byte[1 << 20];
                for (int i = 0; i < plan.entries.size(); ++i) {
                    Zip.Entry e = plan.entries.get(i);
                    String path = plan.paths.get(i);
                    file = path;
                    File out = new File(staged, path);
                    File parent = out.getParentFile();
                    if (!parent.isDirectory() && !parent.mkdirs()) throw new Failure(Failure.READ_ONLY, parent.getPath());
                    CRC32 crc = new CRC32();
                    long written = 0;
                    try (InputStream in = zip.open(e); OutputStream o = new FileOutputStream(out)) {
                        for (int n; (n = in.read(buffer)) > 0;) {
                            check();
                            o.write(buffer, 0, n);
                            crc.update(buffer, 0, n);
                            written += n;
                            done += n;
                        }
                    }
                    if (written != e.size || crc.getValue() != e.crc) throw new Failure(Failure.CORRUPT, path);
                    if (e.time > 0) out.setLastModified(e.time);
                    ++itemsDone;
                }
                check();
                String stagedProblem = context != null ? PortHooks.of(context).installationProblem(context,
                    plan.distribution.id, plan.part.id, staged) : null;
                if (stagedProblem != null) throw new IOException(stagedProblem);
                commit(staged, target);
            } catch (IOException | RuntimeException failure) {
                delete(staged);
                throw failure;
            }
        }
    }

    /** Copies parts' folders (what each needs of them) into place. */
    static final class CopyJob extends Work.Job {
        final List<File> sources, targets;
        final List<List<Glob>> needed;

        CopyJob(Context context, List<File> sources, List<File> targets, List<List<Glob>> needed) {
            super(Texts.t(context, Texts.JOB_COPY), targets.get(0));
            this.sources = sources;
            this.targets = targets;
            this.needed = needed;
        }

        @Override void work() throws IOException {
            List<List<String>> lists = new ArrayList<>();
            for (int i = 0; i < sources.size(); ++i) {
                List<String> files = new ArrayList<>();
                list(sources.get(i), "", files, needed.get(i));
                long bytes = 0;
                for (String path : files) bytes += new File(sources.get(i), path).length();
                long free = Storage.free(targets.get(i).getParentFile()), required = bytes + (64L << 20);
                if (free < required) throw new Failure(Failure.FULL, null, required, free);
                total += bytes;
                itemsTotal += files.size();
                lists.add(files);
            }
            for (int i = 0; i < sources.size(); ++i) copy(sources.get(i), targets.get(i), lists.get(i));
        }

        private void copy(File source, File target, List<String> files) throws IOException {
            File staged = staging(target);
            try {
                byte[] buffer = new byte[1 << 20];
                for (String path : files) {
                    file = path;
                    File in = new File(source, path), out = new File(staged, path);
                    File parent = out.getParentFile();
                    if (!parent.isDirectory() && !parent.mkdirs()) throw new Failure(Failure.READ_ONLY, parent.getPath());
                    try (InputStream i = new FileInputStream(in); OutputStream o = new FileOutputStream(out)) {
                        for (int n; (n = i.read(buffer)) > 0;) {
                            check();
                            o.write(buffer, 0, n);
                            done += n;
                        }
                    }
                    out.setLastModified(in.lastModified());
                    ++itemsDone;
                }
                check();
                commit(staged, target);
            } catch (IOException | RuntimeException failure) {
                delete(staged);
                throw failure;
            }
        }

        private static void list(File folder, String prefix, List<String> out, List<Glob> needed) throws IOException {
            File[] children = folder.listFiles();
            if (children == null) throw new Failure(Failure.IO, folder.getPath());
            Arrays.sort(children);
            for (File child : children) {
                if (isLink(child)) continue;
                String path = prefix + child.getName();
                if (child.isDirectory()) list(child, path + "/", out, needed);
                else if (wanted(path, needed)) out.add(path);
            }
        }
    }

    /** Moves parts' folders into place: renames, when source and target share a volume. */
    static final class MoveJob extends Work.Job {
        final List<File> sources, targets;

        MoveJob(Context context, List<File> sources, List<File> targets) {
            super(Texts.t(context, Texts.JOB_MOVE), targets.get(0));
            this.sources = sources;
            this.targets = targets;
        }

        @Override void work() throws IOException {
            for (int i = 0; i < sources.size(); ++i) {
                File source = sources.get(i), target = targets.get(i);
                File parent = target.getParentFile();
                if (!parent.isDirectory() && !parent.mkdirs()) throw new Failure(Failure.READ_ONLY, parent.getPath());
                File staged = new File(target.getPath() + PART);
                if (staged.exists()) delete(staged);
                if (!source.renameTo(staged)) throw new Failure(Failure.READ_ONLY, source.getPath());
                try {
                    commit(staged, target);
                } catch (IOException failure) {
                    staged.renameTo(source);
                    throw failure;
                }
            }
        }
    }
}
