/* Project-owned PE checks and nested DLL events around the pinned runtime. */
#include "recomp_types.h"
#include "../generated/native-runtime/native32.c"

extern void void_lift_trap(uint32_t address, const char *instruction);

/* shortcut: double operands; replace when the guest has a raw80 x87 context. */
void void_fpu_remainder(uint32_t address, int nearest)
{
    if (g_fp_top < 2 || g_fp_top > 8 || (g_fpu_cw & 0x0300u) == 0x0100u ||
            (nearest != 0 && nearest != 1)) {
        void_lift_trap(address, "unsupported FPREM stack/control word"); return;
    }
    uint64_t bits[2]; memcpy(bits, g_st, sizeof bits);
    for (int i = 0; i < 2; ++i) {
        if ((bits[i] & 0x7FF0000000000000ull) == 0x7FF0000000000000ull &&
                (bits[i] & 0x000FFFFFFFFFFFFFull) && !(bits[i] & 0x0008000000000000ull)) {
            void_lift_trap(address, "unsupported signaling-double FPREM operand"); return;
        }
    }
    unsigned char host[108];
    uint16_t operation_status = 0, guest_cw = g_fpu_cw, projection_cw = g_fpu_cw | 0x003Fu;
    uint32_t native_exception = 0;
    double result;
    __asm {
        lea eax, host
        fnsave [eax]
    }
    __try {
        __asm {
            mov eax, offset g_st
            fld qword ptr [eax + 8]
            fld qword ptr [eax]
            fnclex
            fldcw guest_cw
        }
        if (nearest) { __asm fprem1 }
        else { __asm fprem }
        __asm {
            fnstsw operation_status
            fnclex
            fldcw projection_cw
            fstp result
            fstp st(0)
        }
    } __except(EXCEPTION_EXECUTE_HANDLER) {
        native_exception = GetExceptionCode();
        __asm fnclex
    }
    __asm {
        lea eax, host
        frstor [eax]
    }
    if (native_exception || ((operation_status & 0x003Fu) & ~guest_cw)) {
        void_lift_trap(address, "unsupported unmasked FPREM exception"); return;
    }
    memcpy(g_st, &result, sizeof result);
    g_st_i64[0] = 0;
    void_fpu_cmp = (int)(0x10000u | (operation_status & 0x4700u));
}

/* Vorbis requests size * nmemb bytes; the shipping adapter ignores nmemb. */
void void_sound_bulk_read(void)
{
    const uint32_t callback = 0x14061270u;
    g_cur_func = callback;
#ifdef RECOMP_TRACE
    recomp_trace_enter(callback);
#endif
    uint32_t entry = g_esp;
    uint32_t buffer = MEM32(entry + 4), size = MEM32(entry + 8), count = MEM32(entry + 12);
    if (!size || !count || size > UINT32_MAX / count) {
        g_eax = 0; g_esp = entry + 4; return;
    }
    uint32_t bytes = size * count;
    uint32_t file = MEM32(MEM32(entry + 16));
    uint32_t target = MEM32(MEM32(file) + 0x24);
    recomp_func_t read = recomp_lookup_manual(target);
    if (!read) read = recomp_lookup(target);
    if (!read) read = recomp_lookup_import(target);
    if (!read) { void_lift_trap(target, "unresolved Sound stream reader"); return; }
    g_icall_trace[g_icall_trace_idx & (ICALL_TRACE_SIZE - 1)] = target;
    g_icall_from[g_icall_trace_idx & (ICALL_TRACE_SIZE - 1)] = callback;
    ++g_icall_trace_idx; ++g_icall_count;
    g_ecx = file;
    PUSH32(g_esp, bytes); PUSH32(g_esp, buffer); PUSH32(g_esp, RECOMP_RETADDR);
    read();
    g_cur_func = callback;
    if (g_esp != entry || g_eax > bytes) {
        void_lift_trap(callback, "invalid Sound stream read count or stack cleanup"); return;
    }
    g_eax /= size;
    g_esp = entry + 4;
}

