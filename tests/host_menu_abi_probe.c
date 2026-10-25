/* Extracted host helpers plus the real native32 import bridge. No game/DLL/UI. */
#pragma warning(push)
/* Existing included runtime diagnostics; the probe remains /W4 /WX. */
#pragma warning(disable: 4005 4701 4731)
#include "../native/void_runtime.c"
#pragma warning(pop)
#include <wchar.h>

static unsigned checks, calls, file_calls, snapshots, manual_getters, manual_executes;
static unsigned native_getters, native_executes, execution_index, snapshot_count = 15;
static int backend_result, bridge_mode, bad_stack, long_key, expect_trap;
static const wchar_t *observed_command;
static uint32_t original_stack, arguments[7], context_object[80], console_object[2];
static uint32_t game_object[2], game_vtable[8], console_vtable[16];
static int native_menu_enabled;
static uint32_t d3d_create_device_target;
static jmp_buf trap_resume;
static const char *observed_trap;
static uint32_t observed_trap_address;
static const DWORD result_error = ERROR_SHARING_VIOLATION;
static const uint32_t result_value = 0x76543210;
static const wchar_t *snapshot_keys[] = {
    L"PortWidth", L"PortHeight", L"PortRefreshRate", L"PortVSync", L"PortHDR",
    L"PortAntialiasing", L"PortAnisotropy", L"PortTextureQuality", L"PortLightmapQuality",
    L"PortSoundRate", L"PortAdapterCount", L"PortAdapterIndex", L"PortModeCount",
    L"PortModeIndex", L"PortAutodetectAvailable"
};
static const int snapshot_values[] = {800, 600, 0, 1, 2, 4, 16, 1, 2, 44100, 3, 0, 12, 2, 1};
static wchar_t oversized_key[160];

static void require(int truth, const char *why)
{
    if (!truth) { fprintf(stderr, "FAIL: %s\n", why); ExitProcess(1); }
    ++checks;
}
static int void_settings_debug_command(const wchar_t *command)
{
    observed_command = command; return backend_result;
}
static const char *void_settings_debug_error(void) { return "expected rejection"; }
static unsigned void_settings_debug_snapshot(const wchar_t **keys, int *values, unsigned capacity)
{
    require(capacity == 16, "bounded snapshot capacity"); ++snapshots;
    for (unsigned i = 0; i < snapshot_count && i < 15; ++i) {
        keys[i] = long_key ? oversized_key : snapshot_keys[i]; values[i] = snapshot_values[i];
    }
    return snapshot_count;
}
static void original_console(void)
{
    require(g_esp == original_stack, "fallback entry stack"); ++calls;
}
static void lifted_getter(void);
static void lifted_execute(void);
const recomp_dispatch_entry_t recomp_dispatch_table[] = {
    {0x1017E0F0u, original_console}, {0x21001000u, lifted_getter}, {0x21002000u, lifted_execute}
};
const uint32_t recomp_dispatch_count = 3;

void void_lift_trap(uint32_t address, const char *why)
{
    if (!expect_trap) { fprintf(stderr, "Unexpected trap %08X %s\n", address, why); ExitProcess(2); }
    observed_trap = why; observed_trap_address = address; longjmp(trap_resume, 1);
}

