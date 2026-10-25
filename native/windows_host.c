/* Lifted Game.exe and selected manually mapped DLLs; remaining DLLs native. */
#define WIN32_LEAN_AND_MEAN
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <shlobj.h>
#include <d3d9.h>
#include "native32.h"
#include "recomp_trace.h"
#include "game_entry.h"
#include "asset_overrides.h"
#include "settings_debug.h"
#include "window_policy.h"
#ifdef VOID_LIFT_GAMEMODULE
#include "menu_asset.h"
#include "module_entry.h"
#ifdef VOID_LIFT_ENGINE
#include "engine_entry.h"
#ifdef VOID_LIFT_FILESYSTEMS
#include "fs_entry.h"
#include "vfs_entry.h"
#ifdef VOID_LIFT_SOUND
#include "sound_entry.h"
#ifdef VOID_LIFT_MEDIA
#include "video_entry.h"
#ifdef VOID_LIFT_RENDERER
#include "renderer_entry.h"
#ifdef VOID_LIFT_NXCHARACTER
#include "nxcharacter_entry.h"
#endif
#endif
#endif
#endif
#endif
#endif
uint32_t void_map_module(const char *path, uint32_t base, uint32_t entry);
uint32_t void_dll_event(uint32_t entry, uint32_t base, uint32_t reason, uint32_t reserved);
void void_restore_module(uint32_t base, uint32_t span, uint32_t counter, const void *snapshot);
#endif
#pragma comment(lib, "advapi32.lib")
#pragma comment(lib, "shell32.lib")
void void_lift_trap(uint32_t address, const char *instruction);
void void_raise_exception(void);

