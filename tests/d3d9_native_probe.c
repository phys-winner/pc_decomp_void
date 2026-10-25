/* Native D3D9 calibration, isolated from game DLLs and settings. */
#define WIN32_LEAN_AND_MEAN
#define COBJMACROS
#include <windows.h>
#include <d3d9.h>
#include <wtsapi32.h>
#include <stdint.h>
#include <stdio.h>

static unsigned messages;
static LRESULT CALLBACK probe_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    messages++;
    return DefWindowProcW(window, message, wparam, lparam);
}

static void pump(void) {
    MSG message;
    while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE)) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
}

static void module(const char *name) {
    HMODULE handle = GetModuleHandleA(name);
    char path[MAX_PATH] = {0}, resolved[MAX_PATH] = {0};
    if (handle) GetModuleFileNameA(handle,path,MAX_PATH);
    printf("module %s base=%08lX path=%s\n",name,(unsigned long)(uintptr_t)handle,handle?path:"ABSENT");
    if (handle) {
        HANDLE file = CreateFileA(path,FILE_READ_ATTRIBUTES,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,
            NULL,OPEN_EXISTING,0,NULL);
        if (file!=INVALID_HANDLE_VALUE) {
            DWORD count = GetFinalPathNameByHandleA(file,resolved,MAX_PATH,FILE_NAME_NORMALIZED);
            if (count && count<MAX_PATH) printf("resolved %s path=%s\n",name,resolved);
            CloseHandle(file);
        }
    }
}

static void parameters(const char *label, unsigned case_id, const D3DPRESENT_PARAMETERS *p) {
    printf("parameters %s %u width=%u height=%u format=%u count=%u multisample=%u quality=%lu swap=%u window=%08lX windowed=%d auto_depth=%d depth_format=%u flags=%lu refresh=%u interval=%08lX\n",
        label,case_id,p->BackBufferWidth,p->BackBufferHeight,p->BackBufferFormat,p->BackBufferCount,
        p->MultiSampleType,p->MultiSampleQuality,p->SwapEffect,(unsigned long)(uintptr_t)p->hDeviceWindow,
        p->Windowed,p->EnableAutoDepthStencil,p->AutoDepthStencilFormat,p->Flags,
        p->FullScreen_RefreshRateInHz,p->PresentationInterval);
}

static void support(IDirect3D9 *d3d, BOOL windowed) {
    DWORD quality = 0;
    HRESULT multisample=IDirect3D9_CheckDeviceMultiSampleType(d3d,0,D3DDEVTYPE_HAL,D3DFMT_X8R8G8B8,
        windowed,D3DMULTISAMPLE_NONE,&quality);
    printf("support windowed=%d device_type=%08lX depth_format=%08lX depth_match=%08lX multisample=%08lX quality=%lu\n",
        windowed,(unsigned long)IDirect3D9_CheckDeviceType(d3d,0,D3DDEVTYPE_HAL,D3DFMT_X8R8G8B8,D3DFMT_X8R8G8B8,windowed),
        (unsigned long)IDirect3D9_CheckDeviceFormat(d3d,0,D3DDEVTYPE_HAL,D3DFMT_X8R8G8B8,D3DUSAGE_DEPTHSTENCIL,D3DRTYPE_SURFACE,D3DFMT_D24S8),
        (unsigned long)IDirect3D9_CheckDepthStencilMatch(d3d,0,D3DDEVTYPE_HAL,D3DFMT_X8R8G8B8,D3DFMT_X8R8G8B8,D3DFMT_D24S8),
        (unsigned long)multisample,
        quality);
}

