package port.launcher;

import java.io.DataOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.BufferedOutputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;

/** A game part played straight from a ZIP whose files are stored without compression (the
 *  approach of the RE4 port's MobileCache): the stored files are read in place through the
 *  archive's descriptor, the few compressed ones are unpacked beside it (the sidecar), and the
 *  game's file layer (native/zipmount.c) finds both through the index written here.
 *
 *  Index format "ZMI1", little-endian:
 *    magic "ZMI1", u32 count, u64 archive size, 32 bytes SHA-256 of the central directory
 *    count records sorted by lower-case path: u64 data offset, u64 size, u32 CRC-32,
 *    u32 flags (1 = in the sidecar), u64 modification time (ms), u16 path length, path (UTF-8)
 *  Plain Java. */
final class StoredArchive {
    static final int SIDECAR = 1;

    static final class Item {
        final String path;            /* relative to the part's root, '/' separated */
        final Zip.Entry entry;
        final long offset;            /* data offset in the archive; -1 for sidecar items */

        Item(String path, Zip.Entry entry, long offset) {
            this.path = path;
            this.entry = entry;
            this.offset = offset;
        }

        boolean stored() { return offset >= 0; }
    }

    static final class Plan {
        final String root;
        final List<Item> items;
        final long storedBytes, sidecarBytes;
        final int sidecarFiles;

        Plan(String root, List<Item> items) {
            this.root = root;
            this.items = Collections.unmodifiableList(items);
            long stored = 0, sidecar = 0;
            int count = 0;
            for (Item item : items) {
                if (item.stored()) stored += item.entry.size;
                else { sidecar += item.entry.size; ++count; }
            }
            storedBytes = stored;
            sidecarBytes = sidecar;
            sidecarFiles = count;
        }
    }

    private StoredArchive() { }

    /** The files under root ("" or "folder/") that the game would read from the archive. */
    static Plan plan(Zip zip, String root, List<Glob> needed) throws IOException {
        List<Item> items = new ArrayList<>();
        for (Zip.Entry e : zip.entries) {
            if (e.directory() || !e.name.regionMatches(true, 0, root, 0, root.length())) continue;
            String path = Install.relative(e.name.substring(root.length()));
            if (path == null) throw new Failure(Failure.UNSAFE, e.name);
            if (path.isEmpty() || !Install.wanted(path, needed)) continue;
            if (e.encrypted()) throw new Failure(Failure.ENCRYPTED, e.name);
            if (!Zip.supported(e.method)) throw new Failure(Failure.METHOD, Zip.methodName(e.method));
            boolean stored = e.method == Zip.STORED && e.packedSize == e.size;
            items.add(new Item(path, e, stored ? zip.dataOffset(e) : -1));
        }
        if (items.isEmpty()) throw new Failure(Failure.NOT_FOUND, root);
        Collections.sort(items, (a, b) -> key(a.path).compareTo(key(b.path)));
        for (int i = 1; i < items.size(); ++i)
            if (key(items.get(i).path).equals(key(items.get(i - 1).path))) throw new Failure(Failure.UNSAFE, items.get(i).path);
        return new Plan(root, items);
    }

    static String key(String path) { return path.toLowerCase(Locale.ROOT); }

    /** SHA-256 of the archive's central directory entries as parsed: an archive replaced under the
     *  same name, or rewritten, no longer matches its index. */
    static byte[] fingerprint(Zip zip) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            for (Zip.Entry e : zip.entries) {
                digest.update(e.name.getBytes(StandardCharsets.UTF_8));
                for (long value : new long[] {e.method, e.crc, e.packedSize, e.size, e.header}) {
                    for (int shift = 0; shift < 64; shift += 8) digest.update((byte) (value >>> shift));
                }
            }
            return digest.digest();
        } catch (NoSuchAlgorithmException e) {
            throw new AssertionError(e);
        }
    }

    static void writeIndex(Plan plan, long archiveSize, byte[] fingerprint, File out) throws IOException {
        File part = new File(out.getPath() + ".part");
        try (FileOutputStream file = new FileOutputStream(part);
             DataOutputStream data = new DataOutputStream(new BufferedOutputStream(file, 1 << 16))) {
            data.write(new byte[] {'Z', 'M', 'I', '1'});
            u32(data, plan.items.size());
            u64(data, archiveSize);
            data.write(fingerprint, 0, 32);
            for (Item item : plan.items) {
                byte[] name = item.path.getBytes(StandardCharsets.UTF_8);
                if (name.length > 0xFFFF) throw new Failure(Failure.UNSAFE, item.path);
                u64(data, item.stored() ? item.offset : 0);
                u64(data, item.entry.size);
                u32(data, item.entry.crc);
                u32(data, item.stored() ? 0 : SIDECAR);
                u64(data, item.entry.time);
                data.write(name.length & 0xFF);
                data.write(name.length >>> 8);
                data.write(name);
            }
            data.flush();
            file.getFD().sync();
        }
        if (!part.renameTo(out)) throw new IOException("cannot write " + out);
    }

    private static void u32(DataOutputStream out, long value) throws IOException {
        for (int shift = 0; shift < 32; shift += 8) out.write((int) (value >>> shift) & 0xFF);
    }

    private static void u64(DataOutputStream out, long value) throws IOException {
        for (int shift = 0; shift < 64; shift += 8) out.write((int) (value >>> shift) & 0xFF);
    }
}
