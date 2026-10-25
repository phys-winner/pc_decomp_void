package org.thevoid.port;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.RandomAccessFile;
import java.nio.file.Files;
import java.security.MessageDigest;

/** tests/test_launcher_unpack.py drives this: the launcher's ZIP reader,
 *  Deflate64 decoder and unpacking job on the PC, one case per run. */
public final class LauncherUnpackTest {
    public static void main(String[] args) throws Exception {
        switch (args[0]) {
        case "inflate":   /* raw stream, expected bytes, 64 or 32 (Deflate64 or Deflate) */
            inflate(new File(args[1]), new File(args[2]), args[3].equals("64"));
            break;
        case "unpack":    /* archive, the chosen folder, [cancel-after-bytes] */
            unpack(new File(args[1]), new File(args[2]), args.length > 3 ? Long.parseLong(args[3]) : -1);
            break;
        case "root":      /* a folder the player chose */
            File root = Unpacker.findRoot(new File(args[1]));
            System.out.println("root " + (root != null && Unpacker.isVoid(root)) + " " + (root == null ? "-" : root.getPath()));
            break;
        case "target":    /* the chosen folder */
            System.out.println("target " + Unpacker.target(new File(args[1])).getPath());
            break;
        default:
            throw new IllegalArgumentException(args[0]);
        }
    }

    private static void inflate(File stream, File expected, boolean deflate64) throws Exception {
        long start = System.nanoTime();
        MessageDigest got = MessageDigest.getInstance("SHA-256");
        long n = 0;
        try (InputStream in = new Deflate64(new FileInputStream(stream), deflate64)) {
            byte[] b = new byte[1 << 16];
            for (int r; (r = in.read(b, 0, b.length)) > 0; n += r) got.update(b, 0, r);
        } catch (IOException e) {
            System.out.println("error " + e.getMessage());
            return;
        }
        String want = hex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(expected.toPath())));
        System.out.println("inflated " + n + " " + (hex(got.digest()).equals(want) ? "same" : "DIFFERENT")
            + " " + (System.nanoTime() - start) / 1000000 + " ms");
    }

    private static void unpack(File archive, File chosen, long cancelAfter) throws Exception {
        long start = System.nanoTime();
        Unpacker.Plan plan;
        try {
            plan = Unpacker.plan(new Zip(new RandomAccessFile(archive, "r").getChannel()));
        } catch (Unpacker.Failure f) {
            System.out.println("failure " + f.code + " " + f.detail);
            return;
        }
        File target = Unpacker.target(chosen);
        System.out.println("plan root=" + plan.root + " files=" + plan.files.size() + " folders=" + plan.folders.size()
            + " size=" + plan.size + " target=" + target.getPath());
        System.out.println("info " + GameActivityTitles.title(plan.info) + " / " + GameActivityTitles.language(plan.languages));
        Unpacker.Job job = new Unpacker.Job(plan, target, archive.getPath(), archive);
        Thread t = new Thread(job);
        t.start();
        if (cancelAfter >= 0) {
            while (job.done <= cancelAfter && !job.finished) Thread.sleep(1);
            job.cancelled = true;
        }
        t.join();
        if (job.failure != null) {
            System.out.println("failure " + job.failure.code + " " + job.failure.detail);
        } else {
            double s = (System.nanoTime() - start) / 1e9;
            System.out.println(String.format(java.util.Locale.ROOT, "unpacked %d bytes in %.1f s (%.0f MB/s)",
                job.done, s, job.done / 1e6 / s));
        }
        System.out.println("left " + (target.exists() ? String.join(",", sorted(target.list())) : "-"));
    }

    private static String[] sorted(String[] names) {
        java.util.Arrays.sort(names);
        return names;
    }

    private static String hex(byte[] d) {
        StringBuilder s = new StringBuilder();
        for (byte b : d) s.append(String.format("%02x", b));
        return s.toString();
    }

    /** The release's names as GameActivity.Release reads them (that class needs Android). */
    static final class GameActivityTitles {
        static String title(String info) { return attribute(info, "Title"); }
        static String language(String languages) { return attribute(languages, "Name"); }

        static String attribute(String xml, String name) {
            int at = xml.indexOf(name + "=\"");
            if (at < 0) return "";
            int start = at + name.length() + 2, end = xml.indexOf('"', start);
            return end > start ? xml.substring(start, end) : "";
        }
    }
}
