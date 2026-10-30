/* SPDX-License-Identifier: GPL-2.0-only */
/* Private native allocator context. No wire grant or funding certificate. */
#ifndef LSF_NODE_CAPACITY_PRIVATE_H
#define LSF_NODE_CAPACITY_PRIVATE_H
#include <linux/types.h>
#include <linux/compiler_types.h>

struct page;
struct pcpu_chunk;
struct vm_struct;
struct vmap_area;
struct maple_tree;
struct ma_state;
struct task_struct;
struct mm_struct;
struct maple_node;
struct irq_desc;
struct cpumask;
struct module;
struct device;
struct irq_domain;
struct kobject;
struct irqaction;
struct proc_dir_entry;
struct lsf_device_registration_source;
struct lsf_node_irq_call { u64 generation; };
struct lsf_node_irq_name {
    unsigned int pci_slot, name_slot;
    u64 pci_generation, name_generation;
};

#define LSF_NODE_CAPACITY_VECTORS 8u
/* Private versioned observation, never a funding/fit/retirement certificate.
 * All fields are produced by the actual allocating TUs or original registrar.
 * No pointer, actor identity or caller-selected scalar crosses the wire. */
#define LSF_NODE_FACT_WORDS 40u
enum lsf_node_fact_field {
    LSF_NODE_FACT_FORMAT, LSF_NODE_FACT_PROFILE, LSF_NODE_FACT_NODE_OFFSET,
    LSF_NODE_FACT_CAPACITY_OFFSET, LSF_NODE_FACT_CAPACITY_BYTES,
    LSF_NODE_FACT_POSSIBLE_MASK, LSF_NODE_FACT_ONLINE_MASK, LSF_NODE_FACT_NR_CPU_IDS,
    LSF_NODE_FACT_UNIT_PAGES, LSF_NODE_FACT_UNITS, LSF_NODE_FACT_ATOM_BYTES,
    LSF_NODE_FACT_GROUP_OFFSET, LSF_NODE_FACT_GROUP_BYTES, LSF_NODE_FACT_UNIT_OFFSET,
    LSF_NODE_FACT_FLOOR_BYTES, LSF_NODE_FACT_COMMITTED_BYTES,
    LSF_NODE_FACT_RESERVED_BYTES, LSF_NODE_FACT_CURSOR,
    LSF_NODE_FACT_RECORD_HIGH_WATER, LSF_NODE_FACT_LIVE_RECORDS,
    LSF_NODE_FACT_OWNER_HIGH_WATER, LSF_NODE_FACT_NEXT_GENERATION,
    LSF_NODE_FACT_VECTOR_COUNT, LSF_NODE_FACT_VECTOR_CPU_MASK,
    LSF_NODE_FACT_VECTOR_PACKED0, LSF_NODE_FACT_VECTOR_PACKED1,
    LSF_NODE_FACT_PARENT_DOMAIN_CLASS, LSF_NODE_FACT_MATRIX_CLASS,
    LSF_NODE_FACT_BANK_ORDER, LSF_NODE_FACT_ENVELOPE_BYTES,
    LSF_NODE_FACT_BANK_BYTES, LSF_NODE_FACT_TAIL_BYTES, LSF_NODE_FACT_FLAGS
};
struct lsf_node_capacity_facts { u64 word[LSF_NODE_FACT_WORDS]; };
#define LSF_NODE_IRQ_PROC_ENTRIES 9u
#define LSF_NODE_CAPACITY_KIND_BASE 0xfe00u
#define LSF_NODE_CAPACITY_NATIVE_BASE 0xfd00u
#define LSF_NODE_CAPACITY_UNBOUND (~0ull)
#define LSF_NODE_CAPACITY_PARENT_KIND 0xff00u

enum lsf_node_capacity_role {
    LSF_NODE_PCPU_CHUNK = 1,
    LSF_NODE_PCPU_ALLOC_MAP,
    LSF_NODE_PCPU_BOUND_MAP,
    LSF_NODE_PCPU_BLOCKS,
    LSF_NODE_PCPU_EXTENSIONS,
    LSF_NODE_PCPU_PAGES,
    LSF_NODE_PCPU_DATA,
    LSF_NODE_PCPU_STAT,
    LSF_NODE_VM_POINTERS,
    LSF_NODE_VA_POINTERS,
    LSF_NODE_VM_STRUCT,
    LSF_NODE_VMAP_AREA,
    LSF_NODE_P4D_PAGE,
    LSF_NODE_PUD_PAGE,
    LSF_NODE_PMD_PAGE,
    LSF_NODE_PTE_PAGE,
    LSF_NODE_MAPLE_PAGE,
    LSF_NODE_MAPLE_NODE,
    LSF_NODE_IRQ_DESC,
    LSF_NODE_IRQ_PARENT_DATA,
    LSF_NODE_IRQ_APIC,
    LSF_NODE_IRQ_ACTION,
    LSF_NODE_PROC_PDE,
    LSF_NODE_PROC_NAME,
    LSF_NODE_SMALL_PAGE,
    LSF_NODE_RADIX_PRIVATE,
    LSF_NODE_RADIX_SHARED,
    LSF_NODE_CAPACITY_ROLES
};

