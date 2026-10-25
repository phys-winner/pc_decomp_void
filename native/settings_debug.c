#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wctype.h>
#include <errno.h>
#define COBJMACROS
#include <d3d9.h>
#include "settings_debug.h"
#include "settings_regex.h"
#include "menu_profiles.h"

#define XML_CAP 32768
typedef struct Config {
    int width, height, refresh, vsync, hdr, aa, af, texture, lightmap, rate;
    int memory;
} Config;

static wchar_t config_dir[MAX_PATH];
static Config current;
static int ready;
static const char *last_error = "not initialized";
typedef struct DisplayMode { int width,height,refresh; } DisplayMode;
#define MODE_CAP 4096
static DisplayMode display_modes[MODE_CAP];
static unsigned display_mode_count, aa_mask[2], maximum_af;
static D3DADAPTER_IDENTIFIER9 adapter;
static int adapter_available, capabilities_available, auto_profile;
static IDirect3D9 *adapter_api;
static HMODULE adapter_library;
static int original_data_verified;
#ifdef VOID_SETTINGS_TEST
static int fixture_adapter;
void void_settings_debug_test_adapter(unsigned vendor,unsigned device,const char *description,
    const int *triples,unsigned count,unsigned aa,unsigned hdr_aa,unsigned af) {
    unsigned i;
    fixture_adapter=1; adapter_available=1;
    capabilities_available=af!=~0U;
    memset(&adapter,0,sizeof(adapter));adapter.VendorId=vendor;adapter.DeviceId=device;
    strncpy_s(adapter.Description,sizeof(adapter.Description),description,_TRUNCATE);
    display_mode_count=count<MODE_CAP?count:MODE_CAP;
    for(i=0;i<display_mode_count;++i) {
        display_modes[i].width=triples[i*3];display_modes[i].height=triples[i*3+1];
        display_modes[i].refresh=triples[i*3+2];
    }
    aa_mask[0]=aa|1U;aa_mask[1]=hdr_aa|1U;maximum_af=capabilities_available?af:0;
}
#endif

const char *void_settings_debug_error(void) { return last_error; }
static int reject(const char *reason) { last_error = reason; return 0; }

int void_settings_debug_set_data_directory(const wchar_t *original_data) {
    wchar_t path[MAX_PATH];
    HANDLE file;
    char bytes[sizeof(void_gpu_profiles_source)];
    DWORD size,read;
    original_data_verified=0;
    if(!original_data || _snwprintf_s(path,MAX_PATH,_TRUNCATE,L"%s\\profiles.xml",original_data)<0)
        return reject("invalid original data directory");
    file=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL);
    if(file==INVALID_HANDLE_VALUE) return reject("cannot read original GPU profiles");
    size=GetFileSize(file,NULL);
    if(size!=sizeof(void_gpu_profiles_source)-1 || !ReadFile(file,bytes,size,&read,NULL) || read!=size ||
        memcmp(bytes,void_gpu_profiles_source,size)) {
        CloseHandle(file);return reject("original GPU profiles do not match pinned input");
    }
    CloseHandle(file);original_data_verified=1;return 1;
}

static int mode_compare(const void *left,const void *right) {
    const DisplayMode *a=(const DisplayMode *)left,*b=(const DisplayMode *)right;
    if(a->width!=b->width) return a->width<b->width?-1:1;
    if(a->height!=b->height) return a->height<b->height?-1:1;
    return a->refresh==b->refresh?0:(a->refresh<b->refresh?-1:1);
}

static void normalize_modes(void) {
    unsigned read,write=0;
    qsort(display_modes,display_mode_count,sizeof(DisplayMode),mode_compare);
    for(read=0;read<display_mode_count;++read) {
        DisplayMode m=display_modes[read];
        if(m.width<640 || m.width>8192 || m.height<480 || m.height>8192 ||
            m.refresh<30 || m.refresh>360) continue;
        if(write && !mode_compare(&display_modes[write-1],&m)) continue;
        display_modes[write++]=m;
    }
    display_mode_count=write;
    if(maximum_af>16)maximum_af=16;
}

