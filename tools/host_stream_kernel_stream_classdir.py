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


# Separate, UNSELECTED source stage. The original transform above is unchanged.
# This closes only the empty class_dir directory; later NETDEV/attribute/queue
# readiness cuts remain original and no owner or enabled profile calls it.
REGISTRATION_HEADER = 'include/net/lsf_stream_classdir_registration_private.h'
REGISTRATION_FRAGMENT = 'net/factory-stream-classdir-registration.c'
REGISTRATION_PREVIOUS = {'drivers/base/core.c': (156264, '63490dfe942d2dcc17d16902a77cde82317d64381d49c9e247c6ebdf76668403'), 'lib/kobject.c': (30901, 'bc8d7b2ec6df8407d27dbc037a96decbd3c555bf88205e44dbe20e50240fba45'), 'fs/sysfs/dir.c': (5980, 'ed16f630f6a72803b83b0c3d5df43176f0cd4d32c14454f3a5a4e8f43f50a324'), 'fs/kernfs/dir.c': (53024, 'b11c838c7b69112131068ae542cf6114d7cffb99a6193680e9769b9552912440'), 'lib/idr.c': (19984, '8d681ffb5578ae2aff1f5921382f93a98ae6b37e78275fd6b3b4e3c9b7af5e70'), 'lib/radix-tree.c': (49800, '0034524e5696f9f8460373f10ff1880da04b4b86041c0a22480ae5624b323591'), 'security/security.c': (185609, '3341ceb0348fd7034ee953755c71a102c5cbf4ab28be13dd734f7a93ad2e389c'), 'security/selinux/hooks.c': (208914, 'be29cf703ca3beb339b4f224c7982112e2058b9537657c9a55ebb2e2b898bac9'), 'net/factory-device-sysfs.c': (4390, '3d0fe4d48be85c807766289a850dec492f0d136627713ad74a1ebbd5274b8688'), 'net/device-prepaid.h': (18030, 'a1949573f7dfd9f238751dc8b9e2feb9d3e4813f311c0fe2a8c0e7f5034c382c'), 'net/factory-stream-netdev-classdir.c': (18406, 'e7416ddc0453d1d837f096e5cdfdc6843075bf198192b8a1cfa9b6c8b8ff292b'), 'net/factory-stream-stop.c': (6004, 'bf12f4cfb4b416a82988af07640a8ce6008f66e3c6a43e6c617ac498e18aa82a'), 'net/factory.c': (36592, 'b0ea30b948fb5d9ff654002fa99fb0e76841c343f4f8a0f6c6c524152dd1aa9a')}
REGISTRATION_BODIES = {'int lsf_factory_device_sysfs_iattrs(': (591, '3e3c76cbc0b822ad91e87be1fa27fd08d08f75fa792e17931ba29aeb575e5b6d'), 'int lsf_factory_stream_netdev_classdir_tail_finish(': (1430, '36591ed9f6dbc747d0300d4a3944847e353db309e4190f15bb3c7a6d10f0d941'), 'int lsf_prepaid_device_idr_alloc_cyclic(': (686, '32bd6b4fa8c3b14f12395d044fadb7c53a2ec01e4be9ced7437d707600d3b023'), 'static int lsf_prepaid_device_idr_alloc_u32(': (846, '305f2a7eb0541a06c28de29643add5a606aeb8d333cd1dce114a6e1976e2b6ca'), 'int security_kernfs_init_security(': (736, '00e05f904d5599d9ea1f9c51d56089b054f3b4c349fe30f3a4842e7c2936b2ad'), 'int sysfs_create_dir_ns(': (880, '120e018bbb9d2d6de4fed4f4668568f0e12587ac609aca5fa1aab459a2859978'), 'static int create_dir(': (1175, '31b08e705b127ab1bfe92f162b6e606fcf7692ffa1dd438ede172ef81d2364c2'), 'static int lsf_prepaid_device_radix_extend(': (1574, '544d2b545580c8b807a4410b1fd547f2446bb964f96559ef78c835897388375b'), 'static int lsf_prepaid_device_sysfs_create_dir_ns(': (837, '721756667f8af9889eb7da30daa773d9a8a5da500d9923a4e5cdde6470698fe2'), 'static int selinux_kernfs_init_security(': (1557, '69d4fc00d62c614c2c606f350da98fefc5f0dd2da0e0eff0743144abf3499b8c'), 'static struct kernfs_node *lsf_prepaid_device_kernfs_birth(': (2098, 'e0fea9890bb9253a73c77fe31dfc38d7b4b8850e6900ec973e199415d69face6'), 'static struct radix_tree_node *\nlsf_prepaid_device_radix_node_alloc(': (744, '7506237afa9875231a2e9e3f86488e0f1bf67eb44ba6a7837947148aa831a48f'), 'static void kernfs_free_rcu(': (554, 'a83b68f5903a58fa342e13214e5bafbe55dbbc2bcf5261bbca44cdda8106d30b'), 'static void lsf_prepaid_device_sysfs_warn_dup(': (477, '21ad99929817844a8d7ac0c786857245f9f297e115c875f59e0cee48691a879a'), 'struct kernfs_node *lsf_prepaid_device_kernfs_create_dir_ns(': (612, 'c7967eb3fcb681793c9b715a94443568322073633ff7e381decc4389daf46af4'), 'struct kernfs_node *lsf_prepaid_device_kernfs_new_node(': (726, '0d46cbab4a8cad60b9a5fd1c353b366c5f0633b9375a6594b3c5946161eb58b0'), 'void __rcu **lsf_prepaid_device_idr_get_free(': (2199, 'f9398e577413d029216092115cd9fb276731674ba0bee27db68d64003d7b903e'), 'void radix_tree_node_rcu_free(': (1202, '4dff696a157a87c75406623e0a043c32e2835d5303552d8aa19510a663cb94bf')}


