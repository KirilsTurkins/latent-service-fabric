/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef _LSF_STREAM_NETDEV_CLASSDIR_PRIVATE_H
#define _LSF_STREAM_NETDEV_CLASSDIR_PRIVATE_H
struct device; struct kobject; struct class;
#define LSF_STREAM_CLASSDIR_INITIALIZED 16u
int lsf_prepaid_stream_netdev_class_known(const struct class *);
int lsf_prepaid_stream_netdev_classdir_geometry(unsigned long *, unsigned long *);
int lsf_prepaid_stream_netdev_classdir_initialized(const struct kobject *);
struct kobject *lsf_prepaid_stream_netdev_parent(struct device *, struct device *);
int lsf_factory_stream_netdev_classdir_select(struct device *, struct device *);
void *lsf_factory_stream_netdev_classdir_allocate(struct device *);
int lsf_factory_stream_netdev_classdir_name(void *, struct kobject *, const char *);
int lsf_factory_stream_netdev_classdir_publish(struct device *, void *);
int lsf_factory_stream_netdev_classdir_current(struct device *, const struct kobject *);
int lsf_factory_stream_netdev_classdir_queue(const void *);
int lsf_factory_stream_netdev_classdir_tail_enter(const void *);
int lsf_factory_stream_netdev_classdir_name_return(const void *, const void *);
int lsf_factory_stream_netdev_classdir_tail_finish(const void *);
#endif
