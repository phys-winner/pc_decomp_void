#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <setjmp.h>

typedef void (*recomp_func_t)(void);
static uint32_t g_eax, g_edx, g_esp;
#define MEM32(address) (*(uint32_t *)(uintptr_t)(uint32_t)(address))
static unsigned lookups, traps, checks;
static uint32_t trapped_address;
static jmp_buf trap_landing;
static void guest_leaf(void) { ++checks; }
static int native32_in_guest(uint32_t va) { return va >= 0x21000000 && va < 0x21010000; }
static recomp_func_t recomp_lookup(uint32_t va) { ++lookups; return va == 0x21000010 ? guest_leaf : NULL; }
static void void_lift_trap(uint32_t va, const char *why) { (void)why; ++traps; trapped_address = va; longjmp(trap_landing, 1); }
static uint32_t d3d_create_device_target;
static void direct3d_create_device(void) { ++checks; }
#include "host-shims.h"

#define REQUIRE(expression) do { if (!(expression)) { fprintf(stderr, "FAIL line %u: %s\n", __LINE__, #expression); return 1; } ++checks; } while (0)
static DWORD tls_index, fls_index;

static int exercise(uintptr_t marker)
{
    static const DWORD errors[] = {0, 1, ERROR_ACCESS_DENIED, 0xFFFFFFFF};
    uint32_t stack[26] = {0xDEAD0000};
    REQUIRE(TlsSetValue(tls_index, (void *)marker));
    REQUIRE(FlsSetValue(fls_index, (void *)marker));
    for (unsigned i = 0; i < sizeof(errors) / sizeof(errors[0]); ++i) {
        recomp_func_t fn = recomp_lookup_manual((uint32_t)(uintptr_t)GetLastError);
        REQUIRE(fn == thread_get_error);
        g_eax = 0xAABBCCDD; g_edx = 0x11223344; g_esp = (uint32_t)(uintptr_t)stack;
        SetLastError(errors[i]); fn();
        DWORD actual_error = GetLastError();
        REQUIRE(g_eax == errors[i] && actual_error == errors[i]);
        REQUIRE(g_esp == (uint32_t)(uintptr_t)stack + 4 && g_edx == 0x11223344);
        fn = recomp_lookup_manual((uint32_t)(uintptr_t)SetLastError);
        REQUIRE(fn == thread_set_error);
        stack[1] = errors[i]; g_eax = 0xAABBCCDD; g_esp = (uint32_t)(uintptr_t)stack;
        SetLastError(42); fn(); actual_error = GetLastError();
        REQUIRE(actual_error == errors[i] && g_eax == 0xAABBCCDD);
        REQUIRE(g_esp == (uint32_t)(uintptr_t)stack + 8 && g_edx == 0x11223344);
        for (unsigned invalid = 0; invalid < 2; ++invalid) {
            DWORD index = invalid ? TLS_OUT_OF_INDEXES : tls_index;
            SetLastError(errors[i]);
            void *expected = TlsGetValue(index); DWORD expected_error = GetLastError();
            fn = recomp_lookup_manual((uint32_t)(uintptr_t)TlsGetValue);
            REQUIRE(fn == thread_tls_value);
            stack[1] = index; g_esp = (uint32_t)(uintptr_t)stack;
            SetLastError(errors[i]); fn(); actual_error = GetLastError();
            REQUIRE(g_eax == (uint32_t)(uintptr_t)expected && actual_error == expected_error);
            REQUIRE(g_esp == (uint32_t)(uintptr_t)stack + 8 && g_edx == 0x11223344);
            index = invalid ? FLS_OUT_OF_INDEXES : fls_index;
            SetLastError(errors[i]); expected = FlsGetValue(index); expected_error = GetLastError();
            fn = recomp_lookup_manual((uint32_t)(uintptr_t)FlsGetValue);
            REQUIRE(fn == thread_fls_value);
            stack[1] = index; g_esp = (uint32_t)(uintptr_t)stack;
            SetLastError(errors[i]); fn(); actual_error = GetLastError();
            REQUIRE(g_eax == (uint32_t)(uintptr_t)expected && actual_error == expected_error);
            REQUIRE(g_esp == (uint32_t)(uintptr_t)stack + 8 && g_edx == 0x11223344);
        }
        REQUIRE(stack[0] == 0xDEAD0000);
    }
    REQUIRE(TlsGetValue(tls_index) == (void *)marker);
    REQUIRE(FlsGetValue(fls_index) == (void *)marker);
    return 0;
}
static DWORD WINAPI worker(void *unused) { (void)unused; return exercise(0x10203040); }
int main(void)
{
    REQUIRE(sizeof(void *) == 4);
    tls_index = TlsAlloc(); fls_index = FlsAlloc(NULL);
    REQUIRE(tls_index != TLS_OUT_OF_INDEXES && fls_index != FLS_OUT_OF_INDEXES);
    REQUIRE(exercise(0) == 0);
    REQUIRE(exercise(0x55667788) == 0);
    HANDLE thread = CreateThread(NULL, 0, worker, NULL, 0, NULL);
    REQUIRE(thread != NULL && WaitForSingleObject(thread, 5000) == WAIT_OBJECT_0);
    DWORD exit_code; REQUIRE(GetExitCodeThread(thread, &exit_code) && !exit_code); CloseHandle(thread);
    REQUIRE(TlsGetValue(tls_index) == (void *)0x55667788 && FlsGetValue(fls_index) == (void *)0x55667788);
    lookups = 0;
    REQUIRE(recomp_lookup_manual(0x21000010) == guest_leaf && lookups == 1);
    REQUIRE(recomp_lookup_manual(0x22000000) == NULL && lookups == 1);
    const uint32_t invalid_targets[] = {0, 0xFFFF, 0x21000020};
    for (unsigned i = 0; i < sizeof(invalid_targets) / sizeof(invalid_targets[0]); ++i) {
        if (!setjmp(trap_landing)) { recomp_lookup_manual(invalid_targets[i]); REQUIRE(0); }
        REQUIRE(trapped_address == invalid_targets[i]);
    }
    REQUIRE(traps == 3 && lookups == 2);
    d3d_create_device_target = 0x23000000;
    REQUIRE(recomp_lookup_manual(d3d_create_device_target) == direct3d_create_device && lookups == 2);
    REQUIRE(TlsFree(tls_index) && FlsFree(fls_index));
    printf("Thread API shims / strict single-lookup dispatch PASS: %u checks\n", checks);
    return 0;
}
