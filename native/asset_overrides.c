/* A first FS provider for one UI script; original archive providers remain. */
#define WIN32_LEAN_AND_MEAN
#include "asset_overrides.h"
#include <bcrypt.h>
#include <shlobj.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <wchar.h>
#pragma comment(lib, "bcrypt.lib")
#pragma comment(lib, "shell32.lib")

#define MAX_ASSET_BYTES (4u * 1024u * 1024u)
static const char pinned_xml_sha[] = "2bc9d3741877f7cc836e6ebef29ed3dd50028e29cc160d0e970601cd9ff0c7f1";
static const char pinned_settings_sha[] = "4ff83f7ef62304faa7fe6123290f19d2ada59940f9dca1cbfe8464393fd19dc6";
static const char pinned_config_sha[] = "122f1ec97fe00754f5d67ebb941b9776a2d8bc8f3b6a9f884fd8b32ac4b4b17a";
static wchar_t original_xml[MAX_PATH], private_xml[MAX_PATH], script_payload[MAX_PATH], script_directory[MAX_PATH];
static wchar_t original_settings[MAX_PATH], private_settings[MAX_PATH];
static wchar_t original_config[MAX_PATH], private_config[MAX_PATH];
static char script_hash[65];
static volatile LONG enabled, redirected_opens, redirected_attributes, script_opens;

