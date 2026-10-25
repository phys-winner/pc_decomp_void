"""Observe and exercise only the explicitly selected workspace x86 host window."""
import argparse
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import time
from PIL import Image

PROJECT = Path(__file__).resolve().parent.parent
EXPECTED_HOST = os.path.normcase(str(PROJECT / "build" / "x86" / "void-x86.exe"))

user = c.WinDLL("user32", use_last_error=True)
gdi = c.WinDLL("gdi32", use_last_error=True)
kernel = c.WinDLL("kernel32", use_last_error=True)
callback = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
user.EnumWindows.argtypes = [callback, w.LPARAM]
user.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
user.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
user.IsWindowVisible.argtypes = [w.HWND]
user.IsIconic.argtypes = [w.HWND]
user.GetClientRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
user.ClientToScreen.argtypes = [w.HWND, c.POINTER(w.POINT)]
user.GetForegroundWindow.restype = w.HWND
user.GetWindowLongW.argtypes = [w.HWND, c.c_int]
user.GetWindowLongW.restype = w.LONG
user.SetCursorPos.argtypes = [c.c_int, c.c_int]
user.GetDC.argtypes = [w.HWND]
user.GetDC.restype = w.HDC
user.ReleaseDC.argtypes = [w.HWND, w.HDC]
kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
kernel.OpenProcess.restype = w.HANDLE
kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)]
kernel.CloseHandle.argtypes = [w.HANDLE]
gdi.CreateCompatibleDC.argtypes = [w.HDC]
gdi.CreateCompatibleDC.restype = w.HDC
gdi.CreateCompatibleBitmap.argtypes = [w.HDC, c.c_int, c.c_int]
gdi.CreateCompatibleBitmap.restype = w.HBITMAP
gdi.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
gdi.SelectObject.restype = w.HGDIOBJ
gdi.BitBlt.argtypes = [w.HDC, c.c_int, c.c_int, c.c_int, c.c_int, w.HDC, c.c_int, c.c_int, w.DWORD]
gdi.DeleteObject.argtypes = [w.HGDIOBJ]
gdi.DeleteDC.argtypes = [w.HDC]


class BitmapInfo(c.Structure):
    _fields_ = [("size", w.DWORD), ("width", w.LONG), ("height", w.LONG),
                ("planes", w.WORD), ("bits", w.WORD), ("compression", w.DWORD),
                ("image_size", w.DWORD), ("xppm", w.LONG), ("yppm", w.LONG),
                ("colors_used", w.DWORD), ("colors_important", w.DWORD)]


gdi.GetDIBits.argtypes = [w.HDC, w.HBITMAP, w.UINT, w.UINT, c.c_void_p, c.POINTER(BitmapInfo), w.UINT]


class MouseInput(c.Structure):
    _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("data", w.DWORD),
                ("flags", w.DWORD), ("time", w.DWORD), ("extra", c.c_size_t)]


class KeyboardInput(c.Structure):
    _fields_ = [("vk", w.WORD), ("scan", w.WORD), ("flags", w.DWORD),
                ("time", w.DWORD), ("extra", c.c_size_t)]


class InputUnion(c.Union):
    _fields_ = [("mouse", MouseInput), ("keyboard", KeyboardInput)]


class Input(c.Structure):
    _fields_ = [("kind", w.DWORD), ("value", InputUnion)]


user.SendInput.argtypes = [w.UINT, c.POINTER(Input), c.c_int]
user.SendInput.restype = w.UINT
assert c.sizeof(BitmapInfo) == 40
assert c.sizeof(Input) == (40 if c.sizeof(c.c_void_p) == 8 else 28)


def check(result, operation):
    if not result:
        raise OSError(c.get_last_error(), operation)
    return result


def process_path(pid):
    handle = check(kernel.OpenProcess(0x1000, False, pid), "OpenProcess")
    try:
        text = c.create_unicode_buffer(32768)
        size = w.DWORD(len(text))
        check(kernel.QueryFullProcessImageNameW(handle, 0, text, c.byref(size)), "QueryFullProcessImageNameW")
        return os.path.normcase(os.path.abspath(text.value))
    finally:
        kernel.CloseHandle(handle)


