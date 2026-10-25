/* Android application glue: JNI from GameActivity, the native window, the
 * game thread, touch input in DirectInput scan codes, and AAudio output for
 * the DirectSound mixer. */
#ifdef VOID_ANDROID_APP
#define _GNU_SOURCE
#include "host.h"
#include "fonts.h"
#include "hud.h"
#include "input.h"
#include "sound_events.h"
#include "touch_native.h"
#include "shader_warm.h"
#include <aaudio/AAudio.h>
#include <android/native_window.h>
#include <android/native_window_jni.h>
#include <jni.h>
#include <math.h>
#include <time.h>
#include <unistd.h>

int void_game_main(const char *game, const char *data, const char *images, int selftest);
void void_process_exit(uint32_t code, int run_detach);
void void_d3dx_set_packaged_cache_dir(const char *dir);
uint64_t void_d3dx_missing_shader(void);

static ANativeWindow *window;
static pthread_mutex_t window_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t window_cond = PTHREAD_COND_INITIALIZER;
static pthread_t game_thread;
static int game_started;
static char game_dir[512], data_dir[512], images_dir[512];
static JavaVM *jvm;
static jobject activity;

/* The activity's surface comes and goes (Home, the app switcher, the screen
 * turning off): window_serial counts the changes, and the renderer takes a
 * new one up at its next present (d3d9_gl.c), acknowledging the serial it
 * has switched to; a destroyed surface waits (briefly) for that. */
static uint32_t window_serial, window_acked;
static _Atomic int audio_paused;
int void_audio_is_paused(void) { return audio_paused; }

/* d3d9_gl.c asks for the window when the game creates its device; wait for
 * the surface if the activity has not delivered it yet. */
void *void_android_window(void)
{
    pthread_mutex_lock(&window_lock);
    while (!window) pthread_cond_wait(&window_cond, &window_lock);
    ANativeWindow *w = window;
    pthread_mutex_unlock(&window_lock);
    return w;
}

/* The current window (NULL while the activity has none) and its serial; with
 * wait set, block until there is one. */
void *void_android_window_current(uint32_t *serial, int wait)
{
    pthread_mutex_lock(&window_lock);
    while (wait && !window) pthread_cond_wait(&window_cond, &window_lock);
    ANativeWindow *w = window;
    *serial = window_serial;
    pthread_mutex_unlock(&window_lock);
    return w;
}

void void_android_window_ack(uint32_t serial)
{
    pthread_mutex_lock(&window_lock);
    window_acked = serial;
    pthread_cond_broadcast(&window_cond);
    pthread_mutex_unlock(&window_lock);
}

static void *game_main(void *arg)
{
    (void)arg;
    int code = void_game_main(game_dir, data_dir, images_dir, 0);
    void_log("[android] game thread finished with %d", code);
    void_process_exit((uint32_t)code, 0);
    return NULL;
}

JNIEXPORT jint JNI_OnLoad(JavaVM *vm, void *reserved)
{
    (void)reserved;
    jvm = vm;
    return JNI_VERSION_1_6;
}

