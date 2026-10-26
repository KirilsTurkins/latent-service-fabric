"""Unselected finite NETDEV notification; no file/group/consumer enablement.

Every body starts at its COMPLETE actual declaration. Readonly native helpers
and firmware macro bodies are whole-source pinned; old55/371 is an intermediate.
"""
import hashlib
from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_device_security import function
from tools.host_stream_kernel_cleanup_native import OWNED, require

HEADER = 'include/net/lsf_stream_netdev_notify_private.h'
FRAGMENT = 'net/factory-stream-netdev-notify.c'
PREIMAGES = {'drivers/base/core.c': (158686, '4142cec3dcb3831682835dc1807d8b1d605e0403b6cfca721c5635a1cedbe769'), 'drivers/acpi/glue.c': (10012, 'a7c102b52215ad26bd052a708285c1643e064d676bdb638072e9a62b0adf297e'), 'net/factory.c': (36879, 'b1a99f1e4687dc515010c66e03276f9c5e962ee0477aa56d2557881a7f368b4b')}
DEPENDENCIES = {'drivers/net/virtio_net.c': (194543, '1e0187612413e38c6e839c80c6983d42c3d73924acfe7d725e64cd9cdef7d12b'), 'net/core/dev.c': (332535, '911460f30f10458a729296fcd38eb312fda7b327c75f9516c268282f94756060'), 'net/core/net-sysfs.c': (53929, 'c07ec343e23ca48e635207ba9624c8efd09bcc15c6fdca1f77d937f2628ce331'), 'include/linux/netdevice.h': (170928, 'a3aa5523a162de7cbb9a20dc376c1b190ba7cfc65b83d95f41279f5bf33f8416'), 'include/linux/acpi.h': (45981, '5a47594fd6e64de376b1227b959f80b6129753d4c967a813e09caf9f0ed3e9da'), 'net/factory-private.h': (5468, 'de95bf8ba08437594521011cd0002abf57b07b26879ff372fbd8c023ca7f2a00'), 'include/net/lsf_stream_netdev_directory_private.h': (2714, '845e44ced2aeb21e6594ddc00560717be38a179526ff20366a98169c2aeb5ba9')}
PRIMARY = {'drivers/base/swnode.c': (27174, 'e0531a13b55f42c365c8da4bdcf59ee945484ae78f338d39888ed9b242a7668d'), 'drivers/usb/core/usb-acpi.c': (10650, '5c453c92c6457300d5279381a91bd1215d5624235376e6ef2d20674b378d5211'), 'drivers/usb/core/usb.h': (7555, 'c67b4a827da5bf1fb1bc9316813d590e94665e5c844f091a6f247467b85438af'), 'include/linux/property.h': (20539, '5d2c6fa275ca7600b33d96cfe1652f27a2a85480cf707b7975bffa24d41a136a'), 'include/linux/dev_printk.h': (9975, 'ba476a7261040b824eedb7d55a97c3f65be10870deb73baf8700c4310c56c769'), 'drivers/base/property.c': (45826, '53a22a27eafbe72b0d1454c999aeee25416a48bc626eaefa99a6b8d7dbb5075b')}
BODIES = {'drivers/base/core.c::int device_add(': (5840, '03108e5cf6ddb729a3abab79b68b21d9cdacfad35b813db25d9d62819a4e6b31'), 'drivers/base/core.c::static void device_platform_notify(': (114, '4dade84e628e60b40ec33d69c9aa1c57a4ffba8b106d9371b5e68c6b3b7bddcb'), 'drivers/base/core.c::static void device_platform_notify_remove(': (135, '7aae217939c855ef8392c6650a7ec853542546781d08ab7a1dc0159bc440dcc2'), 'drivers/base/core.c::void set_primary_fwnode(': (648, 'ee997770e0cbf08965b127b0fe72ba42e0e8a2854a8b87d0ed54c4e790318580'), 'drivers/base/core.c::void set_secondary_fwnode(': (236, '946cf7451c5696cd493eadf1ac8d51c052c22661c5c42e7809559acaec9358be'), 'drivers/base/core.c::void device_set_of_node_from_dev(': (185, 'f63455fa9d41631a18f98525aa857f05cc3249e729f50a087b60c7ef800bbbec'), 'drivers/base/core.c::void device_set_node(': (134, 'aef58235c25bf5c1ddcc7ab53103b19bbeeef6879d0afe200812862d6e5b73e9'), 'drivers/acpi/glue.c::static struct acpi_bus_type *acpi_get_bus_type(': (284, '399a16173ebe1215150ed525a6879e4374c34048268c9cf2f011d6aa25c653d2'), 'drivers/acpi/glue.c::int acpi_bind_one(': (2157, '947e40c6d39fd0c0b71e402c9fff619f766b4b4263ec7d3deedd893b8b95a3b7'), 'drivers/acpi/glue.c::void acpi_device_notify(': (851, 'e36cb1ee9da55ecddfd2e4dab39a9f553c5011c2742201f1c950443aea78166a'), 'drivers/acpi/glue.c::void acpi_device_notify_remove(': (285, 'a98019d982656f25e6a77e97105bb971d0af8501e9e8b8e890e30c7e458bf2d6'), 'drivers/base/swnode.c::int device_add_software_node(': (773, '18e7c4ba14ef291d3c7d77df6c20f25df0aefedae35624015d066cc0a7892325'), 'drivers/base/swnode.c::void device_remove_software_node(': (269, '40125186a87ba6e24a5356321bc5c9c104cf3bc9725e03f58a21eb42c5d86377'), 'drivers/base/swnode.c::int device_create_managed_software_node(': (526, '2d2346a7d4aa432e855617aa793f059f8fc2933a3d9410e9559418eca84e2ee6'), 'drivers/base/swnode.c::void software_node_notify(': (404, '3d66bd5698acea95594e2b8bca43589a4c19ee421dcc59a7bb116bea663f318c'), 'drivers/base/swnode.c::void software_node_notify_remove(': (358, '4bdabf37fed5b178b5ef23ba343f41c90eae0bf2c0b9f7966af7a1d8e28108d6')}


