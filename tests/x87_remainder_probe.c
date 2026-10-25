/* Differential ISA/context proof for the project's bounded double model. */
#include "../native/void_runtime.c"
#include "x87-rem-functions.h"

typedef struct { unsigned char bytes[108]; } x87_state;
#pragma pack(push,1)
typedef struct {
    uint64_t left,right;
    uint32_t cw,nearest,guard;
    x87_state input;
} rem_case;
#pragma pack(pop)
static unsigned trap_count;
static uint32_t trap_address;
static const char *trap_reason;
static HANDLE thread_ready,thread_continue;
static int thread_cc,thread_yields,thread_initial;
static int callback_cc;
static x87_state mismatched_host;
static int verified_amd;
static uint32_t cpu_signature;
static unsigned metadata_zeroings,strict_host_images,pending_host_images;

void void_lift_trap(uint32_t address,const char *instruction) {
    ++trap_count; trap_address=address; trap_reason=instruction;
}
recomp_func_t recomp_lookup_manual(uint32_t address) { (void)address; return NULL; }

/* Oracle begins with independently supplied raw80 state, not double loads. */
static void oracle_step(const x87_state *input,int nearest,x87_state *output) {
    x87_state host;
    __asm {
        lea eax,host
        fnsave [eax]
        mov eax,input
        frstor [eax]
    }
    if (nearest) { __asm fprem1 }
    else { __asm fprem }
    __asm {
        mov eax,output
        fnsave [eax]
        lea eax,host
        frstor [eax]
    }
}

static uint64_t oracle_project(const x87_state *input,uint16_t cw,unsigned char widened[10]) {
    x87_state host; uint64_t output; uint16_t masked=cw|0x3Fu;
    __asm {
        lea eax,host
        fnsave [eax]
        mov eax,input
        frstor [eax]
        fnclex
        fldcw masked
        fstp qword ptr output
        fld qword ptr output
        mov eax,widened
        fstp tbyte ptr [eax]
        lea eax,host
        frstor [eax]
    }
    return output;
}

static void host_seed(unsigned index,x87_state *outer,x87_state *before) {
    static const uint16_t modes[12]={0x007F,0x027F,0x037F,0x047F,0x067F,0x077F,
                                    0x087F,0x0A7F,0x0B7F,0x0C7F,0x0E7F,0x0F7F};
    static const double value=3.25;
    __asm {
        mov eax,outer
        fnsave [eax]
        fld value
        fldz
        mov eax,before
        fnsave [eax]
    }
    uint16_t cw=modes[index%12],sw;
    memcpy(before->bytes,&cw,2); memcpy(&sw,before->bytes+4,2);
    sw=(sw&~0x473Fu)|((index&15u)<<8 &0x0700u)|((index&1u)?0x4000u:0)|((index%63)+1);
    if (index%13==12) { cw=0x037E; sw|=0x8081; memcpy(before->bytes,&cw,2); }
    memcpy(before->bytes+4,&sw,2);
    __asm {
        mov eax,before
        frstor [eax]
        fnsave [eax]
        frstor [eax]
    }
}

static int host_image_policy(const x87_state *before,const x87_state *after) {
    if (!memcmp(before->bytes,after->bytes,108)) return 1;
    uint16_t sw; memcpy(&sw,before->bytes+4,2);
    /* AMD FXSAVE may lose these error pointers when ES=0 during scheduling. */
    int metadata_zero=1;
    for (unsigned offset=12;offset<26;offset++) if (after->bytes[offset]) metadata_zero=0;
    if (verified_amd && !(sw&0x80u) && metadata_zero &&
            !memcmp(before->bytes,after->bytes,12) && !memcmp(before->bytes+26,after->bytes+26,82)) return 2;
    return 0;
}

static int host_finish(const x87_state *outer,const x87_state *before) {
    x87_state after;
    __asm {
        lea eax,after
        fnsave [eax]
        mov eax,outer
        frstor [eax]
    }
    int policy=host_image_policy(before,&after);
    if (policy==1) {
        uint16_t sw; memcpy(&sw,before->bytes+4,2);
        ++strict_host_images; if (sw&0x80u) ++pending_host_images; return 1;
    }
    mismatched_host=after;
    if (policy==2) { ++metadata_zeroings; return 1; }
    return 0;
}

