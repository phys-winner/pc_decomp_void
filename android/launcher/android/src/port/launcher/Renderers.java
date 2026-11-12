package port.launcher;

import android.content.Context;
import android.os.Build;
import java.io.File;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.Set;

/** The renderers of port.json and whether each can run here: the Android version, the libraries
 *  this build carries, the system Vulkan version the platform declares, the GPU model (Turnip drives
 *  Adreno GPUs only) and, for the DXVK modes, the driver check of Probe (Vulkan 1.3, robustness2,
 *  BC1-3 textures...). A Vulkan mode the check has not confirmed yet is "not checked": it can be
 *  chosen by hand, never automatically. A start that never reached the game's first frame is the
 *  last word: the launcher then names the renderer and offers the default one. */
final class Renderers {
    static final class Status {
        final Spec.Mode mode;
        /** available: can be chosen; verified: confirmed to run here (the check passed, or OpenGL ES). */
        final boolean available, verified;
        final String reason;

        Status(Spec.Mode mode, boolean available, boolean verified, String reason) {
            this.mode = mode;
            this.available = available;
            this.verified = verified;
            this.reason = reason;
        }
    }

    private Renderers() { }

    static Set<String> libraries(Context context) {
        Set<String> names = new HashSet<>();
        String[] list = new File(context.getApplicationInfo().nativeLibraryDir).list();
        if (list != null) for (String name : list) names.add(name);
        return names;
    }

    static List<Status> evaluate(Context context, Spec spec, Spec.Distribution d, Gpu gpu, boolean convertedTextures) {
        Set<String> present = libraries(context);
        Map<String, String> report = Probe.needed(spec) ? Probe.report(context) : null;
        boolean probing = report == null && Probe.running(context);
        boolean carried = present.contains(Probe.FILE);
        List<Status> result = new ArrayList<>();
        for (String id : d.renderers) {
            Spec.Mode mode = spec.mode(id);
            if (mode != null) result.add(evaluate(context, mode, gpu, present, convertedTextures, carried, report, probing));
        }
        return result;
    }

    private static Status evaluate(Context context, Spec.Mode mode, Gpu gpu, Set<String> present, boolean converted,
                                   boolean carried, Map<String, String> report, boolean probing) {
        if (Build.VERSION.SDK_INT < mode.minSdk)
            return new Status(mode, false, false, Texts.fmt(context, Texts.R_ANDROID, version(mode.minSdk), Build.VERSION.SDK_INT));
        List<String> missing = new ArrayList<>();
        for (String name : mode.libraries) if (!present.contains(name)) missing.add(name);
        if (!missing.isEmpty()) return new Status(mode, false, false, Texts.fmt(context, Texts.R_LIBRARIES, String.join(", ", missing)));
        if ("gles".equals(mode.kind)) return new Status(mode, true, true, null);
        if (converted) return new Status(mode, false, false, Texts.t(context, Texts.R_CONVERTED));
        boolean turnip = "turnip".equals(mode.kind);
        if (turnip) {
            if (!gpu.qualcomm() || (mode.adrenoMin > 0 && (gpu.adreno < mode.adrenoMin || gpu.adreno > mode.adrenoMax))) {
                String here = gpu.renderer.isEmpty() ? "?" : gpu.renderer;
                return new Status(mode, false, false, Texts.fmt(context, Texts.R_ADRENO, mode.adrenoMin, mode.adrenoMax, here));
            }
        } else {
            /* The system Vulkan driver, as the platform declares it. */
            if (gpu.vulkan == 0) return new Status(mode, false, false, Texts.t(context, Texts.R_NO_VULKAN));
            if (mode.vulkan != 0 && Integer.compareUnsigned(gpu.vulkan, mode.vulkan) < 0)
                return new Status(mode, false, false, Texts.fmt(context, Texts.R_VULKAN, Gpu.version(gpu.vulkan), Gpu.version(mode.vulkan)));
        }
        if (!carried || report == null)
            return new Status(mode, true, false, Texts.t(context, probing ? Texts.R_CHECKING : Texts.R_UNCHECKED));
        return judge(context, mode, report);
    }

