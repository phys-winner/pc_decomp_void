/* d3dx9_36.dll: the subset the renderer imports, natively.
 *
 * HLSL compilation is served from a content-addressed cache. A miss records
 * the complete request (source, macros, entry, profile, flags) so the cache
 * can be filled offline with Microsoft's own compiler on Windows, without
 * running the game there; the request then fails as a compile error would. */
#define _GNU_SOURCE
#include "d3d9_internal.h"
#include "hud.h"
#include <errno.h>
#include <math.h>
#include <stdatomic.h>
#include <sys/stat.h>
#include <unistd.h>

#define D3DX "d3dx9_36.dll"
#define D3DXERR_INVALIDDATA 0x88760B59u

static _Atomic uint32_t cache_responses;
uint32_t void_d3dx_cache_responses(void) { return atomic_load_explicit(&cache_responses, memory_order_relaxed); }
static _Atomic uint64_t missing_shader;
static _Atomic uint64_t missing_family;
uint64_t void_d3dx_missing_shader(void) { return atomic_load_explicit(&missing_shader, memory_order_relaxed); }
static char packaged_cache_dir[1024];

static void shader_missing(uint64_t key, int missing)
{
    if (missing) atomic_store_explicit(&missing_shader, key, memory_order_relaxed);
    else atomic_compare_exchange_strong_explicit(&missing_shader, &key, 0, memory_order_relaxed, memory_order_relaxed);
}

void void_d3dx_shader_failure(uint64_t key, int failed)
{
    if (failed) atomic_store_explicit(&missing_family, 0, memory_order_relaxed);
    shader_missing(key, failed);
}

static void shader_family_result(uint64_t key, uint64_t family, int missing)
{
    if (missing) {
        atomic_store_explicit(&missing_family, family, memory_order_relaxed);
        shader_missing(key, 1);
    } else {
        /* RendererD3D may retry the same source with a supported profile. */
        if (family && atomic_load_explicit(&missing_family, memory_order_relaxed) == family) {
            uint64_t previous = atomic_load_explicit(&missing_shader, memory_order_relaxed);
            shader_missing(previous, 0);
            atomic_store_explicit(&missing_family, 0, memory_order_relaxed);
        } else shader_missing(key, 0);
    }
}

/* Set once before the Android game thread starts; the CLI uses only its profile. */
void void_d3dx_set_packaged_cache_dir(const char *dir)
{
    snprintf(packaged_cache_dir, sizeof packaged_cache_dir, "%s", dir ? dir : "");
}

const char *void_d3dx_packaged_cache_dir(void) { return packaged_cache_dir; }

/* ============================================================ ID3DXBuffer */
typedef struct { void_com_object com; uint32_t data, size; } dxbuffer_t;
static void dxbuffer_destroy(void_com_object *o) { dxbuffer_t *b = (dxbuffer_t *)o; void_gfree(b->data); free(b); }
COM_METHOD(dxb, QueryInterface, 3) { MEM32(ARG(2)) = THIS_; void_com_addref((void_com_object *)void_com_host(THIS_)); return 0; }
COM_METHOD(dxb, AddRef, 1) { return void_com_addref((void_com_object *)void_com_host(THIS_)); }
COM_METHOD(dxb, Release, 1) { return void_com_release((void_com_object *)void_com_host(THIS_)); }
COM_METHOD(dxb, GetBufferPointer, 1) { return ((dxbuffer_t *)void_com_host(THIS_))->data; }
COM_METHOD(dxb, GetBufferSize, 1) { return ((dxbuffer_t *)void_com_host(THIS_))->size; }
static const void_fn dxbuffer_methods[] = { dxb_QueryInterface, dxb_AddRef, dxb_Release, dxb_GetBufferPointer, dxb_GetBufferSize };
static void_com_class dxbuffer_class = { "ID3DXBuffer", 5, dxbuffer_methods, 0 };

static uint32_t make_buffer(const void *data, uint32_t size)
{
    dxbuffer_t *b = (dxbuffer_t *)calloc(1, sizeof *b);
    b->size = size;
    b->data = void_galloc(size ? size : 1);
    if (data) memcpy(GPTR(b->data), data, size);
    uint32_t guest = void_com_wrap(&b->com, &dxbuffer_class, 0);
    b->com.destroy = dxbuffer_destroy;
    return guest;
}

WINAPI_EXPORT(D3DX, D3DXCreateBuffer, 2)
{
    MEM32(ARG(1)) = make_buffer(NULL, ARG(0));
    return D3D_OK;
}

/* ================================================================ profiles */
static uint32_t vs_profile, ps_profile;
WINAPI_EXPORT(D3DX, D3DXGetVertexShaderProfile, 1) { if (!vs_profile) vs_profile = void_gstrdup("vs_3_0"); return vs_profile; }
WINAPI_EXPORT(D3DX, D3DXGetPixelShaderProfile, 1) { if (!ps_profile) ps_profile = void_gstrdup("ps_3_0"); return ps_profile; }

/* ====================================================== constant tables */
typedef struct {
    void_com_object com;
    uint32_t blob;           /* guest copy of the CTAB contents */
    uint32_t size;
    uint32_t handles;        /* guest block: one 8-byte cookie per constant */
    int count;
    int pixel;
} ctable_t;

static ctable_t *tables[4096];
static int table_count;

static uint32_t ct_info(ctable_t *t, int i) { return t->blob + MEM32(t->blob + 16) + 20u * (uint32_t)i; }
static uint32_t ct_type(ctable_t *t, int i) { return t->blob + MEM32(ct_info(t, i) + 12); }
static const char *ct_name(ctable_t *t, int i) { return (const char *)GPTR(t->blob + MEM32(ct_info(t, i))); }

static int ct_handle_index(ctable_t *t, uint32_t handle)
{
    if (!handle) return -1;
    if (handle >= t->handles && handle < t->handles + 8u * (uint32_t)t->count && !((handle - t->handles) & 7))
        return (int)((handle - t->handles) / 8);
    /* Not one of our handles: D3DX accepts the constant's name instead. */
    if (!void_vm_readable(handle, 1)) return -1;
    const char *name = (const char *)GPTR(handle);
    for (int i = 0; i < t->count; ++i) if (!strcmp(ct_name(t, i), name)) return i;
    return -1;
}

static void ct_destroy(void_com_object *o) { ctable_t *t = (ctable_t *)o; void_gfree(t->blob); void_gfree(t->handles); free(t); }

#define CT ((ctable_t *)void_com_host(THIS_))
static int ct_trace = -1;
#define CT_TRACE(...) do { if (ct_trace < 0) ct_trace = getenv("VOID_TRACE_CTAB") != NULL;     if (ct_trace) void_log("[ctab] " __VA_ARGS__); } while (0)

COM_METHOD(ct, QueryInterface, 3) { void_com_addref(&CT->com); MEM32(ARG(2)) = THIS_; return 0; }
COM_METHOD(ct, AddRef, 1) { return void_com_addref(&CT->com); }
COM_METHOD(ct, Release, 1) { return void_com_release(&CT->com); }
COM_METHOD(ct, GetBufferPointer, 1) { return CT->blob; }
COM_METHOD(ct, GetBufferSize, 1) { return CT->size; }
COM_METHOD(ct, GetDesc, 2)
{
    ctable_t *t = CT;
    uint32_t out = ARG(1);
    MEM32(out) = t->blob + MEM32(t->blob + 4);    /* Creator */
    MEM32(out + 4) = MEM32(t->blob + 8);          /* Version */
    MEM32(out + 8) = (uint32_t)t->count;
    return D3D_OK;
}

static void ct_fill_desc(ctable_t *t, int i, uint32_t out)
{
    uint32_t info = ct_info(t, i), type = ct_type(t, i);
    MEM32(out) = t->blob + MEM32(info);           /* Name */
    MEM32(out + 4) = MEM16(info + 4);             /* RegisterSet */
    MEM32(out + 8) = MEM16(info + 6);             /* RegisterIndex */
    MEM32(out + 12) = MEM16(info + 8);            /* RegisterCount */
    MEM32(out + 16) = MEM16(type);                /* Class */
    MEM32(out + 20) = MEM16(type + 2);            /* Type */
    MEM32(out + 24) = MEM16(type + 4);            /* Rows */
    MEM32(out + 28) = MEM16(type + 6);            /* Columns */
    MEM32(out + 32) = MEM16(type + 8) ? MEM16(type + 8) : 1;   /* Elements */
    MEM32(out + 36) = MEM16(type + 10);           /* StructMembers */
    MEM32(out + 40) = 4u * MEM16(type + 4) * MEM16(type + 6) * (MEM16(type + 8) ? MEM16(type + 8) : 1u);  /* Bytes */
    MEM32(out + 44) = MEM32(info + 16) ? t->blob + MEM32(info + 16) : 0;   /* DefaultValue */
}

COM_METHOD(ct, GetConstantDesc, 4)
{
    ctable_t *t = CT;
    int i = ct_handle_index(t, ARG(1));
    if (i < 0) { CT_TRACE("%08X GetConstantDesc(%08X) invalid", THIS_, ARG(1)); if (ARG(3)) MEM32(ARG(3)) = 0; return D3DERR_INVALIDCALL; }
    if (ARG(2)) ct_fill_desc(t, i, ARG(2));
    if (ARG(3)) MEM32(ARG(3)) = 1;
    CT_TRACE("%08X GetConstantDesc(#%d %s) set %u reg %u count %u class %u type %u", THIS_, i, ct_name(t, i),
        MEM16(ct_info(t, i) + 4), MEM16(ct_info(t, i) + 6), MEM16(ct_info(t, i) + 8), MEM16(ct_type(t, i)), MEM16(ct_type(t, i) + 2));
    return D3D_OK;
}

COM_METHOD(ct, GetSamplerIndex, 2)
{
    ctable_t *t = CT;
    int i = ct_handle_index(t, ARG(1));
    uint32_t r = (i < 0 || MEM16(ct_info(t, i) + 4) != 3) ? 0xFFFFFFFFu : MEM16(ct_info(t, i) + 6);
    CT_TRACE("%08X GetSamplerIndex(%08X -> #%d %s) = %d", THIS_, ARG(1), i, i >= 0 ? ct_name(t, i) : "?", (int)r);
    return r;
}

COM_METHOD(ct, GetConstant, 3)
{
    ctable_t *t = CT;
    if (ARG(1)) { void_log("[d3dx] GetConstant on a struct member is unsupported"); return 0; }
    CT_TRACE("%08X GetConstant(%u of %d)", THIS_, ARG(2), t->count);
    return ARG(2) < (uint32_t)t->count ? t->handles + 8u * ARG(2) : 0;
}

COM_METHOD(ct, GetConstantByName, 3)
{
    ctable_t *t = CT;
    if (ARG(1)) { void_log("[d3dx] GetConstantByName below a parent is unsupported"); return 0; }
    const char *name = (const char *)GPTR(ARG(2));
    for (int i = 0; i < t->count; ++i) if (!strcmp(ct_name(t, i), name)) {
        CT_TRACE("%08X GetConstantByName(%s) = #%d", THIS_, name, i);
        return t->handles + 8u * (uint32_t)i;
    }
    CT_TRACE("%08X GetConstantByName(%s) = not found", THIS_, name);
    return 0;
}

COM_METHOD(ct, GetConstantElement, 3)
{
    ctable_t *t = CT;
    int i = ct_handle_index(t, ARG(1));
    if (i >= 0 && ARG(2) == 0) return t->handles + 8u * (uint32_t)i;
    void_log("[d3dx] GetConstantElement(%u) unsupported", ARG(2));
    return 0;
}

