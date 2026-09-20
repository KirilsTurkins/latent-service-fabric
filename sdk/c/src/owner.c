#include "internal.h"

#include <arpa/inet.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef union lsf_allocation {
    size_t size;
    max_align_t alignment;
} lsf_allocation;

static void *default_allocate(size_t size, void *context) { (void)context; return malloc(size); }
static void default_deallocate(void *pointer, void *context) { (void)context; free(pointer); }

void *lsf_allocate(latent_transport *owner, size_t size) {
    if (size > SIZE_MAX - sizeof(lsf_allocation)) return NULL;
    size_t total = size + sizeof(lsf_allocation);
    if (owner != NULL && total > owner->config.maximum_owned_bytes - owner->usage.owned_bytes) {
        owner->allocation_failed = true;
        return NULL;
    }
    lsf_allocation *allocation = owner == NULL ? malloc(total)
        : owner->allocator.allocate(total, owner->allocator.context);
    if (allocation == NULL) { if (owner != NULL) owner->allocation_failed = true; return NULL; }
    allocation->size = total;
    if (owner != NULL) {
        owner->usage.owned_bytes += total;
        if (owner->usage.owned_bytes > owner->usage.peak_owned_bytes) owner->usage.peak_owned_bytes = owner->usage.owned_bytes;
    }
    return allocation + 1;
}

void lsf_deallocate(latent_transport *owner, void *pointer) {
    if (pointer == NULL) return;
    lsf_allocation *allocation = (lsf_allocation *)pointer - 1;
    if (owner == NULL) free(allocation);
    else {
        owner->usage.owned_bytes -= allocation->size;
        owner->allocator.deallocate(allocation, owner->allocator.context);
    }
}

static void wipe(void *pointer, size_t length) {
    volatile uint8_t *bytes = pointer;
    while (length != 0) { *bytes++ = 0; --length; }
}

latent_transport_config latent_transport_defaults(void) {
    return (latent_transport_config){.timeout_millis = 5000, .connect_timeout_millis = 1000,
        .maximum_in_flight = 4, .maximum_queued = 4, .maximum_retained_calls = 16,
        .maximum_request_bytes = 131072, .maximum_response_bytes = 1048576,
        .maximum_decoded_bytes = 2097152, .maximum_owned_bytes = 16777216};
}

static bool ascii(latent_string value, size_t maximum, bool nonempty) {
    if (value.length > maximum || (nonempty && value.length == 0)
        || (value.length != 0 && value.data == NULL)) return false;
    for (size_t index = 0; index < value.length; ++index) {
        if ((unsigned char)value.data[index] < 0x21 || (unsigned char)value.data[index] > 0x7e) return false;
    }
    return true;
}

static bool endpoint(latent_transport *owner, latent_string input) {
    if (!ascii(input, 86, true) || input.length < 13 || memcmp(input.data, "http://", 7) != 0) return false;
    size_t length = input.length - 7;
    if (length >= sizeof(owner->authority)) return false;
    memcpy(owner->authority, input.data + 7, length);
    owner->authority[length] = 0;
    char host[64];
    const char *port;
    bool ipv6 = owner->authority[0] == '[';
    const char *separator = ipv6 ? strchr(owner->authority, ']') : strrchr(owner->authority, ':');
    if (separator == NULL || (ipv6 && separator[1] != ':')) return false;
    size_t host_length = (size_t)(separator - owner->authority) - (ipv6 ? 1u : 0u);
    if (host_length == 0 || host_length >= sizeof(host)) return false;
    memcpy(host, owner->authority + (ipv6 ? 1 : 0), host_length);
    host[host_length] = 0;
    port = separator + (ipv6 ? 2 : 1);
    size_t port_length = strlen(port);
    uint64_t number;
    if (!latent_profile_parse_u64((latent_string){port, port_length}, &number) || number == 0 || number > 65535) return false;
    if (ipv6) {
        struct sockaddr_in6 *address = (void *)&owner->address;
        address->sin6_family = AF_INET6;
        address->sin6_port = htons((uint16_t)number);
        if (inet_pton(AF_INET6, host, &address->sin6_addr) != 1 || !IN6_IS_ADDR_LOOPBACK(&address->sin6_addr)) return false;
        owner->address_length = sizeof(*address);
    } else {
        struct sockaddr_in *address = (void *)&owner->address;
        address->sin_family = AF_INET;
        address->sin_port = htons((uint16_t)number);
        if (inet_pton(AF_INET, host, &address->sin_addr) != 1 || (ntohl(address->sin_addr.s_addr) >> 24) != 127) return false;
        owner->address_length = sizeof(*address);
    }
    return true;
}