JNIEXPORT jboolean JNICALL Java_org_thevoid_port_GameActivity_nativeStart(JNIEnv *env, jobject self, jstring game,
    jstring data, jstring images, jstring shader_cache, jint screen_w, jint screen_h, jboolean verbose)
{
    if (game_started) return JNI_TRUE;
    const char *g = (*env)->GetStringUTFChars(env, game, NULL);
    const char *d = (*env)->GetStringUTFChars(env, data, NULL);
    const char *i = (*env)->GetStringUTFChars(env, images, NULL);
    const char *s = (*env)->GetStringUTFChars(env, shader_cache, NULL);
    snprintf(game_dir, sizeof game_dir, "%s", g);
    snprintf(data_dir, sizeof data_dir, "%s", d);
    snprintf(images_dir, sizeof images_dir, "%s", i);
    void_d3dx_set_packaged_cache_dir(s);
    (*env)->ReleaseStringUTFChars(env, game, g);
    (*env)->ReleaseStringUTFChars(env, data, d);
    (*env)->ReleaseStringUTFChars(env, images, i);
    (*env)->ReleaseStringUTFChars(env, shader_cache, s);
    activity = (*env)->NewGlobalRef(env, self);
    void_verbose = verbose ? 1 : 0;
    /* The render size the activity wrote into the profile's rcfg.xml: the
     * desktop the game sees and a display mode it may choose. */
    if (screen_w > 0 && screen_h > 0) {
        void_input_set_screen_size(screen_w, screen_h);
        void_display_prefer(screen_w, screen_h);
    }
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setstacksize(&attr, 64u << 20);
    game_started = pthread_create(&game_thread, &attr, game_main, NULL) == 0;
    pthread_attr_destroy(&attr);
    return game_started ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativeSurface(JNIEnv *env, jobject self, jobject surface)
{
    (void)self;
    pthread_mutex_lock(&window_lock);
    ANativeWindow *old = window;
    window = surface ? ANativeWindow_fromSurface(env, surface) : NULL;
    uint32_t serial = ++window_serial;
    pthread_cond_broadcast(&window_cond);
    if (!surface && old) {
        /* Android wants the EGL surface gone before surfaceDestroyed returns;
         * the game thread lets it go at its next present. A game busy
         * loading may not present for a while: do not hold the UI thread
         * long (EGL keeps its own reference to the window meanwhile). */
        struct timespec until;
        clock_gettime(CLOCK_REALTIME, &until);
        until.tv_sec += 1;
        while (window_acked != serial && pthread_cond_timedwait(&window_cond, &window_lock, &until) == 0) {}
    }
    pthread_mutex_unlock(&window_lock);
    if (old) ANativeWindow_release(old);
}

/* onPause/onResume: the game itself waits in its present while it has no
 * surface; the audio stream pauses with the activity and the game's clock
 * stops, so no time passes in the game while it is away. */
JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativePause(JNIEnv *env, jobject self, jboolean paused)
{
    (void)env; (void)self;
    audio_paused = paused ? 1 : 0;
    void_clock_freeze(paused ? 1 : 0);
}

/* Scan code (DIK) based input from the touch layer. */
static uint32_t dik_to_vk(uint32_t dik)
{
    for (uint32_t vk = 1; vk < 256; ++vk) if (void_vk_to_dik(vk) == dik) return vk;
    return 0;
}

JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativeKey(JNIEnv *env, jobject self, jint scan, jboolean down)
{
    (void)env; (void)self;
    uint32_t vk = dik_to_vk((uint32_t)scan);
    if (vk) void_input_key(vk, down);
}

JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativeMouseButton(JNIEnv *env, jobject self, jint button, jboolean down)
{
    (void)env; (void)self;
    void_input_mouse_button(button, down);
}

/* A point of the view in [0,1] as game pixels, undoing the present's
 * aspect-preserving fit (d3d9_gl.c). */
static void view_to_game(float x, float y, int *gx, int *gy)
{
    int w, h;
    void_input_screen_size(&w, &h);
    float sw = window ? (float)ANativeWindow_getWidth(window) : (float)w;
    float sh = window ? (float)ANativeWindow_getHeight(window) : (float)h;
    float scale = sw / (float)w < sh / (float)h ? sw / (float)w : sh / (float)h;
    float dx = (sw - (float)w * scale) / 2.0f, dy = (sh - (float)h * scale) / 2.0f;
    *gx = (int)((x * sw - dx) / scale);
    *gy = (int)((y * sh - dy) / scale);
}

JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativeCursorPosition(JNIEnv *env, jclass cls, jfloatArray out)
{
    (void)cls;
    if (!out || (*env)->GetArrayLength(env, out) < 2) return;
    int w, h;
    uint32_t x, y;
    void_input_screen_size(&w, &h);
    void_input_cursor(&x, &y);
    float sw = window ? (float)ANativeWindow_getWidth(window) : (float)w;
    float sh = window ? (float)ANativeWindow_getHeight(window) : (float)h;
    if (w <= 0 || h <= 0 || sw <= 0 || sh <= 0) return;
    float scale = fminf(sw / w, sh / h);
    jfloat position[2] = {(x * scale + (sw - w * scale) / 2) / sw,
                         (y * scale + (sh - h * scale) / 2) / sh};
    (*env)->SetFloatArrayRegion(env, out, 0, 2, position);
}

/* Relative motion in game pixels, or an absolute position in [0,1]. */
JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativeMouseMove(JNIEnv *env, jobject self, jfloat x, jfloat y, jboolean relative)
{
    (void)env; (void)self;
    if (relative) {
        void_input_mouse_move((int)x, (int)y);
    } else {
        void_touch_body_target_reset();
        int nx, ny;
        uint32_t cx, cy;
        view_to_game(x, y, &nx, &ny);
        /* The cursor goes there by mouse motion where the game shows one (a
         * menu follows the motion). Without a cursor the game is back in the
         * world, where that motion would turn the camera: just put it there. */
        if (!void_hud_cursor_recent(3)) {
            void_input_mouse_warp(nx, ny);
            return;
        }
        void_input_cursor(&cx, &cy);
        void_input_mouse_move(nx - (int)cx, ny - (int)cy);
    }
}

JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativeMouseWheel(JNIEnv *env, jobject self, jint delta)
{
    (void)env; (void)self;
    void_input_mouse_wheel(delta);
}

JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativeMovement(JNIEnv *env, jclass cls, jfloat x, jfloat y)
{
    (void)env; (void)cls;
    void_touch_movement(x, y);
}

JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativeSetGameplayOptions(JNIEnv *env, jclass cls, jfloat fov, jfloat veins)
{
    (void)env; (void)cls;
    void_touch_gameplay_options(fov, veins);
}

JNIEXPORT jboolean JNICALL Java_org_thevoid_port_GameActivity_nativeConsoleCommand(JNIEnv *env, jclass cls, jstring command)
{
    (void)cls;
    if (!command) return JNI_FALSE;
    const char *text = (*env)->GetStringUTFChars(env, command, NULL);
    if (!text) return JNI_FALSE;
    int accepted = void_touch_console(text);
    (*env)->ReleaseStringUTFChars(env, command, text);
    return accepted ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT jint JNICALL Java_org_thevoid_port_GameActivity_nativeBodyTarget(JNIEnv *env, jclass cls)
{
    (void)env; (void)cls;
    return void_touch_body_target();
}

JNIEXPORT jint JNICALL Java_org_thevoid_port_GameActivity_nativeBodyTransferColour(JNIEnv *env, jclass cls)
{
    (void)env; (void)cls;
    return void_touch_body_transfer_colour();
}

JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativeBodyAmounts(JNIEnv *env, jclass cls, jfloatArray out)
{
    (void)cls;
    if (!out || (*env)->GetArrayLength(env, out) < 28) return;
    float values[28];
    void_touch_body_amounts(values);
    (*env)->SetFloatArrayRegion(env, out, 0, 28, values);
}

JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativeBodyDetails(JNIEnv *env, jclass cls, jfloatArray out)
{
    (void)cls;
    if (!out || (*env)->GetArrayLength(env, out) < 14) return;
    float values[14];
    void_touch_body_details(values);
    (*env)->SetFloatArrayRegion(env, out, 0, 14, values);
}

/* The hearts a carried Memory colour can go into, as the body's script
 * publishes them (touch_native.c): zone, x, y (the game's pixels), current,
 * maximum each. Returns the count. */
JNIEXPORT jint JNICALL Java_org_thevoid_port_GameActivity_nativeZoneLabels(JNIEnv *env, jclass cls, jfloatArray out)
{
    (void)cls;
    if (!out || (*env)->GetArrayLength(env, out) < 21 * 5) return 0;
    float values[21 * 5];
    int n = void_touch_zone_labels(values);
    if (n) (*env)->SetFloatArrayRegion(env, out, 0, 5 * n, values);
    return n;
}

JNIEXPORT jstring JNICALL Java_org_thevoid_port_GameActivity_nativeBodyStatName(JNIEnv *env, jclass cls, jint colour)
{
    (void)cls;
    char name[256];
    void_touch_body_stat_name(colour, name);
    return (*env)->NewStringUTF(env, name);
}

JNIEXPORT jobjectArray JNICALL Java_org_thevoid_port_GameActivity_nativeHintTexts(JNIEnv *env, jclass cls)
{
    (void)cls;
    char texts[56][256];
    if (!void_touch_hint_texts(texts)) return NULL;
    jclass string_class = (*env)->FindClass(env, "java/lang/String");
    if (!string_class) return NULL;
    jobjectArray result = (*env)->NewObjectArray(env, 56, string_class, NULL);
    if (!result) return NULL;
    for (int i = 0; i < 56; ++i) {
        jstring text = (*env)->NewStringUTF(env, texts[i]);
        if (!text) return NULL;
        (*env)->SetObjectArrayElement(env, result, i, text);
        (*env)->DeleteLocalRef(env, text);
    }
    return result;
}

JNIEXPORT jint JNICALL Java_org_thevoid_port_GameActivity_nativeBrushColour(JNIEnv *env, jclass cls)
{
    (void)env; (void)cls;
    return void_touch_brush_colour();
}

JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativeCancelStroke(JNIEnv *env, jclass cls)
{
    (void)env; (void)cls;
    void_touch_cancel_stroke();
}

/* What the last presented frame showed (hud.h): the cursor and the helper
 * icons, in the low 32 bits; the count of presented frames in the high ones. */
JNIEXPORT jlong JNICALL Java_org_thevoid_port_GameActivity_nativeHudState(JNIEnv *env, jclass cls)
{
    (void)env; (void)cls;
    uint32_t frame = 0, tags = void_hud_state(&frame);
    return (jlong)(((uint64_t)frame << 32) | tags);
}

uint32_t void_d3dx_cache_responses(void);
uint32_t d3d_shader_compile_count(void);

/* The original effect-cache generation and the driver's GPU compilation both
 * continue after Java has copied the packaged bytecode. No total is known. */
JNIEXPORT jlong JNICALL Java_org_thevoid_port_GameActivity_nativeShaderProgress(JNIEnv *env, jclass cls)
{
    (void)env; (void)cls;
    return (jlong)(((uint64_t)d3d_shader_compile_count() << 32) | void_d3dx_cache_responses());
}

JNIEXPORT jlong JNICALL Java_org_thevoid_port_GameActivity_nativeMissingShader(JNIEnv *env, jclass cls)
{
    (void)env; (void)cls;
    return (jlong)void_d3dx_missing_shader();
}

JNIEXPORT jlong JNICALL Java_org_thevoid_port_GameActivity_nativeShaderWarmup(JNIEnv *env, jclass cls)
{
    (void)env; (void)cls;
    return (jlong)d3d_shader_warm_progress();
}

/* The measured HUD images (hud.h): out receives HUD_SLOTS * HUD_SLOT_FLOATS
 * floats; returns the mask of slots drawn in the last presented frame. */
JNIEXPORT jint JNICALL Java_org_thevoid_port_GameActivity_nativeHudSlots(JNIEnv *env, jclass cls, jfloatArray out)
{
    (void)cls;
    static float values[HUD_SLOTS][HUD_SLOT_FLOATS];
    uint32_t mask = void_hud_slots(values);
    if (out && (*env)->GetArrayLength(env, out) >= HUD_SLOTS * HUD_SLOT_FLOATS)
        (*env)->SetFloatArrayRegion(env, out, 0, HUD_SLOTS * HUD_SLOT_FLOATS, &values[0][0]);
    return (jint)mask;
}

/* Sounds the touch layer vibrates to (sound_events.h): out[0..2] count the
 * plays of landing, damage and colour-sucking sounds, out[3] is how many
 * sucking sounds are playing now. */
JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativeSoundEvents(JNIEnv *env, jclass cls, jintArray out)
{
    (void)cls;
    uint32_t counts[SOUND_EVENTS];
    void_sound_events(counts);
    jint values[4] = { (jint)counts[SOUND_EVENT_LAND], (jint)counts[SOUND_EVENT_DAMAGE], (jint)counts[SOUND_EVENT_ABSORB],
                       (jint)void_sound_event_playing(SOUND_EVENT_ABSORB) };
    if (out && (*env)->GetArrayLength(env, out) >= 4) (*env)->SetIntArrayRegion(env, out, 0, 4, values);
}

/* A picture the game has saved since the last call (its screenshot), or null. */
JNIEXPORT jstring JNICALL Java_org_thevoid_port_GameActivity_nativeSavedPicture(JNIEnv *env, jclass cls)
{
    (void)cls;
    char *path = void_picture_saved();
    if (!path) return NULL;
    jstring s = (*env)->NewStringUTF(env, path);
    free(path);
    return s;
}

/* The size the game's picture is drawn at, before the game starts: its
 * targets of the screen's size are drawn that large while the game lays
 * out its interface in the size it was given (d3d9_resource.c). */
void d3d_set_physical_size(uint32_t w, uint32_t h);

JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativeSetPhysicalSize(JNIEnv *env, jclass cls, jint w, jint h)
{
    (void)env; (void)cls;
    if (w > 0 && h > 0) d3d_set_physical_size((uint32_t)w, (uint32_t)h);
}

/* The display's refresh rate, before the game starts: the physics' fixed
 * step follows it (physx.c). */
void void_physics_set_display_rate(float hz);

JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativeSetDisplayRate(JNIEnv *env, jclass cls, jfloat hz)
{
    (void)env; (void)cls;
    void_physics_set_display_rate(hz);
}

/* The interface scale for the game's text (fonts.c), before the game starts. */
JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativeSetFontScale(JNIEnv *env, jclass cls, jfloat scale)
{
    (void)env; (void)cls;
    void_fonts_set_scale(scale);
}

JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativeSetCursorHidden(JNIEnv *env, jclass cls, jboolean hidden)
{
    (void)env; (void)cls;
    void_hud_set_cursor_hidden(hidden);
}

JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativeSetHudHidden(JNIEnv *env, jclass cls, jint tags)
{
    (void)env; (void)cls;
    void_hud_set_hidden((uint32_t)tags);
}

/* A still menu's lower rate: the least time between presents, microseconds (hud.h). */
JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativeSetFramePeriod(JNIEnv *env, jclass cls, jint microseconds)
{
    (void)env; (void)cls;
    void_hud_set_frame_period(microseconds > 0 ? (uint32_t)microseconds : 0);
}

/* Double clicks on or off for the screen shown (input.h). */
JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativeSetDoubleClicks(JNIEnv *env, jclass cls, jboolean on)
{
    (void)env; (void)cls;
    void_input_set_double_clicks(on);
}

/* The window keeps its picture for up to ms milliseconds while the game goes
 * on (a screen change the layer hides), 0 lets go (hud.h). */
JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativeHoldPicture(JNIEnv *env, jclass cls, jint ms)
{
    (void)env; (void)cls;
    void_hud_hold_picture(ms > 0 ? (uint32_t)ms : 0);
}

/* Put the cursor at a point of the view in [0,1] without mouse motion (a
 * paint stroke starts under the finger instead of turning the camera). */
JNIEXPORT void JNICALL Java_org_thevoid_port_GameActivity_nativeMouseWarp(JNIEnv *env, jobject self, jfloat x, jfloat y)
{
    (void)env; (void)self;
    int nx, ny;
    view_to_game(x, y, &nx, &ny);
    void_input_mouse_warp(nx, ny);
}

/* ------------------------------------------------------------- audio */
static AAudioStream *stream;
static pthread_mutex_t audio_lock = PTHREAD_MUTEX_INITIALIZER;

static void close_audio_stream(void)
{
    if (!stream) return;
    AAudioStream_requestStop(stream);
    AAudioStream_close(stream);
    stream = NULL;
}

void void_audio_output(const int16_t *frames, uint32_t count)
{
    pthread_mutex_lock(&audio_lock);
    /* A paused Android route can be disconnected; reopen it on return. */
    if (audio_paused) {
        close_audio_stream();
        pthread_mutex_unlock(&audio_lock);
        usleep((useconds_t)((uint64_t)count * 1000000u / 48000u));
        return;
    }
    if (!stream) {
        AAudioStreamBuilder *b = NULL;
        aaudio_result_t result = AAudio_createStreamBuilder(&b);
        if (result == AAUDIO_OK) {
            AAudioStreamBuilder_setFormat(b, AAUDIO_FORMAT_PCM_I16);
            AAudioStreamBuilder_setChannelCount(b, 2);
            AAudioStreamBuilder_setSampleRate(b, 48000);
            AAudioStreamBuilder_setPerformanceMode(b, AAUDIO_PERFORMANCE_MODE_LOW_LATENCY);
            AAudioStreamBuilder_setUsage(b, AAUDIO_USAGE_GAME);
            AAudioStreamBuilder_setContentType(b, AAUDIO_CONTENT_TYPE_MUSIC);
            result = AAudioStreamBuilder_openStream(b, &stream);
            if (result == AAUDIO_OK) result = AAudioStream_requestStart(stream);
            AAudioStreamBuilder_delete(b);
        }
        if (result != AAUDIO_OK) {
            void_log("[audio] open/start failed: %d; will retry", (int)result);
            close_audio_stream();
            pthread_mutex_unlock(&audio_lock);
            usleep(100000);
            return;
        }
        void_log("[audio] output started");
    }
    /* The mixer paces itself in real time; never block it for long. */
    int32_t written = AAudioStream_write(stream, frames, (int32_t)count, 20000000LL);
    if (written < 0) {
        void_log("[audio] write failed: %d; will reopen", (int)written);
        close_audio_stream();
        pthread_mutex_unlock(&audio_lock);
        usleep(100000);
        return;
    }
    /* Level of what reached the device, every 10 s of audio: silence or
     * underruns show up in the log rather than only by ear. */
    static uint32_t level_frames;
    static double level_sum;
    static int level_peak;
    for (uint32_t i = 0; i < (uint32_t)written * 2; ++i) {
        int v = frames[i] < 0 ? -frames[i] : frames[i];
        if (v > level_peak) level_peak = v;
        level_sum += (double)frames[i] * frames[i];
    }
    level_frames += (uint32_t)written;
    if (level_frames >= 48000u * 10u) {
        void_log("[audio] last 10 s: peak %d, rms %.0f, underruns %d", level_peak,
                 sqrt(level_sum / (2.0 * level_frames)), (int)AAudioStream_getXRunCount(stream));
        level_frames = 0;
        level_sum = 0;
        level_peak = 0;
    }
    pthread_mutex_unlock(&audio_lock);
}
#endif
