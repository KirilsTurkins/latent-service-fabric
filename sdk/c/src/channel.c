#include "internal.h"

#include <errno.h>
#include <inttypes.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

typedef union lsf_http2_allocation {
    size_t size;
    max_align_t alignment;
} lsf_http2_allocation;

static void *http2_allocate(size_t size, void *context) {
    latent_transport *owner = context;
    if (size > SIZE_MAX - sizeof(lsf_http2_allocation)) return NULL;
    size_t total = size + sizeof(lsf_http2_allocation);
    lsf_http2_allocation *allocation = lsf_allocate(owner, total);
    if (allocation == NULL) return NULL;
    allocation->size = total;
    owner->usage.http2_bytes += total;
    return allocation + 1;
}

static void http2_free(void *pointer, void *context) {
    if (pointer == NULL) return;
    latent_transport *owner = context;
    lsf_http2_allocation *allocation = (lsf_http2_allocation *)pointer - 1;
    owner->usage.http2_bytes -= allocation->size;
    lsf_deallocate(owner, allocation);
}

static void *http2_callocate(size_t count, size_t size, void *context) {
    if (count != 0 && size > SIZE_MAX / count) return NULL;
    void *pointer = http2_allocate(count * size, context);
    if (pointer != NULL) memset(pointer, 0, count * size);
    return pointer;
}

static void *http2_reallocate(void *pointer, size_t size, void *context) {
    if (pointer == NULL) return http2_allocate(size, context);
    if (size == 0) { http2_free(pointer, context); return NULL; }
    lsf_http2_allocation *allocation = (lsf_http2_allocation *)pointer - 1;
    size_t previous = allocation->size - sizeof(*allocation);
    void *replacement = http2_allocate(size, context);
    if (replacement == NULL) return NULL;
    memcpy(replacement, pointer, size < previous ? size : previous);
    http2_free(pointer, context);
    return replacement;
}

static int stream_failure(latent_profile_call *call, latent_profile_failure_category category) {
    lsf_fail(call, category);
    call->owner->channel_failed = true;
    return NGHTTP2_ERR_CALLBACK_FAILURE;
}

static int begin_headers(nghttp2_session *session, const nghttp2_frame *frame, void *context) {
    latent_transport *owner = context;
    if (frame->hd.type == NGHTTP2_PUSH_PROMISE) { owner->channel_failed = true; return NGHTTP2_ERR_CALLBACK_FAILURE; }
    latent_profile_call *call = nghttp2_session_get_stream_user_data(session, frame->hd.stream_id);
    if (call == NULL) return 0;
    if (++call->header_blocks > 2) return stream_failure(call, LATENT_PROFILE_FAILURE_CATEGORY_DECODE);
    return 0;
}

static bool header_equal(const uint8_t *value, size_t length, const char *expected) {
    return strlen(expected) == length && memcmp(value, expected, length) == 0;
}

static void audit_ack(latent_profile_call *call) {
    latent_profile_response_metadata *metadata = &call->metadata;
    metadata->has_audit_ack = false;
    if (!metadata->has_audit_status) return;
    int32_t code = 0;
    if (lsf_text_equal(metadata->audit_status, LSF_TEXT("durable"))) code = LATENT_PROFILE_AUDIT_ACK_STATUS_DURABLE;
    else if (lsf_text_equal(metadata->audit_status, LSF_TEXT("outcome-unknown"))) code = LATENT_PROFILE_AUDIT_ACK_STATUS_OUTCOME_UNKNOWN;
    else if (lsf_text_equal(metadata->audit_status, LSF_TEXT("audit-unavailable"))) code = LATENT_PROFILE_AUDIT_ACK_STATUS_AUDIT_UNAVAILABLE;
    else if (lsf_text_equal(metadata->audit_status, LSF_TEXT("disabled"))) code = LATENT_PROFILE_AUDIT_ACK_STATUS_DISABLED;
    if (code != 0) {
        metadata->has_audit_ack = true;
        metadata->audit_ack = (latent_profile_audit_ack){.status = code,
            .has_attempt_sequence = metadata->has_audit_attempt_sequence,
            .attempt_sequence = metadata->audit_attempt_sequence};
    }
}

