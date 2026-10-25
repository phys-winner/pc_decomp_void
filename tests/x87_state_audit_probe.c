/* Reproduce the current x87 model's state losses; this is not a repair. */
#ifndef VOID_AUDIT_RUNTIME_PATH
#define VOID_AUDIT_RUNTIME_PATH "../native/void_runtime.c"
#endif
#include VOID_AUDIT_RUNTIME_PATH
#include "x87-audit-functions.h"

static const int64_t value_a=9007199254740993ll, value_b=9007199254740992ll;
static HANDLE thread_ready, thread_continue;
static int64_t thread_result;
static int64_t nested_result;
static int64_t value_input, value_output;
static int thread_yields;

void void_lift_trap(uint32_t address,const char *instruction) {
    fprintf(stderr,"Unexpected trap %08X %s\n",address,instruction); ExitProcess(90);
}
recomp_func_t recomp_lookup_manual(uint32_t address) { (void)address; return NULL; }

static void reset_model(void) {
    memset(g_st,0,sizeof(g_st)); memset(g_st_i64,0,sizeof(g_st_i64)); g_fp_top=0;
}
static void push_exact(int64_t value) {
    value_input=value; g_ecx=(uint32_t)(uintptr_t)&value_input;
    PUSH32(g_esp,RECOMP_RETADDR); sub_21005000();
}
static int64_t store_exact(void) {
    value_output=0; g_edx=(uint32_t)(uintptr_t)&value_output;
    PUSH32(g_esp,RECOMP_RETADDR); sub_21006000(); return value_output;
}
static void shadow_callback(void) { push_exact(value_b); g_esp+=4; }
static void inner_callback(void) { push_exact(value_a); g_esp+=4; }
static void nested_callback(void) {
    uint32_t arguments[25]={0}; double callback_return;
    push_exact(value_b); cb_run(0x21008000u,arguments,0);
    __asm fstp callback_return
    nested_result=store_exact(); g_esp+=4;
}

static DWORD WINAPI guest_thread(void *unused) {
    (void)unused;
    mach_enter(); reset_model(); push_exact(value_a);
    SetEvent(thread_ready);
    DWORD deadline=GetTickCount()+10000;
    while (WaitForSingleObject(thread_continue,0)==WAIT_TIMEOUT) {
        native32_yield(); thread_yields++;
        if ((LONG)(GetTickCount()-deadline)>=0) { mach_leave(); return 91; }
    }
    thread_result=store_exact(); mach_leave();
    return 0;
}

static void native_remainder(double left,double right,int nearest,double *result,uint16_t *status) {
    unsigned char saved[108];
    __asm {
        lea eax,saved
        fnsave [eax]
        fld right
        fld left
    }
    if (nearest) { __asm fprem1 }
    else { __asm fprem }
    __asm {
        mov eax,status
        fnstsw word ptr [eax]
        mov eax,result
        fstp qword ptr [eax]
        fstp st(0)
        lea eax,saved
        frstor [eax]
    }
}

