// lsf-example-begin: capsule
#include "lsf/intents.h"
#include <string.h>

enum operation { UPDATE, QUERY, SCAN };
enum phase { READ_OLD, WRITE_VALUE, STAGE_EVENT, READ_STAGED, OPEN_PAGE, NEXT_ENTRY };
struct frame {
    lsf_scope_t scope;
    lsf_async_t async;
    lsf_state_call_t call;
    lsf_intent_call_t intent_call;
    lsf_state_command_t command;
    lsf_state_query_t query;
    lsf_state_page_t page;
    enum operation operation;
    enum phase phase;
    uint32_t delta, limit, entries;
    bool reject;
    uint64_t count;
    uint8_t bytes[8];
    probe_list_u8_t prefix;
    probe_option_list_u8_t cursor;
    latent_state_key_value_value_t value;
    latent_state_key_value_result_option_versioned_value_state_error_t read;
    latent_state_key_value_result_void_state_error_t write;
    latent_intents_staging_result_staged_intent_intent_error_t staged;
    latent_state_key_value_result_own_page_state_error_t scan;
    latent_state_key_value_result_option_entry_state_error_t entry;
    latent_state_key_value_page_info_t page_info;
};
static uint8_t key_bytes[] = "aggregate/count";
static const char media[] = "application/vnd.lsf.aggregate-v1";
static probe_list_u8_t key(void) { return (probe_list_u8_t){key_bytes, sizeof(key_bytes) - 1}; }

