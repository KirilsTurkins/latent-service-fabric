"""Unselected NETDEV own-directory source; no notifier/files/readiness enablement.

Consumes the exact nine-object intermediate. Every clone starts at the complete
original declaration, including static, and projects back to that exact body.
"""
import hashlib
from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_device_security import function
from tools.host_stream_kernel_cleanup_native import OWNED, require
from tools.host_stream_kernel_stream_classdir import _registration_clone

HEADER = 'include/net/lsf_stream_netdev_directory_private.h'
FRAGMENT = 'net/factory-stream-netdev-directory.c'
PREIMAGES = {'drivers/base/core.c': (156919, '147d54547d6cd899d61394a5fe414584684a638170ce31142be7ae1fd24833a4'), 'lib/kobject.c': (32471, 'af45e0cfd88b8236a99e36c7668f1193e9ddca5306d5c58b304b1372605eb019'), 'fs/sysfs/dir.c': (7703, '8edb17b9207210656a4187c88bddd5f812d55b6f997db1cfa05766e0bae2dadb'), 'fs/kernfs/dir.c': (57671, '3c68627ebb5fec9322d7d966e0d5faf19604d7868450ce1e33b262fc313a1245'), 'lib/idr.c': (21672, 'df9249fd70edd86b7adee142f0cee95e1966d7577d74ed5eec0b899086b67684'), 'lib/radix-tree.c': (54952, 'ebcdb39069b94d57731097e66958853bea58c7bff52d282a90ad35010c167568'), 'security/security.c': (186744, 'db3a563790f53adb3a626f9e7c1b8c5bef7e0456dbf9f0654d5b14588d571a28'), 'security/selinux/hooks.c': (210862, 'a0efbbf50fee49847c4e69f5de2ac0363e916441b4aaeba54874580afdb80dae'), 'net/factory-device-sysfs.c': (4547, '444d3f7a01df2837fa461d2f25d14eefa7a2a82ef81956d4f6d4511f69c2a38d'), 'net/device-prepaid.h': (18273, '2676d85e23a255740c3d5e7d020ecc3dc4fef48eb485268e58c0dced3cd88abf'), 'net/factory.c': (36781, 'd75054655b89795c735c351876060d5ab5470ef1ab56dab6f1ad3d87e6fa23e0')}
BODIES = {'int device_add(': (5316, '48ccede3d3992f20dfc8591fc34ca632bb6b7f94652b7d112968cb134ade481f'), 'int lsf_factory_device_sysfs_iattrs(': (748, 'cb8df1ccb5bc57f806a822229e31b2ea3651033be453f0e7b3a6ea3e86b7e6fa'), 'int lsf_prepaid_stream_classdir_idr_alloc_cyclic(': (716, '3c8ef160b71fb7613e90bd6ce831451266d3c516fd8ed5ae21791e6ed707e9d5'), 'int security_kernfs_init_security(': (1028, '974c9534dd2be672d1f90ceecce0aa3a441bed0dc9c7713866636b2f9b0c5711'), 'int sysfs_create_dir_ns(': (1197, 'b5015472b4a5d2573ad356a0cdd58f69f11b08dc70459339a748a0789b85062b'), 'static inline int lsf_device_kind(': (3221, 'bc590bdf439c6d4c65e8b2064bd00cf6f9971c061196b9721a09f92142027be1'), 'static int create_dir(': (1456, 'c790a30d166a12f7b68588cafddc84d9f9798cf489865305d3db974a155c5018'), 'static int lsf_prepaid_stream_classdir_idr_alloc_u32(': (873, 'd1f259f1af0950f4ae232a8df40ed83ee71f6ca3f2d4004c866e44646a00659c'), 'static int lsf_prepaid_stream_classdir_radix_extend(': (1601, 'ab3b8544cb1ba0f30040b1aa8016dd74da5415e8a74de89f5da1d38b28eb4f0d'), 'static int lsf_prepaid_stream_classdir_sysfs_create_dir_ns(': (864, '82d2617fa55eea987f671dbb7f9eff5cc72328b8e27c7f37755211d71df7ebfa'), 'static int lsf_stream_classdir_create_dir(': (1191, 'ab14501fa92e60196223387c533bdd7afa4561e30eefaa906821775c01018915'), 'static int lsf_stream_classdir_security_kernfs_init(': (745, 'beab2e04ec4f96eaa2dd362e29ca6e6d995a56ed5e13984999db9b383cc08077'), 'static int lsf_stream_classdir_selinux_kernfs_init(': (1559, '44a540ad3e5d49cbbaf3cdf0d87ecc308d8bf60daf7568b5de14128a81493ab2'), 'static int selinux_kernfs_init_security(': (1848, '6525fe5e2d547e01321a9b9d8f692debe21d2ec005dfe12f3b40b8eb84b34efb'), 'static struct kernfs_node *lsf_prepaid_stream_classdir_kernfs_birth(': (2085, '3cc8949b646ca3d28fc81c8b7cb6abb3ab504201b33fd578a9c31e0378c0a0a5'), 'static struct kernfs_node *lsf_prepaid_stream_classdir_kernfs_new_node(': (756, 'c8d8584a44c46ce5f9db80a01af96bb4055ce5b8e59dafe32271fe239beb0e6b'), 'static struct radix_tree_node *\nlsf_prepaid_stream_classdir_radix_node_alloc(': (751, 'c620a0ac8744e6a22c10edfb571a60a4b404031e816fe62bc82090788eeb1d1f'), 'static void kernfs_free_rcu(': (822, '2b7ee1cc82be335600f6d81413ff12042535ffbcc84e7a261897e4970d0de43b'), 'static void lsf_prepaid_stream_classdir_warn_dup(': (444, '82a06526722c54c1284a99a53fefa2ca96b40c3aeea91d19358890f2166d594f'), 'static void lsf_stream_classdir_kernfs_free(': (760, 'a90a2e24fdad5c36c1593037392b42ad8565a1074d1a11f1f58516988322ba35'), 'struct kernfs_node *kernfs_new_node(': (895, 'cf927b2f692727076a555c27910a1ae4d93c1e0b9f3facab4c3a4e2f507db3df'), 'struct kernfs_node *lsf_prepaid_stream_classdir_kernfs_create_dir_ns(': (639, '32cb09e00fa0e4300365b985372eb775b0bdbf68c46e11060b11c2f0eb1683e7'), 'void __rcu **lsf_prepaid_stream_classdir_idr_get_free(': (2229, 'd3b624d2da8ddf00d4d592d22853732ab1dc1aa01d87986e3a79bb2004d825a8'), 'void radix_tree_node_rcu_free(': (1674, 'c82e93f55351d987db762b5329f8b7d02ed9ae4a782057689e64a4c555fbde1d')}


