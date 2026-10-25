/* Standalone context-switch probe; links the unmodified native32 runtime. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include "native32.h"

const recomp_dispatch_entry_t recomp_dispatch_table[1] = {{0, NULL}};
const uint32_t recomp_dispatch_count = 0;
recomp_func_t recomp_lookup_manual(uint32_t va) { (void)va; return NULL; }

/* Project wrapper helpers are linked but never exercised by this probe. */
void void_lift_trap(uint32_t address, const char *instruction)
{
    fprintf(stderr, "Unexpected project helper trap at %08X: %s\n", address, instruction);
    ExitProcess(3);
}

typedef struct {
    uint32_t regs[8];
    uint32_t flags[4];
} snapshot;

static HANDLE a_ready, b_done;
static snapshot expected, restored;
static DWORD a_id, b_id;
static int control_regs, control_flags, control_carry;
static int switched_regs, switched_flags, switched_carry;

static void capture(snapshot *s)
{
    uint32_t regs[] = {g_eax, g_ecx, g_edx, g_esp, g_ebx, g_esi, g_edi, g_ebp};
    uint32_t flags[] = {g_flag_k, g_flag_a, g_flag_b, g_flag_cf};
    memcpy(s->regs, regs, sizeof regs);
    memcpy(s->flags, flags, sizeof flags);
}

static void publish_a(void)
{
    uint32_t _flag_k = FK_CMP, _flag_a = 0, _flag_b = 1, _cf = 1;
    g_eax = 0xA1111111u; g_ecx = 0xA2222222u; g_edx = 0xA3333333u;
    g_ebx = 0xA5555555u; g_esi = 0xA6666666u; g_edi = 0xA7777777u;
    g_ebp = 0xA8888888u;
    /* Keep the runtime-allocated guest ESP valid. */
    RECOMP_FLAGS_OUT();
}

static void publish_b(void)
{
    uint32_t _flag_k = FK_ADD, _flag_a = 0x1020u, _flag_b = 0x3040u, _cf = 0;
    g_eax = 0xB1111111u; g_ecx = 0xB2222222u; g_edx = 0xB3333333u;
    g_ebx = 0xB5555555u; g_esi = 0xB6666666u; g_edi = 0xB7777777u;
    g_ebp = 0xB8888888u;
    RECOMP_FLAGS_OUT();
}

/* Same inbound flags and carry condition as a generated body with an early jb. */
__declspec(noinline) static int next_lifted_entry_carry(void)
{
    uint32_t _flag_k = FK_NONE, _flag_a = 0, _flag_b = 0, _cf = 0;
    RECOMP_ENTER(0x11111111u);
    int taken = recomp_cond(_flag_k, _flag_a, _flag_b, CC_B);
    RECOMP_FLAGS_OUT();
    return taken;
}

static DWORD WINAPI thread_a(void *unused)
{
    (void)unused;
    a_id = GetCurrentThreadId();
    mach_enter();
    publish_a();
    capture(&expected);
    mach_leave();

    /* Positive control: restore the same thread without any intervening guest. */
    mach_enter();
    capture(&restored);
    control_regs = memcmp(expected.regs, restored.regs, sizeof expected.regs) == 0;
    control_flags = memcmp(expected.flags, restored.flags, sizeof expected.flags) == 0;
    control_carry = next_lifted_entry_carry();
    mach_leave();

    if (!SetEvent(a_ready) || WaitForSingleObject(b_done, 5000) != WAIT_OBJECT_0) return 2;
    mach_enter();
    capture(&restored);
    switched_regs = memcmp(expected.regs, restored.regs, sizeof expected.regs) == 0;
    switched_flags = memcmp(expected.flags, restored.flags, sizeof expected.flags) == 0;
    switched_carry = next_lifted_entry_carry();
    mach_leave();
    return 0;
}

static DWORD WINAPI thread_b(void *unused)
{
    (void)unused;
    b_id = GetCurrentThreadId();
    if (WaitForSingleObject(a_ready, 5000) != WAIT_OBJECT_0) return 2;
    mach_enter();
    publish_b();
    mach_leave();
    return SetEvent(b_done) ? 0 : 2;
}

int main(void)
{
    native32_init();
    a_ready = CreateEventW(NULL, TRUE, FALSE, NULL);
    b_done = CreateEventW(NULL, TRUE, FALSE, NULL);
    if (!a_ready || !b_done) return 2;
    HANDLE threads[2] = {CreateThread(NULL, 0, thread_a, NULL, 0, NULL),
                         CreateThread(NULL, 0, thread_b, NULL, 0, NULL)};
    if (!threads[0] || !threads[1] ||
        WaitForMultipleObjects(2, threads, TRUE, 10000) != WAIT_OBJECT_0) return 2;
    DWORD codes[2];
    GetExitCodeThread(threads[0], &codes[0]); GetExitCodeThread(threads[1], &codes[1]);
    CloseHandle(threads[0]); CloseHandle(threads[1]);
    CloseHandle(a_ready); CloseHandle(b_done);
    if (codes[0] || codes[1]) return 2;

    printf("threads A=%lu B=%lu; no guest PE or game DLL loaded\n", a_id, b_id);
    printf("same-thread control: GPR=%s flags=%s inbound_carry=%d expected=1\n",
           control_regs ? "PASS" : "FAIL", control_flags ? "PASS" : "FAIL", control_carry);
    printf("cross-thread restore: GPR=%s flags=%s inbound_carry=%d expected=1\n",
           switched_regs ? "PASS" : "FAIL", switched_flags ? "PASS" : "FAIL", switched_carry);
    printf("expected A flags: k=%u a=%08X b=%08X cf=%u\n", expected.flags[0],
           expected.flags[1], expected.flags[2], expected.flags[3]);
    printf("restored flags:   k=%u a=%08X b=%08X cf=%u\n", restored.flags[0],
           restored.flags[1], restored.flags[2], restored.flags[3]);
    int pass = control_regs && control_flags && control_carry &&
               switched_regs && switched_flags && switched_carry;
    printf("context restoration: %s\n", pass ? "PASS" : "FAIL");
    return pass ? 0 : 1;
}
