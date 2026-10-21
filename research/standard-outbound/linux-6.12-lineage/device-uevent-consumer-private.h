/* SPDX-License-Identifier: GPL-2.0-only */
/* WIP extra actual-TU consumer declarations; not a registrar or authority. */
#ifndef LSF_STREAM_DEVICE_UEVENT_CONSUMER_PRIVATE_H
#define LSF_STREAM_DEVICE_UEVENT_CONSUMER_PRIVATE_H
#include <net/lsf_stream_device_uevent.h>
#define LSF_DEVICE_UEVENT_MAX_ANCESTORS 256u
struct kobject;
struct kset_uevent_ops;
struct device;
struct bus_type;
int lsf_factory_device_uevent_path_bytes(const void *,
    struct lsf_device_registration_source *, unsigned long *);
struct device_type;
struct sock;
bool lsf_prepaid_device_selinux_socket_hook(int (*)(struct sock *, struct sk_buff *));
int lsf_prepaid_device_uevent_device(const struct kobject *);
int lsf_prepaid_device_uevent_ops_known(const struct kset_uevent_ops *);
int lsf_prepaid_device_uevent_pci_bus_known(const struct bus_type *);
int lsf_prepaid_device_uevent_pci_type_known(const struct device_type *);
#endif