def _owned(name):
    raw = (OWNED/name).read_bytes()
    require(0 < len(raw) <= 32*1024 and b'\r' not in raw, 'netdev-directory-owned-bound')
    return raw


def _body(text, signature):
    raw = function(text, signature)
    size, digest = BODIES[signature]
    require(len(raw.encode()) == size and hashlib.sha256(raw.encode()).hexdigest() == digest,
        'netdev-directory-full-declaration-preimage')
    return raw


def _include(editor):
    old = '#include <net/lsf_stream_classdir_registration_private.h>\n'
    editor.edit(old, old+'#include <net/lsf_stream_netdev_directory_private.h>\n')


def _append(editor, fragment):
    original = editor.text
    editor.edit(original, original+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'+fragment+'#endif\n')


def _dispatch(editor, signature, branch):
    original = _body(editor.text, signature)
    body = Editor(original)
    body.edit('\n{\n', '\n{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'+branch+'#endif\n')
    editor.edit(original, body.finish())


def _renames():
    return {
        'lsf_stream_classdir_registration_source': 'lsf_stream_netdev_directory_source',
        'lsf_factory_stream_classdir_kobject': 'lsf_factory_stream_netdev_directory_kobject',
        'lsf_factory_stream_classdir_node': 'lsf_factory_stream_netdev_directory_node',
        'lsf_factory_stream_classdir_current': 'lsf_factory_stream_netdev_directory_current',
        'lsf_factory_stream_classdir_allocate': 'lsf_factory_stream_netdev_directory_allocate',
        'lsf_factory_stream_classdir_name': 'lsf_factory_stream_netdev_directory_name',
        'lsf_factory_stream_classdir_abort_node': 'lsf_factory_stream_netdev_directory_abort_node',
        'lsf_factory_stream_classdir_abort_name': 'lsf_factory_stream_netdev_directory_abort_name',
        'lsf_factory_stream_classdir_return_begin': 'lsf_factory_stream_netdev_directory_return_begin',
        'lsf_factory_stream_classdir_release_name': 'lsf_factory_stream_netdev_directory_release_name',
        'lsf_factory_stream_classdir_return_finish': 'lsf_factory_stream_netdev_directory_return_finish',
        'lsf_factory_stream_classdir_iattrs': 'lsf_factory_stream_netdev_directory_iattrs',
        'lsf_factory_stream_classdir_retain_unknown': 'lsf_factory_stream_netdev_directory_retain_unknown',
        'LSF_STREAM_CLASSDIR_NODE': 'LSF_STREAM_NETDEV_DIRECTORY_NODE',
        'LSF_STREAM_CLASSDIR_NAME': 'LSF_STREAM_NETDEV_DIRECTORY_NAME',
        'LSF_STREAM_CLASSDIR_IDR': 'LSF_STREAM_NETDEV_DIRECTORY_IDR',
        'lsf_prepaid_stream_classdir_registration_ready': 'lsf_prepaid_stream_netdev_directory_ready',
        'lsf_stream_classdir_create_dir': 'lsf_stream_netdev_directory_create_dir',
        'lsf_prepaid_stream_classdir_warn_dup': 'lsf_prepaid_stream_netdev_directory_warn_dup',
        'lsf_prepaid_stream_classdir_sysfs_create_dir_ns': 'lsf_prepaid_stream_netdev_directory_sysfs_create_dir_ns',
        'lsf_prepaid_stream_classdir_kernfs_birth': 'lsf_prepaid_stream_netdev_directory_kernfs_birth',
        'lsf_prepaid_stream_classdir_kernfs_new_node': 'lsf_prepaid_stream_netdev_directory_kernfs_new_node',
        'lsf_prepaid_stream_classdir_kernfs_create_dir_ns': 'lsf_prepaid_stream_netdev_directory_kernfs_create_dir_ns',
        'lsf_stream_classdir_kernfs_free': 'lsf_stream_netdev_directory_kernfs_free',
        'lsf_prepaid_stream_classdir_idr_alloc_u32': 'lsf_prepaid_stream_netdev_directory_idr_alloc_u32',
        'lsf_prepaid_stream_classdir_idr_alloc_cyclic': 'lsf_prepaid_stream_netdev_directory_idr_alloc_cyclic',
        'lsf_prepaid_stream_classdir_idr_get_free': 'lsf_prepaid_stream_netdev_directory_idr_get_free',
        'lsf_prepaid_stream_classdir_radix_node_alloc': 'lsf_prepaid_stream_netdev_directory_radix_node_alloc',
        'lsf_prepaid_stream_classdir_radix_extend': 'lsf_prepaid_stream_netdev_directory_radix_extend',
        'lsf_stream_classdir_security_kernfs_init': 'lsf_stream_netdev_directory_security_kernfs_init',
        'lsf_stream_classdir_selinux_kernfs_init': 'lsf_stream_netdev_directory_selinux_kernfs_init',
    }


def transform(outputs):
    require(type(outputs) is dict and HEADER not in outputs and FRAGMENT not in outputs and
        bool(PREIMAGES), 'netdev-directory-fresh-stage')
    for name, (size, digest) in PREIMAGES.items():
        raw = outputs.get(name)
        require(type(raw) is bytes and len(raw) == size and hashlib.sha256(raw).hexdigest() == digest,
            'netdev-directory-a53-whole-source-preimage')
    result = dict(outputs)
    names = _renames()
    clone = lambda text, signature: _registration_clone(_body(text, signature), names)

    core = Editor(outputs['drivers/base/core.c'].decode())
    _include(core)
    _append(core, '''int lsf_prepaid_stream_netdev_directory_type(const struct kobject *kobj)
{
    const struct device *dev;
    if (!kobj || kobj->ktype != &device_ktype || !kobj->state_initialized ||
        device_ktype.default_groups || device_ktype.release != device_release ||
        device_ktype.sysfs_ops != &dev_sysfs_ops || device_ktype.namespace != device_namespace ||
        device_ktype.get_ownership != device_get_ownership || kobj->kset != devices_kset)
        return 0;
    dev = kobj_to_dev(kobj);
    /* Unknown release/resource descendants are not admitted or silently erased. */
    return dev->p && dev->p->device == dev && !dev->release && !dev->type && !dev->dma_range_map &&
        !dev->driver_override.name && list_empty(&dev->devres_head) &&
        lsf_prepaid_stream_netdev_class_known(dev->class);
}

int lsf_prepaid_stream_netdev_directory_ready(const struct kobject *kobj)
{
    struct lsf_stream_netdev_directory_source source;
    return lsf_factory_stream_netdev_directory_kobject(kobj, &source) == 1 &&
        lsf_factory_stream_netdev_directory_current(source) == 1 &&
        lsf_prepaid_stream_netdev_directory_type(kobj);
}
''')
    original = _body(core.text, 'int device_add(')
    body = Editor(original)
    anchor = '\t/* notify platform of device entry */\n\tdevice_platform_notify(dev);\n'
    body.edit(anchor, '''#ifdef CONFIG_LSF_STREAM_FACTORY
\t{
\t\tint stream = lsf_factory_stream_netdev_directory_added(dev);
\t\tif (stream < 0)
\t\t\treturn -EOPNOTSUPP; /* Unknown original refs/graph remain retained. */
\t\tif (stream) {
\t\t\t/* The directory exists, but no platform notification, file or
\t\t\t * ADD event has run. Do NOT enter attrError's unpaired REMOVE
\t\t\t * notifications. Use the original directory/glue/parent unwind. */
\t\t\terror = -EOPNOTSUPP;
\t\t\tglue_dir = get_glue_dir(dev);
\t\t\tkobject_del(&dev->kobj);
\t\t\tgoto Error;
\t\t}
\t}
#endif
'''+anchor)
    core.edit(original, body.finish())
    result['drivers/base/core.c'] = core.finish().encode()

    kobj = Editor(outputs['lib/kobject.c'].decode())
    _include(kobj)
    original = _body(kobj.text, 'static int create_dir(')
    private = clone(kobj.text, 'static int lsf_stream_classdir_create_dir(')
    kobj.edit(original, '#ifdef CONFIG_LSF_STREAM_FACTORY\n'+private+'#endif\n'+original)
    _dispatch(kobj, 'static int create_dir(', '''\t{
\t\tstruct lsf_stream_netdev_directory_source source;
\t\tint owned = lsf_factory_stream_netdev_directory_kobject(kobj, &source);
\t\tif (owned < 0) return -EOPNOTSUPP;
\t\tif (owned) return lsf_stream_netdev_directory_create_dir(kobj);
\t}
''')
    result['lib/kobject.c'] = kobj.finish().encode()

    sysfs = Editor(outputs['fs/sysfs/dir.c'].decode())
    _include(sysfs)
    private = clone(sysfs.text, 'static void lsf_prepaid_stream_classdir_warn_dup(')+clone(sysfs.text,
        'static int lsf_prepaid_stream_classdir_sysfs_create_dir_ns(')
    original = _body(sysfs.text, 'int sysfs_create_dir_ns(')
    sysfs.edit(original, '#ifdef CONFIG_LSF_STREAM_FACTORY\n'+private+'#endif\n'+original)
    _dispatch(sysfs, 'int sysfs_create_dir_ns(', '''\t{
\t\tstruct lsf_stream_netdev_directory_source source;
\t\tint owned = lsf_factory_stream_netdev_directory_kobject(kobj, &source);
\t\tif (owned < 0) return -EOPNOTSUPP;
\t\tif (owned) return lsf_prepaid_stream_netdev_directory_sysfs_create_dir_ns(source, kobj, ns);
\t}
''')
    result['fs/sysfs/dir.c'] = sysfs.finish().encode()

    kernfs = Editor(outputs['fs/kernfs/dir.c'].decode())
    _include(kernfs)
    _append(kernfs, ''.join(clone(kernfs.text, signature) for signature in (
        'static struct kernfs_node *lsf_prepaid_stream_classdir_kernfs_birth(',
        'static struct kernfs_node *lsf_prepaid_stream_classdir_kernfs_new_node(',
        'struct kernfs_node *lsf_prepaid_stream_classdir_kernfs_create_dir_ns(')))
    original = _body(kernfs.text, 'static void kernfs_free_rcu(')
    private = clone(kernfs.text, 'static void lsf_stream_classdir_kernfs_free(')
    kernfs.edit(original, '#ifdef CONFIG_LSF_STREAM_FACTORY\n'+private+'#endif\n'+original)
    body = Editor(original)
    anchor = '\tstruct kernfs_node *kn = container_of(rcu, struct kernfs_node, rcu);\n'
    body.edit(anchor, anchor+'''#ifdef CONFIG_LSF_STREAM_FACTORY
\t{
\t\tstruct lsf_stream_netdev_directory_source source;
\t\tint owned = lsf_factory_stream_netdev_directory_node(kn, &source);
\t\tif (owned < 0) return;
\t\tif (owned) { lsf_stream_netdev_directory_kernfs_free(kn); return; }
\t}
#endif
''')
    kernfs.edit(original, body.finish())
    _dispatch(kernfs, 'struct kernfs_node *kernfs_new_node(', '''\t{
\t\tstruct lsf_stream_netdev_directory_source source;
\t\tint owned = lsf_factory_stream_netdev_directory_node(parent, &source);
\t\t/* Only the explicit typed own-directory entry above is funded. A
\t\t * child file/group/link is a later, unported family: refuse BEFORE
\t\t * native parent access/allocation, never an ambient fallback. */
\t\tif (owned) return NULL;
\t}
''')
    result['fs/kernfs/dir.c'] = kernfs.finish().encode()

    idr = Editor(outputs['lib/idr.c'].decode())
    _include(idr)
    _append(idr, ''.join(clone(idr.text, signature) for signature in (
        'static int lsf_prepaid_stream_classdir_idr_alloc_u32(',
        'int lsf_prepaid_stream_classdir_idr_alloc_cyclic(')))
    result['lib/idr.c'] = idr.finish().encode()

    radix = Editor(outputs['lib/radix-tree.c'].decode())
    _include(radix)
    _append(radix, ''.join(clone(radix.text, signature) for signature in (
        'static struct radix_tree_node *\nlsf_prepaid_stream_classdir_radix_node_alloc(',
        'static int lsf_prepaid_stream_classdir_radix_extend(',
        'void __rcu **lsf_prepaid_stream_classdir_idr_get_free(')))
    original = _body(radix.text, 'void radix_tree_node_rcu_free(')
    body = Editor(original)
    anchor = '\tstruct radix_tree_node *node =\n\t\t\tcontainer_of(head, struct radix_tree_node, rcu_head);\n'
    body.edit(anchor, anchor+'''#ifdef CONFIG_LSF_STREAM_FACTORY
\t{
\t\tstruct lsf_stream_netdev_directory_source source;
\t\tint owned = lsf_factory_stream_netdev_directory_return_begin(node, LSF_STREAM_NETDEV_DIRECTORY_IDR, &source);
\t\tif (owned < 0) return;
\t\tif (owned) {
\t\t\tmemset(node->slots, 0, sizeof(node->slots));
\t\t\tmemset(node->tags, 0, sizeof(node->tags));
\t\t\tINIT_LIST_HEAD(&node->private_list);
\t\t\t(void)lsf_factory_stream_netdev_directory_return_finish(source);
\t\t\treturn;
\t\t}
\t}
#endif
''')
    radix.edit(original, body.finish())
    result['lib/radix-tree.c'] = radix.finish().encode()

    for path, original_signature, clone_signature, destination in (
        ('security/security.c', 'int security_kernfs_init_security(',
            'static int lsf_stream_classdir_security_kernfs_init(',
            'lsf_stream_netdev_directory_security_kernfs_init'),
        ('security/selinux/hooks.c', 'static int selinux_kernfs_init_security(',
            'static int lsf_stream_classdir_selinux_kernfs_init(',
            'lsf_stream_netdev_directory_selinux_kernfs_init'),
    ):
        editor = Editor(outputs[path].decode())
        _include(editor)
        original = _body(editor.text, original_signature)
        private = clone(editor.text, clone_signature)
        editor.edit(original, '#ifdef CONFIG_LSF_STREAM_FACTORY\n'+private+'#endif\n'+original)
        _dispatch(editor, original_signature, '''\t{
\t\tstruct lsf_stream_netdev_directory_source source;
\t\tint owned = lsf_factory_stream_netdev_directory_node(kn, &source);
\t\tif (owned < 0) return -EOPNOTSUPP;
\t\tif (owned) return '''+destination+'''(kn_dir, kn);
\t}
''')
        result[path] = editor.finish().encode()

    iattr = Editor(outputs['net/factory-device-sysfs.c'].decode())
    _dispatch(iattr, 'int lsf_factory_device_sysfs_iattrs(', '''    {
        int owned = lsf_factory_stream_netdev_directory_iattrs(node, alloc);
        if (owned) return owned;
    }
''')
    result['net/factory-device-sysfs.c'] = iattr.finish().encode()
    device = Editor(outputs['net/device-prepaid.h'].decode())
    device.edit('static inline int lsf_device_kind(unsigned int kind)\n',
        'enum { LSF_DEVICE_STREAM_NETDEV_DIRECTORY_NODE = 0x172, LSF_DEVICE_STREAM_NETDEV_DIRECTORY_NAME, LSF_DEVICE_STREAM_NETDEV_DIRECTORY_IDR };\n'
        'static inline int lsf_device_kind(unsigned int kind)\n')
    original = _body(device.text, 'static inline int lsf_device_kind(')
    body = Editor(original)
    body.edit('return kind ==', 'return kind == LSF_DEVICE_STREAM_NETDEV_DIRECTORY_NODE || '
        'kind == LSF_DEVICE_STREAM_NETDEV_DIRECTORY_NAME || kind == LSF_DEVICE_STREAM_NETDEV_DIRECTORY_IDR || kind ==')
    device.edit(original, body.finish())
    result['net/device-prepaid.h'] = device.finish().encode()
    factory = Editor(outputs['net/factory.c'].decode())
    _include(factory)
    factory.edit('#include "factory-stream-classdir-registration.c"\n',
        '#include "factory-stream-classdir-registration.c"\n#include "factory-stream-netdev-directory.c"\n')
    result['net/factory.c'] = factory.finish().encode()
    result[HEADER] = _owned('stream-netdev-directory-private.h')
    result[FRAGMENT] = _owned('factory-stream-netdev-directory.c')
    return result
