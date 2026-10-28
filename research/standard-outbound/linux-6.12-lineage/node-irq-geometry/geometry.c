/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in authenticated allocating TUs; ordinary functions stay exact. */
#include "lsf-node-irq-geometry.h"
#include <linux/errno.h>
#include <linux/overflow.h>
#include <linux/string.h>
#include <linux/cpumask.h>
#include <linux/compiler_attributes.h>
#if !defined(CONFIG_X86_64) || !defined(CONFIG_SMP) || !defined(CONFIG_SPARSE_IRQ)
#error "Node IRQ geometry requires the accepted x86-64 sparse-IRQ profile"
#endif
#define LSF_PAIR(type) sizeof(type), __alignof__(type)
#define LSF_FACTS(role, count, ...) \
	static const struct lsf_node_irq_geometry lsf_node_irq_geometry \
	__used __section(".lsf_node_geometry") = { \
		LSF_NODE_GEOMETRY_MAGIC, 1, role, count, { __VA_ARGS__ } }

#if LSF_NODE_GEOMETRY_ROLE == 1
#include <asm/irq_vectors.h>
LSF_FACTS(1, 9, LSF_PAIR(struct irq_matrix), LSF_PAIR(struct cpumap),
	NR_VECTORS, BITS_TO_LONGS(NR_VECTORS), sizeof(unsigned long),
	struct_size((struct irq_matrix *)0, scratch_map, BITS_TO_LONGS(NR_VECTORS) * 2),
	struct_size((struct cpumap *)0, alloc_map, BITS_TO_LONGS(NR_VECTORS) * 2));
#elif LSF_NODE_GEOMETRY_ROLE == 2
/* Native cache alignment is sizeof(maple_node), not its C type alignment. */
LSF_FACTS(2, 6, LSF_PAIR(struct maple_node), LSF_PAIR(struct maple_alloc),
	sizeof(struct maple_node), MAPLE_ALLOC_SLOTS);
#elif LSF_NODE_GEOMETRY_ROLE == 3
LSF_FACTS(3, 14, LSF_PAIR(struct pcpu_chunk), LSF_PAIR(struct pcpu_block_md),
	LSF_PAIR(struct pcpuobj_ext), LSF_PAIR(struct vm_struct), LSF_PAIR(struct vmap_area),
	PCPU_MIN_ALLOC_SIZE, PCPU_BITMAP_BLOCK_SIZE, PAGE_SIZE, sizeof(struct page *));

/*
 * Read-only dynamic operands from the actual initialized allocator. Caller
 * supplies owned output. Does not allocate, publish, reserve or return credit.
 * Data-page count follows possible CPUs; pointer-array count includes units.
 * This is ONE whole new chunk, not a bound on asynchronous balance work or a
 * lease on existing shared chunks, slab pages or VM/page-table backing.
 */
int lsf_node_percpu_requests(struct lsf_node_percpu_requests *out)
{
	size_t region, blocks, bytes, pages, total = 0;
	int group;

	if (!out)
		return -EINVAL;
	memset(out, 0, sizeof(*out));
	if (num_possible_cpus() != 1 || !cpu_possible(0) || nr_cpu_ids != 1)
		return -EOPNOTSUPP;
	if (pcpu_unit_pages <= 0 || pcpu_nr_units <= 0 || pcpu_nr_groups <= 0 ||
	    pcpu_atom_size <= 0 || !pcpu_group_sizes || !pcpu_group_offsets)
		return -EAGAIN;
	out->possible_cpus = num_possible_cpus();
	out->unit_pages = pcpu_unit_pages;
	out->units = pcpu_nr_units;
	out->groups = pcpu_nr_groups;
	out->atom_bytes = pcpu_atom_size;
	out->chunk = pcpu_chunk_struct_size;
	if (check_mul_overflow((size_t)pcpu_unit_pages, (size_t)PAGE_SIZE, &bytes))
		return -EOVERFLOW;
	region = bytes / PCPU_MIN_ALLOC_SIZE;
	blocks = bytes / PCPU_BITMAP_BLOCK_SIZE;
	/* unit_pages is positive int on the fixed x86-64 profile. */
	if (check_mul_overflow((size_t)BITS_TO_LONGS(region), sizeof(unsigned long), &bytes))
		return -EOVERFLOW;
	out->alloc_map = bytes;
	if (check_mul_overflow((size_t)BITS_TO_LONGS(region + 1), sizeof(unsigned long), &bytes))
		return -EOVERFLOW;
	out->bound_map = bytes;
	if (check_mul_overflow(blocks, sizeof(struct pcpu_block_md), &bytes))
		return -EOVERFLOW;
	out->metadata_blocks = bytes;
#ifdef NEED_PCPUOBJ_EXT
	if (need_pcpuobj_ext()) {
		if (check_mul_overflow(region, sizeof(struct pcpuobj_ext), &bytes))
			return -EOVERFLOW;
		out->object_extensions = bytes;
	}
#endif
	if (check_mul_overflow((size_t)pcpu_nr_units, (size_t)pcpu_unit_pages, &pages) ||
	    check_mul_overflow(pages, sizeof(struct page *), &bytes))
		return -EOVERFLOW;
	out->temporary_page_pointers = bytes;
	if (check_mul_overflow((size_t)num_possible_cpus(), (size_t)pcpu_unit_pages, &pages) ||
	    check_mul_overflow(pages, (size_t)PAGE_SIZE, &bytes))
		return -EOVERFLOW;
	out->data_pages = bytes;
	if (check_mul_overflow((size_t)pcpu_nr_groups, sizeof(struct vm_struct *), &bytes))
		return -EOVERFLOW;
	out->vm_pointer_array = bytes;
	for (group = 0; group < pcpu_nr_groups; group++) {
		if (check_add_overflow(total, pcpu_group_sizes[group], &total))
			return -EOVERFLOW;
	}
	out->virtual_bytes = total;
	return 0;
}
#elif LSF_NODE_GEOMETRY_ROLE == 4
LSF_FACTS(4, 10, LSF_PAIR(struct apic_chip_data), LSF_PAIR(struct vector_cleanup),
	sizeof(vector_irq), NR_VECTORS, FIRST_EXTERNAL_VECTOR, FIRST_SYSTEM_VECTOR,
	NR_CPUS, IS_ENABLED(CONFIG_CPUMASK_OFFSTACK));
#elif LSF_NODE_GEOMETRY_ROLE == 5
LSF_FACTS(5, 10, LSF_PAIR(struct irq_desc), LSF_PAIR(struct irqstat),
	LSF_PAIR(struct irqaction), sizeof(struct cpumask),
	IS_ENABLED(CONFIG_CPUMASK_OFFSTACK),
	IS_ENABLED(CONFIG_GENERIC_IRQ_EFFECTIVE_AFF_MASK),
	IS_ENABLED(CONFIG_GENERIC_PENDING_IRQ));
#elif LSF_NODE_GEOMETRY_ROLE == 6
LSF_FACTS(6, 8, LSF_PAIR(struct irq_domain), LSF_PAIR(struct irq_data),
	LSF_PAIR(struct irqchip_fwid), sizeof(((struct irq_domain *)0)->revmap[0]),
	offsetof(struct irq_domain, revmap));
#else
#error "unknown native Node IRQ geometry role"
#endif
#undef LSF_FACTS
#undef LSF_PAIR