def _bound(raw, expected):
    return type(raw) is bytes and (len(raw), hashlib.sha256(raw).hexdigest()) == expected


def _body(text, path, signature):
    raw = function(text, signature)
    require(_bound(raw.encode(), BODIES[path+'::'+signature]), 'notify-complete-function-preimage')
    return raw


def _owned(name):
    raw = (OWNED/name).read_bytes()
    require(0 < len(raw) <= 32768 and b'\r' not in raw, 'notify-owned-source-bound')
    return raw


def _include(editor, anchor):
    editor.edit(anchor, anchor+'#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_netdev_notify_private.h>\n#endif\n')


def _wrap(original, branch):
    # The entire original brace block remains byte-exact as an inner block.
    # Thus no original declaration initializer can precede the refusal cut,
    # and no ordinary evaluation is reordered or cloned speculatively.
    start = original.index('\n{\n')
    return (original[:start]+'\n{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'+branch+
        '#endif\n'+original[start+1:]+'}\n')


def _deny_writer(editor, path, signature, result):
    original = _body(editor.text, path, signature)
    editor.edit(original, _wrap(original,
        '\tif (lsf_factory_stream_netdev_notify_firmware_write(dev)) '+result+'\n'))


def _writers(core):
    path = 'drivers/base/core.c'
    for signature in ('void set_primary_fwnode(', 'void set_secondary_fwnode(',
        'void device_set_of_node_from_dev(', 'void device_set_node('):
        _deny_writer(core, path, signature, 'return;')


