"""Unselected exact owned NETDEV CPU-indexed reference/stats routing.

Original wait-allrefs/final-release/RCU bodies remain authoritative. The
NETDEV main/fixed-child/final-release source ports remain separate required
work; no consumer is enabled and no kernel compilation is claimed.
"""
import hashlib
from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_device_security import function
from tools.host_stream_kernel_cleanup_native import OWNED, require

PREIMAGES = {'include/linux/netdevice.h': (170262, '35577d1d0decaad06824a0591c5929a1e837c7dc00e95b42cba1bc6743fb3941'), 'net/core/dev.c': (324886, '633e28e79577be12e9246585c0a1e8fa82c5c469eb2cf8758b42a65289690676')}
PINS = {'static inline void __dev_put(': (184, '63fe60015ff9b99c546a9f36f806bb01ba894fca232db30bcbadf47d9449c1cc'), 'static inline void __dev_hold(': (185, '3b474ef27e30675cb5c1cbb8d9c00cb9ec39b7831009cdaf30b8e6b2271d5de1'), 'int netdev_refcnt_read(': (251, 'bbc3f488c8cd1534e751c1d72aa4c82c04d846c2791e3bd598f9035e39886ba6'), 'noinline void netdev_core_stats_inc(': (426, '1f0ec17f2fc69b61e6eff115a474c809366bde1e4f23e242aa94e6eea5bc2e69'), 'struct rtnl_link_stats64 *dev_get_stats(': (1837, '980259d14338c7d8b387855c76434b3aca0d896c5032039002ece859c46976f7'), 'struct net_device *alloc_netdev_mqs(': (2785, '483dcf1cb1b5614ed5b180c5d947143ea0ddcaafec9b6393f1544722a0b5f963'), 'void free_netdev(': (1258, '03900bdc05d59cd59606ef1aa72a6911ae381dec35bd5c98ad1c5208de487ba4')}
HEADER = 'include/linux/netdevice.h'
DEV = 'net/core/dev.c'
CPU_HEADER = 'include/net/lsf_stream_netdev_cpu_private.h'


def _body(text, signature):
    body = function(text, signature)
    size, digest = PINS[signature]
    require(len(body.encode()) == size and hashlib.sha256(body.encode()).hexdigest() == digest,
        'stream-cpu-selected-body-preimage')
    return body


def _owned(name):
    raw = (OWNED/name).read_bytes()
    require(0 < len(raw) <= 16*1024 and b'\r' not in raw, 'stream-cpu-owned-source-bound')
    return raw


def _header(raw):
    e = Editor(raw.decode())
    e.edit('struct net_device {\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\nstruct lsf_stream_netdev_cpu_storage;\n#endif\n'
        'struct net_device {\n')
    e.edit('\tu8\t\t\tpriv[] ____cacheline_aligned\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t/* Actual typed constructor owns this field and its original refs/RCU lifetime. */\n'
        '\tstruct lsf_stream_netdev_cpu_storage *lsf_cpu_storage;\n#endif\n'
        '\tu8\t\t\tpriv[] ____cacheline_aligned\n')
    e.edit('static inline void __dev_put(struct net_device *dev)\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        'void lsf_stream_netdev_cpu_put(struct net_device *);\n'
        'void lsf_stream_netdev_cpu_get(struct net_device *);\n#endif\n'
        'static inline void __dev_put(struct net_device *dev)\n')
    for method in ('put', 'hold'):
        signature = 'static inline void __dev_'+method+'('
        old = _body(raw.decode(), signature)
        body = Editor(old)
        helper = 'put' if method == 'put' else 'get'
        body.edit('\tif (dev) {\n',
            '\tif (dev) {\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\t\tif (READ_ONCE(dev->lsf_cpu_storage)) {\n'
            '\t\t\tlsf_stream_netdev_cpu_'+helper+'(dev);\n\t\t\treturn;\n\t\t}\n#endif\n')
        e.edit(old, body.finish())
    return e.finish().encode()


