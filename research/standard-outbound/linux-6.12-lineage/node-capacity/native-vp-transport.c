/* SPDX-License-Identifier: GPL-2.0-only */
/* Append after native common.c. All ordinary bodies remain intact. */
#include <linux/overflow.h>
#include <net/lsf_node_capacity_private.h>
#include <uapi/linux/virtio_net.h>

int lsf_prepaid_stream_vp_transport_geometry(unsigned int kind, unsigned int count,
    unsigned long *bytes, unsigned long *alignment)
{
    struct virtio_pci_device *vp = NULL;
    unsigned long element, align;
    if (!bytes || !alignment) return -EINVAL;
#ifdef CONFIG_CPUMASK_OFFSTACK
    return -EOPNOTSUPP; /* No optional mask backing is silently omitted. */
#endif
    switch (kind) {
    case LSF_STREAM_VP_VQS:
        if (count != 2u) return -EOPNOTSUPP;
        element = sizeof(*vp->vqs); align = __alignof__(*vp->vqs); break;
    case LSF_STREAM_VP_NAMES:
        if (count != 2u && count != 3u) return -EOPNOTSUPP;
        element = sizeof(*vp->msix_names); align = __alignof__(*vp->msix_names); break;
    case LSF_STREAM_VP_MASKS:
        if (count != 2u && count != 3u) return -EOPNOTSUPP;
        element = sizeof(*vp->msix_affinity_masks); align = __alignof__(*vp->msix_affinity_masks); break;
    case LSF_STREAM_VP_INFO:
        if (count != 1u) return -EOPNOTSUPP;
        element = sizeof(struct virtio_pci_vq_info); align = __alignof__(struct virtio_pci_vq_info); break;
    default: return -EOPNOTSUPP;
    }
    if (!element || !align || align > 64u || (align & (align - 1u)) ||
        check_mul_overflow(element, (unsigned long)count, bytes)) return -EOVERFLOW;
    *alignment = align;
    return 0;
}

static int lsf_stream_vp_irq_ready(struct virtio_device *vdev)
{
    /* There is NO funded original IRQ provider in this source stage.
     * Never infer one from NodeFixed, a vector number, flags or a config bit.
     * Both selected MSI-X and INTx refuse BEFORE their first IRQ effect. */
    (void)vdev;
    return -EOPNOTSUPP;
}

static int lsf_stream_vp_transport_shape(struct virtio_device *vdev, unsigned int nvqs,
    struct virtqueue *vqs[], struct virtqueue_info infos[], struct irq_affinity *desc)
{
    if (nvqs != 2u || !vqs || !infos || desc) return -EOPNOTSUPP;
    /* Authenticate both original temporary tuple births before dereferencing
     * its rows; the generic native API cannot supply substitute heap arrays. */
    if (lsf_factory_stream_vp_transport_arguments(vdev, vqs, infos) != 1)
        return -EOPNOTSUPP;
    if (!infos[0].name || !infos[1].name || !infos[0].callback || !infos[1].callback ||
        strcmp(infos[0].name, "input.0") || strcmp(infos[1].name, "output.0") ||
        !infos[0].ctx || infos[1].ctx || vdev->id.device != VIRTIO_ID_NET ||
        !virtio_has_feature(vdev, VIRTIO_F_VERSION_1) ||
        !virtio_has_feature(vdev, VIRTIO_F_RING_RESET) ||
        virtio_has_feature(vdev, VIRTIO_F_ADMIN_VQ) ||
        virtio_has_feature(vdev, VIRTIO_NET_F_CTRL_VQ) ||
        virtio_has_feature(vdev, VIRTIO_F_RING_PACKED) ||
        virtio_has_feature(vdev, VIRTIO_RING_F_INDIRECT_DESC) ||
        virtio_has_feature(vdev, VIRTIO_NET_F_MRG_RXBUF) ||
        virtio_has_feature(vdev, VIRTIO_NET_F_HASH_REPORT)) return -EOPNOTSUPP;
#ifdef CONFIG_CPUMASK_OFFSTACK
    return -EOPNOTSUPP;
#endif
    return 1;
}

