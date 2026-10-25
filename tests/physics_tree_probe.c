/* Compare per-node tree arithmetic and all original recursive/callback state. */
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
#define GUEST_USER_TOP 0x7ffe0000u
static unsigned char memory[32768], wanted_memory[32768], initial_memory[32768];
static uint32_t half_constant=0x3f000000u,zero_constant;
static void *guest_address(uint32_t va) {
    if (va == 0x182f054cu) return &half_constant;
    if (va == 0x182f0400u) return &zero_constant;
    assert(va >= BASE && va < BASE + sizeof memory);
    return memory + (va - BASE);
}
#undef ADDR
#define ADDR(va) ((uintptr_t)guest_address((uint32_t)(va)))

static int physics_native_enabled;
/* GUARD */

void original_af40(void);void candidate_af40(void);
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
    uint32_t regs[8], flags[4], mxcsr, current, backedges, icall_index;
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
    s.backedges=g_backedges; s.comparison=void_fpu_cmp;s.icall_index=g_icall_trace_idx;
    return s;
}

static void restore(snapshot s) {
    g_eax=s.regs[0]; g_ecx=s.regs[1]; g_edx=s.regs[2]; g_ebx=s.regs[3];
    g_esp=s.regs[4]; g_ebp=s.regs[5]; g_esi=s.regs[6]; g_edi=s.regs[7];
    g_flag_k=s.flags[0]; g_flag_a=s.flags[1]; g_flag_b=s.flags[2]; g_flag_cf=s.flags[3];
    memcpy(g_xmm,s.xmm,sizeof g_xmm); memcpy(g_mm,s.mm,sizeof g_mm);
    memcpy(g_st,s.st,sizeof g_st); memcpy(g_st_i64,s.shadow,sizeof g_st_i64);
    g_fp_top=s.top; g_fpu_cw=s.cw; g_mxcsr=s.mxcsr; g_cur_func=s.current;
    g_backedges=s.backedges; void_fpu_cmp=s.comparison;g_icall_trace_idx=s.icall_index;
}

static snapshot observed_yields[128], wanted_yields[128];
static unsigned yield_count, wanted_yield_count, cases;
static unsigned perturb;