def _dev(raw):
    e = Editor(raw.decode())
    e.edit('#include <linux/netdevice.h>\n',
        '#include <linux/netdevice.h>\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include <net/lsf_stream_netdev_cpu_private.h>\n#endif\n')
    old = _body(e.text, 'int netdev_refcnt_read(')
    body = Editor(old)
    body.edit('#ifdef CONFIG_PCPU_DEV_REFCNT\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (READ_ONCE(dev->lsf_cpu_storage)) return lsf_stream_netdev_cpu_ref_read(dev);\n'
        '#endif\n#ifdef CONFIG_PCPU_DEV_REFCNT\n')
    e.edit(old, body.finish())
    old = _body(e.text, 'noinline void netdev_core_stats_inc(')
    body = Editor(old)
    body.edit('\tif (unlikely(!p)) {\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (READ_ONCE(dev->lsf_cpu_storage)) {\n'
        '\t\tlsf_stream_netdev_cpu_stats_inc(dev, offset);\n\t\treturn;\n\t}\n#endif\n'
        '\tif (unlikely(!p)) {\n')
    e.edit(old, body.finish())
    old = _body(e.text, 'struct rtnl_link_stats64 *dev_get_stats(')
    body = Editor(old)
    body.edit('\t/* This READ_ONCE() pairs with the write in netdev_core_stats_alloc() */\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (READ_ONCE(dev->lsf_cpu_storage)) {\n'
        '\t\tlsf_stream_netdev_cpu_stats_add(dev, storage);\n\t\treturn storage;\n\t}\n#endif\n'
        '\t/* This READ_ONCE() pairs with the write in netdev_core_stats_alloc() */\n')
    e.edit(old, body.finish())
    old = _body(e.text, 'struct net_device *alloc_netdev_mqs(')
    body = Editor(old)
    alloc = ('\tdev->pcpu_refcnt = alloc_percpu(int);\n'
        '\tif (!dev->pcpu_refcnt)\n\t\tgoto free_dev;\n')
    body.edit(alloc,
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n\t{\n'
        '\t\tint stream_owned = lsf_factory_stream_netdev_cpu_allocate(dev);\n'
        '\t\tif (stream_owned < 0) goto free_dev;\n'
        '\t\tif (!stream_owned) {\n#endif\n'+alloc+
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n\t\t}\n\t}\n#endif\n')
    body.edit('\tfree_percpu(dev->pcpu_refcnt);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (READ_ONCE(dev->lsf_cpu_storage))\n'
        '\t\t(void)lsf_factory_stream_netdev_cpu_retire(dev);\n'
        '\telse\n#endif\n\tfree_percpu(dev->pcpu_refcnt);\n')
    e.edit(old, body.finish())
    old = _body(e.text, 'void free_netdev(')
    body = Editor(old)
    body.edit('\tdev->core_stats = NULL;\n',
        '\tdev->core_stats = NULL;\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (READ_ONCE(dev->lsf_cpu_storage))\n'
        '\t\t(void)lsf_factory_stream_netdev_cpu_retire(dev);\n#endif\n')
    e.edit(old, body.finish())
    prior = e.text
    e.edit(prior, prior+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf_stream_netdev_cpu.c"\n#endif\n')
    return e.finish().encode()


def transform(outputs, sources):
    require(type(outputs) is dict and type(sources) is dict and set(sources) == set(PREIMAGES)
        and set(sources).intersection(outputs) <= {HEADER} and CPU_HEADER not in outputs
        and all(type(outputs.get(n)) is bytes for n in ('net/factory.c', 'net/device-prepaid.h')),
        'stream-cpu-fixed-input-set')
    for name, raw in sources.items():
        size, digest = PREIMAGES[name]
        require(type(raw) is bytes and len(raw) == size and hashlib.sha256(raw).hexdigest() == digest,
            'stream-cpu-original-whole-preimage')
        # The normal baseline already carries this exact unmodified header.
        # Never discard an existing transformed TU or accept an alternate body.
        require(name not in outputs or outputs[name] == raw,
            'stream-cpu-identical-original-passthrough')
    result = dict(outputs)
    result[HEADER] = _header(sources[HEADER])
    result[DEV] = _dev(sources[DEV])
    result[CPU_HEADER] = _owned('stream-netdev-cpu-private.h')
    result['net/core/lsf_stream_netdev_cpu.c'] = _owned('stream-netdev-cpu.c')
    result['net/factory-stream-netdev-cpu.c'] = _owned('factory-stream-netdev-cpu.c')
    device = Editor(outputs['net/device-prepaid.h'].decode())
    require('LSF_DEVICE_NETDEV_CPU' not in device.text and 'LSF_DEVICE_NETDEV =' in device.text,
        'stream-cpu-typed-parent-kind-stage')
    device.edit('static inline int lsf_device_kind(unsigned int kind)\n',
        'enum { LSF_DEVICE_NETDEV_CPU = 0x166 };\n'
        'static inline int lsf_device_kind(unsigned int kind)\n')
    original = function(device.text, 'static inline int lsf_device_kind(')
    body = Editor(original)
    body.edit('return kind ==', 'return kind == LSF_DEVICE_NETDEV_CPU || kind ==')
    device.edit(original, body.finish())
    result['net/device-prepaid.h'] = device.finish().encode()
    factory = Editor(outputs['net/factory.c'].decode())
    require('#include "factory-stream-netdev-address.c"' in factory.text,
        'stream-cpu-original-typed-netdev-helper-stage')
    prior = factory.text
    factory.edit(prior, prior+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "factory-stream-netdev-cpu.c"\n#endif\n')
    result['net/factory.c'] = factory.finish().encode()
    return result
