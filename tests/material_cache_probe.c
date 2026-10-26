/* Windows directory adapter; the migration/copy/filter bodies below are the
 * production main.c functions, exercising real fixture files and error paths. */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <direct.h>
#include <io.h>
#include <errno.h>
#define strcasecmp _stricmp
#define mkdir(path, mode) _mkdir(path)
#define access _access
#define F_OK 0
#define S_ISDIR(mode) (((mode) & _S_IFMT) == _S_IFDIR)
#define void_log(...) ((void)0)
struct dirent { char d_name[MAX_PATH]; };
typedef struct { HANDLE search; WIN32_FIND_DATAA data; int first; struct dirent entry; } DIR;
static unsigned scans, deletions;
static int fail_delete, fail_scan;
static DIR *opendir(const char *path) {
    char pattern[1400]; snprintf(pattern, sizeof pattern, "%s/*", path);
    DIR *d = calloc(1, sizeof *d);
    d->search = FindFirstFileA(pattern, &d->data);
    if (d->search == INVALID_HANDLE_VALUE) {free(d); errno=ENOENT; return NULL;}
    d->first=1; ++scans; return d;
}
static struct dirent *readdir(DIR *d) {
    if (fail_scan) {errno=EIO; return NULL;}
    if (d->first) d->first=0;
    else if (!FindNextFileA(d->search, &d->data)) {
        errno=GetLastError()==ERROR_NO_MORE_FILES ? 0 : EIO;
        return NULL;
    }
    strcpy(d->entry.d_name,d->data.cFileName); return &d->entry;
}
static int closedir(DIR *d) {int ok=FindClose(d->search); free(d); return ok?0:-1;}
static int cache_unlink(const char *path) {
    ++deletions;
    if (fail_delete && strstr(path,"effects20.dat")) {errno=EACCES; return -1;}
    return _unlink(path);
}
#define unlink cache_unlink

/* __PRODUCTION_FUNCTIONS__ */

/* Execute the actual emitted family selectors for both original renderers. */
static uint32_t eax,ecx,esp;
static uint32_t object[2];
#define MEM32(p) object[((p)-0x1000u)/4u]
#define RECOMP_REGS_LOCALS
#define RECOMP_ENTER(a) ((void)0)
#define RECOMP_REGS_OUT() ((void)0)
#define RECOMP_FLAGS_OUT() ((void)0)
#define FK_NONE 0
#define FK_CMP 1
#define FK_TEST 2
#define FK_ADD 3
#define CMP_B(a,b) ((uint32_t)(a)<(uint32_t)(b))
#define CMP_NE(a,b) ((a)!=(b))
#define CMP_EQ(a,b) ((a)==(b))
#define SET_LO8(a,b) ((a)=((a)&0xffffff00u)|(uint8_t)(b))
/* __SELECTOR_FUNCTIONS__ */

static void marker(char out[1400],const char *dir) {snprintf(out,1400,"%s/.port-sm3-only-v1",dir);}
int main(int argc,char **argv) {
    assert(argc==6);
    for (unsigned hdr=0;hdr<3;++hdr) {
        object[1]=hdr; ecx=0x1000; esp=0x2000;
        selector_2009(); printf("2009 %u %08x\n",hdr,eax); assert(esp==0x2004);
        selector_2008(); printf("2008 %u %08x\n",hdr,eax);
        plain_2009(); printf("plain2009 %u %08x\n",hdr,eax);
        plain_2008(); printf("plain2008 %u %08x\n",hdr,eax);
        profile_2009(); printf("profile2009 %u %08x\n",hdr,eax);
        profile_2008(); printf("profile2008 %u %08x\n",hdr,eax);
    }
    assert(!seed_cache_file("EFFECTS2BH.HDR"));
    assert(seed_cache_file("effects30.hdr") && seed_cache_file("effects30h.dat"));
    assert(seed_cache_file("effects20.dat.backup") && seed_cache_file("effects40.dat"));
    assert(copy_tree(argv[1],argv[2]));
    char path[1400];
    unsigned before=deletions;
    prune_legacy_material_cache(argv[3]); assert(deletions-before==12);
    marker(path,argv[3]); assert(!access(path,F_OK));
    before=deletions; unsigned scanned=scans;
    prune_legacy_material_cache(argv[3]); assert(deletions==before && scans==scanned);
    fail_delete=1; prune_legacy_material_cache(argv[4]); marker(path,argv[4]); assert(access(path,F_OK));
    fail_delete=0; prune_legacy_material_cache(argv[4]); assert(!access(path,F_OK));
    fail_scan=1; prune_legacy_material_cache(argv[5]); marker(path,argv[5]); assert(access(path,F_OK));
    fail_scan=0; prune_legacy_material_cache(argv[5]); assert(!access(path,F_OK));
    puts("production material-cache copy, migration, retry and one-time marker PASS");
    return 0;
}