int main(void) {
    native32_init(); mach_enter(); reset_model();
    push_exact(value_a);
    regs_t saved; regs_save(&saved);
    g_st_i64[0]=value_b; regs_load(&saved);
    int64_t restored=store_exact();
    printf("snapshot_shadow expected=%016llX actual=%016llX\n",(uint64_t)value_a,(uint64_t)restored);
    if (restored!=(EXPECT_SNAPSHOT_FIXED?value_a:value_b)) return 1;

    for (int i=0;i<8;i++) g_st_i64[i]=value_a+i;
    regs_save(&saved);
    memset(g_st_i64,0,sizeof(g_st_i64)); regs_load(&saved);
    for (int i=0;i<8;i++) if (g_st_i64[i]!=(EXPECT_SNAPSHOT_FIXED?value_a+i:0)) return 8;

    reset_model(); push_exact(value_a);
    uint32_t arguments[25]={0}; double callback_return;
    cb_run(0x21004000u,arguments,0);
    __asm fstp callback_return
    int parent_depth=g_fp_top;
    int64_t after_callback=store_exact();
    printf("callback_shadow expected=%016llX actual=%016llX parent_depth=%d\n",(uint64_t)value_a,(uint64_t)after_callback,parent_depth);
    if (after_callback!=(EXPECT_SNAPSHOT_FIXED?value_a:value_b) || parent_depth!=1) return 2;

    reset_model(); push_exact(value_a); cb_run(0x21007000u,arguments,0);
    int64_t after_nested=store_exact();
    printf("nested_shadow expected=%016llX actual=%016llX parent=%016llX\n",(uint64_t)value_b,(uint64_t)nested_result,(uint64_t)after_nested);
    if (nested_result!=(EXPECT_SNAPSHOT_FIXED?value_b:value_a) || after_nested!=(EXPECT_SNAPSHOT_FIXED?value_a:value_b)) return 9;

    double native_result; uint16_t native_status;
    native_remainder(5.5,2.0,1,&native_result,&native_status);
    reset_model(); fp_push_impl(g_st,&g_fp_top,2.0); fp_push_impl(g_st,&g_fp_top,5.5);
    PUSH32(g_esp,RECOMP_RETADDR); sub_21001000();
    printf("fprem1 native=%.17g lifted=%.17g native_conditions=%04X\n",native_result,g_st[0],native_status&0x4700);
    if (native_result!=-0.5 || g_st[0]!=native_result) return 3;

    native_remainder(9.0,2.0,0,&native_result,&native_status);
    reset_model(); fp_push_impl(g_st,&g_fp_top,2.0); fp_push_impl(g_st,&g_fp_top,9.0);
    g_eax=0; PUSH32(g_esp,RECOMP_RETADDR); sub_21002000();
    printf("call_status native_conditions=%04X lifted_conditions=%04X\n",native_status&0x4700,g_eax&0x4700);
    if ((native_status&0x4700)!=0x0100 || (g_eax&0x4700)!=(native_status&0x4700)) return 4;
    mach_leave();

    thread_ready=CreateEventW(NULL,TRUE,FALSE,NULL); thread_continue=CreateEventW(NULL,TRUE,FALSE,NULL);
    HANDLE thread=CreateThread(NULL,0,guest_thread,NULL,0,NULL);
    if (!thread || WaitForSingleObject(thread_ready,10000)!=WAIT_OBJECT_0) return 5;
    mach_enter(); reset_model(); push_exact(value_b); mach_leave(); SetEvent(thread_continue);
    if (WaitForSingleObject(thread,10000)!=WAIT_OBJECT_0) return 6;
    DWORD thread_exit=99; GetExitCodeThread(thread,&thread_exit);
    printf("thread_shadow expected=%016llX actual=%016llX thread_exit=%lu yields=%d\n",(uint64_t)value_a,(uint64_t)thread_result,thread_exit,thread_yields);
    CloseHandle(thread); CloseHandle(thread_ready); CloseHandle(thread_continue);
    if (thread_exit || thread_result!=(EXPECT_SNAPSHOT_FIXED?value_a:value_b) || !thread_yields) return 7;
    puts(EXPECT_SNAPSHOT_FIXED?"SNAPSHOT_AND_DOUBLE_REMAINDER_PASS":"BASELINE_INT64_LOSS_REPRODUCED; double remainder repair passes");
    return 0;
}

const recomp_dispatch_entry_t recomp_dispatch_table[]={
    {0x21001000u,sub_21001000},{0x21002000u,sub_21002000},{0x21003000u,sub_21003000},{0x21004000u,shadow_callback},
    {0x21005000u,sub_21005000},{0x21006000u,sub_21006000},{0x21007000u,nested_callback},{0x21008000u,inner_callback}};
const uint32_t recomp_dispatch_count=8;