uint32_t void_map_module(const char *path, uint32_t base, uint32_t entry)
{
    if (g_mod_n >= MAX_MODULES || native32_module(path)) return 0;
    FILE *file = fopen(path, "rb");
    if (!file) return 0;
    fseek(file, 0, SEEK_END);
    long file_size = ftell(file);
    rewind(file);
    IMAGE_DOS_HEADER dos;
    IMAGE_NT_HEADERS32 nt;
    int valid = file_size >= (long)sizeof(dos) && fread(&dos, sizeof(dos), 1, file) == 1 &&
        dos.e_magic == IMAGE_DOS_SIGNATURE && dos.e_lfanew >= (LONG)sizeof(dos) &&
        dos.e_lfanew <= file_size - (long)sizeof(nt);
    if (valid) {
        valid = !fseek(file, dos.e_lfanew, SEEK_SET) && fread(&nt, sizeof(nt), 1, file) == 1 &&
            nt.Signature == IMAGE_NT_SIGNATURE && nt.FileHeader.Machine == IMAGE_FILE_MACHINE_I386 &&
            (nt.FileHeader.Characteristics & IMAGE_FILE_DLL) &&
            nt.FileHeader.SizeOfOptionalHeader == sizeof(IMAGE_OPTIONAL_HEADER32) &&
            nt.OptionalHeader.Magic == IMAGE_NT_OPTIONAL_HDR32_MAGIC &&
            nt.OptionalHeader.ImageBase == base && nt.OptionalHeader.AddressOfEntryPoint == entry - base &&
            nt.OptionalHeader.SizeOfImage && nt.OptionalHeader.SizeOfImage <= 0x1000000 &&
            !(nt.OptionalHeader.SizeOfImage & 0xFFF) && base <= UINT32_MAX - nt.OptionalHeader.SizeOfImage &&
            nt.OptionalHeader.SizeOfHeaders <= (uint32_t)file_size &&
            nt.OptionalHeader.SizeOfHeaders <= nt.OptionalHeader.SizeOfImage &&
            nt.OptionalHeader.NumberOfRvaAndSizes > IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT &&
            !nt.OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_TLS].VirtualAddress &&
            !nt.OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_TLS].Size &&
            !nt.OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT].VirtualAddress &&
            !nt.OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT].Size &&
            nt.FileHeader.NumberOfSections && nt.FileHeader.NumberOfSections <= 96 &&
            nt.FileHeader.NumberOfSections <= (file_size - ftell(file)) / sizeof(IMAGE_SECTION_HEADER);
    }
    for (unsigned i = 0; valid && i < nt.FileHeader.NumberOfSections; ++i) {
        IMAGE_SECTION_HEADER section;
        valid = fread(&section, sizeof(section), 1, file) == 1;
        if (!valid) break;
        uint32_t size = section.Misc.VirtualSize > section.SizeOfRawData ? section.Misc.VirtualSize : section.SizeOfRawData;
        valid = section.VirtualAddress < nt.OptionalHeader.SizeOfImage &&
            size <= nt.OptionalHeader.SizeOfImage - section.VirtualAddress &&
            (!section.PointerToRawData || (section.PointerToRawData <= (uint32_t)file_size &&
             section.SizeOfRawData <= (uint32_t)file_size - section.PointerToRawData));
    }
    fclose(file);
    if (!valid) { fprintf(stderr, "[void] Unsupported or invalid manual DLL PE: %s\n", path); return 0; }
    uint32_t span = nt.OptionalHeader.SizeOfImage;
    /* Reserve it ourselves: image_loader's MEM_COMMIT fallback must only touch our reservation. */
    uintptr_t end = (uintptr_t)base + span;
    for (uintptr_t address = base; address < end;) {
        MEMORY_BASIC_INFORMATION region;
        if (!VirtualQuery((void *)address, &region, sizeof(region)) || region.State != MEM_FREE) {
            fprintf(stderr, "[void] Manual DLL range occupied at %08X\n", (unsigned)address); return 0;
        }
        uintptr_t next = (uintptr_t)region.BaseAddress + region.RegionSize;
        if (next <= address) return 0;
        address = next;
    }
    void *reservation = VirtualAlloc((void *)(uintptr_t)base, span, MEM_RESERVE, PAGE_NOACCESS);
    if (reservation != (void *)(uintptr_t)base) {
        if (reservation) VirtualFree(reservation, 0, MEM_RELEASE);
        fprintf(stderr, "[void] Cannot reserve manual DLL at %08X\n", base); return 0;
    }
    uint32_t mapped = native32_map(path, base);
    DWORD previous;
    if (mapped != span || !VirtualProtect(reservation, span, PAGE_READWRITE, &previous)) {
        fprintf(stderr, "[void] Cannot map/protect manual DLL %s\n", path); return 0;
    }
    for (uintptr_t address = base; address < end;) {
        MEMORY_BASIC_INFORMATION region;
        if (!VirtualQuery((void *)address, &region, sizeof(region)) || region.State != MEM_COMMIT ||
            (region.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY))) return 0;
        uintptr_t next = (uintptr_t)region.BaseAddress + region.RegionSize;
        if (next <= address) return 0;
        address = next;
    }
    fprintf(stderr, "[void] Manual DLL mapped at %08X span=%08X; entire image NX; no Windows bootstrap\n", base, span);
    return span;
}


