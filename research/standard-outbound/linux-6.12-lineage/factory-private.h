/* SPDX-License-Identifier: GPL-2.0-only */
/* Kernel-private source contract. No exported symbols or caller certificates. */
#ifndef LSF_STREAM_FACTORY_PRIVATE_H
#define LSF_STREAM_FACTORY_PRIVATE_H
#include <linux/net.h>
#include "prepaid.h"

struct lsf_factory_context;
int lsf_factory_register(void);
struct lsf_factory_consumer {
    /* These must be compiled from the exact complete selected platform, not
     * registered dynamically. create includes outer socket/inode, security,
     * protocol and failure cleanup from the SAME prepaid context. */
    int (*create)(struct net *, int, int, int,
                  struct lsf_factory_context *, struct socket **);
    void (*close)(struct socket *, struct lsf_factory_context *);
};

/* No callback accepts an address/cookie to retrospectively establish origin. */
void *lsf_factory_allocate(struct lsf_factory_context *, unsigned long,
                         struct lsf_prepaid_ticket, int,
                         struct lsf_prepaid_ticket *);
int lsf_factory_return(struct lsf_factory_context *, struct lsf_prepaid_ticket);
int lsf_factory_deferred(struct lsf_factory_context *, int);
void lsf_factory_poison(struct lsf_factory_context *);
/* Allocator-only blob routing. The address may identify an existing birth
 * record for RETURN, never create or authenticate a new owner. Unknown arena
 * addresses poison/retain. No symbol is exported or exposed on the device. */
struct lsf_factory_blob {
    struct lsf_factory_context *context;
    struct lsf_prepaid_ticket ticket;
};
void *lsf_factory_blob_allocate(struct lsf_factory_context *, unsigned long,
                              unsigned int);
int lsf_factory_blob_lookup(const void *, unsigned int, struct lsf_factory_blob *);
int lsf_factory_blob_queue(const void *);
int lsf_factory_blob_finish(struct lsf_factory_blob, unsigned int);
void *lsf_factory_child_allocate(struct lsf_factory_blob, unsigned long,
                                unsigned int);
int lsf_factory_protocol_parent(const void *, struct lsf_factory_context *,
                                struct lsf_prepaid_ticket, struct lsf_factory_blob *);
int lsf_factory_options_publish(const void *);
int lsf_factory_options_queue(const void *);
int lsf_factory_options_owned(const void *, struct lsf_factory_blob);
int lsf_factory_netport_publish(const void *, unsigned int);
int lsf_factory_netport_queue(const void *);
int lsf_factory_netport_candidate(struct lsf_factory_context *, unsigned int,
                                 struct lsf_prepaid_ticket *, unsigned int *);
/* Caller holds the original Netport lock. Revalidates identity before even
 * deriving the node address; a copied candidate is not lifetime ownership. */
int lsf_factory_netport_current(struct lsf_factory_context *,
                               struct lsf_prepaid_ticket, unsigned int, void **);
void lsf_prepaid_netport_drain(struct lsf_factory_context *);
int lsf_factory_sidcache_publish(const void *, lsf_u64);
int lsf_factory_sidcache_queue(const void *);
int lsf_factory_sidcache_destroy(const void *);
int lsf_factory_sidcache_candidate(struct lsf_factory_context *, unsigned int,
                                  struct lsf_prepaid_ticket *, lsf_u64 *);
int lsf_factory_sidcache_current(struct lsf_factory_context *,
                                struct lsf_prepaid_ticket, lsf_u64, void **);
void lsf_prepaid_sidcache_drain(struct lsf_factory_context *);
struct sk_buff;
struct sk_buff *lsf_prepaid_audit_skb_new(struct lsf_factory_blob, unsigned int);
int lsf_factory_audit_head_current(const void *, unsigned long, struct lsf_factory_blob *);


int lsf_factory_avc_member(const void *, unsigned int, unsigned long,
                           struct lsf_factory_blob *);
int lsf_factory_avc_phase(struct lsf_factory_blob, unsigned int);
int lsf_factory_avc_publish(const void *, unsigned int);
int lsf_factory_avc_replace(const void *, const void *, unsigned int);
int lsf_factory_avc_queue(const void *);
int lsf_factory_avc_candidate(struct lsf_factory_context *, unsigned int,
                              struct lsf_prepaid_ticket *, unsigned int *);
int lsf_factory_avc_current(struct lsf_factory_context *,
                            struct lsf_prepaid_ticket, unsigned int, void **);
void lsf_prepaid_avc_drain(struct lsf_factory_context *);

/* Deliberately unavailable: mandatory security, outer VFS, protocol, RX,
 * route/cache/deferred layout and final-free consumers are not yet complete.
 * No operator input, device command, env, sysctl or boolean can supply them. */
static inline const struct lsf_factory_consumer *lsf_factory_selected_consumer(void)
{
    return NULL;
}
#endif
