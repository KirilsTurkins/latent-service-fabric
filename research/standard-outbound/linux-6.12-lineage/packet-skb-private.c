/* SPDX-License-Identifier: GPL-2.0-only */
/* Included in the authenticated skbuff.c after its original private helpers.
 * Only protected-factory packet births use this LINEAR constructor. Original
 * dataref/users, socket delivery, cloning and destructor ordering remain real. */
static int lsf_prepaid_packet_return(const void *address, unsigned int kind)
{
    struct lsf_factory_blob birth;
    int owned = lsf_factory_packet_birth(address, kind, &birth);
    if (owned == 1 && !lsf_factory_blob_finish(birth, kind))
        return -1;
    return owned;
}

static void *lsf_prepaid_packet_head(struct lsf_factory_blob source,
                                   unsigned int *size)
{
    unsigned int allocated;
    void *data;
    if (!size || *size > LSF_TCP_BYTES)
        return NULL;
    allocated = SKB_HEAD_ALIGN(*size);
    if (allocated < *size || allocated > LSF_TCP_BYTES)
        return NULL;
    data = lsf_factory_child_allocate(source, allocated, LSF_PREPAID_PACKET_HEAD);
    if (data)
        *size = allocated;
    return data;
}

struct sk_buff *lsf_prepaid_packet_skb_new(struct lsf_factory_blob source,
                                        unsigned int size)
{
    struct sk_buff *skb;
    void *data;
    if (SMP_CACHE_BYTES > 64 || __alignof__(struct sk_buff) > 64 ||
        __alignof__(struct skb_shared_info) > 64)
        return NULL;
    skb = lsf_factory_child_allocate(source, sizeof(*skb), LSF_PREPAID_PACKET_SKB);
    if (!skb)
        return NULL;
    data = lsf_prepaid_packet_head(source, &size);
    if (!data) {
        lsf_prepaid_packet_return(skb, LSF_PREPAID_PACKET_SKB);
        return NULL;
    }
    /* Match the maintained __alloc_skb initialization and real shared-info
     * geometry. sizeof/offsets come from this selected kernel translation
     * unit, never a freestanding reference's serialized type definitions. */
    memset(skb, 0, offsetof(struct sk_buff, tail));
    __build_skb_around(skb, data, size);
    skb->pfmemalloc = false;
    return skb;
}

/* Source callers already hold a real Linux sock reference/lock. Validate the
 * exact noncopy birth attached by the protected constructor BEFORE allocating
 * a packet. This is not a pointer adoption or a userspace factory entry. */
struct sk_buff *lsf_prepaid_packet_alloc_sock(struct sock *sk, unsigned int size)
{
    struct lsf_factory_blob parent;
    struct lsf_prepaid_ticket ticket;
    if (!sk || !sk->sk_lsf_factory)
        return NULL;
    ticket = (struct lsf_prepaid_ticket){sk->sk_lsf_view_slot,
                                        sk->sk_lsf_view_generation};
    if (!lsf_factory_protocol_parent(sk, sk->sk_lsf_factory, ticket, &parent))
        return NULL;
    return lsf_prepaid_packet_skb_new(parent, size);
}

bool lsf_prepaid_packet_linear(const struct sk_buff *skb,
                                     struct lsf_factory_blob source)
{
    struct lsf_factory_blob head_birth;
    unsigned long head = (unsigned long)skb->head;
    unsigned long data = (unsigned long)skb->data;
    unsigned long tail;
#ifdef NET_SKBUFF_DATA_USES_OFFSET
    tail = skb->tail;
#else
    if ((unsigned long)skb->tail < head) {
        lsf_factory_poison(source.context);
        return false;
    }
    tail = (unsigned long)skb->tail - head;
#endif
    /* This bounded packet constructor supplies no fragments or zero-copy references.
     * An unexpected modified shape fails closed before any new allocation. */
    if (skb->fclone != SKB_FCLONE_UNAVAILABLE || skb->head_frag || skb->data_len ||
        data < head || data - head > skb_end_offset(skb) ||
        tail > skb_end_offset(skb) || tail < data - head ||
        skb->len != tail - (data - head) ||
        skb_end_offset(skb) > LSF_TCP_BYTES ||
        skb_end_offset(skb) % SKB_DATA_ALIGN(1) ||
        lsf_factory_packet_head_current(skb->head,
            (unsigned long)skb_end_offset(skb) + SKB_DATA_ALIGN(sizeof(struct skb_shared_info)),
            &head_birth) != 1 || head_birth.context != source.context ||
        skb_shinfo(skb)->nr_frags || skb_shinfo(skb)->frag_list ||
        /* Maintained skb_zcopy only reads flags/uarg but takes a mutable
         * pointer. Keep the copy caller's const contract and original getter. */
        skb_zcopy((struct sk_buff *)skb)) {
        lsf_factory_poison(source.context);
        return false;
    }
    return true;
}

