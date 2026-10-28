/* Engine.dll's navigation mesh: the polygons of a leaf under a point.
 *
 * engine::CNavMesh finds the polygon of its mesh under a point (0x100ECD70:
 * the point to fixed point, a vertical ray down the mesh's tree); for each
 * leaf the ray crosses, 0x100EC930 tests every polygon: the normal as the
 * sum of its fan's cross products (64-bit integers) that face up, the
 * distance along the ray to its plane, and whether the point lies inside
 * one of the fan's triangles seen from above. GameModule asks every frame
 * where the hero stands, once for each creature's mesh (0x101C7380); lifted,
 * the test was the hottest function of a frame in the world (12 %). It runs
 * natively here, operation for operation as the lifted body does them (the
 * x87 steps in double, the SSE ones in float).
 *
 *   0x100EC930 (stdcall): [esp+4] = the ray (+0 the mesh, +4 float t,
 *   +8 the polygon found), [esp+8] = the leaf (+0 polygon count, +4 the
 *   first), [esp+12] = int point[3]; returns AL = 0, pops 12 bytes.
 *
 * VOID_NAVMESH=lifted runs the lifted body; =check runs both and logs any
 * answer that differs. */
#include "host.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

/* Native queries hold the machine lock, as generated plain-memory code does. */
#if defined(RECOMP_PLAIN_MEMORY)
#undef RECOMP_MEM_QUAL
#define RECOMP_MEM_QUAL
#endif

#ifdef VOID_RELEASE
#include "release_overrides.h"   /* the test's twin in another release (tools/lift_release.py) */
#else
#define ENGINE_NAVMESH_LEAF sub_110EC930           /* the 2009 Engine.dll */
#define ENGINE_NAVMESH_LEAF_LIFTED sub_110EC930_lifted
#define ENGINE_EPSILON 0x11122974u                  /* float 1e-6 */
#define ENGINE_FIXED_TO_UNITS 0x11122D0Cu           /* float 0.005 */
#endif

#ifdef ENGINE_NAVMESH_LEAF
void ENGINE_NAVMESH_LEAF_LIFTED(void);

/* CNavMesh */
#define MESH_VERTICES 0x14u        /* int[3] each */
#define MESH_POLY_OFFSETS 0x18u    /* dword index of each polygon in the polygon data */
#define MESH_POLY_DATA 0x1Cu       /* per polygon: ?, vertex count, vertex codes */
#define MESH_VERTEX_MAP 0x28u      /* vertex code -> vertex */

typedef struct { int32_t x, y, z; } ivec;

static ivec vertex(uint32_t mesh, uint32_t code)
{
    uint32_t index = MEM32(MEM32(mesh + MESH_VERTEX_MAP) + 4u * ((code & 1u) + 4u * (code >> 1)));
    uint32_t at = MEM32(mesh + MESH_VERTICES) + 12u * index;
    ivec v = {(int32_t)MEM32(at), (int32_t)MEM32(at + 4), (int32_t)MEM32(at + 8)};
    return v;
}

/* 0x100EC300: which side of edge a->b the point is on (x and z, 64-bit);
 * 1 once both sides have been seen. */
static int side(ivec a, ivec b, ivec p, uint8_t *neg, uint8_t *pos)
{
    int64_t s = (int64_t)(p.x - a.x) * (int64_t)(a.z - b.z) + (int64_t)(p.z - a.z) * (int64_t)(b.x - a.x);
    if (s > 0) {
        if (*neg) return 1;
        *pos = 1;
    } else if (s < 0) {
        if (*pos) return 1;
        *neg = 1;
    }
    return 0;
}

