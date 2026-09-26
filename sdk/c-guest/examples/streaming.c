/* SPDX-License-Identifier: Apache-2.0 */
#include "lsf/streaming.h"
#include "lsf/async.h"

enum phase { OPEN, WRITE, FINISH, READ, BYTES, TRAILERS, AGAIN };
struct frame {
    lsf_async_t async;
    lsf_scope_t owned;
    uint32_t which;
    uint64_t count;
    enum phase phase;
    latent_http_streaming_request_t request;
    lsf_upload_t upload;
    lsf_body_t body;
    lsf_http_chunk_t chunk;
    latent_http_streaming_result_own_upload_http_error_t opened;
    latent_http_streaming_result_void_http_error_t written;
    latent_http_streaming_result_response_http_error_t response;
    latent_http_streaming_result_option_own_chunk_http_error_t read;
    latent_http_streaming_result_list_u8_http_error_t bytes;
    latent_http_streaming_result_list_header_http_error_t trailers;
};

static void cleanup(struct frame *frame) {
    lsf_async_close(&frame->async);
    lsf_http_chunk_close(&frame->chunk);
    lsf_body_close(&frame->body);
    lsf_upload_close(&frame->upload);
    lsf_scope_close(&frame->owned);
    lsf_frame_leave(frame);
    free(frame);
}

static probe_callback_code_t finish(struct frame *frame, uint64_t value) {
    cleanup(frame);
    exports_tests_streaming_http_api_run_return(value);
    return PROBE_CALLBACK_CODE_EXIT;
}

/* Cancellation can race with a returned owned result. Dispose of that result
 * before the frame and its pre-existing owners, without starting another call. */
static void discard_returned(struct frame *frame) {
    switch (frame->phase) {
    case OPEN:
        if (!frame->opened.is_err) latent_http_streaming_upload_drop_own(frame->opened.val.ok);
        break;
    case FINISH:
        if (!frame->response.is_err) {
            latent_http_streaming_body_drop_own(frame->response.val.ok.body);
            lsf_streaming_metadata_close(&frame->response.val.ok);
        }
        break;
    case READ:
        if (!frame->read.is_err && frame->read.val.ok.is_some)
            latent_http_streaming_chunk_drop_own(frame->read.val.ok.val);
        break;
    case BYTES:
        if (!frame->bytes.is_err) probe_list_u8_free(&frame->bytes.val.ok);
        break;
    case TRAILERS:
    case AGAIN:
        if (!frame->trailers.is_err) lsf_streaming_headers_close(&frame->trailers.val.ok);
        break;
    case WRITE: break;
    }
}

static probe_callback_code_t advance(struct frame *frame, lsf_async_result_t result) {
    for (;;) {
        if (result == LSF_ASYNC_PENDING) return lsf_async_wait(&frame->async);
        if (result == LSF_ASYNC_CANCELLED || result == LSF_ASYNC_CANCELLED_RETURNED) {
            if (result == LSF_ASYNC_CANCELLED_RETURNED) discard_returned(frame);
            cleanup(frame);
            probe_task_cancel();
            return PROBE_CALLBACK_CODE_EXIT;
        }
        probe_subtask_status_t status;
        switch (frame->phase) {
        case OPEN:
            if (frame->opened.is_err) {
                lsf_require(frame->opened.val.err.tag == LATENT_HTTP_STREAMING_HTTP_ERROR_PERMISSION_DENIED);
                return finish(frame, 10);
            }
            lsf_upload_adopt(&frame->upload, frame->opened.val.ok);
            if (frame->which == 1) return finish(frame, 1);
            frame->phase = WRITE;
            status = latent_http_streaming_write(lsf_upload_borrow(&frame->upload),
                (probe_list_u8_t){(uint8_t *)"data", 4}, &frame->written);
            break;
        case WRITE:
            lsf_require(!frame->written.is_err);
            frame->phase = FINISH;
            status = latent_http_streaming_finish(lsf_upload_move(&frame->upload), &frame->response);
            break;
        case FINISH:
            lsf_require(!frame->response.is_err);
            lsf_body_adopt(&frame->body, frame->response.val.ok.body);
            lsf_streaming_metadata_close(&frame->response.val.ok);
            if (frame->which == 2) return finish(frame, 2);
            frame->phase = READ;
            status = latent_http_streaming_read(lsf_body_borrow(&frame->body), 4, &frame->read);
            break;
        case READ:
            lsf_require(!frame->read.is_err);
            if (!frame->read.val.ok.is_some) {
                frame->phase = TRAILERS;
                status = latent_http_streaming_trailers(lsf_body_borrow(&frame->body), &frame->trailers);
            } else {
                lsf_http_chunk_adopt(&frame->chunk, frame->read.val.ok.val);
                if (frame->which == 3) lsf_body_close(&frame->body);
                frame->phase = BYTES;
                status = latent_http_streaming_chunk_bytes(lsf_http_chunk_borrow(&frame->chunk), &frame->bytes);
            }
            break;
        case BYTES:
            lsf_require(!frame->bytes.is_err);
            frame->count += frame->bytes.val.ok.len;
            probe_list_u8_free(&frame->bytes.val.ok);
            lsf_http_chunk_close(&frame->chunk);
            if (frame->which == 3) return finish(frame, frame->count);
            frame->phase = READ;
            status = latent_http_streaming_read(lsf_body_borrow(&frame->body), 4, &frame->read);
            break;
        case TRAILERS:
            lsf_require(!frame->trailers.is_err);
            lsf_streaming_headers_close(&frame->trailers.val.ok);
            frame->phase = AGAIN;
            status = latent_http_streaming_trailers(lsf_body_borrow(&frame->body), &frame->trailers);
            break;
        case AGAIN:
            lsf_require(frame->trailers.is_err &&
                        frame->trailers.val.err.tag == LATENT_HTTP_STREAMING_HTTP_ERROR_INVALID_STATE);
            return finish(frame, frame->count);
        default: __builtin_trap();
        }
        result = lsf_async_submit(&frame->async, status);
    }
}

probe_callback_code_t exports_tests_streaming_http_api_run(uint32_t which,
    probe_string_t *text, uint64_t handle) {
    (void)handle;
    struct frame *frame = calloc(1, sizeof(*frame));
    lsf_require(frame != NULL);
    lsf_scope_init(&frame->owned, 65536);
    frame->which = which;
    frame->request = (latent_http_streaming_request_t){
        .method = LATENT_HTTP_STREAMING_METHOD_POST, .url = *text,
        .body_length = {true, 4}, .body_media_type = {true, LSF_LITERAL("text/plain")},
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
    probe_subtask_status_t status = latent_http_streaming_open(&frame->request, &frame->opened);
    return advance(frame, lsf_async_submit(&frame->async, status));
}

probe_callback_code_t exports_tests_streaming_http_api_run_callback(probe_event_t *event) {
    struct frame *frame = probe_context_get_0();
    lsf_require(frame != NULL);
    return advance(frame, lsf_async_event(&frame->async, event));
}
