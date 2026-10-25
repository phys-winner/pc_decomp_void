/* ARM64 check of the host FPREM/FPREM1 (android/host/core.c) against
 * reference vectors produced by the real x87 (tests/fprem_vectors.c).
 * Reads the vector file on stdin; prints mismatches and a summary. */
#include "../android/host/core.c"

const recomp_dispatch_entry_t recomp_dispatch_table[1] = {{0, 0}};
const uint32_t recomp_dispatch_count = 0;
VOID_HIDDEN recomp_ehframe_t *g_eh_frames;
VOID_HIDDEN uint32_t g_eh_obj, g_eh_info;
int void_vm_readable(uint32_t address, uint32_t size) { (void)address; (void)size; return 0; }

int main(void)
{
    char line[256];
    unsigned total = 0, bad = 0;
    while (fgets(line, sizeof line, stdin)) {
        int nearest;
        unsigned long long xb, yb, rb;
        unsigned status;
        if (sscanf(line, "%d %llX %llX %llX %X", &nearest, &xb, &yb, &rb, &status) != 5) continue;
        double x, y;
        memcpy(&x, &xb, 8); memcpy(&y, &yb, 8);
        g_fp_top = 2;
        g_st[0] = x; g_st[1] = y;
        void_fpu_remainder(0, nearest);
        uint64_t got;
        memcpy(&got, &g_st[0], 8);
        unsigned got_status = (unsigned)void_fpu_cmp & 0x4700u;
        /* C2 set: the step is implementation-defined; only check the flag. */
        int ok = (status & 0x0400u) ? (got_status & 0x0400u) != 0 : (got == rb && got_status == status);
        ++total;
        if (!ok) {
            if (bad < 20) printf("mismatch nearest=%d x=%016llX y=%016llX expected %016llX/%04X got %016llX/%04X\n",
                nearest, xb, yb, rb, status, (unsigned long long)got, got_status);
            ++bad;
        }
    }
    printf("%s: %u vectors, %u mismatches\n", bad ? "FAIL" : "PASS", total, bad);
    return bad ? 1 : 0;
}
