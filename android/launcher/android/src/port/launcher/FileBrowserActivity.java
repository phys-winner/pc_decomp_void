package port.launcher;

import android.app.Activity;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;
import java.io.File;
import java.io.FileInputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** The launcher's own file browser, for devices whose system picker is turned off or missing, and
 *  for players who prefer it: storage volumes, Downloads and the port's folder at the top; folders
 *  that hold the game's files and ZIP archives that can be played without unpacking are marked as
 *  the player browses. Paths need "All files access", which the launcher asks for first. */
public final class FileBrowserActivity extends Activity {
    static final String MODE = "mode", START = "start", RESULT = "path";

    private static final class Item {
        final File file;
        final String title, detail;
        final boolean folder;

        Item(File file, String title, String detail, boolean folder) {
            this.file = file;
            this.title = title;
            this.detail = detail;
            this.folder = folder;
        }
    }

    private Ui ui;
    private Spec spec;
    private int mode;
    private File current;     /* null: the list of volumes */
    private final List<Item> items = new ArrayList<>();
    private final Map<String, String> badges = new HashMap<>();
    private final ExecutorService badgeWork = Executors.newSingleThreadExecutor();
    private final Handler handler = new Handler(Looper.getMainLooper());
    private TextView path, up, select, empty;
    private LinearLayout bar;
    private ListView list;
    private Adapter adapter;
    private Object backCallback;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        ui = new Ui(this);
        spec = Spec.get(this);
        mode = getIntent().getIntExtra(MODE, Pickers.FOLDER);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackground(ui.backdrop());
        root.setPadding(ui.dp(12), ui.dp(8), ui.dp(12), ui.dp(8));
        TextView title = ui.label(Texts.t(this, mode == Pickers.ZIP ? Texts.BROWSER_ZIP : mode == Pickers.GOG ? Texts.GOG_PICK : Texts.BROWSER_FOLDER), 20, ui.text);
        title.setTypeface(ui.titleFont);
        root.addView(title);
        path = ui.label("", 12, ui.muted);
        root.addView(path);
        bar = new LinearLayout(this);
        up = ui.button("↑  " + Texts.t(this, Texts.BROWSER_UP), Ui.SECONDARY, this::up);
        select = ui.button(Texts.t(this, Texts.BROWSER_SELECT), Ui.PRIMARY, this::choose);
        select.setTextSize(15);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, -2, 1);
        bar.addView(up, lp);
        lp = new LinearLayout.LayoutParams(0, -2, 1.4f);
        lp.leftMargin = ui.dp(8);
        bar.addView(select, lp);
        lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = ui.dp(6);
        lp.bottomMargin = ui.dp(6);
        root.addView(bar, lp);
        FrameLayout frame = new FrameLayout(this);
        list = new ListView(this);
        list.setDivider(null);
        list.setDividerHeight(ui.dp(6));
        adapter = new Adapter();
        list.setAdapter(adapter);
        list.setOnItemClickListener((parent, view, position, id) -> open(items.get(position)));
        frame.addView(list);
        empty = ui.label("", 15, ui.muted);
        empty.setGravity(Gravity.CENTER);
        frame.addView(empty, new FrameLayout.LayoutParams(-1, -2, Gravity.CENTER));
        root.addView(frame, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(root);
        ui.edgeToEdge(root);
        if (Build.VERSION.SDK_INT >= 33) {
            android.window.OnBackInvokedCallback back = this::back;
            backCallback = back;
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT, back);
        }
        String start = getIntent().getStringExtra(START);
        File first = start != null ? new File(start) : null;
        while (first != null && !first.isDirectory()) first = first.getParentFile();
        if (first == null) {
            String last = State.get(this, State.CHOICES, "browser.last", "");
            if (!last.isEmpty() && new File(last).isDirectory()) first = new File(last);
        }
        show(first);
    }

    @Override protected void onResume() {
        super.onResume();
        show(current);
    }

    @Override protected void onDestroy() {
        badgeWork.shutdownNow();
        if (Build.VERSION.SDK_INT >= 33 && backCallback != null)
            getOnBackInvokedDispatcher().unregisterOnBackInvokedCallback((android.window.OnBackInvokedCallback) backCallback);
        super.onDestroy();
    }

    @SuppressWarnings("deprecation")
    @Override public void onBackPressed() { back(); }

    private void back() {
        if (current == null) { setResult(RESULT_CANCELED); finish(); }
        else up();
    }

    private void up() {
        if (current == null) return;
        for (Storage.Volume v : Storage.volumes(this)) if (v.root.equals(current)) { show(null); return; }
        File parent = current.getParentFile();
        show(parent != null && parent.canRead() ? parent : null);
    }

    private void choose() {
        if (current == null || mode != Pickers.FOLDER) return;
        State.put(this, State.CHOICES, "browser.last", current.getAbsolutePath());
        setResult(RESULT_OK, new Intent().putExtra(RESULT, current.getAbsolutePath()));
        finish();
    }

    private void open(Item item) {
        if (item.folder) { show(item.file); return; }
        State.put(this, State.CHOICES, "browser.last", item.file.getParent());
        setResult(RESULT_OK, new Intent().putExtra(RESULT, item.file.getAbsolutePath()));
        finish();
    }

    private void show(File folder) {
        items.clear();
        empty.setText("");
        boolean access = Storage.allFiles(this);
        if (folder == null || !access) {
            current = null;
            path.setText(access ? "" : Texts.t(this, Texts.PERM_FILES));
            for (Storage.Volume v : Storage.volumes(this))
                items.add(new Item(v.root, v.title, v.root.getPath() + " · " + Texts.fmt(this, Texts.FREE, Texts.size(this, v.root.getUsableSpace())), true));
            File downloads = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
            if (downloads.isDirectory()) items.add(new Item(downloads, Texts.t(this, Texts.DOWNLOADS), downloads.getPath(), true));
            File port = spec.storageRoot();
            if (!spec.storage.isEmpty() && port.isDirectory()) items.add(new Item(port, spec.label, port.getPath(), true));
            if (!access) {
                items.clear();
                empty.setText(Texts.t(this, Texts.PERM_FILES));
                empty.setOnClickListener(v -> Storage.requestAllFiles(this, 1));
            }
        } else {
            current = folder;
            path.setText(folder.getPath());
            File[] children = folder.listFiles();
            if (children == null) {
                empty.setText(Texts.t(this, Texts.BROWSER_DENIED));
            } else {
                Arrays.sort(children, (a, b) -> {
                    if (a.isDirectory() != b.isDirectory()) return a.isDirectory() ? -1 : 1;
                    return a.getName().compareToIgnoreCase(b.getName());
                });
                for (File child : children) {
                    if (child.getName().startsWith(".")) continue;
                    if (child.isDirectory()) items.add(new Item(child, child.getName(), null, true));
                    else if (mode == Pickers.ZIP && child.getName().toLowerCase(Locale.ROOT).endsWith(".zip"))
                        items.add(new Item(child, child.getName(), Texts.size(this, child.length()), false));
                    else if (mode == Pickers.GOG && child.getName().toLowerCase(Locale.ROOT).endsWith(".exe"))
                        items.add(new Item(child, child.getName(), Texts.size(this, child.length()), false));
                }
                if (items.isEmpty()) empty.setText(Texts.t(this, Texts.BROWSER_EMPTY));
            }
        }
        /* Nothing is above the list of volumes; a ZIP is chosen by tapping it, so its "Up" takes the row. */
        up.setVisibility(current != null ? View.VISIBLE : View.GONE);
        select.setVisibility(mode == Pickers.FOLDER && current != null ? View.VISIBLE : View.GONE);
        bar.setVisibility(current != null ? View.VISIBLE : View.GONE);
        adapter.notifyDataSetChanged();
        list.setSelection(0);
    }

    /** "game files: …" for a folder, "not compressed" for a ZIP; computed once, off the UI thread. */
    private void badge(Item item, TextView view) {
        String key = item.file.getAbsolutePath();
        if (badges.containsKey(key)) {
            String text = badges.get(key);
            view.setText(join(item.detail, text));
            return;
        }
        badges.put(key, null);
        badgeWork.execute(() -> {
            String text = null;
            try {
                if (item.folder) {
                    List<String> names = new ArrayList<>();
                    for (Spec.Distribution d : spec.distributions)
                        for (Spec.Part p : d.parts) if (Install.present(p, item.file)) names.add(Texts.of(this, p.title));
                    if (!names.isEmpty()) text = Texts.fmt(this, Texts.HAS_GAME, String.join(", ", names));
                } else if (mode == Pickers.ZIP) {
                    try (FileInputStream in = new FileInputStream(item.file); Zip zip = new Zip(in.getChannel())) {
                        List<String> names = new ArrayList<>();
                        boolean stored = true;
                        for (Install.ArchivePart part : Install.plan(zip, spec)) {
                            names.add(Texts.of(this, part.part.title));
                            stored &= part.compressed == 0;
                        }
                        if (!names.isEmpty()) {
                            text = Texts.fmt(this, Texts.HAS_GAME, String.join(", ", names));
                            if (stored) text += " · " + Texts.t(this, Texts.ZIP_STORED);
                        }
                    }
                }
            } catch (Exception e) {
                /* not readable or not a game: no badge */
            }
            final String found = text;
            handler.post(() -> {
                badges.put(key, found);
                adapter.notifyDataSetChanged();
            });
        });
    }

    private static String join(String a, String b) {
        if (a == null || a.isEmpty()) return b;
        if (b == null || b.isEmpty()) return a;
        return a + " · " + b;
    }

    private final class Adapter extends BaseAdapter {
        @Override public int getCount() { return items.size(); }
        @Override public Object getItem(int position) { return items.get(position); }
        @Override public long getItemId(int position) { return position; }

        @Override public View getView(int position, View convert, ViewGroup parent) {
            Item item = items.get(position);
            LinearLayout row;
            TextView title, detail;
            if (convert instanceof LinearLayout) {
                row = (LinearLayout) convert;
                title = (TextView) row.getChildAt(0);
                detail = (TextView) row.getChildAt(1);
            } else {
                row = new LinearLayout(FileBrowserActivity.this);
                row.setOrientation(LinearLayout.VERTICAL);
                row.setPadding(ui.dp(14), ui.dp(10), ui.dp(14), ui.dp(10));
                row.setMinimumHeight(ui.dp(52));
                android.graphics.drawable.GradientDrawable bg = new android.graphics.drawable.GradientDrawable();
                bg.setColor(ui.cell);
                bg.setCornerRadius(ui.dp(12));
                row.setBackground(bg);
                title = ui.label("", 16, ui.text);
                detail = ui.label("", 12, ui.muted);
                row.addView(title);
                row.addView(detail);
            }
            title.setText((item.folder ? "📁  " : "📦  ") + item.title);
            detail.setText(item.detail != null ? item.detail : "");
            if (current != null) badge(item, detail);
            String badge = badges.get(item.file.getAbsolutePath());
            title.setTextColor(badge != null ? ui.accent : ui.text);
            detail.setVisibility(detail.getText().length() > 0 ? View.VISIBLE : View.GONE);
            return row;
        }
    }
}