static char original_exe[MAX_PATH];
static wchar_t original_exe_w[MAX_PATH];
static wchar_t profile_root[MAX_PATH];
static wchar_t profile_common[MAX_PATH];
static HKEY game_settings_key;
static uint32_t d3d_create_device_target;
#ifdef VOID_LIFT_GAMEMODULE
static int native_menu_enabled;
static void native_menu_call(uint32_t address, unsigned nargs, const uint32_t *args)
{
    recomp_func_t call = recomp_lookup_manual(address);
    if (!call) call = recomp_lookup_import(address);
    if (!call) void_lift_trap(address, "Cannot dispatch native settings console call");
    uint32_t entry_esp = g_esp, caller = g_cur_func;
    for (unsigned i = nargs; i; --i) PUSH32(g_esp, args[i - 1]);
    PUSH32(g_esp, RECOMP_RETADDR);
    call();
    if (g_esp != entry_esp) void_lift_trap(address, "Settings console call stack imbalance");
    g_cur_func = caller;
}
static void native_menu_publish_settings(void)
{
    const wchar_t *keys[16];
    int values[16];
    unsigned count = void_settings_debug_snapshot(keys, values, 16);
    if (!count) return;
    if (count > 16) void_lift_trap(0x1017E0F0u, "Invalid settings snapshot count");
    uint32_t saved[] = {g_eax, g_ecx, g_edx, g_ebx, g_ebp, g_esi, g_edi, g_esp,
        g_flag_k, g_flag_a, g_flag_b, g_flag_cf, g_cur_func};
    native_menu_call(MEM32(MEM32(g_ecx) + 0x14), 0, NULL);
    uint32_t console = MEM32(g_eax + 0x124);
    uint32_t execute = MEM32(MEM32(console) + 0x34);
    for (unsigned i = 0; i < count; ++i) {
        wchar_t command[128];
        if (_snwprintf_s(command, 128, _TRUNCATE, L"setting %ls %d", keys[i], values[i]) < 0)
            void_lift_trap(0x1017E0F0u, "Settings property command too long");
        uint32_t argument = (uint32_t)(uintptr_t)command;
        g_ecx = console;
        native_menu_call(execute, 1, &argument);
    }
    g_eax = saved[0]; g_ecx = saved[1]; g_edx = saved[2]; g_ebx = saved[3];
    g_ebp = saved[4]; g_esi = saved[5]; g_edi = saved[6]; g_esp = saved[7];
    g_flag_k = saved[8]; g_flag_a = saved[9]; g_flag_b = saved[10]; g_flag_cf = saved[11];
    g_cur_func = saved[12];
}
static void native_menu_command(void)
{
    uint32_t wrapper = MEM32(g_esp + 4);
    uint32_t string = MEM32(wrapper);
    const wchar_t *command = (const wchar_t *)(uintptr_t)(string + 8);
    int handled = void_settings_debug_command(command);
    if (!handled) {
        recomp_func_t original = recomp_lookup(0x1017E0F0u);
        if (!original) void_lift_trap(0x1017E0F0u, "Missing original console binding");
        original();
        return;
    }
    native_menu_publish_settings();
    if (handled < 0) fprintf(stderr, "[void-settings] Rejected: %s\n", void_settings_debug_error());
    else fprintf(stderr, "[void-settings] Configuration committed; applies on next launch\n");
    g_eax = 0;
    g_esp += 8;
}
static int initialize_native_menu(const char *game_bin)
{
    wchar_t bin[MAX_PATH], data[MAX_PATH], host[MAX_PATH], assets[MAX_PATH];
    wchar_t *file;
    DWORD length;
    if (!profile_common[0]) return 1;
    if (!MultiByteToWideChar(CP_ACP, 0, game_bin, -1, bin, MAX_PATH) ||
        _snwprintf_s(data, MAX_PATH, _TRUNCATE, L"%ls\\..\\..\\data", bin) < 0) return 0;
    length = GetFullPathNameW(data, MAX_PATH, bin, NULL);
    if (!length || length >= MAX_PATH) return 0;
    length = GetModuleFileNameW(NULL, host, MAX_PATH);
    if (!length || length >= MAX_PATH || !(file = wcsrchr(host, L'\\'))) return 0;
    *file = 0;
    if (_snwprintf_s(assets, MAX_PATH, _TRUNCATE, L"%ls\\..\\runtime-assets", host) < 0) return 0;
    length = GetFullPathNameW(assets, MAX_PATH, data, NULL);
    if (!length || length >= MAX_PATH) return 0;
    if (!void_settings_debug_set_data_directory(bin) || !void_settings_debug_init(profile_common)) {
        fprintf(stderr, "[void-settings] Initialization failed: %s\n", void_settings_debug_error());
        return 0;
    }
    if (!void_asset_overrides_init(bin, data, VOID_MENU_ASSET_SHA256, profile_common)) {
        fprintf(stderr, "[void-assets] Initialization failed: %lu\n", GetLastError());
        return 0;
    }
    native_menu_enabled = 1;
    return 1;
}
#endif
int void_native_config_ready(void)
{
#ifdef VOID_LIFT_GAMEMODULE
    return native_menu_enabled;
#else
    return 0;
#endif
}
#ifdef VOID_LIFT_GAMEMODULE
enum { GM_UNMAPPED, GM_MAPPED, GM_INITIALIZING, GM_READY, GM_DETACHING, GM_DETACHED, GM_RESTORING };
typedef struct {
    const char *name;
    uint32_t base, entry;
    char path[MAX_PATH];
    wchar_t path_w[MAX_PATH];
    volatile LONG state;
    unsigned references, attach_events, detach_events;
    BYTE *pristine;
    uint32_t span, crt_counter;
} manual_module;
static manual_module manual_modules[] = {
    {"GameModule.dll", GAMEMODULE_BASE, GAMEMODULE_ENTRY}
#ifdef VOID_LIFT_ENGINE
    , {"Engine.dll", ENGINE_BASE, ENGINE_ENTRY}
#ifdef VOID_LIFT_FILESYSTEMS
    , {"FS.dll", FS_BASE, FS_ENTRY}, {"VFS.dll", VFS_BASE, VFS_ENTRY}
#ifdef VOID_LIFT_SOUND
    , {"Sound.dll", SOUND_BASE, SOUND_ENTRY}
#ifdef VOID_LIFT_MEDIA
    , {"Video.dll", VIDEO_BASE, VIDEO_ENTRY}
#ifdef VOID_LIFT_RENDERER
    , {"RendererD3D.dll", RENDERER_BASE, RENDERER_ENTRY}
#ifdef VOID_LIFT_NXCHARACTER
    , {"NxCharacter.dll", NXCHARACTER_BASE, NXCHARACTER_ENTRY}
#endif
#endif
#endif
#endif
#endif
#endif
};
#define GM (&manual_modules[0])
#define MANUAL_COUNT (sizeof(manual_modules) / sizeof(manual_modules[0]))
static int gm_self_test;
static CRITICAL_SECTION gm_loader_lock;
#ifdef VOID_LIFT_NXCHARACTER
static int engine_nx_dependency_held;
#endif
#ifdef VOID_LIFT_ENGINE
static const char *engine_image;
#ifdef VOID_LIFT_FILESYSTEMS
static const char *fs_image, *vfs_image;
#ifdef VOID_LIFT_SOUND
static const char *sound_image;
#ifdef VOID_LIFT_MEDIA
static const char *video_image;
#ifdef VOID_LIFT_RENDERER
static const char *renderer_image;
#ifdef VOID_LIFT_NXCHARACTER
static const char *nxcharacter_image;
#endif
#endif
#endif
#endif
#endif
#endif
static const char *basename_a(const char *name)
{
    const char *file = name;
    if (name) for (; *name; ++name) if (*name == '\\' || *name == '/') file = name + 1;
    return file;
}
static const wchar_t *basename_w(const wchar_t *name)
{
    const wchar_t *file = name;
    if (name) for (; *name; ++name) if (*name == L'\\' || *name == L'/') file = name + 1;
    return file;
}
static manual_module *manual_named_a(const char *name)
{
    if (!name) return NULL;
    const char *file = basename_a(name);
    for (size_t i = 0; i < MANUAL_COUNT; ++i) {
        size_t stem = strlen(manual_modules[i].name) - 4;
        if (!_stricmp(file, manual_modules[i].name) ||
            (strlen(file) == stem && !_strnicmp(file, manual_modules[i].name, stem))) return &manual_modules[i];
    }
    return NULL;
}
static manual_module *manual_named_w(const wchar_t *name)
{
    if (!name) return NULL;
    char file[MAX_PATH];
    if (!WideCharToMultiByte(CP_ACP, 0, basename_w(name), -1, file, sizeof(file), NULL, NULL)) return NULL;
    return manual_named_a(file);
}
static manual_module *manual_handle(HMODULE handle)
{
    for (size_t i = 0; i < MANUAL_COUNT; ++i)
        if ((uintptr_t)handle == manual_modules[i].base) return &manual_modules[i];
    return NULL;
}
static int manual_present(const manual_module *module)
{
    return module->state >= GM_INITIALIZING && module->state <= GM_DETACHING;
}
static HMODULE manual_load(manual_module *module);
static BOOL manual_release(manual_module *module, uint32_t reserved, int release_reference)
{
    EnterCriticalSection(&gm_loader_lock);
    if (module->state != GM_READY || (release_reference && !module->references)) {
        LeaveCriticalSection(&gm_loader_lock);
        if (release_reference) SetLastError(ERROR_INVALID_HANDLE);
        return FALSE;
    }
    if (release_reference && --module->references) { LeaveCriticalSection(&gm_loader_lock); return TRUE; }
    module->state = GM_DETACHING;
    ++module->detach_events;
    /* No loader lock while waiting for the guest machine or running guest/native callbacks. */
    LeaveCriticalSection(&gm_loader_lock);
    uint32_t result = void_dll_event(module->entry, module->base, DLL_PROCESS_DETACH, reserved);
    EnterCriticalSection(&gm_loader_lock);
    module->state = GM_DETACHED;
    module->references = 0;
#ifdef VOID_LIFT_NXCHARACTER
    int release_nx = module->base == ENGINE_BASE && engine_nx_dependency_held;
    if (release_nx) engine_nx_dependency_held = 0;
#endif
    LeaveCriticalSection(&gm_loader_lock);
    fprintf(stderr, "[void] Lifted %s detach #%u result=%08X reserved=%08X; mapping retained until process exit\n",
        module->name, module->detach_events, result, reserved);
#ifdef VOID_LIFT_NXCHARACTER
    /* Engine's static imports remain attached throughout its final DllMain. */
    if (release_nx && !manual_release(manual_named_a("NxCharacter.dll"), reserved, 1))
        void_lift_trap(module->entry, "Cannot release Engine's NxCharacter dependency");
#endif
    return TRUE;
}
static void manual_detach_all(uint32_t reserved)
{
    /* GameModule cleanup may still call Engine. */
    for (size_t i = 0; i < MANUAL_COUNT; ++i) (void)manual_release(&manual_modules[i], reserved, 0);
}
static uint32_t manual_attach(manual_module *module)
{
    EnterCriticalSection(&gm_loader_lock);
    if (module->state != GM_MAPPED) { LeaveCriticalSection(&gm_loader_lock); return 0; }
    module->state = GM_INITIALIZING;
    LeaveCriticalSection(&gm_loader_lock);
#ifdef VOID_LIFT_NXCHARACTER
    if (module->base == ENGINE_BASE) {
        /* native32_bind resolves the two static imports without running DllMain. */
        if (!manual_load(manual_named_a("NxCharacter.dll"))) {
            EnterCriticalSection(&gm_loader_lock);
            module->state = GM_MAPPED; /* Engine's entry has not run; a later retry is valid. */
            LeaveCriticalSection(&gm_loader_lock);
            return 0;
        }
        EnterCriticalSection(&gm_loader_lock);
        engine_nx_dependency_held = 1;
        LeaveCriticalSection(&gm_loader_lock);
    }
#endif
    EnterCriticalSection(&gm_loader_lock);
    ++module->attach_events;
    LeaveCriticalSection(&gm_loader_lock);
    uint32_t result = void_dll_event(module->entry, module->base, DLL_PROCESS_ATTACH, 0);
    EnterCriticalSection(&gm_loader_lock);
    module->state = result ? GM_READY : GM_DETACHED;
#ifdef VOID_LIFT_NXCHARACTER
    int release_nx = !result && module->base == ENGINE_BASE && engine_nx_dependency_held;
    if (release_nx) engine_nx_dependency_held = 0;
#endif
    LeaveCriticalSection(&gm_loader_lock);
#ifdef VOID_LIFT_NXCHARACTER
    if (release_nx && !manual_release(manual_named_a("NxCharacter.dll"), 0, 1))
        void_lift_trap(module->entry, "Cannot roll back Engine's NxCharacter dependency");
#endif
    fprintf(stderr, "[void] Lifted %s attach #%u result=%08X; no Windows bootstrap\n",
        module->name, module->attach_events, result);
    if (GetModuleHandleA(module->name)) void_lift_trap(module->entry, "Windows loaded an original manual DLL");
    return result;
}
static HMODULE manual_load(manual_module *module)
{
    EnterCriticalSection(&gm_loader_lock);
    int restore = module->state == GM_DETACHED && module->pristine && !module->references;
    if (restore) module->state = GM_RESTORING;
    LeaveCriticalSection(&gm_loader_lock);
    if (restore) {
        /* Last detach has finished CRT/FLS cleanup; reset all static state before another attach. */
        void_restore_module(module->base, module->span, module->crt_counter, module->pristine);
        EnterCriticalSection(&gm_loader_lock);
        module->state = GM_MAPPED;
        LeaveCriticalSection(&gm_loader_lock);
    }
    /* shortcut: observed startup loads are serial; add waiting if parallel loads are observed. */
    if (module->state == GM_MAPPED && !manual_attach(module)) { SetLastError(ERROR_DLL_INIT_FAILED); return NULL; }
    EnterCriticalSection(&gm_loader_lock);
    if (module->state != GM_READY || module->references == UINT32_MAX) {
        LeaveCriticalSection(&gm_loader_lock); SetLastError(ERROR_DLL_INIT_FAILED); return NULL;
    }
    ++module->references;
    LeaveCriticalSection(&gm_loader_lock);
    return (HMODULE)(uintptr_t)module->base;
}
static FARPROC WINAPI game_proc_address(HMODULE module, LPCSTR name);
static BOOL WINAPI game_free_library(HMODULE module);
static VOID WINAPI game_exit_process(UINT code);
static HMODULE WINAPI game_load_library_w(LPCWSTR name);
#endif
/* Avoid context handover for these current-thread error/slot operations. */
static void thread_get_error(void)
{
    g_eax = GetLastError();
    g_esp += 4;
}
static void thread_set_error(void)
{
    DWORD error = MEM32(g_esp + 4);
    g_esp += 8;
    SetLastError(error);
}
static void thread_tls_value(void)
{
    g_eax = (uint32_t)(uintptr_t)TlsGetValue(MEM32(g_esp + 4));
    g_esp += 8;
}
static void thread_fls_value(void)
{
    g_eax = (uint32_t)(uintptr_t)FlsGetValue(MEM32(g_esp + 4));
    g_esp += 8;
}
static void direct3d_create9(void)
{
    DWORD error = GetLastError();
    HMODULE module = GetModuleHandleA("d3d9.dll");
    if (!module) module = LoadLibraryA("d3d9.dll");
    FARPROC create = module ? GetProcAddress(module, "Direct3DCreate9") : NULL;
    if (!create) void_lift_trap(0, "Cannot resolve Direct3DCreate9");
    recomp_func_t call = recomp_lookup_import((uint32_t)(uintptr_t)create);
    if (!call) void_lift_trap(0, "Cannot bridge Direct3DCreate9");
    SetLastError(error);
    call();
    if (g_eax) d3d_create_device_target = MEM32(MEM32(g_eax) + 16 * 4);
}
static void direct3d_create_device(void)
{
    DWORD error = GetLastError();
    const D3DPRESENT_PARAMETERS *p = (const D3DPRESENT_PARAMETERS *)(uintptr_t)MEM32(g_esp + 24);
    fprintf(stderr, "[void-d3d] CreateDevice this=%08X adapter=%u type=%u focus=%08X behavior=%08X params=%p\n",
        MEM32(g_esp + 4), MEM32(g_esp + 8), MEM32(g_esp + 12), MEM32(g_esp + 16), MEM32(g_esp + 20), p);
    if (p) fprintf(stderr, "[void-d3d] backbuffer=%ux%u format=%u count=%u multisample=%u quality=%u swap=%u hwnd=%p windowed=%u depth=%u depthFormat=%u flags=%08X refresh=%u interval=%08X\n",
        p->BackBufferWidth, p->BackBufferHeight, p->BackBufferFormat, p->BackBufferCount,
        p->MultiSampleType, p->MultiSampleQuality, p->SwapEffect, p->hDeviceWindow,
        p->Windowed, p->EnableAutoDepthStencil, p->AutoDepthStencilFormat, p->Flags,
        p->FullScreen_RefreshRateInHz, p->PresentationInterval);
    SetLastError(error);
    recomp_func_t call = recomp_lookup_import(d3d_create_device_target);
    if (!call) void_lift_trap(d3d_create_device_target, "Cannot bridge Direct3D CreateDevice");
    call();
    error = GetLastError();
    fprintf(stderr, "[void-d3d] CreateDevice result=%08X\n", g_eax);
    SetLastError(error);
}
recomp_func_t recomp_lookup_manual(uint32_t va)
{
#ifdef VOID_LIFT_GAMEMODULE
    if (native_menu_enabled && va == 0x1017E0F0u) return native_menu_command;
#endif
    if (d3d_create_device_target && va == d3d_create_device_target) return direct3d_create_device;
    if (va == (uint32_t)(uintptr_t)GetLastError) return thread_get_error;
    if (va == (uint32_t)(uintptr_t)SetLastError) return thread_set_error;
    if (va == (uint32_t)(uintptr_t)TlsGetValue) return thread_tls_value;
    if (va == (uint32_t)(uintptr_t)FlsGetValue) return thread_fls_value;
    if (va < 0x10000u) void_lift_trap(va, "unresolved guest control-flow target");
    if (native32_in_guest(va)) {
        recomp_func_t target = recomp_lookup(va);
        if (target) return target;
        void_lift_trap(va, "unresolved guest control-flow target");
    }
    return NULL;
}

