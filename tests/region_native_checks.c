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

static void differential_sat(void) {
    initialize_native(0, 0);
    for (unsigned n = 0; n < 12000; ++n) {
        float a[6], b[15];
        for (unsigned i = 0; i < 6; ++i) {
            a[i] = i < 3 ? random_float() : fabsf(random_float());
            b[i] = i < 3 ? random_float() : fabsf(random_float());
        }
        for (unsigned i = 6; i < 15; ++i) b[i] = random_float() / 128.f;
        if (n < 64) {
            for (unsigned i = 0; i < 6; ++i) a[i] = b[i] = n & 1 ? 0.f : -0.f;
            for (unsigned i = 6; i < 15; ++i) b[i] = (i - 6) % 4 == 0 ? 1.f : 0.f;
        }
        memcpy(GPTR(BOX), a, sizeof a); memcpy(GPTR(OBB), b, sizeof b);
        g_edx = BOX; g_esp = SP - 192; MEM32(g_esp + 4) = OBB; g_backedges = 0;
        state before = capture();
        sub_160D6ED0_lifted();
        state wanted = capture();
        uint32_t edges = 0;
        assert(region_sat_overlap(a, b, &edges) == (wanted.regs[0] & 255u));
        assert(edges == wanted.backedges && edges <= 17);
        restore(before); sub_160D6ED0(); state actual = capture();
        for (unsigned i = 3; i < 8; ++i) assert(actual.regs[i] == wanted.regs[i]);
        assert((actual.regs[0] & 255u) == (wanted.regs[0] & 255u));
        assert(!memcmp(actual.flags, wanted.flags, sizeof actual.flags));
        assert(actual.top == wanted.top && !memcmp(GPTR(BOX), a, sizeof a) && !memcmp(GPTR(OBB), b, sizeof b));
    }
    for (unsigned mode = 0; mode < 4; ++mode) {
        initialize_native(0, 0);
        g_edx = BOX; g_esp = SP - 192; MEM32(g_esp + 4) = OBB;
        sat_enabled = mode != 0;
        if (mode == 1) g_fp_top = 1;
        if (mode == 2) MEM32(BOX) = 0x7f812345u;
        if (mode == 3) { g_edx = g_esp - 124; memcpy(GPTR(g_edx), GPTR(BOX), 24); }
        state before = capture(); memcpy(initial_memory, memory, sizeof memory);
        sub_160D6ED0_lifted(); state wanted = capture(); memcpy(wanted_memory, memory, sizeof memory);
        restore(before); memcpy(memory, initial_memory, sizeof memory);
        sub_160D6ED0(); state actual = capture();
        assert(!memcmp(&actual, &wanted, sizeof actual) && !memcmp(memory, wanted_memory, sizeof memory));
    }
    sat_enabled = 1;
    puts("PASS private SAT and native ABI: 12000 emitted-oracle comparisons, exact bounded backedge counts");
}

static void differential_geometry(void) {
    uint32_t geometry[27];
    initialize_native(0, 0);
    for (unsigned i = 0; i < 6; ++i) {
        put(BOX + 4*i, i < 3 ? -1.f : 1.f); put(QUERY + 4*i, i < 3 ? -1.f : 1.f);
        put(OBB + 4*i, i < 3 ? 0.f : 1.f);
    }
    memcpy(geometry, GPTR(QUERY), 24); memcpy(geometry + 6, GPTR(BOX), 24);
    memcpy(geometry + 12, GPTR(OBB), 60);
    for (unsigned n = 0; n < 680; ++n) {
        initialize_native(0, n);
        memcpy(GPTR(QUERY), geometry, 24); memcpy(GPTR(BOX), geometry + 6, 24);
        memcpy(GPTR(OBB), geometry + 12, 60);
        MEM16(RECORDS) = 3; MEM16(RECORDS + 2) = 0; MEM16(RECORDS + 5) = 0; MEM16(RECORDS + 8) = 1;
        MEM8(RECORDS + 4) = 1; MEM8(RECORDS + 7) = 254; MEM8(RECORDS + 10) = n & 1 ? 0 : 255;
        for (unsigned i = 0; i < 24; ++i) MEM32(COUNTS + 4*i) = n & 1 ? 0x80000000u : 0;
        if (n >= 64 && n < 118) {
            uint32_t at = n - 64 < 6 ? QUERY + 4*(n-64) : n - 64 < 12 ? BOX + 4*(n-70) : OBB + 4*(n-76);
            if (n - 64 < 27) MEM32(at) ^= 1u;
        }
        if (n >= 118 && n < 678) put(OBB, (float)(n - 118) * .001f);
        differential_native(0);
    }
    puts("PASS native region: repeated and changed geometry, colours, records and channel totals");
}

