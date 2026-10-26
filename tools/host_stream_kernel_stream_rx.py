"""Unselected exact-source queue integration for the continuously paid bank.

This projection chooses geometry BEFORE vring allocation and supplies separate
normal stop/Root/observation paths. It never selects a consumer, completes an
ancestor plan or mints qualification. Full typed constructor/material closure,
compiled fit, physical DMA/dataref/Root return and normal installation remain
required gates; this source cannot enable the provider.
"""
import hashlib

from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_device_security import function
from tools.host_stream_kernel_cleanup_native import OWNED, require


PREIMAGES = {
    'drivers/virtio/virtio_pci_common.c': (21355,
        '4a4d4c097c63faf4182d34d1fa30feb24a0b3a550d346df0474d58f5ece267f3'),
    'net/core/skbuff.c': (189334,
        '6a2fec31182c7c4d247d85aaffba036de9c0b6a9911c3cc1249d00b423ea0ae8'),
    'drivers/virtio/virtio_ring.c': (85364, 'daf818da379b3af96e8f633a5914e410d7f5035fd9b6227aac88f42bb4f2ec93'),
    'drivers/net/virtio_net.c': (186457, '0dbf1a236ae7a0d0d6571c0af4aff825d3faa491d51d7abef1c9df9d7a704e17'),
    'drivers/virtio/virtio_pci_modern.c': (21148,
        'ee9d80730580f2f6ca7fd4dae2c0195d007ed876a3a9e835e81151db3d0a5ec6'),
}
HEADER = 'include/net/lsf_stream_ring_profile_private.h'
MATERIAL_HEADER = 'include/net/lsf_stream_material_geometry_private.h'
MATERIAL_PINS = {'stream-material-geometry-private.h': '272a9e2f310d87aee62b1b8046730604660deb04afe07237e8b81d7011336710', 'stream-net-material-geometry.c': 'daaf16fb5a052f48b992aaa3ef135b0f8bbbb4723bc63a18760b875e6b985010', 'stream-pci-material-geometry.c': '6e1b2777a456bcd315863cbbf5a2931eecff1bbb24b393084ae398544c2ff39e'}


def _owned(name):
    raw = (OWNED/name).read_bytes()
    require(0 < len(raw) <= 48*1024 and b'\r' not in raw,
        'stream-rx-owned-source-bound')
    return raw.decode()


def _source(name, raw):
    size, digest = PREIMAGES[name]
    require(type(raw) is bytes and len(raw) == size
        and hashlib.sha256(raw).hexdigest() == digest,
        'stream-rx-pinned-source-preimage')
    return Editor(raw.decode())


def _material_owned(name):
    raw = _owned(name).encode()
    require(hashlib.sha256(raw).hexdigest() == MATERIAL_PINS[name],
        'stream-rx-fixed-material-geometry-source')
    return raw.decode()


def pci_common(raw):
    editor = _source('drivers/virtio/virtio_pci_common.c', raw)
    original = editor.text
    editor.edit(original, original+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'+
        _material_owned('stream-pci-material-geometry.c')+'#endif\n')
    return editor.finish().encode()


def modern(raw):
    editor = _source('drivers/virtio/virtio_pci_modern.c', raw)
    editor.edit('#include <linux/delay.h>\n',
        '#include <linux/delay.h>\n#include <net/lsf_stream_ring_profile_private.h>\n')
    # Keep the actual hardware maximum separate from the finite allocation
    # count. Original num_max and every ordinary/unselected path stay original.
    editor.edit('\tbool is_avq;\n\tu16 num;\n',
        '\tbool is_avq;\n\tint stream_num;\n\tu16 num, maximum;\n')
    editor.edit('\tinfo->msix_vector = msix_vec;\n\n\t/* create the vring */\n',
        '\tmaximum = num;\n'
        '\tstream_num = lsf_factory_stream_queue_count(mdev->pci_dev, &vp_dev->vdev, index, num);\n'
        '\tif (stream_num < 0)\n\t\treturn ERR_PTR(stream_num);\n'
        '\tif (stream_num)\n\t\tnum = stream_num;\n\n'
        '\tinfo->msix_vector = msix_vec;\n\n\t/* create the vring */\n')
    old = '''\tvq = vring_create_virtqueue(index, num,
\t\t\t\t    SMP_CACHE_BYTES, &vp_dev->vdev,
\t\t\t\t    true, true, ctx,
\t\t\t\t    notify, callback, name);
'''
    editor.edit(old, '''\tif (stream_num)
\t\tvq = lsf_prepaid_stream_ring_create(index, num,
\t\t\tSMP_CACHE_BYTES, &vp_dev->vdev, true, ctx, notify, callback, name);
\telse {
'''+old+'''\t}
''')
    editor.edit('\tvq->num_max = num;\n', '\tvq->num_max = maximum;\n')
    return editor.finish().encode()


