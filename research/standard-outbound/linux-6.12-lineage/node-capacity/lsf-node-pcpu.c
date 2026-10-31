/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in the real mm/percpu.c TU, after its ordinary native functions.
 * Private chunks retain the native pcpu_chunk, bitmaps, unit addressing,
 * vmalloc mappings and reverse page/chunk identity. No bank pointer is cast
 * into a substitute statistics array or fabricated __percpu address.
 */
#include <net/lsf_node_capacity_private.h>
#include <linux/irq.h>
#include <linux/irqdesc.h>
#include <linux/overflow.h>

int lsf_node_pcpu_observe(struct lsf_node_capacity *owner,
    struct lsf_node_capacity_facts *facts)
{
    int error = -EOPNOTSUPP;

    if (!facts)
        return error;
    cpus_read_lock();
    mutex_lock(&pcpu_alloc_mutex);
    if (lsf_node_capacity_checkpoint(owner))
        goto out;
    /* The captured units must be the SAME real native geometry used by this
     * successful preparation, not CONFIG_NR_CPUS or static layout evidence. */
    if (!owner->pcpu_prepared || pcpu_unit_pages <= 0 || pcpu_nr_units <= 0 ||
        pcpu_atom_size <= 0 || num_possible_cpus() != 1 || !cpu_possible(0) ||
        num_online_cpus() != 1 || !cpu_online(0) || nr_cpu_ids != 1 ||
        pcpu_nr_groups != 1 || !pcpu_group_offsets || !pcpu_group_sizes ||
        owner->unit_pages != (unsigned long)pcpu_unit_pages ||
        owner->units != (unsigned long)pcpu_nr_units ||
        owner->atom_bytes != (unsigned long)pcpu_atom_size ||
        owner->group_offset != pcpu_group_offsets[0] ||
        owner->group_bytes != pcpu_group_sizes[0] ||
        owner->unit_offset != pcpu_unit_offsets[0])
        goto out;
    facts->word[LSF_NODE_FACT_POSSIBLE_MASK] = BIT_ULL(0);
    facts->word[LSF_NODE_FACT_ONLINE_MASK] = BIT_ULL(0);
    facts->word[LSF_NODE_FACT_NR_CPU_IDS] = nr_cpu_ids;
    facts->word[LSF_NODE_FACT_UNIT_PAGES] = owner->unit_pages;
    facts->word[LSF_NODE_FACT_UNITS] = owner->units;
    facts->word[LSF_NODE_FACT_ATOM_BYTES] = owner->atom_bytes;
    facts->word[LSF_NODE_FACT_GROUP_OFFSET] = owner->group_offset;
    facts->word[LSF_NODE_FACT_GROUP_BYTES] = owner->group_bytes;
    facts->word[LSF_NODE_FACT_UNIT_OFFSET] = owner->unit_offset;
    error = 0;
out:
    mutex_unlock(&pcpu_alloc_mutex);
    cpus_read_unlock();
    return error;
}

