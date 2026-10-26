/* DECLARATIONS */
#include <windows.h>
#define GUEST_USER_TOP 0x7ffe0000u
#define BASE 0x20000000u
#define SP (BASE + 0x700000u)
#define INPUT (BASE + 0x10000u)
#define OUTPUT (BASE + 0x100000u)
#define STREAM (BASE + 0x1000u)
static unsigned char memory[0x800000], initial[0x800000], wanted[0x800000];
static unsigned char image[0x400000];
static uint32_t image_size, heap;
static unsigned allocations, frees, native_calls, fallback_probes, yields;
static int native_enabled, invalid_probe;
static void *guest_address(uint32_t at) {
    if (at >= 0x16000000u && at < 0x16000000u + image_size) return image + at - 0x16000000u;
    assert(at >= BASE && at < BASE + sizeof memory);
    return memory + at - BASE;
}
static int void_vm_readable(uint32_t at, uint32_t size) {
    return at >= BASE && at <= BASE + sizeof memory && size <= BASE + sizeof memory - at;
}
#undef GPTR
#define GPTR(va) guest_address((uint32_t)(va))
int void_renderer_native_enabled(void) { return native_enabled; }
typedef unsigned char Bytef;
#define Z_NULL 0
typedef unsigned long (__cdecl *adler_api)(unsigned long, const Bytef *, unsigned int);
static adler_api system_adler;
static unsigned long adler32(unsigned long seed, const Bytef *data, unsigned length) {
    ++native_calls;
    return system_adler(seed, data, length);
}
/* PROTOTYPES */
void original_adler(void);
void sub_16120040_lifted(void) {
    if (invalid_probe) { ++fallback_probes; return; }
    original_adler();
}
/* HELPER */
static void allocate(void) {
    uint32_t count=MEM32(g_esp+8), size=MEM32(g_esp+12);
    assert(count && size && count <= 0x10000u / size);
    g_eax=heap;
    memset(GPTR(heap),0,count*size);
    heap+=(count*size+15u)&~15u;
    assert(heap < BASE+0x680000u);
    ++allocations; g_esp+=4;
}
static void release(void) { ++frees; g_esp+=4; }
recomp_func_t void_resolve(uint32_t at) {
    if (at==0x30000010u) return allocate;
    if (at==0x30000020u) return release;
    fprintf(stderr,"unexpected callback %08x\n",at); assert(0); return NULL;
}
/* The existing production CRT override, not a different inflate algorithm. */
void sub_1612A0F0(void) {
    uint32_t dst=MEM32(g_esp+4),src=MEM32(g_esp+8),size=MEM32(g_esp+12);
    if(size) memmove(GPTR(dst),GPTR(src),size);
    g_eax=dst;g_esp+=4;
}
void sub_16125D86(void) { assert(g_ecx==MEM32(0x1633d310u));g_esp+=4; }
/* EMITTED */
#undef eax
#undef ecx
#undef edx
#undef ebx
#undef esp
#undef ebp
#undef esi
#undef edi

typedef struct { uint32_t saved[5], value, edges; double st[8]; int64_t shadow[8]; xmm_t xmm[8]; uint64_t mm[8];
    int top; uint16_t cw; uint32_t mxcsr; } abi;