static inline int lsf_node_small_role(enum lsf_node_capacity_role role)
{
    return (role >= LSF_NODE_IRQ_DESC && role <= LSF_NODE_PROC_NAME) ||
        role == LSF_NODE_RADIX_PRIVATE || role == LSF_NODE_RADIX_SHARED;
}

struct lsf_node_capacity_extent {
    unsigned long bytes, alignment;
};

/* Call-local original reservation. It carries no caller-selected byte cost. */
struct lsf_node_native_ticket {
    unsigned int slot, role;
    u64 generation;
    unsigned long bytes, alignment;
};

struct irq_matrix;
struct irq_data;
struct lsf_node_vector_slot {
    struct lsf_node_native_ticket apic, desc;
    struct irq_matrix *matrix;
    unsigned int cpu, vector, phase;
};
#define LSF_NODE_VECTOR_INTENT 1u
#define LSF_NODE_VECTOR_HELD 2u
#define LSF_NODE_VECTOR_BOUND 3u
#define LSF_NODE_VECTOR_ACTIVE 4u
#define LSF_NODE_VECTOR_RETAINED 5u

struct xarray;
struct xa_node;
/* Identity snapshots are never dereferenced after native root teardown. */
struct lsf_node_radix_origin {
    unsigned long root_identity;
    u64 view_generation;
    struct lsf_node_native_ticket domain, pci;
    unsigned int role;
};

/* Embedded in the actual bank-backed Node parent BEFORE its first write.
 * Extents are filled by allocating TUs while their real geometry is stable.
 * They are never decoded from a request or inferred from an object address.
 * Stack-only Maple bindings are cleared before the allocating call returns;
 * deferred native callbacks use record provenance, never these stack aliases.
 */
struct lsf_node_capacity {
    struct lsf_node_capacity_extent extent[LSF_NODE_CAPACITY_ROLES];
    void *pcpu_chunk, *pcpu_pages, *pcpu_vms;
    struct vmap_area *vmap_splits[1];
    void __percpu *pcpu_stats[LSF_NODE_CAPACITY_VECTORS];
    void *pcpu_stat_backing[LSF_NODE_CAPACITY_VECTORS];
    struct maple_tree *sparse_tree;
    struct ma_state *active_mas;
    struct task_struct *mas_task;
    u64 mas_generation;
    void *maple_page;
    unsigned int maple_used;
    unsigned long unit_pages, units, atom_bytes, group_offset, group_bytes, unit_offset;
    unsigned int started, pcpu_prepared, pcpu_claimed, pcpu_returned, vmap_split_used;
    unsigned int pcpu_allocated;
    void *irq_descs[LSF_NODE_CAPACITY_VECTORS];
    unsigned int irq_claimed, irq_returned;
    struct lsf_node_native_ticket cleanup_origin;
    struct lsf_node_native_ticket device_root;
    unsigned int device_closed;
    const struct lsf_node_irq_call *irq_call;
    struct task_struct *irq_task;
    const void *irq_domain;
    u64 irq_generation;
    struct lsf_node_native_ticket irq_domain_birth, irq_pci_birth, irq_sysfs_desc;
    struct lsf_node_native_ticket irq_desc_pci[LSF_NODE_CAPACITY_VECTORS];
    struct lsf_node_native_ticket irq_desc_domain[LSF_NODE_CAPACITY_VECTORS];
    struct lsf_node_native_ticket irq_names[LSF_NODE_CAPACITY_VECTORS];
    unsigned long irq_kobject_offset, irq_kobject_bytes;
    void *irq_parent_data[LSF_NODE_CAPACITY_VECTORS];
    void *irq_apic[LSF_NODE_CAPACITY_VECTORS];
    unsigned int irq_parent_claimed, irq_apic_claimed;
    unsigned int irq_parent_returned, irq_apic_returned;
    struct lsf_node_vector_slot vector_slots[LSF_NODE_CAPACITY_VECTORS];
    unsigned int irq_aux_prepared;
    struct irqaction *irq_actions[LSF_NODE_CAPACITY_VECTORS];
    unsigned int irq_action_claimed, irq_action_returned;
    struct proc_dir_entry *irq_proc_entries[LSF_NODE_CAPACITY_VECTORS][LSF_NODE_IRQ_PROC_ENTRIES];
    unsigned int irq_proc_claimed[LSF_NODE_CAPACITY_VECTORS];
    char *irq_proc_names[LSF_NODE_CAPACITY_VECTORS];
    unsigned int irq_name_claimed;
    void *small_pages[LSF_NODE_CAPACITY_ROLES];
    unsigned int small_used[LSF_NODE_CAPACITY_ROLES];
    u64 small_allocating;
    struct lsf_node_radix_origin radix_origin[256];
};

