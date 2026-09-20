#include <latent/transport.h>

#include <assert.h>
#include <arpa/inet.h>
#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define TEXT(value) ((latent_string){value, sizeof(value) - 1u})

typedef struct observed {
    unsigned calls;
    bool failed;
    int32_t category;
    bool grpc_present;
    int32_t grpc;
    bool dispatched;
    int32_t outcome;
    char identity[257];
    bool audit;
    int32_t audit_status;
    bool raw_audit;
    char audit_text[65];
    bool attempt_present;
    uint64_t attempt;
    bool unsupported;
    char unsupported_text[257];
    bool platform_detail;
    unsigned variant;
    uint8_t payload[256];
    size_t payload_length;
    int32_t disposition;
    bool terminal;
    uint64_t generation;
    bool receipt;
    bool policy;
    size_t count;
    bool page;
    char cursor[161];
    bool counters;
    latent_transport *stop_owner;
    uint32_t pause_millis;
} observed;

static const latent_profile_client_vtable *api;
static const char *address;

static uint64_t now(void) {
    struct timespec value;
    assert(clock_gettime(CLOCK_MONOTONIC, &value) == 0);
    return (uint64_t)value.tv_sec * 1000 + (uint64_t)value.tv_nsec / 1000000;
}

static void copy(char *output, size_t capacity, latent_string input) {
    assert(input.length < capacity);
    if (input.length != 0) memcpy(output, input.data, input.length);
    output[input.length] = 0;
}

static void metadata(observed *record, const latent_profile_response_metadata *value) {
    record->outcome = value->outcome;
    latent_string identity = value->identity.has_activation_id ? value->identity.activation_id : value->identity.operation_id;
    copy(record->identity, sizeof(record->identity), identity);
    record->audit = value->has_audit_ack;
    record->audit_status = value->audit_ack.status;
    record->raw_audit = value->has_audit_status;
    if (value->has_audit_status) copy(record->audit_text, sizeof(record->audit_text), value->audit_status);
    record->attempt_present = value->has_audit_attempt_sequence;
    record->attempt = value->audit_attempt_sequence;
}

static bool failure(observed *record, const latent_profile_client_failure *error) {
    ++record->calls;
    assert(record->calls == 1);
    if (error == NULL) return false;
    record->failed = true;
    record->category = error->category;
    record->grpc_present = error->has_grpc_status;
    record->grpc = error->grpc_status;
    record->dispatched = error->dispatched;
    record->outcome = error->outcome;
    copy(record->identity, sizeof(record->identity), error->identity.has_activation_id ? error->identity.activation_id : error->identity.operation_id);
    record->unsupported = error->has_unsupported_wire_value;
    if (record->unsupported) copy(record->unsupported_text, sizeof(record->unsupported_text), error->unsupported_wire_value.value);
    record->platform_detail = error->has_platform_error;
    if (error->has_platform_error) {
        assert(error->platform_error.detail_items_count == 1);
        assert(error->platform_error.detail_items[0].fields_count == 1);
    }
    if (record->stop_owner != NULL) {
        assert(!latent_transport_poll(record->stop_owner, 0));
        assert(!latent_transport_destroy(record->stop_owner));
        latent_transport_stop(record->stop_owner);
    }
    return true;
}

static void invoked(const latent_profile_invoke_result *result, const latent_profile_client_failure *error, void *data) {
    observed *record = data;
    assert((result == NULL) != (error == NULL));
    if (failure(record, error)) return;
    metadata(record, &result->metadata);
    const latent_profile_invoke_response *value = &result->value;
    assert(value->has_consumption && value->consumption.cpu_fuel == UINT64_MAX);
    record->generation = value->route_generation;
    record->variant = value->has_success ? 1u : value->has_declared_error ? 2u : 3u;
    if (value->has_success) {
        assert(value->success.has_committed_state_version && value->success.committed_state_version.length == 0);
        assert(value->success.metadata_count == 1 && value->success.metadata[0].key.length == 7);
        assert(value->success.metadata[0].key.data[3] == 0);
        assert(value->success.payload.length <= sizeof(record->payload));
        record->payload_length = value->success.payload.length;
        memcpy(record->payload, value->success.payload.data, value->success.payload.length);
    }
    if (record->stop_owner != NULL) latent_transport_stop(record->stop_owner);
    if (record->pause_millis != 0) {
        struct timespec delay = {0, (long)record->pause_millis * 1000000};
        while (nanosleep(&delay, &delay) != 0) assert(errno == EINTR);
    }
}

static void cancelled(const latent_profile_cancel_result *result, const latent_profile_client_failure *error, void *data) {
    observed *record = data;
    assert((result == NULL) != (error == NULL));
    if (failure(record, error)) return;
    metadata(record, &result->metadata);
    record->disposition = result->value.disposition;
    record->terminal = result->value.has_terminal_state;
}

