"""Finite source-owned NETDEV POST_INIT preflight; consumer remains unselected.

No callback is replaced or executed by this projector. All original bodies,
source declarations and inverses are exact; PM/direct-writer closure is pending.
"""
import hashlib
import json
from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_device_security import function
from tools.host_stream_kernel_cleanup_native import OWNED, require

HEADER = 'include/net/lsf_stream_netdev_post_init_private.h'
FRAGMENT = 'net/factory-stream-netdev-post-init.c'
INPUT_SHA = '8c34faa41636437aeeca9602af1dd63b1b251354a69b25c7c5745e63e20fb677'
PREIMAGES = {'net/core/dev.c': (332535, '911460f30f10458a729296fcd38eb312fda7b327c75f9516c268282f94756060'), 'drivers/net/virtio_net.c': (194543, '1e0187612413e38c6e839c80c6983d42c3d73924acfe7d725e64cd9cdef7d12b'), 'net/ipv4/fib_frontend.c': (40789, '054b45ed18db33e7f842e3565aa29fd21e171fff61debfe3b9dd2def46f55682'), 'net/factory.c': (36921, 'fe81f05f1ff597d4106f4238584327f268b98076c3ff2be844969bbe6db1a4d0')}
DEPENDENCIES = {'net/factory-stream-rx-preallocate.c': (46360, 'a99ff0e60a383fb607a2630ae5a642f2702c7a02ca4e94f5ca798496d50f571f'), 'net/factory-stream-material-arena.c': (3263, '8a78a41d72dd8771020108b6527ff4031292be21253d5b91f04907f6c22bed06'), 'net/factory-stream-netdev-address.c': (8477, 'fcf6eb3e568526364cd6a84d0f44a9317843c05b56bbcd7c111e4e5eda118400'), 'net/factory-stream-netdev-fixed.c': (16075, 'd8d0799c7330c729a79a5d6bb2a0487c52a11f962fee3e928e340a7906adffaf'), 'net/factory-stream-rss.c': (6520, 'a272bd5a0a4f6ce93a779d6af52bc30c44eeb08dcccf17e5bb4262dcb46f99b8'), 'net/factory-stream-netdev-core.c': (18545, '418bca3f30763011adc9a05619922674bb92dda6608177d08be7ce36700a04d8'), 'net/factory-device.c': (9857, '4d7eb3c02c00233ffa72492eb8b6836067a456dded260c34dbb30d5f52e1c31d'), 'net/device-prepaid.h': (18564, 'ed2bfd8132b42078d35cffb113b8ed59f7df639c47d0b575a6aea605f8233d2d'), 'net/prepaid.h': (30751, '2b1394dc1a7c7ec3f41ef0373ee0078995408471b08c24b57cbe543360e6214e'), 'include/linux/netdevice.h': (170928, 'a3aa5523a162de7cbb9a20dc376c1b190ba7cfc65b83d95f41279f5bf33f8416'), 'net/core/net-sysfs.c': (53929, 'c07ec343e23ca48e635207ba9624c8efd09bcc15c6fdca1f77d937f2628ce331')}
PRIMARY = {'net/ipv4/devinet.c': (71613, 'fb67c0c96ac132a0f401e0fd095e3be52100fc3561d98f3df1759414c4352281'), 'net/ipv6/addrconf.c': (191206, '7f2040aa1ce8a60f7801d3018d80b3a081917a2336fc64e0e07c4947b2b8d535'), 'net/core/rtnetlink.c': (172634, '7bd18cfc77168f195eaac481d43b6e28d73fe0fd0c2b4ade4e054126901f3c10'), 'drivers/virtio/virtio.c': (15716, 'ad70807209add0d0782c8e6c016f8b49d171656448dceb8dcf342a3c6858c57e')}
BODIES = {'net/core/dev.c::int register_netdevice(': (4858, 'aebb77f0c187a4a76590b1f778abf658a045557014157fce0e581bfae11bc39d'), 'net/core/dev.c::int register_netdevice_notifier(': (649, '49353a44ab521f0340c3a069e3ce87a147dad382f782c6b97d46dec923c2af2a'), 'net/core/dev.c::int unregister_netdevice_notifier(': (415, 'faeb92f02e756c1a71987725497812689ec01898be9611ee61b1cfd8e7d6ceef'), 'net/core/dev.c::static int __register_netdevice_notifier_net(': (476, '31de149f34108ac092cd7521d5c23401695ecf7706363a3c4ab15aa4bf200062'), 'net/core/dev.c::static int __unregister_netdevice_notifier_net(': (267, '88e8b81d85695c1edad6a8354d604adab51bcd6189d2e599b8b19b7afa79f030'), 'net/core/dev.c::int register_netdevice_notifier_net(': (196, '3ae780ccdd364aeb0485f9ea460dab7b152c55ad0ba1a8dbf9c6d278fa22c9ee'), 'net/core/dev.c::int unregister_netdevice_notifier_net(': (203, '11d1f32136e723a7613f76a8648ae8ba0850eaf10a03b742a363f06cbc5c2174'), 'net/core/dev.c::static void __move_netdevice_notifier_net(': (235, 'f6d0c1f2d4e4df379615f7ec51a6b9dc2a9419f47dd757ab2c281fe2387a9d2e'), 'net/core/dev.c::int register_netdevice_notifier_dev_net(': (337, 'cb060d3b697d343e5bb62244f08458dad16ce66ca84497200e4680e2183495db'), 'net/core/dev.c::int unregister_netdevice_notifier_dev_net(': (281, '3b03cb512f0f061b3cacbfb96777d40223d7e553754dc1e3c2c3059f045f00df'), 'net/core/dev.c::int call_netdevice_notifiers_info(': (541, '54995ba207121e4208e713d663d04fda7f27c4b1939d3240cedf019b5ca0dbec'), 'net/core/dev.c::int call_netdevice_notifiers(': (133, '60cbbf41f99e9585807bc4eefa74a0df911a526681756c787366c0101a590d27'), 'drivers/net/virtio_net.c::static int virtnet_probe(': (11636, '0c2f81d19220bc1b0c947581c5afb66787fcf61ffe3b509580e3218f0eaf14e9'), 'drivers/net/virtio_net.c::static void enable_rx_mode_work(': (125, '4de7576b2d74cd410d1bde0cd3417fa0e2333703a4be8cae4ac4e25de2e9b4f1'), 'net/ipv4/fib_frontend.c::static int fib_netdev_event(': (1487, 'c851f2e159f35e9ed609e9daa16614edc32947180b9f5850360d0d5989d066bf'), 'net/ipv4/devinet.c::static int inetdev_event(': (2256, 'e4fc34ceb6a1bf72241970b9a2644d5c29d7d2f99bcd363e1fabb6c834e24718'), 'net/ipv6/addrconf.c::static int addrconf_notify(': (4194, '163c924cf4964faf9d5f3162d0be9a515754f68f850e76e36730f900d66c60c7'), 'net/core/rtnetlink.c::static int rtnetlink_event(': (682, '6d72994a98d3b7f5de820113766d1cd6235060323528d7ab371b0042d629b1d5'), 'drivers/virtio/virtio.c::static int virtio_dev_probe(': (2265, '6cdb39ef3fbd4af64fc64d1e6be5a8f0b1c4a6d991efd32493c1f9dcb3f8e6c8'), 'drivers/virtio/virtio.c::int register_virtio_device(': (1251, 'eee85910214e7e2ae4febe5e0cd7af5b0f4f202bfcd21e34ba5fd64b96860753'), 'drivers/virtio/virtio.c::static void __virtio_config_changed(': (338, '6c568764742e66d767c5665e6af17225b7a8e6ed2aa2640dcd71fe78357b61da'), 'drivers/virtio/virtio.c::void virtio_config_changed(': (209, '54fe3e60e8a0f74140c65c33fb3d0111601315dd2433cdadd33d7c2c2c36a2c9'), 'drivers/virtio/virtio.c::static void virtio_config_core_enable(': (240, 'aa294cc0d1a56f31b9698a090f053525326afc2e2da16f018f9bfaf8fd6c530b'), 'drivers/virtio/virtio.c::static void virtio_config_core_disable(': (177, 'e32e0359403e450ac2f9daa929436aeb6482bc4fbbb3c33bc19f488a8146df17')}
DECLARATIONS = {'drivers/net/virtio_net.c::static const struct net_device_ops virtnet_netdev = {': (738, '52a90e08aa0c204e1960243ba62a230b6b489ab44b53b64a65bff34a1ab1ac63'), 'net/ipv4/fib_frontend.c::static struct notifier_block fib_netdev_notifier = {': (92, 'f83e05394d4623a3fb3b7d1e31d47a2e57b60435834b15795715abe8da255f67'), 'net/ipv4/devinet.c::static struct notifier_block ip_netdev_notifier = {': (88, '131cd0718bb7d8f7468c246cc67d4cfa2ce6082266f656ec8a067c2204d733c7'), 'net/ipv6/addrconf.c::static struct notifier_block ipv6_dev_notf = {': (124, '2d18d3e93f05d1f9f0cfc0e39bf609ef0cb8950b3c6cf2a018c9618455123f3e'), 'net/core/rtnetlink.c::static struct notifier_block rtnetlink_dev_notifier = {': (94, '019f7d6a19fa9ced715898ba21651d28534268276d82a34c15b192b1d17927aa')}
CALLBACKS = (('net/ipv4/devinet.c','ip_netdev_notifier','inetdev_event','0','ipv4'), ('net/ipv4/fib_frontend.c','fib_netdev_notifier','fib_netdev_event','0','fib4'), ('net/core/rtnetlink.c','rtnetlink_dev_notifier','rtnetlink_event','0','rtnl'), ('net/ipv6/addrconf.c','ipv6_dev_notf','addrconf_notify','ADDRCONF_NOTIFY_PRIORITY','ipv6'))


