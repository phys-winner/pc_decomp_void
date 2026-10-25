/* Measured PhysX leaves and the debug renderer's single-colour line append. */
#include "host.h"

static int physics_native_enabled = 1;
void void_physics_native_enable(int enabled) { physics_native_enabled = enabled != 0; }

#ifndef VOID_RELEASE
/* Extreme values and aliases need the original NaN conversion/store behavior. */
int void_physics_sweep_finite(void)
{
    if (!physics_native_enabled || g_esp < 56u || g_esp > UINT32_MAX - 32u) return 0;
    uint32_t pointers[7], sizes[7];
    for (unsigned i = 0; i < 7; ++i) {
        uint32_t pointer = MEM32(g_esp + 4u + i * 4u), size = i == 5 ? 4u : 12u;
        if (pointer > UINT32_MAX - size ||
            (pointer < g_esp + 32u && g_esp - 56u < pointer + size)) return 0;
        for (unsigned j = 0; j < i; ++j)
            if (pointer < pointers[j] + sizes[j] && pointers[j] < pointer + size) return 0;
        pointers[i] = pointer;
        sizes[i] = size;
    }
    for (unsigned i = 0; i < 5; ++i) {
        uint32_t vector = pointers[i];
        for (unsigned j = 0; j < 3; ++j)
            if ((MEM32(vector + j * 4u) & 0x7fffffffu) > 0x4cbebc20u) return 0;
    }
    return 1;
}

/* Check each current node again after recursion, callbacks and loop yields. */
int void_physics_tree_node_finite(uint32_t context, uint32_t node, uint32_t frame)
{
    if (!physics_native_enabled || context < 0x10000u || context > GUEST_USER_TOP - 0x64u ||
        node < 0x10000u || node > GUEST_USER_TOP - 24u || frame < 24u || frame > UINT32_MAX - 20u ||
        (context < node + 24u && node < context + 0x64u) ||
        (context < frame + 20u && frame - 24u < context + 0x64u) ||
        (node < frame + 20u && frame - 24u < node + 24u)) return 0;
    for (unsigned i = 0; i < 12; ++i)
        if ((MEM32(context + 0x1cu + i * 4u) & 0x7fffffffu) > 0x4cbebc20u) return 0;
    for (unsigned i = 0; i < 6; ++i)
        if ((MEM32(node + i * 4u) & 0x7fffffffu) > 0x4cbebc20u) return 0;
    return 1;
}

/* The worker's straight-line transform prefix has no calls or yields. Bound
 * its polynomial inputs and exclude the complete frame, including the first
 * call's argument/return slots, before its original prologue writes anything. */
int void_physics_worker_pair_finite(void)
{
    uint32_t stack = g_esp;
    if (!physics_native_enabled || stack < 0x10428u || stack > GUEST_USER_TOP - 32u) return 0;
    for (unsigned i = 0; i < 2; ++i) {
        uint32_t transform = MEM32(stack + 12u + i * 4u);
        if (transform < 0x10000u || transform > GUEST_USER_TOP - 28u ||
            (transform < stack + 32u && stack - 0x428u < transform + 28u)) return 0;
        for (unsigned j = 0; j < 7; ++j)
            if ((MEM32(transform + j * 4u) & 0x7fffffffu) >
                (j < 3 ? 0x4cbebc20u : 0x40000000u)) return 0;
    }
    return 1;
}

void sub_181802C0_lifted(void);
void sub_110014F0_lifted(void);
int void_renderer_append12(int preserve_ecx);

/* Engine's copy of the append preserves ECX and has its own growth/EH path. */
void sub_110014F0(void)
{
    if (!physics_native_enabled || !void_renderer_append12(1)) sub_110014F0_lifted();
}

void sub_181802C0(void)
{
    uint32_t object = g_ecx, stack = g_esp;
    if (!physics_native_enabled || object < 0x10000u || object > GUEST_USER_TOP - 32u ||
        stack < 0x10028u || stack > GUEST_USER_TOP - 16u) {
        sub_181802C0_lifted();
        return;
    }
    uint32_t begin = MEM32(object + 20), end = MEM32(object + 24), cap = MEM32(object + 28);
    uint32_t first = MEM32(stack + 4), second = MEM32(stack + 8);
    if (begin < 0x10000u || end < begin || cap < end || cap > GUEST_USER_TOP ||
        (end - begin) % 28u || (cap - begin) % 28u || cap - end < 28u ||
        first < 0x10000u || first > GUEST_USER_TOP - 12u ||
        second < 0x10000u || second > GUEST_USER_TOP - 12u ||
        (object < cap && begin < object + 32u) ||
        (object < stack + 16u && stack - 40u < object + 32u) ||
        (first < stack + 16u && stack - 40u < first + 12u) ||
        (second < stack + 16u && stack - 40u < second + 12u) ||
        (end < stack + 16u && stack - 40u < end + 28u)) {
        sub_181802C0_lifted();
        return;
    }
    uint32_t coordinates[6] = {MEM32(first), MEM32(first + 4), MEM32(first + 8),
                               MEM32(second), MEM32(second + 4), MEM32(second + 8)};
    for (unsigned i = 0; i < 6; ++i)
        if ((coordinates[i] & 0x7fffffffu) >= 0x7f800000u) {
            sub_181802C0_lifted();
            return;
        }
    /* Finite float loads/stores are exact; each x87 push/pop only clears slot 7. */
    MEM32(stack - 4) = g_ebp;
    MEM32(stack - 36) = g_esi;
    MEM32(stack - 40) = g_edi;
    for (unsigned i = 0; i < 6; ++i) MEM32(stack - 32u + i * 4u) = coordinates[i];
    for (unsigned i = 0; i < 6; ++i) MEM32(end + i * 4u) = coordinates[i];
    g_ecx = MEM32(stack + 12);
    MEM32(end + 24) = g_ecx;
    MEM32(object + 24) = end + 28u;
    g_st[7] = 0;
    g_st_i64[7] = 0;
    g_eax = end;
    g_esp = stack + 16u;
    g_flag_k = FK_ADD;
    g_flag_a = end;
    g_flag_b = 28;
    g_flag_cf = 0;
}
#endif
