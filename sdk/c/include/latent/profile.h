#ifndef LATENT_CLIENT_PROFILE_H
#define LATENT_CLIENT_PROFILE_H

#include "latent.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct latent_profile_counter {
    latent_string key;
    uint64_t value;
} latent_profile_counter;

typedef int32_t latent_profile_audit_ack_status;
#define LATENT_PROFILE_AUDIT_ACK_STATUS_UNSPECIFIED ((latent_profile_audit_ack_status)0)
#define LATENT_PROFILE_AUDIT_ACK_STATUS_DURABLE ((latent_profile_audit_ack_status)1)
#define LATENT_PROFILE_AUDIT_ACK_STATUS_OUTCOME_UNKNOWN ((latent_profile_audit_ack_status)2)
#define LATENT_PROFILE_AUDIT_ACK_STATUS_AUDIT_UNAVAILABLE ((latent_profile_audit_ack_status)3)
#define LATENT_PROFILE_AUDIT_ACK_STATUS_DISABLED ((latent_profile_audit_ack_status)4)

typedef int32_t latent_profile_cancel_disposition;
#define LATENT_PROFILE_CANCEL_DISPOSITION_UNSPECIFIED ((latent_profile_cancel_disposition)0)
#define LATENT_PROFILE_CANCEL_DISPOSITION_ACCEPTED ((latent_profile_cancel_disposition)1)
#define LATENT_PROFILE_CANCEL_DISPOSITION_ALREADY_TERMINAL ((latent_profile_cancel_disposition)2)
#define LATENT_PROFILE_CANCEL_DISPOSITION_NOT_FOUND ((latent_profile_cancel_disposition)3)

typedef int32_t latent_profile_capability_policy_record_kind;
#define LATENT_PROFILE_CAPABILITY_POLICY_RECORD_KIND_UNSPECIFIED ((latent_profile_capability_policy_record_kind)0)
#define LATENT_PROFILE_CAPABILITY_POLICY_RECORD_KIND_POLICY ((latent_profile_capability_policy_record_kind)1)
#define LATENT_PROFILE_CAPABILITY_POLICY_RECORD_KIND_PROVIDER_BINDING ((latent_profile_capability_policy_record_kind)2)

typedef int32_t latent_profile_failure_category;
#define LATENT_PROFILE_FAILURE_CATEGORY_UNSPECIFIED ((latent_profile_failure_category)0)
#define LATENT_PROFILE_FAILURE_CATEGORY_LOCAL_CANCELLED ((latent_profile_failure_category)1)
#define LATENT_PROFILE_FAILURE_CATEGORY_DEADLINE ((latent_profile_failure_category)2)
#define LATENT_PROFILE_FAILURE_CATEGORY_TRANSPORT ((latent_profile_failure_category)3)
#define LATENT_PROFILE_FAILURE_CATEGORY_RPC ((latent_profile_failure_category)4)
#define LATENT_PROFILE_FAILURE_CATEGORY_DECODE ((latent_profile_failure_category)5)
#define LATENT_PROFILE_FAILURE_CATEGORY_LIMIT ((latent_profile_failure_category)6)
#define LATENT_PROFILE_FAILURE_CATEGORY_INVALID_REQUEST ((latent_profile_failure_category)7)

typedef int32_t latent_profile_outcome_knowledge;
#define LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNSPECIFIED ((latent_profile_outcome_knowledge)0)
#define LATENT_PROFILE_OUTCOME_KNOWLEDGE_NOT_DISPATCHED ((latent_profile_outcome_knowledge)1)
#define LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN ((latent_profile_outcome_knowledge)2)
#define LATENT_PROFILE_OUTCOME_KNOWLEDGE_OBSERVED ((latent_profile_outcome_knowledge)3)

typedef struct latent_profile_resource_budget {
    uint64_t cpu_fuel;
    uint64_t memory_bytes;
    uint32_t child_calls;
    uint32_t outbound_requests;
    uint64_t state_read_bytes;
    uint64_t state_write_bytes;
    uint64_t blob_read_bytes;
    uint64_t blob_write_bytes;
    uint64_t log_bytes;
    uint32_t effect_count;
    bool has_wall_time_limit_millis;
    uint64_t wall_time_limit_millis;
} latent_profile_resource_budget;

