/* Compare the two SAT leaves, including state visible at scheduler hand-overs. */
#define RECOMP_GENERATED_CODE
#include "runtime-fixture.h"
#include <assert.h>

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
static unsigned char memory[32768], wanted_memory[32768], initial_memory[32768];
static uint32_t engine_threshold = 0x3f7fffefu, renderer_threshold = 0x3f7fffefu;
static void *guest_address(uint32_t va) {
    if (va == 0x11122ce0u) return &engine_threshold;
    if (va == 0x162d2a64u) return &renderer_threshold;
    assert(va >= BASE && va < BASE + sizeof memory);
    return memory + (va - BASE);
}
#undef ADDR
#define ADDR(va) ((uintptr_t)guest_address((uint32_t)(va)))

static int native_enabled;
int void_renderer_native_enabled(void) { return native_enabled; }

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
    uint32_t regs[8], flags[4], mxcsr, current, backedges;
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
    s.backedges=g_backedges; s.comparison=void_fpu_cmp;
    return s;
}

static void restore(snapshot s) {
    g_eax=s.regs[0]; g_ecx=s.regs[1]; g_edx=s.regs[2]; g_ebx=s.regs[3];
    g_esp=s.regs[4]; g_ebp=s.regs[5]; g_esi=s.regs[6]; g_edi=s.regs[7];
    g_flag_k=s.flags[0]; g_flag_a=s.flags[1]; g_flag_b=s.flags[2]; g_flag_cf=s.flags[3];
    memcpy(g_xmm,s.xmm,sizeof g_xmm); memcpy(g_mm,s.mm,sizeof g_mm);
    memcpy(g_st,s.st,sizeof g_st); memcpy(g_st_i64,s.shadow,sizeof g_st_i64);
    g_fp_top=s.top; g_fpu_cw=s.cw; g_mxcsr=s.mxcsr; g_cur_func=s.current;
    g_backedges=s.backedges; void_fpu_cmp=s.comparison;
}

static snapshot observed_yields[64], wanted_yields[64];
static unsigned yield_count, wanted_yield_count, cases, answers[2];
static unsigned perturb;

static void yield_hook(void) {
    assert(yield_count < 64);
    observed_yields[yield_count++] = state();
    if (perturb) {
        /* Exercise reload of live values, dead slots, shadows, and the stack
         * counter; an ordinary context switch would restore these unchanged. */
        if (isfinite(g_st[0])) g_st[0] += 1.0 / 1024.0;
        uint64_t bits; memcpy(&bits,g_st+7,8); bits ^= UINT64_C(0x10000000);
        memcpy(g_st+7,&bits,8);
        g_st_i64[0] ^= INT64_C(0x11223344);
        g_st_i64[7] ^= INT64_C(0x55667788);
        ++g_fp_top;
    }
}

static uint32_t random_state = 0x43ab129du;
static uint32_t random32(void) {
    random_state ^= random_state << 13; random_state ^= random_state >> 17;
    random_state ^= random_state << 5; return random_state;
}
static float random_float(void) { return (int32_t)random32() / 16777216.0f; }
static float from_bits(uint32_t bits) { float f; memcpy(&f,&bits,4); return f; }
static void put_float(uint32_t address, float value) { memcpy(guest_address(address),&value,4); }

