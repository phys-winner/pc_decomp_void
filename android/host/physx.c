/* PhysX 2.8.1 host side.
 *
 * PhysXLoader.dll (system software 9.09.0428) only locates the engine DLLs and
 * forwards; its forwarding is reproduced here (cdecl, as NX_CALL_CONV):
 *   NxCreatePhysicsSDK -> PhysXCore!NpCreatePhysicsSDK
 *   NxGetUtilLib       -> PhysXCore!NpGetUtilLib
 *   NxGetCookingLib    -> PhysXCooking!NxGetCookingInterface
 * PhysXCore and PhysXCooking themselves are lifted guest modules. Their GPU
 * (cudart), hardware PPU (setupapi) and remote debugger (sockets) paths are
 * answered as "no such device / network down". */
#include "host.h"
#include <math.h>
#include <string.h>

#define LOADER "physxloader.dll"

static uint32_t core_module, cooking_module;
static uint32_t physics_sdk, util_lib;

static uint32_t module_export(uint32_t module, const char *name)
{
    uint32_t s = void_gstrdup(name);
    uint32_t va = void_module_proc(module, s);
    void_gfree(s);
    return va;
}

static uint32_t core(void)
{
    if (!core_module) core_module = void_module_load("PhysXCore.dll");
    return core_module;
}

/* The physics' fixed step at the display's rate. Engine's scenes simulate
 * in fixed steps of 1/60 s (physics::CScene: setTiming(1/60, 8, FIXED),
 * the float at Engine+0x12a25c), what a 60 Hz screen shows; at 120 frames
 * a second every other frame had no step and the world moved in jerks
 * (measured on the Pixel 10a: the camera still in one frame of six while
 * walking, none with a step of 1/120). A step of one refresh of the screen
 * the game is drawn on: one step a frame at its full rate, two at half. */
static float display_hz = 60.0f;

void void_physics_set_display_rate(float hz)
{
    if (hz >= 30.0f && hz <= 240.0f) display_hz = hz;
}

static void physics_step_for_display(void)
{
    uint32_t engine = void_module_handle("Engine.dll");
    if (!engine) return;
    uint32_t va = engine + 0x12a25cu, old = 0;
    float was;
    memcpy(&was, GPTR(va), 4);
    if (fabsf(was - 1.0f / 60.0f) > 1e-6f) {
        void_log("[physx] Engine's step is %g, not 1/60: left as it is", was);
        return;
    }
    float hz = display_hz < 60.0f ? 60.0f : display_hz > 144.0f ? 144.0f : display_hz;
    if (hz < 61.0f || !void_vm_protect(va & ~0xFFFu, 0x1000, 0x04, &old)) return;
    float step = 1.0f / hz;
    memcpy(GPTR(va), &step, 4);
    void_vm_protect(va & ~0xFFFu, 0x1000, old, &old);
    void_log("[physx] the scenes' fixed step 1/%.0f s for a %.0f Hz display", hz, display_hz);
}

/* NxCreatePhysicsSDK(sdkVersion, allocator, outputStream, desc, errorCode) */
CDECL_EXPORT(LOADER, NxCreatePhysicsSDK)
{
    physics_step_for_display();
    uint32_t version = ARG(0), allocator = ARG(1), output = ARG(2), desc = ARG(3), error_out = ARG(4);
    void_log("[physx] NxCreatePhysicsSDK(version %08X, allocator %08X, output %08X, desc %08X)", version, allocator, output, desc);
    if (version > 0x2060100u && error_out) MEM32(error_out) = 1;
    uint32_t module = core();
    if (!module) return 0;
    uint32_t create = module_export(module, "NpCreatePhysicsSDK");
    if (!create) return 0;
    uint32_t err = void_galloc(4);
    MEM32(err) = version;
    uint32_t args[5] = { version, allocator, output, desc, err };
    physics_sdk = void_call_guest(create, 5, args, 0);
    if (version > 0x2060100u && error_out) MEM32(error_out) = MEM32(err);
    void_log("[physx] NpCreatePhysicsSDK = %08X (error %u)", physics_sdk, MEM32(err));
    void_gfree(err);
    return physics_sdk;
}

CDECL_EXPORT(LOADER, NxCreatePhysicsSDKWithID)
{
    void_log("[physx] NxCreatePhysicsSDKWithID is not used by this game");
    return 0;
}

CDECL_EXPORT(LOADER, NxGetUtilLib)
{
    if (util_lib) return util_lib;
    uint32_t module = core();
    uint32_t get = module ? module_export(module, "NpGetUtilLib") : 0;
    if (get) util_lib = void_call_guest(get, 0, NULL, 0);
    return util_lib;
}

