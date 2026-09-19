#include "internal.h"

static latent_profile_resource_budget budget(const latent_resource_budget *value) {
    return (latent_profile_resource_budget){
        .cpu_fuel = value->cpu_fuel, .memory_bytes = value->memory_bytes,
        .child_calls = value->child_calls, .outbound_requests = value->outbound_requests,
        .state_read_bytes = value->state_read_bytes, .state_write_bytes = value->state_write_bytes,
        .blob_read_bytes = value->blob_read_bytes, .blob_write_bytes = value->blob_write_bytes,
        .log_bytes = value->log_bytes, .effect_count = value->effect_count,
        .has_wall_time_limit_millis = value->has_wall_time_limit,
        .wall_time_limit_millis = value->wall_time_limit_millis
    };
}

static latent_budget_consumption consumption(const latent_profile_budget_consumption *value) {
    return (latent_budget_consumption){
        .cpu_fuel = value->cpu_fuel, .peak_memory_bytes = value->peak_memory_bytes,
        .wall_time_micros = value->wall_time_micros, .child_calls = value->child_calls,
        .outbound_requests = value->outbound_requests, .state_read_bytes = value->state_read_bytes,
        .state_write_bytes = value->state_write_bytes, .blob_read_bytes = value->blob_read_bytes,
        .blob_write_bytes = value->blob_write_bytes, .log_bytes = value->log_bytes, .effect_count = value->effect_count
    };
}

static latent_declared_error declared(const latent_profile_declared_error *value) {
    return (latent_declared_error){value->code, value->message, value->payload, value->media_type,
                                   value->metadata, value->metadata_count};
}

static bool platform(latent_profile_call *call, const latent_profile_platform_error *value, latent_platform_error *output) {
    latent_error_detail *details = NULL;
    if (value->detail_items_count != 0) {
        details = lsf_arena_allocate(&call->arena, value->detail_items_count * sizeof(*details));
        if (details == NULL) return false;
        for (size_t index = 0; index < value->detail_items_count; ++index) {
            details[index] = (latent_error_detail){value->detail_items[index].kind,
                value->detail_items[index].fields, value->detail_items[index].fields_count};
        }
    }
    *output = (latent_platform_error){value->code, value->message, value->retryable, details, value->detail_items_count};
    return true;
}

static latent_invocation_receipt receipt(const latent_profile_invoke_response *value) {
    return (latent_invocation_receipt){.activation_id = value->activation_id, .revision_id = value->revision_id,
        .release_digest = value->release_digest, .route_generation = value->route_generation,
        .consumption = consumption(&value->consumption), .has_publication_id = value->has_publication_id,
        .publication_id = value->publication_id};
}

static void complete_invoke(latent_profile_call *call, const latent_transport_error *error) {
    latent_invocation *handle = call->legacy_handle.call == NULL ? NULL : &call->legacy_handle;
    if (error != NULL) { call->legacy_callback.invoke(handle, NULL, error, call->user_data); return; }
    const latent_profile_invoke_response *value = &call->result.invoke.value;
    latent_invoke_response success = {.activation_id = value->activation_id, .revision_id = value->revision_id,
        .release_digest = value->release_digest, .route_generation = value->route_generation,
        .payload = value->success.payload, .media_type = value->success.media_type,
        .has_committed_state_version = value->success.has_committed_state_version,
        .committed_state_version = value->success.committed_state_version,
        .effect_ids = value->success.effect_ids, .effect_id_count = value->success.effect_ids_count,
        .consumption = consumption(&value->consumption), .metadata = value->success.metadata,
        .metadata_count = value->success.metadata_count, .has_publication_id = value->has_publication_id,
        .publication_id = value->publication_id};
    latent_declared_invocation_error application = {receipt(value), declared(&value->declared_error)};
    latent_platform_invocation_failure failure = {.receipt = receipt(value)};
    latent_invocation_outcome outcome = {0};
    if (value->has_success) { outcome.kind = LATENT_INVOCATION_SUCCEEDED; outcome.success = &success; }
    else if (value->has_declared_error) { outcome.kind = LATENT_INVOCATION_DECLARED_ERROR; outcome.declared_error = &application; }
    else {
        if (!platform(call, &value->platform_failure, &failure.error)) {
            latent_transport_error allocation = {LSF_TEXT("bounded C response allocation failed"), false};
            call->legacy_callback.invoke(handle, NULL, &allocation, call->user_data);
            return;
        }
        outcome.kind = LATENT_INVOCATION_PLATFORM_FAILURE;
        outcome.platform_failure = &failure;
    }
    call->legacy_callback.invoke(handle, &outcome, NULL, call->user_data);
}

