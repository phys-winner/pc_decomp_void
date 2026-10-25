#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "recomp_types.h"
#include <stdio.h>

uint32_t g_eax,g_ecx,g_edx,g_esp,g_ebx,g_esi,g_edi,g_ebp;
double g_st[8]; int g_fp_top; uint16_t g_fpu_cw;
ptrdiff_t g_mem_base;
uint32_t g_cur_func;
void sub_10259D8D(void); void sub_10259D99(void);
static unsigned char host[108],native_saved[116],native_reset[108],native_restored[108],model_saved[116];
static uint32_t stack[16];

int main(void)
{
    memset(native_saved,0xA5,sizeof native_saved); memset(model_saved,0xA5,sizeof model_saved);
    __asm {
        fnsave host
        fld1
        fldz
        lea ecx,native_saved
        fnsave [ecx+8]
        fnsave native_reset
        frstor [ecx+8]
        fnsave native_restored
        frstor host
    }
    uint16_t native_tag=*(uint16_t *)(native_saved+16),reset_tag=*(uint16_t *)(native_reset+8);
    if (native_tag==0xFFFF||reset_tag!=0xFFFF||memcmp(native_saved+8,native_restored,108)) return 1;
    g_st[0]=0; g_st[1]=1; g_fp_top=2; g_fpu_cw=0x37F;
    g_ecx=(uint32_t)(uintptr_t)model_saved; g_esp=(uint32_t)(uintptr_t)(stack+8);
    stack[8]=0xDEADBEEF; sub_10259D8D();
    unsigned unchanged=0; for (unsigned i=8;i<116;i++) unchanged+=model_saved[i]==0xA5;
    if (unchanged!=108||g_fp_top!=2) return 2;
    g_st[0]=99; g_st[1]=-3; g_fp_top=2; g_fpu_cw=0xB7F;
    g_esp=(uint32_t)(uintptr_t)(stack+8); sub_10259D99();
    if (g_st[0]!=99||g_st[1]!=-3||g_fp_top!=2||g_fpu_cw!=0xB7F) return 3;
    printf("GAP native FNSAVE writes108/resetTagsFFFF; emitted writes0/retainsCount2; native FRSTOR restores108; emitted retains mutated ST0=99/CW0B7F; nativeTags=%04X\n",native_tag);
    return 0;
}
