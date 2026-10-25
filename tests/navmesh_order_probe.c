#define RECOMP_GENERATED_CODE
#include "runtime-fixture.h"
#include <assert.h>
#include <stdarg.h>
#include <time.h>

uint32_t g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi,g_fs_base,g_gs_base,g_cur_func;
ptrdiff_t g_mem_base;
double g_st[8]; int64_t g_st_i64[8]; int g_fp_top; uint16_t g_fpu_cw;
uint16_t g_seg_cs,g_seg_ds,g_seg_es,g_seg_fs,g_seg_gs,g_seg_ss;
uint64_t g_mm[8]; xmm_t g_xmm[8]; uint32_t g_mxcsr;
uint32_t g_flag_k,g_flag_a,g_flag_b,g_flag_cf;
int void_fpu_cmp;
uint32_t g_icall_trace[ICALL_TRACE_SIZE],g_icall_from[ICALL_TRACE_SIZE],g_icall_trace_idx,g_icall_count;
uint32_t g_enter_trace[RECOMP_ENTER_SIZE],g_enter_idx,g_backedges;
void (*recomp_yield_hook)(void);
const recomp_dispatch_entry_t recomp_dispatch_table[]={{0,NULL}};
const uint32_t recomp_dispatch_count=0;
void recomp_trace_enter(uint32_t va) {(void)va;}
void void_log(const char *format,...) {(void)format;}

#define BASE 0x20000000u
#define MESH (BASE+0x100u)
#define RAY (BASE+0x200u)
#define LEAF (BASE+0x300u)
#define POINT (BASE+0x400u)
#define VERTICES (BASE+0x1000u)
#define MAP (BASE+0x4000u)
#define OFFSETS (BASE+0x7000u)
#define POLYS (BASE+0x8000u)
#define SP (BASE+0xf000u)
static unsigned char memory[65536],initial[65536],expected[65536];
static float epsilon=1e-6f,scale=0.005f;
static void *guest_address(uint32_t va) {
    if(va==0x11122974u)return &epsilon;
    if(va==0x11122d0cu)return &scale;
    assert(va>=BASE && va<BASE+sizeof memory);
    return memory+va-BASE;
}
#undef ADDR
#define ADDR(va) ((uintptr_t)guest_address((uint32_t)(va)))

/* EMITTED */

#undef eax
#undef ecx
#undef edx
#undef ebx
#undef esp
#undef ebp
#undef esi
#undef edi
void sub_110EC930_lifted(void) {assert(0);}
#undef ADDR
#define ADDR(va) ((uintptr_t)memory+((uint32_t)(va)-BASE))
#if NAVMESH_PLAIN_MEMORY
#define RECOMP_PLAIN_MEMORY
#else
#undef RECOMP_PLAIN_MEMORY
#endif
/* NATIVE */
#undef ADDR
#define ADDR(va) ((uintptr_t)guest_address((uint32_t)(va)))
#undef RECOMP_MEM_QUAL
#define RECOMP_MEM_QUAL volatile

