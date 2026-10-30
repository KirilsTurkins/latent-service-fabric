/* SPDX-License-Identifier: GPL-2.0-only */
/* Already-retired constructor-only Root. No production selection or native refund. */
/* Include after factory-cleanup-native-bootstrap.c and before .release. */
struct lsf_cleanup_root_release {
    struct page *pages;
    struct mm_struct *mm;
    struct pid *tgid;
    const struct cred *cred;
    struct net *net;
};

/* Exact original noncompound order-7 alloc_pages owner. No source path lends
 * page references: actual stack mapping/unmapping does not transfer the bank
 * owner. All Task/stack/PTE users must already have physically retired.
 * Mirror the pinned allocator's bad-page rejection predicates BEFORE its
 * head put: __free_pages on a retained noncompound head could free only tails.
 * The actual page_pool helper is already declared by linux/mm.h. */
static int lsf_cleanup_root_pages_locked(void)
{
    unsigned int i;
    for (i = 0; i < (1u << LSF_BACKING_ORDER); ++i) {
        struct page *page = factory.pages + i;
        if (PageCompound(page) || PageHWPoison(page) ||
            page_ref_count(page) != (i == 0) || atomic_read(&page->_mapcount) != -1 ||
            page->mapping || page_pool_page_is_pp(page) ||
            (page->flags & PAGE_FLAGS_CHECK_AT_FREE)
#ifdef CONFIG_MEMCG
            || page->memcg_data
#endif
            )
            return 0;
    }
    return 1;
}

/* Exact no-application-birth constructor profile. A completed old application
 * birth is deliberately refused too; zero current live owners is insufficient. */
static int lsf_cleanup_root_no_application_locked(void)
{
    unsigned int i, word;
    if (factory.last_lease || factory.reply_pending || factory.inflight ||
        factory.reply.lease || factory.reply.handle)
        return 0;
    for (i = 0; i < LSF_FACTORY_CONTEXTS; ++i)
        if (factory.contexts[i].key.slot || factory.contexts[i].key.generation ||
            factory.contexts[i].socket || factory.contexts[i].net || factory.contexts[i].lease)
            return 0;
    for (i = 0; i < LSF_OWNER_SLOTS; ++i) {
        struct lsf_prepaid_context *context = &factory.pool.contexts[i];
        if (i == LSF_DEVICE_OWNER_SLOT)
            continue;
        if (context->generation || context->cursor || context->live ||
            context->continuations || context->poisoned ||
            context->closed != (i < LSF_FACTORY_CONTEXTS))
            return 0;
        for (word = 0; word < 8; ++word)
            if (context->scope.identity[word])
                return 0;
    }
    return 1;
}

/* Existing static record identities remain valid after their own return.
 * Never follow the former Task, Request or six provider part addresses. */
