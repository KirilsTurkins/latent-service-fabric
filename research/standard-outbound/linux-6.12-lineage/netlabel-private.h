/* SPDX-License-Identifier: GPL-2.0-only */
/* Private builtin source. No exported origin/admission/free-certificate ABI. */
#ifndef LSF_STREAM_NETLABEL_PRIVATE_H
#define LSF_STREAM_NETLABEL_PRIVATE_H
#include <linux/types.h>
#include <linux/gfp_types.h>
struct sock;
struct sockaddr;
struct ip_options_rcu;
struct netlbl_lsm_secattr;
struct netlbl_lsm_catmap;
struct cipso_v4_doi;
struct policydb;
struct context;
struct ebitmap;
struct lsf_factory_blob;

#ifdef CONFIG_LSF_STREAM_FACTORY
int lsf_prepaid_netlabel_source(struct sock *, struct lsf_factory_blob *);
bool lsf_prepaid_label_domain_return(const void *);
bool lsf_prepaid_label_catmap_return(const void *);
bool lsf_prepaid_label_secattr_return(struct netlbl_lsm_secattr *);
bool lsf_prepaid_cipso_buffer_return(const void *);
bool lsf_prepaid_options_failed_return(const void *);
bool lsf_prepaid_options_retire(struct ip_options_rcu *);
char *lsf_prepaid_netlabel_strdup(const char *, const struct lsf_factory_blob *);
struct netlbl_lsm_secattr *lsf_prepaid_netlabel_sock_genattr(
    struct sock *, const struct lsf_factory_blob *);
int lsf_prepaid_security_sid_to_secattr(u32, struct netlbl_lsm_secattr *,
                                       const struct lsf_factory_blob *);
int lsf_prepaid_mls_export_cat(struct policydb *, struct context *,
                              struct netlbl_lsm_secattr *, const struct lsf_factory_blob *);
int lsf_prepaid_ebitmap_export(struct ebitmap *, struct netlbl_lsm_catmap **,
                              const struct lsf_factory_blob *);
int lsf_prepaid_catmap_setlong(struct netlbl_lsm_catmap **, u32, unsigned long,
                              gfp_t, const struct lsf_factory_blob *);
int lsf_prepaid_netlbl_sock_setattr(struct sock *, u16,
    const struct netlbl_lsm_secattr *, bool, const struct lsf_factory_blob *);
int lsf_prepaid_netlbl_conn_setattr(struct sock *, struct sockaddr *,
    const struct netlbl_lsm_secattr *, const struct lsf_factory_blob *);
int lsf_prepaid_cipso_sock_setattr(struct sock *, const struct cipso_v4_doi *,
    const struct netlbl_lsm_secattr *, bool, const struct lsf_factory_blob *);
#endif
#endif