void void_lift_trap(uint32_t address, const char *instruction)
{
    fprintf(stderr, "[void] Unsupported guest instruction at %08X: %s; caller=%08X last_sync_ESP=%08X last_sync_EAX=%08X last_sync_ECX=%08X last_sync_EDX=%08X\n",
        address, instruction, g_cur_func, g_esp, g_eax, g_ecx, g_edx);
    recomp_dump_trace("unsupported instruction");
    native32_dump_icalls(32);
    /* A fatal dispatch must not run DLL detach callbacks through the broken guest. */
    TerminateProcess(GetCurrentProcess(), 70);
    ExitProcess(70);
}

static HMODULE WINAPI game_module_a(LPCSTR name)
{
#ifdef VOID_LIFT_GAMEMODULE
    manual_module *module = manual_named_a(name);
    if (module) {
        if (manual_present(module)) return (HMODULE)(uintptr_t)module->base;
        SetLastError(ERROR_MOD_NOT_FOUND); return NULL;
    }
#endif
    return (!name || !_stricmp(name, "Game.exe")) ? (HMODULE)(uintptr_t)GAME_BASE : GetModuleHandleA(name);
}
static HMODULE WINAPI game_module_w(LPCWSTR name)
{
#ifdef VOID_LIFT_GAMEMODULE
    manual_module *module = manual_named_w(name);
    if (module) {
        if (manual_present(module)) return (HMODULE)(uintptr_t)module->base;
        SetLastError(ERROR_MOD_NOT_FOUND); return NULL;
    }
#endif
    return (!name || !_wcsicmp(name, L"Game.exe")) ? (HMODULE)(uintptr_t)GAME_BASE : GetModuleHandleW(name);
}
#ifdef VOID_LIFT_GAMEMODULE
/* Engine's DirectInput8Create requires the real Windows-registered host HINSTANCE. */
static HMODULE WINAPI engine_module_a(LPCSTR name)
{
    return name ? game_module_a(name) : GetModuleHandleA(NULL);
}
static HMODULE WINAPI engine_module_w(LPCWSTR name)
{
    return name ? game_module_w(name) : GetModuleHandleW(NULL);
}
#endif
static void module_a(void)
{
    g_eax = (uint32_t)(uintptr_t)game_module_a((LPCSTR)(uintptr_t)MEM32(g_esp + 4));
    g_esp += 8;
}
static void module_w(void)
{
    g_eax = (uint32_t)(uintptr_t)game_module_w((LPCWSTR)(uintptr_t)MEM32(g_esp + 4));
    g_esp += 8;
}
static DWORD WINAPI game_filename_a(HMODULE module, LPSTR buffer, DWORD capacity)
{
#ifdef VOID_LIFT_GAMEMODULE
    manual_module *manual = manual_handle(module);
    if (manual) {
        if (!manual_present(manual)) { SetLastError(ERROR_INVALID_HANDLE); return 0; }
        if (!capacity) { SetLastError(ERROR_INSUFFICIENT_BUFFER); return 0; }
        size_t length = strlen(manual->path);
        strncpy(buffer, manual->path, capacity); buffer[capacity - 1] = 0;
        if (length >= capacity) SetLastError(ERROR_INSUFFICIENT_BUFFER);
        return length < capacity ? (DWORD)length : capacity;
    }
#endif
    if (module && (uintptr_t)module != GAME_BASE) {
        return GetModuleFileNameA(module, buffer, capacity);
    } else if (!capacity) {
        SetLastError(ERROR_INSUFFICIENT_BUFFER); return 0;
    } else {
        size_t length = strlen(original_exe);
        strncpy(buffer, original_exe, capacity);
        buffer[capacity - 1] = 0;
        if (length >= capacity) SetLastError(ERROR_INSUFFICIENT_BUFFER);
        return length < capacity ? (DWORD)length : capacity;
    }
}
static DWORD WINAPI game_filename_w(HMODULE module, LPWSTR buffer, DWORD capacity)
{
#ifdef VOID_LIFT_GAMEMODULE
    manual_module *manual = manual_handle(module);
    if (manual) {
        if (!manual_present(manual)) { SetLastError(ERROR_INVALID_HANDLE); return 0; }
        if (!capacity) { SetLastError(ERROR_INSUFFICIENT_BUFFER); return 0; }
        size_t length = wcslen(manual->path_w);
        wcsncpy(buffer, manual->path_w, capacity); buffer[capacity - 1] = 0;
        if (length >= capacity) SetLastError(ERROR_INSUFFICIENT_BUFFER);
        return length < capacity ? (DWORD)length : capacity;
    }
#endif
    if (module && (uintptr_t)module != GAME_BASE) {
        return GetModuleFileNameW(module, buffer, capacity);
    } else if (!capacity) {
        SetLastError(ERROR_INSUFFICIENT_BUFFER); return 0;
    } else {
        size_t length = wcslen(original_exe_w);
        wcsncpy(buffer, original_exe_w, capacity);
        buffer[capacity - 1] = 0;
        if (length >= capacity) SetLastError(ERROR_INSUFFICIENT_BUFFER);
        return length < capacity ? (DWORD)length : capacity;
    }
}
static void filename_a(void)
{
    g_eax = game_filename_a((HMODULE)(uintptr_t)MEM32(g_esp + 4),
        (LPSTR)(uintptr_t)MEM32(g_esp + 8), MEM32(g_esp + 12));
    g_esp += 16;
}
static void filename_w(void)
{
    g_eax = game_filename_w((HMODULE)(uintptr_t)MEM32(g_esp + 4),
        (LPWSTR)(uintptr_t)MEM32(g_esp + 8), MEM32(g_esp + 12));
    g_esp += 16;
}
static HRESULT WINAPI game_folder_path(HWND window, int folder, HANDLE token, DWORD flags, LPWSTR path)
{
    if (profile_root[0] && (folder & 0xFF) == CSIDL_PERSONAL) {
        wcscpy(path, profile_root);
        return S_OK;
    }
    if (profile_common[0] && (folder & 0xFF) == CSIDL_COMMON_APPDATA) {
        wcscpy(path, profile_common);
        return S_OK;
    }
    return SHGetFolderPathW(window, folder, token, flags, path);
}
static int seed_profile_settings(void)
{
    if (!profile_root[0]) return 1;
    wchar_t source[MAX_PATH], destination[MAX_PATH];
    if (FAILED(SHGetFolderPathW(NULL, CSIDL_COMMON_APPDATA, NULL, SHGFP_TYPE_CURRENT, source))) return 0;
    const wchar_t *suffix = L"\\Ice-pick Lodge\\Void";
    if (wcslen(profile_root) + wcslen(L"\\CommonAppData") + wcslen(suffix) + 16 >= MAX_PATH ||
            wcslen(source) + wcslen(suffix) + 16 >= MAX_PATH) return 0;
    wcscpy(profile_common, profile_root); wcscat(profile_common, L"\\CommonAppData");
    wcscpy(destination, profile_common); wcscat(destination, suffix);
    wcscat(source, suffix);
    int created = SHCreateDirectoryExW(NULL, destination, NULL);
    if (created != ERROR_SUCCESS && created != ERROR_ALREADY_EXISTS && created != ERROR_FILE_EXISTS) return 0;
    const wchar_t *files[] = {L"rcfg.xml", L"scfg.xml", L"settings.xml"};
    for (unsigned i = 0; i < sizeof(files) / sizeof(files[0]); ++i) {
        wchar_t input[MAX_PATH], output[MAX_PATH];
        swprintf(input, MAX_PATH, L"%ls\\%ls", source, files[i]);
        swprintf(output, MAX_PATH, L"%ls\\%ls", destination, files[i]);
        if (!CopyFileW(input, output, TRUE)) {
            DWORD error = GetLastError();
            if (error != ERROR_FILE_EXISTS && error != ERROR_FILE_NOT_FOUND && error != ERROR_PATH_NOT_FOUND) return 0;
        }
    }
    return 1;
}
static void folder_path(void)
{
    g_eax = (uint32_t)game_folder_path((HWND)(uintptr_t)MEM32(g_esp + 4), (int)MEM32(g_esp + 8),
        (HANDLE)(uintptr_t)MEM32(g_esp + 12), MEM32(g_esp + 16), (LPWSTR)(uintptr_t)MEM32(g_esp + 20));
    g_esp += 24;
}
static BOOL WINAPI game_show_window(HWND window, int command)
{
    return void_window_show(window, command, void_native_config_ready());
}
static BOOL WINAPI game_window_position(HWND window, HWND after, int x, int y, int width, int height, UINT flags)
{
    return void_window_position(window, after, x, y, width, height, flags, void_native_config_ready());
}
static void show_window(void)
{
    g_eax = game_show_window((HWND)(uintptr_t)MEM32(g_esp + 4), (int)MEM32(g_esp + 8));
    g_esp += 12;
}
static void window_position(void)
{
    g_eax = game_window_position((HWND)(uintptr_t)MEM32(g_esp + 4), (HWND)(uintptr_t)MEM32(g_esp + 8),
        (int)MEM32(g_esp + 12), (int)MEM32(g_esp + 16), (int)MEM32(g_esp + 20),
        (int)MEM32(g_esp + 24), MEM32(g_esp + 28));
    g_esp += 32;
}
static void asset_create_file_a(void)
{
    g_eax = (uint32_t)(uintptr_t)void_asset_create_file_a((LPCSTR)(uintptr_t)MEM32(g_esp + 4),
        MEM32(g_esp + 8), MEM32(g_esp + 12), (LPSECURITY_ATTRIBUTES)(uintptr_t)MEM32(g_esp + 16),
        MEM32(g_esp + 20), MEM32(g_esp + 24), (HANDLE)(uintptr_t)MEM32(g_esp + 28));
    g_esp += 32;
}
static void asset_create_file_w(void)
{
    g_eax = (uint32_t)(uintptr_t)void_asset_create_file_w((LPCWSTR)(uintptr_t)MEM32(g_esp + 4),
        MEM32(g_esp + 8), MEM32(g_esp + 12), (LPSECURITY_ATTRIBUTES)(uintptr_t)MEM32(g_esp + 16),
        MEM32(g_esp + 20), MEM32(g_esp + 24), (HANDLE)(uintptr_t)MEM32(g_esp + 28));
    g_esp += 32;
}
static void asset_attributes_a(void)
{
    g_eax = void_asset_get_file_attributes_a((LPCSTR)(uintptr_t)MEM32(g_esp + 4));
    g_esp += 8;
}
static void asset_attributes_w(void)
{
    g_eax = void_asset_get_file_attributes_w((LPCWSTR)(uintptr_t)MEM32(g_esp + 4));
    g_esp += 8;
}
static HMODULE WINAPI game_load_library_a(LPCSTR name);
#ifdef VOID_LIFT_GAMEMODULE
static FARPROC WINAPI engine_proc_address(HMODULE module, LPCSTR name);
#endif

