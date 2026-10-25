/* fread-compatible callback on synthetic guest/native IReadObject readers. */
#include "../native/void_runtime.c"

#define BASE 0x21000000u
#define FILE_OBJECT (BASE + 0x8000u)
#define FILE_VTABLE (BASE + 0x8100u)
#define DATASOURCE (BASE + 0x8200u)
#define READ_VA (BASE + 0x100u)
#define MAX_STREAM 32767u

extern void void_sound_bulk_read(void);

static unsigned char input[MAX_STREAM], collected[MAX_STREAM];
static unsigned char *buffer_end, *active_buffer;
static uint32_t active_capacity, input_size, position, short_limit;
static uint32_t read_calls, last_request, last_read;
static unsigned scenarios;
static unsigned reader_fault;

static void require(int condition, int code, const char *message)
{
    if (!condition) {
        fprintf(stderr, "FAIL %d: %s\n", code, message);
        ExitProcess(code);
    }
}

void void_lift_trap(uint32_t address, const char *instruction)
{
    if (reader_fault && address == 0x14061270u &&
        !strcmp(instruction, "invalid Sound stream read count or stack cleanup")) {
        printf("PASS rejects invalid reader %s\n", reader_fault == 1 ? "RETn stack cleanup" : "byte count above request");
        fflush(stdout);
        ExitProcess(0);
    }
    fprintf(stderr, "Unexpected trap %08X %s\n", address, instruction);
    ExitProcess(90);
}

recomp_func_t recomp_lookup_manual(uint32_t va)
{
    (void)va;
    return NULL;
}

static uint32_t read_bytes(uint32_t object, uint32_t buffer, uint32_t requested)
{
    require(object == FILE_OBJECT && buffer == (uint32_t)(uintptr_t)active_buffer,
        91, "IReadObject got the wrong ECX file object or buffer argument");
    ++read_calls;
    last_request = requested;
    uint32_t amount = input_size - position;
    if (amount > requested) amount = requested;
    if (short_limit && amount > short_limit) amount = short_limit;
    require(amount <= active_capacity, 92, "read would overrun its output buffer");
    if (amount) memcpy(active_buffer, input + position, amount);
    position += amount;
    last_read = amount;
    return amount;
}

static void guest_read(void)
{
    uint32_t result = read_bytes(g_ecx, MEM32(g_esp + 4), MEM32(g_esp + 8));
    g_eax = reader_fault == 2 ? last_request + 1 : result;
    g_ecx = 0xBAD00001u;
    g_edx = 0xBAD00002u;
    g_esp += reader_fault == 1 ? 8 : 12; /* valid thiscall reader RET8 */
}

/* ECX=this, EDX unused; buffer and byte count stay on the native stack. */
static uint32_t __fastcall native_read(void *object, void *unused,
                                     void *buffer, uint32_t requested)
{
    (void)unused;
    return read_bytes((uint32_t)(uintptr_t)object, (uint32_t)(uintptr_t)buffer, requested);
}

const recomp_dispatch_entry_t recomp_dispatch_table[] = {{READ_VA, guest_read}};
const uint32_t recomp_dispatch_count = 1;

static unsigned char *prepare_buffer(uint32_t capacity)
{
    require(capacity <= 8500, 93, "test buffer exceeds its committed guarded span");
    active_capacity = capacity;
    active_buffer = buffer_end - capacity;
    memset(active_buffer - 64, 0xA5, 64);
    if (capacity) memset(active_buffer, 0xCD, capacity);
    return active_buffer;
}

static void check_buffer(uint32_t amount)
{
    for (unsigned i = 0; i < 64; ++i)
        require(active_buffer[-64 + (int)i] == 0xA5, 94, "buffer prefix canary changed");
    for (uint32_t i = amount; i < active_capacity; ++i)
        require(active_buffer[i] == 0xCD, 95, "bytes beyond the actual short read changed");
}

