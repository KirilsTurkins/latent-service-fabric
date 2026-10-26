/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in the actual factory TU, after its original actor/pool helpers.
 * No selected consumer is supplied here. Original constructor v2 read/write,
 * private observation mint and physical Root-return paths remain separate.
 *
 * Native writev/readv exchanges are synchronous and nonblocking. The native
 * owner serializes one request/reply pair, retaining its original IoCall and
 * buffers throughout. No kernel payload buffer, socket fd, retry or new queue.
 */
#include <linux/in.h>
#include <linux/in6.h>
#include <linux/ktime.h>
#include <linux/poll.h>
#include <linux/security.h>
#include <linux/uio.h>
#include <net/sock.h>
#include <net/tcp_states.h>
#include "stream-operation-private.h"

/* Both records live INSIDE the original factory object. Its existing compiled
 * bootstrap-size/Root owner proof therefore includes these actual bytes. */

static void lsf_stream_reply(const struct lsf_stream_request *request,
                            unsigned int status, int error,
                            unsigned int count, unsigned int ready,
                            unsigned int flags)
{
    factory.stream_response = (struct lsf_stream_response){
        .magic = cpu_to_le32(LSF_STREAM_MAGIC),
        .version = cpu_to_le32(LSF_STREAM_VERSION),
        .operation = request->operation,
        .status = cpu_to_le32(status), .slot = request->slot,
        .error = cpu_to_le32(error < 0 ? -error : error),
        .generation = request->generation, .lease = request->lease,
        .sequence = request->sequence, .count = cpu_to_le32(count),
        .ready = cpu_to_le32(ready), .flags = cpu_to_le32(flags),
        .family = request->family
    };
}

static int lsf_stream_shape(const struct lsf_stream_request *request,
                           size_t bytes)
{
    unsigned int i, op = le32_to_cpu(request->operation);
    unsigned int payload = le32_to_cpu(request->payload_bytes);
    unsigned int purpose = le32_to_cpu(request->purpose);
    unsigned int family = le32_to_cpu(request->family);
    unsigned int interest = le32_to_cpu(request->interest);
    if (le32_to_cpu(request->magic) != LSF_STREAM_MAGIC ||
        le32_to_cpu(request->version) != LSF_STREAM_VERSION ||
        request->reserved1 || request->reserved2 ||
        request->reserved3 || !request->lease || !request->sequence ||
        !request->expiry || op < LSF_STREAM_CREATE ||
        op > LSF_STREAM_DNS_TCP_FALLBACK || purpose < LSF_STREAM_TCP ||
        purpose > LSF_STREAM_DNS_TCP ||
        (family != LSF_STREAM_IPV4 && family != LSF_STREAM_IPV6))
        return 0;
    for (i = 0; i < 8; ++i)
        if (!request->scope[i])
            return 0;
    if (family == LSF_STREAM_IPV4) {
        for (i = 4; i < sizeof(request->address); ++i)
            if (request->address[i])
                return 0;
    } else if (!memchr_inv(request->address, 0, 10) &&
               request->address[10] == 0xff && request->address[11] == 0xff) {
        return 0; /* Original AddressPolicy must normalize mapped IPv6 first. */
    }
    if (op == LSF_STREAM_CREATE) {
        if (le32_to_cpu(request->slot) != LSF_FACTORY_CONTEXTS ||
            request->generation || le64_to_cpu(request->sequence) != 1 ||
            purpose == LSF_STREAM_DNS_TCP)
            return 0;
    } else if (le32_to_cpu(request->slot) >= LSF_FACTORY_CONTEXTS ||
               !request->generation)
        return 0;
    if (op == LSF_STREAM_DNS_TCP_FALLBACK && purpose != LSF_STREAM_DNS_TCP)
        return 0;
    if (op == LSF_STREAM_READ || op == LSF_STREAM_WRITE) {
        if (!payload || payload > LSF_STREAM_PAYLOAD)
            return 0;
    } else if (payload)
        return 0;
    if (op == LSF_STREAM_READY) {
        if (!interest || interest > 3)
            return 0;
    } else if (interest)
        return 0;
    if (op == LSF_STREAM_CONNECT) {
        if (!le32_to_cpu(request->port) || le32_to_cpu(request->port) > 65535)
            return 0;
    } else {
        if (request->port)
            return 0;
        for (i = 0; i < sizeof(request->address); ++i)
            if (request->address[i])
                return 0;
    }
    return bytes == sizeof(*request) +
        (op == LSF_STREAM_WRITE ? payload : 0);
}

