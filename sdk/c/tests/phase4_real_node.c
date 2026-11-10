/* Explicit live-node probe. The caller provisions the committed fixture. */
#include <latent/transaction_client.h>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *required(const char *name) {
    const char *value = getenv(name);
    if (value == NULL || *value == '\0') { fprintf(stderr, "missing live fixture field: %s\n", name); exit(2); }
    return value;
}
static latent_string str(const char *value) { return (latent_string){value, strlen(value)}; }
static bool matches(latent_string value, const char *expected) {
    size_t len = strlen(expected); return value.length == len && memcmp(value.data, expected, len) == 0;
}
typedef struct observation { unsigned calls; uint8_t fingerprint[32]; char receipt[257]; size_t receipt_len; } observation;
static void received(const latent_transaction_lookup_command_result *result,
        const latent_transaction_client_failure *failure, void *context) {
    observation *out = context;
    assert(failure == NULL && result != NULL && result->value.has_command && out->calls < 2);
    const latent_transaction_command_inspection *command = &result->value.command;
    assert(matches(command->command_id, required("LSF_401_COMMAND_ID")));
    assert(matches(command->attempt_id, required("LSF_401_ATTEMPT_ID")));
    assert(command->has_key && matches(command->key.client_key, required("LSF_401_COMMAND_KEY")));
    assert(command->outcome == LATENT_TRANSACTION_COMMAND_OUTCOME_COMMITTED && command->metadata_durable
        && command->application_state_committed && command->has_commit && command->has_source);
    assert(matches(command->source.publication_id, required("LSF_401_PUBLICATION")));
    assert(command->fingerprint_sha256.length == sizeof(out->fingerprint));
    assert(command->commit.receipt_id.length > 0 && command->commit.receipt_id.length <= sizeof(out->receipt));
    if (out->calls == 0) {
        memcpy(out->fingerprint, command->fingerprint_sha256.data, sizeof(out->fingerprint));
        out->receipt_len = command->commit.receipt_id.length;
        memcpy(out->receipt, command->commit.receipt_id.data, out->receipt_len);
    } else {
        assert(memcmp(out->fingerprint, command->fingerprint_sha256.data, sizeof(out->fingerprint)) == 0);
        assert(out->receipt_len == command->commit.receipt_id.length
            && memcmp(out->receipt, command->commit.receipt_id.data, out->receipt_len) == 0);
    }
    ++out->calls;
}
int main(void) {
    const char *endpoint = required("LSF_401_ENDPOINT"), *tenant = required("LSF_401_TENANT"), *token = required("LSF_401_TOKEN");
    char url[300]; int written = snprintf(url, sizeof(url), "http://%s", endpoint);
    assert(written > 0 && (size_t)written < sizeof(url));
    latent_transport_config config = latent_transport_defaults();
    config.endpoint = str(url); config.tenant = str(tenant); config.bearer_token = (latent_bytes){(const uint8_t *)token, strlen(token)};
    latent_transport *owner = NULL; assert(latent_transport_create(&config, &owner, NULL));
    const latent_transaction_client_vtable *api = latent_transport_transaction_vtable();
    latent_transaction_lookup_command_request request = {.has_profile = true, .profile = latent_transaction_current_profile(),
        .has_command = true, .command = {.has_namespace = true, .namespace = {str(tenant), str(required("LSF_401_NAMESPACE")), str(required("LSF_401_INCARNATION"))},
        .operation = str(required("LSF_401_OPERATION")), .client_key = str(required("LSF_401_COMMAND_KEY"))},
        .has_authorization_publication = true, .authorization_publication = {.id = str(required("LSF_401_PUBLICATION")), .tenant = str(tenant)}};
    observation out = {0};
    for (unsigned i = 0; i < 2; ++i) {
        latent_profile_call *call = api->lookup_command(latent_transport_transaction(owner), &request, NULL, received, &out);
        assert(call != NULL);
        for (unsigned step = 0; out.calls <= i && step < 1000; ++step) assert(latent_transport_poll(owner, 10));
        assert(out.calls == i + 1); api->release_call(call);
    }
    assert(latent_transport_shutdown(owner, 1000));
    latent_transport_usage usage = latent_transport_get_usage(owner);
    assert(usage.stopped && usage.sockets == 0 && usage.sessions == 0 && usage.http2_bytes == 0
        && usage.retained_calls == 0 && usage.callbacks_pending == 0 && usage.in_flight == 0 && usage.queued == 0);
    assert(latent_transport_destroy(owner)); puts("C live original-command lookup and shutdown passed");
    return 0;
}