static latent_profile_client_failure simple_failure(latent_profile_failure_category category) {
    return (latent_profile_client_failure){.category = category,
        .message = LSF_TEXT("bounded C RPC failed"), .outcome = LATENT_PROFILE_OUTCOME_KNOWLEDGE_NOT_DISPATCHED};
}

bool latent_transport_create(const latent_transport_config *config, latent_transport **output,
                             latent_profile_client_failure *failure) {
    if (output != NULL) *output = NULL;
    if (failure != NULL) *failure = simple_failure(LATENT_PROFILE_FAILURE_CATEGORY_INVALID_REQUEST);
    if (config == NULL || output == NULL || config->timeout_millis == 0 || config->timeout_millis > LSF_MAX_TIMEOUT
        || config->connect_timeout_millis == 0 || config->connect_timeout_millis > LSF_MAX_TIMEOUT
        || config->maximum_in_flight == 0 || config->maximum_in_flight > 32
        || config->maximum_queued > 128 || config->maximum_retained_calls == 0 || config->maximum_retained_calls > 256
        || config->maximum_request_bytes == 0 || config->maximum_request_bytes > 1048576
        || config->maximum_response_bytes == 0 || config->maximum_response_bytes > 1048576
        || config->maximum_decoded_bytes == 0 || config->maximum_decoded_bytes > 8388608
        || config->maximum_owned_bytes < sizeof(latent_transport) || config->maximum_owned_bytes > 134217728
        || !ascii(config->tenant, 256, true)
        || !ascii((latent_string){(const char *)config->bearer_token.data, config->bearer_token.length}, 256, true)
        || ((config->allocator.allocate == NULL) != (config->allocator.deallocate == NULL))) return false;
    latent_transport_allocator allocator = config->allocator;
    if (allocator.allocate == NULL) allocator = (latent_transport_allocator){default_allocate, default_deallocate, NULL};
    latent_transport *owner = allocator.allocate(sizeof(*owner), allocator.context);
    if (owner == NULL) { if (failure != NULL) *failure = simple_failure(LATENT_PROFILE_FAILURE_CATEGORY_LIMIT); return false; }
    memset(owner, 0, sizeof(*owner));
    owner->config = *config;
    owner->allocator = allocator;
    owner->socket_fd = -1;
    if (!endpoint(owner, config->endpoint)) { allocator.deallocate(owner, allocator.context); return false; }
    memcpy(owner->tenant, config->tenant.data, config->tenant.length);
    memcpy(owner->authorization, "Bearer ", 7);
    memcpy(owner->authorization + 7, config->bearer_token.data, config->bearer_token.length);
    owner->authorization_length = 7 + config->bearer_token.length;
    owner->config.tenant = (latent_string){owner->tenant, config->tenant.length};
    owner->config.endpoint = (latent_string){NULL, 0};
    owner->config.bearer_token = (latent_bytes){NULL, 0};
    owner->profile.owner = owner;
    owner->legacy.owner = owner;
    owner->usage.owned_bytes = sizeof(*owner);
    owner->usage.peak_owned_bytes = sizeof(*owner);
    *output = owner;
    if (failure != NULL) memset(failure, 0, sizeof(*failure));
    return true;
}

latent_profile_client *latent_transport_profile(latent_transport *owner) { return owner == NULL ? NULL : &owner->profile; }
latent_client *latent_transport_legacy(latent_transport *owner) { return owner == NULL ? NULL : &owner->legacy; }

void lsf_complete(latent_profile_call *call) {
    if (call->completed) return;
    call->completed = true;
    if (call->active) --call->owner->usage.in_flight;
    else --call->owner->usage.queued;
}

