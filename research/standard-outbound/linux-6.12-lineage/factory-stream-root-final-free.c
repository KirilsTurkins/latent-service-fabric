/* SPDX-License-Identifier: GPL-2.0-only */
/* Separate NORMAL Root collector. Historical constructor predicates/mint/wire
 * remain byte-exact. No consumer selection or native refund is introduced.
 * All scalar state lives in the SAME prepaid RX/Root objects. */
#include <linux/rcupdate.h>

static int lsf_stream_root_pending_locked(void)
{
    struct lsf_stream_rx_state *state;
    lockdep_assert_held(&pool_lock);
    if (!lsf_factory_selected_consumer() || factory.opened != 2u ||
        !factory.device || factory.device->cleanup_request_returned != 1u)
        return 0;
    state = lsf_stream_rx_current_locked();
    return state && state->closing && state->hardware_stopped &&
        state->collect_notice && !state->collecting;
}

/* Permit only the already counted continuous RX/state LIVE views. Every
 * unrelated device/security/provider ancestor must have ACTUALLY returned.
 * This uses exact ticket+generation, never kind or address similarity alone. */
static int lsf_stream_root_rx_live_locked(struct lsf_stream_rx_state *state,
    unsigned int slot, const struct lsf_prepaid_view *record)
{
    struct lsf_prepaid_ticket ticket = {0};
    unsigned int i, kind = 0;
    if (slot == state->state.slot && record->generation == state->state.generation) {
        ticket = state->state; kind = LSF_DEVICE_QUEUE;
        if (record->cache_bucket != state->root.slot ||
            record->cache_anchor != state->root.generation) return 0;
    } else {
        for (i = 0; i < LSF_STREAM_RX_DESCRIPTORS; ++i) {
            if (slot == state->heads[i].ticket.slot &&
                record->generation == state->heads[i].ticket.generation) {
                ticket = state->heads[i].ticket; kind = LSF_DEVICE_RX_HEAD; break;
            }
            if (slot == state->headers[i].ticket.slot &&
                record->generation == state->headers[i].ticket.generation) {
                ticket = state->headers[i].ticket; kind = LSF_DEVICE_RX_HEADER; break;
            }
        }
        if (!ticket.slot || record->cache_bucket != state->state.slot ||
            record->cache_anchor != state->state.generation) return 0;
    }
    return lsf_device_record(&factory.pool, state->owner, ticket, kind) == record &&
        (record->deferred == LSF_PREPAID_PRIVATE || record->deferred == LSF_PREPAID_PUBLISHED);
}

static int lsf_stream_root_records_ready_locked(struct lsf_stream_rx_state *state)
{
    struct lsf_prepaid_view *record, *ancestor;
    unsigned int i, depth;
    record = &factory.pool.records[0];
    if (record->phase != LSF_PREPAID_LIVE || record->bytes != LSF_BACKING_BYTES ||
        record->generation || record->owner_generation || record->offset || record->owner ||
        record->kind || record->deferred || record->cache_bucket || record->cache_anchor ||
        record->security_cache_location || record->security_cache_identity)
        return 0;
    for (i = 0; i < LSF_STREAM_RX_DESCRIPTORS; ++i)
        if (state->heads[i].posted || !state->heads[i].data_returned || state->headers[i].borrowed)
            return 0;
    for (i = 0; i < 10; ++i)
        if (state->queue_claimed[i] != 2) return 0;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (i == state->root.slot) continue;
        if (record->phase == LSF_PREPAID_EMPTY) {
            if (record->generation || record->owner_generation || record->offset ||
                record->bytes || record->owner || record->kind || record->deferred ||
                record->cache_bucket || record->cache_anchor ||
                record->security_cache_location || record->security_cache_identity) return 0;
            continue;
        }
        if (record->owner != state->owner.slot || record->owner_generation != state->owner.generation ||
            !record->generation || !record->bytes || record->kind == LSF_DEVICE_ROOT ||
            !lsf_device_kind(record->kind) || record->offset < LSF_FACTORY_INFRA_OFFSET ||
            record->offset - LSF_FACTORY_INFRA_OFFSET > LSF_FACTORY_INFRA_BYTES ||
            record->bytes > LSF_FACTORY_INFRA_BYTES - (record->offset - LSF_FACTORY_INFRA_OFFSET) ||
            (record->phase != LSF_PREPAID_RETURNED &&
                !lsf_stream_root_rx_live_locked(state, i, record))) return 0;
        /* Immutable birth ancestry only. No returned object payload is read. */
        ancestor = record;
        for (depth = 0; depth < LSF_ALLOCATION_SLOTS; ++depth) {
            unsigned int parent = ancestor->cache_bucket;
            u64 generation = ancestor->cache_anchor;
            if (!parent || parent >= LSF_ALLOCATION_SLOTS || !generation ||
                generation >= ancestor->generation) return 0;
            ancestor = &factory.pool.records[parent];
            if (ancestor->generation != generation || ancestor->owner != state->owner.slot ||
                ancestor->owner_generation != state->owner.generation) return 0;
            if (parent == state->root.slot) {
                if (generation != state->root.generation || ancestor->kind != LSF_DEVICE_ROOT ||
                    ancestor->phase != LSF_PREPAID_LIVE) return 0;
                break;
            }
            if (ancestor->phase != LSF_PREPAID_RETURNED &&
                !lsf_stream_root_rx_live_locked(state, parent, ancestor)) return 0;
        }
        if (depth == LSF_ALLOCATION_SLOTS) return 0;
    }
    return 1;
}

