package org.thevoid.port;

import java.io.File;
import java.util.Arrays;
import org.thevoid.port.launcher.TextureBackend;

/** The existing TVT converter, operated by the launcher's foreground worker. */
public final class LauncherTextures implements TextureBackend {
    @Override public Scan scan(File game) {
        Textures.Status status = Textures.scan(game);
        Scan scan = new Scan();
        scan.textures = status.textures;
        scan.bytes = status.bytes;
        scan.converted = status.current ? status.converted : 0;
        scan.convertedTextures = status.convertedTextures;
        scan.convertedBytes = status.convertedBytes;
        scan.failure = status.failure;
        return scan;
    }
    @Override public int convert(File game, int format, int threads) {
        if (!Textures.available()) return -1;
        synchronized (Textures.nativeOperation) { return Textures.nativeConvert(game.getAbsolutePath(), format, threads); }
    }
    @Override public int undo(File game) {
        if (!Textures.available()) return -1;
        synchronized (Textures.nativeOperation) { return Textures.nativeRemove(game.getAbsolutePath()); }
    }
    @Override public void cancel() { if (Textures.available()) Textures.nativeCancel(); }
    @Override public long[] progress() {
        long[] values = Textures.available() ? Textures.nativeProgress() : null;
        return values == null || values.length < 5 ? new long[4] : Arrays.copyOfRange(values, 1, 5);
    }
    @Override public String message() { return Textures.available() ? Textures.nativeMessage() : "libtexconv.so"; }
}
