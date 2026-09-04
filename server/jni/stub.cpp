#include <jni.h>
#include <android/log.h>
#include <pthread.h>
#include <unistd.h>
#include <dlfcn.h>
#include <sys/mman.h>
#include <time.h>
#include <vector>
#include <string.h>
#include <stdio.h>
#include <sys/stat.h>
#include <errno.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <netdb.h>

// Globals for build-time binary patching of the glogin redirect
char g_kgc_glogin_host[64] = "127.0.0.1\0" "                                                   ";
char g_kgc_glogin_port[16] = "8080\0" "          ";
char g_kgc_glogin_scheme[9] = "http\0   ";
// Separate poll host/port: the browser opens glogin_host (domain, valid Cloudflare
// cert), but the native poller reaches the origin directly. Public builds use the
// origin's Caddy :80 route because this raw HTTP client cannot speak HTTPS.
char g_kgc_glogin_poll_host[64] = "127.0.0.1\0" "                                                   ";


#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, "XignCodeStub", __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, "XignCodeStub", __VA_ARGS__)

// --- XIGNCODE STUB METHODS ---
static jint     z_int(JNIEnv* e, jclass c, ...)       { return 0; }
static void     z_void(JNIEnv* e, jclass c, ...)      { }
static jstring  z_str(JNIEnv* e, jclass c, ...)       { return e->NewStringUTF(""); }
static jstring  z_str_seed(JNIEnv* e, jclass c, jstring seed) {
    if (!seed) return e->NewStringUTF("dummy_cookie");
    const char* utf = e->GetStringUTFChars(seed, nullptr);
    if (!utf) return e->NewStringUTF("dummy_cookie");
    // Return the seed itself as the cookie (server might accept non-empty)
    jstring result = e->NewStringUTF(utf);
    e->ReleaseStringUTFChars(seed, utf);
    return result;
}
static jboolean z_true(JNIEnv* e, jclass c, ...)      { return JNI_TRUE; }

static const JNINativeMethod kMethods[] = {
    {"ZCWAVE_Initialize",            "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Lcom/wellbia/xigncode/XigncodeClientSystem$Callback;Lcom/wellbia/xigncode/XigncodeCallback;)I", (void*)z_int},
    {"ZCWAVE_InitializeEx",          "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Lcom/wellbia/xigncode/XigncodeClientSystem$Callback;Lcom/wellbia/xigncode/XigncodeCallback;Landroid/app/Activity;I)I", (void*)z_int},
    {"ZCWAVE_Cleanup",               "()I",                                    (void*)z_int},
    {"ZCWAVE_GetRevision",           "()I",                                    (void*)z_int},
    {"ZCWAVE_OnReceive",             "([B)I",                                  (void*)z_int},
    {"ZCWAVE_OnServerConnect",       "()I",                                    (void*)z_int},
    {"ZCWAVE_OnServerDisconnect",    "()I",                                    (void*)z_int},
    {"ZCWAVE_GetCooke",              "()Ljava/lang/String;",                   (void*)z_str},
    {"ZCWAVE_GetCookie2",            "(Ljava/lang/String;)Ljava/lang/String;", (void*)z_str_seed},
    {"ZCWAVE_GetCookie3",            "(Ljava/lang/String;)Ljava/lang/String;", (void*)z_str_seed},
    {"ZCWAVE_OnActivityPause",       "()V",                                    (void*)z_void},
    {"ZCWAVE_OnActivityResume",      "()V",                                    (void*)z_void},
    {"ZCWAVE_SetApplicationContext", "(Landroid/content/Context;)V",           (void*)z_void},
    {"ZCWAVE_SetDeviceId",           "(Ljava/lang/String;)V",                  (void*)z_void},
    {"ZCWAVE_SetResolutionInfo",     "(II)V",                                  (void*)z_void},
    {"ZCWAVE_SetUserInfo",           "(Ljava/lang/String;)V",                  (void*)z_void},
};

// v171 adds a second XIGNCODE class, AppSignClientSystem (app-signature check),
// hit on Guest Login. Its native descriptors differ from XigncodeClientSystem
// (callbacks are erased to Object; extra Guard* value-obfuscation API). Without
// these registered, JNI falls back to a dynamic symbol lookup that our stub .so
// doesn't export -> UnsatisfiedLinkError -> NoClassDefFoundError -> login fails.
static const JNINativeMethod kAppSignMethods[] = {
    {"ZCWAVE_Initialize",            "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/Object;Ljava/lang/Object;)I", (void*)z_int},
    {"ZCWAVE_InitializeEx",          "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/Object;Ljava/lang/Object;Landroid/app/Activity;I)I", (void*)z_int},
    {"ZCWAVE_InitializeExEx",        "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/Object;Ljava/lang/Object;Landroid/content/Context;I)I", (void*)z_int},
    {"ZCWAVE_Cleanup",               "()I",                                    (void*)z_int},
    {"ZCWAVE_GetRevision",           "()I",                                    (void*)z_int},
    {"ZCWAVE_Notify",                "(I)V",                                   (void*)z_void},
    {"ZCWAVE_OnReceive",             "([B)I",                                  (void*)z_int},
    {"ZCWAVE_OnServerConnect",       "()I",                                    (void*)z_int},
    {"ZCWAVE_OnServerDisconnect",    "()I",                                    (void*)z_int},
    {"ZCWAVE_GetCooke",              "()Ljava/lang/String;",                   (void*)z_str},
    {"ZCWAVE_GetCookie2",            "(Ljava/lang/String;)Ljava/lang/String;", (void*)z_str_seed},
    {"ZCWAVE_GetCookie3",            "(Ljava/lang/String;)Ljava/lang/String;", (void*)z_str_seed},
    {"ZCWAVE_OnActivityPause",       "()V",                                    (void*)z_void},
    {"ZCWAVE_OnActivityResume",      "()V",                                    (void*)z_void},
    {"ZCWAVE_SetApplicationContext", "(Landroid/content/Context;)V",           (void*)z_void},
    {"ZCWAVE_SetDeviceId",           "(Ljava/lang/String;)V",                  (void*)z_void},
    {"ZCWAVE_SetResolutionInfo",     "(II)V",                                  (void*)z_void},
    {"ZCWAVE_SetUserInfo",           "(Ljava/lang/String;)V",                  (void*)z_void},
    {"ZCWAVE_GuardAlloc",            "()I",                                    (void*)z_int},
    {"ZCWAVE_GuardFree",             "(I)V",                                   (void*)z_void},
    {"ZCWAVE_GuardGetKey",           "(I)I",                                   (void*)z_int},
    {"ZCWAVE_GuardGetSalt",          "(I)I",                                   (void*)z_int},
    {"ZCWAVE_GuardGetTimestamp",     "(I)I",                                   (void*)z_int},
    {"ZCWAVE_GuardUpdateTimestamp",  "(I)V",                                   (void*)z_void},
    {"ZCWAVE_GuardValidate",         "(I)Z",                                   (void*)z_true},
    {"nativeOnHackDetectedCallback", "(ILjava/lang/String;)V",                 (void*)z_void},
};

void* worker_thread(void* arg);

static pthread_once_t init_once = PTHREAD_ONCE_INIT;

static void start_worker() {
    LOGI("Starting worker thread...");
    pthread_t t;
    pthread_create(&t, nullptr, worker_thread, nullptr);
    pthread_detach(t);
}

JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM* vm, void* reserved) {
    JNIEnv* env = 0;
    if (vm->GetEnv((void**)&env, JNI_VERSION_1_6) != JNI_OK) return JNI_ERR;
    // v171 loads "xigncode" from AppSignClientSystem.<clinit>, so XigncodeClientSystem
    // may not exist here. A failed FindClass leaves a pending exception; clear it
    // unconditionally or the NEXT JNI call (FindClass/RegisterNatives) aborts the VM.
    jclass cls = env->FindClass("com/wellbia/xigncode/XigncodeClientSystem");
    if (env->ExceptionCheck()) env->ExceptionClear();
    if (cls) {
        env->RegisterNatives(cls, kMethods, sizeof(kMethods)/sizeof(kMethods[0]));
        if (env->ExceptionCheck()) env->ExceptionClear();
    }
    jclass appsign = env->FindClass("com/wellbia/xigncode/AppSignClientSystem");
    if (env->ExceptionCheck()) env->ExceptionClear();
    if (appsign) {
        env->RegisterNatives(appsign, kAppSignMethods, sizeof(kAppSignMethods)/sizeof(kAppSignMethods[0]));
        if (env->ExceptionCheck()) env->ExceptionClear();
    }
    pthread_once(&init_once, start_worker);
    return JNI_VERSION_1_6;
}