def _bound(raw, expected):
    return type(raw) is bytes and (len(raw),hashlib.sha256(raw).hexdigest())==expected


def _body(text, path, signature):
    require(text.count(signature)==1,'post-init-one-function-prefix')
    start=text.index(signature)
    require(start==0 or text[start-1]=='\n','post-init-full-function-prefix-line')
    raw=function(text,signature)
    require(_bound(raw.encode(),BODIES[path+'::'+signature]),'post-init-complete-declaration-body')
    return raw


def _declaration(text, path, prefix):
    require(text.count(prefix)==1,'post-init-complete-static-instance')
    start=text.index(prefix);end=text.find('\n};\n',start)
    require(start==0 or text[start-1]=='\n','post-init-full-instance-prefix-line')
    require(end>=start,'post-init-static-instance-end')
    raw=text[start:end+4]
    require(_bound(raw.encode(),DECLARATIONS[path+'::'+prefix]),'post-init-static-instance-pin')
    return raw


def _owned(name):
    raw=(OWNED/name).read_bytes()
    require(0<len(raw)<=32768 and b'\r' not in raw,'post-init-owned-source-bound')
    return raw


def _include(editor, anchor):
    editor.edit(anchor,anchor+'#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_netdev_post_init_private.h>\n#endif\n')


