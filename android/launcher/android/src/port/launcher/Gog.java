package port.launcher;

import android.content.Context;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.TimeUnit;

/** Reads an offline EXE and its adjacent BIN files as data, using bundled ARM64 innoextract.
 * The Windows installer is never run. Game-specific required files and original hashes still apply. */
final class Gog {
    static final class Info {
        final File setup;
        String id;
        boolean split;
        long bytes;
        int count;
        final Map<String, Long> files = new LinkedHashMap<>();
        Info(File setup) { this.setup = setup; }
    }

    private static String executable(Context context) {
        return new File(context.getApplicationInfo().nativeLibraryDir, Spec.get(context).gogInstaller).getAbsolutePath();
    }

    static Info parse(File setup, List<String> lines) throws IOException {
        Info info = new Info(setup);
        long bytes = 0;
        try {
            for (String line : lines) {
                if (line.startsWith("GOG2\t")) {
                    String[] row = line.split("\t", -1);
                    if (row.length != 5 || info.id != null || !row[1].matches("[0-9]{1,20}")) throw new IOException("Invalid GOG metadata");
                    info.id = row[1]; info.count = Integer.parseInt(row[2]); info.bytes = Long.parseLong(row[3]);
                    if (!(row[4].equals("0") || row[4].equals("1")) || info.count < 1 || info.count > 100000 ||
                        info.bytes < 1 || info.bytes > (32L << 30)) throw new IOException("Invalid GOG size");
                    info.split = row[4].equals("1");
                } else if (line.startsWith("FILE\t")) {
                    String[] row = line.split("\t", -1);
                    if (info.id == null || row.length != 3 || row[2].length() > 2048 || row[2].matches(".*[\\p{Cntrl}\"].*")) throw new IOException("Invalid GOG file path");
                    String path = Install.relative(row[2]), key = row[2].toLowerCase(Locale.ROOT);
                    long size = Long.parseLong(row[1]);
                    if (path == null || path.isEmpty() || !path.equals(row[2]) || size < 0 || size > (32L << 30) ||
                        info.files.put(key, size) != null || info.files.size() > 100000) throw new IOException("Invalid or duplicate GOG file");
                    bytes += size;
                    if (bytes > (32L << 30)) throw new IOException("GOG payload exceeds 32 GiB");
                }
            }
        } catch (NumberFormatException invalid) { throw new IOException("Invalid GOG number", invalid); }
        if (info.id == null || info.files.size() != info.count || bytes != info.bytes) throw new IOException("Incomplete GOG metadata");
        return info;
    }

    static boolean contains(Info info, Spec.Part part) {
        for (String required : part.required) {
            String key = required.toLowerCase(Locale.ROOT);
            if (key.endsWith("/")) {
                boolean found = false;
                for (String path : info.files.keySet()) if (path.startsWith(key)) { found = true; break; }
                if (!found) return false;
            } else if (!info.files.containsKey(key) || info.files.get(key) == 0) return false;
        }
        return true;
    }

    static List<Spec.Distribution> distributions(Info info, Spec spec) {
        List<Spec.Distribution> result = new ArrayList<>();
        java.util.Set<String> groups = new java.util.HashSet<>();
        for (Spec.Distribution distribution : spec.distributions) {
            if (distribution.parts.size() != 1) continue;
            Spec.Part part = distribution.parts.get(0);
            if (!contains(info, part)) continue;
            boolean complete = true;
            if (!part.folderGroup.isEmpty()) {
                for (Spec.Distribution peer : spec.distributions) for (Spec.Part required : peer.parts)
                    if (part.folderGroup.equals(required.folderGroup) && !contains(info, required)) complete = false;
                if (!complete || !groups.add(part.folderGroup)) continue;
            }
            result.add(distribution);
        }
        return result;
    }

