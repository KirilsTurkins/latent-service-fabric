/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef _LSF_STREAM_NETDEV_NOTIFY_PRIVATE_H
#define _LSF_STREAM_NETDEV_NOTIFY_PRIVATE_H
#include <linux/kconfig.h>
#include <net/lsf_stream_netdev_directory_private.h>

struct device;
struct acpi_bus_type;

int lsf_factory_stream_netdev_notify_kind(const struct device *);
int lsf_factory_stream_netdev_notify_lifetime(const struct device *);
int lsf_factory_stream_netdev_notify_profile(const struct device *);
int lsf_factory_stream_netdev_notify_firmware_write(const struct device *);
int lsf_factory_stream_netdev_notify_software_decision(const struct device *, const void *);
int lsf_prepaid_stream_netdev_platform_notify(struct device *);
int lsf_prepaid_stream_netdev_platform_remove(struct device *);

#if IS_ENABLED(CONFIG_ACPI)
int lsf_prepaid_stream_netdev_acpi_probe(struct device *);
#else
static inline int lsf_prepaid_stream_netdev_acpi_probe(struct device *dev)
{
    (void)dev;
    return 0; /* Unsupported profile; no notification has been performed. */
}
#endif

#if IS_BUILTIN(CONFIG_USB) && IS_ENABLED(CONFIG_ACPI)
int lsf_prepaid_stream_netdev_usb_acpi_type(const struct acpi_bus_type *);
#else
static inline int lsf_prepaid_stream_netdev_usb_acpi_type(const struct acpi_bus_type *type)
{
    (void)type;
    return 0; /* Never adopt a module's callback or its lifetime. */
}
#endif
#endif