static void failure_fields(latent_profile_call *call, latent_profile_failure_category category) {
    call->failure.category = category;
    call->failure.message = LSF_TEXT("bounded C RPC failed");
    call->failure.dispatched = call->dispatched;
    call->failure.identity = call->metadata.identity;
    call->failure.outcome = call->dispatched ? LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN
                                           : LATENT_PROFILE_OUTCOME_KNOWLEDGE_NOT_DISPATCHED;
    call->failure.has_grpc_status = call->has_grpc_status;
    call->failure.grpc_status = call->grpc_status;
    call->failure.has_audit_ack = call->metadata.has_audit_ack;
    call->failure.audit_ack = call->metadata.audit_ack;
    call->failure.has_audit_status = call->metadata.has_audit_status;
    call->failure.audit_status = call->metadata.audit_status;
    call->failure.has_audit_attempt_sequence = call->metadata.has_audit_attempt_sequence;
    call->failure.audit_attempt_sequence = call->metadata.audit_attempt_sequence;
}

void lsf_fail(latent_profile_call *call, latent_profile_failure_category category) {
    if (call->completed) return;
    failure_fields(call, category);
    lsf_complete(call);
}

static void dispatch(latent_profile_call *call) {
    ++call->owner->callback_depth;
    if (call->legacy) {
        lsf_legacy_complete(call);
        --call->owner->callback_depth;
        return;
    }
    const latent_profile_client_failure *failure = call->failure.category == 0 ? NULL : &call->failure;
    switch (call->operation) {
        case LSF_INVOKE: call->callback.invoke(failure == NULL ? &call->result.invoke : NULL, failure, call->user_data); break;
        case LSF_CANCEL: call->callback.cancel(failure == NULL ? &call->result.cancel : NULL, failure, call->user_data); break;
        case LSF_GET_ACTIVATION: call->callback.get_activation(failure == NULL ? &call->result.get_activation : NULL, failure, call->user_data); break;
        case LSF_GET_POLICY: call->callback.get_policy(failure == NULL ? &call->result.get_policy : NULL, failure, call->user_data); break;
        case LSF_LIST_POLICIES: call->callback.list_policies(failure == NULL ? &call->result.list_policies : NULL, failure, call->user_data); break;
        case LSF_LIST_CAPABILITIES: call->callback.list_capabilities(failure == NULL ? &call->result.list_capabilities : NULL, failure, call->user_data); break;
        case LSF_APPLY_POLICY: call->callback.apply_policy(failure == NULL ? &call->result.apply_policy : NULL, failure, call->user_data); break;
        case LSF_GET_POLICY_OPERATION: call->callback.get_policy_operation(failure == NULL ? &call->result.get_policy_operation : NULL, failure, call->user_data); break;
    }
    --call->owner->callback_depth;
}

void lsf_notify(latent_transport *owner) {
    if (owner->notifying) return;
    owner->notifying = true;
    for (uint32_t index = 0; index < owner->config.maximum_retained_calls; ++index) {
        latent_profile_call *call = owner->calls;
        while (call != NULL && (!call->completed || call->notified || call->in_callback)) call = call->next;
        if (call == NULL) break;
        if (call->failure.category == 0 && lsf_now() >= call->deadline)
            failure_fields(call, LATENT_PROFILE_FAILURE_CATEGORY_DEADLINE);
        call->in_callback = true;
        dispatch(call);
        call->in_callback = false;
        call->notified = true;
        --owner->usage.callbacks_pending;
        lsf_arena_clear(&call->arena);
        lsf_deallocate(owner, call->request);
        lsf_deallocate(owner, call->response);
        call->request = NULL;
        call->response = NULL;
        if (call->legacy) lsf_release(call);
    }
    owner->notifying = false;
}

void lsf_release(latent_profile_call *call) {
    if (call == NULL || !call->notified || call->in_callback) return;
    latent_transport *owner = call->owner;
    latent_profile_call **position = &owner->calls;
    while (*position != NULL && *position != call) position = &(*position)->next;
    if (*position == NULL) return;
    *position = call->next;
    --owner->usage.retained_calls;
    lsf_deallocate(owner, call);
}

