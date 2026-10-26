/* Actual HUD lookup/present and shader-warm entry, with single-thread GL stubs. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <io.h>
#include <sys/stat.h>
#define _Atomic
typedef int atomic_int;
#define atomic_load(p) (*(p))
#define atomic_store(p,v) (*(p)=(v))
#define atomic_load_explicit(p,o) (*(p))
#define atomic_store_explicit(p,v,o) (*(p)=(v))
#define atomic_fetch_add(p,v) ((*(p)+=(v))-(v))
#define atomic_fetch_sub(p,v) ((*(p)-=(v))+(v))
#define atomic_fetch_add_explicit(p,v,o) atomic_fetch_add(p,v)
static uint32_t exchange32(void *p, uint32_t value) { uint32_t old=*(uint32_t*)p; *(uint32_t*)p=value; return old; }
#define atomic_exchange(p,v) exchange32((p),(v))
#define atomic_exchange_explicit(p,v,o) exchange32((p),(v))
typedef int pthread_mutex_t;
typedef int pthread_once_t;
typedef int pthread_t;
#define PTHREAD_MUTEX_INITIALIZER 0
#define PTHREAD_ONCE_INIT 0
static int pthread_mutex_lock(pthread_mutex_t *p) { (void)p; return 0; }
static int pthread_mutex_unlock(pthread_mutex_t *p) { (void)p; return 0; }
static int pthread_once(pthread_once_t *p, void (*fn)(void)) { if (!*p) { *p=1; fn(); } return 0; }
static int pthread_create(pthread_t *t, void *a, void *(*f)(void*), void *b) { (void)t; (void)a; f(b); return 1; }
static int pthread_detach(pthread_t t) { (void)t; return 0; }
#define strcasecmp _stricmp
#define strncasecmp _strnicmp
#define strtok_r strtok_s
#define stat _stat64
#define lstat _stat64
#define S_ISREG(mode) (((mode)&_S_IFMT)==_S_IFREG)
#define WIN_MAX_PATH 260
#define fseek _fseeki64
#define ftell _ftelli64
#define void_log(...) ((void)0)
static uint32_t g_ecx, g_eax;
void sub_101BF450_lifted(void) { g_eax=0; }
void sub_101BE240_lifted(void) { g_eax=0; }
static void void_touch_observe_context(uint32_t value) { (void)value; }
static uint64_t void_monotonic_ns(void) { static uint64_t now; return now+=1000; }
static const char *archive;
static int vfs_missing;
static FILE *void_vfs_open(const char *container) { assert(!_stricmp(container,"Textures.vfs")); return vfs_missing?NULL:fopen(archive,"rb"); }
typedef struct { const char *win; char host[1024]; } mount_t;
static mount_t mounts[8]; static int mount_count;
static char data_root[1024], cwd[260]="C:\\Games\\The Void\\bin\\win32";
static pthread_mutex_t cwd_lock;
static char *void_fonts_path(const char *path) { (void)path; return NULL; }
/* Host-only directory enumeration; production normalization and resolution follow. */
static int dir_lookup(const char *dir,const char *name,char *out,size_t capacity)
{
    char glob[1200], match[256]=""; snprintf(glob,sizeof glob,"%s/*",dir);
    struct __finddata64_t item; intptr_t h=_findfirst64(glob,&item);
    if(h==-1) return -1;
    do {
        if(!strcasecmp(item.name,name) && (!*match || !strcmp(item.name,name)))
            snprintf(match,sizeof match,"%s",item.name);
    } while(!_findnext64(h,&item));
    _findclose(h); if(*match) snprintf(out,capacity,"%s",match); return *match!=0;
}
#include "path-fixture.h"
#include "hud.h"
#include "vfs_dir.h"
#include "hud_shaders.h"
#include "vfs-fixture.h"
#include "hud-fixture.h"
typedef unsigned GLuint;
#define GL_VERTEX_SHADER 1
#define GL_FRAGMENT_SHADER 2
static unsigned stage_calls, driver_calls;
static uint64_t driver(void) { ++driver_calls; return 1; }
static int d3d_shader_warm_bytecode(const void *p,uint32_t n) { assert(p && n==8); ++stage_calls; return 1; }
static GLuint binary_load(uint64_t h) { (void)h; assert(0); return 0; }
static void binary_save(GLuint p,uint64_t h) { (void)p; (void)h; assert(0); }
static GLuint d3d_shader_compile_source(unsigned t,const char *s) { (void)t; (void)s; assert(0); return 0; }
static GLuint link_recipe(GLuint v,GLuint p,unsigned n,const char **s) { (void)v; (void)p; (void)n; (void)s; assert(0); return 0; }
#include "warm-state.h"
static void *scan_caches(void *unused) { (void)unused; return NULL; }
#include "warm-step.h"