typedef struct latent_profile_error_detail {
    latent_string kind;
    const latent_key_value * fields;
    size_t fields_count;
} latent_profile_error_detail;

typedef struct latent_profile_platform_error {
    latent_string code;
    latent_string message;
    bool retryable;
    const latent_profile_error_detail * detail_items;
    size_t detail_items_count;
} latent_profile_platform_error;

typedef struct latent_profile_object_metadata {
    latent_string name;
    bool has_tenant;
    latent_string tenant;
    bool has_namespace;
    latent_string namespace;
    const latent_key_value * labels;
    size_t labels_count;
    const latent_key_value * annotations;
    size_t annotations_count;
} latent_profile_object_metadata;

typedef struct latent_profile_page_request {
    uint32_t page_size;
    bool has_page_token;
    latent_string page_token;
} latent_profile_page_request;

typedef struct latent_profile_page_response {
    bool has_next_page_token;
    latent_string next_page_token;
} latent_profile_page_response;

typedef struct latent_profile_audit_ack {
    latent_profile_audit_ack_status status;
    bool has_attempt_sequence;
    uint64_t attempt_sequence;
} latent_profile_audit_ack;

typedef struct latent_profile_invocation_target {
    latent_string tenant;
    latent_string service;
    latent_string contract;
    latent_string function;
    bool has_route;
    latent_string route;
} latent_profile_invocation_target;

typedef struct latent_profile_invoke_request {
    bool has_activation_id;
    latent_string activation_id;
    bool has_parent_activation_id;
    latent_string parent_activation_id;
    bool has_root_activation_id;
    latent_string root_activation_id;
    bool has_target;
    latent_profile_invocation_target target;
    latent_bytes payload;
    latent_string media_type;
    bool has_deadline_unix_millis;
    uint64_t deadline_unix_millis;
    uint32_t priority;
    bool has_idempotency_key;
    latent_string idempotency_key;
    bool has_budget;
    latent_profile_resource_budget budget;
    const latent_key_value * metadata;
    size_t metadata_count;
} latent_profile_invoke_request;

typedef struct latent_profile_budget_consumption {
    uint64_t cpu_fuel;
    uint64_t peak_memory_bytes;
    uint64_t wall_time_micros;
    uint32_t child_calls;
    uint32_t outbound_requests;
    uint64_t state_read_bytes;
    uint64_t state_write_bytes;
    uint64_t blob_read_bytes;
    uint64_t blob_write_bytes;
    uint64_t log_bytes;
    uint32_t effect_count;
} latent_profile_budget_consumption;

typedef struct latent_profile_success {
    latent_bytes payload;
    latent_string media_type;
    bool has_committed_state_version;
    latent_string committed_state_version;
    const latent_string * effect_ids;
    size_t effect_ids_count;
    const latent_key_value * metadata;
    size_t metadata_count;
} latent_profile_success;

typedef struct latent_profile_declared_error {
    latent_string code;
    latent_string message;
    latent_bytes payload;
    latent_string media_type;
    const latent_key_value * metadata;
    size_t metadata_count;
} latent_profile_declared_error;

typedef struct latent_profile_invoke_response {
    latent_string activation_id;
    latent_string revision_id;
    latent_string release_digest;
    uint64_t route_generation;
    bool has_success;
    latent_profile_success success;
    bool has_declared_error;
    latent_profile_declared_error declared_error;
    bool has_platform_failure;
    latent_profile_platform_error platform_failure;
    bool has_consumption;
    latent_profile_budget_consumption consumption;
    bool has_publication_id;
    latent_string publication_id;
} latent_profile_invoke_response;

typedef struct latent_profile_cancel_request {
    latent_string activation_id;
    latent_string reason;
} latent_profile_cancel_request;

typedef struct latent_profile_cancel_response {
    latent_profile_cancel_disposition disposition;
    bool has_terminal_state;
    latent_string terminal_state;
} latent_profile_cancel_response;

typedef struct latent_profile_get_activation_request {
    latent_string activation_id;
} latent_profile_get_activation_request;

typedef struct latent_profile_activation_success_summary {
    bool has_committed_state_version;
    latent_string committed_state_version;
    const latent_string * effect_ids;
    size_t effect_ids_count;
    const latent_key_value * metadata;
    size_t metadata_count;
} latent_profile_activation_success_summary;

