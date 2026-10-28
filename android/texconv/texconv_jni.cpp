/* JNI for org.thevoid.port.Textures (the launcher's texture conversion). */
#include <jni.h>

#include "texconv.h"

namespace {

struct Path {
    JNIEnv *env;
    jstring string;
    const char *chars;
    Path(JNIEnv *e, jstring s) : env(e), string(s), chars(s ? e->GetStringUTFChars(s, nullptr) : nullptr) {}
    ~Path() { if (chars) env->ReleaseStringUTFChars(string, chars); }
};

jlongArray longs(JNIEnv *env, const jlong *values, jsize count)
{
    jlongArray out = env->NewLongArray(count);
    if (out) env->SetLongArrayRegion(out, 0, count, values);
    return out;
}

}  // namespace

extern "C" {

/* {textures, bytes, estimate ETC2, estimate ASTC, free bytes, converted format, converted textures,
 *  converted bytes, current}, or null with the reason in nativeMessage. */
JNIEXPORT jlongArray JNICALL Java_org_thevoid_port_Textures_nativeScan(JNIEnv *env, jclass, jstring game)
{
    Path path(env, game);
    if (!path.chars) return nullptr;
    texconv_status s;
    if (texconv_scan(path.chars, &s)) return nullptr;
    const jlong values[] = {s.textures, s.bytes, s.estimate_etc2, s.estimate_astc, s.free_bytes, s.converted,
                            s.converted_textures, s.converted_bytes, s.current};
    return longs(env, values, sizeof values / sizeof *values);
}

JNIEXPORT jint JNICALL Java_org_thevoid_port_Textures_nativeConvert(JNIEnv *env, jclass, jstring game, jint format, jint threads)
{
    Path path(env, game);
    return path.chars ? texconv_convert(path.chars, format, threads) : -1;
}

JNIEXPORT jint JNICALL Java_org_thevoid_port_Textures_nativeRemove(JNIEnv *env, jclass, jstring game)
{
    Path path(env, game);
    return path.chars ? texconv_remove(path.chars) : -1;
}

JNIEXPORT void JNICALL Java_org_thevoid_port_Textures_nativeCancel(JNIEnv *, jclass) { texconv_cancel(); }

/* {state, done, total, bytes done, bytes total} */
JNIEXPORT jlongArray JNICALL Java_org_thevoid_port_Textures_nativeProgress(JNIEnv *env, jclass)
{
    texconv_progress p;
    texconv_get_progress(&p);
    const jlong values[] = {p.state, p.done, p.total, p.bytes_done, p.bytes_total};
    return longs(env, values, sizeof values / sizeof *values);
}

JNIEXPORT jstring JNICALL Java_org_thevoid_port_Textures_nativeMessage(JNIEnv *env, jclass)
{
    texconv_progress p;
    texconv_get_progress(&p);
    return env->NewStringUTF(p.message);
}

}
