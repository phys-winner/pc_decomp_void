#define WIN32_LEAN_AND_MEAN
#define COBJMACROS
#define DIRECTSOUND_VERSION 0x0800
#include <windows.h>
#include <mmsystem.h>
#include <dsound.h>
#include <stdio.h>

typedef HRESULT (WINAPI *create8_fn)(LPCGUID, LPDIRECTSOUND8 *, LPUNKNOWN);
typedef HRESULT (WINAPI *enumerate_fn)(LPDSENUMCALLBACKW, LPVOID);
typedef UINT (WINAPI *wave_count_fn)(void);

typedef struct enumeration_t { unsigned callbacks, concrete_devices; } enumeration_t;

static void print_utf8(const WCHAR *value)
{
    char text[8192];
    if (!value) { fputs("null", stdout); return; }
    if (!WideCharToMultiByte(CP_UTF8, 0, value, -1, text, sizeof text, NULL, NULL)) {
        printf("conversion_error_%lu", GetLastError()); return;
    }
    for (char *at = text; *at; ++at) {
        if (*at == '\n' || *at == '\r') *at = ' ';
    }
    fputs(text, stdout);
}

static BOOL CALLBACK enumerate_device(LPGUID guid, LPCWSTR description,
    LPCWSTR module, LPVOID context)
{
    enumeration_t *count = (enumeration_t *)context;
    ++count->callbacks;
    if (guid) ++count->concrete_devices;
    printf("device index=%u default=%d guid=", count->callbacks - 1, guid == NULL);
    if (guid) printf("%08lx-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x",
        guid->Data1, guid->Data2, guid->Data3,
        guid->Data4[0], guid->Data4[1], guid->Data4[2], guid->Data4[3],
        guid->Data4[4], guid->Data4[5], guid->Data4[6], guid->Data4[7]);
    else fputs("null", stdout);
    fputs(" description=", stdout); print_utf8(description);
    fputs(" module=", stdout); print_utf8(module); putchar('\n');
    return TRUE;
}

static int print_module(const char *name, HMODULE module)
{
    WCHAR path[32768], final_path[32768];
    DWORD length = GetModuleFileNameW(module, path, 32768);
    if (!length || length >= 32768) return 0;
    printf("module name=%s path=", name); print_utf8(path);
    HANDLE file = CreateFileW(path, FILE_READ_ATTRIBUTES,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) { printf(" final_path_error=%lu\n", GetLastError()); return 0; }
    length = GetFinalPathNameByHandleW(file, final_path, 32768, FILE_NAME_NORMALIZED);
    DWORD error = GetLastError();
    CloseHandle(file);
    if (!length || length >= 32768) { printf(" final_path_error=%lu\n", error); return 0; }
    fputs(" final_path=", stdout); print_utf8(final_path); putchar('\n');
    return 1;
}

int main(void)
{
    HMODULE sound = LoadLibraryExW(L"dsound.dll", NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
    DWORD sound_error = sound ? 0 : GetLastError();
    HMODULE wave = LoadLibraryExW(L"winmm.dll", NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
    DWORD wave_error = wave ? 0 : GetLastError();
    printf("load dsound=%d error=%lu winmm=%d error_wave=%lu pointer_bits=%u\n",
        sound != NULL, sound_error, wave != NULL, wave_error, (unsigned)(sizeof(void *) * 8));
    int success = sound && wave;
    if (sound && !print_module("dsound", sound)) success = 0;
    if (wave && !print_module("winmm", wave)) success = 0;
    create8_fn create8 = sound ? (create8_fn)GetProcAddress(sound, "DirectSoundCreate8") : NULL;
    enumerate_fn enumerate = sound ? (enumerate_fn)GetProcAddress(sound, "DirectSoundEnumerateW") : NULL;
    wave_count_fn wave_count = wave ? (wave_count_fn)GetProcAddress(wave, "waveOutGetNumDevs") : NULL;
    printf("exports create8=%d enumerateW=%d waveOutGetNumDevs=%d\n",
        create8 != NULL, enumerate != NULL, wave_count != NULL);
    if (!create8 || !enumerate || !wave_count) success = 0;
    if (enumerate) {
        enumeration_t count = {0, 0};
        HRESULT result = enumerate(enumerate_device, &count);
        printf("enumerate hr=%08lx callbacks=%u concrete_devices=%u\n",
            (unsigned long)result, count.callbacks, count.concrete_devices);
    }
    if (wave_count) printf("wave count=%u\n", wave_count());
    if (create8) {
        LPDIRECTSOUND8 device = NULL;
        HRESULT result = create8(NULL, &device, NULL);
        printf("create8 default_guid_null=1 outer_null=1 hr=%08lx object=%d\n",
            (unsigned long)result, device != NULL);
        if (device) printf("release remaining=%lu\n", IDirectSound8_Release(device));
    }
    BOOL wave_closed = wave ? FreeLibrary(wave) : FALSE;
    BOOL sound_closed = sound ? FreeLibrary(sound) : FALSE;
    printf("cleanup winmm_closed=%d dsound_closed=%d\n", wave_closed, sound_closed);
    return success && wave_closed && sound_closed ? 0 : 2;
}