static uint32_t random_state=0x73fe8ab2u;
static uint32_t random32(void) {random_state^=random_state<<13;random_state^=random_state>>17;random_state^=random_state<<5;return random_state;}
static unsigned cases,hits,misses;
static void reset_cpu(void) {
    g_eax=0xabcdef12;g_esp=SP;g_ebx=0x12345678;g_ebp=0x98765432;g_esi=0x12673456;g_edi=0xabcd8423;
    memset(g_st,0,sizeof g_st);memset(g_st_i64,0,sizeof g_st_i64);memset(g_xmm,0,sizeof g_xmm);
    g_fp_top=0;g_fpu_cw=0x37f;g_mxcsr=0x1f80;g_backedges=0;
    MEM32(SP)=0;MEM32(SP+4)=RAY;MEM32(SP+8)=LEAF;MEM32(SP+12)=POINT;
}
static void compare(void) {
    reset_cpu();memcpy(initial,memory,sizeof memory);original_leaf();memcpy(expected,memory,sizeof memory);
    if(MEM32(RAY+8)==0xffffffffu)misses++;else hits++;
    memcpy(memory,initial,sizeof memory);reset_cpu();sub_110EC930();
    if(memcmp(memory,expected,SP-BASE-512)) {
        printf("case %u: t %08X/%08X polygon %u/%u\n",cases,MEM32(RAY+4),*(uint32_t*)(expected+RAY-BASE+4),MEM32(RAY+8),*(uint32_t*)(expected+RAY-BASE+8));
        assert(0);
    }
    assert(g_esp==SP+16 && !(g_eax&255));
    cases++;
}
static void initialize(unsigned count,unsigned shape) {
    memset(memory,0,sizeof memory);
    *(float*)GPTR(BASE+0x500u)=epsilon;*(float*)GPTR(BASE+0x504u)=scale;
    MEM32(MESH+MESH_VERTICES)=VERTICES;MEM32(MESH+MESH_VERTEX_MAP)=MAP;
    MEM32(MESH+MESH_POLY_OFFSETS)=OFFSETS;MEM32(MESH+MESH_POLY_DATA)=POLYS;
    MEM32(RAY)=MESH;*(float*)GPTR(RAY+4)=1000.0f;MEM32(RAY+8)=0xffffffffu;
    MEM32(LEAF)=count;MEM32(LEAF+4)=3;
    MEM32(POINT)=(int32_t)(random32()%40001)-20000;MEM32(POINT+4)=(int32_t)(random32()%40001)-20000;MEM32(POINT+8)=(int32_t)(random32()%40001)-20000;
    unsigned offset=0,index=0;
    for(unsigned k=0;k<count;k++) {
        unsigned n=shape==0?3:shape==1?4:shape==2?3+random32()%14:3+random32()%7;
        MEM32(OFFSETS+4*(3+k))=offset;MEM32(POLYS+4*offset)=k;
        MEM32(POLYS+4*(offset+1))=n;
        for(unsigned i=0;i<n;i++,index++) {
            uint32_t code=index*2+(index&1);
            MEM32(MAP+4*((code&1)+4*(code>>1)))=index;
            MEM32(POLYS+4*(offset+2+i))=code;
            int32_t x=(int32_t)(random32()%40001)-20000,z=(int32_t)(random32()%40001)-20000,y=(int32_t)(random32()%40001)-20000;
            if(shape<2) {
                x=(i==1||i==2)?10000:-10000;z=(i>=2)?10000:-10000;
                y=(int32_t)(k*500)-2000;
            }
            if(shape==3 && i>0 && random32()%3==0) {x=(int32_t)MEM32(VERTICES+12*(index-1));z=(int32_t)MEM32(VERTICES+12*(index-1)+8);}
            MEM32(VERTICES+12*index)=x;MEM32(VERTICES+12*index+4)=y;MEM32(VERTICES+12*index+8)=z;
        }
        offset+=n+2;
    }
}
static void benchmark(void) {
    for(unsigned shape=0;shape<3;shape++) {
        random_state=0x73fe8ab2u;initialize(12,shape);
        MEM32(POINT+4)=3000;
        uint32_t checksum=0;clock_t start=clock();
        for(unsigned i=0;i<200000;i++) {
            MEM32(POINT)=(int32_t)(i%5)*7000-14000;MEM32(POINT+8)=(int32_t)(i%7)*5000-15000;
            *(float*)GPTR(RAY+4)=1000.0f;MEM32(RAY+8)=0xffffffffu;
            float t;uint32_t index;leaf_test(RAY,LEAF,POINT,&t,&index);
            checksum^=MEM32(RAY+4)+index;
        }
        printf("BENCH shape=%u seconds=%.6f checksum=%08X\n",shape,(double)(clock()-start)/CLOCKS_PER_SEC,checksum);
    }
}
int main(int argc,char **argv) {
    (void)argv;
    for(unsigned shape=0;shape<4;shape++)for(unsigned i=0;i<2000;i++) {
        initialize(1+random32()%12,shape);
        static float limits[]={0.0f,-0.0f,0.000001f,0.1f,1.0f,1000.0f,INFINITY,NAN};
        *(float*)GPTR(RAY+4)=limits[i%8];compare();
    }
    initialize(0,0);compare();
    for(int x=-10000;x<=10000;x+=10000)for(int z=-10000;z<=10000;z+=10000) {
        initialize(1,1);MEM32(POINT)=x;MEM32(POINT+4)=3000;MEM32(POINT+8)=z;compare();
    }
    static int32_t extremes[]={INT32_MIN,INT32_MIN+1,-1,0,1,INT32_MAX-1,INT32_MAX};
    for(unsigned i=0;i<300;i++) {
        initialize(1,1);
        for(unsigned v=0;v<4;v++)for(unsigned axis=0;axis<3;axis++)
            MEM32(VERTICES+12*v+4*axis)=extremes[random32()%7];
        for(unsigned axis=0;axis<3;axis++)MEM32(POINT+4*axis)=extremes[random32()%7];
        compare();
    }
    assert(hits>100 && misses>100);
    printf("PASS navmesh memory: %u cases, %u hits/%u misses; exact emitted leaf+helpers, distance bits, polygon, input memory, degenerate fans, boundaries, both windings and ray limits\n",cases,hits,misses);
    if(argc>1)benchmark();
    return 0;
}
