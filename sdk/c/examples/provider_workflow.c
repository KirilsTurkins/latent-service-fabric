#include "common.h"

#include <stdio.h>
#include <string.h>

typedef enum check {
    HTTP_GUEST, BLOB_GUEST, DECLARED_ERROR, PLATFORM_FAILURE, WRONG_TENANT, WRONG_CREDENTIAL,
    BOUNDED_PAGES, PROVIDER_INSPECTION, MUTATION_RECEIPT, EXACT_REPLAY, PRECONDITION_CONFLICT,
    LOCAL_CANCELLATION, EXPLICIT_CANCELLATION, LOST_RESPONSE_STATUS, ABSOLUTE_DEADLINE,
    RESPONSE_LIMIT, SHUTDOWN_OUTSTANDING, CLIENT_OWNERS_REAPED, CHECK_COUNT
} check;

typedef struct workflow {
    ex_config config;
    latent_transport *clients[5];
    const latent_profile_client_vtable *api;
    bool assertions[CHECK_COUNT];
    bool admitted[9];
    ex_result last;
    const char *stage;
    const char *reason;
} workflow;

static const char *const names[CHECK_COUNT] = {"httpGuest", "blobGuest", "declaredError", "platformFailure",
    "wrongTenant", "wrongCredential", "boundedPages", "providerInspection", "mutationReceipt", "exactReplay",
    "preconditionConflict", "localCancellation", "explicitCancellation", "lostResponseStatus", "absoluteDeadline",
    "responseLimit", "shutdownOutstanding", "clientOwnersReaped"};
static const char *const activations[9] = {"c-http", "c-blob", "c-declared", "c-platform", "c-limited",
    "c-local-cancel", "c-explicit-cancel", "c-deadline", "c-shutdown"};

static bool require(workflow *state, bool value, const char *reason) {
    if (!value) state->reason = reason;
    return value;
}

static bool finish(workflow *state, latent_transport *client, latent_profile_call *call, ex_result *result) {
    bool valid = ex_wait(client, result, ex_now() + 6000);
    state->api->release_call(call);
    state->last = *result;
    return valid;
}

static bool terminal(workflow *state, const char *identity, bool expected_terminal) {
    uint64_t deadline = ex_now() + 4000;
    latent_transport *client = state->clients[0];
    while (ex_now() < deadline) {
        ex_result result = {0};
        latent_profile_get_activation_request request = {ex_string(identity)};
        uint64_t current = ex_now();
        if (current >= deadline) return false;
        uint64_t remaining = deadline - current;
        latent_profile_call_options options = ex_options((uint32_t)(remaining > 500 ? 500 : remaining));
        latent_profile_call *call = state->api->get_activation(latent_transport_profile(client), &request, &options, ex_status, &result);
        bool valid = ex_wait(client, &result, deadline);
        state->api->release_call(call);
        state->last = result;
        if (!valid || result.failed || strcmp(result.identity, identity) != 0) return false;
        if (result.terminal == expected_terminal) return true;
        if (!expected_terminal) return false;
        ex_pause();
    }
    return false;
}

static bool invoke_cases(workflow *state) {
    latent_transport *client = state->clients[0];
    const char *const suffixes[] = {"http", "blob", "declared", "platform"};
    for (unsigned index = 0; index < 4; ++index) {
        ex_result result = {0};
        const char *function = index == 2 ? "fail" : index == 3 ? "spin" : NULL;
        latent_profile_call *call = ex_invoke(&state->config, client, index > 1 ? 2 : index,
                                             suffixes[index], function, false, 5000, &result);
        if (!finish(state, client, call, &result) || !require(state, !result.failed, "guest-rpc")) return false;
        bool valid = index < 2 ? ex_guest(&result, index == 0 ? 2201 : 4)
                   : index == 2 ? result.declared : result.platform;
        if (!require(state, valid && strcmp(result.identity, activations[index]) == 0, "guest-outcome")) return false;
        state->admitted[index] = true;
        state->assertions[index] = true;
    }
    for (unsigned index = 0; index < 2; ++index) {
        client = state->clients[index + 2];
        ex_result result = {0};
        latent_profile_call *call = ex_invoke(&state->config, client, 0, index == 0 ? "wrong-tenant" : "wrong-auth",
                                             NULL, index == 0, 5000, &result);
        if (!finish(state, client, call, &result)
            || !require(state, result.failed && result.has_grpc && result.grpc == (index == 0 ? 7 : 16), "authority-rejection")) return false;
        state->assertions[WRONG_TENANT + index] = true;
    }
    ex_result result = {0};
    client = state->clients[4];
    latent_profile_call *call = ex_invoke(&state->config, client, 0, "limited", NULL, false, 5000, &result);
    if (!finish(state, client, call, &result)
        || !require(state, result.failed && result.dispatched && result.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN
                     && result.category == LATENT_PROFILE_FAILURE_CATEGORY_LIMIT && strcmp(result.identity, "c-limited") == 0,
                    "response-limit-facts") || !require(state, terminal(state, "c-limited", true), "limited-retained-status")) return false;
    state->admitted[4] = true;
    state->assertions[RESPONSE_LIMIT] = true;
    return true;
}

