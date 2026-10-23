/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_CLEANUP_WORKER_OPERATIONS_PRIVATE_H
#define LSF_STREAM_CLEANUP_WORKER_OPERATIONS_PRIVATE_H
#include <linux/errno.h>
#include <linux/preempt.h>
/* No Task argument or caller origin flag. Nonzero never takes normal fallback. */
int lsf_factory_cleanup_worker_operation_current(void);
#endif
