/* SPDX-License-Identifier: GPL-2.0-only */
/* Include in selected factory TU AFTER original device helpers. UNLINKED.
 * This constructs continuously Node-owned slots, not per-packet allocations.
 * Original pool_lock protects every pointer/phase/record below. */
#include <linux/pci.h>
#include <linux/kobject.h>
#include <linux/virtio.h>
#include <linux/virtio_config.h>
#include <linux/virtio_ids.h>
#include <linux/virtio_net.h>
#include <net/lsf_stream_ring_profile_private.h>

static inline int lsf_stream_geometry_add(u64 *total, u64 bytes, u64 count, u64 alignment)
{
    u64 aligned, all, start;
    if (!bytes || alignment < 64 || (alignment & (alignment - 1)) ||
        check_add_overflow(*total, alignment - 1, &start) ||
        check_add_overflow(bytes, 63ull, &aligned))
        return 0;
    aligned &= ~63ull;
    start &= ~(alignment - 1);
    if (check_mul_overflow(aligned, count, &all) ||
        check_add_overflow(start, all, total))
        return 0;
    return 1;
}

/* Call BEFORE any selected ring/RX construction, from the original factory
 * admission path. The ancestor producer must account for all existing/planned
 * allocations; a current-cursor snapshot alone is not a complete upper bound.
 * The actual constructor must follow THIS same ordered layout, including
 * page-aligned ring START offsets (not only page-rounded lengths). Original
 * order-7 base and infrastructure offset must be page aligned. No cap is
 * accepted as an argument; original constants remain authoritative. */
static inline int lsf_stream_geometry_fits(const struct lsf_stream_ring_geometry *g)
{
    u64 bytes = 0, records;
    if (!g || g->computed != LSF_STREAM_GEOMETRY_ALL ||
        !g->ancestor_bytes || !g->ancestor_records || g->ring_alignment != 4096 ||
        LSF_FACTORY_INFRA_OFFSET % g->ring_alignment ||
        !lsf_stream_geometry_add(&bytes, g->ancestor_bytes, 1, 64) ||
        !lsf_stream_geometry_add(&bytes, g->rx_head_bytes, LSF_STREAM_RX_DESCRIPTORS, 64) ||
        !lsf_stream_geometry_add(&bytes, g->rx_header_bytes, LSF_STREAM_RX_DESCRIPTORS, 64) ||
        !lsf_stream_geometry_add(&bytes, g->rx_queue_bytes, 1, 64) ||
        !lsf_stream_geometry_add(&bytes, g->tx_queue_bytes, 1, 64) ||
        !lsf_stream_geometry_add(&bytes, g->rx_ring_bytes, 1, g->ring_alignment) ||
        !lsf_stream_geometry_add(&bytes, g->tx_ring_bytes, 1, g->ring_alignment) ||
        !lsf_stream_geometry_add(&bytes, g->rx_state_bytes, 1, 64) ||
        !lsf_stream_geometry_add(&bytes, g->tx_state_bytes, 1, 64) ||
        !lsf_stream_geometry_add(&bytes, g->rx_extra_bytes, 1, 64) ||
        !lsf_stream_geometry_add(&bytes, g->tx_extra_bytes, 1, 64) ||
        !lsf_stream_geometry_add(&bytes, g->rx_vq_bytes, 1, 64) ||
        !lsf_stream_geometry_add(&bytes, g->tx_vq_bytes, 1, 64) ||
        /* Two continuous views per RX slot plus ten fixed queue/ring views.
         * Backing record and all other Root records belong to ancestor_records. */
        check_add_overflow(g->ancestor_records,
            2ull * LSF_STREAM_RX_DESCRIPTORS + 10ull, &records))
        return 0;
    return bytes <= LSF_FACTORY_INFRA_BYTES && records <= LSF_ALLOCATION_SLOTS;
}


struct lsf_stream_rx_head {
    void *address;
    struct lsf_prepaid_ticket ticket;
    u64 incarnation;
    unsigned int posted, data_returned, closing;
};
struct lsf_stream_rx_header {
    void *address;
    struct lsf_prepaid_ticket ticket;
    unsigned int borrowed, head_slot;
    u64 incarnation;
};
struct lsf_stream_rx_state {
    struct lsf_prepaid_key owner;
    struct lsf_prepaid_ticket state, root;
    struct lsf_stream_ring_geometry geometry;
    struct lsf_stream_rx_head heads[LSF_STREAM_RX_DESCRIPTORS];
    struct lsf_stream_rx_header headers[LSF_STREAM_RX_DESCRIPTORS];
    void *queue[10];
    struct lsf_prepaid_ticket queue_ticket[10];
    const struct pci_dev *pci;
    const struct virtio_device *virtio;
    unsigned int queue_claimed[10];
    unsigned int stopped, poisoned, closing, hardware_stopped, device_borrows;
    unsigned int collect_notice, collecting, finalizing, material_returned;
    struct lsf_stream_material_plan *material;
};
/* Scalar pointer is not ownership. Before dereference subsequent hooks must
 * revalidate state/key/ticket against original live Root and exact record.
 * Its final unpublication is required BEFORE the original bank physical put. */
static struct lsf_stream_rx_state *lsf_stream_rx;
static_assert(sizeof(struct lsf_stream_rx_state) <= LSF_FACTORY_INFRA_BYTES);
/* This include must follow the unchanged observer declarations too. */
static_assert(sizeof(factory) + LSF_BACKING_BYTES + sizeof(lsf_retirement) +
    sizeof(lsf_retirement_wait) + sizeof(lsf_stream_rx) < LSF_BOOTSTRAP_CEILING);

#include "factory-stream-material-plan.c"

static void *lsf_stream_rx_extent_locked(struct lsf_prepaid_key owner,
    struct lsf_prepaid_ticket parent, u64 bytes, unsigned int kind, u64 alignment,
    struct lsf_prepaid_ticket *ticket)
{
    u64 offset;
    lockdep_assert_held(&pool_lock);
    if (!lsf_device_allocate_stream_aligned(&factory.pool, owner, bytes,
        kind, parent, ticket, alignment, &offset))
        return NULL;
    return (char *)page_address(factory.pages) + offset;
}

