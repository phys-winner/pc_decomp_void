#define RECOMP_GENERATED_CODE
#include "recomp_types.h"
#include <assert.h>

uint32_t g_eax, g_ecx, g_edx, g_ebx, g_esp, g_ebp, g_esi, g_edi, g_fs_base, g_gs_base, g_cur_func;
ptrdiff_t g_mem_base;
double g_st[8]; int g_fp_top; uint16_t g_fpu_cw;
uint16_t g_seg_cs, g_seg_ds, g_seg_es, g_seg_fs, g_seg_gs, g_seg_ss;
uint64_t g_mm[8]; xmm_t g_xmm[8]; uint32_t g_mxcsr;
uint32_t g_icall_trace[ICALL_TRACE_SIZE], g_icall_from[ICALL_TRACE_SIZE], g_icall_trace_idx, g_icall_count;
const recomp_dispatch_entry_t recomp_dispatch_table[] = {{0, NULL}};
const uint32_t recomp_dispatch_count = 0;
void recomp_trace_enter(uint32_t va) { (void)va; }

static unsigned growth_calls;
void sub_16082390(void) {
    growth_calls++;
    g_eax = 0x11223344; g_ecx = 0x55667788; g_edx = 0x99aabbcc;
    g_flag_k = FK_CMP; g_flag_a = 11; g_flag_b = 7; g_flag_cf = 0;
    g_esp += 16;
}

/* EMITTED */

#undef eax
#undef ecx
#undef edx
#undef ebx
#undef esp
#undef ebp
#undef esi
#undef edi
#define GUEST_USER_TOP 0x7ffe0000u

static unsigned fallback_calls;
static int fallback_only;
static uint32_t fallback_state[8];
void sub_16082260_lifted(void) {
    fallback_calls++;
    if (fallback_only) {
        uint32_t regs[] = {g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi};
        assert(!memcmp(regs, fallback_state, sizeof regs));
    } else original_append();
}

/* NATIVE */

#define BASE 0x20000000u
#define SP (BASE + 0x7000u)
#define VECTOR (BASE + 0x100u)
#define BEGIN (BASE + 0x1000u)
static unsigned char memory[32768], original_memory[32768];
static uint32_t random_state = 0x8ac124efu;
static unsigned cases;

static uint32_t random32(void) {
    random_state ^= random_state << 13;
    random_state ^= random_state >> 17;
    random_state ^= random_state << 5;
    return random_state;
}

typedef struct {
    uint32_t regs[8], flags[4], mxcsr;
    xmm_t xmm[8]; uint64_t mm[8]; double st[8]; int top; uint16_t cw;
} snapshot;

static snapshot state(void) {
    snapshot s = {0};
    uint32_t regs[] = {g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi};
    uint32_t flags[] = {g_flag_k,g_flag_a,g_flag_b,g_flag_cf};
    memcpy(s.regs, regs, sizeof regs); memcpy(s.flags, flags, sizeof flags);
    memcpy(s.xmm, g_xmm, sizeof g_xmm); memcpy(s.mm, g_mm, sizeof g_mm);
    memcpy(s.st, g_st, sizeof g_st); s.top=g_fp_top; s.cw=g_fpu_cw; s.mxcsr=g_mxcsr;
    return s;
}

static void restore(snapshot s) {
    g_eax=s.regs[0]; g_ecx=s.regs[1]; g_edx=s.regs[2]; g_ebx=s.regs[3];
    g_esp=s.regs[4]; g_ebp=s.regs[5]; g_esi=s.regs[6]; g_edi=s.regs[7];
    g_flag_k=s.flags[0]; g_flag_a=s.flags[1]; g_flag_b=s.flags[2]; g_flag_cf=s.flags[3];
    memcpy(g_xmm,s.xmm,sizeof g_xmm); memcpy(g_mm,s.mm,sizeof g_mm);
    memcpy(g_st,s.st,sizeof g_st); g_fp_top=s.top; g_fpu_cw=s.cw; g_mxcsr=s.mxcsr;
}

