#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "mojoshader.h"

typedef struct Buffer Buffer;
typedef struct {
    HRESULT (__stdcall *QueryInterface)(Buffer *, const void *, void **);
    ULONG (__stdcall *AddRef)(Buffer *);
    ULONG (__stdcall *Release)(Buffer *);
    void *(__stdcall *GetBufferPointer)(Buffer *);
    DWORD (__stdcall *GetBufferSize)(Buffer *);
} BufferVtbl;
struct Buffer { const BufferVtbl *v; };
typedef HRESULT (__stdcall *assemble_t)(const char *, UINT, const void *, void *, DWORD, Buffer **, Buffer **);

static size_t instructions(const void *bytes, size_t size, uint32_t *result)
{
    const uint32_t *code = bytes;
    size_t n = 0;
    assert(size >= 8 && size % 4 == 0);
    result[n++] = code[0];
    for (size_t i = 1; i < size / 4;) {
        uint32_t opcode = code[i] & 0xffff;
        if (opcode == 0xfffe) { i += 1 + ((code[i] >> 16) & 0x7fff); continue; }
        size_t count = 1 + ((code[i] >> 24) & 0xf);
        assert(i + count <= size / 4 && n + count < 512);
        memcpy(result + n, code + i, count * sizeof(uint32_t));
        n += count;
        i += count;
        if (opcode == 0xffff) { assert(i == size / 4); return n; }
    }
    assert(!"shader missing END token");
    return 0;
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    int fixed = !strcmp(argv[1], "fixed"), losses = 0;
    HMODULE dll = LoadLibraryA("d3dx9_36.dll");
    assemble_t assemble = dll ? (assemble_t)GetProcAddress(dll, "D3DXAssembleShader") : NULL;
    assert(assemble);
    const char *cases[] = {
        "ps_3_0\n"
        "dcl_texcoord_pp v0.xyz\ndcl_texcoord1_pp v1.xyz\ndcl_cube s0\n"
        "mov r0.xyz, v0.xyz\nadd r0.xyz, r0.xyz, v1.xyz\ntexld r0, r0, s0\nmov oC0, r0\n",
        "ps_3_0\n"
        "dcl_normal v0.xyz\ndcl_tangent2 v1.xyz\n"
        "mov r0.xyz, v0.xyz\nadd oC0.xyz, r0.xyz, v1.xyz\nmov oC0.w, v1.x\n",
        "vs_3_0\n"
        "dcl_position v0\ndcl_texcoord4 v1\ndcl_position o0\ndcl_texcoord2 o1\n"
        "mov o0, v0\nmov o1, v1\n",
        "ps_2_0\n"
        "dcl_pp t0.xy\ndcl_2d s0\ntexld r0, t0, s0\nmov oC0, r0\n"
    };
    for (size_t i = 0; i < sizeof cases / sizeof *cases; ++i) {
        const char *source = cases[i];
        Buffer *oracle = NULL, *errors = NULL;
        HRESULT hr = assemble(source, (UINT)strlen(source), NULL, NULL, 0, &oracle, &errors);
        if (FAILED(hr)) fprintf(stderr, "Microsoft: %s\n", errors ? (char *)errors->v->GetBufferPointer(errors) : "no diagnostic");
        assert(SUCCEEDED(hr) && oracle);
        const MOJOSHADER_parseData *mojo = MOJOSHADER_assemble(NULL, source, (unsigned int)strlen(source),
            NULL, 0, NULL, 0, NULL, 0, NULL, NULL, NULL, NULL, NULL);
        if (mojo && mojo->error_count) fprintf(stderr, "Mojo: %s\n", mojo->errors[0].error);
        assert(mojo && !mojo->error_count);
        uint32_t expected[512], actual[512];
        size_t expected_count = instructions(oracle->v->GetBufferPointer(oracle), oracle->v->GetBufferSize(oracle), expected);
        size_t actual_count = instructions(mojo->output, mojo->output_len, actual);
        int same = expected_count == actual_count && !memcmp(expected, actual, expected_count * sizeof(uint32_t));
        int ps3 = !strncmp(source, "ps_3_0", 6);
        assert(same == (fixed || !ps3));
        if (!same) ++losses;
        if (fixed) {
            const MOJOSHADER_parseData *glsl = MOJOSHADER_parse(MOJOSHADER_PROFILE_GLSLES3, "main",
                (const unsigned char *)mojo->output, mojo->output_len, NULL, 0, NULL, 0, NULL, NULL, NULL);
            assert(glsl && !glsl->error_count);
            for (int a = 0; a < glsl->attribute_count; ++a)
                for (int b = a + 1; b < glsl->attribute_count; ++b)
                    assert(glsl->attributes[a].usage != glsl->attributes[b].usage ||
                           glsl->attributes[a].index != glsl->attributes[b].index);
            if (i == 0) assert(strstr(glsl->output, "io_5_0") && strstr(glsl->output, "io_5_1"));
            MOJOSHADER_freeParseData(glsl);
        }
        MOJOSHADER_freeParseData(mojo);
        oracle->v->Release(oracle); if (errors) errors->v->Release(errors);
    }
    assert(losses == (fixed ? 0 : 2));
    printf("PASS: %s assembler, 4 Microsoft instruction/semantic oracles, %d expected semantic losses\n", fixed ? "fixed" : "original", losses);
    return 0;
}