static abi snapshot(void) {
    abi s={0}; uint32_t saved[]={g_ebx,g_ebp,g_esi,g_edi,g_esp};
    memcpy(s.saved,saved,sizeof saved);s.value=g_eax;s.edges=g_backedges;
    memcpy(s.st,g_st,sizeof g_st);memcpy(s.shadow,g_st_i64,sizeof g_st_i64);
    memcpy(s.xmm,g_xmm,sizeof g_xmm);memcpy(s.mm,g_mm,sizeof g_mm);
    s.top=g_fp_top;s.cw=g_fpu_cw;s.mxcsr=g_mxcsr;return s;
}
static void initialize(void) {
    memset(memory,0xcc,sizeof memory);
    g_eax=0x11223344;g_ecx=0x55667788;g_edx=0x99887766;g_ebx=0xf1234567;
    g_esp=SP;g_ebp=0xe2345678;g_esi=0xd3456789;g_edi=0xc456789a;
    g_flag_k=FK_EFLAGS;g_flag_a=0x855;g_flag_b=0;g_flag_cf=1;
    g_fs_base=BASE+0x800;g_gs_base=0;g_fp_top=0;g_fpu_cw=0x37f;g_mxcsr=0x1f80;
    for(unsigned i=0;i<8;++i) {g_st[i]=i*.125;g_st_i64[i]=i*1234;g_mm[i]=i*4357;memset(&g_xmm[i],i,sizeof g_xmm[i]);}
    g_backedges=0;recomp_yield_hook=NULL;native_calls=allocations=frees=yields=0;
    heap=BASE+0x500000;native_enabled=0;invalid_probe=0;
}
static uint32_t invoke(void (*fn)(void),const uint32_t *args,unsigned count) {
    g_esp=SP;MEM32(SP)=0x30000000;
    for(unsigned i=0;i<count;++i)MEM32(SP+4+i*4)=args[i];
    fn();assert(g_esp==SP+4);return g_eax;
}
static void yield(void) { ++yields; }
static void leaf(uint32_t seed,uint32_t buffer,uint32_t count,int expect_fast,int hook) {
    initialize();
    for(unsigned i=0;i<100000;++i)memory[0x10000+i]=(unsigned char)(i*17+i/7);
    uint32_t args[]={seed,buffer,count};
    for(unsigned i=0;i<3;++i)MEM32(SP+4+i*4)=args[i];MEM32(SP)=0x30000000;
    memcpy(initial,memory,sizeof memory);
    recomp_yield_hook=hook?yield:NULL;
    if(hook==2)g_backedges=63;
    sub_16120040();abi expected=snapshot();unsigned expected_yields=yields;
    memcpy(wanted,memory,sizeof memory);
    initialize();memcpy(memory,initial,sizeof memory);native_enabled=1;recomp_yield_hook=hook?yield:NULL;
    if(hook==2)g_backedges=63;
    sub_16120040();abi observed=snapshot();
    if(memcmp(&expected,&observed,sizeof expected)) {fprintf(stderr,"leaf seed%08x buf%08x n%u edges%u/%u\n",seed,buffer,count,expected.edges,observed.edges);assert(0);}
    /* The original caller discards the leaf's saved-register scratch. */
    memset(wanted+SP-BASE-16,0,16);memset(memory+SP-BASE-16,0,16);
    assert(!memcmp(wanted,memory,sizeof memory));assert(yields==expected_yields);
    assert((native_calls!=0)==expect_fast);
}
typedef struct { uint32_t output,status,in_used,out_used,checksum,allocs,frees; abi state; } stream_result;
static stream_result inflate_file(const unsigned char *packed,uint32_t length,int enabled,unsigned chunk) {
    initialize();native_enabled=enabled;
    memset(GPTR(STREAM),0,56);MEM32(STREAM+0x20)=0x30000010;MEM32(STREAM+0x24)=0x30000020;
    memcpy(GPTR(INPUT),packed,length);
    uint32_t version=BASE+0x2000;memcpy(GPTR(version),"1.2.3",6);
    uint32_t init_args[]={STREAM,47,version,56};
    assert((int)invoke(sub_1611E830,init_args,4)==0);
    MEM32(STREAM)=INPUT;MEM32(STREAM+4)=0;MEM32(STREAM+0xc)=OUTPUT;MEM32(STREAM+0x10)=0;
    int result=0;unsigned rounds=0;
    while(++rounds<200000) {
        uint32_t supplied=MEM32(STREAM)-INPUT+MEM32(STREAM+4);
        if(!MEM32(STREAM+4) && supplied<length)MEM32(STREAM+4)=length-supplied<chunk?length-supplied:chunk;
        MEM32(STREAM+0x10)=chunk;
        uint32_t before_in=MEM32(STREAM),before_out=MEM32(STREAM+0xc);
        uint32_t args[]={STREAM,2};result=(int)invoke(sub_1611E9F0,args,2);
        if(result==1 || (result<0&&result!=-5))break;
        if(MEM32(STREAM)==before_in&&MEM32(STREAM+0xc)==before_out&&supplied==length)break;
        assert(MEM32(STREAM+0xc)<OUTPUT+0x100000u);
    }
    assert(rounds<200000);
    stream_result r={0};r.status=(uint32_t)result;r.in_used=MEM32(STREAM)-INPUT;
    r.out_used=MEM32(STREAM+0xc)-OUTPUT;r.checksum=MEM32(STREAM+0x30);
    uint32_t end_args[]={STREAM};assert((int)invoke(sub_1611FFF0,end_args,1)==0);
    r.allocs=allocations;r.frees=frees;r.state=snapshot();
    /* Scratch, tracing and branch counts are not serialized game/stream output. */
    r.state.edges=0;return r;
}
int main(int argc,char **argv) {
    assert(argc>2);HMODULE library=LoadLibraryA("C:/Program Files/Git/mingw64/bin/zlib1.dll");assert(library);
    system_adler=(adler_api)GetProcAddress(library,"adler32");assert(system_adler);
    FILE *f=fopen(argv[1],"rb");assert(f);image_size=(uint32_t)fread(image,1,sizeof image,f);fclose(f);assert(image_size);
    unsigned lengths[]={0,1,2,7,15,16,17,255,5551,5552,5553,11104,65536};unsigned leaves=0,streams=0,stream_native_calls=0;
    for(unsigned i=0;i<sizeof lengths/sizeof lengths[0];++i)for(unsigned unaligned=0;unaligned<4;++unaligned) {
        leaf(1,INPUT+unaligned,lengths[i],1,0);++leaves;
        leaf(0x12345678,INPUT+unaligned,lengths[i],1,0);++leaves;
    }
    leaf(0xffffffffu,INPUT,5553,0,0);++leaves;
    leaf(1,INPUT,5553,0,1);++leaves;
    leaf(1,INPUT,17,1,1);leaf(1,INPUT,17,0,2);leaves+=2;
    leaf(0,0,0,1,0);leaf(99,0,0xffffffffu,1,0);leaves+=2;
    leaf(1,SP-8,7,0,0);++leaves;
    uint32_t invalid[][3]={{1,0,1},{1,0xfffffff0,100},{1,INPUT,0xffffffffu},{1,0x10000,1}};
    for(unsigned i=0;i<4;++i) {
        initialize();native_enabled=1;invalid_probe=1;fallback_probes=0;
        for(unsigned j=0;j<3;++j)MEM32(SP+4+j*4)=invalid[i][j];
        sub_16120040();assert(fallback_probes==1 && native_calls==0 && g_esp==SP);
    }
    for(int i=2;i<argc;++i) {
        f=fopen(argv[i],"rb");assert(f);unsigned char packed[200000];uint32_t size=(uint32_t)fread(packed,1,sizeof packed,f);fclose(f);
        unsigned chunks[]={1,17,4096};
        for(unsigned j=0;j<3;++j) {
            stream_result a=inflate_file(packed,size,0,chunks[j]);
            memcpy(wanted,memory,sizeof memory);
            stream_result b=inflate_file(packed,size,1,chunks[j]);
            stream_native_calls+=native_calls;
            if(memcmp(&a,&b,sizeof a)) {fprintf(stderr,"stream %s chunk%u mismatch status%u/%u used%u/%u out%u/%u\n",argv[i],chunks[j],a.status,b.status,a.in_used,b.in_used,a.out_used,b.out_used);assert(0);}
            if(strstr(argv[i],"-valid.bin")) {
                assert(b.status==1);
                char expected_path[4096];snprintf(expected_path,sizeof expected_path,"%s",argv[i]);
                strcpy(strrchr(expected_path,'.'),".expected");
                FILE *expected=fopen(expected_path,"rb");assert(expected);
                unsigned char expected_data[200000];size_t expected_size=fread(expected_data,1,sizeof expected_data,expected);fclose(expected);
                assert(b.out_used==expected_size && !memcmp(GPTR(OUTPUT),expected_data,expected_size));
            } else if(strstr(argv[i],"bad-checksum") || strstr(argv[i],"bad-header")) {
                assert((int)b.status==-3);
            } else if(strstr(argv[i],"truncated")) {
                assert(b.status!=1);
            }
            memset(wanted+0x6f0000,0,0x10000);memset(memory+0x6f0000,0,0x10000);
            assert(!memcmp(wanted,memory,sizeof memory));++streams;
        }
    }
    assert(stream_native_calls>0);
    printf("%u leaf ABI/memory +4 invalid-range fallback +%u actual original inflate valid/truncated/checksum/header streams (%u native Adler calls) PASS\n",leaves,streams,stream_native_calls);
    return 0;
}