int lsf_node_pcpu_layout(struct lsf_node_capacity *owner)
{
    struct lsf_node_capacity_extent *out;
    unsigned long region, blocks, bytes, pages;

    lockdep_assert_held(&pcpu_alloc_mutex);
    if (lsf_node_capacity_checkpoint(owner))
        return -EOPNOTSUPP;
    out = owner->extent;
    /* These optional allocation/profiling providers need their own original
     * metadata owners. The selected immutable native profile has them off;
     * do not silently skip their hooks in a different running configuration.
     */
    if (IS_ENABLED(CONFIG_MEMCG) || IS_ENABLED(CONFIG_MEM_ALLOC_PROFILING) ||
        IS_ENABLED(CONFIG_DEBUG_KMEMLEAK) || num_possible_cpus() != 1 ||
        !cpu_possible(0) || nr_cpu_ids != 1 ||
        num_online_cpus() != 1 || !cpu_online(0) ||
        pcpu_unit_pages <= 0 || pcpu_nr_units <= 0 || pcpu_nr_groups != 1 ||
        pcpu_atom_size <= 0 || !pcpu_group_offsets || !pcpu_group_sizes ||
        pcpu_unit_map[0] >= pcpu_nr_units || sizeof(struct irqstat) > 64 ||
        PCPU_MIN_ALLOC_SIZE > 64 || 64 % PCPU_MIN_ALLOC_SIZE ||
        LSF_NODE_CAPACITY_VECTORS * 64ul > PAGE_SIZE ||
        check_mul_overflow((unsigned long)pcpu_unit_pages, PAGE_SIZE, &bytes))
        return -EOPNOTSUPP;
    region = bytes / PCPU_MIN_ALLOC_SIZE;
    blocks = bytes / PCPU_BITMAP_BLOCK_SIZE;
    out[LSF_NODE_PCPU_CHUNK] = (struct lsf_node_capacity_extent){
        pcpu_chunk_struct_size, __alignof__(struct pcpu_chunk)};
    if (check_mul_overflow((unsigned long)BITS_TO_LONGS(region),
            sizeof(unsigned long), &bytes))
        return -EOVERFLOW;
    out[LSF_NODE_PCPU_ALLOC_MAP] = (struct lsf_node_capacity_extent){bytes,
        __alignof__(unsigned long)};
    if (check_mul_overflow((unsigned long)BITS_TO_LONGS(region + 1),
            sizeof(unsigned long), &bytes))
        return -EOVERFLOW;
    out[LSF_NODE_PCPU_BOUND_MAP] = (struct lsf_node_capacity_extent){bytes,
        __alignof__(unsigned long)};
    if (check_mul_overflow(blocks, sizeof(struct pcpu_block_md), &bytes))
        return -EOVERFLOW;
    out[LSF_NODE_PCPU_BLOCKS] = (struct lsf_node_capacity_extent){bytes,
        __alignof__(struct pcpu_block_md)};
#ifdef NEED_PCPUOBJ_EXT
    if (need_pcpuobj_ext()) {
        if (check_mul_overflow(region, sizeof(struct pcpuobj_ext), &bytes))
            return -EOVERFLOW;
        out[LSF_NODE_PCPU_EXTENSIONS] = (struct lsf_node_capacity_extent){bytes,
            __alignof__(struct pcpuobj_ext)};
    }
#endif
    if (check_mul_overflow((unsigned long)pcpu_nr_units,
            (unsigned long)pcpu_unit_pages, &pages) ||
        check_mul_overflow(pages, sizeof(struct page *), &bytes))
        return -EOVERFLOW;
    out[LSF_NODE_PCPU_PAGES] = (struct lsf_node_capacity_extent){bytes,
        __alignof__(struct page *)};
    out[LSF_NODE_PCPU_DATA] = (struct lsf_node_capacity_extent){PAGE_SIZE, PAGE_SIZE};
    out[LSF_NODE_PCPU_STAT] = (struct lsf_node_capacity_extent){sizeof(struct irqstat),
        __alignof__(struct irqstat)};
    owner->unit_pages = pcpu_unit_pages;
    owner->units = pcpu_nr_units;
    owner->atom_bytes = pcpu_atom_size;
    owner->group_offset = pcpu_group_offsets[0];
    owner->group_bytes = pcpu_group_sizes[0];
    owner->unit_offset = pcpu_unit_offsets[0];
    return 0;
}

static void *lsf_node_pcpu_take(struct lsf_node_capacity *owner,
    enum lsf_node_capacity_role role)
{
    return lsf_node_capacity_take(owner, role, owner->extent[role].bytes,
        owner->extent[role].alignment);
}

static struct pcpu_chunk *lsf_node_pcpu_alloc_chunk(struct lsf_node_capacity *owner)
{
    struct pcpu_chunk *chunk;