/* Native DLLs must see the same executable identity as the lifted launcher. */
static void patch_dll_identity(HMODULE module)
{
    BYTE *base = (BYTE *)module;
    IMAGE_NT_HEADERS32 *nt = (IMAGE_NT_HEADERS32 *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    DWORD rva = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;
    if (!rva) return;
    IMAGE_IMPORT_DESCRIPTOR *imports = (IMAGE_IMPORT_DESCRIPTOR *)(base + rva);
    for (; imports->Name; ++imports) {
        if (!imports->OriginalFirstThunk) continue;
        IMAGE_THUNK_DATA32 *names = (IMAGE_THUNK_DATA32 *)(base + imports->OriginalFirstThunk);
        IMAGE_THUNK_DATA32 *slots = (IMAGE_THUNK_DATA32 *)(base + imports->FirstThunk);
        for (; names->u1.AddressOfData; ++names, ++slots) {
            if (IMAGE_SNAP_BY_ORDINAL32(names->u1.Ordinal)) continue;
            const char *name = (const char *)((IMAGE_IMPORT_BY_NAME *)(base + names->u1.AddressOfData))->Name;
            void *replacement = NULL;
            if (!strcmp(name, "GetModuleFileNameA")) replacement = game_filename_a;
            if (!strcmp(name, "GetModuleFileNameW")) replacement = game_filename_w;
            if (!strcmp(name, "GetModuleHandleA")) replacement = game_module_a;
            if (!strcmp(name, "GetModuleHandleW")) replacement = game_module_w;
            if (!strcmp(name, "SHGetFolderPathW")) replacement = game_folder_path;
            if (!strcmp(name, "CreateFileA")) replacement = void_asset_create_file_a;
            if (!strcmp(name, "CreateFileW")) replacement = void_asset_create_file_w;
            if (!strcmp(name, "GetFileAttributesA")) replacement = void_asset_get_file_attributes_a;
            if (!strcmp(name, "GetFileAttributesW")) replacement = void_asset_get_file_attributes_w;
            if (!strcmp(name, "ShowWindow")) replacement = game_show_window;
            if (!strcmp(name, "SetWindowPos")) replacement = game_window_position;
#ifdef VOID_LIFT_GAMEMODULE
            int engine = module == GetModuleHandleA("Engine.dll");
#ifdef VOID_LIFT_ENGINE
            engine |= (uintptr_t)module == ENGINE_BASE;
#endif
            if (engine) {
                if (!strcmp(name, "GetModuleHandleA")) replacement = engine_module_a;
                if (!strcmp(name, "GetModuleHandleW")) replacement = engine_module_w;
            }
            if (!strcmp(name, "LoadLibraryA")) replacement = game_load_library_a;
            if (!strcmp(name, "LoadLibraryW")) replacement = game_load_library_w;
            if (!strcmp(name, "GetProcAddress")) replacement = engine ? engine_proc_address : game_proc_address;
            if (!strcmp(name, "FreeLibrary")) replacement = game_free_library;
            if (!strcmp(name, "ExitProcess")) replacement = game_exit_process;
#endif
            if (!replacement || slots->u1.Function == (DWORD)(uintptr_t)replacement) continue;
            DWORD old;
            if (!VirtualProtect(&slots->u1.Function, sizeof(DWORD), PAGE_READWRITE, &old))
                void_lift_trap((uint32_t)(uintptr_t)slots, "Cannot patch DLL identity import");
            slots->u1.Function = (DWORD)(uintptr_t)replacement;
            DWORD ignored;
            if (!VirtualProtect(&slots->u1.Function, sizeof(DWORD), old, &ignored))
                void_lift_trap((uint32_t)(uintptr_t)slots, "Cannot restore DLL import protection");
        }
    }
}
static void patch_loaded_dlls(void)
{
    const char *dlls[] = {"GameModule.dll", "Engine.dll", "FS.dll", "VFS.dll", "RendererD3D.dll", "Sound.dll", "Video.dll"};
    for (size_t i = 0; i < sizeof(dlls) / sizeof(dlls[0]); ++i) {
        HMODULE loaded = GetModuleHandleA(dlls[i]);
        if (loaded) patch_dll_identity(loaded);
    }
}
static HMODULE WINAPI game_load_library_a(LPCSTR name)
{
#ifdef VOID_LIFT_GAMEMODULE
    manual_module *manual = manual_named_a(name);
    if (manual) return manual_load(manual);
#endif
    HMODULE module = LoadLibraryA(name);
    DWORD error = GetLastError();
    patch_loaded_dlls();
    SetLastError(error);
    return module;
}
static void load_library_a(void)
{
    g_eax = (uint32_t)(uintptr_t)game_load_library_a((LPCSTR)(uintptr_t)MEM32(g_esp + 4));
    g_esp += 8;
}
#ifdef VOID_LIFT_GAMEMODULE
static HMODULE WINAPI game_load_library_w(LPCWSTR name)
{
    manual_module *manual = manual_named_w(name);
    if (manual) return manual_load(manual);
    HMODULE module = LoadLibraryW(name);
    DWORD error = GetLastError();
    patch_loaded_dlls(); SetLastError(error);
    return module;
}
static FARPROC WINAPI game_proc_address(HMODULE module, LPCSTR name)
{
    manual_module *manual = manual_handle(module);
    if (manual || (uintptr_t)module == GAME_BASE) {
        if (manual && !manual_present(manual)) {
            SetLastError(ERROR_INVALID_HANDLE); return NULL;
        }
        uint32_t address = native32_export((uint32_t)(uintptr_t)module, name);
        if (!address) SetLastError(ERROR_PROC_NOT_FOUND);
        return (FARPROC)(uintptr_t)address;
    }
    if ((uintptr_t)name >= 0x10000 && module == GetModuleHandleA("user32.dll")) {
        if (!strcmp(name, "ShowWindow")) return (FARPROC)game_show_window;
        if (!strcmp(name, "SetWindowPos")) return (FARPROC)game_window_position;
    }
    /* Dynamic kernel API lookups use the same identity/lifecycle adapters as static IATs. */
    if ((uintptr_t)name >= 0x10000 &&
        (module == GetModuleHandleA("kernel32.dll") || module == GetModuleHandleA("kernelbase.dll"))) {
        if (!strcmp(name, "GetModuleHandleA")) return (FARPROC)game_module_a;
        if (!strcmp(name, "GetModuleHandleW")) return (FARPROC)game_module_w;
        if (!strcmp(name, "GetModuleFileNameA")) return (FARPROC)game_filename_a;
        if (!strcmp(name, "GetModuleFileNameW")) return (FARPROC)game_filename_w;
        if (!strcmp(name, "LoadLibraryA")) return (FARPROC)game_load_library_a;
        if (!strcmp(name, "LoadLibraryW")) return (FARPROC)game_load_library_w;
        if (!strcmp(name, "GetProcAddress")) return (FARPROC)game_proc_address;
        if (!strcmp(name, "FreeLibrary")) return (FARPROC)game_free_library;
        if (!strcmp(name, "ExitProcess")) return (FARPROC)game_exit_process;
        if (!strcmp(name, "CreateFileA")) return (FARPROC)void_asset_create_file_a;
        if (!strcmp(name, "CreateFileW")) return (FARPROC)void_asset_create_file_w;
        if (!strcmp(name, "GetFileAttributesA")) return (FARPROC)void_asset_get_file_attributes_a;
        if (!strcmp(name, "GetFileAttributesW")) return (FARPROC)void_asset_get_file_attributes_w;
    }
    return GetProcAddress(module, name);
}
static FARPROC WINAPI engine_proc_address(HMODULE module, LPCSTR name)
{
    if ((uintptr_t)name >= 0x10000 &&
        (module == GetModuleHandleA("kernel32.dll") || module == GetModuleHandleA("kernelbase.dll"))) {
        if (!strcmp(name, "GetModuleHandleA")) return (FARPROC)engine_module_a;
        if (!strcmp(name, "GetModuleHandleW")) return (FARPROC)engine_module_w;
        if (!strcmp(name, "GetProcAddress")) return (FARPROC)engine_proc_address;
    }
    return game_proc_address(module, name);
}
static BOOL WINAPI game_free_library(HMODULE module)
{
    manual_module *manual = manual_handle(module);
    return manual ? manual_release(manual, 0, 1) : FreeLibrary(module);
}
static VOID WINAPI game_exit_process(UINT code)
{
    manual_detach_all(1); /* These binaries test reserved for NULL; nonzero denotes process termination. */
    ExitProcess(code);
}
static void load_library_w(void)
{
    g_eax = (uint32_t)(uintptr_t)game_load_library_w((LPCWSTR)(uintptr_t)MEM32(g_esp + 4));
    g_esp += 8;
}
static void proc_address(void)
{
    g_eax = (uint32_t)(uintptr_t)game_proc_address((HMODULE)(uintptr_t)MEM32(g_esp + 4), (LPCSTR)(uintptr_t)MEM32(g_esp + 8));
    g_esp += 12;
}
static void free_library(void)
{
    g_eax = game_free_library((HMODULE)(uintptr_t)MEM32(g_esp + 4));
    g_esp += 8;
}
static void exit_process(void) { game_exit_process(MEM32(g_esp + 4)); }
#endif
static void reg_open_w(void)
{
    HKEY root = (HKEY)(uintptr_t)MEM32(g_esp + 4);
    LPCWSTR path = (LPCWSTR)(uintptr_t)MEM32(g_esp + 8);
    PHKEY key = (PHKEY)(uintptr_t)MEM32(g_esp + 20);
    LSTATUS status = RegOpenKeyExW(root, path, MEM32(g_esp + 12), MEM32(g_esp + 16), key);
    if (!status && root == HKEY_LOCAL_MACHINE && path && !_wcsicmp(path, L"Software\\Ice-pick Lodge\\Void"))
        game_settings_key = *key;
    g_eax = (uint32_t)status;
    g_esp += 24;
}
static void reg_close(void)
{
    HKEY key = (HKEY)(uintptr_t)MEM32(g_esp + 4);
    LSTATUS status = RegCloseKey(key);
    if (!status && key == game_settings_key) game_settings_key = NULL;
    g_eax = (uint32_t)status;
    g_esp += 8;
}
static void reg_query_w(void)
{
    HKEY key = (HKEY)(uintptr_t)MEM32(g_esp + 4);
    LPCWSTR value = (LPCWSTR)(uintptr_t)MEM32(g_esp + 8);
    LPDWORD reserved = (LPDWORD)(uintptr_t)MEM32(g_esp + 12);
    LPDWORD type = (LPDWORD)(uintptr_t)MEM32(g_esp + 16);
    LPBYTE data = (LPBYTE)(uintptr_t)MEM32(g_esp + 20);
    LPDWORD size = (LPDWORD)(uintptr_t)MEM32(g_esp + 24);
    char name[256] = "";
    if (value) WideCharToMultiByte(CP_UTF8, 0, value, -1, name, sizeof(name), NULL, NULL);
    DWORD input_size = size ? *size : 0;
    LSTATUS status = RegQueryValueExW(key, value, reserved, type, data, size);
    /* Config writes this existing user setting to VirtualStore; direct HKLM reads miss it even with virtualization enabled. */
    if (status == ERROR_FILE_NOT_FOUND && key == game_settings_key && value && !_wcsicmp(value, L"FirstRun")) {
        HKEY user_key;
        if (!RegOpenKeyExW(HKEY_CURRENT_USER,
            L"Software\\Classes\\VirtualStore\\MACHINE\\SOFTWARE\\WOW6432Node\\Ice-pick Lodge\\Void",
            0, KEY_QUERY_VALUE, &user_key)) {
            if (size) *size = input_size;
            status = RegQueryValueExW(user_key, value, reserved, type, data, size);
            RegCloseKey(user_key);
            fprintf(stderr, "[void-reg] Existing Config VirtualStore FirstRun read: %ld\n", status);
        }
    }
    fprintf(stderr, "[void-reg] key=%p name='%s' reserved=%p size_in=%lu type_ptr=%p data_ptr=%p status=%ld type=%lu size_out=%lu\n",
        key, name, reserved, input_size, type, data, status, type ? *type : 0, size ? *size : 0);
    g_eax = (uint32_t)status;
    g_esp += 28;
}

static LONG WINAPI fault(EXCEPTION_POINTERS *exception)
{
    fprintf(stderr, "[void] Host fault %08lX at %p, guest=%08X ESP=%08X EAX=%08X ECX=%08X\n",
        exception->ExceptionRecord->ExceptionCode,
        exception->ExceptionRecord->ExceptionAddress, g_cur_func, g_esp, g_eax, g_ecx);
    recomp_trace_flush(); recomp_dump_trace("host exception"); native32_dump_icalls(32);
    return EXCEPTION_EXECUTE_HANDLER;
}
static LONG CALLBACK diagnostic_fault(EXCEPTION_POINTERS *exception)
{
    EXCEPTION_RECORD *record = exception->ExceptionRecord;
    if (record->ExceptionCode == EXCEPTION_ACCESS_VIOLATION && record->NumberParameters >= 2 &&
        record->ExceptionInformation[0] != 8 && record->ExceptionInformation[1] != (ULONG_PTR)record->ExceptionAddress) {
        fprintf(stderr, "[void] AV access=%lu address=%p PC=%p native_EAX=%08lX native_ECX=%08lX native_EDX=%08lX\n",
            (DWORD)record->ExceptionInformation[0], (void *)record->ExceptionInformation[1], record->ExceptionAddress,
            exception->ContextRecord->Eax, exception->ContextRecord->Ecx, exception->ContextRecord->Edx);
        fault(exception);
    }
    return EXCEPTION_CONTINUE_SEARCH;
}
#ifdef VOID_LIFT_GAMEMODULE
static int module_api_self_test(void)
{
    typedef struct { const char *name; unsigned ordinal; uint32_t address; int code; } export_check;
    HMODULE module = (HMODULE)(uintptr_t)GAMEMODULE_BASE;
    char filename[MAX_PATH];
    uint32_t precision_errata = IsProcessorFeaturePresent(PF_FLOATING_POINT_PRECISION_ERRATA) ? 1u : 0u;
    if (MEM32(GAMEMODULE_BASE + 0x2DB3A8) != precision_errata) {
        fprintf(stderr, "[void-self-test] GameModule CRT precision-errata flag FAILED\n"); return 71;
    }
    fprintf(stderr, "[void-self-test] GameModule CRT precision-errata flag=%u; native Win32=%u\n",
        MEM32(GAMEMODULE_BASE + 0x2DB3A8), precision_errata);
    int ok = GM->state == GM_READY && GM->attach_events == 1 &&
        MEM32(GAMEMODULE_BASE + 0x2DB314) == 1 && /* Original CRT process-attach count. */
        GetModuleHandleA("GameModule.dll") == NULL &&
        game_module_a(NULL) == (HMODULE)(uintptr_t)GAME_BASE &&
        game_module_a("Game.exe") == (HMODULE)(uintptr_t)GAME_BASE &&
        game_module_a(GM->path) == module && game_module_w(L"GameModule.dll") == module &&
        engine_module_a(NULL) == GetModuleHandleA(NULL) &&
        engine_module_w(NULL) == GetModuleHandleW(NULL) &&
        engine_module_a("GameModule.dll") == module && engine_module_w(L"GameModule.dll") == module &&
        game_filename_a(module, filename, MAX_PATH) == strlen(GM->path) &&
        !strcmp(filename, GM->path) &&
        game_proc_address(module, "_createFactory@0") == (FARPROC)(uintptr_t)0x10187940 &&
        game_proc_address(module, (LPCSTR)(uintptr_t)8) == (FARPROC)(uintptr_t)0x10187940 &&
        game_proc_address(GetModuleHandleA("kernel32.dll"), "GetModuleHandleA") == (FARPROC)game_module_a;
    if (!ok) { fprintf(stderr, "[void-self-test] Module API/CRT attach check FAILED\n"); return 71; }
    if (game_proc_address(module, "__void_missing_export__") || GetLastError() != ERROR_PROC_NOT_FOUND ||
        game_load_library_a("GameModule.dll") != module || game_load_library_w(GM->path_w) != module ||
        GM->references != 2 || !game_free_library(module) || GM->state != GM_READY || GM->references != 1 ||
        !game_free_library(module) || GM->state != GM_DETACHED || GM->detach_events != 1 ||
        MEM32(GAMEMODULE_BASE + 0x2DB314) != 0 || game_free_library(module) ||
        game_proc_address(module, "_createFactory@0") || game_module_a("GameModule.dll")) {
        fprintf(stderr, "[void-self-test] Export/reference/detach check FAILED\n"); return 71;
    }
#ifdef VOID_LIFT_ENGINE
    manual_module *engine = &manual_modules[1];
    HMODULE engine_handle = (HMODULE)(uintptr_t)ENGINE_BASE;
#ifdef VOID_LIFT_NXCHARACTER
    manual_module *nx_dependency = manual_named_a("NxCharacter.dll");
    if (engine_nx_dependency_held || nx_dependency->state != GM_MAPPED || nx_dependency->references ||
        nx_dependency->attach_events || MEM32(NXCHARACTER_CRT_COUNT)) return 71;
#endif
    if (engine->state != GM_MAPPED || engine->attach_events ||
        game_module_a("Engine.dll") || game_module_w(L"Engine.dll") ||
        game_proc_address(engine_handle, "_createFactory@0") ||
        game_load_library_w(L"Engine.dll") != engine_handle || engine->state != GM_READY ||
        engine->attach_events != 1 || engine->references != 1 || GetModuleHandleA("Engine.dll") ||
        MEM32(ENGINE_BASE + 0x14C760) != 1 ||
#ifdef VOID_LIFT_NXCHARACTER
        !engine_nx_dependency_held || nx_dependency->state != GM_READY || nx_dependency->references != 1 ||
        nx_dependency->attach_events != 1 || nx_dependency->detach_events ||
        MEM32(NXCHARACTER_CRT_COUNT) != 1 || GetModuleHandleA("NxCharacter.dll") ||
#endif
        game_proc_address(engine_handle, "_createFactory@0") != (FARPROC)(uintptr_t)ENGINE_FACTORY ||
        engine_proc_address(GetModuleHandleA("kernel32.dll"), "GetModuleHandleA") != (FARPROC)engine_module_a ||
        engine_proc_address(GetModuleHandleA("kernel32.dll"), "GetProcAddress") != (FARPROC)engine_proc_address ||
        game_filename_a(engine_handle, filename, MAX_PATH) != strlen(engine->path) || strcmp(filename, engine->path) ||
        game_load_library_a("Engine") != engine_handle || engine->references != 2 ||
        !game_free_library(engine_handle) || engine->state != GM_READY || engine->references != 1 ||
#ifdef VOID_LIFT_NXCHARACTER
        !engine_nx_dependency_held || nx_dependency->state != GM_READY || nx_dependency->references != 1 ||
        MEM32(NXCHARACTER_CRT_COUNT) != 1 ||
#endif
        !game_free_library(engine_handle) || engine->state != GM_DETACHED || engine->detach_events != 1 ||
        MEM32(ENGINE_BASE + 0x14C760) != 0 ||
        game_module_a("Engine.dll") || game_load_library_a("Engine.dll")) {
        fprintf(stderr, "[void-self-test] Engine lifecycle/export/identity check FAILED\n"); return 71;
    }
#ifdef VOID_LIFT_NXCHARACTER
    if (engine_nx_dependency_held || nx_dependency->state != GM_DETACHED || nx_dependency->references ||
        nx_dependency->detach_events != 1 || MEM32(NXCHARACTER_CRT_COUNT) || game_module_a("NxCharacter.dll")) {
        fprintf(stderr, "[void-self-test] Engine static NxCharacter dependency release FAILED\n"); return 71;
    }
#endif
#endif
#ifdef VOID_LIFT_FILESYSTEMS
    const uint32_t factories[] = {FS_FACTORY, VFS_FACTORY
#ifdef VOID_LIFT_SOUND
        , SOUND_FACTORY
#ifdef VOID_LIFT_MEDIA
        , VIDEO_FACTORY
#ifdef VOID_LIFT_RENDERER
        , RENDERER_FACTORY
#ifdef VOID_LIFT_NXCHARACTER
        , NXCHARACTER_FACTORY
#endif
#endif
#endif
#endif
    };
    const uint32_t crt_counters[] = {FS_BASE + 0x35078, VFS_BASE + 0x2CD20
#ifdef VOID_LIFT_SOUND
        , SOUND_CRT_COUNT
#ifdef VOID_LIFT_MEDIA
        , VIDEO_CRT_COUNT
#ifdef VOID_LIFT_RENDERER
        , RENDERER_CRT_COUNT
#ifdef VOID_LIFT_NXCHARACTER
        , NXCHARACTER_CRT_COUNT
#endif
#endif
#endif
#endif
    };
    for (size_t i = 2; i < MANUAL_COUNT; ++i) {
        manual_module *file_module = &manual_modules[i];
        HMODULE file_handle = (HMODULE)(uintptr_t)file_module->base;
        const char *factory_name = "_createFactory@0";
        unsigned factory_ordinal = 1;
        const export_check *exports = NULL;
        size_t export_count = 0;
#ifdef VOID_LIFT_RENDERER
        static const export_check renderer_exports[] = {
            {"_createFactory@0", 1, RENDERER_BASE + 0x16F640, 1},
            {"shcode", 2, RENDERER_BASE + 0x16F680, 1},
            {"sphereMap", 3, RENDERER_BASE + 0x16FC60, 1},
            {"test", 4, RENDERER_BASE + 0x16F630, 1}
        };
        if (file_module->base == RENDERER_BASE) {
            exports = renderer_exports; export_count = sizeof(renderer_exports) / sizeof(renderer_exports[0]);
        }
#endif
#ifdef VOID_LIFT_NXCHARACTER
        static const export_check nx_exports[] = {
            {"??0NxControllerManager@@IAE@XZ", 1, NXCHARACTER_BASE + 0x3CE0, 1},
            {"??0NxControllerManager@@QAE@ABV0@@Z", 2, NXCHARACTER_BASE + 0x3D00, 1},
            {"??1NxControllerManager@@MAE@XZ", 3, NXCHARACTER_BASE + 0x3CF0, 1},
            {"??4NxControllerManager@@QAEAAV0@ABV0@@Z", 4, NXCHARACTER_BASE + 0x3D10, 1},
            {"??_7NxControllerManager@@6B@", 5, NXCHARACTER_BASE + 0x14400, 0},
            {"NxCreateControllerManager", 6, NXCHARACTER_FACTORY, 1},
            {"NxReleaseControllerManager", 7, NXCHARACTER_RELEASE, 1}
        };
        if (file_module->base == NXCHARACTER_BASE) {
            factory_name = "NxCreateControllerManager"; factory_ordinal = 6;
            exports = nx_exports; export_count = sizeof(nx_exports) / sizeof(nx_exports[0]);
        }
#endif
        unsigned initial_events = 0;
        LONG initial_state = GM_MAPPED;
#ifdef VOID_LIFT_NXCHARACTER
        if (file_module->base == NXCHARACTER_BASE) { initial_events = 1; initial_state = GM_DETACHED; }
#endif
        if (file_module->state != initial_state || file_module->attach_events != initial_events ||
            file_module->detach_events != initial_events || MEM32(crt_counters[i - 2]) != 0 ||
            !file_module->pristine || game_module_a(file_module->name) || GetModuleHandleA(file_module->name)) {
            fprintf(stderr, "[void-self-test] %s pristine mapping check FAILED\n", file_module->name); return 71;
        }
        for (unsigned cycle = 1; cycle <= 2; ++cycle) {
            if (cycle == 2) MEM8(file_module->base + file_module->span - 1) ^= 0xA5;
            if (
            game_load_library_a(file_module->name) != file_handle || file_module->state != GM_READY ||
            file_module->attach_events != initial_events + cycle || file_module->references != 1 || MEM32(crt_counters[i - 2]) != 1 ||
            MEM8(file_module->base + file_module->span - 1) != file_module->pristine[file_module->span - 1] ||
            game_proc_address(file_handle, factory_name) != (FARPROC)(uintptr_t)factories[i - 2] ||
            game_proc_address(file_handle, (LPCSTR)(uintptr_t)factory_ordinal) != (FARPROC)(uintptr_t)factories[i - 2] ||
            game_filename_a(file_handle, filename, MAX_PATH) != strlen(file_module->path) || strcmp(filename, file_module->path)) {
                fprintf(stderr, "[void-self-test] %s attach/export cycle %u FAILED\n", file_module->name, cycle); return 71;
            }
            uint32_t errata_address = 0;
#ifdef VOID_LIFT_SOUND
            if (file_module->base == SOUND_BASE) errata_address = SOUND_BASE + 0xCCF5C;
#endif
#ifdef VOID_LIFT_RENDERER
            if (file_module->base == RENDERER_BASE) errata_address = RENDERER_BASE + 0x357CF8;
#endif
            if (errata_address) {
                if (MEM32(errata_address) != precision_errata) {
                    fprintf(stderr, "[void-self-test] %s CRT precision-errata flag cycle %u FAILED\n", file_module->name, cycle);
                    return 71;
                }
                fprintf(stderr, "[void-self-test] %s CRT precision-errata flag=%u; native Win32=%u; cycle=%u\n",
                    file_module->name, MEM32(errata_address), precision_errata, cycle);
            }
            for (size_t e = 0; e < export_count; ++e) {
                if (game_proc_address(file_handle, exports[e].name) != (FARPROC)(uintptr_t)exports[e].address ||
                    game_proc_address(file_handle, (LPCSTR)(uintptr_t)exports[e].ordinal) != (FARPROC)(uintptr_t)exports[e].address ||
                    (exports[e].code && !recomp_lookup(exports[e].address)) ||
                    (!exports[e].code && recomp_lookup(exports[e].address))) {
                    fprintf(stderr, "[void-self-test] %s export %s cycle %u FAILED\n", file_module->name, exports[e].name, cycle);
                    return 71;
                }
            }
            if (export_count && (game_proc_address(file_handle, "__void_missing_export__") ||
                game_proc_address(file_handle, (LPCSTR)(uintptr_t)0) ||
                game_proc_address(file_handle, (LPCSTR)(uintptr_t)(export_count + 1)) || GetLastError() != ERROR_PROC_NOT_FOUND)) {
                fprintf(stderr, "[void-self-test] %s missing export bounds FAILED\n", file_module->name); return 71;
            }
            if (
            game_load_library_w(file_module->path_w) != file_handle || file_module->references != 2 ||
            !game_free_library(file_handle) || file_module->state != GM_READY || file_module->references != 1 ||
            !game_free_library(file_handle) || file_module->state != GM_DETACHED || file_module->detach_events != initial_events + cycle ||
            MEM32(crt_counters[i - 2]) != 0 ||
            game_module_a(file_module->name) || game_free_library(file_handle) ||
            game_proc_address(file_handle, factory_name)) {
                fprintf(stderr, "[void-self-test] %s lifecycle/export/identity cycle %u FAILED\n", file_module->name, cycle); return 71;
            }
        }
    }
#endif
    fprintf(stderr, "[void-self-test] PASS: original CRT attach/detach counts, no native manual DLLs, names/paths, Engine host identity, exports/ordinal, references; selected plugin reload cycles\n");
    return 0;
}
#endif
static DWORD WINAPI run_game(void *unused)
{
    (void)unused;
#ifdef VOID_LIFT_GAMEMODULE
    uint32_t attached = manual_attach(GM);
    if (!attached) void_lift_trap(GAMEMODULE_ENTRY, "Lifted GameModule DLL_PROCESS_ATTACH returned FALSE");
    fprintf(stderr, "[void] Lifted GameModule attach #%u result=%08X CRT_count=%u; PE TLS absent; lazy CRT TLS/FLS, no synthetic DLL thread notifications\n",
        GM->attach_events, attached, MEM32(GAMEMODULE_BASE + 0x2DB314));
    if (GetModuleHandleA("GameModule.dll")) void_lift_trap(GAMEMODULE_ENTRY, "Windows loaded an original GameModule alongside the manual image");
    if (gm_self_test) {
        int code = module_api_self_test();
        manual_detach_all(0);
        return code;
    }
#endif
    fprintf(stderr, "[void] Starting lifted Game.exe at %08X\n", GAME_ENTRY);
    native32_call_guest(GAME_ENTRY, 0, NULL);
    fprintf(stderr, "[void] Guest returned EAX=%08X\n", g_eax);
    DWORD code = g_eax;
#ifdef VOID_LIFT_GAMEMODULE
    manual_detach_all(0);
#endif
    return code;
}

/* The order must be identical for both binds: each bind rebuilds the synthetic shim VA table. */
static native32_shim_t host_shims[] = {
    {"ShowWindow", show_window, 0}, {"SetWindowPos", window_position, 0},
    {"CreateFileA", asset_create_file_a, 0}, {"CreateFileW", asset_create_file_w, 0},
    {"GetFileAttributesA", asset_attributes_a, 0}, {"GetFileAttributesW", asset_attributes_w, 0},
    {"Direct3DCreate9", direct3d_create9, 0},
    {"GetModuleHandleA", module_a, 0}, {"GetModuleHandleW", module_w, 0},
    {"GetModuleFileNameA", filename_a, 0}, {"GetModuleFileNameW", filename_w, 0},
    {"LoadLibraryA", load_library_a, 0}, {"RegQueryValueExW", reg_query_w, 0},
    {"RegOpenKeyExW", reg_open_w, 0}, {"RegCloseKey", reg_close, 0},
    {"SHGetFolderPathW", folder_path, 0}
    , {"RaiseException", void_raise_exception, 0}
#ifdef VOID_LIFT_GAMEMODULE
    , {"LoadLibraryW", load_library_w, 0}, {"GetProcAddress", proc_address, 0},
    {"FreeLibrary", free_library, 0}, {"ExitProcess", exit_process, 0}
#endif
};

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "Usage: void-x86.exe <recovered Game.exe> <original game bin directory> [trace options]\n");
        return 64;
    }
    setvbuf(stderr, NULL, _IONBF, 0);
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    SetUnhandledExceptionFilter(fault);
    DWORD profile_length = GetEnvironmentVariableW(L"VOID_PROFILE_ROOT", profile_root, MAX_PATH);
    if (profile_length >= MAX_PATH) { fprintf(stderr, "[void] Profile path too long\n"); return 65; }
    if (strlen(argv[2]) + sizeof("\\Game.exe") > sizeof(original_exe)) return 65;
    snprintf(original_exe, sizeof(original_exe), "%s\\Game.exe", argv[2]);
    if (!MultiByteToWideChar(CP_ACP, 0, original_exe, -1, original_exe_w, MAX_PATH)) return 65;
