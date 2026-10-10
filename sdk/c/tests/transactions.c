#include <latent/transaction_client.h>

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define TEXT(value) ((latent_string){value, sizeof(value) - 1u})
#define BYTES(value) ((latent_bytes){(const uint8_t *)value, sizeof(value) - 1u})
#define DIGEST "sha256:1111111111111111111111111111111111111111111111111111111111111111"
#define PUBLICATION "publication:" DIGEST

typedef struct observed {
    unsigned calls;
    bool failed, dispatched, command, dispatcher, effect, state, namespace_receipt, plan;
    int32_t category, outcome, command_outcome;
    size_t expected_count, payload_length;
    uint8_t expected_first;
    uint64_t expected_revision, after_revision;
    bool unsupported;
    char raw[257], key[257];
} observed;
static const latent_transaction_client_vtable *api;

static void capture(observed *out, const latent_transaction_response_metadata *metadata,
                    const latent_transaction_client_failure *failure) {
    ++out->calls; assert(out->calls == 1);
    const latent_transaction_recovery_identity *identity = failure != NULL ? &failure->identity : &metadata->identity;
    const latent_transaction_observed_outcome *known = failure != NULL ? &failure->observed : &metadata->observed;
    const latent_profile_response_metadata *transport = metadata == NULL ? NULL : &metadata->transport;
    out->failed = failure != NULL;
    out->category = failure == NULL ? 0 : failure->transport.category;
    out->dispatched = failure != NULL && failure->transport.dispatched;
    out->outcome = failure != NULL ? failure->transport.outcome : transport->outcome;
    out->expected_count = identity->expected_versions_count;
    if (identity->expected_versions_count != 0 && identity->expected_versions[0].has_version && identity->expected_versions[0].version.length != 0)
        out->expected_first = identity->expected_versions[0].version.data[0];
    if (identity->command != NULL && identity->command->client_key.length <= 256) {
        memcpy(out->key, identity->command->client_key.data, identity->command->client_key.length);
        out->key[identity->command->client_key.length] = 0;
    }
    out->command = known->has_command;
    out->dispatcher = known->dispatcher != NULL; out->effect = known->effect != NULL;
    out->state = known->state != NULL; out->namespace_receipt = known->namespace != NULL;
    out->plan = known->effect_plan != NULL;
    if (out->plan) assert(identity->effect_plan != NULL && identity->effect_mutation != NULL);
    if (known->has_command) {
        out->command_outcome = known->command.outcome;
        assert(!known->command.has_success && !known->command.has_business_rejection
            && !known->command.has_technical_failure && !known->command.has_cleanup_failure);
        assert(known->command.success.payload.length == 0 && known->command.business_rejection.payload.length == 0);
    }
    if (identity->dispatcher_expected_generation != NULL) out->expected_revision = identity->dispatcher_expected_generation->revision;
    if (known->dispatcher != NULL) out->after_revision = known->dispatcher->after_generation.revision;
    if (failure != NULL && failure->transport.has_unsupported_wire_value) {
        out->unsupported = true;
        latent_string raw = failure->transport.unsupported_wire_value.value;
        assert(raw.length <= 256); memcpy(out->raw, raw.data, raw.length); out->raw[raw.length] = 0;
    }
}

#define CALLBACK(method, request, response) \
static void method(const latent_transaction_##method##_result *value, \
        const latent_transaction_client_failure *failure, void *context) { \
    observed *out = context; \
    assert((value == NULL) != (failure == NULL)); \
    capture(out, value == NULL ? NULL : &value->metadata, failure); \
}
LATENT_TRANSACTION_METHODS(CALLBACK)
#undef CALLBACK