def _registration_body(text, signature):
    raw = function(text, signature)
    size, digest = REGISTRATION_BODIES[signature]
    require(len(raw.encode()) == size and hashlib.sha256(raw.encode()).hexdigest() == digest,
        'stream-classdir-registration-body-preimage')
    return raw


def _registration_clone(original, renames):
    """Closed identifier projection, with an exact inverse to the original body."""
    import re
    require(len(set(renames.values())) == len(renames) and
        not any(re.search(r'\b'+re.escape(n)+r'\b', original) for n in renames.values()),
        'stream-classdir-registration-rename-disjoint')
    pattern = re.compile(r'\b('+'|'.join(map(re.escape, renames))+r')\b')
    result = pattern.sub(lambda m: renames[m[0]], original)
    inverse = {v: k for k, v in renames.items()}
    pattern = re.compile(r'\b('+'|'.join(map(re.escape, inverse))+r')\b')
    require(pattern.sub(lambda m: inverse[m[0]], result) == original,
        'stream-classdir-registration-clone-inverse')
    return result


def _registration_renames():
    return {
        'lsf_device_registration_source': 'lsf_stream_classdir_registration_source',
        'lsf_factory_device_registration_kobject': 'lsf_factory_stream_classdir_kobject',
        'lsf_factory_device_registration_node': 'lsf_factory_stream_classdir_node',
        'lsf_factory_device_registration_current': 'lsf_factory_stream_classdir_current',
        'lsf_factory_device_registration_allocate': 'lsf_factory_stream_classdir_allocate',
        'lsf_factory_device_sysfs_name': 'lsf_factory_stream_classdir_name',
        'LSF_REGISTRATION_KIND_NODE': 'LSF_STREAM_CLASSDIR_NODE',
        'LSF_REGISTRATION_KIND_NAME': 'LSF_STREAM_CLASSDIR_NAME',
        'LSF_REGISTRATION_KIND_IDR_NODE': 'LSF_STREAM_CLASSDIR_IDR',
        'lsf_prepaid_device_kobject_registration_ready': 'lsf_prepaid_stream_classdir_registration_ready',
        'lsf_prepaid_device_sysfs_warn_dup': 'lsf_prepaid_stream_classdir_warn_dup',
        'lsf_prepaid_device_sysfs_create_dir_ns': 'lsf_prepaid_stream_classdir_sysfs_create_dir_ns',
        'lsf_prepaid_device_kernfs_birth': 'lsf_prepaid_stream_classdir_kernfs_birth',
        'lsf_prepaid_device_kernfs_new_node': 'lsf_prepaid_stream_classdir_kernfs_new_node',
        'lsf_prepaid_device_kernfs_create_dir_ns': 'lsf_prepaid_stream_classdir_kernfs_create_dir_ns',
        'lsf_prepaid_device_idr_alloc_u32': 'lsf_prepaid_stream_classdir_idr_alloc_u32',
        'lsf_prepaid_device_idr_alloc_cyclic': 'lsf_prepaid_stream_classdir_idr_alloc_cyclic',
        'lsf_prepaid_device_idr_get_free': 'lsf_prepaid_stream_classdir_idr_get_free',
        'lsf_prepaid_device_radix_node_alloc': 'lsf_prepaid_stream_classdir_radix_node_alloc',
        'lsf_prepaid_device_radix_extend': 'lsf_prepaid_stream_classdir_radix_extend',
    }


