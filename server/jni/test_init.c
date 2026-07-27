#include <android/log.h>
#include <dlfcn.h>

static void init_func(void) {
    __android_log_print(ANDROID_LOG_INFO, "TestInit", "constructor fired!");
    void* h = dlopen("libxigncode.so", RTLD_NOW | RTLD_GLOBAL);
    if (h) {
        __android_log_print(ANDROID_LOG_INFO, "TestInit", "dlopen libxigncode.so SUCCESS");
    } else {
        __android_log_print(ANDROID_LOG_INFO, "TestInit", "dlopen libxigncode.so FAILED: %s", dlerror());
    }
}

void (*init_array_entry)(void) __attribute__((section(".init_array"), used)) = &init_func;