static unsigned engine_cases, engine_fast, engine_fallback, engine_yield_cases;
static unsigned renderer_mutation_cases;

static void engine_case(unsigned reason, uint32_t engine_value, uint32_t renderer_value, unsigned scheduling) {
    initialize_native(0, 0);
    engine_epsilon = engine_value; renderer_epsilon = renderer_value;
    g_edx = BOX; g_esp = SP - 192; MEM32(g_esp + 4) = OBB;
    sat_enabled = reason != 1;
    if (reason == 2) g_fp_top = 1;
    if (reason == 3) MEM32(BOX) = 0x7f812345u;
    if (reason == 4) MEM32(OBB + 24) = 0x3f800001u;
    if (reason == 5) { g_edx = g_esp - 124; memcpy(GPTR(g_edx), GPTR(BOX), 24); }
    if (reason == 6) { MEM32(g_esp + 4) = g_esp - 100; memcpy(GPTR(g_esp - 100), GPTR(OBB), 60); }
    if (scheduling) {
        for (unsigned i = 0; i < 6; ++i) { put(BOX + i * 4, i < 3 ? 0.f : 1.f); put(OBB + i * 4, i < 3 ? 0.f : 1.f); }
        g_backedges = RECOMP_YIELD_EVERY - (scheduling == 1 ? 33u : scheduling == 2 ? 32u : 1u);
    }
    recomp_yield_hook = scheduling == 4 ? NULL : scheduling ? scheduler_switch : NULL;
    state before = capture(); memcpy(initial_memory, memory, sizeof memory);
    unsigned previous_yields = scheduler_yields;
    original_engine_sat(); state wanted = capture(); memcpy(wanted_memory, memory, sizeof memory);
    unsigned oracle_yields = scheduler_yields - previous_yields;
    restore(before); memcpy(memory, initial_memory, sizeof memory);
    unsigned previous_entries = engine_lifted_entries, previous_global = engine_global_entries;
    previous_yields = scheduler_yields;
    sub_1105E810(); state actual = capture();
    unsigned fallback = reason || engine_value != 0x3f7fffefu || (scheduling == 2 || scheduling == 3);
    assert(engine_lifted_entries == previous_entries + (ENGINE_NATIVE ? fallback : 1));
    assert(scheduler_yields - previous_yields == oracle_yields);
    if (fallback) {
        assert(!memcmp(&wanted, &actual, sizeof actual));
        assert(!memcmp(memory, wanted_memory, sizeof memory));
#ifdef REGION_PRODUCTION_HELPERS
        if (engine_value != 0x3f7fffefu) assert(engine_global_entries == previous_global + 1);
#endif
        ++engine_fallback;
    } else {
        assert(engine_global_entries == previous_global);
        for (unsigned i = 3; i < 8; ++i) assert(actual.regs[i] == wanted.regs[i]);
        assert((actual.regs[0] & 255u) == (wanted.regs[0] & 255u));
        assert(actual.top == wanted.top && actual.backedges == wanted.backedges);
        assert(!memcmp(actual.flags, wanted.flags, sizeof actual.flags));
        for (unsigned i = 0; i < sizeof memory; ++i) {
            if (i >= before.regs[4] - BASE - 136u && i < before.regs[4] - BASE + 8u) continue;
            assert(memory[i] == wanted_memory[i]);
        }
        ++engine_fast;
    }
    if (scheduling == 3) { assert(oracle_yields > 0); ++engine_yield_cases; }
    ++engine_cases;
    recomp_yield_hook = NULL;
    engine_epsilon = renderer_epsilon = 0x3f7fffefu;
    sat_enabled = 1;
}

static void engine_guard_ranges(void) {
    for (unsigned mode = 0; mode < 6; ++mode) {
        initialize_native(0, 0);
        engine_epsilon = renderer_epsilon = 0x3f7fffefu;
        g_edx = BOX; g_esp = SP - 192; MEM32(g_esp + 4) = OBB;
        if (mode == 0) g_esp = 0x70u;
        if (mode == 1) g_esp = GUEST_USER_TOP - 4u;
        if (mode == 2) g_edx = 0;
        if (mode == 3) g_edx = GUEST_USER_TOP - 20u;
        if (mode == 4) MEM32(g_esp + 4) = 0;
        if (mode == 5) MEM32(g_esp + 4) = GUEST_USER_TOP - 56u;
        state before = capture(); memcpy(initial_memory, memory, sizeof memory);
        unsigned previous = engine_lifted_entries;
        engine_intercept = 1;
        if (!setjmp(engine_entry)) { sub_1105E810(); assert(0); }
        engine_intercept = 0;
        state after = capture();
        assert(engine_lifted_entries == previous + 1);
        assert(!memcmp(&before, &after, sizeof before));
        assert(!memcmp(initial_memory, memory, sizeof memory));
    }
}

