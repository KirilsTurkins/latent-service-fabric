/* C11 semantic contract fixture. No transport, background work, or retry policy. */
#include "latent/latent.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

#define TEXT(value) ((latent_string){(value), sizeof(value) - 1u})
#define CAPACITY 128u

typedef struct copied_string {
    char bytes[CAPACITY];
    size_t length;
} copied_string;

typedef struct copied_identity {
    bool present;
    copied_string value;
} copied_identity;

struct latent_invocation {
    unsigned operation_number;
};

struct latent_client {
    const latent_client_vtable *vtable;
    latent_invocation operation;
    unsigned invoke_count;
    unsigned status_count;
    bool pending;
    bool terminal;
    bool cancellation_requested;
    copied_identity supplied_activation;
    copied_identity supplied_root;
    copied_identity supplied_parent;
    copied_string activation_id;
    latent_invoke_callback invoke_callback;
    void *invoke_user_data;
    bool cancel_pending;
    bool cancel_transport_failure;
    copied_string cancel_id;
    copied_string cancel_reason;
    latent_cancel_callback cancel_callback;
    void *cancel_user_data;
};

typedef struct observed_call {
    latent_client *client;
    latent_invocation *expected_operation;
    bool operation_matched;
    unsigned calls;
    bool transport_failure;
    copied_string activation_id;
    copied_string phase;
    copied_string terminal_state;
    copied_string failure_message;
    latent_cancel_disposition disposition;
    bool has_terminal_state;
    bool has_terminal_outcome;
    latent_invocation_outcome_kind outcome;
} observed_call;

static void copy_string(copied_string *destination, latent_string source) {
    assert(source.length < CAPACITY);
    assert(source.data != NULL || source.length == 0u);
    if (source.length != 0u) {
        memcpy(destination->bytes, source.data, source.length);
    }
    destination->bytes[source.length] = '\0';
    destination->length = source.length;
}

static latent_string view(const copied_string *value) {
    return (latent_string){value->bytes, value->length};
}

static bool equal(latent_string left, latent_string right) {
    return left.length == right.length &&
           (left.length == 0u || memcmp(left.data, right.data, left.length) == 0);
}

static void assert_text(const copied_string *actual, latent_string expected) {
    assert(equal(view(actual), expected));
}

static void copy_identity(copied_identity *destination, bool present, latent_string value) {
    destination->present = present;
    copy_string(&destination->value, value);
}

static latent_invocation *fake_invoke(
    latent_client *client,
    const latent_invoke_request *request,
    latent_invoke_callback callback,
    void *user_data) {
    assert(!client->pending);
    assert(callback != NULL);
    client->invoke_count += 1u;
    client->operation.operation_number = client->invoke_count;
    client->pending = true;
    client->terminal = false;
    client->cancellation_requested = false;
    client->invoke_callback = callback;
    client->invoke_user_data = user_data;
    /* Copy precisely the request fields this fake retains beyond call return. */
    copy_identity(&client->supplied_activation, request->has_activation_id, request->activation_id);
    copy_identity(&client->supplied_root, request->has_root_activation_id, request->root_activation_id);
    copy_identity(&client->supplied_parent, request->has_parent_activation_id, request->parent_activation_id);
    copy_string(&client->activation_id,
                request->has_activation_id ? request->activation_id : TEXT("server-assigned"));
    return &client->operation;
}

static void fake_cancel(
    latent_client *client,
    latent_string activation_id,
    latent_string reason,
    latent_cancel_callback callback,
    void *user_data) {
    assert(!client->cancel_pending);
    assert(callback != NULL);
    client->cancel_pending = true;
    copy_string(&client->cancel_id, activation_id);
    copy_string(&client->cancel_reason, reason);
    client->cancel_callback = callback;
    client->cancel_user_data = user_data;
}

static void finish_cancel(latent_client *client) {
    latent_cancel_response response = {0};
    latent_transport_error failure = {TEXT("cancel transport unavailable"), true};
    latent_cancel_callback callback = client->cancel_callback;
    void *user_data = client->cancel_user_data;
    assert(client->cancel_pending);
    client->cancel_pending = false;
    client->cancel_callback = NULL;
    client->cancel_user_data = NULL;
    if (client->cancel_transport_failure) {
        client->cancel_transport_failure = false;
        callback(client, NULL, &failure, user_data);
        return;
    }
    if (client->invoke_count == 0u || !equal(view(&client->cancel_id), view(&client->activation_id))) {
        response.disposition = LATENT_CANCEL_NOT_FOUND;
    } else if (client->terminal) {
        response.disposition = LATENT_CANCEL_ALREADY_TERMINAL;
        response.has_terminal_state = true;
        response.terminal_state = client->cancellation_requested ? TEXT("cancelled") : TEXT("completed");
    } else {
        response.disposition = LATENT_CANCEL_ACCEPTED;
        client->cancellation_requested = true;
    }
    callback(client, &response, NULL, user_data);
}

