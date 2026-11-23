#include "exceptions.h"
#include <assert.h>
#include <stdio.h>

static unsigned seen[32];
static unsigned count;
static void record(unsigned item) {
    assert(count < 32);
    seen[count++] = item;
}

static void recurse(int remaining) {
    TEAVM_ALLOC_STACK(INT32_C(0));
    TEAVM_TRY
        TeaVM_LongjmpDesc *const parent = teavm_shadowStack.header.jmpTarget;
        if (remaining) recurse(remaining - 1);
        assert(teavm_shadowStack.header.jmpTarget == parent);
        longjmp(parent->buffer, 1);
    TEAVM_CATCH
        case 1:
            record(10 + remaining);
            break;
    TEAVM_END_TRY
    assert(teavm_shadowStack.header.jmpTarget == NULL);
    TEAVM_RELEASE_STACK;
}

static void nested(void) {
    TEAVM_ALLOC_STACK(INT32_C(0));
    TEAVM_TRY
        record(1);
        TeaVM_LongjmpDesc *const outer = teavm_shadowStack.header.jmpTarget;
        TEAVM_TRY
            assert(teavm_shadowStack.header.jmpTarget != outer);
            record(2);
            longjmp(teavm_shadowStack.header.jmpTarget->buffer, 2);
        TEAVM_CATCH
            case 2:
                record(3);
                /* A catch runs with its own descriptor already removed. */
                TEAVM_TRY
                    record(4);
                    longjmp(teavm_shadowStack.header.jmpTarget->buffer, 3);
                TEAVM_CATCH
                    case 3:
                        record(5);
                        break;
                TEAVM_END_TRY
                longjmp(teavm_shadowStack.header.jmpTarget->buffer, 7);
        TEAVM_END_TRY
        assert(0);
    TEAVM_CATCH
        case 7:
            record(6);
            break;
    TEAVM_END_TRY
    assert(teavm_shadowStack.header.jmpTarget == NULL);
    /* The default route in an inner handler must reach the still-live outer. */
    TEAVM_TRY
        TEAVM_TRY
            longjmp(teavm_shadowStack.header.jmpTarget->buffer, 9);
        TEAVM_CATCH
            case 8:
                assert(0);
                break;
        TEAVM_END_TRY
        assert(0);
    TEAVM_CATCH
        case 9:
            record(7);
            break;
    TEAVM_END_TRY
    assert(teavm_shadowStack.header.jmpTarget == NULL);
    TEAVM_RELEASE_STACK;
}

static void sequential(void) {
    volatile int turns = 0;
    TEAVM_ALLOC_STACK(INT32_C(0));
    while (turns != 256) {
        TEAVM_TRY
            ++turns;
            longjmp(teavm_shadowStack.header.jmpTarget->buffer, 1);
        TEAVM_CATCH
            case 1:
                break;
        TEAVM_END_TRY
        assert(teavm_shadowStack.header.jmpTarget == NULL);
        TEAVM_TRY
            assert(turns > 0);
        TEAVM_CATCH
            case 2:
                assert(0);
                break;
        TEAVM_END_TRY
        assert(teavm_shadowStack.header.jmpTarget == NULL);
    }
    TEAVM_RELEASE_STACK;
}

static int leave_frame(int resume) {
    TEAVM_ALLOC_STACK(INT32_C(0));
    if (resume) goto resumed;
    TEAVM_TRY
        /* The generated suspension/return edge restores before leaving. */
        TEAVM_RESTORE_JUMP_BUFFER;
        TEAVM_RELEASE_STACK;
        return 11;
    TEAVM_CATCH
        case 1:
            assert(0);
            break;
    TEAVM_END_TRY
resumed:;
    TEAVM_TRY
        longjmp(teavm_shadowStack.header.jmpTarget->buffer, 2);
    TEAVM_CATCH
        case 2:
            break;
    TEAVM_END_TRY
    TEAVM_RELEASE_STACK;
    return 12;
}

static void explicit_edges(void) {
    volatile int turns = 0;
    TEAVM_ALLOC_STACK(INT32_C(0));
    while (turns != 4) {
        TEAVM_TRY
            ++turns;
            TEAVM_RESTORE_JUMP_BUFFER;
            goto next_turn;
        TEAVM_CATCH
            case 1:
                assert(0);
                break;
        TEAVM_END_TRY
        assert(0);
next_turn:;
        assert(teavm_shadowStack.header.jmpTarget == NULL);
    }
    TEAVM_RELEASE_STACK;
}

int main(void) {
    sequential();
    nested();
    recurse(3);
    explicit_edges();
    assert(leave_frame(0) == 11);
    assert(leave_frame(1) == 12);
    assert(teavm_stackTop == NULL);
    const unsigned expected[] = {1,2,3,4,5,6,7,10,11,12,13};
    assert(count == sizeof(expected) / sizeof(expected[0]));
    for (unsigned i = 0; i < count; ++i) assert(seen[i] == expected[i]);
    puts("sequential nested catch-reentry rethrow recursive explicit-exit fresh-frame: passed");
    return 0;
}
