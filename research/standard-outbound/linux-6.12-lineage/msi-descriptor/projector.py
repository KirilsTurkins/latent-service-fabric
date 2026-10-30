"""Uninstalled original-bank MSI descriptor/device-XArray prefix.

Append to the frozen 451 outputs. IRQ descriptors/controllers/actions stay closed.
All four complete C/H materials are separate pinned research files.
"""
import hashlib
import json
from pathlib import Path
from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_device_security import function
from tools.host_stream_kernel_cleanup_native import require
from tools.rust_capsule_project import read_file
ROOT = Path(__file__).resolve().parents[4]
INPUT_SHA = 'ca7d71dce015fe73d00d389ba196d8411cd32a16580d1fe04b39aee5b7425cda'
PREIMAGES = {'kernel/irq/msi.c': (50900, 'e3a694a9cf4964100f1653b8b4b399881b7f8bf72ffbc5109ca173bd269ba5cd'), 'drivers/pci/msi/irqdomain.c': (13880, '12a6036306d82f929879679395c1e7a93cb3ca0f815f65e2caf32d20212be3b0'), 'drivers/pci/msi/lsf-stream-q35-table.c': (4238, '7f529fc8a21eea42b510029a25691b6f081ca955d0bacca3be005172a90ecafc'), 'net/factory.c': (38276, 'f9e9615290ef43558537614eea0a7d0b120d2f906d900012334f84626b16376b'), 'net/device-prepaid.h': (19613, 'ed1fe5bd97a3e0a92adc522c06a80c2ce25549df69535cdaa0e887953f8abf63'), 'lib/radix-tree.c': (61226, '636c87fdd50597fcaefe2fea571f213462d9bec2612c1602b613b7ca585b7f3b')}
PRIMARY = {'lib/xarray.c': (61079, 'b35b4f31434c62d4dfb08a65b5df8074cc55011d6814d4980b6444f8234ecf7a')}
CONTEXT = {'include/linux/xarray.h': (59453, '3b98cad8f1a4234b7520720819012bc1344dfa4b0df16b215df7c994d798eb36')}
MATERIAL_PATHS = {'kernel/irq/lsf-stream-msi-descriptor.c': 'research/standard-outbound/linux-6.12-lineage/msi-descriptor/lsf-stream-msi-descriptor.c', 'lib/lsf-stream-msi-xarray.c': 'research/standard-outbound/linux-6.12-lineage/msi-descriptor/lsf-stream-msi-xarray.c', 'net/factory-stream-msi-descriptor.c': 'research/standard-outbound/linux-6.12-lineage/msi-descriptor/factory-stream-msi-descriptor.c', 'include/net/lsf_stream_msi_descriptor_private.h': 'research/standard-outbound/linux-6.12-lineage/msi-descriptor/lsf_stream_msi_descriptor_private.h'}
MATERIAL_PINS = {'kernel/irq/lsf-stream-msi-descriptor.c': (5728, '099950aa9e5c88f6758b2c48568a219c20dfe5101b7baec75025635754bc42b5'), 'lib/lsf-stream-msi-xarray.c': (4414, '09e4c0998d9d0d30551df5c1d01e97f6377fb7c2ab66186d472fe43b5fd34b86'), 'net/factory-stream-msi-descriptor.c': (18511, '2c675f2606b9aa3f237593528bc62c751573819d6e27bb20621ab380d877a954'), 'include/net/lsf_stream_msi_descriptor_private.h': (1800, 'e26a1b1a11207344a76be4516a7edf1e1b36dada7c1f71851de07b2c54ba468d')}


def _bound(raw, pin):
    return type(raw) is bytes and len(raw) == pin[0] and hashlib.sha256(raw).hexdigest() == pin[1]


def materials(root=ROOT):
    require(set(MATERIAL_PATHS) == set(MATERIAL_PINS) and
        len(set(MATERIAL_PATHS.values())) == len(MATERIAL_PINS) == 4, 'msi-store-material-set')
    result = {}
    for name, pin in MATERIAL_PINS.items():
        raw = read_file(root / MATERIAL_PATHS[name], pin[0])
        require(_bound(raw, pin) and b'\r' not in raw, 'msi-store-material-identity')
        result[name] = raw
    require(sum(map(len, result.values())) <= 128 * 1024, 'msi-store-material-total')
    return result


def _wrap(original, branch):
    at = original.index('\n{\n')
    return original[:at] + '\n{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' + branch + '#endif\n' + original[at+1:] + '}\n'