def _registration_include(editor):
    old = '#include <net/lsf_stream_device_sysfs.h>\n'
    if old not in editor.text:
        old = '#include <net/lsf_stream_device_registration.h>\n'
    if old not in editor.text:
        old = '#include <net/lsf_stream_netdev_classdir_private.h>\n'
    editor.edit(old, old+'#include <net/lsf_stream_classdir_registration_private.h>\n')


def _registration_append(editor, fragment):
    old = editor.text
    editor.edit(old, old+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'+fragment+'#endif\n')


def _registration_dispatch(editor, signature, branch):
    original = _registration_body(editor.text, signature)
    body = Editor(original)
    body.edit('\n{\n', '\n{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'+branch+'#endif\n')
    editor.edit(original, body.finish())


def registration_transform(outputs):
    """Typed empty classdir descendants and actual delayed returns; not enabled."""
    require(type(outputs) is dict and REGISTRATION_HEADER not in outputs and
        REGISTRATION_FRAGMENT not in outputs and bool(REGISTRATION_PREVIOUS),
        'stream-classdir-registration-stage')
    for name, (size, digest) in REGISTRATION_PREVIOUS.items():
        raw = outputs.get(name)
        require(type(raw) is bytes and len(raw) == size and
            hashlib.sha256(raw).hexdigest() == digest,
            'stream-classdir-registration-fifty-source-preimage')
    result = dict(outputs)
    rename = _registration_renames()

    core = Editor(outputs[CORE].decode())
    _registration_include(core)
    _registration_append(core, '''int lsf_prepaid_stream_classdir_registration_ready(const struct kobject *kobj)
{
    struct lsf_stream_classdir_registration_source source;
    if (lsf_factory_stream_classdir_kobject(kobj, &source) != 1 ||
        lsf_factory_stream_classdir_current(source) != 1) return 0;
    return kobj->ktype == &class_dir_ktype && !class_dir_ktype.default_groups &&
        class_dir_ktype.release == class_dir_release &&
        class_dir_ktype.child_ns_type == class_dir_child_ns_type &&
        lsf_prepaid_stream_netdev_class_known(to_class_dir(kobj)->class);
}
''')
    result[CORE] = core.finish().encode()

    kobj = Editor(outputs[KOBJECT].decode())
    _registration_include(kobj)
    original = _registration_body(kobj.text, 'static int create_dir(')
    private = _registration_clone(original, rename | {'create_dir': 'lsf_stream_classdir_create_dir'})
    private_body = Editor(private)
    private_body.edit('owned < 0 || (owned && lsf_prepaid_stream_classdir_registration_ready(kobj) != 1)',
        'owned != 1 || lsf_prepaid_stream_classdir_registration_ready(kobj) != 1')
    # A class_dir has no default groups; the real common namespace/ref actions
    # remain unchanged in this private clone. The complete old body stays below.
    kobj.edit(original, '#ifdef CONFIG_LSF_STREAM_FACTORY\n'+private_body.finish()+'#endif\n'+original)
    _registration_dispatch(kobj, 'static int create_dir(', '''\t{
\t\tstruct lsf_stream_classdir_registration_source stream_source;
\t\tint stream = lsf_factory_stream_classdir_kobject(kobj, &stream_source);
\t\tif (stream < 0) return -EOPNOTSUPP;
\t\tif (stream) return lsf_stream_classdir_create_dir(kobj);
\t}
''')
    result[KOBJECT] = kobj.finish().encode()

    sysfs = Editor(outputs['fs/sysfs/dir.c'].decode())
    _registration_include(sysfs)
    warning = _registration_clone(_registration_body(sysfs.text,
        'static void lsf_prepaid_device_sysfs_warn_dup('), rename)
    # Optional PATH_MAX warning storage is NOT a fixed-name birth. Refuse the
    # original optional allocation, preserving its NULL-buffer diagnostic branch
    # and the actual EEXIST result, without an ambient allocation or name adoption.
    warning_body = Editor(warning)
    warning_body.edit('buf = lsf_factory_stream_classdir_allocate(source, PATH_MAX, LSF_STREAM_CLASSDIR_NAME);',
        '(void)source;\n\tbuf = NULL; /* Original optional-buffer allocation failed. */')
    warning_body.edit('\tif (buf)\n\t\t(void)lsf_factory_device_sysfs_release(source, buf, LSF_STREAM_CLASSDIR_NAME);\n',
        '\t/* No warning storage was born, so there is no return claim. */\n')
    private = _registration_clone(_registration_body(sysfs.text,
        'static int lsf_prepaid_device_sysfs_create_dir_ns('), rename)
    original = _registration_body(sysfs.text, 'int sysfs_create_dir_ns(')
    sysfs.edit(original, '#ifdef CONFIG_LSF_STREAM_FACTORY\n'+warning_body.finish()+private+'#endif\n'+original)
    _registration_dispatch(sysfs, 'int sysfs_create_dir_ns(', '''\t{
\t\tstruct lsf_stream_classdir_registration_source stream_source;
\t\tint stream = lsf_factory_stream_classdir_kobject(kobj, &stream_source);
\t\tif (stream < 0) return -EOPNOTSUPP;
\t\tif (stream) return lsf_prepaid_stream_classdir_sysfs_create_dir_ns(stream_source, kobj, ns);
\t}
''')
    result['fs/sysfs/dir.c'] = sysfs.finish().encode()

    kernfs = Editor(outputs['fs/kernfs/dir.c'].decode())
    _registration_include(kernfs)
    birth = _registration_clone(_registration_body(kernfs.text,
        'static struct kernfs_node *lsf_prepaid_device_kernfs_birth('), rename)
    body = Editor(birth)
    body.edit('lsf_factory_device_sysfs_release(source, kn, LSF_STREAM_CLASSDIR_NODE)',
        'lsf_factory_stream_classdir_abort_node(source, kn, name)')
    body.edit('lsf_factory_device_sysfs_release(source, name, LSF_STREAM_CLASSDIR_NAME)',
        'lsf_factory_stream_classdir_abort_name(source, name)')
    new_node = _registration_clone(_registration_body(kernfs.text,
        'struct kernfs_node *lsf_prepaid_device_kernfs_new_node('), rename)
    local_node = Editor(new_node)
    local_node.edit('struct kernfs_node *lsf_prepaid_stream_classdir_kernfs_new_node(',
        'static struct kernfs_node *lsf_prepaid_stream_classdir_kernfs_new_node(')
    create = _registration_clone(_registration_body(kernfs.text,
        'struct kernfs_node *lsf_prepaid_device_kernfs_create_dir_ns('), rename)
    _registration_append(kernfs, body.finish()+local_node.finish()+create)
    original = _registration_body(kernfs.text, 'static void kernfs_free_rcu(')
    helper = '''static void lsf_stream_classdir_kernfs_free(struct kernfs_node *kn)
{
    struct lsf_stream_classdir_registration_source source;
    /* This is the original kernfs RCU free callback, not ID removal/unlink.
     * Borrowed ordinary parent refs have already followed original kernfs_put. */
    if (atomic_read(&kn->count) != 0 || atomic_read(&kn->active) != KN_DEACTIVATED_BIAS ||
        lsf_factory_stream_classdir_iattrs(kn, 0) != 1) {
        lsf_factory_stream_classdir_retain_unknown(); return;
    }
    if (lsf_factory_stream_classdir_return_begin(kn, LSF_STREAM_CLASSDIR_NODE, &source) != 1)
        return;
    if (lsf_factory_stream_classdir_release_name(source, kn->name) != 1) return;
    (void)lsf_factory_stream_classdir_return_finish(source);
}
'''
    kernfs.edit(original, '#ifdef CONFIG_LSF_STREAM_FACTORY\n'+helper+'#endif\n'+original)
    body = Editor(original)
    body.edit('\tstruct kernfs_node *kn = container_of(rcu, struct kernfs_node, rcu);\n',
        '\tstruct kernfs_node *kn = container_of(rcu, struct kernfs_node, rcu);\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n\t{\n'
        '\t\tstruct lsf_stream_classdir_registration_source stream_source;\n'
        '\t\tint stream = lsf_factory_stream_classdir_node(kn, &stream_source);\n'
        '\t\tif (stream < 0) return;\n'
        '\t\tif (stream) { lsf_stream_classdir_kernfs_free(kn); return; }\n\t}\n#endif\n')
    kernfs.edit(original, body.finish())
    result['fs/kernfs/dir.c'] = kernfs.finish().encode()

    idr = Editor(outputs['lib/idr.c'].decode())
    _registration_include(idr)
    _registration_append(idr, ''.join(_registration_clone(_registration_body(idr.text, s), rename) for s in (
        'static int lsf_prepaid_device_idr_alloc_u32(', 'int lsf_prepaid_device_idr_alloc_cyclic(')))
    result['lib/idr.c'] = idr.finish().encode()

    radix = Editor(outputs['lib/radix-tree.c'].decode())
    _registration_include(radix)
    _registration_append(radix, ''.join(_registration_clone(_registration_body(radix.text, s), rename) for s in (
        'static struct radix_tree_node *\nlsf_prepaid_device_radix_node_alloc(',
        'static int lsf_prepaid_device_radix_extend(', 'void __rcu **lsf_prepaid_device_idr_get_free(')))
    original = _registration_body(radix.text, 'void radix_tree_node_rcu_free(')
    body = Editor(original)
    body.edit('\tstruct radix_tree_node *node =\n\t\t\tcontainer_of(head, struct radix_tree_node, rcu_head);\n',
        '\tstruct radix_tree_node *node =\n\t\t\tcontainer_of(head, struct radix_tree_node, rcu_head);\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n\t{\n'
        '\t\tstruct lsf_stream_classdir_registration_source stream_source;\n'
        '\t\tint stream = lsf_factory_stream_classdir_return_begin(node, LSF_STREAM_CLASSDIR_IDR, &stream_source);\n'
        '\t\tif (stream < 0) return;\n\t\tif (stream) {\n'
        '\t\t\tmemset(node->slots, 0, sizeof(node->slots));\n'
        '\t\t\tmemset(node->tags, 0, sizeof(node->tags));\n'
        '\t\t\tINIT_LIST_HEAD(&node->private_list);\n'
        '\t\t\t(void)lsf_factory_stream_classdir_return_finish(stream_source);\n'
        '\t\t\treturn;\n\t\t}\n\t}\n#endif\n')
    radix.edit(original, body.finish())
    result['lib/radix-tree.c'] = radix.finish().encode()

    security = Editor(outputs['security/security.c'].decode())
    _registration_include(security)
    original = _registration_body(security.text, 'int security_kernfs_init_security(')
    private = _registration_clone(original, rename | {
        'security_kernfs_init_security': 'lsf_stream_classdir_security_kernfs_init'})
    body = Editor(private)
    body.edit('owned < 0 || (owned && lsf_factory_stream_classdir_current(source) != 1)',
        'owned != 1 || lsf_factory_stream_classdir_current(source) != 1')
    security.edit(original, '#ifdef CONFIG_LSF_STREAM_FACTORY\nstatic '+body.finish()+'#endif\n'+original)
    _registration_dispatch(security, 'int security_kernfs_init_security(', '''\t{
\t\tstruct lsf_stream_classdir_registration_source stream_source;
\t\tint stream = lsf_factory_stream_classdir_node(kn, &stream_source);
\t\tif (stream < 0) return -EOPNOTSUPP;
\t\tif (stream) return lsf_stream_classdir_security_kernfs_init(kn_dir, kn);
\t}
''')
    result['security/security.c'] = security.finish().encode()

    selinux = Editor(outputs['security/selinux/hooks.c'].decode())
    _registration_include(selinux)
    original = _registration_body(selinux.text, 'static int selinux_kernfs_init_security(')
    private = _registration_clone(original, rename | {
        'selinux_kernfs_init_security': 'lsf_stream_classdir_selinux_kernfs_init'})
    body = Editor(private)
    body.edit('owned < 0 || (owned && lsf_factory_stream_classdir_current(source) != 1)',
        'owned != 1 || lsf_factory_stream_classdir_current(source) != 1')
    selinux.edit(original, '#ifdef CONFIG_LSF_STREAM_FACTORY\n'+body.finish()+'#endif\n'+original)
    _registration_dispatch(selinux, 'static int selinux_kernfs_init_security(', '''\t{
\t\tstruct lsf_stream_classdir_registration_source stream_source;
\t\tint stream = lsf_factory_stream_classdir_node(kn, &stream_source);
\t\tif (stream < 0) return -EOPNOTSUPP;
\t\tif (stream) return lsf_stream_classdir_selinux_kernfs_init(kn_dir, kn);
\t}
''')
    result['security/selinux/hooks.c'] = selinux.finish().encode()

    iattr = Editor(outputs['net/factory-device-sysfs.c'].decode())
    _registration_dispatch(iattr, 'int lsf_factory_device_sysfs_iattrs(', '''    {
        int stream = lsf_factory_stream_classdir_iattrs(node, alloc);
        if (stream) return stream;
    }
''')
    result['net/factory-device-sysfs.c'] = iattr.finish().encode()

    device = Editor(outputs['net/device-prepaid.h'].decode())
    device.edit('static inline int lsf_device_kind(unsigned int kind)\n',
        'enum { LSF_DEVICE_STREAM_CLASSDIR_NODE = 0x16f, LSF_DEVICE_STREAM_CLASSDIR_NAME, LSF_DEVICE_STREAM_CLASSDIR_IDR };\n'
        'static inline int lsf_device_kind(unsigned int kind)\n')
    original = function(device.text, 'static inline int lsf_device_kind(')
    body = Editor(original)
    body.edit('return kind ==', 'return kind == LSF_DEVICE_STREAM_CLASSDIR_NODE || '
        'kind == LSF_DEVICE_STREAM_CLASSDIR_NAME || kind == LSF_DEVICE_STREAM_CLASSDIR_IDR || kind ==')
    device.edit(original, body.finish())
    result['net/device-prepaid.h'] = device.finish().encode()

    classdir = Editor(outputs['net/factory-stream-netdev-classdir.c'].decode())
    classdir.edit('#include <net/lsf_stream_netdev_classdir_private.h>\n',
        '#include <net/lsf_stream_netdev_classdir_private.h>\n'
        '#include <net/lsf_stream_classdir_registration_private.h>\n'
        'static int lsf_stream_classdir_try_finish_locked(struct lsf_stream_rx_state *, struct lsf_prepaid_ticket);\n')
    original = _registration_body(classdir.text, 'int lsf_factory_stream_netdev_classdir_tail_finish(')
    body = Editor(original)
    body.edit('        r->security_cache_identity != (LSF_STREAM_NETDEV_TAIL_ACTIVE | LSF_STREAM_NETDEV_RELEASE) ||\n'
        '        !lsf_device_finish(&factory.pool, state->owner, ticket, LSF_DEVICE_NETDEV_CLASSDIR)) goto poison;\n',
        '        r->security_cache_identity != (LSF_STREAM_NETDEV_TAIL_ACTIVE | LSF_STREAM_NETDEV_RELEASE)) goto poison;\n'
        '    /* Original epilogue completed; real RCU children still retain SAME record. */\n'
        '    r->security_cache_identity = LSF_STREAM_CLASSDIR_TAIL_DONE | LSF_STREAM_NETDEV_RELEASE;\n'
        '    if (lsf_stream_classdir_try_finish_locked(state, ticket) < 0) goto poison;\n')
    body.edit('    /* Cached name and original parent put already returned. Never read object\n'
        '     * payload after this actual final view return. Original Root still owns the bank. */\n',
        '    /* Cached name and original parent put returned. Handled does not claim\n'
        '     * physical view return while a real child remains. Never read object. */\n')
    classdir.edit(original, body.finish())
    result['net/factory-stream-netdev-classdir.c'] = classdir.finish().encode()

    stop = Editor(outputs['net/factory-stream-stop.c'].decode())
    stop.edit('        result = lsf_stream_netdev_drain_after_remove(state);\n',
        '        result = lsf_stream_classdir_drain_after_remove(state);\n'
        '        if (!result) result = lsf_stream_netdev_drain_after_remove(state);\n')
    result['net/factory-stream-stop.c'] = stop.finish().encode()
    factory = Editor(outputs['net/factory.c'].decode())
    _registration_include(factory)
    factory.edit('static int lsf_stream_netdev_drain_after_remove(struct lsf_stream_rx_state *);\n',
        'static int lsf_stream_classdir_drain_after_remove(struct lsf_stream_rx_state *);\n'
        'static int lsf_stream_netdev_drain_after_remove(struct lsf_stream_rx_state *);\n')
    factory.edit('#include "factory-stream-netdev-classdir.c"\n',
        '#include "factory-stream-netdev-classdir.c"\n#include "factory-stream-classdir-registration.c"\n')
    result['net/factory.c'] = factory.finish().encode()
    result[REGISTRATION_HEADER] = _owned('stream-classdir-registration-private.h')
    result[REGISTRATION_FRAGMENT] = _owned('factory-stream-classdir-registration.c')
    return result
