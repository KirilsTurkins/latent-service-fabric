"""WIP same-branch registration/explicit IDR producers; not an installed profile."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_device_capabilities as prior

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_device_registration.json'
RADIX = 'lib/radix-tree.c'
IDR = 'lib/idr.c'
EXTRAS = {RADIX, IDR, 'include/linux/radix-tree.h', 'include/linux/idr.h',
    'include/linux/kernfs.h'}
DEFINITIONS = {'radix_tree_node_alloc', 'radix_tree_extend', 'idr_get_free',
    'radix_tree_node_ctor', 'radix_tree_node_rcu_free', 'idr_alloc_u32', 'idr_alloc_cyclic'}
GATES = prior.GATES + ('actualDeviceRegistrationExecuted', 'completeDeviceRegistration')
replace = prior.replace
require = prior.require


def fixture():
    value = json.loads(FIXTURE.read_bytes())
    parent = prior.fixture()
    require(value['schemaVersion'] == 'lsf.kernel-device-registration-source.v1' and
        value['upstreamCommit'] == parent['upstreamCommit'] and
        value['archiveSha256'] == parent['archiveSha256'], 'device-registration-maintained-identity')
    require(set(value['source']) == set(parent['source']) | EXTRAS and
        all(value['source'][name] == row for name, row in parent['source'].items()),
        'device-registration-whole-membership')
    require(set(value['sections']) == set(parent['sections']) | DEFINITIONS and
        all(value['sections'][name] == row for name, row in parent['sections'].items()),
        'device-registration-original-definitions')
    require(all(value[name] is False for name in GATES), 'device-registration-uninstalled')
    return value


def section(text, name):
    row = fixture()['sections'][name]
    starts = [i for i in range(len(text)) if text.startswith(row['prefix'], i) and
        (not i or text[i - 1] == '\n')]
    require(len(starts) == 1, 'device-registration-definition-occurrence')
    end = text.find('\n}\n', starts[0])
    require(end >= 0, 'device-registration-definition-end')
    raw = text[starts[0]:end + 3]
    require(raw == row['text'] and len(raw.encode()) == row['bytes'] and
        hashlib.sha256(raw.encode()).hexdigest() == row['sha256'],
        'device-registration-definition-preimage')
    return raw


def authenticate(inputs):
    value = fixture()
    require(set(inputs) == set(value['source']), 'device-registration-whole-membership')
    prior.prior.prior.prior.prior.prior.route.bind.avc.maintained.authenticate_files(inputs, value['source'])
    prior.authenticate({name: inputs[name] for name in prior.fixture()['source']})
    for name, row in value['sections'].items():
        section(inputs[row['source']].decode(), name)


def private_node_alloc(raw):
    require(section(raw, 'radix_tree_node_alloc') == raw, 'device-registration-radix-allocator-preimage')
    text = replace(raw, 'radix_tree_node_alloc(gfp_t gfp_mask,',
        'lsf_prepaid_device_radix_node_alloc(struct lsf_device_registration_source source,\n\t\t\tgfp_t gfp_mask,')
    start = text.index('\tstruct radix_tree_node *ret = NULL;\n')
    end = text.index('out:\n', start) + len('out:\n')
    # No SLUB or per-CPU preload fallback. Keep actual maintained constructor
    # and every shift/offset/count/parent/array assignment following this hunk.
    text = text[:start] + ('\tstruct radix_tree_node *ret;\n\n'
        '\t(void)gfp_mask;\n'
        '\tif (IS_ENABLED(CONFIG_DEBUG_KMEMLEAK))\n\t\treturn NULL;\n'
        '\tret = lsf_factory_device_registration_allocate(source,\n'
        '\t\tsizeof(*ret), LSF_REGISTRATION_KIND_IDR_NODE);\n') + text[end:]
    return replace(text, '\tif (ret) {\n\t\tret->shift = shift;\n',
        '\tif (ret) {\n\t\tradix_tree_node_ctor(ret);\n\t\tret->shift = shift;\n')


def private_extend(raw):
    require(section(raw, 'radix_tree_extend') == raw, 'device-registration-radix-extension-preimage')
    text = replace(raw, 'static int radix_tree_extend(struct radix_tree_root *root, gfp_t gfp,',
        'static int lsf_prepaid_device_radix_extend(struct lsf_device_registration_source source,\n'
        '\t\t\t\tstruct radix_tree_root *root, gfp_t gfp,')
    return replace(text, 'radix_tree_node_alloc(gfp, NULL,',
        'lsf_prepaid_device_radix_node_alloc(source, gfp, NULL,')


def private_get_free(raw):
    require(section(raw, 'idr_get_free') == raw, 'device-registration-idr-walk-preimage')
    text = replace(raw, 'void __rcu **idr_get_free(struct radix_tree_root *root,',
        'void __rcu **lsf_prepaid_device_idr_get_free(struct lsf_device_registration_source source,\n'
        '\t\t\t      struct radix_tree_root *root,')
    # This cross-TU entry is also guarded before the allocation-free walk can
    # update a shared existing IDR. Allocation hooks alone cannot admit that.
    text = replace(text, '\tshift = radix_tree_load_root(root, &child, &maxindex);\n',
        '\tif (source.kind != LSF_REGISTRATION_KIND_NODE ||\n'
        '\t    lsf_factory_device_registration_current(source) != 1)\n'
        '\t\treturn ERR_PTR(-EOPNOTSUPP);\n\n'
        '\tshift = radix_tree_load_root(root, &child, &maxindex);\n')
    text = replace(text, 'radix_tree_extend(root, gfp, start, shift)',
        'lsf_prepaid_device_radix_extend(source, root, gfp, start, shift)')
    return replace(text, 'radix_tree_node_alloc(gfp, node, root, shift,',
        'lsf_prepaid_device_radix_node_alloc(source, gfp, node, root, shift,')


def private_alloc_u32(raw):
    require(section(raw, 'idr_alloc_u32') == raw, 'device-registration-idr-allocation-preimage')
    text = replace(raw, 'int idr_alloc_u32(struct idr *idr, void *ptr, u32 *nextid,',
        'static int lsf_prepaid_device_idr_alloc_u32(struct lsf_device_registration_source source,\n'
        '\t\t\tstruct idr *idr, void *ptr, u32 *nextid,')
    return replace(text, 'idr_get_free(&idr->idr_rt, &iter, gfp, max - base)',
        'lsf_prepaid_device_idr_get_free(source, &idr->idr_rt, &iter, gfp, max - base)')


def private_cyclic(raw):
    require(section(raw, 'idr_alloc_cyclic') == raw, 'device-registration-idr-cycle-preimage')
    text = replace(raw, 'int idr_alloc_cyclic(struct idr *idr, void *ptr, int start, int end, gfp_t gfp)',
        'int lsf_prepaid_device_idr_alloc_cyclic(struct lsf_device_registration_source source,\n'
        '\t\t\tstruct idr *idr, void *ptr, int start, int end, gfp_t gfp)')
    # The source is the very node being inserted, not a per-task or ordinary
    # shared-parent ownership inference. Revalidation still happens per birth.
    text = replace(text, '\tint err, max = end > 0 ? end - 1 : INT_MAX;\n',
        '\tint err, max = end > 0 ? end - 1 : INT_MAX;\n\n'
        '\tif (source.kind != LSF_REGISTRATION_KIND_NODE || source.address != ptr ||\n'
        '\t    lsf_factory_device_registration_current(source) != 1)\n'
        '\t\treturn -EOPNOTSUPP;\n')
    require(text.count('idr_alloc_u32(idr, ptr, &id, max, gfp)') == 2,
        'device-registration-idr-two-original-attempts')
    return text.replace('idr_alloc_u32(idr, ptr, &id, max, gfp)',
        'lsf_prepaid_device_idr_alloc_u32(source, idr, ptr, &id, max, gfp)')


def final_radix_free(raw):
    require(section(raw, 'radix_tree_node_rcu_free') == raw, 'device-registration-radix-final-preimage')
    text = replace(raw, '\t\t\tcontainer_of(head, struct radix_tree_node, rcu_head);\n',
        '\t\t\tcontainer_of(head, struct radix_tree_node, rcu_head);\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tstruct lsf_device_registration_source lsf_source;\n'
        '\tint lsf_owned = lsf_factory_device_registration_return_begin(node,\n'
        '\t\tLSF_REGISTRATION_KIND_IDR_NODE, &lsf_source);\n'
        '\tif (lsf_owned < 0)\n\t\treturn;\n#endif\n')
    return replace(text, '\tkmem_cache_free(radix_tree_node_cachep, node);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n\tif (lsf_owned) {\n'
        '\t\t(void)lsf_factory_device_registration_return_finish(lsf_source);\n'
        '\t\treturn;\n\t}\n#endif\n\tkmem_cache_free(radix_tree_node_cachep, node);\n')


def derive(inputs):
    authenticate(inputs)
    outputs = prior.derive({name: inputs[name] for name in prior.fixture()['source']})
    for name in EXTRAS:
        outputs[name] = inputs[name]
    include = '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_device_registration.h>\n#endif\n'
    text = inputs[RADIX].decode()
    text = replace(text, '#include <linux/radix-tree.h>\n', '#include <linux/radix-tree.h>\n' + include)
    raw = section(text, 'radix_tree_node_rcu_free')
    text = replace(text, raw, final_radix_free(raw))
    # Every original pure/static dependency and the real cache constructor is
    # defined above this insertion. Ordinary producers remain complete/exact.
    raw = section(text, 'radix_tree_node_ctor')
    clones = '\n'.join(operation(section(inputs[RADIX].decode(), name)) for name, operation in (
        ('radix_tree_node_alloc', private_node_alloc), ('radix_tree_extend', private_extend),
        ('idr_get_free', private_get_free)))
    outputs[RADIX] = replace(text, raw, raw + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' + clones + '#endif\n').encode()
    text = replace(inputs[IDR].decode(), '#include <linux/xarray.h>\n',
        '#include <linux/xarray.h>\n' + include)
    text += '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' + private_alloc_u32(section(text, 'idr_alloc_u32')) + '\n'
    text += private_cyclic(section(inputs[IDR].decode(), 'idr_alloc_cyclic')) + '#endif\n'
    outputs[IDR] = text.encode()
    text = replace(outputs['net/device-prepaid.h'].decode(), '    LSF_DEVICE_CAP_SAVE\n',
        '    LSF_DEVICE_CAP_SAVE,\n    LSF_DEVICE_KERNFS_NODE,\n'
        '    LSF_DEVICE_KERNFS_NAME,\n    LSF_DEVICE_IDR_NODE\n')
    outputs['net/device-prepaid.h'] = replace(text, 'kind == LSF_DEVICE_CAP_SAVE;',
        'kind == LSF_DEVICE_CAP_SAVE || kind == LSF_DEVICE_KERNFS_NODE ||\n'
        '        kind == LSF_DEVICE_KERNFS_NAME || kind == LSF_DEVICE_IDR_NODE;').encode()
    text = replace(outputs['net/factory.c'].decode(), '#include <net/lsf_stream_device_capabilities.h>\n',
        '#include <net/lsf_stream_device_capabilities.h>\n'
        '#include <net/lsf_stream_device_registration.h>\n#include <linux/kernfs.h>\n'
        '#include <linux/radix-tree.h>\n')
    text = replace(text, '#include "factory-device-firmware.c"\n',
        'static int lsf_factory_device_registration_pending_locked(void);\n'
        '#include "factory-device-firmware.c"\n')
    outputs['net/factory.c'] = replace(text, '#include "factory-device-capabilities.c"\n',
        '#include "factory-device-capabilities.c"\n#include "factory-device-registration.c"\n').encode()
    text = replace(outputs['net/factory-device.c'].decode(),
        '    unsigned int pci_attempted, constructor_active;\n',
        '    unsigned int pci_attempted, constructor_active;\n'
        '    struct task_struct *constructor_task;\n')
    # Every actual leave call follows successful enter in the same synchronous
    # scan task and therefore owns factory_lock. Revoke failure retains the
    # poisoned active/borrow fence, but may not strand this known-held mutex.
    text = replace(text,
        'void lsf_factory_device_pci_leave(void)\n{\n    mutex_unlock(&factory_lock);\n',
        'void lsf_factory_device_pci_leave(void)\n{\n'
        '    int revoked = lsf_factory_device_registration_constructor_revoke();\n'
        '    mutex_unlock(&factory_lock);\n'
        '    if (!revoked)\n        return;\n')
    outputs['net/factory-device.c'] = text.encode()
    text = outputs['net/factory-device-firmware.c'].decode()
    text = replace(text, 'if (factory.device && !factory.device->constructor_active) {\n',
        'if (factory.device && !factory.device->constructor_active &&\n'
        '        !factory.device->constructor_task) {\n')
    text = replace(text, '        factory.device->constructor_active = 1;\n',
        '        factory.device->constructor_active = 1;\n'
        '        factory.device->constructor_task = current;\n')
    text = replace(text, 'if (!factory.device || !factory.device->constructor_active) {\n',
        'if (!factory.device || !factory.device->constructor_active ||\n'
        '        factory.device->constructor_task) {\n')
    text = replace(text, '(owned->core_initialized && !owned->core_tail_complete) ||\n',
        '(owned->core_initialized && !owned->core_tail_complete) ||\n'
        '        lsf_factory_device_registration_pending_locked() ||\n')
    text = replace(text, '    if (!lsf_device_queue(&factory.pool, factory.device->key,\n',
        '    if (lsf_factory_device_registration_pending_locked())\n        goto out;\n'
        '    if (!lsf_device_queue(&factory.pool, factory.device->key,\n')
    outputs['net/factory-device-firmware.c'] = text.encode()
    outputs['include/net/lsf_stream_device_registration.h'] = (OWNED/'device-registration-private.h').read_bytes()
    outputs['net/factory-device-registration.c'] = (OWNED/'factory-device-registration.c').read_bytes()
    return outputs
