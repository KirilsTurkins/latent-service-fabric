/* SPDX-License-Identifier: GPL-2.0-only */
/* Kernel-private fixed framing. No socket fd, allocator size or free proof. */
#ifndef LSF_STREAM_OPERATION_PRIVATE_H
#define LSF_STREAM_OPERATION_PRIVATE_H
#include <linux/build_bug.h>
#include <linux/types.h>

#define LSF_STREAM_MAGIC 0x4c535354u
#define LSF_STREAM_VERSION 1u
#define LSF_STREAM_PAYLOAD 16384u
#define LSF_STREAM_REPLY_PENDING 2u

enum lsf_stream_operation {
    LSF_STREAM_CREATE = 1, LSF_STREAM_CONNECT, LSF_STREAM_READ,
    LSF_STREAM_WRITE, LSF_STREAM_READY, LSF_STREAM_SHUTDOWN_SEND,
    LSF_STREAM_CLOSE, LSF_STREAM_RETIRED, LSF_STREAM_FINISH_CONNECT,
    LSF_STREAM_DNS_TCP_FALLBACK
};
enum lsf_stream_purpose {
    LSF_STREAM_TCP = 1, LSF_STREAM_DNS_UDP, LSF_STREAM_DNS_TCP
};
enum lsf_stream_family {
    LSF_STREAM_IPV4 = 4, LSF_STREAM_IPV6 = 6
};
enum lsf_stream_status {
    LSF_STREAM_COMPLETE, LSF_STREAM_PENDING, LSF_STREAM_EOF, LSF_STREAM_FAILED
};

struct lsf_stream_request {
    __le32 magic, version, operation, family;
    __le32 slot, reserved1;
    __le64 generation, lease, sequence, expiry;
    __le32 payload_bytes, reserved2;
    __le64 scope[8];
    unsigned char address[16];
    __le32 port, purpose, interest, reserved3;
};
struct lsf_stream_response {
    __le32 magic, version, operation, status;
    __le32 slot, error;
    __le64 generation, lease, sequence;
    __le32 count, ready, flags, family;
};
static_assert(sizeof(struct lsf_stream_request) == 160);
static_assert(sizeof(struct lsf_stream_response) == 64);

/* Lives INSIDE each original fixed factory context, covered by the original
 * sizeof(factory) bootstrap fence. No second context/record allocation table.
 * Both DNS transports consume the SAME original64KiB context. */
struct lsf_stream_context {
    u64 sequence, expiry;
    unsigned char address[16];
    __be16 port;
    unsigned int purpose, family, connect_started, connected, retired;
};
#endif