static void status(const latent_profile_get_activation_result *result, const latent_profile_client_failure *error, void *data) {
    observed *record = data;
    assert((result == NULL) != (error == NULL));
    if (failure(record, error)) return;
    metadata(record, &result->metadata);
    record->terminal = result->value.has_terminal_state;
    if (record->terminal) assert(result->value.terminal_at_unix_millis == UINT64_MAX);
}

static void policy(const latent_profile_get_policy_result *result, const latent_profile_client_failure *error, void *data) {
    observed *record = data;
    assert((result == NULL) != (error == NULL));
    if (failure(record, error)) return;
    metadata(record, &result->metadata);
    record->policy = result->value.has_policy;
    record->generation = result->value.policy.generation;
}

static void policies(const latent_profile_list_policies_result *result, const latent_profile_client_failure *error, void *data) {
    observed *record = data;
    assert((result == NULL) != (error == NULL));
    if (failure(record, error)) return;
    metadata(record, &result->metadata);
    record->count = result->value.policies_count;
    record->generation = result->value.catalog_generation;
    record->page = result->value.has_page;
    if (result->value.page.has_next_page_token) copy(record->cursor, sizeof(record->cursor), result->value.page.next_page_token);
}

static void capabilities(const latent_profile_list_capabilities_result *result, const latent_profile_client_failure *error, void *data) {
    observed *record = data;
    assert((result == NULL) != (error == NULL));
    if (failure(record, error)) return;
    metadata(record, &result->metadata);
    record->count = result->value.capabilities_count;
    record->page = result->value.has_page;
    assert(result->value.has_tenant_usage && result->value.tenant_usage.counters_count == 2);
    bool zero = false, maximum = false;
    for (size_t index = 0; index < result->value.tenant_usage.counters_count; ++index) {
        const latent_profile_counter *counter = &result->value.tenant_usage.counters[index];
        if (counter->key.length == 4 && memcmp(counter->key.data, "zero", 4) == 0) { assert(counter->value == 0); zero = true; }
        if (counter->key.length == 7 && memcmp(counter->key.data, "maximum", 7) == 0) { assert(counter->value == UINT64_MAX); maximum = true; }
    }
    assert(zero && maximum);
    record->counters = true;
    assert(result->value.capabilities[0].inspection.provider_binding.revision == UINT64_MAX);
}

static void applied(const latent_profile_apply_policy_result *result, const latent_profile_client_failure *error, void *data) {
    observed *record = data;
    assert((result == NULL) != (error == NULL));
    if (failure(record, error)) return;
    metadata(record, &result->metadata);
    record->receipt = result->value.has_receipt;
    record->policy = result->value.has_policy;
    record->generation = result->value.receipt.generation;
}

static void operation(const latent_profile_get_policy_operation_result *result, const latent_profile_client_failure *error, void *data) {
    observed *record = data;
    assert((result == NULL) != (error == NULL));
    if (failure(record, error)) return;
    metadata(record, &result->metadata);
    record->receipt = result->value.has_receipt;
    record->generation = result->value.receipt.generation;
}

static latent_transport_config configuration(void) {
    latent_transport_config config = latent_transport_defaults();
    config.endpoint = (latent_string){address, strlen(address)};
    config.tenant = TEXT("tests");
    config.bearer_token = (latent_bytes){(const uint8_t *)"LSF-PUBLIC-C-PEER-TEST-ONLY", sizeof("LSF-PUBLIC-C-PEER-TEST-ONLY") - 1};
    config.timeout_millis = 500;
    config.maximum_response_bytes = 65536;
    return config;
}

static latent_transport *create(latent_transport_config config) {
    latent_transport *owner = NULL;
    latent_profile_client_failure error;
    assert(latent_transport_create(&config, &owner, &error));
    assert(owner != NULL);
    return owner;
}

static void close_owner(latent_transport *owner) {
    assert(latent_transport_shutdown(owner, 1000));
    latent_transport_usage usage = latent_transport_get_usage(owner);
    assert(usage.sessions == 0 && usage.sockets == 0 && usage.http2_bytes == 0);
    assert(usage.in_flight == 0 && usage.queued == 0 && usage.retained_calls == 0 && usage.callbacks_pending == 0);
    assert(latent_transport_destroy(owner));
}

static latent_profile_invoke_request request(latent_string identity, latent_string mode) {
    return (latent_profile_invoke_request){.has_activation_id = true, .activation_id = identity,
        .has_target = true, .target = {.tenant = TEXT("tests"), .service = TEXT("example"), .contract = TEXT("tests:local/api@1.0.0"), .function = TEXT("run")},
        .payload = {(const uint8_t *)mode.data, mode.length}, .media_type = TEXT("application/octet-stream"),
        .has_budget = true, .budget = {.cpu_fuel = UINT64_MAX, .memory_bytes = 65536, .has_wall_time_limit_millis = true, .wall_time_limit_millis = 0}};
}

