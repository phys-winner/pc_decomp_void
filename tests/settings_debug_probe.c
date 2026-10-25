#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include "../native/settings_debug.h"

static void print_snapshot(void) {
    const wchar_t *keys[16];int values[16];unsigned i,count;
    count=void_settings_debug_snapshot(keys,values,16);
    for(i=0;i<count;++i)printf("SNAPSHOT %ls %d\n",keys[i],values[i]);
}

int wmain(int argc, wchar_t **argv) {
    int i, initialized;
    wchar_t original_data[MAX_PATH];
    if (argc<2) return 64;
    if(!GetEnvironmentVariableW(L"VOID_ORIGINAL_DATA_ROOT",original_data,MAX_PATH) ||
        !void_settings_debug_set_data_directory(original_data)) {
        printf("DATA 0 %s\n",void_settings_debug_error());return 65;
    }
#ifdef VOID_SETTINGS_TEST
    {
        char description[512],value[64];
        unsigned vendor=4318,device=0x2882,af=8;
        const int modes[]={1280,1024,60,800,600,75,1024,768,75,800,600,60,
            1024,768,60,800,600,60,400,300,240};
        if(GetEnvironmentVariableA("VOID_TEST_ADAPTER",value,sizeof(value))) {
            if(GetEnvironmentVariableA("VOID_TEST_VENDOR",value,sizeof(value)))vendor=(unsigned)strtoul(value,NULL,0);
            if(GetEnvironmentVariableA("VOID_TEST_DEVICE",value,sizeof(value)))device=(unsigned)strtoul(value,NULL,0);
            if(GetEnvironmentVariableA("VOID_TEST_AF",value,sizeof(value)))af=(unsigned)strtoul(value,NULL,0);
            if(!GetEnvironmentVariableA("VOID_TEST_DESCRIPTION",description,sizeof(description)))
                strcpy_s(description,sizeof(description),"NVIDIA GeForce RTX 4060");
            void_settings_debug_test_adapter(vendor,device,description,modes,7,
                (1U<<1)|(1U<<2)|(1U<<4)|(1U<<8),1U<<2,af);
        }
    }
#endif
    initialized = void_settings_debug_init(argv[1]);
    printf("INIT %d %s\n",initialized,void_settings_debug_error());
    print_snapshot();
    for (i=2;i<argc;++i) {
        int result = void_settings_debug_command(argv[i]);
        printf("COMMAND %d %s\n",result,void_settings_debug_error());
        print_snapshot();
    }
    return 0;
}