static void renderer_epsilon_case(uint32_t engine_value, uint32_t renderer_value) {
    initialize_native(0, 0); sat_enabled = 1;
    engine_epsilon = engine_value; renderer_epsilon = renderer_value;
    g_edx = BOX; g_esp = SP - 192; MEM32(g_esp + 4) = OBB;
    state before = capture(); memcpy(initial_memory, memory, sizeof memory);
    original_renderer_sat(); state wanted = capture(); memcpy(wanted_memory, memory, sizeof memory);
    restore(before); memcpy(memory, initial_memory, sizeof memory);
    unsigned previous_entries = renderer_lifted_entries, previous_global = renderer_global_entries;
    sub_160D6ED0(); state actual = capture();
    unsigned fallback = renderer_value != 0x3f7fffefu;
    assert(renderer_lifted_entries == previous_entries + fallback);
    if (fallback) {
        assert(!memcmp(&wanted, &actual, sizeof actual));
        assert(!memcmp(memory, wanted_memory, sizeof memory));
#ifdef REGION_PRODUCTION_HELPERS
        assert(renderer_global_entries == previous_global + 1);
#endif
    } else {
        assert(renderer_global_entries == previous_global);
        for (unsigned i = 3; i < 8; ++i) assert(actual.regs[i] == wanted.regs[i]);
        assert((actual.regs[0] & 255u) == (wanted.regs[0] & 255u));
        assert(actual.top == wanted.top && actual.backedges == wanted.backedges);
        assert(!memcmp(actual.flags, wanted.flags, sizeof actual.flags));
    }
    initialize_native(0, 0); enabled = 1;
    unsigned previous_native = native_calls, previous_fallback = fallback_calls;
    differential_native(0);
    assert(native_calls == previous_native + !fallback);
    assert(fallback_calls == previous_fallback + fallback);
    ++renderer_mutation_cases;
    engine_epsilon = renderer_epsilon = 0x3f7fffefu;
}

static void differential_engine_epsilon(void) {
    static const uint32_t values[][2] = {
        {0x3f7fffef,0x3f7fffef}, /* original values */
        {0x3f7fffee,0x3f7fffef}, /* Engine-only one bit */
        {0x3f7fffef,0x3e800000}, /* renderer-only finite */
        {0x3f000000,0xbe800000}, /* both different finite */
        {0x7f812345,0x3f7fffef}, /* Engine-only sNaN */
        {0x3f7fffef,0x7f812345}, /* renderer-only sNaN */
        {0xff812345,0x7fc54321}, /* both different NaN */
        {0x7f800000,0xff800000}, /* both different infinities */
        {0x00000000,0x80000000}, /* both different zero */
        {0x80000000,0x3f7fffef}
    };
    for (unsigned value = 0; value < sizeof values / sizeof values[0]; ++value)
        for (unsigned n = 0; n < 200; ++n) {
            engine_case(0, values[value][0], values[value][1], 0);
            if (n < 32) renderer_epsilon_case(values[value][0], values[value][1]);
        }
    for (unsigned reason = 1; reason <= 6; ++reason)
        for (unsigned n = 0; n < 64; ++n) engine_case(reason, 0x3f7fffef, 0x3f7fffef, 0);
    for (unsigned scheduling = 1; scheduling <= 4; ++scheduling)
        for (unsigned n = 0; n < 32; ++n) engine_case(0, 0x3f7fffef, 0x3f7fffef, scheduling);
    engine_guard_ranges();
    assert(engine_fast > 500 && engine_fallback > 1500 && engine_yield_cases == 32);
    printf("PASS Engine SAT own-live-epsilon cases=%u eligible=%u fallback=%u native_override=%d: engine-only/renderer-only/both-different finite, sNaN, infinity and signed-zero; all fallback CPU+memory exact; disabled/nonempty-x87/finite/alias/range guards; near-yield boundaries and actual scheduler handover\n",
        engine_cases, engine_fast, engine_fallback, ENGINE_NATIVE);
    printf("PASS renderer own-live-epsilon SAT and weighted-region cases=%u: independent Engine mutations and exact modified-renderer fallback\n", renderer_mutation_cases);
}

int main(void) {
    differential_engine_epsilon();
    differential_sat();
    for (unsigned kind = 0; kind < 22; ++kind) for (unsigned n = 0; n < (kind == 19 ? 256u : 180u); ++n) {
        enabled = 1; initialize_native(kind, n); differential_native(kind);
        if (n < 3) { enabled = 0; initialize_native(kind, n); differential_native(kind); }
    }
    assert(native_calls > 1000 && fallback_calls > 1000);
    differential_geometry();
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
