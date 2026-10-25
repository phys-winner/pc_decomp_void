/* Execute only the pinned CRT helper pages in an isolated original-image fixture. */
#define WIN32_LEAN_AND_MEAN
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#pragma pack(push, 1)
typedef struct {
    uint32_t entry, fdiv_flag, regs[8], eflags;
    unsigned char fpu[108], arguments[64];
} input_t;
typedef struct {
    uint32_t exception_code, exception_pc, entry_esp, return_pc, regs[8], eflags;
    unsigned char before[28], fpu[108], memory[256];
} output_t;
#pragma pack(pop)

static input_t input;
static output_t output;
static uint32_t host_stack, scratch, target, initial_eax, initial_ecx, initial_edx;
static uint32_t initial_ebx, initial_ebp, initial_esi, initial_edi, initial_flags;
static unsigned char host_fpu[108], test_fpu[108], arguments[64];

static __declspec(naked) void invoke_original(void)
{
    __asm {
        pushfd
        pushad
        mov host_stack, esp
        fnsave host_fpu
        sub esp, 512
        mov scratch, esp
        mov edi, esp
        mov eax, 0A5A5A5A5h
        mov ecx, 128
        cld
        rep stosd
        mov edi, scratch
        add edi, 256
        mov esi, offset arguments
        mov ecx, 16
        rep movsd
        frstor test_fpu
        fnstenv output.before
        fldenv output.before
        mov eax, scratch
        add eax, 252
        mov output.entry_esp, eax
        mov output.return_pc, offset returned
        mov eax, scratch
        add eax, 256
        mov esp, eax
        push initial_flags
        popfd
        mov ebx, initial_ebx
        mov ebp, initial_ebp
        mov esi, initial_esi
        mov edi, initial_edi
        mov ecx, initial_ecx
        mov edx, initial_edx
        mov eax, initial_eax
        call target
    returned:
        mov output.regs[0], eax
        mov output.regs[4], ecx
        mov output.regs[8], edx
        mov output.regs[12], ebx
        mov output.regs[16], esp
        mov output.regs[20], ebp
        mov output.regs[24], esi
        mov output.regs[28], edi
        pushfd
        pop output.eflags
        fnsave output.fpu
        mov esi, output.entry_esp
        sub esi, 128
        lea edi, output.memory
        mov ecx, 64
        cld
        rep movsd
        frstor host_fpu
        mov esp, host_stack
        popad
        popfd
        ret
    }
}

static int capture_exception(EXCEPTION_POINTERS *exception)
{
    CONTEXT *c = exception->ContextRecord;
    output.exception_code = exception->ExceptionRecord->ExceptionCode;
    output.exception_pc = (uint32_t)(uintptr_t)exception->ExceptionRecord->ExceptionAddress;
    output.regs[0] = c->Eax; output.regs[1] = c->Ecx; output.regs[2] = c->Edx; output.regs[3] = c->Ebx;
    output.regs[4] = c->Esp; output.regs[5] = c->Ebp; output.regs[6] = c->Esi; output.regs[7] = c->Edi;
    output.eflags = c->EFlags;
    memcpy(output.fpu, &c->FloatSave, 108);
    memcpy(output.memory, (void *)(uintptr_t)(output.entry_esp - 128), 256);
    return EXCEPTION_EXECUTE_HANDLER;
}

int main(int argc, char **argv)
{
    if (argc != 4 || sizeof(input_t) != 216 || sizeof(output_t) != 444) return 64;
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    FILE *image = fopen(argv[1], "rb"), *cases = fopen(argv[2], "rb"), *results = fopen(argv[3], "wb");
    if (!image || !cases || !results) return 65;
    void *mapped = VirtualAlloc((void *)0x10000000u, 0x39C000, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    if (mapped != (void *)0x10000000u || fread(mapped, 1, 0x39C000, image) != 0x39C000) return 66;
    fclose(image);
    /* Only two bounded, import-free CRT pages can execute. Every other PE page remains NX. */
    DWORD old;
    if (!VirtualProtect((void *)0x10259000u, 0x1000, PAGE_EXECUTE_READ, &old) ||
        !VirtualProtect((void *)0x1025C000u, 0x1000, PAGE_EXECUTE_READ, &old)) return 67;
    FlushInstructionCache(GetCurrentProcess(), mapped, 0x39C000);
    unsigned count = 0;
    while (fread(&input, sizeof input, 1, cases) == 1) {
        if (input.entry != 0x10259FB4u && input.entry != 0x1025CB3Cu &&
            input.entry != 0x1025CDF4u && input.entry != 0x1025C936u && input.entry != 0x1025CBEEu) return 68;
        *(uint32_t *)0x10357CF8u = input.fdiv_flag;
        target = input.entry; initial_eax = input.regs[0]; initial_ecx = input.regs[1]; initial_edx = input.regs[2];
        initial_ebx = input.regs[3]; initial_ebp = input.regs[5]; initial_esi = input.regs[6]; initial_edi = input.regs[7];
        initial_flags = input.eflags;
        memcpy(test_fpu, input.fpu, 108); memcpy(arguments, input.arguments, 64); memset(&output, 0, sizeof output);
        __try { invoke_original(); }
        __except(capture_exception(GetExceptionInformation())) {
            __asm { fninit }
            __asm { frstor host_fpu }
        }
        if (fwrite(&output, sizeof output, 1, results) != 1) return 69;
        ++count;
    }
    fclose(cases); fclose(results); VirtualFree(mapped, 0, MEM_RELEASE);
    printf("PASS native pinned Renderer CRT oracle records=%u; two RX helper pages, remaining original image NX, no DLL bootstrap\n", count);
    return 0;
}