/* The queue caller owns both real objects. A protected socket may not adopt
 * an outside, stale or another context's packet while collapsing its receive
 * queue. Establish original membership BEFORE inspecting any packet shape. */
bool lsf_prepaid_packet_for_sock(const struct sk_buff *skb, struct sock *sk)
{
    struct lsf_factory_blob parent, source;
    struct lsf_prepaid_ticket ticket;
    if (!sk || !sk->sk_lsf_factory)
        return false;
    ticket = (struct lsf_prepaid_ticket){sk->sk_lsf_view_slot,
                                        sk->sk_lsf_view_generation};
    if (!lsf_factory_protocol_parent(sk, sk->sk_lsf_factory, ticket, &parent))
        return false;
    if (lsf_factory_packet_birth(skb, LSF_PREPAID_PACKET_SKB, &source) != 1 ||
        source.context != parent.context) {
        lsf_factory_poison(parent.context);
        return false;
    }
    return lsf_prepaid_packet_linear(skb, source);
}

static struct sk_buff *lsf_prepaid_packet_clone(struct sk_buff *skb,
                                             struct lsf_factory_blob source)
{
    struct sk_buff *copy;
    if (!lsf_prepaid_packet_linear(skb, source))
        return NULL;
    copy = lsf_factory_child_allocate(source, sizeof(*copy), LSF_PREPAID_PACKET_SKB);
    if (!copy)
        return NULL;
    copy->fclone = SKB_FCLONE_UNAVAILABLE;
    /* Original __skb_clone copies the actual header, takes the real dataref,
     * and leaves socket ownership/destructor detached, exactly as upstream. */
    return __skb_clone(copy, skb);
}

static int lsf_prepaid_packet_expand(struct sk_buff *skb, int nhead, int ntail,
                                   struct lsf_factory_blob source)
{
    unsigned int osize = skb_end_offset(skb), size;
    long requested = (long)osize + nhead + ntail;
    long off;
    u8 *data;
    if (nhead < 0 || skb_shared(skb) || requested < 0 ||
        requested > (long)LSF_TCP_BYTES || !lsf_prepaid_packet_linear(skb, source) ||
        requested < (long)(skb_tail_pointer(skb) - skb->head) + nhead ||
        skb_tail_pointer(skb) < skb->head ||
        (unsigned long)(skb_tail_pointer(skb) - skb->head) > osize) {
        lsf_factory_poison(source.context);
        return -EOPNOTSUPP;
    }
    size = (unsigned int)requested;
    data = lsf_prepaid_packet_head(source, &size);
    if (!data)
        return -ENOMEM;
    size = SKB_WITH_OVERHEAD(size);
    /* Preserve the maintained expansion's actual header/shared-info copy and
     * last-dataref release. Cloned siblings keep the old head charged. */
    memcpy(data + nhead, skb->head, skb_tail_pointer(skb) - skb->head);
    memcpy((struct skb_shared_info *)(data + size), skb_shinfo(skb),
           offsetof(struct skb_shared_info, frags[0]));
    if (skb_cloned(skb))
        skb_release_data(skb, SKB_CONSUMED);
    else
        skb_free_head(skb);
    off = (data + nhead) - skb->head;
    skb->head = data;
    skb->head_frag = 0;
    skb->data += off;
    skb_set_end_offset(skb, size);
#ifdef NET_SKBUFF_DATA_USES_OFFSET
    off = nhead;
#endif
    skb->tail += off;
    skb_headers_offset_update(skb, nhead);
    skb->cloned = 0;
    skb->hdr_len = 0;
    skb->nohdr = 0;
    atomic_set(&skb_shinfo(skb)->dataref, 1);
    skb_metadata_clear(skb);
    if (!skb->sk || skb->destructor == sock_edemux)
        skb->truesize += size - osize;
    return 0;
}