static int lsf_cleanup_root_records_locked(struct lsf_cleanup_task_source source)
{
    struct lsf_prepaid_view *record, *part, *ancestor;
    struct lsf_prepaid_ticket parent;
    unsigned int i, which, depth, seen = 0;
    record = &factory.pool.records[0];
    if (record->phase != LSF_PREPAID_LIVE || record->bytes != LSF_BACKING_BYTES ||
        record->generation || record->owner_generation || record->offset || record->owner ||
        record->kind || record->deferred || record->cache_bucket || record->cache_anchor ||
        record->security_cache_location || record->security_cache_identity)
        return 0;
    part = lsf_cleanup_provider_held_record_locked(source, source.request,
        LSF_DEVICE_CLEANUP_REQUEST, source.root);
    if (!part || part->phase != LSF_PREPAID_RETURNED)
        return 0;
    part = lsf_cleanup_provider_held_record_locked(source, source.task,
        LSF_DEVICE_CLEANUP_TASK, source.request);
    if (!part || part->phase != LSF_PREPAID_RETURNED)
        return 0;
    for (i = 1; i < LSF_ALLOCATION_SLOTS; ++i) {
        record = &factory.pool.records[i];
        if (i == source.root.slot)
            continue;
        if (record->phase == LSF_PREPAID_EMPTY) {
            if (record->generation || record->owner_generation || record->offset ||
                record->bytes || record->owner || record->kind || record->deferred ||
                record->cache_bucket || record->cache_anchor ||
                record->security_cache_location || record->security_cache_identity)
                return 0;
            continue;
        }
        if (record->phase != LSF_PREPAID_RETURNED || record->kind == LSF_DEVICE_ROOT ||
            (record->deferred != LSF_PREPAID_PRIVATE && record->deferred != LSF_PREPAID_QUEUED) ||
            record->owner != source.owner.slot || record->owner_generation != source.owner.generation ||
            !lsf_device_kind(record->kind) ||
            !lsf_cleanup_provider_held_record_locked(source,
                (struct lsf_prepaid_ticket){i, record->generation}, record->kind,
                (struct lsf_prepaid_ticket){record->cache_bucket, record->cache_anchor}))
            return 0;
        /* The held helper checks complete range and owner but its parent
         * argument alone is not independent ancestry authentication. Follow
         * the original immutable scalar birth chain, at most256steps, to the
         * exact Root. Original generations strictly increase at every birth. */
        ancestor = record;
        for (depth = 0; depth < LSF_ALLOCATION_SLOTS; ++depth) {
            unsigned int slot = ancestor->cache_bucket;
            lsf_u64 generation = ancestor->cache_anchor;
            if (!slot || slot >= LSF_ALLOCATION_SLOTS || !generation ||
                generation >= ancestor->generation)
                return 0;
            ancestor = &factory.pool.records[slot];
            if (ancestor->generation != generation ||
                ancestor->owner != source.owner.slot ||
                ancestor->owner_generation != source.owner.generation)
                return 0;
            if (slot == source.root.slot) {
                if (generation != source.root.generation || ancestor->kind != LSF_DEVICE_ROOT ||
                    ancestor->phase != LSF_PREPAID_LIVE)
                    return 0;
                break;
            }
            if (ancestor->phase != LSF_PREPAID_RETURNED ||
                !lsf_device_kind(ancestor->kind) || ancestor->kind == LSF_DEVICE_ROOT)
                return 0;
        }
        if (depth == LSF_ALLOCATION_SLOTS)
            return 0;
        if (record->kind < LSF_DEVICE_CLEANUP_PROVIDER_POOL ||
            record->kind > LSF_DEVICE_CLEANUP_PROVIDER_CONTEXT)
            continue;
        which = record->kind - LSF_DEVICE_CLEANUP_PROVIDER_POOL;
        if ((which == LSF_PROVIDER_POOL &&
             (i != factory.device->cleanup_provider_pool.slot ||
              record->generation != factory.device->cleanup_provider_pool.generation)) ||
            (which == LSF_PROVIDER_WORKER &&
             (i != factory.device->cleanup_provider_worker.slot ||
              record->generation != factory.device->cleanup_provider_worker.generation)))
            return 0;
        parent = (which == LSF_PROVIDER_WORKER || which == LSF_PROVIDER_PWQ ||
            which == LSF_PROVIDER_ATTRS) ? factory.device->cleanup_provider_pool : source.root;
        if ((seen & (1u << which)) || record->cache_bucket != parent.slot ||
            record->cache_anchor != parent.generation)
            return 0;
        seen |= 1u << which;
    }
    return seen == (1u << LSF_PROVIDER_PARTS) - 1u;
}

/* Called once by actual final FD .release after its existing close and cache
 * scans; factory_lock held. Not-ready/uncertain graphs remain quarantined.
 * All successful private Tasks/children/Request/Control already returned.
 * This admits no wait, reopen, late callback collector or production socket. */
