#include <dlfcn.h>
#include <jni.h>
#include <android/log.h>

#define LOG_TAG "LibMainWrap"

extern "C" jint JNI_OnLoad(JavaVM* vm, void* reserved) {
    __android_log_print(ANDROID_LOG_INFO, LOG_TAG, "JNI_OnLoad: loading libxigncode.so...");
    void* xh = dlopen("libxigncode.so", RTLD_NOW | RTLD_GLOBAL);
    if (xh) {
        __android_log_print(ANDROID_LOG_INFO, LOG_TAG, "libxigncode.so loaded OK");
    } else {
        __android_log_print(ANDROID_LOG_WARN, LOG_TAG, "libxigncode.so FAILED: %s", dlerror());
    }

    __android_log_print(ANDROID_LOG_INFO, LOG_TAG, "loading libmain_real.so...");
    void* mh = dlopen("libmain_real.so", RTLD_NOW);
    if (!mh) {
        __android_log_print(ANDROID_LOG_FATAL, LOG_TAG, "libmain_real.so FAILED: %s", dlerror());
        return JNI_VERSION_1_6;
    }

    auto real_onload = reinterpret_cast<jint(*)(JavaVM*, void*)>(dlsym(mh, "JNI_OnLoad"));
    if (!real_onload) {
        __android_log_print(ANDROID_LOG_FATAL, LOG_TAG, "dlsym JNI_OnLoad FAILED: %s", dlerror());
        return JNI_VERSION_1_6;
    }

    __android_log_print(ANDROID_LOG_INFO, LOG_TAG, "forwarding to real JNI_OnLoad...");
    return real_onload(vm, reserved);
}