/* Original caller must have already prepaid/constructed ALL ancestors and
 * supplied the complete producer-computed plan. This function does not infer
 * completeness from a cursor, caller boolean, byte receipt or record count.
 * No pointer is published to the device/normal networking before success. */
static int lsf_stream_rx_preallocate_locked(struct lsf_stream_ring_geometry g,
    struct lsf_stream_material_plan *material)
{
    struct lsf_prepaid_context *owner;
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_ticket ticket;
    struct lsf_prepaid_key key;
    u64 occupied = 0, state_bytes = (sizeof(*state) + 63u) & ~(u64)63u;
    u64 queue_bytes[10];
    unsigned int queue_kind[10] = { LSF_DEVICE_QUEUE, LSF_DEVICE_QUEUE,
        LSF_DEVICE_RING, LSF_DEVICE_RING,
        LSF_DEVICE_DESCRIPTOR_STATE, LSF_DEVICE_DESCRIPTOR_STATE,
        LSF_DEVICE_DESCRIPTOR_EXTRA, LSF_DEVICE_DESCRIPTOR_EXTRA,
        LSF_DEVICE_QUEUE, LSF_DEVICE_QUEUE };
    unsigned int i;
    lockdep_assert_held(&factory_lock);
    lockdep_assert_held(&pool_lock);
    if (!lsf_factory_selected_consumer() || lsf_stream_rx || !factory.pages ||
        !factory.device || factory.pool.stopped || factory.pool.poisoned ||
        READ_ONCE(factory.uncertain) || g.computed != LSF_STREAM_GEOMETRY_ALL)
        return -EOPNOTSUPP;
    key = factory.device->key;
    material = lsf_stream_material_current_locked(material);
    if (!material || material->sealed || material->owner.slot != key.slot ||
        material->owner.generation != key.generation ||
        material->root.slot != factory.device->root.slot ||
        material->root.generation != factory.device->root.generation)
        return -EPERM;
    owner = lsf_device_context(&factory.pool, key);
    if (!owner || owner->closed || !lsf_device_record(&factory.pool, key,
        factory.device->root, LSF_DEVICE_ROOT) || owner->cursor > LSF_FACTORY_INFRA_BYTES)
        return -EPERM;
    for (i = 0; i < LSF_ALLOCATION_SLOTS; ++i)
        occupied += factory.pool.records[i].phase != LSF_PREPAID_EMPTY;
    /* Exact ordered-plan prefix: original extents/padding already held, plus
     * this actual32-slot state. Returned records are still occupied too. */
    if (g.ancestor_records != occupied + 1 ||
        g.ancestor_bytes != owner->cursor + state_bytes || !lsf_stream_geometry_fits(&g))
        return -ENOBUFS;
    state = lsf_stream_rx_extent_locked(key, factory.device->root, sizeof(*state),
        LSF_DEVICE_QUEUE, 64, &ticket);
    if (!state)
        goto poison;
    memset(state, 0, sizeof(*state));
    state->state = ticket; state->root = factory.device->root;
    state->owner = key; state->geometry = g;
    state->material = material; /* Same actual prepaid plan, never caller certification. */
    for (i = 0; i < LSF_STREAM_RX_DESCRIPTORS; ++i) {
        state->heads[i].address = lsf_stream_rx_extent_locked(key, ticket,
            g.rx_head_bytes, LSF_DEVICE_RX_HEAD, 64, &state->heads[i].ticket);
        if (!state->heads[i].address)
            goto poison;
        state->heads[i].data_returned = 1; // Never lent, not a physical-return claim.
    }
    for (i = 0; i < LSF_STREAM_RX_DESCRIPTORS; ++i) {
        state->headers[i].address = lsf_stream_rx_extent_locked(key, ticket,
            g.rx_header_bytes, LSF_DEVICE_RX_HEADER, 64, &state->headers[i].ticket);
        if (!state->headers[i].address)
            goto poison;
    }
    queue_bytes[0] = g.rx_queue_bytes; queue_bytes[1] = g.tx_queue_bytes;
    queue_bytes[2] = g.rx_ring_bytes; queue_bytes[3] = g.tx_ring_bytes;
    queue_bytes[4] = g.rx_state_bytes; queue_bytes[5] = g.tx_state_bytes;
    queue_bytes[6] = g.rx_extra_bytes; queue_bytes[7] = g.tx_extra_bytes;
    queue_bytes[8] = g.rx_vq_bytes; queue_bytes[9] = g.tx_vq_bytes;
    for (i = 0; i < 10; ++i) {
        state->queue[i] = lsf_stream_rx_extent_locked(key, ticket, queue_bytes[i],
            queue_kind[i], (i == 2 || i == 3) ? g.ring_alignment : 64,
            &state->queue_ticket[i]);
        if (!state->queue[i])
            goto poison;
    }
    /* Every view/record/padding is now held before any DMA/native publication.
     * Nothing is returned per packet; actual borrowing hooks come next. */
    lsf_stream_rx = state;
    return 0;
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    /* Partial preallocation remains in SAME original paid Root; no free,
     * rollback/retry allocation, private pointer exposure or fake fit. */
    return -ENOBUFS;
}

/* Actual source-selected normal PCI/virtio births ONLY; never adopt an
 * ordinary vdev or trust a device pointer/size to establish an allocation. */