extern uint32_t d3d_constant_generation;

/* Write float4 registers of the table's stage. */
static void write_f(ctable_t *t, uint32_t reg, const float *v, uint32_t count)
{
    d3d_device *d = g_d3d_device;
    if (!d) return;
    uint32_t limit = t->pixel ? 224 : 256;
    for (uint32_t i = 0; i < count && reg + i < limit; ++i)
        memcpy(t->pixel ? d->st.ps_f[reg + i] : d->st.vs_f[reg + i], v + 4 * i, 16);
    ++d3d_constant_generation;
}

static void write_i(ctable_t *t, uint32_t reg, const int32_t *v, uint32_t count)
{
    d3d_device *d = g_d3d_device;
    if (!d) return;
    for (uint32_t i = 0; i < count && reg + i < 16; ++i) memcpy(t->pixel ? d->st.ps_i[reg + i] : d->st.vs_i[reg + i], v + 4 * i, 16);
    ++d3d_constant_generation;
}

static void write_b(ctable_t *t, uint32_t reg, const int32_t *v, uint32_t count)
{
    d3d_device *d = g_d3d_device;
    if (!d) return;
    for (uint32_t i = 0; i < count && reg + i < 16; ++i) (t->pixel ? d->st.ps_b : d->st.vs_b)[reg + i] = v[i] != 0;
    ++d3d_constant_generation;
}

/* Set a constant from `n` floats laid out as D3DX does (row-major elements). */
static uint32_t set_floats(ctable_t *t, int i, const float *data, uint32_t n, int transpose)
{
    uint32_t info = ct_info(t, i), type = ct_type(t, i);
    uint32_t set = MEM16(info + 4), reg = MEM16(info + 6), regs = MEM16(info + 8);
    uint32_t cls = MEM16(type), rows = MEM16(type + 4), cols = MEM16(type + 6);
    uint32_t elements = MEM16(type + 8) ? MEM16(type + 8) : 1;
    float buf[4 * 256];
    memset(buf, 0, sizeof buf);
    uint32_t per = rows * cols;
    if (regs > 256) regs = 256;
    for (uint32_t e = 0; e < elements; ++e) {
        const float *m = data + e * per;
        if (e * per >= n) break;
        uint32_t regs_per = elements ? regs / elements : regs;
        for (uint32_t r = 0; r < regs_per; ++r) {
            float *out = buf + 4 * (e * regs_per + r);
            for (uint32_t c = 0; c < 4; ++c) {
                float v = 0.0f;
                if (cls == 3) {             /* MATRIX_COLUMNS: register r is column r */
                    if (r < cols && c < rows) v = transpose ? m[r * rows + c] : m[c * cols + r];
                } else if (cls == 2) {      /* MATRIX_ROWS */
                    if (r < rows && c < cols) v = transpose ? m[c * rows + r] : m[r * cols + c];
                } else {                    /* SCALAR / VECTOR */
                    if (r == 0 && c < cols) v = m[c];
                }
                out[c] = v;
            }
        }
    }
    if (set == 2) write_f(t, reg, buf, regs);
    else if (set == 1) { int32_t iv[4 * 16]; for (uint32_t k = 0; k < 4 * regs && k < 64; ++k) iv[k] = (int32_t)buf[k]; write_i(t, reg, iv, regs); }
    else if (set == 0) { int32_t bv[16]; for (uint32_t k = 0; k < regs && k < 16; ++k) bv[k] = buf[4 * k] != 0.0f; write_b(t, reg, bv, regs); }
    return D3D_OK;
}

COM_METHOD(ct, SetDefaults, 2)
{
    ctable_t *t = CT;
    for (int i = 0; i < t->count; ++i) {
        uint32_t info = ct_info(t, i);
        if (!MEM32(info + 16)) continue;
        uint32_t set = MEM16(info + 4), reg = MEM16(info + 6), regs = MEM16(info + 8);
        const float *def = (const float *)GPTR(t->blob + MEM32(info + 16));
        if (set == 2) write_f(t, reg, def, regs);
        else if (set == 1) write_i(t, reg, (const int32_t *)def, regs);
        else if (set == 0) write_b(t, reg, (const int32_t *)def, regs);
    }
    return D3D_OK;
}

COM_METHOD(ct, SetValue, 5)
{
    ctable_t *t = CT;
    int i = ct_handle_index(t, ARG(2));
    if (i < 0) return D3DERR_INVALIDCALL;
    return set_floats(t, i, (const float *)GPTR(ARG(3)), ARG(4) / 4, 0);
}

COM_METHOD(ct, SetBool, 4)
{
    ctable_t *t = CT;
    int i = ct_handle_index(t, ARG(2));
    if (i < 0) return D3DERR_INVALIDCALL;
    float f = ARG(3) ? 1.0f : 0.0f;
    return set_floats(t, i, &f, 1, 0);
}

static uint32_t set_array(ctable_t *t, uint32_t handle, uint32_t data, uint32_t count, int ints)
{
    int i = ct_handle_index(t, handle);
    if (i < 0) return D3DERR_INVALIDCALL;
    float tmp[1024];
    if (count > 1024) count = 1024;
    for (uint32_t k = 0; k < count; ++k) {
        uint32_t raw = MEM32(data + 4 * k);
        if (ints) tmp[k] = (float)(int32_t)raw; else memcpy(&tmp[k], &raw, 4);
    }
    return set_floats(t, i, tmp, count, 0);
}

COM_METHOD(ct, SetBoolArray, 5) { return set_array(CT, ARG(2), ARG(3), ARG(4), 1); }
COM_METHOD(ct, SetInt, 4) { ctable_t *t = CT; int i = ct_handle_index(t, ARG(2)); if (i < 0) return D3DERR_INVALIDCALL; float f = (float)(int32_t)ARG(3); return set_floats(t, i, &f, 1, 0); }
COM_METHOD(ct, SetIntArray, 5) { return set_array(CT, ARG(2), ARG(3), ARG(4), 1); }
COM_METHOD(ct, SetFloat, 4) { ctable_t *t = CT; int i = ct_handle_index(t, ARG(2)); if (i < 0) return D3DERR_INVALIDCALL; uint32_t u = ARG(3); float f; memcpy(&f, &u, 4); return set_floats(t, i, &f, 1, 0); }
COM_METHOD(ct, SetFloatArray, 5) { return set_array(CT, ARG(2), ARG(3), ARG(4), 0); }
COM_METHOD(ct, SetVector, 4) { return set_array(CT, ARG(2), ARG(3), 4, 0); }
COM_METHOD(ct, SetVectorArray, 5) { return set_array(CT, ARG(2), ARG(3), 4 * ARG(4), 0); }
COM_METHOD(ct, SetMatrix, 4)
{
    ctable_t *t = CT;
    int i = ct_handle_index(t, ARG(2));
    if (i < 0) return D3DERR_INVALIDCALL;
    uint32_t type = ct_type(t, i), rows = MEM16(type + 4), cols = MEM16(type + 6);
    /* Pick the rows x cols block out of the 4x4 D3DXMATRIX. */
    const float *m = (const float *)GPTR(ARG(3));
    float block[16];
    for (uint32_t r = 0; r < rows && r < 4; ++r) for (uint32_t c = 0; c < cols && c < 4; ++c) block[r * cols + c] = m[r * 4 + c];
    return set_floats(t, i, block, rows * cols, 0);
}
COM_METHOD(ct, SetMatrixArray, 5)
{
    ctable_t *t = CT;
    int i = ct_handle_index(t, ARG(2));
    if (i < 0) return D3DERR_INVALIDCALL;
    uint32_t type = ct_type(t, i), rows = MEM16(type + 4), cols = MEM16(type + 6), count = ARG(4);
    float *block = (float *)calloc((size_t)count * 16 + 16, sizeof(float));
    const float *m = (const float *)GPTR(ARG(3));
    for (uint32_t e = 0; e < count; ++e)
        for (uint32_t r = 0; r < rows && r < 4; ++r) for (uint32_t c = 0; c < cols && c < 4; ++c)
            block[e * rows * cols + r * cols + c] = m[e * 16 + r * 4 + c];
    uint32_t hr = set_floats(t, i, block, count * rows * cols, 0);
    free(block);
    return hr;
}
COM_METHOD(ct, SetMatrixPointerArray, 5) { void_log("[d3dx] SetMatrixPointerArray unsupported"); return D3DERR_INVALIDCALL; }
COM_METHOD(ct, SetMatrixTranspose, 4)
{
    ctable_t *t = CT;
    int i = ct_handle_index(t, ARG(2));
    if (i < 0) return D3DERR_INVALIDCALL;
    uint32_t type = ct_type(t, i), rows = MEM16(type + 4), cols = MEM16(type + 6);
    const float *m = (const float *)GPTR(ARG(3));
    float block[16];
    for (uint32_t r = 0; r < rows && r < 4; ++r) for (uint32_t c = 0; c < cols && c < 4; ++c) block[r * cols + c] = m[c * 4 + r];
    return set_floats(t, i, block, rows * cols, 0);
}
COM_METHOD(ct, SetMatrixTransposeArray, 5) { void_log("[d3dx] SetMatrixTransposeArray unsupported"); return D3DERR_INVALIDCALL; }
COM_METHOD(ct, SetMatrixTransposePointerArray, 5) { void_log("[d3dx] SetMatrixTransposePointerArray unsupported"); return D3DERR_INVALIDCALL; }

static const void_fn ctable_methods[] = {
    ct_QueryInterface, ct_AddRef, ct_Release, ct_GetBufferPointer, ct_GetBufferSize, ct_GetDesc, ct_GetConstantDesc,
    ct_GetSamplerIndex, ct_GetConstant, ct_GetConstantByName, ct_GetConstantElement, ct_SetDefaults, ct_SetValue,
    ct_SetBool, ct_SetBoolArray, ct_SetInt, ct_SetIntArray, ct_SetFloat, ct_SetFloatArray, ct_SetVector,
    ct_SetVectorArray, ct_SetMatrix, ct_SetMatrixArray, ct_SetMatrixPointerArray, ct_SetMatrixTranspose,
    ct_SetMatrixTransposeArray, ct_SetMatrixTransposePointerArray,
};
static void_com_class ctable_class = { "ID3DXConstantTable", 27, ctable_methods, 0 };

/* Find the CTAB comment in shader bytecode; returns the guest VA of its data. */
static uint32_t find_ctab(uint32_t code, uint32_t *size)
{
    uint32_t p = code + 4;
    for (int guard = 0; guard < 100000; ++guard) {
        uint32_t token = MEM32(p);
        if (token == 0x0000FFFFu) break;
        if ((token & 0xFFFF) == 0xFFFE) {
            uint32_t len = (token >> 16) & 0x7FFF;
            if (len >= 1 && MEM32(p + 4) == FOURCC('C','T','A','B')) { *size = 4 * (len - 1); return p + 8; }
            p += 4 + 4 * len;
            continue;
        }
        break;   /* comments precede instructions */
    }
    return 0;
}