static void query_adapter(void) {
    typedef IDirect3D9 *(WINAPI *CreateD3D9)(UINT);
    CreateD3D9 create;
    D3DCAPS9 caps;
    UINT count,i;
    unsigned hdr,level;
    DWORD quality;
#ifdef VOID_SETTINGS_TEST
    if(fixture_adapter) {normalize_modes();return;}
#endif
    adapter_available=0;capabilities_available=0;display_mode_count=0;maximum_af=0;aa_mask[0]=aa_mask[1]=1U;
    if(adapter_api) {IDirect3D9_Release(adapter_api);adapter_api=NULL;}
    if(adapter_library) {FreeLibrary(adapter_library);adapter_library=NULL;}
    adapter_library=LoadLibraryExW(L"d3d9.dll",NULL,LOAD_LIBRARY_SEARCH_SYSTEM32);
    if(!adapter_library)return;
    create=(CreateD3D9)GetProcAddress(adapter_library,"Direct3DCreate9");
    if(!create || !(adapter_api=create(D3D_SDK_VERSION)) || !IDirect3D9_GetAdapterCount(adapter_api))return;
    if(FAILED(IDirect3D9_GetAdapterIdentifier(adapter_api,D3DADAPTER_DEFAULT,0,&adapter)))return;
    adapter_available=1;
    if(SUCCEEDED(IDirect3D9_GetDeviceCaps(adapter_api,D3DADAPTER_DEFAULT,D3DDEVTYPE_HAL,&caps))) {
        maximum_af=caps.MaxAnisotropy;capabilities_available=1;
    }
    count=IDirect3D9_GetAdapterModeCount(adapter_api,D3DADAPTER_DEFAULT,D3DFMT_X8R8G8B8);
    if(count>MODE_CAP)count=MODE_CAP;
    for(i=0;i<count;++i) {
        D3DDISPLAYMODE mode;
        if(SUCCEEDED(IDirect3D9_EnumAdapterModes(adapter_api,D3DADAPTER_DEFAULT,D3DFMT_X8R8G8B8,i,&mode))) {
            display_modes[display_mode_count].width=(int)mode.Width;
            display_modes[display_mode_count].height=(int)mode.Height;
            display_modes[display_mode_count++].refresh=(int)mode.RefreshRate;
        }
    }
    for(hdr=0;capabilities_available && hdr<2;++hdr)for(level=1;level<=16;++level)
        if(SUCCEEDED(IDirect3D9_CheckDeviceMultiSampleType(adapter_api,D3DADAPTER_DEFAULT,D3DDEVTYPE_HAL,
            hdr?D3DFMT_A16B16G16R16F:D3DFMT_X8R8G8B8,FALSE,(D3DMULTISAMPLE_TYPE)level,&quality)))
            aa_mask[hdr]|=1U<<level;
    normalize_modes();
}

static int highest_refresh(int width,int height) {
    unsigned i;int result=0;
    for(i=0;i<display_mode_count;++i)
        if(display_modes[i].width==width && display_modes[i].height==height && display_modes[i].refresh>result)
            result=display_modes[i].refresh;
    return result;
}

static unsigned resolution_count(void) {
    unsigned i,n=0;
    for(i=0;i<display_mode_count;++i)
        if(!i || display_modes[i].width!=display_modes[i-1].width || display_modes[i].height!=display_modes[i-1].height)++n;
    return n;
}

static unsigned refresh_count(const Config *c) {
    unsigned i,n=1; /* D3D default refresh0 is always legal. */
    for(i=0;i<display_mode_count;++i)
        if(display_modes[i].width==c->width && display_modes[i].height==c->height)++n;
    return n;
}

static unsigned supported_aa(const Config *c) {return aa_mask[c->hdr==2];}
static int safe_aa(const Config *c,int requested) {
    unsigned mask=supported_aa(c);int level;
    for(level=requested>16?16:requested;level>0;--level)if(mask&(1U<<level))return level;
    return 0;
}