static latent_profile_request_identity identity(lsf_operation operation, const void *request) {
    latent_profile_request_identity result = {0};
    if (request == NULL) return result;
    if (operation == LSF_INVOKE) {
        const latent_profile_invoke_request *value = request;
        result.has_activation_id = value->has_activation_id;
        result.activation_id = value->activation_id;
    } else if (operation == LSF_CANCEL || operation == LSF_GET_ACTIVATION) {
        result.has_activation_id = true;
        result.activation_id = *(const latent_string *)request;
    } else if (operation == LSF_APPLY_POLICY) {
        result.has_operation_id = true;
        result.operation_id = ((const latent_profile_apply_policy_request *)request)->operation_id;
    } else if (operation == LSF_GET_POLICY_OPERATION) {
        result.has_operation_id = true;
        result.operation_id = ((const latent_profile_get_policy_operation_request *)request)->operation_id;
    }
    return result;
}

latent_profile_call *lsf_start(latent_transport *owner, lsf_operation operation, const void *request,
                              const latent_profile_call_options *options, lsf_callback callback,
                              void *user_data, const lsf_legacy_callback *legacy_callback) {
    latent_profile_call temporary = {.owner = owner, .operation = operation, .callback = callback,
                                    .user_data = user_data, .legacy = legacy_callback != NULL};
    if (legacy_callback != NULL) temporary.legacy_callback = *legacy_callback;
    temporary.metadata.identity = identity(operation, request);
    temporary.failure = simple_failure(LATENT_PROFILE_FAILURE_CATEGORY_INVALID_REQUEST);
    temporary.failure.identity = temporary.metadata.identity;
    uint64_t started = lsf_now();
    uint64_t timeout = options != NULL && options->has_timeout_millis ? options->timeout_millis : owner->config.timeout_millis;
    if (timeout > LSF_MAX_TIMEOUT || request == NULL) { dispatch(&temporary); return NULL; }
    if (timeout > owner->config.timeout_millis) timeout = owner->config.timeout_millis;
    if (operation == LSF_INVOKE) {
        const latent_profile_invoke_request *invoke = request;
        if (invoke->has_deadline_unix_millis) {
            struct timespec current;
            if (clock_gettime(CLOCK_REALTIME, &current) != 0) { dispatch(&temporary); return NULL; }
            uint64_t wall = (uint64_t)current.tv_sec * 1000 + (uint64_t)current.tv_nsec / 1000000;
            uint64_t remaining = invoke->deadline_unix_millis <= wall ? 0 : invoke->deadline_unix_millis - wall;
            if (remaining < timeout) timeout = remaining;
        }
    }
    latent_string known = temporary.metadata.identity.has_activation_id ? temporary.metadata.identity.activation_id
                         : temporary.metadata.identity.operation_id;
    if (known.length > LSF_MAX_ID || (known.length != 0 && known.data == NULL)) { dispatch(&temporary); return NULL; }
    if (owner->stopped || timeout == 0) {
        temporary.failure.category = owner->stopped ? LATENT_PROFILE_FAILURE_CATEGORY_LOCAL_CANCELLED : LATENT_PROFILE_FAILURE_CATEGORY_DEADLINE;
        dispatch(&temporary); return NULL;
    }
    if (owner->usage.retained_calls >= owner->config.maximum_retained_calls
        || (owner->usage.in_flight >= owner->config.maximum_in_flight && owner->usage.queued >= owner->config.maximum_queued)) {
        temporary.failure.category = LATENT_PROFILE_FAILURE_CATEGORY_LIMIT; dispatch(&temporary); return NULL;
    }
    latent_profile_call *call = lsf_allocate(owner, sizeof(*call));
    if (call == NULL) { temporary.failure.category = LATENT_PROFILE_FAILURE_CATEGORY_LIMIT; dispatch(&temporary); return NULL; }
    *call = temporary;
    memset(&call->failure, 0, sizeof(call->failure));
    if (known.length != 0) memcpy(call->identity, known.data, known.length);
    if (call->metadata.identity.has_activation_id) call->metadata.identity.activation_id = (latent_string){call->identity, known.length};
    if (call->metadata.identity.has_operation_id) call->metadata.identity.operation_id = (latent_string){call->identity, known.length};
    call->deadline = started + timeout;
    call->arena = (lsf_arena){.owner = owner, .maximum = owner->config.maximum_decoded_bytes};
    call->maximum_response = owner->config.maximum_response_bytes;
    if (operation == LSF_LIST_CAPABILITIES && call->maximum_response > 131072) call->maximum_response = 131072;
    call->legacy_handle.call = call;
    call->next = owner->calls;
    owner->calls = call;
    ++owner->usage.retained_calls;
    ++owner->usage.callbacks_pending;
    call->active = owner->usage.in_flight < owner->config.maximum_in_flight;
    if (call->active) ++owner->usage.in_flight;
    else ++owner->usage.queued;
    size_t maximum_request = owner->config.maximum_request_bytes;
    if (operation >= LSF_GET_POLICY && maximum_request > 131072) maximum_request = 131072;
    if (operation == LSF_LIST_CAPABILITIES && maximum_request > 8192) maximum_request = 8192;
    if (!lsf_request_valid(call, request)) lsf_fail(call, LATENT_PROFILE_FAILURE_CATEGORY_INVALID_REQUEST);
    else {
        call->request = lsf_allocate(owner, maximum_request + 5);
        call->response = lsf_allocate(owner, call->maximum_response + 5);
        if (call->request == NULL || call->response == NULL) lsf_fail(call, LATENT_PROFILE_FAILURE_CATEGORY_LIMIT);
        else {
            size_t length = 0;
            bool limit = false;
            if (!lsf_encode(lsf_rpcs[operation].request, request, call->request + 5, maximum_request, &length, call->deadline, &limit)) {
                lsf_fail(call, lsf_now() >= call->deadline ? LATENT_PROFILE_FAILURE_CATEGORY_DEADLINE
                    : limit ? LATENT_PROFILE_FAILURE_CATEGORY_LIMIT : LATENT_PROFILE_FAILURE_CATEGORY_INVALID_REQUEST);
            } else {
                call->request[0] = 0;
                for (unsigned index = 0; index < 4; ++index) call->request[index + 1] = (uint8_t)(length >> (24 - 8 * index));
                call->request_length = length + 5;
                if (lsf_now() >= call->deadline) lsf_fail(call, LATENT_PROFILE_FAILURE_CATEGORY_DEADLINE);
            }
        }
    }
    if (call->completed) {
        call->in_callback = true;
        dispatch(call);
        call->in_callback = false;
        call->notified = true;
        --owner->usage.callbacks_pending;
        lsf_deallocate(owner, call->request);
        lsf_deallocate(owner, call->response);
        lsf_release(call);
        return NULL;
    }
    return call;
}

