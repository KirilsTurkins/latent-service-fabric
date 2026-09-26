/* SPDX-License-Identifier: Apache-2.0 */
/* Same conformance WIT as the maintained Rust capabilities fixture. */
#include "probe.h"
#include "lsf/ownership.h"

void exports_tests_capabilities_api_snapshot(exports_tests_capabilities_api_context_snapshot_t *ret) {
    *ret = (exports_tests_capabilities_api_context_snapshot_t){0};
    latent_context_context_activation_id(&ret->activation);
    latent_context_context_root_activation_id(&ret->root);
    ret->parent.is_some = latent_context_context_parent_activation_id(&ret->parent.val);
    latent_context_context_principal(&ret->principal);
    latent_context_context_trace(&ret->trace);
    ret->deadline.is_some = latent_context_context_deadline_unix_millis(&ret->deadline.val);
    latent_context_context_metadata(&ret->metadata);
    latent_context_context_remaining_budget(&ret->remaining);
    /* All imported allocations transfer to generated export post-return. */
}

static void observe_log(probe_string_t *message, exports_tests_capabilities_api_list_field_t *fields,
                        exports_tests_capabilities_api_log_observation_t *ret) {
    latent_context_context_resource_budget_t before, after;
    latent_context_context_remaining_budget(&before);
    *ret = (exports_tests_capabilities_api_log_observation_t){.before = before.log_bytes};
    bool accepted = false;
    latent_log_log_log_error_t error = {0};
    latent_log_log_list_field_t borrowed = {.ptr = fields->ptr, .len = fields->len};
    if (latent_log_log_write(LATENT_LOG_LOG_LEVEL_INFO, message, &borrowed, &accepted, &error)) {
        ret->outcome.val.ok = accepted;
    } else {
        ret->outcome.is_err = true;
        ret->outcome.val.err = error;
    }
    latent_context_context_remaining_budget(&after);
    ret->after = after.log_bytes;
}

void exports_tests_capabilities_api_log_probe(probe_string_t *message,
    exports_tests_capabilities_api_list_field_t *fields, exports_tests_capabilities_api_log_observation_t *ret) {
    observe_log(message, fields, ret);
    probe_string_free(message);
    exports_tests_capabilities_api_list_field_free(fields);
}

void exports_tests_capabilities_api_log_twice(probe_string_t *message,
    exports_tests_capabilities_api_list_field_t *fields, exports_tests_capabilities_api_list_log_observation_t *ret) {
    lsf_scope_t scope;
    lsf_scope_init(&scope, 2 * sizeof(*ret->ptr));
    ret->ptr = lsf_scope_alloc(&scope, 2, sizeof(*ret->ptr));
    lsf_require(ret->ptr != NULL);
    ret->len = 2;
    for (size_t index = 0; index < ret->len; ++index) observe_log(message, fields, &ret->ptr[index]);
    probe_string_free(message);
    exports_tests_capabilities_api_list_field_free(fields);
    lsf_require(lsf_scope_detach(&scope, ret->ptr));
    lsf_scope_close(&scope);
}

void exports_tests_capabilities_api_clocks(exports_tests_capabilities_api_list_clock_reading_t *ret) {
    lsf_scope_t scope;
    lsf_scope_init(&scope, 3 * sizeof(*ret->ptr));
    ret->ptr = lsf_scope_alloc(&scope, 3, sizeof(*ret->ptr));
    lsf_require(ret->ptr != NULL);
    ret->len = 3;
    for (size_t index = 0; index < ret->len; ++index) {
        ret->ptr[index].monotonic = latent_clock_monotonic_now_nanos();
        ret->ptr[index].wall = latent_clock_wall_now_unix_millis();
    }
    lsf_require(lsf_scope_detach(&scope, ret->ptr));
    lsf_scope_close(&scope);
}

void exports_tests_capabilities_api_work_observe(exports_tests_capabilities_api_work_observation_t *ret) {
    *ret = (exports_tests_capabilities_api_work_observation_t){0};
    latent_context_context_remaining_budget(&ret->before);
    lsf_scope_t scope;
    lsf_scope_init(&scope, 2 * 1024 * 1024);
    volatile uint8_t *bytes = lsf_scope_alloc(&scope, 2 * 1024 * 1024, 1);
    lsf_require(bytes != NULL);
    for (size_t index = 0; index < 1024; ++index) {
        bytes[index * 1024] = 1;
        ret->checksum += bytes[index * 1024];
    }
    probe_string_t message;
    probe_string_set(&message, "bounded-work");
    exports_tests_capabilities_api_list_field_t fields = {0};
    exports_tests_capabilities_api_log_observation_t logged;
    observe_log(&message, &fields, &logged);
    ret->logged = logged.outcome;
    latent_context_context_remaining_budget(&ret->after);
    lsf_scope_close(&scope);
}
