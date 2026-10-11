/* SPDX-License-Identifier: Apache-2.0 */
#ifndef LSF_GUEST_STATE_H
#define LSF_GUEST_STATE_H
#include "guest.h"
#include "async.h"

/* Cells are allocated in the caller's finite lexical scope. Aliases share the
 * same live/borrowed state; they never own a second canonical host handle.
 * A scope and all request/result buffers must outlive pending callback frames. */
typedef enum { LSF_STATE_COMMAND, LSF_STATE_QUERY, LSF_STATE_PAGE } lsf_state_kind_t;
typedef struct lsf_state_cell {
    lsf_scope_t *scope;
    struct lsf_state_cell *parent;
    lsf_state_kind_t kind;
    bool live, borrowed;
    uint32_t pages;
    union {
        latent_state_key_value_own_transaction_t command;
        latent_state_key_value_own_query_view_t query;
        latent_state_key_value_own_page_t page;
    } raw;
} lsf_state_cell_t;
typedef struct { lsf_state_cell_t *cell; } lsf_state_command_t;
typedef struct { lsf_state_cell_t *cell; } lsf_state_query_t;
typedef struct { lsf_state_cell_t *cell; } lsf_state_page_t;

static inline void lsf_state_close_cell(lsf_state_cell_t *cell) {
    lsf_require(cell != NULL && !cell->borrowed);
    if (!cell->live) return;
    lsf_require(cell->pages == 0);
    cell->live = false; /* Consumption remains final if the host drop traps. */
    if (cell->parent) {
        lsf_require(cell->parent->pages != 0);
        cell->parent->pages--;
    }
    switch (cell->kind) {
    case LSF_STATE_COMMAND: latent_state_key_value_transaction_drop_own(cell->raw.command); break;
    case LSF_STATE_QUERY: latent_state_key_value_query_view_drop_own(cell->raw.query); break;
    case LSF_STATE_PAGE: latent_state_key_value_page_drop_own(cell->raw.page); break;
    default: __builtin_trap();
    }
}
static inline void lsf_state_cell_cleanup(void *object) {
    lsf_state_close_cell(object);
    free(object);
}
static inline lsf_state_cell_t *lsf_state_cell(lsf_scope_t *scope, lsf_state_kind_t kind) {
    lsf_state_cell_t *cell = calloc(1, sizeof(*cell));
    lsf_require(cell != NULL);
    if (!lsf_scope_adopt(scope, cell, sizeof(*cell), lsf_state_cell_cleanup)) {
        free(cell);
        __builtin_trap(); /* Guest allocation failure is not an invented WIT denial. */
    }
    cell->scope = scope;
    cell->kind = kind;
    return cell;
}
static inline void lsf_state_check(lsf_state_cell_t *cell, lsf_state_kind_t kind) {
    lsf_require(cell != NULL && cell->kind == kind && cell->live && !cell->borrowed);
}
static inline bool lsf_state_acquire_command(lsf_scope_t *scope, lsf_state_command_t *out,
                                             latent_state_key_value_state_error_t *error) {
    lsf_require(out != NULL && error != NULL);
    lsf_state_cell_t *cell = lsf_state_cell(scope, LSF_STATE_COMMAND);
    if (!latent_state_key_value_acquire_command(&cell->raw.command, error)) return false;
    cell->live = true;
    *out = (lsf_state_command_t){cell};
    return true;
}
static inline bool lsf_state_acquire_query(lsf_scope_t *scope, lsf_state_query_t *out,
                                           latent_state_key_value_state_error_t *error) {
    lsf_require(out != NULL && error != NULL);
    lsf_state_cell_t *cell = lsf_state_cell(scope, LSF_STATE_QUERY);
    if (!latent_state_key_value_acquire_query(&cell->raw.query, error)) return false;
    cell->live = true;
    *out = (lsf_state_query_t){cell};
    return true;
}
static inline void lsf_state_command_close(lsf_state_command_t *owner) {
    lsf_require(owner != NULL);
    lsf_state_close_cell(owner->cell); /* Access only; there is no guest commit. */
}
static inline void lsf_state_query_close(lsf_state_query_t *owner) {
    lsf_require(owner != NULL);
    lsf_state_close_cell(owner->cell);
}
static inline void lsf_state_page_close(lsf_state_page_t *owner) {
    lsf_require(owner != NULL);
    lsf_state_close_cell(owner->cell);
}