#ifdef VOID_LIFT_GAMEMODULE
    for (size_t i = 0; i < MANUAL_COUNT; ++i) {
        manual_module *module = &manual_modules[i];
        if (strlen(argv[2]) + strlen(module->name) + 2 > sizeof(module->path)) return 65;
        snprintf(module->path, sizeof(module->path), "%s\\%s", argv[2], module->name);
        if (!MultiByteToWideChar(CP_ACP, 0, module->path, -1, module->path_w, MAX_PATH)) return 65;
    }
#endif
    if (!seed_profile_settings()) { fprintf(stderr, "[void] Cannot initialize isolated common settings\n"); return 66; }
#ifdef VOID_LIFT_GAMEMODULE
    if (!initialize_native_menu(argv[2])) return 66;
#endif
    if (!SetCurrentDirectoryA(argv[2]) || !SetDllDirectoryA(argv[2])) {
        fprintf(stderr, "[void] Cannot select original DLL directory: %lu\n", GetLastError()); return 66;
    }
    for (int i = 3; i < argc; ++i) {
#ifdef VOID_LIFT_GAMEMODULE
        if (!strcmp(argv[i], "--self-test")) { gm_self_test = 1; continue; }
#endif
#ifdef VOID_LIFT_ENGINE
        if (!strcmp(argv[i], "--engine-image") && i + 1 < argc) { engine_image = argv[++i]; continue; }
#ifdef VOID_LIFT_FILESYSTEMS
        if (!strcmp(argv[i], "--fs-image") && i + 1 < argc) { fs_image = argv[++i]; continue; }
        if (!strcmp(argv[i], "--vfs-image") && i + 1 < argc) { vfs_image = argv[++i]; continue; }
#ifdef VOID_LIFT_SOUND
        if (!strcmp(argv[i], "--sound-image") && i + 1 < argc) { sound_image = argv[++i]; continue; }
#ifdef VOID_LIFT_MEDIA
        if (!strcmp(argv[i], "--video-image") && i + 1 < argc) { video_image = argv[++i]; continue; }
#ifdef VOID_LIFT_RENDERER
        if (!strcmp(argv[i], "--renderer-image") && i + 1 < argc) { renderer_image = argv[++i]; continue; }
#ifdef VOID_LIFT_NXCHARACTER
        if (!strcmp(argv[i], "--nxcharacter-image") && i + 1 < argc) { nxcharacter_image = argv[++i]; continue; }
#endif
#endif
#endif
#endif
#endif
#endif
        int consumed = recomp_trace_arg(argc, argv, i);
        if (!consumed) { fprintf(stderr, "Unknown option: %s\n", argv[i]); return 64; }
        i += consumed - 1;
    }
