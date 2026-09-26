/* SPDX-License-Identifier: Apache-2.0 */
#include "lsf/http.h"
#include "lsf/async.h"

struct frame {
    lsf_async_t async;
    latent_http_client_request_t request;
    latent_http_client_result_response_http_error_t result;
};

static probe_callback_code_t finish(struct frame *frame, lsf_async_result_t state) {
    if (state == LSF_ASYNC_PENDING) return lsf_async_wait(&frame->async);
    bool cancelled = state == LSF_ASYNC_CANCELLED || state == LSF_ASYNC_CANCELLED_RETURNED;
    exports_examples_http_status_api_result_u16_http_error_t value = {0};
    if (state != LSF_ASYNC_CANCELLED) {
        value.is_err = frame->result.is_err;
        if (value.is_err) value.val.err = frame->result.val.err;
        else {
            value.val.ok = frame->result.val.ok.status;
            lsf_http_response_close(&frame->result.val.ok);
        }
    }
    probe_string_free(&frame->request.url);
    lsf_async_close(&frame->async);
    lsf_frame_leave(frame);
    free(frame);
    if (cancelled) probe_task_cancel();
    else exports_examples_http_status_api_check_return(value);
    return PROBE_CALLBACK_CODE_EXIT;
}

probe_callback_code_t exports_examples_http_status_api_check(probe_string_t *url) {
    struct frame *frame = calloc(1, sizeof(*frame));
    lsf_require(frame != NULL);
    frame->request = (latent_http_client_request_t){
        .method = LATENT_HTTP_CLIENT_METHOD_GET, .url = *url,
        .timeout_millis = {true, 5000},
    };
    *url = (probe_string_t){0};
    lsf_frame_enter(frame);
    return finish(frame, lsf_async_submit(&frame->async,
        latent_http_client_send(&frame->request, &frame->result)));
}

probe_callback_code_t exports_examples_http_status_api_check_callback(probe_event_t *event) {
    struct frame *frame = probe_context_get_0();
    lsf_require(frame != NULL);
    return finish(frame, lsf_async_event(&frame->async, event));
}