/* Callers are the source-bound allocating TUs. The owner is validated against
 * the original Node record before any owner payload is read. None of these
 * operations acquires a second escrow, returns physical credit or opens IRQs.
 */
int lsf_node_capacity_checkpoint(struct lsf_node_capacity *owner);
void *lsf_node_capacity_small_take(struct lsf_node_capacity *owner,
    enum lsf_node_capacity_role role, unsigned long bytes, unsigned long alignment);
int lsf_node_capacity_begin(struct lsf_node_capacity *owner);
int lsf_node_capacity_reserve(struct lsf_node_capacity *owner,
    enum lsf_node_capacity_role role, struct lsf_node_native_ticket *ticket);
int lsf_node_capacity_commit(struct lsf_node_capacity *owner,
    const struct lsf_node_native_ticket *ticket, const void *address);
void *lsf_node_capacity_take(struct lsf_node_capacity *owner,
    enum lsf_node_capacity_role role, unsigned long bytes,
    unsigned long alignment);
int lsf_node_capacity_native_free(const void *address,
    enum lsf_node_capacity_role role);
int lsf_node_capacity_native_owned(const void *address,
    enum lsf_node_capacity_role role, struct lsf_node_capacity **owner);
int lsf_node_capacity_publish(const void *address,
    enum lsf_node_capacity_role role);
int lsf_node_capacity_queue(const void *address,
    enum lsf_node_capacity_role role);
void lsf_node_vmap_cache_free(struct vmap_area *area);
int lsf_node_pgtable_pre_free(struct mm_struct *mm, const void *address,
    enum lsf_node_capacity_role role);
int lsf_node_pgtable_backing_hold(const void *address);
int lsf_node_irq_sparse_identity(const struct maple_tree *tree);
int lsf_node_irq_sparse_entry(const struct ma_state *mas, const void *entry);
int lsf_node_capacity_mas_bind(struct lsf_node_capacity *owner, struct ma_state *mas);
int lsf_node_capacity_mas_bind_cleanup(struct ma_state *mas, const void *entry);
int lsf_node_capacity_maple_checkpoint(struct lsf_node_capacity *owner);
int lsf_node_capacity_mas_unbind(struct lsf_node_capacity *owner, struct ma_state *mas);
int lsf_node_capacity_mas_owner(struct ma_state *mas, struct lsf_node_capacity **owner);
void *lsf_node_capacity_maple_take(struct lsf_node_capacity *owner);
int lsf_node_mas_store(struct lsf_node_capacity *owner, struct ma_state *mas, void *entry);
int lsf_node_mas_allocate(struct ma_state *mas, gfp_t gfp);
void lsf_node_mt_free_one(struct maple_node *node);
void lsf_node_mt_free_bulk(size_t count, void __rcu **nodes);
int lsf_node_maple_rcu_queue(struct maple_node *node);
int lsf_node_capacity_stat_view(struct lsf_node_capacity *owner,
    unsigned int index, void *backing, void __percpu *pointer);
int lsf_node_capacity_stat_lookup(void __percpu *pointer,
    struct lsf_node_capacity **owner, unsigned int *index);
int lsf_node_capacity_stat_return(struct lsf_node_capacity *owner,
    unsigned int index);
int lsf_node_capacity_stat_finish_return(struct lsf_node_capacity *owner,
    unsigned int index, int freed);
int lsf_node_capacity_stat_allocated(struct lsf_node_capacity *owner,
    unsigned int index, int offset);
int lsf_node_capacity_stat_private_return(struct lsf_node_capacity *owner,
    unsigned int index, int *allocated);
