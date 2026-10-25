#define RECOMP_GENERATED_CODE
#include "runtime-fixture.h"
#include <assert.h>

uint32_t g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi,g_fs_base,g_gs_base,g_cur_func;
ptrdiff_t g_mem_base;
double g_st[8]; int64_t g_st_i64[8]; int g_fp_top; uint16_t g_fpu_cw;
uint16_t g_seg_cs,g_seg_ds,g_seg_es,g_seg_fs,g_seg_gs,g_seg_ss;
uint64_t g_mm[8]; xmm_t g_xmm[8]; uint32_t g_mxcsr;
uint32_t g_flag_k,g_flag_a,g_flag_b,g_flag_cf; int void_fpu_cmp;
uint32_t g_icall_trace[ICALL_TRACE_SIZE],g_icall_from[ICALL_TRACE_SIZE],g_icall_trace_idx,g_icall_count;
uint32_t g_enter_trace[RECOMP_ENTER_SIZE],g_enter_idx,g_backedges;
void (*recomp_yield_hook)(void);
const recomp_dispatch_entry_t recomp_dispatch_table[]={{0,NULL}};
const uint32_t recomp_dispatch_count=0;

#define BASE 0x20000000u
#define SP (BASE+0xf000u)
#define CTX (BASE+0x1000u)
#define TREE (BASE+0x2000u)
#define LEAVES (BASE+0x3000u)
#define RECORDS (BASE+0x4000u)
#define COUNTS (BASE+0x5000u)
#define QUERY (BASE+0x6000u)
#define BOX (BASE+0x7000u)
#define OBB (BASE+0x8000u)
static unsigned char memory[65536],initial_memory[65536],wanted_memory[65536];
static void *guest_address(uint32_t va) {
    /* CONSTANTS */
    assert(va>=BASE && va<BASE+sizeof memory);
    return memory+(va-BASE);
}
static int enabled;
int void_renderer_region_enabled(void) { return enabled; }
/* A shared opaque boundary, exercising register/FP reload from nested RGBE.
 * Both compared paths call the actual emitted RGBE routine around this stub. */
void sub_16125DCB(void) {
    double value=*(double*)ADDR(g_esp+4); int exponent=(int32_t)MEM32(g_esp+12);
    fp_push(ldexp(value,exponent)); g_eax=0x12345678; g_ecx=0x23456789; g_edx=0x3456789a;
    g_flag_k=FK_ADD; g_flag_a=123; g_flag_b=456; g_flag_cf=0; g_esp+=4;
}
/* HELPERS */
/* ORIGINAL */

#undef eax
#undef ecx
#undef edx
#undef ebx
#undef esp
#undef ebp
#undef esi
#undef edi
static uint32_t random_state=0x9c72ac41;
static uint32_t random32(void) {
    random_state^=random_state<<13; random_state^=random_state>>17; random_state^=random_state<<5;
    return random_state;
}
static float random_float(void) { return (int32_t)random32()/16777216.f; }
static void put(uint32_t va,float value) { memcpy(guest_address(va),&value,4); }
typedef struct {
    uint32_t regs[8],flags[4],current,backedges,enter,trace[RECOMP_ENTER_SIZE];
    xmm_t xmm[8]; double st[8]; int64_t shadows[8]; int top;
} state;
static state capture(void) {
    state s={0};
    uint32_t r[]={g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi};
    uint32_t f[]={g_flag_k,g_flag_a,g_flag_b,g_flag_cf};
    memcpy(s.regs,r,sizeof r); memcpy(s.flags,f,sizeof f); memcpy(s.xmm,g_xmm,sizeof g_xmm);
    memcpy(s.st,g_st,sizeof g_st); memcpy(s.shadows,g_st_i64,sizeof g_st_i64);
    memcpy(s.trace,g_enter_trace,sizeof g_enter_trace);
    s.current=g_cur_func; s.backedges=g_backedges; s.enter=g_enter_idx; s.top=g_fp_top; return s;
}
static void restore(state s) {
    g_eax=s.regs[0];g_ecx=s.regs[1];g_edx=s.regs[2];g_ebx=s.regs[3];
    g_esp=s.regs[4];g_ebp=s.regs[5];g_esi=s.regs[6];g_edi=s.regs[7];
    g_flag_k=s.flags[0];g_flag_a=s.flags[1];g_flag_b=s.flags[2];g_flag_cf=s.flags[3];
    memcpy(g_xmm,s.xmm,sizeof g_xmm);memcpy(g_st,s.st,sizeof g_st);
    memcpy(g_st_i64,s.shadows,sizeof g_st_i64);memcpy(g_enter_trace,s.trace,sizeof g_enter_trace);
    g_cur_func=s.current;g_backedges=s.backedges;g_enter_idx=s.enter;g_fp_top=s.top;
}
static unsigned cases;
static void initialize(unsigned count,unsigned kind) {
    for(unsigned i=0;i<sizeof memory;i++) memory[i]=(unsigned char)random32();
    g_eax=random32();g_ecx=random32();g_edx=random32();g_ebx=random32();g_esp=SP;
    g_ebp=random32();g_esi=random32();g_edi=random32();g_flag_k=FK_EFLAGS;
    g_flag_a=random32()&0x8d5;g_flag_b=0;g_flag_cf=random32()&1;g_cur_func=random32();
    g_backedges=0;g_enter_idx=0;memset(g_enter_trace,0,sizeof g_enter_trace);
    for(unsigned i=0;i<8;i++) {
        for(unsigned j=0;j<4;j++) g_xmm[i].u32[j]=random32();
        g_st[i]=random_float();g_st_i64[i]=(int64_t)(((uint64_t)random32()<<32)|random32());
    }
    g_fp_top=0;MEM32(SP)=0x30000000;MEM32(SP+4)=CTX;MEM32(SP+8)=BOX;MEM32(SP+12)=1;
    MEM32(CTX)=TREE;MEM32(CTX+4)=OBB;MEM32(CTX+8)=QUERY;MEM32(CTX+12)=COUNTS;
    MEM32(TREE+0x38)=RECORDS;MEM32(TREE+0x48)=LEAVES;
    MEM32(LEAVES+8)=(kind&1)?0x80000000:0;MEM32(LEAVES+12)=random32();
    MEM16(RECORDS)=count;
    for(unsigned i=0;i<count;i++) {
        MEM16(RECORDS+2+i*3)=random32()%12;
        MEM8(RECORDS+4+i*3)=kind==2?0xff:kind==3?0:(uint8_t)random32();
        MEM8(RECORDS+2+count*3+i)=(uint8_t)random32();
    }
    for(unsigned i=0;i<4;i++) put(CTX+16+i*4,random_float());
    for(unsigned i=0;i<24;i++) put(COUNTS+i*4,random_float());
    for(unsigned i=0;i<3;i++) {
        put(BOX+i*4,-8.f+random_float()*.1f);put(BOX+12+i*4,8.f+random_float()*.1f);
        put(QUERY+i*4,-4.f);put(QUERY+12+i*4,4.f);
        put(OBB+i*4,0);put(OBB+12+i*4,3.f);
    }
    for(unsigned i=0;i<9;i++) put(OBB+24+i*4,i%4==0?1.f:0.f);
}