static void cleanup(struct frame *frame) {
    /* This runs only after the outstanding canonical subtask physically retires. */
    lsf_require(frame->call.access == NULL && frame->intent_call.borrow.access == NULL);
    lsf_state_get_result_close(&frame->read);
    lsf_state_entry_result_close(&frame->entry);
    latent_state_key_value_page_info_free(&frame->page_info);
    if (frame->prefix.len) free(frame->prefix.ptr);
    if (frame->cursor.is_some && frame->cursor.val.len) free(frame->cursor.val.ptr);
    lsf_scope_close(&frame->scope); /* Reverse order: pages before original view. */
    lsf_async_close(&frame->async);
    lsf_frame_leave(frame);
    free(frame);
}
static probe_callback_code_t aggregate_return(struct frame *frame, bool is_error,
    exports_examples_transactional_aggregate_api_business_error_t error, probe_list_u8_t version) {
    enum operation operation = frame->operation;
    exports_examples_transactional_aggregate_api_result_aggregate_business_error_t result = {.is_err = is_error};
    if (is_error) result.val.err = error;
    else result.val.ok = (exports_examples_transactional_aggregate_api_aggregate_t){frame->count, version};
    cleanup(frame);
    if (operation == UPDATE) exports_examples_transactional_aggregate_api_update_return(result);
    else exports_examples_transactional_aggregate_api_query_return(result);
    /* The pinned generator's aggregate result-free skips reused list types. */
    if (!is_error && result.val.ok.version.len) free(result.val.ok.version.ptr);
    return PROBE_CALLBACK_CODE_EXIT;
}
static bool decode(struct frame *frame) {
    frame->count = 0;
    if (!frame->read.val.ok.is_some) return true;
    latent_state_key_value_value_t *value = &frame->read.val.ok.val.value;
    if (value->bytes.len != 8 || value->metadata.len != 0 || value->media_type.len != sizeof(media) - 1
        || memcmp(value->media_type.ptr, media, sizeof(media) - 1) != 0) return false;
    for (size_t i = 0; i < 8; i++) frame->count |= (uint64_t)value->bytes.ptr[i] << (8 * i);
    return true;
}
static probe_callback_code_t pump(struct frame *frame, lsf_async_result_t state) {
    for (;;) {
        if (state == LSF_ASYNC_PENDING) return lsf_async_wait(&frame->async);
        if (frame->phase == STAGE_EVENT) lsf_intent_retire(&frame->intent_call);
        else lsf_state_call_retire(&frame->call);
        if (state == LSF_ASYNC_CANCELLED || state == LSF_ASYNC_CANCELLED_RETURNED) {
            /* A returned page owner must be released even when its waiter left. */
            if (state == LSF_ASYNC_CANCELLED_RETURNED && frame->phase == OPEN_PAGE && !frame->scan.is_err)
                latent_state_key_value_page_drop_own(frame->scan.val.ok);
            cleanup(frame);
            probe_task_cancel();
            return PROBE_CALLBACK_CODE_EXIT;
        }
        probe_subtask_status_t status;
        switch (frame->phase) {
        case READ_OLD:
            lsf_require(!frame->read.is_err); /* Denials remain platform failures, never absence. */
            if (!decode(frame)) return aggregate_return(frame, true,
                EXPORTS_EXAMPLES_TRANSACTIONAL_AGGREGATE_API_BUSINESS_ERROR_MALFORMED_STATE, (probe_list_u8_t){0});
            if (frame->operation == QUERY) {
                latent_state_key_value_view_identity_t info = {0};
                latent_state_key_value_state_error_t error;
                lsf_require(lsf_state_query_info(&frame->query, &info, &error));
                probe_list_u8_t version = {info.version.ptr, info.version.len};
                info.version = (latent_state_key_value_version_t){0};
                latent_state_key_value_view_identity_free(&info);
                return aggregate_return(frame, false, 0, version);
            }
            if (UINT64_MAX - frame->count < frame->delta) return aggregate_return(frame, true,
                EXPORTS_EXAMPLES_TRANSACTIONAL_AGGREGATE_API_BUSINESS_ERROR_OVERFLOW, (probe_list_u8_t){0});
            frame->count += frame->delta;
            lsf_state_get_result_close(&frame->read);
            for (size_t i = 0; i < 8; i++) frame->bytes[i] = (uint8_t)(frame->count >> (8 * i));
            frame->value = (latent_state_key_value_value_t){
                .bytes = {frame->bytes, sizeof(frame->bytes)}, .media_type = LSF_LITERAL("application/vnd.lsf.aggregate-v1")};
            frame->phase = WRITE_VALUE;
            status = lsf_state_put(&frame->call, &frame->command, key(), frame->value, &frame->write);
            break;
        case WRITE_VALUE:
            lsf_require(!frame->write.is_err);
            frame->phase = STAGE_EVENT;
            status = lsf_intent_stage(&frame->intent_call, &frame->command,
                lsf_intent(LSF_LITERAL("approved-event"), LSF_LITERAL("event"), frame->value, (probe_option_u64_t){0}), &frame->staged);
            break;
        case STAGE_EVENT:
            lsf_require(!frame->staged.is_err);
            if (frame->reject) return aggregate_return(frame, true,
                EXPORTS_EXAMPLES_TRANSACTIONAL_AGGREGATE_API_BUSINESS_ERROR_REJECTED, (probe_list_u8_t){0});
            frame->phase = READ_STAGED;
            status = lsf_state_get(&frame->call, &frame->command, key(), &frame->read);
            break;
        case READ_STAGED: {
            lsf_require(!frame->read.is_err && frame->read.val.ok.is_some);
            probe_list_u8_t version = {frame->read.val.ok.val.version.ptr, frame->read.val.ok.val.version.len};
            frame->read.val.ok.val.version = (latent_state_key_value_version_t){0};
            return aggregate_return(frame, false, 0, version);
        }
        case OPEN_PAGE: {
            lsf_require(!frame->scan.is_err);
            frame->page = lsf_state_adopt_page(frame->query.cell, frame->scan.val.ok);
            latent_state_key_value_state_error_t error;
            lsf_require(lsf_state_page_info(&frame->page, &frame->page_info, &error));
            frame->phase = NEXT_ENTRY;
            status = lsf_state_page_next(&frame->call, &frame->page, &frame->entry);
            break;
        }
        case NEXT_ENTRY:
            lsf_require(!frame->entry.is_err);
            if (!frame->entry.val.ok.is_some) {
                lsf_require(frame->entries == frame->page_info.entry_count);
                exports_examples_transactional_aggregate_api_result_scan_result_business_error_t result = {0};
                result.val.ok = (exports_examples_transactional_aggregate_api_scan_result_t){
                    .count = frame->entries, .encoded_bytes = frame->page_info.encoded_bytes,
                    .view_version = {frame->page_info.view.version.ptr, frame->page_info.view.version.len},
                    .next_cursor = frame->page_info.next_cursor};
                frame->page_info.view.version = (latent_state_key_value_version_t){0};
                frame->page_info.next_cursor = (probe_option_list_u8_t){0};
                cleanup(frame);
                exports_examples_transactional_aggregate_api_scan_return(result);
                if (result.val.ok.view_version.len) free(result.val.ok.view_version.ptr);
                if (result.val.ok.next_cursor.is_some && result.val.ok.next_cursor.val.len) free(result.val.ok.next_cursor.val.ptr);
                return PROBE_CALLBACK_CODE_EXIT;
            }
            frame->entries++;
            lsf_state_entry_result_close(&frame->entry);
            status = lsf_state_page_next(&frame->call, &frame->page, &frame->entry);
            break;
        default: __builtin_trap();
        }
        state = lsf_async_submit(&frame->async, status);
    }
}
static struct frame *start(enum operation operation) {
    struct frame *frame = calloc(1, sizeof(*frame)); lsf_require(frame != NULL);
    frame->operation = operation;
    lsf_frame_enter(frame);
    latent_state_key_value_state_error_t error;
    if (operation == UPDATE) lsf_require(lsf_state_acquire_command(&frame->scope, &frame->command, &error));
    else lsf_require(lsf_state_acquire_query(&frame->scope, &frame->query, &error));
    return frame;
}
probe_callback_code_t exports_examples_transactional_aggregate_api_update(
    exports_examples_transactional_aggregate_api_update_request_t *request) {
    struct frame *frame = start(UPDATE); frame->delta = request->delta; frame->reject = request->reject;
    frame->phase = READ_OLD;
    return pump(frame, lsf_async_submit(&frame->async, lsf_state_get(&frame->call, &frame->command, key(), &frame->read)));
}
probe_callback_code_t exports_examples_transactional_aggregate_api_query(void) {
    struct frame *frame = start(QUERY); frame->phase = READ_OLD;
    return pump(frame, lsf_async_submit(&frame->async, lsf_state_get_query(&frame->call, &frame->query, key(), &frame->read)));
}
probe_callback_code_t exports_examples_transactional_aggregate_api_scan(probe_list_u8_t *prefix, uint32_t limit,
    probe_list_u8_t *maybe_cursor) {
    struct frame *frame = start(SCAN); frame->phase = OPEN_PAGE; frame->prefix = *prefix; *prefix = (probe_list_u8_t){0};
    frame->limit = limit;
    if (maybe_cursor != NULL) { frame->cursor = (probe_option_list_u8_t){true, *maybe_cursor}; *maybe_cursor = (probe_list_u8_t){0}; }
    return pump(frame, lsf_async_submit(&frame->async,
        lsf_state_scan_query(&frame->call, &frame->query, frame->prefix, limit, frame->cursor, &frame->scan)));
}
static probe_callback_code_t callback(probe_event_t *event) {
    struct frame *frame = probe_context_get_0(); lsf_require(frame != NULL);
    return pump(frame, lsf_async_event(&frame->async, event));
}
probe_callback_code_t exports_examples_transactional_aggregate_api_update_callback(probe_event_t *event) { return callback(event); }
probe_callback_code_t exports_examples_transactional_aggregate_api_query_callback(probe_event_t *event) { return callback(event); }
probe_callback_code_t exports_examples_transactional_aggregate_api_scan_callback(probe_event_t *event) { return callback(event); }
// lsf-example-end: capsule
