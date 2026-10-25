static unsigned native_calls, fallback_calls;
static unsigned force_yield, scheduler_yields, scheduler_sat_yields;
void sub_16013760(void) {
    if (void_renderer_region_calculate()) ++native_calls;
    else { ++fallback_calls; original_region(); }
}

static void initialize_native(unsigned kind, unsigned n) {
    unsigned count = kind == 3 ? 512 : kind == 13 ? 600 : kind == 4 ? 0 : 1 + random32() % 64;
    initialize(count, kind & 1);
    MEM32(TREE + 4) = 12;
    MEM32(LEAVES + 12) = random32();
    for (unsigned i = 0; i < 3; ++i) {
        float a = random_float() * .125f, size = fabsf(random_float()) * .125f;
        put(BOX + i * 4, a); put(BOX + 12 + i * 4, a + size);
        float q = random_float() * .125f, half = fabsf(random_float()) * .125f;
        put(QUERY + i * 4, q - half); put(QUERY + 12 + i * 4, q + half);
        put(OBB + i * 4, kind == 2 ? 1000.f : q);
        put(OBB + 12 + i * 4, half);
    }
    if (kind == 1) {
        float angle = random_float(); float c = cosf(angle), s = sinf(angle);
        float rotation[] = {c,s,0,-s,c,0,0,0,1};
        for (unsigned i = 0; i < 9; ++i) put(OBB + 24 + i * 4, rotation[i]);
    }
    if (kind == 4) for (unsigned i = 0; i < 6; ++i) {
        MEM32(BOX + i * 4) = (random32() & 1) ? 0x80000000u : 0;
        MEM32(QUERY + i * 4) = (random32() & 1) ? 0x80000000u : 0;
    }
    if (kind == 5 || kind == 6 || kind == 13)
        for (unsigned i = 0; i < count; ++i) MEM8(RECORDS + 4 + i * 3u) = kind == 5 ? 0 : 255;
    if (kind == 7) MEM32(BOX + (n % 6) * 4) = n & 1 ? 0x7f812345u : 0xff800000u;
    if (kind == 8) MEM32(CTX + 12) = BOX;
    if (kind == 9) { MEM16(RECORDS) = 1; MEM16(RECORDS + 2) = 0; MEM8(RECORDS + 4) = 0; MEM32(CTX + 12) = RECORDS; }
    if (kind == 10) g_fp_top = 1;
    if (kind == 11) MEM32(CTX + 20) = 0x7f812345u;
    if (kind == 12) put(BOX, 1e30f);
    if (kind == 14 || kind == 15) {
        MEM16(RECORDS) = 2;
        MEM16(RECORDS + 2) = MEM16(RECORDS + 5) = 0;
        MEM8(RECORDS + 4) = MEM8(RECORDS + 7) = 1;
        for (unsigned i = 0; i < 24; ++i) MEM32(COUNTS + i * 4) = 0x80000000u;
        for (unsigned i = 0; i < 6; ++i) {
            MEM32(BOX + i * 4) = kind == 14 ? 0x80000000u : 0x3f800000u;
            MEM32(QUERY + i * 4) = MEM32(BOX + i * 4);
            MEM32(OBB + i * 4) = 0;
        }
    }
    if (kind == 16) {
        MEM32(CTX + 8) = SP - 128;
        for (unsigned i = 0; i < 6; ++i) put(SP - 128 + i * 4, i < 3 ? -1.f : 1.f);
        MEM16(RECORDS) = 1; MEM8(RECORDS + 4) = 255;
    }
    if (kind == 17) MEM32(OBB + 24 + (n % 9) * 4) = n & 1 ? 0x7f812345u : 0x3f800001u;
    if (kind == 18) for (unsigned i = 0; i < 3; ++i) {
        MEM32(BOX + i * 4) = 0xcd7fffffu; MEM32(BOX + 12 + i * 4) = 0x4d7fffffu;
        MEM32(QUERY + i * 4) = 0xcd7fffffu; MEM32(QUERY + 12 + i * 4) = 0x4d7fffffu;
    }
    if (kind == 19) {
        MEM16(RECORDS) = 0;
        MEM32(LEAVES + 12) = (n << 24) | ((n & 1) ? 0x00ffffffu : 0x00010001u);
    }
    if (kind == 21) {MEM32(TREE+4)=6;MEM16(RECORDS+2)=11;}
    if (kind == 20) {
        static const uint32_t values[] = {0,0x80000000u,1,0x807fffffu,0x7f800000u,0xff800000u,
            0x7fc12345u,0x7f812345u,0xff812345u,0x7f7fffffu,0xff7fffffu};
        for (unsigned i = 0; i < 24; ++i) MEM32(COUNTS + i * 4) = values[(n + i) % 11];
    }
}

