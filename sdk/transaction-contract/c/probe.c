/* Actual maintained async C compiler input, never an implementation of the host. */
#include "probe.h"
#include "lsf/guest.h"
#include "lsf/async.h"

enum phase { GET, PUT, DELETE, SCAN, NEXT, STAGE };
struct frame {
    lsf_async_t async;
    enum phase phase;
    bool query, has_access, has_page;
    uint64_t count;
    latent_state_key_value_own_transaction_t transaction;
    latent_state_key_value_own_query_view_t view;
    latent_state_key_value_own_page_t page;
    latent_state_key_value_result_option_versioned_value_state_error_t value;
    latent_state_key_value_result_void_state_error_t mutation;
    latent_state_key_value_result_own_page_state_error_t scanned;
    latent_state_key_value_result_option_entry_state_error_t entry;
    latent_intents_staging_result_staged_intent_intent_error_t staged;
    latent_state_key_value_put_args_t put;
    latent_state_key_value_scan_args_t scan;
    latent_state_key_value_scan_query_args_t scan_query;
    latent_intents_staging_stage_args_t stage;
    probe_tuple2_string_string_t metadata;
};

static void cleanup(struct frame *f) {
    lsf_async_close(&f->async);
    if (f->has_page) latent_state_key_value_page_drop_own(f->page);
    if (f->has_access) {
        if (f->query) latent_state_key_value_query_view_drop_own(f->view);
        else latent_state_key_value_transaction_drop_own(f->transaction);
    }
    lsf_frame_leave(f);
    free(f);
}

static probe_callback_code_t finish(struct frame *f) {
    uint64_t count = f->count;
    cleanup(f);
    exports_tests_transaction_contract_api_run_return(count);
    return PROBE_CALLBACK_CODE_EXIT;
}

/* A cancelled host call can still return an owned page or allocated data. */
static void discard(struct frame *f) {
    switch (f->phase) {
    case GET: latent_state_key_value_result_option_versioned_value_state_error_free(&f->value); break;
    case SCAN: if (!f->scanned.is_err) latent_state_key_value_page_drop_own(f->scanned.val.ok); break;
    case NEXT: latent_state_key_value_result_option_entry_state_error_free(&f->entry); break;
    case PUT: case DELETE: case STAGE: break;
    }
}

static probe_callback_code_t advance(struct frame *f, lsf_async_result_t result) {
    for (;;) {
        if (result == LSF_ASYNC_PENDING) return lsf_async_wait(&f->async);
        if (result == LSF_ASYNC_CANCELLED || result == LSF_ASYNC_CANCELLED_RETURNED) {
            if (result == LSF_ASYNC_CANCELLED_RETURNED) discard(f);
            cleanup(f);
            probe_task_cancel();
            return PROBE_CALLBACK_CODE_EXIT;
        }
        probe_subtask_status_t status;
        switch (f->phase) {
        case GET:
            lsf_require(!f->value.is_err);
            f->count += f->value.val.ok.is_some;
            latent_state_key_value_result_option_versioned_value_state_error_free(&f->value);
            if (!f->query) {
                f->phase = PUT;
                status = latent_state_key_value_put(&f->put, &f->mutation);
                break;
            }
            f->phase = SCAN;
            status = latent_state_key_value_scan_query(&f->scan_query, &f->scanned);
            break;
        case PUT:
            lsf_require(!f->mutation.is_err);
            f->phase = DELETE;
            status = latent_state_key_value_delete(latent_state_key_value_borrow_transaction(f->transaction),
                (probe_list_u8_t){(uint8_t *)"k", 1}, &f->mutation);
            break;
        case DELETE:
            lsf_require(!f->mutation.is_err);
            f->phase = SCAN;
            status = latent_state_key_value_scan(&f->scan, &f->scanned);
            break;
        case SCAN: {
            lsf_require(!f->scanned.is_err);
            f->page = f->scanned.val.ok;
            f->has_page = true;
            latent_state_key_value_page_info_t info;
            latent_state_key_value_state_error_t error;
            lsf_require(latent_state_key_value_describe_page(latent_state_key_value_borrow_page(f->page), &info, &error));
            f->count += info.entry_count;
            latent_state_key_value_page_info_free(&info);
            f->phase = NEXT;
            status = latent_state_key_value_page_next(latent_state_key_value_borrow_page(f->page), &f->entry);
            break;
        }
        case NEXT:
            lsf_require(!f->entry.is_err);
            f->count += f->entry.val.ok.is_some;
            latent_state_key_value_result_option_entry_state_error_free(&f->entry);
            if (f->query) return finish(f);
            f->phase = STAGE;
            status = latent_intents_staging_stage(&f->stage, &f->staged);
            break;
        case STAGE:
            lsf_require(!f->staged.is_err);
            f->count += f->staged.val.ok.sequence;
            return finish(f);
        default: __builtin_trap();
        }
        result = lsf_async_submit(&f->async, status);
    }
}