static struct lsf_stream_rx_state *lsf_stream_rx_current_locked(void)
{
    struct lsf_prepaid_view *record;
    struct lsf_stream_rx_state *state = lsf_stream_rx;
    unsigned long base, address = (unsigned long)state;
    unsigned int i;
    lockdep_assert_held(&pool_lock);
    if (!factory.pages || !factory.device || !state || factory.pool.poisoned ||
        READ_ONCE(factory.uncertain))
        return NULL;
    base = (unsigned long)page_address(factory.pages);
    if (address < base || address - base > LSF_BACKING_BYTES - sizeof(*state))
        return NULL;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset != address - base || record->kind != LSF_DEVICE_QUEUE ||
            record->bytes < sizeof(*state))
            continue;
        if (!lsf_device_record(&factory.pool, factory.device->key,
            (struct lsf_prepaid_ticket){i, record->generation}, LSF_DEVICE_QUEUE) ||
            record->cache_bucket != factory.device->root.slot ||
            record->cache_anchor != factory.device->root.generation)
            return NULL;
        /* Only now is the original state extent safe to read. */
        if (state->state.slot != i || state->state.generation != record->generation ||
            state->owner.slot != factory.device->key.slot ||
            state->owner.generation != factory.device->key.generation || state->poisoned)
            return NULL;
        return state;
    }
    return NULL;
}

/* Exact existing pool/Root only. Called with ORIGINAL pool_lock held by a
 * real record/loan return; no user input, queue, allocation or physical drop.
 * Kthreadd consumes notice ONCE per attempt, so retained tails never spin. */
void lsf_factory_stream_root_notify_locked(struct lsf_prepaid *pool)
{
    struct lsf_stream_rx_state *state;
    lockdep_assert_held(&pool_lock);
    if (pool != &factory.pool || !lsf_factory_selected_consumer()) return;
    state = lsf_stream_rx_current_locked();
    if (!state || !state->closing || state->collecting) return;
    state->collect_notice = 1;
    wake_up_process(kthreadd_task);
}

/* Only the actual collector can seal further birth after every other
 * original typed owner is returned. A rejected late birth poisons/retains;
 * it never manufactures a final-free or bypasses the original allocator. */
int lsf_factory_stream_allocation_open_locked(struct lsf_prepaid *pool)
{
    struct lsf_stream_rx_state *state;
    lockdep_assert_held(&pool_lock);
    if (!lsf_factory_selected_consumer()) return 1;
    if (pool != &factory.pool) return 0;
    state = lsf_stream_rx_current_locked();
    if (state && state->finalizing) {
        pool->poisoned = 1;
        WRITE_ONCE(factory.uncertain, 1);
        return 0;
    }
    return 1;
}

/* Only an already authenticated born PCI/virtio pair may enter. The original
 * Root record and this counted bank loan keep the memory alive while device
 * references cover their original release callbacks. No callback/put runs
 * under pool_lock; no new allocation, queue or mirrored lifetime table. */
static int lsf_stream_rx_device_get_locked(struct lsf_stream_rx_state *state,
    unsigned int *held)
{
    struct lsf_prepaid_ticket pci = {0};
    struct lsf_prepaid_view *record;
    unsigned long base;
    unsigned int i;
    lockdep_assert_held(&pool_lock);
    if (!held) return 0;
    *held = 0;
    if (!state || !state->pci || !state->virtio || state->device_borrows == UINT_MAX ||
        !factory.pages || state != lsf_stream_rx_current_locked())
        return 0;
    base = (unsigned long)page_address(factory.pages);
    /* Revalidate BOTH LIVE typed births and immutable parent before touching
     * either kobject, including the final-stop path after asynchronous use. */
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->kind == LSF_DEVICE_PCI && record->bytes >= sizeof(*state->pci) &&
            (unsigned long)state->pci == base + record->offset &&
            lsf_device_record(&factory.pool, state->owner,
                (struct lsf_prepaid_ticket){i, record->generation}, LSF_DEVICE_PCI)) {
            pci = (struct lsf_prepaid_ticket){i, record->generation}; break;
        }
    }
    if (!pci.slot) return 0;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->kind == LSF_DEVICE_VIRTIO && record->bytes >= sizeof(*state->virtio) &&
            (unsigned long)state->virtio == base + record->offset &&
            record->cache_bucket == pci.slot && record->cache_anchor == pci.generation &&
            lsf_device_record(&factory.pool, state->owner,
                (struct lsf_prepaid_ticket){i, record->generation}, LSF_DEVICE_VIRTIO)) break;
    }
    if (i == LSF_ALLOCATION_SLOTS || state->virtio->dev.parent != &state->pci->dev)
        return 0;
    ++state->device_borrows;
    /* LIVE birth storage is not a positive kref. A racing original release
     * must never be resurrected. Even partial acquisition retains this SAME
     * bank loan; the fixed stack mask is consumed outside locks by put below. */
    if (kobject_get_unless_zero((struct kobject *)&state->pci->dev.kobj)) *held |= 1;
    if (kobject_get_unless_zero((struct kobject *)&state->virtio->dev.kobj)) *held |= 2;
    return 1;
}

/* Device put can schedule the original prepaid ACPI work. Its record is
 * returned INSIDE the callback; that is not the workqueue epilogue fence.
 * SAME bank loan remains counted until flush_work has completed outside locks.
 * No queue, new work item, retry, expiry renewal or record refund is added. */
static int lsf_stream_rx_firmware_tail(void)
{
    struct lsf_factory_device_firmware *owned;
    struct work_struct *work;
    unsigned long flags;
    int result;
    spin_lock_irqsave(&pool_lock, flags);
    if (!factory.device || !factory.pages) goto refuse;
    if (!factory.device->firmware.slot) {
        if (factory.device->firmware.generation) goto refuse;
        spin_unlock_irqrestore(&pool_lock, flags);
        return 1; /* No firmware descriptor/work birth ever occurred. */
    }
    owned = lsf_factory_device_firmware_locked();
    if (!owned || !owned->retirement || !owned->queued) goto refuse;
    work = &owned->work;
    spin_unlock_irqrestore(&pool_lock, flags);
    /* Called AFTER both actual device puts returned. The original scheduling
     * call has therefore completed, not merely set its pre-queue scalar. */
    flush_work(work);
    spin_lock_irqsave(&pool_lock, flags);
    result = lsf_factory_device_firmware_locked() == owned &&
        owned->returned == 1 && owned->putting == 1 && !owned->companion && !owned->handle &&
        factory.pool.records[factory.device->firmware.slot].phase == LSF_PREPAID_RETURNED;
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
refuse:
    spin_unlock_irqrestore(&pool_lock, flags);
    return 0;
}