def _core_notify(core):
    # These original static helpers REMAIN BYTE-EXACT, including call order.
    _body(core.text, 'drivers/base/core.c', 'static void device_platform_notify(')
    _body(core.text, 'drivers/base/core.c', 'static void device_platform_notify_remove(')
    original = _body(core.text, 'drivers/base/core.c', 'int device_add(')
    body = Editor(original)
    old = """		if (stream) {
			/* The directory exists, but no platform notification, file or
			 * ADD event has run. Do NOT enter attrError's unpaired REMOVE
			 * notifications. Use the original directory/glue/parent unwind. */
			error = -EOPNOTSUPP;
			glue_dir = get_glue_dir(dev);
			kobject_del(&dev->kobj);
			goto Error;
		}
"""
    new = """		if (stream) {
			int notified = lsf_prepaid_stream_netdev_platform_notify(dev);
			if (notified < 0) return -EOPNOTSUPP;
			if (notified && lsf_prepaid_stream_netdev_platform_remove(dev) != 1)
				return -EOPNOTSUPP;
			/* Zero means the registry/config profile was refused BEFORE
			 * notification; positive means actual notification and paired
			 * removal completed. No file or ADD event has run. Never enter
			 * attrError's unperformed KOBJ_REMOVE in either case. */
			error = -EOPNOTSUPP;
			glue_dir = get_glue_dir(dev);
			kobject_del(&dev->kobj);
			goto Error;
		}
"""
    body.edit(old, new)
    core.edit(original, body.finish())
    wrappers = """
int lsf_prepaid_stream_netdev_platform_notify(struct device *dev)
{
    int profile = lsf_factory_stream_netdev_notify_profile(dev);
    if (profile != 1) return -EOPNOTSUPP;
    profile = lsf_prepaid_stream_netdev_acpi_probe(dev);
    if (profile <= 0) return profile;
    /* Both ACTUAL original notifications run. Their owned effect-site gates
     * revalidate after the probe; a later unknown profile poisons the existing
     * bank and is observed below, never misreported as a successful void call. */
    device_platform_notify(dev);
    /* No next birth is admitted: this path stops before the first file.
     * Lifetime, not a renewed constructor deadline, gates paired cleanup. */
    return lsf_factory_stream_netdev_notify_lifetime(dev) == 1 ? 1 : -EOPNOTSUPP;
}

int lsf_prepaid_stream_netdev_platform_remove(struct device *dev)
{
    if (lsf_factory_stream_netdev_notify_lifetime(dev) != 1) return -EOPNOTSUPP;
    device_platform_notify_remove(dev);
    return lsf_factory_stream_netdev_notify_lifetime(dev) == 1 ? 1 : -EOPNOTSUPP;
}
"""
    core.edit(core.text, core.text+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'+wrappers+'#endif\n')


def _acpi(glue):
    path = 'drivers/acpi/glue.c'
    # Full, file-local clone; caller owns the ONE original read section.
    old_lookup = _body(glue.text, path, 'static struct acpi_bus_type *acpi_get_bus_type(')
    lookup = Editor(old_lookup)
    lookup.edit('static struct acpi_bus_type *acpi_get_bus_type(',
        'static struct acpi_bus_type *lsf_stream_netdev_acpi_get_bus_type_locked(')
    lookup.edit('\tdown_read(&bus_type_sem);\n', '\tlockdep_assert_held(&bus_type_sem);\n')
    lookup.edit('\tup_read(&bus_type_sem);\n\treturn ret;', '\treturn ret;')
    lookup = lookup.finish()
    helpers = """
/* No unbounded callback eligibility: the actual locked list is empty or the
 * one exact builtin USB registration. Unknown/multiple entries refuse before
 * invoking ANY match/bind callback. Original register/unregister write locking
 * protects that actual static object's lifetime for the entire matching loop. */
static int lsf_stream_netdev_acpi_registry_locked(void)
{
    struct acpi_bus_type *type;
    lockdep_assert_held(&bus_type_sem);
    if (list_empty(&bus_type_list)) return 1;
    if (!list_is_singular(&bus_type_list)) return 0;
    type = list_first_entry(&bus_type_list, struct acpi_bus_type, list);
    return lsf_prepaid_stream_netdev_usb_acpi_type(type) == 1;
}

static int lsf_stream_netdev_acpi_compiled_profile(void)
{
#if !IS_ENABLED(CONFIG_ACPI) || !IS_BUILTIN(CONFIG_USB) || IS_ENABLED(CONFIG_OF) || \
    defined(CONFIG_DYNAMIC_DEBUG) || defined(CONFIG_DYNAMIC_DEBUG_CORE) || defined(DEBUG)
    return 0;
#else
    return 1;
#endif
}

int lsf_prepaid_stream_netdev_acpi_probe(struct device *dev)
{
    int result;
    if (lsf_factory_stream_netdev_notify_profile(dev) != 1) return -EOPNOTSUPP;
    if (!lsf_stream_netdev_acpi_compiled_profile()) return 0;
    down_read(&bus_type_sem);
    result = lsf_stream_netdev_acpi_registry_locked();
    up_read(&bus_type_sem);
    return result;
}
"""
    original = _body(glue.text, path, 'void acpi_device_notify(')
    private = Editor(original)
    private.edit('void acpi_device_notify(', 'static int lsf_stream_netdev_acpi_notify(')
    private.edit('\tint ret;\n', '\tint ret;\n\n'
        '\tif (lsf_factory_stream_netdev_notify_profile(dev) != 1) return -EOPNOTSUPP;\n'
        '\tif (!lsf_stream_netdev_acpi_compiled_profile()) return 0;\n'
        '\tdown_read(&bus_type_sem);\n'
        '\tif (!lsf_stream_netdev_acpi_registry_locked()) {\n'
        '\t\tup_read(&bus_type_sem);\n\t\treturn 0;\n\t}\n')
    private.edit('\tret = acpi_bind_one(dev, NULL);\n', '\tret = acpi_bind_one(dev, NULL);\n'
        '\tif (ret != -EINVAL) {\n\t\tup_read(&bus_type_sem);\n'
        '\t\tlsf_factory_stream_netdev_directory_retain_unknown();\n'
        '\t\treturn -EOPNOTSUPP;\n\t}\n')
    private.edit('\t\tstruct acpi_bus_type *type = acpi_get_bus_type(dev);\n',
        '\t\tstruct acpi_bus_type *type = lsf_stream_netdev_acpi_get_bus_type_locked(dev);\n'
        '\t\tup_read(&bus_type_sem);\n'
        '\t\tif (type) {\n\t\t\tlsf_factory_stream_netdev_directory_retain_unknown();\n'
        '\t\t\treturn -EOPNOTSUPP;\n\t\t}\n')
    private.edit('\treturn;\n', '\treturn 1;\n')
    private.edit('\tdev_dbg(dev, "No ACPI support\\n");\n',
        '\tdev_dbg(dev, "No ACPI support\\n");\n\treturn 1;\n')
    private = private.finish()
    public = _wrap(original,
        '\t{\n\t\tint owned = lsf_factory_stream_netdev_notify_kind(dev);\n'
        '\t\tif (owned < 0) return;\n\t\tif (owned) {\n'
        '\t\t\tif (lsf_stream_netdev_acpi_notify(dev) != 1)\n'
        '\t\t\t\tlsf_factory_stream_netdev_directory_retain_unknown();\n'
        '\t\t\treturn;\n\t\t}\n\t}\n')
    glue.edit(original, '#ifdef CONFIG_LSF_STREAM_FACTORY\n'+helpers+lookup+private+'#endif\n'+public)
    # An unexpected non-NULL input/local companion cannot reach the owned
    # allocation path. This is not a native field writer/lifetime lock; the
    # earlier NETDEV_POST_INIT/direct-writer prerequisite remains unqualified.
    original = _body(glue.text, path, 'int acpi_bind_one(')
    body = Editor(original)
    body.edit('\tint retval = -EINVAL;\n', '\tint retval = -EINVAL;\n\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t{\n\t\tint owned = lsf_factory_stream_netdev_notify_kind(dev);\n'
        '\t\tif (owned < 0) return -EOPNOTSUPP;\n'
        '\t\tif (owned && (acpi_dev || lsf_factory_stream_netdev_notify_lifetime(dev) != 1)) {\n'
        '\t\t\tlsf_factory_stream_netdev_directory_retain_unknown();\n'
        '\t\t\treturn -EOPNOTSUPP;\n\t\t}\n\t}\n#endif\n')
    body.edit('\tacpi_dev_get(acpi_dev);\n', '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (lsf_factory_stream_netdev_notify_kind(dev)) {\n'
        '\t\tlsf_factory_stream_netdev_directory_retain_unknown();\n'
        '\t\treturn -EOPNOTSUPP;\n\t}\n#endif\n\tacpi_dev_get(acpi_dev);\n')
    glue.edit(original, body.finish())
    original = _body(glue.text, path, 'void acpi_device_notify_remove(')
    glue.edit(original, _wrap(original,
        '\tif (lsf_factory_stream_netdev_notify_lifetime(dev) < 0) return;\n'))


def _software(software):
    path = 'drivers/base/swnode.c'
    for signature, failure in (
        ('int device_add_software_node(', 'return -EOPNOTSUPP;'),
        ('void device_remove_software_node(', 'return;'),
        ('int device_create_managed_software_node(', 'return -EOPNOTSUPP;'),
    ):
        _deny_writer(software, path, signature, failure)
    for signature in ('void software_node_notify(', 'void software_node_notify_remove('):
        original = _body(software.text, path, signature)
        body = Editor(original)
        name = signature.split('void ', 1)[1].split('(', 1)[0]
        private = 'lsf_stream_netdev_'+name
        body.edit(signature, 'static void '+private+'(')
        body.edit('\tswnode = dev_to_swnode(dev);\n',
            '\tif (lsf_factory_stream_netdev_notify_lifetime(dev) < 0) return;\n'
            '\tswnode = dev_to_swnode(dev);\n'
            '\tif (lsf_factory_stream_netdev_notify_software_decision(dev, swnode) < 0) return;\n'
            )
        branch = ('\t{\n\t\tint owned = lsf_factory_stream_netdev_notify_kind(dev);\n'
            '\t\tif (owned < 0) return;\n'
            '\t\tif (owned) { '+private+'(dev); return; }\n\t}\n')
        software.edit(original, '#ifdef CONFIG_LSF_STREAM_FACTORY\n'+body.finish()+
            '#endif\n'+_wrap(original, branch))


def transform(outputs, primary):
    require(type(outputs) is dict and type(primary) is dict and set(primary) == set(PRIMARY) and
        HEADER not in outputs and FRAGMENT not in outputs, 'notify-fresh-closed-source')
    for name, expected in {**PREIMAGES, **DEPENDENCIES}.items():
        require(_bound(outputs.get(name), expected), 'notify-whole-existing-source-preimage')
    for name, expected in PRIMARY.items():
        require(_bound(primary.get(name), expected), 'notify-whole-official-primary')
        require(name not in outputs or outputs[name] == primary[name], 'notify-never-reset-transformed-source')
    require('drivers/base/swnode.c' not in outputs and 'drivers/usb/core/usb-acpi.c' not in outputs,
        'notify-original-new-translation-units-only')
    result = dict(outputs)
    core = Editor(outputs['drivers/base/core.c'].decode())
    _include(core, '#include <net/lsf_stream_netdev_directory_private.h>\n')
    _writers(core)
    _core_notify(core)
    result['drivers/base/core.c'] = core.finish().encode()
    glue = Editor(outputs['drivers/acpi/glue.c'].decode())
    _include(glue, '#include "internal.h"\n')
    _acpi(glue)
    result['drivers/acpi/glue.c'] = glue.finish().encode()
    software = Editor(primary['drivers/base/swnode.c'].decode())
    _include(software, '#include "base.h"\n')
    _software(software)
    result['drivers/base/swnode.c'] = software.finish().encode()
    usb = Editor(primary['drivers/usb/core/usb-acpi.c'].decode())
    _include(usb, '#include "hub.h"\n')
    bridge = """
#if defined(CONFIG_LSF_STREAM_FACTORY) && IS_BUILTIN(CONFIG_USB) && IS_ENABLED(CONFIG_ACPI)
int lsf_prepaid_stream_netdev_usb_acpi_type(const struct acpi_bus_type *type)
{
    /* Identity first: do not dereference an unknown registration. Native
     * register/unregister's ORIGINAL bus_type_sem protects list lifetime. */
    return type == &usb_acpi_bus && type->match == usb_acpi_bus_match &&
        type->find_companion == usb_acpi_find_companion && !type->setup;
}
#endif
"""
    usb.edit(usb.text, usb.text+bridge)
    result['drivers/usb/core/usb-acpi.c'] = usb.finish().encode()
    factory = Editor(outputs['net/factory.c'].decode())
    factory.edit('#include "factory-stream-netdev-directory.c"\n',
        '#include "factory-stream-netdev-directory.c"\n#include "factory-stream-netdev-notify.c"\n')
    result['net/factory.c'] = factory.finish().encode()
    result[HEADER] = _owned('stream-netdev-notify-private.h')
    result[FRAGMENT] = _owned('factory-stream-netdev-notify.c')
    require(b'lsf_factory_selected_consumer(void)\n{\n    return NULL;\n}' in
        result['net/factory-private.h'], 'notify-consumer-remains-unselected')
    return result
