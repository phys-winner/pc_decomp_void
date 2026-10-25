package org.thevoid.port;

import android.content.Context;
import java.io.File;
import java.io.IOException;
import java.io.InterruptedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/** Runs the real installer with filesystem-backed APK assets and no device. */
public final class ShaderCacheInstallTest {
    private static final String A = "0000000000000001.bin", B = "0000000000000002.err", C = "0000000000000003.bin";
    private static File root;

    private static void put(File file, String text) throws IOException {
        file.getParentFile().mkdirs();
        Files.write(file.toPath(), text.getBytes(StandardCharsets.UTF_8));
    }

    private static String read(File file) throws IOException {
        return new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8);
    }

    private static File data(String name) { return new File(root, name); }
    private static File cached(File data, String name) { return new File(data, "shadercache/" + name); }

    private static String manifest(File assets, String... names) throws Exception {
        StringBuilder text = new StringBuilder();
        for (String name : names) {
            byte[] bytes = Files.readAllBytes(new File(assets, "shadercache/" + name).toPath());
            String digest = String.format("%064x", new java.math.BigInteger(1, java.security.MessageDigest.getInstance("SHA-256").digest(bytes)));
            text.append(name).append(' ').append(bytes.length).append(' ').append(digest).append('\n');
        }
        return text.toString();
    }

    /** An index line for a duplicate: its shared content's size and digest and
     *  the shipped name it links to, with no asset of its own. */
    private static String aliasOf(File assets, String name, String canonical) throws Exception {
        byte[] bytes = Files.readAllBytes(new File(assets, "shadercache/" + canonical).toPath());
        String digest = String.format("%064x", new java.math.BigInteger(1, java.security.MessageDigest.getInstance("SHA-256").digest(bytes)));
        return name + ' ' + bytes.length + ' ' + digest + ' ' + canonical + '\n';
    }

    private static List<Integer> install(Context context, File data, int total) throws IOException {
        List<Integer> progress = new ArrayList<>();
        ShaderCache.install(context, data, (done, count) -> {
            assert count == total && done >= 0 && done <= count;
            assert progress.isEmpty() || done >= progress.get(progress.size() - 1);
            progress.add(done);
        });
        return progress;
    }

    private static void fails(Context context, File data) throws IOException {
        boolean failed = false;
        try { install(context, data, 3); }
        catch (IOException expected) { failed = true; }
        assert failed : "preparation must not silently continue after I/O failure";
    }

    private static void nativeWork() {
        ShaderCache.NativeWork work = new ShaderCache.NativeWork();
        assert !work.settled(1000);
        assert !work.update(0, 100, 8, false);
        assert !work.update(200, 106, 8, false);
        assert !work.settled(200) : "one advancing poll does not finish startup";
        assert !work.update(400, 112, 8, false);
        assert !work.settled(400) : "moving frames still need a settled interval";
        assert !work.update(600, 118, 8, false);
        assert work.settled(600) : "direct-to-world startup can finish without ever observing a menu";
        assert !work.update(800, 124, 9, false);
        assert !work.settled(800) : "new shader work restarts the settling interval";
        assert !work.update(1000, 130, 9, false);
        assert !work.update(1200, 136, 9, false);
        assert !work.settled(1200);
        assert !work.update(1400, 142, 9, false);
        assert work.settled(1400);
        work.reset();
        assert !work.settled(1500) : "resume cannot reuse old moving-frame evidence";
        assert !work.update(0, 1, 0, false);
        assert !work.update(200, 2, 2, false);
        assert !work.update(400, 3, 2, false);
        assert !work.update(600, 3, 3, false);
        assert !work.update(1000, 3, 5, false);
        assert work.update(1200, 3, 7, false) && work.beganAt == 400;
        assert work.update(1400, 3, 7, false) : "long single compilation keeps its badge";
        assert work.update(1600, 4, 7, false) : "one moving sample is not yet recovery";
        assert !work.settled(1600);
        assert !work.update(1800, 5, 7, false) : "normal frames and settled shader work dismiss the badge";
        assert work.settled(1800);
        assert !work.update(2000, 6, 8, false);
        assert !work.update(2200, 6, 9, false);
        assert !work.update(2400, 7, 10, false) : "short cached loading must not flash";
        assert !work.update(5000, 7, 10, false) : "an idle stalled frame alone is not shader preparation";

        work.reset();
        assert !work.update(10000, 30, 40, true);
        assert !work.update(10200, 31, 42, true);
        assert !work.update(10400, 32, 44, true) : "playing an intro stays unobscured";
        assert !work.update(10800, 32, 45, true);
        assert work.update(11200, 32, 46, true) : "a stale video tag must not hide real stalled shader work";
        assert !work.update(11400, 33, 46, true) : "a video resumes without a badge";

        work.reset();
        assert !work.update(50000, 33, 900, false) : "resume starts a fresh observation interval";
        assert !work.update(51000, 33, 900, false);
        assert work.update(51200, 33, 901, false);
        assert work.update(55000, 33, 901, false) : "no new completed shaders does not mean a compile finished";
        assert work.update(55200, 34, 901, false);
        assert !work.update(55400, 35, 901, false);
    }

    public static void main(String[] args) throws Exception {
        nativeWork();
        root = new File(args[0]);
        File assets = new File(root, "assets"), index = new File(assets, "shadercache/index.txt");
        Context context = new Context(assets);
        put(index, A + "\n\n " + B + " \n" + C + "\n");
        put(new File(assets, "shadercache/" + A), "apk-bytecode");
        put(new File(assets, "shadercache/" + B), "hr=80004005\nexpected compile error");
        put(new File(assets, "shadercache/" + C), "apk-bytecode-c");
        File first = data("first");
        put(cached(first, A), "profile-bytecode");
        put(cached(first, C), "");
        put(cached(first, "apk"), "old marker");
        assert install(context, first, 3).equals(Arrays.asList(0, 1, 2, 3));
        assert read(cached(first, A)).equals("profile-bytecode") : "keep valid per-profile cache";
        assert read(cached(first, C)).equals("apk-bytecode-c") : "repair empty outputs";
        assert !cached(first, C + ".part").exists() && !cached(first, "apk.part").exists();
        assert install(context, first, 3).equals(Arrays.asList(3)) : "warm launch uses completed marker";
        Files.delete(cached(first, B).toPath());
        assert install(context, first, 3).equals(Arrays.asList(0, 1, 2, 3)) : "marker must not conceal missing files";
        assert read(cached(first, B)).contains("expected compile error");

        File failed = data("missing-asset");
        Files.delete(new File(assets, "shadercache/" + C).toPath());
        fails(context, failed);
        assert !cached(failed, "apk").exists();
        assert cached(failed, A).isFile() && cached(failed, B).isFile();
        put(new File(assets, "shadercache/" + C), "retry-bytecode");
        assert install(context, failed, 3).equals(Arrays.asList(0, 1, 2, 3));
        assert read(cached(failed, C)).equals("retry-bytecode");

        File empty = data("empty-asset");
        put(new File(assets, "shadercache/" + C), "");
        fails(context, empty);
        assert !cached(empty, "apk").exists() && !cached(empty, C).exists();
        put(new File(assets, "shadercache/" + C), "restored");

        File blocked = data("blocked-output");
        put(new File(cached(blocked, C), "blocker"), "keep");
        fails(context, blocked);
        assert read(new File(cached(blocked, C), "blocker")).equals("keep");
        assert !cached(blocked, "apk").exists() && !cached(blocked, C + ".part").exists();

        File changed = data("changed-apk");
        install(context, changed, 3);
        String oldMarker = read(cached(changed, "apk"));
        String extra = "0000000000000004.bin";
        put(index, A + "\n" + B + "\n" + C + "\n" + extra + "\n");
        boolean updateFailed = false;
        try { install(context, changed, 4); }
        catch (IOException expected) { updateFailed = true; }
        assert updateFailed && read(cached(changed, "apk")).equals(oldMarker);
        put(new File(assets, "shadercache/" + extra), "update");
        assert install(context, changed, 4).equals(Arrays.asList(0, 1, 2, 3, 4));
        assert !read(cached(changed, "apk")).equals(oldMarker);

        File cancelled = data("cancelled");
        put(index, A + "\n" + B + "\n" + C + "\n");
        boolean interrupted = false;
        try {
            ShaderCache.install(context, cancelled, (done, count) -> {
                if (done == 1) Thread.currentThread().interrupt();
            });
        } catch (InterruptedIOException expected) { interrupted = true; }
        finally { Thread.interrupted(); }
        assert interrupted && !cached(cancelled, "apk").exists();
        assert cached(cancelled, A).isFile() && !cached(cancelled, B).exists();
        install(context, cancelled, 3);

        File invalid = data("invalid-index");
        for (String name : new String[] {"../escape.bin", "..\\escape.bin", "/absolute.bin", "apk", "x.bin"}) {
            put(index, name + "\n");
            fails(context, invalid);
            assert !invalid.exists();
        }
        put(index, "\n");
        assert install(context, data("no-shaders"), 0).equals(Arrays.asList(0));

        put(index, manifest(assets, A, B, C));
        File verified = data("verified-manifest");
        put(cached(verified, A), "bad-bytecode");
        install(context, verified, 3);
        assert read(cached(verified, A)).equals("apk-bytecode") : "repair nonempty corrupt private copy";
        assert install(context, verified, 3).equals(Arrays.asList(3));
        put(cached(verified, A), "bad-bytecode");
        assert cached(verified, A).length() == new File(assets, "shadercache/" + A).length();
        install(context, verified, 3);
        assert read(cached(verified, A)).equals("apk-bytecode") : "matching marker must not conceal same-size corruption";
        String previousMarker = read(cached(verified, "apk"));
        put(new File(assets, "shadercache/" + A), "new-bytecode");
        put(index, manifest(assets, A, B, C));
        install(context, verified, 3);
        assert read(cached(verified, A)).equals("new-bytecode") && !read(cached(verified, "apk")).equals(previousMarker)
            : "corrected output with the same filename must migrate";
        put(new File(assets, "shadercache/" + A), "bad-bytecode");
        fails(context, data("corrupt-bundled-data"));
        assert !cached(data("corrupt-bundled-data"), "apk").exists();
        for (String metadata : new String[] {"0 abc", "10 abc", "-1 " + new String(new char[64]).replace('\0', 'a'),
                "999999999999999999999999 abc", "10", "10 abc extra"}) {
            put(index, A + " " + metadata + "\n");
            fails(context, data("invalid-metadata"));
        }
        // Duplicate shaders: a fourth field names the one shipped content they
        // share, installed as a symbolic link (a copy where links are refused)
        // with no asset of its own.
        String dup = "0000000000000009.bin";
        put(new File(assets, "shadercache/" + A), "shared-bytecode");
        put(index, manifest(assets, A, B) + aliasOf(assets, dup, A));
        File deduped = data("deduped");
        assert install(context, deduped, 3).equals(Arrays.asList(0, 1, 2, 3));
        assert read(cached(deduped, dup)).equals("shared-bytecode") : "a duplicate installs its shared content";
        assert read(cached(deduped, A)).equals("shared-bytecode");
        assert !new File(assets, "shadercache/" + dup).exists() : "a duplicate ships no asset of its own";
        assert install(context, deduped, 3).equals(Arrays.asList(3)) : "warm launch keeps the links";
        Files.delete(cached(deduped, dup).toPath());
        assert install(context, deduped, 3).equals(Arrays.asList(0, 1, 2, 3)) : "a lost duplicate is relinked";
        assert read(cached(deduped, dup)).equals("shared-bytecode");
        String aa = new String(new char[64]).replace('\0', 'a');
        put(index, manifest(assets, A, B) + dup + " 10 " + aa + " " + dup + "\n");
        fails(context, data("self-alias"));
        put(index, manifest(assets, A, B) + C + " 10 " + aa + " notahex.bin\n");
        fails(context, data("bad-alias-target"));

        put(index, manifest(assets, A, B, C));
        File warmIndex = new File(assets, "shaderwarm/index.txt"), warmAsset = new File(assets, "shaderwarm/" + A);
        put(warmIndex, manifest(assets, A));
        put(warmAsset, read(new File(assets, "shadercache/" + A)));
        File warmData = data("warm-programs"), warmCopy = new File(warmData, "shaderwarm/" + A);
        install(context, warmData, 3);
        assert read(warmCopy).equals(read(warmAsset));
        put(warmCopy, "same-size-x");
        install(context, warmData, 3);
        assert read(warmCopy).equals(read(warmAsset)) : "repair corrupt program recipes even with a complete stage cache";
        put(warmAsset, "mismatch");
        fails(context, data("bad-warm-program"));
        put(warmIndex, "../escape.bin 10 " + new String(new char[64]).replace('\0', 'a'));
        fails(context, data("bad-warm-name"));
        put(warmIndex, A + " 999999999999999999999999999999 " + new String(new char[64]).replace('\0', 'a'));
        fails(context, data("bad-warm-size"));
        System.out.println("PASS: installer progress/retry/cancel and native loading badge: stalls, recovery, quick loads, videos and resume");
    }
}
