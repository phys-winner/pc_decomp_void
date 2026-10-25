#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#include "asset_overrides.h"
static unsigned checks;
static void require(int value, const char *message) {
    ++checks;
    if (!value) { fprintf(stderr,"FAIL: %s\n",message); ExitProcess(90); }
}
static void match_file(HANDLE a, HANDLE b) {
    require(a!=INVALID_HANDLE_VALUE&&b!=INVALID_HANDLE_VALUE,"read handle is invalid");
    BY_HANDLE_FILE_INFORMATION x,y;
    require(GetFileInformationByHandle(a,&x)&&GetFileInformationByHandle(b,&y),"file identity query failed");
    require(x.dwVolumeSerialNumber==y.dwVolumeSerialNumber&&x.nFileIndexHigh==y.nFileIndexHigh&&
        x.nFileIndexLow==y.nFileIndexLow,"wrapper opened a different file");
    CloseHandle(a);CloseHandle(b);
}
static void write_settings(HANDLE file,LPCWSTR target,const char *xml) {
    require(file!=INVALID_HANDLE_VALUE,"settings write handle is invalid");
    HANDLE actual=CreateFileW(target,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE,NULL,OPEN_EXISTING,0,NULL);
    require(actual!=INVALID_HANDLE_VALUE,"private settings target unavailable");
    BY_HANDLE_FILE_INFORMATION x,y;
    require(GetFileInformationByHandle(file,&x)&&GetFileInformationByHandle(actual,&y),"settings write identity query failed");
    require(x.dwVolumeSerialNumber==y.dwVolumeSerialNumber&&x.nFileIndexHigh==y.nFileIndexHigh&&
        x.nFileIndexLow==y.nFileIndexLow,"settings write was not redirected to private target");
    CloseHandle(actual);
    DWORD written=0;
    require(WriteFile(file,xml,(DWORD)strlen(xml),&written,NULL)&&written==strlen(xml)&&FlushFileBuffers(file),
        "private settings write failed");
    CloseHandle(file);
}
int wmain(int argc,wchar_t **argv) {
    if(argc!=6||sizeof(void*)!=4)return 91;
    char hash[65];
    require(WideCharToMultiByte(CP_ACP,0,argv[3],-1,hash,sizeof hash,NULL,NULL)>0,"hash conversion failed");
    if(!wcscmp(argv[4],L"reject")) {
        require(!void_asset_overrides_init(argv[1],argv[2],hash,argv[5]),"invalid setup was accepted");
        printf("PASS rejected invalid immutable asset setup\n");return 0;
    }
    require(!wcscmp(argv[4],L"positive"),"unknown probe mode");
    require(void_asset_overrides_init(argv[1],argv[2],hash,argv[5]),"valid setup failed");
    wchar_t original[MAX_PATH],target[MAX_PATH],other[MAX_PATH],payload[MAX_PATH],variant[MAX_PATH];
    swprintf(original,MAX_PATH,L"%ls\\fsystems.xml",argv[1]);
    swprintf(target,MAX_PATH,L"%ls\\fsystems.xml",argv[2]);
    swprintf(other,MAX_PATH,L"%ls\\settings.xml",argv[1]);
    swprintf(payload,MAX_PATH,L"%ls\\Scripts\\ui\\main_menu.bin",argv[2]);
    wcscpy(variant,original);
    for(wchar_t *p=variant;*p;++p)if(*p==L'\\')*p=L'/';else if(*p>=L'a'&&*p<=L'z')*p-=L'a'-L'A';
    match_file(void_asset_create_file_w(variant,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL),
        CreateFileW(target,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL));
    char narrow[MAX_PATH];
    require(WideCharToMultiByte(CP_ACP,0,original,-1,narrow,sizeof narrow,NULL,NULL)>0,"ANSI source conversion failed");
    match_file(void_asset_create_file_a(narrow,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL),
        CreateFileW(target,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL));
    require(void_asset_get_file_attributes_w(variant)==GetFileAttributesW(target),"W attributes were not redirected");
    require(void_asset_get_file_attributes_a(narrow)==GetFileAttributesW(target),"A attributes were not redirected");
    require(void_asset_create_file_w(original,GENERIC_WRITE,0,NULL,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,NULL)==INVALID_HANDLE_VALUE&&
        GetLastError()==ERROR_ACCESS_DENIED,"W write open was not denied");
    require(void_asset_create_file_a(narrow,GENERIC_READ,0,NULL,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,NULL)==INVALID_HANDLE_VALUE&&
        GetLastError()==ERROR_ACCESS_DENIED,"A truncate open was not denied");
    require(void_asset_create_file_w(original,GENERIC_READ,0,NULL,OPEN_EXISTING,FILE_FLAG_DELETE_ON_CLOSE,NULL)==INVALID_HANDLE_VALUE&&
        GetLastError()==ERROR_ACCESS_DENIED,"delete-on-close was not denied");
    require(void_asset_create_file_w(original,FILE_WRITE_ATTRIBUTES,0,NULL,OPEN_EXISTING,0,NULL)==INVALID_HANDLE_VALUE&&
        GetLastError()==ERROR_ACCESS_DENIED,"attribute write open was not denied");
    require(void_asset_create_file_w(payload,GENERIC_WRITE,0,NULL,CREATE_ALWAYS,0,NULL)==INVALID_HANDLE_VALUE&&
        GetLastError()==ERROR_ACCESS_DENIED,"private script write was not denied");
    wchar_t extra[MAX_PATH];swprintf(extra,MAX_PATH,L"%ls\\Scripts\\ui\\unmodified.bin",argv[2]);
    require(void_asset_create_file_w(extra,GENERIC_WRITE,0,NULL,CREATE_NEW,0,NULL)==INVALID_HANDLE_VALUE&&
        GetLastError()==ERROR_ACCESS_DENIED,"creating an unmodified private script was not denied");
    require(void_asset_create_file_w(target,GENERIC_WRITE,0,NULL,CREATE_ALWAYS,0,NULL)==INVALID_HANDLE_VALUE&&
        GetLastError()==ERROR_ACCESS_DENIED,"private mount XML write was not denied");
    wchar_t config_original[MAX_PATH],config_target[MAX_PATH];char config_narrow[MAX_PATH];
    swprintf(config_original,MAX_PATH,L"%ls\\config.xml",argv[1]);
    swprintf(config_target,MAX_PATH,L"%ls\\config.xml",argv[2]);
    require(WideCharToMultiByte(CP_ACP,0,config_original,-1,config_narrow,sizeof config_narrow,NULL,NULL)>0,"ANSI config conversion failed");
    match_file(void_asset_create_file_w(config_original,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL),
        CreateFileW(config_target,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL));
    match_file(void_asset_create_file_a(config_narrow,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL),
        CreateFileW(config_target,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL));
    require(void_asset_get_file_attributes_w(config_original)==GetFileAttributesW(config_target),"window config W attrs differ");
    require(void_asset_get_file_attributes_a(config_narrow)==GetFileAttributesW(config_target),"window config A attrs differ");
    require(void_asset_create_file_w(config_original,GENERIC_WRITE,0,NULL,CREATE_ALWAYS,0,NULL)==INVALID_HANDLE_VALUE&&
        GetLastError()==ERROR_ACCESS_DENIED,"original config W write was not denied");
    require(void_asset_create_file_a(config_narrow,GENERIC_WRITE,0,NULL,CREATE_ALWAYS,0,NULL)==INVALID_HANDLE_VALUE&&
        GetLastError()==ERROR_ACCESS_DENIED,"original config A write was not denied");
    require(void_asset_create_file_w(config_target,GENERIC_WRITE,0,NULL,CREATE_ALWAYS,0,NULL)==INVALID_HANDLE_VALUE&&
        GetLastError()==ERROR_ACCESS_DENIED,"private window config write was not denied");
    wchar_t settings[MAX_PATH],settings_variant[MAX_PATH];
    swprintf(settings,MAX_PATH,L"%ls\\Ice-pick Lodge\\Void\\settings.xml",argv[5]);
    wcscpy(settings_variant,other);
    for(wchar_t *p=settings_variant;*p;++p)if(*p==L'\\')*p=L'/';else if(*p>=L'a'&&*p<=L'z')*p-=L'a'-L'A';
    match_file(void_asset_create_file_w(settings_variant,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL),
        CreateFileW(settings,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL));
    char settings_narrow[MAX_PATH];
    require(WideCharToMultiByte(CP_ACP,0,other,-1,settings_narrow,sizeof settings_narrow,NULL,NULL)>0,"ANSI settings conversion failed");
    match_file(void_asset_create_file_a(settings_narrow,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL),
        CreateFileW(settings,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL));
    require(void_asset_get_file_attributes_w(settings_variant)==GetFileAttributesW(settings),"settings W attributes differ from target");
    require(void_asset_get_file_attributes_a(settings_narrow)==GetFileAttributesW(settings),"settings A attributes differ from target");
    require((GetFileAttributesW(other)&FILE_ATTRIBUTE_READONLY)&&
        !(void_asset_get_file_attributes_w(other)&FILE_ATTRIBUTE_READONLY),"original readonly attribute leaked into private storage");
    const char *w_xml="<Settings><prop name=\"DebugInterface\" value=\"1\" /></Settings>\n";
    write_settings(void_asset_create_file_w(other,GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_WRITE,NULL,
        CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,NULL),settings,w_xml);
    const char *a_xml="<Settings><prop name=\"DebugInterface\" value=\"0\" /><prop name=\"PortWidth\" value=\"1024\" /></Settings>\n";
    write_settings(void_asset_create_file_a(settings_narrow,GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_WRITE,NULL,
        CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,NULL),settings,a_xml);
    HANDLE reread=void_asset_create_file_w(other,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,0,NULL);
    char bytes[256];DWORD read=0;
    require(reread!=INVALID_HANDLE_VALUE&&ReadFile(reread,bytes,sizeof bytes,&read,NULL),"saved settings reread failed");
    require(read==strlen(a_xml)&&!memcmp(bytes,a_xml,read),"saved settings alias did not retain actual written XML");
    CloseHandle(reread);
    swprintf(other,MAX_PATH,L"%ls\\unmodified.bin",argv[1]);
    SetLastError(0x12345678);DWORD expected=GetFileAttributesW(other),expected_error=GetLastError();
    SetLastError(0x12345678);DWORD actual=void_asset_get_file_attributes_w(other),actual_error=GetLastError();
    require(actual==expected&&actual_error==expected_error,"unmodified attributes or LastError changed");
    swprintf(other,MAX_PATH,L"%ls\\fsystems.xml.unmodified",argv[1]);
    SetLastError(0xABCDEF12);expected=GetFileAttributesW(other);expected_error=GetLastError();
    SetLastError(0xABCDEF12);actual=void_asset_get_file_attributes_w(other);actual_error=GetLastError();
    require(actual==expected&&actual_error==expected_error,"prefix-only path unexpectedly redirected");
    require(void_asset_overrides_script_open_count()==0,"XML opening counted as script opening");
    match_file(void_asset_create_file_w(payload,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL),
        CreateFileW(payload,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL));
    require(void_asset_overrides_script_open_count()==1,"actual private payload open was not observed");
    printf("PASS %u checks: exact readonly mount and writable settings aliases A/W, real file identity, "
           "settings write/reread, unmodified forwarding/LastError, write denial and private script open count\n",checks);
    return 0;
}
