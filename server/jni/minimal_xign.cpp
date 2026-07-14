#include <android/log.h>

#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, "MinimalXign", __VA_ARGS__)

extern "C" JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM* vm, void* reserved) {
    LOGI("JNI_OnLoad called! Library is loaded.");
    return JNI_VERSION_1_6;
}
