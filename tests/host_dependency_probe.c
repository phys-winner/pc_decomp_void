/* Real host lifecycle functions, controlled guest DllMain/snapshot stand-ins. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "host-dependency-types.h"

#define ENGINE_BASE 0x11000000u
#define NXCHARACTER_BASE 0x17000000u
static manual_module manual_modules[8];
#define MANUAL_COUNT (sizeof(manual_modules) / sizeof(manual_modules[0]))
static CRITICAL_SECTION gm_loader_lock;
#ifdef VOID_LIFT_NXCHARACTER
static int engine_nx_dependency_held;
#endif
static unsigned crt[8], order[20], order_count, restore_count, checks;
static int fail_engine, fail_nx;
static BYTE pristine;
static HMODULE manual_load(manual_module *module);

#define CHECK(expression) do { ++checks; if (!(expression)) { \
    fprintf(stderr, "FAIL %u line %d: %s\n", checks, __LINE__, #expression); ExitProcess(91); } } while (0)

void void_lift_trap(uint32_t address, const char *message)
{
    fprintf(stderr, "Unexpected trap %08X %s\n", address, message); ExitProcess(90);
}

static unsigned index_for(uint32_t base)
{
    for (unsigned i = 0; i < MANUAL_COUNT; ++i) if (manual_modules[i].base == base) return i;
    ExitProcess(92);
}

static uint32_t void_dll_event(uint32_t entry, uint32_t base, uint32_t reason, uint32_t reserved)
{
    unsigned index = index_for(base);
    CHECK((DWORD)(uintptr_t)gm_loader_lock.OwningThread != GetCurrentThreadId());
    CHECK(entry == manual_modules[index].entry);
    CHECK(order_count < sizeof(order) / sizeof(order[0]));
    order[order_count++] = reason == DLL_PROCESS_ATTACH ?
        (base == ENGINE_BASE ? 2u : 1u) : (base == ENGINE_BASE ? 3u : 4u);
    if (base == ENGINE_BASE) {
#ifdef VOID_LIFT_NXCHARACTER
        CHECK(manual_modules[7].state == GM_READY && manual_modules[7].references >= 1 && crt[7] == 1);
        CHECK(engine_nx_dependency_held);
#endif
        if (reason == DLL_PROCESS_ATTACH && fail_engine) return 0;
    } else if (reason == DLL_PROCESS_ATTACH && fail_nx) return 0;
    if (reason == DLL_PROCESS_ATTACH) { CHECK(crt[index] == 0); crt[index] = 1; }
    else { CHECK(crt[index] == 1); CHECK(reserved <= 1); crt[index] = 0; }
    return 1;
}

static void void_restore_module(uint32_t base, uint32_t span, uint32_t counter, const BYTE *snapshot)
{
    unsigned index = index_for(base);
    CHECK((DWORD)(uintptr_t)gm_loader_lock.OwningThread != GetCurrentThreadId());
    CHECK(span == 1 && counter == index && snapshot == &pristine && crt[index] == 0);
    ++restore_count;
}

#include "host-dependency-functions.h"

static void reset(void)
{
    memset(manual_modules, 0, sizeof manual_modules); memset(crt, 0, sizeof crt);
    order_count = restore_count = 0; fail_engine = fail_nx = 0;
#ifdef VOID_LIFT_NXCHARACTER
    engine_nx_dependency_held = 0;
#endif
    manual_modules[1].name = "Engine.dll"; manual_modules[1].base = ENGINE_BASE;
    manual_modules[1].entry = ENGINE_BASE + 0x10; manual_modules[1].state = GM_MAPPED;
    manual_modules[7].name = "NxCharacter.dll"; manual_modules[7].base = NXCHARACTER_BASE;
    manual_modules[7].entry = NXCHARACTER_BASE + 0x10; manual_modules[7].state = GM_MAPPED;
    manual_modules[7].pristine = &pristine; manual_modules[7].span = 1; manual_modules[7].crt_counter = 7;
    /* Other descriptor rows are not loaded but participate in detach-all. */
    for (unsigned i = 0; i < MANUAL_COUNT; ++i) if (i != 1 && i != 7) {
        manual_modules[i].name = "unused.dll"; manual_modules[i].base = 0x20000000u + i * 0x10000u;
    }
}