probe_callback_code_t exports_tests_transaction_contract_api_run(uint32_t mode) {
    struct frame *f = calloc(1, sizeof(*f));
    lsf_require(f != NULL);
    f->query = mode == 0;
    f->phase = GET;
    lsf_frame_enter(f);
    latent_state_key_value_state_error_t error;
    probe_subtask_status_t status;
    if (f->query) {
        lsf_require(latent_state_key_value_acquire_query(&f->view, &error));
        f->has_access = true;
        latent_state_key_value_view_identity_t info;
        lsf_require(latent_state_key_value_query_info(latent_state_key_value_borrow_query_view(f->view), &info, &error));
        f->count += info.version.len;
        latent_state_key_value_view_identity_free(&info);
        f->scan_query = (latent_state_key_value_scan_query_args_t){
            .view = latent_state_key_value_borrow_query_view(f->view), .limit = 1 };
        status = latent_state_key_value_get_query(latent_state_key_value_borrow_query_view(f->view),
            (probe_list_u8_t){(uint8_t *)"k", 1}, &f->value);
    } else {
        lsf_require(latent_state_key_value_acquire_command(&f->transaction, &error));
        f->has_access = true;
        latent_state_key_value_command_info_t info;
        lsf_require(latent_state_key_value_info(latent_state_key_value_borrow_transaction(f->transaction), &info, &error));
        f->count += info.command_id.len;
        latent_state_key_value_command_info_free(&info);
        f->metadata = (probe_tuple2_string_string_t){LSF_LITERAL("present"), LSF_LITERAL("")};
        f->put = (latent_state_key_value_put_args_t){
            .transaction = latent_state_key_value_borrow_transaction(f->transaction),
            .key = {(uint8_t *)"k", 1},
            .value = { .media_type = LSF_LITERAL("application/octet-stream"), .metadata = {&f->metadata, 1} } };
        f->scan = (latent_state_key_value_scan_args_t){
            .transaction = latent_state_key_value_borrow_transaction(f->transaction), .limit = 1 };
        f->stage = (latent_intents_staging_stage_args_t){
            .transaction = latent_state_key_value_borrow_transaction(f->transaction),
            .intent = { .binding = LSF_LITERAL("approved-mail"), .operation = LSF_LITERAL("send"),
                .payload = f->put.value, .expires_at_unix_millis = {true, UINT64_MAX} } };
        status = latent_state_key_value_get(latent_state_key_value_borrow_transaction(f->transaction),
            (probe_list_u8_t){(uint8_t *)"k", 1}, &f->value);
    }
    return advance(f, lsf_async_submit(&f->async, status));
}

probe_callback_code_t exports_tests_transaction_contract_api_run_callback(probe_event_t *event) {
    struct frame *f = probe_context_get_0();
    lsf_require(f != NULL);
    return advance(f, lsf_async_event(&f->async, event));
}
