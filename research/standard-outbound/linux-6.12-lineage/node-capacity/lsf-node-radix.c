// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * Copyright (C) 2001 Momchil Velikov
 * Portions Copyright (C) 2001 Christoph Hellwig
 * Copyright (C) 2005 SGI, Christoph Lameter
 * Copyright (C) 2006 Nick Piggin
 * Copyright (C) 2012 Konstantin Khlebnikov
 * Copyright (C) 2016 Intel, Matthew Wilcox
 * Copyright (C) 2016 Intel, Ross Zwisler
 */
/* Included at END of actual lib/radix-tree.c, after the real native ctor.
 * Native extend/create bodies below have only explicit-owner/callee changes.
 * Generic allocators, preloads, IDRs and ordinary radix bodies stay exact. */
#include <net/lsf_node_capacity_private.h>

int lsf_node_radix_layout(struct lsf_node_capacity_extent *out)
{
    if (!out || sizeof(struct radix_tree_node) > PAGE_SIZE ||
        __alignof__(struct radix_tree_node) > PAGE_SIZE)
        return -EOPNOTSUPP;
    out[LSF_NODE_RADIX_PRIVATE] = (struct lsf_node_capacity_extent){
        sizeof(struct radix_tree_node), __alignof__(struct radix_tree_node)};
    out[LSF_NODE_RADIX_SHARED] = out[LSF_NODE_RADIX_PRIVATE];
    return 0;
}

static struct radix_tree_node *lsf_node_radix_node_alloc(
    struct lsf_node_capacity *owner, gfp_t gfp,
    struct radix_tree_node *parent, struct radix_tree_root *root,
    unsigned int shift, unsigned int offset, unsigned int count,
    unsigned int nr_values)
{
    struct radix_tree_node *ret;
    int role = lsf_node_radix_root_role(owner, root);

    (void)gfp; /* No slab/preload fallback for this source-bound constructor. */
    if (role != LSF_NODE_RADIX_PRIVATE && role != LSF_NODE_RADIX_SHARED)
        return NULL;
    ret = lsf_node_radix_take(owner, root, sizeof(*ret), __alignof__(*ret));
    if (!ret)
        return NULL;
    radix_tree_node_ctor(ret);
    ret->shift = shift;
    ret->offset = offset;
    ret->count = count;
    ret->nr_values = nr_values;
    ret->parent = parent;
    ret->array = root;
    if (lsf_node_capacity_publish(ret, role) != 1) {
        lsf_node_radix_uncertain(ret);
        return NULL;
    }
    return ret;
}

static int lsf_node_radix_extend(struct lsf_node_capacity *owner,
				struct radix_tree_root *root, gfp_t gfp,
				unsigned long index, unsigned int shift)
{
	void *entry;
	unsigned int maxshift;
	int tag;

	/* Figure out what the shift should be.  */
	maxshift = shift;
	while (index > shift_maxindex(maxshift))
		maxshift += RADIX_TREE_MAP_SHIFT;

	entry = rcu_dereference_raw(root->xa_head);
	if (!entry && (!is_idr(root) || root_tag_get(root, IDR_FREE)))
		goto out;

	do {
		struct radix_tree_node *node = lsf_node_radix_node_alloc(owner, gfp, NULL,
							root, shift, 0, 1, 0);
		if (!node)
			return -ENOMEM;

		if (is_idr(root)) {
			all_tag_set(node, IDR_FREE);
			if (!root_tag_get(root, IDR_FREE)) {
				tag_clear(node, IDR_FREE, 0);
				root_tag_set(root, IDR_FREE);
			}
		} else {
			/* Propagate the aggregated tag info to the new child */
			for (tag = 0; tag < RADIX_TREE_MAX_TAGS; tag++) {
				if (root_tag_get(root, tag))
					tag_set(node, tag, 0);
			}
		}

		BUG_ON(shift > BITS_PER_LONG);
		if (radix_tree_is_internal_node(entry)) {
			entry_to_node(entry)->parent = node;
		} else if (xa_is_value(entry)) {
			/* Moving a value entry root->xa_head to a node */
			node->nr_values = 1;
		}
		/*
		 * entry was already in the radix tree, so we do not need
		 * rcu_assign_pointer here
		 */
		node->slots[0] = (void __rcu *)entry;
		entry = node_to_entry(node);
		rcu_assign_pointer(root->xa_head, entry);
		shift += RADIX_TREE_MAP_SHIFT;
	} while (shift <= maxshift);
out:
	return maxshift + RADIX_TREE_MAP_SHIFT;
}

