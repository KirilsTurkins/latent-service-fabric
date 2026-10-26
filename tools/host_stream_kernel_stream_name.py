"""Exact unselected primary NETDEV name-node birth/return source port.

Ordinary devices retain original allocation. No alias-name strings, complete
source closure, compiled fit, provider selection or runtime success is claimed.
"""
import hashlib
from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_device_security import function
from tools.host_stream_kernel_cleanup_native import OWNED, require

DEV = 'net/core/dev.c'
HEADER = 'include/net/lsf_stream_netdev_name_private.h'
PREVIOUS = (331387, 'cb7d5e05c92ff5f12a026681d6dd0cf3e06a58c0e7526ad096fa6e66c7469c65')
PINS = {'static struct netdev_name_node *netdev_name_node_alloc(': (342, 'ae06f3da65e46b47faea3ac2735bdbde132b1f0e3d941b90bafe623978dcddd8'), 'static struct netdev_name_node *\nnetdev_name_node_head_alloc(': (266, '882522b7bf739fe0767e071443f1ad43bb2b937f9f13dae42ad3297bafb772fe'), 'static void netdev_name_node_free(': (93, '953f18e47649d04cac9e099b7001ef1c21115c871b5fc5394764a80d518defd4')}


def _owned(name):
    raw = (OWNED/name).read_bytes()
    require(0 < len(raw) <= 16*1024 and b'\r' not in raw, 'stream-name-owned-bound')
    return raw


def _body(text, signature):
    raw = function(text, signature)
    size, digest = PINS[signature]
    require(len(raw.encode()) == size and hashlib.sha256(raw.encode()).hexdigest() == digest,
        'stream-name-original-body-pin')
    return raw


def transform(outputs):
    require(type(outputs) is dict and all(type(outputs.get(n)) is bytes for n in
        (DEV, 'net/factory.c', 'net/device-prepaid.h')) and HEADER not in outputs,
        'stream-name-exact-stage')
    raw = outputs[DEV]
    require((len(raw), hashlib.sha256(raw).hexdigest()) == PREVIOUS,
        'stream-name-reviewed-fixed-postimage')
    result = dict(outputs)
    dev = Editor(raw.decode())
    dev.edit('#include <linux/etherdevice.h>\n', '#include <linux/etherdevice.h>\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_netdev_name_private.h>\n#endif\n')
    signature = 'static struct netdev_name_node *netdev_name_node_alloc('
    original = _body(dev.text, signature)
    body = Editor(original)
    body.edit('\tname_node = kmalloc(sizeof(*name_node), GFP_KERNEL);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t{\n\t\tint stream_owned = lsf_factory_stream_netdev_name_parent(dev);\n'
        '\t\tif (stream_owned < 0 || (stream_owned && name != dev->name)) return NULL;\n'
        '\t\tif (stream_owned)\n\t\t\tname_node = lsf_factory_stream_netdev_name_allocate(dev);\n'
        '\t\telse\n\t\t\tname_node = kmalloc(sizeof(*name_node), GFP_KERNEL);\n\t}\n'
        '#else\n\tname_node = kmalloc(sizeof(*name_node), GFP_KERNEL);\n#endif\n')
    dev.edit(original, body.finish())
    signature = 'static struct netdev_name_node *\nnetdev_name_node_head_alloc('
    original = _body(dev.text, signature)
    body = Editor(original)
    body.edit('\tstruct netdev_name_node *name_node;\n',
        '\tstruct netdev_name_node *name_node;\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tint stream_owned = lsf_factory_stream_netdev_name_parent(dev);\n'
        '\tif (stream_owned < 0) return NULL;\n#endif\n')
    body.edit('\tINIT_LIST_HEAD(&name_node->list);\n',
        '\tINIT_LIST_HEAD(&name_node->list);\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (stream_owned && !lsf_factory_stream_netdev_name_publish(dev, name_node)) return NULL;\n'
        '#endif\n')
    dev.edit(original, body.finish())
    original = _body(dev.text, 'static void netdev_name_node_free(')
    body = Editor(original)
    body.edit('\tkfree(name_node);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (!lsf_factory_stream_netdev_name_return(name_node))\n#endif\n\tkfree(name_node);\n')
    dev.edit(original, body.finish())
    before = dev.text
    dev.edit(before, before+"""
#ifdef CONFIG_LSF_STREAM_FACTORY
int lsf_prepaid_stream_netdev_name_geometry(unsigned long *bytes, unsigned long *alignment)
{
    if (!bytes || !alignment || __alignof__(struct netdev_name_node) > 64u)
        return -EOPNOTSUPP;
    *bytes = sizeof(struct netdev_name_node);
    *alignment = __alignof__(struct netdev_name_node);
    return 0;
}
#endif
""")
    result[DEV] = dev.finish().encode()
    device = Editor(outputs['net/device-prepaid.h'].decode())
    require('LSF_DEVICE_NETDEV_NAME' not in device.text, 'stream-name-fresh-kind')
    device.edit('static inline int lsf_device_kind(unsigned int kind)\n',
        'enum { LSF_DEVICE_NETDEV_NAME = 0x16a };\n'
        'static inline int lsf_device_kind(unsigned int kind)\n')
    original = function(device.text, 'static inline int lsf_device_kind(')
    body = Editor(original)
    body.edit('return kind ==', 'return kind == LSF_DEVICE_NETDEV_NAME || kind ==')
    device.edit(original, body.finish())
    result['net/device-prepaid.h'] = device.finish().encode()
    factory = Editor(outputs['net/factory.c'].decode())
    require('factory-stream-netdev-name.c' not in factory.text and
        'factory-stream-netdev-fixed.c' in factory.text, 'stream-name-fixed-before-source')
    before = factory.text
    factory.edit(before, before+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "factory-stream-netdev-name.c"\n#endif\n')
    result['net/factory.c'] = factory.finish().encode()
    result[HEADER] = _owned('stream-netdev-name-private.h')
    result['net/factory-stream-netdev-name.c'] = _owned('factory-stream-netdev-name.c')
    return result