static int lsf_stream_rx_device_put(struct lsf_stream_rx_state *state,
    struct pci_dev *pci, struct virtio_device *vdev, unsigned int held, bool final_stop)
{
    unsigned long flags;
    int result = 0, tails = 1;
    /* A final device release can re-enter original prepaid return hooks.
     * Bank loan remains held through both callbacks, outside ALL pool locks. */
    if (held & 2) put_device(&vdev->dev);
    if (held & 1) put_device(&pci->dev);
    if (final_stop) tails = lsf_stream_rx_firmware_tail();
    spin_lock_irqsave(&pool_lock, flags);
    if (tails && lsf_stream_rx_current_locked() == state && state->pci == pci &&
        state->virtio == vdev && state->device_borrows) {
        --state->device_borrows;
        lsf_factory_stream_root_notify_locked(&factory.pool);
        result = 1;
    } else {
        factory.pool.poisoned = 1;
        WRITE_ONCE(factory.uncertain, 1); /* Original loan remains quarantined. */
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

int lsf_factory_stream_queue_count(struct pci_dev *pci, struct virtio_device *vdev,
    unsigned int index, unsigned int maximum)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *record;
    struct lsf_prepaid_ticket pci_birth = {0};
    unsigned long flags, base, at = (unsigned long)vdev;
    unsigned int i, desired = index == 0 ? LSF_STREAM_RX_DESCRIPTORS : LSF_STREAM_TX_DESCRIPTORS;
    unsigned int held = 0;
    int owned, borrowed = 0, result = -EOPNOTSUPP;
    if (!lsf_factory_selected_consumer())
        return 0; /* Original constructor qualification unchanged. */
    owned = lsf_factory_device_pci_owned(pci, sizeof(*pci));
    if (owned <= 0)
        return owned; /* Zero genuinely outside, negative never falls back. */
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    if (!state || state->stopped || state->closing || factory.pool.stopped || index > 1 || maximum < desired)
        goto out;
    base = (unsigned long)page_address(factory.pages);
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset == (unsigned long)pci - base && record->kind == LSF_DEVICE_PCI &&
            record->bytes >= sizeof(*pci) && lsf_device_record(&factory.pool, state->owner,
                (struct lsf_prepaid_ticket){i, record->generation}, LSF_DEVICE_PCI)) {
            pci_birth = (struct lsf_prepaid_ticket){i, record->generation};
            break;
        }
    }
    if (!pci_birth.slot)
        goto out;
    /* Require the actual privately allocated virtio child of SAME PCI birth.
     * No dereference of a caller-selected vdev before original record match. */
    if (at < base || at - base > LSF_BACKING_BYTES - sizeof(*vdev))
        goto out;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (record->offset == at - base && record->kind == LSF_DEVICE_VIRTIO &&
            record->bytes >= sizeof(*vdev) && record->cache_bucket == pci_birth.slot &&
            record->cache_anchor == pci_birth.generation &&
            lsf_device_record(&factory.pool, state->owner,
                (struct lsf_prepaid_ticket){i, record->generation}, LSF_DEVICE_VIRTIO))
            break;
    }
    if (i == LSF_ALLOCATION_SLOTS || vdev->id.device != VIRTIO_ID_NET ||
        vdev->dev.parent != &pci->dev ||
        !virtio_has_feature(vdev, VIRTIO_F_VERSION_1) ||
        !virtio_has_feature(vdev, VIRTIO_F_RING_RESET) ||
        !vdev->config->synchronize_cbs ||
        virtio_has_feature(vdev, VIRTIO_F_RING_PACKED) ||
        virtio_has_feature(vdev, VIRTIO_RING_F_INDIRECT_DESC) ||
        virtio_has_feature(vdev, VIRTIO_NET_F_MRG_RXBUF) ||
        virtio_has_feature(vdev, VIRTIO_NET_F_HASH_REPORT) ||
        (state->virtio && state->virtio != vdev) || (state->pci && state->pci != pci))
        goto out;
    state->pci = pci; state->virtio = vdev;
    if (!lsf_stream_rx_device_get_locked(state, &held)) goto out;
    borrowed = 1;
    if (held != 3) goto out;
    result = desired;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    /* Pure feature predicate from actual pinned ring TU; no DMA operations,
     * allocation or feature clearing. Unsupported DMA refuses before birth. */
    if (borrowed) {
        if (held == 3 && !lsf_prepaid_stream_direct_dma(vdev)) result = -EOPNOTSUPP;
        if (!lsf_stream_rx_device_put(state, pci, vdev, held, false)) result = -EIO;
    }
    return result;
}

void *lsf_factory_stream_queue_view(struct virtio_device *vdev,
    enum lsf_stream_queue_view which, unsigned long bytes)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *record;
    u64 expected[10];
    unsigned int kind[10] = { LSF_DEVICE_QUEUE, LSF_DEVICE_QUEUE,
        LSF_DEVICE_RING, LSF_DEVICE_RING, LSF_DEVICE_DESCRIPTOR_STATE,
        LSF_DEVICE_DESCRIPTOR_STATE, LSF_DEVICE_DESCRIPTOR_EXTRA,
        LSF_DEVICE_DESCRIPTOR_EXTRA, LSF_DEVICE_QUEUE, LSF_DEVICE_QUEUE };
    unsigned long flags;
    void *result = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    if (!state || state->stopped || state->closing || factory.pool.stopped || state->virtio != vdev ||
        (unsigned int)which >= 10 || state->queue_claimed[which])
        goto out;
    expected[0] = state->geometry.rx_queue_bytes; expected[1] = state->geometry.tx_queue_bytes;
    expected[2] = state->geometry.rx_ring_bytes; expected[3] = state->geometry.tx_ring_bytes;
    expected[4] = state->geometry.rx_state_bytes; expected[5] = state->geometry.tx_state_bytes;
    expected[6] = state->geometry.rx_extra_bytes; expected[7] = state->geometry.tx_extra_bytes;
    expected[8] = state->geometry.rx_vq_bytes; expected[9] = state->geometry.tx_vq_bytes;
    record = lsf_device_record(&factory.pool, state->owner, state->queue_ticket[which], kind[which]);
    if (!bytes || bytes != expected[which] || !record ||
        record->cache_bucket != state->state.slot || record->cache_anchor != state->state.generation ||
        state->queue[which] != (char *)page_address(factory.pages) + record->offset ||
        !lsf_device_publish(&factory.pool, state->owner, state->queue_ticket[which], kind[which]))
        goto out;
    state->queue_claimed[which] = 1;
    result = state->queue[which];
    memset(result, 0, bytes);
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* The complete4-view tuple is validated/published atomically before native
 * construction; a failed check never exposes a partially claimed constructor. */
