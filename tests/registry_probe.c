#define WIN32_LEAN_AND_MEAN
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdio.h>
#include <assert.h>

static void token_flags(const char *name, HANDLE token)
{
    const TOKEN_INFORMATION_CLASS classes[] = { TokenElevation, TokenVirtualizationAllowed, TokenVirtualizationEnabled };
    const char *labels[] = { "elevated", "virtualization_allowed", "virtualization_enabled" };
    DWORD value, returned;
    for (unsigned i = 0; i < 3; ++i) {
        value = 0;
        if (GetTokenInformation(token, classes[i], &value, sizeof(value), &returned))
            printf("%s %s=%lu\n", name, labels[i], (unsigned long)value);
        else printf("%s %s error=%lu\n", name, labels[i], (unsigned long)GetLastError());
    }
}

static LSTATUS query(HKEY root, const wchar_t *path, REGSAM access, DWORD *type, DWORD *value, DWORD *bytes)
{
    HKEY key = NULL;
    LSTATUS opened = RegOpenKeyExW(root, path, 0, access, &key);
    printf("access=0x%08lx open=%ld ", (unsigned long)access, (long)opened);
    if (opened != ERROR_SUCCESS) { puts("query=not_called"); return opened; }
    typedef LONG (NTAPI *query_key_fn)(HANDLE, int, void *, ULONG, ULONG *);
    query_key_fn query_key = (query_key_fn)GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "NtQueryKey");
    if (query_key) {
        DWORD flags = 0; ULONG returned = 0;
        LONG status = query_key(key, 6, &flags, sizeof(flags), &returned);
        printf("key_virtualization_status=0x%08lx flags=0x%08lx candidate=%lu enabled=%lu target=%lu store=%lu source=%lu ",
            (unsigned long)status, (unsigned long)flags, (unsigned long)(flags & 1), (unsigned long)((flags >> 1) & 1),
            (unsigned long)((flags >> 2) & 1), (unsigned long)((flags >> 3) & 1), (unsigned long)((flags >> 4) & 1));
    }
    *type = 0; *value = 0xffffffff; *bytes = sizeof(*value);
    LSTATUS status = RegQueryValueExW(key, L"FirstRun", NULL, type, (LPBYTE)value, bytes);
    printf("query=%ld type=%lu value=0x%08lx bytes=%lu\n", (long)status,
        (unsigned long)*type, (unsigned long)*value, (unsigned long)*bytes);
    RegCloseKey(key);
    return status;
}

int main(void)
{
    assert(sizeof(void *) == 4);
    printf("PID=%lu pointer_bytes=%zu\n", (unsigned long)GetCurrentProcessId(), sizeof(void *));
    char user[256]; DWORD user_size = sizeof(user);
    if (GetUserNameA(user, &user_size)) printf("current_user=%s\n", user);
    else printf("current_user error=%lu\n", (unsigned long)GetLastError());
    HANDLE token;
    if (OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) {
        token_flags("process", token);
        CloseHandle(token);
    } else printf("process_token error=%lu\n", (unsigned long)GetLastError());
    if (OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, TRUE, &token)) {
        token_flags("thread", token);
        CloseHandle(token);
    } else printf("thread_token error=%lu\n", (unsigned long)GetLastError());

    DWORD type, value, bytes;
    puts("HKLM\\Software\\Ice-pick Lodge\\Void, original access:");
    query(HKEY_LOCAL_MACHINE, L"Software\\Ice-pick Lodge\\Void", KEY_QUERY_VALUE, &type, &value, &bytes);
    puts("HKLM\\Software\\Ice-pick Lodge\\Void, KEY_READ comparison:");
    query(HKEY_LOCAL_MACHINE, L"Software\\Ice-pick Lodge\\Void", KEY_READ, &type, &value, &bytes);
    puts("HKCU explicit VirtualStore:");
    LSTATUS virtual_status = query(HKEY_CURRENT_USER,
        L"Software\\Classes\\VirtualStore\\MACHINE\\SOFTWARE\\WOW6432Node\\Ice-pick Lodge\\Void",
        KEY_QUERY_VALUE, &type, &value, &bytes);
    if (virtual_status != ERROR_SUCCESS || type != REG_DWORD || bytes != sizeof(DWORD)) {
        fputs("Explicit VirtualStore DWORD self-check failed.\n", stderr);
        return 1;
    }
    puts("Explicit VirtualStore DWORD self-check PASS; no values or token flags changed.");
    return 0;
}