// --- IL2CPP NATIVE POLLER ---
typedef void* (*il2cpp_domain_get_t)();
typedef void* (*il2cpp_thread_attach_t)(void* domain);
typedef void  (*il2cpp_thread_detach_t)(void* thread);
typedef void** (*il2cpp_domain_get_assemblies_t)(const void* domain, size_t* size);
typedef void* (*il2cpp_assembly_get_image_t)(const void* assembly);
typedef const char* (*il2cpp_image_get_name_t)(const void* image);
typedef void* (*il2cpp_class_from_name_t)(const void* image, const char* namespaze, const char* name);
typedef void* (*il2cpp_class_get_method_from_name_t)(const void* klass, const char* name, int argsCount);
typedef void* (*il2cpp_runtime_invoke_t)(const void* method, void* obj, void** params, void** exc);
typedef void* (*il2cpp_class_get_type_t)(const void* klass);
typedef void* (*il2cpp_type_get_object_t)(const void* type);
typedef int32_t (*il2cpp_string_length_t)(void* str);
typedef const uint16_t* (*il2cpp_string_chars_t)(void* str);

typedef void* (*il2cpp_class_get_field_from_name_t)(void* klass, const char* name);
typedef void (*il2cpp_field_get_value_t)(void* obj, void* field, void* value);
typedef void* (*il2cpp_class_get_parent_t)(void* klass);
typedef void* (*il2cpp_object_get_class_t)(void* obj);

std::string utf16_to_utf8(const uint16_t* chars, int32_t length) {
    std::string result;
    for (int i = 0; i < length; ++i) {
        uint32_t c = chars[i];
        // Combine a UTF-16 surrogate pair into one code point (emoji / astral chars),
        // else a lone high surrogate would be emitted as invalid UTF-8 and corrupt the string.
        if (c >= 0xD800 && c <= 0xDBFF && i + 1 < length) {
            uint16_t lo = chars[i + 1];
            if (lo >= 0xDC00 && lo <= 0xDFFF) {
                c = 0x10000 + ((c - 0xD800) << 10) + (lo - 0xDC00);
                ++i;
            }
        }
        if (c < 0x80) {
            result += (char)c;
        } else if (c < 0x800) {
            result += (char)(0xC0 | (c >> 6));
            result += (char)(0x80 | (c & 0x3F));
        } else if (c < 0x10000) {
            result += (char)(0xE0 | (c >> 12));
            result += (char)(0x80 | ((c >> 6) & 0x3F));
            result += (char)(0x80 | (c & 0x3F));
        } else {
            result += (char)(0xF0 | (c >> 18));
            result += (char)(0x80 | ((c >> 12) & 0x3F));
            result += (char)(0x80 | ((c >> 6) & 0x3F));
            result += (char)(0x80 | (c & 0x3F));
        }
    }
    return result;
}

typedef void* (*il2cpp_string_new_t)(const char*);
il2cpp_string_new_t str_new = nullptr;

typedef void (*AutoRegisterImplFunc)(void* _this, void* id, void* methodInfo);
AutoRegisterImplFunc origAutoRegisterImpl = nullptr;

void HookedAutoRegisterImpl(void* _this, void* id, void* methodInfo) {
    int len = id ? *(int32_t*)((char*)id + 0x10) : 0;
    if (len == 0) {
        static char device_id[64] = {0};
        if (device_id[0] == 0) {
            FILE* f = fopen("/data/data/com.nowl.castle/guest_id.txt", "r");
            if (f) {
                fgets(device_id, sizeof(device_id), f);
                fclose(f);
            } else {
                srand(time(NULL) ^ getpid());
                sprintf(device_id, "guest-%d-%d", rand(), rand());
                f = fopen("/data/data/com.nowl.castle/guest_id.txt", "w");
                if (f) {
                    fputs(device_id, f);
                    fclose(f);
                }
            }
            LOGI("HookedAutoRegisterImpl injected persistent ID: %s", device_id);
        }
        if (str_new) {
            id = str_new(device_id);
        }
    }
    if (origAutoRegisterImpl) origAutoRegisterImpl(_this, id, methodInfo);
}

struct Il2CppArray {
    void* klass;
    void* monitor;
    void* bounds;
    uint32_t max_length;
    void* vector[1];
};

void* GetIl2CppSymbol(void* handle, const char* symbol) {
    void* func = dlsym(handle, symbol);
    if (!func) {
        LOGE("Failed to dlsym %s", symbol);
    }
    return func;
}

typedef void (*UpdateFunc)(void* _this, void* methodInfo);
UpdateFunc origUpdate = nullptr;

void* getStatMethod = nullptr;
void* getNameMethod = nullptr;
void* resUnitField = nullptr;
void* allFieldUnitsField = nullptr;  // resolved by name - arm64 offset differs from arm32 dump
void* buffManagerField = nullptr;    // GameUnit.buffManager
void* unitsField = nullptr;          // BuffManager.units (List<Buff> of active buffs)
void* buffTypeField = nullptr;       // Buff.type (BuffType enum)
void* buffDataField = nullptr;       // Buff.buffData (ResourceBuffData, has master-data id)
void* resSkillField = nullptr;       // Buff.resSkill (ResourceSkill source)
void* buffTimeField = nullptr;       // Buff.time (float)
void* buffTotalTimeField = nullptr;  // Buff.totalTime (float; 0 = permanent/passive)
// ResourceBase.id is the first managed field -> absolute offset = il2cpp obj header (0x10 on 64-bit)
#define RES_ID(obj) (*(int32_t*)((char*)(obj) + 0x10))

// Buff.BuffType enum -> short label. ponytail: category only, not per-effect
// master-data name (that needs buffData/resSkill id resolution + XML lookup).
static const char* buffTypeName(int32_t t) {
    switch (t) {
        case 0:  return "BuffOpt";
        case 1:  return "Bind";
        case 2:  return "Item";
        case 3:  return "Tile";
        case 4:  return "Skill";
        case 5:  return "Syn";
        case 6:  return "Poten";
        case 7:  return "Event";
        case 8:  return "Custom";
        case 9:  return "Treasure";
        case 10: return "Acc";
        case 11: return "Rune";
        case 12: return "Mark";
        case 13: return "Global";
        case 14: return "Overcome";
        default: return "?";
    }
}
il2cpp_runtime_invoke_t rt_invoke = nullptr;
il2cpp_string_length_t str_len = nullptr;
il2cpp_string_chars_t str_chars = nullptr;
il2cpp_field_get_value_t f_get_val = nullptr;
il2cpp_object_get_class_t obj_get_class = nullptr;
il2cpp_class_get_method_from_name_t class_get_method = nullptr;
il2cpp_class_get_parent_t class_get_parent = nullptr;
il2cpp_class_get_field_from_name_t g_field_from_name = nullptr;

typedef void* (*il2cpp_string_new_t)(const char* str);


// --- Inbox (PostListItem.Set) hook: render server-supplied raw title/text ---
// Server marks a custom string with the "@raw:" prefix; the hook strips it and writes the
// remainder straight into the Text component, bypassing the Localizer key lookup. Mail without
// the prefix is left exactly as PostListItem.Set localized it (normal system/event mail).
typedef void (*SetFunc)(void* _this, void* data, void* methodInfo);
SetFunc origSet = nullptr;
void* pli_titleTextField = nullptr;   // PostListItem.titleText (UnityEngine.UI.Text)
void* pli_descTextField  = nullptr;   // PostListItem.descText
void* postDataTitleField = nullptr;   // PostData.title (lazy-resolved from arg class)
void* postDataTextField  = nullptr;   // PostData.text
void* setTextMethod      = nullptr;   // UnityEngine.UI.Text::set_text(string)

typedef double (*GetStatFunc)(void* _this, int32_t type, bool fromStatPanel, void* methodInfo);
GetStatFunc getStat = nullptr;

// --- Google login -> our web login (works around the GPGS package/cert wall) ---
// The client's Google button normally calls Google Play Games sign-in, which can't
// authenticate this repacked build. Detour it to Application.OpenURL(<web login>),
// so pressing it opens our /glogin page in the device browser instead. The browser
// reaches the server through the same adb-reverse loopback the game uses.
// reaches the server through the same adb-reverse loopback the game uses.
// For public XAPK builds, the python build script binary-patches g_kgc_glogin_host.

static char g_poll_id[160] = {0};
static volatile bool g_have_id = false;      // set by poll thread, read by Update
static bool g_login_done = false;
void* login_poll_thread(void* arg);

