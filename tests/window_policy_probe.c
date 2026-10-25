#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include "../native/window_policy.h"

static unsigned activations;
static LRESULT CALLBACK window_proc(HWND window,UINT message,WPARAM first,LPARAM second)
{
    if (message==WM_ACTIVATE && LOWORD(first)!=WA_INACTIVE) ++activations;
    return DefWindowProcW(window,message,first,second);
}

static int pump_state(HWND window,int iconic)
{
    DWORD deadline=GetTickCount()+1000;
    for (;;) {
        MSG message;
        while (PeekMessageW(&message,NULL,0,0,PM_REMOVE)) {
            TranslateMessage(&message); DispatchMessageW(&message);
        }
        if (!!IsIconic(window)==iconic) return 1;
        if ((LONG)(GetTickCount()-deadline)>=0) return 0;
        Sleep(1);
    }
}

int main(void)
{
    HWND foreground=GetForegroundWindow(); HINSTANCE instance=GetModuleHandleW(NULL);
    WNDCLASSW type={0}; type.lpfnWndProc=window_proc; type.hInstance=instance;
    type.lpszClassName=L"VoidWindowPolicyProbe";
    if (!RegisterClassW(&type)) return 1;
    HWND window=CreateWindowExW(0,type.lpszClassName,L"Void no-activation policy probe",
        WS_CAPTION|WS_SYSMENU,-32000,-32000,96,64,NULL,NULL,instance,NULL);
    int result=0;
    if (!window) { result=2; goto done; }
    if (GetForegroundWindow()!=foreground) { result=3; goto done; }
    if (void_window_show(window,SW_SHOW,1)||!IsWindowVisible(window)) { result=4; goto done; }
    if (GetForegroundWindow()!=foreground||GetActiveWindow()==window||activations) { result=5; goto done; }
    if (!void_window_show(window,SW_SHOW,1)) { result=6; goto done; }
    if (!void_window_position(window,NULL,-32000,-32000,112,80,SWP_NOZORDER,1)) { result=7; goto done; }
    if (GetForegroundWindow()!=foreground||GetActiveWindow()==window||activations) { result=8; goto done; }
    if ((GetWindowLongW(window,GWL_EXSTYLE)&WS_EX_NOACTIVATE)||
        SendMessageW(window,WM_MOUSEACTIVATE,(WPARAM)window,MAKELPARAM(HTCLIENT,WM_LBUTTONDOWN))!=MA_ACTIVATE) {
        result=9; goto done;
    }
    if (!void_window_show(window,SW_MINIMIZE,1)||!pump_state(window,1)) { result=10; goto done; }
    if (GetForegroundWindow()!=foreground||GetActiveWindow()==window||activations) { result=11; goto done; }
    if (!void_window_show(window,SW_RESTORE,1)||!pump_state(window,0)||!IsWindowVisible(window)) { result=12; goto done; }
    if (GetForegroundWindow()!=foreground||GetActiveWindow()==window||activations) { result=13; goto done; }
    SetLastError(0);
    if (!void_window_show(window,SW_SHOWMAXIMIZED,1)||GetLastError()!=ERROR_NOT_SUPPORTED||IsZoomed(window)) {
        result=19; goto done;
    }
    if (!void_window_show(window,SW_HIDE,1)||IsWindowVisible(window)) { result=14; goto done; }
    /* Disabled policy passes non-activating calls through to the original APIs. */
    if (void_window_show(window,SW_HIDE,0)) { result=15; goto done; }
    if (!void_window_position(window,NULL,-32000,-32000,512,256,SWP_NOZORDER|SWP_NOACTIVATE,0)) { result=16; goto done; }
    RECT rectangle; GetWindowRect(window,&rectangle);
    if (rectangle.right-rectangle.left!=512||rectangle.bottom-rectangle.top!=256) { result=17; goto done; }
    if (GetForegroundWindow()!=foreground||activations) { result=18; goto done; }
    puts("PASS initialSW_SHOW/STARTUPINFO, position, minimize/restore, previousvisibility, disabledAPI, explicit unsupported maximize, click-activation allowed; foreground unchanged");
done:
    if (window) DestroyWindow(window);
    UnregisterClassW(type.lpszClassName,instance);
    if (result) printf("FAILED code=%d activations=%u foreground_changed=%d\n",result,activations,GetForegroundWindow()!=foreground);
    return result;
}