def ring(raw):
    editor = _source('drivers/virtio/virtio_ring.c', raw)
    editor.edit('#include <linux/virtio.h>\n',
        '#include <linux/virtio.h>\n#include <net/lsf_stream_ring_profile_private.h>\n')
    editor.edit('''\tint err, err_reset;

\tif (num > vq->vq.num_max)
''', '''\tint err, err_reset;

\t/* Private fixed geometry cannot enter ambient allocate-before-free resize.
\t * Negative ownership is unknown/private and must retain, never fall back. */
\tif (lsf_factory_stream_ring_owned(vq, sizeof(*vq)))
\t\treturn -EOPNOTSUPP;
\tif (num > vq->vq.num_max)
''')
    editor.edit('''\tvring_free(_vq);

\tkfree(vq);
''', '''\t/* The original transport must already have supplied actual reset/IRQ
\t * fences. Unknown private retirement retains the original paid extent. */
\tif (lsf_prepaid_stream_ring_release(_vq))
\t\treturn;
\tvring_free(_vq);

\tkfree(vq);
''')
    # Include after ALL original private definitions and functions. Public
    # prototypes above serve the earlier callsites. Reverse the complete edit,
    # not just a list of selected snippets, to prove the original remainder.
    old = editor.text
    editor.edit(old, old+'\n'+_owned('stream-ring-geometry.c')+'\n'+_owned('stream-owned-ring.c'))
    return editor.finish().encode()


