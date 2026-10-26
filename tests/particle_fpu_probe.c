/* Original emitted particle interpolation versus the production local-x87 copy. */
/* DECLARATIONS */

#define BASE 0x20000000u
#define HEADER (BASE + 0x1000u)
#define RECORDS (BASE + 0x2000u)
#define OUTPUT (BASE + 0x20000u)
#define SP (BASE + 0x3f000u)
#define CONSTANT_BASE 0x162d0000u
#define CONSTANT_BYTES 0xa0000u
#define GUEST_USER_TOP 0x7ffe0000u
static unsigned char memory[0x40000], initial_memory[0x40000], wanted_memory[0x40000];
static unsigned char constants[CONSTANT_BYTES], canonical_constants[CONSTANT_BYTES];
static unsigned char initial_constants[CONSTANT_BYTES], wanted_constants[CONSTANT_BYTES];
static void *guest_address(uint32_t at) {
    if (at >= CONSTANT_BASE && at < CONSTANT_BASE + CONSTANT_BYTES) return constants + at - CONSTANT_BASE;
    assert(at >= BASE && at < BASE + sizeof memory);
    return memory + at - BASE;
}
static int native_enabled = 1;
int void_renderer_native_enabled(void) { return native_enabled; }
/* GUARD */
/* ORIGINALS */
/* LOCALIZED */
/* SNAPSHOTS */

typedef struct { snapshot cpu; uint64_t memory_hash, constant_hash; } checkpoint;
static checkpoint observed_yields[4200], wanted_yields[4200];
static unsigned yield_count, wanted_yield_count, cases, fast_cases, fallback_cases, perturb;
static int check_yield_memory;
static uint32_t random_state = 0x72bf1a39u;
static uint32_t random32(void) {
    random_state ^= random_state << 13; random_state ^= random_state >> 17;
    random_state ^= random_state << 5; return random_state;
}
static void put_float(uint32_t at, float value) { memcpy(guest_address(at), &value, 4); }
static uint64_t hash_bytes(const unsigned char *bytes, size_t count) {
    uint64_t hash=UINT64_C(0xcbf29ce484222325);
    for (size_t i=0;i<count;++i) hash=(hash^bytes[i])*UINT64_C(0x100000001b3);
    return hash;
}

static void yield_hook(void) {
    assert(yield_count < 4200);
    checkpoint *at=&observed_yields[yield_count++];
    at->cpu=state();
    at->memory_hash=check_yield_memory ? hash_bytes(memory,sizeof memory) : 0;
    at->constant_hash=check_yield_memory ? hash_bytes(constants,sizeof constants) : 0;
    if (perturb) {
        if (isfinite(g_st[0])) g_st[0] += 1.0 / 1024;
        g_st_i64[0] ^= INT64_C(0x12345678);
        g_st_i64[7] ^= INT64_C(0x76543210);
        uint64_t bits; memcpy(&bits, g_st + 7, 8); bits ^= UINT64_C(0x10000000); memcpy(g_st + 7, &bits, 8);
        ++g_fp_top;
        g_xmm[2].u32[3] ^= 0x12345678u;
        /* The next record can be edited while the machine lock is handed over. */
        if (yield_count == 1) put_float(RECORDS + 24 + 12, 2.5f);
    }
}