    /** A Vulkan mode by the driver check's report (Probe). */
    static Status judge(Context context, Spec.Mode mode, Map<String, String> report) {
        String driver = "turnip".equals(mode.kind) ? "turnip" : "stock";
        String status = report.getOrDefault(driver + ".status", "");
        switch (status) {
        case "ok": return new Status(mode, true, true, null);
        case "crash": return new Status(mode, false, false, Texts.t(context, Texts.R_CRASH));
        case "error": return new Status(mode, false, false, Texts.fmt(context, Texts.R_ERROR, report.getOrDefault(driver + ".error", "?")));
        case "missing": {
            Set<String> tokens = new LinkedHashSet<>();
            for (String token : report.getOrDefault(driver + ".missing", "").split(",")) if (!token.trim().isEmpty()) tokens.add(token.trim());
            if (!mode.needsBC) tokens.remove("bcTextures");
            if (tokens.isEmpty()) return new Status(mode, true, true, null);
            return new Status(mode, false, false, reasons(context, tokens, report.getOrDefault(driver + ".api", "?")));
        }
        case "skipped":
            if ("turnip".equals(driver) && Probe.vendor(report, "stock") != Probe.QUALCOMM && Probe.vendor(report, "stock") != 0) {
                String gpu = report.getOrDefault("stock.device", "?");
                return new Status(mode, false, false, Texts.fmt(context, Texts.R_ADRENO, mode.adrenoMin, mode.adrenoMax, gpu));
            }
            return new Status(mode, true, false, Texts.t(context, Texts.R_UNCHECKED));
        default: return new Status(mode, true, false, Texts.t(context, Texts.R_UNCHECKED));
        }
    }

    /** The check's missing-requirement tokens (native/vulkan_requirements.h) as the player reads them. */
    static String reasons(Context context, Set<String> tokens, String api) {
        Set<String> parts = new LinkedHashSet<>(), features = new LinkedHashSet<>();
        for (String token : tokens) {
            switch (token) {
            case "vulkan13": parts.add(Texts.fmt(context, Texts.R_VULKAN13, api)); break;
            case "robustness2": parts.add(Texts.t(context, Texts.R_ROBUSTNESS)); break;
            case "bcTextures": parts.add(Texts.t(context, Texts.R_BC)); break;
            case "swapchain": case "androidSurface": parts.add(Texts.t(context, Texts.R_PRESENT)); break;
            case "notTurnip": parts.add(Texts.t(context, Texts.R_NOT_TURNIP)); break;
            default: features.add(token);
            }
        }
        if (!features.isEmpty()) parts.add(Texts.fmt(context, Texts.R_FEATURES, String.join(", ", features)));
        return parts.isEmpty() ? Texts.t(context, Texts.R_UNFIT) : String.join("; ", parts);
    }

    /** "Android 11" for API 30 and so on (the versions a port can require). */
    static int version(int sdk) {
        if (sdk >= 33) return sdk - 20;
        if (sdk >= 31) return 12;
        return sdk >= 30 ? 11 : sdk >= 29 ? 10 : sdk >= 28 ? 9 : 8;
    }

    static Status status(List<Status> statuses, String id) {
        for (Status s : statuses) if (s.mode.id.equals(id)) return s;
        return null;
    }

    static String key(Spec.Distribution d) { return "renderer." + d.id; }

    /** The player's renderer: the game's own setting (hooks), else the launcher's, else the default. */
    static String chosen(Context context, Spec spec, Spec.Distribution d, PortHooks hooks) {
        String mode = explicitChoice(context, spec, d, hooks);
        return mode != null ? mode : spec.defaultMode;
    }

    /** The mode the player chose (in the game's settings or the launcher); null when nobody did. */
    static String explicitChoice(Context context, Spec spec, Spec.Distribution d, PortHooks hooks) {
        String mode = null;
        try { mode = hooks.renderer(context); } catch (RuntimeException e) { android.util.Log.w("Launcher", "hooks renderer: " + e); }
        if (mode == null || spec.mode(mode) == null) mode = State.get(context, State.CHOICES, key(d), "");
        return spec.mode(mode) != null ? mode : null;
    }

    static void choose(Context context, Spec.Distribution d, PortHooks hooks, String mode) {
        State.put(context, State.CHOICES, key(d), mode);
        try { hooks.setRenderer(context, mode); } catch (RuntimeException e) { android.util.Log.w("Launcher", "hooks renderer: " + e); }
    }

    /** The renderer a start uses: the chosen one if it can run here (one the driver check has not
     *  confirmed only when the player chose it), else the default or the first confirmed one. */
    static String effective(String defaultMode, List<Status> statuses, String chosen, boolean explicit) {
        Status s = status(statuses, chosen);
        if (s != null && s.available && (s.verified || explicit)) return chosen;
        Status fallback = status(statuses, defaultMode);
        if (fallback != null && fallback.available && fallback.verified) return defaultMode;
        for (Status other : statuses) if (other.available && other.verified) return other.mode.id;
        return chosen;
    }

    /** The renderer of the last start that never showed the game's first frame; null if none, or
     *  if the game itself refused the start (Launch.failed: files, access), which is no renderer's fault. */
    static String failed(Context context, Spec.Distribution d) {
        return failed(State.read(context, State.launch(d.id)), Launch.build(context));
    }

    static String failed(Properties launch, String build) {
        if (!"1".equals(launch.getProperty("started")) || "1".equals(launch.getProperty("reached"))) return null;
        if (!launch.getProperty("failed", "").isEmpty()) return null;
        if (!build.equals(launch.getProperty("build"))) return null;
        return launch.getProperty("renderer", "");
    }
}