static void wait_for(latent_transport *owner, observed *record) {
    uint64_t deadline = now() + 2000;
    while (record->calls == 0 && now() < deadline) assert(latent_transport_poll(owner, 5));
    assert(record->calls == 1);
}

static observed invoke_mode(latent_transport *owner, latent_string identity, latent_string mode) {
    observed record = {0};
    latent_profile_invoke_request value = request(identity, mode);
    latent_profile_call *call = api->invoke(latent_transport_profile(owner), &value, NULL, invoked, &record);
    wait_for(owner, &record);
    if (call != NULL) api->release_call(call);
    return record;
}

static void configuration_and_connection(void) {
    const latent_string invalid[] = {TEXT("http://localhost:80"), TEXT("https://127.0.0.1:80"),
        TEXT("http://192.0.2.1:80"), TEXT("http://[::2]:80"), TEXT("http://127.0.0.1:0"),
        TEXT("http://127.0.0.1:080"), TEXT("http://127.0.0.1:80/path"), TEXT("http://127.0.0.1:80@evil")};
    for (size_t index = 0; index < sizeof(invalid) / sizeof(invalid[0]); ++index) {
        latent_transport_config config = configuration();
        config.endpoint = invalid[index];
        latent_transport *owner = NULL;
        latent_profile_client_failure error;
        assert(!latent_transport_create(&config, &owner, &error) && owner == NULL);
        assert(error.category == LATENT_PROFILE_FAILURE_CATEGORY_INVALID_REQUEST);
    }
    latent_transport_config config = configuration();
    config.bearer_token = (latent_bytes){(const uint8_t *)"token\n", 6};
    latent_transport *owner = NULL;
    assert(!latent_transport_create(&config, &owner, NULL));
    config = configuration();
    config.endpoint = TEXT("http://[::1]:80");
    close_owner(create(config));
    int descriptor = socket(AF_INET, SOCK_STREAM, 0);
    assert(descriptor >= 0);
    struct sockaddr_in reserved = {.sin_family = AF_INET, .sin_addr = {.s_addr = htonl(INADDR_LOOPBACK)}};
    assert(bind(descriptor, (const struct sockaddr *)&reserved, sizeof(reserved)) == 0);
    socklen_t length = sizeof(reserved);
    assert(getsockname(descriptor, (struct sockaddr *)&reserved, &length) == 0);
    char endpoint[64];
    int used = snprintf(endpoint, sizeof(endpoint), "http://127.0.0.1:%u", (unsigned)ntohs(reserved.sin_port));
    assert(used > 0 && (size_t)used < sizeof(endpoint));
    config = configuration();
    config.endpoint = (latent_string){endpoint, (size_t)used};
    owner = create(config);
    observed record = invoke_mode(owner, TEXT("refused-tcp"), TEXT("ok"));
    assert(record.failed && !record.dispatched && record.category == LATENT_PROFILE_FAILURE_CATEGORY_TRANSPORT);
    assert(record.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_NOT_DISPATCHED);
    close_owner(owner);
    assert(close(descriptor) == 0);
}

static void basic_and_ownership(void) {
    latent_transport *owner = create(configuration());
    char identity[] = "copy-before-return";
    uint8_t opaque[] = {0, 1, 255, 0, 128};
    latent_profile_invoke_request value = request((latent_string){identity, strlen(identity)}, TEXT("ignored"));
    value.payload = (latent_bytes){opaque, sizeof(opaque)};
    observed record = {0};
    latent_profile_call *call = api->invoke(latent_transport_profile(owner), &value, NULL, invoked, &record);
    assert(call != NULL && record.calls == 0);
    memset(identity, 'x', sizeof(identity));
    memset(opaque, 0xa5, sizeof(opaque));
    memset(&value, 0xa5, sizeof(value));
    wait_for(owner, &record);
    assert(!record.failed && record.generation == UINT64_MAX && strcmp(record.identity, "copy-before-return") == 0);
    assert(record.payload_length == 5 && record.payload[2] == 255 && record.payload[4] == 128);
    latent_transport_usage retained = latent_transport_get_usage(owner);
    assert(retained.retained_calls == 1 && retained.in_flight == 0 && retained.sessions == 1 && retained.sockets == 1);
    assert(!latent_transport_destroy(owner));
    api->release_call(call);
    for (unsigned index = 0; index < 3; ++index) {
        record = invoke_mode(owner, TEXT("reusable"), TEXT("ok"));
        assert(!record.failed);
        assert(latent_transport_get_usage(owner).sessions == 1);
    }
    record = invoke_mode(owner, TEXT("declared"), TEXT("declared"));
    assert(!record.failed && record.variant == 2);
    record = invoke_mode(owner, TEXT("platform"), TEXT("platform"));
    assert(!record.failed && record.variant == 3);
    record = invoke_mode(owner, TEXT(""), TEXT("ok"));
    assert(record.failed && record.grpc == 3 && record.grpc_present && record.dispatched);
    close_owner(owner);
}

