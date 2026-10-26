#define _GNU_SOURCE
#include <assert.h>
#include <pthread.h>
#include <sched.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static cpu_set_t original, narrowed;
static void void_log(const char *format, ...)
{
    va_list args;
    va_start(args, format);
    vprintf(format, args);
    va_end(args);
    putchar('\n');
}

/* PRODUCTION */

static void *host_worker(void *arg)
{
    (void)arg;
    cpu_set_t mask;
    assert(sched_getaffinity(0, sizeof mask, &mask) == 0 && CPU_EQUAL(&mask, &narrowed));
    void_host_thread_init();
    assert(sched_getaffinity(0, sizeof mask, &mask) == 0 && CPU_EQUAL(&mask, &original));
    void_host_thread_init();
    assert(sched_getaffinity(0, sizeof mask, &mask) == 0 && CPU_EQUAL(&mask, &original));
    return NULL;
}

int main(int argc, char **argv)
{
    if (argc > 1) assert(strcmp(argv[1], "no-pin") == 0 && setenv("VOID_BIG_CORES", "0", 1) == 0);
    assert(sched_getaffinity(0, sizeof original, &original) == 0);
    assert(CPU_COUNT(&original) > 1);
    pin_guest_thread();
    CPU_ZERO(&narrowed);
    for (int cpu = 0; cpu < CPU_SETSIZE; ++cpu) {
        if (CPU_ISSET(cpu, &original)) { CPU_SET(cpu, &narrowed); break; }
    }
    assert(sched_setaffinity(0, sizeof narrowed, &narrowed) == 0);
    pthread_t worker;
    assert(pthread_create(&worker, NULL, host_worker, NULL) == 0);
    assert(pthread_join(worker, NULL) == 0);
    void_host_thread_init();
    cpu_set_t mask;
    assert(sched_getaffinity(0, sizeof mask, &mask) == 0 && CPU_EQUAL(&mask, &original));
    printf("PASS: real pthread inherited %d CPU, restored %d allowed CPUs (%s)\n",
           CPU_COUNT(&narrowed), CPU_COUNT(&original), argc > 1 ? "guest pin disabled" : "guest pin enabled");
    return 0;
}
