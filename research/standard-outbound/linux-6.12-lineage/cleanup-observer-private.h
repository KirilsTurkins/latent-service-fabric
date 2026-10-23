/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_CLEANUP_OBSERVER_PRIVATE_H
#define LSF_STREAM_CLEANUP_OBSERVER_PRIVATE_H
#include <linux/errno.h>
#if defined(CONFIG_TRACEPOINTS) && defined(CONFIG_KPROBES) && defined(CONFIG_PROC_EVENTS)
unsigned long lsf_cleanup_tracepoint_seal_bytes(void);
unsigned long lsf_cleanup_kprobe_seal_bytes(void);
unsigned long lsf_cleanup_connector_seal_bytes(void);
int lsf_cleanup_tracepoint_prebirth_seal(void);
int lsf_cleanup_kprobe_prebirth_seal(void);
int lsf_cleanup_connector_prebirth_seal(void);
void lsf_cleanup_tracepoint_prebirth_rollback(void);
void lsf_cleanup_kprobe_prebirth_rollback(void);
void lsf_cleanup_connector_prebirth_rollback(void);
#endif
#endif