typedef struct latent_profile_activation_status {
    latent_string activation_id;
    latent_string phase;
    bool has_terminal_state;
    latent_string terminal_state;
    uint64_t last_updated_unix_millis;
    const latent_key_value * metadata;
    size_t metadata_count;
    bool has_succeeded;
    latent_profile_activation_success_summary succeeded;
    bool has_declared_error;
    latent_profile_declared_error declared_error;
    bool has_platform_failure;
    latent_profile_platform_error platform_failure;
    bool has_final_consumption;
    latent_profile_budget_consumption final_consumption;
    bool has_terminal_at_unix_millis;
    uint64_t terminal_at_unix_millis;
} latent_profile_activation_status;

typedef struct latent_profile_policy {
    latent_string id;
    bool has_metadata;
    latent_profile_object_metadata metadata;
    latent_string document;
    uint64_t generation;
    latent_string language;
    latent_profile_capability_policy_record_kind record_kind;
    latent_string content_digest;
    bool revoked;
} latent_profile_policy;

typedef struct latent_profile_apply_policy_request {
    bool has_policy;
    latent_profile_policy policy;
    bool has_expected_generation;
    uint64_t expected_generation;
    latent_string operation_id;
} latent_profile_apply_policy_request;

typedef struct latent_profile_capability_policy_operation {
    latent_string operation_id;
    latent_string tenant;
    latent_string id;
    latent_profile_capability_policy_record_kind record_kind;
    uint64_t generation;
    latent_string content_digest;
    bool revoked;
} latent_profile_capability_policy_operation;

typedef struct latent_profile_apply_policy_response {
    bool has_policy;
    latent_profile_policy policy;
    bool has_receipt;
    latent_profile_capability_policy_operation receipt;
} latent_profile_apply_policy_response;

typedef struct latent_profile_get_policy_request {
    latent_string id;
    latent_profile_capability_policy_record_kind record_kind;
} latent_profile_get_policy_request;

typedef struct latent_profile_get_policy_response {
    bool has_policy;
    latent_profile_policy policy;
} latent_profile_get_policy_response;

typedef struct latent_profile_get_policy_operation_request {
    latent_string operation_id;
} latent_profile_get_policy_operation_request;

typedef struct latent_profile_get_policy_operation_response {
    bool has_receipt;
    latent_profile_capability_policy_operation receipt;
} latent_profile_get_policy_operation_response;

typedef struct latent_profile_list_policies_request {
    latent_profile_capability_policy_record_kind record_kind;
    bool has_page;
    latent_profile_page_request page;
} latent_profile_list_policies_request;

typedef struct latent_profile_list_policies_response {
    const latent_profile_policy * policies;
    size_t policies_count;
    uint64_t catalog_generation;
    bool has_page;
    latent_profile_page_response page;
} latent_profile_list_policies_response;

typedef struct latent_profile_capability_inspection_policy {
    latent_string id;
    uint64_t revision;
    latent_string digest;
} latent_profile_capability_inspection_policy;

typedef struct latent_profile_capability_binding_inspection {
    bool has_definition_digest;
    latent_string definition_digest;
    bool has_provider_binding;
    latent_profile_capability_inspection_policy provider_binding;
    const latent_profile_capability_inspection_policy * policies;
    size_t policies_count;
    latent_string provider_profile;
    latent_string provider_configuration_digest;
    uint64_t provider_configuration_epoch;
    latent_string state;
} latent_profile_capability_binding_inspection;

typedef struct latent_profile_capability_descriptor {
    latent_string id;
    latent_string contract;
    latent_string provider;
    const latent_string * operations;
    size_t operations_count;
    const latent_key_value * attributes;
    size_t attributes_count;
    bool has_inspection;
    latent_profile_capability_binding_inspection inspection;
} latent_profile_capability_descriptor;

typedef struct latent_profile_list_capabilities_request {
    bool has_contract_prefix;
    latent_string contract_prefix;
    bool has_provider;
    latent_string provider;
    bool has_page;
    latent_profile_page_request page;
    latent_string deployment_id;
    bool include_node_usage;
} latent_profile_list_capabilities_request;

typedef struct latent_profile_capability_inspection_revision {
    latent_string deployment_id;
    latent_string revision_id;
    latent_string component_digest;
    bool has_publication_id;
    latent_string publication_id;
    uint64_t route_generation;
    uint64_t catalog_transaction;
} latent_profile_capability_inspection_revision;