    chunk = lsf_node_pcpu_take(owner, LSF_NODE_PCPU_CHUNK);
    if (!chunk)
        return NULL;
    INIT_LIST_HEAD(&chunk->list);
    /* Existing native relocation and empty-page accounting explicitly leave
     * isolated chunks alone. Never insert this list into any global slot,
     * sidelined, reclaim or depopulate list, including on a failed prepare.
     */
    chunk->isolated = true;
    chunk->nr_pages = pcpu_unit_pages;
    chunk->alloc_map = lsf_node_pcpu_take(owner, LSF_NODE_PCPU_ALLOC_MAP);
    chunk->bound_map = lsf_node_pcpu_take(owner, LSF_NODE_PCPU_BOUND_MAP);
    chunk->md_blocks = lsf_node_pcpu_take(owner, LSF_NODE_PCPU_BLOCKS);
    if (!chunk->alloc_map || !chunk->bound_map || !chunk->md_blocks)
        return NULL;
#ifdef NEED_PCPUOBJ_EXT
    if (need_pcpuobj_ext()) {
        chunk->obj_exts = lsf_node_pcpu_take(owner, LSF_NODE_PCPU_EXTENSIONS);
        if (!chunk->obj_exts)
            return NULL;
    }
#endif
    pcpu_init_md_blocks(chunk);
    chunk->free_bytes = chunk->nr_pages * PAGE_SIZE;
    return chunk;
}

int lsf_node_pcpu_prepare(struct lsf_node_capacity *owner)
{
    struct pcpu_chunk *chunk;
    struct vm_struct **vms;
    struct page **pages;
    void *physical;
    unsigned long flags;
    unsigned int index, cpu;
    int error, offset;

    cpus_read_lock();
    mutex_lock(&pcpu_alloc_mutex);
    error = lsf_node_capacity_begin(owner);
    if (error)
        goto out;
    /* No original allocator fallback: partial metadata, VA or mappings stay
     * with the same Node on failure, never a retry with a fresh reservation.
     */
    error = -ENOMEM;
    chunk = lsf_node_pcpu_alloc_chunk(owner);
    if (!chunk)
        goto out;
    owner->pcpu_chunk = chunk;
    pages = lsf_node_pcpu_take(owner, LSF_NODE_PCPU_PAGES);
    if (!pages)
        goto out;
    owner->pcpu_pages = pages;
    vms = lsf_node_pcpu_vm_areas(owner, pcpu_group_offsets, pcpu_group_sizes,
        pcpu_nr_groups, pcpu_atom_size);
    if (!vms)
        goto out;
    owner->pcpu_vms = vms;
    chunk->data = vms;
    chunk->base_addr = vms[0]->addr - pcpu_group_offsets[0];
    physical = lsf_node_pcpu_take(owner, LSF_NODE_PCPU_DATA);
    if (!physical)
        goto out;
    for_each_possible_cpu(cpu) {
        /* Exactly one possible CPU was authenticated above; use its REAL
         * native unit index, not CPU ID as an invented unit-array index.
         */
        pages[pcpu_page_idx(cpu, 0)] = virt_to_page(physical);
        error = lsf_node_pcpu_map(owner,
            (unsigned long)pcpu_chunk_addr(chunk, cpu, 0),
            &pages[pcpu_page_idx(cpu, 0)], 1);
        if (error)
            goto out;
        pcpu_set_page_chunk(pages[pcpu_page_idx(cpu, 0)], chunk);
    }
    pcpu_post_map_flush(chunk, 0, 1);
    spin_lock_irqsave(&pcpu_lock, flags);
    pcpu_chunk_populated(chunk, 0, 1);
    spin_unlock_irqrestore(&pcpu_lock, flags);
    for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index) {
        /* The actual private allocation request is a disjoint 64-byte cell;
         * the native irqstat remains its original type inside that cell.
         * Its entire real internal fragmentation is owned, not guessed away.
         */
        /* Reserve the same-array child view BEFORE its native allocation-map
         * mutation; neither an actual cell nor its pointer may escape unpaid.
         */
        error = lsf_node_capacity_stat_view(owner, index,
            physical + index * 64,
            __addr_to_pcpu_ptr(chunk->base_addr + index * 64));
        if (error)
            goto out;
        spin_lock_irqsave(&pcpu_lock, flags);
        offset = pcpu_alloc_area(chunk, 64 / PCPU_MIN_ALLOC_SIZE,
            64 / PCPU_MIN_ALLOC_SIZE, index * 64 / PCPU_MIN_ALLOC_SIZE);
        if (offset >= 0)
            pcpu_stats_area_alloc(chunk, 64);
        error = lsf_node_capacity_stat_allocated(owner, index, offset);
        spin_unlock_irqrestore(&pcpu_lock, flags);
        if (error)
            goto out;
    }
    error = lsf_node_irq_action_prepare(owner);
    if (!error)
        error = lsf_node_irq_prepare(owner);
    if (!error)
        error = lsf_node_irq_aux_prepare(owner);
    if (!error)
        error = lsf_node_vector_prepare(owner);
    if (!error)
        error = lsf_node_capacity_pcpu_commit(owner);
