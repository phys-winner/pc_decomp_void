package port.launcher;

import java.util.Locale;
import java.util.regex.Pattern;

/** A path pattern of the port specification, matched against '/'-separated paths relative to a
 *  game folder, ignoring case (Windows games do): '*' and '?' stay within one folder name, '**'
 *  spans folders, and a pattern ending in '/' matches the folder and everything in it. Plain Java. */
final class Glob {
    private final Pattern pattern;
    final String source;

    Glob(String source) {
        this.source = source;
        String text = source.replace('\\', '/');
        while (text.startsWith("/")) text = text.substring(1);
        if (text.endsWith("/")) text += "**";
        StringBuilder regex = new StringBuilder();
        for (int i = 0; i < text.length(); ++i) {
            char c = text.charAt(i);
            if (c == '*' && i + 1 < text.length() && text.charAt(i + 1) == '*') {
                boolean slash = i + 2 < text.length() && text.charAt(i + 2) == '/';
                /* "**" + "/" also matches no folder at all: "a/**" + "/b" matches "a/b". */
                regex.append(slash ? "(?:.*/)?" : ".*");
                i += slash ? 2 : 1;
            } else if (c == '*') {
                regex.append("[^/]*");
            } else if (c == '?') {
                regex.append("[^/]");
            } else {
                regex.append(Pattern.quote(String.valueOf(c)));
            }
        }
        pattern = Pattern.compile(regex.toString(), Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE);
    }

    boolean matches(String path) {
        return pattern.matcher(path.replace('\\', '/')).matches();
    }

    /** Whether some path under this folder ("a/b", no trailing slash) can match: lets a scan skip
     *  folders no pattern reaches. */
    boolean mayMatchBelow(String folder) {
        String text = source.replace('\\', '/').toLowerCase(Locale.ROOT);
        while (text.startsWith("/")) text = text.substring(1);
        if (text.endsWith("/")) text += "**";
        String[] want = text.split("/"), have = folder.toLowerCase(Locale.ROOT).split("/");
        for (int i = 0; i < have.length; ++i) {
            if (i >= want.length) return false;
            if (want[i].equals("**")) return true;
            if (!new Glob(want[i]).matches(have[i])) return false;
        }
        return true;
    }
}