static int host_policy_negative_controls(void) {
    x87_state before,after; memset(&before,0xA5,sizeof before);
    uint16_t sw=0; memcpy(before.bytes+4,&sw,2);
    after=before; memset(after.bytes+12,0,14);
    int original_vendor=verified_amd; verified_amd=1;
    if (host_image_policy(&before,&after)!=2) return 1;
    after.bytes[0]^=1; if (host_image_policy(&before,&after)) return 2; after.bytes[0]^=1;
    after.bytes[12]=1; if (host_image_policy(&before,&after)) return 3; after.bytes[12]=0;
    sw=0x80; memcpy(before.bytes+4,&sw,2); memcpy(after.bytes+4,&sw,2);
    if (host_image_policy(&before,&after)) return 4;
    sw=0; memcpy(before.bytes+4,&sw,2); memcpy(after.bytes+4,&sw,2);
    verified_amd=0; if (host_image_policy(&before,&after)) return 5;
    if (host_image_policy(&before,&before)!=1) return 6;
    verified_amd=original_vendor; return 0;
}

static void print_host_diff(const x87_state *before) {
    for (unsigned offset=0;offset<108;offset++) {
        if (before->bytes[offset]!=mismatched_host.bytes[offset])
            printf("host_diff offset=%u before=%02X after=%02X\n",offset,
                before->bytes[offset],mismatched_host.bytes[offset]);
    }
    printf("host_before="); for (unsigned offset=0;offset<108;offset++)printf("%02X",before->bytes[offset]); puts("");
    printf("host_after="); for (unsigned offset=0;offset<108;offset++)printf("%02X",mismatched_host.bytes[offset]); puts("");
}

/* No guest arithmetic: isolate physical identity versus Windows scheduling. */
static int identity_control(int scheduled) {
    for (unsigned attempt=0;attempt<100000;attempt++) {
        x87_state outer,before,identity;
        host_seed(attempt,&outer,&before);
        __asm {
            lea eax,identity
            fnsave [eax]
            frstor [eax]
        }
        if (scheduled) Sleep(1);
        unsigned previous=metadata_zeroings;
        int equal=host_finish(&outer,&before);
        if (!equal) {
            printf("NATIVE_IDENTITY_METADATA_CHANGED scheduled=%d attempt=%u; no guest operation executed\n",scheduled,attempt);
            print_host_diff(&before); return 4;
        }
        if (metadata_zeroings!=previous && metadata_zeroings==1) {
            printf("NATIVE_IDENTITY_METADATA_ZEROING scheduled=%d attempt=%u verified_amd=%d; no guest operation executed\n",scheduled,attempt,verified_amd);
            print_host_diff(&before);
        }
        if (scheduled && attempt==63) break;
    }
    printf("NATIVE_IDENTITY_SCOPE_PASS scheduled=%d full_images=%u metadata_zeroings=%u pending_full_images=%u verified_amd=%d cpu_signature=%08X\n",
        scheduled,strict_host_images,metadata_zeroings,pending_host_images,verified_amd,cpu_signature); return 0;
}

static uint16_t condition_word(void) {
    return (uint16_t)(void_fpu_cmp>=0x10000?void_fpu_cmp&0x4700:
        void_fpu_cmp==2?0x4500:void_fpu_cmp<0?0x0100:void_fpu_cmp==0?0x4000:0);
}

static void call_guest(recomp_func_t function) {
    PUSH32(g_esp,RECOMP_RETADDR); function();
}
static void set_inputs(uint64_t left,uint64_t right,uint16_t cw) {
    memset(g_st,0,sizeof g_st); memset(g_st_i64,0,sizeof g_st_i64);
    memcpy(g_st,&left,8); memcpy(g_st+1,&right,8); g_fp_top=2; g_fpu_cw=cw;
}

static void inner_callback(void) { call_guest(sub_22008000); g_esp+=4; }
static void outer_callback(void) {
    uint32_t arguments[25]={0};
    call_guest(sub_22002000); int expected=void_fpu_cmp;
    cb_run(0x2200F000u,arguments,0);
    callback_cc=void_fpu_cmp==expected; g_esp+=4;
}

static DWORD WINAPI condition_thread(void *unused) {
    (void)unused;
    mach_enter(); thread_initial=void_fpu_cmp; void_fpu_cmp=-1;
    SetEvent(thread_ready); DWORD deadline=GetTickCount()+10000;
    while (WaitForSingleObject(thread_continue,0)==WAIT_TIMEOUT) {
        native32_yield(); ++thread_yields;
        if ((LONG)(GetTickCount()-deadline)>=0) { mach_leave(); return 1; }
    }
    thread_cc=void_fpu_cmp; mach_leave(); return 0;
}

