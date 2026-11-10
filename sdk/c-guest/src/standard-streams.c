/* SPDX-License-Identifier: Apache-2.0
 * A bounded, invocation-local POSIX subset over the existing stream provider.
 * Only blocking IPv4 literals and one-descriptor select are supported here.
 * No hostname lookup, ambient descriptor, urgent data, or retry is supplied.
 */
#include "probe.h"
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <netinet/in.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <poll.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <time.h>

#include <lsf/standard-streams.h>

enum { FIRST_FD = 3, SLOT_COUNT = 8, MAX_TRANSFER = 16384 };

/* Static storage belongs to this component instance's charged linear memory.
 * A busy slot cannot be closed or reused across a suspended canonical call.
 */
struct descriptor {
    bool allocated;
    bool busy;
    bool has_connection;
    bool write_shut;
    bool failed;
    bool has_error;
    latent_network_streams_own_connection_t connection;
    latent_network_streams_stream_error_t last_error;
};
static struct descriptor descriptors[SLOT_COUNT];

static int fail(int code) { errno = code; return -1; }

static struct descriptor *find_descriptor(int fd) {
    if (fd < FIRST_FD || fd >= FIRST_FD + SLOT_COUNT) return NULL;
    struct descriptor *slot = &descriptors[fd - FIRST_FD];
    return slot->allocated ? slot : NULL;
}

static int error_number(latent_network_streams_error_code_t code) {
    switch (code) {
    case LATENT_NETWORK_STREAMS_ERROR_CODE_INVALID_INPUT: return EINVAL;
    case LATENT_NETWORK_STREAMS_ERROR_CODE_INVALID_STATE: return EIO;
    case LATENT_NETWORK_STREAMS_ERROR_CODE_UNSUPPORTED: return ENOTSUP;
    case LATENT_NETWORK_STREAMS_ERROR_CODE_DENIED: return EACCES;
    case LATENT_NETWORK_STREAMS_ERROR_CODE_REVOKED: return ESTALE;
    case LATENT_NETWORK_STREAMS_ERROR_CODE_EXHAUSTED: return ENOBUFS;
    case LATENT_NETWORK_STREAMS_ERROR_CODE_TIMEOUT: return ETIMEDOUT;
    case LATENT_NETWORK_STREAMS_ERROR_CODE_CANCELLED: return ECANCELED;
    default: return EIO;
    }
}

static int failed_call(struct descriptor *slot, latent_network_streams_stream_error_t error) {
    slot->last_error = error;
    slot->has_error = true;
    slot->failed = true;
    slot->busy = false;
    return fail(error_number(error.code));
}

int lsf_stream_last_error(int fd, struct lsf_stream_error *out) {
    struct descriptor *slot = find_descriptor(fd);
    if (!slot) return fail(EBADF);
    if (!out) return fail(EINVAL);
    if (!slot->has_error) return fail(ENOENT);
    *out = (struct lsf_stream_error) {
        .code = slot->last_error.code,
        .accepted_prefix_bytes = slot->last_error.accepted_prefix_bytes,
        .may_have_applied = slot->last_error.may_have_applied,
    };
    return 0;
}

static latent_network_streams_borrow_connection_t borrow(struct descriptor *slot) {
    return latent_network_streams_borrow_connection(slot->connection);
}

static struct descriptor *ready_descriptor(int fd) {
    struct descriptor *slot = find_descriptor(fd);
    if (!slot) { errno = EBADF; return NULL; }
    if (slot->busy) { errno = EBUSY; return NULL; }
    if (!slot->has_connection) { errno = ENOTCONN; return NULL; }
    if (slot->failed) { errno = EIO; return NULL; }
    return slot;
}

int __lsf_c_net_socket(int domain, int type, int protocol) {
    if (domain != AF_INET) return fail(EAFNOSUPPORT);
    if (type != SOCK_STREAM || (protocol != 0 && protocol != IPPROTO_TCP)) return fail(ENOTSUP);
    for (int index = 0; index < SLOT_COUNT; ++index) {
        struct descriptor *slot = &descriptors[index];
        if (!slot->allocated) {
            *slot = (struct descriptor){ .allocated = true };
            return FIRST_FD + index;
        }
    }
    return fail(EMFILE);
}

