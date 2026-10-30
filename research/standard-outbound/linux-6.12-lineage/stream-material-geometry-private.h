/* SPDX-License-Identifier: GPL-2.0-only */
/* Unselected typed inputs to the original material reservation producer.
 * These are allocation shapes, NOT owners or a completeness certificate.
 * No caller-supplied sizes, serialized cost claims or geometry bits live here.
 */
#ifndef LSF_STREAM_MATERIAL_GEOMETRY_PRIVATE_H
#define LSF_STREAM_MATERIAL_GEOMETRY_PRIVATE_H
#include <linux/errno.h>
#include <linux/types.h>

struct lsf_stream_net_material_geometry {
    /* Embedded tail of alloc_netdev_mqs, never a separate allocation. The
     * actual net/core producer must add its net_device/alignment/core births. */
    u64 netdev_private_bytes, netdev_private_alignment;
    u64 rss_bytes, rss_alignment;
    /* One selected RX/TX pair, no control queue. Temporary find_vqs arrays
     * have their own original births/returns, even if freed during probe. */
    u64 vqs_bytes, vqs_alignment;
    u64 vqs_info_bytes, vqs_info_alignment;
    u64 ctx_bytes, ctx_alignment;
};

struct lsf_stream_pci_material_geometry {
    u64 vq_info_bytes, vq_info_alignment;
    u64 vqs_bytes, vqs_alignment;
    /* Element sizes only: the real source-selected vector attempt supplies
     * its own count/parents, including failed attempts before any fallback. */
    u64 msix_name_bytes, msix_name_alignment;
    u64 msix_mask_slot_bytes, msix_mask_slot_alignment;
    u64 msix_mask_backing_bytes, msix_mask_backing_alignment;
};

int lsf_prepaid_stream_net_material_geometry(struct lsf_stream_net_material_geometry *);
int lsf_prepaid_stream_pci_material_geometry(struct lsf_stream_pci_material_geometry *);
#endif