static uint32_t make_ctable(uint32_t code)
{
    uint32_t size = 0, ctab = find_ctab(code, &size);
    if (!ctab) return 0;
    ctable_t *t = (ctable_t *)calloc(1, sizeof *t);
    t->size = size;
    t->blob = void_galloc(size);
    memcpy(GPTR(t->blob), GPTR(ctab), size);
    t->count = (int)MEM32(t->blob + 12);
    t->pixel = (MEM32(code) & 0xFFFF0000u) == 0xFFFF0000u;
    t->handles = void_galloc(8u * (uint32_t)(t->count ? t->count : 1));
    for (int i = 0; i < t->count; ++i) { MEM32(t->handles + 8u * (uint32_t)i) = FOURCC('C','T','H','D'); MEM32(t->handles + 8u * (uint32_t)i + 4) = (uint32_t)i; }
    uint32_t guest = void_com_wrap(&t->com, &ctable_class, 0);
    t->com.destroy = ct_destroy;
    if (table_count < 4096) tables[table_count++] = t;
    return guest;
}

WINAPI_EXPORT(D3DX, D3DXGetShaderConstantTable, 2)
{
    uint32_t t = make_ctable(ARG(0));
    MEM32(ARG(1)) = t;
    return t ? D3D_OK : D3DERR_INVALIDCALL;
}

WINAPI_EXPORT(D3DX, D3DXGetShaderConstantTableEx, 3)
{
    uint32_t t = make_ctable(ARG(0));
    MEM32(ARG(2)) = t;
    return t ? D3D_OK : D3DERR_INVALIDCALL;
}

/* Input semantics from dcl instructions on v# registers. */
WINAPI_EXPORT(D3DX, D3DXGetShaderInputSemantics, 3)
{
    uint32_t code = ARG(0), out = ARG(1), count_out = ARG(2);
    uint32_t p = code + 4, n = 0;
    int pixel = (MEM32(code) & 0xFFFF0000u) == 0xFFFF0000u;
    for (int guard = 0; guard < 100000; ++guard) {
        uint32_t token = MEM32(p);
        if (token == 0x0000FFFFu) break;
        if ((token & 0xFFFF) == 0xFFFE) { p += 4 + 4 * ((token >> 16) & 0x7FFF); continue; }
        uint32_t opcode = token & 0xFFFF, len = (token >> 24) & 0x0F;
        if (opcode == 31 && len >= 2) {
            uint32_t usage = MEM32(p + 4), reg = MEM32(p + 8);
            uint32_t type = ((reg >> 28) & 7) | ((reg >> 8) & 0x18);
            if (type == 1 || (pixel && type == 3)) {
                if (out) { MEM32(out + 8 * n) = usage & 0x1F; MEM32(out + 8 * n + 4) = (usage >> 16) & 0xF; }
                ++n;
            }
        }
        p += 4 + 4 * len;
    }
    if (count_out) MEM32(count_out) = n;
    return D3D_OK;
}

WINAPI_EXPORT(D3DX, D3DXGetShaderOutputSemantics, 3) { if (ARG(2)) MEM32(ARG(2)) = 0; return D3D_OK; }

/* ===================================================== shader compilation */
static uint64_t fnv(uint64_t h, const void *data, size_t n)
{
    const uint8_t *p = (const uint8_t *)data;
    for (size_t i = 0; i < n; ++i) { h ^= p[i]; h *= 0x100000001B3ull; }
    return h;
}

static char *read_all(const char *path, size_t *size)
{
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    if (fseek(f, 0, SEEK_END)) { fclose(f); return NULL; }
    long n = ftell(f);
    if (n < 0 || (uint64_t)n > UINT32_MAX) { fclose(f); return NULL; }
    rewind(f);
    char *data = (char *)malloc((size_t)n + 1);
    if (!data) { fclose(f); return NULL; }
    if (fread(data, 1, (size_t)n, f) != (size_t)n) { free(data); fclose(f); return NULL; }
    data[n] = 0;
    fclose(f);
    *size = (size_t)n;
    return data;
}

/* ======================================================== texture shaders */
/* tx_1_0 texture shaders fill procedural textures on the CPU in D3DX. The
 * game's few sources are recognised by their exact text and evaluated by an
 * equivalent C procedure; the "bytecode" handed back names the procedure. */
enum { TX_NONE, TX_NORMALIZE_CUBE };
typedef struct { const char *source; int proc; } tx_known_t;
static const tx_known_t tx_known[] = {
    {"float3 main(float3 dir: POSITION, float size: PSIZE): COLOR\n{\n\treturn (normalize(dir) + 1) / 2;\n}", TX_NORMALIZE_CUBE},
};

static int tx_match(const char *src, uint32_t len)
{
    for (size_t i = 0; i < sizeof tx_known / sizeof tx_known[0]; ++i) {
        size_t n = strlen(tx_known[i].source);
        /* Line endings may be CRLF in the original text. */
        size_t a = 0, b = 0;
        while (a < len && b < n) {
            if (src[a] == '\r') { ++a; continue; }
            if (src[a] != tx_known[i].source[b]) break;
            ++a; ++b;
        }
        while (a < len && (src[a] == '\r' || src[a] == '\n' || src[a] == 0)) ++a;
        if (a == len && b == n) return tx_known[i].proc;
    }
    return TX_NONE;
}

static uint32_t tx_bytecode(int proc)
{
    /* version 'TX' 1.0, a VTXS comment naming the procedure, end token */
    uint32_t code[5] = { 0x54580100u, 0x0002FFFEu, FOURCC('V','T','X','S'), (uint32_t)proc, 0x0000FFFFu };
    return make_buffer(code, sizeof code);
}

typedef struct { void_com_object com; int proc; } txshader_t;
#define TXS ((txshader_t *)void_com_host(THIS_))
COM_METHOD(txs, QueryInterface, 3) { void_com_addref(&TXS->com); MEM32(ARG(2)) = THIS_; return 0; }
COM_METHOD(txs, AddRef, 1) { return void_com_addref(&TXS->com); }
COM_METHOD(txs, Release, 1) { return void_com_release(&TXS->com); }
COM_METHOD(txs, GetFunction, 2) { MEM32(ARG(1)) = tx_bytecode(TXS->proc); return D3D_OK; }
COM_METHOD(txs, GetConstantBuffer, 2) { MEM32(ARG(1)) = make_buffer(NULL, 0); return D3D_OK; }
COM_METHOD(txs, GetDesc, 2) { MEM32(ARG(1)) = 0; MEM32(ARG(1) + 4) = 0x54580100u; MEM32(ARG(1) + 8) = 0; return D3D_OK; }
COM_TODO(txs, ConstantAccess)
static const void_fn txshader_methods[] = {
    txs_QueryInterface, txs_AddRef, txs_Release, txs_GetFunction, txs_GetConstantBuffer, txs_GetDesc,
    txs_ConstantAccess, txs_ConstantAccess, txs_ConstantAccess, txs_ConstantAccess, txs_ConstantAccess,
    txs_ConstantAccess, txs_ConstantAccess, txs_ConstantAccess, txs_ConstantAccess, txs_ConstantAccess,
    txs_ConstantAccess, txs_ConstantAccess, txs_ConstantAccess, txs_ConstantAccess, txs_ConstantAccess,
    txs_ConstantAccess, txs_ConstantAccess, txs_ConstantAccess, txs_ConstantAccess, txs_ConstantAccess,
};
static void_com_class txshader_class = { "ID3DXTextureShader", 26, txshader_methods, 0 };

WINAPI_EXPORT(D3DX, D3DXCreateTextureShader, 2)
{
    uint32_t code = ARG(0);
    if (MEM32(code) != 0x54580100u || MEM32(code + 8) != FOURCC('V','T','X','S')) {
        void_log("[d3dx] D3DXCreateTextureShader: unknown texture shader bytecode");
        return D3DERR_INVALIDCALL;
    }
    txshader_t *t = (txshader_t *)calloc(1, sizeof *t);
    t->proc = (int)MEM32(code + 12);
    MEM32(ARG(1)) = void_com_wrap(&t->com, &txshader_class, 0);
    return D3D_OK;
}

static void tx_eval(int proc, const float in[3], float size, float out[4])
{
    (void)size;
    switch (proc) {
    case TX_NORMALIZE_CUBE: {
        float len = sqrtf(in[0] * in[0] + in[1] * in[1] + in[2] * in[2]);
        for (int k = 0; k < 3; ++k) out[k] = (in[k] / len + 1.0f) / 2.0f;
        out[3] = 1.0f;
        break;
    }
    default:
        out[0] = out[1] = out[2] = 0.0f;
        out[3] = 1.0f;
    }
}

/* Store one texel of a byte format from a float colour (D3DX rounding). */
static void tx_store(uint8_t *p, uint32_t format, const float c[4])
{
    uint32_t q[4];
    for (int k = 0; k < 4; ++k) {
        float v = c[k] < 0.0f ? 0.0f : c[k] > 1.0f ? 1.0f : c[k];
        q[k] = (uint32_t)(v * 255.0f + 0.5f);
    }
    switch (format) {
    case 21: case 22:
        p[0] = (uint8_t)q[2]; p[1] = (uint8_t)q[1]; p[2] = (uint8_t)q[0]; p[3] = format == 22 ? 255 : (uint8_t)q[3];
        break;
    case 50: p[0] = (uint8_t)q[0]; break;
    case 51: p[0] = (uint8_t)q[0]; p[1] = (uint8_t)q[3]; break;
    case 28: p[0] = (uint8_t)q[3]; break;
    default: p[0] = (uint8_t)q[2]; p[1] = (uint8_t)q[1]; p[2] = (uint8_t)q[0]; p[3] = (uint8_t)q[3]; break;
    }
}

static uint32_t tx_fill(d3d_texture *t, int proc)
{
    const d3d_format *f = t->fmt;
    if (f->block_bytes || !(t->format == 21 || t->format == 22 || t->format == 50 || t->format == 51 || t->format == 28)) {
        void_log("[d3dx] texture shader fill into format %u unsupported", t->format);
        return D3DERR_INVALIDCALL;
    }
    uint32_t bpp = f->bits / 8;
    for (int face = 0; face < t->faces; ++face) {
        for (uint32_t l = 0; l < t->levels; ++l) {
            uint32_t w, h;
            d3d_texture_level_size(t, l, &w, &h);
            uint32_t pitch = d3d_format_pitch(f, w);
            uint8_t *data = (uint8_t *)calloc((size_t)pitch * h, 1);
            for (uint32_t y = 0; y < h; ++y) {
                for (uint32_t x = 0; x < w; ++x) {
                    float in[3], out[4], size;
                    if (t->rtype == D3DRTYPE_CUBETEXTURE) {
                        /* D3DX cube face directions (texel centres in [-1, 1]). */
                        float u = ((float)x + 0.5f) / (float)w * 2.0f - 1.0f, v = ((float)y + 0.5f) / (float)h * 2.0f - 1.0f;
                        switch (face) {
                        case 0: in[0] = 1.0f; in[1] = -v; in[2] = -u; break;
                        case 1: in[0] = -1.0f; in[1] = -v; in[2] = u; break;
                        case 2: in[0] = u; in[1] = 1.0f; in[2] = v; break;
                        case 3: in[0] = u; in[1] = -1.0f; in[2] = -v; break;
                        case 4: in[0] = u; in[1] = -v; in[2] = 1.0f; break;
                        default: in[0] = -u; in[1] = -v; in[2] = -1.0f; break;
                        }
                        size = 2.0f / (float)w;
                    } else {
                        in[0] = ((float)x + 0.5f) / (float)w;
                        in[1] = ((float)y + 0.5f) / (float)h;
                        in[2] = 0.0f;
                        size = 1.0f / (float)w;
                    }
                    tx_eval(proc, in, size, out);
                    tx_store(data + (size_t)y * pitch + (size_t)x * bpp, t->format, out);
                }
            }
            d3d_texture_upload_level(t, (uint32_t)face, l, data, pitch);
            if (t->sysmem) {
                uint32_t index = (uint32_t)face * t->levels + l;
                if (!t->sysmem[index]) t->sysmem[index] = void_galloc(pitch * h);
                memcpy(GPTR(t->sysmem[index]), data, (size_t)pitch * h);
            }
            free(data);
        }
    }
    return D3D_OK;
}

