/* Compile recorded D3DXCompileShader requests with the same d3dx9_36.dll the
 * Windows game uses (SysWOW64, loaded dynamically; x86 build only).
 *   shader_compile_requests.exe REQUEST_DIR OUTPUT_DIR
 * For every <hash>.req writes <hash>.bin (bytecode) or <hash>.err (messages). */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { const char *Name, *Definition; } MACRO;
typedef struct ID3DXBuffer ID3DXBuffer;
typedef struct {
    HRESULT (__stdcall *QueryInterface)(ID3DXBuffer *, const void *, void **);
    ULONG (__stdcall *AddRef)(ID3DXBuffer *);
    ULONG (__stdcall *Release)(ID3DXBuffer *);
    void *(__stdcall *GetBufferPointer)(ID3DXBuffer *);
    DWORD (__stdcall *GetBufferSize)(ID3DXBuffer *);
} ID3DXBufferVtbl;
struct ID3DXBuffer { const ID3DXBufferVtbl *v; };
typedef HRESULT (__stdcall *compile_t)(const char *, UINT, const MACRO *, void *, const char *, const char *, DWORD,
    ID3DXBuffer **, ID3DXBuffer **, void **);
typedef HRESULT (__stdcall *assemble_t)(const char *, UINT, const MACRO *, void *, DWORD, ID3DXBuffer **, ID3DXBuffer **);
typedef HRESULT (__stdcall *disassemble_t)(const DWORD *, BOOL, const char *, ID3DXBuffer **);

static char *read_file(const char *path, size_t *size)
{
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    rewind(f);
    char *data = (char *)malloc((size_t)n + 1);
    fread(data, 1, (size_t)n, f);
    data[n] = 0;
    fclose(f);
    *size = (size_t)n;
    return data;
}

static const char *field(const char *p, const char *name, char *out, size_t cap)
{
    size_t n = strlen(name);
    if (strncmp(p, name, n) || p[n] != '=') return NULL;
    p += n + 1;
    size_t i = 0;
    while (*p && *p != '\n' && i + 1 < cap) out[i++] = *p++;
    out[i] = 0;
    return *p == '\n' ? p + 1 : p;
}