def _wrap(original, branch):
    start=original.index('\n{\n')
    return original[:start]+'\n{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'+branch+'#endif\n'+original[start+1:]+'}\n'


def _preflight_source():
    return '''
/* Registration/unregistration/move use the ORIGINAL RTNL. Both heads must be
 * accepted BEFORE either native chain runs; STOP_MASK/return handling below
 * remains entirely native. A known static instance is recognized BEFORE any
 * next/callback field dereference. Four actual instances, not a new task cap. */
static unsigned int lsf_stream_post_init_identity(const struct notifier_block *nb)
{
    if (lsf_prepaid_stream_post_init_ipv4(nb)) return 1u;
    if (lsf_prepaid_stream_post_init_fib4(nb)) return 2u;
    if (lsf_prepaid_stream_post_init_rtnl(nb)) return 4u;
    if (lsf_prepaid_stream_post_init_ipv6(nb)) return 8u;
    return 0;
}

static int lsf_stream_post_init_chains(struct net_device *dev)
{
    struct raw_notifier_head *heads[2] = { &dev_net(dev)->netdev_chain, &netdev_chain };
    struct notifier_block *nb;
    unsigned int chain, seen = 0, identity;
    ASSERT_RTNL();
    for (chain = 0; chain < ARRAY_SIZE(heads); ++chain) {
        nb = rcu_dereference_raw(heads[chain]->head);
        while (nb) {
            identity = lsf_stream_post_init_identity(nb);
            if (!identity || (seen & identity)) return 0;
            seen |= identity;
            nb = rcu_dereference_raw(nb->next);
        }
    }
    return 1;
}
'''


