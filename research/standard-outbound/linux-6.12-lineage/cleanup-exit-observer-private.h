/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_CLEANUP_EXIT_OBSERVER_PRIVATE_H
#define LSF_STREAM_CLEANUP_EXIT_OBSERVER_PRIVATE_H
#include <linux/errno.h>
#if defined(CONFIG_TASKSTATS) && defined(CONFIG_BSD_PROCESS_ACCT)
unsigned long lsf_cleanup_taskstats_seal_bytes(void);
unsigned long lsf_cleanup_acct_seal_bytes(void);
int lsf_cleanup_taskstats_prebirth_seal(void);
int lsf_cleanup_acct_prebirth_seal(void);
void lsf_cleanup_taskstats_prebirth_rollback(void);
void lsf_cleanup_acct_prebirth_rollback(void);
#endif
#endif