/* Caller holds the SAME factory mutex. Match the entire actual birth before
 * accessing a socket. Poison permits conservative local close only; it can
 * never authorize data, a new root, recycle or an original charge release. */
static struct lsf_factory_context *lsf_stream_current(
    const struct lsf_stream_request *request, unsigned int cleanup)
{
    unsigned int i, slot = le32_to_cpu(request->slot);
    struct lsf_factory_context *context;
    struct lsf_prepaid_context *owner;
    u64 sequence = le64_to_cpu(request->sequence);
    if (slot >= LSF_FACTORY_CONTEXTS)
        return NULL;
    context = &factory.contexts[slot];
    owner = &factory.pool.contexts[slot];
    if (context->key.slot != slot || context->key.generation !=
            le64_to_cpu(request->generation) ||
        owner->generation != context->key.generation ||
        context->lease != le64_to_cpu(request->lease) ||
        context->stream.family != le32_to_cpu(request->family) ||
        context->stream.sequence == U64_MAX ||
        sequence != context->stream.sequence + 1 ||
        (le32_to_cpu(request->purpose) != context->stream.purpose &&
         !(le32_to_cpu(request->operation) == LSF_STREAM_DNS_TCP_FALLBACK &&
           context->stream.purpose == LSF_STREAM_DNS_UDP &&
           le32_to_cpu(request->purpose) == LSF_STREAM_DNS_TCP)) ||
        le64_to_cpu(request->expiry) > context->stream.expiry)
        return NULL;
    for (i = 0; i < 8; ++i)
        if (owner->scope.identity[i] != le64_to_cpu(request->scope[i]))
            return NULL;
    if (!cleanup && (factory.pool.stopped || factory.pool.poisoned ||
        owner->closed || owner->poisoned || READ_ONCE(factory.uncertain) ||
        ktime_get_ns() >= le64_to_cpu(request->expiry)))
        return NULL;
    context->stream.sequence = sequence; /* Never replay this exchange. */
    return context;
}

static int lsf_stream_peer(struct lsf_factory_context *context)
{
    struct sockaddr_storage storage = {0};
    struct sockaddr_in *v4 = (struct sockaddr_in *)&storage;
    struct sockaddr_in6 *v6 = (struct sockaddr_in6 *)&storage;
    unsigned int family = context->stream.family;
    int result = READ_ONCE(context->socket->ops)->getname(
        context->socket, (struct sockaddr *)&storage, 1);
    if (family == LSF_STREAM_IPV4) {
        if (result != sizeof(*v4) || v4->sin_family != AF_INET ||
            memcmp(&v4->sin_addr.s_addr, context->stream.address, 4) ||
            v4->sin_port != context->stream.port)
            return -EPERM;
    } else if (family == LSF_STREAM_IPV6) {
        if (result != sizeof(*v6) || v6->sin6_family != AF_INET6 ||
            memcmp(&v6->sin6_addr, context->stream.address, 16) ||
            v6->sin6_port != context->stream.port)
            return -EPERM;
    } else {
        return -EPERM;
    }
    context->stream.connected = 1;
    return 0;
}

static int lsf_stream_connect(struct lsf_factory_context *context,
                              const struct lsf_stream_request *request)
{
    struct sockaddr_storage storage = {0};
    struct sockaddr *address = (struct sockaddr *)&storage;
    struct sockaddr_in *v4 = (struct sockaddr_in *)&storage;
    struct sockaddr_in6 *v6 = (struct sockaddr_in6 *)&storage;
    __be16 port = htons(le32_to_cpu(request->port));
    unsigned int family = context->stream.family;
    int error, length;
    if (!context->socket || context->stream.connect_started)
        return -EALREADY;
    if (context->stream.purpose == LSF_STREAM_DNS_TCP &&
        (memcmp(request->address, context->stream.address, 16) ||
         port != context->stream.port))
        return -EPERM; /* Same original DNS server, not another destination. */
    if (family == LSF_STREAM_IPV4) {
        v4->sin_family = AF_INET; v4->sin_port = port;
        memcpy(&v4->sin_addr.s_addr, request->address, 4);
        length = sizeof(*v4);
    } else if (family == LSF_STREAM_IPV6) {
        v6->sin6_family = AF_INET6; v6->sin6_port = port;
        memcpy(&v6->sin6_addr, request->address, 16);
        /* Zone/flow values are not an additional ambient authority input.
         * Original normalized address policy and selected private net bind. */
        length = sizeof(*v6);
    } else {
        return -EINVAL;
    }
    error = security_socket_connect(context->socket, address, length);
    if (error)
        return error;
    context->stream.connect_started = 1;
    memcpy(context->stream.address, request->address, 16);
    context->stream.port = port;
    error = READ_ONCE(context->socket->ops)->connect(context->socket,
        address, length, O_NONBLOCK);
    return error ? error : lsf_stream_peer(context);
}

