package org.thevoid.port;

import android.app.Service;
import android.content.Intent;
import android.os.Binder;
import android.os.IBinder;

/** The game's shader compiler on another core: a process of its own
 *  (android:process=":shaders") with the game's lifted runtime and of the
 *  images only the lifted Microsoft compiler, answering the shader variants
 *  the game could not find in its caches (d3dx9.c void_d3dx_serve), so that
 *  the game draws on while one compiles instead of holding the frame for it.
 *  The game's activity binds it for as long as the game runs; the process
 *  ends with the binding, or with the game's process (the native loop never
 *  returns). */
public final class ShaderCompilerService extends Service {
    static final String LIBRARY = "library", GAME = "game", DATA = "data", IMAGES = "images", PAGE = "page";
    private static native int nativeServe(String game, String data, String images, String page);
    private static boolean serving;

    @Override public IBinder onBind(Intent intent) {
        String game = intent.getStringExtra(GAME), data = intent.getStringExtra(DATA);
        String images = intent.getStringExtra(IMAGES), page = intent.getStringExtra(PAGE);
        String library = intent.getStringExtra(LIBRARY) != null ? intent.getStringExtra(LIBRARY) : "void";
        synchronized (ShaderCompilerService.class) {
            if (!serving && game != null && data != null && images != null && page != null) {
                serving = true;
                new Thread(() -> serve(library, game, data, images, page), "void-shaders").start();
            }
        }
        return new Binder();
    }

    private void serve(String library, String game, String data, String images, String page) {
        try {
            NativeLibrary.load(this, library);
            /* Below the game's threads, in the same cores' group. */
            android.os.Process.setThreadPriority(4);
            int code = nativeServe(game, data, images, page);
            android.util.Log.w("TheVoid", "shader compile service stopped (" + code + ")");
        } catch (java.io.IOException | LinkageError e) {
            android.util.Log.e("TheVoid", "shader compile service failed", e);
        }
    }

    /** The game is gone: so is the compiler. */
    @Override public boolean onUnbind(Intent intent) {
        System.exit(0);
        return false;
    }
}