static int context_tests(void) {
    set_inputs(0x4022000000000000ull,0x4000000000000000ull,0x027F); /* 9,2 */
    void_fpu_cmp=0; call_guest(sub_22003000);
    if ((g_eax&0x4700)!=0x0100) return 20;
    set_inputs(0x4022000000000000ull,0x4000000000000000ull,0x027F);
    call_guest(sub_22005000); if ((g_eax&0x4700)!=0x0100) return 21;
    set_inputs(0x4022000000000000ull,0x4000000000000000ull,0x027F);
    g_edx=0x22001000u; call_guest(sub_2200B000); if ((g_eax&0x4700)!=0x0100) return 22;
    set_inputs(0x3FF0000000000000ull,0x4000000000000000ull,0x027F); /* 1,2 */
    call_guest(sub_22007000); if ((g_eax&0x4700)!=0x0100) return 23;
    call_guest(sub_2200D000); if ((g_eax&0x4700)!=0x0100) return 24;
    set_inputs(0xBFF0000000000000ull,0x4000000000000000ull,0x027F);
    call_guest(sub_22009000); if ((g_eax&0x4700)!=0x0600) return 25;
    uint16_t memory_status=0; g_edi=(uint32_t)(uintptr_t)&memory_status;
    call_guest(sub_2200A000); if (memory_status!=0x0600) return 26;
    set_inputs(0x401C000000000000ull,0x4000000000000000ull,0x027F); /* 7,2 */
    void_fpu_cmp=-1; uint32_t arguments[25]={0}; cb_run(0x2200E000u,arguments,0);
    if (!callback_cc||void_fpu_cmp!=-1) return 27;
    regs_t snapshot; regs_save(&snapshot); void_fpu_cmp=0x14700; regs_load(&snapshot);
    if (void_fpu_cmp!=-1) return 28;
    mach_leave();
    thread_ready=CreateEventW(NULL,TRUE,FALSE,NULL); thread_continue=CreateEventW(NULL,TRUE,FALSE,NULL);
    HANDLE thread=CreateThread(NULL,0,condition_thread,NULL,0,NULL);
    if (!thread||WaitForSingleObject(thread_ready,10000)!=WAIT_OBJECT_0) return 29;
    mach_enter(); void_fpu_cmp=0x14200; mach_leave(); SetEvent(thread_continue);
    if (WaitForSingleObject(thread,10000)!=WAIT_OBJECT_0) return 30;
    DWORD code=99; GetExitCodeThread(thread,&code);
    CloseHandle(thread); CloseHandle(thread_ready); CloseHandle(thread_continue); mach_enter();
    if (code||thread_initial!=1||thread_cc!=-1||!thread_yields) return 31;
    return 0;
}

