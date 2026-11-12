package port.launcher;

import android.content.Context;
import android.content.pm.PackageManager;
import android.opengl.EGL14;
import android.opengl.EGLConfig;
import android.opengl.EGLContext;
import android.opengl.EGLDisplay;
import android.opengl.EGLExt;
import android.opengl.EGLSurface;
import android.opengl.GLES20;
import android.os.Build;
import java.io.File;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** What this device's GPU offers, read once per process: the GLES renderer name and the texture
 *  formats it samples (an off-screen EGL context), and the system Vulkan driver's version as the
 *  platform declares it (PackageManager features, no driver loaded). */
final class Gpu {
    boolean probed, s3tc, rgtc, bptc, astc, etc2;
    String renderer = "", vendor = "";
    int vulkan;              /* VK_MAKE_API_VERSION of the system driver; 0 without Vulkan */
    int adreno;              /* the Adreno model number; 0 on other GPUs */

    private static Gpu cached;

    private Gpu() { }

    static synchronized Gpu get(Context context) {
        if (cached != null) return cached;
        Gpu g = new Gpu();
        g.probeGles();
        PackageManager pm = context.getPackageManager();
        for (int minor = 4; minor >= 0 && g.vulkan == 0; --minor) {
            int version = (1 << 22) | (minor << 12);
            if (pm.hasSystemFeature(PackageManager.FEATURE_VULKAN_HARDWARE_VERSION, version)) g.vulkan = version;
        }
        Matcher m = Pattern.compile("Adreno[^0-9]*(\\d{3})").matcher(g.renderer);
        if (m.find()) g.adreno = Integer.parseInt(m.group(1));
        android.util.Log.i("Launcher", "GPU " + g.renderer + " (" + g.vendor + "), Vulkan " + version(g.vulkan)
            + ", s3tc " + g.s3tc + ", astc " + g.astc);
        cached = g;
        return g;
    }

    /** Qualcomm by the GPU name, the SoC maker, or the Adreno kernel driver. */
    boolean qualcomm() {
        if (adreno != 0 || renderer.contains("Adreno") || vendor.contains("Qualcomm")) return true;
        if (Build.VERSION.SDK_INT >= 31 && ("QTI".equalsIgnoreCase(Build.SOC_MANUFACTURER) || "Qualcomm".equalsIgnoreCase(Build.SOC_MANUFACTURER)))
            return true;
        return new File("/dev/kgsl-3d0").exists();
    }

    static String version(int v) { return v == 0 ? "—" : (v >>> 22) + "." + ((v >>> 12) & 0x3FF); }

    private void probeGles() {
        EGLDisplay display = EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);
        EGLContext context = EGL14.EGL_NO_CONTEXT;
        EGLSurface surface = EGL14.EGL_NO_SURFACE;
        try {
            int[] version = new int[2];
            if (display == EGL14.EGL_NO_DISPLAY || !EGL14.eglInitialize(display, version, 0, version, 1)) return;
            int[] attributes = {EGL14.EGL_RENDERABLE_TYPE, EGLExt.EGL_OPENGL_ES3_BIT_KHR, EGL14.EGL_SURFACE_TYPE, EGL14.EGL_PBUFFER_BIT, EGL14.EGL_NONE};
            EGLConfig[] configs = new EGLConfig[1];
            int[] count = new int[1];
            if (!EGL14.eglChooseConfig(display, attributes, 0, configs, 0, 1, count, 0) || count[0] == 0) return;
            context = EGL14.eglCreateContext(display, configs[0], EGL14.EGL_NO_CONTEXT, new int[] {EGL14.EGL_CONTEXT_CLIENT_VERSION, 3, EGL14.EGL_NONE}, 0);
            surface = EGL14.eglCreatePbufferSurface(display, configs[0], new int[] {EGL14.EGL_WIDTH, 1, EGL14.EGL_HEIGHT, 1, EGL14.EGL_NONE}, 0);
            if (context == EGL14.EGL_NO_CONTEXT || surface == EGL14.EGL_NO_SURFACE || !EGL14.eglMakeCurrent(display, surface, surface, context)) return;
            String extensions = GLES20.glGetString(GLES20.GL_EXTENSIONS);
            String name = GLES20.glGetString(GLES20.GL_RENDERER), maker = GLES20.glGetString(GLES20.GL_VENDOR);
            if (name != null) renderer = name;
            if (maker != null) vendor = maker;
            if (extensions != null) {
                probed = true;
                s3tc = extensions.contains("GL_EXT_texture_compression_s3tc")
                    || (extensions.contains("GL_EXT_texture_compression_dxt1") && extensions.contains("GL_ANGLE_texture_compression_dxt3")
                        && extensions.contains("GL_ANGLE_texture_compression_dxt5"));
                rgtc = extensions.contains("GL_EXT_texture_compression_rgtc");
                bptc = extensions.contains("GL_EXT_texture_compression_bptc");
                astc = extensions.contains("GL_KHR_texture_compression_astc_ldr");
                etc2 = true;   /* core in OpenGL ES 3.0 */
            }
        } catch (Throwable e) {
            android.util.Log.w("Launcher", "GPU probe: " + e);
        } finally {
            if (display != EGL14.EGL_NO_DISPLAY) {
                EGL14.eglMakeCurrent(display, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_CONTEXT);
                if (surface != EGL14.EGL_NO_SURFACE) EGL14.eglDestroySurface(display, surface);
                if (context != EGL14.EGL_NO_CONTEXT) EGL14.eglDestroyContext(display, context);
                EGL14.eglTerminate(display);
            }
        }
    }
}
