/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_DEVICE_NOTIFICATION_PRIVATE_H
#define LSF_STREAM_DEVICE_NOTIFICATION_PRIVATE_H
#include <linux/wait.h>
#include <net/lsf_stream_device_recipient.h>
struct sk_buff;
int lsf_factory_device_recipient_packet(struct lsf_device_registration_source,
    const struct sock *, const struct sk_buff *);
int lsf_prepaid_device_socket_notify(struct lsf_device_registration_source,
    struct sock *, bool);

/* Only the actual original waitqueue lock extent may dispatch these private
 * callbacks. These are not exported and confer no owner or callback admission. */
bool lsf_prepaid_device_pollwake_matches(wait_queue_func_t);
int lsf_prepaid_device_pollwake(struct lsf_device_registration_source,
    wait_queue_entry_t *, unsigned int, int, void *);
#ifdef CONFIG_EPOLL
bool lsf_prepaid_device_epoll_matches(wait_queue_func_t);
int lsf_prepaid_device_epoll_callback(struct lsf_device_registration_source,
    wait_queue_entry_t *, unsigned int, int, void *);
#endif
int lsf_prepaid_device_wake(struct lsf_device_registration_source,
    struct wait_queue_head *, unsigned int, int, int, void *);
int lsf_prepaid_device_wake_sync(struct lsf_device_registration_source,
    struct wait_queue_head *, unsigned int, void *);
int lsf_prepaid_device_wake_locked(struct lsf_device_registration_source,
    struct wait_queue_head *, unsigned int, int, int, void *);
#endif
