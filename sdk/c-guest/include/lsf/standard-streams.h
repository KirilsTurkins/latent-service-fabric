/* SPDX-License-Identifier: Apache-2.0
 * Compiler-selected invocation-local IPv4 stream subset. No DNS or ambient
 * descriptor capability is created by these declarations.
 */
#ifndef LSF_C_STANDARD_STREAMS_H
#define LSF_C_STANDARD_STREAMS_H
#include <stdbool.h>
#include <stdint.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>
#include <poll.h>
#include <fcntl.h>

/* Preserve stream error facts that POSIX errno and a partial count cannot carry.
 * `code` is the exact latent:network/streams@0.1.0 error-code discriminant.
 */
struct lsf_stream_error {
    uint32_t code;
    uint32_t accepted_prefix_bytes;
    bool may_have_applied;
};
int lsf_stream_last_error(int, struct lsf_stream_error *);

/* Socket functions are not declared by the pinned WASI preview1 headers. */
int __lsf_c_net_socket(int, int, int);
int __lsf_c_net_connect(int, const struct sockaddr *, socklen_t);
int __lsf_c_net_bind(int, const struct sockaddr *, socklen_t);
ssize_t __lsf_c_net_send(int, const void *, size_t, int);
ssize_t __lsf_c_net_recv(int, void *, size_t, int);
ssize_t __lsf_c_net_read(int, void *, size_t);
ssize_t __lsf_c_net_write(int, const void *, size_t);
int __lsf_c_net_shutdown(int, int);
int __lsf_c_net_close(int);
int __lsf_c_net_poll(struct pollfd *, nfds_t, int);
int __lsf_c_net_fcntl(int, int, ...);
int __lsf_c_net_getsockopt(int, int, int, void *, socklen_t *);
int __lsf_c_net_setsockopt(int, int, int, const void *, socklen_t);

/* These absent WASI declarations can be named but are never silently served. */
#ifndef POLLPRI
#define POLLPRI 0x0004
#endif
#ifndef POLLRDBAND
#define POLLRDBAND 0x0008
#endif
#ifndef POLLWRBAND
#define POLLWRBAND 0x0010
#endif
#ifndef SO_KEEPALIVE
#define SO_KEEPALIVE 9
#endif
#ifndef SOL_IP
#define SOL_IP 0
#endif

#define socket __lsf_c_net_socket
#define connect __lsf_c_net_connect
#define bind __lsf_c_net_bind
#define send __lsf_c_net_send
#define recv __lsf_c_net_recv
#define read __lsf_c_net_read
#define write __lsf_c_net_write
#define shutdown __lsf_c_net_shutdown
#define close __lsf_c_net_close
#define poll __lsf_c_net_poll
#define fcntl __lsf_c_net_fcntl
#define getsockopt __lsf_c_net_getsockopt
#define setsockopt __lsf_c_net_setsockopt
#endif
