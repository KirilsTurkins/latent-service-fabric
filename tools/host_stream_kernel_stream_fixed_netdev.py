"""Unselected main/fixed NETDEV births and real deferred final-release custody.

Exact original constructor, device release and RCU order remain authoritative.
No source-completeness, compiled useful fit, kernel run or selection is claimed.
"""
import hashlib
from tools import host_stream_kernel_stream_cpu as cpu
from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_device_security import function
from tools.host_stream_kernel_cleanup_native import OWNED, require

DEV = 'net/core/dev.c'
ETH = 'net/ethernet/eth.c'
SYSFS = 'net/core/net-sysfs.c'
NET = 'drivers/net/virtio_net.c'
HEADER = 'include/net/lsf_stream_netdev_fixed_private.h'
GEOMETRY = 'include/net/lsf_stream_netdev_fixed_geometry_private.h'
PRIMARY = {
    ETH: (17068, '89d73fac160a9f75864b03ea8690b6f803ce5c257c882929f5341b2df2ef09c9'),
    SYSFS: (52728, '76ca487483c356850792c4fa96e79f9b03a7682fc4ef4a7213093b9655c2c283'),
}
PREVIOUS = {'net/core/dev.c': (325944, 'e4da89df5751ab1640ed90b60b2c53766b6402bfabb739122222c13f833eee43'), 'include/linux/netdevice.h': (170928, 'a3aa5523a162de7cbb9a20dc376c1b190ba7cfc65b83d95f41279f5bf33f8416'), 'drivers/net/virtio_net.c': (193802, 'fd336cd0e48d150cd4a6bcbf34b79017f036b7506fd1ee434e7ab3f30eeef6f7')}
PINS = {'static int netif_alloc_netdev_queues(': (441, '90272eaf2131b8215187ceb683c96f9a1778f774cba3eae8e87b0a1679e503de'), 'static int netif_alloc_rx_queues(': (669, 'c60aa4ef18fec9a266d6c53ca45f2c58e1d770a15839fd99fbabbeade1e1d244'), 'static void netif_free_tx_queues(': (80, '5ca615a66e45aa8adba4afa48765b64fef7fb3b5bb472605331861e781ff499f'), 'static void netif_free_rx_queues(': (299, 'f021f5c8efbc6caa0cef63c3ea63ef4486187041e4cb2d4c19d899718c42376b'), 'struct net_device *alloc_etherdev_mqs(': (199, 'bcc8c505c8c0f843b510aed2f139d514fc0dc33c99a24d4701aedfbb20368ed9'), 'static void netdev_release(': (281, '82bc7ff4705eda69116cc3875b1658b6b8f8c07412a3439c884a0d50e643620e'), 'static int virtnet_probe(': (10719, '5e1aedb2d004b0f0b3e59fa58e768ce53b143147b2e6daa38ffdb9372c017a6f')}
GEOMETRY_PINS = {
    'stream-netdev-fixed-geometry-private.h': 'c0f6b7a6f14dd517413aa38df8a311e6182716a07bc206ae34d204e655c670fe',
    'stream-netdev-fixed-geometry.c': '69076854e8150be58f4be3b77b4dced5092712447c906b0e524305cba3859452',
}


def _owned(name):
    raw = (OWNED/name).read_bytes()
    require(0 < len(raw) <= 32*1024 and b'\r' not in raw, 'stream-fixed-owned-source-bound')
    if name in GEOMETRY_PINS:
        require(hashlib.sha256(raw).hexdigest() == GEOMETRY_PINS[name], 'stream-fixed-root-geometry-pin')
    return raw


def _body(text, signature):
    raw = function(text, signature)
    size, digest = PINS[signature]
    require(len(raw.encode()) == size and hashlib.sha256(raw.encode()).hexdigest() == digest,
        'stream-fixed-original-body-pin')
    return raw


def _queue(original, direction):
    e = Editor(original)
    e.edit('netif_alloc_'+('netdev' if direction == 'tx' else 'rx')+'_queues(',
        'lsf_stream_netdev_alloc_'+direction+'_queues(')
    variable = 'tx' if direction == 'tx' else 'rx'
    selector = 'LSF_STREAM_NETDEV_TX' if direction == 'tx' else 'LSF_STREAM_NETDEV_RX'
    e.edit('\t'+variable+' = kvzalloc(sz, GFP_KERNEL_ACCOUNT | __GFP_RETRY_MAYFAIL);\n',
        '\t'+variable+' = lsf_factory_stream_netdev_fixed_allocate(dev, '+selector+', sz);\n')
    if direction == 'rx':
        e.edit('\tkvfree(dev->_rx);\n',
            '\t(void)lsf_factory_stream_netdev_fixed_return(dev, LSF_STREAM_NETDEV_RX);\n')
    return e.finish()


