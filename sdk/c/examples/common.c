#include "common.h"

#include <stdio.h>
#include <string.h>
#include <time.h>

uint64_t ex_now(void) {
    struct timespec instant;
    if (clock_gettime(CLOCK_MONOTONIC, &instant) != 0) return UINT64_MAX;
    return (uint64_t)instant.tv_sec * 1000 + (uint64_t)instant.tv_nsec / 1000000;
}

void ex_pause(void) {
    struct timespec duration = {0, 1000000};
    (void)nanosleep(&duration, NULL);
}

latent_string ex_string(const char *value) { return (latent_string){value, strlen(value)}; }
latent_profile_call_options ex_options(uint32_t timeout) { return (latent_profile_call_options){true, timeout}; }

static void copy(ex_result *result, char *output, size_t maximum, latent_string input) {
    if (input.length >= maximum || (input.length != 0 && input.data == NULL)) { result->valid = false; return; }
    if (input.length != 0) memcpy(output, input.data, input.length);
    output[input.length] = 0;
}

static bool begin(ex_result *result, const latent_profile_client_failure *failure) {
    result->valid = ++result->callbacks == 1;
    if (failure == NULL) return true;
    result->failed = true;
    result->category = failure->category;
    result->has_grpc = failure->has_grpc_status;
    result->grpc = failure->grpc_status;
    result->dispatched = failure->dispatched;
    result->outcome = failure->outcome;
    result->audit_absent = !failure->has_audit_ack && !failure->has_audit_status && !failure->has_audit_attempt_sequence;
    copy(result, result->identity, sizeof(result->identity), failure->identity.has_activation_id
         ? failure->identity.activation_id : failure->identity.operation_id);
    return false;
}

static void metadata(ex_result *result, const latent_profile_response_metadata *value) {
    result->outcome = value->outcome;
    result->audit_absent = !value->has_audit_ack && !value->has_audit_status && !value->has_audit_attempt_sequence;
    copy(result, result->identity, sizeof(result->identity), value->identity.has_activation_id
         ? value->identity.activation_id : value->identity.operation_id);
}

static void receipt(ex_result *result, const latent_profile_capability_policy_operation *value) {
    copy(result, result->receipt.operation_id, sizeof(result->receipt.operation_id), value->operation_id);
    copy(result, result->receipt.tenant, sizeof(result->receipt.tenant), value->tenant);
    copy(result, result->receipt.id, sizeof(result->receipt.id), value->id);
    copy(result, result->receipt.digest, sizeof(result->receipt.digest), value->content_digest);
    result->receipt.record_kind = value->record_kind;
    result->receipt.generation = value->generation;
    result->receipt.revoked = value->revoked;
}

static void page(ex_result *result, bool present, const latent_profile_page_response *value) {
    result->has_page = present;
    result->has_cursor = present && value->has_next_page_token;
    if (result->has_cursor) {
        copy(result, result->cursor, sizeof(result->cursor), value->next_page_token);
        result->cursor_length = value->next_page_token.length;
    }
}

void ex_invoked(const latent_profile_invoke_result *response, const latent_profile_client_failure *failure, void *data) {
    ex_result *result = data;
    if (!begin(result, failure)) return;
    metadata(result, &response->metadata);
    result->success = response->value.has_success;
    result->declared = response->value.has_declared_error;
    result->platform = response->value.has_platform_failure;
    if (result->platform) copy(result, result->platform_code, sizeof(result->platform_code), response->value.platform_failure.code);
    if (result->success) {
        latent_bytes bytes = response->value.success.payload;
        if (bytes.length > sizeof(result->payload)) { result->valid = false; return; }
        if (bytes.length != 0) memcpy(result->payload, bytes.data, bytes.length);
        result->payload_length = bytes.length;
        copy(result, result->media_type, sizeof(result->media_type), response->value.success.media_type);
    }
}

void ex_cancelled(const latent_profile_cancel_result *response, const latent_profile_client_failure *failure, void *data) {
    ex_result *result = data;
    if (!begin(result, failure)) return;
    metadata(result, &response->metadata);
    result->disposition = response->value.disposition;
}

