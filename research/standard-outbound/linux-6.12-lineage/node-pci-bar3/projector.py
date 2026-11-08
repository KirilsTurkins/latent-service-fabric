"""Default-off, guarded q35 BAR3 sizing slice, layered on the INTx image.

The separate guarded QEMU owner is required: reading zero alone does not prove
that a BAR is unimplemented. This does not qualify ordinary BAR sizing.
"""
import hashlib
import json

INPUT_SHA256 = 'e52a472177edb56bc9a38620eb0201e4805e5cfe507fd41e236368143e3abd24'
FACTORY_SHA256 = '0dc467258451df8e38451989f7e58614045c286a6d56497eda315d01e7e55d05'
PROBE_SHA256 = 'cba659a94d447ac84e11ec9e03181ff3229adb62d4b4e5054408c195ac963d25'
ADDED = 'net/factory-node-pci-bar3.c'


def require(condition, reason):
    if not condition:
        raise ValueError('node-pci-bar3-' + reason)


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def identities(values):
    return {name: identity(raw) for name, raw in sorted(values.items())}


def replace_once(raw, old, new, inverse=False):
    require(raw.count(old) == 1 and (inverse or raw.count(new) == 0), 'unique-anchor')
    return raw.replace(old, new, 1)


def transform(values, factory, probe):
    require(type(values) is dict and len(values) == 493 and
        all(type(k) is str and type(v) is bytes for k, v in values.items()), 'input-set')
    before = identities(values)
    digest = hashlib.sha256(json.dumps(before, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    require(digest == INPUT_SHA256, 'complete-input-identity')
    require(type(factory) is bytes and len(factory) == 4589 and
        hashlib.sha256(factory).hexdigest() == FACTORY_SHA256, 'factory-material-identity')
    require(type(probe) is bytes and len(probe) == 1707 and
        hashlib.sha256(probe).hexdigest() == PROBE_SHA256, 'probe-material-identity')
    require(ADDED not in values, 'added-file-collision')
    operations = [
        ('net/Kconfig',
         b'\t  This does not fund IRQs or install a network consumer.\n',
         b'\t  This does not fund IRQs or install a network consumer.\n\n'
         b'config LSF_STREAM_NODE_PCI_BAR3\n'
         b'\tbool "LSF guarded q35 unimplemented BAR3 qualification image"\n'
         b'\tdepends on LSF_STREAM_NODE_PCI_INTX\n\tdefault n\n\thelp\n'
         b'\t  Check one unimplemented BAR word under the separate QEMU guard.\n'
         b'\t  This does not size implemented BARs or install a provider.\n'),
        ('net/factory-node-bootstrap.c',
         b'struct lsf_node_parent {\n',
         b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_BAR3\n'
         b'enum lsf_node_bar3_phase {\n'
         b'    LSF_NODE_BAR3_EMPTY = 0, LSF_NODE_BAR3_WRITE_MAY_HAVE_RUN = 1,\n'
         b'    LSF_NODE_BAR3_RESTORE_CLAIMED = 2, LSF_NODE_BAR3_RESTORE_WRITTEN = 3,\n'
         b'    LSF_NODE_BAR3_OBSERVED = 4,\n};\n#endif\n\nstruct lsf_node_parent {\n'),
        ('net/factory-node-bootstrap.c',
         b'    unsigned int prefix_intx_phase, prefix_intx_saved, prefix_intx_pin, prefix_intx_line;\n',
         b'    unsigned int prefix_intx_phase, prefix_intx_saved, prefix_intx_pin, prefix_intx_line;\n'
         b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_BAR3\n'
         b'    unsigned int prefix_bar3_phase, prefix_bar3_saved;\n#endif\n'),
        ('net/factory-node-bootstrap.c',
         b'#include "factory-node-pci-intx.c"\n#endif\n',
         b'#include "factory-node-pci-intx.c"\n#endif\n'
         b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_BAR3\n#include "factory-node-pci-bar3.c"\n#endif\n'),
        ('drivers/pci/probe.c',
         b'static void pci_read_irq(struct pci_dev *dev)\n',
         probe+b'\nstatic void pci_read_irq(struct pci_dev *dev)\n'),
        ('drivers/pci/probe.c',
         b'\t\tpci_read_irq(dev);\n#ifdef CONFIG_LSF_STREAM_NODE_PCI_INTX\n'
         b'\t\tif (!lsf_pci_intx_snapshot(dev, &lsf_after_command, &lsf_after_pin, &lsf_after_line, false) ||\n',
         b'\t\tpci_read_irq(dev);\n#ifdef CONFIG_LSF_STREAM_NODE_PCI_BAR3\n'
         b'\t\tif (!lsf_pci_bar3_checked(dev))\n\t\t\treturn -EOPNOTSUPP;\n#endif\n'
         b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_INTX\n'
         b'\t\tif (!lsf_pci_intx_snapshot(dev, &lsf_after_command, &lsf_after_pin, &lsf_after_line, false) ||\n'),
        ('net/factory-node-pci-setup.c',
         b'    if (!node || node->prefix_intx_phase != LSF_NODE_INTX_OBSERVED)\n'
         b'        goto poison;\n#endif\n',
         b'    if (!node || node->prefix_intx_phase != LSF_NODE_INTX_OBSERVED)\n'
         b'        goto poison;\n#endif\n#ifdef CONFIG_LSF_STREAM_NODE_PCI_BAR3\n'
         b'    if (!node || node->prefix_bar3_phase != LSF_NODE_BAR3_OBSERVED)\n'
         b'        goto poison;\n#endif\n'),
        ('net/factory-node-pci-setup.c',
         b'            node->prefix_intx_phase != LSF_NODE_INTX_OBSERVED ||\n#endif\n',
         b'            node->prefix_intx_phase != LSF_NODE_INTX_OBSERVED ||\n#endif\n'
         b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_BAR3\n'
         b'            node->prefix_bar3_phase != LSF_NODE_BAR3_OBSERVED ||\n#endif\n'),
        ('net/factory-node-pci-prefix.c',
         b'    if (after->prefix_intx_phase != LSF_NODE_INTX_OBSERVED)\n'
         b'        goto poison;\n#endif\n',
         b'    if (after->prefix_intx_phase != LSF_NODE_INTX_OBSERVED)\n'
         b'        goto poison;\n#endif\n#ifdef CONFIG_LSF_STREAM_NODE_PCI_BAR3\n'
         b'    if (after->prefix_bar3_phase != LSF_NODE_BAR3_OBSERVED)\n'
         b'        goto poison;\n#endif\n'),
        ('net/factory-node-pci-prefix.c',
         b'    pr_notice("LSFQ35PCIFIXUP1 entries=%u matches=0 dispatcher=1 intxCheck=1 barProbe=0 registered=0\\n",\n'
         b'        after->prefix_fixup_count);\n'
         b'    pr_notice("LSFQ35PCIINTX1 command=%04x pin=%u line=%u restored=1 barProbe=0 registered=0\\n",\n'
         b'        after->prefix_intx_saved, after->prefix_intx_pin, after->prefix_intx_line);\n',
         b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_BAR3\n'
         b'    pr_notice("LSFQ35PCIFIXUP1 entries=%u matches=0 dispatcher=1 intxCheck=1 barProbe=1 registered=0\\n",\n'
         b'        after->prefix_fixup_count);\n'
         b'    pr_notice("LSFQ35PCIINTX1 command=%04x pin=%u line=%u restored=1 barProbe=1 registered=0\\n",\n'
         b'        after->prefix_intx_saved, after->prefix_intx_pin, after->prefix_intx_line);\n'
         b'    pr_notice("LSFQ35PCIBAR3 saved=%08x restored=1 fullSizing=0 registered=0\\n",\n'
         b'        after->prefix_bar3_saved);\n#else\n'
         b'    pr_notice("LSFQ35PCIFIXUP1 entries=%u matches=0 dispatcher=1 intxCheck=1 barProbe=0 registered=0\\n",\n'
         b'        after->prefix_fixup_count);\n'
         b'    pr_notice("LSFQ35PCIINTX1 command=%04x pin=%u line=%u restored=1 barProbe=0 registered=0\\n",\n'
         b'        after->prefix_intx_saved, after->prefix_intx_pin, after->prefix_intx_line);\n#endif\n'),
    ]
    result, changed = dict(values), set()
    for name, old, new in operations:
        require(name in result and old != new, 'exact-input')
        result[name] = replace_once(result[name], old, new)
        changed.add(name)
    inverse = dict(result)
    for name, old, new in reversed(operations):
        inverse[name] = replace_once(inverse[name], new, old, True)
    require(all(inverse[name] == values[name] for name in changed), 'whole-file-inverse')
    require(all(result[name] == raw for name, raw in values.items() if name not in changed), 'other-inputs-exact')
    result[ADDED] = factory
    require(len(result) == 494 and sum(map(len, result.values())) <= 16*1024**2, 'original-source-bounds')
    return result, {'before': before, 'after': identities(result), 'added': ADDED,
        'changedFiles': sorted(changed), 'originalBodiesInverseExact': True,
        'defaultOff': True, 'actualExecutionObserved': False,
        'fullBarSizing': False, 'irqEnabled': False, 'consumerInstalled': False,
        'tcpEnabled': False, 'nodeFundingQualified': False, 'nodeRetirementQualified': False}