int __lsf_c_net_fcntl(int fd, int command, ...) {
    if (!find_descriptor(fd)) return fail(EBADF);
    if (command == F_GETFL) return O_RDWR;
    if (command == F_GETFD) return 0;
    /* In particular, no nonblocking mode or close-on-exec behavior is faked. */
    return fail(ENOTSUP);
}

int __lsf_c_net_getsockopt(int fd, int level, int option, void *value, socklen_t *length) {
    if (!find_descriptor(fd)) return fail(EBADF);
    if (level != SOL_SOCKET || option != SO_TYPE) return fail(ENOTSUP);
    if (!value || !length || *length < sizeof(int)) return fail(EINVAL);
    int result = SOCK_STREAM;
    memcpy(value, &result, sizeof(result));
    *length = sizeof(result);
    return 0;
}

int __lsf_c_net_setsockopt(int fd, int level, int option, const void *value, socklen_t length) {
    (void)level; (void)option; (void)value; (void)length;
    if (!find_descriptor(fd)) return fail(EBADF);
    return fail(ENOTSUP);
}

/* Format actual sockaddr bytes, never a synthetic address for a hostname. */
static size_t decimal_octet(char *out, uint8_t value) {
    size_t length = 0;
    if (value >= 100) out[length++] = (char)('0' + value / 100);
    if (value >= 10) out[length++] = (char)('0' + (value / 10) % 10);
    out[length++] = (char)('0' + value % 10);
    return length;
}

int __lsf_c_net_connect(int fd, const struct sockaddr *address, socklen_t length) {
    struct descriptor *slot = find_descriptor(fd);
    if (!slot) return fail(EBADF);
    if (slot->busy) return fail(EBUSY);
    if (slot->has_connection) return fail(EISCONN);
    if (slot->failed) return fail(EIO);
    if (!address || length < sizeof(struct sockaddr_in)) return fail(EINVAL);
    struct sockaddr_in input;
    memcpy(&input, address, sizeof(input));
    if (input.sin_family != AF_INET) return fail(EAFNOSUPPORT);
    uint8_t octets[4], port_bytes[2];
    memcpy(octets, &input.sin_addr, sizeof(octets));
    memcpy(port_bytes, &input.sin_port, sizeof(port_bytes));
    uint16_t port = (uint16_t)((uint16_t)port_bytes[0] * 256u + port_bytes[1]);
    if (!port) return fail(EINVAL);
    char host[15]; size_t used = 0;
    for (unsigned index = 0; index < 4; ++index) {
        if (index) host[used++] = '.';
        used += decimal_octet(host + used, octets[index]);
    }
    latent_network_streams_connect_request_t request = {
        .host = { .ptr = (uint8_t *)host, .len = used },
        .port = port, .transport = LATENT_NETWORK_STREAMS_TRANSPORT_TCP,
        .timeout_millis = { .is_some = false },
    };
    latent_network_streams_own_connection_t connection;
    latent_network_streams_stream_error_t error;
    slot->busy = true;
    if (!latent_network_streams_connect(&request, &connection, &error)) return failed_call(slot, error);
    slot->connection = connection;
    slot->has_connection = true;
    slot->busy = false;
    return 0;
}

int __lsf_c_net_bind(int fd, const struct sockaddr *address, socklen_t length) {
    (void)address; (void)length;
    if (!find_descriptor(fd)) return fail(EBADF);
    return fail(ENOTSUP);
}