def target(pid, foreground=True):
    if process_path(pid) != EXPECTED_HOST:
        raise RuntimeError("Target PID is not the workspace x86 host")
    windows = []

    @callback
    def collect(hwnd, _):
        owner = w.DWORD()
        user.GetWindowThreadProcessId(hwnd, c.byref(owner))
        title = c.create_unicode_buffer(512)
        user.GetWindowTextW(hwnd, title, len(title))
        if owner.value == pid and title.value == "The Void" and user.IsWindowVisible(hwnd):
            windows.append(hwnd)
        return True

    user.EnumWindows(collect, 0)
    if len(windows) != 1:
        raise RuntimeError("Expected exactly one visible, restored The Void host window")
    hwnd = windows[0]
    if user.IsIconic(hwnd):
        raise RuntimeError("Own game window is minimized; select it manually before capture/input")
    if foreground and user.GetForegroundWindow() != hwnd:
        raise RuntimeError("Own game window must be foreground before capture/input")
    rect = w.RECT()
    origin = w.POINT(0, 0)
    check(user.GetClientRect(hwnd, c.byref(rect)), "GetClientRect")
    check(user.ClientToScreen(hwnd, c.byref(origin)), "ClientToScreen")
    width, height = rect.right, rect.bottom
    if width < 1 or height < 1 or width * height > 100_000_000:
        raise RuntimeError("Invalid game client bounds")
    return hwnd, origin.x, origin.y, width, height


