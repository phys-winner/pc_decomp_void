/* Project hooks the generated code calls by name (tools/lift_game.py,
 * tools/lift_media.py), with the Windows host's semantics. */
#include "host.h"
#ifdef VOID_RELEASE
#include "release_overrides.h"
#endif
#ifndef SOUND_BULK_READ_VA
#define SOUND_BULK_READ_VA 0x14061270u   /* the 2009 Sound.dll */
#endif

/* FirstRun gate: Android has no external Config.exe; settings come from the
 * private profile, so the native configuration is always "ready". */
int void_native_config_ready(void) { return 1; }

/* Vorbis requests size * nmemb bytes; the shipping adapter ignores nmemb.
 * Port of native/void_runtime.c void_sound_bulk_read. */
void void_sound_bulk_read(void)
{
    const uint32_t callback = SOUND_BULK_READ_VA;
    g_cur_func = callback;
    uint32_t entry = g_esp;
    uint32_t buffer = MEM32(entry + 4), size = MEM32(entry + 8), count = MEM32(entry + 12);
    if (!size || !count || size > UINT32_MAX / count) {
        g_eax = 0;
        g_esp = entry + 4;
        return;
    }
    uint32_t bytes = size * count;
    uint32_t file = MEM32(MEM32(entry + 16));
    uint32_t target = MEM32(MEM32(file) + 0x24);
    recomp_func_t read = void_resolve(target);
    g_icall_trace[g_icall_trace_idx & (ICALL_TRACE_SIZE - 1)] = target;
    g_icall_from[g_icall_trace_idx & (ICALL_TRACE_SIZE - 1)] = callback;
    ++g_icall_trace_idx;
    g_ecx = file;
    PUSH32(g_esp, bytes);
    PUSH32(g_esp, buffer);
    PUSH32(g_esp, RECOMP_RETADDR);
    read();
    g_cur_func = callback;
    if (g_esp != entry || g_eax > bytes) void_lift_trap(callback, "invalid Sound stream read count or stack cleanup");
    g_eax /= size;
    g_esp = entry + 4;
}
