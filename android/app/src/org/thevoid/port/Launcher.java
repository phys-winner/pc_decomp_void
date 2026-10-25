package org.thevoid.port;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.res.ColorStateList;
import android.database.Cursor;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.provider.DocumentsContract;
import android.provider.OpenableColumns;
import android.system.Os;
import android.view.Gravity;
import android.view.View;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** The game's launcher: where the game's files are — a ZIP archive of the
 *  game, unpacked into a folder the player chooses in the system's picker,
 *  or a folder that holds them — skipping the opening videos, and the start.
 *  The game runs in GameActivity, which takes the chosen folder. */
public final class Launcher extends Activity {
    static final String EXTRA_GAME = "game", PREFS = "launcher";
    private static final int ASK_ARCHIVE = 1, ASK_TARGET = 2, ASK_FOLDER = 3, ASK_STORAGE = 4;
    private static final String EXTERNAL = "com.android.externalstorage.documents",
        DOWNLOADS = "com.android.providers.downloads.documents";
    private static final int GOLD = Color.rgb(255, 205, 50), GOLD_DARK = Color.rgb(170, 125, 20),
        CELL = Color.rgb(50, 50, 60), GREY = Color.rgb(165, 165, 178), RED = Color.rgb(255, 125, 110);
    /** On the screen: UnpackService tells the end of an unpacking in a notification otherwise. */
    static volatile boolean visible;

    private SharedPreferences prefs;
    private Settings settings;
    private File base;   /* /sdcard/TheVoid: the player's profile, the development images */
    private File game;   /* the chosen game's root; null: none yet */
    private final Handler handler = new Handler(Looper.getMainLooper());
    /* An archive between its choice and its unpacking. */
    private Uri archive;
    private File archiveFile;
    private Unpacker.Plan plan;
    private String busy;   /* reading an archive, looking for the game in a folder */
    private boolean storageRefused, storageSeen;
    private File cleanupScanning;
    private GameCleanup.Plan cleanupPlan;
    private int cleanupGeneration;