def _register(editor):
    path='net/core/dev.c';original=_body(editor.text,path,'int register_netdevice(')
    clone=original.replace('int register_netdevice(',
        'static int lsf_prepaid_stream_register_netdevice(',1)
    anchor='\tret = call_netdevice_notifiers(NETDEV_POST_INIT, dev);\n'
    require(clone.count(anchor)==1,'post-init-original-event-anchor')
    preflight='''    {
        struct virtio_device *same = NULL;
        /* Same actual constructor/physical parent is rechecked before the
         * source-bound chains. This lock observation is not a theorem about
         * concurrent PM/restore/direct native writers; those stay unqualified. */
        if (lsf_factory_stream_netdev_preinit(dev, &same) != 1 ||
            !lsf_prepaid_stream_post_init_virtnet_ops(dev) ||
            !lsf_prepaid_stream_post_init_virtio_quiet(same) ||
            !lsf_stream_post_init_chains(dev)) {
            ret = -EOPNOTSUPP;
            goto err_ifindex_release; /* No POST_INIT ran: no PRE_UNINIT. */
        }
    }
'''
    clone=clone.replace(anchor,preflight+anchor,1)
    inverse=clone.replace(preflight,'',1).replace('static int lsf_prepaid_stream_register_netdevice(',
        'int register_netdevice(',1)
    require(inverse==original,'post-init-clone-whole-inverse')
    branch='''    struct virtio_device *lsf_parent = NULL;
    int lsf_kind = lsf_factory_stream_netdev_preinit(dev, &lsf_parent);
    if (lsf_kind < 0) return lsf_kind;
    if (lsf_kind > 0) {
        /* Reject an unknown earlier ndo_init BEFORE it can execute. */
        if (!lsf_prepaid_stream_post_init_virtnet_ops(dev) ||
            !lsf_prepaid_stream_post_init_virtio_quiet(lsf_parent))
            return -EOPNOTSUPP;
        return lsf_prepaid_stream_register_netdevice(dev);
    }
'''
    selected='#ifdef CONFIG_LSF_STREAM_FACTORY\n'+_preflight_source()+clone+'#endif\n'
    editor.edit(original,selected+_wrap(original,branch))
    return original,clone


def _callback_source(block, callback, priority, name):
    return '''
#ifdef CONFIG_LSF_STREAM_FACTORY
int lsf_prepaid_stream_post_init_'''+name+'''(const struct notifier_block *nb)
{
    /* The actual static registration is authenticated before its fields.
     * Its complete original POST_INIT path has no retention/effects. */
    if (nb != &'''+block+''') return 0;
    return nb->notifier_call == '''+callback+''' && nb->priority == '''+priority+''';
}
#endif
'''


