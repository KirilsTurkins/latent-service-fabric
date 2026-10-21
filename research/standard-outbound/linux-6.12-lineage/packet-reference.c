/* SPDX-License-Identifier: GPL-2.0-only */
/* Supplemental serialized SKB/lock/layout doubles only. The emitted private
 * packet helpers and maintained copy/clone/free bodies are exact source; this
 * is not Linux geometry, DMA, concurrency or kernel-final-free execution. */
#define LSF_AUDIT_SKB_REFERENCE_ENTRY packet_prior_audit_reference_main
#include "packet-audit-reference.c"

static void packet_observed(const char *label)
{
    assert(!cache_held && !pool_held && !read_held);
    lsf_ref_write("PACKET_CONTROL ", 15);
    lsf_ref_write(label, lsf_ref_length(label));
    lsf_ref_write(" PASS\n", 6);
}

int main(void)
{
    struct sk_buff *skb, *copy, *sibling;
    struct lsf_prepaid_context *owner;
    struct lsf_factory_blob birth;
    struct sock *sk;
    unsigned int before;
    void *old;
    (void)sibling; (void)birth; (void)sk; (void)before; (void)old;
    (void)packet_observed;
    (void)lsf_prepaid___pskb_copy_fclone;
    assert(packet_prior_audit_reference_main() == 0);
    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_packet_skb_new(parent, 1024);
    assert(skb && owner->live == 3 && !heap_count);
    skb_reserve(skb, 64); skb_put(skb, 4); memcpy(skb->data, "data", 4);
    copy = __pskb_copy_fclone(skb, 128, GFP_ATOMIC, false);
#ifdef LSF_OLD_PACKET_COPY
    assert(copy && owner->live == 3 && heap_count == 2);
    puts("PACKET_OLD actual-pskb-copy-escapes-original-owner RED");
    return 2;
#else
    assert(copy && owner->live == 5 && !heap_count && copy->head != skb->head);
    assert(copy->len == 4 && copy->data[0] == 'd' && copy->data[3] == 'a');
    packet_observed("actual-retransmit-copy-prepays-distinct-head-and-header");
    retire_skb(copy); retire_skb(skb); assert(owner->live == 1 && !heap_returns);
    packet_observed("copy-original-last-dataref-return-without-backing-refund");

    audit_reset(); owner = &factory.pool.contexts[0];
    /* The serialized constructor initializes the actual reserved object,
     * never a local pointer carrying copied birth fields. */
    sk = (struct sock *)(backing + factory.pool.records[parent.ticket.slot].offset);
    *sk = (struct sock){parent.context, parent.ticket.slot, parent.ticket.generation};
    skb = lsf_prepaid_packet_alloc_sock(sk, 1024);
    assert(skb && owner->live == 3 && !heap_count);
    packet_observed("socket-control-constructor-validates-original-parent-before-birth");
    assert(lsf_prepaid_packet_for_sock(skb, sk));
    packet_observed("receive-queue-input-has-same-original-socket-context");
    sk->sk_lsf_view_generation++;
    assert(!lsf_prepaid_packet_alloc_sock(sk, 64));
    assert(factory.pool.poisoned && owner->live == 3 && !heap_count);
    packet_observed("foreign-socket-generation-refuses-before-control-allocation");

    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_packet_skb_new(parent, 1024); assert(skb);
    struct lsf_factory_context *foreign = &factory.contexts[1];
    struct lsf_prepaid_ticket foreign_ticket;
    struct lsf_scope foreign_scope = {{1,2,3,4,5,6,7,9}};
    lsf_u64 foreign_offset;
    assert(lsf_prepaid_context_create(&factory.pool, foreign_scope, LSF_TCP_BYTES, &foreign->key));
    assert(lsf_prepaid_allocate(&factory.pool, foreign->key, 64, 0,
        (struct lsf_prepaid_ticket){0}, &foreign_ticket, &foreign_offset));
    sk = (struct sock *)(backing + foreign_offset);
    *sk = (struct sock){foreign, foreign_ticket.slot, foreign_ticket.generation};
    assert(!lsf_prepaid_packet_for_sock(skb, sk));
    assert(factory.pool.contexts[1].poisoned && owner->live == 3 &&
        factory.pool.contexts[1].live == 1 && !heap_count);
    packet_observed("foreign-receive-queue-cannot-adopt-another-original-packet");
    audit_reset(); owner = &factory.pool.contexts[0];
    sk = (struct sock *)(backing + factory.pool.records[parent.ticket.slot].offset);
    *sk = (struct sock){parent.context, parent.ticket.slot, parent.ticket.generation};
    skb = __alloc_skb(1024, GFP_ATOMIC, 0, NUMA_NO_NODE);
    assert(!lsf_prepaid_packet_for_sock(skb, sk));
    assert(owner->poisoned && owner->live == 1 && heap_count == 2);
    packet_observed("normal-receive-packet-cannot-be-retrospectively-charged-to-socket");

    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_packet_skb_new(parent, 1024); assert(skb);
    skb_put(skb, 4); memcpy(skb->data, "held", 4);
    sibling = skb_clone(skb, GFP_ATOMIC);
    assert(sibling && owner->live == 4 && skb_shinfo(skb)->dataref.count == 2);
    assert(lsf_factory_packet_birth(skb, LSF_PREPAID_PACKET_SKB, &birth) == 1);
    old = sibling->head;
    assert(pskb_expand_head(skb, 64, 128, GFP_ATOMIC) == 0);
    assert(skb->head != old && sibling->head == old && owner->live == 5);
    assert(skb->data[0] == 'h' && sibling->data[3] == 'd');
    assert(skb_shinfo(sibling)->dataref.count == 1);
    packet_observed("real-clone-and-expand-retain-old-head-through-last-sibling");
    owner->closed = 1; factory.pool.stopped = 1;
    assert(lsf_prepaid_return(&factory.pool, parent.context->key, parent.ticket));
    copy = skb_clone(skb, GFP_ATOMIC); assert(copy && owner->live == 5);
    retire_skb(sibling); retire_skb(skb); assert(owner->live == 2);
    assert(!lsf_prepaid_recycle(&factory.pool, parent.context->key));
    retire_skb(copy); assert(owner->live == 0);
    assert(lsf_prepaid_recycle(&factory.pool, parent.context->key));
    assert(factory.pool.records[0].phase == LSF_PREPAID_LIVE && !heap_returns);
    packet_observed("genuine-late-packet-clone-after-root-close-keeps-real-owners");

    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_packet_skb_new(parent, 1024); assert(skb);
    skb_reserve(skb, 64); skb_put(skb, 3); memcpy(skb->data, "abc", 3);
    copy = skb_copy_expand(skb, 128, 128, GFP_ATOMIC);
    assert(copy && copy->len == 3 && copy->data[2] == 'c' && owner->live == 5 && !heap_count);
    retire_skb(copy); retire_skb(skb); assert(owner->live == 1);
    packet_observed("actual-copy-expand-keeps-original-copy-and-header-offset-tail");

    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_packet_skb_new(parent, 1024); assert(skb);
    before = owner->live;
    assert(!__pskb_copy_fclone(skb, -1, GFP_ATOMIC, false));
    assert(!__pskb_copy_fclone(skb, 2147483647, GFP_ATOMIC, false));
    assert(!skb_copy_expand(skb, -1, 0, GFP_ATOMIC));
    assert(!skb_copy_expand(skb, 2147483647, 2147483647, GFP_ATOMIC));
    assert(owner->live == before && !owner->poisoned && !heap_count);
    packet_observed("negative-and-overlarge-copy-extents-refuse-before-allocation");
    owner->cursor = LSF_TCP_BYTES;
    old = skb->head;
    assert(!__pskb_copy_fclone(skb, 64, GFP_ATOMIC, false));
    assert(pskb_expand_head(skb, 0, 64, GFP_ATOMIC) == -ENOMEM);
    assert(skb->head == old && owner->live == before && !heap_count);
    packet_observed("unchanged-96k-copy-and-expansion-refusal-keeps-original-buffer");

    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_packet_skb_new(parent, 1024); assert(skb);
    skb->end = LSF_TCP_BYTES;
    assert(!__pskb_copy_fclone(skb, 64, GFP_ATOMIC, false));
    assert(owner->poisoned && owner->live == 3 && !heap_count);
    packet_observed("actual-copy-proves-complete-head-before-shared-info-read");
    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_packet_skb_new(parent, 1024); assert(skb);
    skb_shinfo(skb)->nr_frags = 1;
    assert(!skb_copy_expand(skb, 64, 64, GFP_ATOMIC));
    assert(owner->poisoned && owner->live == 3 && !heap_count);
    packet_observed("unclosed-fragment-copy-refuses-with-original-ownership-retained");

    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_packet_skb_new(parent, 1024); assert(skb);
    struct skb_free_array batch = {0};
    kfree_skb_add_bulk(skb, &batch, reason_consumed);
    assert(!batch.skb_count && owner->live == 1 && !heap_returns);
    packet_observed("packet-bulk-return-never-enters-normal-slab-array");
    audit_reset(); owner = &factory.pool.contexts[0];
    skb = lsf_prepaid_packet_skb_new(parent, 1024); assert(skb);
    skb_release_data(skb, SKB_CONSUMED); napi_reference_cache.skb_count = 0;
    napi_skb_cache_put(skb);
    assert(!napi_reference_cache.skb_count && owner->live == 1 && !heap_returns);
    packet_observed("packet-final-napi-return-routes-before-normal-cache");
    audit_reset(); owner = &factory.pool.contexts[0];
    skb = __alloc_skb(1024, GFP_ATOMIC, 0, NUMA_NO_NODE);
    skb_put(skb, 3); memcpy(skb->data, "old", 3);
    copy = __pskb_copy_fclone(skb, 64, GFP_ATOMIC, false);
    assert(copy && copy->len == 3 && copy->data[2] == 'd' && heap_count == 4);
    retire_skb(copy); retire_skb(skb);
    assert(heap_returns == 4 && owner->live == 1 && !owner->poisoned);
    packet_observed("ordinary-outside-arena-copy-retains-original-allocator-and-return");
    return 0;
#endif
}