static int header(nghttp2_session *session, const nghttp2_frame *frame, const uint8_t *name,
                  size_t name_length, const uint8_t *value, size_t length, uint8_t flags, void *context) {
    (void)flags;
    (void)context;
    latent_profile_call *call = nghttp2_session_get_stream_user_data(session, frame->hd.stream_id);
    if (call == NULL) return 0;
    if (call->completed) return NGHTTP2_ERR_CALLBACK_FAILURE;
    if (name_length > 64 || name_length == 0 || call->header_count >= LSF_MAX_HEADER_COUNT
        || name_length > LSF_MAX_HEADER_BYTES - call->header_bytes
        || length > LSF_MAX_HEADER_BYTES - call->header_bytes - name_length) {
        return stream_failure(call, LATENT_PROFILE_FAILURE_CATEGORY_LIMIT);
    }
    for (uint32_t index = 0; index < call->header_count; ++index) {
        if (strlen(call->header_names[index]) == name_length && memcmp(call->header_names[index], name, name_length) == 0)
            return stream_failure(call, LATENT_PROFILE_FAILURE_CATEGORY_DECODE);
    }
    memcpy(call->header_names[call->header_count++], name, name_length);
    call->header_bytes += name_length + length;
    if (header_equal(name, name_length, ":status")) {
        call->status_ok = header_equal(value, length, "200");
        if (!call->status_ok) return stream_failure(call, LATENT_PROFILE_FAILURE_CATEGORY_DECODE);
    } else if (header_equal(name, name_length, "content-type")) {
        call->content_type_ok = header_equal(value, length, "application/grpc") || header_equal(value, length, "application/grpc+proto");
        if (!call->content_type_ok) return stream_failure(call, LATENT_PROFILE_FAILURE_CATEGORY_DECODE);
    } else if (header_equal(name, name_length, "grpc-encoding")) {
        if (!header_equal(value, length, "identity")) return stream_failure(call, LATENT_PROFILE_FAILURE_CATEGORY_DECODE);
    } else if (header_equal(name, name_length, "grpc-status")) {
        uint64_t number;
        if (!latent_profile_parse_u64((latent_string){(const char *)value, length}, &number) || number > INT32_MAX)
            return stream_failure(call, LATENT_PROFILE_FAILURE_CATEGORY_DECODE);
        call->has_grpc_status = true;
        call->grpc_status = (int32_t)number;
    } else if (header_equal(name, name_length, "latent-audit-status")) {
        if (length == 0 || length > 64) return stream_failure(call, LATENT_PROFILE_FAILURE_CATEGORY_DECODE);
        for (size_t index = 0; index < length; ++index) {
            if (value[index] < 0x21 || value[index] > 0x7e) return stream_failure(call, LATENT_PROFILE_FAILURE_CATEGORY_DECODE);
        }
        memcpy(call->audit_status, value, length);
        call->metadata.has_audit_status = true;
        call->metadata.audit_status = (latent_string){call->audit_status, length};
        audit_ack(call);
    } else if (header_equal(name, name_length, "latent-audit-attempt")) {
        uint64_t number;
        if (!latent_profile_parse_u64((latent_string){(const char *)value, length}, &number))
            return stream_failure(call, LATENT_PROFILE_FAILURE_CATEGORY_DECODE);
        call->metadata.has_audit_attempt_sequence = true;
        call->metadata.audit_attempt_sequence = number;
        audit_ack(call);
    } else if (header_equal(name, name_length, "grpc-status-details-bin")) {
        if (length > sizeof(call->platform_details) - 1) return stream_failure(call, LATENT_PROFILE_FAILURE_CATEGORY_LIMIT);
        memcpy(call->platform_details, value, length);
        call->platform_details_length = length;
    }
    return 0;
}