static void invoke_received(const latent_transaction_invoke_command_result *value,
        const latent_transaction_client_failure *failure, void *context) {
    observed *out = context;
    assert((value == NULL) != (failure == NULL));
    capture(out, value == NULL ? NULL : &value->metadata, failure);
    if (value != NULL && value->value.command.has_success) out->payload_length = value->value.command.success.payload.length;
}
static void wait_for(latent_transport *owner, observed *out) {
    for (unsigned count = 0; out->calls == 0 && count < 1000; ++count) assert(latent_transport_poll(owner, 10));
    assert(out->calls == 1);
}
static void finish(latent_transport *owner, latent_profile_call *call, observed *out, bool failed) {
    if (call != NULL) wait_for(owner, out);
    assert(out->calls == 1 && out->failed == failed);
    api->release_call(call);
    latent_transport_usage usage = latent_transport_get_usage(owner);
    assert(usage.retained_calls == 0 && usage.callbacks_pending == 0 && usage.in_flight == 0 && usage.queued == 0);
}
static latent_transaction_namespace_selector ns(void) {
    return (latent_transaction_namespace_selector){TEXT("tests"), TEXT("transactional-aggregate"), TEXT("1")};
}
static latent_transaction_command_selector selector(latent_string key) {
    return (latent_transaction_command_selector){.has_namespace = true, .namespace = ns(),
        .operation = TEXT("update"), .has_entity = true, .entity = TEXT("entity-a"), .client_key = key};
}
static latent_transaction_inspect_namespace_request inspect(void) {
    return (latent_transaction_inspect_namespace_request){.has_profile = true, .profile = latent_transaction_current_profile(),
        .has_namespace = true, .namespace = ns(), .has_authorization_publication = true,
        .authorization_publication = {.id = TEXT(PUBLICATION), .tenant = TEXT("tests")}};
}
static latent_transaction_lookup_command_request lookup(latent_string key) {
    return (latent_transaction_lookup_command_request){.has_profile = true, .profile = latent_transaction_current_profile(),
        .has_command = true, .command = selector(key), .has_authorization_publication = true,
        .authorization_publication = {.id = TEXT(PUBLICATION), .tenant = TEXT("tests")}};
}
static latent_profile_invoke_request invocation(void) {
    return (latent_profile_invoke_request){.has_target = true, .target = {.tenant = TEXT("tests"), .service = TEXT("aggregate"),
        .contract = TEXT("examples:transactional-aggregate/api@1.0.0"), .function = TEXT("update")},
        .payload = BYTES("input-a"), .media_type = TEXT("application/octet-stream"), .has_activation_id = true,
        .activation_id = TEXT("activation-a"), .has_budget = true};
}
static latent_transaction_invoke_command_request invoke_request(latent_string key, latent_transaction_expected_version *expected) {
    return (latent_transaction_invoke_command_request){.has_profile = true, .profile = latent_transaction_current_profile(),
        .has_invocation = true, .invocation = invocation(), .has_command = true, .command = selector(key),
        .input_format = TEXT("aggregate-input-v1"), .expected_versions = expected, .expected_versions_count = 1};
}
static latent_transaction_get_effect_request get_effect_request(latent_string identity) {
    latent_transaction_lookup_command_request original = lookup(TEXT("ok"));
    return (latent_transaction_get_effect_request){.has_profile = true, .profile = original.profile, .has_command = true,
        .command = original.command, .effect_id = identity, .has_authorization_publication = true,
        .authorization_publication = original.authorization_publication};
}
static latent_transaction_control_dispatcher_request control(latent_string identity) {
    return (latent_transaction_control_dispatcher_request){.has_profile = true, .profile = latent_transaction_current_profile(),
        .scope = LATENT_TRANSACTION_DISPATCHER_SCOPE_NODE, .operation_id = identity, .action = LATENT_TRANSACTION_DISPATCHER_ACTION_PAUSE,
        .has_expected_generation = true, .expected_generation = {.owner_epoch = UINT64_MAX, .revision = UINT64_MAX - 1}};
}