static void complete_status(latent_profile_call *call, const latent_transport_error *error) {
    latent_client *client = &call->owner->legacy;
    if (error != NULL) { call->legacy_callback.get_activation(client, NULL, error, call->user_data); return; }
    const latent_profile_activation_status *value = &call->result.get_activation.value;
    latent_activation_success_summary success = {value->succeeded.has_committed_state_version,
        value->succeeded.committed_state_version, value->succeeded.effect_ids, value->succeeded.effect_ids_count,
        value->succeeded.metadata, value->succeeded.metadata_count};
    latent_declared_error application = declared(&value->declared_error);
    latent_platform_error failure = {0};
    latent_activation_status status = {.activation_id = value->activation_id, .phase = value->phase,
        .has_terminal_state = value->has_terminal_state, .terminal_state = value->terminal_state,
        .has_terminal_outcome = value->has_succeeded || value->has_declared_error || value->has_platform_failure,
        .has_final_consumption = value->has_final_consumption, .final_consumption = consumption(&value->final_consumption),
        .last_updated_unix_millis = value->last_updated_unix_millis,
        .has_terminal_at_unix_millis = value->has_terminal_at_unix_millis, .terminal_at_unix_millis = value->terminal_at_unix_millis,
        .metadata = value->metadata, .metadata_count = value->metadata_count};
    if (value->has_succeeded) {
        status.terminal_outcome.kind = LATENT_RETAINED_INVOCATION_SUCCEEDED;
        status.terminal_outcome.success = &success;
    } else if (value->has_declared_error) {
        status.terminal_outcome.kind = LATENT_RETAINED_INVOCATION_DECLARED_ERROR;
        status.terminal_outcome.declared_error = &application;
    } else if (value->has_platform_failure) {
        if (!platform(call, &value->platform_failure, &failure)) {
            latent_transport_error allocation = {LSF_TEXT("bounded C response allocation failed"), false};
            call->legacy_callback.get_activation(client, NULL, &allocation, call->user_data);
            return;
        }
        status.terminal_outcome.kind = LATENT_RETAINED_INVOCATION_PLATFORM_FAILURE;
        status.terminal_outcome.platform_failure = &failure;
    }
    call->legacy_callback.get_activation(client, &status, NULL, call->user_data);
}

void lsf_legacy_complete(latent_profile_call *call) {
    latent_transport_error failure = {call->failure.message, false};
    const latent_transport_error *error = call->failure.category == 0 ? NULL : &failure;
    if (call->operation == LSF_INVOKE) complete_invoke(call, error);
    else if (call->operation == LSF_GET_ACTIVATION) complete_status(call, error);
    else {
        latent_cancel_response response = {(latent_cancel_disposition)call->result.cancel.value.disposition,
            call->result.cancel.value.has_terminal_state, call->result.cancel.value.terminal_state};
        call->legacy_callback.cancel(&call->owner->legacy, error == NULL ? &response : NULL, error, call->user_data);
    }
}

static latent_invocation *invoke(latent_client *client, const latent_invoke_request *value,
                                  latent_invoke_callback callback, void *user_data) {
    if (client == NULL || callback == NULL) return NULL;
    latent_profile_invoke_request request = {0};
    if (value != NULL) {
        request = (latent_profile_invoke_request){.has_activation_id = value->has_activation_id,
            .activation_id = value->activation_id, .has_root_activation_id = value->has_root_activation_id,
            .root_activation_id = value->root_activation_id, .has_parent_activation_id = value->has_parent_activation_id,
            .parent_activation_id = value->parent_activation_id, .has_target = true,
            .target = {value->target.tenant, value->target.service, value->target.contract, value->target.function,
                       value->target.has_route, value->target.route},
            .payload = value->payload, .media_type = value->media_type, .has_deadline_unix_millis = value->has_deadline,
            .deadline_unix_millis = value->deadline_unix_millis, .priority = value->priority,
            .has_idempotency_key = value->has_idempotency_key, .idempotency_key = value->idempotency_key,
            .has_budget = true, .budget = budget(&value->budget), .metadata = value->metadata, .metadata_count = value->metadata_count};
    }
    lsf_legacy_callback legacy = {.invoke = callback};
    latent_profile_call *call = lsf_start(client->owner, LSF_INVOKE, value == NULL ? NULL : &request, NULL,
                                         (lsf_callback){0}, user_data, &legacy);
    return call == NULL ? NULL : &call->legacy_handle;
}

static void cancel(latent_client *client, latent_string activation_id, latent_string reason,
                    latent_cancel_callback callback, void *user_data) {
    if (client == NULL || callback == NULL) return;
    latent_profile_cancel_request request = {activation_id, reason};
    lsf_legacy_callback legacy = {.cancel = callback};
    (void)lsf_start(client->owner, LSF_CANCEL, &request, NULL, (lsf_callback){0}, user_data, &legacy);
}

static void get_activation(latent_client *client, latent_string activation_id,
                            latent_get_activation_callback callback, void *user_data) {
    if (client == NULL || callback == NULL) return;
    latent_profile_get_activation_request request = {activation_id};
    lsf_legacy_callback legacy = {.get_activation = callback};
    (void)lsf_start(client->owner, LSF_GET_ACTIVATION, &request, NULL, (lsf_callback){0}, user_data, &legacy);
}

static void destroy(latent_client *client) {
    if (client != NULL) (void)latent_transport_destroy(client->owner);
}

const latent_client_vtable *latent_transport_legacy_vtable(void) {
    static const latent_client_vtable vtable = {invoke, cancel, get_activation, destroy};
    return &vtable;
}
