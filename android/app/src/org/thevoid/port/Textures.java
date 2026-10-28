package org.thevoid.port;

import android.content.Context;
import android.content.Intent;
import android.opengl.EGL14;
import android.opengl.EGLConfig;
import android.opengl.EGLContext;
import android.opengl.EGLDisplay;
import android.opengl.EGLExt;
import android.opengl.EGLSurface;
import android.opengl.GLES20;

import java.io.File;

/** The launcher's texture conversion (android/texconv, libtexconv.so): the
 *  game's DXT textures, which a GPU without S3TC cannot sample (the port then
 *  decodes them at load into four to eight times the memory), re-encoded once
 *  into ETC2 or ASTC 4x4: <game>/data/port-textures.tvt, which the game's
 *  D3DX loader uses (android/host/d3dx9.c). The original files are only read.
 *  One operation at a time: {@link #current}, kept alive by TextureService. */
final class Textures {
    static final int ETC2 = 1, ASTC = 2;
    static final int IDLE = 0, SCANNING = 1, CONVERTING = 2, FINISHING = 3, DONE = 4, FAILED = 5, CANCELLED = 6;

    private static native long[] nativeScan(String game);
    private static native int nativeConvert(String game, int format, int threads);
    private static native int nativeRemove(String game);
    private static native void nativeCancel();
    private static native long[] nativeProgress();
    private static native String nativeMessage();

    private static Boolean loaded;
    private static final Object nativeOperation = new Object();

    static synchronized boolean available() {
        if (loaded == null) {
            try {
                System.loadLibrary("texconv");
                loaded = true;
            } catch (Throwable e) {
                android.util.Log.w("TheVoid", "textures: no converter: " + e);
                loaded = false;
            }
        }
        return loaded;
    }

    /* -------------------------------------------------------------- the GPU */

    /** What the GPU samples natively, probed once with an off-screen GLES 3 context. */
    static final class Gpu {
        boolean probed, s3tc, astc;
        String renderer = "";
    }

    private static Gpu gpu;

