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
typedef HRESULT (__stdcall *disassemble_t)(const DWORD *, BOOL, const char *, Buffer **);

#include "disassembly-size.h"

static char *instructions(const char *text)
{
    char *result = calloc(strlen(text) + 1, 1), *out = result;
    assert(result);
    while (*text) {
        while (*text == ' ' || *text == '\t' || *text == '\r' || *text == '\n') ++text;
        const char *end = strchr(text, '\n');
        if (!end) end = text + strlen(text);
        if (text[0] != '/' || text[1] != '/') {
            const char *last = end;
            while (last > text && (last[-1] == ' ' || last[-1] == '\t' || last[-1] == '\r')) --last;
            memcpy(out, text, (size_t)(last - text));
            out += last - text;
            if (last > text) *out++ = '\n';
        }
        text = *end ? end + 1 : end;
    }
    return result;
}

int main(int argc, char **argv)
{
    assert(argc > 1);
    HMODULE dll = LoadLibraryA("d3dx9_36.dll");
    assemble_t assemble = dll ? (assemble_t)GetProcAddress(dll, "D3DXAssembleShader") : NULL;
    disassemble_t disassemble = dll ? (disassemble_t)GetProcAddress(dll, "D3DXDisassembleShader") : NULL;
    assert(assemble && disassemble);
    assert(disassembly_text_size("vs_1_1\nmov oPos, v0\nend\n") == strlen("vs_1_1\nmov oPos, v0\n"));
    assert(disassembly_text_size("vs_1_1\r\nmov oPos, v0\r\nend\r\n") == strlen("vs_1_1\r\nmov oPos, v0\r\n"));
    assert(disassembly_text_size("vs_3_0\nendloop\n") == strlen("vs_3_0\nendloop\n"));
    assert(disassembly_text_size("// the end\n") == strlen("// the end\n"));
    assert(disassembly_text_size("") == 0);
    for (int i = 1; i < argc; ++i) {
        FILE *file = fopen(argv[i], "rb");
        assert(file && !fseek(file, 0, SEEK_END));
        long length = ftell(file);
        assert(length > 4 && !fseek(file, 0, SEEK_SET));
        unsigned char *bytecode = malloc((size_t)length);
        assert(bytecode && fread(bytecode, 1, (size_t)length, file) == (size_t)length);
        fclose(file);
        const MOJOSHADER_parseData *mojo = MOJOSHADER_parse(MOJOSHADER_PROFILE_D3D, "main", bytecode,
            (unsigned int)length, NULL, 0, NULL, 0, NULL, NULL, NULL);
        assert(mojo && !mojo->error_count);
        Buffer *bad = NULL, *errors = NULL, *assembled = NULL, *original_text = NULL, *roundtrip_text = NULL;
        HRESULT hr = assemble(mojo->output, mojo->output_len, NULL, NULL, 0, &bad, &errors);
        assert(FAILED(hr) && !bad && errors);
        assert(strstr(errors->v->GetBufferPointer(errors), "end"));
        errors->v->Release(errors); errors = NULL;
        size_t valid_length = disassembly_text_size(mojo->output);
        hr = assemble(mojo->output, (UINT)valid_length, NULL, NULL, 0, &assembled, &errors);
        if (FAILED(hr)) fprintf(stderr, "assembly failed: %s\n%s\n", argv[i],
            errors ? (char *)errors->v->GetBufferPointer(errors) : "no diagnostic");
        assert(SUCCEEDED(hr) && assembled);
        assert(SUCCEEDED(disassemble((DWORD *)bytecode, FALSE, NULL, &original_text)));
        assert(SUCCEEDED(disassemble(assembled->v->GetBufferPointer(assembled), FALSE, NULL, &roundtrip_text)));
        char *a = instructions(original_text->v->GetBufferPointer(original_text));
        char *b = instructions(roundtrip_text->v->GetBufferPointer(roundtrip_text));
        if (strcmp(a, b)) fprintf(stderr, "instruction mismatch: %s\nORIGINAL:\n%s\nROUNDTRIP:\n%s\n", argv[i], a, b);
        assert(!strcmp(a, b));
        free(a); free(b); free(bytecode);
        original_text->v->Release(original_text); roundtrip_text->v->Release(roundtrip_text);
        assembled->v->Release(assembled); if (errors) errors->v->Release(errors);
        MOJOSHADER_freeParseData(mojo);
    }
    printf("PASS: %d real shader variants; original Mojo END rejected; normalized Windows assembly preserves all instructions\n", argc - 1);
    return 0;
}
