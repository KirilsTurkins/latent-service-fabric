/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in actual kernel/irq/matrix.c. Caller holds actual vector_lock;
 * the vector TU supplies only its authenticated global vector_matrix. Existing
 * allocator/system/managed maps and backing remain original platform state. */
#include <net/lsf_node_capacity_private.h>
int lsf_node_matrix_held(struct irq_matrix *matrix, unsigned int cpu,
    unsigned int vector)
{
    struct cpumap *map;
    if (!matrix || cpu != 0 || !cpu_possible(cpu) || !cpu_online(cpu) ||
        num_possible_cpus() != 1 || num_online_cpus() != 1 || nr_cpu_ids != 1 ||
        vector < matrix->alloc_start || vector >= matrix->alloc_end ||
        matrix->online_maps != 1)
        return 0;
    map = per_cpu_ptr(matrix->maps, cpu);
    return map->initialized && map->online && test_bit(vector, map->alloc_map) &&
        !test_bit(vector, map->managed_map) && !test_bit(vector, matrix->system_map);
}


int lsf_node_matrix_room(struct irq_matrix *matrix, unsigned int count)
{
    struct cpumap *map;
    if (!matrix || count != LSF_NODE_CAPACITY_VECTORS || !cpu_possible(0) || !cpu_online(0) ||
        num_possible_cpus() != 1 || num_online_cpus() != 1 || nr_cpu_ids != 1 ||
        matrix->online_maps != 1 || matrix->global_reserved > matrix->global_available ||
        count > matrix->global_available - matrix->global_reserved)
        return 0;
    map = per_cpu_ptr(matrix->maps, 0);
    return map->initialized && map->online && count <= map->available;
    /* This is only an admission precondition under vector_lock. Actual native
     * alloc_map bits are claimed before any capacity is reported prepared. */
}
