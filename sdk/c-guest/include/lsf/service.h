/* SPDX-License-Identifier: Apache-2.0 */
#ifndef LSF_GUEST_SERVICE_H
#define LSF_GUEST_SERVICE_H
#include "guest.h"

static inline void lsf_service_metadata_close(probe_list_tuple2_string_string_t *pairs) {
    for (size_t i = 0; i < pairs->len; ++i) {
        probe_string_free(&pairs->ptr[i].f0);
        probe_string_free(&pairs->ptr[i].f1);
    }
    if (pairs->len) free(pairs->ptr);
    *pairs = (probe_list_tuple2_string_string_t){0};
}

static inline void lsf_service_outcome_close(void *object) {
    latent_service_invoke_invocation_outcome_t *outcome = object;
    if (!outcome) return;
    switch (outcome->tag) {
    case LATENT_SERVICE_INVOKE_INVOCATION_OUTCOME_SUCCESS: {
        latent_service_invoke_invocation_result_t *value = &outcome->val.success;
        if (value->payload.len) free(value->payload.ptr);
        probe_string_free(&value->media_type);
        lsf_service_metadata_close(&value->metadata);
        break;
    }
    case LATENT_SERVICE_INVOKE_INVOCATION_OUTCOME_DECLARED_ERROR: {
        latent_service_invoke_declared_error_t *value = &outcome->val.declared_error;
        probe_string_free(&value->code);
        probe_string_free(&value->message);
        if (value->payload.len) free(value->payload.ptr);
        probe_string_free(&value->media_type);
        lsf_service_metadata_close(&value->metadata);
        break;
    }
    case LATENT_SERVICE_INVOKE_INVOCATION_OUTCOME_PLATFORM_FAILURE: {
        latent_service_invoke_platform_error_t *value = &outcome->val.platform_failure;
        probe_string_free(&value->message);
        for (size_t i = 0; i < value->details.len; ++i) {
            probe_string_free(&value->details.ptr[i].kind);
            lsf_service_metadata_close(&value->details.ptr[i].fields);
        }
        if (value->details.len) free(value->details.ptr);
        break;
    }
    default: __builtin_trap();
    }
    *outcome = (latent_service_invoke_invocation_outcome_t){0};
}
#endif