static void all_methods(latent_transport *owner) {
    latent_transaction_client *client = latent_transport_transaction(owner);
    observed out = {0}; latent_profile_call *call;
    uint8_t version = 0xaa;
    latent_transaction_expected_version expected = {.key = BYTES("count"), .has_version = true, .version = {&version, 1}};
    latent_transaction_invoke_command_request invoke = invoke_request(TEXT("paired"), &expected);
    char payload[] = "input-a"; invoke.invocation.payload = (latent_bytes){(const uint8_t *)payload, 7};
    call = api->invoke_command(client, &invoke, NULL, invoke_received, &out);
    assert(call != NULL); version = 0xbb; payload[0] = 'x';
    finish(owner, call, &out, false); assert(out.expected_first == 0xaa && out.expected_count == 1 && out.payload_length == 750 * 1024);
    assert(latent_transport_get_usage(owner).sockets == 1);
    latent_transaction_query_request query_request = {.has_profile = true, .profile = latent_transaction_current_profile(), .has_invocation = true,
        .invocation = invocation(), .has_namespace = true, .namespace = ns()};
    out = (observed){0}; call = api->query(client, &query_request, NULL, query, &out);
    finish(owner, call, &out, false); assert(!out.command);
    latent_transaction_lookup_command_request known = lookup(TEXT("ok"));
    out = (observed){0}; call = api->lookup_command(client, &known, NULL, lookup_command, &out); finish(owner, call, &out, false); assert(out.command);
    latent_transaction_lookup_commit_request committed = {.has_profile = true, .profile = known.profile, .has_command = true,
        .command = known.command, .receipt_id = TEXT("receipt-a"), .has_authorization_publication = true,
        .authorization_publication = known.authorization_publication};
    out = (observed){0}; call = api->lookup_commit(client, &committed, NULL, lookup_commit, &out); finish(owner, call, &out, false);
    latent_transaction_get_effect_request effect = get_effect_request(TEXT("effect-a"));
    out = (observed){0}; call = api->get_effect(client, &effect, NULL, get_effect, &out); finish(owner, call, &out, false); assert(out.effect);
    latent_transaction_list_effect_history_request history = {.has_effect = true, .effect = effect, .has_page = true, .page = {.limit = 1}};
    out = (observed){0}; call = api->list_effect_history(client, &history, NULL, list_effect_history, &out); finish(owner, call, &out, false);
    latent_transaction_cancel_command_request cancel = {.has_command = true, .command = known, .reason = TEXT("caller requested")};
    out = (observed){0}; call = api->cancel_command(client, &cancel, NULL, cancel_command, &out); finish(owner, call, &out, false);
    latent_transaction_inspect_namespace_request inspected = inspect();
    latent_transaction_mutate_namespace_request mutation = {.has_namespace = true, .namespace = inspected, .operation_id = TEXT("namespace-op"),
        .mutation = LATENT_TRANSACTION_NAMESPACE_MUTATION_KIND_QUIESCE, .has_expected_generation = true, .expected_generation = UINT64_MAX - 1};
    out = (observed){0}; call = api->mutate_namespace(client, &mutation, NULL, mutate_namespace, &out); finish(owner, call, &out, false); assert(out.namespace_receipt);
    out = (observed){0}; call = api->inspect_namespace(client, &inspected, NULL, inspect_namespace, &out); finish(owner, call, &out, false);
    latent_transaction_select_entity_request entities = {.has_namespace = true, .namespace = inspected, .has_page = true, .page = {.limit = 1}};
    out = (observed){0}; call = api->select_entity(client, &entities, NULL, select_entity, &out); finish(owner, call, &out, false);
    latent_transaction_mutate_state_request state = {.has_namespace = true, .namespace = inspected, .operation_id = TEXT("state-op"),
        .mutation = LATENT_TRANSACTION_STATE_MUTATION_KIND_CHECKPOINT_NAMESPACE, .expected_version = BYTES("v1"), .expected_policy_digest = TEXT(DIGEST),
        .reason = TEXT("explicit checkpoint")};
    out = (observed){0}; call = api->mutate_state(client, &state, NULL, mutate_state, &out); finish(owner, call, &out, false); assert(out.state);
    latent_transaction_get_state_operation_receipt_request state_lookup = {.has_namespace = true, .namespace = inspected, .operation_id = TEXT("state-op")};
    out = (observed){0}; call = api->get_state_operation_receipt(client, &state_lookup, NULL, get_state_operation_receipt, &out); finish(owner, call, &out, false);
    latent_transaction_inspect_dispatcher_request dispatcher = {.has_profile = true, .profile = latent_transaction_current_profile(), .scope = LATENT_TRANSACTION_DISPATCHER_SCOPE_NODE};
    out = (observed){0}; call = api->inspect_dispatcher(client, &dispatcher, NULL, inspect_dispatcher, &out); finish(owner, call, &out, false);
    latent_transaction_control_dispatcher_request command = control(TEXT("dispatcher-op"));
    out = (observed){0}; call = api->control_dispatcher(client, &command, NULL, control_dispatcher, &out); finish(owner, call, &out, false);
    assert(out.dispatcher && out.expected_revision == UINT64_MAX - 1 && out.after_revision == UINT64_MAX);
    latent_transaction_get_dispatcher_operation_request dispatcher_lookup = {.has_original = true, .original = command};
    out = (observed){0}; call = api->get_dispatcher_operation(client, &dispatcher_lookup, NULL, get_dispatcher_operation, &out); finish(owner, call, &out, false);
}