#ifdef VOID_LIFT_ENGINE
    if (!engine_image) { fprintf(stderr, "Engine stage requires --engine-image <private prebased Engine.dll>\n"); return 64; }
#ifdef VOID_LIFT_FILESYSTEMS
    if (!fs_image || !vfs_image) { fprintf(stderr, "Filesystem stage requires --fs-image and --vfs-image\n"); return 64; }
#ifdef VOID_LIFT_SOUND
    if (!sound_image) { fprintf(stderr, "Sound stage requires --sound-image\n"); return 64; }
#ifdef VOID_LIFT_MEDIA
    if (!video_image) { fprintf(stderr, "Media stage requires --video-image\n"); return 64; }
#ifdef VOID_LIFT_RENDERER
    if (!renderer_image) { fprintf(stderr, "Renderer stage requires --renderer-image\n"); return 64; }
#ifdef VOID_LIFT_NXCHARACTER
    if (!nxcharacter_image) { fprintf(stderr, "Character stage requires --nxcharacter-image\n"); return 64; }
#endif
#endif
#endif
#endif
#endif
#endif
    native32_hold_image(argv[1], GAME_BASE);
    native32_init();
    if (g_mem_base != 0) { fprintf(stderr, "[void] Flat memory requires fixed guest addresses\n"); return 67; }