static void yield_hook(void) {
    assert(yield_count < 128);
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


#define CTX (BASE+0x1000u)
#define NODES (BASE+0x2000u)
#define CALLBACK 0x55550000u
static unsigned node_count,callback_mode,callback_count,wanted_callback_count,current_case;
static unsigned aggregate_fast,aggregate_fallback;
static snapshot callbacks[128],wanted_callbacks[128];
static uint64_t callback_memory[128],wanted_callback_memory[128];
static uint32_t initial_icall[ICALL_TRACE_SIZE],wanted_icall[ICALL_TRACE_SIZE],initial_from[ICALL_TRACE_SIZE],wanted_from[ICALL_TRACE_SIZE];
static uint64_t memory_hash(void){uint64_t h=14695981039346656037ull;for(unsigned i=0;i<sizeof memory;i++)h=(h^memory[i])*1099511628211ull;return h;}
static void callback(void) {
    assert(callback_count<128);callbacks[callback_count]=state();callback_memory[callback_count]=memory_hash();++callback_count;
    assert(MEM32(g_esp+12)==CTX+0x84);
    g_eax=0;
    if(callback_mode==1)g_eax=1;
    if(callback_mode==2){put_float(CTX+0x84,.25f);g_eax=2;}
    if(callback_mode==3){MEM32(CTX+0x1c)=0x7f812345u;put_float(CTX+0x84,.5f);g_eax=2;}
    if(callback_mode==4){MEM32(NODES+40u*(node_count-1))=0xff812345u;g_eax=0;}
    g_flag_k=FK_TEST;g_flag_a=g_eax;g_flag_b=3;g_flag_cf=0;
    g_esp+=4;
}
recomp_func_t void_resolve(uint32_t va){assert(va==CALLBACK);return callback;}
static void initialize_tree(unsigned kind) {
    for(unsigned i=0;i<sizeof memory;i++)memory[i]=(unsigned char)random32();
    g_eax=random32();g_ecx=CTX;g_edx=random32();g_ebx=random32();g_esp=SP;g_ebp=random32();g_esi=random32();g_edi=random32();
    g_flag_k=FK_EFLAGS;g_flag_a=random32()&0x8d5u;g_flag_b=0;g_flag_cf=random32()&1;
    for(unsigned i=0;i<8;i++){
        for(unsigned j=0;j<4;j++)g_xmm[i].u32[j]=random32();
        g_mm[i]=((uint64_t)random32()<<32)|random32();g_st[i]=random_float();g_st_i64[i]=(int64_t)(((uint64_t)random32()<<32)|random32());
    }
    g_fp_top=random32()%9;g_fpu_cw=0x7f|((random32()%4)<<10)|((random32()%3)<<8);g_mxcsr=0x1f80;g_cur_func=random32();g_backedges=0;void_fpu_cmp=random32()%8;
    g_icall_trace_idx=0;memset(g_icall_trace,0,sizeof g_icall_trace);memset(g_icall_from,0,sizeof g_icall_from);
    memset(GPTR(CTX),0,0x100);put_float(CTX+0x24,1);put_float(CTX+0x28,1);put_float(CTX+0x2c,1);put_float(CTX+0x30,1);put_float(CTX+0x3c,1);put_float(CTX+0x84,10);
    unsigned depth=random32()%6;node_count=(1u<<(depth+1))-1;
    for(unsigned i=0;i<node_count;i++) {
        uint32_t n=NODES+40*i;float radius=1.f+(i%4)*.125f;
        for(unsigned j=0;j<3;j++){put_float(n+4*j,-radius);put_float(n+12+4*j,radius);}
        MEM32(n+24)=i*2+1<node_count?NODES+40*(i*2+1):1;
        MEM32(n+28)=0;MEM32(n+32)=i;MEM32(n+36)=0x12340000u+i;
    }
    MEM32(SP)=0x30000000;MEM32(SP+4)=NODES;MEM32(SP+8)=CALLBACK;MEM32(SP+12)=0x12345678;
    callback_mode=kind<5?kind:random32()%5;
    if(kind==5){for(unsigned j=0;j<12;j++)put_float(CTX+0x1c+4*j,random_float());for(unsigned i=0;i<node_count;i++)for(unsigned j=0;j<6;j++)put_float(NODES+40*i+4*j,random_float());}
    if(kind==6){MEM32(NODES+40*(random32()%node_count)+4*(random32()%6))=random32();}
    if(kind==7){MEM32(CTX+0x1c+4*(random32()%12))=random32();}
    if(kind==8){static const uint32_t special[]={0x7f812345,0xff812345,0x7fc12345,0x7f800000,0xff800000,0x7f7fffff,0xff7fffff,1,0x80000001,0x4cbebc20,0xccbebc20};uint32_t x=special[random32()%11];if(random32()&1)MEM32(CTX+0x1c+4*(random32()%12))=x;else MEM32(NODES+40*(random32()%node_count)+4*(random32()%6))=x;}
    if(kind==9){for(unsigned i=0;i<8;i++){uint64_t bits=UINT64_C(0x7ff0000000001234)+(random32()&7);memcpy(g_st+i,&bits,8);}}
    if(kind==10){/* Context aliases current node, all metadata remains a valid leaf. */memcpy(GPTR(CTX),GPTR(NODES),24);MEM32(CTX+24)=1;MEM32(CTX+32)=12;MEM32(CTX+36)=34;MEM32(CTX+4)&=~4u;MEM32(SP+4)=CTX;node_count=1;callback_mode=0;}
    if(kind==11){/* Node aliases callee scratch and arguments; force first-axis rejection. */uint32_t n=SP+12;MEM32(SP+4)=n;for(unsigned j=0;j<3;j++){put_float(n+4*j,-1);put_float(n+12+4*j,1);}MEM32(n+24)=1;MEM32(n+32)=12;MEM32(n+36)=34;callback_mode=0;}
    if(kind==12){MEM32(CTX+4)=4;}
    if(kind==13){for(unsigned j=0;j<12;j++)MEM32(CTX+0x1c+4*j)=(random32()&1)<<31;for(unsigned i=0;i<node_count;i++)for(unsigned j=0;j<6;j++)MEM32(NODES+40*i+4*j)=(random32()&1)<<31;}
    if(kind==14){for(unsigned j=0;j<12;j++)MEM32(CTX+0x1c+4*j)=(random32()&0x807fffffu)|((random32()%153)<<23);for(unsigned i=0;i<node_count;i++)for(unsigned j=0;j<6;j++)MEM32(NODES+40*i+4*j)=(random32()&0x807fffffu)|((random32()%153)<<23);}
    if(kind==15){for(unsigned j=0;j<12;j++)MEM32(CTX+0x1c+4*j)=0x4cbebc20u|((random32()&1)<<31);for(unsigned i=0;i<node_count;i++)for(unsigned j=0;j<6;j++)MEM32(NODES+40*i+4*j)=0x4cbebc20u|((random32()&1)<<31);}
}
static void differential(unsigned yields,unsigned enabled) {
    physics_native_enabled=enabled;recomp_yield_hook=yields?yield_hook:NULL;yield_count=callback_count=0;
    snapshot before=state();memcpy(initial_memory,memory,sizeof memory);memcpy(initial_icall,g_icall_trace,sizeof initial_icall);memcpy(initial_from,g_icall_from,sizeof initial_from);
    original_af40();snapshot wanted=state();memcpy(wanted_memory,memory,sizeof memory);memcpy(wanted_icall,g_icall_trace,sizeof wanted_icall);memcpy(wanted_from,g_icall_from,sizeof wanted_from);
    wanted_yield_count=yield_count;memcpy(wanted_yields,observed_yields,yield_count*sizeof(snapshot));wanted_callback_count=callback_count;memcpy(wanted_callbacks,callbacks,callback_count*sizeof(snapshot));memcpy(wanted_callback_memory,callback_memory,callback_count*sizeof(uint64_t));
    restore(before);memcpy(memory,initial_memory,sizeof memory);memcpy(g_icall_trace,initial_icall,sizeof initial_icall);memcpy(g_icall_from,initial_from,sizeof initial_from);yield_count=callback_count=0;fast_nodes=fallback_nodes=0;
    candidate_af40();snapshot actual=state();aggregate_fast+=fast_nodes;aggregate_fallback+=fallback_nodes;
    int ss=memcmp(&wanted,&actual,sizeof wanted),mm=memcmp(wanted_memory,memory,sizeof memory),cc=callback_count!=wanted_callback_count||memcmp(wanted_callbacks,callbacks,callback_count*sizeof(snapshot))||memcmp(wanted_callback_memory,callback_memory,callback_count*sizeof(uint64_t));
    int yy=yield_count!=wanted_yield_count||memcmp(wanted_yields,observed_yields,yield_count*sizeof(snapshot));
    int tt=memcmp(wanted_icall,g_icall_trace,sizeof wanted_icall)||memcmp(wanted_from,g_icall_from,sizeof wanted_from);
    if(ss||mm||cc||yy||tt){fprintf(stderr,"FAIL case%u kind%u mode%u enabled%u state%d mem%d calls%d(%u/%u) yields%d(%u/%u) trace%d fast%u fallback%u\n",cases,current_case,yields,enabled,ss,mm,cc,callback_count,wanted_callback_count,yy,yield_count,wanted_yield_count,tt,fast_nodes,fallback_nodes);
      for(unsigned i=0;i<sizeof memory;i++)if(wanted_memory[i]!=memory[i]){fprintf(stderr,"memory%u %02x/%02x\n",i,wanted_memory[i],memory[i]);break;}
      const unsigned char *a=(const unsigned char*)&wanted,*b=(const unsigned char*)&actual;for(unsigned i=0;i<sizeof wanted;i++)if(a[i]!=b[i]){fprintf(stderr,"state%u %02x/%02x\n",i,a[i],b[i]);break;}exit(1);}
    assert(g_esp==SP+16);++cases;
}
int main(void){for(unsigned mode=0;mode<3;mode++){perturb=mode==2;for(unsigned kind=0;kind<16;kind++)for(unsigned n=0;n<100;n++){current_case=kind;initialize_tree(kind);differential(mode!=0,1);if(n<2){initialize_tree(kind);differential(mode!=0,0);}}}
 assert(aggregate_fast>1000 && aggregate_fallback>1000);printf("PASS AF40 %u full-state trees fast%u fallback%u recursive/callback/IEEE/alias/forcedyield\n",cases,aggregate_fast,aggregate_fallback);return 0;}
