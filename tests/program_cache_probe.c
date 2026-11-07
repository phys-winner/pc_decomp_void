#define main shader_warm_existing_main
#include "shader_warm_probe.c"
#undef main
#include <sys/utime.h>

static void cache_file(uint64_t recipe, uint64_t identity, uint32_t payload, int64_t mtime)
{
    char path[1200]; binary_path(recipe, path);
    binary_header h = {BINARY_MAGIC, 0x8741, payload, 0, identity, recipe};
    FILE *f = fopen(path, "wb"); assert(f && fwrite(&h, sizeof h, 1, f) == 1);
    if (payload == 16) assert(fwrite("binary 1", 1, 9, f) == 9);
    assert(!fflush(f) && !_chsize_s(_fileno(f), sizeof h + payload) && !fclose(f));
    struct __utimbuf64 times = {mtime, mtime}; assert(!_utime64(path, &times));
}

static int exists(uint64_t recipe)
{
    char path[1200]; binary_path(recipe, path); return !access(path, F_OK);
}

int main(int argc, char **argv)
{
    assert(argc == 3);
    snprintf(shared, sizeof shared, "%s/cache", argv[1]); assert(!_mkdir(shared));
    snprintf(profile, sizeof profile, "%s/profile", argv[1]); assert(!_mkdir(profile));
    char path[1200], directory[1200]; binary_path(0, directory);
    *strrchr(directory, '/') = 0;
    if (!strcmp(argv[2], "clean")) {
        cache_file(1, driver(), 16, 1000000);
        cache_file(2, driver() ^ 1, 16, 1000001);
        put(directory, "0000000000000003.bin", "bad", 3);
        put(directory, "0000000000000004.bin.part", "unfinished", 10);
        put(directory, "notes.txt", "keep", 4);
        put(directory, "000000000000000A.bin", "keep", 4);
        snprintf(path, sizeof path, "%s/0000000000000005.bin", directory); assert(!_mkdir(path));
        put(path, "child", "keep", 4);
        /* Python may supply a link; the production scan must leave its target alone. */
        const uint64_t stored = sizeof(binary_header) + 16;
        assert(binary_load(1));
        assert(atomic_load(&binary_bytes) == stored && !exists(2) && !exists(3));
        snprintf(path, sizeof path, "%s/0000000000000004.bin.part", directory); assert(access(path, F_OK));
        snprintf(path, sizeof path, "%s/notes.txt", directory); assert(!access(path, F_OK));
        snprintf(path, sizeof path, "%s/000000000000000A.bin", directory); assert(!access(path, F_OK));
        snprintf(path, sizeof path, "%s/0000000000000005.bin/child", directory); assert(!access(path, F_OK));
        binary_save(1, 6); assert(exists(6) && atomic_load(&binary_bytes) == 2 * stored);
        reject_binaries = 1; assert(!binary_load(1) && !exists(1));
        assert(atomic_load(&binary_bytes) == stored);
        reject_binaries = 0; binary_save(1, 1);
        assert(exists(1) && atomic_load(&binary_bytes) == 2 * stored);
        scan_caches(NULL); assert(atomic_load(&binary_bytes) == 2 * stored);
        puts("PASS: stale driver, corrupt and partial files removed; unknown names/directories kept; header and rejection accounting; worker does not double-count");
    } else if (!strcmp(argv[2], "budget")) {
        assert(!binary_load(99));
        uint64_t stored = sizeof(binary_header) + 16;
        atomic_store(&binary_bytes, BINARY_BUDGET - stored + 1);
        binary_save(1, 1); assert(!exists(1));
        atomic_store(&binary_bytes, BINARY_BUDGET - stored);
        binary_save(1, 1); assert(exists(1) && atomic_load(&binary_bytes) == BINARY_BUDGET);
        binary_save(1, 2); assert(!exists(2) && atomic_load(&binary_bytes) == BINARY_BUDGET);
        puts("PASS: exact budget boundary includes binary header and refuses overflow");
    } else {
        int count = !strcmp(argv[2], "trim") ? 25 : 24;
        for (int i = 0; i < count; ++i) cache_file((uint64_t)i + 1, driver(), BINARY_LIMIT - sizeof(binary_header), 1000000 + i);
        assert(!binary_load(99));
        uint64_t expected = count == 25 ? BINARY_BUDGET * 3 / 4 : BINARY_BUDGET;
        assert(atomic_load(&binary_bytes) == expected);
        for (int i = 0; i < count; ++i) assert(exists((uint64_t)i + 1) == (count != 25 || i >= 7));
        puts(count == 25 ? "PASS: oldest files trimmed from 400 MiB to 288 MiB" : "PASS: cache at 384 MiB is retained byte-exactly");
    }
    return 0;
}