int lsf_node_capacity_pcpu_commit(struct lsf_node_capacity *owner);
void __percpu *lsf_node_capacity_stat_take(struct lsf_node_capacity *owner);
int lsf_node_pcpu_free(void __percpu *pointer);
int lsf_node_pcpu_close_private(struct lsf_node_capacity *owner);

/* Real native layout producers; their implementation lives in the allocating
 * TU. Optional zero extents stay zero and cannot be taken from the bank.
 */
int lsf_node_pcpu_layout(struct lsf_node_capacity *owner);
int lsf_node_irq_layout(struct lsf_node_capacity *owner);
int lsf_node_irq_prepare(struct lsf_node_capacity *owner);
struct irq_desc *lsf_node_capacity_desc_take(struct lsf_node_capacity *owner);
int lsf_node_capacity_desc_close_private(struct lsf_node_capacity *owner,
    unsigned int index);
int lsf_node_irq_desc_delete(unsigned int irq, struct irq_desc *desc);
int lsf_node_irq_desc_queue(struct irq_desc *desc);
struct irq_desc *lsf_node_irq_desc_build(struct lsf_node_capacity *owner,
    int irq, int node, unsigned int flags, const struct cpumask *affinity,
    struct module *module_owner);
int lsf_node_irq_desc_store(struct lsf_node_capacity *owner, unsigned int irq,
    struct irq_desc *desc);
int lsf_node_irq_call_enter(struct irq_domain *domain, struct lsf_node_irq_call *call);
int lsf_node_irq_call_leave(struct lsf_node_irq_call *call);
int lsf_node_irq_current_owner(struct lsf_node_capacity **owner);
struct irq_domain *lsf_node_irq_current_domain(struct lsf_node_capacity *owner);
int lsf_node_irq_device_owner(struct irq_desc *desc, struct lsf_node_capacity **owner);
int lsf_node_irq_pci_owner(struct device *device, struct lsf_node_capacity **owner);
int lsf_node_irq_pci_original(struct device *device, struct lsf_node_capacity **owner);
struct irq_desc *lsf_node_irq_desc_allocate(int irq, int node, unsigned int flags,
    const struct cpumask *affinity, struct module *owner);
int lsf_node_irq_desc_insert(unsigned int irq, struct irq_desc *desc);
int lsf_node_irq_sysfs_enter(struct irq_desc *desc);
int lsf_node_irq_sysfs_leave(struct irq_desc *desc);
int lsf_node_irq_name_copy(struct irq_desc *desc, const char *text, char **copy);
int lsf_node_irq_name_capture(const struct kobject *object, const char *name,
    struct lsf_node_irq_name *copy);
int lsf_node_irq_name_finish(struct lsf_node_irq_name copy, const char *name);
int lsf_node_irq_kobject_owned(const struct kobject *object);
int lsf_node_irq_kobject_retain(const struct kobject *object);
int lsf_node_irq_kobject_current(const struct kobject *object);
int lsf_node_irq_kobject_type_known(const struct kobject *object);
int lsf_node_irq_kobject_ready(const struct kobject *object);
int lsf_node_irq_kobject_add(struct irq_desc *desc, int irq);
int lsf_node_irq_kobject_cleanup(struct kobject *object);
int lsf_node_vm_layout(struct lsf_node_capacity_extent *out);
int lsf_node_maple_layout(struct lsf_node_capacity_extent *out);
int lsf_node_pcpu_prepare(struct lsf_node_capacity *owner);
struct vm_struct **lsf_node_pcpu_vm_areas(struct lsf_node_capacity *owner,
    const unsigned long *offsets, const size_t *sizes, int groups,
    size_t alignment);
int lsf_node_pcpu_map(struct lsf_node_capacity *owner, unsigned long address,
    struct page **pages, unsigned int count);

int lsf_node_irqdomain_layout(struct lsf_node_capacity_extent *out);
int lsf_node_vector_layout(struct lsf_node_capacity_extent *out);
int lsf_node_irq_aux_prepare(struct lsf_node_capacity *owner);
int lsf_node_vector_prepare(struct lsf_node_capacity *owner);
int lsf_node_irq_aux_ready(struct lsf_node_capacity *owner);
void *lsf_node_irq_aux_take(struct lsf_node_capacity *owner,
    enum lsf_node_capacity_role role, const void *parent);
int lsf_node_irq_aux_index(const void *address, enum lsf_node_capacity_role role,
    struct lsf_node_capacity **owner, unsigned int *index);
