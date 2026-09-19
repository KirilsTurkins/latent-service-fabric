#ifndef LATENT_PROFILE_LIFETIME_FIXTURE_H
#define LATENT_PROFILE_LIFETIME_FIXTURE_H

#include "latent/profile.h"
#include <assert.h>
#include <string.h>

#define LIFETIME_TEXT(value) ((latent_string){(value), sizeof(value) - 1u})

struct latent_profile_call {
    latent_profile_client *client;
    bool completed;
    bool released;
    latent_profile_apply_policy_callback callback;
    void *user_data;
};

struct latent_profile_client {
    latent_profile_call call;
    unsigned writes;
    unsigned cancels;
    unsigned pages;
    bool destroyed;
    bool has_receipt;
    char operation[64];
    char policy[64];
    latent_profile_capability_policy_operation receipt;
};

typedef struct profile_observation {
    unsigned calls;
    bool failed;
    bool dispatched;
    bool has_receipt;
    bool has_audit;
    int32_t outcome;
    int32_t disposition;
    uint64_t generation;
    char identity[64];
    char phase[64];
    uint8_t payload[16];
    size_t payload_length;
} profile_observation;

static void fixture_profile_copy(char destination[64], latent_string source) {
    assert(source.length < 64);
    if (source.length != 0) memcpy(destination, source.data, source.length);
    destination[source.length] = '\0';
}

static latent_profile_call *fixture_profile_begin(latent_profile_client *client) {
    assert(client->call.released && !client->destroyed);
    client->call = (latent_profile_call){.client = client};
    return &client->call;
}

static latent_profile_call *fixture_profile_invoke(latent_profile_client *client,
    const latent_profile_invoke_request *request, const latent_profile_call_options *options,
    latent_profile_invoke_callback callback, void *user_data) {
    (void)options;
    latent_profile_call *call = fixture_profile_begin(client);
    latent_profile_invoke_result result = {.value = {.activation_id = request->activation_id,
        .has_success = true, .success = {.payload = request->payload}}};
    callback(&result, NULL, user_data);
    call->completed = true;
    return call;
}

static latent_profile_call *fixture_profile_cancel(latent_profile_client *client,
    const latent_profile_cancel_request *request, const latent_profile_call_options *options,
    latent_profile_cancel_callback callback, void *user_data) {
    (void)request;
    (void)options;
    latent_profile_call *call = fixture_profile_begin(client);
    client->cancels++;
    latent_profile_cancel_result result = {.value = {.disposition = LATENT_PROFILE_CANCEL_DISPOSITION_ACCEPTED}};
    callback(&result, NULL, user_data);
    call->completed = true;
    return call;
}

static latent_profile_call *fixture_profile_status(latent_profile_client *client,
    const latent_profile_get_activation_request *request, const latent_profile_call_options *options,
    latent_profile_get_activation_callback callback, void *user_data) {
    (void)options;
    latent_profile_call *call = fixture_profile_begin(client);
    latent_profile_get_activation_result result = {.value = {.activation_id = request->activation_id, .phase = LIFETIME_TEXT("running")}};
    callback(&result, NULL, user_data);
    call->completed = true;
    return call;
}

static latent_profile_call *fixture_profile_policy(latent_profile_client *client,
    const latent_profile_get_policy_request *request, const latent_profile_call_options *options,
    latent_profile_get_policy_callback callback, void *user_data) {
    (void)options;
    latent_profile_call *call = fixture_profile_begin(client);
    latent_profile_get_policy_result result = {.value = {.has_policy = true, .policy = {.id = request->id, .record_kind = request->record_kind}}};
    callback(&result, NULL, user_data);
    call->completed = true;
    return call;
}

static latent_profile_call *fixture_profile_policies(latent_profile_client *client,
    const latent_profile_list_policies_request *request, const latent_profile_call_options *options,
    latent_profile_list_policies_callback callback, void *user_data) {
    (void)options;
    assert(request->has_page && request->page.page_size == 1);
    latent_profile_call *call = fixture_profile_begin(client);
    client->pages++;
    latent_profile_list_policies_result result = {.value = {.catalog_generation = UINT64_MAX,
        .has_page = true, .page = {.has_next_page_token = true, .next_page_token = LIFETIME_TEXT("opaque-next-page")}}};
    callback(&result, NULL, user_data);
    call->completed = true;
    return call;
}