#ifdef VOID_LIFT_GAMEMODULE
    InitializeCriticalSection(&gm_loader_lock);
#endif
    AddVectoredExceptionHandler(0, diagnostic_fault);
    char trace_option[8];
    if (GetEnvironmentVariableA("VOID_TRACE_NATIVE", trace_option, sizeof(trace_option)) && !strcmp(trace_option, "1")) native32_trace_native = 1;
    uint32_t game_span = native32_map(argv[1], GAME_BASE);
    DWORD game_protection;
    if (!game_span || !VirtualProtect((void *)(uintptr_t)GAME_BASE, game_span, PAGE_READWRITE, &game_protection)) return 67;
    fprintf(stderr, "[void] Game image at %08X span=%08X; entire image NX\n", GAME_BASE, game_span);
#ifdef VOID_LIFT_GAMEMODULE
    if (!void_map_module(GM->path, GAMEMODULE_BASE, GAMEMODULE_ENTRY)) return 67;
    GM->state = GM_MAPPED;
#ifdef VOID_LIFT_ENGINE
    if (!void_map_module(engine_image, ENGINE_BASE, ENGINE_ENTRY)) return 67;
    manual_modules[1].state = GM_MAPPED;
#ifdef VOID_LIFT_FILESYSTEMS
    if (!void_map_module(fs_image, FS_BASE, FS_ENTRY) || !void_map_module(vfs_image, VFS_BASE, VFS_ENTRY)) return 67;
    manual_modules[2].state = manual_modules[3].state = GM_MAPPED;