/* A call lease and its generated argument fields belong in a retained frame.
 * Retire exactly once after LSF_ASYNC_RETURNED or a physically retired cancel,
 * including synchronously returned calls. Never retire on PENDING. */
typedef struct {
    lsf_state_cell_t *access;
    union {
        latent_state_key_value_put_args_t put;
        latent_state_key_value_scan_args_t scan;
        latent_state_key_value_scan_query_args_t scan_query;
    } arguments;
} lsf_state_call_t;
static inline void lsf_state_call_begin(lsf_state_call_t *call, lsf_state_cell_t *access) {
    lsf_require(call != NULL && call->access == NULL && access != NULL && access->live && !access->borrowed);
    if (access->parent) {
        lsf_require(access->parent->live && !access->parent->borrowed);
        access->parent->borrowed = true;
    }
    access->borrowed = true;
    call->access = access;
}
static inline void lsf_state_call_retire(lsf_state_call_t *call) {
    lsf_require(call != NULL && call->access != NULL && call->access->borrowed);
    call->access->borrowed = false;
    if (call->access->parent) call->access->parent->borrowed = false;
    call->access = NULL;
}
static inline bool lsf_state_command_info(lsf_state_command_t *owner,
    latent_state_key_value_command_info_t *info, latent_state_key_value_state_error_t *error) {
    lsf_state_check(owner->cell, LSF_STATE_COMMAND);
    lsf_state_call_t call = {0};
    lsf_state_call_begin(&call, owner->cell);
    bool ok = latent_state_key_value_info(latent_state_key_value_borrow_transaction(owner->cell->raw.command), info, error);
    lsf_state_call_retire(&call);
    return ok;
}
static inline bool lsf_state_query_info(lsf_state_query_t *owner,
    latent_state_key_value_view_identity_t *info, latent_state_key_value_state_error_t *error) {
    lsf_state_check(owner->cell, LSF_STATE_QUERY);
    lsf_state_call_t call = {0};
    lsf_state_call_begin(&call, owner->cell);
    bool ok = latent_state_key_value_query_info(latent_state_key_value_borrow_query_view(owner->cell->raw.query), info, error);
    lsf_state_call_retire(&call);
    return ok;
}
static inline probe_subtask_status_t lsf_state_get(lsf_state_call_t *call, lsf_state_command_t *owner,
    probe_list_u8_t key, latent_state_key_value_result_option_versioned_value_state_error_t *result) {
    lsf_state_check(owner->cell, LSF_STATE_COMMAND);
    lsf_state_call_begin(call, owner->cell);
    return latent_state_key_value_get(latent_state_key_value_borrow_transaction(owner->cell->raw.command), key, result);
}
static inline probe_subtask_status_t lsf_state_get_query(lsf_state_call_t *call, lsf_state_query_t *owner,
    probe_list_u8_t key, latent_state_key_value_result_option_versioned_value_state_error_t *result) {
    lsf_state_check(owner->cell, LSF_STATE_QUERY);
    lsf_state_call_begin(call, owner->cell);
    return latent_state_key_value_get_query(latent_state_key_value_borrow_query_view(owner->cell->raw.query), key, result);
}
static inline probe_subtask_status_t lsf_state_put(lsf_state_call_t *call, lsf_state_command_t *owner,
    probe_list_u8_t key, latent_state_key_value_value_t value, latent_state_key_value_result_void_state_error_t *result) {
    lsf_state_check(owner->cell, LSF_STATE_COMMAND);
    lsf_state_call_begin(call, owner->cell);
    call->arguments.put = (latent_state_key_value_put_args_t){
        latent_state_key_value_borrow_transaction(owner->cell->raw.command), key, value};
    return latent_state_key_value_put(&call->arguments.put, result);
}
static inline probe_subtask_status_t lsf_state_delete(lsf_state_call_t *call, lsf_state_command_t *owner,
    probe_list_u8_t key, latent_state_key_value_result_void_state_error_t *result) {
    lsf_state_check(owner->cell, LSF_STATE_COMMAND);
    lsf_state_call_begin(call, owner->cell);
    return latent_state_key_value_delete(latent_state_key_value_borrow_transaction(owner->cell->raw.command), key, result);
}
static inline probe_subtask_status_t lsf_state_scan(lsf_state_call_t *call, lsf_state_command_t *owner,
    probe_list_u8_t prefix, uint32_t limit, probe_option_list_u8_t cursor,
    latent_state_key_value_result_own_page_state_error_t *result) {
    lsf_state_check(owner->cell, LSF_STATE_COMMAND);
    lsf_state_call_begin(call, owner->cell);
    call->arguments.scan = (latent_state_key_value_scan_args_t){
        latent_state_key_value_borrow_transaction(owner->cell->raw.command), prefix, limit, cursor};
    return latent_state_key_value_scan(&call->arguments.scan, result);
}
static inline probe_subtask_status_t lsf_state_scan_query(lsf_state_call_t *call, lsf_state_query_t *owner,
    probe_list_u8_t prefix, uint32_t limit, probe_option_list_u8_t cursor,
    latent_state_key_value_result_own_page_state_error_t *result) {
    lsf_state_check(owner->cell, LSF_STATE_QUERY);
    lsf_state_call_begin(call, owner->cell);
    call->arguments.scan_query = (latent_state_key_value_scan_query_args_t){
        latent_state_key_value_borrow_query_view(owner->cell->raw.query), prefix, limit, cursor};
    return latent_state_key_value_scan_query(&call->arguments.scan_query, result);
}
static inline lsf_state_page_t lsf_state_adopt_page(lsf_state_cell_t *view, latent_state_key_value_own_page_t raw) {
    lsf_require(view != NULL && view->live && !view->borrowed && view->kind != LSF_STATE_PAGE);
    lsf_state_cell_t *page = lsf_state_cell(view->scope, LSF_STATE_PAGE);
    page->parent = view;
    view->pages++;
    page->raw.page = raw;
    page->live = true;
    return (lsf_state_page_t){page};
}
static inline bool lsf_state_page_info(lsf_state_page_t *owner,
    latent_state_key_value_page_info_t *info, latent_state_key_value_state_error_t *error) {
    lsf_state_check(owner->cell, LSF_STATE_PAGE);
    lsf_state_call_t call = {0};
    lsf_state_call_begin(&call, owner->cell);
    bool ok = latent_state_key_value_describe_page(latent_state_key_value_borrow_page(owner->cell->raw.page), info, error);
    lsf_state_call_retire(&call);
    return ok;
}
static inline probe_subtask_status_t lsf_state_page_next(lsf_state_call_t *call, lsf_state_page_t *owner,
    latent_state_key_value_result_option_entry_state_error_t *result) {
    lsf_state_check(owner->cell, LSF_STATE_PAGE);
    lsf_state_call_begin(call, owner->cell);
    return latent_state_key_value_page_next(latent_state_key_value_borrow_page(owner->cell->raw.page), result);
}