static bool inspection(workflow *state) {
    latent_transport *owner = state->clients[0];
    latent_profile_client *client = latent_transport_profile(owner);
    latent_profile_call_options options = ex_options(5000);
    latent_profile_list_policies_request request = {.record_kind = LATENT_PROFILE_CAPABILITY_POLICY_RECORD_KIND_POLICY,
                                                    .has_page = true, .page = {.page_size = 1}};
    ex_result first = {0};
    latent_profile_call *call = state->api->list_policies(client, &request, &options, ex_policies, &first);
    if (!finish(state, owner, call, &first) || !require(state, !first.failed && first.count == 1 && first.has_cursor && first.audit_absent, "policy-first-page")) return false;
    request.page.has_page_token = true;
    request.page.page_token = (latent_string){first.cursor, first.cursor_length};
    ex_result next = {0};
    call = state->api->list_policies(client, &request, &options, ex_policies, &next);
    if (!finish(state, owner, call, &next) || !require(state, !next.failed && next.count == 1 && next.audit_absent
         && strcmp(first.first_id, next.first_id) != 0, "policy-next-page")) return false;
    request.record_kind = LATENT_PROFILE_CAPABILITY_POLICY_RECORD_KIND_PROVIDER_BINDING;
    request.page.has_page_token = false;
    next = (ex_result){0};
    call = state->api->list_policies(client, &request, &options, ex_policies, &next);
    if (!finish(state, owner, call, &next) || !require(state, !next.failed && next.count == 1 && next.audit_absent, "provider-binding-page")) return false;
    state->assertions[BOUNDED_PAGES] = true;
    latent_profile_list_capabilities_request capabilities = {.deployment_id = state->config.targets[0].route,
                                                             .has_page = true, .page = {.page_size = 1}};
    ex_result inspected = {0};
    call = state->api->list_capabilities(client, &capabilities, &options, ex_capabilities, &inspected);
    if (!finish(state, owner, call, &inspected) || !require(state, !inspected.failed && inspected.count == 1
        && strcmp(inspected.contract, "latent:http/client@0.2.0") == 0 && inspected.provider_binding[0] != 0
        && inspected.provider_policy[0] != 0, "capability-inspection")) return false;
    for (unsigned index = 0; index < 2; ++index) {
        latent_profile_get_policy_request get = {.id = ex_string(index == 0 ? inspected.provider_binding : inspected.provider_policy),
            .record_kind = index == 0 ? LATENT_PROFILE_CAPABILITY_POLICY_RECORD_KIND_PROVIDER_BINDING : LATENT_PROFILE_CAPABILITY_POLICY_RECORD_KIND_POLICY};
        ex_result result = {0};
        call = state->api->get_policy(client, &get, &options, ex_policy, &result);
        if (!finish(state, owner, call, &result) || !require(state, !result.failed && result.has_policy && result.audit_absent, "referenced-policy-inspection")) return false;
    }
    state->assertions[PROVIDER_INSPECTION] = true;
    return true;
}