WINAPI_EXPORT(D3DX, D3DXFillTextureTX, 2)
{
    return tx_fill((d3d_texture *)void_com_host(ARG(0)), ((txshader_t *)void_com_host(ARG(1)))->proc);
}

WINAPI_EXPORT(D3DX, D3DXFillCubeTextureTX, 2)
{
    return tx_fill((d3d_texture *)void_com_host(ARG(0)), ((txshader_t *)void_com_host(ARG(1)))->proc);
}

/* Shader bytecode from the content-addressed cache <data>/shadercache, keyed
 * by everything the result depends on. A miss is recorded as a request for
 * Microsoft's d3dx9_36.dll on the PC (tools/shader_service.py) and, with
 * VOID_SHADER_WAIT=<seconds>, waited for. `function` "@asm" with profile
 * "asm" stands for D3DXAssembleShader. Failures are cached as well (<hash>.err,
 * "hr=XXXXXXXX" then the messages), so the game sees the error Windows gives.
 * Returns 1 with *out an ID3DXBuffer of bytecode, -1 with *out an ID3DXBuffer
 * of messages and *hr the HRESULT, or 0 when the cache cannot answer. */
static int cache_bytecode_valid(const char *bytes, size_t size)
{
    uint32_t version = 0, end = 0;
    if (size < 8 || size % 4) return 0;
    memcpy(&version, bytes, 4);
    memcpy(&end, bytes + size - 4, 4);
    uint32_t type = version >> 16, major = (version >> 8) & 255;
    return (type == 0xfffe || type == 0xffff || type == 0x5458) && major >= 1 && major <= 3 && end == 0x0000ffff;
}

static int cache_answer_in(const char *dir, uint64_t h, uint32_t *out, uint32_t *hr, int errors, int binary)
{
    char path[1200];
    size_t size = 0;
    snprintf(path, sizeof path, "%s/%016llx.bin", dir, (unsigned long long)h);
    char *blob = read_all(path, &size);
    if (blob && size && (!binary || cache_bytecode_valid(blob, size))) {
        *out = make_buffer(blob, (uint32_t)size);
        free(blob);
        return 1;
    }
    free(blob);
    if (!errors) return 0;
    snprintf(path, sizeof path, "%s/%016llx.err", dir, (unsigned long long)h);
    blob = read_all(path, &size);
    if (!blob || !size) { free(blob); return 0; }
    unsigned long code = 0;
    char *messages = blob;
    if (sscanf(blob, "hr=%lx", &code) == 1) {
        char *nl = memchr(blob, '\n', size);
        messages = nl ? nl + 1 : blob + size;
    }
    *hr = code ? (uint32_t)code : E_FAIL_;
    size_t n = size - (size_t)(messages - blob);
    *out = make_buffer(messages, (uint32_t)n + 1);
    ((char *)GPTR(((dxbuffer_t *)void_com_host(*out))->data))[n] = 0;
    free(blob);
    return -1;
}

/* A development switch (a <data>/shadercache/no-bundle file, like the wait
 * file; the APK sets no environment): ignore the APK's bundled cache, so the
 * on-device compiler is exercised against a cold profile. */
static int bundle_disabled(void)
{
    static int cached = -1;
    if (cached < 0) {
        char p[1200];
        snprintf(p, sizeof p, "%s/shadercache/no-bundle", void_data_dir());
        cached = access(p, F_OK) == 0;
        if (cached) void_log("[d3dx] packaged shader bundle ignored (no-bundle)");
    }
    return cached;
}

static int cache_answer(uint64_t h, uint32_t *out, uint32_t *hr, int binary)
{
    char profile[1100];
    snprintf(profile, sizeof profile, "%s/shadercache", void_data_dir());
    int packaged = packaged_cache_dir[0] && !bundle_disabled();
    /* A corrected bundled success supersedes an older recorded compile failure. */
    int answer = cache_answer_in(profile, h, out, hr, 0, binary);
    if (!answer && packaged) answer = cache_answer_in(packaged_cache_dir, h, out, hr, 0, binary);
    if (!answer) answer = cache_answer_in(profile, h, out, hr, 1, binary);
    if (!answer && packaged) answer = cache_answer_in(packaged_cache_dir, h, out, hr, 1, binary);
    if (answer) atomic_fetch_add_explicit(&cache_responses, 1, memory_order_relaxed);
    return answer;
}

/* The seconds to wait for the development service: VOID_SHADER_WAIT, or what
 * <data>/shadercache/wait holds (a device whose cache is being filled: the
 * APK sets no environment), read again every few seconds. */
static int shader_wait_seconds(uint64_t now)
{
    static uint64_t read_at;
    static int seconds;
    const char *wait = getenv("VOID_SHADER_WAIT");
    if (wait) return atoi(wait);
    if (!read_at || now - read_at >= 5000000000ull) {
        char path[1200];
        size_t n = 0;
        snprintf(path, sizeof path, "%s/shadercache/wait", void_data_dir());
        char *w = read_all(path, &n);
        seconds = w ? atoi(w) : 0;
        free(w);
        read_at = now;
    }
    return seconds;
}

/* Shaders the cache could not answer. RendererD3D asks again for a variant
 * it failed to get in every frame that draws with it: remembered here, such
 * a request costs no file system calls (the profile's cache is on shared
 * storage, a few milliseconds each). Looked up again after a while, when the
 * development service may have answered. */
#define MISS_SLOTS 4096u
#define MISS_RECHECK_NS 10000000000ull
static struct { uint64_t key, at; } misses[MISS_SLOTS];

static int miss_recent(uint64_t h, uint64_t now)
{
    for (uint32_t i = 0, at = (uint32_t)h & (MISS_SLOTS - 1); i < 16; ++i, at = (at + 1) & (MISS_SLOTS - 1)) {
        if (!misses[at].at) return 0;
        if (misses[at].key == h) return now - misses[at].at < MISS_RECHECK_NS;
    }
    return 0;
}

static void miss_note(uint64_t h, uint64_t now, int missing)
{
    uint32_t at = (uint32_t)h & (MISS_SLOTS - 1), free_at = MISS_SLOTS;
    for (uint32_t i = 0; i < 16; ++i, at = (at + 1) & (MISS_SLOTS - 1)) {
        if (misses[at].at && misses[at].key == h) { misses[at].at = missing ? now : 1; return; }
        if (free_at == MISS_SLOTS && (!misses[at].at || misses[at].at == 1)) free_at = at;
        if (!misses[at].at) break;
    }
    if (!missing) return;
    if (free_at == MISS_SLOTS) free_at = (uint32_t)h & (MISS_SLOTS - 1);   /* a full run: the oldest guess goes */
    misses[free_at].key = h;
    misses[free_at].at = now;
}

/* ---- the lifted Microsoft compiler (tools/lift_d3dx.py), on the device ----
 * d3dxcompiler_void.dll is the November 2007 d3dx9_36.dll lifted under a
 * private name. On a shader cache miss the host loads it (its DllMain and CRT
 * initialisers run then, once) and calls its real D3DXCompileShader on the
 * guest machine; the bytecode (or Microsoft's exact error) is written into the
 * profile cache, so the phone compiles the shaders the renderer asks for
 * itself and never asks a PC again. Validation (d3d9.dll) is absent, so the
 * compiler skips it and still emits bytecode, which is what the renderer
 * draws with. */
#define D3DXC_COMPILE 0x1A20DAE4u   /* _D3DXCompileShader@40, base 0x1A000000 */

static int d3dx_loaded, d3dx_tried;
static int d3dx_device_ready(void)
{
    if (!d3dx_tried) {
        d3dx_tried = 1;
        /* Opt-in while the lifted compiler is being brought up: it loads and
         * runs (DllMain, CRT init, the HLSL front end) but still faults deep in
         * a shader compile, so it runs only when <data>/shadercache/device-compile
         * exists. Without it a cache miss falls back to the recorded request and
         * bundled cache, exactly as before -- safe for normal play. */
        char p[1200];
        snprintf(p, sizeof p, "%s/shadercache/device-compile", void_data_dir());
        if (access(p, F_OK) != 0) return 0;
        uint64_t t0 = void_monotonic_ns();
        d3dx_loaded = void_module_load("d3dxcompiler_void.dll") != 0;
        void_log("[d3dx] on-device compiler %s (load %llu ms)", d3dx_loaded ? "ready" : "unavailable",
            (unsigned long long)((void_monotonic_ns() - t0) / 1000000ull));
    }
    return d3dx_loaded;
}

/* An ID3DXBuffer the lifted compiler returned: its bytes, then released.
 * Its methods are COM (STDMETHODCALLTYPE, i.e. __stdcall): `this` is the first
 * STACK argument, not ecx -- the lifted GetBufferPointer is `mov eax,[ebp+8];
 * mov eax,[eax+0xc]; ret 4`. So call them with `this` pushed as arg0, not
 * through void_call_guest_this (which puts it in ecx, as the game's own
 * __thiscall C++ methods want); ecx-passing left `this` as a stale stack slot
 * -- a leaked RECOMP_RETADDR -- and the getter faulted dereferencing it. */
static uint8_t *dxbuf_take(uint32_t buf, uint32_t *size)
{
    if (!buf) { *size = 0; return NULL; }
    uint32_t vt = MEM32(buf);
    uint32_t data = void_call_guest(MEM32(vt + 12), 1, &buf, 1);   /* GetBufferPointer */
    uint32_t n = void_call_guest(MEM32(vt + 16), 1, &buf, 1);      /* GetBufferSize */
    uint8_t *copy = NULL;
    if (data && n && n < 0x400000u) { copy = (uint8_t *)malloc(n); if (copy) memcpy(copy, GPTR(data), n); }
    *size = copy ? n : 0;
    void_call_guest(MEM32(vt + 8), 1, &buf, 1);                    /* Release */
    return copy;
}

/* Compile HLSL on the device and write <hash>.bin (bytecode) or <hash>.err
 * (Microsoft's message, "hr=XXXXXXXX" then text) into the profile cache, as
 * tools/shader_service.py does from a PC. Returns 1 if it wrote either. */