static void fake_get_activation(
    latent_client *client,
    latent_string activation_id,
    latent_get_activation_callback callback,
    void *user_data) {
    latent_activation_status status = {0};
    latent_activation_success_summary success = {0};
    latent_platform_error cancelled = {0};
    assert(equal(activation_id, view(&client->activation_id)));
    client->status_count += 1u;
    status.activation_id = view(&client->activation_id);
    status.phase = client->terminal && !client->cancellation_requested ? TEXT("committed") : TEXT("running");
    status.has_terminal_state = client->terminal;
    status.has_terminal_outcome = client->terminal;
    status.has_final_consumption = client->terminal;
    status.has_terminal_at_unix_millis = client->terminal;
    status.last_updated_unix_millis = 42u;
    status.terminal_at_unix_millis = 42u;
    if (client->terminal) {
        if (client->cancellation_requested) {
            status.terminal_state = TEXT("cancelled");
            cancelled.code = TEXT("cancelled");
            cancelled.message = TEXT("activation cancelled");
            status.terminal_outcome.kind = LATENT_RETAINED_INVOCATION_PLATFORM_FAILURE;
            status.terminal_outcome.platform_failure = &cancelled;
        } else {
            status.terminal_state = TEXT("completed");
            status.terminal_outcome.kind = LATENT_RETAINED_INVOCATION_SUCCEEDED;
            status.terminal_outcome.success = &success;
        }
    }
    callback(client, &status, NULL, user_data);
}

static void fake_destroy(latent_client *client) {
    assert(!client->pending);
    assert(!client->cancel_pending);
}

static const latent_client_vtable fake_vtable = {
    .invoke = fake_invoke,
    .cancel = fake_cancel,
    .get_activation = fake_get_activation,
    .destroy = fake_destroy,
};

static latent_client new_client(void) {
    latent_client client = {0};
    client.vtable = &fake_vtable;
    return client;
}

static void observe_invoke(
    latent_invocation *invocation,
    const latent_invocation_outcome *outcome,
    const latent_transport_error *transport_error,
    void *user_data) {
    observed_call *observed = user_data;
    assert((outcome != NULL) != (transport_error != NULL));
    observed->calls += 1u;
    assert(invocation == observed->expected_operation);
    observed->operation_matched = true;
    observed->expected_operation = NULL;
    observed->transport_failure = transport_error != NULL;
    if (transport_error != NULL) {
        copy_string(&observed->failure_message, transport_error->message);
    } else {
        observed->outcome = outcome->kind;
        if (outcome->kind == LATENT_INVOCATION_SUCCEEDED) {
            assert(outcome->success != NULL);
            assert(outcome->declared_error == NULL && outcome->platform_failure == NULL);
            copy_string(&observed->activation_id, outcome->success->activation_id);
        } else {
            assert(outcome->kind == LATENT_INVOCATION_PLATFORM_FAILURE);
            assert(outcome->platform_failure != NULL);
            assert(outcome->success == NULL && outcome->declared_error == NULL);
            copy_string(&observed->activation_id, outcome->platform_failure->receipt.activation_id);
        }
    }
}

static void observe_cancel(
    latent_client *client,
    const latent_cancel_response *response,
    const latent_transport_error *transport_error,
    void *user_data) {
    observed_call *observed = user_data;
    assert(client == observed->client);
    assert((response != NULL) != (transport_error != NULL));
    observed->calls += 1u;
    observed->transport_failure = transport_error != NULL;
    if (transport_error != NULL) {
        observed->disposition = (latent_cancel_disposition)0;
        observed->has_terminal_state = false;
        copy_string(&observed->failure_message, transport_error->message);
    } else {
        observed->disposition = response->disposition;
        observed->has_terminal_state = response->has_terminal_state;
        if (response->has_terminal_state) {
            copy_string(&observed->terminal_state, response->terminal_state);
        }
    }
}

