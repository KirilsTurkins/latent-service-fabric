/* SPDX-License-Identifier: GPL-2.0-only */
/* Private typed allocation shapes, not a reservation or completeness proof. */
#ifndef LSF_STREAM_NETDEV_FIXED_GEOMETRY_PRIVATE_H
#define LSF_STREAM_NETDEV_FIXED_GEOMETRY_PRIVATE_H
#include <linux/types.h>

struct lsf_stream_netdev_fixed_geometry {
    u64 main_bytes, main_alignment;
    u64 tx_bytes, tx_alignment;
    u64 rx_bytes, rx_alignment;
    u64 ethtool_bytes, ethtool_alignment;
};

/* private_bytes comes only from the actual virtnet_info type geometry.
 * The selected source admits one TX and one RX queue; no caller count. */
int lsf_prepaid_stream_netdev_fixed_geometry(unsigned long private_bytes,
    struct lsf_stream_netdev_fixed_geometry *out);
#endif
