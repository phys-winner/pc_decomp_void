/* The launcher's Vulkan driver check, libportprobe.so: Probe.java calls it in the short-lived
 * process :probe, once for the system Vulkan driver and, on Qualcomm GPUs, once for the port's
 * Turnip through adrenotools, so a driver that crashes takes only that process down. It creates a
 * Vulkan instance, reads the first GPU and reports what DXVK would refuse (vulkan_requirements.h)
 * as key=value lines that Renderers.java turns into the launcher's reasons. No device, surface or
 * swapchain is created. The Java class comes from PORT_PROBE_CLASS (tools/launcher.py passes the
 * game's package): the source does not depend on it. After the Heroes V port's probe.cpp, in C. */
#include <dlfcn.h>
#include <jni.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan_core.h>
#include "vulkan_requirements.h"

#ifndef PORT_PROBE_CLASS
#define PORT_PROBE_CLASS "port/launcher/Probe"
#endif

typedef struct { char *text; size_t size, used; } port_report;

/* Values travel as one Modified UTF-8 line each: printable ASCII only. */
static void port_clean(char *out, size_t size, const char *text)
{
    size_t n = 0;
    for (const char *p = text; p && *p && n + 1 < size; ++p) out[n++] = (*p >= 0x20 && *p < 0x7f) ? *p : ' ';
    if (size) out[n] = 0;
}

static void port_line(port_report *r, const char *prefix, const char *key, const char *value)
{
    char clean[512];
    port_clean(clean, sizeof clean, value);
    if (r->size <= r->used + 1) return;
    int n = snprintf(r->text + r->used, r->size - r->used, "%s.%s=%s\n", prefix, key, clean);
    if (n > 0) r->used = r->used + (size_t)n < r->size ? r->used + (size_t)n : r->size - 1;
}

static void port_version(char *out, size_t size, uint32_t v)
{
    snprintf(out, size, "%u.%u.%u", VK_API_VERSION_MAJOR(v), VK_API_VERSION_MINOR(v), VK_API_VERSION_PATCH(v));
}

static int port_has(const VkExtensionProperties *list, uint32_t count, const char *name)
{
    for (uint32_t i = 0; i < count; ++i) if (!strcmp(list[i].extensionName, name)) return 1;
    return 0;
}