static void observe_status(
    latent_client *client,
    const latent_activation_status *status,
    const latent_transport_error *transport_error,
    void *user_data) {
    observed_call *observed = user_data;
    assert(client == observed->client);
    assert(status != NULL && transport_error == NULL);
    observed->calls += 1u;
    copy_string(&observed->activation_id, status->activation_id);
    copy_string(&observed->phase, status->phase);
    observed->has_terminal_state = status->has_terminal_state;
    observed->has_terminal_outcome = status->has_terminal_outcome;
    if (status->has_terminal_state) {
        assert(status->has_terminal_outcome && status->has_final_consumption);
        copy_string(&observed->terminal_state, status->terminal_state);
    }
}

static void finish_invoke(latent_client *client, bool lose_response) {
    latent_invocation_outcome outcome = {0};
    latent_invoke_response success = {0};
    latent_platform_invocation_failure cancelled = {0};
    latent_transport_error failure = {TEXT("invoke response lost"), true};
    latent_invoke_callback callback = client->invoke_callback;
    void *user_data = client->invoke_user_data;
    assert(client->pending);
    client->pending = false;
    client->terminal = true;
    client->invoke_callback = NULL;
    client->invoke_user_data = NULL;
    if (lose_response) {
        callback(&client->operation, NULL, &failure, user_data);
        return;
    }
    if (client->cancellation_requested) {
        outcome.kind = LATENT_INVOCATION_PLATFORM_FAILURE;
        cancelled.receipt.activation_id = view(&client->activation_id);
        cancelled.error.code = TEXT("cancelled");
        cancelled.error.message = TEXT("activation cancelled");
        outcome.platform_failure = &cancelled;
    } else {
        outcome.kind = LATENT_INVOCATION_SUCCEEDED;
        success.activation_id = view(&client->activation_id);
        outcome.success = &success;
    }
    callback(&client->operation, &outcome, NULL, user_data);
}

static void pending_identity_supports_status_and_all_cancel_results(void) {
    latent_client client = new_client();
    observed_call invoked = {0};
    observed_call status = {.client = &client};
    observed_call cancelled = {.client = &client};
    latent_invoke_request request = {0};
    char activation[] = "caller-known";
    char root[] = "lineage-root";
    char parent[] = "lineage-parent";
    char cancel_id[] = "caller-known";
    char reason[] = "stop please";
    request.has_activation_id = true;
    request.activation_id = (latent_string){activation, sizeof(activation) - 1u};
    request.has_root_activation_id = true;
    request.root_activation_id = (latent_string){root, sizeof(root) - 1u};
    request.has_parent_activation_id = true;
    request.parent_activation_id = (latent_string){parent, sizeof(parent) - 1u};
    invoked.expected_operation = client.vtable->invoke(&client, &request, observe_invoke, &invoked);
    assert(invoked.expected_operation != NULL && invoked.calls == 0u);
    memset(activation, 'x', sizeof(activation) - 1u);
    memset(root, 'x', sizeof(root) - 1u);
    memset(parent, 'x', sizeof(parent) - 1u);
    assert(client.supplied_activation.present && client.supplied_root.present && client.supplied_parent.present);
    assert_text(&client.supplied_activation.value, TEXT("caller-known"));
    assert_text(&client.supplied_root.value, TEXT("lineage-root"));
    assert_text(&client.supplied_parent.value, TEXT("lineage-parent"));
    client.vtable->get_activation(&client, TEXT("caller-known"), observe_status, &status);
    assert(status.calls == 1u && !status.has_terminal_state && !status.has_terminal_outcome);
    assert_text(&status.phase, TEXT("running"));
    client.vtable->cancel(&client,
                         (latent_string){cancel_id, sizeof(cancel_id) - 1u},
                         (latent_string){reason, sizeof(reason) - 1u}, observe_cancel, &cancelled);
    assert(cancelled.calls == 0u && invoked.calls == 0u);
    memset(cancel_id, 'x', sizeof(cancel_id) - 1u);
    memset(reason, 'x', sizeof(reason) - 1u);
    assert_text(&client.cancel_id, TEXT("caller-known"));
    assert_text(&client.cancel_reason, TEXT("stop please"));
    finish_cancel(&client);
    assert(cancelled.calls == 1u && cancelled.disposition == LATENT_CANCEL_ACCEPTED);
    assert(!cancelled.transport_failure && !cancelled.has_terminal_state);
    assert(invoked.calls == 0u); /* Accepted cancellation is not a terminal response. */
    finish_invoke(&client, false);
    assert(invoked.calls == 1u && invoked.operation_matched && invoked.expected_operation == NULL);
    assert(invoked.outcome == LATENT_INVOCATION_PLATFORM_FAILURE);
    assert_text(&invoked.activation_id, TEXT("caller-known"));
    client.vtable->cancel(&client, TEXT("caller-known"), TEXT("again"), observe_cancel, &cancelled);
    finish_cancel(&client);
    assert(cancelled.calls == 2u && cancelled.disposition == LATENT_CANCEL_ALREADY_TERMINAL);
    assert(cancelled.has_terminal_state && !cancelled.transport_failure);
    assert_text(&cancelled.terminal_state, TEXT("cancelled"));
    client.vtable->cancel(&client, TEXT("unknown"), TEXT("stop"), observe_cancel, &cancelled);
    finish_cancel(&client);
    assert(cancelled.calls == 3u && cancelled.disposition == LATENT_CANCEL_NOT_FOUND);
    assert(!cancelled.has_terminal_state && !cancelled.transport_failure);
    client.cancel_transport_failure = true;
    client.vtable->cancel(&client, TEXT("caller-known"), TEXT("stop"), observe_cancel, &cancelled);
    finish_cancel(&client);
    assert(cancelled.calls == 4u && cancelled.transport_failure);
    assert(cancelled.disposition == (latent_cancel_disposition)0 && !cancelled.has_terminal_state);
    assert_text(&cancelled.failure_message, TEXT("cancel transport unavailable"));
    assert(client.invoke_count == 1u && invoked.calls == 1u);
    client.vtable->destroy(&client);
}

