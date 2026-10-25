/* msvcrt.dll shims for the lifted D3DX HLSL compiler (tools/lift_d3dx.py).
 *
 * The game's own DLLs link the CRT statically, so this file exists only for
 * d3dxcompiler_void.dll, which Microsoft built against msvcrt.dll (/MD) and so
 * imports the C runtime. Only what the shader-compiler subtree reaches is here
 * (textures, meshes, image codecs and their setjmp/stdio are not lifted). The
 * compiler reports its errors through C++ exceptions, which the host EH drives
 * already (android/host/eh.c _CxxThrowException); __CxxFrameHandler is only the
 * handler-stub target the fs:[0] walk reads, never actually called.
 *
 * Calling conventions: the CRT is __cdecl (the caller pops arguments), so the
 * shims pop only the return address (CDECL_EXPORT). The _CIxxx math helpers
 * take and return their operands on the x87 stack, and floor/ceil/_finite/...
 * take a double in the stack slots and return it in ST(0); those manage the
 * stack themselves (RAW_EXPORT) over the guest x87 file (g_st/g_fp_top). */
#define _GNU_SOURCE
#include "host.h"
#include <ctype.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

#define CRT "msvcrt.dll"

/* The 8-byte double cdecl passes in two stack dwords, low word first. */
static double arg_double(int i) { uint64_t bits = (uint64_t)ARG(i) | ((uint64_t)ARG(i + 1) << 32); double v; memcpy(&v, &bits, 8); return v; }

/* ------------------------------------------------------------ memory */
CDECL_EXPORT(CRT, memcpy) { uint32_t d = ARG(0); if (ARG(2)) memcpy(GPTR(d), GPTR(ARG(1)), ARG(2)); return d; }
CDECL_EXPORT(CRT, memmove) { uint32_t d = ARG(0); if (ARG(2)) memmove(GPTR(d), GPTR(ARG(1)), ARG(2)); return d; }
CDECL_EXPORT(CRT, memset) { uint32_t d = ARG(0); if (ARG(2)) memset(GPTR(d), (int)ARG(1), ARG(2)); return d; }
CDECL_EXPORT(CRT, malloc) { return void_galloc(ARG(0)); }
CDECL_EXPORT(CRT, calloc) { uint32_t n = ARG(0) * ARG(1); uint32_t p = void_galloc(n); return p; }   /* void_galloc zeroes */
CDECL_EXPORT(CRT, free) { void_gfree(ARG(0)); return 0; }
CDECL_EXPORT(CRT, realloc) { return void_heap_realloc(void_process_heap(), ARG(0), ARG(1), 0, 0); }
/* operator new(uint) / operator delete(void*): the CRT's, not the game's. */
CDECL_EXPORT_AS(CRT, op_new, "??2@YAPAXI@Z") { return void_galloc(ARG(0) ? ARG(0) : 1); }
CDECL_EXPORT_AS(CRT, op_delete, "??3@YAXPAX@Z") { void_gfree(ARG(0)); return 0; }

/* ------------------------------------------------------------ strings */
CDECL_EXPORT(CRT, strchr) { const char *s = (const char *)GPTR(ARG(0)); const char *p = strchr(s, (int)ARG(1)); return p ? ARG(0) + (uint32_t)(p - s) : 0; }
CDECL_EXPORT(CRT, strncmp) { return (uint32_t)strncmp((const char *)GPTR(ARG(0)), (const char *)GPTR(ARG(1)), ARG(2)); }
CDECL_EXPORT(CRT, _stricmp) { return (uint32_t)strcasecmp((const char *)GPTR(ARG(0)), (const char *)GPTR(ARG(1))); }
CDECL_EXPORT(CRT, _strnicmp) { return (uint32_t)strncasecmp((const char *)GPTR(ARG(0)), (const char *)GPTR(ARG(1)), ARG(2)); }
CDECL_EXPORT(CRT, _strdup) { const char *s = (const char *)GPTR(ARG(0)); return void_gstrdup(s); }
CDECL_EXPORT(CRT, atoi) { return (uint32_t)atoi((const char *)GPTR(ARG(0))); }
CDECL_EXPORT(CRT, atol) { return (uint32_t)atol((const char *)GPTR(ARG(0))); }

