/* Keep the pinned register model; published flags belong to each guest thread. */
#ifndef VOID_RECOMP_TYPES_H
#define VOID_RECOMP_TYPES_H

#include "../reference/pcrecomp/runtime/recomp32/recomp_types.h"

/* Only the existing condition encoding is shared; this is not a full x87 SW. */
RECOMP_SHARED_DATA int void_fpu_cmp = 1;
void void_fpu_remainder(uint32_t address, int nearest);
#ifdef RECOMP_GENERATED_CODE
#define _fpu_cmp void_fpu_cmp
#endif

#if defined(_MSC_VER)
#define VOID_FLAG_STORAGE __declspec(selectany) __declspec(thread)
#elif defined(__cplusplus)
#define VOID_FLAG_STORAGE __attribute__((weak)) thread_local
#else
#define VOID_FLAG_STORAGE __attribute__((weak)) _Thread_local
#endif

VOID_FLAG_STORAGE uint32_t void_flag_k = 0;
VOID_FLAG_STORAGE uint32_t void_flag_a = 0;
VOID_FLAG_STORAGE uint32_t void_flag_b = 0;
VOID_FLAG_STORAGE uint32_t void_flag_cf = 0;

/* The original transfer macros expand these names at use, after this redirect. */
#define g_flag_k void_flag_k
#define g_flag_a void_flag_a
#define g_flag_b void_flag_b
#define g_flag_cf void_flag_cf

#undef VOID_FLAG_STORAGE
#endif