def transform(outputs, primary):
    require(type(outputs) is dict and len(outputs)==375 and
        all(type(n) is str and type(raw) is bytes for n,raw in outputs.items()),'post-init-frozen-map-shape')
    canonical=(json.dumps({n:{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        for n,raw in outputs.items()},sort_keys=True,separators=(',',':'))+'\n').encode()
    require(hashlib.sha256(canonical).hexdigest()==INPUT_SHA,'post-init-whole-375-notify-preimage')
    require(type(primary) is dict and set(primary)==set(PRIMARY),'post-init-closed-primary-inputs')
    for name,pin in {**PREIMAGES,**DEPENDENCIES}.items():
        require(name in outputs and _bound(outputs[name],pin),'post-init-whole-derived-preimage')
    for name,pin in PRIMARY.items():
        require(_bound(primary[name],pin),'post-init-whole-primary-preimage')
    require(HEADER not in outputs and FRAGMENT not in outputs,'post-init-fresh-owned-files')
    source={**outputs,**primary}
    for key in BODIES:
        path,signature=key.split('::',1);_body(source[path].decode(),path,signature)
    for key in DECLARATIONS:
        path,prefix=key.split('::',1);_declaration(source[path].decode(),path,prefix)
    result=dict(outputs)
    net=Editor(outputs['net/core/dev.c'].decode())
    _include(net,'#include <linux/netdevice.h>\n');_register(net)
    result['net/core/dev.c']=net.finish().encode()
    for path,block,callback,priority,name in CALLBACKS:
        editor=Editor(source[path].decode())
        _include(editor,'#include <linux/netdevice.h>\n')
        editor.edit(editor.text,editor.text+_callback_source(block,callback,priority,name))
        result[path]=editor.finish().encode()
    driver=Editor(outputs['drivers/net/virtio_net.c'].decode())
    _include(driver,'#include <linux/netdevice.h>\n')
    ops='''
#ifdef CONFIG_LSF_STREAM_FACTORY
int lsf_prepaid_stream_post_init_virtnet_ops(const struct net_device *dev)
{
    return dev->netdev_ops == &virtnet_netdev &&
        !virtnet_netdev.ndo_init && !virtnet_netdev.ndo_uninit;
}
#endif
'''
    driver.edit(driver.text,driver.text+ops)
    result['drivers/net/virtio_net.c']=driver.finish().encode()
    core=Editor(primary['drivers/virtio/virtio.c'].decode())
    _include(core,'#include <linux/virtio.h>\n')
    quiet='''
#ifdef CONFIG_LSF_STREAM_FACTORY
int lsf_prepaid_stream_post_init_virtio_quiet(struct virtio_device *dev)
{
    unsigned long flags;
    int quiet;
    /* Read only the real native lock-protected state. Do not clear a pending
     * change, disable callbacks, renew authority or claim PM/restore closure. */
    spin_lock_irqsave(&dev->config_lock, flags);
    quiet = !dev->config_core_enabled;
    spin_unlock_irqrestore(&dev->config_lock, flags);
    return quiet;
}
#endif
'''
    core.edit(core.text,core.text+quiet)
    result['drivers/virtio/virtio.c']=core.finish().encode()
    factory=Editor(outputs['net/factory.c'].decode())
    factory.edit('#include "factory-stream-netdev-notify.c"\n',
        '#include "factory-stream-netdev-notify.c"\n#include "factory-stream-netdev-post-init.c"\n')
    result['net/factory.c']=factory.finish().encode()
    result[HEADER]=_owned('stream-netdev-post-init-private.h')
    result[FRAGMENT]=_owned('factory-stream-netdev-post-init.c')
    require(len(result)==381 and b'lsf_factory_selected_consumer(void)\n{\n    return NULL;\n}' in
        result['net/factory-private.h'],'post-init-unselected-consumer')
    return result
