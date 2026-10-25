/* Native x86 DirectInput creation only; no acquisition, polling or UI. */
#define WIN32_LEAN_AND_MEAN
#define DIRECTINPUT_VERSION 0x0800
#define COBJMACROS
#include <windows.h>
#include <dinput.h>
#include <stdio.h>
#include <string.h>

static void module_path(const char *name)
{
    char path[MAX_PATH] = {0};
    HMODULE module = GetModuleHandleA(name);
    if (module) GetModuleFileNameA(module, path, MAX_PATH);
    printf("module_%s=%s\n", name, module ? path : "<not loaded>");
    if (module) {
        const IMAGE_DOS_HEADER *dos = (const IMAGE_DOS_HEADER *)module;
        const IMAGE_NT_HEADERS32 *nt = (const IMAGE_NT_HEADERS32 *)((const BYTE *)module + dos->e_lfanew);
        printf("machine_%s=%04X\n", name, nt->FileHeader.Machine);
        HANDLE file = CreateFileA(path, FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, OPEN_EXISTING, 0, NULL);
        char resolved[MAX_PATH] = {0};
        if (file != INVALID_HANDLE_VALUE) {
            DWORD length = GetFinalPathNameByHandleA(file, resolved, MAX_PATH, FILE_NAME_NORMALIZED);
            if (length && length < MAX_PATH) printf("resolved_%s=%s\n", name, resolved);
            CloseHandle(file);
        }
    }
}

static void result(const char *interface_name, const char *operation,
                   HRESULT hr, const void *pointer)
{
    printf("result=%s %s %08lX %08lX\n", interface_name, operation,
           (unsigned long)hr, (unsigned long)(uintptr_t)pointer);
}

static int probe_a(HINSTANCE instance, const GUID *mouse, const GUID *keyboard)
{
    IDirectInput8A *input = NULL;
    HRESULT hr = DirectInput8Create(instance, 0x0800, &IID_IDirectInput8A, (void **)&input, NULL);
    result("A", "DirectInput8Create", hr, input);
    if (FAILED(hr) || !input) return 0;
    IDirectInputDevice8A *device = NULL;
    hr = input->lpVtbl->CreateDevice(input, mouse, &device, NULL);
    result("A", "SysMouse", hr, device);
    int mouse_ok = SUCCEEDED(hr) && device != NULL;
    if (mouse_ok) device->lpVtbl->Release(device);
    device = NULL;
    hr = input->lpVtbl->CreateDevice(input, keyboard, &device, NULL);
    result("A", "SysKeyboard", hr, device);
    int keyboard_ok = SUCCEEDED(hr) && device != NULL;
    if (keyboard_ok) device->lpVtbl->Release(device);
    input->lpVtbl->Release(input);
    return mouse_ok && keyboard_ok;
}

static int probe_w(HINSTANCE instance, const GUID *mouse, const GUID *keyboard)
{
    IDirectInput8W *input = NULL;
    HRESULT hr = DirectInput8Create(instance, 0x0800, &IID_IDirectInput8W, (void **)&input, NULL);
    result("W", "DirectInput8Create", hr, input);
    if (FAILED(hr) || !input) return 0;
    IDirectInputDevice8W *device = NULL;
    hr = input->lpVtbl->CreateDevice(input, mouse, &device, NULL);
    result("W", "SysMouse", hr, device);
    int mouse_ok = SUCCEEDED(hr) && device != NULL;
    if (mouse_ok) device->lpVtbl->Release(device);
    device = NULL;
    hr = input->lpVtbl->CreateDevice(input, keyboard, &device, NULL);
    result("W", "SysKeyboard", hr, device);
    int keyboard_ok = SUCCEEDED(hr) && device != NULL;
    if (keyboard_ok) device->lpVtbl->Release(device);
    input->lpVtbl->Release(input);
    return mouse_ok && keyboard_ok;
}

int main(void)
{
    static const unsigned char engine_mouse[16] = {
        0x60,0x2B,0x1D,0x6F,0xA0,0xD5,0xCF,0x11,0xBF,0xC7,0x44,0x45,0x53,0x54,0,0};
    static const unsigned char engine_keyboard[16] = {
        0x61,0x2B,0x1D,0x6F,0xA0,0xD5,0xCF,0x11,0xBF,0xC7,0x44,0x45,0x53,0x54,0,0};
    GUID mouse, keyboard;
    memcpy(&mouse, engine_mouse, 16); memcpy(&keyboard, engine_keyboard, 16);
    int guids_match = !memcmp(&mouse, &GUID_SysMouse, 16) &&
                      !memcmp(&keyboard, &GUID_SysKeyboard, 16);
    HINSTANCE instance = GetModuleHandleW(NULL);
    printf("process=%lu\nthread=%lu\nbits=%u\nhinstance=%08lX\nengine_guids_match_sdk=%d\n",
        GetCurrentProcessId(), GetCurrentThreadId(), (unsigned)(sizeof(void *) * 8),
        (unsigned long)(uintptr_t)instance, guids_match);
    if (!instance || !guids_match || sizeof(void *) != 4) return 2;
    int a_ok = probe_a(instance, &mouse, &keyboard);
    int w_ok = probe_w(instance, &mouse, &keyboard);
    module_path("dinput8.dll"); module_path("dinput.dll");
    printf("creation_only_ok=%d\n", a_ok && w_ok);
    return a_ok && w_ok ? 0 : 1;
}
