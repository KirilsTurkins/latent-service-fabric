/* SPDX-License-Identifier: GPL-2.0-only */
/* Include in pinned virtio_net.c after its private types and
 * virtnet_rss_hdr_size. No allocation, feature selection or publication.
 * These shapes cover only the named direct births, not netdev/core/kernfs,
 * per-CPU/security/registration descendants or the already-owned RX/queues.
 */
#include <linux/overflow.h>
#include <net/lsf_stream_material_geometry_private.h>

int lsf_prepaid_stream_net_material_geometry(struct lsf_stream_net_material_geometry *out)
{
    struct virtio_net_rss_config_hdr *rss = NULL;
    size_t vqs, infos, ctx, rss_bytes;
    if (!out) return -EINVAL;
    if (__alignof__(struct virtnet_info) > 64u ||
        __alignof__(*rss) > 64u || __alignof__(struct virtqueue *) > 64u ||
        __alignof__(struct virtqueue_info) > 64u || __alignof__(bool) > 64u ||
        check_mul_overflow((size_t)2, sizeof(struct virtqueue *), &vqs) ||
        check_mul_overflow((size_t)2, sizeof(struct virtqueue_info), &infos) ||
        check_mul_overflow((size_t)2, sizeof(bool), &ctx))
        return -EOPNOTSUPP;
    /* The selected source forbids RSS/HASH_REPORT/CTRL_VQ/big/mergeable RX.
     * Original virtnet_rss_hdr_size still allocates ONE indirection entry
     * when has_rss is false. Omitting that birth would undercount probe.
     * This is the identical struct_size expression, not a guessed header. */
    rss_bytes = struct_size(rss, indirection_table, 1);
    if (!rss_bytes || rss_bytes == SIZE_MAX) return -EOVERFLOW;
    *out = (struct lsf_stream_net_material_geometry){
        .netdev_private_bytes = sizeof(struct virtnet_info),
        .netdev_private_alignment = __alignof__(struct virtnet_info),
        .rss_bytes = rss_bytes, .rss_alignment = __alignof__(*rss),
        .vqs_bytes = vqs, .vqs_alignment = __alignof__(struct virtqueue *),
        .vqs_info_bytes = infos, .vqs_info_alignment = __alignof__(struct virtqueue_info),
        .ctx_bytes = ctx, .ctx_alignment = __alignof__(bool)
    };
    return 0;
}
