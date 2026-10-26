/* SPDX-License-Identifier: GPL-2.0-only */
/* Include in pinned virtio_pci_common.c after its real private definitions.
 * No allocation, IRQ request, feature negotiation or successful-path guess.
 * IRQ domain/action/descriptors, PCI transport, retry counts and every other
 * descendant remain separate typed-producer obligations. ANCESTORS stays clear.
 */
#include <linux/cpumask.h>
#include <linux/overflow.h>
#include <net/lsf_stream_material_geometry_private.h>

int lsf_prepaid_stream_pci_material_geometry(struct lsf_stream_pci_material_geometry *out)
{
    struct virtio_pci_device *vp = NULL;
    size_t vqs, mask_backing = 0;
    if (!out) return -EINVAL;
    if (__alignof__(struct virtio_pci_vq_info) > 64u ||
        __alignof__(*vp->vqs) > 64u || __alignof__(*vp->msix_names) > 64u ||
        __alignof__(*vp->msix_affinity_masks) > 64u ||
        __alignof__(struct cpumask) > 64u ||
        check_mul_overflow((size_t)2, sizeof(*vp->vqs), &vqs))
        return -EOPNOTSUPP;
    /* alloc_cpumask_var adds backing ONLY in the real OFFSTACK build.
     * cpumask_size uses the actual kernel's runtime CPU mask extent; sizeof
     * the pointer slot cannot stand in for that separate allocation. */
    if (IS_ENABLED(CONFIG_CPUMASK_OFFSTACK)) {
        mask_backing = cpumask_size();
        if (!mask_backing) return -EOPNOTSUPP;
    }
    *out = (struct lsf_stream_pci_material_geometry){
        .vq_info_bytes = sizeof(struct virtio_pci_vq_info),
        .vq_info_alignment = __alignof__(struct virtio_pci_vq_info),
        .vqs_bytes = vqs, .vqs_alignment = __alignof__(*vp->vqs),
        .msix_name_bytes = sizeof(*vp->msix_names),
        .msix_name_alignment = __alignof__(*vp->msix_names),
        .msix_mask_slot_bytes = sizeof(*vp->msix_affinity_masks),
        .msix_mask_slot_alignment = __alignof__(*vp->msix_affinity_masks),
        .msix_mask_backing_bytes = mask_backing,
        .msix_mask_backing_alignment = __alignof__(struct cpumask)
    };
    return 0;
}
