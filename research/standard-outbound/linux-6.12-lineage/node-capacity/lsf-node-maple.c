/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in actual lib/maple_tree.c; the exact original shared sparse tree
 * uses native preallocation and native store/RCU algorithms. Allocation context
 * is explicit and call-local. Deferred callbacks use only original records.
 */
#include <net/lsf_node_capacity_private.h>

int lsf_node_maple_layout(struct lsf_node_capacity_extent *out)
{
    if (!out || sizeof(struct maple_node) != sizeof(struct maple_alloc) ||
        sizeof(struct maple_node) > PAGE_SIZE ||
        PAGE_SIZE % sizeof(struct maple_node))
        return -EOPNOTSUPP;
    out[LSF_NODE_MAPLE_PAGE] = (struct lsf_node_capacity_extent){PAGE_SIZE, PAGE_SIZE};
    /* Native maple_node_cache uses node size as cache alignment, not the
     * smaller C type alignment. The actual physical page covers both.
     */
    out[LSF_NODE_MAPLE_NODE] = (struct lsf_node_capacity_extent){
        sizeof(struct maple_node), sizeof(struct maple_node)};
    return 0;
}

static int lsf_node_mt_alloc_bulk(struct lsf_node_capacity *owner, gfp_t gfp,
    size_t count, void **nodes)
{
    size_t index;

    if (gfp != GFP_KERNEL)
        return 0;
    for (index = 0; index < count; ++index) {
        nodes[index] = lsf_node_capacity_maple_take(owner);
        if (!nodes[index])
            break;
    }
    return index;
}

static void lsf_node_mas_alloc_nodes(struct lsf_node_capacity *owner,
    struct ma_state *mas, gfp_t gfp)
{
	struct maple_alloc *node;
	unsigned long allocated = mas_allocated(mas);
	unsigned int requested = mas_alloc_req(mas);
	unsigned int count;
	void **slots = NULL;
	unsigned int max_req = 0;

	if (!requested)
		return;

	mas_set_alloc_req(mas, 0);
	if (mas->mas_flags & MA_STATE_PREALLOC) {
		if (allocated)
			return;
		BUG_ON(!allocated);
		WARN_ON(!allocated);
	}

	if (!allocated || mas->alloc->node_count == MAPLE_ALLOC_SLOTS) {
		node = (struct maple_alloc *)lsf_node_capacity_maple_take(owner);
		if (!node)
			goto nomem_one;

		if (allocated) {
			node->slot[0] = mas->alloc;
			node->node_count = 1;
		} else {
			node->node_count = 0;
		}

		mas->alloc = node;
		node->total = ++allocated;
		requested--;
	}

	node = mas->alloc;
	node->request_count = 0;
	while (requested) {
		max_req = MAPLE_ALLOC_SLOTS - node->node_count;
		slots = (void **)&node->slot[node->node_count];
		max_req = min(requested, max_req);
		count = lsf_node_mt_alloc_bulk(owner, gfp, max_req, slots);
		if (!count)
			goto nomem_bulk;

		if (node->node_count == 0) {
			node->slot[0]->node_count = 0;
			node->slot[0]->request_count = 0;
		}

		node->node_count += count;
		allocated += count;
		node = node->slot[0];
		requested -= count;
	}
	mas->alloc->total = allocated;
	return;

nomem_bulk:
	/* Clean up potential freed allocations on bulk failure */
	memset(slots, 0, max_req * sizeof(unsigned long));
nomem_one:
	mas_set_alloc_req(mas, requested);
	if (mas->alloc && !(((unsigned long)mas->alloc & 0x1)))
		mas->alloc->total = allocated;
	mas_set_err(mas, -ENOMEM);
}

int lsf_node_mas_allocate(struct ma_state *mas, gfp_t gfp)
{
    struct lsf_node_capacity *owner;
    int selected = lsf_node_capacity_mas_owner(mas, &owner);

    if (selected == 1) {
        if (gfp == GFP_KERNEL)
            lsf_node_mas_alloc_nodes(owner, mas, gfp);
        else
            mas_set_err(mas, -ENOMEM);
    } else if (selected < 0) {
        mas_set_err(mas, -ENOMEM);
    }
    return selected;
}

void lsf_node_mt_free_one(struct maple_node *node)
{
    if (!lsf_node_capacity_native_free(node, LSF_NODE_MAPLE_NODE))
        kmem_cache_free(maple_node_cache, node);
}

int lsf_node_maple_rcu_queue(struct maple_node *node)
{
    /* This is called at each real call_rcu, after native unlink/dead marking.
     * Outside pointers preserve the native callback. Selected callbacks carry
     * only their original record; no ma_state stack pointer survives here.
     */
    return lsf_node_capacity_queue(node, LSF_NODE_MAPLE_NODE);
}

void lsf_node_mt_free_bulk(size_t count, void __rcu **nodes)
{
    void **plain = (void **)nodes;
    size_t index, ordinary = 0;

    /* Mixed native arrays keep every ordinary pointer in its original order.
     * No allocation, dropping a remainder, or treating one selected element
     * as authority to leak/free unrelated ordinary cache objects.
     */
    for (index = 0; index < count; ++index)
        if (!lsf_node_capacity_native_free(plain[index], LSF_NODE_MAPLE_NODE))
            plain[ordinary++] = plain[index];
    if (ordinary)
        kmem_cache_free_bulk(maple_node_cache, ordinary, plain);
}

int lsf_node_mas_store(struct lsf_node_capacity *owner, struct ma_state *mas, void *entry)
{
    int error, unbound;

    error = lsf_node_capacity_mas_bind(owner, mas);
    if (error)
        return error;
    /* The native calculation includes the real tree height and store type;
     * no guessed per-vector node multiplier or occupation snapshot is used.
     * Native failure destroys the private preallocation before publication.
     */
    error = mas_preallocate(mas, entry, GFP_KERNEL);
    if (!error) {
        error = lsf_node_capacity_checkpoint(owner);
        if (error)
            mas_destroy(mas);
        else
            mas_store_prealloc(mas, entry);
    }
    unbound = lsf_node_capacity_mas_unbind(owner, mas);
    return error ? error : unbound;
}
