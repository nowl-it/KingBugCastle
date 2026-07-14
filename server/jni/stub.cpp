#include <jni.h>
#include <android/log.h>
#include <pthread.h>
#include <unistd.h>
#include <dlfcn.h>
#include <sys/mman.h>
#include <time.h>
#include <vector>
#include <string.h>

#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, "XignCodeStub", __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, "XignCodeStub", __VA_ARGS__)

// --- XIGNCODE STUB METHODS ---
static jint    z_int(JNIEnv* e, jclass c, ...)        { return 0; }
static void    z_void(JNIEnv* e, jclass c, ...)       { }
static jstring z_str(JNIEnv* e, jclass c, ...)        { return e->NewStringUTF(""); }

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
    jclass cls = env->FindClass("com/wellbia/xigncode/XigncodeClientSystem");
    if (cls) {
        env->RegisterNatives(cls, kMethods, sizeof(kMethods)/sizeof(kMethods[0]));
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
il2cpp_string_new_t str_new = nullptr;

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
// Patch `target` prologue -> HookedSet; return trampoline that runs the 16 stolen
// bytes then jumps to target+16 (i.e. calls the original). Null if prologue unsafe.
static void* install_inline_hook(void* target, void* hook) {
    uint32_t* t = (uint32_t*)target;
    for (int i = 0; i < 4; ++i) {
        if (insn_pc_relative(t[i])) {
            LOGE("inline hook: stolen insn %d is PC-relative (%08x) - aborting", i, t[i]);
            return nullptr;
        }
    }
    void* tramp = mmap(nullptr, 64, PROT_READ | PROT_WRITE | PROT_EXEC,
                       MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (tramp == MAP_FAILED) return nullptr;
    memcpy(tramp, target, 16);
    write_abs_jump((char*)tramp + 16, (char*)target + 16);
    __builtin___clear_cache((char*)tramp, (char*)tramp + 32);

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
    while (!handle) {
        handle = dlopen("libil2cpp.so", RTLD_NOLOAD);
        if (!handle) sleep(1);
    }
    
    LOGI("libil2cpp.so is loaded! Waiting 5s for classes to register...");
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