static void port_probe(PFN_vkGetInstanceProcAddr gipa, const char *prefix, int turnip, port_report *r)
{
    PFN_vkEnumerateInstanceVersion instance_version =
        (PFN_vkEnumerateInstanceVersion)gipa(NULL, "vkEnumerateInstanceVersion");
    PFN_vkEnumerateInstanceExtensionProperties instance_extensions =
        (PFN_vkEnumerateInstanceExtensionProperties)gipa(NULL, "vkEnumerateInstanceExtensionProperties");
    PFN_vkCreateInstance create = (PFN_vkCreateInstance)gipa(NULL, "vkCreateInstance");
    char text[64];
    if (!instance_extensions || !create) {
        port_line(r, prefix, "status", "error");
        port_line(r, prefix, "error", "incomplete Vulkan loader");
        return;
    }
    uint32_t loader = VK_API_VERSION_1_0, count = 0;
    if (instance_version) instance_version(&loader);
    instance_extensions(NULL, &count, NULL);
    VkExtensionProperties *available = calloc(count ? count : 1, sizeof *available);
    if (!available) return;
    if (count) instance_extensions(NULL, &count, available);
    port_vk_caps caps;
    memset(&caps, 0, sizeof caps);
    caps.android_surface = port_has(available, count, VK_KHR_SURFACE_EXTENSION_NAME) &&
        port_has(available, count, "VK_KHR_android_surface");
    free(available);
    const char *enabled[2] = { VK_KHR_SURFACE_EXTENSION_NAME, "VK_KHR_android_surface" };
    VkApplicationInfo app;
    memset(&app, 0, sizeof app);
    app.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
    app.pApplicationName = "Port launcher driver check";
    app.apiVersion = loader >= VK_API_VERSION_1_1 ? VK_API_VERSION_1_3 : VK_API_VERSION_1_0;
    VkInstanceCreateInfo info;
    memset(&info, 0, sizeof info);
    info.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    info.pApplicationInfo = &app;
    info.enabledExtensionCount = caps.android_surface ? 2 : 0;
    info.ppEnabledExtensionNames = enabled;
    VkInstance instance = VK_NULL_HANDLE;
    VkResult result = create(&info, NULL, &instance);
    if (result != VK_SUCCESS) {
        snprintf(text, sizeof text, "vkCreateInstance failed %d", (int)result);
        port_line(r, prefix, "status", "error");
        port_line(r, prefix, "error", text);
        return;
    }
#define PORT_GET(type, name) ((type)gipa(instance, name))
    PFN_vkDestroyInstance destroy = PORT_GET(PFN_vkDestroyInstance, "vkDestroyInstance");
    PFN_vkEnumeratePhysicalDevices enumerate = PORT_GET(PFN_vkEnumeratePhysicalDevices, "vkEnumeratePhysicalDevices");
    PFN_vkGetPhysicalDeviceProperties properties = PORT_GET(PFN_vkGetPhysicalDeviceProperties, "vkGetPhysicalDeviceProperties");
    PFN_vkGetPhysicalDeviceProperties2 properties2 = PORT_GET(PFN_vkGetPhysicalDeviceProperties2, "vkGetPhysicalDeviceProperties2");
    PFN_vkGetPhysicalDeviceFeatures features = PORT_GET(PFN_vkGetPhysicalDeviceFeatures, "vkGetPhysicalDeviceFeatures");
    PFN_vkGetPhysicalDeviceFeatures2 features2 = PORT_GET(PFN_vkGetPhysicalDeviceFeatures2, "vkGetPhysicalDeviceFeatures2");
    PFN_vkEnumerateDeviceExtensionProperties device_extensions =
        PORT_GET(PFN_vkEnumerateDeviceExtensionProperties, "vkEnumerateDeviceExtensionProperties");
    PFN_vkGetPhysicalDeviceFormatProperties formats =
        PORT_GET(PFN_vkGetPhysicalDeviceFormatProperties, "vkGetPhysicalDeviceFormatProperties");
#undef PORT_GET
    if (app.apiVersion < VK_API_VERSION_1_1) { properties2 = NULL; features2 = NULL; }
    VkPhysicalDevice devices[8], chosen = VK_NULL_HANDLE;
    VkPhysicalDeviceProperties p;
    memset(&p, 0, sizeof p);
    count = 8;
    if (enumerate && properties && enumerate(instance, &count, devices) >= VK_SUCCESS)
        for (uint32_t i = 0; i < count && i < 8; ++i) {
            properties(devices[i], &p);
            /* DXVK skips CPU adapters when a GPU exists; a phone has one GPU. */
            if (p.deviceType != VK_PHYSICAL_DEVICE_TYPE_CPU || !chosen) chosen = devices[i];
            if (p.deviceType != VK_PHYSICAL_DEVICE_TYPE_CPU) break;
        }
    if (!chosen || !features || !device_extensions || !formats) {
        port_line(r, prefix, "status", "error");
        port_line(r, prefix, "error", "no Vulkan GPU");
        if (destroy) destroy(instance, NULL);
        return;
    }
    properties(chosen, &p);
    caps.api_version = p.apiVersion;
    count = 0;
    device_extensions(chosen, NULL, &count, NULL);
    VkExtensionProperties *extensions = calloc(count ? count : 1, sizeof *extensions);
    if (extensions && count) device_extensions(chosen, NULL, &count, extensions);
    caps.swapchain = extensions && port_has(extensions, count, VK_KHR_SWAPCHAIN_EXTENSION_NAME);
    caps.robustness2 = extensions && port_has(extensions, count, VK_EXT_ROBUSTNESS_2_EXTENSION_NAME);
    free(extensions);
    char driver[600] = "";
    VkDriverId driver_id = (VkDriverId)0;
    if (properties2 && p.apiVersion >= VK_API_VERSION_1_2) {
        VkPhysicalDeviceDriverProperties d;
        memset(&d, 0, sizeof d);
        d.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES;
        VkPhysicalDeviceProperties2 p2;
        memset(&p2, 0, sizeof p2);
        p2.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2;
        p2.pNext = &d;
        properties2(chosen, &p2);
        snprintf(driver, sizeof driver, "%.255s %.255s", d.driverName, d.driverInfo);
        driver_id = d.driverID;
    }
    /* Structures of a version the device lacks must not be chained. */
    VkPhysicalDeviceVulkan12Features v12;
    VkPhysicalDeviceVulkan13Features v13;
    VkPhysicalDeviceRobustness2FeaturesEXT r2;
    VkPhysicalDeviceFeatures2 f2;
    memset(&v12, 0, sizeof v12);
    memset(&v13, 0, sizeof v13);
    memset(&r2, 0, sizeof r2);
    memset(&f2, 0, sizeof f2);
    v12.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES;
    v13.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES;
    r2.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ROBUSTNESS_2_FEATURES_EXT;
    f2.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2;
    void **next = &f2.pNext;
    if (p.apiVersion >= VK_API_VERSION_1_2) { *next = &v12; next = &v12.pNext; }
    if (p.apiVersion >= VK_API_VERSION_1_3) { *next = &v13; next = &v13.pNext; }
    if (caps.robustness2) { *next = &r2; next = &r2.pNext; }
    if (features2 && p.apiVersion >= VK_API_VERSION_1_1) features2(chosen, &f2);
    else features(chosen, &f2.features);
    caps.core = f2.features;
    caps.sampler_mirror_clamp_to_edge = v12.samplerMirrorClampToEdge;
    caps.vulkan_memory_model = v12.vulkanMemoryModel;
    caps.host_query_reset = v12.hostQueryReset;
    caps.timeline_semaphore = v12.timelineSemaphore;
    caps.shader_demote_to_helper_invocation = v13.shaderDemoteToHelperInvocation;
    caps.synchronization2 = v13.synchronization2;
    caps.dynamic_rendering = v13.dynamicRendering;
    caps.maintenance4 = v13.maintenance4;
    caps.robust_buffer_access2 = r2.robustBufferAccess2;
    caps.null_descriptor = r2.nullDescriptor;
    const VkFormat bc[3] = { VK_FORMAT_BC1_RGBA_UNORM_BLOCK, VK_FORMAT_BC2_UNORM_BLOCK, VK_FORMAT_BC3_UNORM_BLOCK };
    int *bc_found[3] = { &caps.bc1, &caps.bc2, &caps.bc3 };
    for (int i = 0; i < 3; ++i) {
        VkFormatProperties fp;
        memset(&fp, 0, sizeof fp);
        formats(chosen, bc[i], &fp);
        *bc_found[i] = (fp.optimalTilingFeatures & VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT) != 0;
    }
    char missing[1024];
    int gaps = port_vk_missing(&caps, 1, missing, sizeof missing);
    /* Mesa Turnip, not the system's Qualcomm driver: builds of it rename the device ("PurpleVK..."),
     * never the driver id. */
    if (turnip && !(p.vendorID == 0x5143 && (driver_id == VK_DRIVER_ID_MESA_TURNIP || strstr(p.deviceName, "Turnip")))) {
        size_t used = strlen(missing);
        snprintf(missing + used, sizeof missing - used, "%snotTurnip", gaps++ ? "," : "");
    }
    port_line(r, prefix, "status", gaps ? "missing" : "ok");
    port_line(r, prefix, "device", p.deviceName);
    snprintf(text, sizeof text, "%04x", p.vendorID);
    port_line(r, prefix, "vendor", text);
    snprintf(text, sizeof text, "%04x", p.deviceID);
    port_line(r, prefix, "deviceId", text);
    port_version(text, sizeof text, p.apiVersion);
    port_line(r, prefix, "api", text);
    port_version(text, sizeof text, loader);
    port_line(r, prefix, "loader", text);
    if (driver[0]) port_line(r, prefix, "driver", driver);
    if (driver_id) {
        snprintf(text, sizeof text, "%d", (int)driver_id);
        port_line(r, prefix, "driverId", text);
    }
    snprintf(text, sizeof text, "%d%d%d", caps.bc1, caps.bc2, caps.bc3);
    port_line(r, prefix, "bc", text);
    port_line(r, prefix, "missing", missing);
    if (destroy) destroy(instance, NULL);
}

