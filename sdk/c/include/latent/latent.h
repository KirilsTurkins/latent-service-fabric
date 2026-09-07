#ifndef LATENT_SDK_H
#define LATENT_SDK_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct latent_client latent_client;
/* Identifies a local invoke operation for callback correlation. It is not an
   activation ID and cannot identify an activation after that operation ends.
   Callers must never dereference or free this opaque handle, and must not use
   it after the invocation completion callback returns. */
typedef struct latent_invocation latent_invocation;

typedef struct latent_bytes {
    const uint8_t *data;
    size_t length;
} latent_bytes;

typedef struct latent_string {
    const char *data;
    size_t length;
} latent_string;

typedef struct latent_key_value {
    latent_string key;
    latent_string value;
} latent_key_value;

typedef struct latent_error_detail {
    latent_string kind;
    const latent_key_value *fields;
    size_t field_count;
} latent_error_detail;

typedef struct latent_resource_budget {
    uint64_t cpu_fuel;
    uint64_t memory_bytes;
    /* Relative to admission. `has_wall_time_limit && value == 0` means no
       wall time is granted; it never means use a default. */
    bool has_wall_time_limit;
    uint64_t wall_time_limit_millis;
    uint32_t child_calls;
    uint32_t outbound_requests;
    uint64_t state_read_bytes;
    uint64_t state_write_bytes;
    uint64_t blob_read_bytes;
    uint64_t blob_write_bytes;
    uint64_t log_bytes;
    uint32_t effect_count;
} latent_resource_budget;

typedef struct latent_budget_consumption {
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
} latent_budget_consumption;

typedef struct latent_target {
    latent_string tenant;
    latent_string service;
    latent_string contract;
    latent_string function;
    latent_string route;
    bool has_route;
} latent_target;

typedef struct latent_invoke_request {
    latent_target target;
    latent_bytes payload;
    latent_string media_type;
    latent_resource_budget budget;
    uint8_t priority;
    bool has_deadline;
    uint64_t deadline_unix_millis;
    latent_string idempotency_key;
    bool has_idempotency_key;
    const latent_key_value *metadata;
    size_t metadata_count;
    /* Presence is independent of string length: a present empty value must be
       forwarded for server validation, never treated as absent. If activation
       ID is absent, the server assigns it. Root and parent are optional lineage
       claims subject to server validation and authorization. */
    bool has_activation_id;
    latent_string activation_id;
    bool has_root_activation_id;
    latent_string root_activation_id;
    bool has_parent_activation_id;
    latent_string parent_activation_id;
} latent_invoke_request;

typedef struct latent_invoke_response {
    latent_string activation_id;
    latent_string revision_id;
    latent_string release_digest;
    uint64_t route_generation;
    latent_bytes payload;
    latent_string media_type;
    bool has_committed_state_version;
    latent_string committed_state_version;
    const latent_string *effect_ids;
    size_t effect_id_count;
    latent_budget_consumption consumption;
    const latent_key_value *metadata;
    size_t metadata_count;
} latent_invoke_response;

typedef struct latent_platform_error {
    latent_string code;
    latent_string message;
    bool retryable;
    const latent_error_detail *details;
    size_t detail_count;
} latent_platform_error;

typedef struct latent_declared_error {
    latent_string code;
    latent_string message;
    latent_bytes payload;
    latent_string media_type;
    const latent_key_value *metadata;
    size_t metadata_count;
} latent_declared_error;

typedef struct latent_invocation_receipt {
    latent_string activation_id;
    latent_string revision_id;
    latent_string release_digest;
    uint64_t route_generation;
    latent_budget_consumption consumption;
} latent_invocation_receipt;

typedef struct latent_declared_invocation_error {
    latent_invocation_receipt receipt;
    latent_declared_error error;
} latent_declared_invocation_error;

typedef struct latent_platform_invocation_failure {
    latent_invocation_receipt receipt;
    latent_platform_error error;
} latent_platform_invocation_failure;

typedef enum latent_invocation_outcome_kind {
    LATENT_INVOCATION_SUCCEEDED = 1,
    LATENT_INVOCATION_DECLARED_ERROR = 2,
    LATENT_INVOCATION_PLATFORM_FAILURE = 3,
} latent_invocation_outcome_kind;

/* Exactly the member identified by `kind` is non-null. */
typedef struct latent_invocation_outcome {
    latent_invocation_outcome_kind kind;
    const latent_invoke_response *success;
    const latent_declared_invocation_error *declared_error;
    const latent_platform_invocation_failure *platform_failure;
} latent_invocation_outcome;