int main(int argc, char **argv)
{
    if (argc < 3) { fprintf(stderr, "usage: %s REQUEST_DIR OUTPUT_DIR\n", argv[0]); return 64; }
    HMODULE d3dx = LoadLibraryA("d3dx9_36.dll");
    compile_t compile = d3dx ? (compile_t)GetProcAddress(d3dx, "D3DXCompileShader") : NULL;
    assemble_t assemble = d3dx ? (assemble_t)GetProcAddress(d3dx, "D3DXAssembleShader") : NULL;
    disassemble_t disassemble = d3dx ? (disassemble_t)GetProcAddress(d3dx, "D3DXDisassembleShader") : NULL;
    if (!compile || !assemble || !disassemble) { fprintf(stderr, "d3dx9_36.dll shader entry points unavailable\n"); return 2; }
    char pattern[MAX_PATH];
    snprintf(pattern, sizeof pattern, "%s\\*.req", argv[1]);
    WIN32_FIND_DATAA fd;
    HANDLE find = FindFirstFileA(pattern, &fd);
    if (find == INVALID_HANDLE_VALUE) { printf("no requests\n"); return 0; }
    int ok = 0, failed = 0;
    do {
        char path[MAX_PATH], hash[64];
        snprintf(path, sizeof path, "%s\\%s", argv[1], fd.cFileName);
        snprintf(hash, sizeof hash, "%.*s", (int)(strlen(fd.cFileName) - 4), fd.cFileName);
        size_t size = 0;
        char *req = read_file(path, &size);
        if (!req) continue;
        char function[256], profile[64], flags_text[32], include[16], mlen_text[32], slen_text[32];
        const char *p = req;
        p = field(p, "function", function, sizeof function);
        p = p ? field(p, "profile", profile, sizeof profile) : NULL;
        p = p ? field(p, "flags", flags_text, sizeof flags_text) : NULL;
        p = p ? field(p, "include", include, sizeof include) : NULL;
        p = p ? field(p, "macros", mlen_text, sizeof mlen_text) : NULL;
        if (!p) { fprintf(stderr, "%s: malformed\n", fd.cFileName); free(req); continue; }
        size_t mlen = strtoul(mlen_text, NULL, 10);
        if (mlen > size - (size_t)(p - req)) {
            fprintf(stderr, "%s: truncated macros\n", fd.cFileName); free(req); continue;
        }
        char *macros = (char *)malloc(mlen + 1);
        memcpy(macros, p, mlen);
        macros[mlen] = 0;
        p += mlen;
        p = field(p, "source", slen_text, sizeof slen_text);
        if (!p) { fprintf(stderr, "%s: malformed source\n", fd.cFileName); free(req); free(macros); continue; }
        size_t slen = strtoul(slen_text, NULL, 10);
        if (slen != size - (size_t)(p - req)) {
            fprintf(stderr, "%s: truncated source\n", fd.cFileName); free(req); free(macros); continue;
        }
        MACRO defs[256];
        int ndefs = 0;
        for (char *line = macros; *line && ndefs < 255;) {
            char *end = strchr(line, '\n');
            if (end) *end = 0;
            char *eq = strchr(line, '=');
            if (eq) { *eq = 0; defs[ndefs].Name = line; defs[ndefs].Definition = eq + 1; ++ndefs; }
            if (!end) break;
            line = end + 1;
        }
        defs[ndefs].Name = NULL; defs[ndefs].Definition = NULL;
        ID3DXBuffer *code = NULL, *errors = NULL;
        /* function "@asm" is a D3DXAssembleShader request, "@disasm" a
         * D3DXDisassembleShader one (bytecode as source, comment as macro). */
        HRESULT hr;
        if (!strcmp(function, "@asm")) {
            hr = assemble(p, (UINT)slen, defs, NULL, strtoul(flags_text, NULL, 10), &code, &errors);
        } else if (!strcmp(function, "@disasm")) {
            DWORD *bytecode = (DWORD *)malloc(slen + 4);
            memcpy(bytecode, p, slen);
            hr = disassemble(bytecode, strtoul(flags_text, NULL, 10) != 0, ndefs ? defs[0].Definition : NULL, &code);
            free(bytecode);
        } else {
            hr = compile(p, (UINT)slen, defs, NULL, function, profile, strtoul(flags_text, NULL, 10), &code, &errors, NULL);
        }
        char out[MAX_PATH];
        if (SUCCEEDED(hr) && code) {
            snprintf(out, sizeof out, "%s\\%s.bin", argv[2], hash);
            FILE *f = fopen(out, "wb");
            fwrite(code->v->GetBufferPointer(code), 1, code->v->GetBufferSize(code), f);
            fclose(f);
            ++ok;
            printf("%s %s/%s: %lu bytes\n", hash, function, profile, (unsigned long)code->v->GetBufferSize(code));
        } else {
            snprintf(out, sizeof out, "%s\\%s.err", argv[2], hash);
            FILE *f = fopen(out, "wb");
            fprintf(f, "hr=%08lX\n", (unsigned long)hr);
            if (errors) fwrite(errors->v->GetBufferPointer(errors), 1, errors->v->GetBufferSize(errors), f);
            fclose(f);
            ++failed;
            printf("%s %s/%s: FAILED %08lX %s\n", hash, function, profile, (unsigned long)hr,
                errors ? (const char *)errors->v->GetBufferPointer(errors) : "");
        }
        if (code) code->v->Release(code);
        if (errors) errors->v->Release(errors);
        free(macros);
        free(req);
    } while (FindNextFileA(find, &fd));
    FindClose(find);
    printf("compiled %d, failed %d\n", ok, failed);
    return failed ? 1 : 0;
}