def _main(original):
    e = Editor(original)
    e.edit('struct net_device *alloc_netdev_mqs(int sizeof_priv, const char *name,',
        'struct net_device *lsf_prepaid_stream_alloc_netdev_mqs(struct virtio_device *vdev,\n'
        '\t\tint sizeof_priv, const char *name,')
    e.edit('\tstruct net_device *dev;\n', '\tstruct net_device *dev;\n'
        '\tif (txqs != 1 || rxqs != 1 || setup != ether_setup ||\n'
        '\t    name_assign_type != NET_NAME_ENUM || strcmp(name, "eth%d")) return NULL;\n')
    e.edit('\tdev = kvzalloc(struct_size(dev, priv, sizeof_priv),\n'
        '\t\t       GFP_KERNEL_ACCOUNT | __GFP_RETRY_MAYFAIL);\n',
        '\tdev = lsf_factory_stream_netdev_allocate(vdev,\n'
        '\t\tstruct_size(dev, priv, sizeof_priv), sizeof_priv);\n')
    e.edit('netif_alloc_netdev_queues(dev)', 'lsf_stream_netdev_alloc_tx_queues(dev)')
    e.edit('netif_alloc_rx_queues(dev)', 'lsf_stream_netdev_alloc_rx_queues(dev)')
    e.edit('\tdev->ethtool = kzalloc(sizeof(*dev->ethtool), GFP_KERNEL_ACCOUNT);\n',
        '\tdev->ethtool = lsf_factory_stream_netdev_fixed_allocate(dev,\n'
        '\t\tLSF_STREAM_NETDEV_ETHTOOL, sizeof(*dev->ethtool));\n')
    e.edit('\treturn dev;\n',
        '\tif (!lsf_factory_stream_netdev_publish(dev)) goto free_all;\n\treturn dev;\n')
    e.edit('\tkvfree(dev);\n', '\t(void)lsf_factory_stream_netdev_release(dev);\n')
    return e.finish()