typedef struct latent_transport_error {
    latent_string message;
    bool retryable;
} latent_transport_error;

typedef enum latent_cancel_disposition {
    LATENT_CANCEL_ACCEPTED = 1,
    LATENT_CANCEL_ALREADY_TERMINAL = 2,
    LATENT_CANCEL_NOT_FOUND = 3,
} latent_cancel_disposition;

typedef struct latent_cancel_response {
    latent_cancel_disposition disposition;
    bool has_terminal_state;
    latent_string terminal_state;
} latent_cancel_response;

typedef struct latent_activation_success_summary {
    bool has_committed_state_version;
    latent_string committed_state_version;
    const latent_string *effect_ids;
    size_t effect_id_count;
    const latent_key_value *metadata;
    size_t metadata_count;
} latent_activation_success_summary;

typedef enum latent_retained_invocation_outcome_kind {
    LATENT_RETAINED_INVOCATION_SUCCEEDED = 1,
    LATENT_RETAINED_INVOCATION_DECLARED_ERROR = 2,
    LATENT_RETAINED_INVOCATION_PLATFORM_FAILURE = 3,
} latent_retained_invocation_outcome_kind;

/* Exactly the member identified by kind is non-null. */
typedef struct latent_retained_invocation_outcome {
    latent_retained_invocation_outcome_kind kind;
    const latent_activation_success_summary *success;
    const latent_declared_error *declared_error;
    const latent_platform_error *platform_failure;
} latent_retained_invocation_outcome;

typedef struct latent_activation_status {
    latent_string activation_id;
    latent_string phase;
    bool has_terminal_state;
    latent_string terminal_state;
    bool has_terminal_outcome;
    latent_retained_invocation_outcome terminal_outcome;
    bool has_final_consumption;
    latent_budget_consumption final_consumption;
    uint64_t last_updated_unix_millis;
    bool has_terminal_at_unix_millis;
    uint64_t terminal_at_unix_millis;
    const latent_key_value *metadata;
    size_t metadata_count;
} latent_activation_status;

/* Every asynchronous operation invokes its callback exactly once, with exactly
   one result/outcome/status/response or transport_error pointer non-null.
   Callbacks may run inline before the initiating method returns. Result/error
   pointers and nested data are borrowed until the callback returns; copy data
   that must outlive it. An invocation handle may be compared during its callback,
   but must not be retained for use afterward. The client and user_data must
   remain valid until every outstanding callback has completed. */
typedef void (*latent_invoke_callback)(
    latent_invocation *invocation,
    const latent_invocation_outcome *outcome,
    const latent_transport_error *transport_error,
    void *user_data);

typedef void (*latent_get_activation_callback)(
    latent_client *client,
    const latent_activation_status *status,
    const latent_transport_error *transport_error,
    void *user_data);

/* Invoked exactly once per cancel operation, with exactly one of response and
   transport_error non-null. The response/error and all nested data are borrowed
   only until this callback returns; copy anything that must be retained. */
typedef void (*latent_cancel_callback)(
    latent_client *client,
    const latent_cancel_response *response,
    const latent_transport_error *transport_error,
    void *user_data);

/* Request data and its nested pointers are borrowed until the method returns.
   An asynchronous implementation must copy any request data it retains. Client
   and user_data instead follow the outstanding-callback lifetime above. */
typedef struct latent_client_vtable {
    /* Request and all nested data are borrowed until invoke returns. An
       asynchronous implementation must copy the data it retains. The returned
       handle is local operation identity, not a persistent activation ID. */
    latent_invocation *(*invoke)(
        latent_client *client,
        const latent_invoke_request *request,
        latent_invoke_callback callback,
        void *user_data);

    /* Cancel by a known activation ID, including while invoke is pending or
       after its response was lost. Arguments are borrowed until cancel returns;
       asynchronous implementations must copy retained activation ID/reason data.
       Transport failure is reported separately from the three dispositions. */
    void (*cancel)(
        latent_client *client,
        latent_string activation_id,
        latent_string reason,
        latent_cancel_callback callback,
        void *user_data);

    void (*get_activation)(
        latent_client *client,
        latent_string activation_id,
        latent_get_activation_callback callback,
        void *user_data);

    /* Destroy only after every outstanding operation callback has completed. */
    void (*destroy)(latent_client *client);
} latent_client_vtable;

#ifdef __cplusplus
}
#endif

#endif