static void leaf_test(uint32_t ray, uint32_t leaf, uint32_t point_va, float *t_out, uint32_t *index_out)
{
    uint32_t mesh = MEM32(ray), count = MEM32(leaf), first = MEM32(leaf + 4);
    float eps = *(const float *)GPTR(ENGINE_EPSILON), scale = *(const float *)GPTR(ENGINE_FIXED_TO_UNITS);
    ivec p = {(int32_t)MEM32(point_va), (int32_t)MEM32(point_va + 4), (int32_t)MEM32(point_va + 8)};
    uint32_t poly = MEM32(mesh + MESH_POLY_DATA) + 4u * MEM32(MEM32(mesh + MESH_POLY_OFFSETS) + 4u * first);
    for (uint32_t k = 0; k < count; ++k, poly += 4u * (MEM32(poly + 4) + 2u)) {
        uint32_t n = MEM32(poly + 4);
        if (n <= 2) continue;
        ivec v0 = vertex(mesh, MEM32(poly + 8)), prev = vertex(mesh, MEM32(poly + 12));
        float nx = 0, ny = 0, nz = 0;
        for (uint32_t i = 2; i < n; ++i) {
            ivec cur = vertex(mesh, MEM32(poly + 8 + 4 * i));
            int32_t ax = prev.x - v0.x, ay = prev.y - v0.y, az = prev.z - v0.z;
            int32_t bx = cur.x - v0.x, by = cur.y - v0.y, bz = cur.z - v0.z;
            /* 0x1001BC60: a x b */
            int64_t cx = (int64_t)az * by - (int64_t)ay * bz;
            int64_t cy = (int64_t)ax * bz - (int64_t)az * bx;
            int64_t cz = (int64_t)ay * bx - (int64_t)ax * by;
            if (cy > 0) {
                nx = (float)((double)cx + (double)nx);
                ny = (float)((double)cy + (double)ny);
                nz = (float)((double)cz + (double)nz);
            }
            prev = cur;
        }
        if (!(ny > eps)) continue;
        float tmax = *(const float *)GPTR(ray + 4);
        float len2 = nz * nz + nx * nx;
        len2 = len2 + ny * ny;
        double root = sqrt((double)len2);
        float inv = (float)(root == 0.0 ? 1.0 : 1.0 / root);
        float nxn = inv * nx, nyn = ny * inv, nzn = nz * inv;
        float d = (float)(p.z - v0.z) * nzn;
        d = d + (float)(p.y - v0.y) * nyn;
        d = d + (float)(p.x - v0.x) * nxn;
        d = d * scale;
        float t;
        if (eps > fabs((double)d)) {
            if (tmax == 0.0f) continue;
            t = 0.0f;
        } else {
            t = d / nyn;
            if (0.0f > t) continue;
            if (!(tmax > t)) continue;
        }
        /* Inside one of the fan's triangles, seen from above? */
        ivec a = vertex(mesh, MEM32(poly + 12));
        uint32_t i;
        for (i = 2; i < n; ++i) {
            ivec b = vertex(mesh, MEM32(poly + 8 + 4 * i));
            uint8_t neg = 0, pos = 0;
            if (!side(v0, a, p, &neg, &pos) && !side(a, b, p, &neg, &pos) && !side(b, v0, p, &neg, &pos) &&
                (neg || pos))
                break;
            a = b;
        }
        if (i == n) continue;
        *(float *)GPTR(ray + 4) = t;
        MEM32(ray + 8) = first + k;
    }
    *t_out = *(const float *)GPTR(ray + 4);
    *index_out = MEM32(ray + 8);
}

static int mode = -1;
static struct { uint32_t calls, differ; } check;

void ENGINE_NAVMESH_LEAF(void)
{
    if (mode < 0) {
        const char *env = getenv("VOID_NAVMESH");
        mode = !env ? 1 : !strcmp(env, "lifted") ? 0 : !strcmp(env, "check") ? 2 : 1;
        void_log("[engine] nav mesh leaf test: %s", mode == 0 ? "lifted" : mode == 2 ? "native, checked" : "native");
    }
    uint32_t esp = g_esp, ray = MEM32(esp + 4), leaf = MEM32(esp + 8), point = MEM32(esp + 12);
    if (mode == 0 || !ray || !leaf || !point) { ENGINE_NAVMESH_LEAF_LIFTED(); return; }
    float t;
    uint32_t index;
    if (mode == 1) {
        leaf_test(ray, leaf, point, &t, &index);
        g_eax &= ~0xFFu;
        g_esp = esp + 16;   /* ret 0Ch */
        return;
    }
    uint32_t t0 = MEM32(ray + 4), i0 = MEM32(ray + 8);
    leaf_test(ray, leaf, point, &t, &index);
    uint32_t t_native = MEM32(ray + 4), i_native = MEM32(ray + 8);
    MEM32(ray + 4) = t0;
    MEM32(ray + 8) = i0;
    ENGINE_NAVMESH_LEAF_LIFTED();
    ++check.calls;
    if (t_native != MEM32(ray + 4) || i_native != MEM32(ray + 8)) {
        if (check.differ++ < 16)
            void_log("[engine] nav mesh leaf differs: native t %08X polygon %u, lifted t %08X polygon %u", t_native,
                     i_native, MEM32(ray + 4), MEM32(ray + 8));
    }
    if ((check.calls & 0x7FF) == 1)
        void_log("[engine] nav mesh leaf check: %u calls, %u differ", check.calls, check.differ);
}
#endif
