"""WIP actual sysfs/kernfs constructors, fixed-bank IDR and mandatory hook boundaries.

Not an installed registration path. Original normal bodies remain unchanged;
nondefault UID/GID, inherited labels and later attribute allocation are explicit
unsupported states until their real allocation/consumer closures are supplied.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_device_registration as prior
from tools import host_stream_kernel_maintained as maintained

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_device_sysfs.json'
DIR = 'fs/kernfs/dir.c'
LINK = 'fs/kernfs/symlink.c'
INODE = 'fs/kernfs/inode.c'
SYSFS = 'fs/sysfs/dir.c'
SECURITY = 'security/security.c'
SELINUX = 'security/selinux/hooks.c'
CORE = 'drivers/base/core.c'
KOBJECT = 'lib/kobject.c'
EXTRAS = {DIR, LINK, INODE, SYSFS, 'fs/kernfs/file.c', 'fs/kernfs/kernfs-internal.h'}
DEFINITIONS = {'__kernfs_new_node', 'kernfs_new_node', 'kernfs_create_dir_ns',
    'kernfs_free_rcu', 'kernfs_put', 'kernfs_create_link', '__kernfs_create_file',
    'sysfs_create_dir_ns', 'sysfs_warn_dup', '__kernfs_iattrs', 'kernfs_xattr_get',
    'kernfs_xattr_set', 'security_kernfs_init_security', 'selinux_kernfs_init_security',
    'create_dir', 'kobject_get_ownership', 'device_get_ownership', 'device_ktype'}
GATES = prior.GATES + ('actualSysfsRegistrationExecuted', 'completeSysfsClosure',
    'mandatoryKernfsSecurityQualified', 'ueventDeliveryOwned')
replace = prior.replace
require = prior.require


def fixture():
    value = json.loads(FIXTURE.read_bytes())
    parent = prior.fixture()
    require(value['schemaVersion'] == 'lsf.kernel-device-sysfs-source.v1' and
        value['upstreamCommit'] == parent['upstreamCommit'] and
        value['archiveSha256'] == parent['archiveSha256'], 'device-sysfs-maintained-identity')
    require(set(value['source']) == set(parent['source']) | EXTRAS and
        all(value['source'][name] == row for name, row in parent['source'].items()),
        'device-sysfs-whole-membership')
    require(set(value['sections']) == set(parent['sections']) | DEFINITIONS and
        all(value['sections'][name] == row for name, row in parent['sections'].items()),
        'device-sysfs-original-definitions')
    require(all(value[name] is False for name in GATES), 'device-sysfs-uninstalled')
    return value


def section(text, name):
    row = fixture()['sections'][name]
    starts = [i for i in range(len(text)) if text.startswith(row['prefix'], i) and
        (not i or text[i - 1] == '\n')]
    require(len(starts) == 1, 'device-sysfs-definition-occurrence')
    ending = row.get('terminator', '\n}\n')
    end = text.find(ending, starts[0])
    require(end >= 0, 'device-sysfs-definition-end')
    raw = text[starts[0]:end + len(ending)]
    require(raw == row['text'] and len(raw.encode()) == row['bytes'] and
        hashlib.sha256(raw.encode()).hexdigest() == row['sha256'],
        'device-sysfs-definition-preimage')
    return raw


def authenticate(inputs):
    value = fixture()
    require(set(inputs) == set(value['source']), 'device-sysfs-whole-membership')
    maintained.authenticate_files(inputs, value['source'])
    prior.authenticate({name: inputs[name] for name in prior.fixture()['source']})
    for name, row in value['sections'].items():
        section(inputs[row['source']].decode(), name)


def wrapper(raw, prelude):
    declaration, body = raw.split('\n{\n', 1)
    return declaration + '\n{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' + prelude + (
        '\t{\n#endif\n') + body[:-2] + '#ifdef CONFIG_LSF_STREAM_FACTORY\n\t}\n#endif\n}\n'


def private_birth(raw):
    require(section(raw, '__kernfs_new_node') == raw, 'device-sysfs-node-birth-preimage')
    text = replace(raw, 'static struct kernfs_node *__kernfs_new_node(struct kernfs_root *root,',
        'static struct kernfs_node *lsf_prepaid_device_kernfs_birth(\n'
        '\t\tstruct lsf_device_registration_source source, struct kernfs_root *root,')
    text = replace(text, '\tint ret;\n', '\tint ret;\n'
        '\tstruct lsf_device_registration_source node_source;\n\n'
        '\tif (lsf_factory_device_registration_current(source) != 1 ||\n'
        '\t    !uid_eq(uid, GLOBAL_ROOT_UID) || !gid_eq(gid, GLOBAL_ROOT_GID))\n'
        '\t\treturn NULL;\n')
    text = replace(text, 'name = kstrdup_const(name, GFP_KERNEL);',
        'name = lsf_factory_device_sysfs_name(source, name);')
    text = replace(text, 'kn = kmem_cache_zalloc(kernfs_node_cache, GFP_KERNEL);',
        'kn = lsf_factory_device_registration_allocate(source, sizeof(*kn),\n'
        '\t\tLSF_REGISTRATION_KIND_NODE);')
    text = replace(text, '\tidr_preload(GFP_KERNEL);\n',
        '\tif (lsf_factory_device_registration_node(kn, &node_source) != 1)\n'
        '\t\treturn NULL; /* poisoned unknown birth: retain both allocations */\n')
    text = replace(text, 'ret = idr_alloc_cyclic(&root->ino_idr, kn, 1, 0, GFP_ATOMIC);',
        'ret = lsf_prepaid_device_idr_alloc_cyclic(node_source,\n'
        '\t\t&root->ino_idr, kn, 1, 0, GFP_ATOMIC);')
    text = replace(text, '\tidr_preload_end();\n', '')
    # Keep the original UID/GID and mandatory security branches, all fields,
    # ID/generation publication and every original unwind label. The first
    # finite guard makes unsupported nondefault ownership explicit beforehand.
    text = replace(text, '\tkmem_cache_free(kernfs_node_cache, kn);\n',
        '\tif (lsf_factory_device_sysfs_release(source, kn, LSF_REGISTRATION_KIND_NODE) != 1)\n'
        '\t\treturn NULL;\n')
    return replace(text, '\tkfree_const(name);\n',
        '\t(void)lsf_factory_device_sysfs_release(source, name, LSF_REGISTRATION_KIND_NAME);\n')


def private_new_node(raw):
    require(section(raw, 'kernfs_new_node') == raw, 'device-sysfs-new-node-preimage')
    text = replace(raw, 'struct kernfs_node *kernfs_new_node(struct kernfs_node *parent,',
        'struct kernfs_node *lsf_prepaid_device_kernfs_new_node(\n'
        '\t\tstruct lsf_device_registration_source source, struct kernfs_node *parent,')
    text = replace(text, '\tstruct kernfs_node *kn;\n',
        '\tstruct kernfs_node *kn;\n\n'
        '\tif (lsf_factory_device_registration_current(source) != 1)\n'
        '\t\treturn NULL;\n')
    return replace(text, 'kn = __kernfs_new_node(kernfs_root(parent), parent,',
        'kn = lsf_prepaid_device_kernfs_birth(source, kernfs_root(parent), parent,')


def normal_new_node(raw):
    require(section(raw, 'kernfs_new_node') == raw, 'device-sysfs-new-node-dispatch-preimage')
    return wrapper(raw, '\tstruct lsf_device_registration_source source;\n'
        '\tint owned = lsf_factory_device_registration_node(parent, &source);\n'
        '\tif (owned < 0)\n\t\treturn NULL;\n'
        '\tif (owned)\n'
        '\t\treturn lsf_prepaid_device_kernfs_new_node(source, parent, name, mode, uid, gid, flags);\n')


def private_create_dir(raw):
    require(section(raw, 'kernfs_create_dir_ns') == raw, 'device-sysfs-create-dir-preimage')
    text = replace(raw, 'struct kernfs_node *kernfs_create_dir_ns(struct kernfs_node *parent,',
        'struct kernfs_node *lsf_prepaid_device_kernfs_create_dir_ns(\n'
        '\t\tstruct lsf_device_registration_source source, struct kernfs_node *parent,')
    return replace(text, 'kn = kernfs_new_node(parent, name, mode | S_IFDIR,',
        'kn = lsf_prepaid_device_kernfs_new_node(source, parent, name, mode | S_IFDIR,')


def final_node(raw):
    require(section(raw, 'kernfs_free_rcu') == raw, 'device-sysfs-rcu-node-preimage')
    return replace(raw, '\tstruct kernfs_node *kn = container_of(rcu, struct kernfs_node, rcu);\n',
        '\tstruct kernfs_node *kn = container_of(rcu, struct kernfs_node, rcu);\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tstruct lsf_device_registration_source source;\n'
        '\tint owned = lsf_factory_device_registration_node(kn, &source);\n'
        '\tif (owned < 0)\n\t\treturn;\n'
        '\tif (owned) {\n\t\tlsf_prepaid_device_kernfs_free(kn);\n\t\treturn;\n\t}\n#endif\n')


def private_link(raw):
    require(section(raw, 'kernfs_create_link') == raw, 'device-sysfs-link-preimage')
    text = replace(raw, 'struct kernfs_node *kernfs_create_link(struct kernfs_node *parent,',
        'static struct kernfs_node *lsf_prepaid_device_kernfs_link(\n'
        '\t\tstruct lsf_device_registration_source source, struct kernfs_node *parent,')
    return replace(text, 'kn = kernfs_new_node(parent, name, S_IFLNK|0777, uid, gid, KERNFS_LINK);',
        'kn = lsf_prepaid_device_kernfs_new_node(source, parent, name, S_IFLNK|0777, uid, gid, KERNFS_LINK);')


def normal_link(raw):
    require(section(raw, 'kernfs_create_link') == raw, 'device-sysfs-link-dispatch-preimage')
    return wrapper(raw, '\tstruct lsf_device_registration_source source;\n'
        '\tint owned = lsf_factory_device_sysfs_pair(parent, target, &source);\n'
        '\tif (owned < 0)\n\t\treturn ERR_PTR(-EOPNOTSUPP);\n'
        '\tif (owned)\n\t\treturn lsf_prepaid_device_kernfs_link(source, parent, name, target);\n')


def private_warning(raw):
    require(section(raw, 'sysfs_warn_dup') == raw, 'device-sysfs-warning-preimage')
    text = replace(raw, 'void sysfs_warn_dup(struct kernfs_node *parent, const char *name)',
        'static void lsf_prepaid_device_sysfs_warn_dup(struct lsf_device_registration_source source,\n'
        '\t\tstruct kernfs_node *parent, const char *name)')
    text = replace(text, 'buf = kzalloc(PATH_MAX, GFP_KERNEL);',
        'buf = lsf_factory_device_registration_allocate(source, PATH_MAX, LSF_REGISTRATION_KIND_NAME);')
    return replace(text, '\tkfree(buf);\n', '\tif (buf)\n'
        '\t\t(void)lsf_factory_device_sysfs_release(source, buf, LSF_REGISTRATION_KIND_NAME);\n')


def private_sysfs_dir(raw):
    require(section(raw, 'sysfs_create_dir_ns') == raw, 'device-sysfs-initial-dir-preimage')
    text = replace(raw, 'int sysfs_create_dir_ns(struct kobject *kobj, const void *ns)',
        'static int lsf_prepaid_device_sysfs_create_dir_ns(\n'
        '\t\tstruct lsf_device_registration_source source, struct kobject *kobj, const void *ns)')
    text = replace(text, '\tkgid_t gid;\n', '\tkgid_t gid;\n\n'
        '\tif (lsf_factory_device_registration_current(source) != 1 ||\n'
        '\t    lsf_prepaid_device_kobject_registration_ready(kobj) != 1)\n'
        '\t\treturn -EOPNOTSUPP;\n')
    text = replace(text, 'kn = kernfs_create_dir_ns(parent, kobject_name(kobj), 0755, uid, gid,',
        'kn = lsf_prepaid_device_kernfs_create_dir_ns(source, parent, kobject_name(kobj), 0755, uid, gid,')
    return replace(text, 'sysfs_warn_dup(parent, kobject_name(kobj));',
        'lsf_prepaid_device_sysfs_warn_dup(source, parent, kobject_name(kobj));')


def normal_sysfs_dir(raw):
    require(section(raw, 'sysfs_create_dir_ns') == raw, 'device-sysfs-initial-dispatch-preimage')
    return wrapper(raw, '\tstruct lsf_device_registration_source source;\n'
        '\tint owned = lsf_factory_device_registration_kobject(kobj, &source);\n'
        '\tif (owned < 0)\n\t\treturn -EOPNOTSUPP;\n'
        '\tif (owned)\n\t\treturn lsf_prepaid_device_sysfs_create_dir_ns(source, kobj, ns);\n')


def iattrs_guard(raw):
    require(section(raw, '__kernfs_iattrs') == raw, 'device-sysfs-iattrs-preimage')
    return wrapper(raw, '\tif (lsf_factory_device_sysfs_iattrs(kn, alloc) < 0)\n'
        '\t\treturn NULL;\n')


def xattr_get_guard(raw):
    require(section(raw, 'kernfs_xattr_get') == raw, 'device-sysfs-xattr-get-preimage')
    return wrapper(raw, '\tif (lsf_factory_device_sysfs_iattrs(kn, 0) < 0)\n'
        '\t\treturn -EOPNOTSUPP;\n')


def xattr_set_guard(raw):
    require(section(raw, 'kernfs_xattr_set') == raw, 'device-sysfs-xattr-set-preimage')
    return wrapper(raw, '\tstruct lsf_device_registration_source source;\n'
        '\tif (lsf_factory_device_registration_node(kn, &source))\n'
        '\t\treturn -EOPNOTSUPP;\n')


def security_guard(raw):
    require(section(raw, 'security_kernfs_init_security') == raw, 'device-sysfs-lsm-entry-preimage')
    return wrapper(raw, '\tstruct lsf_device_registration_source source;\n'
        '\tstruct lsm_static_call *scall;\n'
        '\tint owned = lsf_factory_device_registration_node(kn, &source);\n'
        '\tif (owned < 0 || (owned && lsf_factory_device_registration_current(source) != 1))\n'
        '\t\treturn -EOPNOTSUPP;\n'
        '\tif (owned) {\n\t\tlsm_for_each_hook(scall, kernfs_init_security) {\n'
        '#ifdef CONFIG_SECURITY_SELINUX\n'
        '\t\t\tif (!lsf_prepaid_device_selinux_kernfs_hook(scall->hl->hook.kernfs_init_security))\n'
        '\t\t\t\treturn -EOPNOTSUPP;\n'
        '#else\n\t\t\treturn -EOPNOTSUPP;\n#endif\n\t\t}\n\t}\n')


def selinux_guard(raw):
    require(section(raw, 'selinux_kernfs_init_security') == raw, 'device-sysfs-selinux-preimage')
    text = replace(raw, '\tchar *context;\n', '\tchar *context;\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tstruct lsf_device_registration_source source;\n'
        '\tint owned = lsf_factory_device_registration_node(kn, &source);\n'
        '\tif (owned < 0 || (owned && lsf_factory_device_registration_current(source) != 1))\n'
        '\t\treturn -EOPNOTSUPP;\n#endif\n')
    return replace(text, '\tclen = (u32)rc;\n', '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (owned)\n\t\treturn -EOPNOTSUPP;\n#endif\n\tclen = (u32)rc;\n')


def kobject_create_guard(raw):
    require(section(raw, 'create_dir') == raw, 'device-sysfs-kobject-create-preimage')
    return wrapper(raw, '\tstruct lsf_device_registration_source source;\n'
        '\tint owned = lsf_factory_device_registration_kobject(kobj, &source);\n'
        '\tif (owned < 0 || (owned && lsf_prepaid_device_kobject_registration_ready(kobj) != 1))\n'
        '\t\treturn -EOPNOTSUPP;\n')


def kobject_ready(raw):
    require(section(raw, 'device_ktype') == raw, 'device-sysfs-actual-device-ktype-preimage')
    # Actual device_ktype has the unchanged device_get_ownership and namespace
    # callbacks. With no class, their original branches allocate nothing.
    # Reject a parent callback before kobject_namespace can invoke it as well.
    return raw + ('\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        'int lsf_prepaid_device_kobject_registration_ready(const struct kobject *kobj)\n'
        '{\n\tstruct lsf_device_registration_source source;\n'
        '\tif (lsf_factory_device_registration_kobject(kobj, &source) != 1 ||\n'
        '\t    lsf_factory_device_registration_current(source) != 1)\n'
        '\t\treturn 0;\n'
        '\tif (kobj->ktype != &device_ktype || kobj_to_dev(kobj)->class ||\n'
        '\t    (kobj->parent && kobj->parent->ktype && kobj->parent->ktype->child_ns_type))\n'
        '\t\treturn 0;\n\treturn 1;\n}\n#endif\n')


def derive(inputs):
    authenticate(inputs)
    outputs = prior.derive({name: inputs[name] for name in prior.fixture()['source']})
    for name in EXTRAS:
        outputs[name] = inputs[name]
    include = '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_device_sysfs.h>\n#endif\n'
    text = replace(inputs[DIR].decode(), '#include "kernfs-internal.h"\n',
        '#include "kernfs-internal.h"\n' + include +
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "lsf-device-sysfs.c"\n#endif\n')
    raw = section(text, 'kernfs_free_rcu')
    text = replace(text, raw, final_node(raw))
    raw = section(text, '__kernfs_new_node')
    text = replace(text, raw, raw + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' + private_birth(raw) + '#endif\n')
    raw = section(text, 'kernfs_new_node')
    text = replace(text, raw, '#ifdef CONFIG_LSF_STREAM_FACTORY\n' + private_new_node(raw) + '#endif\n' + normal_new_node(raw))
    raw = section(text, 'kernfs_create_dir_ns')
    outputs[DIR] = replace(text, raw, raw + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' + private_create_dir(raw) + '#endif\n').encode()
    text = replace(inputs[LINK].decode(), '#include "kernfs-internal.h"\n', '#include "kernfs-internal.h"\n' + include)
    raw = section(text, 'kernfs_create_link')
    outputs[LINK] = replace(text, raw, '#ifdef CONFIG_LSF_STREAM_FACTORY\n' + private_link(raw) + '#endif\n' + normal_link(raw)).encode()
    text = replace(inputs[SYSFS].decode(), '#include "sysfs.h"\n', '#include "sysfs.h"\n' + include)
    raw = section(text, 'sysfs_warn_dup')
    text = replace(text, raw, raw + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' + private_warning(raw) + '#endif\n')
    raw = section(text, 'sysfs_create_dir_ns')
    outputs[SYSFS] = replace(text, raw, '#ifdef CONFIG_LSF_STREAM_FACTORY\n' + private_sysfs_dir(raw) + '#endif\n' + normal_sysfs_dir(raw)).encode()
    text = replace(inputs[INODE].decode(), '#include "kernfs-internal.h"\n', '#include "kernfs-internal.h"\n' + include)
    for name, operation in (('__kernfs_iattrs', iattrs_guard), ('kernfs_xattr_get', xattr_get_guard), ('kernfs_xattr_set', xattr_set_guard)):
        raw = section(text, name)
        text = replace(text, raw, operation(raw))
    outputs[INODE] = text.encode()
    for filename in (CORE, KOBJECT):
        text = replace(outputs[filename].decode(), '#include <net/lsf_stream_device_core.h>\n',
            '#include <net/lsf_stream_device_core.h>\n#include <net/lsf_stream_device_sysfs.h>\n')
        if filename == CORE:
            raw = section(text, 'device_ktype')
            text = replace(text, raw, kobject_ready(raw))
        else:
            raw = section(text, 'create_dir')
            text = replace(text, raw, kobject_create_guard(raw))
        outputs[filename] = text.encode()
    for filename, name, operation in ((SECURITY, 'security_kernfs_init_security', security_guard),
            (SELINUX, 'selinux_kernfs_init_security', selinux_guard)):
        text = outputs[filename].decode()
        raw = section(text, name)
        text = replace(text, raw, operation(raw))
        # Insert after original headers and pr_fmt, without disturbing their
        # macro order. security.c has no direct kernfs include of its own.
        anchor = '#include <linux/fs.h>\n' if filename == SECURITY else '#include <linux/kernfs.h>\n'
        text = replace(text, anchor, anchor + include)
        if filename == SELINUX:
            text += ('\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
                'bool lsf_prepaid_device_selinux_kernfs_hook(\n'
                '\tint (*candidate)(struct kernfs_node *, struct kernfs_node *))\n'
                '{\n\treturn candidate == selinux_kernfs_init_security;\n}\n#endif\n')
        outputs[filename] = text.encode()
    text = replace(outputs['net/factory.c'].decode(), '#include <net/lsf_stream_device_registration.h>\n',
        '#include <net/lsf_stream_device_registration.h>\n#include <net/lsf_stream_device_sysfs.h>\n')
    outputs['net/factory.c'] = replace(text, '#include "factory-device-registration.c"\n',
        '#include "factory-device-registration.c"\n#include "factory-device-sysfs.c"\n').encode()
    outputs['include/net/lsf_stream_device_sysfs.h'] = (OWNED/'device-sysfs-private.h').read_bytes()
    outputs['net/factory-device-sysfs.c'] = (OWNED/'factory-device-sysfs.c').read_bytes()
    outputs['fs/kernfs/lsf-device-sysfs.c'] = (OWNED/'device-sysfs-kernfs.c').read_bytes()
    return outputs
