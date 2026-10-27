/* SPDX-License-Identifier: GPL-2.0+ */
/* Included after native XArray definitions. Selected private device store only. */
#include <net/lsf_stream_msi_descriptor_private.h>
int lsf_msi_node_geometry(unsigned long *bytes, unsigned long *alignment)
{
    if (!bytes || !alignment || __alignof__(struct xa_node) > 64u || XA_CHUNK_SIZE < 3u)
        return -EOPNOTSUPP;
    *bytes = sizeof(struct xa_node);
    *alignment = __alignof__(struct xa_node);
    return 0;
}

static struct xa_node *lsf_msi_xa_preallocate(struct xa_state *xas, gfp_t gfp)
{
    struct xa_node *node;
    (void)gfp; /* No fallback slab, reclaim or new charge in this branch. */
    if (xas->xa_alloc || xas->xa_index > 2u || xas->xa_shift || xas->xa_sibs) {
        lsf_factory_stream_constructor_retain_unknown(); return NULL;
    }
    node = lsf_msi_store_node_take(xas->xa);
    if (!node) return NULL;
    /* Same native cache constructor, before handing ownership to the operation.
     * Before tree publication ONLY, array is an operation-identity marker.
     * xas_alloc consumes it once and installs the native actual array pointer.
     * xas_destroy/RCU free never use this overwritten field for provenance. */
    memset(node, 0, sizeof(*node));
    INIT_LIST_HEAD(&node->private_list);
    node->array = (struct xarray *)xas;
    return node;
}

static struct xa_node *lsf_msi_xas_alloc(struct xa_state *xas, unsigned int shift)
{
	struct xa_node *parent = xas->xa_node;
	struct xa_node *node = xas->xa_alloc;

	if (xas_invalid(xas))
		return NULL;

	if (parent || shift || xas->xa_index > 2u || xas->xa_shift || xas->xa_sibs) {
		lsf_factory_stream_constructor_retain_unknown();
		xas_set_err(xas, -EOPNOTSUPP); return NULL;
	}

	if (node) {
		if (!lsf_msi_store_node_for(node, xas->xa) ||
		    node->array != (struct xarray *)xas) {
			lsf_factory_stream_constructor_retain_unknown();
			xas_set_err(xas, -EOPNOTSUPP); return NULL;
		}
		xas->xa_alloc = NULL;
	} else {
		gfp_t gfp = GFP_NOWAIT | __GFP_NOWARN;

		if (xas->xa->xa_flags & XA_FLAGS_ACCOUNT)
			gfp |= __GFP_ACCOUNT;

		node = lsf_msi_xa_preallocate(xas, gfp);
		if (!node) {
			xas_set_err(xas, -ENOMEM);
			return NULL;
		}
	}

	if (parent) {
		node->offset = xas->xa_offset;
		parent->count++;
		XA_NODE_BUG_ON(node, parent->count > XA_CHUNK_SIZE);
		xas_update(xas, parent);
	}
	XA_NODE_BUG_ON(node, shift > BITS_PER_LONG);
	XA_NODE_BUG_ON(node, !list_empty(&node->private_list));
	node->shift = shift;
	node->count = 0;
	node->nr_values = 0;
	RCU_INIT_POINTER(node->parent, xas->xa_node);
	node->array = xas->xa;

	return node;
}

static bool lsf_msi_xas_nomem(struct xa_state *xas, gfp_t gfp)
{
	if (xas->xa_node != XA_ERROR(-ENOMEM)) {
		xas_destroy(xas);
		return false;
	}
	if (xas->xa->xa_flags & XA_FLAGS_ACCOUNT)
		gfp |= __GFP_ACCOUNT;
	xas->xa_alloc = lsf_msi_xa_preallocate(xas, gfp);
	if (!xas->xa_alloc)
		return false;
	xas->xa_alloc->parent = NULL;
	XA_NODE_BUG_ON(xas->xa_alloc, !list_empty(&xas->xa_alloc->private_list));
	xas->xa_node = XAS_RESTART;
	return true;
}

static bool lsf_msi_internal_xas_nomem(struct xa_state *xas, gfp_t gfp)
	__must_hold(xas->xa->xa_lock)
{
	unsigned int lock_type = xa_lock_type(xas->xa);

	if (xas->xa_node != XA_ERROR(-ENOMEM)) {
		xas_destroy(xas);
		return false;
	}
	if (xas->xa->xa_flags & XA_FLAGS_ACCOUNT)
		gfp |= __GFP_ACCOUNT;
	if (gfpflags_allow_blocking(gfp)) {
		xas_unlock_type(xas, lock_type);
		xas->xa_alloc = lsf_msi_xa_preallocate(xas, gfp);
		xas_lock_type(xas, lock_type);
	} else {
		xas->xa_alloc = lsf_msi_xa_preallocate(xas, gfp);
	}
	if (!xas->xa_alloc)
		return false;
	xas->xa_alloc->parent = NULL;
	XA_NODE_BUG_ON(xas->xa_alloc, !list_empty(&xas->xa_alloc->private_list));
	xas->xa_node = XAS_RESTART;
	return true;
}

static void lsf_msi_xas_destroy(struct xa_state *xas)
{
	struct xa_node *next, *node = xas->xa_alloc;

	while (node) {
		if (!lsf_msi_store_node_for(node, xas->xa) ||
		    node->array != (struct xarray *)xas || rcu_access_pointer(node->parent)) {
			lsf_factory_stream_constructor_retain_unknown(); return;
		}
		XA_NODE_BUG_ON(node, !list_empty(&node->private_list));
		next = rcu_dereference_raw(node->parent);
		/* The last same-operation check has completed. Do not retain a
		 * dead xa_state stack address in the original bank after cleanup. */
		node->array = NULL;
		radix_tree_node_rcu_free(&node->rcu_head);
		xas->xa_alloc = node = next;
	}
}