static void clobber_published(void)
{
    g_eax = 0x01020304; g_ecx = 0x11121314; g_edx = 0x21222324;
    g_ebx = 0x31323334; g_ebp = 0x41424344; g_esi = 0x51525354; g_edi = 0x61626364;
    g_flag_k = FK_TEST; g_flag_a = 77; g_flag_b = 88; g_flag_cf = 0;
    g_cur_func = 0x11009876;
}
static void check_command(uint32_t this_value, const wchar_t *command)
{
    wchar_t expected[128];
    require(this_value == (uint32_t)(uintptr_t)console_object, "console this pointer");
    require(execution_index < snapshot_count && execution_index < 15, "snapshot execution bound");
    _snwprintf_s(expected, 128, _TRUNCATE, L"setting %ls %d",
        snapshot_keys[execution_index], snapshot_values[execution_index]);
    require(!wcscmp(command, expected), "exact UTF16 setting KEY VALUE command");
    ++execution_index;
}
static void lifted_getter(void)
{
    require(g_ecx == (uint32_t)(uintptr_t)game_object, "lifted context getter this");
    require(MEM32(g_esp) == RECOMP_RETADDR, "lifted getter return address");
    ++manual_getters; clobber_published();
    g_eax = (uint32_t)(uintptr_t)context_object; g_esp += 4;
}
static void lifted_execute(void)
{
    require(MEM32(g_esp) == RECOMP_RETADDR, "lifted execute return address");
    check_command(g_ecx, (const wchar_t *)(uintptr_t)MEM32(g_esp + 4));
    ++manual_executes; clobber_published(); g_esp += bad_stack ? 4 : 8;
}
static uint32_t __stdcall native_getter(void)
{
    uint32_t this_value;
    __asm mov this_value, ecx
    require(this_value == (uint32_t)(uintptr_t)game_object, "native context getter this");
    ++native_getters; return (uint32_t)(uintptr_t)context_object;
}
static void __stdcall native_execute(const wchar_t *command)
{
    uint32_t this_value;
    __asm mov this_value, ecx
    check_command(this_value, command); ++native_executes;
}
static void direct3d_create_device(void)
{
    require(0, "Direct3D must not run in this headless probe");
}

static HANDLE WINAPI void_asset_create_file_w(LPCWSTR path, DWORD access, DWORD share,
    LPSECURITY_ATTRIBUTES security, DWORD disposition, DWORD flags, HANDLE template_file)
{
    require((uint32_t)(uintptr_t)path == arguments[0], "file path");
    require(access == arguments[1] && share == arguments[2], "file access/share");
    require((uint32_t)(uintptr_t)security == arguments[3], "file security");
    require(disposition == arguments[4] && flags == arguments[5], "file disposition/flags");
    require((uint32_t)(uintptr_t)template_file == arguments[6], "file template");
    ++file_calls; SetLastError(result_error); return (HANDLE)(uintptr_t)result_value;
}
static HANDLE WINAPI void_asset_create_file_a(LPCSTR path, DWORD access, DWORD share,
    LPSECURITY_ATTRIBUTES security, DWORD disposition, DWORD flags, HANDLE template_file)
{
    return void_asset_create_file_w((LPCWSTR)path, access, share, security, disposition, flags, template_file);
}
static DWORD WINAPI void_asset_get_file_attributes_w(LPCWSTR path)
{
    require((uint32_t)(uintptr_t)path == arguments[0], "attribute path");
    ++file_calls; SetLastError(result_error); return result_value;
}
static DWORD WINAPI void_asset_get_file_attributes_a(LPCSTR path)
{
    return void_asset_get_file_attributes_w((LPCWSTR)path);
}
static int void_native_config_ready(void) { return native_menu_enabled; }
static BOOL void_window_show(HWND window, int command, int enabled)
{
    require((uint32_t)(uintptr_t)window == arguments[0] && (uint32_t)command == arguments[1], "ShowWindow arguments");
    require(enabled == native_menu_enabled, "ShowWindow policy readiness");
    SetLastError(result_error); return TRUE;
}
static BOOL void_window_position(HWND window, HWND after, int x, int y, int width, int height, UINT flags, int enabled)
{
    require((uint32_t)(uintptr_t)window == arguments[0] && (uint32_t)(uintptr_t)after == arguments[1], "SetWindowPos handles");
    require((uint32_t)x == arguments[2] && (uint32_t)y == arguments[3] && (uint32_t)width == arguments[4] &&
        (uint32_t)height == arguments[5] && flags == arguments[6], "SetWindowPos coordinates/flags");
    require(enabled == native_menu_enabled, "SetWindowPos policy readiness");
    SetLastError(result_error); return TRUE;
}
#include "host-menu.h"