typedef void (*GoogleLoginFunc)(void* _this, void* methodInfo);
GoogleLoginFunc origGoogleLogin = nullptr;   // trampoline; unused - we skip GPGS entirely
void* g_openUrlMethod = nullptr;             // UnityEngine.Application::OpenURL(string)

void HookedGoogleLogin(void* _this, void* methodInfo) {
    char KGC_GLOGIN_URL[256];
    snprintf(KGC_GLOGIN_URL, sizeof(KGC_GLOGIN_URL), "%s://%s/glogin", g_kgc_glogin_scheme, g_kgc_glogin_host);
    LOGI("Google button -> opening web login %s", KGC_GLOGIN_URL);
    g_have_id = false;
    g_login_done = false;
    g_poll_id[0] = 0;
    pthread_t pt;
    pthread_create(&pt, nullptr, login_poll_thread, nullptr);
    if (g_openUrlMethod && str_new && rt_invoke) {
        void* url = str_new(KGC_GLOGIN_URL);
        void* params[1] = { url };
        void* exc = nullptr;
        rt_invoke(g_openUrlMethod, nullptr, params, &exc);
        if (exc) LOGE("Google hook: OpenURL threw an exception");
    } else {
        LOGE("Google hook: OpenURL not resolved (openUrl=%p new=%p invoke=%p)",
             g_openUrlMethod, (void*)str_new, (void*)rt_invoke);
    }
    // Intentionally NOT calling origGoogleLogin: the GPGS path is what we replace.
}

// --- Web-login return bridge (Piece 2) ---
// Application.absoluteURL is stripped from the client, so the app can't read the
// return deep link. Instead: the web flow parks the picked session token on the
// server; a background thread here polls /glogin/pending for it (native socket GET,
// off the main thread - a blocking fetch in Update would freeze the UI); and the
// Scene_Login.Update hook (main thread) applies it - set RestAPI.accessToken, call
// FetchInfo to load the lobby - because il2cpp/scene work must be on the Unity thread.
typedef void (*SLUpdateFunc)(void* _this, void* mi);
SLUpdateFunc origSceneLoginUpdate = nullptr;
void* g_authMethod = nullptr;                // Scene_Login::Auth(string id) - full login

static void write_abs_jump(void* at, void* dest);   // defined in the inline-hook section below

// Diagnostic: capture Scene_Lobby.Init's managed exception + stack trace.
// REMOVED: it wrapped Init in rt_invoke which caught a managed NRE (empty trace
// under ndk_translation) that was always there but masked by the SIGSEGV before
// LDR patches. The rt_invoke wrapper itself may interfere with Unity's init flow.
// Uncomment the block at the hook site to re-enable.