/* ctype in the invariant "C" locale (the compiler never leaves it). */
CDECL_EXPORT(CRT, isalnum) { return (uint32_t)isalnum((int)(ARG(0) & 0xFF)); }
CDECL_EXPORT(CRT, isalpha) { return (uint32_t)isalpha((int)(ARG(0) & 0xFF)); }
CDECL_EXPORT(CRT, isdigit) { return (uint32_t)isdigit((int)(ARG(0) & 0xFF)); }
CDECL_EXPORT(CRT, isspace) { return (uint32_t)isspace((int)(ARG(0) & 0xFF)); }
CDECL_EXPORT(CRT, isxdigit) { return (uint32_t)isxdigit((int)(ARG(0) & 0xFF)); }
CDECL_EXPORT(CRT, tolower) { return (uint32_t)tolower((int)(ARG(0) & 0xFF)); }
CDECL_EXPORT(CRT, toupper) { return (uint32_t)toupper((int)(ARG(0) & 0xFF)); }
CDECL_EXPORT(CRT, isleadbyte) { return 0; }

/* ------------------------------------------------------- x87 math (_CIxxx) */
/* The _st/_fp_top macros are for generated code; host code uses the x87 file
 * helpers on the globals directly. */
#define FP_POP()    fp_pop_impl(g_st, &g_fp_top)
#define FP_PUSH(v)  fp_push_impl(g_st, &g_fp_top, (v))
/* One operand in ST(0), result in ST(0); no stack arguments. */
#define FP1(name, expr) RAW_EXPORT(CRT, name) { double x = FP_POP(); FP_PUSH(expr); g_esp += 4u; }
/* ST(1) = first pushed (a), ST(0) = second pushed (b); result in ST(0). */
#define FP2(name, expr) RAW_EXPORT(CRT, name) { double b = FP_POP(); double a = FP_POP(); FP_PUSH(expr); g_esp += 4u; }
FP1(_CIsqrt, sqrt(x))
FP1(_CIsin, sin(x))
FP1(_CIcos, cos(x))
FP1(_CItan, tan(x))
FP1(_CIexp, exp(x))
FP1(_CIlog, log(x))
FP1(_CIasin, asin(x))
FP1(_CIacos, acos(x))
FP1(_CIatan, atan(x))
FP1(_CIsinh, sinh(x))
FP1(_CIcosh, cosh(x))
FP1(_CItanh, tanh(x))
FP2(_CIpow, pow(a, b))
FP2(_CIatan2, atan2(a, b))
FP2(_CIfmod, fmod(a, b))

/* double arg in the stack slots, result in ST(0). */
#define FD1(name, expr) RAW_EXPORT(CRT, name) { double x = arg_double(0); FP_PUSH(expr); g_esp += 4u; }
FD1(floor, floor(x))
FD1(ceil, ceil(x))
/* double arg, int result in EAX. */
CDECL_EXPORT(CRT, _finite) { return (uint32_t)(isfinite(arg_double(0)) ? 1 : 0); }
CDECL_EXPORT(CRT, _isnan) { return (uint32_t)(isnan(arg_double(0)) ? 1 : 0); }
CDECL_EXPORT(CRT, _fpclass) {
    double v = arg_double(0);
    if (isnan(v)) return 0x0002;                 /* _FPCLASS_QNAN */
    if (isinf(v)) return v < 0 ? 0x0004 : 0x0200;/* _FPCLASS_NINF / _FPCLASS_PINF */
    if (v == 0) return signbit(v) ? 0x0020 : 0x0040;
    if (v < 0) return 0x0008;                    /* _FPCLASS_NN */
    return 0x0100;                               /* _FPCLASS_PN */
}

/* atof is __cdecl with a char* argument, returning a double in ST(0). */
RAW_EXPORT(CRT, atof) { double v = atof((const char *)GPTR(ARG(0))); FP_PUSH(v); g_esp += 4u; }

/* -------------------------------------------------------- FP control word */
/* The compiler sets precision/rounding around constant folding. The host's
 * doubles are already 53-bit round-to-nearest (the MSVC default), so the word
 * is tracked and returned but the host mode is not changed. */
