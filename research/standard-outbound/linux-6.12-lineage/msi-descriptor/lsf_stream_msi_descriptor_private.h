/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_MSI_DESCRIPTOR_PRIVATE_H
#define LSF_STREAM_MSI_DESCRIPTOR_PRIVATE_H
#include <linux/types.h>
struct device;
struct pci_dev;
struct xarray;
struct xa_node;
struct xa_state;
struct msi_desc;
#define LSF_MSI_DESC_KIND 0x1b0u
#define LSF_MSI_NODE_ROLE 3u
#define LSF_MSI_STORE_PARTS 4u
#define LSF_MSI_ANY_DESC_ROLE 4u
struct lsf_msi_store_plan {
    unsigned int nvec, slot[LSF_MSI_STORE_PARTS];
    u64 generation[LSF_MSI_STORE_PARTS];
};
int lsf_msi_desc_geometry(unsigned long *, unsigned long *);
int lsf_msi_node_geometry(unsigned long *, unsigned long *);
unsigned long lsf_msi_store_offset(void);
int lsf_msi_store_prepare(struct device *, unsigned int, struct lsf_msi_store_plan *);
void lsf_msi_store_discard(struct device *, struct lsf_msi_store_plan *);
void *lsf_msi_store_take(struct device *, unsigned int);
int lsf_msi_store_classify(const void *, unsigned int, struct device **);
int lsf_msi_store_retire(const void *, unsigned int);
int lsf_msi_store_radix_selected(const void *);
int lsf_msi_store_xa_selected(const struct xarray *);
struct xa_node *lsf_msi_store_node_take(const struct xarray *);
int lsf_msi_store_node_for(const void *, const struct xarray *);
int lsf_msi_descriptor_prepare(struct pci_dev *, unsigned int, struct lsf_msi_store_plan *);
int lsf_msi_descriptor_setup(struct pci_dev *, int, int);
int lsf_msi_descriptor_insert_allowed(struct device *, const struct msi_desc *, unsigned int, unsigned int);
int lsf_msi_xa_insert_allowed(const struct xarray *, unsigned long, const void *);
struct msi_desc *lsf_msi_descriptor_allocate(struct device *, unsigned int, const struct msi_desc *);
int lsf_msi_descriptor_free(struct msi_desc *);
void lsf_factory_stream_constructor_retain_unknown(void);
#endif