static void setup(uint32_t stack)
{
    g_eax = 0xAABBCCDD; g_ecx = (uint32_t)(uintptr_t)game_object; g_edx = 0x22334455;
    g_ebx = 0x33445566; g_ebp = 0x44556677; g_esi = 0x55667788; g_edi = 0x66778899;
    g_flag_k = FK_CMP; g_flag_a = 21; g_flag_b = 22; g_flag_cf = 1;
    g_esp = stack; g_cur_func = 0x10123456;
    game_object[0] = (uint32_t)(uintptr_t)game_vtable;
    game_vtable[5] = bridge_mode ? (uint32_t)(uintptr_t)native_getter : 0x21001000u;
    context_object[0x124 / 4] = (uint32_t)(uintptr_t)console_object;
    console_object[0] = (uint32_t)(uintptr_t)console_vtable;
    console_vtable[0x34 / 4] = bridge_mode ? (uint32_t)(uintptr_t)native_execute : 0x21002000u;
    execution_index = 0;
}
static void preserved(void)
{
    require(g_ecx == (uint32_t)(uintptr_t)game_object && g_edx == 0x22334455, "caller registers preserved");
    require(g_ebx == 0x33445566 && g_ebp == 0x44556677 && g_esi == 0x55667788 && g_edi == 0x66778899,
        "callee saved registers preserved");
    require(g_flag_k == FK_CMP && g_flag_a == 21 && g_flag_b == 22 && g_flag_cf == 1, "published flags preserved");
    require(g_cur_func == 0x10123456, "caller identity preserved");
}
#define esp g_esp
#define eax g_eax
static void call_menu_indirect(uint32_t argument)
{
    uint32_t _flag_k = FK_CMP, _flag_a = 21, _flag_b = 22, _cf = 1;
    PUSH32(g_esp, argument);
    RECOMP_ICALL(0x1017E0F0u);
}
#undef eax
#undef esp

