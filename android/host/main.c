/* Command-line entry for adb-shell bring-up on the device:
 *   void-arm64 --game DIR --data DIR --images DIR [--selftest] [-v]
 * The APK uses the same initialization through void_game_main. */
#define _GNU_SOURCE
#include "host.h"
#include "input.h"
#include <dirent.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

#ifdef VOID_RELEASE
#include "release_overrides.h"
#define GAME_ENTRY RELEASE_GAME_ENTRY
#else
#define GAME_ENTRY 0x004197B9u
#endif

void void_files_std_init(void);
static int exiting;

void void_process_exit(uint32_t code, int run_detach)
{
    if (!exiting && run_detach) {
        exiting = 1;
        void_modules_detach_all(1);
    }
    void_log("[void] process exit %u", code);
    void_log_flush();
    _exit((int)code);
}

static const char *lifted_dlls[] = {
    "GameModule.dll", "Engine.dll", "FS.dll", "VFS.dll", "Sound.dll", "Video.dll", "RendererD3D.dll", "NxCharacter.dll",
};

static int self_test(void)
{
    int failures = 0;
    for (size_t i = 0; i < sizeof lifted_dlls / sizeof lifted_dlls[0]; ++i) {
        uint32_t h = void_module_load(lifted_dlls[i]);
        if (!h) { void_log("[selftest] %s: attach FAILED", lifted_dlls[i]); ++failures; continue; }
        uint32_t factory = void_module_proc(h, void_gstrdup(i == 7 ? "NxCreateControllerManager" : "_createFactory@0"));
        void_log("[selftest] %s attached at %08X, factory %08X", lifted_dlls[i], h, factory);
        if (!factory) ++failures;
        if (!void_module_free(h)) { void_log("[selftest] %s: detach FAILED", lifted_dlls[i]); ++failures; }
    }
    void_log("[selftest] %s: %d failures", failures ? "FAIL" : "PASS", failures);
    return failures ? 71 : 0;
}

/* Config.exe writes these into CommonAppData on Windows before the first
 * game start; seed equivalent files once (never overwrite the player's). */
static void seed_file(const char *dir, const char *name, const char *content)
{
    char path[1100];
    snprintf(path, sizeof path, "%s/%s", dir, name);
    if (!access(path, F_OK)) return;
    FILE *f = fopen(path, "wb");
    if (!f) { void_log("[void] cannot seed %s: %s", path, strerror(errno)); return; }
    fputs(content, f);
    fclose(f);
    void_log("[void] seeded %s", path);
}

static int copy_tree(const char *from, const char *to)
{
    DIR *d = opendir(from);
    if (!d) return 0;
    mkdir(to, 0775);
    struct dirent *e;
    int ok = 1;
    while ((e = readdir(d))) {
        if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
        char a[1200], b[1200];
        snprintf(a, sizeof a, "%s/%s", from, e->d_name);
        snprintf(b, sizeof b, "%s/%s", to, e->d_name);
        struct stat st;
        if (stat(a, &st)) continue;
        if (S_ISDIR(st.st_mode)) { ok &= copy_tree(a, b); continue; }
        FILE *in = fopen(a, "rb"), *out = fopen(b, "wb");
        if (!in || !out) { ok = 0; if (in) fclose(in); if (out) fclose(out); continue; }
        char buf[1 << 16];
        size_t n;
        while ((n = fread(buf, 1, sizeof buf, in)) > 0) fwrite(buf, 1, n, out);
        fclose(in);
        fclose(out);
    }
    closedir(d);
    return ok;
}

/* The profile folders carry the game's English title from data/info.xml
 * (EngTitle): "Void" for the English release, "Turgor" for the Russian one
 * ("Тургор: Голос Цвета"). The game itself resolves {documents},
 * {shdocs} and its config folder in ProgramData with it. */
static void profile_title(char *out, size_t cap)
{
    snprintf(out, cap, "Void");
    char path[1200];
    snprintf(path, sizeof path, "%s/data/info.xml", void_root_dir());
    FILE *f = fopen(path, "rb");
    if (!f) return;
    char text[2048];
    size_t n = fread(text, 1, sizeof text - 1, f);
    fclose(f);
    text[n] = 0;
    const char *p = strstr(text, "EngTitle=\"");
    if (!p) return;
    p += 10;
    const char *end = strchr(p, '"');
    if (!end || end == p || (size_t)(end - p) >= cap) return;
    memcpy(out, p, (size_t)(end - p));
    out[end - p] = 0;
}