static int lsf_stream_root_closed_locked(struct lsf_stream_rx_state *state)
{
    struct lsf_prepaid_context *owner;
    struct lsf_prepaid_view *root;
    unsigned int word;
    if (!lsf_factory_selected_consumer() || !state || !state->closing ||
        !state->hardware_stopped || !state->stopped || state->device_borrows ||
        state->poisoned || factory.pool.poisoned || READ_ONCE(factory.uncertain) ||
        factory.opened != 2u || !factory.pages || !factory.device ||
        !factory.mm || !factory.tgid || !factory.cred || !factory.net ||
        !factory.pool.initialized || !factory.pool.stopped || !factory.cleanup_observer_prebirth ||
        !lsf_stream_contexts_retired_locked() ||
        state->geometry.computed != LSF_STREAM_GEOMETRY_ALL ||
        factory.device->bootstrap_state != LSF_FACTORY_BOOTSTRAP_CLOSED ||
        factory.device->bootstrap_busy || factory.device->bootstrap_error ||
        factory.device->pci_attempted != 1u || factory.device->constructor_active ||
        factory.device->cleanup_operation_active ||
        factory.device->cleanup_physical_role != LSF_CLEANUP_PHYSICAL_PROVIDER ||
        factory.device->cleanup_lifecycle != LSF_CLEANUP_TASK_RETURNED ||
        factory.device->cleanup_final_phase != LSF_CLEANUP_FINAL_RETURNED ||
        factory.device->cleanup_request_users || factory.device->cleanup_task_claimed != 2u ||
        factory.device->cleanup_request_returned != 1u ||
        factory.device->cleanup_worker_associated != 1u || factory.device->cleanup_worker_stop != 2u ||
        factory.device->cleanup_provider_control_retiring != 1u ||
        factory.device->cleanup_provider_control_readers ||
        !factory.device->cleanup_provider_close_requested ||
        !factory.device->cleanup_provider_pool_destructed ||
        lsf_device_uevent_taps.private_alive != 1 || lsf_device_uevent_taps.taps ||
        lsf_device_uevent_taps.poisoned) return 0;
    owner = lsf_device_context(&factory.pool, state->owner);
    root = lsf_device_record(&factory.pool, state->owner, state->root, LSF_DEVICE_ROOT);
    if (!owner || owner->closed != 1u || owner->continuations || !root ||
        root->deferred != LSF_PREPAID_PUBLISHED || root->bytes < sizeof(*factory.device) ||
        (void *)factory.device != (char *)page_address(factory.pages) + root->offset ||
        root->cache_bucket || root->cache_anchor || root->security_cache_location ||
        root->security_cache_identity || factory.device->key.slot != state->owner.slot ||
        factory.device->key.generation != state->owner.generation ||
        factory.device->root.slot != state->root.slot ||
        factory.device->root.generation != state->root.generation) return 0;
    for (word = 0; word < 8; ++word)
        if (owner->scope.identity[word]) return 0;
    return lsf_stream_root_records_ready_locked(state) &&
        lsf_prepaid_cleanup_irq_closed((struct lsf_cleanup_task_source){
            state->owner, state->root, factory.device->cleanup_request,
            factory.device->cleanup_task}, (unsigned long)page_address(factory.pages));
}

