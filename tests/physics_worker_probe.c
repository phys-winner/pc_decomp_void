/* Compare the full worker state at its unchanged first direct-call boundary. */
#define RECOMP_GENERATED_CODE
#include "runtime-fixture.h"
#include <assert.h>
#include <setjmp.h>

uint32_t g_eax, g_ecx, g_edx, g_ebx, g_esp, g_ebp, g_esi, g_edi, g_fs_base, g_gs_base, g_cur_func;
ptrdiff_t g_mem_base;
double g_st[8]; int64_t g_st_i64[8]; int g_fp_top; uint16_t g_fpu_cw;
uint16_t g_seg_cs, g_seg_ds, g_seg_es, g_seg_fs, g_seg_gs, g_seg_ss;
uint64_t g_mm[8]; xmm_t g_xmm[8]; uint32_t g_mxcsr;
uint32_t g_flag_k, g_flag_a, g_flag_b, g_flag_cf;
int void_fpu_cmp;
uint32_t g_icall_trace[ICALL_TRACE_SIZE], g_icall_from[ICALL_TRACE_SIZE], g_icall_trace_idx, g_icall_count;
uint32_t g_enter_trace[RECOMP_ENTER_SIZE], g_enter_idx, g_backedges;
void (*recomp_yield_hook)(void);
const recomp_dispatch_entry_t recomp_dispatch_table[] = {{0, NULL}};
const uint32_t recomp_dispatch_count = 0;
void recomp_trace_enter(uint32_t va) { (void)va; }

#define BASE 0x20000000u
#define SP (BASE + 0x7000u)
#define AABB (BASE + 0x1000u)
#define OBB (BASE + 0x2000u)
#define GUEST_USER_TOP 0x7ffe0000u
static unsigned char memory[32768], wanted_memory[32768], initial_memory[32768];
static uint32_t double_constant=0x40000000u,cookie=0x13579bdfu;
static uint32_t boundary_stack,boundary_arguments[2];
static void *guest_address(uint32_t va) {
    if (va == 0x182f0548u) return &double_constant;
    if (va == 0x18342240u) return &cookie;
    if(boundary_stack && va>=boundary_stack+12u && va<=boundary_stack+16u)
        return boundary_arguments+(va-boundary_stack-12u)/4u;
    assert(va >= BASE && va < BASE + sizeof memory);
    return memory + (va - BASE);
}
#undef ADDR
#define ADDR(va) ((uintptr_t)guest_address((uint32_t)(va)))

static int physics_native_enabled;
/* GUARD */

/* STUBS */
void original_worker(void);void candidate_worker(void);
/* ORIGINALS */
/* LOCALIZED */

#undef eax
#undef ecx
#undef edx
#undef ebx
#undef esp
#undef ebp
#undef esi
#undef edi

typedef struct {
    uint32_t regs[8], flags[4], mxcsr, current, backedges, icall_index, icall_count, enter_index;
    uint32_t entries[RECOMP_ENTER_SIZE], icalls[ICALL_TRACE_SIZE], from[ICALL_TRACE_SIZE];
    xmm_t xmm[8]; uint64_t mm[8]; double st[8]; int64_t shadow[8];
    int top, comparison; uint16_t cw;
} snapshot;

static snapshot state(void) {
    snapshot s = {0};
    uint32_t regs[] = {g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi};
    uint32_t flags[] = {g_flag_k,g_flag_a,g_flag_b,g_flag_cf};
    memcpy(s.regs,regs,sizeof regs); memcpy(s.flags,flags,sizeof flags);
    memcpy(s.xmm,g_xmm,sizeof g_xmm); memcpy(s.mm,g_mm,sizeof g_mm);
    memcpy(s.st,g_st,sizeof g_st); memcpy(s.shadow,g_st_i64,sizeof g_st_i64);
    s.top=g_fp_top; s.cw=g_fpu_cw; s.mxcsr=g_mxcsr; s.current=g_cur_func;
    s.backedges=g_backedges; s.comparison=void_fpu_cmp;s.icall_index=g_icall_trace_idx;s.icall_count=g_icall_count;s.enter_index=g_enter_idx;
    memcpy(s.entries,g_enter_trace,sizeof s.entries);memcpy(s.icalls,g_icall_trace,sizeof s.icalls);memcpy(s.from,g_icall_from,sizeof s.from);
    return s;
}