static void pending_cancel_and_recovery(void) {
    latent_transport *owner = create(configuration());
    latent_profile_client *client = latent_transport_profile(owner);
    observed pending = {0}, running = {0}, cancelled_record = {0};
    latent_profile_invoke_request held = request(TEXT("pending"), TEXT("hold"));
    latent_profile_call *call = api->invoke(client, &held, NULL, invoked, &pending);
    assert(latent_transport_poll(owner, 5));
    latent_profile_get_activation_request lookup = {TEXT("pending")};
    latent_profile_call *status_call = api->get_activation(client, &lookup, NULL, status, &running);
    wait_for(owner, &running);
    assert(!running.failed && !running.terminal && pending.calls == 0);
    api->release_call(status_call);
    latent_profile_cancel_request cancellation = {TEXT("pending"), TEXT("explicit")};
    latent_profile_call *cancel_call = api->cancel(client, &cancellation, NULL, cancelled, &cancelled_record);
    wait_for(owner, &cancelled_record);
    wait_for(owner, &pending);
    assert(!cancelled_record.failed && cancelled_record.disposition == 1 && !cancelled_record.terminal);
    assert(!pending.failed && pending.variant == 3);
    api->release_call(cancel_call);
    api->release_call(call);
    cancelled_record = (observed){0};
    cancel_call = api->cancel(client, &cancellation, NULL, cancelled, &cancelled_record);
    wait_for(owner, &cancelled_record);
    assert(cancelled_record.disposition == 2 && cancelled_record.terminal);
    api->release_call(cancel_call);
    cancellation.activation_id = TEXT("missing");
    cancelled_record = (observed){0};
    cancel_call = api->cancel(client, &cancellation, NULL, cancelled, &cancelled_record);
    wait_for(owner, &cancelled_record);
    assert(cancelled_record.disposition == 3 && !cancelled_record.terminal);
    api->release_call(cancel_call);
    observed lost = invoke_mode(owner, TEXT("drop-id"), TEXT("drop"));
    assert(lost.failed && lost.dispatched && lost.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN);
    lookup.activation_id = TEXT("drop-id");
    running = (observed){0};
    status_call = api->get_activation(client, &lookup, NULL, status, &running);
    wait_for(owner, &running);
    assert(!running.failed && running.terminal && strcmp(running.identity, "drop-id") == 0);
    api->release_call(status_call);
    lookup.activation_id = TEXT("missing-record");
    running = (observed){0};
    status_call = api->get_activation(client, &lookup, NULL, status, &running);
    wait_for(owner, &running);
    assert(running.failed && running.grpc == 5 && running.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN);
    api->release_call(status_call);
    close_owner(owner);
}

static latent_profile_apply_policy_request mutation(latent_string identity) {
    return (latent_profile_apply_policy_request){.has_policy = true,
        .policy = {.id = identity, .has_metadata = true, .metadata = {.name = identity, .has_tenant = true, .tenant = TEXT("tests")},
            .document = TEXT("{}"), .language = TEXT("lsf-capability-policy-v1"), .record_kind = LATENT_PROFILE_CAPABILITY_POLICY_RECORD_KIND_POLICY},
        .has_expected_generation = true, .expected_generation = 0, .operation_id = identity};
}

