package port.launcher;

import java.io.IOException;

/** A failure of reading, importing or cleaning the game's files, which the launcher names in the
 *  player's words (Texts.failure). Plain Java. */
final class Failure extends IOException {
    static final int NOT_ZIP = 1, SPLIT = 2, NOT_FOUND = 3, UNSAFE = 4, METHOD = 5, ENCRYPTED = 6, CORRUPT = 7,
        FULL = 8, READ_ONLY = 9, IO = 10, CANCELLED = 11, REMOTE = 12, CHANGED = 13;

    final int code;
    final String detail;
    final long required, available;

    Failure(int code, String detail) {
        this(code, detail, -1, -1);
    }

    Failure(int code, String detail, long required, long available) {
        super("launcher failure " + code + (detail != null ? ": " + detail : ""));
        this.code = code;
        this.detail = detail;
        this.required = required;
        this.available = available;
    }

    static Failure of(Throwable error) {
        if (error instanceof Failure) return (Failure) error;
        String message = error.getMessage();
        if (message != null && (message.contains("ENOSPC") || message.contains("No space left"))) return new Failure(FULL, null);
        if (message != null && (message.contains("EACCES") || message.contains("EROFS") || message.contains("Permission denied")))
            return new Failure(READ_ONLY, message);
        return new Failure(IO, message != null ? message : error.toString());
    }
}
