/* SPDX-License-Identifier: GPL-2.0-only */
/* Kernel-private stack copy of an existing birth, not a registration token.
 * Every consumer revalidates its actual original record before use. No caller
 * can install a factory, adopt an address, create an owner or refund backing. */
#ifndef LSF_STREAM_DEVICE_REGISTRATION_PRIVATE_H
#define LSF_STREAM_DEVICE_REGISTRATION_PRIVATE_H
#include <linux/types.h>

/* Cross-TU tags are checked against the actual same-bank enum in factory.c. */
#define LSF_REGISTRATION_KIND_NODE 0x10cu
#define LSF_REGISTRATION_KIND_NAME 0x10du
#define LSF_REGISTRATION_KIND_IDR_NODE 0x10eu

struct lsf_device_registration_source {
    const void *address;
    unsigned int kind, slot, pci_slot;
    u64 generation, pci_generation;
};

int lsf_factory_device_registration_kobject(const void *,
    struct lsf_device_registration_source *);
int lsf_factory_device_registration_node(const void *,
    struct lsf_device_registration_source *);
int lsf_factory_device_registration_current(struct lsf_device_registration_source);
int lsf_factory_device_registration_constructor_revoke(void);
void *lsf_factory_device_registration_allocate(
    struct lsf_device_registration_source, unsigned long, unsigned int);
int lsf_factory_device_registration_return_begin(const void *, unsigned int,
    struct lsf_device_registration_source *);
int lsf_factory_device_registration_return_finish(
    struct lsf_device_registration_source);

struct radix_tree_root;
struct radix_tree_iter;
struct idr;
void __rcu **lsf_prepaid_device_idr_get_free(struct lsf_device_registration_source,
    struct radix_tree_root *, struct radix_tree_iter *, gfp_t, unsigned long);
int lsf_prepaid_device_idr_alloc_cyclic(struct lsf_device_registration_source,
    struct idr *, void *, int, int, gfp_t);

#endif
