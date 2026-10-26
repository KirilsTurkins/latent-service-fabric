"""Unselected real NETDEV class-directory birth and original kobject tail.

Does not lift class/kernfs/uevent readiness guards or claim source completeness.
Ordinary devices retain original methods; actual private parent/type is required.
"""
import hashlib
from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_device_security import function
from tools.host_stream_kernel_cleanup_native import OWNED, require

CORE = 'drivers/base/core.c'
KOBJECT = 'lib/kobject.c'
SYSFS = 'net/core/net-sysfs.c'
HELPER = 'net/factory-device-core.c'
HEADER = 'include/net/lsf_stream_netdev_classdir_private.h'
PREVIOUS = {'drivers/base/core.c': (152328, 'e7db197682d53c55bd0ebd71c389ccfc5e5db6392526d9d1d18f76d1d80edcbb'), 'lib/kobject.c': (30780, '496b7cc9cc1c68cb48731e37b62230a8db30615e18459f12842cbe089dbe47e5'), 'net/core/net-sysfs.c': (53375, 'c6d501abeae8ef20f9ef83ea0fff4948bc542231632d997aa3ff91735815b08d'), 'net/factory-device-core.c': (12878, '1fedcccab7878677f4ee32a5c2a360764f23680b1378ffc45e84eb1d80f9aad0'), 'net/factory.c': (36414, '55bcdba03824ed1ce787007a7070b33eded481d405addd4ce83194d668933f29')}
PINS = {'static void class_dir_release(': (114, '5a954b8b5207d66014da36472daa96213467cc32034ac1d8169442e115d35df1'), 'static struct kobject *class_dir_create_and_add(': (505, '5018878ccdf87615f2f4247b4f2253d428234d1e9596145313fec163c450ae1b'), 'static struct kobject *get_device_parent(': (1557, 'a14069ba3fc3b8d67d4ba0393aac09e8531ebbd22fd8a1c16f781b4fdef965f1')}


def _owned(name):
    raw = (OWNED/name).read_bytes()
    require(0 < len(raw) <= 32*1024 and b'\r' not in raw, 'stream-classdir-owned-bound')
    return raw


def _body(text, signature):
    raw = function(text, signature)
    size, digest = PINS[signature]
    require(len(raw.encode()) == size and hashlib.sha256(raw.encode()).hexdigest() == digest,
        'stream-classdir-original-body')
    return raw


def _create(original):
    body = Editor(original)
    body.edit('class_dir_create_and_add(struct subsys_private *sp,',
        'lsf_stream_netdev_classdir_create_and_add(struct device *device,\n'
        '\t\tstruct subsys_private *sp,')
    body.edit('\tdir = kzalloc(sizeof(*dir), GFP_KERNEL);\n',
        '\tdir = lsf_factory_stream_netdev_classdir_allocate(device);\n')
    body.edit('\tretval = kobject_add(&dir->kobj, parent_kobj, "%s", sp->class->name);\n',
        '\tretval = lsf_factory_stream_netdev_classdir_name(dir, &dir->kobj, sp->class->name);\n'
        '\tif (!retval) retval = lsf_factory_stream_netdev_classdir_publish(device, dir);\n'
        '\tif (retval < 0) {\n\t\tkobject_put(&dir->kobj);\n\t\treturn ERR_PTR(retval);\n\t}\n'
        '\t/* The exact original fixed class name is already paid and installed.\n'
        '\t * NULL format preserves original kobject_add parent/kset/ref actions. */\n'
        '\tretval = kobject_add(&dir->kobj, parent_kobj, NULL);\n')
    return body.finish()