static void seed_profile(const char *data)
{
    char dir[1024], title[128];
    profile_title(title, sizeof title);
    void_log("[void] profile folders: My Games/%s, Ice-pick Lodge/%s", title, title);
    /* Steam's install script copies %INSTALLDIR%\Void to
     * %COMMON_MYDOCS%\My Games\Void (the effect and shader caches). */
    char marker[1200], from[1024];
    snprintf(dir, sizeof dir, "%s/PublicDocuments/My Games", data);
    mkdir(dir, 0775);
    snprintf(dir, sizeof dir, "%s/PublicDocuments/My Games/%s", data, title);
    snprintf(marker, sizeof marker, "%s/Cache/effects30.hdr", dir);
    snprintf(from, sizeof from, "%s/Void", void_root_dir());
    if (access(marker, F_OK)) {
        void_log("[void] installing %s -> %s", from, dir);
        if (!copy_tree(from, dir)) void_log("[void] copying the Void folder failed");
    }
    snprintf(dir, sizeof dir, "%s/ProgramData/Ice-pick Lodge", data);
    mkdir(dir, 0775);
    snprintf(dir, sizeof dir, "%s/ProgramData/Ice-pick Lodge/%s", data, title);
    mkdir(dir, 0775);
    seed_file(dir, "rcfg.xml",
        "\xEF\xBB\xBF<?xml version=\"1.0\" encoding=\"utf-8\" ?>\r\n<Renderer>\r\n"
        "\t<Width>1280</Width>\r\n\t<Height>720</Height>\r\n\t<HDR simple=\"1\" />\r\n"
        "\t<RefreshRate>0</RefreshRate>\r\n\t<Antialiasing>0</Antialiasing>\r\n\t<Anisotropy>0</Anisotropy>\r\n"
        "\t<LightmapQuality>2</LightmapQuality>\r\n\t<TextureQuality>1</TextureQuality>\r\n</Renderer>\r\n");
    seed_file(dir, "scfg.xml",
        "\xEF\xBB\xBF<?xml version=\"1.0\" encoding=\"utf-8\" ?>\r\n<Sound>\r\n\t<Quality rate=\"44\" />\r\n</Sound>\r\n");
    seed_file(dir, "settings.xml",
        "<?xml version=\"1.0\" encoding=\"utf-8\" ?>\r\n<Settings>\r\n"
        "  <prop name=\"Gamma\" value=\"1\" />\r\n  <prop name=\"InvertMouse\" value=\"0\" />\r\n"
        "  <prop name=\"MasterVolume\" value=\"0.8\" />\r\n  <prop name=\"MouseSensitivity\" value=\"1\" />\r\n"
        "  <prop name=\"MouseSmooth\" value=\"0\" />\r\n  <prop name=\"MusicVolume\" value=\"0.6\" />\r\n"
        "  <prop name=\"Shadows\" value=\"1\" />\r\n  <prop name=\"SoundVolume\" value=\"0.8\" />\r\n"
        "  <prop name=\"Subtitles\" value=\"1\" />\r\n  <prop name=\"VoiceVolume\" value=\"0.7\" />\r\n</Settings>\r\n");
}

int void_game_main(const char *game, const char *data, const char *images, int selftest)
{
    void_install_fault_handlers();
    mkdir(data, 0775);
    char log_path[1024];
    snprintf(log_path, sizeof log_path, "%s/void.log", data);
    void_log_open(log_path);
    void_log("[void] The Void ARM64 host: game=%s data=%s images=%s", game, data, images);
    if (!void_guest_reserve()) return 65;
    void_threads_init();
    void_dispatch_init();
    if (!void_files_init(game, data)) return 66;
    void_files_std_init();
    seed_profile(data);
    if (getenv("VOID_TIME_SCALE")) void_set_time_scale(strtod(getenv("VOID_TIME_SCALE"), NULL));
    if (!void_modules_init(images)) return 67;
    void_machine_enter();
    int code;
    if (selftest) {
        code = self_test();
    } else {
        void_input_script_start();
        void_log("[void] starting lifted Game.exe at %08X", GAME_ENTRY);
        code = (int)void_call_guest(GAME_ENTRY, 0, NULL, 1);
        void_log("[void] Game.exe entry returned %d", code);
    }
    void_machine_leave();
    void_log_flush();
    return code;
}

#ifndef VOID_ANDROID_APP
int main(int argc, char **argv)
{
    const char *game = "/sdcard/TheVoid/game", *data = "/sdcard/TheVoid/userdata";
    const char *images = "/sdcard/TheVoid/lifted";
    int selftest = 0;
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--game") && i + 1 < argc) game = argv[++i];
        else if (!strcmp(argv[i], "--data") && i + 1 < argc) data = argv[++i];
        else if (!strcmp(argv[i], "--images") && i + 1 < argc) images = argv[++i];
        else if (!strcmp(argv[i], "--selftest")) selftest = 1;
        else if (!strcmp(argv[i], "-v")) void_verbose = 1;
        else { fprintf(stderr, "unknown option %s\n", argv[i]); return 64; }
    }
    setvbuf(stderr, NULL, _IONBF, 0);
    int code = void_game_main(game, data, images, selftest);
    void_process_exit((uint32_t)code, 0);
    return code;
}
#endif