static latent_profile_call *fixture_profile_capabilities(latent_profile_client *client,
    const latent_profile_list_capabilities_request *request, const latent_profile_call_options *options,
    latent_profile_list_capabilities_callback callback, void *user_data) {
    (void)options;
    latent_profile_call *call = fixture_profile_begin(client);
    latent_profile_list_capabilities_result result = {.value = {.has_revision = true, .revision = {.deployment_id = request->deployment_id}}};
    callback(&result, NULL, user_data);
    call->completed = true;
    return call;
}

static latent_profile_call *fixture_profile_apply(latent_profile_client *client,
    const latent_profile_apply_policy_request *request, const latent_profile_call_options *options,
    latent_profile_apply_policy_callback callback, void *user_data) {
    latent_profile_call *call = fixture_profile_begin(client);
    if (options != NULL && options->has_timeout_millis && options->timeout_millis == 0) {
        latent_profile_client_failure failure = {.category = LATENT_PROFILE_FAILURE_CATEGORY_DEADLINE,
            .outcome = LATENT_PROFILE_OUTCOME_KNOWLEDGE_NOT_DISPATCHED,
            .identity = {.has_operation_id = true, .operation_id = request->operation_id}};
        callback(NULL, &failure, user_data);
        call->completed = true;
        return call;
    }
    assert(request->has_expected_generation && request->expected_generation == 0);
    assert(request->operation_id.length != 0 && request->has_policy);
    if (client->has_receipt) {
        latent_profile_apply_policy_result result = {.value = {.has_receipt = true, .receipt = client->receipt},
            .metadata = {.outcome = LATENT_PROFILE_OUTCOME_KNOWLEDGE_OBSERVED}};
        callback(&result, NULL, user_data);
        call->completed = true;
        return call;
    }
    fixture_profile_copy(client->operation, request->operation_id);
    fixture_profile_copy(client->policy, request->policy.id);
    client->receipt = (latent_profile_capability_policy_operation){
        .operation_id = {.data = client->operation, .length = request->operation_id.length},
        .id = {.data = client->policy, .length = request->policy.id.length},
        .tenant = LIFETIME_TEXT("tenant-a"), .record_kind = request->policy.record_kind, .generation = UINT64_MAX};
    client->has_receipt = true;
    client->writes++;
    call->callback = callback;
    call->user_data = user_data;
    return call;
}

static latent_profile_call *fixture_profile_recover(latent_profile_client *client,
    const latent_profile_get_policy_operation_request *request, const latent_profile_call_options *options,
    latent_profile_get_policy_operation_callback callback, void *user_data) {
    (void)options;
    latent_profile_call *call = fixture_profile_begin(client);
    bool found = client->has_receipt && request->operation_id.length == client->receipt.operation_id.length
        && memcmp(request->operation_id.data, client->operation, request->operation_id.length) == 0;
    latent_profile_get_policy_operation_result result = {.value = {.has_receipt = found},
        .metadata = {.outcome = found ? LATENT_PROFILE_OUTCOME_KNOWLEDGE_OBSERVED : LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN}};
    if (found) result.value.receipt = client->receipt;
    callback(&result, NULL, user_data);
    call->completed = true;
    return call;
}

static void fixture_profile_cancel_local(latent_profile_call *call) {
    assert(!call->released);
    if (call->completed) return;
    latent_profile_client_failure failure = {.category = LATENT_PROFILE_FAILURE_CATEGORY_LOCAL_CANCELLED,
        .dispatched = true, .outcome = LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN,
        .identity = {.has_operation_id = true, .operation_id = call->client->receipt.operation_id}};
    call->callback(NULL, &failure, call->user_data);
    call->completed = true;
}

static void fixture_profile_release(latent_profile_call *call) {
    assert(call->completed && !call->released);
    call->released = true;
}

static void fixture_profile_destroy(latent_profile_client *client) {
    assert(client->call.released);
    client->destroyed = true;
}

static const latent_profile_client_vtable fixture_profile_vtable = {
    .invoke = fixture_profile_invoke, .cancel = fixture_profile_cancel, .get_activation = fixture_profile_status,
    .get_policy = fixture_profile_policy, .list_policies = fixture_profile_policies,
    .list_capabilities = fixture_profile_capabilities, .apply_policy = fixture_profile_apply,
    .get_policy_operation = fixture_profile_recover, .cancel_local = fixture_profile_cancel_local,
    .release_call = fixture_profile_release, .destroy = fixture_profile_destroy
};

