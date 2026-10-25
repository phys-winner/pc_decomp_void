/* Actual host folder/seed functions, with guarded real Win32 file operations. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shlobj.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>

static wchar_t profile_root[MAX_PATH], profile_common[MAX_PATH];
static wchar_t allowed_root[MAX_PATH];
static unsigned checks, directory_calls, copy_calls;

static void require(int condition, const char *message)
{
    ++checks;
    if (!condition) { fprintf(stderr, "FAIL: %s\n", message); ExitProcess(90); }
}
static void require_owned_destination(const wchar_t *path)
{
    wchar_t resolved[MAX_PATH];
    DWORD n = GetFullPathNameW(path, MAX_PATH, resolved, NULL);
    size_t prefix = wcslen(allowed_root);
    require(n && n < MAX_PATH && !_wcsnicmp(resolved, allowed_root, prefix) &&
        resolved[prefix] == L'\\', "file operation escaped the dedicated test profile");
}
static int guarded_create_directory(HWND window, LPCWSTR path, const SECURITY_ATTRIBUTES *attributes)
{
    require_owned_destination(path);
    ++directory_calls;
    return SHCreateDirectoryExW(window, path, attributes);
}
static BOOL guarded_copy_file(LPCWSTR source, LPCWSTR destination, BOOL fail_if_exists)
{
    require_owned_destination(destination);
    require(fail_if_exists == TRUE, "seed would overwrite an existing destination");
    ++copy_calls;
    return CopyFileW(source, destination, fail_if_exists);
}

/* Only write destinations are checked; real folder and copy APIs still run. */
#define SHCreateDirectoryExW guarded_create_directory
#define CopyFileW guarded_copy_file
#include "host-profile.h"
#undef SHCreateDirectoryExW
#undef CopyFileW

static void folder_matches_actual(int folder)
{
    wchar_t actual[MAX_PATH] = L"probe", expected[MAX_PATH] = L"probe";
    HRESULT a = game_folder_path(NULL, folder, NULL, SHGFP_TYPE_CURRENT, actual);
    HRESULT b = SHGetFolderPathW(NULL, folder, NULL, SHGFP_TYPE_CURRENT, expected);
    require(a == b, "default folder HRESULT differs from real SHGetFolderPathW");
    require(!wcscmp(actual, expected), "default folder differs from real SHGetFolderPathW");
}
int wmain(int argc, wchar_t **argv)
{
    if (argc != 2 || sizeof(void *) != 4) return 91;
    DWORD length = GetFullPathNameW(argv[1], MAX_PATH, allowed_root, NULL);
    require(length && length < MAX_PATH, "test root does not fit MAX_PATH");
    require(GetFileAttributesW(allowed_root) != INVALID_FILE_ATTRIBUTES,
        "Python must create the dedicated test profile before running this probe");

    require(seed_profile_settings() == 1 && !directory_calls && !copy_calls,
        "empty profile should seed successfully without file operations");
    folder_matches_actual(CSIDL_PERSONAL);
    folder_matches_actual(CSIDL_COMMON_APPDATA);
    folder_matches_actual(CSIDL_DESKTOP);

    wcscpy(profile_root, allowed_root);
    require(seed_profile_settings() == 1, "real profile settings seeding failed");
    wchar_t expected_common[MAX_PATH];
    swprintf(expected_common, MAX_PATH, L"%ls\\CommonAppData", allowed_root);
    require(!wcscmp(profile_common, expected_common), "isolated CommonAppData path is incorrect");
    const int bits[] = {0, CSIDL_FLAG_DONT_VERIFY, CSIDL_FLAG_CREATE};
    for (unsigned i = 0; i < sizeof bits / sizeof bits[0]; ++i) {
        wchar_t path[MAX_PATH];
        require(game_folder_path(NULL, CSIDL_PERSONAL | bits[i], NULL, SHGFP_TYPE_CURRENT, path) == S_OK &&
            !wcscmp(path, allowed_root), "Personal folder override or CSIDL flags failed");
        require(game_folder_path(NULL, CSIDL_COMMON_APPDATA | bits[i], NULL, SHGFP_TYPE_CURRENT, path) == S_OK &&
            !wcscmp(path, expected_common), "CommonAppData override or CSIDL flags failed");
    }
    folder_matches_actual(CSIDL_DESKTOP);
    require(directory_calls == 1 && copy_calls == 3, "seed did not use one owned directory and three copies");

    unsigned before_directories = directory_calls, before_copies = copy_calls;
    wcscpy(profile_root, allowed_root); wcscat(profile_root, L"\\overlong-");
    size_t n = wcslen(profile_root);
    while (n < MAX_PATH - 1) profile_root[n++] = L'x';
    profile_root[n] = 0; profile_common[0] = 0;
    require(seed_profile_settings() == 0, "overlong profile should be rejected");
    require(directory_calls == before_directories && copy_calls == before_copies && !profile_common[0],
        "overlong profile performed a directory/copy operation or published its path");
    printf("PASS %u checks: actual profile seeding, Personal/CommonAppData CSIDL flags, "
        "Desktop/default real API, empty/overlong no-write guards; owned directory calls=%u copies=%u\n",
        checks, directory_calls, copy_calls);
    return 0;
}