static void bounded_recovery(latent_transport *owner) {
    latent_transaction_client *client = latent_transport_transaction(owner);
    uint8_t version = 0xaa;
    latent_transaction_expected_version expected = {.key = BYTES("count"), .has_version = true, .version = {&version, 1}};
    const char *modes[] = {"reject", "abort", "substitution", "lost", "aborted-status", "held"};
    for (size_t index = 0; index < 6; ++index) {
        latent_transaction_invoke_command_request request = invoke_request((latent_string){modes[index], strlen(modes[index])}, &expected);
        observed out = {0}; latent_profile_call *call = api->invoke_command(client, &request, NULL, invoke_received, &out); assert(call != NULL);
        if (index == 5) { assert(latent_transport_poll(owner, 10)); api->cancel_local(call); }
        finish(owner, call, &out, index >= 2);
        assert(out.expected_first == 0xaa && out.expected_count == 1 && strcmp(out.key, modes[index]) == 0);
        if (index == 0) assert(out.command && out.command_outcome == LATENT_TRANSACTION_COMMAND_OUTCOME_REJECTED);
        if (index == 1) assert(out.command && out.command_outcome == LATENT_TRANSACTION_COMMAND_OUTCOME_ABORTED);
        if (index >= 2) assert(!out.command && out.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN);
    }
    const char *lookups[] = {"lost", "expired", "linked256", "unknown", "linked257", "duplicate", "invalid-utf8", "oversized-wire"};
    for (size_t index = 0; index < 8; ++index) {
        latent_transaction_lookup_command_request request = lookup((latent_string){lookups[index], strlen(lookups[index])});
        observed out = {0}; latent_profile_call *call = api->lookup_command(client, &request, NULL, lookup_command, &out);
        finish(owner, call, &out, index >= 4);
        if (index < 3) assert(out.command && out.command_outcome == 2 && out.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_OBSERVED);
        if (index == 3) assert(out.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN);
        if (index >= 4) assert(!out.command && out.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN);
    }
    const char *audit_modes[] = {"audit-body", "audit-header", "wrong-cas"};
    for (size_t index = 0; index < 3; ++index) {
        latent_transaction_control_dispatcher_request request = control((latent_string){audit_modes[index], strlen(audit_modes[index])});
        observed out = {0}; latent_profile_call *call = api->control_dispatcher(client, &request, NULL, control_dispatcher, &out);
        finish(owner, call, &out, true);
        assert(out.expected_revision == UINT64_MAX - 1 && out.dispatcher == (index < 2));
        assert(out.outcome == (index < 2 ? LATENT_PROFILE_OUTCOME_KNOWLEDGE_OBSERVED : LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN));
        if (index == 0) assert(out.unsupported && strcmp(out.raw, "91") == 0);
    }
    latent_transaction_get_effect_request effect = get_effect_request(TEXT("future"));
    observed out = {0}; latent_profile_call *call = api->get_effect(client, &effect, NULL, get_effect, &out);
    finish(owner, call, &out, true); assert(out.unsupported && strcmp(out.raw, "91") == 0 && !out.effect);
    latent_transaction_list_effect_history_request page = {.has_effect = true, .effect = get_effect_request(TEXT("oversized-page")),
        .has_page = true, .page = {.limit = 128}};
    out = (observed){0}; call = api->list_effect_history(client, &page, NULL, list_effect_history, &out);
    finish(owner, call, &out, true); assert(out.category == LATENT_PROFILE_FAILURE_CATEGORY_LIMIT && !out.effect);
}