void ex_status(const latent_profile_get_activation_result *response, const latent_profile_client_failure *failure, void *data) {
    ex_result *result = data;
    if (!begin(result, failure)) return;
    metadata(result, &response->metadata);
    result->terminal = response->value.has_terminal_state;
}

void ex_policy(const latent_profile_get_policy_result *response, const latent_profile_client_failure *failure, void *data) {
    ex_result *result = data;
    if (!begin(result, failure)) return;
    metadata(result, &response->metadata);
    result->has_policy = response->value.has_policy;
    result->generation = response->value.policy.generation;
}

void ex_policies(const latent_profile_list_policies_result *response, const latent_profile_client_failure *failure, void *data) {
    ex_result *result = data;
    if (!begin(result, failure)) return;
    metadata(result, &response->metadata);
    result->count = response->value.policies_count;
    result->generation = response->value.catalog_generation;
    page(result, response->value.has_page, &response->value.page);
    if (result->count != 0) copy(result, result->first_id, sizeof(result->first_id), response->value.policies[0].id);
}

void ex_capabilities(const latent_profile_list_capabilities_result *response, const latent_profile_client_failure *failure, void *data) {
    ex_result *result = data;
    if (!begin(result, failure)) return;
    metadata(result, &response->metadata);
    result->count = response->value.capabilities_count;
    page(result, response->value.has_page, &response->value.page);
    if (result->count != 0) {
        const latent_profile_capability_descriptor *value = &response->value.capabilities[0];
        copy(result, result->contract, sizeof(result->contract), value->contract);
        if (value->has_inspection && value->inspection.has_provider_binding)
            copy(result, result->provider_binding, sizeof(result->provider_binding), value->inspection.provider_binding.id);
        if (value->has_inspection && value->inspection.policies_count != 0)
            copy(result, result->provider_policy, sizeof(result->provider_policy), value->inspection.policies[0].id);
    }
}

void ex_applied(const latent_profile_apply_policy_result *response, const latent_profile_client_failure *failure, void *data) {
    ex_result *result = data;
    if (!begin(result, failure)) return;
    metadata(result, &response->metadata);
    result->has_policy = response->value.has_policy;
    result->has_receipt = response->value.has_receipt;
    result->generation = response->value.policy.generation;
    if (result->has_receipt) receipt(result, &response->value.receipt);
}

void ex_operation(const latent_profile_get_policy_operation_result *response, const latent_profile_client_failure *failure, void *data) {
    ex_result *result = data;
    if (!begin(result, failure)) return;
    metadata(result, &response->metadata);
    result->has_receipt = response->value.has_receipt;
    if (result->has_receipt) receipt(result, &response->value.receipt);
}

latent_transport *ex_client(const ex_config *config, bool foreign, bool denied, bool small) {
    latent_transport_config options = latent_transport_defaults();
    options.endpoint = config->endpoint;
    options.tenant = foreign ? EX_TEXT("foreign") : config->tenant;
    options.bearer_token = denied ? (latent_bytes){(const uint8_t *)"LSF-PUBLIC-WRONG-C-TOKEN-TEST-ONLY", sizeof("LSF-PUBLIC-WRONG-C-TOKEN-TEST-ONLY") - 1}
                                  : (latent_bytes){config->credential, config->credential_length};
    options.maximum_response_bytes = small ? 64 : 65536;
    options.timeout_millis = 5000;
    latent_transport *client = NULL;
    latent_profile_client_failure failure;
    if (!latent_transport_create(&options, &client, &failure)) return NULL;
    return client;
}

bool ex_wait(latent_transport *client, ex_result *result, uint64_t deadline) {
    while (result->callbacks == 0 && ex_now() < deadline) {
        if (!latent_transport_poll(client, 2)) break;
    }
    if (result->callbacks == 0) latent_transport_stop(client);
    return result->callbacks == 1 && result->valid;
}

