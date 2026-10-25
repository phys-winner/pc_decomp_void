/* Compare lifted game instructions with an independent x86 oracle. */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <sys/mman.h>
#endif
#include "cpu.h"
#include "vectors.h"

uint32_t g_image_delta = 0;
void PROBE_FUNCTION(CPU *c);

#if defined(_MSC_VER) && defined(_M_IX86)
typedef struct { uint32_t eax, ecx, edx, ebx, ebp, esi, edi, flags; } Snapshot;
/* Preserve the host ABI while executing the original EAX-argument function. */
__declspec(naked) static void original(void *code, uint32_t input, Snapshot *out)
{
    __asm {
        push ebp
        push ebx
        push esi
        push edi
        push dword ptr [esp+28]
        mov eax, [esp+28]
        mov ecx, 0x12345678
        mov edx, 0x87654321
        mov ebx, 0x13579BDF
        mov ebp, 0x2468ACE0
        mov esi, 0x55AA55AA
        mov edi, 0xAA55AA55
        call dword ptr [esp+24]
        pushfd
        pushad
        mov esi, [esp+36]
        mov eax, [esp+28]
        mov [esi], eax
        mov eax, [esp+24]
        mov [esi+4], eax
        mov eax, [esp+20]
        mov [esi+8], eax
        mov eax, [esp+16]
        mov [esi+12], eax
        mov eax, [esp+8]
        mov [esi+16], eax
        mov eax, [esp+4]
        mov [esi+20], eax
        mov eax, [esp]
        mov [esi+24], eax
        mov eax, [esp+32]
        mov [esi+28], eax
        popad
        popfd
        add esp, 4
        pop edi
        pop esi
        pop ebx
        pop ebp
        ret
    }
}
#endif

int void_probe(char *message, size_t capacity)
{
    const uintptr_t base = 0x20000000u;
    const size_t size = 0x10000;
    unsigned char *stack;
#ifdef _WIN32
    stack = VirtualAlloc((void *)base, size, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
#else
    /* shortcut: low guest addresses for this leaf; full port needs a guest arena and ABI bridges. */
    stack = mmap((void *)base, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (stack == MAP_FAILED) stack = NULL;
#endif
    if (!stack || (uintptr_t)stack != base) {
        snprintf(message, capacity, "FAIL: cannot allocate guest stack at 0x20000000");
        if (stack) {
#ifdef _WIN32
            VirtualFree(stack, 0, MEM_RELEASE);
#else
            munmap(stack, size);
#endif
        }
        return 1;
    }
#if defined(_MSC_VER) && defined(_M_IX86)
    void *code = VirtualAlloc(NULL, sizeof(original_code), MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    DWORD previous;
    if (!code) { VirtualFree(stack, 0, MEM_RELEASE); return 2; }
    memcpy(code, original_code, sizeof(original_code));
    if (!VirtualProtect(code, sizeof(original_code), PAGE_EXECUTE_READ, &previous)) {
        VirtualFree(code, 0, MEM_RELEASE); VirtualFree(stack, 0, MEM_RELEASE); return 3;
    }
    FlushInstructionCache(GetCurrentProcess(), code, sizeof(original_code));
#endif
    int result = 0;
    size_t count = sizeof(vectors) / sizeof(vectors[0]);
    for (size_t i = 0; i < count; ++i) {
        const Vector *v = &vectors[i];
        memset(stack, 0xA5, size);
        wr32((uint32_t)(base + size - 4), 0x30000000u);
        CPU c = {0};
        c.eax = v->input; c.ecx = 0x12345678; c.edx = 0x87654321;
        c.ebx = 0x13579BDF; c.ebp = 0x2468ACE0;
        c.esi = 0x55AA55AA; c.edi = 0xAA55AA55;
        c.esp = (uint32_t)(base + size - 4);
        PROBE_FUNCTION(&c);
        uint32_t flags = c.cf | c.pf << 2 | c.af << 4 | c.zf << 6 | c.sf << 7 | c.of << 11;
        if (c.eax != v->eax || c.ecx != v->ecx || c.edx != v->edx || flags != v->flags ||
            c.ebx != 0x13579BDF || c.ebp != 0x2468ACE0 ||
            c.esi != 0x55AA55AA || c.edi != 0xAA55AA55 || c.esp != base + size ||
            rd32((uint32_t)(base + size - 8)) != 0x55AA55AA ||
            rd32((uint32_t)(base + size - 12)) != 0xAA55AA55 ||
            rd32((uint32_t)(base + size - 4)) != 0x30000000) {
            snprintf(message, capacity, "FAIL: lifted case %zu input=%08X", i, v->input);
            result = 4; break;
        }
#if defined(_MSC_VER) && defined(_M_IX86)
        Snapshot s;
        original(code, v->input, &s);
        if (s.eax != c.eax || s.ecx != c.ecx || s.edx != c.edx ||
            s.ebx != c.ebx || s.ebp != c.ebp || s.esi != c.esi || s.edi != c.edi ||
            (s.flags & 0x8D5) != flags) {
            snprintf(message, capacity, "FAIL: native original case %zu input=%08X", i, v->input);
            result = 5; break;
        }
#endif
    }
#ifdef _WIN32
    VirtualFree(stack, 0, MEM_RELEASE);
#if defined(_MSC_VER) && defined(_M_IX86)
    VirtualFree(code, 0, MEM_RELEASE);
#endif
#else
    munmap(stack, size);
#endif
    if (!result) snprintf(message, capacity,
        "PASS: Engine.dll 0x10029CB0, %zu cases, registers/flags/stack; %zu-bit native host", count, sizeof(void *) * 8);
    return result;
}
