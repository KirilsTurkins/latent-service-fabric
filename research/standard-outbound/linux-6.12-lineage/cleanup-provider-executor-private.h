/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_CLEANUP_PROVIDER_EXECUTOR_H
#define LSF_STREAM_CLEANUP_PROVIDER_EXECUTOR_H
#include <net/lsf_stream_cleanup_provider_operation.h>
enum lsf_cleanup_provider_part {
    LSF_PROVIDER_POOL, LSF_PROVIDER_WORKER, LSF_PROVIDER_PWQ,
    LSF_PROVIDER_ATTRS, LSF_PROVIDER_CONTROL, LSF_PROVIDER_CONTEXT,
    LSF_PROVIDER_PARTS
};
/* Borrowed results of actual births in the SAME record array, not a ledger. */
struct lsf_cleanup_provider_storage {
    struct lsf_prepaid_ticket tickets[LSF_PROVIDER_PARTS];
    void *addresses[LSF_PROVIDER_PARTS];
};
int lsf_prepaid_cleanup_provider_part_geometry(unsigned int, unsigned long *, unsigned long *);
int lsf_factory_cleanup_provider_storage_reserve(struct lsf_cleanup_task_source,
    struct lsf_cleanup_provider_storage *);
int lsf_factory_cleanup_provider_storage_current(struct lsf_cleanup_task_source,
    unsigned int, const void *);
void *lsf_factory_cleanup_provider_control_current(const void *);
void lsf_factory_cleanup_provider_hold(struct lsf_cleanup_task_source);
int lsf_factory_cleanup_provider_pool_address(const void *);
int lsf_prepaid_cleanup_provider_worker_thread(void *);
int lsf_prepaid_cleanup_provider_attributes_bound(struct workqueue_struct *);
int lsf_prepaid_acpi_reference_queue_identity(struct workqueue_struct *);
/* No queue or pool address is accepted by the notification producer. */
void lsf_prepaid_cleanup_provider_pwq_drop(void *);
#endif
