/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_CLEANUP_CLOSE_PRIVATE_H
#define LSF_STREAM_CLEANUP_CLOSE_PRIVATE_H
#include <net/lsf_stream_cleanup_association.h>
#define LSF_CLEANUP_REQUEST_CREATOR 1u
#define LSF_CLEANUP_REQUEST_OPENER 2u
int lsf_factory_cleanup_request_put(struct lsf_cleanup_task_source, unsigned int);
int lsf_factory_cleanup_creator_error(struct lsf_cleanup_task_source);
int lsf_factory_cleanup_worker_stop_take(struct lsf_cleanup_task_source *,
    struct kthread_worker **, struct task_struct **);
int lsf_factory_cleanup_worker_stopped(struct lsf_cleanup_task_source);
int lsf_factory_cleanup_request_pending(void);
void lsf_factory_cleanup_request_drain(void);
int lsf_prepaid_cleanup_request_irq_quiesce(struct lsf_cleanup_task_source);
void lsf_prepaid_cleanup_worker_destroy_full(void);
#endif
