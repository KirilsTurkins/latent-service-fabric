"""Review-only, default-off selected PCI INTx source derivation.

No caller should publish or run this until its trace owner and loss-detecting
sink are implemented and reviewed. No runtime or IRQ qualification is claimed.
"""
import hashlib
import json

INPUT_SHA256 = '734180d07b254cf0be8c60c3242654060d6cec2629bf53e05aaa6cf1082d9e14'
FACTORY_SHA256 = 'fb1804f303b869f63cf5c047428b989b0fee4e36a93863cb6681f6a5852afcc6'
PROBE_SHA256 = '5998c05dd4dcf5b2c457cd11163d3dfc47afefdd4c688efacd0d550877516d11'
ADDED = 'net/factory-node-pci-intx.c'

def require(condition, reason):
    if not condition:
        raise ValueError('node-pci-intx-'+reason)

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

def identities(values):
    return {name: identity(raw) for name, raw in sorted(values.items())}

def replace_once(raw, old, new, inverse=False):
    require(raw.count(old) == 1 and (inverse or raw.count(new) == 0), 'unique-anchor')
    return raw.replace(old, new, 1)

def apply(raw, start, end, old, new, inverse=False):
    if start is None:
        return replace_once(raw, old, new, inverse)
    require(raw.count(start) == raw.count(end) == 1, 'unique-region')
    first, last = raw.index(start), raw.index(end)
    require(first < last, 'region-order')
    return raw[:first]+replace_once(raw[first:last], old, new, inverse)+raw[last:]