out:
    mutex_unlock(&pcpu_alloc_mutex);
    cpus_read_unlock();
    return error;
}

/* Hooked BEFORE the ordinary free_percpu body. Normal pointers return0 and
 * enter that unchanged body. Selected cells use its native free-area routine,
 * but cannot reach global reintegration/reclaim/balance after physical free.
 */
int lsf_node_pcpu_free(void __percpu *pointer)
{
    struct lsf_node_capacity *owner;
    struct pcpu_chunk *chunk;
    unsigned long flags;
    unsigned int index;
    int selected, freed;

    selected = lsf_node_capacity_stat_lookup(pointer, &owner, &index);
    if (selected != 1)
        return selected;
    chunk = owner->pcpu_chunk;
    spin_lock_irqsave(&pcpu_lock, flags);
    selected = lsf_node_capacity_stat_return(owner, index);
    if (selected == 1) {
        freed = pcpu_free_area(chunk, index * 64);
        selected = lsf_node_capacity_stat_finish_return(owner, index, freed);
    }
    spin_unlock_irqrestore(&pcpu_lock, flags);
    /* The native chunk, mapped page, scratch and VM capacity stay retained.
     * No pcpu_isolate_chunk, scheduling, metadata free or bank refund occurs.
     */
    return selected;
}

int lsf_node_pcpu_close_private(struct lsf_node_capacity *owner)
{
    struct pcpu_chunk *chunk;
    unsigned long flags;
    unsigned int index;
    int selected, allocated, freed, error = 0;

    /* The Node close/release caller holds factory_lock and has already sealed
     * admission. A partial prepare cannot race this path. Real callbacks may
     * still return claimed cells; only never-claimed private views are taken.
     */
    mutex_lock(&pcpu_alloc_mutex);
    for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index) {
        spin_lock_irqsave(&pcpu_lock, flags);
        selected = lsf_node_capacity_stat_private_return(owner, index, &allocated);
        if (selected == 1) {
            chunk = owner->pcpu_chunk;
            freed = allocated ? pcpu_free_area(chunk, index * 64) : 0;
            selected = lsf_node_capacity_stat_finish_return(owner, index, freed);
        }
        spin_unlock_irqrestore(&pcpu_lock, flags);
        if (selected < 0) {
            error = selected;
            break;
        }
    }
    if (!error)
        for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index) {
            selected = lsf_node_capacity_desc_close_private(owner, index);
            if (selected < 0) {
                error = selected;
                break;
            }
        }
    if (!error)
        for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index) {
            selected = lsf_node_irq_aux_close_private(owner, index);
            if (selected < 0) {
                error = selected;
                break;
            }
        }
    if (!error)
        for (index = 0; index < LSF_NODE_CAPACITY_VECTORS; ++index) {
            selected = lsf_node_capacity_action_close_private(owner, index);
            if (selected < 0) {
                error = selected;
                break;
            }
        }
    mutex_unlock(&pcpu_alloc_mutex);
    /* All backing, VM aliases, metadata and original admission remain owned.
     * This is neither NodeRetired nor permission to free/reuse a native page.
     */
    return error;
}