static int lsf_stream_finish_connect(struct lsf_factory_context *context)
{
    struct sock *sk;
    int error;
    if (!context->socket || !context->stream.connect_started ||
        context->stream.purpose == LSF_STREAM_DNS_UDP)
        return -EINVAL;
    if (context->stream.connected)
        return 0;
    sk = context->socket->sk;
    error = sock_error(sk);
    if (error)
        return error;
    if (READ_ONCE(sk->sk_state) == TCP_ESTABLISHED)
        return lsf_stream_peer(context);
    if (READ_ONCE(sk->sk_state) == TCP_CLOSE)
        return -ECONNABORTED;
    return -EINPROGRESS; /* Never call connect a second time. */
}

/* Only the original four records and original consumer can construct a socket.
 * A failed/uncertain constructor poisons the SAME physical backing admission.
 * No normal sock_create_kern, sock_alloc_file or fd_install fallback exists. */
static int lsf_stream_create(struct lsf_stream_request *request,
                             const struct lsf_factory_consumer *consumer)
{
    struct lsf_scope scope;
    struct lsf_prepaid_key key;
    struct lsf_factory_context *context;
    unsigned int i, purpose = le32_to_cpu(request->purpose);
    unsigned int family = le32_to_cpu(request->family);
    unsigned long flags;
    u64 lease = le64_to_cpu(request->lease);
    int error, type = purpose == LSF_STREAM_TCP ? SOCK_STREAM : SOCK_DGRAM;
    int protocol = purpose == LSF_STREAM_TCP ? IPPROTO_TCP : IPPROTO_UDP;
    if (lease <= factory.last_lease || READ_ONCE(factory.uncertain) ||
        factory.pool.stopped || factory.pool.poisoned ||
        ktime_get_ns() >= le64_to_cpu(request->expiry))
        return -EPERM;
    for (i = 0; i < 8; ++i)
        scope.identity[i] = le64_to_cpu(request->scope[i]);
    spin_lock_irqsave(&pool_lock, flags);
    error = lsf_prepaid_context_create(&factory.pool, scope,
        purpose == LSF_STREAM_TCP ? LSF_TCP_BYTES : LSF_DNS_BYTES, &key);
    spin_unlock_irqrestore(&pool_lock, flags);
    if (!error)
        return -ENOBUFS;
    context = &factory.contexts[key.slot];
    context->key = key;
    context->lease = lease;
    context->net = factory.net;
    context->stream = (struct lsf_stream_context){ .sequence = 1,
        .expiry = le64_to_cpu(request->expiry), .purpose = purpose, .family = family };
    factory.last_lease = lease;
    /* Even a failed constructor reports the actual born cleanup identity.
     * It is not a successful socket, nor an assertion that no allocation ran. */
    request->slot = cpu_to_le32(key.slot);
    request->generation = cpu_to_le64(key.generation);
    mutex_unlock(&factory_lock);
    error = consumer->create(factory.net,
        family == LSF_STREAM_IPV4 ? AF_INET : AF_INET6, type, protocol,
                             context, &context->socket);
    mutex_lock(&factory_lock);
    if (error || !context->socket || factory.pool.stopped) {
        WRITE_ONCE(factory.uncertain, 1);
        return error < 0 ? error : -EIO;
    }
    return 0;
}

static int lsf_stream_dns_tcp(struct lsf_factory_context *context,
                              const struct lsf_factory_consumer *consumer)
{
    struct socket *tcp = NULL, *udp = context->socket;
    int error;
    if (!udp || context->stream.purpose != LSF_STREAM_DNS_UDP ||
        !context->stream.connected)
        return -EINVAL;
    /* The original UDP tail remains LIVE in this SAME64KiB context while TCP
     * is born. Capacity refusal is final, not another bank or another server. */
    error = consumer->create(factory.net,
        context->stream.family == LSF_STREAM_IPV4 ? AF_INET : AF_INET6, SOCK_STREAM, IPPROTO_TCP,
                             context, &tcp);
    if (error || !tcp) {
        WRITE_ONCE(factory.uncertain, 1);
        return error < 0 ? error : -EIO;
    }
    context->socket = tcp;
    context->stream.purpose = LSF_STREAM_DNS_TCP;
    context->stream.connect_started = context->stream.connected = 0;
    consumer->close(udp, context);
    return 0;
}