typedef struct latent_profile_capability_resource_usage {
    latent_string scope;
    const latent_profile_counter * counters;
    size_t counters_count;
    const latent_string * unavailable;
    size_t unavailable_count;
} latent_profile_capability_resource_usage;

typedef struct latent_profile_list_capabilities_response {
    const latent_profile_capability_descriptor * capabilities;
    size_t capabilities_count;
    bool has_page;
    latent_profile_page_response page;
    bool has_revision;
    latent_profile_capability_inspection_revision revision;
    bool has_tenant_usage;
    latent_profile_capability_resource_usage tenant_usage;
    bool has_node_usage;
    latent_profile_capability_resource_usage node_usage;
    latent_string state;
} latent_profile_list_capabilities_response;

typedef struct latent_profile_capability_inspection_ceiling {
    uint32_t operations;
    uint64_t input_bytes;
    uint64_t output_bytes;
    uint64_t wall_time_millis;
} latent_profile_capability_inspection_ceiling;

typedef struct latent_profile_publication_ref {
    latent_string id;
    latent_string tenant;
} latent_profile_publication_ref;

typedef struct latent_profile_release_selector {
    bool has_component_digest;
    latent_string component_digest;
    bool has_publication;
    latent_profile_publication_ref publication;
} latent_profile_release_selector;

typedef struct latent_profile_publication_identity {
    latent_profile_publication_ref publication;
    latent_string component_digest;
    latent_string package_digest;
} latent_profile_publication_identity;

typedef struct latent_profile_call_options {
    bool has_timeout_millis;
    uint64_t timeout_millis;
} latent_profile_call_options;

typedef struct latent_profile_request_identity {
    bool has_activation_id;
    latent_string activation_id;
    bool has_operation_id;
    latent_string operation_id;
} latent_profile_request_identity;

typedef struct latent_profile_unsupported_wire_value {
    latent_string field;
    latent_string value;
} latent_profile_unsupported_wire_value;

typedef struct latent_profile_response_metadata {
    latent_profile_request_identity identity;
    latent_profile_outcome_knowledge outcome;
    bool has_audit_ack;
    latent_profile_audit_ack audit_ack;
    bool has_audit_status;
    latent_string audit_status;
    bool has_audit_attempt_sequence;
    uint64_t audit_attempt_sequence;
} latent_profile_response_metadata;

typedef struct latent_profile_client_failure {
    latent_profile_failure_category category;
    latent_string message;
    bool has_grpc_status;
    int32_t grpc_status;
    bool has_platform_error;
    latent_profile_platform_error platform_error;
    bool dispatched;
    latent_profile_outcome_knowledge outcome;
    latent_profile_request_identity identity;
    bool has_audit_ack;
    latent_profile_audit_ack audit_ack;
    bool has_audit_status;
    latent_string audit_status;
    bool has_unsupported_wire_value;
    latent_profile_unsupported_wire_value unsupported_wire_value;
    bool has_audit_attempt_sequence;
    uint64_t audit_attempt_sequence;
} latent_profile_client_failure;

typedef struct latent_profile_client latent_profile_client;
typedef struct latent_profile_call latent_profile_call;

typedef struct latent_profile_invoke_result {
    latent_profile_invoke_response value;
    latent_profile_response_metadata metadata;
} latent_profile_invoke_result;

typedef void (*latent_profile_invoke_callback)(
    const latent_profile_invoke_result *response,
    const latent_profile_client_failure *failure,
    void *user_data);

typedef struct latent_profile_cancel_result {
    latent_profile_cancel_response value;
    latent_profile_response_metadata metadata;
} latent_profile_cancel_result;

typedef void (*latent_profile_cancel_callback)(
    const latent_profile_cancel_result *response,
    const latent_profile_client_failure *failure,
    void *user_data);

typedef struct latent_profile_get_activation_result {
    latent_profile_activation_status value;
    latent_profile_response_metadata metadata;
} latent_profile_get_activation_result;

typedef void (*latent_profile_get_activation_callback)(
    const latent_profile_get_activation_result *response,
    const latent_profile_client_failure *failure,
    void *user_data);

typedef struct latent_profile_get_policy_result {
    latent_profile_get_policy_response value;
    latent_profile_response_metadata metadata;
} latent_profile_get_policy_result;