static int lsf_cleanup_root_release_take_locked(struct file *file,
    struct lsf_cleanup_root_release *release)
{
    struct lsf_cleanup_task_source source;
    struct lsf_prepaid_context *owner;
    struct lsf_prepaid_view *root;
    unsigned long flags, base;
    unsigned int word;
    int result = 0;
    lockdep_assert_held(&factory_lock);
    *release = (struct lsf_cleanup_root_release){0};
    spin_lock_irqsave(&pool_lock, flags);
    if (file->private_data != &factory || !lsf_factory_constructor_qualification() ||
        lsf_factory_selected_consumer() || !factory.opened || !factory.pages || !factory.device ||
        file->f_cred != factory.cred ||
        !factory.mm || !factory.tgid || !factory.cred || !factory.net ||
        READ_ONCE(factory.uncertain) || factory.pool.poisoned || !factory.pool.initialized ||
        !factory.pool.stopped || !factory.cleanup_observer_prebirth ||
        lsf_device_uevent_taps.private_alive != 1 || lsf_device_uevent_taps.taps ||
        lsf_device_uevent_taps.poisoned || !lsf_cleanup_root_no_application_locked())
        goto out;
    source = (struct lsf_cleanup_task_source){factory.device->key, factory.device->root,
        factory.device->cleanup_request, factory.device->cleanup_task};
    if (source.owner.slot != LSF_DEVICE_OWNER_SLOT || !source.owner.generation ||
        factory.device->bootstrap_state != LSF_FACTORY_BOOTSTRAP_CLOSED ||
        factory.device->bootstrap_busy || factory.device->bootstrap_error ||
        factory.device->pci_attempted || factory.device->firmware.slot ||
        factory.device->firmware.generation || factory.device->constructor_active ||
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
        !factory.device->cleanup_provider_pool_destructed)
        goto out;
    owner = lsf_device_context(&factory.pool, source.owner);
    root = lsf_device_record(&factory.pool, source.owner, source.root, LSF_DEVICE_ROOT);
    base = (unsigned long)page_address(factory.pages);
    if (!owner || owner->closed != 1u || owner->live != 1u || owner->continuations ||
        !root || root->deferred != LSF_PREPAID_PUBLISHED || root->bytes < sizeof(*factory.device) ||
        factory.device != (void *)(base + root->offset) || root->cache_bucket || root->cache_anchor ||
        root->security_cache_location || root->security_cache_identity ||
        !lsf_cleanup_root_records_locked(source) || !lsf_cleanup_root_pages_locked() ||
        !lsf_prepaid_cleanup_irq_closed(source, base))
        goto out;
    for (word = 0; word < 8; ++word)
        if (owner->scope.identity[word])
            goto out;
    /* Exact actual Control finish entails original restoration, registration
     * unlink, seal/readers0 and actual handoff/barrier flush. All ten internal
     * raw views have caller lifetimes that precede these returned records.
     * Helper tails recheck factory.device under this same pool_lock. */
    if (!lsf_device_queue(&factory.pool, source.owner, source.root, LSF_DEVICE_ROOT) ||
        !lsf_device_finish(&factory.pool, source.owner, source.root, LSF_DEVICE_ROOT) ||
        !lsf_prepaid_cleanup_irq_release(source, base)) {
        factory.pool.poisoned = 1;
        WRITE_ONCE(factory.uncertain, 1);
        goto out; /* No post-finish Root payload access on failure. */
    }
    /* LAST bank payload access preceded Root finish. Scalar static handles
     * alone cross unpublication; opened/initialized/generations remain sticky. */
    *release = (struct lsf_cleanup_root_release){factory.pages, factory.mm,
        factory.tgid, factory.cred, factory.net};
    factory.device = NULL;
    factory.pages = NULL;
    factory.mm = NULL;
    factory.tgid = NULL;
    factory.cred = NULL;
    factory.net = NULL;
    file->private_data = NULL;
    result = 1;
out:
    spin_unlock_irqrestore(&pool_lock, flags);
    return result;
}

/* Run only after factory_lock unlock. No bank/global pointer is followed. */
static void lsf_cleanup_root_release_physical(struct lsf_cleanup_root_release release)
{
    unsigned long flags;
    if (!release.pages)
        return;
    __free_pages(release.pages, LSF_BACKING_ORDER); /* Original order-7 owner. */
    spin_lock_irqsave(&pool_lock, flags);
    factory.pool.records[0].phase = LSF_PREPAID_RETURNED; /* AFTER actual page return. */
    spin_unlock_irqrestore(&pool_lock, flags);
    put_net(release.net);
    put_cred(release.cred);
    put_pid(release.tgid);
    mmdrop(release.mm);
    /* Only the isolated constructor selects this path. This kernel observation
     * follows actual page return and original actor puts, with no bank access,
     * caller-supplied fields, native quota refund or release certificate. */
    pr_info("LSFVM1 physical-return=constructor-root-bank-and-actor-refs\n");
}