static void lsf_stream_vp_info_return(struct virtio_device *vdev,
    struct virtio_pci_vq_info *info)
{
    struct virtio_pci_device *vp = to_vp_device(vdev);
    unsigned int i;
    if (lsf_factory_stream_vp_transport_owned(vdev, info, LSF_STREAM_VP_INFO) != 1 ||
        lsf_factory_stream_vp_transport_owned(vdev, vp->vqs, LSF_STREAM_VP_VQS) != 1) {
        lsf_factory_stream_constructor_retain_unknown(); return;
    }
    /* No caller may retain a stale persistent slot after the native del_vq.
     * Native setup failure has not published an info slot and also comes here. */
    for (i = 0; i < 2u; ++i)
        if (vp->vqs[i] == info) vp->vqs[i] = NULL;
    (void)lsf_factory_stream_vp_transport_return(vdev, info, LSF_STREAM_VP_INFO);
}

static int lsf_stream_vp_arrays_clear(struct virtio_device *vdev)
{
    struct virtio_pci_device *vp = to_vp_device(vdev);
    if (!vp->vqs) return 1;
    if (lsf_factory_stream_vp_transport_owned(vdev, vp->vqs, LSF_STREAM_VP_VQS) != 1 ||
        vp->vqs[0] || vp->vqs[1]) {
        lsf_factory_stream_constructor_retain_unknown(); return 0;
    }
    return 1;
}

static int lsf_prepaid_stream_vp_request_msix_vectors(struct virtio_device *vdev, int nvectors,
				   bool per_vq_vectors, struct irq_affinity *desc)
{
	struct virtio_pci_device *vp_dev = to_vp_device(vdev);
	const char *name = dev_name(&vp_dev->vdev.dev);
	unsigned int flags = PCI_IRQ_MSIX;
	unsigned int i, v;
	int err = -ENOMEM;

	vp_dev->msix_vectors = nvectors;

	vp_dev->msix_names = lsf_factory_stream_vp_transport_allocate(vdev, LSF_STREAM_VP_NAMES, nvectors, 0);
	if (!vp_dev->msix_names)
		goto error;
	vp_dev->msix_affinity_masks
		= lsf_factory_stream_vp_transport_allocate(vdev, LSF_STREAM_VP_MASKS, nvectors, 0);
	if (!vp_dev->msix_affinity_masks)
		goto error;
	for (i = 0; i < nvectors; ++i)
		if (!alloc_cpumask_var(&vp_dev->msix_affinity_masks[i],
					GFP_KERNEL))
			goto error;

	if (!per_vq_vectors)
		desc = NULL;

	if (desc) {
		flags |= PCI_IRQ_AFFINITY;
		desc->pre_vectors++; /* virtio config vector */
	}

	err = lsf_stream_vp_irq_ready(vdev);
	if (err != 1) goto error;

	err = pci_alloc_irq_vectors_affinity(vp_dev->pci_dev, nvectors,
					     nvectors, flags, desc);
	if (err < 0)
		goto error;
	vp_dev->msix_enabled = 1;

	/* Set the vector used for configuration */
	v = vp_dev->msix_used_vectors;
	snprintf(vp_dev->msix_names[v], sizeof *vp_dev->msix_names,
		 "%s-config", name);
	err = lsf_stream_vp_irq_ready(vdev);
	if (err != 1) goto error;

	err = request_irq(pci_irq_vector(vp_dev->pci_dev, v),
			  vp_config_changed, 0, vp_dev->msix_names[v],
			  vp_dev);
	if (err)
		goto error;
	++vp_dev->msix_used_vectors;

	v = vp_dev->config_vector(vp_dev, v);
	/* Verify we had enough resources to assign the vector */
	if (v == VIRTIO_MSI_NO_VECTOR) {
		err = -EBUSY;
		goto error;
	}

	if (!per_vq_vectors) {
		/* Shared vector for all VQs */
		v = vp_dev->msix_used_vectors;
		snprintf(vp_dev->msix_names[v], sizeof *vp_dev->msix_names,
			 "%s-virtqueues", name);
		err = lsf_stream_vp_irq_ready(vdev);
		if (err != 1) goto error;

		err = request_irq(pci_irq_vector(vp_dev->pci_dev, v),
				  vp_vring_interrupt, 0, vp_dev->msix_names[v],
				  vp_dev);
		if (err)
			goto error;
		++vp_dev->msix_used_vectors;
	}
	return 0;
error:
	return err;
}