def transform(values, factory, probe):
    require(type(values) is dict and len(values) == 492 and
        all(type(k) is str and type(v) is bytes for k, v in values.items()), 'input-set')
    before = identities(values)
    digest = hashlib.sha256(json.dumps(before, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    require(digest == INPUT_SHA256, 'complete-input-identity')
    require(type(factory) is bytes and len(factory) == 8421 and
        hashlib.sha256(factory).hexdigest() == FACTORY_SHA256, 'factory-material-identity')
    require(type(probe) is bytes and len(probe) == 5766 and
        hashlib.sha256(probe).hexdigest() == PROBE_SHA256, 'probe-material-identity')
    require(ADDED not in values, 'added-file-collision')
    operations = [
        ('net/Kconfig', None, None,
         b'  This image does not install a production provider or deliver interrupts.\n',
         b'  This image does not install a production provider or deliver interrupts.\n\n'
         b'config LSF_STREAM_NODE_PCI_INTX\n'
         b'\tbool "LSF selected PCI checked INTx qualification image"\n'
         b'\tdepends on LSF_STREAM_NODE_PCI_FIXUP\n\tdefault n\n\thelp\n'
         b'\t  Check the original selected Node and config accesses around one native\n'
         b'\t  INTx mask test and IRQ pin read, then stop before BAR writes.\n'
         b'\t  This does not fund IRQs or install a network consumer.\n'),
        ('net/factory-node-bootstrap.c', None, None,
         b'struct lsf_node_parent {\n',
         b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_INTX\n'
         b'enum lsf_node_intx_phase {\n'
         b'    LSF_NODE_INTX_EMPTY = 0, LSF_NODE_INTX_ARMED = 1,\n'
         b'    LSF_NODE_INTX_PREFLIGHTED = 2, LSF_NODE_INTX_TOGGLE_MAY_HAVE_RUN = 3,\n'
         b'    LSF_NODE_INTX_RESTORE_CLAIMED = 4, LSF_NODE_INTX_RESTORE_WRITTEN = 5,\n'
         b'    LSF_NODE_INTX_OBSERVED = 6,\n};\n#endif\n\nstruct lsf_node_parent {\n'),
        ('net/factory-node-bootstrap.c', None, None,
         b'    unsigned int prefix_fixup, prefix_fixup_count;\n',
         b'    unsigned int prefix_fixup, prefix_fixup_count;\n'
         b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_INTX\n'
         b'    unsigned int prefix_intx_phase, prefix_intx_saved, prefix_intx_pin, prefix_intx_line;\n'
         b'#endif\n'),
        ('net/factory-node-bootstrap.c', None, None,
         b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_FIXUP\n#include "factory-node-pci-fixup.c"\n#endif\n',
         b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_FIXUP\n#include "factory-node-pci-fixup.c"\n#endif\n'
         b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_INTX\n#include "factory-node-pci-intx.c"\n#endif\n'),
        ('drivers/pci/probe.c', None, None,
         b'static void pci_read_irq(struct pci_dev *dev)\n',
         probe+b'\nstatic void pci_read_irq(struct pci_dev *dev)\n'),
        ('drivers/pci/probe.c', None, None,
         b'static void pci_read_irq(struct pci_dev *dev)\n{\n\tunsigned char irq;\n',
         b'static void pci_read_irq(struct pci_dev *dev)\n{\n\tunsigned char irq;\n'
         b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_INTX\n'
         b'\tint selected = lsf_factory_device_pci_owned(dev, sizeof(*dev));\n'
         b'\tif (selected < 0) { lsf_node_intx_fault(); return; }\n'
         b'\tif (selected == 1) { lsf_pci_read_irq_checked(dev); return; }\n'
         b'#endif\n'),
        ('drivers/pci/probe.c', None, None,
         b'static int pci_intx_mask_broken(struct pci_dev *dev)\n{\n\tu16 orig, toggle, new;\n',
         b'static int pci_intx_mask_broken(struct pci_dev *dev)\n{\n\tu16 orig, toggle, new;\n'
         b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_INTX\n'
         b'\tint selected = lsf_factory_device_pci_owned(dev, sizeof(*dev));\n'
         b'\tif (selected < 0) { lsf_node_intx_fault(); return 1; }\n'
         b'\tif (selected == 1) return lsf_pci_intx_mask_broken_checked(dev);\n'
         b'#endif\n'),
        ('drivers/pci/probe.c', None, None,
         b'\tunsigned int lsf_fixup_before, lsf_fixup_after;\n#endif\n\tstruct pci_bus_region region;\n',
         b'\tunsigned int lsf_fixup_before, lsf_fixup_after;\n#endif\n'
         b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_INTX\n'
         b'\tu16 lsf_command, lsf_after_command;\n\tu8 lsf_pin, lsf_line, lsf_after_pin, lsf_after_line;\n'
         b'#endif\n\tstruct pci_bus_region region;\n'),
        ('drivers/pci/probe.c', None, None,
         b'\t/* No INTx toggle, BAR probe, registration or binding in this profile. */\n'
         b'\treturn -ECANCELED;\n#endif\n',
         b'#ifndef CONFIG_LSF_STREAM_NODE_PCI_INTX\n'
         b'\t/* No INTx toggle, BAR probe, registration or binding in this profile. */\n'
         b'\treturn -ECANCELED;\n#else\n'
         b'\tif (lsf_node_intx_begin(dev) != 1 || !pci_is_root_bus(dev->bus) ||\n'
         b'\t    pci_upstream_bridge(dev) || dev->non_compliant_bars || dev->is_virtfn) {\n'
         b'\t\tlsf_node_intx_fault();\n\t\treturn -EOPNOTSUPP;\n\t}\n'
         b'#endif\n#endif\n'),
        ('drivers/pci/probe.c', b'int lsf_prepaid_pci_setup_device(',
         b'static struct pci_dev *lsf_prepaid_pci_scan_device(',
         b'\tdev->broken_intx_masking = pci_intx_mask_broken(dev);\n',
         b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_INTX\n'
         b'\tif (!lsf_pci_intx_snapshot(dev, &lsf_command, &lsf_pin, &lsf_line, true)) {\n'
         b'\t\tlsf_node_intx_fault();\n\t\treturn -EOPNOTSUPP;\n\t}\n#endif\n'
         b'\tdev->broken_intx_masking = pci_intx_mask_broken(dev);\n'
         b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_INTX\n'
         b'\tif (dev->broken_intx_masking || !lsf_node_intx_forward(dev)) {\n'
         b'\t\tlsf_node_intx_fault();\n\t\treturn -EOPNOTSUPP;\n\t}\n#endif\n'),
        ('drivers/pci/probe.c', b'int lsf_prepaid_pci_setup_device(',
         b'static struct pci_dev *lsf_prepaid_pci_scan_device(',
         b'\t\tpci_read_irq(dev);\n\t\tpci_read_bases(dev, 6, PCI_ROM_ADDRESS);\n',
         b'\t\tpci_read_irq(dev);\n#ifdef CONFIG_LSF_STREAM_NODE_PCI_INTX\n'
         b'\t\tif (!lsf_pci_intx_snapshot(dev, &lsf_after_command, &lsf_after_pin, &lsf_after_line, false) ||\n'
         b'\t\t    lsf_after_command != lsf_command || lsf_after_pin != lsf_pin ||\n'
         b'\t\t    lsf_after_line != lsf_line ||\n'
         b'\t\t    !lsf_node_intx_observed(dev, lsf_command, lsf_pin, lsf_line)) {\n'
         b'\t\t\tlsf_node_intx_fault();\n\t\t\treturn -EOPNOTSUPP;\n\t\t}\n'
         b'\t\t/* No BAR probe, registration, bind or installed IRQ. */\n'
         b'\t\treturn -ECANCELED;\n#endif\n'
         b'\t\tpci_read_bases(dev, 6, PCI_ROM_ADDRESS);\n'),
        ('net/factory-node-pci-setup.c', None, None,
         b'        node->prefix_fixup_count > 512u)\n        goto poison;\n#endif\n',
         b'        node->prefix_fixup_count > 512u)\n        goto poison;\n#endif\n'
         b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_INTX\n'
         b'    if (!node || node->prefix_intx_phase != LSF_NODE_INTX_OBSERVED)\n'
         b'        goto poison;\n#endif\n'),
        ('net/factory-node-pci-setup.c', None, None,
         b'            node->prefix_fixup_count > 512u ||\n#endif\n',
         b'            node->prefix_fixup_count > 512u ||\n#endif\n'
         b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_INTX\n'
         b'            node->prefix_intx_phase != LSF_NODE_INTX_OBSERVED ||\n#endif\n'),
        ('net/factory-node-pci-prefix.c', None, None,
         b'        after->prefix_fixup_count > 512u)\n        goto poison;\n#endif\n',
         b'        after->prefix_fixup_count > 512u)\n        goto poison;\n#endif\n'
         b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_INTX\n'
         b'    if (after->prefix_intx_phase != LSF_NODE_INTX_OBSERVED)\n'
         b'        goto poison;\n#endif\n'),
        ('net/factory-node-pci-prefix.c', None, None,
         b'    pr_notice("LSFQ35PCIFIXUP1 entries=%u matches=0 dispatcher=1 intxCheck=0 barProbe=0 registered=0\\n",\n'
         b'        after->prefix_fixup_count);\n',
         b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_INTX\n'
         b'    pr_notice("LSFQ35PCIFIXUP1 entries=%u matches=0 dispatcher=1 intxCheck=1 barProbe=0 registered=0\\n",\n'
         b'        after->prefix_fixup_count);\n'
         b'    pr_notice("LSFQ35PCIINTX1 command=%04x pin=%u line=%u restored=1 barProbe=0 registered=0\\n",\n'
         b'        after->prefix_intx_saved, after->prefix_intx_pin, after->prefix_intx_line);\n'
         b'#else\n'
         b'    pr_notice("LSFQ35PCIFIXUP1 entries=%u matches=0 dispatcher=1 intxCheck=0 barProbe=0 registered=0\\n",\n'
         b'        after->prefix_fixup_count);\n#endif\n'),
    ]
    result, changed = dict(values), set()
    for name, start, end, old, new in operations:
        require(name in result and old != new, 'exact-input')
        result[name] = apply(result[name], start, end, old, new)
        changed.add(name)
    inverse = dict(result)
    for name, start, end, old, new in reversed(operations):
        inverse[name] = apply(inverse[name], start, end, new, old, True)
    require(all(inverse[name] == values[name] for name in changed), 'whole-file-inverse')
    require(all(result[name] == raw for name, raw in values.items() if name not in changed), 'other-inputs-exact')
    result[ADDED] = factory
    require(len(result) == 493 and sum(map(len, result.values())) <= 16*1024**2, 'original-source-bounds')
    return result, {'before': before, 'after': identities(result), 'added': ADDED,
        'changedFiles': sorted(changed), 'originalBodiesInverseExact': True,
        'defaultOff': True, 'actualExecutionObserved': False,
        'irqEnabled': False, 'consumerInstalled': False, 'tcpEnabled': False,
        'nodeFundingQualified': False, 'nodeRetirementQualified': False,
        'sharedInterruptCustodyQualified': False}
