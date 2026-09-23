/* SPDX-License-Identifier: Apache-2.0 */
#include "lsf/http.h"
#include "lsf/async.h"

struct frame {
    lsf_async_t async;
    lsf_scope_t owned;
    latent_http_client_request_t request;
    latent_http_client_result_response_http_error_t result;
    bool returned;
};

static void cleanup(struct frame *frame) {
    lsf_async_close(&frame->async);
    if (frame->returned && !frame->result.is_err)
        lsf_http_response_close(&frame->result.val.ok);
    lsf_scope_close(&frame->owned);
    lsf_frame_leave(frame);
    free(frame);
}

static probe_callback_code_t finish(struct frame *frame, lsf_async_result_t result) {
    if (result == LSF_ASYNC_PENDING) return lsf_async_wait(&frame->async);
    frame->returned = result != LSF_ASYNC_CANCELLED;
    if (result == LSF_ASYNC_CANCELLED || result == LSF_ASYNC_CANCELLED_RETURNED) {
        cleanup(frame);
        probe_task_cancel();
        return PROBE_CALLBACK_CODE_EXIT;
    }
    uint64_t value;
    if (!frame->result.is_err) {
        value = frame->result.val.ok.status + 1000u * (uint64_t)frame->result.val.ok.body.len;
    } else {
        uint8_t error = frame->result.val.err.tag;
        lsf_require(error == LATENT_HTTP_CLIENT_HTTP_ERROR_PERMISSION_DENIED ||
                    error == LATENT_HTTP_CLIENT_HTTP_ERROR_UNCERTAIN);
        value = error == LATENT_HTTP_CLIENT_HTTP_ERROR_PERMISSION_DENIED ? 10 : 11;
    }
    cleanup(frame);
    exports_tests_http_api_run_return(value);
    return PROBE_CALLBACK_CODE_EXIT;
}

probe_callback_code_t exports_tests_http_api_run(uint32_t which, probe_string_t *text,
                                                  uint64_t handle) {
    (void)handle;
    struct frame *frame = calloc(1, sizeof(*frame));
    lsf_require(frame != NULL);
    lsf_scope_init(&frame->owned, 65536);
    frame->request = (latent_http_client_request_t){
        .method = which == 0 ? LATENT_HTTP_CLIENT_METHOD_GET :
                  which == 1 ? LATENT_HTTP_CLIENT_METHOD_HEAD : LATENT_HTTP_CLIENT_METHOD_POST,
        .url = *text,
        .body = {true, {(uint8_t *)"payload", 7}},
        .body_media_type = {true, LSF_LITERAL("text/plain")},
        .timeout_millis = {true, 1000},
    };
    *text = (probe_string_t){0};
    if (!lsf_scope_adopt(&frame->owned, &frame->request.url,
                         frame->request.url.len, lsf_string_drop)) {
        probe_string_free(&frame->request.url);
        free(frame);
        __builtin_trap();
    }
    lsf_frame_enter(frame);
    probe_subtask_status_t status = latent_http_client_send(&frame->request, &frame->result);
    return finish(frame, lsf_async_submit(&frame->async, status));
}

probe_callback_code_t exports_tests_http_api_run_callback(probe_event_t *event) {
    struct frame *frame = probe_context_get_0();
    lsf_require(frame != NULL);
    return finish(frame, lsf_async_event(&frame->async, event));
}