    private TextView gameTitle, gamePath, note, progressTarget, progressText;
    private LinearLayout copies;
    private ProgressBar progress;
    private View progressBox, permissionBox, optionsBox, play, archiveButton, folderButton, stopButton;
    private TextView cleanupButton;
    private FrameLayout skipBox;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        if (GameActivity.running) {   /* the lifted game runs once per process: back to it */
            startActivity(new Intent(this, GameActivity.class));
            finish();
            return;
        }
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        settings = new Settings(this);
        base = baseDir();
        getWindow().setStatusBarColor(Color.rgb(16, 26, 37));
        getWindow().setNavigationBarColor(Color.rgb(3, 5, 8));
        build();
        if (!storage()) askStorage();
        refresh();
    }

    @Override protected void onResume() {
        super.onResume();
        visible = true;
        UnpackService.cancelResult(this);
        if (Unpacker.current != null) {
            handler.removeCallbacks(watcher);
            handler.post(watcher);
        }
        if (prefs != null) refresh();
    }

    @Override protected void onPause() {
        visible = false;
        super.onPause();
    }

    @Override protected void onDestroy() {
        handler.removeCallbacks(watcher);
        if (!isChangingConfigurations()) dropArchive();
        super.onDestroy();
    }

    /* ------------------------------------------------------------ choosing */

    /** The folder the game runs from: the launcher's (or a tool's) choice,
     *  else, as before the launcher, the release last chosen in
     *  /sdcard/TheVoid or its first copy there; null if none. */
    static File chosenGame(Context c, Intent intent) {
        String extra = intent != null ? intent.getStringExtra(EXTRA_GAME) : null;
        if (extra != null && Unpacker.isVoid(new File(extra))) return new File(extra);
        String saved = c.getSharedPreferences(PREFS, MODE_PRIVATE).getString("game", null);
        if (saved != null && Unpacker.isVoid(new File(saved))) return new File(saved);
        File base = baseDir();
        String last = c.getSharedPreferences("GameActivity", MODE_PRIVATE).getString("release", null);
        if (last != null && Unpacker.isVoid(new File(base, last))) return new File(base, last);
        List<File> found = copies(base);
        return found.isEmpty() ? null : found.get(0);
    }

    static File baseDir() { return new File(Environment.getExternalStorageDirectory(), "TheVoid"); }

    /** The copies tools/push_game_data.py puts in /sdcard/TheVoid: game, game-*. */
    static List<File> copies(File base) {
        List<File> out = new ArrayList<>();
        File[] dirs = base.listFiles();
        if (dirs == null) return out;
        Arrays.sort(dirs);
        for (File d : dirs) if (d.isDirectory() && d.getName().startsWith("game") && Unpacker.isVoid(d)) out.add(d);
        return out;
    }

    private void select(File root) {
        game = root;
        prefs.edit().putString("game", root.getAbsolutePath()).apply();
        note(null, false);
        refresh();
    }

    private void pickArchive() {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
        i.putExtra(Intent.EXTRA_MIME_TYPES, new String[] {"application/zip", "application/x-zip-compressed",
            "application/x-zip", "application/octet-stream"});
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        startActivityForResult(i, ASK_ARCHIVE);
    }

    private void pickFolder(int request, File near) {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        Uri initial = near != null ? documentOf(near) : null;
        if (initial != null) i.putExtra(DocumentsContract.EXTRA_INITIAL_URI, initial);
        startActivityForResult(i, request);
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        Uri uri = result == RESULT_OK && data != null ? data.getData() : null;
        if (uri == null) {
            if (request == ASK_TARGET) dropArchive();
            return;
        }
        if (request == ASK_ARCHIVE) readArchive(uri);
        else if (request == ASK_TARGET) chooseTarget(uri);
        else if (request == ASK_FOLDER) chooseFolder(uri);
    }

    private void readArchive(Uri uri) {
        dropArchive();
        final ParcelFileDescriptor fd;
        try {
            fd = getContentResolver().openFileDescriptor(uri, "r");
            if (fd == null) throw new IOException(uri.toString());
        } catch (Exception e) {
            error(fmt(E_IO, e.getMessage()));
            return;
        }
        final File file = fileOf(uri, fd);
        setBusy(text(T_READING));
        new Thread(() -> {
            Unpacker.Plan p = null;
            String failure = null;
            FileInputStream in = new ParcelFileDescriptor.AutoCloseInputStream(fd);
            try {
                p = Unpacker.plan(new Zip(in.getChannel()));
            } catch (Unpacker.Failure f) {
                failure = describe(f);
            } catch (IOException | RuntimeException e) {
                failure = fmt(E_IO, String.valueOf(e.getMessage()));
            }
            if (p == null) close(in);
            final Unpacker.Plan read = p;
            final String error = failure;
            handler.post(() -> {
                setBusy(null);
                if (isFinishing() || isDestroyed()) {
                    if (read != null) close(read.zip);
                    return;
                }
                if (error != null) {
                    error(error);
                    return;
                }
                archive = uri;
                archiveFile = file;
                plan = read;
                askTarget();
            });
        }, "archive").start();
    }

    private String archiveLabel() {
        File named = new File(plan.root.isEmpty() ? String.valueOf(archiveName(archive, archiveFile)) : plan.root);
        return new GameActivity.Release(named, plan.info, plan.languages).label();
    }

    /** Before the picker: what the archive holds and how the folder is used. */
    private void askTarget() {
        dialog().setTitle(text(T_TARGET_TITLE))
            .setMessage(fmt(T_TARGET_BODY, archiveLabel(), plan.files.size(), size(plan.size)))
            .setPositiveButton(text(T_CHOOSE), (d, w) -> pickFolder(ASK_TARGET, archiveFile != null ? archiveFile.getParentFile() : null))
            .setNegativeButton(text(T_CANCEL), (d, w) -> dropArchive())
            .setOnCancelListener(d -> dropArchive())
            .show();
    }

    /** The folder chosen for the game: the collision check (Unpacker.target) and space. */
    private void chooseTarget(Uri tree) {
        if (plan == null) {
            error(text(E_NO_ARCHIVE));
            return;
        }
        File chosen = treePath(tree);
        if (chosen == null || !chosen.isDirectory()) {
            error(text(E_NO_PATH));
            dropArchive();
            return;
        }
        File target;
        try {
            target = Unpacker.target(chosen);
        } catch (Unpacker.Failure f) {
            error(describe(f));
            dropArchive();
            return;
        }
        long free = chosen.getUsableSpace();
        boolean holdsGame = Unpacker.isRoot(chosen) && Unpacker.isVoid(chosen);
        StringBuilder body = new StringBuilder(fmt(T_CONFIRM_BODY, archiveLabel(), size(plan.size), target.getPath(), size(free)));
        if (!target.equals(chosen)) body.append("\n\n").append(fmt(T_TAKEN, target.getName()));
        if (holdsGame) body.append("\n\n").append(text(T_HAS_GAME));
        boolean room = free >= plan.size + (64L << 20);
        if (!room) body.append("\n\n").append(fmt(E_SPACE, size(plan.size), size(free)));
        AlertDialog.Builder b = dialog().setTitle(text(T_CONFIRM_TITLE)).setMessage(body)
            .setNegativeButton(text(T_CANCEL), (d, w) -> dropArchive())
            .setOnCancelListener(d -> dropArchive());
        if (room) b.setPositiveButton(text(T_UNPACK), (d, w) -> unpack(target));
        if (holdsGame) {
            b.setNeutralButton(text(T_USE), (d, w) -> { dropArchive(); select(chosen); });
        } else {
            b.setNeutralButton(text(T_OTHER), (d, w) -> pickFolder(ASK_TARGET, chosen));
        }
        b.show();
    }

    private void chooseFolder(Uri tree) {
        File dir = treePath(tree);
        if (dir == null || !dir.isDirectory()) {
            error(text(E_NO_PATH));
            return;
        }
        setBusy(text(T_SEARCHING));
        new Thread(() -> {
            File root = Unpacker.findRoot(dir);
            boolean isVoid = root != null && Unpacker.isVoid(root);
            handler.post(() -> {
                setBusy(null);
                if (root == null) error(text(E_FOLDER));
                else if (!isVoid) error(fmt(E_FOLDER_NOT_VOID, root.getPath()));
                else select(root);
            });
        }, "folder").start();
    }

    private void dropArchive() {
        if (plan != null) close(plan.zip);
        plan = null;
        archive = null;
        archiveFile = null;
    }

    /* ----------------------------------------------------------- unpacking */

    private void unpack(File target) {
        if (plan == null || Unpacker.current != null) return;
        Unpacker.Job job = new Unpacker.Job(plan, target, archive.toString(), archiveFile);
        plan = null;   /* the job owns the archive now */
        archive = null;
        archiveFile = null;
        prefs.edit().putString("unpacking", target.getAbsolutePath()).putBoolean("unpackingCreated", job.created).apply();
        Unpacker.current = job;
        new Thread(job, "unpack").start();
        startForegroundService(new Intent(this, UnpackService.class));
        note(null, false);
        handler.post(watcher);
    }

    /* The end is taken on the screen; away from it UnpackService tells it
     * in a notification and onResume takes it. */
    private final Runnable watcher = new Runnable() {
        @Override public void run() {
            Unpacker.Job job = Unpacker.current;
            showProgress(job);
            if (job == null) return;
            if (!job.finished) handler.postDelayed(this, 250);
            else if (visible) finished(job);
        }
    };

    private void showProgress(Unpacker.Job job) {
        progressBox.setVisibility(job != null && !job.finished ? View.VISIBLE : View.GONE);
        if (job != null) {
            progressTarget.setText(job.target.getPath());
            progress.setProgress((int) (job.done * 1000 / Math.max(1, job.plan.size)));
            progressText.setText(progressText(job.done, job.plan.size) + (job.file.isEmpty() ? "" : " · " + job.file));
            stopButton.setEnabled(!job.cancelled);
        }
        enable();
    }

    private void finished(Unpacker.Job job) {
        Unpacker.current = null;
        prefs.edit().remove("unpacking").remove("unpackingCreated").apply();
        UnpackService.cancelResult(this);
        showProgress(null);
        if (job.failure == null) {
            select(job.target);
            askDelete(job);
        } else if (job.failure.code == Unpacker.CANCELLED) {
            note(text(T_STOPPED), false);
        } else {
            dialog().setTitle(text(T_FAILED_TITLE)).setMessage(describe(job.failure))
                .setPositiveButton(text(T_OK), null).show();
        }
    }

    private void askStop() {
        Unpacker.Job job = Unpacker.current;
        if (job == null || job.finished) return;
        dialog().setMessage(text(T_STOP_ASK))
            .setPositiveButton(text(T_STOP), (d, w) -> job.cancelled = true)
            .setNegativeButton(text(T_CONTINUE), null)
            .show();
    }

    private void askDelete(Unpacker.Job job) {
        Uri uri = Uri.parse(job.source);
        String name = archiveName(uri, job.sourceFile);
        long length = archiveSize(uri, job.sourceFile);
        dialog().setTitle(text(T_UNPACKED_TITLE))
            .setMessage(fmt(T_DELETE_ASK, job.target.getPath(), name, length >= 0 ? size(length) : "?"))
            .setPositiveButton(text(T_DELETE), (d, w) -> {
                boolean deleted = false;
                try {
                    deleted = DocumentsContract.deleteDocument(getContentResolver(), uri);
                } catch (Exception e) {
                    android.util.Log.i("TheVoid", "launcher: the archive's document: " + e);
                }
                if (!deleted && job.sourceFile != null) deleted = job.sourceFile.delete() || !job.sourceFile.exists();
                android.util.Log.i("TheVoid", "launcher: archive " + name + (deleted ? " deleted" : " not deleted"));
                Toast.makeText(this, text(deleted ? T_DELETED : T_NOT_DELETED), Toast.LENGTH_LONG).show();
            })
            .setNegativeButton(text(T_KEEP), null)
            .show();
    }

    /** An unpacking that ended with the process (Android ended it, the
     *  phone restarted): its hidden folder goes, and a folder it made. */
    private void cleanStale() {
        String stale = prefs.getString("unpacking", null);
        if (stale == null || Unpacker.current != null) return;
        File target = new File(stale);
        Unpacker.clean(new File(target, Unpacker.TEMP), prefs.getBoolean("unpackingCreated", false) ? target : null);
        prefs.edit().remove("unpacking").remove("unpackingCreated").apply();
        android.util.Log.i("TheVoid", "launcher: an interrupted unpacking into " + stale + " removed");
        note(text(T_INTERRUPTED), false);
    }

    /* ---------------------------------------------------------------- play */

    private void play() {
        if (game == null || Unpacker.current != null || busy != null) return;
        if (!Unpacker.isRoot(game) || !Unpacker.isVoid(game)) {
            error(text(E_FOLDER));
            game = null;
            refresh();
            return;
        }
        GameActivity.Release release = new GameActivity.Release(game);
        if (!NativeLibrary.available(this, release.library)) {
            error(fmt(E_LIBRARY, release.label()));
            return;
        }
        if (!Images.available(this, base, release.images)) {
            error(fmt(E_IMAGES, release.images));
            return;
        }
        prefs.edit().putString("game", game.getAbsolutePath()).apply();
        android.util.Log.i("TheVoid", "launcher: playing " + game + ", opening videos " + (skipIntro() ? "skipped" : "shown"));
        startActivity(new Intent(this, GameActivity.class).putExtra(EXTRA_GAME, game.getAbsolutePath()));
        finish();
    }

    /* The port's PortSkipIntro, which the 2009 releases' patched
     * world\main_menu.bin reads from the game's settings (the player's copy,
     * which the game's options change too); the layer's preference makes
     * the copy's first value. */
    private File gameSettings() { return new File(base, "userdata/overrides/settings.xml"); }

    private boolean skipIntro() {
        String v = Profile.prop(GameActivity.Release.read(gameSettings()), "PortSkipIntro");
        return v.isEmpty() ? settings.skipIntro : !v.equals("0");
    }

    private void setSkipIntro(boolean on) {
        settings.skipIntro = on;
        settings.save();
        if (gameSettings().isFile()) {
            Map<String, String> props = new HashMap<>();
            props.put("PortSkipIntro", on ? "1" : "0");
            Profile.setProps(gameSettings(), props);
        }
    }

    private void refreshCleanup() {
        final File selected = storage() ? game : null;
        if (selected != null && selected.equals(cleanupScanning)) return;
        final int request = ++cleanupGeneration;
        cleanupPlan = null;
        cleanupScanning = selected;
        cleanupButton.setVisibility(View.GONE);
        if (selected == null) return;
        new Thread(() -> {
            GameCleanup.Plan found = null;
            try { found = GameCleanup.scan(selected); }
            catch (IOException | RuntimeException e) { android.util.Log.w("TheVoid", "cleanup preview: " + selected, e); }
            final GameCleanup.Plan result = found;
            handler.post(() -> {
                if (isFinishing() || isDestroyed() || request != cleanupGeneration || !selected.equals(game)) return;
                cleanupScanning = null;
                cleanupPlan = result;
                enable();
            });
        }, "cleanup-preview").start();
    }

    private void scanCleanup() {
        if (game == null || busy != null || Unpacker.current != null) return;
        final File selected = game;
        setBusy(text(T_CLEAN_SCAN));
        new Thread(() -> {
            GameCleanup.Plan plan = null;
            String failure = null;
            try { plan = GameCleanup.scan(selected); }
            catch (IOException | RuntimeException e) { failure = fmt(E_IO, String.valueOf(e.getMessage())); }
            final GameCleanup.Plan found = plan;
            final String problem = failure;
            handler.post(() -> {
                setBusy(null);
                if (isFinishing() || isDestroyed()) return;
                if (problem != null) { error(problem); return; }
                cleanupPlan = found;
                enable();
                if (found.files.isEmpty()) { note(text(T_CLEAN_EMPTY), false); return; }
                StringBuilder list = new StringBuilder(fmt(T_CLEAN_PREVIEW, found.root, found.files.size(), size(found.bytes)));
                for (GameCleanup.Entry file : found.files)
                    list.append('\n').append(file.file.getAbsolutePath().substring(found.root.getAbsolutePath().length() + 1))
                        .append(" — ").append(size(file.size));
                ScrollView scroll = new ScrollView(this);
                TextView contents = label(list.toString(), 14, Color.WHITE);
                contents.setPadding(dp(18), dp(8), dp(18), dp(8));
                scroll.addView(contents);
                dialog().setTitle(text(T_CLEAN)).setView(scroll)
                    .setPositiveButton(text(T_DELETE), (d, w) -> deleteExtras(found))
                    .setNegativeButton(text(T_CANCEL), null).show();
            });
        }, "cleanup-scan").start();
    }

    private void deleteExtras(GameCleanup.Plan plan) {
        ++cleanupGeneration;
        cleanupScanning = null;
        cleanupPlan = null;
        setBusy(text(T_CLEAN_BUSY));
        new Thread(() -> {
            long bytes = 0;
            String failure = null;
            try { bytes = GameCleanup.delete(plan); }
            catch (IOException | RuntimeException e) { failure = fmt(E_IO, String.valueOf(e.getMessage())); }
            final long freed = bytes;
            final String problem = failure;
            handler.post(() -> {
                setBusy(null);
                if (isFinishing() || isDestroyed()) return;
                if (problem != null) error(problem); else note(fmt(T_CLEAN_DONE, size(freed)), false);
                refreshCleanup();
            });
        }, "cleanup").start();
    }

    /* ---------------------------------------------------------- permission */

    private boolean storage() {
        return checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
            && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED;
    }

    private void askStorage() {
        if (storageRefused && !shouldShowRequestPermissionRationale(Manifest.permission.WRITE_EXTERNAL_STORAGE)) {
            /* "Don't ask again": only the app's settings can allow it now. */
            startActivity(new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                Uri.fromParts("package", getPackageName(), null)));
            return;
        }
        requestPermissions(new String[] {Manifest.permission.READ_EXTERNAL_STORAGE,
            Manifest.permission.WRITE_EXTERNAL_STORAGE}, ASK_STORAGE);
    }

    @Override public void onRequestPermissionsResult(int request, String[] permissions, int[] results) {
        if (request != ASK_STORAGE) return;
        if (!storage()) storageRefused = true;
        refresh();
    }

    /* ---------------------------------------------------------------- paths */

    /** A folder chosen in the system's picker as a file: the game reads its
     *  files by path (the storage permission), so only folders of the
     *  phone's own storage do. */
    static File treePath(Uri tree) {
        try {
            return documentPath(tree.getAuthority(), DocumentsContract.getTreeDocumentId(tree));
        } catch (RuntimeException e) {
            return null;
        }
    }

    /** "primary:Download/x" of the storage provider, "raw:/storage/..." of Downloads. */
    static File documentPath(String authority, String id) {
        if (id == null) return null;
        if (DOWNLOADS.equals(authority) && id.startsWith("raw:")) return new File(id.substring(4));
        if (!EXTERNAL.equals(authority)) return null;
        int colon = id.indexOf(':');
        String volume = colon < 0 ? id : id.substring(0, colon), path = colon < 0 ? "" : id.substring(colon + 1);
        File root = volume.equals("primary") ? Environment.getExternalStorageDirectory()
            : volume.equals("home") ? new File(Environment.getExternalStorageDirectory(), Environment.DIRECTORY_DOCUMENTS)
            : new File("/storage", volume);
        return path.isEmpty() ? root : new File(root, path);
    }

    /** The storage provider's document of a folder (where the picker opens). */
    static Uri documentOf(File dir) {
        String storage = Environment.getExternalStorageDirectory().getPath(), p = dir.getPath(), id;
        if (p.equals(storage)) {
            id = "primary:";
        } else if (p.startsWith(storage + "/")) {
            id = "primary:" + p.substring(storage.length() + 1);
        } else {
            Matcher m = Pattern.compile("^/storage/([^/]+)(?:/(.*))?$").matcher(p);
            if (!m.matches() || m.group(1).equals("emulated") || m.group(1).equals("self")) return null;
            id = m.group(1) + ":" + (m.group(2) != null ? m.group(2) : "");
        }
        return DocumentsContract.buildDocumentUri(EXTERNAL, id);
    }

    /** The archive the picker opened as a file, if it is one of the
     *  phone's: by its document, else by the descriptor the provider opened
     *  (in the provider's view of the storage), the same size. */
    private static File fileOf(Uri uri, ParcelFileDescriptor fd) {
        long size = -1;
        try {
            size = Os.fstat(fd.getFileDescriptor()).st_size;
        } catch (Exception e) {
            /* compared only when known */
        }
        List<String> candidates = new ArrayList<>();
        try {
            File f = documentPath(uri.getAuthority(), DocumentsContract.getDocumentId(uri));
            if (f != null) candidates.add(f.getPath());
        } catch (RuntimeException e) {
            /* not a document */
        }
        try {
            String link = Os.readlink("/proc/self/fd/" + fd.getFd());
            candidates.add(link);
            Matcher m;
            if ((m = Pattern.compile("^/data/media/(\\d+)/(.*)$").matcher(link)).matches())
                candidates.add("/storage/emulated/" + m.group(1) + "/" + m.group(2));
            if ((m = Pattern.compile("^/mnt/[a-z_]+/\\d+/emulated/(\\d+)/(.*)$").matcher(link)).matches())
                candidates.add("/storage/emulated/" + m.group(1) + "/" + m.group(2));
            if ((m = Pattern.compile("^/mnt/[a-z_]+/\\d+/([0-9A-Fa-f]{4}-[0-9A-Fa-f]{4})/(.*)$").matcher(link)).matches())
                candidates.add("/storage/" + m.group(1) + "/" + m.group(2));
            if ((m = Pattern.compile("^/mnt/media_rw/([^/]+)/(.*)$").matcher(link)).matches())
                candidates.add("/storage/" + m.group(1) + "/" + m.group(2));
        } catch (Exception e) {
            /* no such link */
        }
        for (String c : candidates) {
            File f = new File(c);
            if (f.isFile() && (size < 0 || f.length() == size)) return f;
        }
        return null;
    }

    private String archiveName(Uri uri, File file) {
        String name = query(uri, OpenableColumns.DISPLAY_NAME);
        return name != null ? name : file != null ? file.getName() : "?";
    }

    private long archiveSize(Uri uri, File file) {
        String n = query(uri, OpenableColumns.SIZE);
        try {
            if (n != null) return Long.parseLong(n);
        } catch (NumberFormatException e) {
            /* the file's, then */
        }
        return file != null && file.isFile() ? file.length() : -1;
    }

    private String query(Uri uri, String column) {
        if (uri == null) return null;
        try (Cursor c = getContentResolver().query(uri, new String[] {column}, null, null, null)) {
            if (c != null && c.moveToFirst() && !c.isNull(0)) return c.getString(0);
        } catch (Exception e) {
            /* the document is gone or not ours any more */
        }
        return null;
    }

    private static void close(java.io.Closeable c) {
        try {
            c.close();
        } catch (IOException e) {
            /* it was only read */
        }
    }

    /* ------------------------------------------------------------------ UI */

    private int dp(float v) { return Math.round(v * getResources().getDisplayMetrics().density); }

    private void build() {
        FrameLayout root = new FrameLayout(this);
        root.setBackground(new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,
            new int[] {Color.rgb(16, 26, 37), Color.rgb(11, 18, 28), Color.rgb(3, 5, 8)}));
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        LinearLayout column = new LinearLayout(this) {
            @Override protected void onMeasure(int w, int h) {
                int max = dp(560);
                if (MeasureSpec.getSize(w) > max) w = MeasureSpec.makeMeasureSpec(max, MeasureSpec.EXACTLY);
                super.onMeasure(w, h);
            }
        };
        column.setOrientation(LinearLayout.VERTICAL);
        column.setPadding(dp(16), dp(20), dp(16), dp(24));

        LinearLayout head = new LinearLayout(this);
        head.setGravity(Gravity.CENTER);
        ImageView icon = new ImageView(this);
        icon.setImageDrawable(getApplicationInfo().loadIcon(getPackageManager()));
        head.addView(icon, new LinearLayout.LayoutParams(dp(64), dp(64)));
        TextView title = new TextView(this);
        title.setText("The Void");
        title.setTextColor(Color.WHITE);
        title.setTextSize(30);
        title.setTypeface(Typeface.SERIF);
        title.setPadding(dp(12), 0, 0, 0);
        head.addView(title);
        column.addView(head, new LinearLayout.LayoutParams(-1, -2));

        LinearLayout card = card(column);
        card.addView(heading(text(T_GAME)));
        gameTitle = label("", 18, Color.WHITE);
        gameTitle.setTypeface(Typeface.DEFAULT_BOLD);
        card.addView(gameTitle);
        gamePath = label("", 13, GREY);
        card.addView(gamePath);
        LinearLayout buttons = new LinearLayout(this);
        buttons.setPadding(0, dp(10), 0, dp(4));
        archiveButton = button(text(T_ARCHIVE), false, this::pickArchive);
        folderButton = button(text(T_FOLDER), false, () -> pickFolder(ASK_FOLDER, base.isDirectory() ? base : null));
        LinearLayout.LayoutParams half = new LinearLayout.LayoutParams(0, dp(48), 1);
        half.setMargins(0, 0, dp(6), 0);
        buttons.addView(archiveButton, half);
        half = new LinearLayout.LayoutParams(0, dp(48), 1);
        half.setMargins(dp(6), 0, 0, 0);
        buttons.addView(folderButton, half);
        card.addView(buttons);
        card.addView(label(text(T_HINT), 13, GREY));
        copies = new LinearLayout(this);
        copies.setOrientation(LinearLayout.VERTICAL);
        card.addView(copies);

        LinearLayout box = card(column);
        progressBox = box;
        box.addView(heading(text(T_UNPACKING_TITLE)));
        progressTarget = label("", 13, GREY);
        box.addView(progressTarget);
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setMax(1000);
        progress.setProgressTintList(ColorStateList.valueOf(GOLD));
        box.addView(progress, new LinearLayout.LayoutParams(-1, dp(18)));
        progressText = label("", 14, Color.WHITE);
        box.addView(progressText);
        stopButton = button(text(T_STOP), false, this::askStop);
        LinearLayout.LayoutParams stop = new LinearLayout.LayoutParams(-1, dp(44));
        stop.setMargins(0, dp(10), 0, 0);
        box.addView(stopButton, stop);
        progressBox.setVisibility(View.GONE);

        LinearLayout options = card(column);
        optionsBox = options;
        skipBox = new FrameLayout(this);
        options.addView(skipBox);
        cleanupButton = button(text(T_CLEAN), false, this::scanCleanup);
        cleanupButton.setVisibility(View.GONE);
        options.addView(cleanupButton, new LinearLayout.LayoutParams(-1, dp(48)));

        LinearLayout permission = card(column);
        permissionBox = permission;
        permission.addView(label(text(T_PERMISSION), 15, Color.WHITE));
        LinearLayout.LayoutParams allow = new LinearLayout.LayoutParams(-1, dp(44));
        allow.setMargins(0, dp(10), 0, 0);
        permission.addView(button(text(T_ALLOW), false, this::askStorage), allow);

        note = label("", 14, GOLD);
        note.setPadding(dp(4), dp(12), dp(4), 0);
        note.setVisibility(View.GONE);
        column.addView(note);

        play = button(text(T_PLAY), true, this::play);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, dp(60));
        lp.setMargins(0, dp(18), 0, 0);
        column.addView(play, lp);

        scroll.addView(column, new FrameLayout.LayoutParams(-1, -2, Gravity.CENTER_HORIZONTAL));
        root.addView(scroll, new FrameLayout.LayoutParams(-1, -1));
        setContentView(root);
    }

    private void refresh() {
        boolean files = storage();
        if (files && !storageSeen) {   /* now (or at last, from the app's settings) */
            storageSeen = true;
            cleanStale();
            if (game == null) game = chosenGame(this, null);
        }
        permissionBox.setVisibility(files ? View.GONE : View.VISIBLE);
        if (game != null) {
            gameTitle.setText(files ? new GameActivity.Release(game).label() : game.getName());
            gameTitle.setTextColor(Color.WHITE);
            gamePath.setText(game.getPath());
            gamePath.setVisibility(View.VISIBLE);
        } else {
            gameTitle.setText(text(T_NONE));
            gameTitle.setTextColor(GREY);
            gamePath.setVisibility(View.GONE);
        }
        copies.removeAllViews();
        List<File> found = files ? copies(base) : new ArrayList<>();
        if (!found.isEmpty() && !(found.size() == 1 && found.get(0).equals(game))) {
            copies.addView(heading(text(T_FOUND)));
            for (File f : found) copies.addView(copyRow(f));
        }
        skipBox.removeAllViews();
        skipBox.addView(toggle(Settings.text(Settings.T_SKIP_INTRO), files && skipIntro(), files,
            null, this::setSkipIntro));
        enable();
        refreshCleanup();
    }

    private void enable() {
        boolean idle = Unpacker.current == null && busy == null, files = storage();
        setEnabled(archiveButton, idle && files);
        setEnabled(folderButton, idle && files);
        play.setVisibility(game != null ? View.VISIBLE : View.GONE);
        optionsBox.setVisibility(game != null ? View.VISIBLE : View.GONE);
        setEnabled(play, idle && files && game != null);
        boolean extras = files && game != null && cleanupPlan != null && game.equals(cleanupPlan.root) && !cleanupPlan.files.isEmpty();
        cleanupButton.setVisibility(extras ? View.VISIBLE : View.GONE);
        if (extras) cleanupButton.setText(text(T_CLEAN) + "  ·  " + size(cleanupPlan.bytes));
        setEnabled(cleanupButton, idle && extras);
        for (int i = 0; i < copies.getChildCount(); ++i) copies.getChildAt(i).setEnabled(idle);
    }

    private static void setEnabled(View v, boolean on) {
        v.setEnabled(on);
        v.setAlpha(on ? 1f : 0.4f);
    }

    private void setBusy(String what) {
        busy = what;
        note(what, false);
        enable();
    }

    private void note(String text, boolean error) {
        note.setVisibility(text == null ? View.GONE : View.VISIBLE);
        note.setText(text);
        note.setTextColor(error ? RED : GOLD);
    }

    private void error(String text) {
        note(text, true);
        dialog().setMessage(text).setPositiveButton(text(T_OK), null).show();
    }

    private AlertDialog.Builder dialog() { return new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert); }

    private LinearLayout card(LinearLayout parent) {
        LinearLayout c = new LinearLayout(this);
        c.setOrientation(LinearLayout.VERTICAL);
        c.setPadding(dp(16), dp(10), dp(16), dp(14));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.argb(235, 18, 18, 26));
        bg.setCornerRadius(dp(14));
        bg.setStroke(dp(1), Color.argb(120, 255, 255, 255));
        c.setBackground(bg);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(14), 0, 0);
        parent.addView(c, lp);
        return c;
    }

    private TextView label(String text, float sp, int colour) {
        TextView t = new TextView(this);
        t.setText(text);
        t.setTextSize(sp);
        t.setTextColor(colour);
        t.setPadding(0, dp(4), 0, dp(2));
        return t;
    }

    private TextView heading(String text) {
        TextView t = label(text, 13, GOLD);
        t.setPadding(0, dp(8), 0, dp(2));
        return t;
    }

    private TextView button(String text, boolean primary, Runnable action) {
        TextView b = new TextView(this);
        b.setText(text);
        b.setGravity(Gravity.CENTER);
        b.setTextSize(primary ? 20 : 15);
        b.setTextColor(primary ? GOLD : Color.WHITE);
        if (primary) b.setTypeface(Typeface.DEFAULT_BOLD);
        GradientDrawable bg = new GradientDrawable();
        bg.setCornerRadius(dp(primary ? 14 : 10));
        bg.setColor(primary ? Color.rgb(60, 44, 10) : CELL);
        if (primary) bg.setStroke(dp(2), GOLD_DARK);
        b.setBackground(bg);
        b.setOnClickListener(v -> action.run());
        return b;
    }

    private View copyRow(File dir) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        row.setPadding(dp(12), dp(8), dp(12), dp(8));
        GradientDrawable bg = new GradientDrawable();
        bg.setCornerRadius(dp(10));
        bg.setColor(CELL);
        if (dir.equals(game)) bg.setStroke(dp(2), GOLD);
        row.setBackground(bg);
        row.addView(label(new GameActivity.Release(dir).label(), 15, Color.WHITE));
        row.addView(label(dir.getPath(), 12, GREY));
        row.setOnClickListener(v -> select(dir));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(6), 0, 0);
        row.setLayoutParams(lp);
        return row;
    }

    private interface BoolSink { void set(boolean v); }

    /** A label and a drawn switch, as the layer's (the platform's is near invisible on black). */
    private View toggle(String text, boolean value, boolean enabled, String why, BoolSink sink) {
        LinearLayout row = new LinearLayout(this);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(0, dp(6), 0, dp(6));
        LinearLayout words = new LinearLayout(this);
        words.setOrientation(LinearLayout.VERTICAL);
        words.addView(label(text, 15, Color.WHITE));
        if (why != null) words.addView(label(why, 12, GREY));
        row.addView(words, new LinearLayout.LayoutParams(0, -2, 1));
        final boolean[] on = {value};
        View pill = new View(this) {
            private final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);

            @Override protected void onDraw(Canvas c) {
                float w = getWidth(), h = getHeight(), r = h / 2f;
                p.setColor(on[0] ? GOLD_DARK : Color.rgb(85, 85, 95));
                c.drawRoundRect(0, 0, w, h, r, r, p);
                p.setColor(on[0] ? GOLD : Color.rgb(215, 215, 222));
                c.drawCircle(on[0] ? w - r : r, r, r * 0.8f, p);
            }
        };
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(52), dp(30));
        lp.setMargins(dp(10), 0, 0, 0);
        row.addView(pill, lp);
        row.setAlpha(enabled ? 1f : 0.45f);
        if (enabled) {
            row.setOnClickListener(v -> {
                on[0] = !on[0];
                sink.set(on[0]);
                pill.invalidate();
            });
        }
        return row;
    }

    /* --------------------------------------------------------------- texts */

    static String size(long bytes) {
        Locale l = Locale.getDefault();
        if (bytes >= 1_000_000_000L) return String.format(l, "%.1f %s", bytes / 1e9, text(T_GB));
        return String.format(l, bytes >= 10_000_000L ? "%.0f %s" : "%.1f %s", Math.max(0, bytes) / 1e6, text(T_MB));
    }

    static String progressText(long done, long total) { return fmt(T_PROGRESS, size(done), size(total)); }

    private String describe(Unpacker.Failure f) {
        switch (f.code) {
        case Unpacker.NOT_ZIP: return text(E_NOT_ZIP);
        case Unpacker.SPLIT: return text(E_SPLIT);
        case Unpacker.NO_GAME: return text(E_NO_GAME);
        case Unpacker.NOT_VOID: return fmt(E_NOT_VOID, f.detail);
        case Unpacker.UNSAFE: return fmt(E_UNSAFE, f.detail);
        case Unpacker.METHOD: return fmt(E_METHOD, f.detail);
        case Unpacker.ENCRYPTED: return text(E_ENCRYPTED);
        case Unpacker.CORRUPT: return fmt(E_CORRUPT, f.detail);
        case Unpacker.FULL: return text(E_FULL);
        case Unpacker.READ_ONLY: return fmt(E_READ_ONLY, f.detail);
        default: return fmt(E_IO, f.detail);
        }
    }

    /* The launcher speaks the phone's language (ru, de, pl; English otherwise): no release is known yet. */
    static final int T_GAME = 0, T_NONE = 1, T_ARCHIVE = 2, T_FOLDER = 3, T_HINT = 4, T_FOUND = 5, T_PLAY = 6,
        T_READING = 7, T_SEARCHING = 8, T_TARGET_TITLE = 9, T_TARGET_BODY = 10, T_CHOOSE = 11, T_CANCEL = 12,
        T_CONFIRM_TITLE = 13, T_CONFIRM_BODY = 14, T_TAKEN = 15, T_UNPACK = 16, T_OTHER = 17, T_USE = 18,
        T_UNPACKING_TITLE = 19, T_PROGRESS = 20, T_STOP = 21, T_STOP_ASK = 22, T_CONTINUE = 23, T_UNPACKED_TITLE = 24,
        T_DELETE_ASK = 25, T_DELETE = 26, T_KEEP = 27, T_DELETED = 28, T_NOT_DELETED = 29, T_FAILED_TITLE = 30,
        T_STOPPED = 31, T_INTERRUPTED = 32, T_PERMISSION = 33, T_ALLOW = 34, T_GB = 35, T_MB = 36, T_NOT_HERE = 37,
        T_OK = 38, E_NOT_ZIP = 39, E_SPLIT = 40, E_NO_GAME = 41, E_NOT_VOID = 42, E_UNSAFE = 43, E_METHOD = 44,
        E_ENCRYPTED = 45, E_CORRUPT = 46, E_FULL = 47, E_READ_ONLY = 48, E_IO = 49, E_SPACE = 50, E_NO_PATH = 51,
        E_FOLDER = 52, E_FOLDER_NOT_VOID = 53, E_IMAGES = 54, E_LIBRARY = 55, E_NO_ARCHIVE = 56, T_HAS_GAME = 57,
        T_CLEAN = 58, T_CLEAN_SCAN = 59, T_CLEAN_EMPTY = 60, T_CLEAN_PREVIEW = 61, T_CLEAN_BUSY = 62, T_CLEAN_DONE = 63;
    private static final String[][] TEXTS = {
        {"Game", "Игра", "Spiel", "Gra"},
        {"No game chosen yet", "Игра ещё не выбрана", "Noch kein Spiel gewählt", "Nie wybrano jeszcze gry"},
        {"ZIP archive…", "ZIP-архив…", "ZIP-Archiv…", "Archiwum ZIP…"},
        {"Folder…", "Папка…", "Ordner…", "Folder…"},
        {"The game's files: a ZIP archive of the game (it is unpacked) or a folder that holds them — the one with "
             + "bin\\win32\\Game.exe.",
         "Файлы игры: ZIP-архив с игрой (он будет распакован) или папка с ними — та, где лежит bin\\win32\\Game.exe.",
         "Die Dateien des Spiels: ein ZIP-Archiv des Spiels (es wird entpackt) oder ein Ordner mit ihnen — der mit "
             + "bin\\win32\\Game.exe.",
         "Pliki gry: archiwum ZIP z grą (zostanie rozpakowane) albo folder z nimi — ten, w którym jest "
             + "bin\\win32\\Game.exe."},
        {"On this phone", "На телефоне", "Auf diesem Telefon", "Na tym telefonie"},
        {"Play", "Играть", "Spielen", "Graj"},
        {"Reading the archive…", "Читаю архив…", "Das Archiv wird gelesen…", "Czytam archiwum…"},
        {"Looking for the game…", "Ищу игру…", "Das Spiel wird gesucht…", "Szukam gry…"},
        {"Where to unpack", "Куда распаковать", "Wohin entpacken", "Gdzie rozpakować"},
        {"%1$s\nFiles: %2$d, %3$s.\n\nChoose the folder for the game: an empty folder becomes the game's folder; in a "
             + "folder that holds anything, a new folder TheVoid is made.",
         "%1$s\nФайлов: %2$d, %3$s.\n\nВыберите папку для игры: пустая папка станет папкой игры, а в непустой будет "
             + "создана новая папка TheVoid.",
         "%1$s\nDateien: %2$d, %3$s.\n\nWählen Sie den Ordner für das Spiel: ein leerer Ordner wird der Ordner des "
             + "Spiels, in einem nicht leeren entsteht ein neuer Ordner TheVoid.",
         "%1$s\nPlików: %2$d, %3$s.\n\nWybierz folder na grę: pusty folder stanie się folderem gry, a w niepustym "
             + "powstanie nowy folder TheVoid."},
        {"Choose a folder", "Выбрать папку", "Ordner wählen", "Wybierz folder"},
        {"Cancel", "Отмена", "Abbrechen", "Anuluj"},
        {"Unpack the game?", "Распаковать игру?", "Spiel entpacken?", "Rozpakować grę?"},
        {"%1$s\n%2$s → %3$s\nFree there: %4$s", "%1$s\n%2$s → %3$s\nСвободно там: %4$s",
         "%1$s\n%2$s → %3$s\nDort frei: %4$s", "%1$s\n%2$s → %3$s\nWolne miejsce tam: %4$s"},
        {"The chosen folder is not empty: the game goes into a new folder %s in it.",
         "В выбранной папке уже что-то есть — игра ляжет в новую папку %s внутри неё.",
         "Der gewählte Ordner ist nicht leer: das Spiel kommt in einen neuen Ordner %s darin.",
         "Wybrany folder nie jest pusty: gra trafi do nowego folderu %s w nim."},
        {"Unpack", "Распаковать", "Entpacken", "Rozpakuj"},
        {"Another folder", "Другая папка", "Anderer Ordner", "Inny folder"},
        {"Use this folder", "Взять эту папку", "Diesen Ordner nehmen", "Użyj tego folderu"},
        {"Unpacking The Void", "Распаковка The Void", "The Void wird entpackt", "Rozpakowywanie The Void"},
        {"%1$s of %2$s", "%1$s из %2$s", "%1$s von %2$s", "%1$s z %2$s"},
        {"Stop", "Прервать", "Stoppen", "Przerwij"},
        {"Stop unpacking? What is unpacked so far is removed.",
         "Прервать распаковку? Уже распакованное будет удалено.",
         "Entpacken stoppen? Bereits Entpacktes wird gelöscht.",
         "Przerwać rozpakowywanie? To, co już rozpakowano, zostanie usunięte."},
        {"Continue", "Продолжить", "Weiter", "Kontynuuj"},
        {"The game is unpacked", "Игра распакована", "Das Spiel ist entpackt", "Gra jest rozpakowana"},
        {"The game is in %1$s.\n\nDelete the archive %2$s (%3$s)?", "Игра в папке %1$s.\n\nУдалить архив %2$s (%3$s)?",
         "Das Spiel liegt in %1$s.\n\nDas Archiv %2$s (%3$s) löschen?", "Gra jest w %1$s.\n\nUsunąć archiwum %2$s (%3$s)?"},
        {"Delete", "Удалить", "Löschen", "Usuń"},
        {"Keep", "Оставить", "Behalten", "Zostaw"},
        {"The archive is deleted", "Архив удалён", "Das Archiv ist gelöscht", "Archiwum usunięte"},
        {"The archive could not be deleted", "Не удалось удалить архив", "Das Archiv konnte nicht gelöscht werden",
         "Nie udało się usunąć archiwum"},
        {"Unpacking failed", "Распаковка не удалась", "Entpacken fehlgeschlagen", "Rozpakowywanie nie powiodło się"},
        {"Unpacking stopped; nothing is left of it", "Распаковка прервана, от неё ничего не осталось",
         "Entpacken gestoppt; davon ist nichts übrig", "Rozpakowywanie przerwane; nic po nim nie zostało"},
        {"The last unpacking was interrupted; what it had unpacked is removed",
         "Прошлая распаковка прервалась — распакованное ею удалено",
         "Das letzte Entpacken wurde unterbrochen; was es entpackt hatte, ist gelöscht",
         "Poprzednie rozpakowywanie zostało przerwane; to, co rozpakowało, usunięto"},
        {"The game reads its files and keeps its saves in the phone's storage: allow access to files.",
         "Игра читает свои файлы и хранит сохранения в памяти телефона: разрешите доступ к файлам.",
         "Das Spiel liest seine Dateien und speichert seine Spielstände im Speicher des Telefons: erlauben Sie den "
             + "Zugriff auf Dateien.",
         "Gra czyta swoje pliki i trzyma zapisy w pamięci telefonu: zezwól na dostęp do plików."},
        {"Allow", "Разрешить", "Erlauben", "Zezwól"},
        {"GB", "ГБ", "GB", "GB"},
        {"MB", "МБ", "MB", "MB"},
        {"not in this release", "нет в этой версии игры", "nicht in dieser Version", "nie w tej wersji gry"},
        {"OK", "OK", "OK", "OK"},
        {"This is not a ZIP archive, or it is damaged.", "Это не ZIP-архив, или он повреждён.",
         "Das ist kein ZIP-Archiv, oder es ist beschädigt.", "To nie jest archiwum ZIP albo jest uszkodzone."},
        {"The archive is split into parts: join them into one ZIP.", "Архив разбит на части: соберите его в один ZIP.",
         "Das Archiv ist in Teile geteilt: fügen Sie es zu einem ZIP zusammen.",
         "Archiwum jest podzielone na części: połącz je w jeden ZIP."},
        {"There is no bin\\win32\\Game.exe in the archive.", "В архиве нет bin\\win32\\Game.exe.",
         "Im Archiv ist kein bin\\win32\\Game.exe.", "W archiwum nie ma bin\\win32\\Game.exe."},
        {"The game in the archive (%s) has no data\\info.xml: it is not The Void.",
         "У игры в архиве (%s) нет data\\info.xml — это не The Void.",
         "Das Spiel im Archiv (%s) hat kein data\\info.xml: es ist nicht The Void.",
         "Gra w archiwum (%s) nie ma data\\info.xml: to nie The Void."},
        {"The archive has a path that leads out of its folder: %s", "В архиве есть путь, ведущий за пределы его папки: %s",
         "Das Archiv enthält einen Pfad, der aus seinem Ordner führt: %s",
         "Archiwum zawiera ścieżkę prowadzącą poza jego folder: %s"},
        {"The archive is packed with %s; a ZIP packed with Deflate, Deflate64 or not packed is needed.",
         "Архив сжат методом %s; нужен ZIP со сжатием Deflate, Deflate64 или без сжатия.",
         "Das Archiv ist mit %s gepackt; nötig ist ein ZIP mit Deflate, Deflate64 oder ohne Packen.",
         "Archiwum jest spakowane metodą %s; potrzebny jest ZIP z Deflate, Deflate64 lub bez kompresji."},
        {"The archive is encrypted.", "Архив зашифрован.", "Das Archiv ist verschlüsselt.", "Archiwum jest zaszyfrowane."},
        {"%s came out of the archive damaged (CRC): the archive is damaged.",
         "%s распаковался с ошибкой (CRC): архив повреждён.",
         "%s kam beschädigt aus dem Archiv (CRC): das Archiv ist beschädigt.",
         "%s rozpakował się z błędem (CRC): archiwum jest uszkodzone."},
        {"The storage ran out of space.", "В хранилище кончилось место.", "Der Speicher ist voll.",
         "Zabrakło miejsca w pamięci."},
        {"The app cannot write into %s: choose a folder in the phone's internal storage.",
         "Приложение не может писать в %s: выберите папку во внутренней памяти телефона.",
         "Die App kann nicht in %s schreiben: wählen Sie einen Ordner im internen Speicher des Telefons.",
         "Aplikacja nie może zapisywać w %s: wybierz folder w pamięci wewnętrznej telefonu."},
        {"Error: %s", "Ошибка: %s", "Fehler: %s", "Błąd: %s"},
        {"Not enough space: %1$s needed, %2$s free.", "Не хватает места: нужно %1$s, свободно %2$s.",
         "Nicht genug Platz: %1$s nötig, %2$s frei.", "Za mało miejsca: potrzeba %1$s, wolne %2$s."},
        {"This is not on the phone's storage (a cloud?): choose a file or a folder on the phone.",
         "Это не в памяти телефона (облако?): выберите файл или папку на телефоне.",
         "Das liegt nicht im Speicher des Telefons (eine Cloud?): wählen Sie eine Datei oder einen Ordner auf dem Telefon.",
         "To nie jest w pamięci telefonu (chmura?): wybierz plik lub folder na telefonie."},
        {"There is no bin\\win32\\Game.exe in this folder, above it or below it.",
         "Ни в этой папке, ни выше, ни ниже нет bin\\win32\\Game.exe.",
         "Weder in diesem Ordner noch darüber oder darunter ist bin\\win32\\Game.exe.",
         "Ani w tym folderze, ani wyżej, ani niżej nie ma bin\\win32\\Game.exe."},
        {"%s has no data\\info.xml: it is not The Void.", "В %s нет data\\info.xml — это не The Void.",
         "%s hat kein data\\info.xml: es ist nicht The Void.", "%s nie ma data\\info.xml: to nie The Void."},
        {"This APK does not carry the game's module images (%s), and they are not in /sdcard/TheVoid either.",
         "В этом APK нет образов модулей игры (%s), и в /sdcard/TheVoid их тоже нет.",
         "Diese APK enthält die Modulabbilder des Spiels nicht (%s), und in /sdcard/TheVoid sind sie auch nicht.",
         "Ten APK nie zawiera obrazów modułów gry (%s), a w /sdcard/TheVoid też ich nie ma."},
        {"This APK has no library for this release (%s).", "В этом APK нет библиотеки для этой версии игры (%s).",
         "Diese APK hat keine Bibliothek für diese Version (%s).", "Ten APK nie ma biblioteki dla tej wersji gry (%s)."},
        {"Choose the archive again.", "Выберите архив ещё раз.", "Wählen Sie das Archiv noch einmal.",
         "Wybierz archiwum jeszcze raz."},
        {"This folder already holds the game.", "В этой папке уже есть игра.", "In diesem Ordner ist das Spiel schon.",
         "W tym folderze już jest gra."},
        {"Remove extra game files…", "Удалить лишние файлы игры…", "Überflüssige Spieldateien entfernen…", "Usuń zbędne pliki gry…"},
        {"Counting extra files…", "Подсчёт лишних файлов…", "Überflüssige Dateien werden gezählt…", "Liczenie zbędnych plików…"},
        {"No extra files found", "Лишних файлов не найдено", "Keine überflüssigen Dateien gefunden", "Nie znaleziono zbędnych plików"},
        {"%1$s\nFiles: %2$d. Reclaimable: %3$s.\nGame data, saves, settings and caches are kept.\n\nRemove these files?\n",
         "%1$s\nФайлов: %2$d. Освободится: %3$s.\nДанные игры, сохранения, настройки и кэши сохраняются.\n\nУдалить эти файлы?\n",
         "%1$s\nDateien: %2$d. Frei werdend: %3$s.\nSpieldaten, Spielstände, Einstellungen und Caches bleiben.\n\nDiese Dateien löschen?\n",
         "%1$s\nPlików: %2$d. Do odzyskania: %3$s.\nDane gry, zapisy, ustawienia i pamięci podręczne pozostają.\n\nUsunąć te pliki?\n"},
        {"Removing extra files…", "Удаление лишних файлов…", "Überflüssige Dateien werden entfernt…", "Usuwanie zbędnych plików…"},
        {"Freed: %s", "Освобождено: %s", "Freigegeben: %s", "Odzyskano: %s"},
    };

    static String text(int id) {
        String lang = Locale.getDefault().getLanguage();
        int col = "ru".equals(lang) || "uk".equals(lang) || "be".equals(lang) ? 1 : "de".equals(lang) ? 2 : "pl".equals(lang) ? 3 : 0;
        return TEXTS[id][col];
    }

    static String fmt(int id, Object... args) { return String.format(Locale.getDefault(), text(id), args); }
}