static void profile_observe_apply(const latent_profile_apply_policy_result *result, const latent_profile_client_failure *failure, void *user_data) {
    profile_observation *observed = user_data;
    assert((result != NULL) != (failure != NULL));
    observed->calls++;
    observed->failed = failure != NULL;
    if (failure != NULL) {
        observed->dispatched = failure->dispatched;
        observed->outcome = failure->outcome;
        assert(failure->identity.has_operation_id);
        fixture_profile_copy(observed->identity, failure->identity.operation_id);
    } else {
        observed->has_receipt = result->value.has_receipt;
        observed->generation = result->value.receipt.generation;
        fixture_profile_copy(observed->identity, result->value.receipt.operation_id);
    }
}

static void profile_observe_recovery(const latent_profile_get_policy_operation_result *result, const latent_profile_client_failure *failure, void *user_data) {
    profile_observation *observed = user_data;
    assert(result != NULL && failure == NULL);
    observed->calls++;
    observed->has_receipt = result->value.has_receipt;
    observed->outcome = result->metadata.outcome;
    observed->has_audit = result->metadata.has_audit_ack;
    if (result->value.has_receipt) {
        observed->generation = result->value.receipt.generation;
        fixture_profile_copy(observed->identity, result->value.receipt.operation_id);
    }
}

static void profile_observe_invocation(const latent_profile_invoke_result *result, const latent_profile_client_failure *failure, void *user_data) {
    profile_observation *observed = user_data;
    assert(result != NULL && failure == NULL && result->value.has_success);
    observed->calls++;
    observed->payload_length = result->value.success.payload.length;
    assert(observed->payload_length <= sizeof(observed->payload));
    if (observed->payload_length != 0) memcpy(observed->payload, result->value.success.payload.data, observed->payload_length);
}

static void profile_observe_cancel(const latent_profile_cancel_result *result, const latent_profile_client_failure *failure, void *user_data) {
    profile_observation *observed = user_data;
    assert(result != NULL && failure == NULL);
    observed->calls++;
    observed->disposition = result->value.disposition;
}

static void profile_observe_status(const latent_profile_get_activation_result *result, const latent_profile_client_failure *failure, void *user_data) {
    profile_observation *observed = user_data;
    assert(result != NULL && failure == NULL);
    observed->calls++;
    fixture_profile_copy(observed->phase, result->value.phase);
}

static void profile_observe_policy(const latent_profile_get_policy_result *result, const latent_profile_client_failure *failure, void *user_data) {
    profile_observation *observed = user_data;
    assert(result != NULL && failure == NULL && result->value.has_policy);
    observed->calls++;
    fixture_profile_copy(observed->identity, result->value.policy.id);
}

static void profile_observe_page(const latent_profile_list_policies_result *result, const latent_profile_client_failure *failure, void *user_data) {
    profile_observation *observed = user_data;
    assert(result != NULL && failure == NULL && result->value.has_page && result->value.page.has_next_page_token);
    observed->calls++;
    fixture_profile_copy(observed->identity, result->value.page.next_page_token);
}

static void profile_observe_capabilities(const latent_profile_list_capabilities_result *result, const latent_profile_client_failure *failure, void *user_data) {
    profile_observation *observed = user_data;
    assert(result != NULL && failure == NULL && result->value.has_revision);
    observed->calls++;
    fixture_profile_copy(observed->identity, result->value.revision.deployment_id);
}