static uint32_t fp_control = 0x9001F;   /* _CW_DEFAULT (x86 MSVCRT) */
CDECL_EXPORT(CRT, _controlfp) { uint32_t mask = ARG(1); fp_control = (fp_control & ~mask) | (ARG(0) & mask); return fp_control; }
CDECL_EXPORT(CRT, _clearfp) { return 0; }

/* ------------------------------------------------------------ locale */
static uint32_t locale_c;
CDECL_EXPORT(CRT, setlocale) { if (!locale_c) locale_c = void_gstrdup("C"); return locale_c; }
CDECL_EXPORT(CRT, _errno) { static uint32_t slot; if (!slot) slot = void_galloc(4); return slot; }

/* ------------------------------------------------------------ qsort */
/* num records of `size` bytes in guest memory, ordered by a guest __cdecl
 * comparator. Shell sort: no recursion, correct for any total order (the
 * compiler's keys are distinct, so equal-key stability does not arise). */
CDECL_EXPORT(CRT, qsort) {
    uint32_t base = ARG(0), num = ARG(1), size = ARG(2), cmp = ARG(3);
    if (num < 2 || !size) return 0;
    uint8_t tmp[256];
    if (size > sizeof tmp) { void_log("[msvcrt] qsort element %u too large", size); return 0; }
    for (uint32_t gap = num / 2; gap > 0; gap /= 2) {
        for (uint32_t i = gap; i < num; ++i) {
            memcpy(tmp, GPTR(base + i * size), size);
            uint32_t temp = void_galloc(size);
            memcpy(GPTR(temp), tmp, size);
            uint32_t j = i;
            while (j >= gap) {
                uint32_t a[2] = {base + (j - gap) * size, temp};
                if ((int32_t)void_call_guest(cmp, 2, a, 0) <= 0) break;
                memmove(GPTR(base + j * size), GPTR(base + (j - gap) * size), size);
                j -= gap;
            }
            memcpy(GPTR(base + j * size), tmp, size);
            void_gfree(temp);
        }
    }
    return 0;
}

/* ------------------------------------------------------- _vsnprintf */
/* _vsnprintf(buffer, count, format, va_list). The CRT is the compiler's only
 * formatter (StringCch*PrintfA forward here), used for error and disassembly
 * text. The arguments come from the guest va_list pointer. */
static int format_guest(char *out, size_t cap, const char *fmt, uint32_t va)
{
    size_t n = 0;
    while (*fmt) {
        if (*fmt != '%') { if (n + 1 < cap) out[n] = *fmt; ++n; ++fmt; continue; }
        const char *start = fmt++;
        char spec[32]; size_t sl = 0; spec[sl++] = '%';
        while (*fmt && strchr("-+ #0", *fmt)) { if (sl < sizeof spec - 1) spec[sl++] = *fmt; ++fmt; }
        while (*fmt && (isdigit((unsigned char)*fmt) || *fmt == '*')) { if (sl < sizeof spec - 1) spec[sl++] = *fmt; ++fmt; }
        if (*fmt == '.') { if (sl < sizeof spec - 1) spec[sl++] = *fmt; ++fmt;
            while (*fmt && (isdigit((unsigned char)*fmt) || *fmt == '*')) { if (sl < sizeof spec - 1) spec[sl++] = *fmt; ++fmt; } }
        int wide = 0, i64 = 0;
        while (*fmt && strchr("hlLwIz", *fmt)) {
            if (fmt[0] == 'I' && fmt[1] == '6' && fmt[2] == '4') { i64 = 1; fmt += 3; continue; }
            if (fmt[0] == 'I' && (fmt[1] == '3' || fmt[1] == 'x')) { fmt += 2; continue; }
            if (*fmt == 'l' && fmt[1] == 'l') { i64 = 1; fmt += 2; continue; }
            if (*fmt == 'w') wide = 1;
            ++fmt;
        }
        char conv = *fmt ? *fmt++ : 0;
        char piece[512];
        piece[0] = 0;
        if (conv == '%') { if (n + 1 < cap) out[n] = '%'; ++n; continue; }
        if (!conv) break;
        spec[sl++] = (conv == 'S') ? 's' : (conv == 'C') ? 'c' : conv;
        spec[sl] = 0;
        switch (conv) {
        case 'd': case 'i': case 'u': case 'x': case 'X': case 'o': case 'c': {
            if (i64) { uint64_t v = (uint64_t)MEM32(va) | ((uint64_t)MEM32(va + 4) << 32); va += 8;
                char q[40]; size_t b = sl - 1; memcpy(q, spec, b); q[b++] = 'l'; q[b++] = 'l'; q[b++] = conv; q[b] = 0;
                snprintf(piece, sizeof piece, q, (unsigned long long)v); }
            else { uint32_t v = MEM32(va); va += 4; snprintf(piece, sizeof piece, spec, v); }
            break; }
        case 'p': { uint32_t v = MEM32(va); va += 4; snprintf(piece, sizeof piece, "%08X", v); break; }
        case 'e': case 'E': case 'f': case 'F': case 'g': case 'G': case 'a': case 'A': {
            uint64_t bits = (uint64_t)MEM32(va) | ((uint64_t)MEM32(va + 4) << 32); va += 8;
            double d; memcpy(&d, &bits, 8); snprintf(piece, sizeof piece, spec, d); break; }
        case 's': case 'S': {
            uint32_t p = MEM32(va); va += 4;
            if (!p) strcpy(piece, "(null)");
            else if (conv == 'S' || wide) { char *u = void_wstr_utf8(p); snprintf(piece, sizeof piece, "%s", u ? u : ""); free(u); }
            else snprintf(piece, sizeof piece, spec, (const char *)GPTR(p));
            break; }
        default:
            memcpy(piece, start, (size_t)(fmt - start)); piece[fmt - start] = 0;
        }
        for (const char *q = piece; *q; ++q) { if (n + 1 < cap) out[n] = *q; ++n; }
    }
    if (cap) out[n < cap ? n : cap - 1] = 0;
    return (int)n;
}