static int d3dx_device_fill(uint64_t h, uint32_t src, uint32_t len, uint32_t defines, uint32_t include,
    const char *function, const char *profile, uint32_t flags)
{
    if (!d3dx_device_ready()) return 0;
    uint32_t fva = void_gstrdup(function), pva = void_gstrdup(profile), out3 = void_galloc(12);
    MEM32(out3) = MEM32(out3 + 4) = MEM32(out3 + 8) = 0;
    uint32_t args[10] = { src, len, defines, include, fva, pva, flags, out3, out3 + 4, out3 + 8 };
    uint64_t t0 = void_monotonic_ns();
    uint32_t hr = void_call_guest(D3DXC_COMPILE, 10, args, 1);
    uint32_t shader = MEM32(out3), errors = MEM32(out3 + 4), ctab = MEM32(out3 + 8);
    uint32_t nbytes = 0, nerr = 0;
    uint8_t *bytecode = (int32_t)hr >= 0 ? dxbuf_take(shader, &nbytes) : NULL;
    uint8_t *message = dxbuf_take(errors, &nerr);   /* errors released either way */
    if (ctab) { uint32_t vt = MEM32(ctab); void_call_guest(MEM32(vt + 8), 1, &ctab, 1); }   /* ID3DXConstantTable::Release (COM: this on the stack) */
    void_gfree(fva); void_gfree(pva); void_gfree(out3);
    char path[1200], part[1200];
    int wrote = 0;
    if (bytecode && nbytes) {
        snprintf(part, sizeof part, "%s/shadercache/%016llx.part", void_data_dir(), (unsigned long long)h);
        snprintf(path, sizeof path, "%s/shadercache/%016llx.bin", void_data_dir(), (unsigned long long)h);
        FILE *f = fopen(part, "wb");
        if (f) { int ok = fwrite(bytecode, 1, nbytes, f) == nbytes; if (fclose(f)) ok = 0;
            wrote = ok && rename(part, path) == 0; if (!wrote) unlink(part); }
        void_log("[d3dx] compiled %s/%s on the device: %u bytes -> %016llx (%llu ms)", function, profile, nbytes,
            (unsigned long long)h, (unsigned long long)((void_monotonic_ns() - t0) / 1000000ull));
    } else {
        snprintf(part, sizeof part, "%s/shadercache/%016llx.part", void_data_dir(), (unsigned long long)h);
        snprintf(path, sizeof path, "%s/shadercache/%016llx.err", void_data_dir(), (unsigned long long)h);
        FILE *f = fopen(part, "wb");
        if (f) { int ok = fprintf(f, "hr=%08lX\n", (unsigned long)hr) >= 0;
            if (message && nerr) ok = ok && fwrite(message, 1, nerr, f) == nerr;
            if (fclose(f)) ok = 0; wrote = ok && rename(part, path) == 0; if (!wrote) unlink(part); }
        void_log("[d3dx] %s/%s failed on the device as on Windows: hr=%08lX %s", function, profile,
            (unsigned long)hr, message ? (const char *)message : "");
    }
    free(bytecode);
    free(message);
    return wrote;
}

static int shader_service(uint32_t src, uint32_t len, uint32_t defines, uint32_t include, const char *function,
    const char *profile, uint32_t flags, uint32_t *out, uint32_t *hr)
{
    uint64_t h = 0xCBF29CE484222325ull;
    h = fnv(h, GPTR(src), len);
    h = fnv(h, "\0", 1);
    char macros[16384];
    size_t mlen = 0;
    macros[0] = 0;
    for (uint32_t d = defines; d && MEM32(d); d += 8) {
        const char *name = (const char *)GPTR(MEM32(d));
        const char *value = MEM32(d + 4) ? (const char *)GPTR(MEM32(d + 4)) : "";
        mlen += (size_t)snprintf(macros + mlen, sizeof macros - mlen, "%s=%s\n", name, value);
        if (mlen >= sizeof macros) mlen = sizeof macros - 1;
    }
    h = fnv(h, macros, mlen);
    h = fnv(h, function, strlen(function) + 1);
    uint64_t family = fnv(h, &flags, 4);
    h = fnv(h, profile, strlen(profile) + 1);
    h = fnv(h, &flags, 4);
    char dir[1100], path[1200];
    static int made;
    if (!made) {
        snprintf(dir, sizeof dir, "%s/shadercache", void_data_dir());
        mkdir(dir, 0775);
        snprintf(dir, sizeof dir, "%s/shadercache/requests", void_data_dir());
        mkdir(dir, 0775);
        made = 1;
    }
    int binary = strcmp(profile, "disasm") != 0;
    uint64_t now = void_monotonic_ns();
    int wait_s = shader_wait_seconds(now);
    if (wait_s <= 0 && miss_recent(h, now)) {
        if (function[0] != '@') shader_family_result(h, family, 1);
        return 0;
    }
    int answer = cache_answer(h, out, hr, binary);
    if (answer) {
        miss_note(h, now, 0);
        if (answer > 0) shader_family_result(h, family, 0);
        else shader_missing(h, 0);
        VLOG("[d3dx] %s/%s from cache %016llx (%s)", function, profile, (unsigned long long)h, answer > 0 ? "bytecode" : "error");
        return answer;
    }
    /* The device compiles HLSL itself (the lifted Microsoft compiler), writes
     * the result into the cache and answers from it: no PC, no waiting. */
    if (function[0] != '@' && d3dx_device_fill(h, src, len, defines, include, function, profile, flags)) {
        answer = cache_answer(h, out, hr, binary);
        if (answer) {
            miss_note(h, now, 0);
            if (answer > 0) shader_family_result(h, family, 0);
            else shader_missing(h, 0);
            return answer;
        }
    }
    /* Publish once, atomically: a reader must never pull a partial request. */
    snprintf(dir, sizeof dir, "%s/shadercache/requests", void_data_dir());
    snprintf(path, sizeof path, "%s/%016llx.req", dir, (unsigned long long)h);
    if (access(path, F_OK)) {
        char part[1200];
        snprintf(part, sizeof part, "%s/%016llx.part", dir, (unsigned long long)h);
        FILE *f = fopen(part, "wb");
        if (f) {
            int ok = fprintf(f, "function=%s\nprofile=%s\nflags=%u\ninclude=%s\nmacros=%zu\n%ssource=%u\n", function, profile, flags,
                include ? "yes" : "no", mlen, macros, len) >= 0;
            if (fwrite(GPTR(src), 1, len, f) != len) ok = 0;
            if (fclose(f)) ok = 0;
            if (ok && rename(part, path) == 0)
                void_log("[d3dx] %s/%s flags %X: cache miss %016llx recorded (%u bytes)", function, profile, flags,
                    (unsigned long long)h, len);
            else unlink(part);
        }
    }
    /* Development: wait for the PC-side service (tools/shader_service.py --watch). */
    int wait_ms = wait_s * 1000;
    if (wait_ms <= 0) {
        miss_note(h, now, 1);
        if (function[0] != '@') shader_family_result(h, family, 1);
        return 0;
    }
    char bin[1200], err[1200];
    snprintf(bin, sizeof bin, "%s/shadercache/%016llx.bin", void_data_dir(), (unsigned long long)h);
    snprintf(err, sizeof err, "%s/shadercache/%016llx.err", void_data_dir(), (unsigned long long)h);
    void_blocking_begin();
    for (int waited = 0; waited < wait_ms && access(bin, F_OK) && access(err, F_OK); waited += 100) usleep(100000);
    void_blocking_end();
    usleep(200000);   /* let the push finish writing */
    answer = cache_answer(h, out, hr, binary);
    if (answer > 0) shader_family_result(h, family, 0);
    else if (!answer && function[0] != '@') shader_family_result(h, family, 1);
    else if (answer) shader_missing(h, 0);
    if (answer) void_log("[d3dx] %016llx served by the live compile service (%s)", (unsigned long long)h,
        answer > 0 ? "bytecode" : "error");
    return answer;
}

/* D3DXCompileShader(src, len, defines, include, function, profile, flags,
 *                   ppShader, ppErrors, ppConstantTable) */
WINAPI_EXPORT(D3DX, D3DXCompileShader, 10)
{
    uint32_t src = ARG(0), len = ARG(1), defines = ARG(2), include = ARG(3);
    const char *function = ARG(4) ? (const char *)GPTR(ARG(4)) : "";
    const char *profile = ARG(5) ? (const char *)GPTR(ARG(5)) : "";
    uint32_t flags = ARG(6);
    if (!strcmp(profile, "tx_1_0")) {
        int proc = tx_match((const char *)GPTR(src), len);
        if (proc != TX_NONE) {
            if (ARG(7)) MEM32(ARG(7)) = tx_bytecode(proc);
            if (ARG(8)) MEM32(ARG(8)) = 0;
            if (ARG(9)) MEM32(ARG(9)) = 0;
            VLOG("[d3dx] texture shader recognised as procedure %d", proc);
            return D3D_OK;
        }
    }
    uint32_t buffer = 0, hr = 0;
    int answer = shader_service(src, len, defines, include, function, profile, flags, &buffer, &hr);
    if (answer > 0) {
        if (ARG(7)) MEM32(ARG(7)) = buffer;
        if (ARG(8)) MEM32(ARG(8)) = 0;
        if (ARG(9)) MEM32(ARG(9)) = make_ctable(((dxbuffer_t *)void_com_host(buffer))->data);
        return D3D_OK;
    }
    if (answer < 0) {
        void_log("[d3dx] D3DXCompileShader %s/%s fails as on Windows: %s", function, profile,
            (const char *)GPTR(((dxbuffer_t *)void_com_host(buffer))->data));
        if (ARG(8)) MEM32(ARG(8)) = buffer; else void_com_release((void_com_object *)void_com_host(buffer));
        if (ARG(7)) MEM32(ARG(7)) = 0;
        if (ARG(9)) MEM32(ARG(9)) = 0;
        return hr;
    }
    const char *message = "error X0000: HLSL compilation is served from the offline cache only\n";
    if (ARG(8)) MEM32(ARG(8)) = make_buffer(message, (uint32_t)strlen(message) + 1);
    if (ARG(7)) MEM32(ARG(7)) = 0;
    if (ARG(9)) MEM32(ARG(9)) = 0;
    return E_FAIL_;
}

WINAPI_EXPORT(D3DX, D3DXCompileShaderFromFileA, 9)
{
    char *file = void_astr_utf8(ARG(0));
    void_log("[d3dx] D3DXCompileShaderFromFileA(%s) unsupported", file ? file : "");
    free(file);
    if (ARG(6)) MEM32(ARG(6)) = 0;
    if (ARG(7)) MEM32(ARG(7)) = 0;
    if (ARG(8)) MEM32(ARG(8)) = 0;
    return E_FAIL_;
}

/* RendererD3D disassembles shaders it compiled and assembles the text again
 * (unchanged, as far as seen). Without Microsoft's answers in the cache that
 * text is MojoShader's, whose assembler cannot read every one of them back
 * (vs_1_1 relative addressing: "instruction token high bit must be zero"),
 * and the renderer then reads the buffer a failed assembly left empty. So
 * each disassembly handed out is remembered with its bytecode: the same
 * instructions come back as that bytecode. */
typedef struct { uint64_t key, at; uint32_t size; void *code; } disassembly_t;
static disassembly_t disassemblies[16];
static unsigned disassembly_next;

/* The instructions of an assembly text: comments, blank lines, indentation
 * and the end token aside. */
static uint64_t assembly_key(const char *text, size_t n)
{
    uint64_t h = 0xCBF29CE484222325ull;
    for (size_t i = 0; i < n && text[i];) {
        size_t end = i;
        while (end < n && text[end] && text[end] != '\n') ++end;
        size_t a = i, b = end;
        while (a < b && (text[a] == ' ' || text[a] == '\t' || text[a] == '\r')) ++a;
        while (b > a && (text[b - 1] == ' ' || text[b - 1] == '\t' || text[b - 1] == '\r')) --b;
        int comment = b - a >= 2 && text[a] == '/' && text[a + 1] == '/';
        int end_token = b - a == 3 && !memcmp(text + a, "end", 3);
        if (b > a && !comment && !end_token) { h = fnv(h, text + a, b - a); h = fnv(h, "\n", 1); }
        i = end + 1;
    }
    return h;
}

