#ifndef LSF_C_INTERNAL_H
#define LSF_C_INTERNAL_H

#include "wire_generated.h"

#include <nghttp2/nghttp2.h>
#include <sys/socket.h>

#define LSF_TEXT(value) ((latent_string){value, sizeof(value) - 1u})
#define LSF_MAX_HEADER_BYTES 16384u
#define LSF_MAX_HEADER_COUNT 32u
#define LSF_MAX_ID 256u
#define LSF_MAX_TIMEOUT 300000u

typedef enum lsf_operation {
    LSF_INVOKE, LSF_CANCEL, LSF_GET_ACTIVATION, LSF_GET_POLICY,
    LSF_LIST_POLICIES, LSF_LIST_CAPABILITIES, LSF_APPLY_POLICY, LSF_GET_POLICY_OPERATION
} lsf_operation;

typedef union lsf_callback {
    latent_profile_invoke_callback invoke;
    latent_profile_cancel_callback cancel;
    latent_profile_get_activation_callback get_activation;
    latent_profile_get_policy_callback get_policy;
    latent_profile_list_policies_callback list_policies;
    latent_profile_list_capabilities_callback list_capabilities;
    latent_profile_apply_policy_callback apply_policy;
    latent_profile_get_policy_operation_callback get_policy_operation;
} lsf_callback;

typedef union lsf_result {
    latent_profile_invoke_result invoke;
    latent_profile_cancel_result cancel;
    latent_profile_get_activation_result get_activation;
    latent_profile_get_policy_result get_policy;
    latent_profile_list_policies_result list_policies;
    latent_profile_list_capabilities_result list_capabilities;
    latent_profile_apply_policy_result apply_policy;
    latent_profile_get_policy_operation_result get_policy_operation;
} lsf_result;

struct latent_profile_client { latent_transport *owner; };

struct latent_profile_call {
    latent_transport *owner;
    latent_profile_call *next;
    lsf_operation operation;
    lsf_callback callback;
    void *user_data;
    bool completed;
    bool notified;
    bool in_callback;
    bool dispatched;
    bool active;
    bool remote_end;
    int32_t stream_id;
    uint64_t deadline;
    uint8_t *request;
    size_t request_length;
    size_t request_position;
    uint8_t *response;
    size_t response_length;
    size_t maximum_response;
    lsf_arena arena;
    lsf_result result;
    latent_profile_client_failure failure;
    latent_profile_response_metadata metadata;
    char identity[LSF_MAX_ID + 1];
    char policy_id[LSF_MAX_ID + 1];
    size_t policy_id_length;
    int32_t record_kind;
    uint32_t page_size;
    uint32_t header_blocks;
    uint32_t header_count;
    size_t header_bytes;
    char header_names[LSF_MAX_HEADER_COUNT][65];
    bool status_ok;
    bool content_type_ok;
    bool has_grpc_status;
    int32_t grpc_status;
    char audit_status[65];
    char platform_details[10925];
    size_t platform_details_length;
    char unsupported[257];
};

struct latent_transport {
    latent_transport_config config;
    latent_transport_allocator allocator;
    latent_profile_client profile;
    latent_profile_call *calls;
    latent_transport_usage usage;
    struct sockaddr_storage address;
    socklen_t address_length;
    char authority[80];
    char tenant[257];
    char authorization[264];
    size_t authorization_length;
    int socket_fd;
    bool connecting;
    bool stopped;
    bool polling;
    bool notifying;
    bool channel_failed;
    bool allocation_failed;
    uint32_t callback_depth;
    uint64_t connect_deadline;
    nghttp2_session *session;
    const uint8_t *send_data;
    size_t send_length;
    size_t send_position;
};

latent_profile_call *lsf_start(latent_transport *owner, lsf_operation operation,
                              const void *request, const latent_profile_call_options *options,
                              lsf_callback callback, void *user_data);
void lsf_notify(latent_transport *owner);
void lsf_fail(latent_profile_call *call, latent_profile_failure_category category);
void lsf_complete(latent_profile_call *call);
void lsf_close_channel(latent_transport *owner, latent_profile_failure_category category);
void lsf_release(latent_profile_call *call);
bool lsf_channel_open(latent_transport *owner, uint64_t deadline);
bool lsf_channel_step(latent_transport *owner, uint32_t wait_millis);
bool lsf_channel_submit(latent_profile_call *call);
bool lsf_request_valid(latent_profile_call *call, const void *request);
bool lsf_response_valid(latent_profile_call *call);
void lsf_finish_response(latent_profile_call *call);
void lsf_unsupported(latent_profile_call *call, const char *field, latent_string value);

#endif