static void restore(snapshot s) {
    g_eax=s.regs[0]; g_ecx=s.regs[1]; g_edx=s.regs[2]; g_ebx=s.regs[3];
    g_esp=s.regs[4]; g_ebp=s.regs[5]; g_esi=s.regs[6]; g_edi=s.regs[7];
    g_flag_k=s.flags[0]; g_flag_a=s.flags[1]; g_flag_b=s.flags[2]; g_flag_cf=s.flags[3];
    memcpy(g_xmm,s.xmm,sizeof g_xmm); memcpy(g_mm,s.mm,sizeof g_mm);
    memcpy(g_st,s.st,sizeof g_st); memcpy(g_st_i64,s.shadow,sizeof g_st_i64);
    g_fp_top=s.top; g_fpu_cw=s.cw; g_mxcsr=s.mxcsr; g_cur_func=s.current;
    g_backedges=s.backedges; void_fpu_cmp=s.comparison;g_icall_trace_idx=s.icall_index;g_icall_count=s.icall_count;g_enter_idx=s.enter_index;
    memcpy(g_enter_trace,s.entries,sizeof s.entries);memcpy(g_icall_trace,s.icalls,sizeof s.icalls);memcpy(g_icall_from,s.from,sizeof s.from);
}

static jmp_buf boundary;
void sub_181E7720(void) { longjmp(boundary,1); }
recomp_func_t void_resolve(uint32_t va) { (void)va; abort(); }
static void unexpected_yield(void) { abort(); }
static unsigned cases,fast_cases,fallback_cases,kind_now;
static snapshot before,wanted,actual;
static uint32_t random_state=0x538b291du;
static uint32_t random32(void) { random_state^=random_state<<13;random_state^=random_state>>17;random_state^=random_state<<5;return random_state; }
static float random_float(void) { return (int32_t)random32()/16777216.0f; }
static void put_float(uint32_t va,float f) { memcpy(guest_address(va),&f,4); }

