package port.launcher;

import java.util.Locale;

/** Byte progress with a smoothed rate; unknown totals and stalled operations have no ETA. */
final class WorkProgress {
    private long started = -1, sampled, changed, previous, previousTotal;
    private double speed;
    private int samples;
    long elapsedSeconds, remainingSeconds = -1, bytesPerSecond;
    int percent = -1;

    void update(long now, long done, long total) {
        done = Math.max(0, done);
        if (started < 0) started = now;
        elapsedSeconds = Math.max(0, now - started) / 1000;
        percent = total > 0 ? (int) Math.min(100, done * 100.0 / total) : -1;
        if (samples == 0 || now < sampled || done < previous || total != previousTotal) {
            speed = 0;
            samples = 1;
            sampled = changed = now;
            previous = done;
            previousTotal = total;
        } else if (now - sampled >= 500) {
            if (done > previous) {
                double rate = (done - previous) * 1000.0 / (now - sampled);
                speed = speed == 0 ? rate : speed * 0.75 + rate * 0.25;
                ++samples;
                changed = now;
            }
            sampled = now;
            previous = done;
        }
        if (now - changed >= 3000) { speed = 0; samples = 1; }
        bytesPerSecond = (long) speed;
        remainingSeconds = total > done && elapsedSeconds >= 5 && samples >= 4 && speed > 0
            ? (long) Math.ceil((total - done) / speed) : -1;
    }

    String describe(String language, boolean textures, long done, long total, long items, long itemTotal) {
        update(System.nanoTime() / 1_000_000, done, total);
        language = language.split(",")[0].trim().replace('_', '-');
        String code = language.split("-")[0];
        String[] words = "ru".equals(code) || "be".equals(code)
            ? new String[] {"файлы", "текстуры", "прошло", "осталось"}
            : "uk".equals(code) ? new String[] {"файли", "текстури", "минуло", "залишилося"}
            : "de".equals(code) ? new String[] {"Dateien", "Texturen", "vergangen", "verbleibend"}
            : "pl".equals(code) ? new String[] {"pliki", "tekstury", "upłynęło", "pozostało"}
            : "fr".equals(code) ? new String[] {"fichiers", "textures", "écoulé", "restant"}
            : "es".equals(code) ? new String[] {"archivos", "texturas", "transcurrido", "restante"}
            : "it".equals(code) ? new String[] {"file", "texture", "trascorso", "rimanente"}
            : "pt".equals(code) ? new String[] {"arquivos", "texturas", "decorrido", "restante"}
            : "ja".equals(code) ? new String[] {"ファイル", "テクスチャ", "経過", "残り"}
            : "zh".equals(code) ? new String[] {"文件", "纹理", "已用时间", "剩余时间"}
            : new String[] {"files", "textures", "elapsed", "remaining"};
        Locale locale = Locale.forLanguageTag(language);
        String line = (percent < 0 ? "" : percent + "% · ") + size(locale, done)
            + (total > 0 ? " / " + size(locale, total) : "");
        if (itemTotal > 0 || items > 0) line += " · " + words[textures ? 1 : 0] + ": " + Math.max(0, items)
            + (itemTotal > 0 ? " / " + itemTotal : "");
        line += "\n" + words[2] + ": " + duration(elapsedSeconds);
        if (bytesPerSecond > 0) line += " · " + size(locale, bytesPerSecond) + "/s";
        if (remainingSeconds >= 0) line += " · " + words[3] + ": ~" + duration(remainingSeconds);
        return line;
    }

    private static String size(Locale locale, long bytes) {
        double value = Math.max(0, bytes);
        String unit = "B";
        for (String next : new String[] {"kB", "MB", "GB", "TB"}) {
            if (value < 1000) break;
            value /= 1000;
            unit = next;
        }
        return String.format(locale, value >= 10 || value == 0 ? "%.0f %s" : "%.1f %s", value, unit);
    }

    static String duration(long seconds) {
        seconds = Math.max(0, seconds);
        return seconds >= 3600 ? String.format(Locale.ROOT, "%d:%02d:%02d", seconds / 3600, seconds / 60 % 60, seconds % 60)
            : String.format(Locale.ROOT, "%d:%02d", seconds / 60, seconds % 60);
    }
}