def transform(outputs, originals):
    require(type(outputs) is dict and type(originals) is dict and set(originals) == set(PRIMARY)
        and all(type(outputs.get(n)) is bytes for n in (DEV, NET, 'net/factory.c',
            'net/device-prepaid.h', 'net/factory-stream-stop.c')) and HEADER not in outputs,
        'stream-fixed-exact-stage')
    for name, raw in originals.items():
        size, digest = PRIMARY[name]
        require(type(raw) is bytes and len(raw) == size and hashlib.sha256(raw).hexdigest() == digest,
            'stream-fixed-exact-primary')
    for name, (size, digest) in PREVIOUS.items():
        raw = outputs.get(name)
        require(type(raw) is bytes and len(raw) == size and hashlib.sha256(raw).hexdigest() == digest,
            'stream-fixed-exact-reviewed-cpu-rx-postimage')
    result = dict(outputs)
    dev = Editor(outputs[DEV].decode())
    tx = _queue(_body(dev.text, 'static int netif_alloc_netdev_queues('), 'tx')
    rx = _queue(_body(dev.text, 'static int netif_alloc_rx_queues('), 'rx')
    # CPU stage supplies the exact authenticated original constructor projection.
    # The only new main body is the private copied allocator below.
    constructor = function(dev.text, 'struct net_device *alloc_netdev_mqs(')
    main = _main(constructor)
    include = ('#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_netdev_fixed_private.h>\n'
        +tx.split('\n{\n',1)[0]+';\n'+rx.split('\n{\n',1)[0]+';\n#endif\n')
    dev.edit('#include <linux/etherdevice.h>\n', '#include <linux/etherdevice.h>\n'+include)
    for signature, selector in [('static void netif_free_tx_queues(', 'LSF_STREAM_NETDEV_TX'),
            ('static void netif_free_rx_queues(', 'LSF_STREAM_NETDEV_RX')]:
        original = _body(dev.text, signature)
        body = Editor(original)
        member = '_tx' if selector.endswith('_TX') else '_rx'
        body.edit('\tkvfree(dev->'+member+');\n',
            '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\tif (!lsf_factory_stream_netdev_fixed_return(dev, '+selector+'))\n#endif\n'
            '\tkvfree(dev->'+member+');\n')
        dev.edit(original, body.finish())
    original = function(dev.text, 'void free_netdev(')
    body = Editor(original)
    body.edit('\tkfree(dev->ethtool);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (!lsf_factory_stream_netdev_fixed_return(dev, LSF_STREAM_NETDEV_ETHTOOL))\n#endif\n'
        '\tkfree(dev->ethtool);\n')
    body.edit('\t\tkvfree(dev);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\tif (!lsf_factory_stream_netdev_release(dev))\n#endif\n\t\tkvfree(dev);\n')
    dev.edit(original, body.finish())
    prior = dev.text
    dev.edit(prior, prior+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'+tx+rx+main+
        '#include "lsf_stream_netdev_fixed_geometry.c"\n#endif\n')
    result[DEV] = dev.finish().encode()
    eth = Editor(originals[ETH].decode())
    original = _body(eth.text, 'struct net_device *alloc_etherdev_mqs(')
    body = Editor(original)
    body.edit('alloc_etherdev_mqs(int sizeof_priv, unsigned int txqs,',
        'lsf_prepaid_stream_alloc_etherdev_mqs(struct virtio_device *vdev,\n'
        '\t\tint sizeof_priv, unsigned int txqs,')
    body.edit('alloc_netdev_mqs(sizeof_priv,', 'lsf_prepaid_stream_alloc_netdev_mqs(vdev, sizeof_priv,')
    eth.edit('#include <linux/etherdevice.h>\n', '#include <linux/etherdevice.h>\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_netdev_fixed_private.h>\n#endif\n')
    prior = eth.text
    eth.edit(prior, prior+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'+body.finish()+'#endif\n')
    result[ETH] = eth.finish().encode()
    net = Editor(outputs[NET].decode())
    original = function(net.text, 'static int virtnet_probe(')
    body = Editor(original)
    body.edit('\tdev = alloc_etherdev_mq(sizeof(struct virtnet_info), max_queue_pairs);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n\t{\n\t\tint stream_owned = lsf_factory_stream_netdev_selected(vdev);\n'
        '\t\tif (stream_owned < 0) return stream_owned;\n'
        '\t\tif (stream_owned)\n'
        '\t\t\tdev = lsf_prepaid_stream_alloc_etherdev_mqs(vdev, sizeof(struct virtnet_info),\n'
        '\t\t\t\tmax_queue_pairs, max_queue_pairs);\n\t\telse\n'
        '\t\t\tdev = alloc_etherdev_mq(sizeof(struct virtnet_info), max_queue_pairs);\n\t}\n'
        '#else\n\tdev = alloc_etherdev_mq(sizeof(struct virtnet_info), max_queue_pairs);\n#endif\n')
    net.edit(original, body.finish())
    net.edit('#include <linux/netdevice.h>\n', '#include <linux/netdevice.h>\n'
        '#include <net/lsf_stream_netdev_fixed_private.h>\n')
    result[NET] = net.finish().encode()
    sysfs = Editor(originals[SYSFS].decode())
    original = _body(sysfs.text, 'static void netdev_release(')
    body = Editor(original)
    body.edit('\tkvfree(dev);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (!lsf_factory_stream_netdev_release(dev))\n#endif\n\tkvfree(dev);\n')
    sysfs.edit(original, body.finish())
    sysfs.edit('#include <linux/netdevice.h>\n', '#include <linux/netdevice.h>\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_netdev_fixed_private.h>\n#endif\n')
    result[SYSFS] = sysfs.finish().encode()
    device = Editor(outputs['net/device-prepaid.h'].decode())
    require('LSF_DEVICE_NETDEV_TX' not in device.text, 'stream-fixed-fresh-kinds')
    device.edit('static inline int lsf_device_kind(unsigned int kind)\n',
        'enum { LSF_DEVICE_NETDEV_TX = 0x167, LSF_DEVICE_NETDEV_RX, LSF_DEVICE_NETDEV_ETHTOOL };\n'
        'static inline int lsf_device_kind(unsigned int kind)\n')
    original = function(device.text, 'static inline int lsf_device_kind(')
    body = Editor(original)
    body.edit('return kind ==',
        'return kind == LSF_DEVICE_NETDEV_TX || kind == LSF_DEVICE_NETDEV_RX ||\n'
        '        kind == LSF_DEVICE_NETDEV_ETHTOOL || kind ==')
    device.edit(original, body.finish())
    result['net/device-prepaid.h'] = device.finish().encode()
    factory = Editor(outputs['net/factory.c'].decode())
    factory.edit('#include "factory-stream-stop.c"\n',
        'static int lsf_stream_netdev_drain_after_remove(struct lsf_stream_rx_state *);\n'
        '#include "factory-stream-stop.c"\n')
    prior = factory.text
    factory.edit(prior, prior+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "factory-stream-netdev-fixed.c"\n#endif\n')
    result['net/factory.c'] = factory.finish().encode()
    stop = Editor(outputs['net/factory-stream-stop.c'].decode())
    stop.edit('        pci_stop_and_remove_bus_device_locked(pci);\n',
        '        pci_stop_and_remove_bus_device_locked(pci);\n'
        '        /* Real address callbacks finish before their NETDEV parent,\n'
        '         * while SAME counted bank loan and real device refs remain. */\n'
        '        rcu_barrier();\n'
        '        result = lsf_stream_netdev_drain_after_remove(state);\n')
    result['net/factory-stream-stop.c'] = stop.finish().encode()
    result[HEADER] = _owned('stream-netdev-fixed-private.h')
    result[GEOMETRY] = _owned('stream-netdev-fixed-geometry-private.h')
    result['net/core/lsf_stream_netdev_fixed_geometry.c'] = _owned('stream-netdev-fixed-geometry.c')
    result['net/factory-stream-netdev-fixed.c'] = _owned('factory-stream-netdev-fixed.c')
    return result