int main(void)
{
    InitializeCriticalSection(&gm_loader_lock); reset();
    manual_module *engine = &manual_modules[1], *nx = &manual_modules[7];
    CHECK(manual_load(engine) == (HMODULE)ENGINE_BASE);
    CHECK(manual_load(engine) == (HMODULE)ENGINE_BASE && engine->references == 2 && engine->attach_events == 1);
#ifdef VOID_LIFT_NXCHARACTER
    CHECK(order_count == 2 && order[0] == 1 && order[1] == 2 && nx->references == 1);
    CHECK(manual_load(nx) == (HMODULE)NXCHARACTER_BASE && nx->references == 2);
#endif
    CHECK(manual_release(engine, 0, 1) && engine->state == GM_READY && engine->references == 1);
#ifdef VOID_LIFT_NXCHARACTER
    CHECK(nx->references == 2 && nx->detach_events == 0 && engine_nx_dependency_held);
#endif
    CHECK(manual_release(engine, 0, 1) && engine->state == GM_DETACHED && engine->references == 0);
#ifdef VOID_LIFT_NXCHARACTER
    CHECK(nx->state == GM_READY && nx->references == 1 && !engine_nx_dependency_held && order[2] == 3);
    CHECK(manual_release(nx, 0, 1) && nx->state == GM_DETACHED && nx->references == 0 && order[3] == 4);
#endif
    unsigned events = order_count;
    CHECK(!manual_load(engine) && engine->state == GM_DETACHED && order_count == events);
    CHECK(GetLastError() == ERROR_DLL_INIT_FAILED); /* Existing non-reloadable Engine contract. */
#ifdef VOID_LIFT_NXCHARACTER
    CHECK(manual_load(nx) == (HMODULE)NXCHARACTER_BASE && restore_count == 1 && nx->attach_events == 2);
    CHECK(manual_release(nx, 0, 1) && nx->detach_events == 2);
    reset(); fail_engine = 1;
    CHECK(!manual_load(engine) && engine->state == GM_DETACHED && engine->references == 0);
    CHECK(order_count == 3 && order[0] == 1 && order[1] == 2 && order[2] == 4);
    CHECK(nx->state == GM_DETACHED && !nx->references && !engine_nx_dependency_held && !crt[7]);
    reset(); fail_nx = 1;
    CHECK(!manual_load(engine) && engine->state == GM_MAPPED && !engine->attach_events && !engine->references);
    CHECK(nx->state == GM_DETACHED && !nx->references && !engine_nx_dependency_held && order_count == 1);
    fail_nx = 0;
    CHECK(manual_load(engine) == (HMODULE)ENGINE_BASE && restore_count == 1 && nx->attach_events == 2);
    manual_detach_all(1);
    CHECK(engine->state == GM_DETACHED && nx->state == GM_DETACHED && !engine_nx_dependency_held);
    CHECK(order[order_count - 2] == 3 && order[order_count - 1] == 4 && !crt[1] && !crt[7]);
#else
    CHECK(nx->state == GM_MAPPED && nx->attach_events == 0 && nx->references == 0);
    reset(); CHECK(manual_load(engine) == (HMODULE)ENGINE_BASE); manual_detach_all(1);
    CHECK(engine->state == GM_DETACHED && nx->state == GM_MAPPED);
#endif
    DeleteCriticalSection(&gm_loader_lock);
    printf("PASS %u checks: actual host lifecycle, dependency/ref ordering, failure rollback/retry, independent reload, Engine remains non-reloadable\n", checks);
    return 0;
}