static void remember_disassembly(const char *text, size_t n, uint32_t code, uint32_t size)
{
    void *copy = malloc(size);
    if (!copy) return;
    memcpy(copy, GPTR(code), size);
    disassembly_t *d = &disassemblies[disassembly_next++ % 16];
    free(d->code);
    d->key = assembly_key(text, n);
    d->at = void_monotonic_ns();
    d->size = size;
    d->code = copy;
}

/* D3DXAssembleShader(src, len, defines, include, flags, ppShader, ppErrors):
 * Microsoft's assembler through the shader cache; the bytecode of a
 * disassembly whose text comes back; MojoShader's assembler only when
 * neither can answer (it drops ps_3_0 input semantics). */
WINAPI_EXPORT(D3DX, D3DXAssembleShader, 7)
{
    uint32_t src = ARG(0), len = ARG(1), defines = ARG(2);
    uint32_t buffer = 0, hr = 0;
    int answer = shader_service(src, len, defines, ARG(3), "@asm", "asm", ARG(4), &buffer, &hr);
    if (answer > 0) {
        if (ARG(5)) MEM32(ARG(5)) = buffer;
        if (ARG(6)) MEM32(ARG(6)) = 0;
        return D3D_OK;
    }
    if (answer < 0) {
        void_log("[d3dx] D3DXAssembleShader fails as on Windows: %s", (const char *)GPTR(((dxbuffer_t *)void_com_host(buffer))->data));
        if (ARG(6)) MEM32(ARG(6)) = buffer; else void_com_release((void_com_object *)void_com_host(buffer));
        if (ARG(5)) MEM32(ARG(5)) = 0;
        return hr;
    }
    uint64_t key = assembly_key((const char *)GPTR(src), len);
    for (unsigned i = 0; i < 16; ++i) {
        disassembly_t *d = &disassemblies[i];
        if (!d->code || d->key != key) continue;
        VLOG("[d3dx] D3DXAssembleShader: the text of a disassembly, its own bytecode");
        if (ARG(5)) MEM32(ARG(5)) = make_buffer(d->code, d->size);
        if (ARG(6)) MEM32(ARG(6)) = 0;
        return D3D_OK;
    }
    MOJOSHADER_preprocessorDefine defs[64];
    unsigned ndefs = 0;
    for (uint32_t d = defines; d && MEM32(d) && ndefs < 64; d += 8, ++ndefs) {
        defs[ndefs].identifier = (const char *)GPTR(MEM32(d));
        defs[ndefs].definition = MEM32(d + 4) ? (const char *)GPTR(MEM32(d + 4)) : "";
    }
    const MOJOSHADER_parseData *pd = MOJOSHADER_assemble(NULL, (const char *)GPTR(src), len, NULL, 0, NULL, 0,
        defs, ndefs, NULL, NULL, NULL, NULL, NULL);
    if (!pd || pd->error_count) {
        const char *err = pd && pd->error_count ? pd->errors[0].error : "assembler failure";
        /* The renderer assembles right after it disassembled: a text it
         * edited that MojoShader cannot read is that shader still (never an
         * empty buffer: Microsoft's assembler reads its own texts). */
        disassembly_t *last = &disassemblies[(disassembly_next + 15) % 16];
        if (last->code && void_monotonic_ns() - last->at < 2000000000ull) {
            void_log("[d3dx] D3DXAssembleShader: MojoShader cannot read the text (%s): the shader just disassembled", err);
            if (ARG(5)) MEM32(ARG(5)) = make_buffer(last->code, last->size);
            if (ARG(6)) MEM32(ARG(6)) = 0;
            if (pd) MOJOSHADER_freeParseData(pd);
            return D3D_OK;
        }
        void_log("[d3dx] D3DXAssembleShader failed: %s", err);
        if (ARG(6)) MEM32(ARG(6)) = make_buffer(err, (uint32_t)strlen(err) + 1);
        if (ARG(5)) MEM32(ARG(5)) = 0;
        if (pd) MOJOSHADER_freeParseData(pd);
        return D3DXERR_INVALIDDATA;
    }
    if (ARG(5)) MEM32(ARG(5)) = make_buffer(pd->output, (uint32_t)pd->output_len);
    if (ARG(6)) MEM32(ARG(6)) = 0;
    MOJOSHADER_freeParseData(pd);
    return D3D_OK;
}

/* MojoShader prints the bytecode END token; Microsoft's assembly syntax omits it. */
static size_t disassembly_text_size(const char *text)
{
    size_t length = strlen(text), end = length;
    while (end && (text[end - 1] == '\n' || text[end - 1] == '\r')) --end;
    return end >= 4 && !memcmp(text + end - 4, "\nend", 4) ? end - 3 : length;
}

/* D3DXDisassembleShader(code, colorcode, comments, ppDisassembly): Microsoft's
 * text through the shader cache, since games edit and reassemble it (request
 * "@disasm": the bytecode as source, the colour flag as flags, the comment
 * string as the one macro). MojoShader's disassembler only as a fallback. */
WINAPI_EXPORT(D3DX, D3DXDisassembleShader, 4)
{
    uint32_t code = ARG(0), out = ARG(3);
    uint32_t size = d3d_shader_bytecode_size(code);
    if (size) {
        /* The comment travels as a one-entry D3DXMACRO list. */
        uint32_t macro = 0;
        if (ARG(2)) {
            macro = void_galloc(16);
            MEM32(macro) = void_gstrdup("comments");
            MEM32(macro + 4) = ARG(2);
            MEM32(macro + 8) = 0;
            MEM32(macro + 12) = 0;
        }
        uint32_t buffer = 0, hr = 0;
        int answer = shader_service(code, size, macro, 0, "@disasm", "disasm", ARG(1), &buffer, &hr);
        if (macro) { void_gfree(MEM32(macro)); void_gfree(macro); }
        if (answer > 0) {
            dxbuffer_t *b = (dxbuffer_t *)void_com_host(buffer);
            remember_disassembly((const char *)GPTR(b->data), b->size, code, size);
            MEM32(out) = buffer;
            return D3D_OK;
        }
        if (answer < 0) { void_com_release((void_com_object *)void_com_host(buffer)); MEM32(out) = 0; return hr; }
    }
    const MOJOSHADER_parseData *pd = size ? MOJOSHADER_parse(MOJOSHADER_PROFILE_D3D, "main", (const unsigned char *)GPTR(code),
        size, NULL, 0, NULL, 0, NULL, NULL, NULL) : NULL;
    const char *text = pd && !pd->error_count ? pd->output : "// disassembly unavailable\n";
    size_t length = disassembly_text_size(text);
    MEM32(out) = make_buffer(text, (uint32_t)length + 1);
    ((char *)GPTR(((dxbuffer_t *)void_com_host(MEM32(out)))->data))[length] = 0;
    if (size && pd && !pd->error_count) remember_disassembly(text, length, code, size);
    if (pd) MOJOSHADER_freeParseData(pd);
    return D3D_OK;
}

/* ================================================================ textures */
typedef struct {
    uint32_t width, height, depth, mips, format, rtype;   /* rtype: 3 texture, 5 cube, 4 volume */
    uint32_t data_offset;
} dds_info;

static uint32_t dds_format(const uint8_t *pf)
{
    uint32_t flags = *(const uint32_t *)(pf + 4), fourcc = *(const uint32_t *)(pf + 8);
    uint32_t bits = *(const uint32_t *)(pf + 12), r = *(const uint32_t *)(pf + 16), g = *(const uint32_t *)(pf + 20);
    uint32_t b = *(const uint32_t *)(pf + 24), a = *(const uint32_t *)(pf + 28);
    if (flags & 0x4) return fourcc;                              /* DDPF_FOURCC (also numeric D3DFMTs) */
    if (flags & 0x40) {                                          /* DDPF_RGB */
        if (bits == 32) {
            if (r == 0xFF0000 && g == 0xFF00 && b == 0xFF) return (flags & 1) && a ? 21 : 22;
            if (r == 0xFF && g == 0xFF00 && b == 0xFF0000) return (flags & 1) && a ? 32 : 33;
            if (r == 0x3FF00000 && g == 0xFFC00 && b == 0x3FF) return 35;
            if (r == 0x3FF && g == 0xFFC00 && b == 0x3FF00000) return 31;
            if (r == 0xFFFF && g == 0xFFFF0000) return 34;
        }
        if (bits == 24) return 20;
        if (bits == 16) {
            if (r == 0xF800 && g == 0x7E0 && b == 0x1F) return 23;
            if (r == 0x7C00 && g == 0x3E0 && b == 0x1F) return (flags & 1) && a ? 25 : 24;
            if (r == 0xF00 && g == 0xF0 && b == 0xF) return 26;
        }
    }
    if (flags & 0x20000) {                                       /* DDPF_LUMINANCE */
        if (bits == 8) return 50;
        if (bits == 16) return (flags & 1) ? 51 : 81;
    }
    if ((flags & 0x2) && bits == 8) return 28;                   /* DDPF_ALPHA */
    if ((flags & 0x80000) && bits == 16) return 60;              /* DDPF_BUMPDUDV */
    return 0;
}

static int parse_dds(const uint8_t *data, uint32_t size, dds_info *info)
{
    if (size < 128 || memcmp(data, "DDS ", 4)) return 0;
    const uint8_t *h = data + 4;
    info->height = *(const uint32_t *)(h + 8);
    info->width = *(const uint32_t *)(h + 12);
    info->depth = *(const uint32_t *)(h + 20);
    info->mips = *(const uint32_t *)(h + 24);
    if (!info->mips) info->mips = 1;
    info->format = dds_format(h + 72);
    uint32_t caps2 = *(const uint32_t *)(h + 108);
    info->rtype = (caps2 & 0x200) ? 5 : (caps2 & 0x200000) ? 4 : 3;
    if (info->rtype != 4) info->depth = 1;
    info->data_offset = 128;
    return info->format != 0 && d3d_format_find(info->format) != NULL;
}

static uint32_t level_bytes(const d3d_format *f, uint32_t w, uint32_t h)
{
    return d3d_format_pitch(f, w) * d3d_format_rows(f, h);
}

#define D3DX_DEFAULT_ 0xFFFFFFFFu
#define D3DX_DEFAULT_NONPOW2_ 0xFFFFFFFEu
#define D3DX_FROM_FILE_ 0xFFFFFFFDu

static void fill_image_info(uint32_t out, const dds_info *info)
{
    if (!out) return;
    MEM32(out) = info->width; MEM32(out + 4) = info->height; MEM32(out + 8) = info->depth;
    MEM32(out + 12) = info->mips; MEM32(out + 16) = info->format;
    MEM32(out + 20) = info->rtype; MEM32(out + 24) = 4;           /* D3DXIFF_DDS */
}