def _parent(original):
    body = Editor(original)
    body.edit('static struct kobject *get_device_parent(',
        'struct kobject *lsf_prepaid_stream_netdev_parent(')
    body.edit('\tstruct subsys_private *sp = class_to_subsys(dev->class);\n',
        '\tstruct subsys_private *sp;\n')
    body.edit('\tstruct kobject *kobj = NULL;\n',
        '\tstruct kobject *kobj = NULL;\n\n'
        '\tif (lsf_factory_stream_netdev_classdir_select(dev, parent) != 1)\n'
        '\t\treturn ERR_PTR(-EOPNOTSUPP);\n'
        '\tsp = class_to_subsys(dev->class);\n'
        '\t/* The selected fixed net class requires its real positive subsystem\n'
        '\t * reference. Missing registration cannot use the default-root path. */\n'
        '\tif (!sp) return ERR_PTR(-EOPNOTSUPP);\n')
    body.edit('\t\t\tkobj = kobject_get(k);\n',
        '\t\t\tif (!lsf_factory_stream_netdev_classdir_current(dev, k)) {\n'
        '\t\t\t\tspin_unlock(&sp->glue_dirs.list_lock);\n'
        '\t\t\t\tmutex_unlock(&gdp_mutex);\n\t\t\t\tsubsys_put(sp);\n'
        '\t\t\t\treturn ERR_PTR(-EOPNOTSUPP);\n\t\t\t}\n'
        '\t\t\tkobj = kobject_get(k);\n')
    body.edit('k = class_dir_create_and_add(sp, parent_kobj);',
        'k = lsf_stream_netdev_classdir_create_and_add(dev, sp, parent_kobj);')
    return body.finish()