static void lost_response_can_be_recovered_by_id_without_reinvoking(void) {
    latent_client client = new_client();
    observed_call invoked = {0};
    observed_call status = {.client = &client};
    latent_invoke_request request = {0};
    request.has_activation_id = true;
    request.activation_id = TEXT("recover-known");
    invoked.expected_operation = client.vtable->invoke(&client, &request, observe_invoke, &invoked);
    assert(invoked.calls == 0u);
    finish_invoke(&client, true);
    assert(invoked.calls == 1u && invoked.transport_failure);
    client.vtable->get_activation(&client, TEXT("recover-known"), observe_status, &status);
    assert(status.calls == 1u && status.has_terminal_state && status.has_terminal_outcome);
    assert_text(&status.activation_id, TEXT("recover-known"));
    assert_text(&status.terminal_state, TEXT("completed"));
    assert(client.invoke_count == 1u && client.status_count == 1u);
    client.vtable->destroy(&client);
}

static void absent_identity_is_server_assigned_and_present_empty_is_preserved(void) {
    latent_client client = new_client();
    observed_call invoked = {0};
    latent_invoke_request absent = {0};
    invoked.expected_operation = client.vtable->invoke(&client, &absent, observe_invoke, &invoked);
    assert(!client.supplied_activation.present && !client.supplied_root.present && !client.supplied_parent.present);
    finish_invoke(&client, false);
    assert(invoked.calls == 1u && !invoked.transport_failure);
    assert_text(&invoked.activation_id, TEXT("server-assigned"));
    latent_invoke_request empty = {0};
    empty.has_activation_id = true;
    empty.activation_id = TEXT("");
    empty.has_root_activation_id = true;
    empty.root_activation_id = TEXT("");
    empty.has_parent_activation_id = true;
    empty.parent_activation_id = TEXT("");
    invoked.expected_operation = client.vtable->invoke(&client, &empty, observe_invoke, &invoked);
    assert(client.supplied_activation.present && client.supplied_root.present && client.supplied_parent.present);
    assert(client.supplied_activation.value.length == 0u);
    assert(client.supplied_root.value.length == 0u && client.supplied_parent.value.length == 0u);
    /* This fixture tests forwarding, not server admission of empty identity. */
    finish_invoke(&client, true);
    assert(invoked.calls == 2u);
    client.vtable->destroy(&client);
}

int main(void) {
    pending_identity_supports_status_and_all_cancel_results();
    lost_response_can_be_recovered_by_id_without_reinvoking();
    absent_identity_is_server_assigned_and_present_empty_is_preserved();
    puts("C invocation identity and cancellation semantics passed");
    return 0;
}
