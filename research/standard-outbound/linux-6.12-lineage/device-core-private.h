/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_STREAM_DEVICE_CORE_PRIVATE_H
#define LSF_STREAM_DEVICE_CORE_PRIVATE_H

struct device;
/* These are private source call sites, never caller certificates or ABI. */
int lsf_factory_device_core_begin(const void *);
int lsf_factory_device_core_owned(const void *);
void *lsf_factory_device_core_allocate(const void *, unsigned long);
/* Return: zero genuinely outside, one finished, negative poison/retain. */
int lsf_factory_device_core_return(const void *, const void *);
int lsf_factory_device_core_tail_enter(const void *);
void lsf_factory_device_core_tail_finish(const void *);
int lsf_prepaid_device_private_init(struct device *);

#endif