static void management(void) {
    latent_transport *owner = create(configuration());
    latent_profile_client *client = latent_transport_profile(owner);
    latent_profile_list_policies_request page = {.record_kind = 1, .has_page = true, .page = {.page_size = 1}};
    observed record = {0};
    latent_profile_call *call = api->list_policies(client, &page, NULL, policies, &record);
    wait_for(owner, &record);
    assert(!record.failed && record.count == 1 && record.generation == UINT64_MAX && record.cursor[0] != 0);
    api->release_call(call);
    page.page.has_page_token = true;
    page.page.page_token = (latent_string){record.cursor, strlen(record.cursor)};
    observed next = {0};
    call = api->list_policies(client, &page, NULL, policies, &next);
    memset(record.cursor, 'x', sizeof(record.cursor));
    wait_for(owner, &next);
    assert(!next.failed && next.count == 1 && next.cursor[0] == 0);
    api->release_call(call);
    page.has_page = false;
    record = (observed){0};
    assert(api->list_policies(client, &page, NULL, policies, &record) == NULL && record.category == LATENT_PROFILE_FAILURE_CATEGORY_INVALID_REQUEST);
    page.has_page = true;
    page.page.page_size = 33;
    record = (observed){0};
    assert(api->list_policies(client, &page, NULL, policies, &record) == NULL && record.failed);
    latent_profile_list_capabilities_request inspection = {.deployment_id = TEXT("guest-http")};
    for (unsigned index = 0; index < 2; ++index) {
        inspection.has_page = index == 1;
        record = (observed){0};
        call = api->list_capabilities(client, &inspection, NULL, capabilities, &record);
        wait_for(owner, &record);
        assert(!record.failed && record.counters);
        api->release_call(call);
    }
    inspection.page.page_size = 129;
    record = (observed){0};
    assert(api->list_capabilities(client, &inspection, NULL, capabilities, &record) == NULL && record.failed);
    const latent_string ids[] = {TEXT("no-audit"), TEXT("audit-durable"), TEXT("audit-future-state"), TEXT("audit-outcome-unknown"), TEXT("lost-policy")};
    for (size_t index = 0; index < sizeof(ids) / sizeof(ids[0]); ++index) {
        latent_profile_apply_policy_request apply = mutation(ids[index]);
        record = (observed){0};
        call = api->apply_policy(client, &apply, NULL, applied, &record);
        wait_for(owner, &record);
        if (index == 4) assert(record.failed && record.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN);
        else {
            assert(!record.failed && record.receipt && record.generation == 1);
            if (index == 0) assert(!record.audit && !record.raw_audit && !record.attempt_present);
            else {
                assert(record.attempt_present && record.attempt == UINT64_MAX && record.raw_audit);
                assert(record.audit == (index != 2));
                assert(record.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_OBSERVED);
            }
        }
        api->release_call(call);
        latent_profile_get_policy_operation_request lookup = {ids[index]};
        record = (observed){0};
        call = api->get_policy_operation(client, &lookup, NULL, operation, &record);
        wait_for(owner, &record);
        assert(!record.failed && record.receipt && record.generation == 1);
        api->release_call(call);
        record = (observed){0};
        call = api->apply_policy(client, &apply, NULL, applied, &record);
        wait_for(owner, &record);
        assert(!record.failed && record.generation == 1);
        api->release_call(call);
        apply.policy.document = TEXT("changed");
        record = (observed){0};
        call = api->apply_policy(client, &apply, NULL, applied, &record);
        wait_for(owner, &record);
        assert(record.failed && record.grpc == 9);
        api->release_call(call);
    }
    latent_profile_get_policy_request get = {TEXT("no-audit"), 1};
    record = (observed){0};
    call = api->get_policy(client, &get, NULL, policy, &record);
    wait_for(owner, &record);
    assert(!record.failed && record.policy && record.generation == 1);
    api->release_call(call);
    latent_profile_get_policy_operation_request lookup = {TEXT("rpc-not-found")};
    record = (observed){0};
    call = api->get_policy_operation(client, &lookup, NULL, operation, &record);
    wait_for(owner, &record);
    assert(record.failed && record.grpc == 5 && record.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN);
    api->release_call(call);
    lookup.operation_id = TEXT("absent-operation");
    record = (observed){0};
    call = api->get_policy_operation(client, &lookup, NULL, operation, &record);
    wait_for(owner, &record);
    assert(!record.failed && !record.receipt && record.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN);
    api->release_call(call);
    close_owner(owner);
}

static void errors_and_deadlines(void) {
    latent_transport *owner = create(configuration());
    const latent_string modes[] = {TEXT("malformed"), TEXT("oversize"), TEXT("wrong-id"), TEXT("contradictory"),
        TEXT("empty-publication"), TEXT("future-platform"), TEXT("truncated"), TEXT("header-flood")};
    for (size_t index = 0; index < sizeof(modes) / sizeof(modes[0]); ++index) {
        observed record = invoke_mode(owner, TEXT("bad-reply"), modes[index]);
        assert(record.failed && record.dispatched && record.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN);
        assert(record.category == LATENT_PROFILE_FAILURE_CATEGORY_DECODE || record.category == LATENT_PROFILE_FAILURE_CATEGORY_LIMIT);
        if (index == 5) assert(record.unsupported && strcmp(record.unsupported_text, "future-outcome") == 0);
    }
    observed record = invoke_mode(owner, TEXT("detail"), TEXT("rpc-detail"));
    assert(record.failed && record.grpc == 7 && record.platform_detail);
    record = invoke_mode(owner, TEXT("rpc-future"), TEXT("rpc-future"));
    assert(record.failed && record.grpc == 999 && record.category == LATENT_PROFILE_FAILURE_CATEGORY_RPC);
    record = invoke_mode(owner, TEXT("rpc-deadline"), TEXT("rpc-deadline"));
    assert(record.failed && record.grpc == 4 && record.category == LATENT_PROFILE_FAILURE_CATEGORY_DEADLINE);
    record = invoke_mode(owner, TEXT("refused-id"), TEXT("refused"));
    assert(record.failed && record.dispatched);
    record = invoke_mode(owner, TEXT("goaway-id"), TEXT("goaway"));
    assert(record.failed && record.dispatched);
    record = invoke_mode(owner, TEXT("unknown-field"), TEXT("unknown-field"));
    assert(!record.failed);
    latent_profile_cancel_request cancellation = {TEXT("future-cancel"), TEXT("future")};
    record = (observed){0};
    latent_profile_call *call = api->cancel(latent_transport_profile(owner), &cancellation, NULL, cancelled, &record);
    wait_for(owner, &record);
    assert(record.failed && record.unsupported && strcmp(record.unsupported_text, "-73") == 0);
    api->release_call(call);
    latent_profile_invoke_request held = request(TEXT("local-deadline"), TEXT("hold"));
    latent_profile_call_options options = {.has_timeout_millis = true, .timeout_millis = 40};
    record = (observed){0};
    uint64_t start = now();
    call = api->invoke(latent_transport_profile(owner), &held, &options, invoked, &record);
    wait_for(owner, &record);
    assert(now() - start < 1000 && record.failed && record.category == LATENT_PROFILE_FAILURE_CATEGORY_DEADLINE);
    assert(record.dispatched && !record.grpc_present && latent_transport_get_usage(owner).sockets == 0);
    api->release_call(call);
    for (unsigned index = 0; index < 2; ++index) {
        options.timeout_millis = index == 0 ? 0 : UINT64_MAX;
        record = (observed){0};
        assert(api->invoke(latent_transport_profile(owner), &held, &options, invoked, &record) == NULL);
        assert(record.calls == 1 && !record.dispatched);
    }
    close_owner(owner);
}