typedef void (*latent_profile_get_policy_callback)(
    const latent_profile_get_policy_result *response,
    const latent_profile_client_failure *failure,
    void *user_data);

typedef struct latent_profile_list_policies_result {
    latent_profile_list_policies_response value;
    latent_profile_response_metadata metadata;
} latent_profile_list_policies_result;

typedef void (*latent_profile_list_policies_callback)(
    const latent_profile_list_policies_result *response,
    const latent_profile_client_failure *failure,
    void *user_data);

typedef struct latent_profile_list_capabilities_result {
    latent_profile_list_capabilities_response value;
    latent_profile_response_metadata metadata;
} latent_profile_list_capabilities_result;

typedef void (*latent_profile_list_capabilities_callback)(
    const latent_profile_list_capabilities_result *response,
    const latent_profile_client_failure *failure,
    void *user_data);

typedef struct latent_profile_apply_policy_result {
    latent_profile_apply_policy_response value;
    latent_profile_response_metadata metadata;
} latent_profile_apply_policy_result;

typedef void (*latent_profile_apply_policy_callback)(
    const latent_profile_apply_policy_result *response,
    const latent_profile_client_failure *failure,
    void *user_data);

typedef struct latent_profile_get_policy_operation_result {
    latent_profile_get_policy_operation_response value;
    latent_profile_response_metadata metadata;
} latent_profile_get_policy_operation_result;

typedef void (*latent_profile_get_policy_operation_callback)(
    const latent_profile_get_policy_operation_result *response,
    const latent_profile_client_failure *failure,
    void *user_data);

typedef struct latent_profile_client_vtable {
    latent_profile_call *(*invoke)(
        latent_profile_client *client,
        const latent_profile_invoke_request *request,
        const latent_profile_call_options *options,
        latent_profile_invoke_callback callback,
        void *user_data);

    latent_profile_call *(*cancel)(
        latent_profile_client *client,
        const latent_profile_cancel_request *request,
        const latent_profile_call_options *options,
        latent_profile_cancel_callback callback,
        void *user_data);

    latent_profile_call *(*get_activation)(
        latent_profile_client *client,
        const latent_profile_get_activation_request *request,
        const latent_profile_call_options *options,
        latent_profile_get_activation_callback callback,
        void *user_data);

    latent_profile_call *(*get_policy)(
        latent_profile_client *client,
        const latent_profile_get_policy_request *request,
        const latent_profile_call_options *options,
        latent_profile_get_policy_callback callback,
        void *user_data);

    latent_profile_call *(*list_policies)(
        latent_profile_client *client,
        const latent_profile_list_policies_request *request,
        const latent_profile_call_options *options,
        latent_profile_list_policies_callback callback,
        void *user_data);

    latent_profile_call *(*list_capabilities)(
        latent_profile_client *client,
        const latent_profile_list_capabilities_request *request,
        const latent_profile_call_options *options,
        latent_profile_list_capabilities_callback callback,
        void *user_data);

    latent_profile_call *(*apply_policy)(
        latent_profile_client *client,
        const latent_profile_apply_policy_request *request,
        const latent_profile_call_options *options,
        latent_profile_apply_policy_callback callback,
        void *user_data);

    latent_profile_call *(*get_policy_operation)(
        latent_profile_client *client,
        const latent_profile_get_policy_operation_request *request,
        const latent_profile_call_options *options,
        latent_profile_get_policy_operation_callback callback,
        void *user_data);

    void (*cancel_local)(latent_profile_call *call);
    void (*release_call)(latent_profile_call *call);
    void (*destroy)(latent_profile_client *client);
} latent_profile_client_vtable;

static inline bool latent_profile_parse_u64(latent_string value, uint64_t *output) {
    uint64_t parsed = 0;
    if (output == NULL || value.data == NULL || value.length == 0 || value.length > 20
        || (value.length > 1 && value.data[0] == '0')) return false;
    for (size_t position = 0; position < value.length; ++position) {
        unsigned char digit = (unsigned char)value.data[position];
        if (digit < '0' || digit > '9') return false;
        uint64_t amount = (uint64_t)(digit - '0');
        if (parsed > (UINT64_MAX - amount) / 10) return false;
        parsed = parsed * 10 + amount;
    }
    *output = parsed;
    return true;
}

#ifdef __cplusplus
}
#endif

#endif