ssize_t __lsf_c_net_send(int fd, const void *buffer, size_t length, int flags) {
    struct descriptor *slot = ready_descriptor(fd);
    if (!slot) return -1;
    if (flags != 0) return fail(ENOTSUP);
    if (slot->write_shut) return fail(EPIPE);
    if (!length) return 0;
    if (!buffer) return fail(EINVAL);
    if (length > MAX_TRANSFER) length = MAX_TRANSFER;
    probe_list_u8_t input = { .ptr = (uint8_t *)buffer, .len = length };
    latent_network_streams_stream_error_t error;
    uint32_t written = 0;
    slot->busy = true;
    if (!latent_network_streams_write(borrow(slot), &input, NULL, &written, &error)) {
        int failure = failed_call(slot, error);
        if (error.accepted_prefix_bytes > 0 && error.accepted_prefix_bytes <= length)
            return (ssize_t)error.accepted_prefix_bytes;
        return failure;
    }
    slot->busy = false;
    if (written == 0 || written > length) { slot->failed = true; return fail(EIO); }
    return (ssize_t)written;
}

ssize_t __lsf_c_net_recv(int fd, void *buffer, size_t length, int flags) {
    struct descriptor *slot = ready_descriptor(fd);
    if (!slot) return -1;
    if (flags != 0) return fail(ENOTSUP);
    if (!length) return 0;
    if (!buffer) return fail(EINVAL);
    if (length > MAX_TRANSFER) length = MAX_TRANSFER;
    latent_network_streams_stream_error_t error;
    latent_network_streams_option_own_chunk_t chunk;
    slot->busy = true;
    if (!latent_network_streams_read(borrow(slot), (uint32_t)length, NULL, &chunk, &error))
        return failed_call(slot, error);
    if (!chunk.is_some) { slot->busy = false; return 0; }
    probe_list_u8_t bytes = {0};
    bool copied = latent_network_streams_chunk_bytes(latent_network_streams_borrow_chunk(chunk.val), &bytes, &error);
    if (!copied) {
        latent_network_streams_chunk_drop_own(chunk.val);
        return failed_call(slot, error);
    }
    if (!bytes.ptr || bytes.len == 0 || bytes.len > length) {
        probe_list_u8_free(&bytes);
        latent_network_streams_chunk_drop_own(chunk.val);
        slot->failed = true; slot->busy = false;
        return fail(EIO);
    }
    size_t count = bytes.len;
    memcpy(buffer, bytes.ptr, count);
    probe_list_u8_free(&bytes);
    latent_network_streams_chunk_drop_own(chunk.val);
    slot->busy = false;
    return (ssize_t)count;
}

ssize_t __lsf_c_net_read(int fd, void *buffer, size_t length) {
    return __lsf_c_net_recv(fd, buffer, length, 0);
}

ssize_t __lsf_c_net_write(int fd, const void *buffer, size_t length) {
    return __lsf_c_net_send(fd, buffer, length, 0);
}

int __lsf_c_net_shutdown(int fd, int how) {
    struct descriptor *slot = ready_descriptor(fd);
    if (!slot) return -1;
    if (how != SHUT_WR && how != SHUT_RDWR) return fail(ENOTSUP);
    if (how == SHUT_WR && slot->write_shut) return 0;
    latent_network_streams_observation_t observation;
    latent_network_streams_stream_error_t error;
    slot->busy = true;
    if (!latent_network_streams_shutdown(borrow(slot), how == SHUT_WR ?
            LATENT_NETWORK_STREAMS_SHUTDOWN_MODE_SEND : LATENT_NETWORK_STREAMS_SHUTDOWN_MODE_BOTH,
            &observation, &error)) return failed_call(slot, error);
    if (how == SHUT_WR) slot->write_shut = true;
    if (how == SHUT_RDWR) slot->failed = true;
    slot->busy = false;
    return 0;
}

int __lsf_c_net_close(int fd) {
    struct descriptor *slot = find_descriptor(fd);
    if (!slot) return fail(EBADF);
    if (slot->busy) return fail(EBUSY);
    if (!slot->has_connection) { *slot = (struct descriptor){0}; return 0; }
    latent_network_streams_observation_t observation;
    latent_network_streams_stream_error_t error;
    slot->busy = true;
    bool closed = latent_network_streams_close(slot->connection, &observation, &error);
    *slot = (struct descriptor){0};
    return closed ? 0 : fail(error_number(error.code));
}