def network(raw):
    editor = _source('drivers/net/virtio_net.c', raw)
    editor.edit('#include <linux/netdevice.h>\n',
        '#include <linux/netdevice.h>\n#include <net/lsf_stream_ring_profile_private.h>\n')
    # The real net arrays are constructed before setup_vq. Bind their actual
    # born PCI/virtio records and take the complete prepaid pair atomically.
    old_alloc = function(editor.text, 'static int virtnet_alloc_queues(')
    alloc = Editor(old_alloc)
    alloc.edit('''\tint i;

\tif (vi->has_cvq) {
''', '''\tint i, stream_owned;
\tstruct lsf_stream_net_views stream_views;

\tstream_owned = lsf_factory_stream_net_queues(vi->vdev, vi->max_queue_pairs,
\t\tvi->has_cvq, vi->big_packets, vi->mergeable_rx_bufs,
\t\tsizeof(*vi->rq), sizeof(*vi->sq), &stream_views);
\tif (stream_owned < 0)
\t\treturn stream_owned;
\tif (!stream_owned) {
\tif (vi->has_cvq) {
''')
    alloc.edit('''\tif (!vi->rq)
\t\tgoto err_rq;

\tINIT_DELAYED_WORK''', '''\tif (!vi->rq)
\t\tgoto err_rq;
\t} else {
\t\tvi->ctrl = NULL;
\t\tvi->rq = stream_views.rx;
\t\tvi->sq = stream_views.tx;
\t}

\tINIT_DELAYED_WORK''')
    # No fallible initialization/goto follows the private tuple; original
    # err_rq/err_sq allocations and free labels remain outside its path.
    editor.edit(old_alloc, alloc.finish())
    editor.edit('''\tkfree(vi->rq);
\tkfree(vi->sq);
\tkfree(vi->ctrl);
''', '''\tif (!lsf_factory_stream_net_queues_return(vi->vdev, vi->rq, vi->sq)) {
\t\tkfree(vi->rq);
\t\tkfree(vi->sq);
\t}
\tkfree(vi->ctrl);
''')
    old_small = function(editor.text, 'static int add_recvbuf_small(')
    small = Editor(old_small)
    small.edit('''\tif (unlikely(!skb_page_frag_refill(len, &rq->alloc_frag, gfp)))
\t\treturn -ENOMEM;

\tbuf = virtnet_rq_alloc(rq, len, gfp);
\tif (unlikely(!buf))
\t\treturn -ENOMEM;
''', '''\t/* Continuous paid head, BEFORE either original page allocation. */
\terr = lsf_factory_stream_rx_take(rq->vq->vdev, len, (void **)&buf);
\tif (err < 0)
\t\treturn err;
\tif (err) {
\t\tif (xdp_headroom || rq->do_dma) {
\t\t\tlsf_factory_stream_rx_unposted(buf);
\t\t\treturn -EOPNOTSUPP;
\t\t}
\t} else {
\t\tif (unlikely(!skb_page_frag_refill(len, &rq->alloc_frag, gfp)))
\t\t\treturn -ENOMEM;

\t\tbuf = virtnet_rq_alloc(rq, len, gfp);
\t\tif (unlikely(!buf))
\t\t\treturn -ENOMEM;
\t}
''')
    small.edit('''\terr = virtqueue_add_inbuf_ctx(rq->vq, rq->sg, 1, buf, ctx, gfp);
\tif (err < 0) {
\t\tif (rq->do_dma)
\t\t\tvirtnet_rq_unmap(rq, buf, 0);
\t\tput_page(virt_to_head_page(buf));
''', '''\terr = virtqueue_add_inbuf_ctx(rq->vq, rq->sg, 1, buf, ctx, gfp);
\tif (err < 0) {
\t\tif (rq->do_dma)
\t\t\tvirtnet_rq_unmap(rq, buf, 0);
\t\tif (!lsf_factory_stream_rx_unposted(buf - VIRTNET_RX_PAD - xdp_headroom))
\t\t\tput_page(virt_to_head_page(buf));
''')
    editor.edit(old_small, small.finish())
    editor.edit('''static void virtnet_rq_free_buf(struct virtnet_info *vi,
\t\t\t\tstruct receive_queue *rq, void *buf)
{
''', '''static void virtnet_rq_free_buf(struct virtnet_info *vi,
\t\t\t\tstruct receive_queue *rq, void *buf)
{
\tif (!vi->mergeable_rx_bufs && !vi->big_packets &&
\t    lsf_factory_stream_rx_unposted(buf - VIRTNET_RX_PAD))
\t\treturn;
''')
    # This exact block is the normal small-buffer error tail, after the NIC
    # returned its descriptor and before any successful skb dataref transfer.
    editor.edit('''err:
\tu64_stats_inc(&stats->drops);
\tput_page(page);
\treturn NULL;
}

static struct sk_buff *receive_big''', '''err:
\tu64_stats_inc(&stats->drops);
\tif (!lsf_factory_stream_rx_unposted(buf))
\t\tput_page(page);
\treturn NULL;
}

static struct sk_buff *receive_big''')
    old = editor.text
    editor.edit(old, old+'\n'+_owned('stream-net-geometry.c')+
        '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'+
        _material_owned('stream-net-material-geometry.c')+'#endif\n')
    return editor.finish().encode()