/* Shared body of the texture loaders. `cube` selects cube textures. */
static uint32_t load_texture(uint32_t device, const uint8_t *data, uint32_t size, uint32_t width, uint32_t height,
    uint32_t mips, uint32_t usage, uint32_t format, uint32_t pool, uint32_t filter, uint32_t mipfilter,
    uint32_t srcinfo, uint32_t out, int cube)
{
    (void)device; (void)mipfilter;
    dds_info info;
    if (!parse_dds(data, size, &info)) {
        void_log("[d3dx] texture data is not a supported DDS (%u bytes, magic %.4s)", size, (const char *)data);
        return D3DXERR_INVALIDDATA;
    }
    fill_image_info(srcinfo, &info);
    if ((info.rtype == 5) != (cube != 0)) {
        void_log("[d3dx] DDS resource type %u does not match the %s loader", info.rtype, cube ? "cube" : "2D");
        return D3DXERR_INVALIDDATA;
    }
    const d3d_format *ff = d3d_format_find(info.format);
    /* D3DX_SKIP_DDS_MIP_LEVELS(n, filter): drop the n largest file levels. */
    uint32_t skip = (filter != D3DX_DEFAULT_ && (filter >> 26) & 0x1F) ? (filter >> 26) & 0x1F : 0;
    if (skip >= info.mips) skip = info.mips - 1;
    uint32_t w = info.width >> skip, h = info.height >> skip;
    if (!w) w = 1;
    if (!h) h = 1;
    uint32_t file_levels = info.mips - skip;
    uint32_t want_w = (width == D3DX_DEFAULT_ || width == D3DX_DEFAULT_NONPOW2_ || width == D3DX_FROM_FILE_ || !width) ? w : width;
    uint32_t want_h = (height == D3DX_DEFAULT_ || height == D3DX_DEFAULT_NONPOW2_ || height == D3DX_FROM_FILE_ || !height) ? h : height;
    if (cube) want_h = want_w;
    if (want_w != w || want_h != h) {
        /* A power-of-two reduction (TextureQuality below full) starts from the
         * file's own smaller mip level, as a box-filtered resize would. */
        uint32_t k = 1;
        while (k < file_levels && ((w >> k) > want_w || (h >> k) > want_h)) ++k;
        uint32_t kw = w >> k ? w >> k : 1, kh = h >> k ? h >> k : 1;
        if (k < file_levels && kw == want_w && kh == want_h) {
            skip += k;
            w = kw;
            h = kh;
            file_levels -= k;
        } else {
            void_log("[d3dx] resize %ux%u -> %ux%u not supported: using file size", w, h, want_w, want_h);
        }
    }
    uint32_t levels = (mips == D3DX_FROM_FILE_) ? file_levels : (mips == D3DX_DEFAULT_ || mips == 0) ? 0 : mips;
    uint32_t fmt = (format == 0 || format == D3DX_DEFAULT_ || format == D3DX_FROM_FILE_) ? info.format : format;
    if (fmt != info.format) {
        VLOG("[d3dx] texture format %u requested for a %u file: kept file format", fmt, info.format);
        fmt = info.format;
    }
    d3d_texture *t = d3d_texture_new(g_d3d_device, cube ? D3DRTYPE_CUBETEXTURE : D3DRTYPE_TEXTURE, w, h, 1, levels, usage, fmt, pool);
    if (!t) return D3DERR_INVALIDCALL;
    t->hud_tag = void_hud_tag_for(data, size, &t->hud_slot);   /* the touch layer follows the cursor and helpers */
    uint32_t offset = info.data_offset;
    int faces = cube ? 6 : 1;
    for (int face = 0; face < faces; ++face) {
        for (uint32_t l = 0; l < info.mips; ++l) {
            uint32_t lw = info.width >> l, lh = info.height >> l;
            if (!lw) lw = 1;
            if (!lh) lh = 1;
            uint32_t bytes = level_bytes(ff, lw, lh);
            if (offset + bytes > size) { void_log("[d3dx] truncated DDS"); goto done; }
            if (l >= skip && l - skip < t->levels) {
                uint32_t tl = l - skip;
                d3d_texture_upload_level(t, (uint32_t)face, tl, data + offset, d3d_format_pitch(ff, lw));
                if (t->sysmem) {
                    uint32_t index = (uint32_t)face * t->levels + tl;
                    t->sysmem[index] = void_galloc(bytes);
                    memcpy(GPTR(t->sysmem[index]), data + offset, bytes);
                }
            }
            offset += bytes;
        }
    }
done:
    if (t->levels > file_levels) d3d_generate_mips(t);
    MEM32(out) = d3d_wrap_texture(t);
    VLOG("[d3dx] texture %ux%u levels %u/%u format %.4s pool %u = %08X", w, h, t->levels, file_levels,
        info.format > 0xFFFF ? (const char *)&info.format : "num", pool, MEM32(out));
    return D3D_OK;
}

/* D3DXCreateTextureFromFileInMemoryEx(device, data, size, w, h, mips, usage,
 *   format, pool, filter, mipfilter, colorkey, srcinfo, palette, texture) */
WINAPI_EXPORT(D3DX, D3DXCreateTextureFromFileInMemoryEx, 15)
{
    return load_texture(ARG(0), (const uint8_t *)GPTR(ARG(1)), ARG(2), ARG(3), ARG(4), ARG(5), ARG(6), ARG(7), ARG(8),
        ARG(9), ARG(10), ARG(12), ARG(14), 0);
}

/* D3DXCreateCubeTextureFromFileInMemoryEx(device, data, size, edge, mips,
 *   usage, format, pool, filter, mipfilter, colorkey, srcinfo, palette, cube) */
WINAPI_EXPORT(D3DX, D3DXCreateCubeTextureFromFileInMemoryEx, 14)
{
    return load_texture(ARG(0), (const uint8_t *)GPTR(ARG(1)), ARG(2), ARG(3), ARG(3), ARG(4), ARG(5), ARG(6), ARG(7),
        ARG(8), ARG(9), ARG(11), ARG(13), 1);
}

WINAPI_EXPORT(D3DX, D3DXGetImageInfoFromFileInMemory, 3)
{
    dds_info info;
    if (!parse_dds((const uint8_t *)GPTR(ARG(0)), ARG(1), &info)) {
        void_log("[d3dx] D3DXGetImageInfoFromFileInMemory: unsupported image (%u bytes)", ARG(1));
        return D3DXERR_INVALIDDATA;
    }
    fill_image_info(ARG(2), &info);
    return D3D_OK;
}

static uint8_t *read_guest_path(uint32_t name_va, int wide, uint32_t *size)
{
    char *name = wide ? void_wstr_utf8(name_va) : void_astr_utf8(name_va);
    char *host = name ? void_path_to_host(name) : NULL;
    size_t n = 0;
    uint8_t *data = host ? (uint8_t *)read_all(host, &n) : NULL;
    if (!data) void_log("[d3dx] cannot read %s", name ? name : "(null)");
    free(name);
    free(host);
    *size = (uint32_t)n;
    return data;
}

WINAPI_EXPORT(D3DX, D3DXGetImageInfoFromFileW, 2)
{
    uint32_t size;
    uint8_t *data = read_guest_path(ARG(0), 1, &size);
    if (!data) return D3DERR_NOTFOUND;
    dds_info info;
    int ok = parse_dds(data, size, &info);
    free(data);
    if (!ok) return D3DXERR_INVALIDDATA;
    fill_image_info(ARG(1), &info);
    return D3D_OK;
}

/* D3DXCreateTextureFromFileExW(device, file, w, h, mips, usage, format, pool,
 *   filter, mipfilter, colorkey, srcinfo, palette, texture) */
WINAPI_EXPORT(D3DX, D3DXCreateTextureFromFileExW, 14)
{
    uint32_t size;
    uint8_t *data = read_guest_path(ARG(1), 1, &size);
    if (!data) return D3DERR_NOTFOUND;
    uint32_t hr = load_texture(ARG(0), data, size, ARG(2), ARG(3), ARG(4), ARG(5), ARG(6), ARG(7), ARG(8), ARG(9), ARG(11), ARG(13), 0);
    free(data);
    return hr;
}

/* D3DXCreateCubeTextureFromFileExW(device, file, edge, mips, usage, format,
 *   pool, filter, mipfilter, colorkey, srcinfo, palette, cube) */
WINAPI_EXPORT(D3DX, D3DXCreateCubeTextureFromFileExW, 13)
{
    uint32_t size;
    uint8_t *data = read_guest_path(ARG(1), 1, &size);
    if (!data) return D3DERR_NOTFOUND;
    uint32_t hr = load_texture(ARG(0), data, size, ARG(2), ARG(2), ARG(3), ARG(4), ARG(5), ARG(6), ARG(7), ARG(8), ARG(10), ARG(12), 1);
    free(data);
    return hr;
}

WINAPI_EXPORT(D3DX, D3DXFilterTexture, 4)
{
    d3d_texture *t = (d3d_texture *)void_com_host(ARG(0));
    d3d_generate_mips(t);
    return D3D_OK;
}

static uint32_t check_requirements(uint32_t w, uint32_t h, uint32_t levels, uint32_t format, int cube)
{
    if (w && MEM32(w) == 0) MEM32(w) = 256;
    if (h && !cube && MEM32(h) == 0) MEM32(h) = 256;
    if (levels && (MEM32(levels) == 0 || MEM32(levels) == D3DX_DEFAULT_)) {
        uint32_t m = w ? MEM32(w) : 1, n = 1;
        if (h && !cube && MEM32(h) > m) m = MEM32(h);
        while (m > 1) { m >>= 1; ++n; }
        MEM32(levels) = n;
    }
    if (format && !d3d_format_find(MEM32(format))) MEM32(format) = 21;
    return D3D_OK;
}

/* D3DXCheckTextureRequirements(device, w*, h*, levels*, usage, format*, pool) */
WINAPI_EXPORT(D3DX, D3DXCheckTextureRequirements, 7) { return check_requirements(ARG(1), ARG(2), ARG(3), ARG(5), 0); }
/* D3DXCheckCubeTextureRequirements(device, size*, levels*, usage, format*, pool) */
WINAPI_EXPORT(D3DX, D3DXCheckCubeTextureRequirements, 6) { return check_requirements(ARG(1), 0, ARG(2), ARG(4), 1); }

/* D3DXLoadSurfaceFromSurface(dst, dstpal, dstrect, src, srcpal, srcrect, filter, colorkey) */
WINAPI_EXPORT(D3DX, D3DXLoadSurfaceFromSurface, 8)
{
    d3d_surface *dst = (d3d_surface *)void_com_host(ARG(0)), *src = (d3d_surface *)void_com_host(ARG(3));
    uint32_t dr[4] = {0, 0, dst->width, dst->height}, sr[4] = {0, 0, src->width, src->height};
    if (ARG(2)) for (int i = 0; i < 4; ++i) dr[i] = MEM32(ARG(2) + 4u * (uint32_t)i);
    if (ARG(5)) for (int i = 0; i < 4; ++i) sr[i] = MEM32(ARG(5) + 4u * (uint32_t)i);
    if (!src->fmt || !dst->fmt || sr[2] <= sr[0] || sr[3] <= sr[1] || dr[2] <= dr[0] || dr[3] <= dr[1] ||
        sr[2] > src->width || sr[3] > src->height || dr[2] > dst->width || dr[3] > dst->height)
        return D3DERR_INVALIDCALL;
    /* GPU to GPU between render-target formats: a framebuffer blit. */
    if (!src->sysmem && !dst->sysmem && !(src->container && src->container->sysmem) && !(dst->container && dst->container->sysmem) &&
        src->fmt->render_target && dst->fmt->render_target && src->format == dst->format) {
        d3d_gl_blit(src, sr, dst, dr, (ARG(6) & 0xFF) >= 3 ? 2 : 1);
        return D3D_OK;
    }
    /* Otherwise through logical RGBA: decode or read back, resample, encode. */
    uint32_t sw = sr[2] - sr[0], sh = sr[3] - sr[1], dw = dr[2] - dr[0], dh = dr[3] - dr[1];
    float *px = (float *)malloc((size_t)sw * sh * 16);
    if (!d3d_surface_read_rgba(src, sr, px)) {
        void_log("[d3dx] D3DXLoadSurfaceFromSurface: format %u source cannot be read", src->format);
        free(px);
        return D3DERR_INVALIDCALL;
    }
    if (sw != dw || sh != dh) {
        float *scaled = (float *)malloc((size_t)dw * dh * 16);
        d3d_rgba_resample(px, sw, sh, scaled, dw, dh);
        free(px);
        px = scaled;
    }
    int ok = d3d_surface_write_rgba(dst, dr, px);
    free(px);
    if (!ok) {
        void_log("[d3dx] D3DXLoadSurfaceFromSurface: format %u destination unsupported", dst->format);
        return D3DERR_INVALIDCALL;
    }
    return D3D_OK;
}

