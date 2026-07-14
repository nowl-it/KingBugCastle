LOCAL_PATH := $(call my-dir)

include $(CLEAR_VARS)
LOCAL_MODULE    := xigncode
LOCAL_SRC_FILES := stub.cpp
LOCAL_LDLIBS    := -llog -ldl
LOCAL_LDFLAGS   := -Wl,--no-gc-sections -Wl,-init,xigncode_stub_init
include $(BUILD_SHARED_LIBRARY)