static int detect_profile(Config *next,int *chosen) {
    unsigned p;
    int found=-1;
    if(!adapter_available || !capabilities_available)return reject("GPU identification/capabilities unavailable");
    for(p=0;p<VOID_GPU_PROFILE_COUNT && found<0;++p) {
        const char *cursor=void_gpu_profiles[p].models;
        if(adapter.VendorId!=void_gpu_profiles[p].vendor)continue;
        while(*cursor) {
            char *end;unsigned long model=strtoul(cursor,&end,16);
            if(end==cursor)break;
            if(model==adapter.DeviceId) {found=(int)p;break;}
            cursor=*end==','?end+1:end;
        }
    }
    for(p=0;p<VOID_GPU_PROFILE_COUNT && found<0;++p)
        if(void_settings_regex_match(void_gpu_profiles[p].search,adapter.Description)==1)found=(int)p;
    next->width=800;next->height=600;next->refresh=0;next->vsync=0;next->hdr=found<0?1:0;
    next->aa=0;next->af=0;next->texture=1;next->lightmap=2;
    if(found>=0) {
        const VoidGPUProfile *profile=&void_gpu_profiles[found];
        next->width=profile->width;next->height=profile->height;next->vsync=profile->vsync;
        next->hdr=profile->hdr;next->aa=safe_aa(next,profile->aa);
        next->af=profile->af>(int)maximum_af?(int)maximum_af:profile->af;
        next->texture=profile->texture;next->lightmap=profile->lightmap;
    }
    /* Original Config454280 selects the highest enumerated refresh for the
     * requested dimensions; it retains the dimensions if no mode exists. */
    next->refresh=highest_refresh(next->width,next->height);
    *chosen=found<0?-1:found+1;
    return 1;
}

static int next_resolution(Config *next) {
    unsigned i,first=MODE_CAP,selected=MODE_CAP;
    int after=0;
    for(i=0;i<display_mode_count;++i) {
        if(i && display_modes[i].width==display_modes[i-1].width && display_modes[i].height==display_modes[i-1].height)continue;
        if(first==MODE_CAP)first=i;
        if(after) {selected=i;break;}
        if(display_modes[i].width==next->width && display_modes[i].height==next->height)after=1;
    }
    if(selected==MODE_CAP)selected=first;
    if(selected==MODE_CAP)return reject("No supported display modes available");
    next->width=display_modes[selected].width;next->height=display_modes[selected].height;
    next->refresh=highest_refresh(next->width,next->height);return 1;
}

static void next_refresh(Config *next) {
    unsigned i;int selected=0;
    for(i=0;i<display_mode_count;++i)if(display_modes[i].width==next->width && display_modes[i].height==next->height &&
        display_modes[i].refresh>next->refresh) {selected=display_modes[i].refresh;break;}
    next->refresh=selected;
}

unsigned void_settings_debug_snapshot(const wchar_t **keys,int *values,unsigned capacity) {
    static const wchar_t *names[]={L"PortWidth",L"PortHeight",L"PortRefreshRate",L"PortVSync",L"PortHDR",
        L"PortAntialiasing",L"PortAnisotropy",L"PortTextureQuality",L"PortLightmapQuality",L"PortSoundRate",
        L"PortModeCount",L"PortRefreshCount",L"PortAutoProfile",L"PortAAModeCount",L"PortMaxAnisotropy"};
    int data[15];unsigned i,n=0,mask;
    if(!ready || !keys || !values)return 0;
    data[0]=current.width;data[1]=current.height;data[2]=current.refresh;data[3]=current.vsync;data[4]=current.hdr;
    data[5]=current.aa;data[6]=current.af;data[7]=current.texture;data[8]=current.lightmap;data[9]=current.rate;
    data[10]=(int)resolution_count();data[11]=(int)refresh_count(&current);data[12]=auto_profile;
    mask=supported_aa(&current);for(i=0;i<=16;++i)if(mask&(1U<<i))++n;
    data[13]=capabilities_available?(int)n:-1;data[14]=capabilities_available?(int)maximum_af:-1;
    n=capacity<15?capacity:15;
    for(i=0;i<n;++i) {keys[i]=names[i];values[i]=data[i];}
    return n;
}

