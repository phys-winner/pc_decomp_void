/* Four-mode register-transfer probe. No PE, game DLL or user interface. */
#include "../native/void_runtime.c"
#include "runtime_modes_funcs.h"

#define DATA 0x21008000u
static unsigned yield_count;
static int callback_count;

void void_lift_trap(uint32_t address, const char *instruction)
{
    fprintf(stderr, "Unexpected trap %08X %s\n", address, instruction);
    ExitProcess(90);
}

recomp_func_t recomp_lookup_manual(uint32_t va)
{
    return va == 0x22000000u ? void_raise_exception : NULL;
}

/* cb_run is the exact callback implementation included from the pinned runtime.
 * Calling it directly tests its ABI/context path without a PE or an NX fault. */
static uint64_t __stdcall native_target(uint32_t callback, uint32_t a, uint32_t b)
{
    uint32_t observed_this;
    __asm mov observed_this, ecx
    uint32_t args[24 + 1] = {0};
    DWORD observed_error = GetLastError();
    if (callback != 0x21000500u || a != 0x11223344u || b != 0xAABBCCDDu ||
        observed_this != 0x31323334u || observed_error != 777) {
        fprintf(stderr, "native arguments callback=%08X a=%08X b=%08X this=%08X last_error=%lu\n",
            callback, a, b, observed_this, observed_error);
        ExitProcess(91);
    }
    args[1] = a; args[2] = b;
    uint64_t result = cb_run(callback, args, 0x91929394u);
    if ((uint32_t)(result >> 32) != 8 || (uint32_t)result != (a ^ b)) ExitProcess(92);
    callback_count++;
    SetLastError(888);
    return ((uint64_t)0xCAFEBABEu << 32) | ((uint32_t)result + 9u);
}

static void yielding(void)
{
    if (g_ecx != 6u - yield_count || g_edx != yield_count) ExitProcess(93);
    yield_count++;
    g_eax += 100;
    g_edx++;
    /* Backedge handover must retain the caller's local DEC flags. */
    g_flag_k = FK_CMP; g_flag_a = 0; g_flag_b = 0; g_flag_cf = 0;
}

static uint32_t enter_body(recomp_func_t body, int argument)
{
    uint32_t before = g_esp;
    if (argument) PUSH32(g_esp, 0xFFFFFFFCu);
    PUSH32(g_esp, RECOMP_RETADDR);
    body();
    if (g_esp != before) ExitProcess(94);
    return g_eax;
}

static void words(uint32_t address, const uint32_t *values, size_t count)
{
    memcpy((void *)(uintptr_t)address, values, count * sizeof(*values));
}

static void setup_exception(void)
{
    uint32_t fi[] = {0x19930522u, 1, DATA + 0x140, 1, DATA + 0x160};
    uint32_t unwind[] = {0xFFFFFFFFu, 0};
    uint32_t tries[] = {0, 0, 1, 1, DATA + 0x180};
    uint32_t caught[] = {0, 0, 0, 0x21000800u};
    uint32_t info[] = {0, 0, 0, DATA + 0x1D0};
    uint32_t array[] = {0};
    uint32_t params[] = {0x19930520u, DATA + 0x300, DATA + 0x1B0};
    words(DATA + 0x100, fi, 5); words(DATA + 0x140, unwind, 2);
    words(DATA + 0x160, tries, 5); words(DATA + 0x180, caught, 4);
    words(DATA + 0x1B0, info, 4); words(DATA + 0x1D0, array, 1);
    words(DATA + 0x1E0, params, 3);
    MEM8(DATA + 0x200) = 0xB8; MEM32(DATA + 0x201) = DATA + 0x100;
    MEM8(DATA + 0x205) = 0xE9; MEM32(DATA + 0x206) = 0;
}

int main(void)
{
    void *mapped = VirtualAlloc((void *)0x21000000u, 0x10000,
        MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (mapped != (void *)0x21000000u) return 95;
    native32_init(); mach_enter();
    if (g_mem_base != 0) return 96;
    MEM32(DATA + 4) = (uint32_t)(uintptr_t)native_target;
    uint32_t registers[] = {4, 0x11121314u, 0x21222324u, 0x41424344u,
        0x51525354u, 0x61626364u, 0x71727374u};
    for (int i = 0; i < 2; i++) {
        memset((void *)(uintptr_t)(DATA + 0x20), 0, sizeof registers);
        if (enter_body(i ? sub_21000200 : sub_21000000, 0) != 4 ||
            memcmp((void *)(uintptr_t)(DATA + 0x20), registers, sizeof registers)) return 97;
    }
    if (enter_body(sub_21000300, 1) != 3) return 98;
    g_ebx = 0x41424344u; g_esi = 0x51525354u;
    g_edi = 0x61626364u; g_ebp = 0x71727374u;
    SetLastError(777);
    if (enter_body(sub_21000400, 0) != ((0x11223344u ^ 0xAABBCCDDu) + 9u) ||
        g_edx != 0xCAFEBABEu || g_ebx != 0x41424344u || g_esi != 0x51525354u ||
        g_edi != 0x61626364u || g_ebp != 0x71727374u ||
        callback_count != 1 || GetLastError() != 888) return 99;
    recomp_yield_hook = yielding; yield_count = 0; g_backedges = 0;
    if (enter_body(sub_21000600, 0) != 712 || g_edx != 7 || yield_count != 7) return 100;
    setup_exception(); g_ebp = 0x71727374u;
    if (enter_body(sub_21000700, 0) != 0xA1B2C3D4u || g_ebp != 0x71727374u ||
        MEM32(g_fs_base) != 0xFFFFFFFFu) return 101;
    mach_leave();
    puts("PASS direct/indirect all-GPR + carry, indirect tail RET4, native stdcall/this + EDX:EAX + callback RET8/context/last-error, backward handover, actual C++ catch owner longjmp/ESP/EBP/SEH");
    return 0;
}
