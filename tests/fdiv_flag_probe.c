#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

/* Execute only verified, import-bounded CRT flag initialization in a copied
 * fixture. The DLL is never registered with the OS loader or initialized. */
int main(int argc, char **argv) {
    FILE *file;
    unsigned char *image;
    DWORD old_protection;
    uint32_t base, size, detector, fallback, initializer, flag, module_iat, proc_iat;
    uint32_t detected, arithmetic, initialized;
    uint16_t cw = 0x037F;
    unsigned char host_state[108];
    if (argc != 10) return 2;
    base = strtoul(argv[2], NULL, 0); size = strtoul(argv[3], NULL, 0);
    detector = strtoul(argv[4], NULL, 0); fallback = strtoul(argv[5], NULL, 0);
    initializer = strtoul(argv[6], NULL, 0); flag = strtoul(argv[7], NULL, 0);
    module_iat = strtoul(argv[8], NULL, 0); proc_iat = strtoul(argv[9], NULL, 0);
    image = VirtualAlloc((void *)base, size, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    if (image != (void *)base) return 3;
    if (fopen_s(&file, argv[1], "rb") || !file || fread(image, 1, size, file) != size || fclose(file)) return 4;
    *(uint32_t *)module_iat = (uint32_t)GetModuleHandleA;
    *(uint32_t *)proc_iat = (uint32_t)GetProcAddress;
    if (!VirtualProtect((void *)(detector & ~0xFFFu), 0x1000, PAGE_EXECUTE_READ, &old_protection)) return 5;
    if (!VirtualProtect((void *)(initializer & ~0xFFFu), 0x1000, PAGE_EXECUTE_READ, &old_protection)) return 6;
    __asm { fnsave host_state }
    __asm { fldcw cw }
    detected = ((uint32_t (__cdecl *)(void))detector)();
    __asm { fninit }
    __asm { fldcw cw }
    arithmetic = ((uint32_t (__cdecl *)(void))fallback)();
    __asm { fninit }
    __asm { fldcw cw }
    ((void (__cdecl *)(uint32_t))initializer)(0);
    initialized = *(uint32_t *)flag;
    __asm { frstor host_state }
    printf("{\"system_errata\":%u,\"original_detector\":%u,\"original_arithmetic_fallback\":%u,\"original_initialized_flag\":%u,\"fixture_rx_pages\":[\"0x%08X\",\"0x%08X\"]}\n",
        (uint32_t)IsProcessorFeaturePresent(PF_FLOATING_POINT_PRECISION_ERRATA),
        detected, arithmetic, initialized, detector & ~0xFFFu, initializer & ~0xFFFu);
    VirtualFree(image, 0, MEM_RELEASE);
    return 0;
}