int lsf_factory_stream_ring_views(struct virtio_device *vdev, unsigned int index,
    unsigned long ring_bytes, unsigned long state_bytes, unsigned long extra_bytes,
    unsigned long vq_bytes, struct lsf_stream_ring_views *views)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *records[4];
    u64 expected[4], offered[4] = {ring_bytes, state_bytes, extra_bytes, vq_bytes};
    unsigned int row[4], kind[4] = {LSF_DEVICE_RING, LSF_DEVICE_DESCRIPTOR_STATE,
        LSF_DEVICE_DESCRIPTOR_EXTRA, LSF_DEVICE_QUEUE};
    unsigned long flags, base;
    unsigned int i;
    int result = -EOPNOTSUPP;
    if (!views || index > 1)
        return -EINVAL;
    *views = (struct lsf_stream_ring_views){0};
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    if (!state || state->stopped || state->closing || factory.pool.stopped || state->virtio != vdev)
        goto out;
    base = (unsigned long)page_address(factory.pages);
    row[0] = 2 + index; row[1] = 4 + index; row[2] = 6 + index; row[3] = 8 + index;
    expected[0] = index ? state->geometry.tx_ring_bytes : state->geometry.rx_ring_bytes;
    expected[1] = index ? state->geometry.tx_state_bytes : state->geometry.rx_state_bytes;
    expected[2] = index ? state->geometry.tx_extra_bytes : state->geometry.rx_extra_bytes;
    expected[3] = index ? state->geometry.tx_vq_bytes : state->geometry.rx_vq_bytes;
    for (i = 0; i < 4; ++i) {
        records[i] = lsf_device_record(&factory.pool, state->owner, state->queue_ticket[row[i]], kind[i]);
        if (!offered[i] || offered[i] != expected[i] || state->queue_claimed[row[i]] ||
            !records[i] || records[i]->deferred != LSF_PREPAID_PRIVATE ||
            records[i]->cache_bucket != state->state.slot ||
            records[i]->cache_anchor != state->state.generation ||
            state->queue[row[i]] != (void *)(base + records[i]->offset))
            goto out;
    }
    for (i = 0; i < 4; ++i) {
        if (!lsf_device_publish(&factory.pool, state->owner, state->queue_ticket[row[i]], kind[i])) {
            state->poisoned = factory.pool.poisoned = 1;
            WRITE_ONCE(factory.uncertain, 1);
            goto out; // Retain exact original extents on impossible transition.
        }
        state->queue_claimed[row[i]] = 1;
        memset(state->queue[row[i]], 0, offered[i]);
    }
    *views = (struct lsf_stream_ring_views){state->queue[row[0]], state->queue[row[1]],
        state->queue[row[2]], state->queue[row[3]]};
    result = 0;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Zero genuinely outside, negative private/unknown => retain; no normal-free. */