int main(void) {
    const wchar_t *class_name = L"TheVoidNativeD3D9Calibration";
    HINSTANCE instance = GetModuleHandleW(NULL);
    WNDCLASSEXW window_class = {0};
    window_class.cbSize = sizeof(window_class);
    window_class.style = CS_OWNDC;
    window_class.lpfnWndProc = probe_proc;
    window_class.hInstance = instance;
    window_class.hCursor = LoadCursorW(NULL,MAKEINTRESOURCEW(32512));
    window_class.lpszClassName = class_name;
    ATOM atom = RegisterClassExW(&window_class);
    printf("identity pid=%lu thread=%lu bits=%u instance=%08lX class_atom=%u present_parameters_size=%u\n",
        GetCurrentProcessId(),GetCurrentThreadId(),(unsigned)(sizeof(void*)*8),
        (unsigned long)(uintptr_t)instance,atom,(unsigned)sizeof(D3DPRESENT_PARAMETERS));
    if (!atom || sizeof(void*)!=4 || sizeof(D3DPRESENT_PARAMETERS)!=56) return 2;
    DWORD session = 0;
    ProcessIdToSessionId(GetCurrentProcessId(),&session);
    char desktop_name[128] = {0}, station_name[128] = {0};
    DWORD needed = 0;
    GetUserObjectInformationA(GetThreadDesktop(GetCurrentThreadId()),UOI_NAME,desktop_name,sizeof(desktop_name),&needed);
    GetUserObjectInformationA(GetProcessWindowStation(),UOI_NAME,station_name,sizeof(station_name),&needed);
    printf("environment session=%lu remote=%d desktop=%s station=%s\n",session,GetSystemMetrics(SM_REMOTESESSION),desktop_name,station_name);
    LPWSTR session_buffer=NULL;
    DWORD session_bytes=0;
    BOOL session_ok=WTSQuerySessionInformationW(WTS_CURRENT_SERVER_HANDLE,session,WTSSessionInfoEx,&session_buffer,&session_bytes);
    if (session_ok && session_bytes>=sizeof(WTSINFOEXW) && ((WTSINFOEXW*)session_buffer)->Level==1) {
        WTSINFOEX_LEVEL1_W *information=&((WTSINFOEXW*)session_buffer)->Data.WTSInfoExLevel1;
        printf("wts session=%lu state=%u flags=%08lX locked=%d\n",information->SessionId,
            information->SessionState,(unsigned long)information->SessionFlags,
            information->SessionFlags==WTS_SESSIONSTATE_LOCK);
    } else printf("wts query_failure error=%lu bytes=%lu\n",GetLastError(),session_bytes);
    if (session_buffer) WTSFreeMemory(session_buffer);
    IDirect3D9 *d3d = Direct3DCreate9(D3D_SDK_VERSION);
    if (!d3d) { puts("Direct3DCreate9=NULL"); UnregisterClassW(class_name,instance); return 3; }
    printf("interface this=%08lX vtable=%08lX caps_method=%08lX adapter_count=%u\n",
        (unsigned long)(uintptr_t)d3d,(unsigned long)(uintptr_t)d3d->lpVtbl,
        (unsigned long)(uintptr_t)d3d->lpVtbl->GetDeviceCaps,IDirect3D9_GetAdapterCount(d3d));
    D3DADAPTER_IDENTIFIER9 identifier = {0};
    D3DCAPS9 caps = {0};
    D3DDISPLAYMODE desktop = {0};
    HRESULT id_hr = IDirect3D9_GetAdapterIdentifier(d3d,0,0,&identifier);
    HRESULT caps_hr = IDirect3D9_GetDeviceCaps(d3d,0,D3DDEVTYPE_HAL,&caps);
    HRESULT mode_hr = IDirect3D9_GetAdapterDisplayMode(d3d,0,&desktop);
    printf("adapter identifier_hr=%08lX caps_hr=%08lX display_hr=%08lX vendor=%04lX device=%04lX devcaps=%08lX hw_tl=%d pure=%d vertex_shader=%08lX pixel_shader=%08lX\n",
        (unsigned long)id_hr,(unsigned long)caps_hr,(unsigned long)mode_hr,identifier.VendorId,identifier.DeviceId,
        caps.DevCaps,!!(caps.DevCaps&D3DDEVCAPS_HWTRANSFORMANDLIGHT),!!(caps.DevCaps&D3DDEVCAPS_PUREDEVICE),
        caps.VertexShaderVersion,caps.PixelShaderVersion);
    printf("driver=%s\ndescription=%s\n",identifier.Driver,identifier.Description);
    for (UINT adapter=0;adapter<IDirect3D9_GetAdapterCount(d3d);adapter++) {
        D3DADAPTER_IDENTIFIER9 item={0}; D3DCAPS9 item_caps={0};
        HRESULT item_id=IDirect3D9_GetAdapterIdentifier(d3d,adapter,0,&item);
        HRESULT item_hr=IDirect3D9_GetDeviceCaps(d3d,adapter,D3DDEVTYPE_HAL,&item_caps);
        printf("adapter_caps ordinal=%u id_hr=%08lX caps_hr=%08lX vendor=%04lX device=%04lX devcaps=%08lX monitor=%08lX\n",
            adapter,(unsigned long)item_id,(unsigned long)item_hr,item.VendorId,item.DeviceId,item_caps.DevCaps,
            (unsigned long)(uintptr_t)IDirect3D9_GetAdapterMonitor(d3d,adapter));
    }
    HDESK input_desktop=OpenInputDesktop(0,FALSE,DESKTOP_READOBJECTS);
    char input_name[128]={0};
    DWORD input_error=input_desktop?0:GetLastError();
    if (input_desktop) {
        GetUserObjectInformationA(input_desktop,UOI_NAME,input_name,sizeof(input_name),&needed);
        CloseDesktop(input_desktop);
    }
    printf("input_desktop opened=%d error=%lu name=%s foreground=%08lX\n",input_desktop!=NULL,input_error,
        input_desktop?input_name:"UNAVAILABLE",(unsigned long)(uintptr_t)GetForegroundWindow());
    printf("desktop before width=%u height=%u format=%u refresh=%u\n",desktop.Width,desktop.Height,desktop.Format,desktop.RefreshRate);
    UINT mode_count = IDirect3D9_GetAdapterModeCount(d3d,0,D3DFMT_X8R8G8B8);
    unsigned matching = 0;
    for (UINT index=0;index<mode_count;index++) {
        D3DDISPLAYMODE mode = {0};
        HRESULT hr = IDirect3D9_EnumAdapterModes(d3d,0,D3DFMT_X8R8G8B8,index,&mode);
        if (SUCCEEDED(hr) && mode.Width==800 && mode.Height==600) {
            matching++;
            printf("mode index=%u width=%u height=%u format=%u refresh=%u\n",index,mode.Width,mode.Height,mode.Format,mode.RefreshRate);
        }
    }
    printf("modes total=%u matching_800x600=%u\n",mode_count,matching);
    support(d3d,FALSE); support(d3d,TRUE);
    unsigned successes = 0, cleanups = 0;
    for (unsigned case_id=0;case_id<4;case_id++) {
        BOOL windowed = case_id>=2;
        DWORD behavior = D3DCREATE_HARDWARE_VERTEXPROCESSING | ((case_id%2)==0 ? D3DCREATE_PUREDEVICE : 0);
        DWORD style = windowed ? WS_OVERLAPPEDWINDOW : WS_POPUP;
        RECT rectangle = {0,0,800,600};
        AdjustWindowRect(&rectangle,style,FALSE);
        HWND window = CreateWindowExW(0,class_name,L"The Void native D3D9 calibration",style,
            100,100,rectangle.right-rectangle.left,rectangle.bottom-rectangle.top,NULL,NULL,instance,NULL);
        if (!window) { printf("window_create_failure case=%u error=%lu\n",case_id,GetLastError()); continue; }
        ShowWindow(window,SW_SHOW);
        UpdateWindow(window);
        HWND foreground = GetForegroundWindow();
        DWORD foreground_thread = GetWindowThreadProcessId(foreground,NULL);
        BOOL attached = foreground_thread && foreground_thread!=GetCurrentThreadId() &&
            AttachThreadInput(GetCurrentThreadId(),foreground_thread,TRUE);
        SetForegroundWindow(window); SetActiveWindow(window); SetFocus(window);
        if (attached) AttachThreadInput(GetCurrentThreadId(),foreground_thread,FALSE);
        pump();
        DWORD owner_pid = 0;
        DWORD owner_thread = GetWindowThreadProcessId(window,&owner_pid);
        printf("window case=%u hwnd=%08lX valid=%d owner_pid=%lu owner_thread=%lu class_instance=%08lX wndproc=%08lX foreground=%d behavior=%08lX\n",
            case_id,(unsigned long)(uintptr_t)window,IsWindow(window),owner_pid,owner_thread,
            (unsigned long)GetClassLongW(window,GCL_HMODULE),(unsigned long)GetWindowLongW(window,GWL_WNDPROC),
            GetForegroundWindow()==window,behavior);
        D3DPRESENT_PARAMETERS p = {0};
        p.BackBufferWidth=800; p.BackBufferHeight=600; p.BackBufferFormat=D3DFMT_X8R8G8B8;
        p.BackBufferCount=1; p.MultiSampleType=D3DMULTISAMPLE_NONE; p.MultiSampleQuality=0;
        p.SwapEffect=D3DSWAPEFFECT_DISCARD; p.hDeviceWindow=NULL; p.Windowed=windowed;
        p.EnableAutoDepthStencil=TRUE; p.AutoDepthStencilFormat=D3DFMT_D24S8;
        p.Flags=0; p.FullScreen_RefreshRateInHz=0; p.PresentationInterval=D3DPRESENT_INTERVAL_IMMEDIATE;
        parameters("before",case_id,&p);
        IDirect3DDevice9 *device = NULL;
        HRESULT create_hr = IDirect3D9_CreateDevice(d3d,0,D3DDEVTYPE_HAL,window,behavior,&p,&device);
        printf("result case=%u create_hr=%08lX device=%08lX\n",case_id,(unsigned long)create_hr,(unsigned long)(uintptr_t)device);
        parameters("after",case_id,&p);
        if (SUCCEEDED(create_hr) && device) {
            successes++;
            HRESULT clear_hr = IDirect3DDevice9_Clear(device,0,NULL,D3DCLEAR_TARGET|D3DCLEAR_ZBUFFER,0xFF203040,1.0f,0);
            HRESULT present_hr = IDirect3DDevice9_Present(device,NULL,NULL,NULL,NULL);
            printf("presentation case=%u clear_hr=%08lX present_hr=%08lX\n",case_id,(unsigned long)clear_hr,(unsigned long)present_hr);
            for (unsigned frame=0;frame<5;frame++) { pump(); Sleep(40); }
            IDirect3DDevice9_Release(device);
        }
        DestroyWindow(window); pump();
        BOOL destroyed = !IsWindow(window);
        cleanups += destroyed;
        printf("cleanup case=%u window_destroyed=%d\n",case_id,destroyed);
    }
    D3DDISPLAYMODE after = {0};
    IDirect3D9_GetAdapterDisplayMode(d3d,0,&after);
    printf("desktop after width=%u height=%u format=%u refresh=%u\n",after.Width,after.Height,after.Format,after.RefreshRate);
    module("d3d9.dll"); module("nvldumd.dll"); module("nvd3dum.dll"); module("nvgpucomp32.dll");
    IDirect3D9_Release(d3d);
    BOOL unregistered = UnregisterClassW(class_name,instance);
    printf("summary successes=%u cases=4 cleanups=%u class_unregistered=%d messages=%u desktop_restored=%d\n",
        successes,cleanups,unregistered,messages,!memcmp(&desktop,&after,sizeof(desktop)));
    return cleanups==4 && unregistered ? 0 : 4;
}
