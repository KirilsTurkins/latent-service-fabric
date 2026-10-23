/* SPDX-License-Identifier: GPL-2.0-only */
/* Uninstalled constructor descendants. No selected provider or public ABI. */
#ifndef LSF_STREAM_CLEANUP_DESCENDANTS_PRIVATE_H
#define LSF_STREAM_CLEANUP_DESCENDANTS_PRIVATE_H
#include <linux/gfp_types.h>
#include <net/lsf_stream_cleanup_lifecycle.h>
struct cred;

#define LSF_CLEANUP_CLONE_FLAGS (CLONE_FS | CLONE_FILES | CLONE_VM | CLONE_UNTRACED)

enum lsf_cleanup_child_kind {
    LSF_CLEANUP_CRED,
    LSF_CLEANUP_CRED_SECURITY,
    LSF_CLEANUP_SIGHAND,
    LSF_CLEANUP_SIGNAL,
    LSF_CLEANUP_DELAY,
    LSF_CLEANUP_CHILD_KINDS
};
enum lsf_cleanup_final_phase {
    LSF_CLEANUP_FINAL_NONE,
    LSF_CLEANUP_FINAL_DESTRUCTORS,
    LSF_CLEANUP_FINAL_WAITING,
    LSF_CLEANUP_FINAL_RETURNED
};

/* Geometry comes from the TU containing the REAL maintained type, including
 * the sighand RCU wrapper and initialized composite LSM size. */
int lsf_prepaid_cleanup_child_geometry(unsigned int, unsigned long *, unsigned long *);
int lsf_prepaid_cleanup_cred_geometry(unsigned long *, unsigned long *);
int lsf_prepaid_cleanup_cred_security_geometry(unsigned long *, unsigned long *);
void *lsf_factory_cleanup_child_new(struct lsf_cleanup_task_source,
    struct task_struct *, unsigned int, const void *);
int lsf_factory_cleanup_child_defer(const void *, unsigned int);
int lsf_factory_cleanup_child_finish(const void *, unsigned int);
int lsf_factory_cleanup_task_destruct_begin(struct task_struct *);
int lsf_factory_cleanup_final_pending(void);
void lsf_factory_cleanup_final_drain(void);

int lsf_prepaid_cleanup_copy_creds(struct lsf_cleanup_task_source,
    struct task_struct *, unsigned long);
int lsf_prepaid_cleanup_security_prepare_creds(struct lsf_cleanup_task_source,
    struct task_struct *, struct cred *, const struct cred *, gfp_t);
#endif
