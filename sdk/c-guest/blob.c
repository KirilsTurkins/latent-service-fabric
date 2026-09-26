/* Generated C ABI conformance fixture. Each async task owns one finite frame.
 * Zig's allocator frees canonical ABI buffers; no WASI capability is imported.
 * Provider handles remain with their activation when deliberately abandoned.
 */
#include "probe.h"
#include <stdlib.h>
#include <string.h>

_Noreturn void abort(void) { __builtin_trap(); }

enum phase { CREATE, WRITE, SEAL, OPEN, READ, CLOSE, BYTES, AGAIN, CLOSED_WRITE };
struct frame {
    uint32_t which;
    uint64_t handle;
    enum phase phase;
    probe_subtask_t task;
    probe_waitable_set_t set;
    bool cancelling, owns_chunk;
    latent_blob_blob_own_chunk_t chunk;
    latent_blob_blob_blob_reference_t reference;
    latent_blob_blob_result_blob_handle_blob_error_t opened;
    latent_blob_blob_result_u64_blob_error_t written;
    latent_blob_blob_result_blob_reference_blob_error_t sealed;
    latent_blob_blob_result_own_chunk_blob_error_t read;
    latent_blob_blob_result_bool_blob_error_t closed;
    latent_blob_blob_result_list_u8_blob_error_t bytes;
};

static void require(bool condition) {
    if (!condition) __builtin_trap();
}

static void cleanup(struct frame *f) {
    require(!f->task);
    if (f->owns_chunk) latent_blob_blob_chunk_drop_own(f->chunk);
    latent_blob_blob_blob_reference_free(&f->reference);
    if (f->set) probe_waitable_set_drop(f->set);
    probe_context_set_0(NULL);
    free(f);
}

static probe_callback_code_t finish(struct frame *f, uint64_t value) {
    cleanup(f);
    exports_tests_local_blobs_api_run_return(value);
    return PROBE_CALLBACK_CODE_EXIT;
}

static probe_callback_code_t cancelled(struct frame *f) {
    cleanup(f);
    probe_task_cancel();
    return PROBE_CALLBACK_CODE_EXIT;
}

/* Canonical subtask cancellation is cooperative. Results and request storage
 * stay live until RETURNED or a confirmed cancellation, including STARTED
 * progress events. Leaving the waitable set is required before cancel/drop.
 */
static void drop_task(struct frame *f) {
    probe_waitable_join(f->task, 0);
    probe_subtask_drop(f->task);
    f->task = 0;
}

static void returned_ownership(struct frame *f) {
    if (f->phase == READ && !f->read.is_err) {
        f->chunk = f->read.val.ok;
        f->owns_chunk = true;
    }
    if (f->phase == SEAL && !f->sealed.is_err) f->reference = f->sealed.val.ok;
    if ((f->phase == BYTES || f->phase == AGAIN) && !f->bytes.is_err) {
        probe_list_u8_free(&f->bytes.val.ok);
        f->bytes.val.ok = (probe_list_u8_t){0};
    }
}

static probe_callback_code_t advance(struct frame *f);
static probe_callback_code_t completed(struct frame *f) {
    if (f->cancelling) {
        returned_ownership(f);
        return cancelled(f);
    }
    switch (f->phase) {
    case CREATE:
        if (f->opened.is_err) {
            require(f->opened.val.err.tag == LATENT_BLOB_BLOB_BLOB_ERROR_PERMISSION_DENIED);
            return finish(f, 11);
        }
        f->handle = f->opened.val.ok;
        if (f->which == 1) return finish(f, 1);
        if (f->which == 5) return finish(f, f->handle);
        f->phase = f->which == 2 ? CLOSE : WRITE;
        break;
    case WRITE:
        require(!f->written.is_err && f->written.val.ok == 4);
        f->phase = SEAL;
        break;
    case SEAL:
        require(!f->sealed.is_err);
        f->reference = f->sealed.val.ok;
        f->phase = OPEN;
        break;
    case OPEN:
        require(!f->opened.is_err);
        f->handle = f->opened.val.ok;
        latent_blob_blob_blob_reference_free(&f->reference);
        f->reference = (latent_blob_blob_blob_reference_t){0};
        f->phase = READ;
        break;
    case READ:
        require(!f->read.is_err);
        f->chunk = f->read.val.ok;
        f->owns_chunk = true;
        f->phase = CLOSE;
        break;
    case CLOSE:
        require(!f->closed.is_err && f->closed.val.ok);
        if (f->which == 3) return finish(f, 3); /* Drop the unmaterialized chunk. */
        f->phase = f->which == 2 ? CLOSED_WRITE : BYTES;
        break;
    case BYTES:
        require(!f->bytes.is_err && f->bytes.val.ok.len == 4);
        require(memcmp(f->bytes.val.ok.ptr, "data", 4) == 0);
        probe_list_u8_free(&f->bytes.val.ok);
        f->bytes.val.ok = (probe_list_u8_t){0};
        if (f->which != 6) return finish(f, 4);
        f->phase = AGAIN;
        break;
    case AGAIN:
        require(f->bytes.is_err && f->bytes.val.err.tag == LATENT_BLOB_BLOB_BLOB_ERROR_INVALID_STATE);
        return finish(f, 10);
    case CLOSED_WRITE:
        require(f->written.is_err);
        if (f->written.val.err.tag == LATENT_BLOB_BLOB_BLOB_ERROR_PERMISSION_DENIED) return finish(f, 11);
        require(f->written.val.err.tag == LATENT_BLOB_BLOB_BLOB_ERROR_INVALID_STATE);
        return finish(f, 10);
    }
    return advance(f);
}

