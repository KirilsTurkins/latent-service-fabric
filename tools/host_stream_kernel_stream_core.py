"""Exact unselected NETDEV core-private/name and full kobject-tail custody.

No old PCI constructor or ordinary callback is replaced. This source stage
preserves original allocation limits; complete kernfs/class/packet ports,
compiled useful fit and real-kernel qualification still precede selection.
"""
import hashlib
from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_device_security import function
from tools.host_stream_kernel_cleanup_native import OWNED, require

CORE = 'drivers/base/core.c'
KOBJECT = 'lib/kobject.c'
SYSFS = 'net/core/net-sysfs.c'
HELPER = 'net/factory-device-core.c'
FIXED = 'net/factory-stream-netdev-fixed.c'
RX = 'net/factory-stream-rx-preallocate.c'
ROOT = 'net/factory-stream-root-final-free.c'
HEADER = 'include/net/lsf_stream_netdev_core_private.h'
PREVIOUS = {'drivers/base/core.c': (151930, '244f28347787aec850a4f139a4666e0b2f194a185a77e729acf803f90aeaeea9'), 'lib/kobject.c': (30668, '91d81b1c81ab755db0e4358b5b9e3c4718d5030401dcf4ad7561e6ccd0a973ee'), 'net/factory-device-core.c': (12022, '2c153e1cca1eb589e6e8b0cb2875cbb1b01fe51fba8f7642675deb7f62b9cf3b'), 'net/core/net-sysfs.c': (52903, '686f85927cb0b0d9ad509e2827513a854058fed9c68da9ed502cf8d46c725187'), 'net/factory-stream-netdev-fixed.c': (15763, '0595ac6452778ad6222f157265f4222c6c4b46964c3b7e0db885e2d5232b1637'), 'net/factory-stream-rx-preallocate.c': (46154, '8e9f72047e57e21aca6eefe5b071760924723b4bfc48fa666c95dc10ba65883f'), 'net/factory-stream-root-final-free.c': (12765, '2aa32c9afd9b1b750e5251d54b60d81a550b679e8887a9457afb73f6c61d4e8a')}


def _owned(name):
    raw = (OWNED/name).read_bytes()
    require(0 < len(raw) <= 32*1024 and b'\r' not in raw, 'stream-netdev-core-owned-bound')
    return raw


def _hook(text, signature, prefix):
    original = function(text, signature)
    body = Editor(original)
    body.edit('    spin_lock_irqsave(&pool_lock, flags);\n',
        prefix+'    spin_lock_irqsave(&pool_lock, flags);\n')
    editor = Editor(text)
    editor.edit(original, body.finish())
    return editor.finish()