def transform(outputs):
    require(type(outputs) is dict and HEADER not in outputs and
        all(type(outputs.get(n)) is bytes for n in PREVIOUS) and
        type(outputs.get('net/device-prepaid.h')) is bytes, 'stream-classdir-stage')
    for n, (size, digest) in PREVIOUS.items():
        raw = outputs[n]
        require(len(raw) == size and hashlib.sha256(raw).hexdigest() == digest,
            'stream-classdir-reviewed-core-r2-preimage')
    result = dict(outputs)
    core = Editor(outputs[CORE].decode())
    core.edit('#include <net/lsf_stream_netdev_core_private.h>\n',
        '#include <net/lsf_stream_netdev_core_private.h>\n#include <net/lsf_stream_netdev_classdir_private.h>\n')
    create = _create(_body(core.text, 'static struct kobject *class_dir_create_and_add('))
    original = _body(core.text, 'static struct kobject *get_device_parent(')
    private_parent = _parent(original)
    body = Editor(original)
    declaration, original_body = original.split('\n{\n', 1)
    body.edit(original, declaration+'\n{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tint stream_owned = lsf_factory_stream_netdev_classdir_select(dev, parent);\n'
        '\tif (stream_owned < 0) return ERR_PTR(stream_owned);\n'
        '\tif (stream_owned) return lsf_prepaid_stream_netdev_parent(dev, parent);\n#endif\n'
        '\t{\n'+original_body[:-2]+'\t}\n}\n')
    core.edit(original, body.finish())
    original = _body(core.text, 'static void class_dir_release(')
    body = Editor(original)
    body.edit('\tkfree(dir);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (!lsf_factory_stream_netdev_classdir_queue(dir))\n#endif\n\tkfree(dir);\n')
    core.edit(original, body.finish())
    before = core.text
    core.edit(before, before+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'+create+private_parent+"""
int lsf_prepaid_stream_netdev_classdir_initialized(const struct kobject *kobj)
{
    return kobj && kobj->ktype == &class_dir_ktype && kobj->state_initialized;
}

int lsf_prepaid_stream_netdev_classdir_geometry(unsigned long *bytes, unsigned long *alignment)
{
    if (!bytes || !alignment || offsetof(struct class_dir, kobj) != 0 ||
        __alignof__(struct class_dir) > 64u) return -EOPNOTSUPP;
    *bytes = sizeof(struct class_dir);
    *alignment = __alignof__(struct class_dir);
    return 0;
}
#endif
""")
    result[CORE] = core.finish().encode()
    sysfs = Editor(outputs[SYSFS].decode())
    sysfs.edit('#include <net/lsf_stream_netdev_core_private.h>\n',
        '#include <net/lsf_stream_netdev_core_private.h>\n#include <net/lsf_stream_netdev_classdir_private.h>\n')
    before = sysfs.text
    sysfs.edit(before, before+"""
#ifdef CONFIG_LSF_STREAM_FACTORY
int lsf_prepaid_stream_netdev_class_known(const struct class *candidate)
{
    return candidate == &net_class && candidate->name && !strcmp(candidate->name, "net") &&
        candidate->dev_release == netdev_release && candidate->dev_groups == net_class_groups &&
        candidate->dev_uevent == netdev_uevent && candidate->ns_type == &net_ns_type_operations &&
        candidate->namespace == net_namespace && candidate->get_ownership == net_get_ownership;
}
#endif
""")
    result[SYSFS] = sysfs.finish().encode()
    kobj = Editor(outputs[KOBJECT].decode())
    kobj.edit('#include <net/lsf_stream_netdev_core_private.h>\n',
        '#include <net/lsf_stream_netdev_core_private.h>\n#include <net/lsf_stream_netdev_classdir_private.h>\n')
    original = function(kobj.text, 'static void lsf_prepaid_kobject_cleanup(')
    body = Editor(original)
    body.edit('\t\tif (!lsf_factory_stream_netdev_core_name_return(kobj, name))\n',
        '\t\tif (!lsf_factory_stream_netdev_classdir_name_return(kobj, name) &&\n'
        '\t\t    !lsf_factory_stream_netdev_core_name_return(kobj, name))\n')
    kobj.edit(original, body.finish())
    result[KOBJECT] = kobj.finish().encode()
    helper = Editor(outputs[HELPER].decode())
    original = function(helper.text, 'int lsf_factory_device_core_tail_enter(')
    body = Editor(original)
    body.edit('    int stream_kind = lsf_factory_stream_netdev_core_classify(kobject, 1);\n',
        '    int stream_kind;\n'
        '    int classdir = lsf_factory_stream_netdev_classdir_tail_enter(kobject);\n'
        '    if (classdir) return classdir;\n'
        '    stream_kind = lsf_factory_stream_netdev_core_classify(kobject, 1);\n')
    helper.edit(original, body.finish())
    original = function(helper.text, 'void lsf_factory_device_core_tail_finish(')
    body = Editor(original)
    body.edit('    int stream_result = lsf_factory_stream_netdev_core_tail_finish(kobject);\n',
        '    int stream_result;\n'
        '    int classdir = lsf_factory_stream_netdev_classdir_tail_finish(kobject);\n'
        '    if (classdir) return;\n'
        '    stream_result = lsf_factory_stream_netdev_core_tail_finish(kobject);\n')
    helper.edit(original, body.finish())
    result[HELPER] = helper.finish().encode()
    device = Editor(outputs['net/device-prepaid.h'].decode())
    require('LSF_DEVICE_NETDEV_CORE_NAME' in device.text and 'LSF_DEVICE_NETDEV_CLASSDIR' not in device.text,
        'stream-classdir-core-before-stage')
    device.edit('static inline int lsf_device_kind(unsigned int kind)\n',
        'enum { LSF_DEVICE_NETDEV_CLASSDIR = 0x16d, LSF_DEVICE_NETDEV_CLASSDIR_NAME };\n'
        'static inline int lsf_device_kind(unsigned int kind)\n')
    original = function(device.text, 'static inline int lsf_device_kind(')
    body = Editor(original)
    body.edit('return kind ==',
        'return kind == LSF_DEVICE_NETDEV_CLASSDIR || kind == LSF_DEVICE_NETDEV_CLASSDIR_NAME || kind ==')
    device.edit(original, body.finish())
    result['net/device-prepaid.h'] = device.finish().encode()
    factory = Editor(outputs['net/factory.c'].decode())
    factory.edit('#include <net/lsf_stream_netdev_core_private.h>\n',
        '#include <net/lsf_stream_netdev_core_private.h>\n#include <net/lsf_stream_netdev_classdir_private.h>\n')
    before = factory.text
    factory.edit(before, before+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "factory-stream-netdev-classdir.c"\n#endif\n')
    result['net/factory.c'] = factory.finish().encode()
    result[HEADER] = _owned('stream-netdev-classdir-private.h')
    result['net/factory-stream-netdev-classdir.c'] = _owned('factory-stream-netdev-classdir.c')
    return result
