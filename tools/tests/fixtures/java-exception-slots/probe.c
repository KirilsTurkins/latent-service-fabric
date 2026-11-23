/* Native macro-lifetime witness; no TeaVM compiler or guest is executed. */
#include "exceptions.h"
#include <stdio.h>

TeaVM_StackFrame* teavm_stackTop;

static void raise_now(int code) {
    assert(teavm_stackTop && teavm_stackTop->jmpTarget);
    longjmp(teavm_stackTop->jmpTarget->buffer, code);
}

static int exercise(int mode, int depth) {
    volatile int trace = 0;
    TeaVM_LongjmpDesc* volatile outer = NULL;
    TeaVM_LongjmpDesc* volatile first = NULL;
    struct { TeaVM_StackFrame header; } teavm_shadowStack;
    teavm_shadowStack.header.next = teavm_stackTop;
    teavm_shadowStack.header.jmpTarget = NULL;
    teavm_stackTop = &teavm_shadowStack.header;
    TEAVM_TRY
        outer = teavm_shadowStack.header.jmpTarget;
        if (teavm_shadowStack.header.next) {
            assert(outer != teavm_shadowStack.header.next->jmpTarget);
        }
        TEAVM_TRY
            first = teavm_shadowStack.header.jmpTarget;
            assert(first != outer && first->previous == outer);
            if (mode == 6 && depth > 0) {
                assert(exercise(6, depth - 1) == 42);
                assert(teavm_stackTop == &teavm_shadowStack.header);
                assert(teavm_shadowStack.header.jmpTarget == first);
            }
            if (mode == 1 || mode == 4) raise_now(11);
            if (mode == 3) raise_now(33);
            trace |= 1;
            if (mode == 5) {
                TEAVM_RESTORE_JUMP_BUFFER;
                goto after_first;
            }
        TEAVM_CATCH
            case 11: {
                assert(teavm_shadowStack.header.jmpTarget == outer);
                trace |= 2;
                if (mode == 4) raise_now(33);
                break;
            }
        TEAVM_END_TRY
    after_first:;
        assert(teavm_shadowStack.header.jmpTarget == outer);
        TEAVM_TRY
            assert(teavm_shadowStack.header.jmpTarget != outer);
            assert(teavm_shadowStack.header.jmpTarget->previous == outer);
            if (LSF_EXPECT_REUSE) assert(teavm_shadowStack.header.jmpTarget == first);
            if (mode == 2) raise_now(22);
            trace |= 4;
        TEAVM_CATCH
            case 22: {
                assert(teavm_shadowStack.header.jmpTarget == outer);
                trace |= 8;
                break;
            }
        TEAVM_END_TRY
    TEAVM_CATCH
        case 33: {
            trace |= 16;
            break;
        }
    TEAVM_END_TRY
    assert(teavm_shadowStack.header.jmpTarget == NULL);
    teavm_stackTop = teavm_shadowStack.header.next;
    const int expected[] = {5, 6, 9, 16, 18, 5, 5};
    assert(trace == expected[mode]);
    return 42;
}

int main(void) {
    for (int repeat = 0; repeat < 20; ++repeat) {
        for (int mode = 0; mode < 7; ++mode) {
            assert(exercise(mode, 4) == 42);
            assert(teavm_stackTop == NULL);
        }
    }
    puts("normal, caught, nested, rethrow, catch-throw, goto and recursive handler lifetimes passed");
    return 0;
}
