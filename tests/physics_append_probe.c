#define RECOMP_GENERATED_CODE
#include "recomp_types.h"
#include <assert.h>
uint32_t g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi,g_fs_base,g_gs_base,g_cur_func;
ptrdiff_t g_mem_base;
double g_st[8]; int g_fp_top; uint16_t g_fpu_cw;
uint16_t g_seg_cs,g_seg_ds,g_seg_es,g_seg_fs,g_seg_gs,g_seg_ss;
uint64_t g_mm[8]; xmm_t g_xmm[8]; uint32_t g_mxcsr;
uint32_t g_icall_trace[ICALL_TRACE_SIZE],g_icall_from[ICALL_TRACE_SIZE],g_icall_trace_idx,g_icall_count;
const recomp_dispatch_entry_t recomp_dispatch_table[]={{0,NULL}};
const uint32_t recomp_dispatch_count=0;
void recomp_trace_enter(uint32_t va) {(void)va;}
void (*recomp_lookup_manual(uint32_t va))(void) {(void)va;assert(0);return NULL;}
recomp_func_t recomp_lookup(uint32_t va) {(void)va;assert(0);return NULL;}
recomp_func_t recomp_lookup_import(uint32_t va) {(void)va;assert(0);return NULL;}
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
static int fallback_calls;
void sub_181802C0_lifted(void) {fallback_calls++;}
void sub_110014F0_lifted(void) {assert(0);}
int void_renderer_append12(int preserve_ecx) {(void)preserve_ecx;assert(0);return 0;}
/* NATIVE */
#define BASE 0x20000000u
#define SP (BASE+0x7000u)
#define OBJECT (BASE+0x100u)
#define BEGIN (BASE+0x1000u)
static unsigned char memory[32768],initial[32768],wanted[32768];
static uint32_t random_state=0xa1287bcdu;
static uint32_t random32(void) {random_state^=random_state<<13;random_state^=random_state>>17;random_state^=random_state<<5;return random_state;}
static unsigned cases;
typedef struct {uint32_t regs[8],flags[4],mxcsr; xmm_t xmm[8];uint64_t mm[8];double st[8];int64_t shadow[8];int top;uint16_t cw;} snapshot;
static snapshot state(void) {snapshot s={0};uint32_t r[]={g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi},f[]={g_flag_k,g_flag_a,g_flag_b,g_flag_cf};memcpy(s.regs,r,sizeof r);memcpy(s.flags,f,sizeof f);memcpy(s.xmm,g_xmm,sizeof g_xmm);memcpy(s.mm,g_mm,sizeof g_mm);memcpy(s.st,g_st,sizeof g_st);memcpy(s.shadow,g_st_i64,sizeof g_st_i64);s.top=g_fp_top;s.cw=g_fpu_cw;s.mxcsr=g_mxcsr;return s;}
static void restore(snapshot s) {g_eax=s.regs[0];g_ecx=s.regs[1];g_edx=s.regs[2];g_ebx=s.regs[3];g_esp=s.regs[4];g_ebp=s.regs[5];g_esi=s.regs[6];g_edi=s.regs[7];g_flag_k=s.flags[0];g_flag_a=s.flags[1];g_flag_b=s.flags[2];g_flag_cf=s.flags[3];memcpy(g_xmm,s.xmm,sizeof g_xmm);memcpy(g_mm,s.mm,sizeof g_mm);memcpy(g_st,s.st,sizeof g_st);memcpy(g_st_i64,s.shadow,sizeof g_st_i64);g_fp_top=s.top;g_fpu_cw=s.cw;g_mxcsr=s.mxcsr;}
static void initialize(unsigned used,unsigned remaining,uint32_t first,uint32_t second) {
    for(unsigned i=0;i<sizeof memory;i++) memory[i]=(unsigned char)random32();
    g_eax=random32();g_ecx=OBJECT;g_edx=random32();g_ebx=random32();g_esp=SP;g_ebp=random32();g_esi=random32();g_edi=random32();
    g_flag_k=FK_EFLAGS;g_flag_a=random32()&0x8d5u;g_flag_b=0;g_flag_cf=random32()&1;
    for(unsigned i=0;i<8;i++) {for(unsigned j=0;j<4;j++)g_xmm[i].u32[j]=random32();g_mm[i]=((uint64_t)random32()<<32)|random32();g_st[i]=(double)(int32_t)random32();g_st_i64[i]=(int64_t)g_mm[i];}
    g_fp_top=3;g_fpu_cw=0x37f;g_mxcsr=0x1f80;
    MEM32(OBJECT+20)=BEGIN;MEM32(OBJECT+24)=BEGIN+used*28;MEM32(OBJECT+28)=BEGIN+(used+remaining)*28;
    MEM32(SP)=0x30000000;MEM32(SP+4)=first;MEM32(SP+8)=second;MEM32(SP+12)=random32();
    for(unsigned i=0;i<3;i++){MEM32(first+i*4)=random32()&0xfeffffffu;MEM32(second+i*4)=random32()&0xfeffffffu;}
    fallback_calls=0;
}
static void differential(void) {
    snapshot before=state();memcpy(initial,memory,sizeof memory);original_append();snapshot expected=state();memcpy(wanted,memory,sizeof memory);
    restore(before);memcpy(memory,initial,sizeof memory);sub_181802C0();snapshot actual=state();
    assert(!fallback_calls);assert(!memcmp(&expected,&actual,sizeof actual));assert(!memcmp(wanted,memory,sizeof memory));cases++;
}
static void rejected(void) {snapshot before=state();memcpy(initial,memory,sizeof memory);sub_181802C0();snapshot after=state();assert(fallback_calls==1);assert(!memcmp(&before,&after,sizeof before));assert(!memcmp(initial,memory,sizeof memory));cases++;}
int main(void) {
    g_mem_base=(ptrdiff_t)((uint32_t)(uintptr_t)memory-BASE);
    for(unsigned used=0;used<30;used++) for(int delta=-11;delta<=11;delta++) {
        initialize(used,1,BASE+0x4000,BEGIN+used*28+delta);differential();
        initialize(used,2,BEGIN+used*28+delta,BASE+0x4000);differential();
    }
    for(unsigned alignment=0;alignment<4;alignment++) {initialize(0,1,BASE+0x4000+alignment,BASE+0x5000+alignment);differential();}
    static uint32_t special[]={0,0x80000000u,1,0x807fffffu,0x7f7fffffu,0xff7fffffu};
    for(unsigned i=0;i<sizeof special/sizeof special[0];i++) {initialize(1,1,BASE+0x4000,BASE+0x5000);MEM32(BASE+0x4000)=special[i];differential();}
    initialize(1,0,BASE+0x4000,BASE+0x5000);rejected();
    initialize(1,1,BASE+0x4000,BASE+0x5000);MEM32(BASE+0x4000)=0x7f800000u;rejected();
    initialize(1,1,BASE+0x4000,BASE+0x5000);MEM32(BASE+0x5000)=0x7f812345u;rejected();
    initialize(1,1,BASE+0x4000,BASE+0x5000);MEM32(OBJECT+28)=BEGIN+55;rejected();
    initialize(1,1,BASE+0x4000,BASE+0x5000);MEM32(SP+4)=SP-28;rejected();
    initialize(1,1,BASE+0x4000,BASE+0x5000);MEM32(SP+8)=0;rejected();
    initialize(1,1,BASE+0x4000,BASE+0x5000);void_physics_native_enable(0);rejected();
    printf("PASS debug-line append %u cases: complete memory, registers/flags, XMM/x87/shadows, aliasing, finite boundaries, growth/invalid fallback\n",cases);return 0;
}