static void initialize(unsigned kind) {
    for(unsigned i=0;i<sizeof memory;i++)memory[i]=(unsigned char)random32();
    g_eax=random32();g_ecx=random32();g_edx=random32();g_ebx=random32();g_esp=SP;g_ebp=random32();g_esi=random32();g_edi=random32();
    g_flag_k=FK_EFLAGS;g_flag_a=random32()&0x8d5u;g_flag_b=random32();g_flag_cf=random32()&1;
    for(unsigned i=0;i<8;i++) {
        for(unsigned j=0;j<4;j++)g_xmm[i].u32[j]=random32();
        g_mm[i]=((uint64_t)random32()<<32)|random32();g_st[i]=random_float();g_st_i64[i]=(int64_t)(((uint64_t)random32()<<32)|random32());
    }
    g_fp_top=random32()%9;g_fpu_cw=0x7f|((random32()%4)<<10)|((random32()%3)<<8);g_mxcsr=random32();g_cur_func=random32();g_backedges=0;void_fpu_cmp=random32()%8;
    g_enter_idx=random32();g_icall_trace_idx=random32();g_icall_count=random32();
    for(unsigned i=0;i<RECOMP_ENTER_SIZE;i++)g_enter_trace[i]=random32();
    for(unsigned i=0;i<ICALL_TRACE_SIZE;i++){g_icall_trace[i]=random32();g_icall_from[i]=random32();}
    MEM32(SP)=0x12345678;MEM32(SP+4)=BASE+0x4000;MEM32(SP+8)=BASE+0x4100;
    MEM32(SP+12)=AABB;MEM32(SP+16)=OBB;MEM32(SP+20)=BASE+0x4200;MEM32(SP+24)=BASE+0x3000;MEM32(SP+28)=BASE+0x4300;
    for(unsigned t=0;t<2;t++)for(unsigned j=0;j<7;j++)put_float((t?OBB:AABB)+4*j,j<3?random_float():random_float()/128.f);
    if(kind==1)for(unsigned t=0;t<2;t++)for(unsigned j=0;j<7;j++)MEM32((t?OBB:AABB)+4*j)=(random32()&1)<<31;
    if(kind==2)for(unsigned t=0;t<2;t++)for(unsigned j=0;j<7;j++)MEM32((t?OBB:AABB)+4*j)=(j<3?0x4cbebc20u:0x40000000u)|((random32()&1)<<31);
    if(kind==3)for(unsigned t=0;t<2;t++)for(unsigned j=0;j<7;j++)MEM32((t?OBB:AABB)+4*j)=(random32()&0x807fffffu)|((random32()%(j<3?153u:128u))<<23);
    if(kind==4)for(unsigned t=0;t<2;t++)for(unsigned j=0;j<7;j++)MEM32((t?OBB:AABB)+4*j)=random32();
    if(kind==5){static const uint32_t x[]={1,0x80000001,0x7f812345,0xff812345,0x7fc12345,0x7f800000,0xff800000,0x7f7fffff,0xff7fffff,0x4cbebc21,0x40000001};MEM32((random32()&1?AABB:OBB)+4*(random32()%7))=x[random32()%11];}
    if(kind==6)MEM32(SP+16)=AABB; /* Read-only input alias is safe. */
    if(kind==7)MEM32(SP+16)=AABB+4;
    if(kind==8)MEM32(SP+12)=SP-0x424; /* Prologue and argument scratch alias. */
    if(kind==9)MEM32(SP+16)=SP+4; /* Argument alias. */
    if(kind==10)MEM32(SP+12)=SP-0x440; /* Last float crosses the excluded frame. */
    if(kind==11)for(unsigned i=0;i<8;i++){uint64_t bits=UINT64_C(0x7ff0000000001234)+(random32()&7);memcpy(g_st+i,&bits,8);}
    if(kind==12)for(unsigned t=0;t<2;t++)for(unsigned j=0;j<7;j++)MEM32((t?OBB:AABB)+4*j)=(random32()&0x807fffffu); /* Subnormal products. */
    if(kind==13)for(unsigned t=0;t<2;t++)for(unsigned j=0;j<7;j++)put_float((t?OBB:AABB)+4*j,j<3?random_float()*100000.f:((int)(j+t)%3-1));
}
static void differential(unsigned enabled) {
    physics_native_enabled=enabled;recomp_yield_hook=unexpected_yield;
    before=state();memcpy(initial_memory,memory,sizeof memory);
    if(!setjmp(boundary)){original_worker();abort();}
    wanted=state();memcpy(wanted_memory,memory,sizeof memory);
    restore(before);memcpy(memory,initial_memory,sizeof memory);fast_prefixes=fallback_prefixes=0;
    if(!setjmp(boundary)){candidate_worker();abort();}
    actual=state();fast_cases+=fast_prefixes;fallback_cases+=fallback_prefixes;
    int ss=memcmp(&wanted,&actual,sizeof wanted),mm=memcmp(wanted_memory,memory,sizeof memory);
    if(ss||mm){fprintf(stderr,"FAIL case%u kind%u enabled%u state%d memory%d fast%u fallback%u\n",cases,kind_now,enabled,ss,mm,fast_prefixes,fallback_prefixes);
        for(unsigned i=0;i<sizeof memory;i++)if(wanted_memory[i]!=memory[i]){fprintf(stderr,"memory%u %02x/%02x\n",i,wanted_memory[i],memory[i]);break;}
        const unsigned char *a=(const unsigned char*)&wanted,*b=(const unsigned char*)&actual;for(unsigned i=0;i<sizeof wanted;i++)if(a[i]!=b[i]){fprintf(stderr,"state%u %02x/%02x\n",i,a[i],b[i]);break;}exit(1);}
    assert(actual.regs[4]==SP-0x428);assert(actual.current==0x181F1F80u);assert(fast_prefixes+fallback_prefixes==1);++cases;
}
static void guard_boundaries(void) {
    initialize(0);physics_native_enabled=1;
    assert(guard_actual());
    uint32_t stack=g_esp;
    static const uint32_t bad_stack[]={0,0x427,0x10427,GUEST_USER_TOP-31u,0xffffffffu};
    for(unsigned i=0;i<sizeof bad_stack/sizeof *bad_stack;i++){g_esp=bad_stack[i];assert(!guard_actual());}
    boundary_arguments[0]=AABB;boundary_arguments[1]=OBB;
    boundary_stack=g_esp=0x10428u;assert(guard_actual());
    boundary_stack=g_esp=GUEST_USER_TOP-32u;assert(guard_actual());boundary_stack=0;
    g_esp=stack;
    static const uint32_t bad_pointer[]={0,0xffff,GUEST_USER_TOP-27u,0xfffffff0u,SP-0x428,SP-0x427,SP+31};
    for(unsigned i=0;i<sizeof bad_pointer/sizeof *bad_pointer;i++){MEM32(SP+12)=bad_pointer[i];assert(!guard_actual());}
    MEM32(SP+12)=AABB;assert(guard_actual());
    MEM32(SP+12)=SP-0x444;for(unsigned j=0;j<7;j++)MEM32(SP-0x444+4*j)=0;assert(guard_actual());
    MEM32(SP+12)=SP+32;for(unsigned j=0;j<7;j++)MEM32(SP+32+4*j)=0;assert(guard_actual());
}
int main(void) {
    guard_boundaries();
    for(unsigned kind=0;kind<14;kind++)for(unsigned n=0;n<300;n++){kind_now=kind;initialize(kind);differential(1);if(n<4){initialize(kind);differential(0);}}
    assert(fast_cases>1000&&fallback_cases>500);
    printf("PASS F1F80 %u full-state boundaries fast%u fallback%u IEEE/alias/nonemptyFP/frame/trace\n",cases,fast_cases,fallback_cases);return 0;
}
