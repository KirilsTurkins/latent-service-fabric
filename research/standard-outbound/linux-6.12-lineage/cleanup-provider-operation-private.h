/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_CLEANUP_PROVIDER_OPERATION_H
#define LSF_STREAM_CLEANUP_PROVIDER_OPERATION_H
#include <net/lsf_stream_cleanup_lifecycle.h>
#include <linux/workqueue.h>
/* Physical ownership is not an operation grant. Zero preserves old births. */
enum lsf_cleanup_physical_role {
    LSF_CLEANUP_PHYSICAL_PRIVATE,
    LSF_CLEANUP_PHYSICAL_PROVIDER
};
int lsf_prepaid_cleanup_provider_geometry(unsigned long *, unsigned long *,
    unsigned long *, unsigned long *);
int lsf_factory_cleanup_provider_bind(struct lsf_cleanup_task_source,
    struct lsf_prepaid_ticket, struct lsf_prepaid_ticket);
int lsf_factory_cleanup_provider_physical_current(struct lsf_cleanup_task_source *);
int lsf_factory_cleanup_provider_snapshot_source(struct lsf_cleanup_task_source,
    void **, void **);
int lsf_prepaid_cleanup_provider_snapshot(struct lsf_cleanup_task_source,
    struct work_struct **, work_func_t *);
/* No caller Task, worker, work address, function or origin flag is accepted. */
void lsf_factory_cleanup_provider_dispatch_begin(void);
void lsf_factory_cleanup_provider_dispatch_end(void);
int lsf_factory_cleanup_provider_operation_current(void);
#endif