def capture(pid, path):
    hwnd, x, y, width, height = target(pid)
    desktop = check(user.GetDC(None), "GetDC")
    memory = check(gdi.CreateCompatibleDC(desktop), "CreateCompatibleDC")
    bitmap = check(gdi.CreateCompatibleBitmap(desktop, width, height), "CreateCompatibleBitmap")
    old = gdi.SelectObject(memory, bitmap)
    try:
        check(gdi.BitBlt(memory, 0, 0, width, height, desktop, x, y, 0x00CC0020), "BitBlt")
        if target(pid) != (hwnd, x, y, width, height):
            raise RuntimeError("Game target changed during capture")
        info = BitmapInfo(size=40, width=width, height=-height, planes=1, bits=32)
        pixels = c.create_string_buffer(width * height * 4)
        gdi.SelectObject(memory, old)
        check(gdi.GetDIBits(memory, bitmap, 0, height, pixels, c.byref(info), 0), "GetDIBits")
        image = Image.frombytes("RGB", (width, height), pixels.raw, "raw", "BGRX")
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        result = dict(pid=pid, executable=EXPECTED_HOST, hwnd=hwnd, title="The Void", client_origin=[x, y], size=[width, height], capture="own foreground client pixels", path=str(path))
        path.with_suffix(".json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result))
    finally:
        gdi.SelectObject(memory, old)
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(memory)
        user.ReleaseDC(None, desktop)


def send(event):
    check(user.SendInput(1, c.byref(event), c.sizeof(event)), "SendInput")


KEY_SCANS = {"ESC": 0x01, "ENTER": 0x1c, "SPACE": 0x39, "W": 0x11,
             "A": 0x1e, "S": 0x1f, "D": 0x20, "LCTRL": 0x1d,
             "B": 0x30, "J": 0x24, "LSHIFT": 0x2a, "F5": 0x3f, "F8": 0x42}


def draw(pid, points, duration):
    hwnd, x, y, width, height = target(pid)
    if (not isinstance(points, list) or not 2 <= len(points) <= 200 or
            not 0 <= duration <= 0.1 or len(points) * duration > 5 or
            any(not isinstance(p, list) or len(p) != 2 or
                any(type(v) is not int for v in p) or
                not (0 <= p[0] < width and 0 <= p[1] < height) for p in points)):
        raise ValueError("drawing requires 2..200 integer client points and at most five seconds")
    ctrl = Input(kind=1, value=InputUnion(keyboard=KeyboardInput(scan=0x1d, flags=0x0008)))
    ctrl_up = Input(kind=1, value=InputUnion(keyboard=KeyboardInput(scan=0x1d, flags=0x000a)))
    down = Input(kind=0, value=InputUnion(mouse=MouseInput(flags=0x0002)))
    up = Input(kind=0, value=InputUnion(mouse=MouseInput(flags=0x0004)))
    try:
        send(ctrl)
        time.sleep(0.4)
        if target(pid) != (hwnd, x, y, width, height):
            raise RuntimeError("Game target changed before drawing")
        check(user.SetCursorPos(x + points[0][0], y + points[0][1]), "SetCursorPos")
        send(down)
        for px, py in points:
            if target(pid) != (hwnd, x, y, width, height):
                raise RuntimeError("Game target changed during drawing")
            check(user.SetCursorPos(x + px, y + py), "SetCursorPos")
            time.sleep(duration)
    finally:
        # The game applies the glyph when the left button is released before Ctrl.
        try:
            send(up)
        finally:
            send(ctrl_up)


def main():
    global EXPECTED_HOST
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inspect", "capture", "move", "look", "click", "key", "draw"])
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--executable", type=Path, default=Path(EXPECTED_HOST))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--x", type=int)
    parser.add_argument("--y", type=int)
    parser.add_argument("--button", choices=["left", "right"], default="left")
    parser.add_argument("--key", choices=sorted(KEY_SCANS))
    parser.add_argument("--points", type=Path, help="JSON list of observed client-coordinate drawing points")
    parser.add_argument("--duration", type=float)
    args = parser.parse_args()
    if args.duration is None:
        args.duration = 0.02 if args.action == "draw" else 0.15
    EXPECTED_HOST = os.path.normcase(str(args.executable.resolve()))
    allowed = {os.path.normcase(str(PROJECT / "build" / "x86" / name))
               for name in ("void-x86.exe", "void-x86-gamemodule.exe", "void-x86-engine.exe", "void-x86-filesystems.exe", "void-x86-sound.exe", "void-x86-sound-fast.exe", "void-x86-media.exe", "void-x86-filesystems-fast.exe", "void-x86-renderer.exe", "void-x86-nxcharacter.exe")}
    if EXPECTED_HOST not in allowed:
        parser.error("executable must be exactly one of the task-owned x86 stage paths")
    user.SetProcessDPIAware()
    if not 0 <= args.duration <= 5:
        parser.error("duration must be between 0 and 5 seconds")
    if args.action == "inspect":
        hwnd, x, y, width, height = target(args.pid, foreground=False)
        result = dict(pid=args.pid, executable=EXPECTED_HOST, hwnd=hwnd, title="The Void",
            client_origin=[x, y], size=[width, height], foreground=user.GetForegroundWindow(),
            owns_foreground=user.GetForegroundWindow() == hwnd,
            style=f"{user.GetWindowLongW(hwnd, -16) & 0xffffffff:08X}",
            extended_style=f"{user.GetWindowLongW(hwnd, -20) & 0xffffffff:08X}",
            activation_requested=False)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result))
    elif args.action == "capture":
        if args.output is None:
            parser.error("capture requires --output")
        capture(args.pid, args.output.resolve())
    elif args.action == "draw":
        if args.points is None:
            parser.error("draw requires --points")
        draw(args.pid, json.loads(args.points.read_text()), args.duration)
        print("Sent own game drawing gesture; recognition must be verified in game")
    elif args.action == "look":
        _, _, _, width, height = target(args.pid)
        if args.x is None or args.y is None or abs(args.x) > width or abs(args.y) > height:
            parser.error("relative look delta must be within one client width/height")
        send(Input(kind=0, value=InputUnion(mouse=MouseInput(dx=args.x, dy=args.y, flags=0x0001))))
        time.sleep(args.duration)
        print(f"Sent own game relative look ({args.x}, {args.y})")
    elif args.action in ("move", "click"):
        _, x, y, width, height = target(args.pid)
        if args.x is None or args.y is None or not (0 <= args.x < width and 0 <= args.y < height):
            parser.error("click coordinates must be inside observed game client")
        check(user.SetCursorPos(x + args.x, y + args.y), "SetCursorPos")
        target(args.pid)
        if args.action == "move":
            time.sleep(args.duration)
            target(args.pid)
            print(f"Hovered observed own game client ({args.x}, {args.y})")
            return
        try:
            send(Input(kind=0, value=InputUnion(mouse=MouseInput(flags=0x0002 if args.button == "left" else 0x0008))))
            time.sleep(args.duration)
        finally:
            send(Input(kind=0, value=InputUnion(mouse=MouseInput(flags=0x0004 if args.button == "left" else 0x0010))))
        print(f"Clicked {args.button} button on observed own game client ({args.x}, {args.y})")
    else:
        if args.key is None:
            parser.error("key action requires --key")
        target(args.pid)
        scan = KEY_SCANS[args.key]
        try:
            send(Input(kind=1, value=InputUnion(keyboard=KeyboardInput(scan=scan, flags=0x0008))))
            deadline = time.monotonic() + args.duration
            while time.monotonic() < deadline:
                target(args.pid)
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            if args.output is not None:
                capture(args.pid, args.output.resolve())
        finally:
            send(Input(kind=1, value=InputUnion(keyboard=KeyboardInput(scan=scan, flags=0x000a))))
        print(f"Pressed own game key {args.key} for {args.duration}s")


if __name__ == "__main__":
    main()