// GET /glogin/pending on origin.
// Follows HTTP redirects (301/302): if Location is https://, downgrades to HTTP and
// retries the configured poll port against the same origin host.
// Returns body length, or -1. Plain HTTP, plain text body (not a game-API route).
static int http_get_pending_once(const char* host, const char* port, char* buf, int buflen) {
    struct addrinfo hints, *res;
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    
    if (getaddrinfo(host, port, &hints, &res) != 0) {
        LOGE("http_get_pending: getaddrinfo failed for %s:%s", host, port);
        return -1;
    }
    
    int fd = socket(res->ai_family, res->ai_socktype, res->ai_protocol);
    if (fd < 0) {
        freeaddrinfo(res);
        return -1;
    }

    struct timeval tv = {3, 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
    
    if (connect(fd, res->ai_addr, res->ai_addrlen) != 0) { 
        close(fd); 
        freeaddrinfo(res);
        return -1; 
    }
    freeaddrinfo(res);
    
    char req[512];
    snprintf(req, sizeof(req), "GET /glogin/pending HTTP/1.0\r\nHost: %s:%s\r\n\r\n", host, port);
    write(fd, req, strlen(req));
    char resp[1024]; int total = 0, r;
    while ((r = read(fd, resp + total, sizeof(resp) - 1 - total)) > 0) {
        total += r; if (total >= (int)sizeof(resp) - 1) break;
    }
    close(fd);
    if (total <= 0) return -1;
    resp[total] = 0;

    // Check for 301/302 redirect
    if (total > 12 && (memcmp(resp, "HTTP/1.0 30", 10) == 0 || memcmp(resp, "HTTP/1.1 30", 10) == 0)) {
        char* loc = NULL;
        // Find Location header (case-insensitive search for "location:")
        char* p = resp;
        while (*p && p < resp + total) {
            if (strncasecmp(p, "location:", 9) == 0) {
                p += 9;
                while (*p == ' ') p++;
                loc = p;
                break;
            }
            char* nl = strchr(p, '\n');
            if (!nl) break;
            p = nl + 1;
        }
        if (loc) {
            // Trim to end of line
            char* eol = strchr(loc, '\r');
            if (!eol) eol = strchr(loc, '\n');
            if (eol) *eol = 0;
            LOGI("http_get_pending: following redirect to %s", loc);

            // Always keep the ORIGINAL host — the Location header may point at
            // a domain (e.g. kingbugcastle.id.vn) that goes through Cloudflare,
            // which would redirect HTTP→HTTPS again in an infinite loop.
            // Downgrade https→http while keeping the configured direct-origin port.
            const char* rport = g_kgc_glogin_port;
            if (strncasecmp(loc, "http://", 7) == 0) {
                rport = port;  // already http: keep original port
            }
            return http_get_pending_once(host, rport, buf, buflen);
        }
    }

    char* body = strstr(resp, "\r\n\r\n");
    if (!body) return -1;
    body += 4;
    int bl = strlen(body);
    while (bl > 0 && (body[bl-1]=='\n' || body[bl-1]=='\r' || body[bl-1]==' ')) body[--bl] = 0;
    if (bl <= 0 || bl >= buflen) return -1;
    memcpy(buf, body, bl + 1);
    return bl;
}

static int http_get_pending(char* buf, int buflen) {
    return http_get_pending_once(g_kgc_glogin_poll_host, g_kgc_glogin_port, buf, buflen);
}

void* login_poll_thread(void* arg) {
    for (int i = 0; i < 3600 && !g_have_id; ++i) {   // ~2h, stops on first id
        char id[160];
        int n = http_get_pending(id, sizeof(id));
        if (n > 0 && (unsigned char)id[0] > 0x20) {   // any non-empty account id
            strncpy(g_poll_id, id, sizeof(g_poll_id) - 1);
            g_have_id = true;
            LOGI("login poll: got account id '%s'", g_poll_id);
            break;
        }
        sleep(2);
    }
    return nullptr;
}

void HookedSceneLoginUpdate(void* _this, void* mi) {
    if (origSceneLoginUpdate) origSceneLoginUpdate(_this, mi);
    // Let the login scene settle before driving Auth - calling it in the first frames
    // of boot fails ("Unable to fetch player data"). ~120 frames ≈ 2s.
    static int frames = 0;
    if (++frames < 120) return;
    if (g_login_done || !g_have_id || !g_authMethod || !str_new || !rt_invoke) return;
    LOGI("web login: Scene_Login.Auth(\"%s\") - full handshake", g_poll_id);
    FILE* f = fopen("/data/data/com.nowl.castle/guest_id.txt", "w");
    if (f) {
        fputs(g_poll_id, f);
        fclose(f);
        LOGI("web login: persisted account ID '%s' to guest_id.txt", g_poll_id);
    }
    void* idstr = str_new(g_poll_id);
    void* params[1] = { idstr };
    void* exc = nullptr;
    rt_invoke(g_authMethod, _this, params, &exc);   // real auth -> HandleAuthResponse -> lobby
    if (exc) LOGE("web login: Scene_Login.Auth threw an exception");
    g_login_done = true;
}

// --- Scene_Lobby.Init GameManager-singleton guard ---
// Root cause of the black lobby (RE-confirmed via tombstone): Scene_Lobby.Init does
//   GameManager._singleton.Init()
// but reads _singleton (GameManager static field 0) as null, so GameManager.Init runs
// on a null `this` and derefs this+0x1b0 (_inited) -> SIGSEGV, which il2cpp reports as
// a NullReferenceException in Scene_Lobby.Init (black lobby, popups still render).
// _singleton is created in GameManager..cctor, which il2cpp's runtime_class_init should
// trigger before the static read - but under ndk_translation the class-init is marked
// done without the managed .cctor actually running, so _singleton stays null. Fix: on
// Init entry, if GameManager.Get() returns null, force the .cctor to run, then Init.
typedef void (*LobbyAwakeFunc)(void* _this, void* mi);
static LobbyAwakeFunc origLobbyAwake = nullptr;
static void* g_gmGet = nullptr;      // GameManager.Get()  -> _singleton
static void* g_gmCctor = nullptr;    // GameManager..cctor -> creates+assigns _singleton

// Hook Awake (not Init) because Scene_Lobby.Awake() -> Init() is a same-class
// direct call (compiler emits `bl` not via MethodInfo), so swapping Init's
// MethodInfo pointer never intercepts. Awake IS called by Unity via the
// MethodInfo table, so the pointer swap works here.
void HookedLobbyAwake(void* _this, void* mi) {
    LOGI("HookedLobbyAwake ENTER: this=%p mi=%p", _this, mi);
    if (g_gmGet && g_gmCctor && rt_invoke) {
        void* exc = nullptr;
        void* inst = rt_invoke(g_gmGet, nullptr, nullptr, &exc);
        LOGI("HookedLobbyAwake: GameManager.Get() = %p (exc=%p)", inst, exc);
        if (!inst) {
            LOGI("HookedLobbyAwake: GameManager._singleton is null - forcing .cctor");
            void* e2 = nullptr;
            rt_invoke(g_gmCctor, nullptr, nullptr, &e2);
            void* e3 = nullptr;
            inst = rt_invoke(g_gmGet, nullptr, nullptr, &e3);
            LOGI("HookedLobbyAwake: after forced .cctor, singleton=%p", inst);
        }
    } else {
        LOGI("HookedLobbyAwake: SKIP guard (gmGet=%p gmCctor=%p rt_invoke=%p)",
             g_gmGet, g_gmCctor, (void*)rt_invoke);
    }
    LOGI("HookedLobbyAwake: calling origLobbyAwake=%p", (void*)origLobbyAwake);
    if (origLobbyAwake) origLobbyAwake(_this, mi);
    LOGI("HookedLobbyAwake EXIT (origLobbyAwake returned)");
}

void HookedUpdate(void* _this, void* methodInfo) {
    if (origUpdate) {
        origUpdate(_this, methodInfo);
    }
    
    static long lastLogMs = 0;
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    long nowMs = ts.tv_sec * 1000L + ts.tv_nsec / 1000000L;
    if (nowMs - lastLogMs >= 500) {   // ~0.5s poll (was 5s) - keep web in sync with battle
        lastLogMs = nowMs;
        
        void* allFieldUnits = nullptr;
        if (allFieldUnitsField && f_get_val)
            f_get_val(_this, allFieldUnitsField, &allFieldUnits);
        if (allFieldUnits) {
            Il2CppArray* items = *(Il2CppArray**)((char*)allFieldUnits + 0x10);
            int32_t count = *(int32_t*)((char*)allFieldUnits + 0x18);
            
            if (count > 0 && count < 200 && items) {
                LOGI("Found %d GameUnit instances in BattleManager (Main Thread).", count);
                
                struct StatDef {
                    int32_t type;
                    const char* name;
                };
                // BuffManager.StatType enum values
                // Attack: 16=Atk, 17=MAtk, 35=Crit%, 38=CritDmg, 36=MCrit%, 39=MCritDmg, 15=ASpd, 19=Range,
                // 42=DefPen, 41=DefDen, 20=Drain, 21=MagicDrain, 45=SkillDmg, 46=AtkDmg, 47=AddAtk, 48=AddMAtk
                // Defense: 1=HP, 8=Def, 9=MDef, 10=SShield, 11=SAtkShld, 12=SMAtkShld, 58=Shield, 49=AddHP, 29=DmgReflect
                // Utility: 14=MSpd, 23=HealEff, 2=BaseMana, 3=MaxMana, 4=ManaAdapt, 5=AtkMana, 6=DmgMana
                StatDef statsToFetch[] = {
                    { 1, "HP" }, { 16, "ATK" }, { 17, "MATK" }, { 8, "Def" }, { 9, "MDef" },
                    { 35, "Crit%" }, { 38, "CritDmg" }, { 42, "DefPen" },
                    { 15, "ASpd" }, { 14, "MSpd" },
                    { 10, "SShield" }, { 11, "SAtkShld" }, { 12, "SMAtkShld" },
                    { 36, "MCrit%" }, { 39, "MCritDmg" },
                    { 20, "Drain" }, { 23, "HealEff" },
                    { 45, "SkillDmg" }, { 46, "AtkDmg" },
                    { 41, "DefDen" },
                    { 58, "Shield" }, { 29, "DmgRef" }
                };

                for (int32_t i = 0; i < count; ++i) {
                    if (i >= items->max_length) break;
                    void* unitObj = items->vector[i];
                    if (!unitObj) continue;
                    
                    void* nativeUnitPtr = *(void**)((char*)unitObj + 0x10);
                    if (!nativeUnitPtr) continue;

                    std::string unitName = "Unknown";
                    
                    if (resUnitField && f_get_val && obj_get_class && class_get_parent) {
                        void* resUnitObj = nullptr;
                        f_get_val(unitObj, resUnitField, &resUnitObj);
                        if (resUnitObj) {
                            void* resClass = obj_get_class(resUnitObj);
                            void* getResNameMethod = nullptr;
                            void* currentClass = resClass;
                            while (currentClass) {
                                getResNameMethod = class_get_method(currentClass, "get_name", 0);
                                if (getResNameMethod) break;
                                currentClass = class_get_parent(currentClass);
                            }
                            if (getResNameMethod) {
                                void* excResName = nullptr;
                                void* resNameStrObj = rt_invoke(getResNameMethod, resUnitObj, nullptr, &excResName);
                                if (resNameStrObj && !excResName) {
                                    int32_t len = str_len(resNameStrObj);
                                    const uint16_t* chars = str_chars(resNameStrObj);
                                    unitName = utf16_to_utf8(chars, len);
                                }
                            }
                        }
                    }
                    
                    if (unitName == "Unknown" || unitName.find("Clone") != std::string::npos) {
                        void* excName = nullptr;
                        void* nameStrObj = rt_invoke(getNameMethod, unitObj, nullptr, &excName);
                        if (nameStrObj && !excName) {
                            int32_t len = str_len(nameStrObj);
                            const uint16_t* chars = str_chars(nameStrObj);
                            unitName = utf16_to_utf8(chars, len);
                        }
                    }

                    // instance tag (#<hex>) = low 16 bits of the managed ptr, lets the
                    // server distinguish same-named units (e.g. multiple Goblin Scavenger)
                    char instTag[16];
                    snprintf(instTag, sizeof(instTag), "#%04x", (unsigned)((uintptr_t)unitObj & 0xffff));
                    std::string logLine = "[" + unitName + instTag + "]: ";
                    
                    for (auto& s : statsToFetch) {
                        double val = getStat(unitObj, s.type, false, getStatMethod);
                        char buffer[64];
                        snprintf(buffer, sizeof(buffer), "%s=%.0f, ", s.name, val);
                        logLine += buffer;
                    }

                    // active buffs/effects: GameUnit.buffManager -> units (List<Buff>) -> Buff.type
                    if (buffManagerField && unitsField && buffTypeField && f_get_val) {
                        void* bm = nullptr;
                        f_get_val(unitObj, buffManagerField, &bm);
                        if (bm) {
                            void* buffList = nullptr;
                            f_get_val(bm, unitsField, &buffList);
                            if (buffList) {
                                Il2CppArray* barr = *(Il2CppArray**)((char*)buffList + 0x10);
                                int32_t bcount = *(int32_t*)((char*)buffList + 0x18);
                                logLine += "Eff=";
                                char cbuf[16];
                                snprintf(cbuf, sizeof(cbuf), "%d[", bcount);
                                logLine += cbuf;
                                if (bcount > 0 && bcount < 100 && barr) {
                                    for (int32_t j = 0; j < bcount && j < (int32_t)barr->max_length; ++j) {
                                        void* buffObj = barr->vector[j];
                                        if (!buffObj) continue;
                                        if (j > 0) logLine += ",";
                                        // identity token: b<buffDataId> | s<skillId> | <category>.
                                        // server resolves ids -> names via BuffDatas/Skills master data.
                                        void* bd = nullptr;
                                        if (buffDataField) f_get_val(buffObj, buffDataField, &bd);
                                        char tok[24];
                                        if (bd) {
                                            snprintf(tok, sizeof(tok), "b%d", RES_ID(bd));
                                        } else {
                                            void* rs = nullptr;
                                            if (resSkillField) f_get_val(buffObj, resSkillField, &rs);
                                            if (rs) {
                                                snprintf(tok, sizeof(tok), "s%d", RES_ID(rs));
                                            } else {
                                                int32_t bt = 0;
                                                f_get_val(buffObj, buffTypeField, &bt);
                                                snprintf(tok, sizeof(tok), "%s", buffTypeName(bt));
                                            }
                                        }
                                        logLine += tok;
                                        // duration suffix @time/totalTime (only for timed buffs)
                                        float tm = 0.0f, tt = 0.0f;
                                        if (buffTimeField) f_get_val(buffObj, buffTimeField, &tm);
                                        if (buffTotalTimeField) f_get_val(buffObj, buffTotalTimeField, &tt);
                                        if (tt > 0.0f) {
                                            char tb[24];
                                            snprintf(tb, sizeof(tb), "@%.1f/%.1f", tm, tt);
                                            logLine += tb;
                                        }
                                    }
                                }
                                logLine += "]";
                            }
                        }
                    }
                    LOGI("%s", logLine.c_str());
                }
            }
        }
    }
}

static std::string readStr(void* strObj) {
    if (!strObj || !str_len || !str_chars) return std::string();
    int32_t len = str_len(strObj);
    if (len <= 0) return std::string();
    return utf16_to_utf8(str_chars(strObj), len);
}

// If PostData.<srcField> starts with "@raw:", write the remainder into PostListItem.<textField>.
static void applyRaw(void* data, void* srcField, void* self, void* textField) {
    if (!srcField || !textField || !f_get_val || !str_new || !setTextMethod || !rt_invoke) {
        LOGI("applyRaw: missing prereqs srcF=%p txtF=%p get=%p new=%p set=%p inv=%p",
             srcField, textField, (void*)f_get_val, (void*)str_new, (void*)setTextMethod, (void*)rt_invoke);
        return;
    }
    void* strObj = nullptr;
    f_get_val(data, srcField, &strObj);
    std::string s = readStr(strObj);
    LOGI("applyRaw: fieldVal='%s' (len=%zu)", s.c_str(), s.length());
    if (s.rfind("@raw:", 0) != 0) {
        LOGI("applyRaw: no @raw: prefix, skipping");
        return;
    }
    std::string raw = s.substr(5);
    LOGI("applyRaw: raw payload='%s'", raw.c_str());
    void* textObj = nullptr;
    f_get_val(self, textField, &textObj);
    LOGI("applyRaw: textObj=%p", textObj);
    if (!textObj) return;
    void* newStr = str_new(raw.c_str());
    void* params[1] = { newStr };
    void* exc = nullptr;
    rt_invoke(setTextMethod, textObj, params, &exc);
    if (exc) LOGI("applyRaw: exception on set_text!");
    else LOGI("applyRaw: set_text OK");
}

// --- arm64 inline detour ---------------------------------------------------
// methodPointer swap only intercepts engine-invoked methods (Update/OnEnable);
// PostListItem.Set is a direct C#->C# compiled call, so we patch its prologue with
// an absolute jump to HookedSet and build a trampoline to reach the original.
static bool insn_pc_relative(uint32_t x) {
    if ((x & 0x9F000000u) == 0x10000000u) return true; // ADR
    if ((x & 0x9F000000u) == 0x90000000u) return true; // ADRP
    if ((x & 0x3B000000u) == 0x18000000u) return true; // LDR/LDRSW literal
    if ((x & 0x7C000000u) == 0x14000000u) return true; // B / BL
    if ((x & 0xFF000010u) == 0x54000000u) return true; // B.cond
    if ((x & 0x7E000000u) == 0x34000000u) return true; // CBZ / CBNZ
    if ((x & 0x7E000000u) == 0x36000000u) return true; // TBZ / TBNZ
    return false;
}
// 16-byte absolute jump: LDR X17,#8 ; BR X17 ; .quad dest
static void write_abs_jump(void* at, void* dest) {
    uint32_t* p = (uint32_t*)at;
    p[0] = 0x58000051u;   // LDR X17, #8
    p[1] = 0xD61F0220u;   // BR  X17
    memcpy(p + 2, &dest, sizeof(dest));
}
// Materialize a 64-bit constant into Xd with MOVZ + 3x MOVK. Always 4 insns (no
// zero-halfword shortcut - simpler, and the trampoline has room). Returns count.
static int emit_mov_imm64(uint32_t* out, uint32_t rd, uint64_t val) {
    out[0] = 0xD2800000u | ((uint32_t)( val        & 0xFFFF) << 5) | rd; // MOVZ Xd,#h0
    out[1] = 0xF2A00000u | ((uint32_t)((val >> 16) & 0xFFFF) << 5) | rd; // MOVK Xd,#h1,LSL16
    out[2] = 0xF2C00000u | ((uint32_t)((val >> 32) & 0xFFFF) << 5) | rd; // MOVK Xd,#h2,LSL32
    out[3] = 0xF2E00000u | ((uint32_t)((val >> 48) & 0xFFFF) << 5) | rd; // MOVK Xd,#h3,LSL48
    return 4;
}
// Decode the 21-bit signed immediate of an ADR/ADRP (immhi[23:5], immlo[30:29]).
static int64_t adr_imm(uint32_t x) {
    int64_t imm = (((int64_t)(x >> 5) & 0x7FFFF) << 2) | ((x >> 29) & 0x3);
    if (imm & 0x100000) imm |= ~(int64_t)0x1FFFFF;   // sign-extend from bit 20
    return imm;
}
// Patch `target` prologue -> hook; return a trampoline that runs the 4 stolen
// instructions then jumps to target+16 (i.e. calls the original). ADRP/ADR among
// the stolen instructions are relocated - their result is PC-relative, so copied
// verbatim to a different address they'd compute the wrong pointer; instead we
// materialize the address they'd have produced at the ORIGINAL site. Returns null
// only if a stolen instruction is a PC-relative branch or literal load (can't be
// trivially relocated) - a function prologue almost never starts with one.
static void* install_inline_hook(void* target, void* hook) {
    uint32_t* t = (uint32_t*)target;
    for (int i = 0; i < 4; ++i) {
        uint32_t x = t[i];
        bool adrp = (x & 0x9F000000u) == 0x90000000u;
        bool adr  = (x & 0x9F000000u) == 0x10000000u;
        bool bad  = ((x & 0x3B000000u) == 0x18000000u)   // LDR/LDRSW literal
                 || ((x & 0x7C000000u) == 0x14000000u)   // B / BL
                 || ((x & 0xFF000010u) == 0x54000000u)   // B.cond
                 || ((x & 0x7E000000u) == 0x34000000u)   // CBZ / CBNZ
                 || ((x & 0x7E000000u) == 0x36000000u);  // TBZ / TBNZ
        if (bad && !adrp && !adr) {
            LOGE("inline hook: stolen insn %d not relocatable (%08x) - aborting", i, x);
            return nullptr;
        }
    }
    uint32_t buf[4 * 4 + 4];   // worst case: 4 ADRP -> 4 insns each, + 4-insn jump
    int n = 0;
    for (int i = 0; i < 4; ++i) {
        uint32_t x = t[i];
        uintptr_t pc = (uintptr_t)&t[i];
        if ((x & 0x9F000000u) == 0x90000000u) {          // ADRP Xd, page
            uintptr_t addr = (pc & ~(uintptr_t)0xFFF) + (adr_imm(x) << 12);
            n += emit_mov_imm64(&buf[n], x & 0x1F, addr);
        } else if ((x & 0x9F000000u) == 0x10000000u) {   // ADR Xd, imm
            n += emit_mov_imm64(&buf[n], x & 0x1F, pc + adr_imm(x));
        } else {
            buf[n++] = x;
        }
    }
    buf[n++] = 0x58000051u;                          // LDR X17, #8
    buf[n++] = 0xD61F0220u;                           // BR  X17
    uintptr_t cont = (uintptr_t)target + 16;
    memcpy(&buf[n], &cont, 8); n += 2;

    void* tramp = mmap(nullptr, sizeof(buf), PROT_READ | PROT_WRITE | PROT_EXEC,
                       MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (tramp == MAP_FAILED) return nullptr;
    memcpy(tramp, buf, n * 4);
    __builtin___clear_cache((char*)tramp, (char*)tramp + n * 4);

    long psz = sysconf(_SC_PAGESIZE);
    void* pg = (void*)((uintptr_t)target & ~(uintptr_t)(psz - 1));
    mprotect(pg, psz * 2, PROT_READ | PROT_WRITE | PROT_EXEC);   // patch may cross page
    write_abs_jump(target, hook);
    __builtin___clear_cache((char*)target, (char*)target + 16);
    return tramp;
}

// PostListItem.Set(PostData) hook: after the original localizes title/text, overwrite any
// @raw:-prefixed field with its literal payload (bypassing Localizer). PostData.title/text
// fields are resolved lazily from the argument's runtime class (arm64 offsets differ from dump).
void HookedSet(void* _this, void* data, void* methodInfo) {
    if (origSet) origSet(_this, data, methodInfo);   // origSet = trampoline to original
    if (!_this || !data) return;
    if (!postDataTitleField && obj_get_class && g_field_from_name) {
        void* dc = obj_get_class(data);
        if (dc) {
            postDataTitleField = g_field_from_name(dc, "title");
            postDataTextField  = g_field_from_name(dc, "text");
        }
    }
    applyRaw(data, postDataTitleField, _this, pli_titleTextField);
    applyRaw(data, postDataTextField,  _this, pli_descTextField);
}

void* worker_thread(void* arg) {
    LOGI("Worker thread started. Polling for libil2cpp.so...");
    
    void* handle = nullptr;
    int poll_count = 0;
    while (!handle) {
        handle = dlopen("libil2cpp.so", RTLD_NOLOAD);
        if (!handle) {
            poll_count++;
            // v171+: libaledatic.so may load il2cpp under a memfd name that
            // dlopen(RTLD_NOLOAD) can't see. After 30s, fall back to scanning
            // /proc/self/maps for any memfd region containing ELF magic.
            if (poll_count >= 30 && (poll_count % 10) == 0) {
                LOGI("dlopen poll failed %ds, scanning /proc/self/maps for memfd il2cpp...", poll_count);
                FILE* maps = fopen("/proc/self/maps", "r");
                if (maps) {
                    char line[1024];
                    while (fgets(line, sizeof(line), maps)) {
                        if (!strstr(line, "memfd:") && !strstr(line, "libil2cpp")) continue;
                        if (!strstr(line, "r-xp")) continue;  // executable text segment
                        uintptr_t start, end;
                        sscanf(line, "%lx-%lx", &start, &end);
                        // Verify ELF magic at start
                        if (end - start > 0x100 && *(uint32_t*)start == 0x464C457F) {
                            LOGI("Found ELF in memfd region 0x%lx-0x%lx, trying dlopen via /proc/self/fd", start, end);
                            // Extract fd number from the maps line path
                            char* fd_path = strstr(line, "/memfd:");
                            if (!fd_path) fd_path = strstr(line, "/proc/self/fd/");
                            // Try opening with the linker namespace path
                            char fd_buf[128];
                            // Scan for /proc/self/fd/<N> in the line
                            char* proc_fd = strstr(line, "/proc/self/fd/");
                            if (proc_fd) {
                                sscanf(proc_fd, "%127s", fd_buf);
                                handle = dlopen(fd_buf, RTLD_NOLOAD);
                                if (handle) { LOGI("dlopen(%s) succeeded!", fd_buf); break; }
                            }
                        }
                    }
                    fclose(maps);
                }
            }
            if (poll_count >= 120) {
                LOGE("Gave up waiting for libil2cpp.so after %ds", poll_count);
                return nullptr;
            }
            sleep(1);
        }
    }
    
    LOGI("libil2cpp.so is loaded (poll took %ds)!", poll_count);

    // --- Dump decrypted libil2cpp from process memory ---
    // Only runs when the trigger file exists. Create it with:
    //   adb shell touch /sdcard/kgc_dump_il2cpp
    // After dump completes, the trigger file is removed.
    bool do_dump = (access("/sdcard/kgc_dump_il2cpp", F_OK) == 0);
    if (do_dump) {
        LOGI("Dump trigger found — dumping decrypted il2cpp from memory...");
        FILE* maps = fopen("/proc/self/maps", "r");
        if (!maps) {
            LOGE("Failed to open /proc/self/maps for dump");
        } else {
            char line[1024];
            uintptr_t base = 0, last_end = 0;
            FILE* out = fopen("/sdcard/il2cpp_dumped.so", "wb");
            if (!out) {
                LOGE("Failed to create /sdcard/il2cpp_dumped.so — check permissions");
            }
            while (fgets(line, sizeof(line), maps)) {
                // Match both "libil2cpp.so" and memfd regions (v171 loader)
                if (!strstr(line, "libil2cpp.so") && !strstr(line, "memfd:")) continue;
                // For memfd, verify it's the il2cpp ELF (check once at first r-xp segment)
                uintptr_t start, end;
                char perm[8];
                sscanf(line, "%lx-%lx %4s", &start, &end, perm);
                if (perm[0] != 'r') continue;
                // If this is a memfd line and we haven't found base yet, check ELF magic
                if (!base && strstr(line, "memfd:") && !strstr(line, "libil2cpp")) {
                    if (end - start < 0x100 || *(uint32_t*)start != 0x464C457F) continue;
                }
                if (!base) {
                    base = start;
                    LOGI("libil2cpp base = 0x%lx", (unsigned long)base);
                }
                if (out) {
                    if (last_end && start > last_end) {
                        size_t gap = start - last_end;
                        void* zeros = calloc(1, gap);
                        if (zeros) { fwrite(zeros, 1, gap, out); free(zeros); }
                        LOGI("  gap 0x%lx-0x%lx (%zu KB)", (unsigned long)last_end, (unsigned long)start, gap / 1024);
                    }
                    size_t sz = end - start;
                    void* buf = malloc(sz);
                    if (buf) {
                        memcpy(buf, (void*)start, sz);
                        fwrite(buf, 1, sz, out);
                        free(buf);
                    }
                    LOGI("  %s 0x%lx-0x%lx (%zu KB) -> dumped", perm, (unsigned long)start, (unsigned long)end, sz / 1024);
                    last_end = end;
                }
            }
            if (out) {
                long total = ftell(out);
                fclose(out);
                LOGI("Dumped %ld bytes (%ld MB) to /sdcard/il2cpp_dumped.so", total, total / (1024*1024));
            }
            fclose(maps);
        }
        // Remove trigger so we don't dump every boot
        unlink("/sdcard/kgc_dump_il2cpp");
        LOGI("Removed dump trigger file.");
    } else {
        LOGI("No dump trigger (/sdcard/kgc_dump_il2cpp) — skipping memory dump.");
    }

    // --- Dump global-metadata.dat (only in dump mode) ---
    if (do_dump) {
        // global-metadata.dat is plaintext in base_assets.apk at
        // assets/bin/Data/Managed/Metadata/global-metadata.dat.
        // Try common installed-APK paths for both package ids.
        const char* metaSearchDirs[] = {
            "/data/app/",  // Android expands to /data/app/<pkg>-<hash>/
            nullptr
        };
        const char* packages[] = {
            "com.nowl.castle",
            "com.awesomepiece.castle",
            nullptr
        };
        bool foundMeta = false;
        // Scan /proc/self/maps for the base_assets.apk path (most reliable).
        FILE* maps2 = fopen("/proc/self/maps", "r");
        if (maps2) {
            char line2[1024];
            char apk_path[512] = {0};
            while (fgets(line2, sizeof(line2), maps2)) {
                if (strstr(line2, "base_assets.apk") || strstr(line2, "base.apk")) {
                    // Extract path (last field after spaces)
                    char* p = strrchr(line2, ' ');
                    if (!p) p = strrchr(line2, '\t');
                    if (p) {
                        ++p;
                        // Trim newline
                        char* nl = strchr(p, '\n');
                        if (nl) *nl = 0;
                        strncpy(apk_path, p, sizeof(apk_path)-1);
                        break;
                    }
                }
            }
            fclose(maps2);
            if (apk_path[0]) {
                LOGI("Found APK via maps: %s", apk_path);
                // global-metadata.dat is stored (compress_type=0) in split APKs.
                // Parse the ZIP to find it.
                FILE* apk = fopen(apk_path, "rb");
                if (apk) {
                    // Quick scan: find the local file header for global-metadata.dat
                    // by searching for the filename in the ZIP central directory.
                    fseek(apk, 0, SEEK_END);
                    long apk_size = ftell(apk);
                    // Search EOCD backwards
                    long eocd_pos = -1;
                    for (long off = apk_size - 22; off >= apk_size - 65557 && off >= 0; --off) {
                        fseek(apk, off, SEEK_SET);
                        uint8_t sig[4];
                        if (fread(sig, 1, 4, apk) == 4 && sig[0]==0x50 && sig[1]==0x4B && sig[2]==0x05 && sig[3]==0x06) {
                            eocd_pos = off;
                            break;
                        }
                    }
                    if (eocd_pos >= 0) {
                        fseek(apk, eocd_pos + 10, SEEK_SET);
                        uint16_t total_entries;
                        uint32_t cd_size, cd_offset;
                        fread(&total_entries, 2, 1, apk);
                        fread(&cd_size, 4, 1, apk);
                        fread(&cd_offset, 4, 1, apk);
                        fseek(apk, cd_offset, SEEK_SET);
                        for (uint16_t e = 0; e < total_entries; ++e) {
                            uint32_t sig;
                            fread(&sig, 4, 1, apk);
                            if (sig != 0x02014B50) break;
                            uint16_t fnlen, extralen, commentlen;
                            fseek(apk, 4, SEEK_CUR); // version-made-by, version-needed
                            uint16_t flags, method;
                            fread(&flags, 2, 1, apk);
                            fread(&method, 2, 1, apk);
                            fseek(apk, 8, SEEK_CUR); // time, crc
                            uint32_t comp_size, uncomp_size;
                            fread(&comp_size, 4, 1, apk);
                            fread(&uncomp_size, 4, 1, apk);
                            fread(&fnlen, 2, 1, apk);
                            fread(&extralen, 2, 1, apk);
                            fread(&commentlen, 2, 1, apk);
                            fseek(apk, 4, SEEK_CUR); // disk#, internal attrs
                            fseek(apk, 4, SEEK_CUR); // external attrs
                            uint32_t lh_offset;
                            fread(&lh_offset, 4, 1, apk);
                            char fname[512];
                            uint16_t readlen = fnlen < 511 ? fnlen : 511;
                            fread(fname, 1, readlen, apk);
                            fname[readlen] = 0;
                            if (fnlen > readlen) fseek(apk, fnlen - readlen, SEEK_CUR);
                            fseek(apk, extralen + commentlen, SEEK_CUR);
                            if (strstr(fname, "global-metadata.dat")) {
                                // Jump to local file header
                                fseek(apk, lh_offset + 26, SEEK_SET);
                                uint16_t lh_fnlen, lh_extralen;
                                fread(&lh_fnlen, 2, 1, apk);
                                fread(&lh_extralen, 2, 1, apk);
                                fseek(apk, lh_fnlen + lh_extralen, SEEK_CUR);
                                if (method == 0) {
                                    void* meta_buf = malloc(uncomp_size);
                                    if (meta_buf) {
                                        fread(meta_buf, 1, uncomp_size, apk);
                                        FILE* o = fopen("/sdcard/global-metadata.dat", "wb");
                                        if (o) { fwrite(meta_buf, 1, uncomp_size, o); fclose(o); }
                                        free(meta_buf);
                                        LOGI("global-metadata.dat (%u B) extracted from %s", uncomp_size, apk_path);
                                        foundMeta = true;
                                    }
                                } else {
                                    LOGI("global-metadata.dat is compressed (method=%u), can't extract inline", method);
                                }
                                break;
                            }
                        }
                    }
                    fclose(apk);
                }
            }
        }
        if (!foundMeta)
            LOGI("global-metadata.dat: not found via /proc/self/maps scan");
    }

    LOGI("Waiting 5s for classes to register...");
    sleep(5);
    
    auto il2cpp_domain_get = (il2cpp_domain_get_t)GetIl2CppSymbol(handle, "il2cpp_domain_get");
    auto il2cpp_thread_attach = (il2cpp_thread_attach_t)GetIl2CppSymbol(handle, "il2cpp_thread_attach");
    auto il2cpp_thread_detach = (il2cpp_thread_detach_t)GetIl2CppSymbol(handle, "il2cpp_thread_detach");
    auto il2cpp_domain_get_assemblies = (il2cpp_domain_get_assemblies_t)GetIl2CppSymbol(handle, "il2cpp_domain_get_assemblies");
    auto il2cpp_assembly_get_image = (il2cpp_assembly_get_image_t)GetIl2CppSymbol(handle, "il2cpp_assembly_get_image");
    auto il2cpp_image_get_name = (il2cpp_image_get_name_t)GetIl2CppSymbol(handle, "il2cpp_image_get_name");
    auto il2cpp_class_from_name = (il2cpp_class_from_name_t)GetIl2CppSymbol(handle, "il2cpp_class_from_name");
    
    rt_invoke = (il2cpp_runtime_invoke_t)GetIl2CppSymbol(handle, "il2cpp_runtime_invoke");
    str_len = (il2cpp_string_length_t)GetIl2CppSymbol(handle, "il2cpp_string_length");
    str_chars = (il2cpp_string_chars_t)GetIl2CppSymbol(handle, "il2cpp_string_chars");
    f_get_val = (il2cpp_field_get_value_t)GetIl2CppSymbol(handle, "il2cpp_field_get_value");
    obj_get_class = (il2cpp_object_get_class_t)GetIl2CppSymbol(handle, "il2cpp_object_get_class");
    class_get_method = (il2cpp_class_get_method_from_name_t)GetIl2CppSymbol(handle, "il2cpp_class_get_method_from_name");
    class_get_parent = (il2cpp_class_get_parent_t)GetIl2CppSymbol(handle, "il2cpp_class_get_parent");
    auto il2cpp_class_get_field_from_name = (il2cpp_class_get_field_from_name_t)GetIl2CppSymbol(handle, "il2cpp_class_get_field_from_name");
    g_field_from_name = il2cpp_class_get_field_from_name;
    str_new = (il2cpp_string_new_t)GetIl2CppSymbol(handle, "il2cpp_string_new");

    if (!il2cpp_domain_get) return nullptr;
    
    void* domain = il2cpp_domain_get();
    void* thread = il2cpp_thread_attach(domain);
    
    size_t asm_count = 0;
    void** assemblies = il2cpp_domain_get_assemblies(domain, &asm_count);
    
    void* unityEngineCoreImage = nullptr;
    void* assemblyCSharpImage = nullptr;
    void* unityEngineUIImage = nullptr;

    for (size_t i = 0; i < asm_count; ++i) {
        void* image = il2cpp_assembly_get_image(assemblies[i]);
        const char* name = il2cpp_image_get_name(image);
        if (strcmp(name, "UnityEngine.CoreModule.dll") == 0 || strcmp(name, "UnityEngine.CoreModule") == 0) {
            unityEngineCoreImage = image;
        } else if (strcmp(name, "Assembly-CSharp.dll") == 0 || strcmp(name, "Assembly-CSharp") == 0) {
            assemblyCSharpImage = image;
        } else if (strcmp(name, "UnityEngine.UI.dll") == 0 || strcmp(name, "UnityEngine.UI") == 0) {
            unityEngineUIImage = image;
        }
    }
    
    if (!unityEngineCoreImage || !assemblyCSharpImage) {
        LOGE("Could not find required assemblies.");
        il2cpp_thread_detach(thread);
        return nullptr;
    }
    
    void* objClass = il2cpp_class_from_name(unityEngineCoreImage, "UnityEngine", "Object");
    void* gameUnitClass = il2cpp_class_from_name(assemblyCSharpImage, "", "GameUnit");
    void* battleManagerClass = il2cpp_class_from_name(assemblyCSharpImage, "", "BattleManager");
    
    if (!objClass || !gameUnitClass || !battleManagerClass) {
        LOGE("Could not find classes.");
        il2cpp_thread_detach(thread);
        return nullptr;
    }
    
    getStatMethod = class_get_method(gameUnitClass, "GetStat", 2);
    getNameMethod = class_get_method(objClass, "get_name", 0);
    resUnitField = il2cpp_class_get_field_from_name(gameUnitClass, "resUnit");
    allFieldUnitsField = il2cpp_class_get_field_from_name(battleManagerClass, "allFieldUnits");
    void* buffManagerClass = il2cpp_class_from_name(assemblyCSharpImage, "", "BuffManager");
    void* buffClass = il2cpp_class_from_name(assemblyCSharpImage, "", "Buff");
    buffManagerField = il2cpp_class_get_field_from_name(gameUnitClass, "buffManager");
    if (buffManagerClass) unitsField = il2cpp_class_get_field_from_name(buffManagerClass, "units");
    if (buffClass) {
        buffTypeField = il2cpp_class_get_field_from_name(buffClass, "type");
        buffDataField = il2cpp_class_get_field_from_name(buffClass, "buffData");
        resSkillField = il2cpp_class_get_field_from_name(buffClass, "resSkill");
        buffTimeField = il2cpp_class_get_field_from_name(buffClass, "time");
        buffTotalTimeField = il2cpp_class_get_field_from_name(buffClass, "totalTime");
    }
    void* updateMethod = class_get_method(battleManagerClass, "Update", 0);
    
    if (!getStatMethod || !getNameMethod || !updateMethod) {
        LOGE("Could not find required methods.");
        il2cpp_thread_detach(thread);
        return nullptr;
    }
    
    getStat = (GetStatFunc)*(void**)getStatMethod;
    
    origUpdate = (UpdateFunc)*(void**)updateMethod;
    // MethodInfo.methodPointer may sit on a read-only page - unprotect before swap
    long psz = sysconf(_SC_PAGESIZE);
    void* page = (void*)((uintptr_t)updateMethod & ~(uintptr_t)(psz - 1));
    mprotect(page, psz, PROT_READ | PROT_WRITE | PROT_EXEC);
    *(void**)updateMethod = (void*)HookedUpdate;
    LOGI("Hooked BattleManager.Update successfully!");

    // --- Inbox custom title/text hook (PostListItem.Set) ---
    // Resolve UnityEngine.UI.Text::set_text(string), then hook PostListItem.Set so any
    // @raw:-prefixed PostData.title/text is written straight into the Text component,
    // bypassing the Localizer key lookup (a raw literal is never a valid loc key, so
    // without this it falls back to Post_Title_Default "You got a gift").
    if (unityEngineUIImage) {
        void* textClass = il2cpp_class_from_name(unityEngineUIImage, "UnityEngine.UI", "Text");
        void* tc = textClass;
        while (tc && !setTextMethod) {
            setTextMethod = class_get_method(tc, "set_text", 1);
            tc = class_get_parent(tc);
        }
    }
    void* postListItemClass = il2cpp_class_from_name(assemblyCSharpImage, "", "PostListItem");
    if (postListItemClass) {
        pli_titleTextField = il2cpp_class_get_field_from_name(postListItemClass, "titleText");
        pli_descTextField  = il2cpp_class_get_field_from_name(postListItemClass, "descText");
        void* setMethod = class_get_method(postListItemClass, "Set", 1);
        if (setMethod && setTextMethod && str_new && pli_titleTextField && pli_descTextField) {
            // Set is a direct C#->C# call: patch its compiled code, not the MethodInfo pointer.
            void* setFn = *(void**)setMethod;   // methodPointer = native function address
            origSet = (SetFunc)install_inline_hook(setFn, (void*)HookedSet);
            if (origSet) LOGI("Hooked PostListItem.Set successfully (inline detour)!");
            else LOGE("Inbox hook: inline detour failed (unsafe prologue)");
        } else {
            LOGE("Inbox hook skipped: set=%p setText=%p new=%p titleF=%p descF=%p",
                 setMethod, setTextMethod, (void*)str_new, pli_titleTextField, pli_descTextField);
        }
    } else {
        LOGE("Inbox hook: PostListItem class not found");
    }

    // --- Google login -> web redirect hook ---
    // Detour Scene_Login.OnClickGoogleLogin so the button opens our /glogin page
    // (Application.OpenURL) rather than the GPGS sign-in that can't authenticate
    // this build. Inline detour, not a methodPointer swap: a uGUI onClick caches
    // the delegate at AddListener (before we run), so swapping the MethodInfo
    // pointer would not affect the already-registered click.
    void* applicationClass = il2cpp_class_from_name(unityEngineCoreImage, "UnityEngine", "Application");
    if (applicationClass)    g_openUrlMethod = class_get_method(applicationClass, "OpenURL", 1);
    
    void* sceneLoginClass = il2cpp_class_from_name(assemblyCSharpImage, "", "Scene_Login");
    if (sceneLoginClass && g_openUrlMethod) {
        void* autoRegMethod = class_get_method(sceneLoginClass, "<AutoRegister>g__AutoRegisterImpl|134_0", 1);
        if (autoRegMethod) {
            void* autoRegFn = *(void**)autoRegMethod;
            origAutoRegisterImpl = (AutoRegisterImplFunc)install_inline_hook(autoRegFn, (void*)HookedAutoRegisterImpl);
            if (origAutoRegisterImpl) LOGI("Hooked Scene_Login.AutoRegisterImpl -> persistent local ID!");
            else LOGE("AutoRegister hook: inline detour failed");
        }

        void* glMethod = class_get_method(sceneLoginClass, "OnClickGoogleLogin", 0);
        if (glMethod) {
            void* glFn = *(void**)glMethod;
            origGoogleLogin = (GoogleLoginFunc)install_inline_hook(glFn, (void*)HookedGoogleLogin);
            if (origGoogleLogin) LOGI("Hooked Scene_Login.OnClickGoogleLogin -> web login!");
            else LOGE("Google hook: inline detour failed (unsafe prologue)");
        } else {
            LOGE("Google hook: OnClickGoogleLogin not found");
        }
    } else {
        LOGE("Google hook: Application=%p OpenURL=%p Scene_Login=%p",
             applicationClass, g_openUrlMethod, sceneLoginClass);
    }

    // --- Web-login return bridge: hook Scene_Login.Update (main thread) + poller ---
    if (sceneLoginClass) g_authMethod = class_get_method(sceneLoginClass, "Auth", 1);
    void* slUpdate = sceneLoginClass ? class_get_method(sceneLoginClass, "Update", 0) : nullptr;
    if (slUpdate && g_authMethod) {
        origSceneLoginUpdate = (SLUpdateFunc)*(void**)slUpdate;
        long ps = sysconf(_SC_PAGESIZE);
        void* pg2 = (void*)((uintptr_t)slUpdate & ~(uintptr_t)(ps - 1));
        mprotect(pg2, ps, PROT_READ | PROT_WRITE | PROT_EXEC);
        *(void**)slUpdate = (void*)HookedSceneLoginUpdate;
        pthread_t pt;
        pthread_create(&pt, nullptr, login_poll_thread, nullptr);
        LOGI("Hooked Scene_Login.Update + started login poller (web-login bridge)!");
    } else {
        LOGE("web-login bridge not wired: auth=%p update=%p", g_authMethod, slUpdate);
    }

    // --- Scene_Lobby.Awake GameManager-singleton guard (fixes the black lobby) ---
    // Hook Awake, not Init: Awake->Init is a same-class direct call (compiler bl),
    // so Init's MethodInfo pointer is never consulted at call time. Awake IS
    // dispatched by Unity via the MethodInfo table, so the pointer swap works.
    // Must use MethodInfo pointer swap, NOT install_inline_hook (ndk_translation
    // JIT-translates arm64 before we patch -> inline detours never fire).
    void* gmClass = il2cpp_class_from_name(assemblyCSharpImage, "", "GameManager");
    if (gmClass) {
        g_gmGet   = class_get_method(gmClass, "Get", 0);
        g_gmCctor = class_get_method(gmClass, ".cctor", 0);
    }
    void* sceneLobbyClass = il2cpp_class_from_name(assemblyCSharpImage, "", "Scene_Lobby");
    if (sceneLobbyClass && g_gmGet && g_gmCctor) {
        void* lobbyAwakeM = class_get_method(sceneLobbyClass, "Awake", 0);
        if (lobbyAwakeM) {
            origLobbyAwake = (LobbyAwakeFunc)*(void**)lobbyAwakeM;
            long ps = sysconf(_SC_PAGESIZE);
            void* pg = (void*)((uintptr_t)lobbyAwakeM & ~(uintptr_t)(ps - 1));
            mprotect(pg, ps, PROT_READ | PROT_WRITE | PROT_EXEC);
            *(void**)lobbyAwakeM = (void*)HookedLobbyAwake;
            LOGI("Hooked Scene_Lobby.Awake (methodPointer swap, singleton guard)!");
        } else LOGE("Scene_Lobby.Awake hook: Awake method not found");
    } else {
        LOGE("Scene_Lobby.Awake hook not wired: gm=%p get=%p cctor=%p lobby=%p",
             gmClass, g_gmGet, g_gmCctor, sceneLobbyClass);
    }

    il2cpp_thread_detach(thread);
    return nullptr;
}

// Manual .init_array entry: NDK's __attribute__((constructor)) produces a zero-filled
// .init_array (compiler bug with this NDK/target). The asm directive below places the
// function address directly so the dynamic linker fires it on dlopen.
extern "C" void xigncode_stub_init();
__asm__(".section .init_array,\"aw\"\n"
        ".align 3\n"
        ".xword xigncode_stub_init\n"
        ".previous\n");

extern "C" void xigncode_stub_init() {
    LOGI("XignCodeStub (Native Poller) loaded via .init_array!");
    pthread_once(&init_once, start_worker);
}
