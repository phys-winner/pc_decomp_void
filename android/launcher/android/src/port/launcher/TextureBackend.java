package port.launcher;

import java.io.File;

/** A game's texture converter (port.json "textures.backend"): re-encodes the game's DXT textures
 *  into a format the GPU samples (ETC2 or ASTC) in the game's own container. The launcher shows the
 *  card, runs the work in the background and keeps the player informed; how the textures are found
 *  and stored stays the game's (Heroes V: zz_port_textures.pak per data bank; The Void: one .tvt). */
public interface TextureBackend {
    int ETC2 = 1, ASTC = 2;

    final class Scan {
        public long textures, bytes;          /* convertible originals and their size */
        public int converted;                 /* 0, ETC2 or ASTC: an existing conversion */
        public long convertedTextures, convertedBytes;
        public String failure;                /* why the game's files could not be read; null */
        /** What removeOriginals() would free after a conversion; 0: nothing (or not offered). */
        public long removable;
        /** The originals were removed after the conversion: it can no longer be undone. */
        public boolean originalsRemoved;
    }

    /** Blocking: what there is to convert in the game folder. */
    Scan scan(File game);

    /** Blocking: converts, reporting through progress(); 0 when done, else message() says why. */
    int convert(File game, int format, int threads);

    /** Blocking: removes a conversion; 0 when done. */
    int undo(File game);

    /** Blocking, optional (Scan.removable offers it): removes the original textures a conversion
     *  replaced from the game's files, for space; the conversion can no longer be undone then.
     *  0 when done. */
    default int removeOriginals(File game) { return -1; }

    void cancel();

    /** {done, total, bytesDone, bytesTotal} of the running operation. */
    long[] progress();

    String message();
}