static void scheduler_switch(void) {
    state interrupted = capture();
    unsigned char interrupted_memory[sizeof memory];
    memcpy(interrupted_memory, memory, sizeof memory);
    uint32_t interrupted_random = random_state;
    /* An independent guest frame overwrites global CPU and guest-memory state
     * while native locals remain suspended on this thread's C stack. */
    recomp_yield_hook = NULL;
    initialize_native(6, 0);
    original_region();
    memcpy(memory, interrupted_memory, sizeof memory);
    restore(interrupted);
    random_state = interrupted_random;
    recomp_yield_hook = scheduler_switch;
    ++scheduler_yields;
    scheduler_sat_yields += interrupted.current == 0x160d6ed0u;
}

static void differential_native(unsigned kind) {
    state before = capture(); memcpy(initial_memory, memory, sizeof memory);
    recomp_yield_hook = force_yield ? scheduler_switch : NULL;
    original_region(); state wanted = capture(); memcpy(wanted_memory, memory, sizeof memory);
    restore(before); memcpy(memory, initial_memory, sizeof memory);
    unsigned previous_native = native_calls;
    scheduler_sat_yields = 0;
    sub_16013760(); state actual = capture();
    if (force_yield) assert(scheduler_sat_yields > 0 && native_calls == previous_native + 1);
    for (unsigned i = 0; i < sizeof memory; ++i) {
        if (i >= SP - BASE - 512 && i < SP - BASE) continue;
        if (wanted_memory[i] != memory[i]) {
            fprintf(stderr, "case %u kind %u memory %u %02x/%02x native=%u\n",
                    cases, kind, i, wanted_memory[i], memory[i], native_calls != previous_native);
            assert(0);
        }
    }
    for (unsigned i = 3; i < 8; ++i) if (i != 4) assert(wanted.regs[i] == actual.regs[i]);
    assert(actual.top == wanted.top && actual.regs[4] == SP + 16 && !(actual.regs[0] & 255u));
    assert(!memcmp(actual.st, wanted.st, (size_t)actual.top * sizeof(double)));
    assert(!memcmp(actual.flags, wanted.flags, sizeof actual.flags));
    if ((kind >= 7 && kind <= 13) || kind == 16 || kind == 17 || kind == 21 || !enabled) assert(native_calls == previous_native);
    ++cases;
}

int main(void) {
    for (unsigned kind = 0; kind < 22; ++kind) for (unsigned n = 0; n < (kind == 19 ? 256u : 180u); ++n) {
        enabled = 1; initialize_native(kind, n); differential_native(kind);
        if (n < 3) { enabled = 0; initialize_native(kind, n); differential_native(kind); }
    }
    assert(native_calls > 1000 && fallback_calls > 1000);
    enabled = 1; initialize_native(0, 0);MEM16(RECORDS)=64;
    for(unsigned i=0;i<64;++i)MEM16(RECORDS+2+i*3)=0;
    MEM16(RECORDS+2+63*3)=65535;
    state invalid_before=capture();memcpy(initial_memory,memory,sizeof memory);
    assert(!void_renderer_region_calculate());state invalid_after=capture();
    assert(!memcmp(&invalid_before,&invalid_after,sizeof invalid_before));assert(!memcmp(initial_memory,memory,sizeof memory));
#ifdef REGION_PRODUCTION_HELPERS
    /* Force the native caller's first SAT backedge to hand over, using the
     * production interval rather than changing the runtime macro. */
    initialize_native(0, 0); enabled = 1;
    MEM16(RECORDS) = 1; MEM16(RECORDS + 2) = 0; MEM8(RECORDS + 4) = 1;
    for (unsigned i = 0; i < 6; ++i) {
        put(BOX + i * 4, i < 3 ? -1.f : 1.f);
        put(QUERY + i * 4, i < 3 ? -1.f : 1.f);
        put(OBB + i * 4, i < 3 ? 0.f : 1.f);
    }
    g_backedges = RECOMP_YIELD_EVERY - 1; force_yield = 1;
    differential_native(0);
    assert(scheduler_yields >= 2);
    printf("PASS production helper scheduler switch: native SAT yields=%u\n", scheduler_sat_yields);
#endif
    printf("PASS native region cases=%u native=%u fallback=%u: complete live guest memory, callee-saved GPR, AL/ESP/flags and live x87; exact emitted region/RGBE/SAT oracle; all256 RGBE exponents, mixed masks/weights/rotations, 0/512/600 entries, signed-zero/cached-rejection/boundary cells, IEEE/alias/nonempty-x87 fallback\n",
           cases, native_calls, fallback_calls);
    return 0;
}
