/* SPDX-License-Identifier: Apache-2.0 */
#ifndef LSF_GUEST_ASYNC_H
#define LSF_GUEST_ASYNC_H

/* Generate the application's WIT with --rename-world probe. This header is
 * used only by asynchronous worlds. It introduces no executor or event loop. */
#include "probe.h"
#include "ownership.h"

typedef struct {
    probe_subtask_t task;
    probe_waitable_set_t set;
    bool cancelling;
} lsf_async_t;

typedef enum {
    LSF_ASYNC_PENDING,
    LSF_ASYNC_RETURNED,
    LSF_ASYNC_CANCELLED,
    /* The result became owned before cancellation completed. Adopt/release
     * that result before disposing of the retained frame. */
    LSF_ASYNC_CANCELLED_RETURNED
} lsf_async_result_t;

static inline void lsf_async_drop_task(lsf_async_t *state) {
    lsf_require(state->task != 0);
    probe_waitable_join(state->task, 0);
    probe_subtask_drop(state->task);
    state->task = 0;
}

/* Inputs and result storage must already belong to the retained frame before
 * calling the generated import. A synchronously returned result is owned too. */
static inline lsf_async_result_t lsf_async_submit(lsf_async_t *state,
                                                 probe_subtask_status_t status) {
    lsf_require(!state->task && !state->cancelling);
    probe_subtask_state_t kind = PROBE_SUBTASK_STATE(status);
    if (kind == PROBE_SUBTASK_RETURNED) return LSF_ASYNC_RETURNED;
    lsf_require(kind == PROBE_SUBTASK_STARTING || kind == PROBE_SUBTASK_STARTED);
    state->task = PROBE_SUBTASK_HANDLE(status);
    lsf_require(state->task != 0);
    if (!state->set) state->set = probe_waitable_set_new();
    lsf_require(state->set != 0);
    probe_waitable_join(state->task, state->set);
    return LSF_ASYNC_PENDING;
}

static inline probe_callback_code_t lsf_async_wait(const lsf_async_t *state) {
    lsf_require(state->task != 0 && state->set != 0);
    return PROBE_CALLBACK_CODE_WAIT(state->set);
}

static inline lsf_async_result_t lsf_async_event(lsf_async_t *state,
                                                const probe_event_t *event) {
    lsf_require(state->task != 0 && event != NULL);
    if (event->event == PROBE_EVENT_CANCEL) {
        lsf_require(!state->cancelling);
        state->cancelling = true;
        /* The canonical ABI requires detachment before cancel/drop. Cancel
         * may remain pending; that is not permission to free request storage. */
        probe_waitable_join(state->task, 0);
        uint32_t status = probe_subtask_cancel(state->task);
        if (status == UINT32_MAX) {
            probe_waitable_join(state->task, state->set);
            return LSF_ASYNC_PENDING;
        }
        lsf_async_drop_task(state);
        if (status == PROBE_SUBTASK_RETURNED) return LSF_ASYNC_CANCELLED_RETURNED;
        lsf_require(status == PROBE_SUBTASK_STARTED_CANCELLED ||
                    status == PROBE_SUBTASK_RETURNED_CANCELLED);
        return LSF_ASYNC_CANCELLED;
    }
    lsf_require(event->event == PROBE_EVENT_SUBTASK && event->waitable == state->task);
    if (event->code == PROBE_SUBTASK_STARTED) return LSF_ASYNC_PENDING;
    lsf_async_drop_task(state);
    if (event->code == PROBE_SUBTASK_RETURNED)
        return state->cancelling ? LSF_ASYNC_CANCELLED_RETURNED : LSF_ASYNC_RETURNED;
    lsf_require(state->cancelling &&
                (event->code == PROBE_SUBTASK_STARTED_CANCELLED ||
                 event->code == PROBE_SUBTASK_RETURNED_CANCELLED));
    return LSF_ASYNC_CANCELLED;
}

static inline void lsf_async_close(lsf_async_t *state) {
    lsf_require(state->task == 0);
    if (state->set) probe_waitable_set_drop(state->set);
    *state = (lsf_async_t){0};
}

/* Exactly one frame per exported task, not per deployment. All copied input,
 * request, result and resource fields must live in this frame or its scope. */
static inline void lsf_frame_enter(void *frame) {
    lsf_require(frame != NULL && probe_context_get_0() == NULL);
    probe_context_set_0(frame);
}

static inline void lsf_frame_leave(void *frame) {
    lsf_require(frame != NULL && probe_context_get_0() == frame);
    probe_context_set_0(NULL);
}

#endif
