#ifndef LSF_C_EXAMPLE_COMMON_H
#define LSF_C_EXAMPLE_COMMON_H

#include <latent/transport.h>

#define EX_TEXT(value) ((latent_string){value, sizeof(value) - 1u})

typedef struct ex_target {
    latent_string service;
    latent_string route;
    latent_string contract;
    latent_string function;
    latent_string publication;
    latent_string component_digest;
} ex_target;

typedef struct ex_config {
    char input[16385];
    uint8_t credential[257];
    size_t credential_length;
    latent_string endpoint;
    latent_string tenant;
    latent_string upstream_url;
    latent_string policy_document;
    ex_target targets[3];
    int control_fd;
} ex_config;

typedef struct ex_receipt {
    char operation_id[257];
    char tenant[257];
    char id[257];
    int32_t record_kind;
    uint64_t generation;
    char digest[257];
    bool revoked;
} ex_receipt;

typedef struct ex_result {
    unsigned callbacks;
    bool valid;
    bool failed;
    int32_t category;
    bool has_grpc;
    int32_t grpc;
    bool dispatched;
    int32_t outcome;
    char identity[257];
    bool audit_absent;
    bool success;
    bool declared;
    bool platform;
    char platform_code[65];
    uint8_t payload[512];
    size_t payload_length;
    char media_type[129];
    bool terminal;
    int32_t disposition;
    bool has_policy;
    uint64_t generation;
    bool has_receipt;
    ex_receipt receipt;
    size_t count;
    bool has_page;
    bool has_cursor;
    char cursor[161];
    size_t cursor_length;
    char first_id[257];
    char contract[257];
    char provider_binding[257];
    char provider_policy[257];
} ex_result;

bool ex_config_load(ex_config *config, int argc, char **argv);
void ex_config_close(ex_config *config);
bool ex_mode(ex_config *config, const char *value);
bool ex_marker(ex_config *config, const char *prefix, const char *token);
uint64_t ex_now(void);
void ex_pause(void);
latent_string ex_string(const char *value);
latent_profile_call_options ex_options(uint32_t timeout);
latent_transport *ex_client(const ex_config *config, bool foreign, bool denied, bool small);
bool ex_wait(latent_transport *client, ex_result *result, uint64_t deadline);
bool ex_close(latent_transport **client);
bool ex_guest(const ex_result *result, uint64_t expected);
bool ex_receipt_equal(const ex_receipt *left, const ex_receipt *right);
latent_profile_call *ex_invoke(const ex_config *config, latent_transport *client, unsigned provider,
                               const char *suffix, const char *function, bool foreign, uint32_t timeout,
                               ex_result *result);
void ex_invoked(const latent_profile_invoke_result *response, const latent_profile_client_failure *failure, void *data);
void ex_cancelled(const latent_profile_cancel_result *response, const latent_profile_client_failure *failure, void *data);
void ex_status(const latent_profile_get_activation_result *response, const latent_profile_client_failure *failure, void *data);
void ex_policy(const latent_profile_get_policy_result *response, const latent_profile_client_failure *failure, void *data);
void ex_policies(const latent_profile_list_policies_result *response, const latent_profile_client_failure *failure, void *data);
void ex_capabilities(const latent_profile_list_capabilities_result *response, const latent_profile_client_failure *failure, void *data);
void ex_applied(const latent_profile_apply_policy_result *response, const latent_profile_client_failure *failure, void *data);
void ex_operation(const latent_profile_get_policy_operation_result *response, const latent_profile_client_failure *failure, void *data);

#endif