/* SAME factory mutex held on entry/return. It is released around the original
 * RCU callback barrier, while collecting + LIVE state/Root keep this bank paid.
 * Before that barrier, all other records are returned and future allocations
 * are sealed; rejected late birth poisons/retains, never silently refunds. */
static int lsf_stream_root_release_take_locked(struct lsf_cleanup_root_release *release)
{
    struct lsf_stream_rx_state *state;
    struct lsf_prepaid_context *owner;
    struct lsf_prepaid_key key;
    struct lsf_prepaid_ticket root;
    struct lsf_cleanup_task_source source;
    struct lsf_retirement_publication retirement;
    unsigned long flags, base;
    u64 generation;
    int result = 0;
    lockdep_assert_held(&factory_lock);
    *release = (struct lsf_cleanup_root_release){0};
    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    if (!state || state->collecting) goto out;
    state->collect_notice = 0;
    /* Every actual non-RX birth must have its original physical last-use
     * return. No future-row list, cursor snapshot or prediction replaces the
     * complete original record/parent/history checks below. */
    if (!lsf_stream_root_closed_locked(state)) goto out;
    state->collecting = state->finalizing = 1;
    generation = factory.pool.next_generation;
    spin_unlock_irqrestore(&pool_lock, flags);
    mutex_unlock(&factory_lock);
    rcu_barrier(); /* Actual queued/running callback tails, outside ALL locks. */
    mutex_lock(&factory_lock);
    spin_lock_irqsave(&pool_lock, flags);
    if (lsf_stream_rx_current_locked() != state || !state->collecting ||
        !state->finalizing || factory.pool.next_generation != generation ||
        !lsf_stream_root_closed_locked(state) || !lsf_cleanup_root_pages_locked()) goto poison;
    key = state->owner; root = state->root;
    source = (struct lsf_cleanup_task_source){key, root,
        factory.device->cleanup_request, factory.device->cleanup_task};
    base = (unsigned long)page_address(factory.pages);
    /* SAME original scalar identity, captured while Root payload is LIVE.
     * No observer is required for physical eligibility. Normal File ops are
     * immutable and emit a distinct magic; constructor LSFR is never rebound. */
    retirement = lsf_retirement_capture_locked(source, factory.device->bootstrap_expires_ns);
    *release = (struct lsf_cleanup_root_release){factory.pages, factory.mm,
        factory.tgid, factory.cred, factory.net, retirement};
    if (!lsf_stream_rx_retire_views_locked()) goto poison_release;
    /* lsf_stream_rx is unpublished. No state/PCI/vdev/returned payload read. */
    owner = lsf_device_context(&factory.pool, key);
    if (!owner || owner->live != 1 || owner->continuations ||
        !lsf_device_queue(&factory.pool, key, root, LSF_DEVICE_ROOT) ||
        !lsf_device_finish(&factory.pool, key, root, LSF_DEVICE_ROOT) ||
        !lsf_prepaid_cleanup_irq_release(source, base)) goto poison_release;
    factory.device = NULL;
    factory.pages = NULL;
    factory.mm = NULL; factory.tgid = NULL; factory.cred = NULL; factory.net = NULL;
    result = 1;
    goto out;
poison_release:
    *release = (struct lsf_cleanup_root_release){0};
poison:
    factory.pool.poisoned = 1;
    WRITE_ONCE(factory.uncertain, 1);
    /* Original backing/actor handles remain in factory; no put on failure. */
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

static void lsf_stream_root_release_dispatch(struct lsf_cleanup_root_release release)
{
    unsigned long flags;
    if (!lsf_factory_selected_consumer()) {
        lsf_cleanup_root_release_physical(release);
        return;
    }
    if (!release.pages) return;
    __free_pages(release.pages, LSF_BACKING_ORDER);
    spin_lock_irqsave(&pool_lock, flags);
    factory.pool.records[0].phase = LSF_PREPAID_RETURNED;
    spin_unlock_irqrestore(&pool_lock, flags);
    put_net(release.net); put_cred(release.cred); put_pid(release.tgid); mmdrop(release.mm);
    /* SAME scalar publication only AFTER actual original bank and all four
     * actor references physically returned. No Root pointer crosses this edge. */
    lsf_retirement_publish_after_physical(release.retirement);
}