def skb(raw):
    editor = _source('net/core/skbuff.c', raw)
    editor.edit('#include <linux/module.h>\n',
        '#include <linux/module.h>\n#include <net/lsf_stream_ring_profile_private.h>\n')
    # Keep original initialization and shared_info/dataref setup, using the
    # original paid header instead of introducing a slab/page allocation.
    for signature, allocator in (
        ('struct sk_buff *__build_skb(void *data, unsigned int frag_size)',
         '\tskb = kmem_cache_alloc(net_hotdata.skbuff_cache,\n\t\t\t       GFP_ATOMIC | __GFP_NOWARN);\n'),
        ('static struct sk_buff *__napi_build_skb(void *data, unsigned int frag_size)',
         '\tskb = napi_skb_cache_get();\n'),
    ):
        old = signature+'\n{\n\tstruct sk_buff *skb;\n\n'+allocator
        new = signature+'''\n{
\tstruct sk_buff *skb;
\tint stream_owned = lsf_factory_stream_rx_header(data, frag_size, &skb);

\tif (stream_owned < 0)
\t\treturn NULL;
\tif (!stream_owned) {
'''+allocator+'\t}\n'
        editor.edit(old, new)
    # Original physical old-head disposal: last shared dataref OR original
    # noncloned head relocation. Preserve all three original caller guards;
    # no destructor or temporary header ref substitutes for this real edge.
    editor.edit('''static void skb_free_head(struct sk_buff *skb)
{
\tunsigned char *head = skb->head;
''', '''static void skb_free_head(struct sk_buff *skb)
{
\tunsigned char *head = skb->head;
\tif (lsf_factory_stream_rx_data_return(head))
\t\treturn;
''')
    editor.edit('''static void kfree_skbmem(struct sk_buff *skb)
{
\tstruct sk_buff_fclones *fclones;
''', '''static void kfree_skbmem(struct sk_buff *skb)
{
\tstruct sk_buff_fclones *fclones;
\tif (lsf_factory_stream_rx_header_return(skb))
\t\treturn;
''')
    editor.edit('''\tskb_release_all(skb, reason);
\tsa->skb_array[sa->skb_count++] = skb;
''', '''\tskb_release_all(skb, reason);
\tif (lsf_factory_stream_rx_header_return(skb))
\t\treturn;
\tsa->skb_array[sa->skb_count++] = skb;
''')
    editor.edit('''\tstruct napi_alloc_cache *nc = this_cpu_ptr(&napi_alloc_cache);
\tu32 i;

\tif (!kasan_mempool_poison_object(skb))
''', '''\tstruct napi_alloc_cache *nc = this_cpu_ptr(&napi_alloc_cache);
\tu32 i;

\tif (lsf_factory_stream_rx_header_return(skb))
\t\treturn;
\tif (!kasan_mempool_poison_object(skb))
''')
    return editor.finish().encode()


