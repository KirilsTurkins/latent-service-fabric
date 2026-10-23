/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_CLEANUP_AUDIT_PRIVATE_H
#define LSF_STREAM_CLEANUP_AUDIT_PRIVATE_H
#include <net/lsf_stream_cleanup_perf.h>
int lsf_prepaid_cleanup_audit_geometry(unsigned int, unsigned long *, unsigned long *);
int lsf_prepaid_cleanup_audit_alloc(struct lsf_cleanup_task_source, struct task_struct *);
#endif
