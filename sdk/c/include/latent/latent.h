#ifndef LATENT_SDK_H
#define LATENT_SDK_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct latent_client latent_client;
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

typedef struct latent_resource_budget {
    uint64_t cpu_fuel;
    uint64_t memory_bytes;
    bool has_wall_deadline;
    uint64_t wall_deadline_unix_millis;
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
    const latent_key_value *details;
    size_t detail_count;
} latent_platform_error;

typedef void (*latent_invoke_callback)(
    latent_invocation *invocation,
    const latent_invoke_response *response,
    const latent_platform_error *error,
    void *user_data);

typedef struct latent_client_vtable {
    latent_invocation *(*invoke)(
        latent_client *client,
        const latent_invoke_request *request,
        latent_invoke_callback callback,
        void *user_data);

    bool (*cancel)(
        latent_client *client,
        latent_invocation *invocation,
        latent_string reason);

    void (*destroy)(latent_client *client);
} latent_client_vtable;

#ifdef __cplusplus
}
#endif

#endif