/* ================================================================== fonts */
typedef struct { void_com_object com; uint32_t height; } font_t;
#define FONT ((font_t *)void_com_host(THIS_))
COM_METHOD(font, QueryInterface, 3) { void_com_addref(&FONT->com); MEM32(ARG(2)) = THIS_; return 0; }
COM_METHOD(font, AddRef, 1) { return void_com_addref(&FONT->com); }
COM_METHOD(font, Release, 1) { return void_com_release(&FONT->com); }
COM_METHOD(font, GetDevice, 2) { void_com_addref(&g_d3d_device->com); MEM32(ARG(1)) = g_d3d_device->com.guest; return D3D_OK; }
COM_METHOD(font, GetDescA, 2) { memset(GPTR(ARG(1)), 0, 56); MEM32(ARG(1)) = FONT->height; return D3D_OK; }
COM_METHOD(font, GetDescW, 2) { memset(GPTR(ARG(1)), 0, 92); MEM32(ARG(1)) = FONT->height; return D3D_OK; }
COM_METHOD(font, GetTextMetricsA, 2) { memset(GPTR(ARG(1)), 0, 53); MEM32(ARG(1)) = FONT->height; return 1; }
COM_METHOD(font, GetTextMetricsW, 2) { memset(GPTR(ARG(1)), 0, 57); MEM32(ARG(1)) = FONT->height; return 1; }
COM_METHOD(font, GetDC, 1) { return 0x00040002u; }
COM_METHOD(font, GetGlyphData, 5) { return D3DERR_INVALIDCALL; }
COM_METHOD(font, PreloadCharacters, 3) { return D3D_OK; }
COM_METHOD(font, PreloadGlyphs, 3) { return D3D_OK; }
COM_METHOD(font, PreloadTextA, 3) { return D3D_OK; }
COM_METHOD(font, PreloadTextW, 3) { return D3D_OK; }
/* DrawText(sprite, text, count, rect, format, color): debug overlays only. */
COM_METHOD(font, DrawTextA, 7) { return FONT->height; }
COM_METHOD(font, DrawTextW, 7) { return FONT->height; }
COM_METHOD(font, OnLostDevice, 1) { return D3D_OK; }
COM_METHOD(font, OnResetDevice, 1) { return D3D_OK; }
static const void_fn font_methods[] = {
    font_QueryInterface, font_AddRef, font_Release, font_GetDevice, font_GetDescA, font_GetDescW, font_GetTextMetricsA,
    font_GetTextMetricsW, font_GetDC, font_GetGlyphData, font_PreloadCharacters, font_PreloadGlyphs, font_PreloadTextA,
    font_PreloadTextW, font_DrawTextA, font_DrawTextW, font_OnLostDevice, font_OnResetDevice,
};
static void_com_class font_class = { "ID3DXFont", 18, font_methods, 0 };

WINAPI_EXPORT(D3DX, D3DXCreateFontA, 12)
{
    font_t *f = (font_t *)calloc(1, sizeof *f);
    f->height = ARG(1) ? ARG(1) : 16;
    char *face = void_astr_utf8(ARG(10));
    void_log("[d3dx] D3DXCreateFontA(%u, %s): text drawing is not rendered", ARG(1), face ? face : "");
    free(face);
    MEM32(ARG(11)) = void_com_wrap(&f->com, &font_class, 0);
    return D3D_OK;
}

/* ================================================================== lines */
typedef struct { void_com_object com; float width; } line_t;
#define LINE ((line_t *)void_com_host(THIS_))
COM_METHOD(line, QueryInterface, 3) { void_com_addref(&LINE->com); MEM32(ARG(2)) = THIS_; return 0; }
COM_METHOD(line, AddRef, 1) { return void_com_addref(&LINE->com); }
COM_METHOD(line, Release, 1) { return void_com_release(&LINE->com); }
COM_METHOD(line, GetDevice, 2) { void_com_addref(&g_d3d_device->com); MEM32(ARG(1)) = g_d3d_device->com.guest; return D3D_OK; }
COM_METHOD(line, Begin, 1) { return D3D_OK; }
COM_METHOD(line, Draw, 4) { return D3D_OK; }
COM_METHOD(line, DrawTransform, 5) { return D3D_OK; }
COM_METHOD(line, SetPattern, 2) { return D3D_OK; }
COM_METHOD(line, GetPattern, 1) { return 0xFFFFFFFFu; }
COM_METHOD(line, SetPatternScale, 2) { return D3D_OK; }
static void line_GetPatternScale(void) { fp_push_impl(g_st, &g_fp_top, 1.0); g_esp += 8; }
COM_METHOD(line, SetWidth, 2) { uint32_t u = ARG(1); memcpy(&LINE->width, &u, 4); return D3D_OK; }
static void line_GetWidth(void) { line_t *l = (line_t *)void_com_host(ARG(0)); fp_push_impl(g_st, &g_fp_top, l->width); g_esp += 8; }
COM_METHOD(line, SetAntialias, 2) { return D3D_OK; }
COM_METHOD(line, GetAntialias, 1) { return 0; }
COM_METHOD(line, SetGLLines, 2) { return D3D_OK; }
COM_METHOD(line, GetGLLines, 1) { return 0; }
COM_METHOD(line, End, 1) { return D3D_OK; }
COM_METHOD(line, OnLostDevice, 1) { return D3D_OK; }
COM_METHOD(line, OnResetDevice, 1) { return D3D_OK; }
static const void_fn line_methods[] = {
    line_QueryInterface, line_AddRef, line_Release, line_GetDevice, line_Begin, line_Draw, line_DrawTransform,
    line_SetPattern, line_GetPattern, line_SetPatternScale, line_GetPatternScale, line_SetWidth, line_GetWidth,
    line_SetAntialias, line_GetAntialias, line_SetGLLines, line_GetGLLines, line_End, line_OnLostDevice, line_OnResetDevice,
};
static void_com_class line_class = { "ID3DXLine", 20, line_methods, 0 };

WINAPI_EXPORT(D3DX, D3DXCreateLine, 2)
{
    line_t *l = (line_t *)calloc(1, sizeof *l);
    l->width = 1.0f;
    MEM32(ARG(1)) = void_com_wrap(&l->com, &line_class, 0);
    return D3D_OK;
}

/* ============================================================ math helpers */
WINAPI_EXPORT(D3DX, D3DXMatrixTranslation, 4)
{
    float *m = (float *)GPTR(ARG(0));
    memset(m, 0, 64);
    m[0] = m[5] = m[10] = m[15] = 1.0f;
    memcpy(&m[12], &g_esp, 0);
    uint32_t x = ARG(1), y = ARG(2), z = ARG(3);
    memcpy(&m[12], &x, 4); memcpy(&m[13], &y, 4); memcpy(&m[14], &z, 4);
    return ARG(0);
}

/* ============================================================ image files */
/* D3DXSaveTextureToFile / D3DXSaveSurfaceToFile: the game's screenshots
 * (F12: Documents\My Games\...\Screenshots\scrNNNN.png, as PNG) and its
 * texture dumps (DDS). The picture is read back here; pictures.c encodes
 * and writes it on a thread of its own. */

/* Rect (or the whole) of a surface into the file at a guest Windows path. */
static uint32_t save_surface(char *windows_path, uint32_t file_format, d3d_surface *s, uint32_t rect_va)
{
    uint32_t r[4] = { 0, 0, s ? s->width : 0, s ? s->height : 0 };
    if (rect_va) for (int i = 0; i < 4; ++i) r[i] = MEM32(rect_va + 4u * (uint32_t)i);
    char *host = windows_path ? void_path_to_host(windows_path) : NULL;
    free(windows_path);
    if (!host || !s || !s->fmt || file_format > VOID_IFF_PFM || r[2] <= r[0] || r[3] <= r[1] ||
        r[2] > s->width || r[3] > s->height) {
        free(host);
        return D3DERR_INVALIDCALL;
    }
    uint32_t w = r[2] - r[0], h = r[3] - r[1];
    float *rgba = (float *)malloc((size_t)w * h * 16);
    if (!d3d_surface_read_rgba(s, r, rgba)) {
        void_log("[d3dx] picture: format %u cannot be read", s->format);
        free(rgba), free(host);
        return D3DERR_INVALIDCALL;
    }
    return void_picture_write(host, file_format, w, h, s->format, rgba) ? D3D_OK : D3DERR_INVALIDCALL;
}

static uint32_t save_texture(char *windows_path, uint32_t file_format, uint32_t texture)
{
    d3d_texture *t = texture ? (d3d_texture *)void_com_host(texture) : NULL;
    if (!t || t->rtype == D3DRTYPE_VOLUMETEXTURE || !d3d_texture_surface(t, 0, 0)) {
        free(windows_path);
        return D3DERR_INVALIDCALL;
    }
    return save_surface(windows_path, file_format, t->surfaces[0], 0);
}

/* D3DXSaveTextureToFile(path, format, texture, palette) */
WINAPI_EXPORT(D3DX, D3DXSaveTextureToFileW, 4) { return save_texture(void_wstr_utf8(ARG(0)), ARG(1), ARG(2)); }
WINAPI_EXPORT(D3DX, D3DXSaveTextureToFileA, 4) { return save_texture(void_astr_utf8(ARG(0)), ARG(1), ARG(2)); }
/* D3DXSaveSurfaceToFileW(path, format, surface, palette, rect) */
WINAPI_EXPORT(D3DX, D3DXSaveSurfaceToFileW, 5)
{
    return save_surface(void_wstr_utf8(ARG(0)), ARG(1), ARG(2) ? (d3d_surface *)void_com_host(ARG(2)) : NULL, ARG(4));
}

/* ======================================================= unsupported tools */
#define D3DX_UNSUPPORTED(name, nargs) \
    WINAPI_EXPORT(D3DX, name, nargs) { void_log("[d3dx] " #name " is not available (caller %08X)", g_cur_func); return E_NOTIMPL_; }

D3DX_UNSUPPORTED(D3DXSaveTextureToFileInMemory, 4)
D3DX_UNSUPPORTED(D3DXComputeNormalMap, 6)
D3DX_UNSUPPORTED(D3DXCreateBox, 6)
D3DX_UNSUPPORTED(D3DXCreateCylinder, 8)
D3DX_UNSUPPORTED(D3DXCreateSphere, 6)
D3DX_UNSUPPORTED(D3DXCreateMeshFVF, 6)
D3DX_UNSUPPORTED(D3DXConcatenateMeshes, 8)
D3DX_UNSUPPORTED(D3DXIntersect, 11)
D3DX_UNSUPPORTED(D3DXOptimizeFaces, 5)
D3DX_UNSUPPORTED(D3DXOptimizeVertices, 5)
D3DX_UNSUPPORTED(D3DXUVAtlasPartition, 18)
D3DX_UNSUPPORTED(D3DXComputeIMTFromPerTexelSignal, 12)
D3DX_UNSUPPORTED(D3DXValidMesh, 3)
