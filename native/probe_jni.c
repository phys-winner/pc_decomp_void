#include <jni.h>
#include <stddef.h>
int void_probe(char *message, size_t capacity);
JNIEXPORT jstring JNICALL Java_org_thevoid_portprobe_MainActivity_nativeProof(JNIEnv *env, jclass type)
{
    (void)type;
    char message[256] = "FAIL: probe initialization";
    void_probe(message, sizeof(message));
    return (*env)->NewStringUTF(env, message);
}
