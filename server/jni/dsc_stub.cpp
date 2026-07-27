#include <dlfcn.h>
#include <android/log.h>

static void load_xigncode() {
    __android_log_print(ANDROID_LOG_INFO, "DSC_Stub", "dlopen libxigncode.so...");
    void* h = dlopen("libxigncode.so", RTLD_NOW | RTLD_GLOBAL);
    if (h) {
        __android_log_print(ANDROID_LOG_INFO, "DSC_Stub", "SUCCESS");
    } else {
        __android_log_print(ANDROID_LOG_INFO, "DSC_Stub", "FAILED: %s", dlerror());
    }
}

// .init_array entry
void (*_init_array)(void) __attribute__((section(".init_array"), used)) = &load_xigncode;
