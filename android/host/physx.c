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

#ifdef VOID_RELEASE
#include "release_overrides.h"   /* another release's CScene (tools/lift_release.py) */
#else
/* Engine's physics::CScene in the 2009 Engine.dll (PhysX 2.8.1): its step,
 * CScene::fetch, the "simulating" flag and NxScene's setTiming/getTiming slots. */
#define ENGINE_STEP_RVA 0x12a25cu
#define ENGINE_SCENE_FETCH sub_110DE7C0
#define ENGINE_SCENE_FETCH_LIFTED sub_110DE7C0_lifted
#define CSCENE_SIMULATING 0x40u
#define NXSCENE_SET_TIMING 0x148u
#define NXSCENE_GET_TIMING 0x14Cu
#endif

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
 * the float at Engine+ENGINE_STEP_RVA), what a 60 Hz screen shows; at 120 frames
 * a second every other frame had no step and the world moved in jerks
 * (measured on the Pixel 10a: the camera still in one frame of six while
 * walking, none with a step of 1/120). A step of one refresh of the screen
 * the game is drawn on: one step a frame at its full rate, two at half. */
static float display_hz = 60.0f;

void void_physics_set_display_rate(float hz)
{
    if (hz >= 30.0f && hz <= 240.0f) display_hz = hz;
}

/* The step at the display's rate costs twice the original's simulation where
 * the picture is drawn at 60 frames or fewer (measured on the POCO X3 in Zew
 * at 30 frames: 3.5 steps a frame, a quarter of the main thread waiting in
 * fetchResults), and buys nothing there: 1/60 already gives every frame a step.
 * So the step follows the rate frames are actually shown at: the display's
 * refresh from about 72 frames a second, the original 1/60 below about 58. */
static uint32_t engine_step_va;
static float fine_step, coarse_step = 1.0f / 60.0f;
static int fine_steps = 1;
static uint32_t step_generation = 1;

static void engine_step_write(float step)
{
    uint32_t old = 0;
    if (!engine_step_va || !void_vm_protect(engine_step_va & ~0xFFFu, 0x1000, 0x04, &old)) return;
    memcpy(GPTR(engine_step_va), &step, 4);
    void_vm_protect(engine_step_va & ~0xFFFu, 0x1000, old, &old);
}

static void physics_step_for_display(void)
{
#ifdef ENGINE_STEP_RVA
    uint32_t engine = void_module_handle("Engine.dll");
    if (!engine) return;
    uint32_t va = engine + ENGINE_STEP_RVA;
    float was;
    memcpy(&was, GPTR(va), 4);
    if (fabsf(was - 1.0f / 60.0f) > 1e-6f) {
        void_log("[physx] Engine's step is %g, not 1/60: left as it is", was);
        return;
    }
    float hz = display_hz < 60.0f ? 60.0f : display_hz > 144.0f ? 144.0f : display_hz;
    if (hz < 61.0f) return;
    engine_step_va = va;
    fine_step = 1.0f / hz;
    engine_step_write(fine_step);
    void_log("[physx] the scenes' fixed step 1/%.0f s for a %.0f Hz display, 1/60 while frames are slower", hz,
        display_hz);
#endif
}

#ifdef ENGINE_SCENE_FETCH
/* Whether the shown rate has crossed to the other step for a second. */
static float physics_wanted_step(void)
{
    static uint64_t crossing_since;
    double fps = void_present_rate();
    uint64_t now = void_monotonic_ns();
    int crossing = fps > 0 && (fine_steps ? fps < 58.0 : fps > 72.0);
    if (!crossing) crossing_since = 0;
    else if (!crossing_since) crossing_since = now;
    else if (now - crossing_since >= 1000000000ull) {
        fine_steps = !fine_steps;
        crossing_since = 0;
        ++step_generation;
        engine_step_write(fine_steps ? fine_step : coarse_step);   /* scenes made from now on */
        void_log("[physx] the step is 1/%.0f s: frames at %.1f a second", 1.0 / (fine_steps ? fine_step : coarse_step),
            fps);
    }
    return fine_steps ? fine_step : coarse_step;
}

/* Engine's CScene::fetch (thiscall on the CScene; its NxScene at +0x14, "simulating" at
 * +CSCENE_SIMULATING): fetchResults(NX_RIGID_BODY_FINISHED, block), getTiming, its
 * listeners. Once it returns the scene is idle until CScene::simulate, the one moment
 * NxScene::setTiming may run. Vtable slots as the game itself uses them: setTiming(step, 8,
 * FIXED) from CScene's constructor, getTiming(&step, &iterations, &method, &substeps) here. */
#define NX_TIMESTEP_FIXED 0u

void ENGINE_SCENE_FETCH_LIFTED(void);
void ENGINE_SCENE_FETCH(void)
{
    uint32_t cscene = g_ecx;
    int fetched = MEM8(cscene + CSCENE_SIMULATING) != 0;
    ENGINE_SCENE_FETCH_LIFTED();
    if (!fetched || !engine_step_va) return;
    float want = physics_wanted_step();
    uint32_t scene = MEM32(cscene + 0x14);
    /* The scenes whose step is already this generation's: a few live at once. */
    static struct { uint32_t scene, generation; } done[8];
    static unsigned done_next;
    for (unsigned i = 0; i < 8; ++i)
        if (done[i].scene == scene && done[i].generation == step_generation) return;
    if (!scene || !void_vm_readable(scene, 4) || !void_vm_readable(MEM32(scene) + NXSCENE_SET_TIMING, 8)) return;
    static uint32_t timing;   /* guest scratch for getTiming's four results */
    if (!timing) timing = void_galloc(16);
    void_regs saved;
    void_regs_save(&saved);
    uint32_t vt = MEM32(scene);
    MEM32(timing) = MEM32(timing + 4) = MEM32(timing + 8) = MEM32(timing + 12) = 0;
    uint32_t outs[4] = { timing, timing + 4, timing + 8, timing + 12 };
    void_call_guest_this(MEM32(vt + NXSCENE_GET_TIMING), scene, 4, outs);
    float step;
    memcpy(&step, GPTR(timing), 4);
    uint32_t iterations = MEM32(timing + 4), method = MEM32(timing + 8);
    /* Only the steps given here: a scene the game times otherwise keeps its own. */
    if (method == NX_TIMESTEP_FIXED && step != want && (step == fine_step || step == coarse_step)) {
        uint32_t args[3] = { 0, iterations, method };
        memcpy(&args[0], &want, 4);
        void_call_guest_this(MEM32(vt + NXSCENE_SET_TIMING), scene, 3, args);
    }
    void_regs_load(&saved);
    done[done_next++ % 8].scene = scene;
    done[(done_next - 1) % 8].generation = step_generation;
}
#endif

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