#define LSF_METHOD(method, operation_name, request_type, callback_type) \
static latent_profile_call *method(latent_profile_client *client, const request_type *request, \
        const latent_profile_call_options *options, callback_type callback, void *user_data) { \
    if (client == NULL || callback == NULL) return NULL; \
    return lsf_start(client->owner, operation_name, request, options, (lsf_callback){.method = callback}, user_data, NULL); \
}

LSF_METHOD(invoke, LSF_INVOKE, latent_profile_invoke_request, latent_profile_invoke_callback)
LSF_METHOD(cancel, LSF_CANCEL, latent_profile_cancel_request, latent_profile_cancel_callback)
LSF_METHOD(get_activation, LSF_GET_ACTIVATION, latent_profile_get_activation_request, latent_profile_get_activation_callback)
LSF_METHOD(get_policy, LSF_GET_POLICY, latent_profile_get_policy_request, latent_profile_get_policy_callback)
LSF_METHOD(list_policies, LSF_LIST_POLICIES, latent_profile_list_policies_request, latent_profile_list_policies_callback)
LSF_METHOD(list_capabilities, LSF_LIST_CAPABILITIES, latent_profile_list_capabilities_request, latent_profile_list_capabilities_callback)
LSF_METHOD(apply_policy, LSF_APPLY_POLICY, latent_profile_apply_policy_request, latent_profile_apply_policy_callback)
LSF_METHOD(get_policy_operation, LSF_GET_POLICY_OPERATION, latent_profile_get_policy_operation_request, latent_profile_get_policy_operation_callback)

static void cancel_local(latent_profile_call *call) {
    if (call == NULL || call->completed) return;
    latent_transport *owner = call->owner;
    lsf_fail(call, LATENT_PROFILE_FAILURE_CATEGORY_LOCAL_CANCELLED);
    if (call->dispatched) lsf_close_channel(owner, LATENT_PROFILE_FAILURE_CATEGORY_TRANSPORT);
    lsf_notify(owner);
}