def transform(outputs):
    require(type(outputs) is dict and HEADER not in outputs and
        all(type(outputs.get(n)) is bytes for n in PREVIOUS) and
        all(type(outputs.get(n)) is bytes for n in ('net/factory.c','net/device-prepaid.h')),
        'stream-netdev-core-exact-stage')
    for name, (size, digest) in PREVIOUS.items():
        raw = outputs[name]
        require(len(raw) == size and hashlib.sha256(raw).hexdigest() == digest,
            'stream-netdev-core-reviewed-whole-preimage')
    result = dict(outputs)
    core = Editor(outputs[CORE].decode())
    core.edit('#include <net/lsf_stream_device_core.h>\n',
        '#include <net/lsf_stream_device_core.h>\n#include <net/lsf_stream_netdev_core_private.h>\n')
    before = core.text
    core.edit(before, before+"""
#ifdef CONFIG_LSF_STREAM_FACTORY
int lsf_prepaid_stream_netdev_core_geometry(unsigned long *bytes, unsigned long *alignment)
{
    if (!bytes || !alignment || __alignof__(struct device_private) > 64u)
        return -EOPNOTSUPP;
    *bytes = sizeof(struct device_private);
    *alignment = __alignof__(struct device_private);
    return 0;
}
#endif
""")
    result[CORE] = core.finish().encode()
    sysfs = Editor(outputs[SYSFS].decode())
    sysfs.edit('#include <linux/netdevice.h>\n', '#include <linux/netdevice.h>\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_netdev_core_private.h>\n#endif\n')
    original = function(sysfs.text, 'int netdev_register_kobject(')
    body = Editor(original)
    # Original device_initialize and class/release setup happen first, so an
    # error still owns the real kobject reference needed by original put_device.
    body.edit('\tdev_set_name(dev, "%s", ndev->name);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n\t{\n'
        '\t\tint stream_owned = lsf_factory_stream_netdev_core_classify(dev, 0);\n'
        '\t\tif (stream_owned < 0) return stream_owned;\n'
        '\t\tif (stream_owned) {\n'
        '\t\t\terror = lsf_factory_stream_netdev_core_begin(ndev);\n'
        '\t\t\tif (!error) error = lsf_factory_stream_netdev_core_name(ndev);\n'
        '\t\t\tif (error) return error;\n'
        '\t\t} else dev_set_name(dev, "%s", ndev->name);\n\t}\n'
        '#else\n\tdev_set_name(dev, "%s", ndev->name);\n#endif\n')
    sysfs.edit(original, body.finish())
    result[SYSFS] = sysfs.finish().encode()
    kobj = Editor(outputs[KOBJECT].decode())
    kobj.edit('#include <net/lsf_stream_device_core.h>\n',
        '#include <net/lsf_stream_device_core.h>\n#include <net/lsf_stream_netdev_core_private.h>\n')
    original = function(kobj.text, 'static void lsf_prepaid_kobject_cleanup(')
    body = Editor(original)
    body.edit('\t\tkfree_const(name);\n',
        '\t\tif (!lsf_factory_stream_netdev_core_name_return(kobj, name))\n'
        '\t\t\tkfree_const(name);\n')
    kobj.edit(original, body.finish())
    result[KOBJECT] = kobj.finish().encode()
    helper = outputs[HELPER].decode()
    for signature, address, mode, target in [
        ('int lsf_factory_device_core_owned(', 'device', 0, 'lsf_factory_stream_netdev_core_owned(device)'),
        ('int lsf_factory_device_core_return(', 'device', 0, 'lsf_factory_stream_netdev_core_return(device, address)'),
        ('int lsf_factory_device_core_tail_enter(', 'kobject', 1, 'lsf_factory_stream_netdev_core_tail_enter(kobject)'),
    ]:
        prefix=('    int stream_kind = lsf_factory_stream_netdev_core_classify('+address+', '+str(mode)+');\n'
            '    if (stream_kind) return stream_kind < 0 ? stream_kind : '+target+';\n')
        helper = _hook(helper, signature, prefix)
    helper = _hook(helper, 'void *lsf_factory_device_core_allocate(',
        '    int stream_kind = lsf_factory_stream_netdev_core_classify(device, 0);\n'
        '    if (stream_kind) return stream_kind < 0 ? NULL :\n'
        '        lsf_factory_stream_netdev_core_allocate(device, bytes);\n')
    helper = _hook(helper, 'void lsf_factory_device_core_tail_finish(',
        '    int stream_result = lsf_factory_stream_netdev_core_tail_finish(kobject);\n'
        '    if (stream_result) return;\n')
    result[HELPER] = helper.encode()
    fixed = Editor(outputs[FIXED].decode())
    original = function(fixed.text, 'int lsf_factory_stream_netdev_release(')
    body = Editor(original)
    body.edit('record->security_cache_identity ||\n',
        '(record->security_cache_identity != 0u &&\n'
        '         record->security_cache_identity != (LSF_STREAM_NETDEV_CORE | LSF_STREAM_NETDEV_TAIL_ACTIVE)) ||\n')
    body.edit('record->security_cache_identity = 1u; /* Actual original final kvfree reached. */',
        'record->security_cache_identity |= LSF_STREAM_NETDEV_RELEASE; /* Actual original final kvfree reached. */')
    fixed.edit(original, body.finish())
    original = function(fixed.text, 'static int lsf_stream_netdev_drain_after_remove(')
    body = Editor(original)
    body.edit('record->security_cache_identity != 1u ||\n',
        '(record->security_cache_identity != LSF_STREAM_NETDEV_RELEASE &&\n'
        '             record->security_cache_identity != (LSF_STREAM_NETDEV_RELEASE |\n'
        '                 LSF_STREAM_NETDEV_CORE | LSF_STREAM_NETDEV_TAIL_DONE)) ||\n')
    fixed.edit(original, body.finish())
    result[FIXED] = fixed.finish().encode()
    rx = Editor(outputs[RX].decode())
    rx.edit('    const struct pci_dev *pci;\n',
        '    struct task_struct *netdev_tail_task; /* Borrowed only during original synchronous epilogue. */\n'
        '    const void *netdev_tail_object; /* Exact saved callback object, never dereferenced for revocation. */\n'
        '    const struct pci_dev *pci;\n')
    result[RX] = rx.finish().encode()
    root = Editor(outputs[ROOT].decode())
    original = function(root.text, 'static int lsf_stream_root_records_ready_locked(')
    body = Editor(original)
    body.edit('    record = &factory.pool.records[0];\n',
        '    if (state->netdev_tail_task || state->netdev_tail_object) return 0;\n    record = &factory.pool.records[0];\n')
    root.edit(original, body.finish())
    result[ROOT] = root.finish().encode()
    device = Editor(outputs['net/device-prepaid.h'].decode())
    require('LSF_DEVICE_NETDEV_NAME' in device.text and 'LSF_DEVICE_NETDEV_CORE' not in device.text,
        'stream-netdev-core-name-before-stage')
    device.edit('static inline int lsf_device_kind(unsigned int kind)\n',
        'enum { LSF_DEVICE_NETDEV_CORE = 0x16b, LSF_DEVICE_NETDEV_CORE_NAME };\n'
        'static inline int lsf_device_kind(unsigned int kind)\n')
    original = function(device.text, 'static inline int lsf_device_kind(')
    body = Editor(original)
    body.edit('return kind ==',
        'return kind == LSF_DEVICE_NETDEV_CORE || kind == LSF_DEVICE_NETDEV_CORE_NAME || kind ==')
    device.edit(original, body.finish())
    result['net/device-prepaid.h'] = device.finish().encode()
    factory = Editor(outputs['net/factory.c'].decode())
    factory.edit('#include <net/lsf_stream_device_core.h>\n',
        '#include <net/lsf_stream_device_core.h>\n#include <net/lsf_stream_netdev_core_private.h>\n')
    require('factory-stream-netdev-fixed.c' in factory.text, 'stream-netdev-core-fixed-before-stage')
    before = factory.text
    factory.edit(before, before+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "factory-stream-netdev-core.c"\n#endif\n')
    result['net/factory.c'] = factory.finish().encode()
    result[HEADER] = _owned('stream-netdev-core-private.h')
    result['net/factory-stream-netdev-core.c'] = _owned('factory-stream-netdev-core.c')
    return result