static void initialize(unsigned used, unsigned capacity, uint32_t source) {
    for (unsigned i=0;i<sizeof memory;i++) memory[i]=(unsigned char)random32();
    g_eax=VECTOR; g_ecx=random32(); g_edx=random32(); g_ebx=random32();
    g_esp=SP; g_ebp=random32(); g_esi=random32(); g_edi=random32();
    g_flag_k=FK_EFLAGS; g_flag_a=random32() & 0x8d5u; g_flag_b=0; g_flag_cf=random32() & 1;
    for(unsigned i=0;i<8;i++) {
        for(unsigned j=0;j<4;j++) g_xmm[i].u32[j]=random32();
        g_mm[i]=((uint64_t)random32()<<32) | random32(); g_st[i]=(double)(int32_t)random32();
    }
    g_fp_top=3; g_fpu_cw=0x37f; g_mxcsr=0x1f80;
    MEM32(VECTOR+4)=BEGIN; MEM32(VECTOR+8)=BEGIN+used*12; MEM32(VECTOR+12)=BEGIN+capacity*12;
    MEM32(SP)=0x30000000; MEM32(SP+4)=source;
    fallback_calls=growth_calls=0; fallback_only=0;
}

static void differential(int expect_fallback) {
    snapshot before=state();
    unsigned char initial[sizeof memory]; memcpy(initial,memory,sizeof memory);
    original_append(); snapshot wanted=state(); unsigned expected_growth=growth_calls;
    memcpy(original_memory,memory,sizeof memory);
    restore(before); memcpy(memory,initial,sizeof memory); growth_calls=0;
    sub_16082260(); snapshot observed=state();
    assert(fallback_calls==(unsigned)expect_fallback && growth_calls==expected_growth);
    assert(!memcmp(&wanted,&observed,sizeof wanted));
    assert(!memcmp(original_memory,memory,sizeof memory));
    cases++;
}

static void rejected(void) {
    snapshot before=state();
    memcpy(original_memory,memory,sizeof memory);
    memcpy(fallback_state,before.regs,sizeof fallback_state); fallback_only=1;
    sub_16082260(); snapshot observed=state();
    assert(fallback_calls==1);
    assert(!memcmp(&before,&observed,sizeof before));
    assert(!memcmp(original_memory,memory,sizeof memory));
    cases++;
}

int main(void) {
    g_mem_base=(ptrdiff_t)((uint32_t)(uintptr_t)memory-BASE);
    for (unsigned used=0;used<20;used++) {
        for(unsigned remaining=1;remaining<=3;remaining++) {
            for(int delta=-11;delta<=11;delta++) {
                initialize(used,used+remaining,BEGIN+used*12+delta);
                differential(0);
            }
            for(unsigned alignment=0;alignment<4;alignment++) {
                initialize(used,used+remaining,BASE+0x4000+alignment); differential(0);
                initialize(used,used+remaining,SP+8+alignment); differential(0);
            }
        }
        initialize(used,used,BASE+0x4000); differential(1);
    }
    initialize(0,0,BASE+0x4000); MEM32(VECTOR+4)=MEM32(VECTOR+8)=MEM32(VECTOR+12)=0; differential(1);
    initialize(1,3,BASE+0x4000); MEM32(VECTOR+8)=BEGIN+11; differential(1);
    initialize(1,3,BASE+0x4000); MEM32(VECTOR+12)=BEGIN+35; differential(1);
    initialize(1,3,BASE+0x4000); MEM32(VECTOR+8)=BEGIN-1; rejected();
    initialize(1,3,BASE+0x4000); MEM32(VECTOR+12)=BEGIN+11; rejected();
    initialize(1,3,0); rejected();
    initialize(1,3,GUEST_USER_TOP-11); rejected();
    initialize(1,3,SP-24); rejected();
    initialize(1,3,BASE+0x4000); MEM32(VECTOR+4)=SP-12; MEM32(VECTOR+8)=SP; MEM32(VECTOR+12)=SP+24; rejected();
    initialize(1,3,BASE+0x4000); MEM32(VECTOR+4)=VECTOR; MEM32(VECTOR+8)=VECTOR+12; MEM32(VECTOR+12)=VECTOR+36; rejected();
    initialize(1,3,BASE+0x4000); MEM32(VECTOR+12)=0xffffffffu; rejected();
    initialize(1,3,BASE+0x4000); g_eax=0; rejected();
    initialize(1,3,BASE+0x4000); g_eax=GUEST_USER_TOP-15; rejected();
    initialize(1,3,BASE+0x4000); g_esp=4; rejected();
    initialize(1,3,BASE+0x4000); g_esp=GUEST_USER_TOP-7; rejected();
    initialize(1,3,BASE+0x4000); void_renderer_native_enable(0); differential(1);
    void_renderer_native_enable(1);
    initialize(1,3,BASE+0x4000); differential(0);
    printf("PASS triangle append cases=%u: emitted body/helper, whole memory, registers/flags/XMM/x87, growth and invalid-layout fallback\n",cases);
    return 0;
}
