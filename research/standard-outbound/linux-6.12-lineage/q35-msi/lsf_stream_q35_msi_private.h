/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_Q35_MSI_PRIVATE_H
#define LSF_STREAM_Q35_MSI_PRIVATE_H
#include <linux/types.h>
struct device;
struct pci_dev;
struct irq_domain;
struct irq_domain_info;
struct irq_domain_ops;
struct msi_domain_template;
struct fwnode_handle;
void lsf_factory_stream_constructor_retain_unknown(void);
int lsf_factory_stream_msi_selected(struct device *);
#define LSF_Q35_MSI_TEMPLATE 0u
#define LSF_Q35_MSI_FWNODE 1u
#define LSF_Q35_MSI_FWNAME 2u
#define LSF_Q35_MSI_DOMAIN 3u
#define LSF_Q35_MSI_NAME 4u
#define LSF_Q35_MSI_TOKEN_NAME 5u
#define LSF_Q35_MSI_PARTS 6u
#define LSF_Q35_MSI_KIND 0x1a0u
struct lsf_q35_msi_plan {
    unsigned int slot[LSF_Q35_MSI_PARTS];
    u64 generation[LSF_Q35_MSI_PARTS];
};
int lsf_q35_msi_geometry(unsigned int, unsigned long, unsigned long,
    unsigned long *, unsigned long *);
int lsf_q35_msi_bundle_geometry(unsigned long *, unsigned long *);
int lsf_q35_msi_prepare(struct device *, unsigned long, unsigned long,
    struct lsf_q35_msi_plan *);
void *lsf_q35_msi_take(struct device *, const struct lsf_q35_msi_plan *, unsigned int);
void lsf_q35_msi_discard(struct device *, struct lsf_q35_msi_plan *);
int lsf_q35_msi_classify(const void *, unsigned int, struct device **);
void *lsf_q35_msi_sibling(const void *, unsigned int, unsigned int, int);
int lsf_q35_msi_retire(const void *, unsigned int);
int lsf_q35_x86_vector_known(const struct irq_domain *);
int lsf_q35_x86_parent_known(const struct irq_domain *);
int lsf_q35_msi_template_known(const struct msi_domain_template *);
int lsf_q35_msi_ops_known(const struct irq_domain_ops *, const void *);
int lsf_q35_msi_domain_known(struct device *, const struct irq_domain *);
int lsf_q35_msi_current(struct device *);
int lsf_q35_msi_empty_locked(struct device *);
bool lsf_q35_msi_create(struct device *, unsigned int,
    const struct msi_domain_template *, unsigned int, void *, void *);
void lsf_q35_msi_remove(struct device *, unsigned int);
struct fwnode_handle *lsf_q35_fwnode(struct device *, const struct lsf_q35_msi_plan *, const char *);
struct irq_domain *lsf_q35_domain_create(const struct irq_domain_info *);
int lsf_q35_domain_free(struct irq_domain *);
int lsf_q35_fwnode_free(struct fwnode_handle *);
int lsf_q35_domain_bus_token(struct irq_domain *, unsigned int);
int lsf_q35_domain_remove_allowed(const struct irq_domain *);
int lsf_q35_domain_remove(struct irq_domain *);
int lsf_q35_domain_links_known(const struct irq_domain *);
void __iomem *lsf_q35_msix_map(struct pci_dev *, unsigned int);
#endif