#ifdef VOID_LIFT_SOUND
    if (!void_map_module(sound_image, SOUND_BASE, SOUND_ENTRY)) return 67;
    manual_modules[4].state = GM_MAPPED;
#ifdef VOID_LIFT_MEDIA
    if (!void_map_module(video_image, VIDEO_BASE, VIDEO_ENTRY)) return 67;
    manual_modules[5].state = GM_MAPPED;
#ifdef VOID_LIFT_RENDERER
    if (!void_map_module(renderer_image, RENDERER_BASE, RENDERER_ENTRY)) return 67;
    manual_modules[6].state = GM_MAPPED;
#ifdef VOID_LIFT_NXCHARACTER
    if (!void_map_module(nxcharacter_image, NXCHARACTER_BASE, NXCHARACTER_ENTRY)) return 67;
    manual_modules[7].state = GM_MAPPED;
#endif
#endif
#endif
#endif
#endif
#endif
#endif
    int unresolved = native32_bind(GAME_BASE, host_shims, sizeof(host_shims) / sizeof(host_shims[0]));
#ifdef VOID_LIFT_GAMEMODULE
    unresolved += native32_bind(GAMEMODULE_BASE, host_shims, sizeof(host_shims) / sizeof(host_shims[0]));
#ifdef VOID_LIFT_ENGINE
    unresolved += native32_bind(ENGINE_BASE, host_shims, sizeof(host_shims) / sizeof(host_shims[0]));
#ifdef VOID_LIFT_FILESYSTEMS
    unresolved += native32_bind(FS_BASE, host_shims, sizeof(host_shims) / sizeof(host_shims[0]));
    unresolved += native32_bind(VFS_BASE, host_shims, sizeof(host_shims) / sizeof(host_shims[0]));
#ifdef VOID_LIFT_SOUND
    unresolved += native32_bind(SOUND_BASE, host_shims, sizeof(host_shims) / sizeof(host_shims[0]));
#ifdef VOID_LIFT_MEDIA
    unresolved += native32_bind(VIDEO_BASE, host_shims, sizeof(host_shims) / sizeof(host_shims[0]));
#ifdef VOID_LIFT_RENDERER
    unresolved += native32_bind(RENDERER_BASE, host_shims, sizeof(host_shims) / sizeof(host_shims[0]));
#ifdef VOID_LIFT_NXCHARACTER
    unresolved += native32_bind(NXCHARACTER_BASE, host_shims, sizeof(host_shims) / sizeof(host_shims[0]));
#endif
#endif
#endif
#endif
#endif
    /* Engine's static and dynamically resolved module handles preserve DirectInput's host identity. */
    patch_dll_identity((HMODULE)(uintptr_t)ENGINE_BASE);
#endif
#endif
    if (unresolved) { fprintf(stderr, "[void] %d unresolved imports\n", unresolved); return 68; }
#ifdef VOID_LIFT_FILESYSTEMS
    const uint32_t file_spans[] = {FS_SIZE, VFS_SIZE
#ifdef VOID_LIFT_SOUND
        , SOUND_SIZE
#ifdef VOID_LIFT_MEDIA
        , VIDEO_SIZE
#ifdef VOID_LIFT_RENDERER
        , RENDERER_SIZE
#ifdef VOID_LIFT_NXCHARACTER
        , NXCHARACTER_SIZE
#endif
#endif
#endif
#endif
    };
    const uint32_t file_counters[] = {FS_BASE + 0x35078, VFS_BASE + 0x2CD20
#ifdef VOID_LIFT_SOUND
        , SOUND_CRT_COUNT
#ifdef VOID_LIFT_MEDIA
        , VIDEO_CRT_COUNT
#ifdef VOID_LIFT_RENDERER
        , RENDERER_CRT_COUNT
#ifdef VOID_LIFT_NXCHARACTER
        , NXCHARACTER_CRT_COUNT
#endif
#endif
#endif
#endif
    };
    for (size_t i = 2; i < MANUAL_COUNT; ++i) {
        manual_module *module = &manual_modules[i];
        module->span = file_spans[i - 2];
        module->crt_counter = file_counters[i - 2];
        module->pristine = (BYTE *)HeapAlloc(GetProcessHeap(), 0, module->span);
        if (!module->pristine) return 69;
        memcpy(module->pristine, (void *)(uintptr_t)module->base, module->span);
    }
#endif
    HANDLE thread = CreateThread(NULL, 8 << 20, run_game, NULL, STACK_SIZE_PARAM_IS_A_RESERVATION, NULL);
    if (!thread) return 69;
    WaitForSingleObject(thread, INFINITE);
    DWORD code;
    GetExitCodeThread(thread, &code); CloseHandle(thread);
    return (int)code;
}