static void effect_plan_methods(latent_transport *owner) {
    latent_transaction_client *client = latent_transport_transaction(owner);
    uint8_t version[32], plan_digest[32]; memset(version, 1, sizeof(version)); memset(plan_digest, 2, sizeof(plan_digest));
    latent_transaction_plan_effect_mutation_request original = {.has_effect = true,
        .effect = get_effect_request(TEXT("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")),
        .operation_id = TEXT("effect-op"), .mutation = LATENT_TRANSACTION_STATE_MUTATION_KIND_RETRY_KNOWN_FAILED_EFFECT,
        .expected_version = {version, sizeof(version)}, .expected_policy_digest = TEXT(DIGEST), .reason = TEXT("explicit redrive"), .retry_delay_millis = 100};
    observed out = {0}; latent_profile_call *call = api->plan_effect_mutation(client, &original, NULL, plan_effect_mutation, &out);
    finish(owner, call, &out, false); assert(out.plan && out.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN);
    latent_transaction_effect_management_plan plan = {.has_original = true, .original = original, .plan_digest = {plan_digest, sizeof(plan_digest)},
        .management_sequence = 1, .owner_epoch = UINT64_MAX, .claim_generation = 1, .dispatch_attempt = 1,
        .prepared_at_unix_millis = 1000, .expires_at_unix_millis = 2000, .before = LATENT_TRANSACTION_EFFECT_DISPOSITION_KNOWN_FAILURE,
        .safety = LATENT_TRANSACTION_EFFECT_PLAN_SAFETY_KNOWN_NONEXECUTION};
    latent_transaction_mutate_state_request mutation = {.has_namespace = true, .namespace = inspect(), .operation_id = original.operation_id,
        .mutation = original.mutation, .has_record_id = true, .record_id = original.effect.effect_id, .expected_version = original.expected_version,
        .expected_policy_digest = original.expected_policy_digest, .reason = original.reason, .has_effect_plan = true, .effect_plan = plan};
    out = (observed){0}; call = api->mutate_state(client, &mutation, NULL, mutate_state, &out); finish(owner, call, &out, false);
    assert(out.state && out.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_OBSERVED);
    latent_transaction_get_state_operation_receipt_request recovery = {.has_namespace = true, .namespace = inspect(), .operation_id = original.operation_id,
        .has_original_effect_plan = true, .original_effect_plan = plan};
    recovery.namespace.authorization_publication.id = TEXT("publication:sha256:2222222222222222222222222222222222222222222222222222222222222222");
    out = (observed){0}; call = api->get_state_operation_receipt(client, &recovery, NULL, get_state_operation_receipt, &out); finish(owner, call, &out, false);
    assert(out.state && out.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_OBSERVED);
    mutation.has_effect_plan = false;
    out = (observed){0}; call = api->mutate_state(client, &mutation, NULL, mutate_state, &out); finish(owner, call, &out, true); assert(!out.dispatched);
    mutation.has_effect_plan = true; uint8_t zero[32] = {0}; mutation.expected_version = (latent_bytes){zero, sizeof(zero)};
    out = (observed){0}; call = api->mutate_state(client, &mutation, NULL, mutate_state, &out); finish(owner, call, &out, true); assert(!out.dispatched);
    original.reason = TEXT("bad-audit");
    out = (observed){0}; call = api->plan_effect_mutation(client, &original, NULL, plan_effect_mutation, &out); finish(owner, call, &out, true);
    assert(out.dispatched && out.plan && out.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN);
    original.reason = TEXT("bad-window");
    out = (observed){0}; call = api->plan_effect_mutation(client, &original, NULL, plan_effect_mutation, &out); finish(owner, call, &out, true); assert(!out.plan);
    original.reason = TEXT("forged-fact"); plan.original = original; mutation.expected_version = original.expected_version; mutation.reason = original.reason; mutation.effect_plan = plan;
    out = (observed){0}; call = api->mutate_state(client, &mutation, NULL, mutate_state, &out); finish(owner, call, &out, true); assert(!out.state);
}