static void bounds_and_shutdown(void) {
    latent_transport_config config = configuration();
    config.maximum_in_flight = 1;
    config.maximum_queued = 1;
    config.maximum_retained_calls = 2;
    latent_transport *owner = create(config);
    latent_profile_invoke_request held = request(TEXT("capacity"), TEXT("hold"));
    observed first = {0}, second = {0}, excess = {0};
    latent_profile_call *first_call = api->invoke(latent_transport_profile(owner), &held, NULL, invoked, &first);
    latent_profile_call_options options = {.has_timeout_millis = true, .timeout_millis = 30};
    latent_profile_call *second_call = api->invoke(latent_transport_profile(owner), &held, &options, invoked, &second);
    assert(api->invoke(latent_transport_profile(owner), &held, NULL, invoked, &excess) == NULL);
    assert(excess.failed && excess.category == LATENT_PROFILE_FAILURE_CATEGORY_LIMIT && !excess.dispatched);
    wait_for(owner, &second);
    assert(second.failed && !second.dispatched && second.category == LATENT_PROFILE_FAILURE_CATEGORY_DEADLINE);
    assert(first.calls == 0);
    api->release_call(second_call);
    api->cancel_local(first_call);
    assert(first.calls == 1 && first.category == LATENT_PROFILE_FAILURE_CATEGORY_LOCAL_CANCELLED);
    assert(latent_transport_get_usage(owner).sockets == 0);
    api->release_call(first_call);
    close_owner(owner);
    for (unsigned trial = 0; trial < 24; ++trial) {
        owner = create(configuration());
        observed record = {0};
        latent_profile_invoke_request value = request(TEXT("shutdown-race"), TEXT("ok"));
        latent_profile_call *call = api->invoke(latent_transport_profile(owner), &value, NULL, invoked, &record);
        for (unsigned step = 0; step < trial % 4; ++step) assert(latent_transport_poll(owner, 1));
        assert(latent_transport_shutdown(owner, 1000));
        assert(record.calls == 1 && (!record.failed || record.category == LATENT_PROFILE_FAILURE_CATEGORY_LOCAL_CANCELLED));
        api->release_call(call);
        close_owner(owner);
    }
    owner = create(configuration());
    first = (observed){.stop_owner = owner};
    second = (observed){0};
    latent_profile_invoke_request normal = request(TEXT("reentrant"), TEXT("ok"));
    first_call = api->invoke(latent_transport_profile(owner), &normal, NULL, invoked, &first);
    second_call = api->invoke(latent_transport_profile(owner), &held, NULL, invoked, &second);
    wait_for(owner, &first);
    assert(second.calls == 1 && second.category == LATENT_PROFILE_FAILURE_CATEGORY_LOCAL_CANCELLED);
    api->release_call(first_call);
    api->release_call(second_call);
    close_owner(owner);
}