static int lsf_node_radix_create(struct lsf_node_capacity *owner,
			       struct radix_tree_root *root,
		unsigned long index, struct radix_tree_node **nodep,
		void __rcu ***slotp)
{
	struct radix_tree_node *node = NULL, *child;
	void __rcu **slot = (void __rcu **)&root->xa_head;
	unsigned long maxindex;
	unsigned int shift, offset = 0;
	unsigned long max = index;
	gfp_t gfp = root_gfp_mask(root);

	shift = radix_tree_load_root(root, &child, &maxindex);

	/* Make sure the tree is high enough.  */
	if (max > maxindex) {
		int error = lsf_node_radix_extend(owner, root, gfp, max, shift);
		if (error < 0)
			return error;
		shift = error;
		child = rcu_dereference_raw(root->xa_head);
	}

	while (shift > 0) {
		shift -= RADIX_TREE_MAP_SHIFT;
		if (child == NULL) {
			/* Have to add a child node.  */
			child = lsf_node_radix_node_alloc(owner, gfp, node, root, shift,
							offset, 0, 0);
			if (!child)
				return -ENOMEM;
			rcu_assign_pointer(*slot, node_to_entry(child));
			if (node)
				node->count++;
		} else if (!radix_tree_is_internal_node(child))
			break;

		/* Go a level down */
		node = entry_to_node(child);
		offset = radix_tree_descend(node, &child, index);
		slot = &node->slots[offset];
	}

	if (nodep)
		*nodep = node;
	if (slotp)
		*slotp = slot;
	return 0;
}

int lsf_node_radix_prepare_slot(struct lsf_node_capacity *owner,
    struct radix_tree_root *root, unsigned long index)
{
    struct radix_tree_node *node;
    void __rcu **slot;
    int role = lsf_node_radix_root_role(owner, root);
    int error;

    if ((role != LSF_NODE_RADIX_PRIVATE && role != LSF_NODE_RADIX_SHARED) ||
        is_idr(root))
        return -EOPNOTSUPP;
    error = lsf_node_radix_create(owner, root, index, &node, &slot);
    if (error)
        return error;
    return *slot ? -EEXIST : 0;
}

/* Public lookup_slot intentionally returns NULL for an empty leaf. This
 * bounded walk instead proves the entire empty path exists without calling
 * the constructor again. Caller holds the same native domain root mutex. */
int lsf_node_radix_ready_slot(struct radix_tree_root *root, unsigned long index)
{
    struct radix_tree_node *node, *parent = NULL;
    void *entry = rcu_dereference_raw(root->xa_head);
    unsigned int shift = BITS_PER_LONG, offset, tag;

    if (is_idr(root) || root_tags_get(root))
        return -EIO;
    if (!radix_tree_is_internal_node(entry))
        return index ? 0 : (entry ? -EEXIST : 1);
    while (radix_tree_is_internal_node(entry)) {
        if (entry == RADIX_TREE_RETRY)
            return -EIO;
        node = entry_to_node(entry);
        if (node->shift >= BITS_PER_LONG || node->shift % RADIX_TREE_MAP_SHIFT ||
            (parent && (shift < RADIX_TREE_MAP_SHIFT ||
                node->shift != shift - RADIX_TREE_MAP_SHIFT)) ||
            (!parent && index > node_maxindex(node)))
            return -EIO;
        offset = (index >> node->shift) & RADIX_TREE_MAP_MASK;
        for (tag = 0; tag < RADIX_TREE_MAX_TAGS; ++tag)
            if (tag_get(node, tag, offset))
                return -EIO;
        entry = rcu_dereference_raw(node->slots[offset]);
        shift = node->shift;
        parent = node;
        if (!shift)
            return entry ? -EEXIST : 1;
        if (!entry)
            return 0;
        if (!radix_tree_is_internal_node(entry))
            return -EIO;
    }
    return -EIO;
}