def edit_inputs(affected, primary):
    require(type(affected) is dict and set(affected) == set(PREIMAGES), 'msi-store-affected-set')
    require(type(primary) is dict and set(primary) == set(PRIMARY) | set(CONTEXT), 'msi-store-native-set')
    for name, pin in PREIMAGES.items(): require(_bound(affected[name], pin), 'msi-store-before-identity')
    for name, pin in {**PRIMARY, **CONTEXT}.items(): require(_bound(primary[name], pin), 'msi-store-native-identity')
    result = dict(affected)
    result.update({n: primary[n] for n in PRIMARY})
    def editor(name, anchor):
        e = Editor(result[name].decode('utf-8'))
        e.edit(anchor, anchor + '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_msi_descriptor_private.h>\n#endif\n')
        return e
    def append(e, part):
        e.edit(e.text, e.text + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "' + part + '"\n#endif\n')

    msi = editor('kernel/irq/msi.c', '#include <linux/xarray.h>\n')
    old = function(msi.text, 'static struct msi_desc *msi_alloc_desc(')
    msi.edit(old, _wrap(old, '\tint selected = lsf_factory_stream_msi_selected(dev);\n'
        '\tif (selected) { lsf_factory_stream_constructor_retain_unknown(); return NULL; }\n'))
    old = function(msi.text, 'static void msi_free_desc(')
    msi.edit(old, _wrap(old, '\tif (lsf_msi_descriptor_free(desc)) return;\n'))
    old = function(msi.text, 'static int msi_insert_desc(')
    msi.edit(old, _wrap(old, '\tint selected = lsf_factory_stream_msi_selected(dev);\n'
        '\tif (selected && (selected < 0 || !lsf_msi_descriptor_insert_allowed(dev, desc, domid, index))) {\n'
        '\t\tlsf_factory_stream_constructor_retain_unknown(); msi_free_desc(desc); return -EOPNOTSUPP;\n\t}\n'))
    old = function(msi.text, 'int msi_domain_insert_msi_desc(')
    msi.edit(old, _wrap(old, '\tint selected = lsf_factory_stream_msi_selected(dev);\n'
        '\tif (selected) {\n\t\tstruct msi_desc *paid;\n'
        '\t\tif (selected < 0) { lsf_factory_stream_constructor_retain_unknown(); return -EOPNOTSUPP; }\n'
        '\t\tpaid = lsf_msi_descriptor_allocate(dev, domid, init_desc);\n'
        '\t\treturn paid ? msi_insert_desc(dev, paid, domid, init_desc->msi_index) : -ENOMEM;\n\t}\n'))
    append(msi, 'lsf-stream-msi-descriptor.c')
    result['kernel/irq/msi.c'] = msi.finish().encode()

    pci = editor('drivers/pci/msi/irqdomain.c', '#include <linux/of_irq.h>\n')
    old = function(pci.text, 'int pci_msi_setup_msi_irqs(')
    pci.edit(old, _wrap(old, '\tint selected = lsf_factory_stream_msi_selected(&dev->dev);\n'
        '\tif (selected) {\n\t\tif (selected < 0) { lsf_factory_stream_constructor_retain_unknown(); return -EOPNOTSUPP; }\n'
        '\t\treturn lsf_msi_descriptor_setup(dev, nvec, type);\n\t}\n'))
    result['drivers/pci/msi/irqdomain.c'] = pci.finish().encode()

    table = editor('drivers/pci/msi/lsf-stream-q35-table.c', '#include <net/lsf_stream_constructor_mmio_private.h>\n')
    old = function(table.text, 'static int lsf_q35_msix_interrupts_closed(')
    new = old[:old.index('\n{\n')] + '\n{\n'
    new += '\tif (entries || affd || (nvec != 2 && nvec != 3)) return -EOPNOTSUPP;\n'
    new += '\t/* Real descriptors/store only. pci_msi_setup_msi_irqs refuses before IRQ births. */\n'
    new += '\treturn msix_setup_interrupts(dev, entries, nvec, affd);\n}\n'
    table.edit(old, new)
    old = function(table.text, 'static int lsf_q35_msix_capability_init(')
    new = old.replace('\tunsigned int prepaid_tsize;','\tunsigned int prepaid_tsize;\n\tstruct lsf_msi_store_plan descriptors = {};',1)
    anchor='\t    lsf_q35_msi_current(&dev->dev) != 1) return -EOPNOTSUPP;\n'
    require(new.count(anchor) == 1, 'msi-store-exact-table-shape')
    new = new.replace(anchor, anchor + '\tret = lsf_msi_descriptor_prepare(dev, nvec, &descriptors);\n\tif (ret != 1) return ret < 0 ? ret : -ENOMEM;\n',1)
    new = new.replace('\tif (!paid) return -ENOMEM;', '\tif (!paid) { lsf_msi_store_discard(&dev->dev, &descriptors); return -ENOMEM; }',1)
    new = new.replace('\treturn 0;', '\tlsf_msi_store_discard(&dev->dev, &descriptors);\n\treturn 0;',1)
    new = new.replace('\n\treturn ret;', '\n\tlsf_msi_store_discard(&dev->dev, &descriptors);\n\treturn ret;',1)
    table.edit(old,new)
    result['drivers/pci/msi/lsf-stream-q35-table.c'] = table.finish().encode()

    xa = editor('lib/xarray.c', '#include <linux/xarray.h>\n')
    prototypes = ('#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        'static struct xa_node *lsf_msi_xas_alloc(struct xa_state *, unsigned int);\n'
        'static bool lsf_msi_xas_nomem(struct xa_state *, gfp_t);\n'
        'static bool lsf_msi_internal_xas_nomem(struct xa_state *, gfp_t);\n'
        'static void lsf_msi_xas_destroy(struct xa_state *);\n#endif\n')
    xa.edit('#include "radix-tree.h"\n', '#include "radix-tree.h"\n' + prototypes)
    for prefix, call in [('static void *xas_alloc(', 'lsf_msi_xas_alloc(xas, shift)'),
        ('bool xas_nomem(', 'lsf_msi_xas_nomem(xas, gfp)'),
        ('static bool __xas_nomem(', 'lsf_msi_internal_xas_nomem(xas, gfp)')]:
        old = function(xa.text, prefix)
        xa.edit(old, _wrap(old, '\tint selected = lsf_msi_store_xa_selected(xas->xa);\n'
            '\tif (selected) {\n\t\tif (selected < 0) { xas_set_err(xas, -EOPNOTSUPP); return 0; }\n'
            '\t\treturn ' + call + ';\n\t}\n'))
    old = function(xa.text, 'void xas_destroy(')
    xa.edit(old, _wrap(old, '\tint selected = lsf_msi_store_xa_selected(xas->xa);\n'
        '\tif (selected) { if (selected > 0) lsf_msi_xas_destroy(xas); return; }\n'))
    old = function(xa.text, 'int __xa_insert(')
    xa.edit(old, _wrap(old, '\tint selected = lsf_msi_store_xa_selected(xa);\n'
        '\tif (selected && (selected < 0 || !lsf_msi_xa_insert_allowed(xa, index, entry))) {\n'
        '\t\tlsf_factory_stream_constructor_retain_unknown(); return -EOPNOTSUPP;\n\t}\n'))
    old = function(xa.text, 'void xas_split_alloc(')
    xa.edit(old, _wrap(old, '\tint selected = lsf_msi_store_xa_selected(xas->xa);\n'
        '\tif (selected) { xas_destroy(xas); xas_set_err(xas, -EOPNOTSUPP); return; }\n'))
    append(xa, 'lsf-stream-msi-xarray.c')
    result['lib/xarray.c'] = xa.finish().encode()

    radix = editor('lib/radix-tree.c', '#include <linux/xarray.h>\n')
    old = function(radix.text, 'void radix_tree_node_rcu_free(')
    radix.edit(old, _wrap(old, '\tstruct radix_tree_node *paid = container_of(head, struct radix_tree_node, rcu_head);\n'
        '\tint selected = lsf_msi_store_radix_selected(paid);\n'
        '\tstatic_assert(sizeof(struct radix_tree_node) == sizeof(struct xa_node));\n'
        '\tstatic_assert(__alignof__(struct radix_tree_node) == __alignof__(struct xa_node));\n'
        '\tif (selected) {\n\t\tif (selected < 0) return;\n'
        '\t\tmemset(paid->slots, 0, sizeof(paid->slots));\n\t\tmemset(paid->tags, 0, sizeof(paid->tags));\n'
        '\t\tINIT_LIST_HEAD(&paid->private_list);\n'
        '\t\t(void)lsf_msi_store_retire(paid, LSF_MSI_NODE_ROLE); return;\n\t}\n'))
    result['lib/radix-tree.c'] = radix.finish().encode()
    kinds = Editor(result['net/device-prepaid.h'].decode())
    kinds.edit('    return (kind >= 0x1a0u && kind < 0x1a6u) ||',
        '    return (kind >= LSF_MSI_DESC_KIND && kind < LSF_MSI_DESC_KIND + LSF_MSI_STORE_PARTS) ||\n        (kind >= 0x1a0u && kind < 0x1a6u) ||')
    kinds.edit('#include "prepaid.h"\n', '#include "prepaid.h"\n#include <net/lsf_stream_msi_descriptor_private.h>\n')
    result['net/device-prepaid.h'] = kinds.finish().encode()
    factory = Editor(result['net/factory.c'].decode())
    append(factory, 'factory-stream-msi-descriptor.c')
    result['net/factory.c'] = factory.finish().encode()
    return result


def transform(outputs, primary):
    require(type(outputs) is dict and len(outputs) == 451 and
        all(type(n) is str and type(b) is bytes for n, b in outputs.items()), 'msi-store-whole-shape')
    encoded = (json.dumps({n: {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()}
        for n, b in outputs.items()}, sort_keys=True, separators=(',', ':')) + '\n').encode()
    require(hashlib.sha256(encoded).hexdigest() == INPUT_SHA, 'msi-store-whole451-identity')
    require(not(set(PRIMARY) & set(outputs)) and not(set(MATERIAL_PINS) & set(outputs)), 'msi-store-new-paths')
    result = dict(outputs)
    result.update(edit_inputs({n: outputs[n] for n in PREIMAGES}, primary))
    result.update(materials())
    require(len(result) == 456, 'msi-store-whole456-count')
    require(b'return NULL;' in result['net/factory.c'] and
        b'lsf_factory_selected_consumer' in result['net/factory.c'], 'msi-store-consumer-remains-closed')
    return result