    static synchronized Gpu gpu() {
        if (gpu != null) return gpu;
        Gpu g = new Gpu();
        EGLDisplay display = EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);
        EGLContext context = EGL14.EGL_NO_CONTEXT;
        EGLSurface surface = EGL14.EGL_NO_SURFACE;
        try {
            int[] version = new int[2];
            if (display != EGL14.EGL_NO_DISPLAY && EGL14.eglInitialize(display, version, 0, version, 1)) {
                int[] attributes = {EGL14.EGL_RENDERABLE_TYPE, EGLExt.EGL_OPENGL_ES3_BIT_KHR,
                    EGL14.EGL_SURFACE_TYPE, EGL14.EGL_PBUFFER_BIT, EGL14.EGL_NONE};
                EGLConfig[] configs = new EGLConfig[1];
                int[] count = new int[1];
                if (EGL14.eglChooseConfig(display, attributes, 0, configs, 0, 1, count, 0) && count[0] > 0) {
                    context = EGL14.eglCreateContext(display, configs[0], EGL14.EGL_NO_CONTEXT,
                        new int[] {EGL14.EGL_CONTEXT_CLIENT_VERSION, 3, EGL14.EGL_NONE}, 0);
                    surface = EGL14.eglCreatePbufferSurface(display, configs[0],
                        new int[] {EGL14.EGL_WIDTH, 1, EGL14.EGL_HEIGHT, 1, EGL14.EGL_NONE}, 0);
                    if (context != EGL14.EGL_NO_CONTEXT && surface != EGL14.EGL_NO_SURFACE
                            && EGL14.eglMakeCurrent(display, surface, surface, context)) {
                        String extensions = GLES20.glGetString(GLES20.GL_EXTENSIONS);
                        String renderer = GLES20.glGetString(GLES20.GL_RENDERER);
                        if (extensions != null) {
                            g.probed = true;
                            /* As android/host/d3d9_gl.c decides. */
                            g.s3tc = extensions.contains("GL_EXT_texture_compression_s3tc")
                                || (extensions.contains("GL_EXT_texture_compression_dxt1")
                                    && extensions.contains("GL_ANGLE_texture_compression_dxt3")
                                    && extensions.contains("GL_ANGLE_texture_compression_dxt5"));
                            g.astc = extensions.contains("GL_KHR_texture_compression_astc_ldr");
                        }
                        if (renderer != null) g.renderer = renderer;
                    }
                }
            }
        } catch (Throwable e) {
            android.util.Log.w("TheVoid", "textures: GPU probe: " + e);
        } finally {
            if (display != EGL14.EGL_NO_DISPLAY) {
                EGL14.eglMakeCurrent(display, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_CONTEXT);
                if (surface != EGL14.EGL_NO_SURFACE) EGL14.eglDestroySurface(display, surface);
                if (context != EGL14.EGL_NO_CONTEXT) EGL14.eglDestroyContext(display, context);
                EGL14.eglTerminate(display);
            }
        }
        android.util.Log.i("TheVoid", "textures: GPU " + g.renderer + " s3tc " + g.s3tc + " astc " + g.astc);
        gpu = g;
        return g;
    }

    /* ----------------------------------------------------------- the state */

    /** What a game folder holds: the convertible textures and any conversion. */
    static final class Status {
        File game;
        long textures, bytes, estimateEtc2, estimateAstc, free;
        int converted;                  /* 0, ETC2 or ASTC */
        long convertedTextures, convertedBytes;
        boolean current;                /* made from this game's files */
        String failure;                 /* the scan could not read the textures */
    }

    /** Blocking: reads data/Textures.vfs's directory and the textures' headers. */
    static Status scan(File game) {
        Status s = new Status();
        s.game = game;
        if (!available()) {
            s.failure = "libtexconv.so";
            return s;
        }
        synchronized (nativeOperation) {
            long[] v = nativeScan(game.getAbsolutePath());
            if (v == null || v.length < 9) {
                s.failure = nativeMessage();
                return s;
            }
            s.textures = v[0];
            s.bytes = v[1];
            s.estimateEtc2 = v[2];
            s.estimateAstc = v[3];
            s.free = v[4];
            s.converted = (int) v[5];
            s.convertedTextures = v[6];
            s.convertedBytes = v[7];
            s.current = v[8] != 0;
        }
        return s;
    }

    static volatile Job current;

    static final class Job implements Runnable {
        final File game;
        final int format;             /* ETC2, ASTC, or 0: remove the conversion */
        final long started = System.currentTimeMillis();
        volatile boolean finished, cancelled;
        volatile String failure;      /* null: done or stopped (see cancelled) */
        volatile long[] last = {IDLE, 0, 0, 0, 0};

        Job(File game, int format) {
            this.game = game;
            this.format = format;
        }

        @Override public void run() {
            try {
                synchronized (nativeOperation) {
                    int result = format == 0 ? nativeRemove(game.getAbsolutePath())
                        : nativeConvert(game.getAbsolutePath(), format, Runtime.getRuntime().availableProcessors());
                    long[] p = nativeProgress();
                    if (p != null) last = p;
                    if (p != null && p[0] == CANCELLED) cancelled = true;
                    else if (result != 0) failure = nativeMessage();
                }
            } catch (Throwable e) {
                failure = e.toString();
            } finally {
                finished = true;
            }
        }

        /** {state, done, total, bytesDone, bytesTotal} */
        long[] progress() {
            if (!finished) {
                long[] p = nativeProgress();
                if (p != null) last = p;
            }
            return last;
        }

        void cancel() {
            cancelled = true;
            nativeCancel();
        }
    }

    static Job start(Context c, File game, int format) {
        if (current != null && !current.finished) return null;
        Job job = new Job(game, format);
        current = job;
        new Thread(job, "textures").start();
        if (format != 0) c.startForegroundService(new Intent(c, TextureService.class));
        return job;
    }
}