static int lsf_stream_ready(struct file *file,
                            struct lsf_factory_context *context,
                            unsigned int interest)
{
    __poll_t observed;
    unsigned int ready = 0;
    if (!context->socket || !READ_ONCE(context->socket->ops)->poll)
        return -EINVAL;
    /* NULL poll table: no new registration, callback, allocation or poller.
     * The existing bounded native maintenance owner delivers this wake hint. */
    observed = READ_ONCE(context->socket->ops)->poll(file, context->socket, NULL);
    if ((interest & 1) && (observed & (EPOLLIN | EPOLLRDNORM | EPOLLRDHUP | EPOLLHUP | EPOLLERR)))
        ready |= 1;
    if ((interest & 2) && (observed & (EPOLLOUT | EPOLLWRNORM | EPOLLHUP | EPOLLERR)))
        ready |= 2;
    if ((interest & 1) && (observed & (EPOLLRDHUP | EPOLLHUP)))
        ready |= 4;
    if ((interest & 2) && (observed & EPOLLHUP))
        ready |= 8;
    if (observed & EPOLLERR)
        ready |= 16;
    return ready;
}

static int lsf_stream_payload(struct lsf_factory_context *context,
                              struct iov_iter *payload, unsigned int write)
{
    struct msghdr message = { .msg_flags = MSG_DONTWAIT | MSG_NOSIGNAL,
                              .msg_iter = *payload };
    if (!context->socket || !context->stream.connected)
        return -ENOTCONN;
    /* These original helpers retain security_socket_sendmsg/recvmsg and the
     * actual protocol operation. There is no private nosec fast path. */
    return write ? sock_sendmsg(context->socket, &message) :
        sock_recvmsg(context->socket, &message, MSG_DONTWAIT);
}

static void lsf_stream_outcome(const struct lsf_stream_request *request,
                               int result, unsigned int attempted_write)
{
    unsigned int op = le32_to_cpu(request->operation);
    unsigned int flags = attempted_write ? 1 : 0;
    if (op == LSF_STREAM_WRITE && result == -EAGAIN) {
        /* Synchronous nonblocking sendmsg accepted no bytes; do not turn the
         * conservative attempted-write bit into a replay-uncertainty signal. */
        lsf_stream_reply(request, LSF_STREAM_PENDING, 0, 0, 0, 0);
        return;
    }
    if ((result == -EAGAIN || result == -EINPROGRESS) &&
        (op == LSF_STREAM_CONNECT || op == LSF_STREAM_FINISH_CONNECT ||
         op == LSF_STREAM_READ || op == LSF_STREAM_WRITE ||
         op == LSF_STREAM_READY || op == LSF_STREAM_RETIRED)) {
        lsf_stream_reply(request, LSF_STREAM_PENDING, 0, 0, 0, flags);
    } else if (result < 0) {
        lsf_stream_reply(request, LSF_STREAM_FAILED, result, 0, 0, flags);
    } else if (op == LSF_STREAM_READY) {
        lsf_stream_reply(request, result ? LSF_STREAM_COMPLETE : LSF_STREAM_PENDING,
                         0, 0, result, 0);
    } else if (op == LSF_STREAM_READ && result == 0 &&
               le32_to_cpu(request->purpose) == LSF_STREAM_DNS_UDP) {
        /* A consumed empty DNS datagram is malformed DNS, never stream EOF.
         * The caller must not replay that receive or silently change server. */
        lsf_stream_reply(request, LSF_STREAM_FAILED, -EBADMSG, 0, 0, 0);
    } else if (op == LSF_STREAM_READ && result == 0) {
        lsf_stream_reply(request, LSF_STREAM_EOF, 0, 0, 0, 0);
    } else if (op == LSF_STREAM_WRITE && result == 0) {
        lsf_stream_reply(request, LSF_STREAM_FAILED, -EIO, 0, 0, flags);
    } else {
        lsf_stream_reply(request, LSF_STREAM_COMPLETE, 0,
            op == LSF_STREAM_READ || op == LSF_STREAM_WRITE ? result : 0,
            0, flags);
    }
}