int main(int argc,char **argv) {
    int cpu[4]; __cpuid(cpu,0); uint32_t vendor[3]={(uint32_t)cpu[1],(uint32_t)cpu[3],(uint32_t)cpu[2]};
    verified_amd=!memcmp(vendor,"AuthenticAMD",12);
    __cpuid(cpu,1); cpu_signature=(uint32_t)cpu[0];
    native32_init(); mach_enter();
    if (argc==2 && !strcmp(argv[1],"--identity")) return identity_control(0);
    if (argc==2 && !strcmp(argv[1],"--identity-scheduled")) return identity_control(1);
#ifdef CONTROL_ONLY
    set_inputs(0x4016000000000000ull,0x4000000000000000ull,0x027F); /* 5.5,2 */
    call_guest(sub_22002000); uint64_t result; memcpy(&result,g_st,8);
    if (result!=0x3FF8000000000000ull) return 80;
    set_inputs(0x4022000000000000ull,0x4000000000000000ull,0x027F);
    call_guest(sub_22003000); if ((g_eax&0x4700)!=0x4000) return 81;
    puts("CONTROL_REPRODUCED FPREM1=1.5 and cross-call conditions=4000"); return 0;
#endif
    if (argc!=2) return 1;
    if (host_policy_negative_controls()) return 34;
    FILE *file=fopen(argv[1],"rb"); if (!file) return 2;
    rem_case vector; unsigned count=0,steps=0,partial=0,unsupported=0,masked_invalid=0;
    while (fread(&vector,sizeof vector,1,file)==1) {
        ++count; x87_state after=vector.input,outer,before;
        unsigned iterations=0; uint32_t native_status=0;
        set_inputs(vector.left,vector.right,(uint16_t)vector.cw);
        do {
            if (++iterations>128) return 3;
            native_status=0; unsigned char widened[10]; uint64_t expected=0;
            if (!vector.guard) {
                x87_state next; oracle_step(&after,(int)vector.nearest,&next); after=next;
                memcpy(&native_status,after.bytes+4,2);
                if (!((native_status&0x3Fu)&~vector.cw))
                    expected=oracle_project(&after,(uint16_t)vector.cw,widened);
            }
            int rejected=vector.guard||((native_status&0x3Fu)&~vector.cw);
            unsigned previous_traps=trap_count; int old_cc=void_fpu_cmp; uint64_t old_result;
            g_eax=0xA15B20C3u; g_ecx=0xEC3A45B1u; g_edx=0xD23A45B1u;
            g_ebx=0xB15B20C3u; g_esi=0x515B20C3u; g_edi=0xD15B20C3u; g_ebp=0xB25B20C3u;
            void_flag_k=FK_EFLAGS; void_flag_a=0xD5u; void_flag_b=0; void_flag_cf=1;
            for (int i=2;i<8;i++) { uint64_t raw=0x400C000000000000ull+i; memcpy(g_st+i,&raw,8); }
            for (int i=1;i<8;i++) g_st_i64[i]=0x123456789ABCDEFll+i;
            memcpy(&old_result,g_st,8);
            double other[7]; memcpy(other,g_st+1,sizeof other);
            int64_t shadows[7]; memcpy(shadows,g_st_i64+1,sizeof shadows);
            uint32_t registers[8]={g_eax,g_ecx,g_edx,g_esp,g_ebx,g_esi,g_edi,g_ebp};
            uint32_t flags[4]={void_flag_k,void_flag_a,void_flag_b,void_flag_cf};
            host_seed(count,&outer,&before);
            call_guest(vector.nearest?sub_22002000:sub_22001000);
            int preserved=host_finish(&outer,&before);
            uint64_t actual; memcpy(&actual,g_st,8);
            if (!preserved) {
                printf("host state mismatch case %u iteration %u nearest=%u guest_cw=%04X\n",
                    count,iterations,vector.nearest,vector.cw);
                print_host_diff(&before);
                return 4;
            }
            if (rejected) {
                ++unsupported;
                if (trap_count!=previous_traps+1||trap_address!=(vector.nearest?0x22002000u:0x22001000u)||
                    actual!=old_result||void_fpu_cmp!=old_cc) return 5;
                break;
            }
            if (trap_count!=previous_traps||actual!=expected) {
                printf("result mismatch case %u iteration %u native=%016llX lifted=%016llX trap=%s\n",
                    count,iterations,expected,actual,trap_reason?trap_reason:""); return 6;
            }
            uint16_t defined=(native_status&0x3Fu)?0:(native_status&0x0400u)?0x0400u:0x4700u;
            if ((condition_word()&defined)!=(native_status&defined)) return 7;
            if (g_fp_top!=2||g_fpu_cw!=vector.cw||memcmp(other,g_st+1,sizeof other)||
                memcmp(shadows,g_st_i64+1,sizeof shadows)) return 8;
            uint32_t current[8]={g_eax,g_ecx,g_edx,g_esp,g_ebx,g_esi,g_edi,g_ebp};
            uint32_t current_flags[4]={void_flag_k,void_flag_a,void_flag_b,void_flag_cf};
            if (memcmp(current,registers,sizeof current)||memcmp(flags,current_flags,sizeof flags)) return 9;
            ++steps;
            if (native_status&0x3Fu) { ++masked_invalid; break; }
            if ((vector.left&0x7FF0000000000000ull)==0x7FF0000000000000ull||
                (vector.right&0x7FF0000000000000ull)==0x7FF0000000000000ull) break;
            if (memcmp(widened,after.bytes+28,10)) return 10;
            if (native_status&0x0400u) ++partial;
        } while (native_status&0x0400u);
    }
    if (ferror(file)||!feof(file)) return 11; fclose(file);
    if (!partial||!unsupported||!masked_invalid) return 12;
    int context=context_tests(); if (context) return context;
    /* Depth and reserved precision are explicit unsupported states. */
    unsigned previous=trap_count; g_fp_top=1; call_guest(sub_22001000);
    if (trap_count!=previous+1) return 32;
    set_inputs(0x3FF0000000000000ull,0x4000000000000000ull,0x017F);
    previous=trap_count; call_guest(sub_22002000); if (trap_count!=previous+1) return 33;
    printf("PASS cases=%u steps=%u partial=%u unsupported=%u masked_invalid=%u thread_yields=%d host_full_images=%u host_metadata_zeroings=%u host_pending_full_images=%u verified_amd=%d host_policy_negative_controls=PASS\n",
        count,steps,partial,unsupported,masked_invalid,thread_yields,strict_host_images,metadata_zeroings,pending_host_images,verified_amd);
    mach_leave(); return 0;
}

const recomp_dispatch_entry_t recomp_dispatch_table[]={
    {0x22001000u,sub_22001000},{0x22002000u,sub_22002000},{0x22003000u,sub_22003000},
    {0x22004000u,sub_22004000},{0x22005000u,sub_22005000},{0x22006000u,sub_22006000},
    {0x22007000u,sub_22007000},{0x22008000u,sub_22008000},{0x22009000u,sub_22009000},
    {0x2200A000u,sub_2200A000},{0x2200B000u,sub_2200B000},{0x2200C000u,sub_2200C000},
    {0x2200D000u,sub_2200D000},{0x2200E000u,outer_callback},{0x2200F000u,inner_callback}};
const uint32_t recomp_dispatch_count=15;