static void completion_and_allocation_bounds(void) {
    for (unsigned index = 0; index < 3; ++index) {
        latent_transport_config config = configuration();
        if (index == 0) config.maximum_request_bytes = 16;
        else if (index == 1) config.maximum_decoded_bytes = 16;
        else config.maximum_owned_bytes = 131072;
        latent_transport *owner = create(config);
        observed record = invoke_mode(owner, TEXT("finite-owner"), TEXT("ok"));
        assert(record.failed && record.category == LATENT_PROFILE_FAILURE_CATEGORY_LIMIT);
        assert(record.dispatched == (index == 1));
        assert(latent_transport_get_usage(owner).peak_owned_bytes <= config.maximum_owned_bytes);
        close_owner(owner);
    }
    latent_transport_config config = configuration();
    config.maximum_retained_calls = 1;
    latent_transport *owner = create(config);
    observed first = {0}, second = {0};
    latent_profile_invoke_request value = request(TEXT("retained-capacity"), TEXT("ok"));
    latent_profile_call *first_call = api->invoke(latent_transport_profile(owner), &value, NULL, invoked, &first);
    wait_for(owner, &first);
    assert(!first.failed && latent_transport_get_usage(owner).retained_calls == 1);
    assert(api->invoke(latent_transport_profile(owner), &value, NULL, invoked, &second) == NULL);
    assert(second.failed && second.category == LATENT_PROFILE_FAILURE_CATEGORY_LIMIT && !second.dispatched);
    api->release_call(first_call);
    second = invoke_mode(owner, TEXT("reclaimed-capacity"), TEXT("ok"));
    assert(!second.failed);
    close_owner(owner);
    config = configuration();
    config.maximum_request_bytes = 16;
    owner = create(config);
    first = (observed){.stop_owner = owner};
    assert(api->invoke(latent_transport_profile(owner), &value, NULL, invoked, &first) == NULL);
    assert(first.calls == 1 && first.category == LATENT_PROFILE_FAILURE_CATEGORY_LIMIT);
    close_owner(owner);
    owner = create(configuration());
    first = (observed){.stop_owner = owner};
    assert(api->invoke(latent_transport_profile(owner), NULL, NULL, invoked, &first) == NULL);
    assert(first.calls == 1 && first.category == LATENT_PROFILE_FAILURE_CATEGORY_INVALID_REQUEST);
    close_owner(owner);
    owner = create(configuration());
    first = (observed){0};
    first_call = api->invoke(latent_transport_profile(owner), &value, NULL, invoked, &first);
    api->cancel_local(first_call);
    api->cancel_local(first_call);
    assert(first.calls == 1 && !first.dispatched && first.category == LATENT_PROFILE_FAILURE_CATEGORY_LOCAL_CANCELLED);
    api->release_call(first_call);
    close_owner(owner);
    owner = create(configuration());
    first = (observed){0};
    second = (observed){.pause_millis = 120};
    value = request(TEXT("paired-fast-deadline"), TEXT("paired"));
    latent_profile_call_options options = {.has_timeout_millis = true, .timeout_millis = 80};
    first_call = api->invoke(latent_transport_profile(owner), &value, &options, invoked, &first);
    value.activation_id = TEXT("paired-slow-callback");
    latent_profile_call *second_call = api->invoke(latent_transport_profile(owner), &value, NULL, invoked, &second);
    wait_for(owner, &second);
    wait_for(owner, &first);
    assert(!second.failed && first.failed && first.dispatched && first.category == LATENT_PROFILE_FAILURE_CATEGORY_DEADLINE);
    api->release_call(first_call);
    api->release_call(second_call);
    close_owner(owner);
}

typedef struct allocation_state { size_t calls; size_t fail_at; size_t live; bool injected; } allocation_state;

static void *allocate(size_t size, void *context) {
    allocation_state *state = context;
    if (++state->calls == state->fail_at) { state->injected = true; return NULL; }
    void *pointer = malloc(size);
    if (pointer != NULL) ++state->live;
    return pointer;
}

static void deallocate(void *pointer, void *context) {
    allocation_state *state = context;
    assert(state->live > 0);
    --state->live;
    free(pointer);
}

static void allocation_failures(void) {
    size_t injected = 0;
    for (size_t failure_position = 1; failure_position <= 160; ++failure_position) {
        allocation_state state = {.fail_at = failure_position};
        latent_transport_config config = configuration();
        config.allocator = (latent_transport_allocator){allocate, deallocate, &state};
        latent_transport *owner = NULL;
        latent_profile_client_failure error;
        if (!latent_transport_create(&config, &owner, &error)) { assert(state.live == 0); injected += state.injected; continue; }
        observed record = invoke_mode(owner, TEXT("allocation-path"), TEXT("ok"));
        assert(record.calls == 1);
        close_owner(owner);
        assert(state.live == 0);
        injected += state.injected;
    }
    assert(injected > 32);
    printf("C allocation fault sweep: %zu injected failures across 160 positions\n", injected);
}

static void legacy_callback(latent_invocation *handle, const latent_invocation_outcome *outcome,
                            const latent_transport_error *error, void *data) {
    observed *record = data;
    ++record->calls;
    assert(record->calls == 1 && (error == NULL) != (outcome == NULL));
    if (error != NULL) { record->failed = true; return; }
    assert(handle != NULL);
    record->variant = (unsigned)outcome->kind;
    if (outcome->kind == LATENT_INVOCATION_SUCCEEDED) assert(outcome->success->route_generation == UINT64_MAX);
    else if (outcome->kind == LATENT_INVOCATION_DECLARED_ERROR) assert(outcome->declared_error->receipt.consumption.cpu_fuel == UINT64_MAX);
    else assert(outcome->platform_failure->receipt.consumption.cpu_fuel == UINT64_MAX);
}

