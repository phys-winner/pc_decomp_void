/* Streaming libz adapter for the pinned RendererD3D inflater.
 * The original allocation remains the guest-visible ownership anchor. */
#include "host.h"
#include <zlib.h>
#include <stdlib.h>
#include <string.h>

#ifdef VOID_RELEASE
#include "release_overrides.h"   /* these bodies' twins in another release (tools/lift_release.py) */
#else
#define RENDERER_INFLATE_INIT sub_1611E830        /* the 2009 RendererD3D.dll */
#define RENDERER_INFLATE_INIT_LIFTED sub_1611E830_lifted
#define RENDERER_INFLATE_RESET sub_1611E7D0
#define RENDERER_INFLATE_RESET_LIFTED sub_1611E7D0_lifted
#define RENDERER_INFLATE sub_1611E9F0
#define RENDERER_INFLATE_LIFTED sub_1611E9F0_lifted
#define RENDERER_INFLATE_END sub_1611FFF0
#define RENDERER_INFLATE_END_LIFTED sub_1611FFF0_lifted
#define RENDERER_INFLATE_ZFREE 0x161467A0u        /* zlib's default allocator */
#define RENDERER_INFLATE_ZALLOC 0x161467B0u
/* zlib 1.2.3's messages in the image; the native inflate hands back these copies. */
#define RENDERER_INFLATE_MESSAGES 0x162ce800,0x162ce818,0x162ce830,0x162ce850,0x162ce868,0x162ce884, \
    0x162ce89c,0x162ce8b8,0x162ce8d4,0x162ce8f8,0x162ce914,0x162ce934,0x162ce948,0x162ce95c,0x162ce978, \
    0x162ce990,0x162ce9a4,0x162cf434,0x162cf440,0x162cf468
#define RENDERER_INFLATE_DATA_ERROR 0x162cf434
#endif

#if defined(RENDERER_INFLATE_INIT) && defined(RENDERER_INFLATE_RESET) && defined(RENDERER_INFLATE) && defined(RENDERER_INFLATE_END)
void RENDERER_INFLATE_INIT_LIFTED(void);
void RENDERER_INFLATE_RESET_LIFTED(void);
void RENDERER_INFLATE_LIFTED(void);
void RENDERER_INFLATE_END_LIFTED(void);
int void_renderer_native_enabled(void);

typedef struct inflate_owner {
    uint32_t stream, anchor;
    int raw;
    z_stream native;
    struct inflate_owner *next;
} inflate_owner;
/* The guest machine is serialized by the existing machine lock. */
static inflate_owner *inflate_owners;

static inflate_owner **inflate_slot(uint32_t stream)
{
    inflate_owner **slot = &inflate_owners;
    while (*slot && (*slot)->stream != stream) slot = &(*slot)->next;
    return slot;
}

static int inflate_range(uint32_t address, uint32_t length)
{
    return address >= 0x10000u && address <= GUEST_USER_TOP &&
        length <= GUEST_USER_TOP - address && void_vm_readable(address, length);
}

/* Reuse stable, readable original-image strings. A newer libz diagnostic that
 * did not exist in 1.2.3 is represented by the original generic data error. */
static uint32_t inflate_message(const char *message)
{
    static const uint32_t messages[] = { RENDERER_INFLATE_MESSAGES };
    if (!message) return 0;
    for (unsigned i = 0; i < sizeof messages / sizeof messages[0]; ++i)
        if (!strcmp(message, (const char *)GPTR(messages[i]))) return messages[i];
    return RENDERER_INFLATE_DATA_ERROR;
}

void RENDERER_INFLATE_INIT(void)
{
    uint32_t stack = g_esp, stream = MEM32(stack + 4);
    int bits = (int)MEM32(stack + 8);
    /* Init without End is API misuse; do not orphan an owned native lifetime. */
    if (*inflate_slot(stream)) {
        g_eax = (uint32_t)Z_STREAM_ERROR; g_esp = stack + 4; return;
    }
    int eligible = void_renderer_native_enabled() && inflate_range(stream, 56) &&
        (!MEM32(stream + 32) || MEM32(stream + 32) == RENDERER_INFLATE_ZALLOC) &&
        (!MEM32(stream + 36) || MEM32(stream + 36) == RENDERER_INFLATE_ZFREE);
    /* Original validation, defaults, OOM semantics and state address survive. */
    RENDERER_INFLATE_INIT_LIFTED();
    if (!eligible || (int)g_eax != Z_OK) return;
    inflate_owner *owner = calloc(1, sizeof *owner);
    if (!owner) return; /* No native input consumed: retain original lifetime. */
    if (inflateInit2(&owner->native, bits) != Z_OK) { free(owner); return; }
    owner->stream = stream;
    owner->anchor = MEM32(stream + 28);
    owner->raw = bits < 0;
    owner->next = inflate_owners;
    inflate_owners = owner;
}

