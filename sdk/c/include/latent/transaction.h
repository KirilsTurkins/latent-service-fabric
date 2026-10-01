/* Generated from the authoritative transaction client descriptors. */
#ifndef LATENT_TRANSACTION_MODELS_H
#define LATENT_TRANSACTION_MODELS_H

#include "profile.h"

#ifdef __cplusplus
extern "C" {
#endif


typedef int32_t latent_transaction_command_cancel_disposition;
#define LATENT_TRANSACTION_COMMAND_CANCEL_DISPOSITION_UNSPECIFIED ((latent_transaction_command_cancel_disposition)0)
#define LATENT_TRANSACTION_COMMAND_CANCEL_DISPOSITION_REQUESTED ((latent_transaction_command_cancel_disposition)1)
#define LATENT_TRANSACTION_COMMAND_CANCEL_DISPOSITION_ALREADY_COMMITTED ((latent_transaction_command_cancel_disposition)2)
#define LATENT_TRANSACTION_COMMAND_CANCEL_DISPOSITION_ALREADY_TERMINAL ((latent_transaction_command_cancel_disposition)3)
#define LATENT_TRANSACTION_COMMAND_CANCEL_DISPOSITION_NOT_FOUND ((latent_transaction_command_cancel_disposition)4)
#define LATENT_TRANSACTION_COMMAND_CANCEL_DISPOSITION_RECOVERY_REQUIRED ((latent_transaction_command_cancel_disposition)5)

typedef int32_t latent_transaction_command_outcome;
#define LATENT_TRANSACTION_COMMAND_OUTCOME_UNSPECIFIED ((latent_transaction_command_outcome)0)
#define LATENT_TRANSACTION_COMMAND_OUTCOME_IN_PROGRESS ((latent_transaction_command_outcome)1)
#define LATENT_TRANSACTION_COMMAND_OUTCOME_COMMITTED ((latent_transaction_command_outcome)2)
#define LATENT_TRANSACTION_COMMAND_OUTCOME_REJECTED ((latent_transaction_command_outcome)3)
#define LATENT_TRANSACTION_COMMAND_OUTCOME_ABORTED ((latent_transaction_command_outcome)4)
#define LATENT_TRANSACTION_COMMAND_OUTCOME_UNKNOWN ((latent_transaction_command_outcome)5)
#define LATENT_TRANSACTION_COMMAND_OUTCOME_RECOVERY_REQUIRED ((latent_transaction_command_outcome)6)
#define LATENT_TRANSACTION_COMMAND_OUTCOME_EXPIRED ((latent_transaction_command_outcome)7)

typedef int32_t latent_transaction_effect_disposition;
#define LATENT_TRANSACTION_EFFECT_DISPOSITION_UNSPECIFIED ((latent_transaction_effect_disposition)0)
#define LATENT_TRANSACTION_EFFECT_DISPOSITION_PENDING ((latent_transaction_effect_disposition)1)
#define LATENT_TRANSACTION_EFFECT_DISPOSITION_DISPATCHING ((latent_transaction_effect_disposition)2)
#define LATENT_TRANSACTION_EFFECT_DISPOSITION_PROVIDER_ACKNOWLEDGED ((latent_transaction_effect_disposition)3)
#define LATENT_TRANSACTION_EFFECT_DISPOSITION_KNOWN_FAILURE ((latent_transaction_effect_disposition)4)
#define LATENT_TRANSACTION_EFFECT_DISPOSITION_UNCERTAIN_AFTER_DISPATCH ((latent_transaction_effect_disposition)5)
#define LATENT_TRANSACTION_EFFECT_DISPOSITION_EXPIRED ((latent_transaction_effect_disposition)6)
#define LATENT_TRANSACTION_EFFECT_DISPOSITION_POLICY_BLOCKED ((latent_transaction_effect_disposition)7)
#define LATENT_TRANSACTION_EFFECT_DISPOSITION_ADMINISTRATIVELY_TERMINATED ((latent_transaction_effect_disposition)8)

typedef int32_t latent_transaction_namespace_mutation_kind;
#define LATENT_TRANSACTION_NAMESPACE_MUTATION_KIND_UNSPECIFIED ((latent_transaction_namespace_mutation_kind)0)
#define LATENT_TRANSACTION_NAMESPACE_MUTATION_KIND_CREATE ((latent_transaction_namespace_mutation_kind)1)
#define LATENT_TRANSACTION_NAMESPACE_MUTATION_KIND_QUIESCE ((latent_transaction_namespace_mutation_kind)2)
#define LATENT_TRANSACTION_NAMESPACE_MUTATION_KIND_RETIRE ((latent_transaction_namespace_mutation_kind)3)
#define LATENT_TRANSACTION_NAMESPACE_MUTATION_KIND_DESTROY ((latent_transaction_namespace_mutation_kind)4)
#define LATENT_TRANSACTION_NAMESPACE_MUTATION_KIND_RECREATE ((latent_transaction_namespace_mutation_kind)5)

typedef int32_t latent_transaction_namespace_status;
#define LATENT_TRANSACTION_NAMESPACE_STATUS_UNSPECIFIED ((latent_transaction_namespace_status)0)
#define LATENT_TRANSACTION_NAMESPACE_STATUS_ACTIVE ((latent_transaction_namespace_status)1)
#define LATENT_TRANSACTION_NAMESPACE_STATUS_QUIESCING ((latent_transaction_namespace_status)2)
#define LATENT_TRANSACTION_NAMESPACE_STATUS_RETIRED ((latent_transaction_namespace_status)3)
#define LATENT_TRANSACTION_NAMESPACE_STATUS_TOMBSTONE ((latent_transaction_namespace_status)4)

typedef int32_t latent_transaction_state_mutation_kind;
#define LATENT_TRANSACTION_STATE_MUTATION_KIND_UNSPECIFIED ((latent_transaction_state_mutation_kind)0)
#define LATENT_TRANSACTION_STATE_MUTATION_KIND_RETRY_KNOWN_FAILED_EFFECT ((latent_transaction_state_mutation_kind)1)
#define LATENT_TRANSACTION_STATE_MUTATION_KIND_TERMINATE_EFFECT ((latent_transaction_state_mutation_kind)2)
#define LATENT_TRANSACTION_STATE_MUTATION_KIND_PURGE_EXPIRED_PAYLOAD ((latent_transaction_state_mutation_kind)3)
#define LATENT_TRANSACTION_STATE_MUTATION_KIND_CHECKPOINT_NAMESPACE ((latent_transaction_state_mutation_kind)4)

typedef int32_t latent_transaction_state_operation_disposition;
#define LATENT_TRANSACTION_STATE_OPERATION_DISPOSITION_UNSPECIFIED ((latent_transaction_state_operation_disposition)0)
#define LATENT_TRANSACTION_STATE_OPERATION_DISPOSITION_COMMITTED ((latent_transaction_state_operation_disposition)1)
#define LATENT_TRANSACTION_STATE_OPERATION_DISPOSITION_CONFLICT ((latent_transaction_state_operation_disposition)2)
#define LATENT_TRANSACTION_STATE_OPERATION_DISPOSITION_REJECTED ((latent_transaction_state_operation_disposition)3)
#define LATENT_TRANSACTION_STATE_OPERATION_DISPOSITION_UNKNOWN ((latent_transaction_state_operation_disposition)4)
#define LATENT_TRANSACTION_STATE_OPERATION_DISPOSITION_RECOVERY_REQUIRED ((latent_transaction_state_operation_disposition)5)

typedef struct latent_transaction_abort_fence {
    latent_string command_id;
    latent_string attempt_id;
    latent_string transaction_id;
    latent_bytes owner_fence;
} latent_transaction_abort_fence;

typedef struct latent_transaction_transaction_profile {
    latent_string profile;
    latent_string host_abi_digest;
    latent_string preparation_profile_digest;
} latent_transaction_transaction_profile;

typedef struct latent_transaction_namespace_selector {
    latent_string tenant;
    latent_string namespace;
    latent_string incarnation;
} latent_transaction_namespace_selector;

typedef struct latent_transaction_command_selector {
    bool has_namespace;
    latent_transaction_namespace_selector namespace;
    latent_string operation;
    bool has_entity;
    latent_string entity;
    latent_string client_key;
    bool has_shared_recovery_scope;
    latent_string shared_recovery_scope;
} latent_transaction_command_selector;

typedef struct latent_transaction_lookup_command_request {
    bool has_profile;
    latent_transaction_transaction_profile profile;
    bool has_command;
    latent_transaction_command_selector command;
    bool has_attempt_id;
    latent_string attempt_id;
    bool has_authorization_publication;
    latent_profile_publication_ref authorization_publication;
} latent_transaction_lookup_command_request;

typedef struct latent_transaction_cancel_command_request {
    bool has_command;
    latent_transaction_lookup_command_request command;
    latent_string reason;
} latent_transaction_cancel_command_request;

typedef struct latent_transaction_command_key {
    bool has_namespace;
    latent_transaction_namespace_selector namespace;
    latent_string recovery_scope;
    latent_string operation;
    bool has_entity;
    latent_string entity;
    latent_string client_key;
} latent_transaction_command_key;

typedef struct latent_transaction_source_identity {
    latent_string publication_id;
    latent_string revision_id;
    latent_string release_digest;
    uint64_t route_generation;
    latent_string contract_digest;
    latent_string state_schema;
    latent_string input_format;
    latent_string result_format;
    latent_string component_digest;
} latent_transaction_source_identity;

typedef struct latent_transaction_commit_receipt {
    latent_string command_id;
    latent_string attempt_id;
    latent_string transaction_id;
    latent_bytes committed_version;
    uint64_t committed_at_unix_millis;
    const latent_string * effect_ids;
    size_t effect_ids_count;
    latent_string receipt_id;
    bool has_source;
    latent_transaction_source_identity source;
} latent_transaction_commit_receipt;

typedef struct latent_transaction_linked_retention {
    latent_string record_format;
    uint32_t record_version;
    bool has_payload_expires_at_unix_millis;
    uint64_t payload_expires_at_unix_millis;
    bool has_identity_expires_at_unix_millis;
    uint64_t identity_expires_at_unix_millis;
    bool has_remaining_recovery_millis;
    uint64_t remaining_recovery_millis;
    const latent_string * required_record_ids;
    size_t required_record_ids_count;
    bool payload_available;
} latent_transaction_linked_retention;

typedef struct latent_transaction_command_inspection {
    bool has_key;
    latent_transaction_command_key key;
    latent_string command_id;
    latent_string attempt_id;
    latent_bytes fingerprint_sha256;
    latent_transaction_command_outcome outcome;
    bool metadata_durable;
    bool application_state_committed;
    bool has_source;
    latent_transaction_source_identity source;
    bool has_success;
    latent_profile_success success;
    bool has_business_rejection;
    latent_profile_declared_error business_rejection;
    bool has_technical_failure;
    latent_profile_platform_error technical_failure;
    bool has_commit;
    latent_transaction_commit_receipt commit;
    bool has_proven_abort;
    latent_transaction_abort_fence proven_abort;
    bool has_retention;
    latent_transaction_linked_retention retention;
    bool has_cleanup_failure;
    latent_profile_platform_error cleanup_failure;
} latent_transaction_command_inspection;

typedef struct latent_transaction_cancel_command_response {
    latent_transaction_command_cancel_disposition disposition;
    bool has_command;
    latent_transaction_command_inspection command;
} latent_transaction_cancel_command_response;

typedef struct latent_transaction_effect_receipt {
    latent_string effect_id;
    latent_string command_id;
    latent_string command_attempt_id;
    uint32_t dispatch_attempt;
    latent_transaction_effect_disposition disposition;
    bool has_provider_receipt;
    latent_string provider_receipt;
    bool has_failure_code;
    latent_string failure_code;
    uint64_t occurred_at_unix_millis;
    bool has_retention;
    latent_transaction_linked_retention retention;
    bool has_management_operation_receipt_id;
    latent_string management_operation_receipt_id;
    latent_string provider_profile;
} latent_transaction_effect_receipt;

typedef struct latent_transaction_entity_inspection {
    latent_string entity;
    latent_bytes version;
} latent_transaction_entity_inspection;

typedef struct latent_transaction_expected_version {
    latent_bytes key;
    bool has_absent;
    bool absent;
    bool has_version;
    latent_bytes version;
} latent_transaction_expected_version;

typedef struct latent_transaction_get_effect_request {
    bool has_profile;
    latent_transaction_transaction_profile profile;
    bool has_command;
    latent_transaction_command_selector command;
    latent_string effect_id;
    bool has_authorization_publication;
    latent_profile_publication_ref authorization_publication;
} latent_transaction_get_effect_request;

typedef struct latent_transaction_get_effect_response {
    bool has_effect;
    latent_transaction_effect_receipt effect;
} latent_transaction_get_effect_response;

typedef struct latent_transaction_inspect_namespace_request {
    bool has_profile;
    latent_transaction_transaction_profile profile;
    bool has_namespace;
    latent_transaction_namespace_selector namespace;
    bool has_authorization_publication;
    latent_profile_publication_ref authorization_publication;
} latent_transaction_inspect_namespace_request;

typedef struct latent_transaction_get_state_operation_receipt_request {
    bool has_namespace;
    latent_transaction_inspect_namespace_request namespace;
    latent_string operation_id;
} latent_transaction_get_state_operation_receipt_request;

typedef struct latent_transaction_state_operation_receipt {
    latent_string operation_id;
    latent_string receipt_id;
    latent_transaction_state_mutation_kind mutation;
    bool has_namespace;
    latent_transaction_namespace_selector namespace;
    latent_string authenticated_operator;
    latent_bytes before_version;
    latent_bytes after_version;
    uint64_t completed_at_unix_millis;
    bool has_record_id;
    latent_string record_id;
    latent_string policy_digest;
    latent_transaction_state_operation_disposition disposition;
} latent_transaction_state_operation_receipt;

typedef struct latent_transaction_namespace_operation_receipt {
    latent_string operation_id;
    latent_string receipt_id;
    latent_transaction_namespace_mutation_kind mutation;
    bool has_namespace;
    latent_transaction_namespace_selector namespace;
    latent_string authenticated_operator;
    bool has_before_generation;
    uint64_t before_generation;
    uint64_t after_generation;
    latent_transaction_namespace_status status;
    latent_string state_schema;
    latent_transaction_state_operation_disposition disposition;
} latent_transaction_namespace_operation_receipt;

typedef struct latent_transaction_get_state_operation_receipt_response {
    bool has_receipt;
    latent_transaction_state_operation_receipt receipt;
    bool has_namespace_receipt;
    latent_transaction_namespace_operation_receipt namespace_receipt;
} latent_transaction_get_state_operation_receipt_response;

typedef struct latent_transaction_view_identity {
    bool has_namespace;
    latent_transaction_namespace_selector namespace;
    latent_bytes version;
    latent_string state_schema;
} latent_transaction_view_identity;

typedef struct latent_transaction_namespace_quota {
    uint64_t state_keys;
    uint64_t state_bytes;
    uint64_t result_rows;
    uint64_t result_bytes;
    uint64_t effect_rows;
    uint64_t effect_bytes;
    uint64_t payload_bytes;
    uint64_t recovery_bytes;
} latent_transaction_namespace_quota;

typedef struct latent_transaction_namespace_inspection {
    bool has_view;
    latent_transaction_view_identity view;
    uint64_t encoded_state_bytes;
    uint64_t command_count;
    uint64_t pending_effect_count;
    const latent_transaction_linked_retention * retained_formats;
    size_t retained_formats_count;
    latent_string engine_profile;
    latent_string engine_profile_digest;
    latent_transaction_namespace_status status;
    bool has_quota;
    latent_transaction_namespace_quota quota;
    uint64_t generation;
} latent_transaction_namespace_inspection;

typedef struct latent_transaction_inspect_namespace_response {
    bool has_namespace;
    latent_transaction_namespace_inspection namespace;
} latent_transaction_inspect_namespace_response;

typedef struct latent_transaction_retry_attempt {
    latent_string request_id;
    bool has_expected_abort;
    latent_transaction_abort_fence expected_abort;
} latent_transaction_retry_attempt;

typedef struct latent_transaction_invoke_command_request {
    bool has_profile;
    latent_transaction_transaction_profile profile;
    bool has_invocation;
    latent_profile_invoke_request invocation;
    bool has_command;
    latent_transaction_command_selector command;
    latent_string input_format;
    const latent_transaction_expected_version * expected_versions;
    size_t expected_versions_count;
    bool has_retry_attempt;
    latent_transaction_retry_attempt retry_attempt;
} latent_transaction_invoke_command_request;

typedef struct latent_transaction_invoke_command_response {
    bool has_invocation;
    latent_profile_invoke_response invocation;
    bool has_command;
    latent_transaction_command_inspection command;
    bool replayed;
} latent_transaction_invoke_command_response;

typedef struct latent_transaction_page_request {
    uint32_t limit;
    bool has_cursor;
    latent_bytes cursor;
} latent_transaction_page_request;

typedef struct latent_transaction_list_effect_history_request {
    bool has_effect;
    latent_transaction_get_effect_request effect;
    bool has_page;
    latent_transaction_page_request page;
} latent_transaction_list_effect_history_request;

typedef struct latent_transaction_page_response {
    bool has_next_cursor;
    latent_bytes next_cursor;
    uint32_t returned_count;
    uint64_t encoded_bytes;
} latent_transaction_page_response;

typedef struct latent_transaction_list_effect_history_response {
    const latent_transaction_effect_receipt * receipts;
    size_t receipts_count;
    bool has_page;
    latent_transaction_page_response page;
} latent_transaction_list_effect_history_response;

typedef struct latent_transaction_lookup_command_response {
    bool has_command;
    latent_transaction_command_inspection command;
} latent_transaction_lookup_command_response;

typedef struct latent_transaction_lookup_commit_request {
    bool has_profile;
    latent_transaction_transaction_profile profile;
    bool has_command;
    latent_transaction_command_selector command;
    latent_string receipt_id;
    bool has_authorization_publication;
    latent_profile_publication_ref authorization_publication;
} latent_transaction_lookup_commit_request;

typedef struct latent_transaction_lookup_commit_response {
    bool has_command;
    latent_transaction_command_inspection command;
} latent_transaction_lookup_commit_response;

typedef struct latent_transaction_namespace_configuration {
    latent_string state_schema;
    bool has_quota;
    latent_transaction_namespace_quota quota;
} latent_transaction_namespace_configuration;

typedef struct latent_transaction_mutate_namespace_request {
    bool has_namespace;
    latent_transaction_inspect_namespace_request namespace;
    latent_string operation_id;
    latent_transaction_namespace_mutation_kind mutation;
    bool has_expected_generation;
    uint64_t expected_generation;
    bool has_configuration;
    latent_transaction_namespace_configuration configuration;
} latent_transaction_mutate_namespace_request;

typedef struct latent_transaction_mutate_namespace_response {
    bool has_receipt;
    latent_transaction_namespace_operation_receipt receipt;
    bool replayed;
    bool has_audit_ack;
    latent_profile_audit_ack audit_ack;
} latent_transaction_mutate_namespace_response;

typedef struct latent_transaction_mutate_state_request {
    bool has_namespace;
    latent_transaction_inspect_namespace_request namespace;
    latent_string operation_id;
    latent_transaction_state_mutation_kind mutation;
    bool has_record_id;
    latent_string record_id;
    latent_bytes expected_version;
    latent_string expected_policy_digest;
    latent_string reason;
} latent_transaction_mutate_state_request;

typedef struct latent_transaction_mutate_state_response {
    bool has_receipt;
    latent_transaction_state_operation_receipt receipt;
    bool has_audit_ack;
    latent_profile_audit_ack audit_ack;
} latent_transaction_mutate_state_response;

typedef struct latent_transaction_query_request {
    bool has_profile;
    latent_transaction_transaction_profile profile;
    bool has_invocation;
    latent_profile_invoke_request invocation;
    bool has_namespace;
    latent_transaction_namespace_selector namespace;
    bool has_entity;
    latent_string entity;
    bool has_minimum_view_version;
    latent_bytes minimum_view_version;
} latent_transaction_query_request;

typedef struct latent_transaction_query_response {
    bool has_invocation;
    latent_profile_invoke_response invocation;
    bool has_view;
    latent_transaction_view_identity view;
    bool has_source;
    latent_transaction_source_identity source;
    uint64_t observed_at_unix_millis;
} latent_transaction_query_response;

typedef struct latent_transaction_select_entity_request {
    bool has_namespace;
    latent_transaction_inspect_namespace_request namespace;
    bool has_prefix;
    latent_bytes prefix;
    bool has_page;
    latent_transaction_page_request page;
} latent_transaction_select_entity_request;

typedef struct latent_transaction_select_entity_response {
    const latent_transaction_entity_inspection * entities;
    size_t entities_count;
    bool has_page;
    latent_transaction_page_response page;
} latent_transaction_select_entity_response;

/* Protocol data only. This descriptor grants no authority. */
static inline latent_transaction_transaction_profile latent_transaction_current_profile(void) {
    latent_transaction_transaction_profile result = {
        {"lsf-transaction-v1", 18},
        {"sha256:3b85f790f85ab23d36e492d7bd4a04a1b8aab87fc6f67dd7d7498bcf28129d35", 71},
        {"sha256:6acd7a248633dd01c9cdcbf8a1ed33fc5e6aa1d2edb09b7d89e53fda594b5507", 71},
    };
    return result;
}

#ifdef __cplusplus
}
#endif

#endif