static struct virtqueue *lsf_prepaid_stream_vp_setup_vq(struct virtio_device *vdev, unsigned int index,
				     void (*callback)(struct virtqueue *vq),
				     const char *name,
				     bool ctx,
				     u16 msix_vec,
				     struct virtio_pci_vq_info **p_info)
{
	struct virtio_pci_device *vp_dev = to_vp_device(vdev);
	struct virtio_pci_vq_info *info = lsf_factory_stream_vp_transport_allocate(vdev, LSF_STREAM_VP_INFO, 1, index);
	struct virtqueue *vq;
	unsigned long flags;

	/* fill out our structure that represents an active queue */
	if (!info)
		return ERR_PTR(-ENOMEM);

	vq = vp_dev->setup_vq(vp_dev, info, index, callback, name, ctx,
			      msix_vec);
	if (IS_ERR(vq))
		goto out_info;

	info->vq = vq;
	if (callback) {
		spin_lock_irqsave(&vp_dev->lock, flags);
		if (!vp_is_slow_path_vector(msix_vec))
			list_add(&info->node, &vp_dev->virtqueues);
		else
			list_add(&info->node, &vp_dev->slow_virtqueues);
		spin_unlock_irqrestore(&vp_dev->lock, flags);
	} else {
		INIT_LIST_HEAD(&info->node);
	}

	*p_info = info;
	return vq;

out_info:
	lsf_stream_vp_info_return(vdev, info);
	return vq;
}

static void lsf_prepaid_stream_vp_del_vq(struct virtqueue *vq, struct virtio_pci_vq_info *info)
{
	struct virtio_pci_device *vp_dev = to_vp_device(vq->vdev);
	unsigned long flags;

	if (lsf_factory_stream_vp_transport_owned(&vp_dev->vdev, info, LSF_STREAM_VP_INFO) != 1) {
		lsf_factory_stream_constructor_retain_unknown(); return;
	}

	/*
	 * If it fails during re-enable reset vq. This way we won't rejoin
	 * info->node to the queue. Prevent unexpected irqs.
	 */
	if (!vq->reset) {
		spin_lock_irqsave(&vp_dev->lock, flags);
		list_del(&info->node);
		spin_unlock_irqrestore(&vp_dev->lock, flags);
	}

	vp_dev->del_vq(info);
	lsf_stream_vp_info_return(&vp_dev->vdev, info);
}

