"""Keep an active collector's mode, misses and requests away from render compiles."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_x86_incremental import compiler_environment


def main():
    out = ROOT / "build/shaderwarm-isolation-test"
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / "android/host/d3dx9.c").read_text()
    script = (ROOT / "android/host/script.c").read_text()
    assert "extern _Thread_local int void_shader_pregenerating;" in script
    flag = re.search(r"^_Thread_local int void_shader_pregenerating;$", source, re.M).group()
    fnv = re.search(r"^static uint64_t fnv\(.*?^\}", source, re.M | re.S).group()
    misses = source[source.index("#define MISS_SLOTS"):source.index("/* ---- the compile service's page")]
    request = source[source.index("static int write_request"):source.index("static int shader_service")]
    service = re.search(r"^static int shader_service\(.*?^\}", source, re.M | re.S).group()
    production = flag + "\n" + fnv + "\n" + misses + "\n" + request + "\n" + service
    server = source[source.index("int void_d3dx_serve("):source.index("/* The script's `shaderwarm`")]
    assert 'snprintf(requests, sizeof requests, "%s/requests", cache);' in server
    assert "pregen-requests" not in server
    assert server.count("serve_sweep(") == 2
    (out / "probe.c").write_text(r'''
#include <windows.h>
#include <direct.h>
#include <io.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define assert(c) do { if (!(c)) { fprintf(stderr, "failed line %d: %s\n", __LINE__, #c); ExitProcess(3); } } while (0)
#define _Thread_local __declspec(thread)
#define mkdir(path, mode) _mkdir(path)
#define access _access
#define unlink _unlink
#define F_OK 0
#define VLOG(...) ((void)0)
static const char guest[] = "float4 main() : COLOR { return 1; }";
#undef GPTR
#define GPTR(a) (guest + (a))
#define MEM32(a) 0u
static char profile_dir[1100], ring_requests[1100];
static int ring_value, *ring = &ring_value, handed;
static unsigned device_compiles, status_updates, pending_calls;
static uint64_t compiled_key, collected_key;
static HANDLE collected, resume;
enum { SERVICE_NONE, SERVICE_WAITING, SERVICE_ANSWERED, SERVICE_LATE };
static const char *void_data_dir(void) { return profile_dir; }
static void void_log(const char *format, ...) { (void)format; }
static uint64_t void_monotonic_ns(void) { return 100000000000ull; }
static int shader_wait_seconds(uint64_t now) { (void)now; return 0; }
static int void_d3dx_async_aborted(void) { return 0; }
static int async_here(void) { return 0; }
static void async_handed(uint64_t h) { (void)h; assert(0); }
static int pending_find(uint64_t h) { (void)h; ++pending_calls; return -1; }
static int pending_state(int i, uint64_t now) { (void)i; (void)now; assert(0); return 0; }
static void pending_drop(int i) { (void)i; assert(0); }
static int service_alive(void) { return 1; }
static int service_post(uint64_t h, uint64_t now) { (void)h; (void)now; assert(0); return 0; }
static void service_wake(uint64_t h) { (void)h; assert(0); }
static void *memmem(const void *s, size_t n, const void *v, size_t m) { (void)s; (void)n; (void)v; (void)m; return NULL; }
static void shader_family_result(uint64_t h, uint64_t f, int missing) { (void)h; (void)f; assert(!missing); ++status_updates; }
static void shader_missing(uint64_t h, int missing) { (void)h; (void)missing; ++status_updates; }
static int cache_answer(uint64_t h, uint32_t *out, uint32_t *hr, int binary) {
    assert(binary); if (h != compiled_key) return 0; *out = 1; *hr = 0; return 1;
}
static int d3dx_device_fill(uint64_t h, uint32_t src, uint32_t len, uint32_t defines, uint32_t include,
    const char *function, const char *profile, uint32_t flags) {
    (void)src; (void)len; (void)defines; (void)include; (void)flags;
    assert(!strcmp(function, "main") && !strcmp(profile, "ps_3_0"));
    ++device_compiles; compiled_key = h; return 1;
}
static void void_blocking_begin(void) { assert(0); }
static void void_blocking_end(void) { assert(0); }
static void usleep(unsigned n) { (void)n; assert(0); }
#include "production.h"
static int compile_stage(const char *profile) {
    uint32_t out = 0, hr = 0;
    int answer = shader_service(0, sizeof guest - 1, 0, 0, "main", profile, 0x8410, &out, &hr);
    assert(!answer || (out == 1 && hr == 0)); return answer;
}
static uint64_t private_request(void) {
    char path[1200]; WIN32_FIND_DATAA fd;
    snprintf(path, sizeof path, "%s/shadercache/pregen-requests/*.req", profile_dir);
    HANDLE find = FindFirstFileA(path, &fd); assert(find != INVALID_HANDLE_VALUE);
    uint64_t h = strtoull(fd.cFileName, NULL, 16); assert(h && !FindNextFileA(find, &fd)); FindClose(find);
    snprintf(path, sizeof path, "%s/shadercache/pregen-requests/%016llx.req", profile_dir, (unsigned long long)h);
    FILE *f = fopen(path, "rb"); char header[256] = {0}; assert(f && fread(header, 1, sizeof header - 1, f)); fclose(f);
    assert(strstr(header, "function=main\nprofile=ps_3_0\n") && strstr(header, guest));
    snprintf(path, sizeof path, "%s/shadercache/requests/%016llx.req", profile_dir, (unsigned long long)h);
    assert(access(path, F_OK)); return h;
}
static DWORD WINAPI collect(void *unused) {
    (void)unused; assert(!void_shader_pregenerating); void_shader_pregenerating = 1;
    assert(compile_stage("ps_2_0") == 0 && !device_compiles && !status_updates);
    assert(compile_stage("ps_3_0") == 0 && !device_compiles && !status_updates && !pending_calls);
    collected_key = private_request(); SetEvent(collected);
    assert(WaitForSingleObject(resume, 10000) == WAIT_OBJECT_0 && void_shader_pregenerating == 1);
    unsigned before = status_updates, pending_before = pending_calls;
    assert(compile_stage("ps_3_0") == 1 && status_updates == before && pending_calls == pending_before);
    assert(private_request() == collected_key); void_shader_pregenerating = 0; return 0;
}
int main(int argc, char **argv) {
    assert(argc == 2); snprintf(profile_dir, sizeof profile_dir, "%s", argv[1]);
    collected = CreateEventA(NULL, FALSE, FALSE, NULL); resume = CreateEventA(NULL, FALSE, FALSE, NULL);
    assert(collected && resume); HANDLE worker = CreateThread(NULL, 0, collect, NULL, 0, NULL); assert(worker);
    assert(WaitForSingleObject(collected, 10000) == WAIT_OBJECT_0 && !void_shader_pregenerating);
    assert(!miss_recent(collected_key, void_monotonic_ns()));
    assert(compile_stage("ps_3_0") == 1 && device_compiles == 1 && compiled_key == collected_key);
    assert(private_request() == collected_key); SetEvent(resume);
    assert(WaitForSingleObject(worker, 10000) == WAIT_OBJECT_0); DWORD code;
    assert(GetExitCodeThread(worker, &code) && code == 0 && !void_shader_pregenerating);
    CloseHandle(worker); CloseHandle(collected); CloseHandle(resume);
    puts("PASS: concurrent collector mode isolated, same-hash render JIT synchronous, PC request retained, cached collection quiet");
    return 0;
}
''')
    compiler, env, _ = compiler_environment()
    site = "        write_request(dir, 0, h, function, profile, flags, include, macros, mlen, src, len);\n        return 0;"
    assert production.count(site) == 1
    for name in ("current", "global-flag", "shared-miss"):
        header = production
        if name == "global-flag":
            header = header.replace("_Thread_local int void_shader_pregenerating;", "int void_shader_pregenerating;")
        elif name == "shared-miss":
            header = header.replace(site, site.replace("        return 0;", "        miss_note(h, now, 1);\n        return 0;"))
        (out / "production.h").write_text(header)
        exe = out / (name + ".exe")
        build = subprocess.run([str(compiler), "/nologo", "/O2", "/W3", "/std:c11", "/D_CRT_SECURE_NO_WARNINGS",
                                str(out / "probe.c"), "/Fo" + str(out / (name + ".obj")), "/Fe" + str(exe)],
                               env=env, capture_output=True, text=True)
        (out / (name + "-build.log")).write_text(build.stdout + build.stderr)
        assert build.returncode == 0, build.stdout + build.stderr
        with tempfile.TemporaryDirectory(prefix="fixtures-", dir=out) as fixtures:
            run = subprocess.run([str(exe), fixtures], capture_output=True, text=True, timeout=20)
        (out / (name + "-result.txt")).write_text(run.stdout + run.stderr)
        assert (run.returncode == 0) == (name == "current"), run.stdout + run.stderr
        print(run.stdout.strip() if name == "current" else "PASS: rejected " + name + " regression")


if __name__ == "__main__":
    main()