static int data_chunk(nghttp2_session *session, uint8_t flags, int32_t stream_id,
                      const uint8_t *data, size_t length, void *context) {
    (void)flags;
    (void)context;
    latent_profile_call *call = nghttp2_session_get_stream_user_data(session, stream_id);
    if (call == NULL) return 0;
    if (call->completed) return NGHTTP2_ERR_CALLBACK_FAILURE;
    if (length > call->maximum_response + 5 - call->response_length) return stream_failure(call, LATENT_PROFILE_FAILURE_CATEGORY_LIMIT);
    memcpy(call->response + call->response_length, data, length);
    call->response_length += length;
    if (call->response_length >= 5) {
        uint32_t size = 0;
        for (unsigned index = 1; index < 5; ++index) size = (size << 8) | call->response[index];
        if (call->response[0] != 0) return stream_failure(call, LATENT_PROFILE_FAILURE_CATEGORY_DECODE);
        if (size > call->maximum_response) return stream_failure(call, LATENT_PROFILE_FAILURE_CATEGORY_LIMIT);
        if (call->response_length - 5 > size) return stream_failure(call, LATENT_PROFILE_FAILURE_CATEGORY_DECODE);
    }
    return 0;
}

static int frame_received(nghttp2_session *session, const nghttp2_frame *frame, void *context) {
    latent_transport *owner = context;
    if (frame->hd.type == NGHTTP2_GOAWAY || frame->hd.type == NGHTTP2_PUSH_PROMISE) {
        owner->channel_failed = true;
        return NGHTTP2_ERR_CALLBACK_FAILURE;
    }
    latent_profile_call *call = nghttp2_session_get_stream_user_data(session, frame->hd.stream_id);
    if (call != NULL && (frame->hd.type == NGHTTP2_HEADERS || frame->hd.type == NGHTTP2_DATA)
        && (frame->hd.flags & NGHTTP2_FLAG_END_STREAM) != 0) call->remote_end = true;
    return 0;
}

static int stream_closed(nghttp2_session *session, int32_t stream_id, uint32_t error_code, void *context) {
    (void)context;
    latent_profile_call *call = nghttp2_session_get_stream_user_data(session, stream_id);
    if (call == NULL) return 0;
    call->stream_id = 0;
    if (call->completed) return 0;
    if (error_code != NGHTTP2_NO_ERROR || !call->remote_end) lsf_fail(call, LATENT_PROFILE_FAILURE_CATEGORY_TRANSPORT);
    else lsf_finish_response(call);
    return 0;
}

static ssize_t request_data(nghttp2_session *session, int32_t stream_id, uint8_t *buffer,
                            size_t length, uint32_t *flags, nghttp2_data_source *source, void *context) {
    (void)session;
    (void)stream_id;
    (void)context;
    latent_profile_call *call = source->ptr;
    if (lsf_now() >= call->deadline) return stream_failure(call, LATENT_PROFILE_FAILURE_CATEGORY_DEADLINE);
    size_t remaining = call->request_length - call->request_position;
    if (length > remaining) length = remaining;
    memcpy(buffer, call->request + call->request_position, length);
    call->request_position += length;
    if (call->request_position == call->request_length) *flags |= NGHTTP2_DATA_FLAG_EOF;
    return (ssize_t)length;
}

static bool session_create(latent_transport *owner) {
    nghttp2_session_callbacks *callbacks = NULL;
    nghttp2_option *option = NULL;
    if (nghttp2_session_callbacks_new(&callbacks) != 0) return false;
    if (nghttp2_option_new(&option) != 0) { nghttp2_session_callbacks_del(callbacks); return false; }
    nghttp2_session_callbacks_set_on_begin_headers_callback(callbacks, begin_headers);
    nghttp2_session_callbacks_set_on_header_callback(callbacks, header);
    nghttp2_session_callbacks_set_on_data_chunk_recv_callback(callbacks, data_chunk);
    nghttp2_session_callbacks_set_on_frame_recv_callback(callbacks, frame_received);
    nghttp2_session_callbacks_set_on_stream_close_callback(callbacks, stream_closed);
    nghttp2_option_set_max_outbound_ack(option, 32);
    nghttp2_option_set_max_settings(option, 32);
    nghttp2_option_set_max_continuations(option, 4);
    nghttp2_option_set_max_send_header_block_length(option, 4096);
    nghttp2_option_set_max_deflate_dynamic_table_size(option, 0);
    nghttp2_option_set_peer_max_concurrent_streams(option, owner->config.maximum_in_flight);
    nghttp2_mem memory = {owner, http2_allocate, http2_free, http2_callocate, http2_reallocate};
    int result = nghttp2_session_client_new3(&owner->session, callbacks, owner, option, &memory);
    nghttp2_option_del(option);
    nghttp2_session_callbacks_del(callbacks);
    if (result != 0) return false;
    owner->usage.sessions = 1;
    nghttp2_settings_entry settings[] = {
        {NGHTTP2_SETTINGS_ENABLE_PUSH, 0}, {NGHTTP2_SETTINGS_HEADER_TABLE_SIZE, 4096},
        {NGHTTP2_SETTINGS_MAX_CONCURRENT_STREAMS, 0}, {NGHTTP2_SETTINGS_MAX_HEADER_LIST_SIZE, LSF_MAX_HEADER_BYTES},
        {NGHTTP2_SETTINGS_INITIAL_WINDOW_SIZE, 65535}
    };
    return nghttp2_submit_settings(owner->session, NGHTTP2_FLAG_NONE, settings, sizeof(settings) / sizeof(settings[0])) == 0;
}

