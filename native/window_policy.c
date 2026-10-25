/* Profile-owned windows remain click-activatable, but never activate themselves. */
#define WIN32_LEAN_AND_MEAN
#include "window_policy.h"
#pragma comment(lib, "user32.lib")

static int applies(HWND window,int enabled)
{
    if (!enabled) return 0;
    DWORD previous=GetLastError(),owner=0;
    GetWindowThreadProcessId(window,&owner);
    SetLastError(previous);
    return owner==GetCurrentProcessId();
}

BOOL void_window_position(HWND window,HWND after,int x,int y,int width,int height,
                          UINT flags,int enabled)
{
    if (applies(window,enabled)) flags|=SWP_NOACTIVATE;
    return SetWindowPos(window,after,x,y,width,height,flags);
}

BOOL void_window_show(HWND window,int command,int enabled)
{
    if (!applies(window,enabled)) return ShowWindow(window,command);
    BOOL visible=IsWindowVisible(window);
    UINT flags=SWP_NOMOVE|SWP_NOSIZE|SWP_NOZORDER|SWP_NOACTIVATE;
    switch (command) {
    case SW_HIDE:
        SetWindowPos(window,NULL,0,0,0,0,flags|SWP_HIDEWINDOW); break;
    case SW_SHOW:
    case SW_SHOWNA:
        SetWindowPos(window,NULL,0,0,0,0,flags|SWP_SHOWWINDOW); break;
    case SW_SHOWNORMAL:
    case SW_SHOWNOACTIVATE:
    case SW_RESTORE:
    case SW_SHOWDEFAULT:
        if (IsIconic(window)||IsZoomed(window)) ShowWindowAsync(window,SW_SHOWNOACTIVATE);
        else SetWindowPos(window,NULL,0,0,0,0,flags|SWP_SHOWWINDOW);
        break;
    case SW_SHOWMINIMIZED:
    case SW_SHOWMINNOACTIVE:
    case SW_MINIMIZE:
    case SW_FORCEMINIMIZE:
        ShowWindowAsync(window,SW_SHOWMINNOACTIVE); break;
    default:
        /* shortcut: Game.exe uses only SW_SHOW; add non-activating maximize if a real caller needs SW_SHOWMAXIMIZED. */
        SetLastError(ERROR_NOT_SUPPORTED); break;
    }
    return visible;
}
