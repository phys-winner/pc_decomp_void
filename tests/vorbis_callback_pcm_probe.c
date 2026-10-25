/* Decode using the pinned original Sound.dll codec, without a sound device. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct stream_object stream_object;
typedef struct {
    stream_object *stream; /* Original callback dereferences datasource[0]. */
    unsigned char *bytes;
    size_t length, position;
    int bulk, closed;
    unsigned long calls, non_unit_sizes;
    unsigned long long requested_bytes, returned_bytes;
} memory_file;
struct stream_object { uintptr_t *vtable; memory_file *file; };
typedef size_t (__cdecl *read_fn)(void *, size_t, size_t, void *);
typedef int (__cdecl *seek_fn)(void *, __int64, int);
typedef int (__cdecl *close_fn)(void *);
typedef long (__cdecl *tell_fn)(void *);
typedef struct { read_fn read; seek_fn seek; close_fn close; tell_fn tell; } callbacks;
static uintptr_t open1_address, open2_address, read_address, clear_address, legacy_read_address;

/* ECX=this, EDX ignored, buffer/count on stack: exact thiscall RET8 ABI. */
static uint32_t __fastcall memory_stream_read(stream_object *object, void *unused,
                                             void *output, uint32_t requested)
{
    (void)unused;
    memory_file *file = object->file;
    file->calls++;
    file->requested_bytes += requested;
    size_t available = file->length - file->position;
    size_t copied = requested < available ? requested : available;
    memcpy(output, file->bytes + file->position, copied);
    file->position += copied; file->returned_bytes += copied;
    return (uint32_t)copied;
}
static size_t __cdecl memory_read(void *output, size_t size, size_t count, void *opaque)
{
    memory_file *file = opaque;
    if (size != 1) file->non_unit_sizes++;
    if (!file->bulk)
        return ((read_fn)legacy_read_address)(output, size, count, opaque);
    if (!size || !count || count > SIZE_MAX / size) return 0;
    return memory_stream_read(file->stream, NULL, output, (uint32_t)(size * count)) / size;
}
static int __cdecl memory_seek(void *opaque, __int64 offset, int whence)
{
    memory_file *file = opaque;
    __int64 origin = whence == SEEK_SET ? 0 : whence == SEEK_CUR ? file->position :
        whence == SEEK_END ? file->length : -1;
    if (origin < 0 || offset < -origin || offset > (__int64)file->length - origin) return -1;
    file->position = (size_t)(origin + offset); return 0;
}
static int __cdecl memory_close(void *opaque) { ((memory_file *)opaque)->closed++; return 0; }
static long __cdecl memory_tell(void *opaque) { return (long)((memory_file *)opaque)->position; }

/* Original LTCG register ABIs; public cdecl casts would be incorrect. /Oy-
 * keeps wrapper locals anchored at EBP while the callback words are pushed. */
__declspec(noinline) static int codec_open1(void *vf, memory_file *file, const callbacks *functions)
{
    int result;
    __asm {
        mov edx, functions
        push dword ptr [edx + 12]
        push dword ptr [edx + 8]
        push dword ptr [edx + 4]
        push dword ptr [edx]
        mov eax, vf
        mov ecx, file
        call dword ptr open1_address
        add esp, 16
        mov result, eax
    }
    return result;
}
__declspec(noinline) static int codec_open2(void *vf)
{
    int result;
    __asm { mov eax, vf
        call dword ptr open2_address
        mov result, eax }
    return result;
}
__declspec(noinline) static long codec_read(void *vf, void *buffer, int byte_count, int *bitstream)
{
    long result;
    __asm {
        mov esi, vf
        push bitstream
        push byte_count
        push buffer
        call dword ptr read_address
        add esp, 12
        mov result, eax
    }
    return result;
}
__declspec(noinline) static int codec_clear(void *vf)
{
    int result;
    __asm { mov edi, vf
        call dword ptr clear_address
        mov result, eax }
    return result;
}
typedef __int64 (__cdecl *pcm_total_fn)(void *, int);

int main(int argc, char **argv)
{
    if (argc != 5 || sizeof(void *) != 4) return 90;
    FILE *input = fopen(argv[2], "rb");
    if (!input || fseek(input, 0, SEEK_END)) return 91;
    long length = ftell(input);
    if (length <= 0 || length > 1024 * 1024 || fseek(input, 0, SEEK_SET)) return 92;
    memory_file file = {0};
    file.bytes = malloc((size_t)length); file.length = (size_t)length;
    file.bulk = !strcmp(argv[4], "bulk");
    if (!file.bytes || fread(file.bytes, 1, file.length, input) != file.length) return 93;
    fclose(input);
    HMODULE module = LoadLibraryExA(argv[1], NULL,
        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!module) { printf("load_error=%lu\n", GetLastError()); return 94; }
    uintptr_t base = (uintptr_t)module;
    open1_address = base + 0xF440; open2_address = base + 0xF540;
    read_address = base + 0x10500; clear_address = base + 0xF590;
    legacy_read_address = base + 0x61270;
    uintptr_t vtable[10] = {0};
    vtable[9] = (uintptr_t)memory_stream_read; /* Read slot at +0x24. */
    stream_object stream = {vtable, &file}; file.stream = &stream;
    pcm_total_fn total = (pcm_total_fn)(base + 0xF6D0);
    unsigned char *vf = malloc(0x10000);
    if (!vf) return 95;
    memset(vf, 0xA5, 0x10000);
    callbacks functions = {memory_read, memory_seek, memory_close, memory_tell};
    int opened1 = codec_open1(vf, &file, &functions);
    printf("mode=%s\nprocess=%lu\nmodule_base=%08lX\nopen1=%d\n", argv[4],
        GetCurrentProcessId(), (unsigned long)base, opened1);
    if (opened1) return 96;
    int opened2 = codec_open2(vf); printf("open2=%d\n", opened2);
    if (opened2) { codec_clear(vf); return 97; }
    __int64 samples = total(vf, -1); printf("pcm_total=%I64d\n", samples);
    FILE *output = fopen(argv[3], "wb");
    if (!output) { codec_clear(vf); return 98; }
    unsigned char pcm[4096]; unsigned long long decoded = 0;
    int bitstream = -1, status = 0;
    for (;;) {
        long received = codec_read(vf, pcm, sizeof pcm, &bitstream);
        if (!received) break;
        if (received < 0 || received > sizeof pcm || decoded + received > 32 * 1024 * 1024) {
            printf("decode_error=%ld\n", received); status = 99; break;
        }
        if (fwrite(pcm, 1, (size_t)received, output) != (size_t)received) { status = 100; break; }
        decoded += received;
    }
    fclose(output);
    int cleared = codec_clear(vf);
    for (unsigned i = 0x2D0; i < 0x10000; i++) if (vf[i] != 0xA5) status = 101;
    printf("clear=%d\nclosed=%d\nread_calls=%lu\nnon_unit_sizes=%lu\n"
        "requested_bytes=%I64u\nreturned_bytes=%I64u\npcm_bytes=%I64u\nbitstream=%d\n",
        cleared, file.closed, file.calls, file.non_unit_sizes, file.requested_bytes,
        file.returned_bytes, decoded, bitstream);
    if (cleared || file.closed != 1 || file.non_unit_sizes || samples <= 0 || !decoded) status = 102;
    free(vf); free(file.bytes); FreeLibrary(module);
    return status;
}
