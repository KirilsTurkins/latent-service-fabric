/* SPDX-License-Identifier: GPL-2.0-only */
/* WIP real skbuff.c consumer. This is a separate NodeFixed source domain, not
 * the audit/application context. Original dataref/users, socket destructors,
 * delivery queues and last-head release determine its actual retirement. */
static void *lsf_prepaid_device_uevent_head(struct lsf_device_registration_source source,
    unsigned int *size)
{
    unsigned int allocated;
    void *data;
    if (!size || *size > LSF_DEVICE_UEVENT_MAX_HEAD_BYTES)
        return NULL;
    allocated = SKB_HEAD_ALIGN(*size);
    if (allocated < *size || allocated > LSF_DEVICE_UEVENT_MAX_HEAD_BYTES)
        return NULL;
    data = lsf_factory_device_uevent_allocate(source, allocated, LSF_DEVICE_UEVENT_KIND_HEAD);
    if (data)
        *size = allocated;
    return data;
}

struct sk_buff *lsf_prepaid_device_uevent_skb_new(struct lsf_device_registration_source source,
    unsigned int size)
{
    struct sk_buff *skb;
    void *data;
    if (SMP_CACHE_BYTES > 64 || __alignof__(struct sk_buff) > 64 ||
        __alignof__(struct skb_shared_info) > 64)
        return NULL;
    skb = lsf_factory_device_uevent_allocate(source, sizeof(*skb), LSF_DEVICE_UEVENT_KIND_SKB);
    if (!skb)
        return NULL;
    data = lsf_prepaid_device_uevent_head(source, &size);
    if (!data) {
        (void)lsf_factory_device_uevent_return(skb, LSF_DEVICE_UEVENT_KIND_SKB);
        return NULL;
    }
    memset(skb, 0, offsetof(struct sk_buff, tail));
    __build_skb_around(skb, data, size);
    skb->pfmemalloc = false;
    return skb;
}

static bool lsf_prepaid_device_uevent_linear(const struct sk_buff *skb,
    struct lsf_device_registration_source source)
{
    struct lsf_device_registration_source head_birth;
    unsigned long head, data, tail;
    if (source.kind != LSF_DEVICE_UEVENT_KIND_SKB || source.address != skb ||
        lsf_factory_device_uevent_current(source) != 1)
        goto invalid;
    head = (unsigned long)skb->head;
    data = (unsigned long)skb->data;
#ifdef NET_SKBUFF_DATA_USES_OFFSET
    tail = skb->tail;
#else
    if ((unsigned long)skb->tail < head)
        goto invalid;
    tail = (unsigned long)skb->tail - head;
#endif
    if (skb->fclone != SKB_FCLONE_UNAVAILABLE || skb->head_frag || skb->data_len ||
        data < head || data - head > skb_end_offset(skb) ||
        tail > skb_end_offset(skb) || tail < data - head ||
        skb->len != tail - (data - head) || skb_end_offset(skb) > LSF_DEVICE_UEVENT_MAX_HEAD_BYTES ||
        skb_end_offset(skb) % SKB_DATA_ALIGN(1) ||
        lsf_factory_device_uevent_head_current(skb->head,
            (unsigned long)skb_end_offset(skb) + SKB_DATA_ALIGN(sizeof(struct skb_shared_info)),
            &head_birth) != 1 || head_birth.pci_slot != source.pci_slot ||
        head_birth.pci_generation != source.pci_generation ||
        skb_shinfo(skb)->nr_frags || skb_shinfo(skb)->frag_list ||
        skb_zcopy((struct sk_buff *)skb))
        goto invalid;
    return true;
invalid:
    /* Invalid shape never reaches a normal allocator or reads shared-info
     * beyond its original head. Retain/quarantine the original backing. */
    lsf_factory_device_uevent_poison();
    return false;
}

static struct sk_buff *lsf_prepaid_device_uevent_clone(struct sk_buff *skb,
    struct lsf_device_registration_source source)
{
    struct sk_buff *copy;
    if (!lsf_prepaid_device_uevent_linear(skb, source))
        return NULL;
    copy = lsf_factory_device_uevent_allocate(source, sizeof(*copy), LSF_DEVICE_UEVENT_KIND_SKB);
    if (!copy)
        return NULL;
    copy->fclone = SKB_FCLONE_UNAVAILABLE;
    return __skb_clone(copy, skb);
}

static int lsf_prepaid_device_uevent_expand(struct sk_buff *skb, int nhead, int ntail,
    struct lsf_device_registration_source source)
{
    unsigned int osize, size;
    long requested, off;
    u8 *data;
    if (!lsf_prepaid_device_uevent_linear(skb, source))
        return -EOPNOTSUPP;
    osize = skb_end_offset(skb);
    requested = (long)osize + nhead + ntail;
    if (nhead < 0 || skb_shared(skb) || requested < 0 || requested > (long)LSF_DEVICE_UEVENT_MAX_HEAD_BYTES ||
        requested < (long)(skb_tail_pointer(skb) - skb->head) + nhead ||
        skb_tail_pointer(skb) < skb->head ||
        (unsigned long)(skb_tail_pointer(skb) - skb->head) > osize) {
        lsf_factory_device_uevent_poison();
        return -EOPNOTSUPP;
    }
    size = (unsigned int)requested;
    data = lsf_prepaid_device_uevent_head(source, &size);
    if (!data)
        return -ENOMEM;
    size = SKB_WITH_OVERHEAD(size);
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
