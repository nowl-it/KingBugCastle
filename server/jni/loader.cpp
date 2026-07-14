#include <dlfcn.h>
#include <android/log.h>
#include <pthread.h>

#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, "XGLoader", __VA_ARGS__)

extern void* worker_thread(void* arg);

JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM* vm, void* reserved) {
    LOGI("JNI_OnLoad: dlopen libxigncode.so...");
    void* handle = dlopen("libxigncode.so", RTLD_NOW | RTLD_GLOBAL);
    if (handle) {
        LOGI("libxigncode.so loaded successfully");
    } else {
        LOGI("libxigncode.so failed: %s", dlerror());
        // Fallback: start worker thread directly from here
    }
    return JNI_VERSION_1_6;
}
