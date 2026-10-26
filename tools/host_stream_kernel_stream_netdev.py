"""Unselected exact NETDEV hardware-address births and actual RCU returns.

The main NETDEV/per-CPU producer and final-release path are NOT completed by
this source port. A pointer can only locate an existing typed prepaid birth.
"""
import hashlib
from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_device_security import function
from tools.host_stream_kernel_cleanup_native import OWNED, require

SOURCE = 'net/core/dev_addr_lists.c'
HEADER = 'include/net/lsf_stream_netdev_private.h'
SOURCE_BYTES = 27125
SOURCE_SHA = 'bd95a3e441a5641b3154f54325c5c78d3378672a09227f54080252386fb7dbd8'
PINS = {
    'static struct netdev_hw_addr*\n__hw_addr_create(': (509,
        '1c7fc395030a2bc7f90ad629d3af12fac20b6f764e91a2db4d5b383ca1ba425f'),
    'static int __hw_addr_add_ex(': (1295,
        '63f8dc6416d50b70142e929a6437c5404b437ee0909e35a3b8d8fdcdc625de5c'),
    'static int __hw_addr_del_entry(': (453,
        '44eba3e75cb0b6cef722a3417c8a3f5fc50180fab6b7fd98607514e3b5295c8b'),
    'static void __hw_addr_flush(': (255,
        '624806d733c89b0955913517ed4fb5101878ff97f4e622d7e2036d27792318dc'),
}


def _owned(name):
    raw = (OWNED/name).read_bytes()
    require(0 < len(raw) <= 16*1024 and b'\r' not in raw, 'stream-netdev-source-bound')
    return raw


def _body(text, signature):
    body = function(text, signature)
    size, digest = PINS[signature]
    require(len(body.encode()) == size and hashlib.sha256(body.encode()).hexdigest() == digest,
        'stream-netdev-original-body')
    return body


def _create(original):
    e = Editor(original)
    e.edit('__hw_addr_create(const unsigned char *addr, int addr_len,',
        'lsf_stream_hw_addr_create(struct netdev_hw_addr_list *list,\n'
        '    const unsigned char *addr, int addr_len,')
    e.edit('\tint alloc_size;\n\n\talloc_size = sizeof(*ha);\n'
        '\tif (alloc_size < L1_CACHE_BYTES)\n\t\talloc_size = L1_CACHE_BYTES;\n'
        '\tha = kmalloc(alloc_size, GFP_ATOMIC);\n',
        '\tstruct lsf_stream_netdev_source source;\n'
        '\tint owned = lsf_factory_stream_hw_addr_parent(list, &source);\n'
        '\tif (owned < 0) return NULL;\n'
        '\tif (!owned) return __hw_addr_create(addr, addr_len, addr_type, global, sync);\n'
        '\tha = lsf_factory_stream_hw_addr_allocate(source);\n')
    e.edit('\treturn ha;\n',
        '\t/* Initialized original fields precede the original tree/list publication. */\n'
        '\tif (!lsf_factory_stream_hw_addr_publish(ha, source)) return NULL;\n'
        '\treturn ha;\n')
    return e.finish()


def transform(outputs, original):
    require(type(outputs) is dict and type(original) is bytes and len(original) == SOURCE_BYTES
        and hashlib.sha256(original).hexdigest() == SOURCE_SHA and SOURCE not in outputs
        and HEADER not in outputs and all(type(outputs.get(n)) is bytes for n in
            ('net/factory.c', 'net/device-prepaid.h')), 'stream-netdev-fixed-inputs')
    result = dict(outputs)
    e = Editor(original.decode())
    bodies = {name: _body(e.text, name) for name in PINS}
    create = _create(bodies['static struct netdev_hw_addr*\n__hw_addr_create('])
    declarations = ('#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include <net/lsf_stream_netdev_private.h>\n'+
        create.split('\n{\n', 1)[0]+';\n'
        'static int lsf_stream_hw_addr_defer(struct netdev_hw_addr *);\n#endif\n')
    e.edit('#include "dev.h"\n', '#include "dev.h"\n'+declarations)
    old = bodies['static int __hw_addr_add_ex(']
    add = Editor(old)
    add.edit('\tha = __hw_addr_create(addr, addr_len, addr_type, global, sync);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tha = lsf_stream_hw_addr_create(list, addr, addr_len, addr_type, global, sync);\n'
        '#else\n\tha = __hw_addr_create(addr, addr_len, addr_type, global, sync);\n#endif\n')
    e.edit(old, add.finish())
    for signature in ('static int __hw_addr_del_entry(', 'static void __hw_addr_flush('):
        old = bodies[signature]
        body = Editor(old)
        indent = '\t\t' if signature.endswith('__hw_addr_flush(') else '\t'
        body.edit(indent+'kfree_rcu(ha, rcu_head);\n',
            '#ifdef CONFIG_LSF_STREAM_FACTORY\n'+indent+'if (!lsf_stream_hw_addr_defer(ha))\n'
            '#endif\n'+indent+'kfree_rcu(ha, rcu_head);\n')
        e.edit(old, body.finish())
    prior = e.text
    e.edit(prior, prior+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'+create+"""
static void lsf_stream_hw_addr_rcu(struct rcu_head *head)
{
    struct netdev_hw_addr *ha = container_of(head, struct netdev_hw_addr, rcu_head);
    (void)lsf_factory_stream_hw_addr_finish(ha);
    /* No payload read after actual record return; Root's real rcu_barrier
     * still fences this callback epilogue before physical backing return. */
}

static int lsf_stream_hw_addr_defer(struct netdev_hw_addr *ha)
{
    int owned = lsf_factory_stream_hw_addr_queue(ha);
    if (owned == 1) call_rcu(&ha->rcu_head, lsf_stream_hw_addr_rcu);
    return owned; /* Unknown private means retain, never ordinary kfree_rcu. */
}
#endif
""")
    result[SOURCE] = e.finish().encode()
    device = Editor(outputs['net/device-prepaid.h'].decode())
    require('LSF_DEVICE_NETDEV' not in device.text and 'LSF_DEVICE_HW_ADDR' not in device.text,
        'stream-netdev-fresh-kind-namespace')
    device.edit('static inline int lsf_device_kind(unsigned int kind)\n',
        'enum { LSF_DEVICE_NETDEV = 0x164, LSF_DEVICE_HW_ADDR };\n'
        'static inline int lsf_device_kind(unsigned int kind)\n')
    old = function(device.text, 'static inline int lsf_device_kind(')
    kind = Editor(old)
    kind.edit('return kind ==', 'return kind == LSF_DEVICE_NETDEV || kind == LSF_DEVICE_HW_ADDR || kind ==')
    device.edit(old, kind.finish())
    result['net/device-prepaid.h'] = device.finish().encode()
    factory = Editor(outputs['net/factory.c'].decode())
    require('lsf_factory_stream_hw_addr_parent(' not in factory.text, 'stream-netdev-fresh-factory')
    prior = factory.text
    factory.edit(prior, prior+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "factory-stream-netdev-address.c"\n#endif\n')
    result['net/factory.c'] = factory.finish().encode()
    result['net/factory-stream-netdev-address.c'] = _owned('factory-stream-netdev-address.c')
    result[HEADER] = _owned('stream-netdev-private.h')
    return result
