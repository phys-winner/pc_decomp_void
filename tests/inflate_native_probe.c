/* DECLARATIONS */
#ifdef _WIN32
#include <windows.h>
#else
#include <zlib.h>
#endif
#define GUEST_USER_TOP 0x7ffe0000u
#define BASE 0x20000000u
#define SP (BASE + 0x1f00000u)
#define INPUT (BASE + 0x10000u)
#define OUTPUT (BASE + 0x100000u)
#define STREAM (BASE + 0x1000u)
static unsigned char memory[0x2000000], image[0x400000];
static uint32_t image_size, heap;
static unsigned guest_live, native_live, context_live, original_decode_calls, native_decode_calls;
static int native_enabled, fail_context, fail_native, fail_guest;
static uint32_t guest_blocks[4096];
static unsigned guest_block_count;
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
#ifdef _WIN32
/* Public zlib.h layout on Windows x64: unsigned long is 32 bits here. The
 * staged Android file itself is additionally syntax-checked with NDK zlib.h. */
typedef unsigned char Bytef;
typedef void *(*alloc_func)(void *, unsigned, unsigned);
typedef void (*free_func)(void *, void *);
typedef struct z_stream_s {
    Bytef *next_in; unsigned avail_in; unsigned long total_in;
    Bytef *next_out; unsigned avail_out; unsigned long total_out;
    char *msg; void *state; alloc_func zalloc; free_func zfree; void *opaque;
    int data_type; unsigned long adler, reserved;
} z_stream;
#define Z_OK 0
#define Z_STREAM_ERROR (-2)
#define Z_NULL 0
typedef int (__cdecl *init_api)(z_stream *, int, const char *, int);
typedef int (__cdecl *inflate_api)(z_stream *, int);
typedef int (__cdecl *simple_api)(z_stream *);
typedef const char *(__cdecl *version_api)(void);
static init_api system_init;
static inflate_api system_inflate;
static simple_api system_reset, system_end;
static version_api system_version;
#else
_Static_assert(sizeof(z_stream) == 112, "Android LP64 z_stream layout changed");
typedef int (*init_api)(z_stream *, int, const char *, int);
typedef int (*inflate_api)(z_stream *, int);
typedef int (*simple_api)(z_stream *);
typedef const char *(*version_api)(void);
static init_api system_init = inflateInit2_;
static inflate_api system_inflate = inflate;
static simple_api system_reset = inflateReset, system_end = inflateEnd;
static version_api system_version = zlibVersion;
#undef inflateInit2
#endif
static void *native_allocate(void *opaque, unsigned n, unsigned size) {
    (void)opaque;
    if (fail_native) return NULL;
    void *p = calloc(n,size); if(p) ++native_live; return p;
}
static void native_release(void *opaque, void *p) { (void)opaque; if(p) {assert(native_live);--native_live;free(p);} }
static int qa_init(z_stream *s, int bits) {
    s->zalloc=native_allocate;s->zfree=native_release;
    return system_init(s,bits,system_version(),sizeof *s);
}
static int qa_inflate(z_stream *s,int flush) { ++native_decode_calls;return system_inflate(s,flush); }
static void *qa_context_alloc(size_t n,size_t size) {
    if(fail_context) return NULL;
    void *p=calloc(n,size);if(p)++context_live;return p;
}
static void qa_context_free(void *p) {if(p){assert(context_live);--context_live;free(p);}}
#define inflateInit2 qa_init
#define inflate qa_inflate
#define inflateReset system_reset
#define inflateEnd system_end
/* PROTOTYPES */
#define calloc qa_context_alloc
#define free qa_context_free
/* HELPER */
#undef calloc
#undef free
static void allocate(void) {
    uint32_t count=MEM32(g_esp+8),size=MEM32(g_esp+12);
    if(fail_guest){g_eax=0;g_esp+=4;return;}
    assert(count && size && count <= 0x10000u/size);
    g_eax=heap;memset(GPTR(heap),0,count*size);
    guest_blocks[guest_block_count++]=heap;
    heap+=(count*size+15u)&~15u;assert(heap<BASE+0x1e00000u);
    ++guest_live;g_esp+=4;
}
static void release(void) {
    uint32_t p=MEM32(g_esp+8);unsigned i;
    for(i=0;i<guest_block_count;++i)if(guest_blocks[i]==p)break;
    assert(i<guest_block_count && guest_live);guest_blocks[i]=0;--guest_live;g_esp+=4;
}
recomp_func_t void_resolve(uint32_t at) {
    if(at==0x161467b0u || at==0x30000010u)return allocate;
    if(at==0x161467a0u || at==0x30000020u)return release;
    fprintf(stderr,"unexpected callback %08x\n",at);assert(0);return NULL;
}
void sub_1612A0F0(void) {
    uint32_t dst=MEM32(g_esp+4),src=MEM32(g_esp+8),size=MEM32(g_esp+12);
    if(size)memmove(GPTR(dst),GPTR(src),size);g_eax=dst;g_esp+=4;
}
void sub_16125D86(void) {assert(g_ecx==MEM32(0x1633d310u));g_esp+=4;}
/* EMITTED */
#undef eax
#undef ecx
#undef edx
#undef ebx
#undef esp
#undef ebp
#undef esi
#undef edi
static void initialize(int enabled) {
    assert(!inflate_owners && !guest_live && !native_live && !context_live);
    memset(memory,0,sizeof memory);
    g_eax=0x11223344;g_ecx=0x55667788;g_edx=0x99887766;g_ebx=0xf1234567;
    g_esp=SP;g_ebp=0xe2345678;g_esi=0xd3456789;g_edi=0xc456789a;
    g_flag_k=FK_EFLAGS;g_flag_a=0x855;g_flag_b=0;g_flag_cf=1;
    g_fs_base=BASE+0x800;g_gs_base=0;g_fp_top=0;g_fpu_cw=0x37f;g_mxcsr=0x1f80;
    g_backedges=0;recomp_yield_hook=NULL;heap=BASE+0x500000;
    guest_block_count=0;original_decode_calls=native_decode_calls=0;
    native_enabled=enabled;fail_context=fail_native=fail_guest=0;
}
static int invoke(void (*fn)(void),const uint32_t *args,unsigned count) {
    uint32_t keep[]={g_ebx,g_ebp,g_esi,g_edi};
    g_esp=SP;MEM32(SP)=0x30000000;
    for(unsigned i=0;i<count;++i)MEM32(SP+4+i*4)=args[i];
    fn();assert(g_esp==SP+4);
    assert(g_ebx==keep[0]&&g_ebp==keep[1]&&g_esi==keep[2]&&g_edi==keep[3]);
    return (int)g_eax;
}
typedef struct {uint32_t fields[14];int status;char message[128];} record;
static record records[300000];static unsigned record_count, expected_count, compared, cases;
static unsigned char expected_output[0x100000];static uint32_t expected_length;
static void checkpoint(uint32_t stream,int status,int enabled,const char *label) {
    record r={0};memcpy(r.fields,GPTR(stream),56);r.status=status;
    if(r.fields[6])snprintf(r.message,sizeof r.message,"%s",(const char *)GPTR(r.fields[6]));
    /* Retain each lifetime's original anchor. Different allocation histories
     * need not return the same absolute address on a later new lifetime. */
    inflate_owner *owner=*inflate_slot(stream);
    if(owner)assert(r.fields[7]==owner->anchor||(!r.fields[7]&&status==-2));
    if(r.fields[7])assert(void_vm_readable(r.fields[7],9520));
    r.fields[7]=r.fields[7]!=0;
    if(!enabled)records[record_count++]=r;
    else {
        record *a=&records[record_count++];
        if(memcmp(a,&r,sizeof r)) {
            fprintf(stderr,"MISMATCH %s call%u status%d/%d msg'%s'/'%s'\n",label,record_count,a->status,r.status,a->message,r.message);
            for(unsigned i=0;i<14;++i)if(a->fields[i]!=r.fields[i])fprintf(stderr," field+%u=%08x/%08x\n",i*4,a->fields[i],r.fields[i]);
            exit(3);
        }
        ++compared;
    }
    assert(record_count<300000);
}
static int start(uint32_t stream,int bits,int custom,int enabled,const char *label) {
    memset(GPTR(stream),0,56);MEM32(stream+44)=0x1234;MEM32(stream+52)=0x5678;
    if(custom){MEM32(stream+32)=0x30000010;MEM32(stream+36)=0x30000020;MEM32(stream+40)=0x654321;}
    uint32_t version=BASE+0x2000;memcpy(GPTR(version),"1.2.3",6);
    uint32_t args[]={stream,(uint32_t)bits,version,56};int r=invoke(sub_1611E830,args,4);
    checkpoint(stream,r,enabled,label);return r;
}
static int step(uint32_t stream,int flush,int enabled,const char *label) {
    uint32_t args[]={stream,(uint32_t)flush};int r=invoke(sub_1611E9F0,args,2);checkpoint(stream,r,enabled,label);return r;
}
static void end(uint32_t stream,int enabled,const char *label) {
    uint32_t args[]={stream};int r=invoke(sub_1611FFF0,args,1);checkpoint(stream,r,enabled,label);assert(!r);
}
static void run(const unsigned char *packed,uint32_t length,int enabled,unsigned in_chunk,unsigned out_chunk,int flush,int bits,int custom,int fail,int reset,const char *label) {
    initialize(enabled);memcpy(GPTR(INPUT),packed,length);record_count=0;
    fail_context=fail==1;fail_native=fail==2;fail_guest=fail==3;
    int r=start(STREAM,bits,custom,enabled,label);
    fail_context=fail_native=fail_guest=0;
    unsigned rounds=0;
    if(r==0) {
        for(int pass=0;pass<=reset;++pass) {
            MEM32(STREAM)=INPUT;MEM32(STREAM+4)=0;MEM32(STREAM+12)=OUTPUT;MEM32(STREAM+16)=0;
            /* Zero output is a public contract check before actual progress. */
            step(STREAM,flush,enabled,label);
            if(fail==4)fail_guest=fail_native=1; /* Deferred window allocation. */
            while(++rounds<200000) {
                uint32_t supplied=MEM32(STREAM)-INPUT+MEM32(STREAM+4);
                if(!MEM32(STREAM+4)&&supplied<length)MEM32(STREAM+4)=length-supplied<in_chunk?length-supplied:in_chunk;
                MEM32(STREAM+16)=out_chunk;
                uint32_t before_in=MEM32(STREAM),before_out=MEM32(STREAM+12);
                r=step(STREAM,flush,enabled,label);
                if(r==1||r==2||(r<0&&r!=-5))break;
                if(MEM32(STREAM)==before_in&&MEM32(STREAM+12)==before_out&&supplied==length)break;
                assert(MEM32(STREAM+12)<OUTPUT+sizeof expected_output);
            }
            uint32_t n=MEM32(STREAM+12)-OUTPUT;
            if(!enabled){memcpy(expected_output,GPTR(OUTPUT),n);expected_length=n;}
            else assert(n==expected_length&&!memcmp(expected_output,GPTR(OUTPUT),n));
            if(pass<reset){uint32_t args[]={STREAM};r=invoke(sub_1611E7D0,args,1);checkpoint(STREAM,r,enabled,label);assert(!r);}
        }
        fail_guest=fail_native=0;
        end(STREAM,enabled,label);
        uint32_t args[]={STREAM};r=invoke(sub_1611FFF0,args,1);checkpoint(STREAM,r,enabled,label);assert(r==-2);
    }
    assert(rounds<200000 && !inflate_owners && !guest_live && !native_live && !context_live);
    if(!enabled)expected_count=record_count;else{assert(record_count==expected_count);++cases;}
    if(enabled&&!custom&&(!fail||fail==4)&&r!=-6&&bits>=-15&&bits<=47)assert(native_decode_calls);
    if(enabled&&(custom||(fail&&fail<4)))assert(!native_decode_calls);
}
static void ownership(const unsigned char *packed,uint32_t length,int enabled,const char *label) {
    initialize(enabled);memcpy(GPTR(INPUT),packed,length);record_count=0;
    uint32_t streams[]={STREAM,STREAM+0x80,STREAM+0x100};
    int finished[]={0,0,0};
    for(unsigned i=0;i<3;++i) {
        assert(start(streams[i],47,i==2,enabled,label)==0);
        MEM32(streams[i])=INPUT;MEM32(streams[i]+4)=0;
        MEM32(streams[i]+12)=OUTPUT+i*0x40000;
    }
    unsigned rounds=0;
    while(++rounds<200000) {
        native_enabled=(rounds%3)==0; /* Ownership must survive both changes. */
        for(unsigned i=0;i<3;++i)if(!finished[i]) {
            uint32_t s=streams[i],supplied=MEM32(s)-INPUT+MEM32(s+4);
            unsigned in_chunk=i==0?1:i==1?17:4096,out_chunk=i==0?7:i==1?1:11;
            if(!MEM32(s+4)&&supplied<length)MEM32(s+4)=length-supplied<in_chunk?length-supplied:in_chunk;
            MEM32(s+16)=out_chunk;int r=step(s,2,enabled,label);
            assert(r==0||r==1||r==-5);finished[i]=r==1;
            if(i==0&&rounds==2)for(unsigned field=28;field<=36;field+=8) {
                uint32_t saved=MEM32(s+field),args[]={s};MEM32(s+field)=0;
                assert(invoke(sub_1611FFF0,args,1)==-2);checkpoint(s,-2,enabled,label);
                if(field==28) {
                    assert(invoke(sub_1611E7D0,args,1)==-2);checkpoint(s,-2,enabled,label);
                    assert(step(s,2,enabled,label)==-2);
                }
                MEM32(s+field)=saved; /* Next normal step must resume progress. */
            }
            if(i==1&&rounds==2) {
                /* Seek/rewind while another stream remains partially consumed. */
                uint32_t args[]={s};assert(invoke(sub_1611E7D0,args,1)==0);checkpoint(s,0,enabled,label);
                MEM32(s)=INPUT;MEM32(s+4)=0;MEM32(s+12)=OUTPUT+i*0x40000;
                finished[i]=0;
            }
        }
        if(finished[0]&&finished[1]&&finished[2])break;
    }
    assert(rounds<200000);
    /* End in a different order from creation, then reuse the same stream VA. */
    end(streams[1],enabled,label);end(streams[0],enabled,label);end(streams[2],enabled,label);
    native_enabled=enabled;assert(start(STREAM,47,0,enabled,label)==0);
    MEM32(STREAM)=INPUT;MEM32(STREAM+4)=length;MEM32(STREAM+12)=OUTPUT+0xc0000;MEM32(STREAM+16)=1;
    assert(step(STREAM,2,enabled,label)>=0);end(STREAM,enabled,label); /* Early End. */
    assert(!inflate_owners&&!guest_live&&!native_live&&!context_live);
    if(!enabled){expected_count=record_count;memcpy(expected_output,GPTR(OUTPUT),sizeof expected_output);}
    else{assert(record_count==expected_count&&!memcmp(expected_output,GPTR(OUTPUT),sizeof expected_output));++cases;}
}
static void init_contract(int enabled,int bits,int version_kind,int size,int allocators) {
    initialize(enabled);record_count=0;
    memset(GPTR(STREAM),0,56);MEM32(STREAM+44)=0x1234;MEM32(STREAM+52)=0x5678;
    MEM32(STREAM+40)=0x765432;
    if(allocators&1)MEM32(STREAM+32)=0x30000010;
    if(allocators&2)MEM32(STREAM+36)=0x30000020;
    if(allocators&4){MEM32(STREAM+32)=0x161467b0;MEM32(STREAM+36)=0x161467a0;}
    uint32_t version=BASE+0x2000;
    strcpy((char *)GPTR(version),version_kind==1?"2.0.0":"1.9.99");
    uint32_t args[]={STREAM,(uint32_t)bits,version_kind==2?0:version,(uint32_t)size};
    int r=invoke(sub_1611E830,args,4);checkpoint(STREAM,r,enabled,"init contract");
    if(r==0)end(STREAM,enabled,"init contract");
    assert(!inflate_owners&&!guest_live&&!native_live&&!context_live);
    if(!enabled)expected_count=record_count;else{assert(record_count==expected_count);++cases;}
}
static void duplicate_init_safety(void) {
    initialize(1);record_count=0;
    assert(start(STREAM,47,0,0,"duplicate init safety")==0);
    uint32_t anchor=MEM32(STREAM+28),args[]={STREAM,47,BASE+0x2000,56};
    assert(invoke(sub_1611E830,args,4)==-2);
    assert(MEM32(STREAM+28)==anchor&&guest_live==1&&context_live==1);
    /* Baseline zlib itself leaks on duplicate Init without End. The prototype
     * rejects that API misuse instead of orphaning the managed lifetime. */
    uint32_t end_args[]={STREAM};assert(invoke(sub_1611FFF0,end_args,1)==0);
    assert(!inflate_owners&&!guest_live&&!native_live&&!context_live);
}
int main(int argc,char **argv) {
    assert(argc>2);
#ifdef _WIN32
HMODULE lib=LoadLibraryA("C:/Program Files/Git/mingw64/bin/zlib1.dll");assert(lib);
    system_init=(init_api)GetProcAddress(lib,"inflateInit2_");system_inflate=(inflate_api)GetProcAddress(lib,"inflate");
    system_reset=(simple_api)GetProcAddress(lib,"inflateReset");system_end=(simple_api)GetProcAddress(lib,"inflateEnd");
    system_version=(version_api)GetProcAddress(lib,"zlibVersion");assert(system_init&&system_inflate&&system_reset&&system_end&&system_version);
#else
    printf("Android ARM64 system libz %s; z_stream=%zu; uLong=%zu; pointers=%zu\n",
        system_version(), sizeof(z_stream), sizeof(uLong), sizeof(void *));
    fflush(stdout);
#endif
    FILE *f=fopen(argv[1],"rb");assert(f);image_size=(uint32_t)fread(image,1,sizeof image,f);fclose(f);
    int bits_contract[]={-100,-15,-8,0,7,8,15,16,24,31,32,40,47,48,100};
    for(unsigned b=0;b<sizeof bits_contract/sizeof bits_contract[0];++b)
        for(int v=0;v<3;++v)for(int size=55;size<=57;++size)for(int a=0;a<5;++a)
            for(int mode=0;mode<2;++mode)init_contract(mode,bits_contract[b],v,size,a);
    duplicate_init_safety();
    for(int i=2;i<argc;++i) {
        f=fopen(argv[i],"rb");assert(f);unsigned char packed[200000];uint32_t n=(uint32_t)fread(packed,1,sizeof packed,f);fclose(f);
        int bits=strstr(argv[i],"-raw-")?-15:47;
        const unsigned chunks[][2]={{1,1},{17,7},{4096,17},{17,4096},{4096,4096}};
        int flushes[]={0,1,2,3,4,5,-1,6,99};
        for(unsigned c=0;c<sizeof chunks/sizeof chunks[0];++c)for(unsigned q=0;q<sizeof flushes/sizeof flushes[0];++q)
            for(int mode=0;mode<2;++mode)run(packed,n,mode,chunks[c][0],chunks[c][1],flushes[q],bits,0,0,0,argv[i]);
        if(i==2)for(int failure=0;failure<4;++failure)for(int custom=0;custom<2;++custom)for(int mode=0;mode<2;++mode)
            run(packed,n,mode,17,7,2,bits,custom,failure,1,argv[i]);
        if(strstr(argv[i],"stream-2-zlib-valid")) {
            for(int mode=0;mode<2;++mode)ownership(packed,n,mode,argv[i]);
            for(int custom=0;custom<2;++custom)for(int mode=0;mode<2;++mode)run(packed,n,mode,17,7,2,bits,custom,4,0,argv[i]);
        }
    }
    printf("%u cases, %u per-call public/ABI/output checkpoints against original zlib1.2.3, native zlib%s PASS\n",cases,compared,system_version());
    return 0;
}