CDECL_EXPORT(CRT, _vsnprintf) {
    uint32_t buf = ARG(0), count = ARG(1);
    char tmp[4096];
    int n = format_guest(tmp, sizeof tmp, (const char *)GPTR(ARG(2)), ARG(3));
    uint32_t copy = (uint32_t)n;
    if (count != 0xFFFFFFFFu && copy > count) copy = count;
    if (copy) memcpy(GPTR(buf), tmp, copy);
    if (count == 0xFFFFFFFFu || (uint32_t)n < count) MEM8(buf + (uint32_t)n) = 0;
    return (uint32_t)n;
}

/* --------------------------------------------------------- CRT startup/EH */
/* _initterm(first, last): run each non-null __cdecl initializer in [first,last). */
CDECL_EXPORT(CRT, _initterm) {
    for (uint32_t p = ARG(0); p < ARG(1); p += 4) { uint32_t fn = MEM32(p); if (fn) void_call_guest(fn, 0, NULL, 0); }
    return 0;
}
/* The CRT's global locks: the compiler runs single-threaded under the guest
 * machine lock, so these are no-ops. */
CDECL_EXPORT(CRT, _lock) { return 0; }
CDECL_EXPORT(CRT, _unlock) { return 0; }
/* atexit/onexit registration: the module is detached wholesale, so recording
 * a handler and returning it (success) is enough. */
CDECL_EXPORT(CRT, _onexit) { return ARG(0); }
CDECL_EXPORT(CRT, __dllonexit) { return ARG(0); }
CDECL_EXPORT(CRT, _XcptFilter) { return 0; }            /* EXCEPTION_CONTINUE_SEARCH */
CDECL_EXPORT(CRT, _amsg_exit) { void_log("[msvcrt] _amsg_exit(%u)", ARG(0)); void_lift_trap(g_cur_func, "CRT fatal error"); return 0; }
CDECL_EXPORT(CRT, _purecall) { void_lift_trap(g_cur_func, "pure virtual call"); return 0; }
/* type_info::~type_info (thiscall, no args): a no-op destructor. */
RAW_EXPORT(CRT, type_info_dtor) { g_eax = g_ecx; g_esp += 4u; }
static const void_shim type_info_dtor_alias VOID_SHIM_SECTION = { CRT, "??1type_info@@UAE@XZ", 0, type_info_dtor_entry };
/* The handler-stub target the fs:[0] walk recognises; the host EH never calls it. */
RAW_EXPORT(CRT, __CxxFrameHandler) { void_lift_trap(g_cur_func, "__CxxFrameHandler reached (host EH should drive)"); }
