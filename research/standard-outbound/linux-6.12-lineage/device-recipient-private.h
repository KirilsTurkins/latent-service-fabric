/* SPDX-License-Identifier: GPL-2.0-only */
/* Uninstalled explicit continuation sources. No task allocator override. */
#ifndef LSF_STREAM_DEVICE_RECIPIENT_PRIVATE_H
#define LSF_STREAM_DEVICE_RECIPIENT_PRIVATE_H
#include <net/lsf_stream_device_uevent.h>
#include <linux/pid.h>

#define LSF_DEVICE_RECIPIENT_KIND_WORK 0x113u
#define LSF_DEVICE_RECIPIENT_KIND_SIGQUEUE 0x114u

struct sock;
struct sigqueue;
struct kernel_siginfo;
struct task_struct;
int lsf_factory_device_recipient_begin(const void *, const struct sock *,
    struct lsf_device_registration_source *);
int lsf_factory_device_recipient_current(struct lsf_device_registration_source,
    const struct sock *);
int lsf_factory_device_recipient_finish(struct lsf_device_registration_source);
struct sigqueue *lsf_factory_device_recipient_signal_allocate(
    struct lsf_device_registration_source);
int lsf_factory_device_recipient_signal_birth(const struct sigqueue *,
    struct lsf_device_registration_source *);
/* One means queued for the actual RCU handoff, not occupancy/final return. */
int lsf_factory_device_recipient_signal_return(const struct sigqueue *);
int lsf_prepaid_device_do_send_sig_info(struct lsf_device_registration_source,
    int, struct kernel_siginfo *, struct task_struct *, enum pid_type);

#endif