    static Info inspect(Context context, File setup) throws IOException {
        if (!setup.isFile() || !setup.canRead() || setup.length() < 2 || setup.length() > (8L << 30))
            throw new IOException(Texts.t(context, Texts.GOG_BAD_INPUT));
        try (FileInputStream input = new FileInputStream(setup)) {
            if (input.read() != 'M' || input.read() != 'Z') throw new IOException(Texts.t(context, Texts.GOG_BAD_INPUT));
        }
        Process process = new ProcessBuilder(executable(context), "--port-info", setup.getAbsolutePath()).redirectErrorStream(true).start();
        // Drain while it runs: the manifest may exceed a pipe buffer. A stuck decoder cannot hang the launcher.
        Thread timeout = new Thread(() -> {
            try { if (!process.waitFor(30, TimeUnit.SECONDS)) process.destroyForcibly(); }
            catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
        }, "gog-metadata-timeout");
        timeout.setDaemon(true); timeout.start();
        List<String> lines = new ArrayList<>();
        try (BufferedReader input = new BufferedReader(new InputStreamReader(process.getInputStream(), "UTF-8"))) {
            for (String line; (line = input.readLine()) != null;) {
                if (line.length() > 4096 || lines.size() >= 101024) throw new IOException("GOG metadata exceeds limits");
                lines.add(line);
            }
            if (process.waitFor() != 0) throw new IOException(Texts.t(context, Texts.GOG_BAD_INPUT) + "\n" + tail(lines));
            return parse(setup, lines);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt(); throw new IOException("GOG inspection interrupted", interrupted);
        } finally { process.destroy(); timeout.interrupt(); }
    }

    private static String tail(List<String> lines) {
        return String.join("\n", lines.subList(Math.max(0, lines.size() - 6), lines.size()));
    }

    /** One explicit destination: other editions' saved paths are never reassigned by this import. */
    static final class Job extends Work.Job {
        final Context context;
        final Info info;
        final Spec.Distribution distribution;
        final Spec.Part part;
        volatile Process process;
        File writing;
        long completed;

        Job(Context context, Info info, Spec.Distribution distribution, File target) {
            super(Texts.t(context, Texts.GOG_INSTALLING), target);
            this.context = context.getApplicationContext(); this.info = info; this.distribution = distribution;
            part = distribution.parts.get(0);
            for (Map.Entry<String, Long> entry : info.files.entrySet()) if (Install.wanted(entry.getKey(), part.needed)) {
                total += entry.getValue(); ++itemsTotal;
            }
        }