/* A retired result is an original context-occupancy return ONLY. Physical
 * pages remain owned/charged to the NodeFixed bank until its separate sealed
 * Root-return path. No userspace argument can substitute a return counter. */
static int lsf_stream_retired(struct lsf_factory_context *context)
{
    struct lsf_prepaid_context *owner;
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    owner = lsf_prepaid_context_for(&factory.pool, context->key);
    if (!owner || !owner->closed || context->socket) {
        result = -EINVAL;
    } else if (owner->live || owner->continuations) {
        result = -EAGAIN;
    } else {
        result = lsf_prepaid_recycle(&factory.pool, context->key) ? 0 : -EIO;
        if (!result)
            context->stream.retired = 1; /* Actual complete original recycle, not close. */
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Called without factory_lock, with its original inflight fence retained.
 * The actual socket/protocol/LSM/callback chain may take its original locks;
 * no factory mutex is held across that work or a user-memory fault. */
static int lsf_stream_dispatch(struct file *file,
                               struct lsf_factory_context *context,
                               const struct lsf_stream_request *request,
                               struct iov_iter *payload,
                               const struct lsf_factory_consumer *consumer)
{
    unsigned int op = le32_to_cpu(request->operation);
    struct socket *socket;
    unsigned long flags;
    int result;
    switch (op) {
    case LSF_STREAM_CONNECT:
        return lsf_stream_connect(context, request);
    case LSF_STREAM_FINISH_CONNECT:
        return lsf_stream_finish_connect(context);
    case LSF_STREAM_DNS_TCP_FALLBACK:
        return lsf_stream_dns_tcp(context, consumer);
    case LSF_STREAM_WRITE:
        return lsf_stream_payload(context, payload, 1);
    case LSF_STREAM_READY:
        return lsf_stream_ready(file, context, le32_to_cpu(request->interest));
    case LSF_STREAM_SHUTDOWN_SEND:
        if (!context->socket || !context->stream.connected ||
            context->stream.purpose == LSF_STREAM_DNS_UDP)
            return -EINVAL;
        result = security_socket_shutdown(context->socket, SHUT_WR);
        return result ? result :
            READ_ONCE(context->socket->ops)->shutdown(context->socket, SHUT_WR);
    case LSF_STREAM_CLOSE:
        spin_lock_irqsave(&pool_lock, flags);
        factory.pool.contexts[context->key.slot].closed = 1;
        spin_unlock_irqrestore(&pool_lock, flags);
        socket = context->socket;
        context->socket = NULL;
        if (socket)
            consumer->close(socket, context);
        return 0; /* Request accepted, NOT physical retirement. */
    case LSF_STREAM_RETIRED:
        return lsf_stream_retired(context);
    default:
        return -EINVAL;
    }
}

static ssize_t lsf_factory_stream_write_iter(struct kiocb *iocb,
                                              struct iov_iter *from)
{
    const struct lsf_factory_consumer *consumer = lsf_factory_selected_consumer();
    struct lsf_stream_request request;
    struct lsf_factory_context *context;
    struct file *file = iocb->ki_filp;
    size_t bytes = iov_iter_count(from);
    unsigned int op;
    int result;
    if (!consumer)
        return -EOPNOTSUPP;
    if (bytes < sizeof(request) || bytes > sizeof(request) + LSF_STREAM_PAYLOAD ||
        !copy_from_iter_full(&request, sizeof(request), from) ||
        !lsf_stream_shape(&request, bytes))
        return -EINVAL;
    op = le32_to_cpu(request.operation);
    if (mutex_lock_interruptible(&factory_lock))
        return -EINTR; /* No operation, sequence or socket has been touched. */
    if (!lsf_factory_actor(file) || factory.reply_pending || factory.inflight) {
        result = -EBUSY;
        goto refuse;
    }
    /* This is the original constructor's actual bootstrap/device fence, not
     * a second way to use the factory before its prepaid executor is READY. */
    if (!factory.device ||
        factory.device->bootstrap_state != LSF_FACTORY_BOOTSTRAP_READY) {
        result = -EAGAIN;
        goto refuse;
    }
    if (op != LSF_STREAM_CLOSE && op != LSF_STREAM_RETIRED) {
        result = lsf_factory_device_firmware_retirement_error();
        if (result)
            goto refuse;
    }
    factory.inflight = 1;
    if (op == LSF_STREAM_CREATE) {
        result = lsf_stream_create(&request, consumer); /* Returns with lock. */
    } else {
        context = lsf_stream_current(&request,
            op == LSF_STREAM_CLOSE || op == LSF_STREAM_RETIRED);
        if (!context) {
            result = -EPERM;
        } else if (op == LSF_STREAM_READ) {
            /* Actual recvmsg runs only during the SAME exchange's readv into
             * its original charged output buffer; no retained payload copy. */
            result = 0;
        } else {
            mutex_unlock(&factory_lock);
            result = lsf_stream_dispatch(file, context, &request, from, consumer);
            mutex_lock(&factory_lock);
        }
    }
    factory.stream_request = request;
    if (op == LSF_STREAM_READ && result == 0)
        lsf_stream_reply(&request, LSF_STREAM_COMPLETE, 0, 0, 0, 0);
    else
        lsf_stream_outcome(&request, result, op == LSF_STREAM_WRITE);
    factory.reply_pending = LSF_STREAM_REPLY_PENDING;
    factory.inflight = 0;
    mutex_unlock(&factory_lock);
    if (op == LSF_STREAM_WRITE)
        iov_iter_advance(from, le32_to_cpu(request.payload_bytes));
    return bytes; /* Framing consumed; reply retains the REAL short prefix. */
refuse:
    mutex_unlock(&factory_lock);
    return result;
}

static ssize_t lsf_factory_stream_read_iter(struct kiocb *iocb,
                                             struct iov_iter *to)
{
    const struct lsf_factory_consumer *consumer = lsf_factory_selected_consumer();
    struct lsf_factory_context *context;
    struct iov_iter header = *to, payload = *to;
    struct file *file = iocb->ki_filp;
    unsigned int bytes = 0;
    int result;
    if (!consumer)
        return -EOPNOTSUPP;
    if (iov_iter_count(to) < sizeof(factory.stream_response) ||
        iov_iter_count(to) > sizeof(factory.stream_response) + LSF_STREAM_PAYLOAD)
        return -EINVAL;
    if (mutex_lock_interruptible(&factory_lock))
        return -EINTR;
    if (!lsf_factory_actor(file) || factory.inflight ||
        factory.reply_pending != LSF_STREAM_REPLY_PENDING) {
        result = -EINVAL;
        goto out;
    }
    factory.inflight = 1;
    if (le32_to_cpu(factory.stream_request.operation) == LSF_STREAM_READ &&
        le32_to_cpu(factory.stream_response.status) == LSF_STREAM_COMPLETE) {
        context = &factory.contexts[le32_to_cpu(factory.stream_request.slot)];
        if (iov_iter_count(to) != sizeof(factory.stream_response) +
                le32_to_cpu(factory.stream_request.payload_bytes)) {
            lsf_stream_outcome(&factory.stream_request, -EINVAL, 0);
        } else if (ktime_get_ns() >= le64_to_cpu(factory.stream_request.expiry)) {
            lsf_stream_outcome(&factory.stream_request, -ETIMEDOUT, 0);
        } else if (factory.pool.stopped || factory.pool.poisoned ||
                   READ_ONCE(factory.uncertain) ||
                   factory.pool.contexts[context->key.slot].closed ||
                   factory.pool.contexts[context->key.slot].poisoned ||
                   context->key.generation != le64_to_cpu(factory.stream_request.generation) ||
                   context->lease != le64_to_cpu(factory.stream_request.lease) ||
                   context->stream.sequence != le64_to_cpu(factory.stream_request.sequence)) {
            lsf_stream_outcome(&factory.stream_request, -ECANCELED, 0);
        } else {
            iov_iter_advance(&payload, sizeof(factory.stream_response));
            mutex_unlock(&factory_lock);
            result = lsf_stream_payload(context, &payload, 0);
            mutex_lock(&factory_lock);
            lsf_stream_outcome(&factory.stream_request, result, 0);
            if (result > 0)
                bytes = result;
        }
    }
    /* If output copying fails AFTER a mutation/recv, original ambiguity is
     * sticky. Do not retry it, recycle a context or manufacture an ACK. */
    mutex_unlock(&factory_lock);
    result = copy_to_iter(&factory.stream_response, sizeof(factory.stream_response), &header)
        == sizeof(factory.stream_response) ? sizeof(factory.stream_response) + bytes : -EFAULT;
    mutex_lock(&factory_lock);
    if (result < 0)
        WRITE_ONCE(factory.uncertain, 1);
    else {
        factory.reply_pending = 0;
        iov_iter_advance(to, result);
    }
    factory.inflight = 0;
out:
    mutex_unlock(&factory_lock);
    return result;
}