static bool mutation(workflow *state) {
    latent_transport *owner = state->clients[0];
    latent_profile_client *client = latent_transport_profile(owner);
    latent_profile_call_options options = ex_options(5000);
    latent_profile_apply_policy_request request = {.operation_id = EX_TEXT("c-policy-create"),
        .has_expected_generation = true, .expected_generation = 0, .has_policy = true,
        .policy = {.id = EX_TEXT("c-example-policy"), .has_metadata = true,
            .metadata = {.name = EX_TEXT("c-example-policy"), .has_tenant = true, .tenant = state->config.tenant},
            .language = EX_TEXT("lsf-capability-policy-v1"), .record_kind = LATENT_PROFILE_CAPABILITY_POLICY_RECORD_KIND_POLICY,
            .document = state->config.policy_document}};
    ex_result created = {0};
    latent_profile_call *call = state->api->apply_policy(client, &request, &options, ex_applied, &created);
    if (!finish(state, owner, call, &created) || !require(state, !created.failed && created.has_policy && created.has_receipt
        && created.audit_absent && created.generation == created.receipt.generation
        && strcmp(created.receipt.operation_id, "c-policy-create") == 0 && created.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_OBSERVED,
        "policy-mutation-receipt")) return false;
    latent_profile_get_policy_request get = {EX_TEXT("c-example-policy"), LATENT_PROFILE_CAPABILITY_POLICY_RECORD_KIND_POLICY};
    ex_result result = {0};
    call = state->api->get_policy(client, &get, &options, ex_policy, &result);
    if (!finish(state, owner, call, &result) || !require(state, !result.failed && result.has_policy && result.audit_absent
        && result.generation == created.generation, "mutated-policy-generation")) return false;
    latent_profile_get_policy_operation_request lookup = {EX_TEXT("c-policy-create")};
    result = (ex_result){0};
    call = state->api->get_policy_operation(client, &lookup, &options, ex_operation, &result);
    if (!finish(state, owner, call, &result) || !require(state, !result.failed && result.has_receipt && result.audit_absent
        && ex_receipt_equal(&created.receipt, &result.receipt), "original-operation-recovery")) return false;
    lookup.operation_id = EX_TEXT("c-unknown-operation");
    result = (ex_result){0};
    call = state->api->get_policy_operation(client, &lookup, &options, ex_operation, &result);
    if (!finish(state, owner, call, &result) || !require(state, result.audit_absent
        && result.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN
        && ((!result.failed && !result.has_receipt) || (result.failed && result.has_grpc && result.grpc == 5)), "absent-operation-is-unknown")) return false;
    state->assertions[MUTATION_RECEIPT] = true;
    result = (ex_result){0};
    call = state->api->apply_policy(client, &request, &options, ex_applied, &result);
    if (!finish(state, owner, call, &result) || !require(state, !result.failed && result.has_receipt && result.audit_absent
        && ex_receipt_equal(&created.receipt, &result.receipt), "explicit-exact-replay")) return false;
    state->assertions[EXACT_REPLAY] = true;
    for (unsigned index = 0; index < 2; ++index) {
        latent_profile_apply_policy_request conflicting = request;
        if (index == 0) conflicting.operation_id = EX_TEXT("c-stale-precondition");
        else conflicting.expected_generation = created.generation;
        result = (ex_result){0};
        call = state->api->apply_policy(client, &conflicting, &options, ex_applied, &result);
        if (!finish(state, owner, call, &result) || !require(state, result.failed && result.audit_absent && result.has_grpc
            && (result.grpc == 9 || result.grpc == 6) && result.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_OBSERVED, "precondition-or-replay-conflict")) return false;
    }
    state->assertions[PRECONDITION_CONFLICT] = true;
    return true;
}

static bool marker(workflow *state, latent_transport *owner, const char *prefix, const char *token, ex_result *pending) {
    uint64_t deadline = ex_now() + 4000;
    while (ex_now() < deadline) {
        if (ex_marker(&state->config, prefix, token)) return true;
        if (pending != NULL && pending->callbacks != 0) return false;
        if (owner != NULL && !latent_transport_poll(owner, 2)) return false;
        ex_pause();
    }
    return false;
}

