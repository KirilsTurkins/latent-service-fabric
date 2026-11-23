/* Only the pinned exception descriptor and shadow-stack fields are exercised. */
#pragma once
#include <assert.h>
#include <setjmp.h>
#include <stdint.h>
#include <stdlib.h>
typedef struct TeaVM_LongjmpDesc {
    jmp_buf buffer;
    struct TeaVM_LongjmpDesc* previous;
} TeaVM_LongjmpDesc;
typedef struct TeaVM_StackFrame {
    struct TeaVM_StackFrame* next;
    TeaVM_LongjmpDesc* jmpTarget;
    int32_t size;
    int32_t callSiteId;
} TeaVM_StackFrame;
extern TeaVM_StackFrame* teavm_stackTop;
#define TEAVM_ARRAY_LENGTH(array) (*(int32_t*) (array))
static inline void teavm_throwNullPointerException(void) { abort(); }
static inline void teavm_throwArrayIndexOutOfBoundsException(void) { abort(); }