void void_restore_module(uint32_t base, uint32_t span, uint32_t counter, const void *snapshot)
{
    mstate *machine = (mstate *)TlsGetValue(g_mach_tls);
    int acquired = !machine || machine->depth == 0;
    if (acquired) mach_enter();
    uintptr_t end = (uintptr_t)base + span;
    for (uintptr_t address = base; address < end;) {
        MEMORY_BASIC_INFORMATION region;
        if (!VirtualQuery((void *)address, &region, sizeof(region)) || region.State != MEM_COMMIT ||
            region.Type != MEM_PRIVATE || (uintptr_t)region.AllocationBase != base ||
            region.Protect != PAGE_READWRITE) void_lift_trap(base, "Reload image is no longer the owned NX mapping");
        uintptr_t next = (uintptr_t)region.BaseAddress + region.RegionSize;
        if (next <= address) void_lift_trap(base, "Invalid reload mapping span");
        address = next;
    }
    if (counter < base || counter - base > span - 4 || MEM32(counter) != 0)
        void_lift_trap(base, "Reload requested before original CRT detach completed");
    memcpy((void *)(uintptr_t)base, snapshot, span);
    if (memcmp((void *)(uintptr_t)base, snapshot, span)) void_lift_trap(base, "Reload snapshot restoration failed");
    if (acquired) mach_leave();
}

uint32_t void_dll_event(uint32_t entry, uint32_t base, uint32_t reason, uint32_t reserved)
{
    DWORD last_error = GetLastError();
    recomp_func_t function = recomp_lookup(entry);
    if (!function) void_lift_trap(entry, "DLL entry is not lifted");
    mstate *machine = (mstate *)TlsGetValue(g_mach_tls);
    int acquired = !machine || machine->depth == 0;
    /* Borrow an existing claim instead of nesting it: native_bridge can then release depth 1. */
    if (acquired) mach_enter();
    regs_t saved;
    regs_save(&saved);
    uint32_t flags[] = {g_flag_k, g_flag_a, g_flag_b, g_flag_cf};
    uint32_t seh = MEM32(saved.fs);
    PUSH32(g_esp, reserved); PUSH32(g_esp, reason); PUSH32(g_esp, base); PUSH32(g_esp, RECOMP_RETADDR);
    function();
    uint32_t result = g_eax;
    int balanced = g_esp == saved.esp && MEM32(saved.fs) == seh;
    regs_load(&saved);
    g_flag_k = flags[0]; g_flag_a = flags[1]; g_flag_b = flags[2]; g_flag_cf = flags[3];
    if (acquired) mach_leave();
    SetLastError(last_error);
    if (!balanced) void_lift_trap(entry, "DLL entry did not restore its guest stack/SEH chain");
    return result;
}

/* Internal lifted CRT throws reach RaiseException instead of an imported
 * _CxxThrowException. Keep their unwind on the same guest chain. */
void void_raise_exception(void)
{
    uint32_t *args = (uint32_t *)(uintptr_t)(g_esp + 4);
    if (args[0] != 0xE06D7363u) {
        shim_RaiseException();
        return;
    }
    uint32_t parameters[3];
    SIZE_T read_count = 0;
    if (args[1] != EXCEPTION_NONCONTINUABLE || args[2] != 3 || !args[3] ||
        !ReadProcessMemory(GetCurrentProcess(), (const void *)(uintptr_t)args[3],
                           parameters, sizeof(parameters), &read_count) ||
        read_count != sizeof(parameters)) {
        fprintf(stderr, "[void-eh] Unsupported C++ record: flags=%08X count=%u arguments=%08X\n",
                args[1], args[2], args[3]);
        void_lift_trap(g_cur_func, "Unsupported MSVC C++ RaiseException record");
    }
    uint32_t magic = parameters[0], object = parameters[1], info = parameters[2];
    if (magic != EH_MAGIC_VC6 && magic != EH_MAGIC_VC7 && magic != EH_MAGIC_VC8) {
        fprintf(stderr, "[void-eh] Unsupported C++ magic: %08X\n", magic);
        void_lift_trap(g_cur_func, "Unsupported MSVC C++ exception format");
    }
    if (!info) object = t_cur_obj, info = t_cur_info; /* Same bare rethrow as eh32. */
    uint32_t throw_header[4];
    read_count = 0;
    if (!info || !ReadProcessMemory(GetCurrentProcess(), (const void *)(uintptr_t)info,
                                    throw_header, sizeof(throw_header), &read_count) ||
        read_count != sizeof(throw_header)) {
        void_lift_trap(g_cur_func, "Missing MSVC C++ throw metadata");
    }
    g_esp += 4; /* Remove only the RaiseException return word before dispatch. */
    dispatch(object, info); /* A matching catch resumes its owning body by longjmp. */
    fprintf(stderr, "[void-eh] Uncaught guest C++ exception: object=%08X info=%08X magic=%08X\n",
            object, info, magic);
    void_lift_trap(g_cur_func, "Uncaught guest MSVC C++ exception");
}
