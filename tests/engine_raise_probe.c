/* Synthetic guest C++ catch routing; no PE, game DLL or UI. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include "native32.h"

void void_raise_exception(void);
static int sequence;
static uint32_t outer_record, expected_esp, object, bound_variable;
static recomp_ehframe_t owner;

void void_lift_trap(uint32_t address, const char *instruction)
{
    fprintf(stderr, "EXPECTED_OR_UNEXPECTED_TRAP %08X %s\n", address, instruction);
    ExitProcess(7);
}
static void inner_unwind(void) { if (++sequence != 1) ExitProcess(8); g_esp += 4; }
static void outer_unwind(void) { if (++sequence != 2) ExitProcess(8); g_esp += 4; }
static void caught(void)
{
    if (++sequence != 3 || MEM32(bound_variable) != object + 4) ExitProcess(8);
    g_eax = 0x20010100u; g_esp += 4;
}
const recomp_dispatch_entry_t recomp_dispatch_table[] = {
    {0x20010000u, inner_unwind}, {0x20010010u, outer_unwind}, {0x20010020u, caught}
};
const uint32_t recomp_dispatch_count = 3;
recomp_func_t recomp_lookup_manual(uint32_t va) { (void)va; return NULL; }

static void words(uint32_t dst, const uint32_t *src, size_t count)
{
    memcpy((void *)(uintptr_t)dst, src, count * 4);
}
static void stub(uint32_t dst, uint32_t info)
{
    MEM8(dst) = 0xB8; MEM32(dst + 1) = info;
    MEM8(dst + 5) = 0xE9; MEM32(dst + 6) = 0;
}

static void run(uint32_t magic, const char *mode)
{
    uint32_t blob = (uint32_t)(uintptr_t)VirtualAlloc(NULL, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!blob) ExitProcess(9);
    uint32_t inner_info = blob, outer_info = blob + 0x40;
    uint32_t inner_map = blob + 0x80, outer_map = blob + 0xA0;
    uint32_t tries = blob + 0xD0, handler = blob + 0x100;
    uint32_t throw_info = blob + 0x140, array = blob + 0x180, ct = blob + 0x1A0;
    uint32_t catch_type = blob + 0x200, throw_type = blob + 0x240;
    uint32_t params = blob + 0x280;
    object = blob + 0x300;
    uint32_t ii[] = {0x19930522u, 1, inner_map, 0, 0}; words(inner_info, ii, 5);
    uint32_t oi[] = {0x19930522u, 2, outer_map, 1, tries}; words(outer_info, oi, 5);
    uint32_t im[] = {0xFFFFFFFFu, 0x20010000u}; words(inner_map, im, 2);
    uint32_t om[] = {0xFFFFFFFFu, 0, 0, 0x20010010u}; words(outer_map, om, 4);
    uint32_t tb[] = {0, 1, 2, 1, handler}; words(tries, tb, 5);
    uint32_t h[] = {8, catch_type, 0x20, 0x20010020u}; words(handler, h, 4);
    strcpy((char *)(uintptr_t)(catch_type + 8), ".?AVProbeBase@@");
    strcpy((char *)(uintptr_t)(throw_type + 8), strcmp(mode, "uncaught") ? ".?AVProbeBase@@" : ".?AVOther@@");
    uint32_t ti[] = {0, 0, 0, array}; words(throw_info, ti, 4);
    uint32_t ar[] = {1, ct}; words(array, ar, 2);
    uint32_t catchable[] = {0, throw_type, 4, 0xFFFFFFFFu, 0, 4, 0}; words(ct, catchable, 7);
    uint32_t ps[] = {magic, object, !strcmp(mode, "invalid-info") ? 1 : throw_info}; words(params, ps, 3);
    stub(blob + 0x380, inner_info); stub(blob + 0x3A0, outer_info);

    uint32_t initial_esp = g_esp;
    outer_record = initial_esp - 0x200;
    uint32_t inner_record = initial_esp - 0x300;
    expected_esp = outer_record - 0x40;
    bound_variable = outer_record + 12 + 0x20;
    uint32_t out[] = {0xFFFFFFFFu, blob + 0x3A0, 1, 0}; words(outer_record, out, 4);
    uint32_t in[] = {outer_record, blob + 0x380, 0, 0}; words(inner_record, in, 4);
    MEM32(outer_record - 4) = expected_esp;
    MEM32(g_fs_base) = inner_record;
    sequence = 0;
    owner.entry_esp = outer_record + 16; owner.resume = 0;
    recomp_eh_push(&owner);
    if (setjmp(owner.jb) == 0) {
        g_esp = inner_record - 0x80;
        uint32_t call[] = {RECOMP_RETADDR, 0xE06D7363u, 1,
                           !strcmp(mode, "malformed") ? 4 : 3,
                           !strcmp(mode, "invalid-params") ? 1 : params};
        words(g_esp, call, 5);
        void_raise_exception();
        ExitProcess(10); /* A real matching catch must resume by longjmp. */
    }
    if (sequence != 3 || g_esp != expected_esp || g_ebp != outer_record + 12 ||
        MEM32(g_fs_base) != outer_record || MEM32(outer_record + 8) != 2 ||
        owner.resume != 0x20010100u) ExitProcess(11);
    recomp_eh_pop(&owner);
    MEM32(g_fs_base) = 0xFFFFFFFFu;
    g_esp = initial_esp;
    VirtualFree((void *)(uintptr_t)blob, 0, MEM_RELEASE);
    printf("PASS magic=%08X typed catch, base adjustment, inner/outer unwind, owner longjmp, stack/SEH restoration\n", magic);
}

int main(int argc, char **argv)
{
    native32_init(); mach_enter();
    if (argc == 2) run(!strcmp(argv[1], "magic") ? 0x01994000u : 0x19930520u, argv[1]);
    else {
        run(0x19930520u, "valid"); run(0x19930521u, "valid"); run(0x19930522u, "valid");
        uint32_t before = g_esp;
        uint32_t args[] = {RECOMP_RETADDR, 0x406D1388u, 0, 0, 0}; words(g_esp, args, 5);
        void_raise_exception();
        if (g_esp != before + 20) return 12;
        printf("PASS thread-name fallback pops original 20 bytes\n");
    }
    mach_leave(); return 0;
}