static void initialize(unsigned kind) {
    for(unsigned i=0;i<sizeof memory;i++) memory[i]=(unsigned char)random32();
    g_eax=random32(); g_ecx=random32(); g_edx=AABB; g_ebx=random32();
    g_esp=SP; g_ebp=random32(); g_esi=random32(); g_edi=random32();
    g_flag_k=FK_EFLAGS; g_flag_a=random32()&0x8d5u; g_flag_b=0; g_flag_cf=random32()&1;
    for(unsigned i=0;i<8;i++) {
        for(unsigned j=0;j<4;j++) g_xmm[i].u32[j]=random32();
        g_mm[i]=((uint64_t)random32()<<32)|random32();
        g_st[i]=random_float(); g_st_i64[i]=(int64_t)(((uint64_t)random32()<<32)|random32());
    }
    g_fp_top=(int)(random32()%8); g_fpu_cw=(uint16_t)(0x7f | ((random32()%4)<<10) | ((random32()%3)<<8));
    g_mxcsr=0x1f80; g_cur_func=random32(); g_backedges=0; void_fpu_cmp=(int)(random32()%8);
    MEM32(SP)=0x30000000; MEM32(SP+4)=OBB;
    for(unsigned i=0;i<6;i++) {
        put_float(AABB+i*4, i<3 ? random_float() : fabsf(random_float())*.1f);
        put_float(OBB+i*4, i<3 ? random_float() : fabsf(random_float())*.1f);
    }
    float ax=random_float(), ay=random_float(), az=random_float();
    float sx=sinf(ax), cx=cosf(ax), sy=sinf(ay), cy=cosf(ay), sz=sinf(az), cz=cosf(az);
    float rotation[9] = {cy*cz,cy*sz,-sy, sx*sy*cz-cx*sz,sx*sy*sz+cx*cz,sx*cy,
                         cx*sy*cz+sx*sz,cx*sy*sz-sx*cz,cx*cy};
    for(unsigned i=0;i<9;i++) put_float(OBB+24+i*4,rotation[i]);
    if (kind == 1) { // Dense overlap, axis-aligned and early near-parallel exit.
        memcpy(guest_address(OBB),guest_address(AABB),12);
        for(unsigned i=0;i<9;i++) put_float(OBB+24+i*4,i%4==0 ? 1 : 0);
    } else if (kind == 2) { // Dense overlap with all nine cross axes exercised.
        memcpy(guest_address(OBB),guest_address(AABB),12);
    } else if (kind == 3) { // Face contacts, adjacent representable floats, and signed zero.
        for(unsigned i=0;i<3;i++) {
            put_float(AABB+i*4, i==0 ? from_bits(0x80000000u) : 0);
            put_float(AABB+12+i*4,1); put_float(OBB+i*4,i==0 ? from_bits(0x40000000u+(random32()%3)-1) : 0);
            put_float(OBB+12+i*4,1);
        }
        for(unsigned i=0;i<9;i++) put_float(OBB+24+i*4,i%4==0 ? 1 : 0);
    } else if (kind == 4) { // Unusual shapes and IEEE-754 payloads retain their old behavior.
        for(unsigned i=0;i<15;i++) MEM32(OBB+i*4)=random32();
        for(unsigned i=0;i<6;i++) MEM32(AABB+i*4)=random32();
    } else if (kind == 5) {
        static const uint32_t special[]={0,0x80000000u,1,0x807fffffu,0x7f800000u,0xff800000u,
            0x7fc12345u,0x7f812345u,0xff812345u,0x7f7fffffu,0xff7fffffu,0x7d7fffffu,0x7d800000u};
        uint32_t value=special[random32()%(sizeof special/sizeof special[0])];
        if(random32()&1) MEM32(AABB+(random32()%6)*4)=value;
        else MEM32(OBB+(random32()%15)*4)=value;
        uint64_t bits=UINT64_C(0x7ff0000000001234); memcpy(g_st+(random32()%8),&bits,8);
    }
}

static void differential(void (*original)(void), void (*localized)(void), unsigned yields, unsigned enabled) {
    snapshot before=state(); memcpy(initial_memory,memory,sizeof memory);
    recomp_yield_hook=yields ? yield_hook : NULL; yield_count=0;
    original(); snapshot wanted=state(); memcpy(wanted_memory,memory,sizeof memory);
    wanted_yield_count=yield_count; memcpy(wanted_yields,observed_yields,sizeof observed_yields);
    restore(before); memcpy(memory,initial_memory,sizeof memory); yield_count=0; native_enabled=(int)enabled;
    localized(); snapshot observed=state();
    if (memcmp(&wanted,&observed,sizeof wanted) || memcmp(wanted_memory,memory,sizeof memory)
            || yield_count != wanted_yield_count || memcmp(wanted_yields,observed_yields,yield_count*sizeof(snapshot))) {
        fprintf(stderr,"case %u mismatch: yields=%u perturb=%u enabled=%u observed-hooks=%u wanted-hooks=%u\n",
            cases,yields,perturb,enabled,yield_count,wanted_yield_count);
        const unsigned char *a=(const unsigned char*)&wanted,*b=(const unsigned char*)&observed;
        for(unsigned i=0;i<sizeof wanted;i++) if(a[i]!=b[i]) { fprintf(stderr,"state byte %u: %02x != %02x\n",i,a[i],b[i]); break; }
        for(unsigned i=0;i<sizeof memory;i++) if(wanted_memory[i]!=memory[i]) {
            fprintf(stderr,"memory byte %u: %02x != %02x\n",i,wanted_memory[i],memory[i]); break;
        }
        for(unsigned i=0;i<6;i++) fprintf(stderr,"AABB[%u]=%08x ",i,*(uint32_t*)(initial_memory+(AABB-BASE)+i*4));
        fprintf(stderr,"\n");
        for(unsigned i=0;i<15;i++) fprintf(stderr,"OBB[%u]=%08x ",i,*(uint32_t*)(initial_memory+(OBB-BASE)+i*4));
        fprintf(stderr,"\n");
        assert(0);
    }
    assert(g_esp==SP+8); answers[g_eax&1]++; ++cases;
}

int main(void) {
    void (*originals[])(void)={original_engine,original_renderer};
    void (*localized[])(void)={sub_1105E810,sub_160D6ED0};
    for(unsigned which=0;which<2;which++) for(unsigned mode=0;mode<3;mode++) {
        perturb=mode==2;
        for(unsigned kind=0;kind<6;kind++) for(unsigned n=0;n<400;n++) {
            initialize(kind); differential(originals[which],localized[which],mode!=0,1);
            if(n<3) { initialize(kind); differential(originals[which],localized[which],mode!=0,0); }
        }
    }
    assert(answers[0] && answers[1]);
    printf("PASS local x87 SAT cases=%u: both modules, complete memory/GPR/flags/XMM/MM/x87/shadows/CW/MXCSR, forced yields+reload, disabled fallback\n",cases);
    return 0;
}
