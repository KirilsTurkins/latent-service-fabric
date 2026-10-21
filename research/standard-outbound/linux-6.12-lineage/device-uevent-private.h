/* SPDX-License-Identifier: GPL-2.0-only */
/* WIP: actual NodeFixed event births, never an application-context alias. */
#ifndef LSF_STREAM_DEVICE_UEVENT_PRIVATE_H
#define LSF_STREAM_DEVICE_UEVENT_PRIVATE_H
#include <net/lsf_stream_device_registration.h>
#define LSF_DEVICE_UEVENT_KIND_ENV 0x10fu
#define LSF_DEVICE_UEVENT_KIND_PATH 0x110u
#define LSF_DEVICE_UEVENT_KIND_SKB 0x111u
#define LSF_DEVICE_UEVENT_KIND_HEAD 0x112u
/* A head shape limit inside the ORIGINAL infrastructure bank. This does not
 * create a DNS owner, extra backing, per-event quota or a second ledger. */
#define LSF_DEVICE_UEVENT_MAX_HEAD_BYTES 65536u
struct netlink_tap;
int lsf_factory_device_tap_admit(struct netlink_tap *);
void lsf_factory_device_tap_retired(struct netlink_tap *);
int lsf_factory_device_uevent_kobject(const void *, struct lsf_device_registration_source *);
int lsf_factory_device_uevent_birth(const void *, unsigned int, struct lsf_device_registration_source *);
int lsf_factory_device_uevent_current(struct lsf_device_registration_source);
void *lsf_factory_device_uevent_allocate(struct lsf_device_registration_source,
    unsigned long, unsigned int);
int lsf_factory_device_uevent_return(const void *, unsigned int);
int lsf_factory_device_uevent_head_current(const void *, unsigned long,
    struct lsf_device_registration_source *);
void lsf_factory_device_uevent_poison(void);
struct sk_buff;
struct sk_buff *lsf_prepaid_device_uevent_skb_new(struct lsf_device_registration_source,
    unsigned int);
#endif
