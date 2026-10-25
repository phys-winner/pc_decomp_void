#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef unsigned GLuint;
typedef unsigned GLenum;
typedef struct { struct { uint32_t viewport[4]; } st; } d3d_device;
typedef struct { d3d_device *dev; uint32_t type, gl, ended; void *fence; } d3d_query;
enum { GL_QUERY_RESULT_AVAILABLE = 0x8867, GL_QUERY_RESULT = 0x8866,
       GL_SYNC_FLUSH_COMMANDS_BIT = 1, GL_TIMEOUT_EXPIRED = 0x911b,
       GL_ALREADY_SIGNALED = 0x911a, D3D_OK = 0, S_FALSE_D3D = 1 };
#define FOURCC(a,b,c,d) ((uint32_t)(a) | ((uint32_t)(b)<<8) | ((uint32_t)(c)<<16) | ((uint32_t)(d)<<24))
static uint32_t args[5], memory[16];
static d3d_device device;
static d3d_query query;
#define ARG(i) args[i]
#define MEM32(va) memory[(va)/4]
#define QRY (&query)
#define COM_METHOD(a,b,n) static uint32_t a##_##b(void)
static unsigned available, result_any, ready_after_flush, event_timeout;
static unsigned calls[16], call_count, blocked_reads;
static void record(unsigned call) { assert(call_count < 16); calls[call_count++] = call; }
static void glFlush(void) { record(1); if (ready_after_flush) available = 1; }
static void glGetQueryObjectuiv(GLuint name, GLenum parameter, GLuint *value)
{
    assert(name == 42);
    if (parameter == GL_QUERY_RESULT_AVAILABLE) { record(2); *value = available; }
    else { assert(parameter == GL_QUERY_RESULT); record(3); blocked_reads += !available; *value = result_any; }
}
static GLenum glClientWaitSync(void *fence, unsigned flags, uint64_t timeout)
{
    assert(fence == (void *)(uintptr_t)1 && flags == GL_SYNC_FLUSH_COMMANDS_BIT && timeout == 0);
    record(4); return event_timeout ? GL_TIMEOUT_EXPIRED : GL_ALREADY_SIGNALED;
}

/* PRODUCTION */

/* Exact prior method from resource SHA9eebdcfc21f1bb6f5483f539894d1ee8eed5e964168e424a1ce64e0b81949faf. */
static uint32_t original_GetData(void)
{
    d3d_query *q = QRY;
    uint32_t out = ARG(1), size = ARG(2);
    if (q->type == 4) {
        if (out && size >= 16) { MEM32(out) = FOURCC('C','A','C','H'); MEM32(out + 4) = 1; MEM32(out + 8) = 16; MEM32(out + 12) = 7; }
        return D3D_OK;
    }
    if (q->type == 8) {
        if (q->fence) {
            GLenum r = glClientWaitSync(q->fence, GL_SYNC_FLUSH_COMMANDS_BIT, 0);
            if (r == GL_TIMEOUT_EXPIRED) return S_FALSE_D3D;
        }
        if (out && size >= 4) MEM32(out) = 1;
        return D3D_OK;
    }
    if (!q->ended) { if (out && size >= 4) MEM32(out) = 0; return D3D_OK; }
    GLuint available = 0;
    glGetQueryObjectuiv(q->gl, GL_QUERY_RESULT_AVAILABLE, &available);
    if (!available && !(ARG(3) & 1u)) return S_FALSE_D3D;
    GLuint any = 0;
    glGetQueryObjectuiv(q->gl, GL_QUERY_RESULT, &any);
    if (out && size >= 4) MEM32(out) = any ? q->dev->st.viewport[2] * q->dev->st.viewport[3] : 0;
    return D3D_OK;
}

typedef struct { uint32_t returned, memory[16]; unsigned calls[16], count, blocked; } snapshot;
static void reset(unsigned type, unsigned ended, unsigned ready, unsigned flags, unsigned out, unsigned size,
                  unsigned any, unsigned timeout, unsigned fence)
{
    memset(&query, 0, sizeof query); query.type=type; query.ended=ended; query.gl=42;
    query.dev=&device; query.fence=(void *)(uintptr_t)fence;
    device.st.viewport[2]=2424; device.st.viewport[3]=1080;
    args[1]=out; args[2]=size; args[3]=flags;
    available=ready; result_any=any; ready_after_flush=0; event_timeout=timeout;
    call_count=blocked_reads=0;
    memset(calls,0,sizeof calls);
    for (unsigned i=0;i<16;i++) memory[i]=0xa5a50000u+i;
}
static snapshot capture(uint32_t returned)
{
    snapshot s; memset(&s,0,sizeof s); s.returned=returned; s.count=call_count; s.blocked=blocked_reads;
    memcpy(s.memory,memory,sizeof memory); memcpy(s.calls,calls,sizeof calls); return s;
}
int main(void)
{
    /* The default path must never read an unavailable result, including null polling. */
    reset(9,1,0,1,0,0,1,0,0);
    assert(qry_GetData()==S_FALSE_D3D && !blocked_reads);
    assert(call_count==2 && calls[0]==1 && calls[1]==2);
    unsigned cases=0, old_blocking=0;
    const unsigned types[]={4,8,9}, sizes[]={0,4,16};
    for(unsigned ti=0;ti<3;ti++)for(unsigned ended=0;ended<2;ended++)
    for(unsigned ready=0;ready<2;ready++)for(unsigned flags=0;flags<4;flags++)
    for(unsigned has_out=0;has_out<2;has_out++)for(unsigned si=0;si<3;si++)
    for(unsigned any=0;any<2;any++)for(unsigned timeout=0;timeout<2;timeout++)for(unsigned fence=0;fence<2;fence++) {
        unsigned type=types[ti],out=has_out?16:0,size=sizes[si];
        reset(type,ended,ready,flags,out,size,any,timeout,fence);
        snapshot original=capture(original_GetData()); old_blocking+=original.blocked;
        reset(type,ended,ready,flags,out,size,any,timeout,fence);
        uint32_t untouched[16];memcpy(untouched,memory,sizeof memory);
        snapshot fixed=capture(qry_GetData());
        assert(!blocked_reads);
        if(type!=9 || !ended) assert(!memcmp(&original,&fixed,sizeof original));
        else {
            assert(calls[0]==((flags&1)?1:2));
            assert(call_count==((flags&1)?1u:0u)+1u+(ready?1u:0u));
            assert(fixed.returned==(ready?D3D_OK:S_FALSE_D3D));
            if(!ready || !out || size<4)assert(!memcmp(untouched,memory,sizeof memory));
            else {
                assert(MEM32(out)==(any?2424u*1080u:0));
                untouched[out/4]=MEM32(out);assert(!memcmp(untouched,memory,sizeof memory));
            }
        }
        ++cases;
    }
    assert(cases==2304 && old_blocking>0);
    /* Flushing may make the result available immediately, and null polling remains safe. */
    for(unsigned out=0;out<2;out++) {
        reset(9,1,0,1,out?16:0,out?4:0,1,0,0);ready_after_flush=1;
        assert(qry_GetData()==D3D_OK && call_count==3 && calls[0]==1 && calls[1]==2 && calls[2]==3);
        assert(!blocked_reads);
    }
    printf("PASS query FLUSH: %u asynchronous cases; pending/ready/null/undersized outputs; EVENT/VCACHE unchanged; no unavailable-result reads\n",cases);
    return 0;
}
