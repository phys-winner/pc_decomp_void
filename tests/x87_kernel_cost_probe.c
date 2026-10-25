/* Isolated cost estimate, not a game backend or its correctness oracle. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef struct { unsigned char bytes[108]; } x87_image;
static const double one=1.0;

static void seed(x87_image *guest) {
    x87_image host;
    __asm {
        lea eax,host
        fnsave [eax]
        fldz
        mov eax,guest
        fnsave [eax]
        lea eax,host
        frstor [eax]
    }
}

__declspec(noinline)static void add_once(x87_image *guest) {
    x87_image host;
    __asm {
        lea eax,host
        fnsave [eax]
        mov eax,guest
        frstor [eax]
        fadd one
        fnsave [eax]
        lea eax,host
        frstor [eax]
    }
}

__declspec(noinline)static void add_block(x87_image *guest,unsigned count) {
    x87_image host;
    __asm {
        lea eax,host
        fnsave [eax]
        mov eax,guest
        frstor [eax]
        mov ecx,count
    repeat_add:
        fadd one
        dec ecx
        jnz repeat_add
        fnsave [eax]
        lea eax,host
        frstor [eax]
    }
}

static double read_value(const x87_image *guest) {
    x87_image host; double result;
    __asm {
        lea eax,host
        fnsave [eax]
        mov eax,guest
        frstor [eax]
        fstp result
        lea eax,host
        frstor [eax]
    }
    return result;
}

int main(void) {
    const unsigned iterations=250000;
    LARGE_INTEGER frequency,begin,end; QueryPerformanceFrequency(&frequency);
    x87_image guest,host_before,host_after;
    for (int repeat=0;repeat<5;repeat++) {
        for (int block=0;block<2;block++) {
            seed(&guest);
            __asm {
                lea eax,host_before
                fnsave [eax]
                frstor [eax]
            }
            QueryPerformanceCounter(&begin);
            if (block) add_block(&guest,iterations);
            else for (unsigned i=0;i<iterations;i++) add_once(&guest);
            QueryPerformanceCounter(&end);
            __asm {
                lea eax,host_after
                fnsave [eax]
                frstor [eax]
            }
            if (memcmp(host_before.bytes,host_after.bytes,108)!=0) return 1;
            double result=read_value(&guest);
            if (result!=iterations) return 2;
            printf("{\"repeat\":%d,\"mode\":\"%s\",\"iterations\":%u,\"ticks\":%lld,\"frequency\":%lld,\"ns_per_add\":%.6f,\"result\":%.0f,\"host_restored\":true}\n",
                repeat,block?"block-resident":"full-switch-per-add",iterations,
                end.QuadPart-begin.QuadPart,frequency.QuadPart,
                (end.QuadPart-begin.QuadPart)*(1e9/frequency.QuadPart)/iterations,result);
        }
    }
    return 0;
}