static void local_rejections(latent_transport *owner) {
    latent_transaction_client *client = latent_transport_transaction(owner);
    latent_transaction_control_dispatcher_request command = control(TEXT("overflow")); command.expected_generation.revision = UINT64_MAX;
    observed out = {0}; assert(api->control_dispatcher(client, &command, NULL, control_dispatcher, &out) == NULL);
    assert(out.calls == 1 && out.failed && !out.dispatched && out.expected_revision == UINT64_MAX && out.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_NOT_DISPATCHED);
    uint8_t version = 0xaa;
    latent_transaction_expected_version expected = {.key = BYTES("count"), .has_version = true, .version = {&version, 1}};
    latent_transaction_invoke_command_request request = invoke_request(TEXT("local-deadline"), &expected);
    request.invocation.has_deadline_unix_millis = true; request.invocation.deadline_unix_millis = 0;
    out = (observed){0}; assert(api->invoke_command(client, &request, NULL, invoke_command, &out) == NULL);
    assert(out.calls == 1 && out.category == LATENT_PROFILE_FAILURE_CATEGORY_DEADLINE && !out.dispatched && strcmp(out.key, "local-deadline") == 0);
    request.invocation.has_deadline_unix_millis = false; expected.has_version = false; expected.has_absent = true; expected.absent = false;
    out = (observed){0}; assert(api->invoke_command(client, &request, NULL, invoke_command, &out) == NULL);
    assert(out.calls == 1 && out.category == LATENT_PROFILE_FAILURE_CATEGORY_INVALID_REQUEST && !out.dispatched);
    expected.has_absent = false; expected.has_version = true;
    request.profile.host_abi_digest = TEXT(DIGEST);
    out = (observed){0}; assert(api->invoke_command(client, &request, NULL, invoke_command, &out) == NULL);
    assert(out.calls == 1 && out.category == LATENT_PROFILE_FAILURE_CATEGORY_INVALID_REQUEST && !out.dispatched);
    request.profile = latent_transaction_current_profile(); request.command.namespace.tenant = TEXT("other-tenant");
    out = (observed){0}; assert(api->invoke_command(client, &request, NULL, invoke_command, &out) == NULL);
    assert(out.calls == 1 && out.category == LATENT_PROFILE_FAILURE_CATEGORY_INVALID_REQUEST && !out.dispatched);
}

typedef struct reentrant {
    latent_transport *owner;
    latent_profile_call *current, *nested;
    observed primary, next;
} reentrant;

