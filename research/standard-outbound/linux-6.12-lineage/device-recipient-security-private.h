/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_DEVICE_RECIPIENT_SECURITY_PRIVATE_H
#define LSF_STREAM_DEVICE_RECIPIENT_SECURITY_PRIVATE_H
#include <net/lsf_stream_device_recipient.h>
struct fown_struct;
struct fasync_struct;
struct lsf_factory_blob;
int lsf_prepaid_device_security_file_send_sigiotask(struct lsf_device_registration_source,
    struct task_struct *, struct fown_struct *, int);
int lsf_prepaid_device_selinux_file_send_sigiotask(struct task_struct *,
    struct fown_struct *, int, const struct lsf_factory_blob *);
bool lsf_prepaid_device_selinux_sigio_hook(int (*)(struct task_struct *, struct fown_struct *, int));
void lsf_prepaid_device_kill_fasync(struct lsf_device_registration_source,
    struct fasync_struct **, int, int);
void lsf_prepaid_device_sk_wake_async_rcu(struct lsf_device_registration_source,
    const struct sock *, int, int);
#endif
