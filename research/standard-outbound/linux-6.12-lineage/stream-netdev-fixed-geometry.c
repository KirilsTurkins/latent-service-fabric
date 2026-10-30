/* SPDX-License-Identifier: GPL-2.0-only */
/* Include at the END of pinned net/core/dev.c. These are the actual four
 * direct allocation shapes from alloc_netdev_mqs and its queue constructors.
 * No allocation, publication, configuration or future-child accounting.
 * Per-CPU state, hardware addresses, registration and all other descendants
 * require their own actual funded births; these shapes do not establish fit.
 */
#include <linux/errno.h>
#include <linux/kernel.h>
#include <linux/overflow.h>
#include <net/lsf_stream_netdev_fixed_geometry_private.h>

int lsf_prepaid_stream_netdev_fixed_geometry(unsigned long private_bytes,
    struct lsf_stream_netdev_fixed_geometry *out)
{
    struct net_device *dev = NULL;
    size_t main_bytes;

    if (!out || !private_bytes || private_bytes > INT_MAX)
        return -EINVAL;
    if (__alignof__(*dev) > 64u || __alignof__(*dev->_tx) > 64u ||
        __alignof__(*dev->_rx) > 64u || __alignof__(*dev->ethtool) > 64u)
        return -EOPNOTSUPP;
    /* Identical flexible-tail expression to the original allocator, including
     * the compiled net_device layout. Do not add guessed NETDEV_ALIGN padding. */
    main_bytes = struct_size(dev, priv, private_bytes);
    if (!main_bytes || main_bytes == SIZE_MAX)
        return -EOVERFLOW;
    *out = (struct lsf_stream_netdev_fixed_geometry){
        .main_bytes = main_bytes, .main_alignment = __alignof__(*dev),
        .tx_bytes = sizeof(*dev->_tx), .tx_alignment = __alignof__(*dev->_tx),
        .rx_bytes = sizeof(*dev->_rx), .rx_alignment = __alignof__(*dev->_rx),
        .ethtool_bytes = sizeof(*dev->ethtool),
        .ethtool_alignment = __alignof__(*dev->ethtool)
    };
    return 0;
}