/* Release every nested allocation explicitly; reused aliases are not an
 * assumption about the pinned generator's aggregate-free implementation. */
static inline void lsf_state_value_close(latent_state_key_value_value_t *value) {
    if (value->bytes.len) free(value->bytes.ptr);
    probe_string_free(&value->media_type);
    for (size_t index = 0; index < value->metadata.len; index++) {
        probe_string_free(&value->metadata.ptr[index].f0);
        probe_string_free(&value->metadata.ptr[index].f1);
    }
    if (value->metadata.len) free(value->metadata.ptr);
    *value = (latent_state_key_value_value_t){0};
}
static inline void lsf_state_versioned_value_close(latent_state_key_value_versioned_value_t *value) {
    lsf_state_value_close(&value->value);
    if (value->version.len) free(value->version.ptr);
    *value = (latent_state_key_value_versioned_value_t){0};
}
static inline void lsf_state_get_result_close(latent_state_key_value_result_option_versioned_value_state_error_t *result) {
    if (!result->is_err && result->val.ok.is_some) lsf_state_versioned_value_close(&result->val.ok.val);
    *result = (latent_state_key_value_result_option_versioned_value_state_error_t){0};
}
static inline void lsf_state_entry_result_close(latent_state_key_value_result_option_entry_state_error_t *result) {
    if (!result->is_err && result->val.ok.is_some) {
        latent_state_key_value_entry_t *entry = &result->val.ok.val;
        if (entry->key.len) free(entry->key.ptr);
        lsf_state_versioned_value_close(&entry->value);
    }
    *result = (latent_state_key_value_result_option_entry_state_error_t){0};
}
#endif
