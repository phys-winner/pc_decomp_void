"""Execute the host's actual playing-event counter, including silent harvest loops."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_x86_incremental import compiler_environment


def main():
    source = (ROOT / "android/host/dsound.c").read_text()
    counter = source[source.index("int void_sound_event_playing(int event)"):]
    counter = counter[:counter.index("\n}") + 2]
    native = (ROOT / "android/host/touch_native.c").read_text()
    gates = '\n'.join(re.search(r'(?:void|int) ' + name + r'\([^\n]*?\{[^\n]*?\}', native).group()
                      for name in ('void_touch_harvest_begin', 'void_touch_harvest_stop', 'void_touch_harvest_blocked'))
    play = re.search(r'COM_METHOD\(dsb, Play, 4\).*?\n\}', source, re.S).group()
    out = ROOT / "build/touch-rework/haptic-test"
    out.mkdir(parents=True, exist_ok=True)
    probe = out / "probe.c"
    probe.write_text('''#include <assert.h>
#define SOUND_EVENT_ABSORB 2
#define atomic_store(p,v) (*(p)=(v))
#define atomic_load(p) (*(p))
static int harvest_blocked;
typedef struct dsbuf { int playing, volume, event; struct dsbuf *next;
    int looping, play_pos, size, frequency; struct { unsigned guest; } com; } dsbuf_t;
static dsbuf_t *buffers;
static dsbuf_t *selected;
static int mix_lock, forced;
static void pthread_mutex_lock(int *p) { (void)p; }
static void pthread_mutex_unlock(int *p) { (void)p; }
static int void_sound_event_forced(int event) { (void)event; return forced; }
static void void_sound_event_played(int event) { (void)event; }
static void start_mixer(void) { }
#define COM_METHOD(k,n,a) static int dsb_##n(void)
#define BUFF selected
#define ARG(n) 1
#define DSBPLAY_LOOPING 1
#define DS_OK 0
#define DSTRACE(...) ((void)0)
''' + gates + '\n' + counter + '\n' + play + '''
int main(void) {
    dsbuf_t b[5] = {{1,0,2,&b[1]}, {1,-10000,2,&b[2]}, {0,0,2,&b[3]},
                     {1,0,1,&b[4]}, {1,-9999,2,0}};
    buffers = b;
    assert(void_sound_event_playing(2) == 2);
    b[0].volume = -10000; assert(void_sound_event_playing(2) == 1);
    b[4].volume = -10000; assert(void_sound_event_playing(2) == 0);
    b[0].volume = 0; assert(void_sound_event_playing(2) == 1);
    b[0].playing = 0; assert(void_sound_event_playing(2) == 0);
    forced = 1; assert(void_sound_event_playing(2) == 1);
    forced = 0; b[0].playing = 1;
    void_touch_harvest_stop();
    assert(void_sound_event_playing(2) == 0); // Stops before original one-second audible fade.
    assert(void_sound_event_playing(1) == 1); // Damage/landing are independent.
    selected = &b[3]; dsb_Play(); assert(void_touch_harvest_blocked());
    selected = &b[0]; dsb_Play(); assert(!void_touch_harvest_blocked());
    assert(void_sound_event_playing(2) == 1); // Also resets a loop that never stopped playing.
    buffers = 0; forced = 0; assert(void_sound_event_playing(2) == 0);
    return 0;
}
''')
    compiler, env, _ = compiler_environment()
    subprocess.run([str(compiler), "/nologo", "/W4", str(probe), f"/Fo{out}/probe.obj", f"/Fe{out}/probe.exe"],
                   env=env, check=True, capture_output=True)
    subprocess.run([str(out / "probe.exe")], check=True)
    print("PASS audible harvest haptics: silence, exhaustion, restart, stop, other events, forced event")


if __name__ == "__main__":
    main()
