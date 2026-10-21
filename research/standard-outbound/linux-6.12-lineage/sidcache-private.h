/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_SIDCACHE_PRIVATE_H
#define LSF_STREAM_SIDCACHE_PRIVATE_H
#include <linux/types.h>
struct sidtab;
struct sidtab_entry;
struct lsf_factory_blob;
struct lsf_factory_context;
struct lsf_prepaid_ticket;
void *lsf_prepaid_audit_dup(const struct lsf_factory_blob *, const void *, u32);
int lsf_prepaid_audit_string_return(const void *);
int lsf_prepaid_sid2str_put(struct sidtab *, struct sidtab_entry *, const char *,
                           u32, const struct lsf_factory_blob *);
int lsf_prepaid_sid2str_get(struct sidtab *, struct sidtab_entry *, char **, u32 *,
                           const struct lsf_factory_blob *);
void lsf_prepaid_sidcache_detach(struct sidtab *, struct lsf_factory_context *,
                                struct lsf_prepaid_ticket);
int lsf_prepaid_security_sid_to_context(u32, char **, u32 *, int,
                                       const struct lsf_factory_blob *);
#endif
