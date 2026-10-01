#ifndef LATENT_TRANSACTION_CLIENT_H
#define LATENT_TRANSACTION_CLIENT_H

#include "transport.h"
#include "transaction.h"

#ifdef __cplusplus
extern "C" {
#endif

/* A view of the existing transport owner. All response, failure, identity and
 * observation data is borrowed for the callback only. Copy any recovery values
 * needed later before returning. Call handles are local cancellation handles;
 * release them after notification. These values never grant authority. */
typedef struct latent_transaction_client latent_transaction_client;

typedef struct latent_transaction_recovery_identity {
    const latent_transaction_namespace_selector *namespace;
    const latent_transaction_command_selector *command;
    bool has_activation_id; latent_string activation_id;
    bool has_operation_id; latent_string operation_id;
    bool has_command_id; latent_string command_id;
    bool has_attempt_id; latent_string attempt_id;
    bool has_receipt_id; latent_string receipt_id;
    bool has_effect_id; latent_string effect_id;
    bool has_retry_request_id; latent_string retry_request_id;
    const latent_transaction_abort_fence *expected_abort;
    const latent_transaction_expected_version *expected_versions;
    size_t expected_versions_count;
    bool has_expected_generation; uint64_t expected_generation;
    bool has_expected_version; latent_bytes expected_version;
    bool has_expected_policy_digest; latent_string expected_policy_digest;
    latent_bytes fingerprint_sha256;
    const latent_profile_publication_ref *authorization_publication;
    bool has_dispatcher_action; latent_transaction_dispatcher_action dispatcher_action;
    const latent_transaction_dispatcher_generation *dispatcher_expected_generation;
} latent_transaction_recovery_identity;

typedef struct latent_transaction_observed_outcome {
    bool has_command; latent_transaction_command_inspection command;
    const latent_transaction_state_operation_receipt *state;
    const latent_transaction_namespace_operation_receipt *namespace;
    const latent_transaction_effect_receipt *effect;
    const latent_transaction_dispatcher_operation_receipt *dispatcher;
} latent_transaction_observed_outcome;

typedef struct latent_transaction_response_metadata {
    latent_profile_response_metadata transport;
    latent_transaction_recovery_identity identity;
    latent_transaction_observed_outcome observed;
} latent_transaction_response_metadata;

typedef struct latent_transaction_client_failure {
    latent_profile_client_failure transport;
    latent_transaction_recovery_identity identity;
    latent_transaction_observed_outcome observed;
} latent_transaction_client_failure;

#define LATENT_TRANSACTION_METHODS(M) \
    M(invoke_command, invoke_command_request, invoke_command_response) \
    M(query, query_request, query_response) \
    M(lookup_command, lookup_command_request, lookup_command_response) \
    M(lookup_commit, lookup_commit_request, lookup_commit_response) \
    M(get_effect, get_effect_request, get_effect_response) \
    M(list_effect_history, list_effect_history_request, list_effect_history_response) \
    M(cancel_command, cancel_command_request, cancel_command_response) \
    M(mutate_namespace, mutate_namespace_request, mutate_namespace_response) \
    M(inspect_namespace, inspect_namespace_request, inspect_namespace_response) \
    M(select_entity, select_entity_request, select_entity_response) \
    M(mutate_state, mutate_state_request, mutate_state_response) \
    M(get_state_operation_receipt, get_state_operation_receipt_request, get_state_operation_receipt_response) \
    M(inspect_dispatcher, inspect_dispatcher_request, inspect_dispatcher_response) \
    M(control_dispatcher, control_dispatcher_request, control_dispatcher_response) \
    M(get_dispatcher_operation, get_dispatcher_operation_request, get_dispatcher_operation_response)

#define LATENT_TRANSACTION_CALLBACK(method, request, response) \
    typedef struct latent_transaction_##method##_result { \
        latent_transaction_##response value; \
        latent_transaction_response_metadata metadata; \
    } latent_transaction_##method##_result; \
    typedef void (*latent_transaction_##method##_callback)( \
        const latent_transaction_##method##_result *response_value, \
        const latent_transaction_client_failure *failure, void *user_data);
LATENT_TRANSACTION_METHODS(LATENT_TRANSACTION_CALLBACK)
#undef LATENT_TRANSACTION_CALLBACK

typedef struct latent_transaction_client_vtable {
#define LATENT_TRANSACTION_METHOD(method, request, response) \
    latent_profile_call *(*method)(latent_transaction_client *client, \
        const latent_transaction_##request *request_value, \
        const latent_profile_call_options *options, \
        latent_transaction_##method##_callback callback, void *user_data);
LATENT_TRANSACTION_METHODS(LATENT_TRANSACTION_METHOD)
#undef LATENT_TRANSACTION_METHOD
    void (*cancel_local)(latent_profile_call *call);
    void (*release_call)(latent_profile_call *call);
} latent_transaction_client_vtable;

latent_transaction_client *latent_transport_transaction(latent_transport *transport);
const latent_transaction_client_vtable *latent_transport_transaction_vtable(void);

#ifdef __cplusplus
}
#endif
#endif
