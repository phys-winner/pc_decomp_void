"""Run the production VM metadata path with guarded arrays and mocked host mappings."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_x86_incremental import compiler_environment


def main():
    out = ROOT / "build/vm-ranges-test"
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / "android/host/memory.c").read_text()
    production = source[:source.index("/* ---------------------------------------------------------------- heaps */")]
    production = re.sub(r"^#include .*\n", "", production, flags=re.M)
    production = re.sub(r"int void_guest_reserve\(void\).*?(?=static int host_prot)", "", production, flags=re.S)
    # Two metadata red-zone slots expose the old out-of-bounds writes without invoking host UB.
    assert production.count("[PAGES]") == 4
    production = production.replace("[PAGES]", "[PAGES + 2]")
    # This fixture mocks storage; the shared large-address runtime probe verifies real zero-filled pages.
    production = production.replace("memset(GPTR(p << 12), 0, GUEST_PAGE)", "zero_guest_page(p << 12, GUEST_PAGE)")
    (out / "production.h").write_text(production)
    (out / "probe.c").write_text(r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef int pthread_mutex_t;
typedef int64_t off_t;
#define PTHREAD_MUTEX_INITIALIZER 0
static int pthread_mutex_lock(int *m) { assert(!*m); *m=1; return 0; }
static int pthread_mutex_unlock(int *m) { assert(*m==1); *m=0; return 0; }
#define GUEST_PAGE 0x1000u
#define GUEST_GRANULARITY 0x10000u
#define GUEST_USER_TOP 0x7FFE0000u
#define GUEST_THUNK_BASE 0x7FF00000u
#define GUEST_THUNK_LIMIT 0x7FFD0000u
#define ERROR_INVALID_PARAMETER_ 87u
#define ERROR_INVALID_ADDRESS_ 487u
#define ERROR_NOT_ENOUGH_MEMORY_ 8u
#define ERROR_ACCESS_DENIED_ 5u
#define PROT_NONE 0
#define PROT_READ 1
#define PROT_WRITE 2
#define MAP_PRIVATE 2
#define MAP_SHARED 1
#define MAP_ANONYMOUS 32
#define MAP_FIXED 16
#define MAP_NORESERVE 16384
#define MAP_FAILED ((void *)-1)
#define MADV_DONTNEED 4
#define GPTR(a) ((void *)(uintptr_t)(a))
static uint32_t query[7], last_error;
#define MEM32(a) query[(a)/4]
#define void_log(...) ((void)0)
static unsigned protects, discards, maps, zeroed_pages;
static int fail_protect;
static void void_set_last_error(uint32_t e) { last_error=e; }
static void void_fatal(const char *format, ...) { (void)format; abort(); }
static void zero_guest_page(uint32_t address, size_t size) { (void)address; assert(size == GUEST_PAGE); ++zeroed_pages; }
int void_vm_writable(uint32_t address, uint32_t size);
static int mprotect(void *p,size_t n,int prot) {
    (void)p;(void)n;(void)prot; ++protects; return fail_protect;
}
static int madvise(void *p,size_t n,int why) {
    (void)p;assert(n && why==MADV_DONTNEED);++discards;return 0;
}
static void *mmap(void *p,size_t n,int prot,int flags,int fd,off_t offset) {
    (void)prot;(void)flags;(void)fd;(void)offset;assert(n);++maps;return p;
}
#include "production.h"
static void reset(void) {
    memset(page_state,0,sizeof page_state);memset(page_protect,0,sizeof page_protect);
    memset(page_alloc,0,sizeof page_alloc);memset(alloc_protect,0,sizeof alloc_protect);
    memset(granule_used,0,sizeof granule_used);granule_used[0]=1;
    protects=discards=maps=zeroed_pages=last_error=0;fail_protect=0;assert(!vm_lock);
}
static void cross_window(void) {
    reset();page_state[PAGES-1]=page_state[PAGES]=ST_RESERVE;
    uint32_t allocated=void_vm_alloc(0xFFFFF000u,8192,MEM_COMMIT_,PAGE_READWRITE_);
#ifdef CONTROL_LEGACY
    assert(allocated==0xFFFFF000u && page_state[PAGES]==ST_COMMIT);
#else
    assert(!allocated && last_error==ERROR_INVALID_ADDRESS_ && page_state[PAGES]==ST_RESERVE);
#endif
    reset();page_state[PAGES-1]=page_state[PAGES]=ST_COMMIT;
    page_protect[PAGES-1]=page_protect[PAGES]=PAGE_READWRITE_;
    uint32_t old=0x12345678;int changed=void_vm_protect(0xFFFFF000u,8192,PAGE_READONLY_,&old);
#ifdef CONTROL_LEGACY
    assert(changed && page_protect[PAGES]==PAGE_READONLY_ && old==PAGE_READWRITE_);
#else
    assert(!changed && last_error==ERROR_INVALID_ADDRESS_ && page_protect[PAGES]==PAGE_READWRITE_ && old==0x12345678);
#endif
    reset();page_state[PAGES-1]=page_state[PAGES]=ST_COMMIT;
    int freed=void_vm_free(0xFFFFF000u,8192,MEM_DECOMMIT_);
#ifdef CONTROL_LEGACY
    assert(freed && page_state[PAGES]==ST_RESERVE);
#else
    assert(!freed && last_error==ERROR_INVALID_ADDRESS_ && page_state[PAGES]==ST_COMMIT);
    assert(!protects && !discards && !maps);
#endif
    assert(!vm_lock);
}
int main(void) {
    cross_window();
#ifndef CONTROL_LEGACY
    const uint32_t invalid[][2]={{0,UINT32_MAX},{1,UINT32_MAX},{0xFFFFF000u,8192},
        {GUEST_USER_TOP-1,2},{GUEST_USER_TOP,1},{UINT32_MAX,2},{0x10000,UINT32_MAX}};
    for(unsigned i=0;i<sizeof invalid/sizeof *invalid;++i) {
        reset();uint32_t at=invalid[i][0],size=invalid[i][1],old=123;
        assert(!void_vm_alloc(at,size,MEM_RESERVE_|MEM_COMMIT_,PAGE_READWRITE_));
        assert(!void_vm_alloc(at,size,MEM_COMMIT_,PAGE_READWRITE_));
        assert(!void_vm_protect(at,size,PAGE_READONLY_,&old) && old==123);
        assert(!void_vm_free(at,size,MEM_DECOMMIT_));
        assert(!protects && !discards && !maps && !vm_lock);
    }
#endif
    for(unsigned page=4096;page<=16384;page*=4) {
        reset();host_page=page;
        assert(void_vm_alloc(0x10001,1,MEM_RESERVE_|MEM_COMMIT_,PAGE_READWRITE_)==0x10000);
        assert(page_state[16]==ST_COMMIT && page_state[17]==ST_FREE && !zeroed_pages);
        assert(void_vm_free(0x10000,0,MEM_RELEASE_) && page_state[16]==ST_FREE);
        assert(void_vm_alloc(0x20000,16384,MEM_RESERVE_|MEM_COMMIT_,PAGE_READWRITE_)==0x20000);
        uint32_t old=0;assert(void_vm_protect(0x21001,1,PAGE_READONLY_,&old) && old==PAGE_READWRITE_);
        fail_protect=1;assert(!void_vm_protect(0x21001,1,PAGE_READWRITE_,&old));
        assert(page_protect[33]==PAGE_READONLY_);fail_protect=0;
        discards=0;assert(void_vm_free(0x21001,1,MEM_DECOMMIT_));
        assert(page_state[32]==ST_COMMIT && page_state[33]==ST_RESERVE && page_state[34]==ST_COMMIT);
        assert(discards==(page==4096));
        zeroed_pages=0;
        assert(void_vm_alloc(0x21001,1,MEM_COMMIT_,PAGE_READWRITE_)==0x21000);
        assert(zeroed_pages==(page>4096)); /* only a reused subpage touches physical RAM */
        assert(void_vm_free(0x20000,0,MEM_DECOMMIT_));
        for(unsigned p=32;p<36;++p) assert(page_state[p]==ST_RESERVE);
        assert(void_vm_free(0x20000,0,MEM_RELEASE_) && !granule_used[2]);
        uint32_t top=GUEST_USER_TOP-65536;
        assert(void_vm_alloc(top,65536,MEM_RESERVE_|MEM_COMMIT_,PAGE_READWRITE_)==top);
        assert(void_vm_free(top,0,MEM_RELEASE_));
        assert(!void_vm_alloc(0x10000,0,MEM_COMMIT_,PAGE_READWRITE_) && last_error==ERROR_INVALID_PARAMETER_);
        assert(!void_vm_protect(0x10000,0,PAGE_READONLY_,&old) && last_error==ERROR_INVALID_PARAMETER_);
        assert(!void_vm_free(0x10000,1,MEM_RELEASE_) && last_error==ERROR_INVALID_PARAMETER_);
        assert(!vm_lock);
    }
#ifdef CONTROL_LEGACY
    puts("PASS: legacy path reproduces all 3 metadata overruns; normal 4/16 KiB VM cases preserved");
#else
    puts("PASS: all 3 metadata overruns rejected; 7 boundary pairs; alignment, rollback and 4/16 KiB neighbours preserved");
#endif
    return 0;
}
''')
    compiler, env, _ = compiler_environment()
    check = "    if (!valid_vm_range(address, size)) return 0;\n"
    assert production.count(check) == 3
    for name, flags, body in (("fixed", [], production), ("tension", ["/DVOID_RELEASE"], production),
                              ("legacy", ["/DCONTROL_LEGACY"], production.replace(check, ""))):
        (out / "production.h").write_text(body)
        exe = out / (name + ".exe")
        command = [str(compiler), "/nologo", "/O2", "/std:c11", "/W3", "/I" + str(out), *flags]
        subprocess.run(command + [str(out / "probe.c"), "/Fo" + str(out) + "\\", "/Fe" + str(exe)],
                       env=env, capture_output=True, text=True, check=True)
        result = subprocess.run([str(exe)], capture_output=True, text=True, check=True)
        print(name + ": " + result.stdout, end="")
    (out / "production.h").write_text(production)


if __name__ == "__main__":
    main()