static void legacy_status(latent_client *client, const latent_activation_status *value,
                          const latent_transport_error *error, void *data) {
    observed *record = data;
    assert(client != NULL && ++record->calls == 1 && (value == NULL) != (error == NULL));
    record->failed = error != NULL;
    if (value != NULL) {
        record->terminal = value->has_terminal_state;
        if (record->terminal) assert(value->final_consumption.cpu_fuel == UINT64_MAX);
    }
}

static void legacy_cancel(latent_client *client, const latent_cancel_response *value,
                          const latent_transport_error *error, void *data) {
    observed *record = data;
    assert(client != NULL && ++record->calls == 1 && (value == NULL) != (error == NULL));
    record->failed = error != NULL;
    if (value != NULL) record->disposition = value->disposition;
}

static void legacy(void) {
    latent_transport *owner = create(configuration());
    latent_invoke_request value = {.has_activation_id = true, .activation_id = TEXT("legacy"),
        .target = {.tenant = TEXT("tests"), .service = TEXT("example"), .contract = TEXT("tests:local/api@1.0.0"), .function = TEXT("run")},
        .payload = {(const uint8_t *)"ok", 2}, .media_type = TEXT("application/octet-stream")};
    observed record = {0};
    latent_invocation *handle = latent_transport_legacy_vtable()->invoke(latent_transport_legacy(owner), &value, legacy_callback, &record);
    assert(handle != NULL);
    wait_for(owner, &record);
    assert(latent_transport_get_usage(owner).retained_calls == 0);
    const latent_client_vtable *legacy = latent_transport_legacy_vtable();
    const latent_string modes[] = {TEXT("declared"), TEXT("platform")};
    for (unsigned index = 0; index < 2; ++index) {
        record = (observed){0};
        value.payload = (latent_bytes){(const uint8_t *)modes[index].data, modes[index].length};
        assert(legacy->invoke(latent_transport_legacy(owner), &value, legacy_callback, &record) != NULL);
        wait_for(owner, &record);
        assert(!record.failed && record.variant == (unsigned)(index == 0 ? LATENT_INVOCATION_DECLARED_ERROR : LATENT_INVOCATION_PLATFORM_FAILURE));
    }
    value.activation_id = TEXT("legacy-pending");
    value.payload = (latent_bytes){(const uint8_t *)"hold", 4};
    record = (observed){0};
    assert(legacy->invoke(latent_transport_legacy(owner), &value, legacy_callback, &record) != NULL);
    assert(latent_transport_poll(owner, 2));
    observed running = {0};
    legacy->get_activation(latent_transport_legacy(owner), value.activation_id, legacy_status, &running);
    wait_for(owner, &running);
    assert(!running.failed && !running.terminal && record.calls == 0);
    for (unsigned index = 0; index < 3; ++index) {
        observed cancelled_record = {0};
        legacy->cancel(latent_transport_legacy(owner), index == 2 ? TEXT("missing-legacy") : value.activation_id,
                       TEXT("reason"), legacy_cancel, &cancelled_record);
        wait_for(owner, &cancelled_record);
        assert(!cancelled_record.failed && cancelled_record.disposition == (int32_t)(index + 1));
    }
    wait_for(owner, &record);
    assert(!record.failed && record.variant == LATENT_INVOCATION_PLATFORM_FAILURE);
    running = (observed){0};
    legacy->get_activation(latent_transport_legacy(owner), value.activation_id, legacy_status, &running);
    wait_for(owner, &running);
    assert(!running.failed && running.terminal);
    running = (observed){0};
    legacy->get_activation(latent_transport_legacy(owner), TEXT("missing-legacy"), legacy_status, &running);
    wait_for(owner, &running);
    assert(running.failed);
    record = (observed){0};
    assert(legacy->invoke(latent_transport_legacy(owner), NULL, legacy_callback, &record) == NULL);
    assert(record.failed && record.calls == 1);
    assert(latent_transport_get_usage(owner).retained_calls == 0);
    close_owner(owner);
}

static size_t file_descriptors(void) {
    DIR *directory = opendir("/proc/self/fd");
    assert(directory != NULL);
    size_t count = 0;
    while (readdir(directory) != NULL) ++count;
    assert(closedir(directory) == 0);
    return count;
}

int main(int argc, char **argv) {
    assert(argc == 2);
    address = argv[1];
    api = latent_transport_profile_vtable();
    size_t descriptors = file_descriptors();
    configuration_and_connection();
    basic_and_ownership();
    pending_cancel_and_recovery();
    management();
    errors_and_deadlines();
    bounds_and_shutdown();
    completion_and_allocation_bounds();
    allocation_failures();
    legacy();
    assert(file_descriptors() == descriptors);
    puts("C HTTP/2/protobuf: eight RPCs, ownership, exact u64, audit absence/future, recovery, limits, deadlines, no retry, shutdown races passed");
    return 0;
}