bool lsf_channel_open(latent_transport *owner, uint64_t deadline) {
    owner->channel_failed = false;
    owner->allocation_failed = false;
    owner->socket_fd = socket(owner->address.ss_family, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (owner->socket_fd < 0) return false;
    owner->usage.sockets = 1;
    int amount = 65536;
    int enabled = 1;
    if (setsockopt(owner->socket_fd, SOL_SOCKET, SO_SNDBUF, &amount, sizeof(amount)) != 0
        || setsockopt(owner->socket_fd, SOL_SOCKET, SO_RCVBUF, &amount, sizeof(amount)) != 0
        || setsockopt(owner->socket_fd, IPPROTO_TCP, TCP_NODELAY, &enabled, sizeof(enabled)) != 0) return false;
    int result = connect(owner->socket_fd, (const struct sockaddr *)&owner->address, owner->address_length);
    if (result != 0 && errno != EINPROGRESS) return false;
    owner->connecting = result != 0;
    owner->connect_deadline = lsf_now() + owner->config.connect_timeout_millis;
    if (deadline < owner->connect_deadline) owner->connect_deadline = deadline;
    return session_create(owner);
}

void lsf_close_channel(latent_transport *owner, latent_profile_failure_category category) {
    if (owner->socket_fd >= 0) {
        (void)shutdown(owner->socket_fd, SHUT_RDWR);
        (void)close(owner->socket_fd);
        owner->socket_fd = -1;
    }
    owner->usage.sockets = 0;
    if (owner->session != NULL) {
        nghttp2_session_del(owner->session);
        owner->session = NULL;
    }
    owner->usage.sessions = 0;
    owner->connecting = false;
    owner->send_data = NULL;
    owner->send_length = 0;
    owner->send_position = 0;
    for (latent_profile_call *call = owner->calls; call != NULL; call = call->next) {
        call->stream_id = 0;
        if (!call->completed) lsf_fail(call, category);
    }
}

static nghttp2_nv header_value(const char *name, const char *value, size_t length, uint8_t flags) {
    return (nghttp2_nv){(uint8_t *)name, (uint8_t *)value, strlen(name), length, flags};
}

bool lsf_channel_submit(latent_profile_call *call) {
    latent_transport *owner = call->owner;
    uint64_t now = lsf_now();
    if (now >= call->deadline) { lsf_fail(call, LATENT_PROFILE_FAILURE_CATEGORY_DEADLINE); return true; }
    char timeout[32];
    int length = snprintf(timeout, sizeof(timeout), "%" PRIu64 "m", call->deadline - now);
    if (length <= 0 || (size_t)length >= sizeof(timeout)) return false;
    nghttp2_nv headers[] = {
        header_value(":method", "POST", 4, 0), header_value(":scheme", "http", 4, 0),
        header_value(":authority", owner->authority, strlen(owner->authority), 0),
        header_value(":path", lsf_rpcs[call->operation].path, strlen(lsf_rpcs[call->operation].path), 0),
        header_value("content-type", "application/grpc+proto", 22, 0), header_value("te", "trailers", 8, 0),
        header_value("grpc-accept-encoding", "identity", 8, 0), header_value("grpc-timeout", timeout, (size_t)length, 0),
        header_value("authorization", owner->authorization, owner->authorization_length, NGHTTP2_NV_FLAG_NO_INDEX)
    };
    nghttp2_data_provider provider = {{.ptr = call}, request_data};
    int32_t stream_id = nghttp2_submit_request(owner->session, NULL, headers,
        sizeof(headers) / sizeof(headers[0]), &provider, call);
    if (stream_id < 0) return false;
    call->stream_id = stream_id;
    call->dispatched = true;
    return true;
}

static bool send_pending(latent_transport *owner) {
    for (unsigned pass = 0; pass < 16; ++pass) {
        if (owner->send_position == owner->send_length) {
            nghttp2_ssize length = nghttp2_session_mem_send2(owner->session, &owner->send_data);
            if (length < 0) return false;
            owner->send_position = 0;
            owner->send_length = (size_t)length;
            if (length == 0) break;
        }
        ssize_t sent = send(owner->socket_fd, owner->send_data + owner->send_position,
                            owner->send_length - owner->send_position, MSG_NOSIGNAL);
        if (sent < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) break;
        if (sent <= 0) return false;
        owner->send_position += (size_t)sent;
    }
    return !owner->channel_failed;
}

bool lsf_channel_step(latent_transport *owner, uint32_t wait_millis) {
    uint64_t poll_deadline = lsf_now() + wait_millis;
    if (owner->connecting) {
        uint64_t now = lsf_now();
        if (now >= owner->connect_deadline) {
            lsf_close_channel(owner, LATENT_PROFILE_FAILURE_CATEGORY_DEADLINE); return false;
        }
        if (poll_deadline > owner->connect_deadline) poll_deadline = owner->connect_deadline;
    }
    if (!owner->connecting) {
        for (latent_profile_call *call = owner->calls; call != NULL; call = call->next) {
            if (!call->completed && call->active && !call->dispatched && !lsf_channel_submit(call)) goto failed;
        }
        if (!send_pending(owner)) goto failed;
    }
    struct pollfd descriptor = {.fd = owner->socket_fd, .events = POLLIN};
    if (owner->connecting || owner->send_position != owner->send_length || nghttp2_session_want_write(owner->session)) descriptor.events |= POLLOUT;
    uint64_t now = lsf_now();
    int result = poll(&descriptor, 1, (int)(poll_deadline > now ? poll_deadline - now : 0));
    if (result < 0) { if (errno == EINTR) return true; goto failed; }
    if (result == 0) return true;
    if (owner->connecting && (descriptor.revents & (POLLOUT | POLLERR | POLLHUP))) {
        int error = 0;
        socklen_t size = sizeof(error);
        if (getsockopt(owner->socket_fd, SOL_SOCKET, SO_ERROR, &error, &size) != 0 || error != 0) goto failed;
        owner->connecting = false;
        for (latent_profile_call *call = owner->calls; call != NULL; call = call->next) {
            if (!call->completed && call->active && !call->dispatched && !lsf_channel_submit(call)) goto failed;
        }
    }
    if (!owner->connecting && !send_pending(owner)) goto failed;
    if (descriptor.revents & POLLIN) {
        uint8_t buffer[16384];
        for (unsigned pass = 0; pass < 16; ++pass) {
            ssize_t received = recv(owner->socket_fd, buffer, sizeof(buffer), 0);
            if (received < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) break;
            if (received <= 0) goto failed;
            nghttp2_ssize consumed = nghttp2_session_mem_recv2(owner->session, buffer, (size_t)received);
            if (consumed != received || owner->channel_failed) goto failed;
        }
        if (!send_pending(owner)) goto failed;
    }
    if (descriptor.revents & (POLLERR | POLLHUP | POLLNVAL)) goto failed;
    return true;
failed:
    lsf_close_channel(owner, owner->allocation_failed ? LATENT_PROFILE_FAILURE_CATEGORY_LIMIT : LATENT_PROFILE_FAILURE_CATEGORY_TRANSPORT);
    return false;
}