static BOOL full_path(LPCWSTR source, wchar_t output[MAX_PATH])
{
    if (!source || !source[0]) return FALSE;
    DWORD length = GetFullPathNameW(source, MAX_PATH, output, NULL);
    if (!length || length >= MAX_PATH) return FALSE;
    while (length > 3 && (output[length - 1] == L'\\' || output[length - 1] == L'/'))
        output[--length] = 0;
    for (DWORD i = 0; i < length; ++i) if (output[i] == L'/') output[i] = L'\\';
    return TRUE;
}
static BOOL append_path(LPCWSTR root, LPCWSTR suffix, wchar_t output[MAX_PATH])
{
    if (wcslen(root) + wcslen(suffix) + 1 >= MAX_PATH) return FALSE;
    swprintf(output, MAX_PATH, L"%ls\\%ls", root, suffix);
    return TRUE;
}
static BOOL contained_path(LPCWSTR child, LPCWSTR parent)
{
    size_t count = wcslen(parent);
    return !_wcsnicmp(child, parent, count) && (child[count] == 0 || child[count] == L'\\');
}
static BOOL hash_bytes(const unsigned char *bytes, DWORD size, unsigned char digest[32])
{
    BCRYPT_ALG_HANDLE algorithm = NULL;
    NTSTATUS status = BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, NULL, 0);
    if (status >= 0) status = BCryptHash(algorithm, NULL, 0, (PUCHAR)bytes, size, digest, 32);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    return status >= 0;
}
static BOOL parse_hash(LPCSTR text, unsigned char digest[32])
{
    if (!text || strlen(text) != 64) return FALSE;
    for (unsigned i = 0; i < 32; ++i) {
        unsigned byte = 0;
        for (unsigned j = 0; j < 2; ++j) {
            char c = text[i * 2 + j];
            unsigned n = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 :
                c >= 'A' && c <= 'F' ? c - 'A' + 10 : 256;
            if (n > 15) return FALSE;
            byte = byte * 16 + n;
        }
        digest[i] = (unsigned char)byte;
    }
    return TRUE;
}
static unsigned char *read_file(LPCWSTR path, DWORD *size)
{
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
                              FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return NULL;
    LARGE_INTEGER length;
    unsigned char *bytes = NULL;
    if (GetFileSizeEx(file, &length) && length.QuadPart > 0 && length.QuadPart <= MAX_ASSET_BYTES) {
        *size = (DWORD)length.QuadPart;
        bytes = HeapAlloc(GetProcessHeap(), 0, *size + 1);
        DWORD got = 0;
        if (bytes && (!ReadFile(file, bytes, *size, &got, NULL) || got != *size)) {
            HeapFree(GetProcessHeap(), 0, bytes); bytes = NULL;
        }
        if (bytes) bytes[*size] = 0;
    }
    DWORD error = GetLastError(); CloseHandle(file); SetLastError(error);
    return bytes;
}
static BOOL only_child(LPCWSTR directory, LPCWSTR expected, BOOL is_directory)
{
    wchar_t search[MAX_PATH];
    if (!append_path(directory, L"*", search)) return FALSE;
    WIN32_FIND_DATAW data;
    HANDLE find = FindFirstFileW(search, &data);
    if (find == INVALID_HANDLE_VALUE) return FALSE;
    BOOL found = FALSE, valid = TRUE;
    do {
        if (!wcscmp(data.cFileName, L".") || !wcscmp(data.cFileName, L"..")) continue;
        if (_wcsicmp(data.cFileName, expected) || !!(data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != !!is_directory ||
                (data.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT)) { valid = FALSE; break; }
        found = TRUE;
    } while (FindNextFileW(find, &data));
    FindClose(find);
    return found && valid;
}
static BOOL write_atomic(LPCWSTR path, const void *bytes, DWORD size)
{
    wchar_t temporary[MAX_PATH];
    if (wcslen(path) + 5 >= MAX_PATH) return FALSE;
    swprintf(temporary, MAX_PATH, L"%ls.tmp", path);
    HANDLE file = CreateFileW(temporary, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,
                              FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return FALSE;
    DWORD written = 0;
    BOOL valid = WriteFile(file, bytes, size, &written, NULL) && written == size && FlushFileBuffers(file);
    DWORD error = GetLastError(); CloseHandle(file);
    if (valid) valid = MoveFileExW(temporary, path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
    if (!valid) { DeleteFileW(temporary); SetLastError(error); }
    return valid;
}
static char *xml_path(LPCWSTR path)
{
    char utf8[MAX_PATH * 4];
    int count = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, path, -1, utf8, sizeof utf8, NULL, NULL);
    if (!count) return NULL;
    char *escaped = HeapAlloc(GetProcessHeap(), 0, (size_t)count * 6 + 1);
    if (!escaped) return NULL;
    char *next = escaped;
    for (int i = 0; i < count - 1; ++i) {
        const char *entity = utf8[i] == '&' ? "&amp;" : utf8[i] == '<' ? "&lt;" :
            utf8[i] == '>' ? "&gt;" : utf8[i] == '"' ? "&quot;" : utf8[i] == '\'' ? "&apos;" : NULL;
        if (entity) { size_t n = strlen(entity); memcpy(next, entity, n); next += n; }
        else *next++ = utf8[i] == '\\' ? '/' : utf8[i];
    }
    *next = 0; return escaped;
}
static unsigned char *windowed_config(DWORD *size)
{
    unsigned char *bytes = read_file(original_config, size);
    unsigned char expected[32], actual[32];
    const char *token = "<Fullscreen />";
    size_t count = strlen(token);
    BOOL valid = bytes && parse_hash(pinned_config_sha, expected) &&
        hash_bytes(bytes, *size, actual) && !memcmp(actual, expected, 32);
    unsigned char *found = valid ? (unsigned char *)strstr((char *)bytes, token) : NULL;
    if (!found || strstr((char *)found + count, token)) {
        if (bytes) HeapFree(GetProcessHeap(), 0, bytes);
        SetLastError(ERROR_INVALID_DATA); return NULL;
    }
    size_t position = (size_t)(found - bytes);
    memmove(found, found + count, *size - position - count);
    *size -= (DWORD)count; bytes[*size] = 0;
    return bytes;
}
BOOL void_asset_overrides_init(LPCWSTR data_directory, LPCWSTR assets_root, LPCSTR expected_payload_hash,
                              LPCWSTR profile_common)
{
    InterlockedExchange(&enabled, 0);
    wchar_t data[MAX_PATH], root[MAX_PATH], scripts[MAX_PATH], ui[MAX_PATH], payload[MAX_PATH];
    wchar_t profile[MAX_PATH], profile_absolute[MAX_PATH], common[MAX_PATH], expected_common[MAX_PATH], settings_directory[MAX_PATH];
    unsigned char expected[32], actual[32], xml_hash[32], settings_hash[32];
    DWORD profile_length = GetEnvironmentVariableW(L"VOID_PROFILE_ROOT", profile, MAX_PATH);
    if (!profile_length || profile_length >= MAX_PATH ||
        !full_path(profile, profile_absolute) || !full_path(profile_common, common) ||
        !append_path(profile_absolute, L"CommonAppData", expected_common) || _wcsicmp(common, expected_common) ||
        !full_path(data_directory, data) || !full_path(assets_root, root) || contained_path(root, data) ||
        contained_path(common, data) ||
        !append_path(data, L"fsystems.xml", original_xml) || !append_path(root, L"fsystems.xml", private_xml) ||
        !append_path(data, L"config.xml", original_config) || !append_path(root, L"config.xml", private_config) ||
        !append_path(data, L"settings.xml", original_settings) ||
        !append_path(common, L"Ice-pick Lodge\\Void", settings_directory) ||
        !append_path(settings_directory, L"settings.xml", private_settings) || !_wcsicmp(original_settings, private_settings) ||
        !append_path(root, L"Scripts", scripts) || !append_path(scripts, L"ui", ui) ||
        !append_path(ui, L"main_menu.bin", payload) || !parse_hash(expected_payload_hash, expected)) {
        SetLastError(ERROR_INVALID_PARAMETER); return FALSE;
    }
    DWORD settings_attributes = GetFileAttributesW(private_settings);
    if (settings_attributes == INVALID_FILE_ATTRIBUTES ||
        (settings_attributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT))) {
        SetLastError(ERROR_INVALID_DATA); return FALSE;
    }
    DWORD settings_size = 0;
    unsigned char *settings_source = read_file(original_settings, &settings_size);
    BOOL settings_valid = settings_source && parse_hash(pinned_settings_sha, settings_hash) &&
        hash_bytes(settings_source, settings_size, actual) && !memcmp(actual, settings_hash, 32);
    if (settings_source) HeapFree(GetProcessHeap(), 0, settings_source);
    if (!settings_valid) { SetLastError(ERROR_INVALID_DATA); return FALSE; }
    if (!only_child(scripts, L"ui", TRUE) || !only_child(ui, L"main_menu.bin", FALSE)) {
        SetLastError(ERROR_INVALID_DATA); return FALSE;
    }
    DWORD payload_size = 0;
    unsigned char *payload_bytes = read_file(payload, &payload_size);
    if (!payload_bytes) return FALSE;
    BOOL valid = hash_bytes(payload_bytes, payload_size, actual) && !memcmp(actual, expected, 32);
    HeapFree(GetProcessHeap(), 0, payload_bytes);
    if (!valid) { SetLastError(ERROR_INVALID_DATA); return FALSE; }
    wcscpy(script_payload, payload); wcscpy(script_directory, scripts); strcpy(script_hash, expected_payload_hash);
    InterlockedExchange(&script_opens, 0);
    DWORD original_size = 0;
    unsigned char *source = read_file(original_xml, &original_size);
    if (!source) return FALSE;
    valid = parse_hash(pinned_xml_sha, expected) && hash_bytes(source, original_size, xml_hash) && !memcmp(expected, xml_hash, 32);
    const char *needle = "<system name=\"script\">";
    char *insert = valid ? strstr((char *)source, needle) : NULL;
    char *escaped = xml_path(scripts);
    if (!insert || strstr(insert + strlen(needle), needle) || !escaped) valid = FALSE;
    DWORD windowed_size = 0;
    unsigned char *windowed = valid ? windowed_config(&windowed_size) : NULL;
    if (!windowed) valid = FALSE;
    if (valid) {
        const char *head = "<system name=\"script\"><Path>";
        const char *tail = "</Path></system>\r\n  ";
        size_t prefix = (size_t)(insert - (char *)source);
        size_t added = strlen(head) + strlen(escaped) + strlen(tail);
        size_t total = original_size + added;
        char *output = HeapAlloc(GetProcessHeap(), 0, total);
        valid = output != NULL;
        if (output) {
            memcpy(output, source, prefix);
            memcpy(output + prefix, head, strlen(head));
            memcpy(output + prefix + strlen(head), escaped, strlen(escaped));
            memcpy(output + prefix + strlen(head) + strlen(escaped), tail, strlen(tail));
            memcpy(output + prefix + added, source + prefix, original_size - prefix);
            valid = write_atomic(private_config, windowed, windowed_size) &&
                write_atomic(private_xml, output, (DWORD)total);
            HeapFree(GetProcessHeap(), 0, output);
        }
    }
    if (escaped) HeapFree(GetProcessHeap(), 0, escaped);
    if (windowed) HeapFree(GetProcessHeap(), 0, windowed);
    HeapFree(GetProcessHeap(), 0, source);
    if (!valid) { SetLastError(ERROR_INVALID_DATA); return FALSE; }
    InterlockedExchange(&redirected_opens, 0); InterlockedExchange(&redirected_attributes, 0);
    InterlockedExchange(&enabled, 1);
    fprintf(stderr, "[void-assets] First script provider ready; main_menu.bin SHA256=%s; original fsystems.xml SHA256=%s\n",
        expected_payload_hash, pinned_xml_sha);
    fprintf(stderr, "[void-assets] Settings read/write alias ready; source SHA256=%s; private profile storage selected\n",
        pinned_settings_sha);
    fprintf(stderr, "[void-assets] Windowed config ready; removed exactly one Fullscreen element; original SHA256=%s\n",
        pinned_config_sha);
    return TRUE;
}
static BOOL is_config(LPCWSTR path)
{
    wchar_t normalized[MAX_PATH];
    return enabled && full_path(path, normalized) && !_wcsicmp(normalized, original_xml);
}
static BOOL is_settings(LPCWSTR path)
{
    wchar_t normalized[MAX_PATH];
    return enabled && full_path(path, normalized) && !_wcsicmp(normalized, original_settings);
}
static BOOL is_window_config(LPCWSTR path)
{
    wchar_t normalized[MAX_PATH];
    return enabled && full_path(path, normalized) && !_wcsicmp(normalized, original_config);
}
static BOOL readonly_open(DWORD access, DWORD disposition, DWORD flags)
{
    DWORD writes = GENERIC_WRITE | GENERIC_ALL | FILE_WRITE_DATA | FILE_APPEND_DATA | FILE_WRITE_EA |
        FILE_WRITE_ATTRIBUTES | DELETE | WRITE_DAC | WRITE_OWNER;
    return !(access & writes) && disposition == OPEN_EXISTING && !(flags & FILE_FLAG_DELETE_ON_CLOSE);
}
static BOOL private_mount_path(LPCWSTR path)
{
    wchar_t normalized[MAX_PATH];
    return enabled && full_path(path, normalized) &&
        (contained_path(normalized, script_directory) || !_wcsicmp(normalized, private_xml) ||
         !_wcsicmp(normalized, private_config));
}
static void note_script_open(LPCWSTR path, HANDLE file, DWORD access, DWORD disposition, DWORD flags)
{
    wchar_t normalized[MAX_PATH];
    if (enabled && file != INVALID_HANDLE_VALUE && readonly_open(access, disposition, flags) &&
        full_path(path, normalized) && !_wcsicmp(normalized, script_payload)) {
        if (InterlockedIncrement(&script_opens) == 1)
            fprintf(stderr, "[void-assets] Private UI script opened; SHA256=%s\n", script_hash);
    }
}
LONG void_asset_overrides_script_open_count(void) { return InterlockedCompareExchange(&script_opens, 0, 0); }
HANDLE WINAPI void_asset_create_file_w(LPCWSTR path, DWORD access, DWORD share, LPSECURITY_ATTRIBUTES security,
                                      DWORD disposition, DWORD flags, HANDLE template_file)
{
    DWORD saved = GetLastError(); BOOL matched = is_config(path), settings = is_settings(path), windowed = is_window_config(path); SetLastError(saved);
    if (!readonly_open(access, disposition, flags) && (matched || windowed || private_mount_path(path))) {
        SetLastError(ERROR_ACCESS_DENIED); return INVALID_HANDLE_VALUE;
    }
    HANDLE file = CreateFileW(matched ? private_xml : windowed ? private_config : settings ? private_settings : path,
                              access, share, security, disposition, flags, template_file);
    DWORD error = GetLastError();
    if (matched && file != INVALID_HANDLE_VALUE) InterlockedIncrement(&redirected_opens);
    note_script_open(path, file, access, disposition, flags);
    SetLastError(error); return file;
}
HANDLE WINAPI void_asset_create_file_a(LPCSTR path, DWORD access, DWORD share, LPSECURITY_ATTRIBUTES security,
                                      DWORD disposition, DWORD flags, HANDLE template_file)
{
    wchar_t wide[MAX_PATH]; DWORD saved = GetLastError();
    BOOL converted = path && MultiByteToWideChar(CP_ACP, 0, path, -1, wide, MAX_PATH);
    BOOL matched = converted && (is_config(wide) || is_settings(wide) || is_window_config(wide));
    SetLastError(saved);
    if (matched) return void_asset_create_file_w(wide, access, share, security, disposition, flags, template_file);
    if (converted && !readonly_open(access, disposition, flags) && private_mount_path(wide)) {
        SetLastError(ERROR_ACCESS_DENIED); return INVALID_HANDLE_VALUE;
    }
    HANDLE file = CreateFileA(path, access, share, security, disposition, flags, template_file);
    DWORD error = GetLastError();
    if (path && MultiByteToWideChar(CP_ACP, 0, path, -1, wide, MAX_PATH))
        note_script_open(wide, file, access, disposition, flags);
    SetLastError(error); return file;
}
DWORD WINAPI void_asset_get_file_attributes_w(LPCWSTR path)
{
    DWORD saved = GetLastError(); BOOL matched = is_config(path), settings = is_settings(path), windowed = is_window_config(path); SetLastError(saved);
    DWORD attributes = GetFileAttributesW(matched ? private_xml : windowed ? private_config : settings ? private_settings : path);
    DWORD error = GetLastError(); if (matched) InterlockedIncrement(&redirected_attributes);
    SetLastError(error); return attributes;
}
DWORD WINAPI void_asset_get_file_attributes_a(LPCSTR path)
{
    wchar_t wide[MAX_PATH]; DWORD saved = GetLastError();
    BOOL matched = path && MultiByteToWideChar(CP_ACP, 0, path, -1, wide, MAX_PATH) &&
        (is_config(wide) || is_settings(wide) || is_window_config(wide));
    SetLastError(saved);
    if (matched) return void_asset_get_file_attributes_w(wide);
    return GetFileAttributesA(path);
}