static uint32_t core_call0(const char *name)
{
    uint32_t module = core();
    uint32_t fn = module ? module_export(module, name) : 0;
    return fn ? void_call_guest(fn, 0, NULL, 0) : 0;
}

CDECL_EXPORT(LOADER, NxGetPhysicsSDK) { return core_call0("NpGetPhysicsSDK"); }
CDECL_EXPORT(LOADER, NxGetFoundationSDK) { return core_call0("NpGetFoundationSDK"); }
CDECL_EXPORT(LOADER, NxGetPhysicsSDKAllocator) { return core_call0("NpGetPhysicsSDKAllocator"); }

CDECL_EXPORT(LOADER, NxReleasePhysicsSDK)
{
    uint32_t module = core();
    uint32_t fn = module ? module_export(module, "NpReleasePhysicsSDK") : 0;
    uint32_t sdk = ARG(0);
    if (fn) void_call_guest(fn, 1, &sdk, 0);
    return 0;
}

/* NxGetCookingLib(sdkVersion) */
CDECL_EXPORT(LOADER, NxGetCookingLib)
{
    uint32_t version = ARG(0);
    if (!cooking_module) cooking_module = void_module_load("PhysXCooking.dll");
    uint32_t get = cooking_module ? module_export(cooking_module, "NxGetCookingInterface") : 0;
    uint32_t cooking = get ? void_call_guest(get, 1, &version, 0) : 0;
    void_log("[physx] NxGetCookingLib(%08X) = %08X", version, cooking);
    return cooking;
}

CDECL_EXPORT(LOADER, NxGetCookingLibWithID) { return 0; }
CDECL_EXPORT(LOADER, NxCreateModule) { return 0; }

/* ---------------------------------------------------------- cudart32_65 */
#define CUDA "cudart32_65.dll"
#define CUDA_NO_DEVICE 38u
static uint32_t fat_handle;

WINAPI_EXPORT(CUDA, __cudaRegisterFatBinary, 1)
{
    if (!fat_handle) fat_handle = void_galloc(16);
    return fat_handle;
}
WINAPI_EXPORT(CUDA, __cudaUnregisterFatBinary, 1) { return 0; }
WINAPI_EXPORT(CUDA, __cudaRegisterFunction, 10) { return 0; }
WINAPI_EXPORT(CUDA, __cudaRegisterVar, 8) { return 0; }
WINAPI_EXPORT(CUDA, __cudaRegisterTexture, 7) { return 0; }
WINAPI_EXPORT(CUDA, cudaGetDeviceProperties, 2) { return CUDA_NO_DEVICE; }
WINAPI_EXPORT(CUDA, cudaGetLastError, 0) { return CUDA_NO_DEVICE; }
WINAPI_EXPORT(CUDA, cudaThreadSynchronize, 0) { return CUDA_NO_DEVICE; }
WINAPI_EXPORT(CUDA, cudaEventElapsedTime, 3) { return CUDA_NO_DEVICE; }
WINAPI_EXPORT(CUDA, cudaEventQuery, 1) { return CUDA_NO_DEVICE; }
WINAPI_EXPORT(CUDA, cudaEventRecord, 2) { return CUDA_NO_DEVICE; }
WINAPI_EXPORT(CUDA, cudaEventCreate, 1) { return CUDA_NO_DEVICE; }
WINAPI_EXPORT(CUDA, cudaEventSynchronize, 1) { return CUDA_NO_DEVICE; }
WINAPI_EXPORT(CUDA, cudaMemcpyToSymbol, 5) { return CUDA_NO_DEVICE; }
WINAPI_EXPORT(CUDA, cudaMemcpyToSymbolAsync, 6) { return CUDA_NO_DEVICE; }
WINAPI_EXPORT(CUDA, cudaMalloc, 2) { if (ARG(0)) MEM32(ARG(0)) = 0; return CUDA_NO_DEVICE; }
WINAPI_EXPORT(CUDA, cudaMallocHost, 2) { if (ARG(0)) MEM32(ARG(0)) = 0; return CUDA_NO_DEVICE; }
WINAPI_EXPORT(CUDA, cudaFree, 1) { return CUDA_NO_DEVICE; }
WINAPI_EXPORT(CUDA, cudaFreeHost, 1) { return CUDA_NO_DEVICE; }
WINAPI_EXPORT(CUDA, cudaMemcpy, 4) { return CUDA_NO_DEVICE; }
WINAPI_EXPORT(CUDA, cudaMemcpyAsync, 5) { return CUDA_NO_DEVICE; }
WINAPI_EXPORT(CUDA, cudaMemset, 3) { return CUDA_NO_DEVICE; }
WINAPI_EXPORT(CUDA, cudaLaunch, 1) { return CUDA_NO_DEVICE; }
WINAPI_EXPORT(CUDA, cudaSetupArgument, 3) { return CUDA_NO_DEVICE; }
WINAPI_EXPORT(CUDA, cudaConfigureCall, 8) { return CUDA_NO_DEVICE; }
WINAPI_EXPORT(CUDA, cudaBindTexture, 5) { return CUDA_NO_DEVICE; }
WINAPI_EXPORT(CUDA, cudaUnbindTexture, 1) { return CUDA_NO_DEVICE; }
/* Returns a 20-byte struct through the hidden first argument. */
WINAPI_EXPORT(CUDA, cudaCreateChannelDesc, 6)
{
    uint32_t out = ARG(0);
    for (int i = 0; i < 5; ++i) MEM32(out + 4u * (uint32_t)i) = ARG(1 + i);
    return out;
}

