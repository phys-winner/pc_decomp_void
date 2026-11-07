"""Exercise production picker failures and ZIP filename decoding on the JVM."""
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

from test_launcher_unpack import write_zip

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from toolchain import SDK, JAVA_HOME

SOURCE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT
JAVA = JAVA_HOME / "bin"
ANDROID = SDK / "platforms/android-36/android.jar"
(ROOT / "build").mkdir(exist_ok=True)
OUT = Path(tempfile.mkdtemp(prefix="import-safety-", dir=ROOT / "build"))
APP = SOURCE / "android/app/src/org/thevoid/port"


def method(source, declaration):
    start = source.index(declaration)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def run(command, label):
    result = subprocess.run(list(map(str, command)), capture_output=True, text=True, encoding="utf-8")
    (OUT / (label + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
    if result.stdout.strip():
        print(result.stdout.strip())


def pickers():
    source = (APP / "Launcher.java").read_text(encoding="utf-8")
    constants = source[source.index("    static final int T_GAME ="):source.index("    private static final String[][] TEXTS =")]
    texts = re.search(r"    private static final String\[\]\[\] TEXTS = .*?^    };", source, re.M | re.S).group()
    methods = "\n".join(method(source, declaration) for declaration in
                         ("private void pickArchive()", "private void pickFolder(int request, File near)", "static String text(int id)"))
    probe = r'''
import java.io.File;
import java.util.*;
public final class PickerProbe {
    static class ActivityNotFoundException extends RuntimeException {
        @Override public String getMessage() { return "INTERNAL_PICKER_REASON"; }
    }
    static class Uri { }
    static class DocumentsContract { static final String EXTRA_INITIAL_URI = "initial"; }
    static class Intent {
        static final String ACTION_OPEN_DOCUMENT = "archive", ACTION_OPEN_DOCUMENT_TREE = "folder",
            CATEGORY_OPENABLE = "openable", EXTRA_MIME_TYPES = "types";
        static final int FLAG_GRANT_READ_URI_PERMISSION = 1, FLAG_GRANT_WRITE_URI_PERMISSION = 2;
        final String action; String type; final Map<String, Object> extras = new HashMap<>();
        Intent(String action) { this.action = action; }
        Intent addCategory(String category) { assert category.equals(CATEGORY_OPENABLE); return this; }
        Intent setType(String type) { this.type = type; return this; }
        void putExtra(String name, Object value) { extras.put(name, value); }
        void addFlags(int flags) { assert flags == 3; }
    }
    static final int ASK_ARCHIVE = 1, ASK_TARGET = 2, ASK_FOLDER = 3;
    static final Uri INITIAL = new Uri();
    boolean unavailable; int request, dropped; Intent intent; String failure;
    static Uri documentOf(File near) { return INITIAL; }
    void startActivityForResult(Intent value, int code) {
        intent = value; request = code;
        if (unavailable) throw new ActivityNotFoundException();
    }
    void error(String message) { failure = message; }
    void dropArchive() { ++dropped; }
''' + constants + texts + methods + r'''
    public static void main(String[] args) {
        Set<String> messages = new HashSet<>();
        for (String language : new String[] {"en", "ru", "de", "pl"}) {
            Locale.setDefault(Locale.forLanguageTag(language));
            PickerProbe p = new PickerProbe(); p.unavailable = true;
            p.pickArchive();
            assert p.failure != null && p.failure.length() > 30 && p.dropped == 0;
            assert !p.failure.contains("INTERNAL_PICKER_REASON");
            messages.add(p.failure); p.failure = null;
            p.pickFolder(ASK_FOLDER, null);
            assert p.failure != null && p.dropped == 0; p.failure = null;
            p.pickFolder(ASK_TARGET, new File("near"));
            assert p.failure != null && p.dropped == 1;
            p.unavailable = false; p.failure = null;
            p.pickArchive();
            assert p.failure == null && p.request == ASK_ARCHIVE && p.intent.type.equals("*/*");
            assert ((String[])p.intent.extras.get(Intent.EXTRA_MIME_TYPES)).length == 4;
            p.pickFolder(ASK_FOLDER, null);
            assert p.failure == null && p.request == ASK_FOLDER && p.intent.action.equals(Intent.ACTION_OPEN_DOCUMENT_TREE);
            p.pickFolder(ASK_TARGET, new File("near"));
            assert p.failure == null && p.request == ASK_TARGET && p.dropped == 1;
            assert p.intent.extras.get(DocumentsContract.EXTRA_INITIAL_URI) == INITIAL;
        }
        assert messages.size() == 4;
        System.out.println("PASS: unavailable/successful archive/folder/target pickers, target release, four localized messages");
    }
}
'''
    file = OUT / "PickerProbe.java"
    file.write_text(probe, encoding="utf-8")
    run([JAVA / "javac.exe", "--release", "8", "-encoding", "UTF-8", "-d", OUT / "picker", file], "picker-build")
    run([JAVA / "java.exe", "-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8", "-ea", "-cp", OUT / "picker", "PickerProbe"], "picker-run")


def filenames():
    cases = [
        ("Тургор/данные.ogg".encode("cp866"), 0, 0, None, False, "Тургор/данные.ogg"),
        ("data/каталог/озвучка.ogg".encode("cp866"), 11, 0, None, False, "data/каталог/озвучка.ogg"),
        (b"data/\xe1\x82\xa3.txt", 14, 0, None, False, b"data/\xe1\x82\xa3.txt".decode("cp866")),
        ("data/Тургор.txt".encode("utf-8"), 0, 0x800, None, False, "data/Тургор.txt"),
        ("data/Тургор.txt".encode("utf-8"), 3, 0, None, False, "data/Тургор.txt"),
        (b"raw-name.txt", 0, 0, "data/оригинал.txt", False, "data/оригинал.txt"),
        ("data/имя.txt".encode("cp866"), 0, 0, "ignored.txt", True, "data/имя.txt"),
        ("data/².txt".encode("cp437"), 3, 0, None, False, "data/².txt"),
        (b"data/ascii.txt", 0, 0, None, False, "data/ascii.txt"),
    ]
    entries = [dict(name=raw, data=b"x", method=0, flags=flags, **({"unicode": unicode} if unicode else {}))
               for raw, host, flags, unicode, invalid, expected in cases]
    archive = OUT / "names.zip"
    write_zip(archive, entries)
    contents = bytearray(archive.read_bytes())
    offset = contents.index(b"PK\x01\x02")
    for raw, host, flags, unicode, invalid, expected in cases:
        assert contents[offset:offset + 4] == b"PK\x01\x02"
        struct.pack_into("<H", contents, offset + 4, host << 8 | 63)
        name_size, extra_size, comment_size = struct.unpack_from("<HHH", contents, offset + 28)
        if invalid:
            contents[offset + 46 + name_size + 5] ^= 1
        offset += 46 + name_size + extra_size + comment_size
    archive.write_bytes(contents)
    expected = ", ".join(json.dumps(case[-1], ensure_ascii=True) for case in cases)
    probe = '''package org.thevoid.port;
import java.io.RandomAccessFile;
import java.io.InputStream;
public final class FilenameProbe {
    public static void main(String[] args) throws Exception {
        String[] expected = {''' + expected + '''};
        try (Zip zip = new Zip(new RandomAccessFile(args[0], "r").getChannel())) {
            assert zip.entries.size() == expected.length;
            for (int i = 0; i < expected.length; ++i) {
                Zip.Entry entry = zip.entries.get(i);
                assert entry.name.equals(expected[i]) : "filename at entry " + i;
                try (InputStream in = zip.open(entry)) { assert in.read() == 'x' && in.read() == -1; }
            }
        }
        System.out.println("PASS: CP866 host policy, ambiguous UTF-8 bytes, UTF-8 flag, Unicode-field CRC, CP437 fallback, ASCII and payloads");
    }
}
'''
    file = OUT / "FilenameProbe.java"
    file.write_text(probe, encoding="utf-8")
    sources = [APP / name for name in ("Zip.java", "Unpacker.java", "Deflate64.java")]
    run([JAVA / "javac.exe", "--release", "8", "-encoding", "UTF-8", "-d", OUT / "zip", *sources, file], "zip-build")
    run([JAVA / "java.exe", "-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8", "-ea", "-cp", OUT / "zip", "org.thevoid.port.FilenameProbe", archive], "zip-run")


if __name__ == "__main__":
    failed = []
    for label, check in (("pickers", pickers), ("ZIP names", filenames)):
        try:
            check()
        except AssertionError as error:
            failed.append(label)
            print(label + ": FAIL\n" + str(error))
    print("Evidence: " + str(OUT))
    assert not failed, failed
