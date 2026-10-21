/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in authenticated sidtab.c. Actual original cache lock, parent,
 * policy RCU and LRU limits remain authoritative. No copied layout. */
#if CONFIG_SECURITY_SELINUX_SID2STR_CACHE_SIZE > 0
static void lsf_prepaid_sidcache_callback(struct rcu_head *head)
{
    struct sidtab_str_cache *cache = container_of(head, struct sidtab_str_cache, rcu_member);
    struct lsf_factory_blob birth;
    if (lsf_factory_blob_lookup(cache, LSF_PREPAID_SIDCACHE, &birth) == 1)
        lsf_factory_blob_finish(birth, LSF_PREPAID_SIDCACHE);
    else
        lsf_factory_poison(NULL);
    /* No cache/head access after the original view has returned. */
}

/* Marking QUEUED happens under the original cache lock before unlink. The
 * real callback is requested after unlink/unlock. Never put arena storage
 * through kfree_rcu, including when ownership validation failed. */
static void lsf_prepaid_sidcache_retire(struct sidtab_str_cache *cache, int owned)
{
    if (!cache)
        return;
    if (owned == 1)
        call_rcu(&cache->rcu_member, lsf_prepaid_sidcache_callback);
    else if (owned == 0)
        kfree_rcu(cache, rcu_member);
}

static bool lsf_prepaid_sidcache_destroy(struct sidtab_str_cache *cache)
{
    return lsf_factory_sidcache_destroy(cache) != 0;
}

void lsf_prepaid_sidcache_detach(struct sidtab *table,
    struct lsf_factory_context *context, struct lsf_prepaid_ticket ticket)
{
    struct sidtab_str_cache *cache;
    unsigned long flags;
    void *address;
    int owned = -1;
    spin_lock_irqsave(&table->cache_lock, flags);
    if (lsf_factory_sidcache_current(context, ticket,
            (lsf_u64)(unsigned long)table, &address)) {
        cache = address;
        if (table->cache_free_slots >= CONFIG_SECURITY_SELINUX_SID2STR_CACHE_SIZE ||
            rcu_dereference_protected(cache->parent->cache,
                lockdep_is_held(&table->cache_lock)) != cache) {
            lsf_factory_poison(context);
        } else {
            owned = lsf_factory_sidcache_queue(cache);
            if (owned == 1) {
                list_del(&cache->lru_member);
                rcu_assign_pointer(cache->parent->cache, NULL);
                table->cache_free_slots++;
            }
        }
    }
    spin_unlock_irqrestore(&table->cache_lock, flags);
    if (owned == 1)
        lsf_prepaid_sidcache_retire(cache, owned);
}
#else
void lsf_prepaid_sidcache_detach(struct sidtab *table,
    struct lsf_factory_context *context, struct lsf_prepaid_ticket ticket)
{
    (void)table;
    (void)ticket;
    lsf_factory_poison(context);
}
#endif