int main(void)
{
    struct { uint32_t header[2]; wchar_t text[64]; } string;
    uint32_t wrapper = (uint32_t)(uintptr_t)&string;
    require(sizeof(void *) == 4, "x86 ABI");
    native32_init(); mach_enter();
    /* Register synthetic dispatch ranges only. No PE/image or original DLL is loaded. */
    g_mods[0].base = 0x10000000u; g_mods[0].span = 0x331000;
    g_mods[1].base = 0x21000000u; g_mods[1].span = 0x10000; g_mod_n = 2;
    original_stack = g_esp - 256;
    MEM32(original_stack) = RECOMP_RETADDR; MEM32(original_stack + 4) = (uint32_t)(uintptr_t)&wrapper;
    wcscpy_s(string.text, 64, L"port_config VSync 1");
    for (bridge_mode = 0; bridge_mode <= 1; ++bridge_mode) {
        for (backend_result = -1; backend_result <= 1; ++backend_result) {
            unsigned before = snapshots;
            setup(original_stack); native_menu_command();
            require(observed_command == string.text, "object_ptr inline UTF16 ABI");
            if (!backend_result) {
                require(g_esp == original_stack && g_eax == 0xAABBCCDD, "unrelated exact fallback");
                require(snapshots == before && !execution_index, "unrelated command does not publish");
            } else {
                require(g_esp == original_stack + 8 && g_eax == 0, "handled void RET4");
                require(snapshots == before + 1 && execution_index == 15, "success and rejection both synchronize");
            }
            preserved(); require(MEM32(original_stack) == RECOMP_RETADDR, "outer return address untouched");
        }
        setup(original_stack); native_menu_publish_settings();
        require(g_eax == 0xAABBCCDD && g_esp == original_stack, "direct publish restores EAX/ESP");
        preserved(); require(execution_index == 15, "all fifteen numeric properties published");
    }
    require(calls == 2 && manual_getters == 3 && native_getters == 3 && manual_executes == 45 && native_executes == 45,
        "manual override and real import bridge both exercised");
    require(recomp_lookup_manual(0x1017E0F0u) == original_console, "disabled menu resolves original guest body");
    native_menu_enabled = 1;
    require(recomp_lookup_manual(0x1017E0F0u) == native_menu_command, "actual host override precedes guest lookup");
    bridge_mode = 0; backend_result = 1; setup(original_stack + 8);
    call_menu_indirect((uint32_t)(uintptr_t)&wrapper);
    require(g_esp == original_stack + 8 && g_eax == 0 && execution_index == 15,
        "real RECOMP_ICALL reaches hook and returns with RET4");
    preserved(); native_menu_enabled = 0;
    bridge_mode = 0; snapshot_count = 0; setup(original_stack); native_menu_publish_settings();
    require(!execution_index && g_eax == 0xAABBCCDD && g_esp == original_stack, "empty snapshot is a no-op"); preserved();
    for (unsigned which = 0; which < 4; ++which) {
        snapshot_count = which == 0 ? 17 : 1; long_key = which == 1; bad_stack = which == 2;
        for (unsigned i = 0; i < 159; ++i) oversized_key[i] = L'P'; oversized_key[159] = 0;
        setup(original_stack); if (which == 3) game_vtable[5] = g_shim_page;
        expect_trap = 1; observed_trap = NULL;
        if (!setjmp(trap_resume)) { native_menu_publish_settings(); require(0, "invalid publish must trap"); }
        require(observed_trap != NULL, "guard produced diagnostic");
        require(which == 3 ? observed_trap_address == g_shim_page : observed_trap_address == (which == 2 ? 0x21002000u : 0x1017E0F0u),
            "guard reports exact target");
        const char *expected[] = {"Invalid settings snapshot count", "Settings property command too long",
            "Settings console call stack imbalance", "Cannot dispatch native settings console call"};
        require(!strcmp(observed_trap, expected[which]), "precise guard diagnostic");
        expect_trap = 0;
    }
    snapshot_count = 15; long_key = bad_stack = 0; setup(original_stack);
    for (unsigned i = 0; i < 7; ++i) MEM32(original_stack + 4 + i * 4) = arguments[i] = 0x10000000 + i * 0x100;
    recomp_func_t shims[] = {asset_create_file_a, asset_create_file_w, asset_attributes_a, asset_attributes_w};
    for (unsigned i = 0; i < 4; ++i) {
        g_eax = 0; g_esp = original_stack; SetLastError(0); shims[i]();
        require(GetLastError() == result_error, "file shim LastError");
        require(g_eax == result_value && g_esp == original_stack + (i < 2 ? 32 : 8), "file shim EAX/stdcall stack");
        preserved(); require(MEM32(original_stack) == RECOMP_RETADDR, "file return address untouched");
    }
    require(file_calls == 4, "all file shim calls");
    recomp_func_t window_shims[] = {show_window, window_position};
    for (native_menu_enabled = 0; native_menu_enabled <= 1; ++native_menu_enabled) {
        for (unsigned i = 0; i < 2; ++i) {
            g_esp = original_stack; g_eax = 0; SetLastError(0); window_shims[i]();
            require(GetLastError() == result_error, "window shim LastError");
            require(g_eax == TRUE && g_esp == original_stack + (i ? 32 : 12), "window shim BOOL/stdcall stack");
            preserved(); require(MEM32(original_stack) == RECOMP_RETADDR, "window return address untouched");
        }
    }
    mach_leave();
    printf("Native menu snapshot/asset ABI PASS: %u checks; manual dispatch + actual native import bridge, 15 UTF16 properties, restored GPR/flags/ESP/caller, four strict guards\n", checks);
    return 0;
}