        @Override void work() throws Exception {
            check();
            Info current = inspect(context, info.setup);
            if (!current.id.equals(info.id) || !current.files.equals(info.files)) throw new Failure(Failure.CHANGED, info.setup.getPath());
            String source = info.setup.getCanonicalPath();
            for (String suffix : new String[] {"", Install.PART, Install.OLD}) {
                String destination = new File(target.getPath() + suffix).getCanonicalPath();
                if (source.equals(destination) || source.startsWith(destination + File.separator))
                    throw new Failure(Failure.UNSAFE, info.setup.getPath());
            }
            if (Install.isLink(target)) throw new Failure(Failure.UNSAFE, target.getPath());
            PortHooks hooks = PortHooks.of(context);
            String conflict = hooks.installationProblem(context, distribution.id, part.id, target);
            if (conflict != null) throw new IOException(conflict);
            long required = total + (64L << 20), free = Storage.free(target.getParentFile());
            if (free < required) throw new Failure(Failure.FULL, null, required, free);
            File staged = new File(target.getPath() + Install.PART), old = new File(target.getPath() + Install.OLD);
            if (staged.exists() || Install.isLink(staged) || old.exists() || Install.isLink(old))
                throw new Failure(Failure.READ_ONLY, "Reserved import path already exists: " + staged + " / " + old);
            File parent = staged.getParentFile();
            if (!parent.isDirectory() && !parent.mkdirs()) throw new Failure(Failure.READ_ONLY, parent.getPath());
            if (!staged.mkdir()) throw new Failure(Failure.READ_ONLY, staged.getPath());
            // Recovery may remove only a staging directory this job successfully created.
            State.put(context, State.CHOICES, "importing", target.getAbsolutePath());
            Thread cancel = null;
            try {
                // Hide extracted game assets from Android's media scanner before the decoder writes.
                File nomedia = new File(staged, ".nomedia");
                if (!nomedia.createNewFile()) throw new Failure(Failure.READ_ONLY, nomedia.getPath());
                List<String> command = new ArrayList<>();
                java.util.Collections.addAll(command, executable(context), "--extract", "--test", "--exclude-temp", "--color=0", "--progress=0",
                    "--no-extract-unknown", "--collisions=error", "--output-dir", staged.getAbsolutePath());
                // Include explicit files instead of broad directories: metadata was checked before any decoder writes.
                for (String path : info.files.keySet()) if (Install.wanted(path, part.needed)) {
                    command.add("--include"); command.add("/" + path);
                }
                command.add(info.setup.getAbsolutePath());
                process = new ProcessBuilder(command).redirectErrorStream(true).start();
                cancel = new Thread(() -> {
                    try {
                        while (process.isAlive()) {
                            if (cancelled) { process.destroyForcibly(); break; }
                            synchronized (Job.this) {
                                done = completed + (writing != null ? writing.length() : 0);
                            }
                            Thread.sleep(100);
                        }
                    } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
                }, "gog-cancel");
                cancel.setDaemon(true); cancel.start();
                List<String> last = new ArrayList<>();
                try (BufferedReader input = new BufferedReader(new InputStreamReader(process.getInputStream(), "UTF-8"))) {
                    for (String line; (line = input.readLine()) != null;) {
                        check();
                        if (line.length() > 4096) throw new IOException("GOG output line exceeds limit");
                        if (last.size() == 6) last.remove(0);
                        last.add(line);
                        if (line.startsWith(" - \"")) {
                            int end = line.indexOf('"', 4);
                            if (end > 4) {
                                file = line.substring(4, end).replace('\\', '/');
                                File output = new File(staged, file);
                                if (!output.getCanonicalPath().startsWith(staged.getCanonicalPath() + File.separator))
                                    throw new Failure(Failure.UNSAFE, file);
                                synchronized (this) {
                                    if (writing != null) completed += writing.length();
                                    writing = output;
                                    done = completed + output.length();
                                }
                                ++itemsDone;
                            }
                        }
                    }
                }
                check();
                if (process.waitFor() != 0) throw new IOException(Texts.t(context, Texts.GOG_BAD_INPUT) + "\n" + tail(last));
                File content = staged; // Android innoextract expands {app} to the output directory.
                validate(content, "");
                for (Map.Entry<String, Long> entry : info.files.entrySet()) if (Install.wanted(entry.getKey(), part.needed)) {
                    File extracted = Install.child(content, entry.getKey());
                    if (extracted == null || !extracted.isFile() || extracted.length() != entry.getValue())
                        throw new Failure(Failure.CORRUPT, entry.getKey());
                }
                List<String> missing = Install.missing(part, content);
                if (!missing.isEmpty()) throw new IOException(Texts.fmt(context, Texts.MISSING, String.join(", ", missing)));
                conflict = hooks.installationProblem(context, distribution.id, part.id, content);
                if (conflict != null) throw new IOException(conflict);
                hooks.verifyInstallation(context, distribution.id, part.id, content);
                check();
                commit(content, target, old);
                if (!part.fixed) Install.choose(context, distribution, part, target);
                done = total; itemsDone = itemsTotal;
            } catch (IOException failure) {
                if (cancelled) throw new Failure(Failure.CANCELLED, null);
                throw failure;
            } finally {
                if (process != null && process.isAlive()) process.destroyForcibly();
                if (cancel != null) cancel.interrupt();
                Install.delete(staged);
            }
        }

        /** Moves without replacing a preexisting .old sibling; a failed final rename restores the game. */
        private void commit(File content, File target, File old) throws IOException {
            if (old.exists() || Install.isLink(old)) throw new Failure(Failure.READ_ONLY, old.getPath());
            boolean had = target.exists();
            if (had) java.nio.file.Files.move(target.toPath(), old.toPath());
            try { java.nio.file.Files.move(content.toPath(), target.toPath()); }
            catch (IOException failure) {
                if (had && !target.exists()) java.nio.file.Files.move(old.toPath(), target.toPath());
                throw failure;
            }
            if (had) Install.delete(old);
        }

        private void validate(File root, String prefix) throws IOException {
            check();
            if (Install.isLink(root)) throw new Failure(Failure.UNSAFE, root.getPath());
            if (prefix.isEmpty()) {
                File nomedia = new File(root, ".nomedia");
                if (Install.isLink(nomedia) || !nomedia.isFile() || nomedia.length() != 0)
                    throw new Failure(Failure.CORRUPT, ".nomedia");
            }
            File[] children = root.listFiles();
            if (children == null) throw new IOException("GOG output is missing: " + root);
            for (File child : children) {
                check();
                if (Install.isLink(child)) throw new Failure(Failure.UNSAFE, child.getPath());
                if (prefix.isEmpty() && child.getName().equals(".nomedia")) continue;
                String path = prefix + child.getName();
                if (child.isDirectory()) validate(child, path + "/");
                else {
                    String key = path.toLowerCase(Locale.ROOT);
                    Long expected = info.files.get(key);
                    if (expected == null || !Install.wanted(key, part.needed) || child.length() != expected)
                        throw new Failure(Failure.CORRUPT, path);
                }
            }
        }
    }
}