int lsf_node_irq_aux_retire(const void *address, enum lsf_node_capacity_role role);
int lsf_node_irq_aux_uncertain(const void *address, enum lsf_node_capacity_role role);
int lsf_node_irq_aux_close_private(struct lsf_node_capacity *owner, unsigned int index);
int lsf_node_vector_begin(struct lsf_node_capacity *owner, unsigned int index,
    struct irq_matrix *matrix);
int lsf_node_vector_commit(struct lsf_node_capacity *owner, unsigned int index,
    struct irq_matrix *matrix, int vector, unsigned int cpu);
int lsf_node_vector_read(const void *apic, struct irq_matrix *matrix,
    struct lsf_node_vector_slot *out);
int lsf_node_vector_activate(const void *apic, struct irq_matrix *matrix);
int lsf_node_vector_retain(struct irq_matrix *matrix, unsigned int cpu,
    unsigned int vector, bool managed);
int lsf_node_matrix_room(struct irq_matrix *matrix, unsigned int count);
int lsf_node_matrix_held(struct irq_matrix *matrix, unsigned int cpu,
    unsigned int vector);

struct irqaction;
struct proc_dir_entry;
struct proc_ops;
struct seq_file;
struct irqaction *lsf_node_capacity_action_take(struct lsf_node_capacity *, struct irq_desc *);
int lsf_node_capacity_action_close_private(struct lsf_node_capacity *, unsigned int);
int lsf_node_irq_action_layout(struct lsf_node_capacity_extent *);
int lsf_node_irq_action_prepare(struct lsf_node_capacity *);
int lsf_node_irq_action_free(struct irqaction *);
int lsf_node_irq_proc_layout(struct lsf_node_capacity_extent *);
int lsf_node_irq_proc_name_layout(struct lsf_node_capacity_extent *);
void *lsf_node_irq_proc_allocate(struct lsf_node_capacity *, struct irq_desc *, unsigned int, bool);
int lsf_node_irq_proc_classify(const void *);
int lsf_node_irq_proc_free(struct proc_dir_entry *);
int lsf_node_irq_proc_name_pair(const void *, const void *);
struct proc_dir_entry *lsf_node_irq_proc_mkdir(struct irq_desc *, unsigned int,
    const char *, struct proc_dir_entry *);
struct proc_dir_entry *lsf_node_irq_proc_create_data(struct irq_desc *, unsigned int,
    const char *, umode_t, struct proc_dir_entry *, const struct proc_ops *, void *);
struct proc_dir_entry *lsf_node_irq_proc_create_single_data(struct irq_desc *, unsigned int,
    const char *, umode_t, struct proc_dir_entry *, int (*)(struct seq_file *, void *), void *);

int lsf_node_radix_layout(struct lsf_node_capacity_extent *out);
int lsf_node_radix_root_role(struct lsf_node_capacity *owner,
    struct xarray *root);
void *lsf_node_radix_take(struct lsf_node_capacity *owner,
    struct xarray *root, unsigned long bytes, unsigned long alignment);
int lsf_node_radix_owned(const void *address,
    struct lsf_node_capacity **owner, unsigned int *role);
int lsf_node_radix_root_owned(struct xarray *root,
    struct lsf_node_capacity **owner);
int lsf_node_radix_node_matches(const void *address,
    struct lsf_node_capacity *owner, struct xarray *root,
    unsigned int role);
int lsf_node_radix_queue(const void *address);
int lsf_node_radix_rcu_ready(const void *address);
int lsf_node_radix_finish(const void *address);
int lsf_node_radix_uncertain(const void *address);
int lsf_node_radix_prepare_slot(struct lsf_node_capacity *owner,
    struct xarray *root, unsigned long index);
int lsf_node_radix_ready_slot(struct xarray *root, unsigned long index);
int lsf_node_radix_prune_private(struct xarray *root);
int lsf_node_irq_revmap_prepare(struct irq_domain *domain,
    unsigned int virq, unsigned int nr_irqs);
int lsf_node_irq_revmap_prune(struct irq_domain *domain);
int lsf_node_pcpu_observe(struct lsf_node_capacity *owner,
    struct lsf_node_capacity_facts *facts);
int lsf_node_vector_observe(struct lsf_node_capacity *owner,
    struct lsf_node_capacity_facts *facts);
int lsf_node_vector_prepared_slot(struct lsf_node_capacity *owner,
    struct irq_matrix *matrix, unsigned int index, struct lsf_node_vector_slot *out);

#endif
