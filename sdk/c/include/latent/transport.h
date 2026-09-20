#ifndef LATENT_TRANSPORT_H
#define LATENT_TRANSPORT_H

#include "profile.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct latent_transport latent_transport;

typedef struct latent_transport_allocator {
    void *(*allocate)(size_t size, void *context);
    void (*deallocate)(void *pointer, void *context);
    void *context;
} latent_transport_allocator;

typedef struct latent_transport_config {
    latent_string endpoint;
    latent_string tenant;
    latent_bytes bearer_token;
    uint32_t timeout_millis;
    uint32_t connect_timeout_millis;
    uint32_t maximum_in_flight;
    uint32_t maximum_queued;
    uint32_t maximum_retained_calls;
    size_t maximum_request_bytes;
    size_t maximum_response_bytes;
    size_t maximum_decoded_bytes;
    size_t maximum_owned_bytes;
    latent_transport_allocator allocator;
} latent_transport_config;

typedef struct latent_transport_usage {
    size_t owned_bytes;
    size_t peak_owned_bytes;
    size_t http2_bytes;
    uint32_t in_flight;
    uint32_t queued;
    uint32_t retained_calls;
    uint32_t callbacks_pending;
    uint32_t sockets;
    uint32_t sessions;
    bool stopped;
} latent_transport_usage;

latent_transport_config latent_transport_defaults(void);
bool latent_transport_create(const latent_transport_config *config,
                             latent_transport **output,
                             latent_profile_client_failure *failure);
latent_profile_client *latent_transport_profile(latent_transport *transport);
const latent_profile_client_vtable *latent_transport_profile_vtable(void);
latent_client *latent_transport_legacy(latent_transport *transport);
const latent_client_vtable *latent_transport_legacy_vtable(void);
bool latent_transport_poll(latent_transport *transport, uint32_t maximum_wait_millis);
void latent_transport_stop(latent_transport *transport);
bool latent_transport_shutdown(latent_transport *transport, uint32_t timeout_millis);
bool latent_transport_destroy(latent_transport *transport);
latent_transport_usage latent_transport_get_usage(const latent_transport *transport);

#ifdef __cplusplus
}
#endif

#endif
