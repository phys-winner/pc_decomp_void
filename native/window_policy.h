#ifndef VOID_WINDOW_POLICY_H
#define VOID_WINDOW_POLICY_H
#include <windows.h>
#ifdef __cplusplus
extern "C" {
#endif
BOOL void_window_show(HWND window, int command, int enabled);
BOOL void_window_position(HWND window, HWND after, int x, int y, int width, int height,
                          UINT flags, int enabled);
#ifdef __cplusplus
}
#endif
#endif
