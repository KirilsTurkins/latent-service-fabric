/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_CLEANUP_IO_PRIVATE_H
#define LSF_STREAM_CLEANUP_IO_PRIVATE_H
#include <net/lsf_stream_cleanup_clone.h>
int lsf_prepaid_cleanup_io_geometry(unsigned long *, unsigned long *);
int lsf_factory_cleanup_io_reserve(const struct task_struct *, unsigned long,
    unsigned long, void **);
int lsf_prepaid_cleanup_copy_io(struct lsf_cleanup_task_source,
    unsigned long, struct task_struct *);
#endif