typedef void *(*port_adrenotools_open)(int, int, const char *, const char *, const char *, const char *, const char *, void **);

/* The port's Turnip from the native library directory through adrenotools (extractNativeLibs is
 * what adrenotools requires): its hooks load the driver in a linker namespace of its own, so the
 * system driver stays untouched. 1 = ADRENOTOOLS_DRIVER_CUSTOM; no temporary directory (API 29+
 * uses memfd), no file redirection, no GPU mapping import. A driver given as a full path (the
 * player's own, TurnipDriver.java) is loaded from its folder with the same hooks. */
static PFN_vkGetInstanceProcAddr port_open_turnip(const char *directory, const char *driver, char *error, size_t size)
{
    char path[1024], hooks[1024], folder[1024];
    snprintf(path, sizeof path, "%s/libadrenotools.so", directory ? directory : "");
    snprintf(hooks, sizeof hooks, "%s/", directory ? directory : "");
    const char *slash = strrchr(driver, '/');
    snprintf(folder, sizeof folder, "%.*s", slash ? (int)(slash - driver + 1) : 0, driver);
    void *helper = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    port_adrenotools_open open = helper ? (port_adrenotools_open)dlsym(helper, "adrenotools_open_libvulkan") : NULL;
    void *loader = open ? open(RTLD_NOW | RTLD_LOCAL, 1, NULL, hooks, slash ? folder : hooks, slash ? slash + 1 : driver, NULL, NULL) : NULL;
    PFN_vkGetInstanceProcAddr get = loader ? (PFN_vkGetInstanceProcAddr)dlsym(loader, "vkGetInstanceProcAddr") : NULL;
    if (!get) {
        const char *detail = dlerror();
        snprintf(error, size, "adrenotools returned no driver (%s)",
                 detail ? detail : helper ? "no custom driver" : "libadrenotools.so missing");
    }
    return get;
}