void lsf_prepaid_stream_vp_del_vqs(struct virtio_device *vdev)
{
	struct virtio_pci_device *vp_dev = to_vp_device(vdev);
	struct virtio_pci_vq_info *info;
	struct virtqueue *vq, *n;
	int i;

	struct lsf_node_capacity *node_owner;
	int node_selected;

	if (lsf_factory_stream_vp_transport_selected(vdev) != 1) {
		lsf_factory_stream_constructor_retain_unknown(); return;
	}
	node_selected = lsf_node_irq_pci_original(&vp_dev->pci_dev->dev, &node_owner);
	if (node_selected < 0 || (node_selected == 1 &&
	    !lsf_prepaid_stream_vp_device_known(vdev, vp_dev->pci_dev))) {
		lsf_factory_stream_constructor_retain_unknown(); return;
	}
	if (!node_selected) {
	/* No IRQ was admitted by this stage; unexpected flags retain everything. */
	if (vp_dev->msix_enabled || vp_dev->intx_enabled ||
	    vp_dev->msix_used_vectors || vp_dev->per_vq_vectors) {
		lsf_factory_stream_constructor_retain_unknown(); return;
	}
	}

	list_for_each_entry_safe(vq, n, &vdev->vqs, list) {
		info = vp_is_avq(vdev, vq->index) ? vp_dev->admin_vq.info :
						    vp_dev->vqs[vq->index];

		if (vp_dev->per_vq_vectors) {
			int v = info->msix_vector;
			if (v != VIRTIO_MSI_NO_VECTOR &&
			    !vp_is_slow_path_vector(v)) {
				int irq = pci_irq_vector(vp_dev->pci_dev, v);

				irq_update_affinity_hint(irq, NULL);
				free_irq(irq, vq);
			}
		}
		lsf_prepaid_stream_vp_del_vq(vq, info);
	}
	vp_dev->per_vq_vectors = false;

	if (vp_dev->intx_enabled) {
		free_irq(vp_dev->pci_dev->irq, vp_dev);
		vp_dev->intx_enabled = 0;
	}

	for (i = 0; i < vp_dev->msix_used_vectors; ++i)
		free_irq(pci_irq_vector(vp_dev->pci_dev, i), vp_dev);

	if (vp_dev->msix_affinity_masks) {
		for (i = 0; i < vp_dev->msix_vectors; i++)
			free_cpumask_var(vp_dev->msix_affinity_masks[i]);
	}

	if (vp_dev->msix_enabled) {
		/* Disable the vector used for configuration */
		vp_dev->config_vector(vp_dev, VIRTIO_MSI_NO_VECTOR);

		pci_free_irq_vectors(vp_dev->pci_dev);
		vp_dev->msix_enabled = 0;
	}

	vp_dev->msix_vectors = 0;
	vp_dev->msix_used_vectors = 0;
	{
		void *retired = vp_dev->msix_names;
		vp_dev->msix_names = NULL;
		(void)lsf_factory_stream_vp_transport_return(vdev, retired, LSF_STREAM_VP_NAMES);
	}
	{
		void *retired = vp_dev->msix_affinity_masks;
		vp_dev->msix_affinity_masks = NULL;
		(void)lsf_factory_stream_vp_transport_return(vdev, retired, LSF_STREAM_VP_MASKS);
	}
	if (!lsf_stream_vp_arrays_clear(vdev)) return;
	{
		void *retired = vp_dev->vqs;
		vp_dev->vqs = NULL;
		(void)lsf_factory_stream_vp_transport_return(vdev, retired, LSF_STREAM_VP_VQS);
	}
}

static struct virtqueue *
lsf_prepaid_stream_vp_find_one_vq_msix(struct virtio_device *vdev, int queue_idx,
		    vq_callback_t *callback, const char *name, bool ctx,
		    bool slow_path, int *allocated_vectors,
		    enum vp_vq_vector_policy vector_policy,
		    struct virtio_pci_vq_info **p_info)
{
	struct virtio_pci_device *vp_dev = to_vp_device(vdev);
	struct virtqueue *vq;
	u16 msix_vec;
	int err;

	if (!callback)
		msix_vec = VIRTIO_MSI_NO_VECTOR;
	else if (vector_policy == VP_VQ_VECTOR_POLICY_EACH ||
		 (vector_policy == VP_VQ_VECTOR_POLICY_SHARED_SLOW &&
		 !slow_path))
		msix_vec = (*allocated_vectors)++;
	else if (vector_policy != VP_VQ_VECTOR_POLICY_EACH &&
		 slow_path)
		msix_vec = VP_MSIX_CONFIG_VECTOR;
	else
		msix_vec = VP_MSIX_VQ_VECTOR;
	vq = lsf_prepaid_stream_vp_setup_vq(vdev, queue_idx, callback, name, ctx, msix_vec,
			 p_info);
	if (IS_ERR(vq))
		return vq;

	if (vector_policy == VP_VQ_VECTOR_POLICY_SHARED ||
	    msix_vec == VIRTIO_MSI_NO_VECTOR ||
	    vp_is_slow_path_vector(msix_vec))
		return vq;