static void profile_lifetime(void) {
    latent_profile_client client = {.call = {.released = true}};
    const latent_profile_client_vtable *profile = &fixture_profile_vtable;
    char operation[] = "operation-a";
    char policy_id[] = "policy-a";
    latent_profile_apply_policy_request request = {.has_expected_generation = true, .expected_generation = 0,
        .operation_id = {.data = operation, .length = sizeof(operation) - 1}, .has_policy = true,
        .policy = {.id = {.data = policy_id, .length = sizeof(policy_id) - 1}, .record_kind = LATENT_PROFILE_CAPABILITY_POLICY_RECORD_KIND_POLICY}};
    profile_observation pending = {0};
    latent_profile_call *call = profile->apply_policy(&client, &request, NULL, profile_observe_apply, &pending);
    assert(client.writes == 1 && pending.calls == 0 && !call->completed);
    memset(operation, 'x', sizeof(operation) - 1);
    memset(policy_id, 'x', sizeof(policy_id) - 1);
    profile->cancel_local(call);
    profile->cancel_local(call);
    assert(pending.calls == 1 && pending.failed && pending.dispatched && pending.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN);
    assert(strcmp(pending.identity, "operation-a") == 0 && client.writes == 1 && client.cancels == 0);
    profile->release_call(call);

    latent_profile_get_policy_operation_request lookup = {.operation_id = LIFETIME_TEXT("operation-a")};
    profile_observation recovered = {0};
    call = profile->get_policy_operation(&client, &lookup, NULL, profile_observe_recovery, &recovered);
    assert(call->completed && recovered.calls == 1 && recovered.has_receipt && recovered.generation == UINT64_MAX && !recovered.has_audit);
    profile->release_call(call);
    lookup.operation_id = LIFETIME_TEXT("not-retained");
    profile_observation unknown = {0};
    call = profile->get_policy_operation(&client, &lookup, NULL, profile_observe_recovery, &unknown);
    assert(!unknown.has_receipt && unknown.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN);
    profile->release_call(call);

    request.operation_id = LIFETIME_TEXT("operation-a");
    request.policy.id = LIFETIME_TEXT("policy-a");
    profile_observation replayed = {0};
    call = profile->apply_policy(&client, &request, NULL, profile_observe_apply, &replayed);
    assert(replayed.calls == 1 && replayed.generation == UINT64_MAX && client.writes == 1);
    profile->release_call(call);
    latent_profile_call_options expired = {.has_timeout_millis = true, .timeout_millis = 0};
    profile_observation timeout = {0};
    call = profile->apply_policy(&client, &request, &expired, profile_observe_apply, &timeout);
    assert(timeout.failed && !timeout.dispatched && timeout.outcome == LATENT_PROFILE_OUTCOME_KNOWLEDGE_NOT_DISPATCHED);
    profile->release_call(call);

    uint8_t payload[] = {1, 2};
    latent_profile_invoke_request invocation = {.has_activation_id = true, .activation_id = LIFETIME_TEXT("activation-a"), .payload = {.data = payload, .length = sizeof(payload)}};
    profile_observation invoked = {0};
    call = profile->invoke(&client, &invocation, NULL, profile_observe_invocation, &invoked);
    assert(call->completed && invoked.calls == 1);
    payload[0] = 99;
    assert(invoked.payload[0] == 1);
    profile->release_call(call);
    latent_profile_cancel_request cancel = {.activation_id = LIFETIME_TEXT("activation-a")};
    profile_observation cancelled = {0};
    call = profile->cancel(&client, &cancel, NULL, profile_observe_cancel, &cancelled);
    assert(cancelled.disposition == LATENT_PROFILE_CANCEL_DISPOSITION_ACCEPTED);
    profile->release_call(call);
    latent_profile_get_activation_request status = {.activation_id = LIFETIME_TEXT("activation-a")};
    profile_observation running = {0};
    call = profile->get_activation(&client, &status, NULL, profile_observe_status, &running);
    assert(strcmp(running.phase, "running") == 0);
    profile->release_call(call);
    latent_profile_get_policy_request get = {.id = LIFETIME_TEXT("policy-a"), .record_kind = LATENT_PROFILE_CAPABILITY_POLICY_RECORD_KIND_POLICY};
    profile_observation policy = {0};
    call = profile->get_policy(&client, &get, NULL, profile_observe_policy, &policy);
    assert(strcmp(policy.identity, "policy-a") == 0);
    profile->release_call(call);
    latent_profile_list_policies_request list = {.record_kind = LATENT_PROFILE_CAPABILITY_POLICY_RECORD_KIND_POLICY, .has_page = true, .page = {.page_size = 1}};
    profile_observation page = {0};
    call = profile->list_policies(&client, &list, NULL, profile_observe_page, &page);
    assert(client.pages == 1 && strcmp(page.identity, "opaque-next-page") == 0);
    profile->release_call(call);
    latent_profile_list_capabilities_request capabilities = {.deployment_id = LIFETIME_TEXT("deployment-a")};
    profile_observation selected = {0};
    call = profile->list_capabilities(&client, &capabilities, NULL, profile_observe_capabilities, &selected);
    assert(strcmp(selected.identity, "deployment-a") == 0);
    profile->release_call(call);
    memset(client.operation, 'x', sizeof(client.operation));
    assert(strcmp(recovered.identity, "operation-a") == 0);
    profile->destroy(&client);
    assert(client.destroyed);
}

#undef LIFETIME_TEXT
#endif