static int lsf_node_radix_prune_node(struct lsf_node_capacity *owner,
    struct radix_tree_root *root, struct radix_tree_node *node,
    struct radix_tree_node *parent, unsigned int offset, unsigned int shift)
{
    void *entry;
    struct radix_tree_node *child;
    unsigned int i, count = 0, values = 0, tag;
    int empty;

    /* Authenticate original view and root before reading ANY node fields.
     * This private-root pruner never frees borrowed/global native nodes. */
    if (lsf_node_radix_node_matches(node, owner, root, LSF_NODE_RADIX_PRIVATE) != 1)
        return -EIO;
    if (node->parent != parent || (parent && node->offset != offset) ||
        node->shift != shift || !list_empty(&node->private_list))
        goto poison;
    for (i = 0; i < RADIX_TREE_MAP_SIZE; ++i) {
        entry = rcu_dereference_raw(node->slots[i]);
        if (entry == RADIX_TREE_RETRY)
            goto poison;
        if (radix_tree_is_internal_node(entry)) {
            if (shift < RADIX_TREE_MAP_SHIFT)
                goto poison;
            child = entry_to_node(entry);
            empty = lsf_node_radix_prune_node(owner, root, child, node, i,
                shift - RADIX_TREE_MAP_SHIFT);
            if (empty < 0)
                return empty;
            if (empty) {
                if (!node->count)
                    goto poison;
                rcu_assign_pointer(node->slots[i], NULL);
                node->count--;
                radix_tree_node_free(child);
                entry = NULL;
            }
        } else if (entry && shift) {
            goto poison;
        }
        if (entry) {
            count++;
            values += xa_is_value(entry);
        }
    }
    if (node->count != count || node->nr_values != values)
        goto poison;
    if (count)
        return 0;
    for (tag = 0; tag < RADIX_TREE_MAX_TAGS; ++tag)
        if (!bitmap_empty(node->tags[tag], RADIX_TREE_MAP_SIZE))
            goto poison;
    return 1;
poison:
    lsf_node_radix_uncertain(node);
    return -EIO;
}

int lsf_node_radix_prune_private(struct radix_tree_root *root)
{
    struct lsf_node_capacity *owner;
    struct radix_tree_node *node;
    void *entry;
    unsigned int role;
    int result = lsf_node_radix_root_owned(root, &owner);

    if (result <= 0)
        return result;
    /* Shared vector root remains attached to its original Node payer. */
    if (result == LSF_NODE_RADIX_SHARED)
        return 0;
    if (result != LSF_NODE_RADIX_PRIVATE || is_idr(root) || root_tags_get(root))
        return -EIO;
    entry = rcu_dereference_raw(root->xa_head);
    if (!radix_tree_is_internal_node(entry))
        return 0;
    if (entry == RADIX_TREE_RETRY)
        return -EIO;
    node = entry_to_node(entry);
    /* No payload access before exact original record authentication. */
    result = lsf_node_radix_owned(node, &owner, &role);
    if (result != 1 || role != LSF_NODE_RADIX_PRIVATE)
        return -EIO;
    if (node->shift >= BITS_PER_LONG || node->shift % RADIX_TREE_MAP_SHIFT) {
        lsf_node_radix_uncertain(node);
        return -EIO;
    }
    result = lsf_node_radix_prune_node(owner, root, node, NULL, 0, node->shift);
    if (result == 1) {
        rcu_assign_pointer(root->xa_head, NULL);
        radix_tree_node_free(node);
        return 0;
    }
    return result;
}