	/* allocate per-vq irq if available and necessary */
	snprintf(vp_dev->msix_names[msix_vec], sizeof(*vp_dev->msix_names),
		 "%s-%s", dev_name(&vp_dev->vdev.dev), name);
	err = lsf_stream_vp_irq_ready(vdev);
	if (err == 1)
	err = request_irq(pci_irq_vector(vp_dev->pci_dev, msix_vec),
			  vring_interrupt, 0,
			  vp_dev->msix_names[msix_vec], vq);
	if (err) {
		lsf_prepaid_stream_vp_del_vq(vq, *p_info);
		return ERR_PTR(err);
	}

	return vq;
}

static int lsf_prepaid_stream_vp_find_vqs_msix(struct virtio_device *vdev, unsigned int nvqs,
			    struct virtqueue *vqs[],
			    struct virtqueue_info vqs_info[],
			    enum vp_vq_vector_policy vector_policy,
			    struct irq_affinity *desc)
{
	struct virtio_pci_device *vp_dev = to_vp_device(vdev);
	struct virtio_pci_admin_vq *avq = &vp_dev->admin_vq;
	struct virtqueue_info *vqi;
	int i, err, nvectors, allocated_vectors, queue_idx = 0;
	struct virtqueue *vq;
	bool per_vq_vectors;
	u16 avq_num = 0;

	vp_dev->vqs = lsf_factory_stream_vp_transport_allocate(vdev, LSF_STREAM_VP_VQS, nvqs, 0);
	if (!vp_dev->vqs)
		return -ENOMEM;

	if (vp_dev->avq_index) {
		err = vp_dev->avq_index(vdev, &avq->vq_index, &avq_num);
		if (err)
			goto error_find;
	}

	per_vq_vectors = vector_policy != VP_VQ_VECTOR_POLICY_SHARED;

	if (per_vq_vectors) {
		/* Best option: one for change interrupt, one per vq. */
		nvectors = 1;
		for (i = 0; i < nvqs; ++i) {
			vqi = &vqs_info[i];
			if (vqi->name && vqi->callback)
				++nvectors;
		}
		if (avq_num && vector_policy == VP_VQ_VECTOR_POLICY_EACH)
			++nvectors;
	} else {
		/* Second best: one for change, shared for all vqs. */
		nvectors = 2;
	}

	err = lsf_prepaid_stream_vp_request_msix_vectors(vdev, nvectors, per_vq_vectors, desc);
	if (err)
		goto error_find;

	vp_dev->per_vq_vectors = per_vq_vectors;
	allocated_vectors = vp_dev->msix_used_vectors;
	for (i = 0; i < nvqs; ++i) {
		vqi = &vqs_info[i];
		if (!vqi->name) {
			vqs[i] = NULL;
			continue;
		}
		vqs[i] = lsf_prepaid_stream_vp_find_one_vq_msix(vdev, queue_idx, vqi->callback,
					     vqi->name, vqi->ctx, false,
					     &allocated_vectors, vector_policy,
					     &vp_dev->vqs[queue_idx]);
		queue_idx++;
		if (IS_ERR(vqs[i])) {
			err = PTR_ERR(vqs[i]);
			goto error_find;
		}
	}

	if (!avq_num)
		return 0;
	sprintf(avq->name, "avq.%u", avq->vq_index);
	vq = lsf_prepaid_stream_vp_find_one_vq_msix(vdev, avq->vq_index, vp_modern_avq_done,
				 avq->name, false, true, &allocated_vectors,
				 vector_policy, &vp_dev->admin_vq.info);
	if (IS_ERR(vq)) {
		err = PTR_ERR(vq);
		goto error_find;
	}

	return 0;

error_find:
	lsf_prepaid_stream_vp_del_vqs(vdev);
	return err;
}

static int lsf_prepaid_stream_vp_find_vqs_intx(struct virtio_device *vdev, unsigned int nvqs,
			    struct virtqueue *vqs[],
			    struct virtqueue_info vqs_info[])
{
	struct virtio_pci_device *vp_dev = to_vp_device(vdev);
	struct virtio_pci_admin_vq *avq = &vp_dev->admin_vq;
	int i, err, queue_idx = 0;
	struct virtqueue *vq;
	u16 avq_num = 0;
	struct lsf_node_capacity *node_owner;
	int node_selected = lsf_node_irq_pci_original(&vp_dev->pci_dev->dev, &node_owner);