static void destroy_profile(latent_profile_client *client) {
    if (client != NULL) (void)latent_transport_destroy(client->owner);
}

const latent_profile_client_vtable *latent_transport_profile_vtable(void) {
    static const latent_profile_client_vtable vtable = {
        invoke, cancel, get_activation, get_policy, list_policies, list_capabilities,
        apply_policy, get_policy_operation, cancel_local, lsf_release, destroy_profile
    };
    return &vtable;
}

void latent_transport_stop(latent_transport *owner) {
    if (owner == NULL) return;
    owner->stopped = true;
    owner->usage.stopped = true;
    lsf_close_channel(owner, LATENT_PROFILE_FAILURE_CATEGORY_LOCAL_CANCELLED);
    wipe(owner->authorization, sizeof(owner->authorization));
    owner->authorization_length = 0;
    lsf_notify(owner);
}

bool latent_transport_shutdown(latent_transport *owner, uint32_t timeout_millis) {
    if (owner == NULL || timeout_millis > LSF_MAX_TIMEOUT) return false;
    uint64_t deadline = lsf_now() + timeout_millis;
    latent_transport_stop(owner);
    return !owner->notifying && owner->callback_depth == 0 && owner->usage.callbacks_pending == 0 && lsf_now() <= deadline;
}

bool latent_transport_destroy(latent_transport *owner) {
    if (owner == NULL) return true;
    if (owner->usage.retained_calls != 0 || owner->usage.callbacks_pending != 0
        || owner->polling || owner->notifying || owner->callback_depth != 0) return false;
    latent_transport_stop(owner);
    latent_transport_allocator allocator = owner->allocator;
    wipe(owner, sizeof(*owner));
    allocator.deallocate(owner, allocator.context);
    return true;
}

latent_transport_usage latent_transport_get_usage(const latent_transport *owner) {
    return owner == NULL ? (latent_transport_usage){0} : owner->usage;
}

bool latent_transport_poll(latent_transport *owner, uint32_t maximum_wait_millis) {
    if (owner == NULL || maximum_wait_millis > 1000 || owner->polling || owner->notifying || owner->callback_depth != 0) return false;
    owner->polling = true;
    uint64_t now = lsf_now();
    uint64_t nearest = now + maximum_wait_millis;
    bool expired_channel = false;
    for (latent_profile_call *call = owner->calls; call != NULL; call = call->next) {
        if (call->completed) continue;
        if (now >= call->deadline) {
            expired_channel |= call->dispatched;
            lsf_fail(call, LATENT_PROFILE_FAILURE_CATEGORY_DEADLINE);
        } else if (call->deadline < nearest) nearest = call->deadline;
    }
    if (expired_channel) lsf_close_channel(owner, LATENT_PROFILE_FAILURE_CATEGORY_TRANSPORT);
    for (latent_profile_call *call = owner->calls; call != NULL; call = call->next) {
        if (call->completed) continue;
        if (!call->active && owner->usage.in_flight < owner->config.maximum_in_flight) {
            call->active = true;
            --owner->usage.queued;
            ++owner->usage.in_flight;
        }
        if (call->active && owner->socket_fd < 0 && !lsf_channel_open(owner, call->deadline)) {
            lsf_close_channel(owner, owner->allocation_failed ? LATENT_PROFILE_FAILURE_CATEGORY_LIMIT : LATENT_PROFILE_FAILURE_CATEGORY_TRANSPORT);
            break;
        }
    }
    now = lsf_now();
    if (owner->socket_fd >= 0) (void)lsf_channel_step(owner, (uint32_t)(nearest > now ? nearest - now : 0));
    now = lsf_now();
    expired_channel = false;
    for (latent_profile_call *call = owner->calls; call != NULL; call = call->next) {
        if (!call->completed && now >= call->deadline) {
            expired_channel |= call->dispatched;
            lsf_fail(call, LATENT_PROFILE_FAILURE_CATEGORY_DEADLINE);
        }
    }
    if (expired_channel) lsf_close_channel(owner, LATENT_PROFILE_FAILURE_CATEGORY_TRANSPORT);
    lsf_notify(owner);
    owner->polling = false;
    return true;
}