static void initialize(unsigned count, unsigned type) {
    memset(memory, 0xcc, sizeof memory);
    memcpy(constants, canonical_constants, sizeof constants);
    g_eax=random32(); g_ecx=HEADER; g_edx=random32(); g_ebx=random32();
    g_esp=SP; g_ebp=random32(); g_esi=random32(); g_edi=OUTPUT;
    g_flag_k=FK_EFLAGS; g_flag_a=random32() & 0x8d5u; g_flag_b=0; g_flag_cf=random32() & 1;
    for (unsigned i=0; i<8; ++i) {
        for (unsigned j=0; j<4; ++j) g_xmm[i].u32[j]=random32();
        g_mm[i]=((uint64_t)random32()<<32)|random32();
        g_st[i]=(int32_t)random32()/65536.0;
        g_st_i64[i]=(int64_t)(((uint64_t)random32()<<32)|random32());
    }
    g_fp_top=0; g_fpu_cw=(uint16_t)(0x7f|((random32()%4)<<10)|((random32()%3)<<8));
    g_mxcsr=0x1f80; g_cur_func=random32(); g_backedges=0; void_fpu_cmp=(int)(random32()%8);
    MEM32(HEADER)=0;
    MEM32(HEADER+4)=RECORDS; MEM32(HEADER+8)=RECORDS+24*count;
    MEM32(SP)=0x30000000u; MEM32(SP+4)=random32();
    for (unsigned i=0; i<count; ++i) {
        uint32_t at=RECORDS+i*24;
        MEM32(at)=i%64; MEM32(at+4)=random32(); MEM32(at+8)=type;
        put_float(at+12,(int32_t)(random32()%2049)-1024);
        put_float(at+16,(int32_t)(random32()%2049)-1024);
        if (type==1) put_float(at+20,(int32_t)(random32()%2049)-1024);
        else MEM32(at+20)=random32();
    }
    native_enabled=1;
}

static void differential(unsigned yields, int expected_guard) {
    recomp_yield_hook=yields ? yield_hook : NULL;
    snapshot before=state();
    memcpy(initial_memory,memory,sizeof memory); memcpy(initial_constants,constants,sizeof constants);
    int guard=void_renderer_particle_finite();
    /* The guard must not change emulated CPU state or guest memory. */
    snapshot guarded=state(); assert(!memcmp(&before,&guarded,sizeof before));
    assert(!memcmp(initial_memory,memory,sizeof memory) && !memcmp(initial_constants,constants,sizeof constants));
    if (expected_guard>=0 && guard!=expected_guard) {
        fprintf(stderr,"case %u guard %d != %d\n",cases,guard,expected_guard); assert(0);
    }
    if (guard) ++fast_cases; else ++fallback_cases;
    yield_count=0;
    original_particle(); snapshot wanted=state();
    memcpy(wanted_memory,memory,sizeof memory); memcpy(wanted_constants,constants,sizeof constants);
    wanted_yield_count=yield_count; memcpy(wanted_yields,observed_yields,yield_count*sizeof(checkpoint));
    restore(before); memcpy(memory,initial_memory,sizeof memory); memcpy(constants,initial_constants,sizeof constants);
    yield_count=0; sub_160902D0(); snapshot observed=state();
    if (memcmp(&wanted,&observed,sizeof wanted) || memcmp(wanted_memory,memory,sizeof memory)
            || memcmp(wanted_constants,constants,sizeof constants) || yield_count!=wanted_yield_count
            || memcmp(wanted_yields,observed_yields,yield_count*sizeof(checkpoint))) {
        fprintf(stderr,"case %u mismatch: guard=%d yields=%u perturb=%u count=%u\n",
                cases,guard,yields,perturb,(MEM32(HEADER+8)-MEM32(HEADER+4))/24);
        const unsigned char *a=(const unsigned char *)&wanted,*b=(const unsigned char *)&observed;
        for (unsigned i=0;i<sizeof wanted;++i) if (a[i]!=b[i]) {fprintf(stderr,"state byte %u: %02x != %02x\n",i,a[i],b[i]);break;}
        for (unsigned i=0;i<sizeof memory;++i) if (wanted_memory[i]!=memory[i]) {fprintf(stderr,"memory byte %u\n",i);break;}
        assert(0);
    }
    ++cases;
}

