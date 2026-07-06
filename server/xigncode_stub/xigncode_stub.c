// Stub libxigncode.so for the KGC private server.
// Replaces Wellbia XIGNCODE3 with no-op JNI methods so the client boots and runs
// without the anti-tamper agent (which otherwise sabotages a random thread ~70s in,
// crashing the patched client). Server accepts any xigncode cookie/seed, so empty is fine.
// Build: <ndk>/armv7a-linux-androideabi21-clang -shared -fPIC -o libxigncode.so xigncode_stub.c
#include <jni.h>
#include <string.h>

static jint    z_int(JNIEnv* e, jclass c, ...)        { return 0; }
static void    z_void(JNIEnv* e, jclass c, ...)       { }
static jstring z_str(JNIEnv* e, jclass c, ...)        { return (*e)->NewStringUTF(e, ""); }

static const JNINativeMethod kMethods[] = {
    {"ZCWAVE_Initialize",            "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Lcom/wellbia/xigncode/XigncodeClientSystem$Callback;Lcom/wellbia/xigncode/XigncodeCallback;)I", (void*)z_int},
    {"ZCWAVE_InitializeEx",          "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Lcom/wellbia/xigncode/XigncodeClientSystem$Callback;Lcom/wellbia/xigncode/XigncodeCallback;Landroid/app/Activity;I)I", (void*)z_int},
    {"ZCWAVE_Cleanup",               "()I",                                    (void*)z_int},
    {"ZCWAVE_GetRevision",           "()I",                                    (void*)z_int},
    {"ZCWAVE_OnReceive",             "([B)I",                                  (void*)z_int},
    {"ZCWAVE_OnServerConnect",       "()I",                                    (void*)z_int},
    {"ZCWAVE_OnServerDisconnect",    "()I",                                    (void*)z_int},
    {"ZCWAVE_GetCooke",              "()Ljava/lang/String;",                   (void*)z_str},
    {"ZCWAVE_GetCookie2",            "(Ljava/lang/String;)Ljava/lang/String;", (void*)z_str},
    {"ZCWAVE_GetCookie3",            "(Ljava/lang/String;)Ljava/lang/String;", (void*)z_str},
    {"ZCWAVE_OnActivityPause",       "()V",                                    (void*)z_void},
    {"ZCWAVE_OnActivityResume",      "()V",                                    (void*)z_void},
    {"ZCWAVE_SetApplicationContext", "(Landroid/content/Context;)V",           (void*)z_void},
    {"ZCWAVE_SetDeviceId",           "(Ljava/lang/String;)V",                  (void*)z_void},
    {"ZCWAVE_SetResolutionInfo",     "(II)V",                                  (void*)z_void},
    {"ZCWAVE_SetUserInfo",           "(Ljava/lang/String;)V",                  (void*)z_void},
};

JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM* vm, void* reserved) {
    JNIEnv* env = 0;
    if ((*vm)->GetEnv(vm, (void**)&env, JNI_VERSION_1_6) != JNI_OK) return JNI_ERR;
    jclass cls = (*env)->FindClass(env, "com/wellbia/xigncode/XigncodeClientSystem");
    if (cls) {
        (*env)->RegisterNatives(env, cls, kMethods, sizeof(kMethods)/sizeof(kMethods[0]));
        if ((*env)->ExceptionCheck(env)) (*env)->ExceptionClear(env);
    }
    return JNI_VERSION_1_6;
}