def transform(outputs, sources):
    require(type(outputs) is dict and type(sources) is dict
        and set(sources) == set(PREIMAGES) and HEADER not in outputs
        and MATERIAL_HEADER not in outputs,
        'stream-rx-fixed-source-inputs')
    result = dict(outputs)
    require(not set(PREIMAGES).intersection(result), 'stream-rx-fresh-driver-stage')
    require('net/factory.c' in outputs and 'net/device-prepaid.h' in outputs,
        'stream-rx-original-factory-and-device-header-required')
    editor = Editor(outputs['net/factory.c'].decode())
    editor.edit('#include "factory-cleanup-late-fd-final-free.c"\n',
        'static int lsf_stream_root_pending_locked(void);\n'
        'static int lsf_stream_root_release_take_locked(struct lsf_cleanup_root_release *);\n'
        'static void lsf_stream_root_release_dispatch(struct lsf_cleanup_root_release);\n'
        '#include "factory-cleanup-late-fd-final-free.c"\n')
    editor.edit('#include "factory-stream-operations.c"\n',
        '#include "factory-stream-rx-preallocate.c"\n#include "factory-stream-operations.c"\n'
        '#include "factory-stream-stop.c"\n'
        '#include "factory-stream-retirement.c"\n'
        '#include "factory-stream-root-final-free.c"\n')
    # Original observation/constructor path is byte-equivalent when unselected.
    # Normal stop must establish actual hardware ACK BEFORE destroying the
    # already paid cleanup worker. Failed/unknown stop quarantines all owners.
    editor.edit('    lsf_prepaid_cleanup_worker_destroy_full();\n',
        '    if (lsf_factory_stream_stop())\n        return 0;\n'
        '    lsf_prepaid_cleanup_worker_destroy_full();\n')
    editor.edit('        (void)lsf_cleanup_root_release_take_locked(&release);\n',
        '        (void)(lsf_factory_selected_consumer() ?\n'
        '            lsf_stream_root_release_take_locked(&release) :\n'
        '            lsf_cleanup_root_release_take_locked(&release));\n')
    editor.edit('    lsf_cleanup_root_release_physical(release);\n',
        '    lsf_stream_root_release_dispatch(release);\n')
    editor.edit('    .unlocked_ioctl = lsf_factory_retirement_ioctl,\n',
        '    .unlocked_ioctl = lsf_factory_stream_ioctl,\n')
    result['net/factory.c'] = editor.finish().encode()
    # Keep the historical constructor's one-shot quarantine branch EXACT.
    # Normal tails consume one real-return notice and wait for another actual
    # return rather than poisoning a legitimate retained packet or spinning.
    editor = Editor(outputs['net/factory-cleanup-late-fd-final-free.c'].decode())
    editor.edit('    return factory.opened == 2u && factory.pages && factory.device &&\n',
        '    if (lsf_factory_selected_consumer())\n'
        '        return lsf_stream_root_pending_locked();\n'
        '    return factory.opened == 2u && factory.pages && factory.device &&\n')
    editor.edit('    if (pending && !lsf_cleanup_root_release_take_locked(&release)) {\n',
        '    if (pending && lsf_factory_selected_consumer()) {\n'
        '        (void)lsf_stream_root_release_take_locked(&release);\n'
        '    } else if (pending && !lsf_cleanup_root_release_take_locked(&release)) {\n')
    editor.edit('    lsf_cleanup_root_release_physical(release);\n',
        '    lsf_stream_root_release_dispatch(release);\n')
    editor.edit('    if (physically_taken)\n',
        '    if (physically_taken && !lsf_factory_selected_consumer())\n')
    result['net/factory-cleanup-late-fd-final-free.c'] = editor.finish().encode()

    # Add only the reviewed aligned allocation function to the actual derived
    # header. Never replace its original security/kind/retirement additions.
    header = _owned('device-prepaid.h')
    begin = header.index('/* Separate selected normal-stream allocator.')
    end = header.index('/* These transitions', begin)
    addition = header[begin:end]
    require(addition.count('lsf_device_allocate_stream_aligned(') == 1,
        'stream-rx-single-aligned-allocation-helper')
    editor = Editor(outputs['net/device-prepaid.h'].decode())
    require('lsf_device_allocate_stream_aligned(' not in editor.text,
        'stream-rx-fresh-aligned-header')
    anchor = '/* These transitions are used at the actual publication/unlink/callback sites.'
    editor.edit(anchor, addition+anchor)
    # Fixed private normal-collector hooks; no callback registration or caller
    # certificate. Both actual allocators seal new births only at final take.
    editor.edit('#include "prepaid.h"\n', '#include "prepaid.h"\n'
        'void lsf_factory_stream_root_notify_locked(struct lsf_prepaid *);\n'
        'int lsf_factory_stream_allocation_open_locked(struct lsf_prepaid *);\n')
    for allocator in ('lsf_device_allocate', 'lsf_device_allocate_stream_aligned'):
        old = function(editor.text, 'static inline int '+allocator+'(')
        body = Editor(old)
        body.edit('    if (!context || !ticket || !offset ||',
            '    if (!lsf_factory_stream_allocation_open_locked(pool) ||\n'
            '        !context || !ticket || !offset ||')
        editor.edit(old, body.finish())
    old = function(editor.text, 'static inline int lsf_device_finish(')
    body = Editor(old)
    body.edit('    context->live--;\n',
        '    context->live--;\n    lsf_factory_stream_root_notify_locked(pool);\n')
    editor.edit(old, body.finish())
    result['net/device-prepaid.h'] = editor.finish().encode()
    result['net/factory-stream-rx-preallocate.c'] = _owned('factory-stream-rx-preallocate.c').encode()
    material = _owned('factory-stream-material-plan.c').encode()
    require(len(material) == 15157 and hashlib.sha256(material).hexdigest() ==
        '0c07408ef6251454fb2bece1c91602abc0ce1ffcaba2c07268a371ab2188a1df',
        'stream-rx-fixed-material-core')
    result['net/factory-stream-material-plan.c'] = material
    result['net/factory-stream-stop.c'] = _owned('factory-stream-stop.c').encode()
    result['net/factory-stream-root-final-free.c'] = _owned('factory-stream-root-final-free.c').encode()
    result['net/factory-stream-retirement.c'] = _owned('factory-stream-retirement.c').encode()
    result[HEADER] = _owned('stream-ring-profile-private.h').encode()
    result[MATERIAL_HEADER] = _material_owned('stream-material-geometry-private.h').encode()
    for name, project in (
        ('net/core/skbuff.c', skb),
        ('drivers/virtio/virtio_ring.c', ring),
        ('drivers/net/virtio_net.c', network),
        ('drivers/virtio/virtio_pci_modern.c', modern),
        ('drivers/virtio/virtio_pci_common.c', pci_common),
    ):
        result[name] = project(sources[name])
    return result