static uint32_t call_bulk(uint32_t size, uint32_t count, uint32_t capacity)
{
    prepare_buffer(capacity);
    uint32_t before = g_esp;
    uint32_t saved[] = {g_ebx, g_esi, g_edi, g_ebp};
    PUSH32(g_esp, DATASOURCE);
    PUSH32(g_esp, count);
    PUSH32(g_esp, size);
    PUSH32(g_esp, (uint32_t)(uintptr_t)active_buffer);
    PUSH32(g_esp, RECOMP_RETADDR);
    void_sound_bulk_read();
    uint32_t result = g_eax;
    require(g_esp == before - 16 && g_ebx == saved[0] && g_esi == saved[1] &&
        g_edi == saved[2] && g_ebp == saved[3], 96,
        "fread callback changed cdecl argument cleanup/nonvolatile registers");
    g_esp += 16; /* the original cdecl caller owns these arguments */
    return result;
}

static void reset_stream(uint32_t length, uint32_t limit)
{
    input_size = length;
    position = 0;
    read_calls = last_request = last_read = 0;
    short_limit = limit;
    memset(collected, 0, sizeof collected);
}

static uint32_t stream(uint32_t length, uint32_t request, uint32_t limit)
{
    reset_stream(length, limit);
    uint32_t copied = 0;
    for (;;) {
        uint32_t got = call_bulk(1, request, request);
        require(last_request == request && got == last_read && got <= request,
            97, "size=1 callback return/request differs from actual bytes read");
        check_buffer(got);
        if (!got) break;
        require(copied + got <= length, 98, "concatenated read exceeds the stream");
        memcpy(collected + copied, active_buffer, got);
        copied += got;
    }
    require(copied == length && !memcmp(input, collected, length) && position == length,
        99, "concatenated stream changed across callback boundaries");
    uint32_t effective = limit && limit < request ? limit : request;
    require(read_calls == (length + effective - 1) / effective + 1,
        100, "callback count is not one read per requested block plus EOF");
    ++scenarios;
    return read_calls;
}

static void scalar_case(uint32_t size, uint32_t count, uint32_t capacity,
                        uint32_t length, uint32_t limit, uint32_t expected,
                        uint32_t expected_reads, uint32_t expected_request, uint32_t expected_bytes)
{
    reset_stream(length, limit);
    uint32_t result = call_bulk(size, count, capacity);
    require(result == expected && read_calls == expected_reads &&
        last_request == expected_request && position == expected_bytes && last_read == expected_bytes,
        101, "zero/overflow/short item/EOF callback contract differs");
    require(!expected_bytes || !memcmp(active_buffer, input, expected_bytes),
        102, "scalar callback bytes differ");
    check_buffer(expected_bytes);
    ++scenarios;
}

static void check_guest_nx(void)
{
    MEMORY_BASIC_INFORMATION information;
    require(VirtualQuery((void *)BASE, &information, sizeof information) == sizeof information &&
        information.Type == MEM_PRIVATE && information.State == MEM_COMMIT &&
        information.AllocationBase == (void *)BASE && information.Protect == PAGE_READWRITE,
        103, "synthetic guest mapping became executable or lost ownership");
}