bool ex_close(latent_transport **client) {
    if (*client == NULL) return true;
    if (!latent_transport_shutdown(*client, 1000)) return false;
    latent_transport_usage usage = latent_transport_get_usage(*client);
    if (usage.sockets != 0 || usage.sessions != 0 || usage.http2_bytes != 0 || usage.retained_calls != 0
        || usage.in_flight != 0 || usage.queued != 0 || usage.callbacks_pending != 0) return false;
    if (!latent_transport_destroy(*client)) return false;
    *client = NULL;
    return true;
}

bool ex_guest(const ex_result *result, uint64_t expected) {
    if (!result->valid || result->failed || !result->success
        || strcmp(result->media_type, "application/vnd.latent.wit-values.v1+json") != 0) return false;
    char compact[64];
    size_t length = 0;
    bool quoted = false;
    for (size_t index = 0; index < result->payload_length; ++index) {
        uint8_t value = result->payload[index];
        if (!quoted && (value == ' ' || value == '\n' || value == '\r' || value == '\t')) continue;
        if (length >= sizeof(compact)) return false;
        compact[length++] = (char)value;
        if (value == '"') quoted = !quoted;
    }
    if (length < 5 || compact[0] != '[' || compact[1] != '"' || compact[length - 2] != '"' || compact[length - 1] != ']') return false;
    uint64_t value = 0;
    return latent_profile_parse_u64((latent_string){compact + 2, length - 4}, &value) && value == expected;
}

bool ex_receipt_equal(const ex_receipt *left, const ex_receipt *right) {
    return strcmp(left->operation_id, right->operation_id) == 0 && strcmp(left->tenant, right->tenant) == 0
        && strcmp(left->id, right->id) == 0 && left->record_kind == right->record_kind && left->generation == right->generation
        && strcmp(left->digest, right->digest) == 0 && left->revoked == right->revoked;
}

latent_profile_call *ex_invoke(const ex_config *config, latent_transport *client, unsigned provider,
                               const char *suffix, const char *function, bool foreign, uint32_t timeout,
                               ex_result *result) {
    if (provider >= 3) return NULL;
    char identity[65], payload[4096];
    int identity_length = snprintf(identity, sizeof(identity), "c-%s", suffix);
    int length;
    if (provider == 2) length = snprintf(payload, sizeof(payload), "[]");
    else if (provider == 1) length = snprintf(payload, sizeof(payload), "[0,\"\",\"0\"]");
    else {
        for (size_t index = 0; index < config->upstream_url.length; ++index) {
            unsigned char value = (unsigned char)config->upstream_url.data[index];
            if (value < 0x21 || value > 0x7e || value == '"' || value == '\\') return NULL;
        }
        length = snprintf(payload, sizeof(payload), "[0,\"%.*s\",\"0\"]", (int)config->upstream_url.length, config->upstream_url.data);
    }
    if (identity_length <= 0 || (size_t)identity_length >= sizeof(identity) || length <= 0 || (size_t)length >= sizeof(payload)) return NULL;
    const ex_target *target = &config->targets[provider];
    latent_profile_invoke_request request = {.has_activation_id = true, .activation_id = {identity, (size_t)identity_length},
        .has_target = true, .target = {.tenant = foreign ? EX_TEXT("foreign") : config->tenant, .service = target->service,
            .contract = target->contract, .function = function == NULL ? target->function : ex_string(function), .has_route = true, .route = target->route},
        .payload = {(const uint8_t *)payload, (size_t)length}, .media_type = EX_TEXT("application/vnd.latent.wit-values.v1+json"),
        .has_budget = true, .budget = {.cpu_fuel = provider == 2 ? 100000000 : UINT64_C(10000000000),
            .memory_bytes = provider == 2 ? 4194304 : 16777216, .has_wall_time_limit_millis = true, .wall_time_limit_millis = 5000,
            .outbound_requests = provider == 2 ? 0 : 8, .blob_read_bytes = provider == 1 ? 65536 : 0, .blob_write_bytes = provider == 1 ? 65536 : 0}};
    if (function != NULL && strcmp(function, "spin") == 0) request.budget.cpu_fuel = 1000;
    latent_profile_call_options options = ex_options(timeout);
    return latent_transport_profile_vtable()->invoke(latent_transport_profile(client), &request, &options, ex_invoked, result);
}