static probe_callback_code_t advance(struct frame *f) {
    probe_subtask_status_t status;
    switch (f->phase) {
    case CREATE:
        status = latent_blob_blob_create((probe_string_t){(uint8_t *)"text/plain", 10},
            (probe_option_u64_t){true, f->which == 2 || f->which == 5 ? 0 : 4}, &f->opened);
        break;
    case WRITE:
        status = latent_blob_blob_write(f->handle, 0, (probe_list_u8_t){(uint8_t *)"data", 4}, &f->written);
        break;
    case SEAL: status = latent_blob_blob_seal(f->handle, &f->sealed); break;
    case OPEN: status = latent_blob_blob_open(&f->reference, &f->opened); break;
    case READ: status = latent_blob_blob_read(f->handle, 0, 4, &f->read); break;
    case CLOSE: status = latent_blob_blob_close(f->handle, &f->closed); break;
    case BYTES:
    case AGAIN: status = latent_blob_blob_chunk_bytes(latent_blob_blob_borrow_chunk(f->chunk), &f->bytes); break;
    case CLOSED_WRITE: status = latent_blob_blob_write(f->handle, 0, (probe_list_u8_t){0}, &f->written); break;
    default: __builtin_trap();
    }
    if (PROBE_SUBTASK_STATE(status) == PROBE_SUBTASK_RETURNED) return completed(f);
    require(PROBE_SUBTASK_STATE(status) == PROBE_SUBTASK_STARTING || PROBE_SUBTASK_STATE(status) == PROBE_SUBTASK_STARTED);
    f->task = PROBE_SUBTASK_HANDLE(status);
    if (!f->set) f->set = probe_waitable_set_new();
    probe_waitable_join(f->task, f->set);
    return PROBE_CALLBACK_CODE_WAIT(f->set);
}

probe_callback_code_t exports_tests_local_blobs_api_run(uint32_t which, probe_string_t *text, uint64_t handle) {
    require(probe_context_get_0() == NULL && which <= 6);
    probe_string_free(text); /* This fixture consumes its owned invocation input. */
    struct frame *f = calloc(1, sizeof(*f));
    require(f != NULL);
    f->which = which;
    f->handle = handle;
    f->phase = which == 4 ? CLOSED_WRITE : CREATE;
    probe_context_set_0(f);
    return advance(f);
}

probe_callback_code_t exports_tests_local_blobs_api_run_callback(probe_event_t *event) {
    struct frame *f = probe_context_get_0();
    require(f != NULL && f->task != 0);
    if (event->event == PROBE_EVENT_CANCEL) {
        require(!f->cancelling);
        f->cancelling = true;
        probe_waitable_join(f->task, 0);
        uint32_t status = probe_subtask_cancel(f->task);
        if (status == UINT32_MAX) {
            probe_waitable_join(f->task, f->set);
            return PROBE_CALLBACK_CODE_WAIT(f->set);
        }
        drop_task(f);
        if (status == PROBE_SUBTASK_RETURNED) returned_ownership(f);
        else require(status == PROBE_SUBTASK_STARTED_CANCELLED || status == PROBE_SUBTASK_RETURNED_CANCELLED);
        return cancelled(f);
    }
    require(event->event == PROBE_EVENT_SUBTASK && event->waitable == f->task);
    if (event->code == PROBE_SUBTASK_STARTED) return PROBE_CALLBACK_CODE_WAIT(f->set);
    drop_task(f);
    if (event->code == PROBE_SUBTASK_RETURNED) return completed(f);
    require(f->cancelling && (event->code == PROBE_SUBTASK_STARTED_CANCELLED || event->code == PROBE_SUBTASK_RETURNED_CANCELLED));
    return cancelled(f);
}