/* driver null: the system driver (libvulkan.so); else the Turnip library of that name, or at that full path. */
static jstring JNICALL port_native_probe(JNIEnv *env, jclass cls, jstring directory, jstring driver)
{
    (void)cls;
    port_report report = { calloc(1, 8192), 8192, 0 };
    if (!report.text) return NULL;
    const char *dir = directory ? (*env)->GetStringUTFChars(env, directory, NULL) : NULL;
    const char *name = driver ? (*env)->GetStringUTFChars(env, driver, NULL) : NULL;
    if (!name) {
        void *vulkan = dlopen("libvulkan.so", RTLD_NOW | RTLD_LOCAL);
        PFN_vkGetInstanceProcAddr gipa = vulkan ? (PFN_vkGetInstanceProcAddr)dlsym(vulkan, "vkGetInstanceProcAddr") : NULL;
        if (gipa) port_probe(gipa, "stock", 0, &report);
        else {
            port_line(&report, "stock", "status", "error");
            port_line(&report, "stock", "error", "no system Vulkan loader");
        }
    } else {
        char error[512] = "";
        PFN_vkGetInstanceProcAddr gipa = port_open_turnip(dir, name, error, sizeof error);
        if (gipa) port_probe(gipa, "turnip", 1, &report);
        else {
            port_line(&report, "turnip", "status", "error");
            port_line(&report, "turnip", "error", error);
        }
    }
    if (dir) (*env)->ReleaseStringUTFChars(env, directory, dir);
    if (name) (*env)->ReleaseStringUTFChars(env, driver, name);
    jstring result = (*env)->NewStringUTF(env, report.text);
    free(report.text);
    return result;
}

JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM *vm, void *reserved)
{
    (void)reserved;
    JNIEnv *env = NULL;
    if ((*vm)->GetEnv(vm, (void **)&env, JNI_VERSION_1_6) != JNI_OK) return JNI_ERR;
    /* FindClass in JNI_OnLoad uses the class loader that loaded this library: the app's. */
    jclass cls = (*env)->FindClass(env, PORT_PROBE_CLASS);
    if (!cls) return JNI_ERR;
    static const JNINativeMethod methods[] = {
        { "nativeProbe", "(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;", (void *)port_native_probe },
    };
    if ((*env)->RegisterNatives(env, cls, methods, 1) != JNI_OK) return JNI_ERR;
    return JNI_VERSION_1_6;
}
