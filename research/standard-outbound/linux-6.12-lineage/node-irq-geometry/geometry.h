/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef LSF_NODE_IRQ_GEOMETRY_H
#define LSF_NODE_IRQ_GEOMETRY_H
#include <linux/types.h>

/* Native request operands only. Neither record is an admission or owner. */
#define LSF_NODE_GEOMETRY_MAGIC 0x314f45474e46534cULL
struct lsf_node_irq_geometry {
	u64 magic, version, role, count;
	u64 values[24];
};
struct lsf_node_percpu_requests {
	u64 possible_cpus, unit_pages, units, groups, atom_bytes;
	u64 chunk, alloc_map, bound_map, metadata_blocks, object_extensions;
	u64 temporary_page_pointers, vm_pointer_array, data_pages, virtual_bytes;
};
int lsf_node_percpu_requests(struct lsf_node_percpu_requests *out);
#endif
