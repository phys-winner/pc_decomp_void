/* A biased EBP catch owner, compiled from the actual project emitter. No DLL/UI. */
#include "../native/void_runtime.c"
#include "renderer_eh_funcs.h"

void void_lift_trap(uint32_t address, const char *instruction)
{
    fprintf(stderr, "Unexpected trap %08X %s\n", address, instruction);
    ExitProcess(90);
}

recomp_func_t recomp_lookup_manual(uint32_t address)
{
    return address == 0x22000000u ? void_raise_exception : NULL;
}

int main(int argc, char **argv)
{
    if (argc != 2) return 91;
    FILE *file = fopen(argv[1], "rb");
    if (!file) return 92;
    void *image = VirtualAlloc((void *)0x21000000u, 0x4000,
        MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (image != (void *)0x21000000u || fread(image, 1, 0x4000, file) != 0x4000)
        return 93;
    fclose(file);
    native32_init(); mach_enter();
    const uint32_t initial[] = {0x41424344u, 0x51525354u, 0x61626364u, 0x71727374u};
    for (unsigned pass = 0; pass < 4; ++pass) {
        unsigned index = pass % 2;
        uint32_t owner = 0x21000000u + index * 0x400u;
        uint32_t data = 0x21002000u + index * 0x400u;
        uint32_t stack = g_esp;
        g_ebx = initial[0]; g_esi = initial[1];
        g_edi = initial[2]; g_ebp = initial[3];
        PUSH32(g_esp, RECOMP_RETADDR);
        recomp_func_t function = recomp_lookup(owner);
        if (!function) return 94;
        function();
        if (g_eax != 0xA1B2C3D4u || g_esp != stack || g_ebp != initial[3] ||
            g_ebx != initial[0] || g_esi != initial[1] || g_edi != initial[2] ||
            MEM32(g_fs_base) != 0xFFFFFFFFu || MEM32(data + 0x300) != pass / 2 + 1)
            return 95;
    }
    MEMORY_BASIC_INFORMATION region;
    if (!VirtualQuery(image, &region, sizeof region) || region.Protect != PAGE_READWRITE)
        return 96;
    mach_leave();
    puts("PASS canonical + biased EBP owners, actual dispatch/longjmp twice each, cold resume, GPR/ESP/SEH restored, original image NX");
    return 0;
}