static unsigned char *read_at(const char *path,uint32_t offset,uint32_t size)
{
    FILE *f=fopen(path,"rb"); assert(f && !fseek(f,offset,SEEK_SET));
    unsigned char *p=malloc(size); assert(p && fread(p,1,size,f)==size && !fclose(f)); return p;
}
static void empty_present(void) { void_hud_present(200); assert(!(void_hud_state(NULL)&HUD_MAINMENU)); }
int main(int argc,char **argv)
{
    assert(argc==10); archive=argv[1]; int expected=atoi(argv[4]); vfs_missing=atoi(argv[9]);
    snprintf(mounts[0].host,sizeof mounts[0].host,"%s/game",argv[6]);
    mounts[0].win="C:\\Games\\The Void"; mount_count=1;
    snprintf(data_root,sizeof data_root,"%s/profile",argv[6]);
    uint32_t offset=(uint32_t)strtoul(argv[2],NULL,10), size=(uint32_t)strtoul(argv[3],NULL,10);
    unsigned char *original=read_at(archive,offset,size);
    FILE *input=fopen(argv[7],"rb"); assert(input && !fseek(input,0,SEEK_END));
    uint32_t actual_size=(uint32_t)ftell(input); assert(actual_size && !fseek(input,0,SEEK_SET));
    unsigned char *bytes=malloc(actual_size); assert(bytes && fread(bytes,1,actual_size,input)==actual_size && !fclose(input));
    if (expected && (size!=actual_size || memcmp(original,bytes,size))) assert(!(void_hud_tag_for(original,size,NULL)&HUD_MAINMENU));
    free(original); size=actual_size;
    char superseded_path[1400]; snprintf(superseded_path,sizeof superseded_path,"%s/game/DaTa/tExTuReS/uI/MainMenu_New_RU.TeX",argv[6]);
    input=fopen(superseded_path,"rb");
    if(expected && input) {
        assert(!fseek(input,0,SEEK_END)); uint32_t previous_size=(uint32_t)ftell(input);
        assert(!fseek(input,0,SEEK_SET)); unsigned char *previous=malloc(previous_size); assert(previous);
        assert(fread(previous,1,previous_size,input)==previous_size);
        if(previous_size!=size || memcmp(previous,bytes,size)) assert(!(void_hud_tag_for(previous,previous_size,NULL)&HUD_MAINMENU));
        free(previous);
    }
    if(input) fclose(input);
    uint32_t slot=999, tag=void_hud_tag_for(bytes,size,&slot);
    assert((tag&HUD_MAINMENU)==(expected?HUD_MAINMENU:0));
    assert(slot==(expected?HUD_SLOT_MENU:0));
    /* Creation alone is not a draw and may happen long before the menu. */
    empty_present(); assert(!frame_tags && !frame_slots);
    scan_started=1; scan_finished=1;
    queued=1; queue=calloc(1,sizeof *queue); assert(queue);
    queue->size=8; queue->bytes=calloc(1,8); assert(queue->bytes);
    d3d_shader_warm_step(); assert(!scanned && !warm_total && !stage_calls);
    FILE *negative=fopen(argv[5],"r"); assert(negative);
    uint32_t negative_offset, negative_size, continuation; unsigned negatives=0;
    uint32_t pause_tag=0, pause_slot=0;
    while (fscanf(negative,"%u %u %u",&negative_offset,&negative_size,&continuation)==3) {
        unsigned char *other=read_at(archive,negative_offset,negative_size);
        uint32_t other_slot=0, other_tag=void_hud_tag_for(other,negative_size,&other_slot);
        assert(!(other_tag&HUD_MAINMENU));
        (void)other_slot; (void)continuation;
        void_hud_draw(other_tag); void_hud_present(200);
        d3d_shader_warm_step(); assert(!scanned && !warm_total && !stage_calls);
        free(other); ++negatives;
    }
    assert(negatives==7 && !fclose(negative)); empty_present();
    input=fopen(argv[8],"rb"); assert(input && !fseek(input,0,SEEK_END));
    uint32_t pause_size=(uint32_t)ftell(input); assert(pause_size && !fseek(input,0,SEEK_SET));
    unsigned char *pause_bytes=malloc(pause_size); assert(pause_bytes && fread(pause_bytes,1,pause_size,input)==pause_size && !fclose(input));
    pause_tag=void_hud_tag_for(pause_bytes,pause_size,&pause_slot);
    assert((pause_tag&HUD_PAUSE)==(expected?HUD_PAUSE:0));
    assert(pause_slot==(expected?HUD_SLOT_MENU+6:0));
    pause_bytes[pause_size-1]^=1; assert(!(void_hud_tag_for(pause_bytes,pause_size,NULL)&HUD_PAUSE)); free(pause_bytes);
    /* A caller samples the authentic texture, then presents that frame. */
    float values[32]={0}, rect[4]={.1f,.2f,.3f,.4f};
    void_hud_draw(tag|HUD_CURSOR);
    void_hud_slot_draw(slot,values,values,rect);
    assert(!(void_hud_state(NULL)&HUD_MAINMENU));
    uint32_t before=0, after=0; void_hud_state(&before); void_hud_present(12);
    uint32_t shown=void_hud_state(&after); assert(after==before+1);
    assert((shown&HUD_MAINMENU)==(expected?HUD_MAINMENU:0));
    assert(atomic_load(&forced_tags)==0);
    float slots[HUD_SLOTS][HUD_SLOT_FLOATS];
    assert(void_hud_slots(slots)==(expected?1u<<HUD_SLOT_MENU:0));
    if (expected) assert(!memcmp(slots[HUD_SLOT_MENU]+64,rect,sizeof rect));
    scan_finished=0; d3d_shader_warm_step(); assert(!scanned && !stage_calls);
    scan_finished=1; d3d_shader_warm_step();
    assert(scanned==expected && warm_done==(unsigned)expected && warm_total==(unsigned)expected);
    assert(stage_calls==(unsigned)expected && driver_calls==(unsigned)expected);
    /* The original paused menu draws both glyphs: Java gives PAUSE precedence. */
    void_hud_draw(tag|pause_tag|HUD_CURSOR);
    void_hud_slot_draw(slot,values,values,rect);
    void_hud_slot_draw(pause_slot,values,values,rect);
    void_hud_present(12);
    assert((void_hud_state(NULL)&(HUD_MAINMENU|HUD_PAUSE))==(expected?HUD_MAINMENU|HUD_PAUSE:0));
    assert(void_hud_slots(slots)==(expected?(1u<<HUD_SLOT_MENU)|(1u<<(HUD_SLOT_MENU+6)):0));
    d3d_shader_warm_step(); assert(stage_calls==(unsigned)expected);
    /* No menu draw next frame: publication clears both tag and slot. */
    empty_present(); assert(!void_hud_slots(slots));
    d3d_shader_warm_step(); assert(stage_calls==(unsigned)expected);
    /* A changed pixel past the prefix and a changed prefix both reject. */
    if(expected) {
        bytes[size-1]^=1; slot=999; assert(!(void_hud_tag_for(bytes,size,&slot)&HUD_MAINMENU) && !slot);
        bytes[size-1]^=1; bytes[128]^=1; slot=999; assert(!(void_hud_tag_for(bytes,size,&slot)&HUD_MAINMENU) && !slot);
    }
    free(bytes);
    puts(expected?"PASS: authentic legacy main/pause DDS -> draw -> present -> warm once -> clear; masks/nonmenu/mutations rejected":"PASS: original missing markers reproduce warm stall and absent pause marker");
    return 0;
}
