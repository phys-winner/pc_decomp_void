/* Native replacements for the MSVC CRT's memcpy/memmove in every lifted module.
 *
 * Each image links its own copy (one body serves both names): an overlap
 * test, a backward copy for overlapping buffers, an SSE2 path for 128 bytes
 * and up, and jump tables for the trailing bytes. The lifter's table
 * analysis missed targets of the backward copy, so a rare overlapping move
 * trapped (PhysXCore 0x182CE260 -> 0x182CE548 after nine minutes on the
 * map); the body was also hot in GameModule. The C library's memmove does
 * the same job: cdecl (dst, src, count), returns dst, and leaves the
 * callee-saved registers alone.
 *
 * tools/build_android.py NATIVE_OVERRIDES lists the bodies (found by their
 * opening sequence: push ebp / mov ebp,esp / push edi / push esi /
 * mov esi,[ebp+0Ch] / mov ecx,[ebp+10h] / mov edi,[ebp+8] / ...). */
#include "host.h"
#include <string.h>

static void crt_memmove(void)
{
    uint32_t dst = MEM32(g_esp + 4), src = MEM32(g_esp + 8), count = MEM32(g_esp + 12);
    if (count) memmove(GPTR(dst), GPTR(src), count);
    g_eax = dst;
    g_esp += 4;   /* ret: the caller pops the arguments */
}

#define CRT_MEMMOVE(name) void name##_lifted(void); void name(void) { crt_memmove(); }
#ifdef VOID_RELEASE
/* Another release (tools/lift_release.py): its bodies, found by content. */
#include "release_overrides.h"
RELEASE_CRT_MEMMOVES(CRT_MEMMOVE)
#else
CRT_MEMMOVE(sub_0041C740)   /* Game.exe */
CRT_MEMMOVE(sub_004208C0)
CRT_MEMMOVE(sub_10128710)   /* GameModule.dll */
CRT_MEMMOVE(sub_101292D0)
CRT_MEMMOVE(sub_11074800)   /* Engine.dll */
CRT_MEMMOVE(sub_11076D60)
CRT_MEMMOVE(sub_12014140)   /* FS.dll */
CRT_MEMMOVE(sub_12015110)
CRT_MEMMOVE(sub_1300E530)   /* VFS.dll */
CRT_MEMMOVE(sub_1300F830)
CRT_MEMMOVE(sub_14047F80)   /* Sound.dll */
CRT_MEMMOVE(sub_140484C0)
CRT_MEMMOVE(sub_15006CE0)   /* Video.dll */
CRT_MEMMOVE(sub_150093F0)
CRT_MEMMOVE(sub_16124050)   /* RendererD3D.dll */
CRT_MEMMOVE(sub_1612A0F0)
CRT_MEMMOVE(sub_1700DCC0)   /* NxCharacter.dll */
CRT_MEMMOVE(sub_1700FD90)
CRT_MEMMOVE(sub_182CDDA0)   /* PhysXCore.dll */
CRT_MEMMOVE(sub_182CE260)
CRT_MEMMOVE(sub_190341E0)   /* PhysXCooking.dll */
CRT_MEMMOVE(sub_19034550)
#endif