static int make_path(wchar_t *out, const wchar_t *name) {
    return _snwprintf_s(out, MAX_PATH, _TRUNCATE, L"%s\\%s", config_dir, name) >= 0;
}

static int read_xml(const wchar_t *name, char *out) {
    wchar_t path[MAX_PATH];
    HANDLE file;
    DWORD bytes, size;
    if (!make_path(path, name)) return reject("path too long");
    file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
                       FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return reject("cannot read configuration");
    size = GetFileSize(file, NULL);
    if (!size || size >= XML_CAP || !ReadFile(file, out, size, &bytes, NULL) || bytes != size) {
        CloseHandle(file); return reject("invalid configuration size/read");
    }
    CloseHandle(file);
    if (memchr(out, 0, size)) return reject("configuration must be UTF-8 text");
    out[size] = 0;
    return 1;
}

static int atomic_write(const wchar_t *name, const char *xml) {
    wchar_t path[MAX_PATH], temporary[MAX_PATH];
    HANDLE file;
    DWORD bytes, length = (DWORD)strlen(xml);
    int ok;
    if (!make_path(path, name) || !GetTempFileNameW(config_dir, L"vui", 0, temporary))
        return reject("cannot create configuration temporary file");
    file = CreateFileW(temporary, GENERIC_WRITE, 0, NULL, TRUNCATE_EXISTING,
                       FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) { DeleteFileW(temporary); return reject("cannot open temporary file"); }
    ok = WriteFile(file, xml, length, &bytes, NULL) && bytes == length && FlushFileBuffers(file);
    CloseHandle(file);
    if (ok) ok = MoveFileExW(temporary, path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
    if (!ok) { DeleteFileW(temporary); return reject("configuration commit failed"); }
    return 1;
}

static int numeric(const char *begin, const char *end, int *value) {
    unsigned int n = 0;
    while (begin < end && (*begin==' ' || *begin=='\r' || *begin=='\n' || *begin=='\t')) ++begin;
    if (begin == end || *begin < '0' || *begin > '9') return 0;
    while (begin < end && *begin >= '0' && *begin <= '9') {
        if (n > 100000U) return 0;
        n = n*10U + (unsigned int)(*begin++ - '0');
    }
    while (begin < end && (*begin==' ' || *begin=='\r' || *begin=='\n' || *begin=='\t')) ++begin;
    if (begin != end || n > 1000000U) return 0;
    *value = (int)n;
    return 1;
}

static int element(const char *xml, const char *key, int *value, int optional) {
    char opening[64], closing[64];
    const char *start, *end;
    _snprintf_s(opening, sizeof(opening), _TRUNCATE, "<%s>", key);
    _snprintf_s(closing, sizeof(closing), _TRUNCATE, "</%s>", key);
    start = strstr(xml, opening);
    if (!start) return optional;
    if (strstr(start + strlen(opening), opening)) return reject("duplicate configuration element");
    start += strlen(opening);
    end = strstr(start, closing);
    return end && numeric(start, end, value) ? 1 : reject("invalid numeric configuration element");
}

static int attribute(const char *tag, const char *end, const char *key, int *value) {
    char marker[64];
    const char *p, *q;
    _snprintf_s(marker, sizeof(marker), _TRUNCATE, "%s=\"", key);
    p = strstr(tag, marker);
    if (!p || p >= end) return 0;
    p += strlen(marker);
    q = strchr(p, '"');
    return q && q <= end && numeric(p, q, value);
}

static int valid(const Config *c) {
    return c->width >= 640 && c->width <= 8192 && c->height >= 480 && c->height <= 8192 &&
        (c->refresh == 0 || (c->refresh >= 30 && c->refresh <= 360)) &&
        c->vsync >= 0 && c->vsync <= 1 && c->hdr >= 0 && c->hdr <= 2 &&
        c->aa >= 0 && c->aa <= 16 && c->af >= 0 && c->af <= 16 &&
        c->texture >= 0 && c->texture <= 1 && c->lightmap >= 0 && c->lightmap <= 2 &&
        (c->rate == 22 || c->rate == 44) &&
        (c->memory == 0 || (c->memory >= 16 && c->memory <= 4096));
}

static int load_config(Config *c) {
    char xml[XML_CAP];
    const char *tag, *end;
    int simple;
    Config defaults = {800,600,0,0,1,0,0,1,2,44,0};
    *c = defaults;
    if (!read_xml(L"rcfg.xml", xml) || !strstr(xml,"<Renderer>") || !strstr(xml,"</Renderer>"))
        return reject("invalid Renderer configuration");
    if (!element(xml,"Width",&c->width,0) || !element(xml,"Height",&c->height,0) ||
        !element(xml,"RefreshRate",&c->refresh,1) || !element(xml,"Antialiasing",&c->aa,1) ||
        !element(xml,"Anisotropy",&c->af,1) || !element(xml,"TextureQuality",&c->texture,1) ||
        !element(xml,"LightmapQuality",&c->lightmap,1)) return 0;
    c->vsync = strstr(xml,"<VSync") != NULL;
    tag = strstr(xml,"<HDR");
    c->hdr = 0;
    if (tag) {
        end = strchr(tag,'>');
        if (!end) return reject("invalid HDR element");
        simple = 0;
        if (strstr(tag,"simple=") && strstr(tag,"simple=") < end &&
            !attribute(tag,end,"simple",&simple)) return reject("invalid HDR attribute");
        if (simple != 0 && simple != 1) return reject("invalid HDR mode");
        c->hdr = simple ? 1 : 2;
    }
    if (!read_xml(L"scfg.xml",xml) || !strstr(xml,"<Sound>") || !strstr(xml,"</Sound>"))
        return reject("invalid Sound configuration");
    tag = strstr(xml,"<Quality");
    end = tag ? strchr(tag,'>') : NULL;
    if (tag && (!end || !attribute(tag,end,"rate",&c->rate))) return reject("invalid audio quality");
    tag = strstr(xml,"<Memory");
    end = tag ? strchr(tag,'>') : NULL;
    if (tag && (!end || !attribute(tag,end,"size",&c->memory))) return reject("invalid audio memory");
    return valid(c) ? 1 : reject("configuration value outside supported bounds");
}

static int write_config(const Config *c, int sound) {
    char xml[2048], hdr[48], memory[64];
    if (sound) {
        memory[0] = 0;
        if (c->memory) _snprintf_s(memory,sizeof(memory),_TRUNCATE,"  <Memory size=\"%d\" />\n",c->memory);
        _snprintf_s(xml,sizeof(xml),_TRUNCATE,
            "<?xml version=\"1.0\" encoding=\"utf-8\" ?>\n<Sound>\n  <Quality rate=\"%d\" />\n%s</Sound>\n",c->rate,memory);
        return atomic_write(L"scfg.xml",xml);
    }
    hdr[0] = 0;
    if (c->hdr) _snprintf_s(hdr,sizeof(hdr),_TRUNCATE,"  <HDR simple=\"%d\" />\n",c->hdr==1);
    _snprintf_s(xml,sizeof(xml),_TRUNCATE,
        "<?xml version=\"1.0\" encoding=\"utf-8\" ?>\n<Renderer>\n"
        "  <Width>%d</Width>\n  <Height>%d</Height>\n  <RefreshRate>%d</RefreshRate>\n%s%s"
        "  <Antialiasing>%d</Antialiasing>\n  <Anisotropy>%d</Anisotropy>\n"
        "  <TextureQuality>%d</TextureQuality>\n  <LightmapQuality>%d</LightmapQuality>\n</Renderer>\n",
        c->width,c->height,c->refresh,c->vsync?"  <VSync />\n":"",hdr,c->aa,c->af,c->texture,c->lightmap);
    return atomic_write(L"rcfg.xml",xml);
}

static int add_property(char *xml, const char *name, int value, int replace) {
    char key[96], line[128];
    char *end;
    size_t suffix;
    _snprintf_s(key,sizeof(key),_TRUNCATE,"name=\"%s\"",name);
    if (strstr(xml,key)) {
        if (replace) {
            char *property = strstr(xml,key), *value_start, *value_end, *tag_end;
            size_t old_length, new_length;
            tag_end = strchr(property,'>');
            value_start = strstr(property,"value=\"");
            if (!tag_end || !value_start || value_start>=tag_end)
                return reject("invalid existing port setting");
            value_start += 7;
            value_end = strchr(value_start,'"');
            if (!value_end || value_end>tag_end) return reject("invalid existing port setting value");
            _snprintf_s(line,sizeof(line),_TRUNCATE,"%d",value);
            old_length = (size_t)(value_end-value_start);
            new_length = strlen(line);
            if (strlen(xml)-old_length+new_length>=XML_CAP) return reject("Settings document too large");
            memmove(value_start+new_length,value_end,strlen(value_end)+1);
            memcpy(value_start,line,new_length);
        }
        return 1;
    }
    end = strstr(xml,"</Settings>");
    if (!end) return reject("invalid Settings document");
    _snprintf_s(line,sizeof(line),_TRUNCATE,"  <prop name=\"%s\" value=\"%d\" />\n",name,value);
    if (strlen(xml)+strlen(line)>=XML_CAP) return reject("Settings document too large");
    suffix = strlen(end)+1;
    memmove(end+strlen(line),end,suffix);
    memcpy(end,line,strlen(line));
    return 1;
}

static int seed_settings(const Config *c) {
    char xml[XML_CAP];
    wchar_t path[MAX_PATH];
    const char *names[] = {"DebugInterface","PortDebugColour","PortDebugAmount","PortWidth","PortHeight",
        "PortRefreshRate","PortVSync","PortHDR","PortAntialiasing","PortAnisotropy",
        "PortTextureQuality","PortLightmapQuality","PortSoundRate","PortModeCount","PortRefreshCount",
        "PortAutoProfile","PortAAModeCount","PortMaxAnisotropy"};
    int values[] = {0,0,100,c->width,c->height,c->refresh,c->vsync,c->hdr,c->aa,c->af,c->texture,c->lightmap,c->rate,
        (int)resolution_count(),(int)refresh_count(c),0,-1,capabilities_available?(int)maximum_af:-1};
    size_t i;
    if(capabilities_available) {
        unsigned mask=supported_aa(c),count=0,level;
        for(level=0;level<=16;++level)if(mask&(1U<<level))++count;
        values[16]=(int)count;
    }
    if (!make_path(path,L"settings.xml")) return reject("path too long");
    if (GetFileAttributesW(path)==INVALID_FILE_ATTRIBUTES && GetLastError()==ERROR_FILE_NOT_FOUND) {
        strcpy_s(xml,sizeof(xml),"<?xml version=\"1.0\" encoding=\"utf-8\" ?>\n<Settings>\n"
            "  <prop name=\"Gamma\" value=\"1\" />\n  <prop name=\"InvertMouse\" value=\"0\" />\n"
            "  <prop name=\"MasterVolume\" value=\"0.8\" />\n  <prop name=\"MouseSensitivity\" value=\"1\" />\n"
            "  <prop name=\"MouseSmooth\" value=\"0\" />\n  <prop name=\"MusicVolume\" value=\"0.6\" />\n"
            "  <prop name=\"Shadows\" value=\"1\" />\n  <prop name=\"SoundVolume\" value=\"0.8\" />\n"
            "  <prop name=\"Subtitles\" value=\"1\" />\n  <prop name=\"VoiceVolume\" value=\"0.7\" />\n</Settings>\n");
    } else if (!read_xml(L"settings.xml",xml)) return 0;
    for (i=0;i<sizeof(values)/sizeof(values[0]);++i)
        if (!add_property(xml,names[i],values[i],i>=3)) return 0;
    return atomic_write(L"settings.xml",xml);
}

int void_settings_debug_init(const wchar_t *common_appdata) {
    wchar_t profile[MAX_PATH], expected[MAX_PATH], passed[MAX_PATH], base[MAX_PATH];
    DWORD n;
    ready = 0;
    if(!original_data_verified)return reject("pinned original data directory required");
    n = GetEnvironmentVariableW(L"VOID_PROFILE_ROOT",profile,MAX_PATH);
    if (!n || n>=MAX_PATH || !common_appdata) return reject("isolated profile required");
    n = GetFullPathNameW(profile,MAX_PATH,base,NULL);
    if (!n || n>=MAX_PATH || _snwprintf_s(expected,MAX_PATH,_TRUNCATE,L"%s\\CommonAppData",base)<0)
        return reject("isolated profile path too long/invalid");
    n = GetFullPathNameW(common_appdata,MAX_PATH,passed,NULL);
    if (!n || n>=MAX_PATH || _wcsicmp(expected,passed))
        return reject("CommonAppData must belong to the isolated profile");
    if (_snwprintf_s(config_dir,MAX_PATH,_TRUNCATE,L"%s\\Ice-pick Lodge",passed)<0)
        return reject("path too long");
    if (!CreateDirectoryW(config_dir,NULL) && GetLastError()!=ERROR_ALREADY_EXISTS)
        return reject("cannot create isolated company directory");
    if (wcscat_s(config_dir,MAX_PATH,L"\\Void")) return reject("path too long");
    if (!CreateDirectoryW(config_dir,NULL) && GetLastError()!=ERROR_ALREADY_EXISTS)
        return reject("cannot create isolated game directory");
    query_adapter();auto_profile=0;
    if (!load_config(&current) || !seed_settings(&current)) return 0;
    ready = 1;
    last_error = "";
    return 1;
}

static int command_integer(const wchar_t **cursor, int *value) {
    const wchar_t *start = *cursor;
    wchar_t *end;
    long n;
    while (*start == L' ' || *start == L'\t') ++start;
    if (*start < L'0' || *start > L'9') return 0;
    errno = 0;
    n = wcstol(start,&end,10);
    if (errno || end==start || n<0 || n>1000000L) return 0;
    *cursor = end;
    *value = (int)n;
    return 1;
}

int void_settings_debug_command(const wchar_t *command) {
    wchar_t key[40];
    int first, second = 0, sound = 0, selected_profile;
    Config next;
    const wchar_t *tail;
    if (!command || wcsncmp(command,L"port_config",11) ||
        (command[11] && command[11]!=L' ' && command[11]!=L'\t')) return 0;
    if (!ready) { reject("settings backend not initialized"); return -1; }
    if (wcslen(command)>128) { reject("command too long"); return -1; }
    tail = command + 11;
    while (*tail == L' ' || *tail == L'\t') ++tail;
    {
        size_t length = 0;
        while (tail[length] && tail[length] != L' ' && tail[length] != L'\t') ++length;
        if (!length || length >= _countof(key)) { reject("invalid setting name"); return -1; }
        memcpy(key,tail,length*sizeof(wchar_t)); key[length]=0; tail += length;
    }
    if (!command_integer(&tail,&first)) { reject("expected a numeric value"); return -1; }
    next = current;
    selected_profile=auto_profile;
    if (!wcscmp(key,L"Resolution")) {
        if (!command_integer(&tail,&second)) { reject("Resolution expects width and height"); return -1; }
        next.width=first; next.height=second;
    } else {
        if (!wcscmp(key,L"Autodetect") || !wcscmp(key,L"NextResolution") ||
            !wcscmp(key,L"NextRefresh") || !wcscmp(key,L"NextAA") || !wcscmp(key,L"NextAF")) {
            if(first!=1) {reject("adapter action expects 1");return -1;}
            if((!wcscmp(key,L"Autodetect") || !wcscmp(key,L"NextAA") || !wcscmp(key,L"NextAF")) && !capabilities_available)
                query_adapter();
            if(!wcscmp(key,L"Autodetect")) {
                if(!detect_profile(&next,&selected_profile))return -1;
            } else if(!wcscmp(key,L"NextResolution")) {
                if(!next_resolution(&next))return -1;
            } else if(!wcscmp(key,L"NextRefresh")) {
                if(!highest_refresh(next.width,next.height)) {reject("No supported refresh rates available");return -1;}
                next_refresh(&next);
            } else if(!wcscmp(key,L"NextAA")) {
                unsigned level,mask=supported_aa(&next);next.aa=0;
                if(!capabilities_available) {reject("GPU capabilities unavailable");return -1;}
                for(level=(unsigned)current.aa+1;level<=16;++level)if(mask&(1U<<level)) {next.aa=(int)level;break;}
            } else {
                if(!capabilities_available) {reject("GPU capabilities unavailable");return -1;}
                next.af=current.af<(int)maximum_af?current.af+1:0;
            }
        }
        else if (!wcscmp(key,L"Minimum")) {
            if (first!=1) { reject("Minimum expects 1"); return -1; }
            /* Config.exe 00454AFE..00454B29, unmatched GPU profile. */
            next.width=800; next.height=600; next.refresh=0; next.vsync=0;
            next.hdr=1; next.aa=0; next.af=0; next.texture=1; next.lightmap=2;
        }
        else if (!wcscmp(key,L"RefreshRate")) next.refresh=first;
        else if (!wcscmp(key,L"VSync")) next.vsync=first;
        else if (!wcscmp(key,L"HDR")) next.hdr=first;
        else if (!wcscmp(key,L"Antialiasing")) next.aa=first;
        else if (!wcscmp(key,L"Anisotropy")) next.af=first;
        else if (!wcscmp(key,L"TextureQuality")) next.texture=first;
        else if (!wcscmp(key,L"LightmapQuality")) next.lightmap=first;
        else if (!wcscmp(key,L"SoundRate")) { next.rate=first; sound=1; }
        else if (!wcscmp(key,L"Memory")) { next.memory=first; sound=1; }
        else { reject("unknown configuration setting"); return -1; }
    }
    while (*tail == L' ' || *tail == L'\t') ++tail;
    if (*tail) { reject("unexpected trailing command input"); return -1; }
    if (!valid(&next)) { reject("configuration value outside supported bounds"); return -1; }
    if(!wcscmp(key,L"Resolution")) {
        int rate=highest_refresh(next.width,next.height);
        if(!rate) {reject("resolution is not an enumerated adapter mode");return -1;}
        next.refresh=rate;
    }
    if(!wcscmp(key,L"RefreshRate") && next.refresh) {
        unsigned i;int found=0;
        for(i=0;i<display_mode_count;++i)if(display_modes[i].width==next.width &&
            display_modes[i].height==next.height && display_modes[i].refresh==next.refresh)found=1;
        if(!found) {reject("refresh rate is not supported at this resolution");return -1;}
    }
    if(!wcscmp(key,L"Antialiasing") && (!capabilities_available || !(supported_aa(&next)&(1U<<next.aa))))
        {reject("multisampling mode unavailable/unsupported");return -1;}
    if(!wcscmp(key,L"Anisotropy") && (!capabilities_available || next.af>(int)maximum_af))
        {reject("anisotropy level unavailable/unsupported");return -1;}
    if(!wcscmp(key,L"HDR")) {
        if(!capabilities_available)query_adapter();
        if(!capabilities_available) {reject("GPU capabilities unavailable");return -1;}
        next.aa=safe_aa(&next,next.aa);
    }
    if (!write_config(&next,sound)) return -1;
    current = next;auto_profile=selected_profile;
    last_error = "";
    return 1;
}
