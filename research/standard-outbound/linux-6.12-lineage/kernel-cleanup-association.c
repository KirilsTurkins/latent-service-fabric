/* SPDX-License-Identifier: GPL-2.0-only */
/* Real geometry in the TU containing the actual original owned request. */
int lsf_prepaid_cleanup_worker_geometry(unsigned long *request_bytes,
    unsigned long *worker_offset, unsigned long *worker_bytes)
{
    if (!request_bytes || !worker_offset || !worker_bytes)
        return -EINVAL;
    *request_bytes = sizeof(struct lsf_cleanup_request);
    *worker_offset = offsetof(struct lsf_cleanup_request, worker);
    *worker_bytes = sizeof(struct kthread_worker);
    return 0;
}