void RENDERER_INFLATE(void)
{
    uint32_t stack = g_esp, stream = MEM32(stack + 4);
    inflate_owner *owner = *inflate_slot(stream);
    if (!owner) { RENDERER_INFLATE_LIFTED(); return; }
    /* Ownership is permanent until End, even if the diagnostic toggle changes.
     * Neither invalid pointers nor a damaged public state can enter lifted code. */
    uint32_t input = MEM32(stream), count = MEM32(stream + 4);
    uint32_t output = MEM32(stream + 12), capacity = MEM32(stream + 16);
    if (MEM32(stream + 28) != owner->anchor ||
        (!input && count) || (input && !inflate_range(input, count)) ||
        !inflate_range(output, capacity)) {
        g_eax = (uint32_t)Z_STREAM_ERROR; g_esp = stack + 4; return;
    }
    owner->native.next_in = input ? (Bytef *)GPTR(input) : Z_NULL;
    owner->native.avail_in = count;
    owner->native.next_out = (Bytef *)GPTR(output);
    owner->native.avail_out = capacity;
    int flush = (int)MEM32(stack + 8);
    /* The 1.2.3 routine only treats FINISH=4/BLOCK=5 specially. In particular,
     * its value 6 is not the newer libz Z_TREES command. */
    if (flush < 0 || flush > 5) flush = 0;
    int status = inflate(&owner->native, flush);
    MEM32(stream) = input + count - owner->native.avail_in;
    MEM32(stream + 4) = owner->native.avail_in;
    MEM32(stream + 8) = (uint32_t)owner->native.total_in;
    MEM32(stream + 12) = output + capacity - owner->native.avail_out;
    MEM32(stream + 16) = owner->native.avail_out;
    MEM32(stream + 20) = (uint32_t)owner->native.total_out;
    MEM32(stream + 24) = inflate_message(owner->native.msg);
    MEM32(stream + 44) = (uint32_t)owner->native.data_type;
    MEM32(stream + 48) = owner->raw ? 1u : (uint32_t)owner->native.adler;
    g_eax = (uint32_t)status;
    g_esp = stack + 4;
}

void RENDERER_INFLATE_RESET(void)
{
    uint32_t stack = g_esp, stream = MEM32(stack + 4);
    inflate_owner *owner = *inflate_slot(stream);
    if (!owner) { RENDERER_INFLATE_RESET_LIFTED(); return; }
    if (MEM32(stream + 28) != owner->anchor || inflateReset(&owner->native) != Z_OK) {
        g_eax = (uint32_t)Z_STREAM_ERROR; g_esp = stack + 4; return;
    }
    RENDERER_INFLATE_RESET_LIFTED(); /* Unused original state resets; no original decode. */
}

void RENDERER_INFLATE_END(void)
{
    uint32_t stack = g_esp, stream = MEM32(stack + 4);
    inflate_owner *owner = *inflate_slot(stream);
    if (!owner) { RENDERER_INFLATE_END_LIFTED(); return; }
    if (MEM32(stream + 28) != owner->anchor) {
        g_eax = (uint32_t)Z_STREAM_ERROR; g_esp = stack + 4; return;
    }
    /* This is cleanup of the never-decoded original anchor, not decode fallback. */
    RENDERER_INFLATE_END_LIFTED();
    if ((int)g_eax != Z_OK) return; /* Rejected End must preserve progress. */
    /* Guest allocator callbacks can yield; reacquire the intrusive list link. */
    inflate_owner **slot = inflate_slot(stream);
    owner = *slot;
    (void)inflateEnd(&owner->native);
    *slot = owner->next;
    free(owner);
}
#endif
