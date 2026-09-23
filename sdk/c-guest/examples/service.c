/* SPDX-License-Identifier: Apache-2.0 */
#include "lsf/service.h"
#include "lsf/async.h"

struct frame {
    lsf_async_t async;
    latent_service_invoke_call_args_t request;
    latent_service_invoke_invocation_outcome_t result;
};

static probe_callback_code_t finish(struct frame *frame, lsf_async_result_t result) {
    if (result == LSF_ASYNC_PENDING) return lsf_async_wait(&frame->async);
    uint64_t value = 0;
    bool cancelled = result == LSF_ASYNC_CANCELLED || result == LSF_ASYNC_CANCELLED_RETURNED;
    if (!cancelled) {
        switch (frame->result.tag) {
        case LATENT_SERVICE_INVOKE_INVOCATION_OUTCOME_SUCCESS:
            lsf_require(frame->result.val.success.payload.len == 4 &&
                        memcmp(frame->result.val.success.payload.ptr, "[42]", 4) == 0);
            value = 42;
            break;
        case LATENT_SERVICE_INVOKE_INVOCATION_OUTCOME_DECLARED_ERROR:
            lsf_require(frame->result.val.declared_error.payload.len > 0);
            value = 10;
            break;
        case LATENT_SERVICE_INVOKE_INVOCATION_OUTCOME_PLATFORM_FAILURE:
            switch (frame->result.val.platform_failure.code) {
            case LATENT_SERVICE_INVOKE_PLATFORM_ERROR_CODE_PERMISSION_DENIED: value = 11; break;
            case LATENT_SERVICE_INVOKE_PLATFORM_ERROR_CODE_CANCELLED: value = 12; break;
            case LATENT_SERVICE_INVOKE_PLATFORM_ERROR_CODE_DEADLINE_EXCEEDED: value = 13; break;
            case LATENT_SERVICE_INVOKE_PLATFORM_ERROR_CODE_RESOURCE_EXHAUSTED: value = 14; break;
            default: __builtin_trap();
            }
            break;
        default: __builtin_trap();
        }
    }
    if (result != LSF_ASYNC_CANCELLED) lsf_service_outcome_close(&frame->result);
    lsf_async_close(&frame->async);
    lsf_frame_leave(frame);
    free(frame);
    if (cancelled) probe_task_cancel();
    else exports_tests_caller_api_run_return(value);
    return PROBE_CALLBACK_CODE_EXIT;
}

probe_callback_code_t exports_tests_caller_api_run(uint32_t which, probe_string_t *text,
                                                    uint64_t handle) {
    (void)handle;
    probe_string_free(text);
    struct frame *frame = calloc(1, sizeof(*frame));
    lsf_require(frame != NULL);
    frame->request = (latent_service_invoke_call_args_t){
        .target = {
            .service = LSF_LITERAL("callee"),
            .contract = LSF_LITERAL("tests:local/api@1.0.0"),
            .function = which == 0 ? LSF_LITERAL("answer") :
                        which == 1 ? LSF_LITERAL("fail") : LSF_LITERAL("spin"),
            .route = {true, LSF_LITERAL("callee")},
        },
        .payload = {(uint8_t *)"[]", 2},
        .media_type = LSF_LITERAL("application/vnd.latent.wit-values.v1+json"),
    };
    lsf_frame_enter(frame);
    probe_subtask_status_t status = latent_service_invoke_call(&frame->request, &frame->result);
    return finish(frame, lsf_async_submit(&frame->async, status));
}

probe_callback_code_t exports_tests_caller_api_run_callback(probe_event_t *event) {
    struct frame *frame = probe_context_get_0();
    lsf_require(frame != NULL);
    return finish(frame, lsf_async_event(&frame->async, event));
}
