/* SPDX-License-Identifier: GPL-2.0-only */
/* Kernel-private source contract. No exported symbols or caller certificates. */
#ifndef LSF_STREAM_FACTORY_PRIVATE_H
#define LSF_STREAM_FACTORY_PRIVATE_H
#include <linux/net.h>
#include "prepaid.h"

struct lsf_factory_context;
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

/* Deliberately unavailable: mandatory security, outer VFS, protocol, RX,
 * route/cache/deferred layout and final-free consumers are not yet complete.
 * No operator input, device command, env, sysctl or boolean can supply them. */
static inline const struct lsf_factory_consumer *lsf_factory_selected_consumer(void)
{
    return NULL;
}
#endif