int main(int argc,char **argv) {
    assert(argc==2);
    FILE *file=fopen(argv[1],"rb"); assert(file);
    assert(fread(canonical_constants,1,sizeof canonical_constants,file)==sizeof canonical_constants); fclose(file);
    memcpy(constants,canonical_constants,sizeof constants);
    /* Runtime noise tables: a permutation and finite gradients, independent of the tested transform. */
    for (unsigned i=0;i<256;++i) {
        MEM32(0x1635ff38u+i*4)=(i*37u+17u)&255u;
        put_float(0x16362f68u+i*4,((int)i-128)/128.f);
    }
    memcpy(canonical_constants,constants,sizeof constants);
    static const uint32_t scalar[]={0x162d2a54u,0x162ec318u,0x162ec31cu,0x162ec320u,0x162ec324u,0x162ec354u};
    static const uint32_t special[]={0,0x80000000u,1,0x807fffffu,0x44800000u,0xc4800000u,
        0x44800001u,0x7f800000u,0xff800000u,0x7fc12345u,0x7f812345u,0xff812345u,0x7f7fffffu};
    for (unsigned mode=0;mode<3;++mode) {
        perturb=mode==2;
        for (unsigned n=0;n<600;++n) {
            initialize(n%9,n%3); differential(mode!=0,1);
        }
        for (unsigned type=0;type<2;++type) {
            initialize(0,type); differential(mode!=0,1);
            initialize(4096,type); differential(mode!=0,1);
            initialize(4097,type); differential(mode!=0,0);
            for (unsigned bits=0;bits<sizeof special/sizeof special[0];++bits) for (unsigned field=12;field<=20;field+=4) {
                initialize(2,type); MEM32(RECORDS+field)=special[bits];
                int expected=(field==20 && type!=1) || (special[bits]&0x7fffffffu)<=0x44800000u;
                differential(mode!=0,expected);
            }
            static const uint32_t ticks[]={0,1,0x7fffffffu,0x80000000u,0xffffffffu};
            for (unsigned i=0;i<5;++i) for (unsigned j=0;j<5;++j) {
                initialize(3,type); MEM32(SP+4)=ticks[i];
                for (unsigned n=0;n<3;++n) MEM32(RECORDS+n*24+4)=ticks[j];
                differential(mode!=0,1);
            }
        }
        for (unsigned i=0;i<6;++i) {
            initialize(2,1); MEM32(scalar[i])^=1; differential(mode!=0,0);
        }
        for (unsigned i=1;i<8;++i) {initialize(2,1);g_fp_top=(int)i;differential(mode!=0,0);}
        initialize(2,1); native_enabled=0; differential(mode!=0,0);
        initialize(2,1);g_edi=OUTPUT+0x100;MEM32(RECORDS)=0xffffffc0u;differential(mode!=0,1);
        /* All source/destination alias classes remain on the exact global fallback. */
        static const uint32_t aliases[]={HEADER,HEADER+4,HEADER+8,RECORDS,RECORDS+4,RECORDS+12,
            SP-48,SP-32,SP-24,SP,SP+4,0x162d2a54u,0x162ec318u,0x162ec354u,0x1635ff38u,0x16362f68u};
        for (unsigned i=0;i<sizeof aliases/sizeof aliases[0];++i) {
            initialize(1,1); MEM32(RECORDS)=(aliases[i]-OUTPUT)/4u; differential(0,0);
        }
        static const uint32_t array_aliases[]={HEADER,SP-48,0x162d2a54u,0x162ec318u,0x1635ff38u,0x16362f68u};
        for (unsigned i=0;i<sizeof array_aliases/sizeof array_aliases[0];++i) {
            initialize(1,1); uint32_t at=array_aliases[i];
            memcpy(guest_address(at),guest_address(RECORDS),24);
            MEM32(HEADER+4)=at;MEM32(HEADER+8)=at+24; differential(0,0);
        }
    }
    perturb=1;check_yield_memory=1;
    initialize(3,1); differential(1,1);
    check_yield_memory=0;
    initialize(0,1);MEM32(HEADER+4)=MEM32(HEADER+8)=0;differential(0,0);
    initialize(2,1);MEM32(HEADER+8)=RECORDS-24;assert(!void_renderer_particle_finite());
    initialize(2,1);MEM32(HEADER+8)=RECORDS+25;assert(!void_renderer_particle_finite());
    initialize(2,1);g_ecx=0;assert(!void_renderer_particle_finite());
    initialize(2,1);g_esp=0x1003f;assert(!void_renderer_particle_finite());
    initialize(2,1);g_edi=0x8000;assert(!void_renderer_particle_finite());
    assert(fast_cases && fallback_cases);
    printf("PASS particle local x87 cases=%u fast=%u fallback=%u: exact emitted oracle, real guard, full memory/constants/CPU and scheduler snapshots\n",
            cases,fast_cases,fallback_cases);
    return 0;
}