int lsf_factory_stream_ring_owned(const void *address, unsigned long bytes)
{
    struct lsf_stream_rx_state *state;
    unsigned long flags, base, at = (unsigned long)address;
    unsigned int i;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_factory_selected_consumer() || !factory.pages) goto out;
    base = (unsigned long)page_address(factory.pages);
    if (at < base || at - base >= LSF_BACKING_BYTES) goto out;
    result = -1;
    state = lsf_stream_rx_current_locked();
    if (!state) goto out;
    for (i = 8; i < 10; ++i) {
        struct lsf_prepaid_view *record = lsf_device_record(&factory.pool, state->owner,
            state->queue_ticket[i], LSF_DEVICE_QUEUE);
        if (state->queue[i] == address && record && bytes <= record->bytes &&
            record->offset == at - base && record->cache_bucket == state->state.slot &&
            record->cache_anchor == state->state.generation && state->queue_claimed[i] == 1) {
            result = 1; break;
        }
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Called ONLY after original transport disable/reset+IRQ synchronization,
 * exact original ring has no outstanding descriptors, and original list unlink.
 * Each actual field pointer is checked; no timeout/status substitutes for free. */
int lsf_factory_stream_ring_return(struct virtio_device *vdev, unsigned int index,
    const void *ring, const void *descriptors, const void *extra, const void *vq)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *record;
    const void *actual[4] = {ring, descriptors, extra, vq};
    unsigned int row[4], kind[4] = {LSF_DEVICE_RING, LSF_DEVICE_DESCRIPTOR_STATE,
        LSF_DEVICE_DESCRIPTOR_EXTRA, LSF_DEVICE_QUEUE};
    unsigned long flags;
    unsigned int i;
    int result = -1;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    if (!state || index > 1 || state->virtio != vdev) goto out;
    row[0] = 2 + index; row[1] = 4 + index; row[2] = 6 + index; row[3] = 8 + index;
    for (i = 0; i < 4; ++i) {
        record = lsf_device_record(&factory.pool, state->owner, state->queue_ticket[row[i]], kind[i]);
        if (!record || record->deferred != LSF_PREPAID_PUBLISHED ||
            record->cache_bucket != state->state.slot || record->cache_anchor != state->state.generation ||
            state->queue[row[i]] != actual[i] || state->queue_claimed[row[i]] != 1)
            goto out;
    }
    for (i = 0; i < 4; ++i) {
        if (!lsf_device_queue(&factory.pool, state->owner, state->queue_ticket[row[i]], kind[i]) ||
            !lsf_device_finish(&factory.pool, state->owner, state->queue_ticket[row[i]], kind[i])) {
            state->poisoned = factory.pool.poisoned = 1;
            WRITE_ONCE(factory.uncertain, 1);
            goto out;
        }
        state->queue_claimed[row[i]] = 2;
    }
    result = 1; // Real view returns ONLY; original bank remains continuously paid.
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Original continuous Node records remain LIVE/PUBLISHED across successive
 * packet loans. These scalar loan states never queue/finish a record, refund
 * physical backing, change Root generation or allocate a replacement head. */
static int lsf_stream_rx_address_locked(const void *address)
{
    unsigned long base, at = (unsigned long)address;
    lockdep_assert_held(&pool_lock);
    if (!lsf_factory_selected_consumer() || !factory.pages) return 0;
    base = (unsigned long)page_address(factory.pages);
    return at >= base && at - base < LSF_BACKING_BYTES;
}

static int lsf_stream_rx_publish_locked(struct lsf_stream_rx_state *state,
    struct lsf_prepaid_ticket ticket, unsigned int kind)
{
    struct lsf_prepaid_view *record = lsf_device_record(&factory.pool,
        state->owner, ticket, kind);
    lockdep_assert_held(&pool_lock);
    if (!record || record->cache_bucket != state->state.slot ||
        record->cache_anchor != state->state.generation)
        return 0;
    if (record->deferred == LSF_PREPAID_PRIVATE)
        return lsf_device_publish(&factory.pool, state->owner, ticket, kind);
    return record->deferred == LSF_PREPAID_PUBLISHED;
}

/* Zero outside selected device, negative private refusal, one real paid loan.
 * Caller invokes BEFORE skb_page_frag_refill/virtnet_rq_alloc and never falls
 * back on private refusal. Exact compiled full head extent is mandatory. */
int lsf_factory_stream_rx_take(struct virtio_device *vdev, unsigned long bytes, void **head)
{
    struct lsf_stream_rx_state *state;
    unsigned long flags;
    unsigned int i;
    int result = 0;
    if (!head) return -EINVAL;
    *head = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    if (!state || state->virtio != vdev) {
        if (lsf_factory_selected_consumer()) result = -EOPNOTSUPP;
        goto out;
    }
    result = -ENOBUFS;
    if (state->stopped || state->closing || state->poisoned || factory.pool.stopped ||
        factory.pool.poisoned || READ_ONCE(factory.uncertain) ||
        bytes != state->geometry.rx_head_bytes)
        goto out;
    for (i = 0; i < LSF_STREAM_RX_DESCRIPTORS; ++i) {
        struct lsf_stream_rx_head *slot = &state->heads[i];
        if (slot->posted || !slot->data_returned || slot->closing ||
            slot->incarnation == U64_MAX)
            continue;
        if (!lsf_stream_rx_publish_locked(state, slot->ticket, LSF_DEVICE_RX_HEAD))
            goto out;
        ++slot->incarnation;
        slot->posted = 1;
        slot->data_returned = 0;
        *head = slot->address;
        result = 1;
        break;
    }
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Actual unused descriptor return OR failed add_inbuf/receive, before any
 * skb dataref has been created. Address must be the original head, not page. */
int lsf_factory_stream_rx_unposted(void *head)
{
    struct lsf_stream_rx_state *state;
    unsigned long flags;
    unsigned int i;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_stream_rx_address_locked(head)) goto out;
    result = -1;
    state = lsf_stream_rx_current_locked();
    if (!state) goto out;
    for (i = 0; i < LSF_STREAM_RX_DESCRIPTORS; ++i) {
        struct lsf_stream_rx_head *slot = &state->heads[i];
        if (slot->address != head) continue;
        if (slot->posted != 1 || slot->data_returned ||
            !lsf_stream_rx_publish_locked(state, slot->ticket, LSF_DEVICE_RX_HEAD))
            goto out;
        slot->posted = 0;
        slot->data_returned = 1;
        result = 1;
        break;
    }
out:
    if (result < 0) {
        factory.pool.poisoned = 1;
        WRITE_ONCE(factory.uncertain, 1);
    }
    if (result == 1) lsf_factory_stream_root_notify_locked(&factory.pool);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Actual RX completion transfers the SAME head to original skb shared_info
 * dataref, using one continuously paid header. Caller uses build_skb_around;
 * no new slab/page allocation or fabricated page reference is created. */
int lsf_factory_stream_rx_header(void *head, unsigned long bytes, struct sk_buff **skb)
{
    struct lsf_stream_rx_state *state;
    struct lsf_stream_rx_head *owner = NULL;
    unsigned long flags;
    unsigned int i;
    int result = 0;
    if (!skb) return -EINVAL;
    *skb = NULL;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_stream_rx_address_locked(head)) goto out;
    result = -1;
    state = lsf_stream_rx_current_locked();
    if (!state || bytes != state->geometry.rx_head_bytes) goto out;
    for (i = 0; i < LSF_STREAM_RX_DESCRIPTORS; ++i)
        if (state->heads[i].address == head) { owner = &state->heads[i]; break; }
    if (!owner || owner->posted != 1 || owner->data_returned) goto out;
    result = -ENOBUFS;
    for (i = 0; i < LSF_STREAM_RX_DESCRIPTORS; ++i) {
        struct lsf_stream_rx_header *header = &state->headers[i];
        if (header->borrowed) continue;
        if (!lsf_stream_rx_publish_locked(state, header->ticket, LSF_DEVICE_RX_HEADER))
            goto out;
        header->head_slot = owner - state->heads;
        header->incarnation = owner->incarnation;
        header->borrowed = 1;
        owner->posted = 0;
        memset(header->address, 0, sizeof(struct sk_buff));
        *skb = header->address;
        result = 1;
        break;
    }
out:
    if (result < 0 && result != -ENOBUFS) {
        factory.pool.poisoned = 1;
        WRITE_ONCE(factory.uncertain, 1);
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* The ONLY caller is original skb_free_head: final shared dataref, or the
 * original proven-uncloned old-head relocation. Original refcounts stay. This
 * returns a packet loan, not the continuously live record or bank physical. */
int lsf_factory_stream_rx_data_return(const void *head)
{
    struct lsf_stream_rx_state *state;
    unsigned long flags;
    unsigned int i;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_stream_rx_address_locked(head)) goto out;
    result = -1;
    state = lsf_stream_rx_current_locked();
    if (!state) goto out;
    for (i = 0; i < LSF_STREAM_RX_DESCRIPTORS; ++i) {
        struct lsf_stream_rx_head *slot = &state->heads[i];
        if (slot->address != head) continue;
        if (slot->posted || slot->data_returned || !slot->incarnation) goto out;
        slot->data_returned = 1;
        result = 1;
        break;
    }
out:
    if (result < 0) {
        factory.pool.poisoned = 1;
        WRITE_ONCE(factory.uncertain, 1);
    }
    if (result == 1) lsf_factory_stream_root_notify_locked(&factory.pool);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Hook actual header disposal before slab bulk/cache insertion too. Header
 * retirement is distinct from final shared dataref and never implies it. */
int lsf_factory_stream_rx_header_return(const void *skb)
{
    struct lsf_stream_rx_state *state;
    unsigned long flags;
    unsigned int i;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_stream_rx_address_locked(skb)) goto out;
    result = -1;
    state = lsf_stream_rx_current_locked();
    if (!state) goto out;
    for (i = 0; i < LSF_STREAM_RX_DESCRIPTORS; ++i) {
        struct lsf_stream_rx_header *header = &state->headers[i];
        if (header->address != skb) continue;
        if (header->borrowed != 1 || !header->incarnation) goto out;
        header->borrowed = 0;
        result = 1;
        break;
    }
out:
    if (result < 0) {
        factory.pool.poisoned = 1;
        WRITE_ONCE(factory.uncertain, 1);
    }
    if (result == 1) lsf_factory_stream_root_notify_locked(&factory.pool);
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Real driver alloc_queues precedes find_vqs/setup_vq. Bind the original born
 * virtio/PCI records here, BEFORE either original kcalloc, not by a later ring
 * callback or a caller's module/name. The two actual typed extents were prepaid
 * by compiled geometry; one pair/no-control/small RX is the private platform. */
int lsf_factory_stream_net_queues(struct virtio_device *vdev, unsigned int pairs,
    bool control, bool large, bool mergeable, unsigned long rx_bytes,
    unsigned long tx_bytes, struct lsf_stream_net_views *views)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *birth = NULL, *pci_record, *record[2];
    struct pci_dev *pci;
    struct lsf_prepaid_ticket pci_ticket;
    unsigned long flags, base, at = (unsigned long)vdev;
    unsigned int i;
    int result = 0;
    if (!views) return -EINVAL;
    *views = (struct lsf_stream_net_views){0};
    if (!lsf_factory_selected_consumer()) return 0;
    result = -EOPNOTSUPP; // Selected private path never falls back on unknown device.
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_stream_rx_address_locked(vdev)) goto out;
    state = lsf_stream_rx_current_locked();
    if (!state || state->stopped || state->closing || factory.pool.stopped || pairs != 1 || control ||
        large || mergeable || rx_bytes != state->geometry.rx_queue_bytes ||
        tx_bytes != state->geometry.tx_queue_bytes)
        goto out;
    base = (unsigned long)page_address(factory.pages);
    if (at - base > LSF_BACKING_BYTES - sizeof(*vdev)) goto out;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        struct lsf_prepaid_view *candidate = &factory.pool.records[i];
        if (candidate->offset == at - base && candidate->kind == LSF_DEVICE_VIRTIO &&
            candidate->bytes >= sizeof(*vdev) && lsf_device_record(&factory.pool,
                state->owner, (struct lsf_prepaid_ticket){i, candidate->generation},
                LSF_DEVICE_VIRTIO)) { birth = candidate; break; }
    }
    if (!birth) goto out;
    pci_ticket = (struct lsf_prepaid_ticket){birth->cache_bucket, birth->cache_anchor};
    pci_record = lsf_device_record(&factory.pool, state->owner, pci_ticket, LSF_DEVICE_PCI);
    if (!pci_record || pci_record->bytes < sizeof(*pci)) goto out;
    pci = (void *)(base + pci_record->offset);
    /* Only after original record/parent/range authentication may either
     * actual object be dereferenced. No reference or allocation is created. */
    if (vdev->dev.parent != &pci->dev || vdev->id.device != VIRTIO_ID_NET ||
        !virtio_has_feature(vdev, VIRTIO_F_VERSION_1) ||
        !virtio_has_feature(vdev, VIRTIO_F_RING_RESET) ||
        !vdev->config->synchronize_cbs ||
        virtio_has_feature(vdev, VIRTIO_F_RING_PACKED) ||
        virtio_has_feature(vdev, VIRTIO_RING_F_INDIRECT_DESC) ||
        !lsf_prepaid_stream_direct_dma(vdev) ||
        (state->virtio && state->virtio != vdev) || (state->pci && state->pci != pci))
        goto out;
    for (i = 0; i < 2; ++i) {
        record[i] = lsf_device_record(&factory.pool, state->owner,
            state->queue_ticket[i], LSF_DEVICE_QUEUE);
        if (!record[i] || record[i]->deferred != LSF_PREPAID_PRIVATE ||
            record[i]->cache_bucket != state->state.slot ||
            record[i]->cache_anchor != state->state.generation || state->queue_claimed[i] ||
            state->queue[i] != (void *)(base + record[i]->offset))
            goto out;
    }
    state->pci = pci; state->virtio = vdev;
    for (i = 0; i < 2; ++i) {
        if (!lsf_device_publish(&factory.pool, state->owner, state->queue_ticket[i],
            LSF_DEVICE_QUEUE)) {
            factory.pool.poisoned = state->poisoned = 1;
            WRITE_ONCE(factory.uncertain, 1);
            goto out;
        }
        state->queue_claimed[i] = 1;
        memset(state->queue[i], 0, i ? tx_bytes : rx_bytes);
    }
    *views = (struct lsf_stream_net_views){state->queue[0], state->queue[1]};
    result = 1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Original free_queues has deleted both NAPI owners and completed its real
 * synchronize_net grace period. A negative identity never reaches kfree.
 * Packet dataref/header loans remain distinct and can outlive these arrays. */
int lsf_factory_stream_net_queues_return(struct virtio_device *vdev,
    const void *rx, const void *tx)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_view *record[2];
    const void *actual[2] = {rx, tx};
    unsigned long flags;
    unsigned int i;
    int result = 0;
    spin_lock_irqsave(&pool_lock, flags);
    if (!lsf_stream_rx_address_locked(rx) && !lsf_stream_rx_address_locked(tx)) goto out;
    result = -1;
    state = lsf_stream_rx_current_locked();
    if (!state || state->virtio != vdev) goto out;
    for (i = 0; i < 2; ++i) {
        record[i] = lsf_device_record(&factory.pool, state->owner,
            state->queue_ticket[i], LSF_DEVICE_QUEUE);
        if (!record[i] || record[i]->deferred != LSF_PREPAID_PUBLISHED ||
            record[i]->cache_bucket != state->state.slot ||
            record[i]->cache_anchor != state->state.generation ||
            state->queue_claimed[i] != 1 || state->queue[i] != actual[i]) goto out;
    }
    state->stopped = 1;
    for (i = 0; i < 2; ++i) {
        if (!lsf_device_queue(&factory.pool, state->owner, state->queue_ticket[i], LSF_DEVICE_QUEUE) ||
            !lsf_device_finish(&factory.pool, state->owner, state->queue_ticket[i], LSF_DEVICE_QUEUE))
            goto out;
        state->queue_claimed[i] = 2;
    }
    result = 1;
out:
    if (result < 0) {
        factory.pool.poisoned = 1;
        WRITE_ONCE(factory.uncertain, 1);
    }
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Final RX child-view collection ONLY. This is deliberately NOT a Root bank
 * free, a constructor-profile relaxation, or evidence of unrelated device/
 * socket/DNS/neighbour/LSM retirement. Normal Root must establish ALL other
 * original tails first and invoke this at its final locked collection edge. */
static int lsf_stream_rx_finish_loan_view_locked(struct lsf_stream_rx_state *state,
    struct lsf_prepaid_ticket ticket, unsigned int kind, const void *address, u64 bytes)
{
    struct lsf_prepaid_view *record = lsf_device_record(&factory.pool,
        state->owner, ticket, kind);
    unsigned long base = (unsigned long)page_address(factory.pages);
    lockdep_assert_held(&pool_lock);
    if (!record || record->cache_bucket != state->state.slot ||
        record->cache_anchor != state->state.generation || !bytes || bytes > U64_MAX - 63 ||
        record->bytes != ((bytes + 63u) & ~(u64)63u) ||
        (void *)(base + record->offset) != address ||
        (record->deferred != LSF_PREPAID_PRIVATE && record->deferred != LSF_PREPAID_PUBLISHED))
        return 0;
    if (record->deferred == LSF_PREPAID_PUBLISHED &&
        !lsf_device_queue(&factory.pool, state->owner, ticket, kind))
        return 0;
    return lsf_device_finish(&factory.pool, state->owner, ticket, kind);
}

static int lsf_stream_rx_retire_views_locked(void)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_context *owner;
    struct lsf_prepaid_ticket state_ticket;
    struct lsf_prepaid_key key;
    unsigned int i;
    lockdep_assert_held(&factory_lock);
    lockdep_assert_held(&pool_lock);
    state = lsf_stream_rx_current_locked();
    if (!lsf_factory_selected_consumer() || !state || !state->stopped || !state->hardware_stopped ||
        state->device_borrows || state->poisoned || factory.pool.poisoned || READ_ONCE(factory.uncertain))
        return 0;
    /* Both net arrays passed actual NAPI delete+synchronize_net; all ring
     * tuples passed actual reset/IRQ and descriptor return. Their records are
     * still retained immutable birth metadata, not followed object pointers. */
    for (i = 0; i < 10; ++i) {
        struct lsf_prepaid_ticket ticket = state->queue_ticket[i];
        struct lsf_prepaid_view *record;
        if (!ticket.slot || ticket.slot >= LSF_ALLOCATION_SLOTS ||
            state->queue_claimed[i] != 2) return 0;
        record = &factory.pool.records[ticket.slot];
        if (record->phase != LSF_PREPAID_RETURNED || record->generation != ticket.generation ||
            record->owner != state->owner.slot || record->owner_generation != state->owner.generation ||
            record->cache_bucket != state->state.slot || record->cache_anchor != state->state.generation)
            return 0;
    }
    for (i = 0; i < LSF_STREAM_RX_DESCRIPTORS; ++i)
        if (state->heads[i].posted || !state->heads[i].data_returned || state->headers[i].borrowed)
            return 0;
    key = state->owner; state_ticket = state->state;
    owner = lsf_device_context(&factory.pool, key);
    if (!owner) return 0;
    for (i = 0; i < LSF_STREAM_RX_DESCRIPTORS; ++i) {
        if (!lsf_stream_rx_finish_loan_view_locked(state, state->heads[i].ticket,
                LSF_DEVICE_RX_HEAD, state->heads[i].address, state->geometry.rx_head_bytes) ||
            !lsf_stream_rx_finish_loan_view_locked(state, state->headers[i].ticket,
                LSF_DEVICE_RX_HEADER, state->headers[i].address, state->geometry.rx_header_bytes))
            goto uncertain;
    }
    /* All descendants returned before their SAME original state extent. */
    if (!lsf_device_finish(&factory.pool, key, state_ticket, LSF_DEVICE_QUEUE))
        goto uncertain;
    lsf_stream_rx = NULL; // No state payload access after its view return.
    return 1; // Views only; original Root, bank pages and actor refs stay paid.
uncertain:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    return 0;
}