static bool held(workflow *state, unsigned kind) {
    const char *const suffixes[] = {"local-cancel", "explicit-cancel", "deadline", "shutdown"};
    const char *suffix = suffixes[kind];
    char token[64];
    (void)snprintf(token, sizeof(token), "hold-c-%s", suffix);
    state->stage = suffix;
    latent_transport *owner = state->clients[1];
    if (!require(state, ex_mode(&state->config, token), "rendezvous-mode")) return false;
    ex_result pending = {0};
    latent_profile_call *call = ex_invoke(&state->config, owner, 0, suffix, NULL, false, kind == 2 ? 500 : 3000, &pending);
    bool passed = false;
    if (call == NULL || !require(state, marker(state, owner, "started", token, &pending), "provider-not-started")) goto cleanup;
    state->admitted[kind + 5] = true;
    if (!require(state, terminal(state, activations[kind + 5], false), "pending-status")) goto cleanup;
    if (kind == 0 || kind == 1) {
        if (kind == 0) {
            state->api->cancel_local(call);
            if (!require(state, pending.callbacks == 1 && pending.failed && pending.category == LATENT_PROFILE_FAILURE_CATEGORY_LOCAL_CANCELLED,
                         "local-cancellation-facts")) goto cleanup;
        }
        ex_result cancelled = {0};
        latent_profile_cancel_request request = {ex_string(activations[kind + 5]), EX_TEXT("explicit C workflow cancellation")};
        latent_profile_call_options options = ex_options(5000);
        latent_profile_call *cancellation = state->api->cancel(latent_transport_profile(owner), &request, &options, ex_cancelled, &cancelled);
        if (!finish(state, owner, cancellation, &cancelled) || !require(state, !cancelled.failed
            && (cancelled.disposition == LATENT_PROFILE_CANCEL_DISPOSITION_ACCEPTED
                 || (kind == 0 && cancelled.disposition == LATENT_PROFILE_CANCEL_DISPOSITION_ALREADY_TERMINAL)), "explicit-cancel-disposition")) goto cleanup;
        if (kind == 1 && (!ex_wait(owner, &pending, ex_now() + 4000)
            || !require(state, (!pending.failed && pending.platform && strcmp(pending.platform_code, "cancelled") == 0)
                        || (pending.failed && pending.has_grpc && (pending.grpc == 1 || pending.grpc == 4)), "cancelled-invocation-outcome"))) goto cleanup;
    } else if (kind == 2) {
        if (!ex_wait(owner, &pending, ex_now() + 1000) || !require(state, pending.failed
            && pending.category == LATENT_PROFILE_FAILURE_CATEGORY_DEADLINE && strcmp(pending.identity, "c-deadline") == 0,
            "absolute-deadline-facts")) goto cleanup;
    } else {
        if (!require(state, latent_transport_shutdown(owner, 1000) && pending.callbacks == 1 && pending.failed
            && pending.category == LATENT_PROFILE_FAILURE_CATEGORY_LOCAL_CANCELLED, "outstanding-shutdown")) goto cleanup;
        latent_transport_usage usage = latent_transport_get_usage(owner);
        if (!require(state, usage.sockets == 0 && usage.sessions == 0 && usage.http2_bytes == 0
            && usage.in_flight == 0 && usage.queued == 0 && usage.callbacks_pending == 0, "physical-client-owner-retirement")) goto cleanup;
    }
    if (!require(state, marker(state, NULL, "closed", token, NULL), "provider-not-physically-closed")
        || !require(state, terminal(state, activations[kind + 5], true), "retained-terminal-status")) goto cleanup;
    state->assertions[kind == 0 ? LOCAL_CANCELLATION : kind == 1 ? EXPLICIT_CANCELLATION : kind == 2 ? ABSOLUTE_DEADLINE : SHUTDOWN_OUTSTANDING] = true;
    if (kind == 0) state->assertions[LOST_RESPONSE_STATUS] = true;
    passed = true;
cleanup:
    if (call != NULL && pending.callbacks == 0) state->api->cancel_local(call);
    state->api->release_call(call);
    if (!ex_mode(&state->config, "reply")) passed = false;
    if (!passed && pending.failed) state->last = pending;
    return passed;
}

int main(int argc, char **argv) {
    workflow state = {.stage = "configuration", .reason = "private-input", .api = latent_transport_profile_vtable()};
    bool passed = ex_config_load(&state.config, argc, argv);
    if (passed) {
        for (unsigned index = 0; index < 5; ++index) {
            state.clients[index] = ex_client(&state.config, index == 2, index == 3, index == 4);
            if (state.clients[index] == NULL) passed = false;
        }
    }
    if (passed) { state.stage = "invocation"; passed = invoke_cases(&state); }
    if (passed) { state.stage = "inspection"; passed = inspection(&state); }
    if (passed) { state.stage = "mutation"; passed = mutation(&state); }
    for (unsigned index = 0; passed && index < 4; ++index) passed = held(&state, index);
    bool closed = true;
    for (unsigned index = 0; index < 5; ++index) if (!ex_close(&state.clients[index])) closed = false;
    state.assertions[CLIENT_OWNERS_REAPED] = closed;
    ex_config_close(&state.config);
    for (unsigned index = 0; index < CHECK_COUNT; ++index) if (!state.assertions[index]) passed = false;
    if (!passed) {
        fprintf(stderr, "{\"stage\":\"%s\",\"reason\":\"%s\",\"category\":%d,\"grpcStatus\":%d}\n",
                state.stage, state.reason, state.last.category, state.last.has_grpc ? state.last.grpc : 0);
        return 1;
    }
    fputs("{\"schemaVersion\":\"latent.sdk.provider.workflow.result.v1\",\"language\":\"c\",\"assertions\":{", stdout);
    for (unsigned index = 0; index < CHECK_COUNT; ++index) printf("%s\"%s\":true", index == 0 ? "" : ",", names[index]);
    fputs("},\"activationIds\":[", stdout);
    bool first = true;
    for (unsigned index = 0; index < 9; ++index) {
        if (state.admitted[index]) { printf("%s\"%s\"", first ? "" : ",", activations[index]); first = false; }
    }
    puts("],\"operationId\":\"c-policy-create\",\"auditAttempt\":null,\"transport\":\"numeric-loopback-http2-protobuf-v1\"}");
    return 0;
}