/* ------------------------------------------------------- sockets (none) */
#define WSAENETDOWN_ 10050u
#define WS_STUBS(dll, sfx, o_inet, o_ioctl) \
    WINAPI_EXPORT_AS(dll, WSAStartup##sfx, "WSAStartup", 115, 2) { return 10091u; /* WSASYSNOTREADY */ } \
    WINAPI_EXPORT_AS(dll, WSAGetLastError##sfx, "WSAGetLastError", 111, 0) { return WSAENETDOWN_; } \
    WINAPI_EXPORT_AS(dll, socket##sfx, "socket", 23, 3) { return 0xFFFFFFFFu; } \
    WINAPI_EXPORT_AS(dll, connect##sfx, "connect", 4, 3) { return 0xFFFFFFFFu; } \
    WINAPI_EXPORT_AS(dll, closesocket##sfx, "closesocket", 3, 1) { return 0; } \
    WINAPI_EXPORT_AS(dll, send##sfx, "send", 19, 4) { return 0xFFFFFFFFu; } \
    WINAPI_EXPORT_AS(dll, recv##sfx, "recv", 16, 4) { return 0xFFFFFFFFu; } \
    WINAPI_EXPORT_AS(dll, gethostbyname##sfx, "gethostbyname", 52, 1) { return 0; } \
    WINAPI_EXPORT_AS(dll, gethostbyaddr##sfx, "gethostbyaddr", 51, 3) { return 0; } \
    WINAPI_EXPORT_AS(dll, htons##sfx, "htons", 9, 1) { return (uint32_t)(uint16_t)((ARG(0) << 8) | ((ARG(0) >> 8) & 0xFF)); } \
    WINAPI_EXPORT_AS(dll, inet_addr##sfx, "inet_addr", o_inet, 1) { return 0xFFFFFFFFu; } \
    WINAPI_EXPORT_AS(dll, ioctlsocket##sfx, "ioctlsocket", o_ioctl, 3) { return 0xFFFFFFFFu; }
WS_STUBS("ws2_32.dll", _ws2, 11, 10)
WS_STUBS("wsock32.dll", _wsock, 10, 12)

/* ---------------------------------------------------- setupapi (no PPU) */
#define SETUP "setupapi.dll"
WINAPI_EXPORT(SETUP, SetupDiGetClassDevsA, 4) { return 0xFFFFFFFFu; }
WINAPI_EXPORT(SETUP, SetupDiEnumDeviceInterfaces, 5) { void_set_last_error(ERROR_NO_MORE_ITEMS_); return 0; }
WINAPI_EXPORT(SETUP, SetupDiGetDeviceInterfaceDetailA, 6) { void_set_last_error(ERROR_NO_MORE_ITEMS_); return 0; }
WINAPI_EXPORT(SETUP, SetupDiDestroyDeviceInfoList, 1) { return 1; }

/* ------------------------------------------------- kernel32 extras */
#define K32 "kernel32.dll"
WINAPI_EXPORT(K32, DeviceIoControl, 8) { void_set_last_error(ERROR_NOT_SUPPORTED_); return 0; }
WINAPI_EXPORT(K32, HeapWalk, 2) { void_set_last_error(ERROR_NO_MORE_ITEMS_); return 0; }
WINAPI_EXPORT(K32, OpenProcess, 3) { void_set_last_error(ERROR_ACCESS_DENIED_); return 0; }