static void stop_from_receipt(const latent_transaction_lookup_command_result *value,
        const latent_transaction_client_failure *failure, void *context) {
    reentrant *out = context;
    assert(value != NULL && failure == NULL);
    capture(&out->primary, &value->metadata, NULL);
    assert(out->primary.command && strcmp(out->primary.key, "reentrant") == 0);
    assert(!latent_transport_poll(out->owner, 0) && !latent_transport_destroy(out->owner));
    size_t retained = latent_transport_get_usage(out->owner).retained_calls;
    api->release_call(out->current);
    assert(latent_transport_get_usage(out->owner).retained_calls == retained);
    latent_transaction_get_effect_request request = get_effect_request(TEXT("reentrant-effect"));
    out->nested = api->get_effect(latent_transport_transaction(out->owner), &request, NULL, get_effect, &out->next);
    assert(out->nested != NULL);
    latent_transport_stop(out->owner);
    assert(latent_transport_get_usage(out->owner).sockets == 0
        && latent_transport_get_usage(out->owner).sessions == 0);
    /* Physical stop does not free a currently borrowed receipt or request. */
    assert(value->metadata.observed.command.has_commit
        && value->metadata.identity.command->client_key.length == 9
        && memcmp(value->metadata.identity.command->client_key.data, "reentrant", 9) == 0);
}

static void reentrant_shutdown(latent_transport *owner) {
    latent_transaction_query_request held = {.has_profile = true, .profile = latent_transaction_current_profile(),
        .has_invocation = true, .invocation = invocation(), .has_namespace = true, .namespace = ns()};
    held.invocation.target.function = TEXT("held-query");
    observed pending = {0};
    latent_profile_call *waiting = api->query(latent_transport_transaction(owner), &held, NULL, query, &pending);
    assert(waiting != NULL);
    reentrant out = {.owner = owner};
    latent_transaction_lookup_command_request request = lookup(TEXT("reentrant"));
    out.current = api->lookup_command(latent_transport_transaction(owner), &request, NULL, stop_from_receipt, &out);
    assert(out.current != NULL);
    wait_for(owner, &out.primary);
    assert(pending.calls == 1 && pending.failed && pending.dispatched
        && pending.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN);
    assert(out.next.calls == 1 && out.next.failed && !out.next.dispatched
        && out.next.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_NOT_DISPATCHED);
    api->release_call(out.current); api->release_call(out.nested); api->release_call(waiting);
    latent_transport_usage usage = latent_transport_get_usage(owner);
    assert(usage.stopped && usage.retained_calls == 0 && usage.callbacks_pending == 0
        && usage.in_flight == 0 && usage.queued == 0 && usage.sockets == 0 && usage.sessions == 0);
}

int main(int argc, char **argv) {
    assert(argc == 2); api = latent_transport_transaction_vtable();
    latent_transport_config config = latent_transport_defaults();
    config.endpoint = (latent_string){argv[1], strlen(argv[1])}; config.tenant = TEXT("tests");
    config.bearer_token = BYTES("LSF-PUBLIC-C-PEER-TEST-ONLY");
    config.maximum_request_bytes = config.maximum_response_bytes = 2097152;
    config.maximum_decoded_bytes = 8388608; config.maximum_owned_bytes = 33554432;
    latent_transport *owner = NULL; assert(latent_transport_create(&config, &owner, NULL));
    local_rejections(owner); assert(latent_transport_get_usage(owner).sockets == 0);
    all_methods(owner); bounded_recovery(owner); effect_plan_methods(owner); reentrant_shutdown(owner);
    assert(latent_transport_shutdown(owner, 1000));
    latent_transport_usage usage = latent_transport_get_usage(owner);
    assert(usage.sockets == 0 && usage.sessions == 0 && usage.retained_calls == 0 && usage.callbacks_pending == 0);
    assert(usage.peak_owned_bytes <= config.maximum_owned_bytes && usage.owned_bytes < 4096);
    printf("C transactions: sixteen authenticated HTTP/2 methods, full u64 CAS, immutable effect plans, historical recovery, independent audit/provider facts, paired 750KiB result, proven abort, limits and reentrant physical shutdown; peak=%zu\n", usage.peak_owned_bytes);
    assert(latent_transport_destroy(owner));
    return 0;
}