	/* Selected Node capacity is MSI-X only. Never borrow an ordinary shared
	 * OS descriptor after the three bounded MSI-X attempts fail. This remains
	 * independent of any future positive MSI-X provider/funding gate. */
	if (node_selected)
		return node_selected < 0 ? node_selected : -EOPNOTSUPP;

	vp_dev->vqs = lsf_factory_stream_vp_transport_allocate(vdev, LSF_STREAM_VP_VQS, nvqs, 0);
	if (!vp_dev->vqs)
		return -ENOMEM;

	if (vp_dev->avq_index) {
		err = vp_dev->avq_index(vdev, &avq->vq_index, &avq_num);
		if (err)
			goto out_del_vqs;
	}

	err = lsf_stream_vp_irq_ready(vdev);
	if (err != 1) goto out_del_vqs;

	err = request_irq(vp_dev->pci_dev->irq, vp_interrupt, IRQF_SHARED,
			dev_name(&vdev->dev), vp_dev);
	if (err)
		goto out_del_vqs;

	vp_dev->intx_enabled = 1;
	vp_dev->per_vq_vectors = false;
	for (i = 0; i < nvqs; ++i) {
		struct virtqueue_info *vqi = &vqs_info[i];

		if (!vqi->name) {
			vqs[i] = NULL;
			continue;
		}
		vqs[i] = lsf_prepaid_stream_vp_setup_vq(vdev, queue_idx, vqi->callback,
				     vqi->name, vqi->ctx,
				     VIRTIO_MSI_NO_VECTOR, &vp_dev->vqs[queue_idx]);
		queue_idx++;
		if (IS_ERR(vqs[i])) {
			err = PTR_ERR(vqs[i]);
			goto out_del_vqs;
		}
	}

	if (!avq_num)
		return 0;
	sprintf(avq->name, "avq.%u", avq->vq_index);
	vq = lsf_prepaid_stream_vp_setup_vq(vdev, avq->vq_index, vp_modern_avq_done, avq->name,
			 false, VIRTIO_MSI_NO_VECTOR,
			 &vp_dev->admin_vq.info);
	if (IS_ERR(vq)) {
		err = PTR_ERR(vq);
		goto out_del_vqs;
	}

	return 0;
out_del_vqs:
	lsf_prepaid_stream_vp_del_vqs(vdev);
	return err;
}

int lsf_prepaid_stream_vp_find_vqs(struct virtio_device *vdev, unsigned int nvqs,
		struct virtqueue *vqs[], struct virtqueue_info vqs_info[],
		struct irq_affinity *desc)
{
	int err;

	err = lsf_stream_vp_transport_shape(vdev, nvqs, vqs, vqs_info, desc);
	if (err != 1) return err;

	/* Try MSI-X with one vector per queue. */
	err = lsf_prepaid_stream_vp_find_vqs_msix(vdev, nvqs, vqs, vqs_info,
			       VP_VQ_VECTOR_POLICY_EACH, desc);
	if (!err)
		return 0;
	/* Fallback: MSI-X with one shared vector for config and
	 * slow path queues, one vector per queue for the rest.
	 */
	err = lsf_prepaid_stream_vp_find_vqs_msix(vdev, nvqs, vqs, vqs_info,
			       VP_VQ_VECTOR_POLICY_SHARED_SLOW, desc);
	if (!err)
		return 0;
	/* Fallback: MSI-X with one vector for config, one shared for queues. */
	err = lsf_prepaid_stream_vp_find_vqs_msix(vdev, nvqs, vqs, vqs_info,
			       VP_VQ_VECTOR_POLICY_SHARED, desc);
	if (!err)
		return 0;
	/* Is there an interrupt? If not give up. */
	if (!(to_vp_device(vdev)->pci_dev->irq))
		return err;
	/* Finally fall back to regular interrupts. */
	return lsf_prepaid_stream_vp_find_vqs_intx(vdev, nvqs, vqs, vqs_info);
}