/* The authenticated WASI fd_set is a bounded list, not a native bitmap.
 * Exceptional descriptors and more than one distinct descriptor are refused
 * before entering the provider. Entries at or above nfds are ignored.
 */
static int select_collect(const fd_set *set, int nfds, int *selected, bool exceptional) {
    if (!set) return 0;
    if (set->__nfds > FD_SETSIZE) return fail(EINVAL);
    for (size_t index = 0; index < set->__nfds; ++index) {
        int fd = set->__fds[index];
        if (fd < 0) return fail(EINVAL);
        if (fd >= nfds) continue;
        if (exceptional) return fail(ENOTSUP);
        if (*selected != -1 && *selected != fd) return fail(ENOTSUP);
        *selected = fd;
    }
    return 0;
}

int __lsf_c_net_select(int nfds, fd_set *readfds, fd_set *writefds,
                       fd_set *errorfds, const struct timeval *timeout) {
    if (nfds < 0) return fail(EINVAL);
    int selected = -1;
    if (select_collect(readfds, nfds, &selected, false) ||
        select_collect(writefds, nfds, &selected, false) ||
        select_collect(errorfds, nfds, &selected, true)) return -1;
    if (selected < 0) return fail(ENOTSUP);
    struct descriptor *slot = ready_descriptor(selected);
    if (!slot) return -1;
    bool want_read = readfds && FD_ISSET(selected, readfds);
    bool want_write = writefds && FD_ISSET(selected, writefds);
    if (timeout) {
        struct timeval value = *timeout;
        if (value.tv_sec < 0 || value.tv_usec < 0 || value.tv_usec >= 1000000)
            return fail(EINVAL);
        /* WIT Timeout does not distinguish an observation deadline from
         * expiration of the original connection or activation. Never turn
         * an ambiguous failure into a successful empty POSIX observation. */
        return fail(ENOTSUP);
    }
    latent_network_streams_interest_t interest = want_read && want_write ?
        LATENT_NETWORK_STREAMS_INTEREST_EITHER : want_read ?
        LATENT_NETWORK_STREAMS_INTEREST_READABLE : LATENT_NETWORK_STREAMS_INTEREST_WRITABLE;
    latent_network_streams_stream_error_t error;
    latent_network_streams_readiness_t ready = {0};
    slot->busy = true;
    if (!latent_network_streams_ready(borrow(slot), interest, NULL, &ready, &error))
        return failed_call(slot, error);
    int count = (want_read && ready.readable) + (want_write && ready.writable);
    if (!count) { slot->failed = true; slot->busy = false; return fail(EIO); }
    slot->busy = false;
    if (readfds) { FD_ZERO(readfds); if (want_read && ready.readable) FD_SET(selected, readfds); }
    if (writefds) { FD_ZERO(writefds); if (want_write && ready.writable) FD_SET(selected, writefds); }
    if (errorfds) FD_ZERO(errorfds);
    return count;
}

int __lsf_c_net_pselect(int nfds, fd_set *readfds, fd_set *writefds,
                        fd_set *errorfds, const struct timespec *timeout) {
    if (nfds < 0) return fail(EINVAL);
    if (!timeout) return __lsf_c_net_select(nfds, readfds, writefds, errorfds, NULL);
    struct timespec value = *timeout;
    if (value.tv_sec < 0 || value.tv_nsec < 0 || value.tv_nsec >= 1000000000)
        return fail(EINVAL);
    return fail(ENOTSUP);
}

/* The current stream WIT does not identify POLLPRI, POLLERR or POLLHUP.
 * Refuse every descriptor poll, rather than silently erase requested events.
 * The existing libc path remains available for descriptor-free timer polls.
 */
extern int net_original_poll(struct pollfd *, nfds_t, int) __asm__("poll");
int __lsf_c_net_poll(struct pollfd *fds, nfds_t count, int timeout) {
    if (count > SLOT_COUNT) return fail(ENOTSUP);
    if (count && !fds) return fail(EINVAL);
    for (nfds_t index = 0; index < count; ++index)
        if (fds[index].fd >= 0) return fail(ENOTSUP);
    return net_original_poll(fds, count, timeout);
}