int main(int argc, char **argv)
{
    void *mapped = VirtualAlloc((void *)BASE, 0x10000,
        MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    require(mapped == (void *)BASE, 104, "cannot reserve synthetic guest data");
    memset(mapped, 0xCC, 0x10000);
    g_mods[0].base = BASE; g_mods[0].span = 0x10000;
    strcpy(g_mods[0].name, "synthetic-sound-read");
    g_mod_n = 1;
    unsigned char *guarded = VirtualAlloc(NULL, 5 * 0x1000, MEM_RESERVE, PAGE_NOACCESS);
    require(guarded && VirtualAlloc(guarded + 0x1000, 3 * 0x1000, MEM_COMMIT, PAGE_READWRITE)
        == guarded + 0x1000, 105, "cannot reserve guarded output buffer");
    buffer_end = guarded + 4 * 0x1000; /* suffix remains PAGE_NOACCESS */
    for (uint32_t i = 0; i < MAX_STREAM; ++i)
        input[i] = (unsigned char)((i * 37u + (i >> 3) * 19u + 0x5Bu) ^ (i >> 8));
    native32_init();
    MEM32(FILE_OBJECT) = FILE_VTABLE;
    MEM32(DATASOURCE) = FILE_OBJECT;
    mach_enter();
    g_ebx = 0x41424344u; g_esi = 0x51525354u;
    g_edi = 0x61626364u; g_ebp = 0x71727374u;
    if (argc > 1) {
        require(argc == 2 && (!strcmp(argv[1], "--negative-stack") ||
            !strcmp(argv[1], "--negative-count")), 107, "unknown negative control");
        reader_fault = !strcmp(argv[1], "--negative-stack") ? 1 : 2;
        MEM32(FILE_VTABLE + 0x24) = READ_VA;
        reset_stream(10, 0);
        call_bulk(1, 8, 8);
        require(0, 108, "invalid reader was not rejected by the runtime trap guard");
    }
    const uint32_t lengths[] = {0, 1, 2, 8499, 8500, 8501, 17003, MAX_STREAM};
    const uint32_t requests[] = {1, 3, 8, 257, 8500};
    uint32_t legacy_calls[2], bulk_calls[2];
    for (int native = 0; native < 2; ++native) {
        MEM32(FILE_VTABLE + 0x24) = native ? (uint32_t)(uintptr_t)native_read : READ_VA;
        scalar_case(0, 8500, 0, 4, 0, 0, 0, 0, 0);
        scalar_case(4, 0, 0, 4, 0, 0, 0, 0, 0);
        scalar_case(0x80000000u, 2, 0, 4, 0, 0, 0, 0, 0);
        scalar_case(0xFFFFFFFFu, 2, 0, 4, 0, 0, 0, 0, 0);
        scalar_case(0x10000u, 0x10000u, 0, 4, 0, 0, 0, 0, 0);
        scalar_case(0xFFFFFFFFu, 1, 0, 0, 0, 0, 1, 0xFFFFFFFFu, 0);
        scalar_case(1, 8500, 8500, 8500, 0, 8500, 1, 8500, 8500);
        scalar_case(4, 3, 12, 10, 0, 2, 1, 12, 10);
        scalar_case(4, 3, 12, 12, 5, 1, 1, 12, 5);
        scalar_case(3, 5, 15, 16, 0, 5, 1, 15, 15);
        scalar_case(8, 1, 8, 3, 0, 0, 1, 8, 3);
        scalar_case(4, 3, 12, 0, 0, 0, 1, 12, 0);
        for (unsigned i = 0; i < sizeof lengths / sizeof lengths[0]; ++i)
            for (unsigned j = 0; j < sizeof requests / sizeof requests[0]; ++j)
                stream(lengths[i], requests[j], 0);
        stream(MAX_STREAM, 8500, 7);
        /* size=1/count=1 reproduces the old callback's ignored nmemb request. */
        legacy_calls[native] = stream(MAX_STREAM, 1, 0);
        bulk_calls[native] = stream(MAX_STREAM, 8500, 0);
        require(legacy_calls[native] == MAX_STREAM + 1 && bulk_calls[native] == 5,
            106, "one-byte versus bulk read model did not remove repeated callbacks");
        check_guest_nx();
    }
    mach_leave();
    VirtualFree(guarded, 0, MEM_RELEASE);
    printf("PASS %u scenarios on guest thiscall RET8 and real native bridge reader; "
        "cdecl ESP/nonvolatile registers, zero/overflow noRead, max DWORD EOF, "
        "short/partial items, guarded output and identical concatenated streams; "
        "32767-byte stream legacy-model calls=%u/%u bulk calls=%u/%u\n",
        scenarios, legacy_calls[0], legacy_calls[1], bulk_calls[0], bulk_calls[1]);
    return 0;
}
