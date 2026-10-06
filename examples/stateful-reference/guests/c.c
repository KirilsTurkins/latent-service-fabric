// lsf-example-begin: order-draft
#include "lsf/intents.h"
#include <string.h>

enum phase { READ_PRIMARY, READ_SUMMARY, WRITE_PRIMARY, WRITE_SUMMARY, STAGE_EVENT, STAGE_HTTP };
struct frame {
    lsf_scope_t scope;
    lsf_async_t async;
    lsf_state_call_t call;
    lsf_intent_call_t intent_call;
    lsf_state_command_t command;
    lsf_state_query_t query;
    enum phase phase;
    bool edit, reject;
    uint64_t expected, revision;
    uint32_t units;
    probe_string_t id;
    uint8_t primary_key[46], summary_key[48], bytes[12], event[48];
    size_t primary_size, summary_size;
    latent_state_key_value_result_option_versioned_value_state_error_t primary, summary;
    latent_state_key_value_result_void_state_error_t write;
    latent_intents_staging_result_staged_intent_intent_error_t staged;
    latent_state_key_value_value_t value, payload;
};
static const char media[] = "application/vnd.lsf.order-draft-v1";
static bool namespace_matches(probe_string_t name, struct frame *f) {
    const char prefix[] = "order-drafts-";
    return name.len == sizeof(prefix) - 1 + f->id.len
        && memcmp(name.ptr, prefix, sizeof(prefix) - 1) == 0
        && memcmp(name.ptr + sizeof(prefix) - 1, f->id.ptr, f->id.len) == 0;
}
static probe_list_u8_t primary_key(struct frame *f) { return (probe_list_u8_t){f->primary_key, f->primary_size}; }
static probe_list_u8_t summary_key(struct frame *f) { return (probe_list_u8_t){f->summary_key, f->summary_size}; }
static void cleanup(struct frame *f) {
    lsf_require(f->call.access == NULL && f->intent_call.borrow.access == NULL);
    lsf_state_get_result_close(&f->primary); lsf_state_get_result_close(&f->summary);
    if (f->id.len) free(f->id.ptr);
    lsf_scope_close(&f->scope); lsf_async_close(&f->async); lsf_frame_leave(f); free(f);
}
static probe_callback_code_t finish(struct frame *f, bool failed, exports_examples_order_draft_api_business_error_t error) {
    exports_examples_order_draft_api_result_draft_business_error_t result = {.is_err = failed};
    bool edit = f->edit;
    if (failed) result.val.err = error;
    else {
        latent_state_key_value_state_error_t denied;
        probe_list_u8_t namespace_view;
        if (edit) {
            latent_state_key_value_command_info_t info = {0};
            lsf_require(lsf_state_command_info(&f->command, &info, &denied));
            namespace_view = (probe_list_u8_t){info.view.version.ptr, info.view.version.len};
            info.view.version = (latent_state_key_value_version_t){0};
            latent_state_key_value_command_info_free(&info);
        } else {
            latent_state_key_value_view_identity_t info = {0};
            lsf_require(lsf_state_query_info(&f->query, &info, &denied));
            namespace_view = (probe_list_u8_t){info.version.ptr, info.version.len};
            info.version = (latent_state_key_value_version_t){0};
            latent_state_key_value_view_identity_free(&info);
        }
        probe_option_list_u8_t version = {0};
        if (f->primary.val.ok.is_some) {
            version.is_some = true;
            version.val = (probe_list_u8_t){f->primary.val.ok.val.version.ptr, f->primary.val.ok.val.version.len};
            f->primary.val.ok.val.version = (latent_state_key_value_version_t){0};
        }
        result.val.ok = (exports_examples_order_draft_api_draft_t){f->id, f->revision, f->units, namespace_view, version};
        f->id = (probe_string_t){0};
    }
    cleanup(f);
    if (edit) exports_examples_order_draft_api_edit_return(result);
    else exports_examples_order_draft_api_query_return(result);
    if (!failed) {
        if (result.val.ok.draft_id.len) free(result.val.ok.draft_id.ptr);
        if (result.val.ok.namespace_view.len) free(result.val.ok.namespace_view.ptr);
        if (result.val.ok.key_version.is_some && result.val.ok.key_version.val.len) free(result.val.ok.key_version.val.ptr);
    }
    return PROBE_CALLBACK_CODE_EXIT;
}
static bool valid_value(latent_state_key_value_value_t *v) {
    return v->bytes.len == 12 && v->metadata.len == 0 && v->media_type.len == sizeof(media) - 1
        && memcmp(v->media_type.ptr, media, sizeof(media) - 1) == 0;
}
static bool decode(struct frame *f) {
    bool a = f->primary.val.ok.is_some, b = f->summary.val.ok.is_some;
    if (!a && !b) { f->revision = 0; if (!f->edit) f->units = 0; return true; }
    if (!a || !b) return false;
    latent_state_key_value_value_t *first = &f->primary.val.ok.val.value, *second = &f->summary.val.ok.val.value;
    if (!valid_value(first) || !valid_value(second) || memcmp(first->bytes.ptr, second->bytes.ptr, 12)) return false;
    f->revision = 0; uint32_t units = 0;
    for (size_t i = 0; i < 8; i++) f->revision |= (uint64_t)first->bytes.ptr[i] << (8 * i);
    for (size_t i = 0; i < 4; i++) units |= (uint32_t)first->bytes.ptr[8 + i] << (8 * i);
    if (!f->edit) f->units = units;
    return f->revision != 0 && units <= 10000;
}
static probe_callback_code_t pump(struct frame *f, lsf_async_result_t state) {
    for (;;) {
        if (state == LSF_ASYNC_PENDING) return lsf_async_wait(&f->async);
        if (f->phase == STAGE_EVENT || f->phase == STAGE_HTTP) lsf_intent_retire(&f->intent_call);
        else lsf_state_call_retire(&f->call);
        if (state == LSF_ASYNC_CANCELLED || state == LSF_ASYNC_CANCELLED_RETURNED) {
            cleanup(f); probe_task_cancel(); return PROBE_CALLBACK_CODE_EXIT;
        }
        probe_subtask_status_t status;
        switch (f->phase) {
        case READ_PRIMARY:
            lsf_require(!f->primary.is_err);
            f->phase = READ_SUMMARY;
            status = f->edit ? lsf_state_get(&f->call, &f->command, summary_key(f), &f->summary)
                             : lsf_state_get_query(&f->call, &f->query, summary_key(f), &f->summary);
            break;
        case READ_SUMMARY:
            lsf_require(!f->summary.is_err);
            if (!decode(f)) return finish(f, true, EXPORTS_EXAMPLES_ORDER_DRAFT_API_BUSINESS_ERROR_MALFORMED_STATE);
            if (!f->edit) return finish(f, false, 0);
            if (f->revision != f->expected) return finish(f, true, EXPORTS_EXAMPLES_ORDER_DRAFT_API_BUSINESS_ERROR_STALE_EDIT);
            if (f->revision == UINT64_MAX) return finish(f, true, EXPORTS_EXAMPLES_ORDER_DRAFT_API_BUSINESS_ERROR_REVISION_OVERFLOW);
            f->revision++;
            for (size_t i = 0; i < 8; i++) f->bytes[i] = (uint8_t)(f->revision >> (8 * i));
            for (size_t i = 0; i < 4; i++) f->bytes[8 + i] = (uint8_t)(f->units >> (8 * i));
            f->value = (latent_state_key_value_value_t){.bytes = {f->bytes, 12}, .media_type = LSF_LITERAL("application/vnd.lsf.order-draft-v1")};
            memcpy(f->event, "draft-change-v1:", 16); memcpy(f->event + 16, f->id.ptr, f->id.len);
            f->payload = (latent_state_key_value_value_t){.bytes = {f->event, f->id.len + 16}, .media_type = LSF_LITERAL("application/octet-stream")};
            f->phase = WRITE_PRIMARY;
            status = lsf_state_put(&f->call, &f->command, primary_key(f), f->value, &f->write); break;
        case WRITE_PRIMARY:
            lsf_require(!f->write.is_err); f->phase = WRITE_SUMMARY;
            status = lsf_state_put(&f->call, &f->command, summary_key(f), f->value, &f->write); break;
        case WRITE_SUMMARY:
            lsf_require(!f->write.is_err); f->phase = STAGE_EVENT;
            status = lsf_intent_stage(&f->intent_call, &f->command,
                lsf_intent(LSF_LITERAL("draft-change"), LSF_LITERAL("event"), f->payload, (probe_option_u64_t){0}), &f->staged); break;
        case STAGE_EVENT:
            lsf_require(!f->staged.is_err); f->phase = STAGE_HTTP;
            status = lsf_intent_stage(&f->intent_call, &f->command,
                lsf_intent(LSF_LITERAL("draft-http"), LSF_LITERAL("put-once"), f->payload, (probe_option_u64_t){0}), &f->staged); break;
        case STAGE_HTTP:
            lsf_require(!f->staged.is_err);
            return finish(f, f->reject, EXPORTS_EXAMPLES_ORDER_DRAFT_API_BUSINESS_ERROR_REJECTED);
        default: __builtin_trap();
        }
        state = lsf_async_submit(&f->async, status);
    }
}
static struct frame *start(bool edit, probe_string_t id) {
    struct frame *f = calloc(1, sizeof(*f)); lsf_require(f != NULL); f->edit = edit; lsf_frame_enter(f);
    if (id.len == 0 || id.len > 32) return f;
    for (size_t i = 0; i < id.len; i++) {
        uint8_t c = id.ptr[i];
        if (!(c >= 'a' && c <= 'z') && !(c >= '0' && c <= '9') && !(i && c == '-')) return f;
    }
    f->id.ptr = malloc(id.len); lsf_require(f->id.ptr != NULL); memcpy(f->id.ptr, id.ptr, id.len); f->id.len = id.len;
    memcpy(f->primary_key, "drafts/", 7); memcpy(f->primary_key + 7, id.ptr, id.len); memcpy(f->primary_key + 7 + id.len, "/draft", 6); f->primary_size = id.len + 13;
    memcpy(f->summary_key, "drafts/", 7); memcpy(f->summary_key + 7, id.ptr, id.len); memcpy(f->summary_key + 7 + id.len, "/summary", 8); f->summary_size = id.len + 15;
    return f;
}
probe_callback_code_t exports_examples_order_draft_api_edit(exports_examples_order_draft_api_edit_request_t *request) {
    struct frame *f = start(true, request->draft_id);
    if (!f->id.len) return finish(f, true, EXPORTS_EXAMPLES_ORDER_DRAFT_API_BUSINESS_ERROR_INVALID_DRAFT);
    if (request->units > 10000) return finish(f, true, EXPORTS_EXAMPLES_ORDER_DRAFT_API_BUSINESS_ERROR_INVALID_UNITS);
    f->expected = request->expected_revision; f->units = request->units; f->reject = request->reject;
    latent_state_key_value_state_error_t denied;
    lsf_require(lsf_state_acquire_command(&f->scope, &f->command, &denied));
    latent_state_key_value_command_info_t info = {0};
    lsf_require(lsf_state_command_info(&f->command, &info, &denied));
    bool permitted = namespace_matches(info.view.namespace, f);
    latent_state_key_value_command_info_free(&info);
    if (!permitted) return finish(f, true, EXPORTS_EXAMPLES_ORDER_DRAFT_API_BUSINESS_ERROR_INVALID_DRAFT);
    f->phase = READ_PRIMARY;
    return pump(f, lsf_async_submit(&f->async, lsf_state_get(&f->call, &f->command, primary_key(f), &f->primary)));
}
probe_callback_code_t exports_examples_order_draft_api_query(probe_string_t *id) {
    struct frame *f = start(false, *id);
    if (!f->id.len) return finish(f, true, EXPORTS_EXAMPLES_ORDER_DRAFT_API_BUSINESS_ERROR_INVALID_DRAFT);
    latent_state_key_value_state_error_t denied;
    lsf_require(lsf_state_acquire_query(&f->scope, &f->query, &denied));
    latent_state_key_value_view_identity_t info = {0};
    lsf_require(lsf_state_query_info(&f->query, &info, &denied));
    bool permitted = namespace_matches(info.namespace, f);
    latent_state_key_value_view_identity_free(&info);
    if (!permitted) return finish(f, true, EXPORTS_EXAMPLES_ORDER_DRAFT_API_BUSINESS_ERROR_INVALID_DRAFT);
    f->phase = READ_PRIMARY;
    return pump(f, lsf_async_submit(&f->async, lsf_state_get_query(&f->call, &f->query, primary_key(f), &f->primary)));
}
static probe_callback_code_t callback(probe_event_t *event) {
    struct frame *f = lsf_frame_current(); lsf_require(f != NULL); return pump(f, lsf_async_event(&f->async, event));
}
probe_callback_code_t exports_examples_order_draft_api_edit_callback(probe_event_t *event) { return callback(event); }
probe_callback_code_t exports_examples_order_draft_api_query_callback(probe_event_t *event) { return callback(event); }
// lsf-example-end: order-draft
