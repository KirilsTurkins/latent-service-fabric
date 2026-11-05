"""Default-off same-Node PCI setup projection; no execution claim."""
import hashlib
import json

INPUT_SHA256 = 'f5a77ca0b19b6dfb8fd1e7b356879bfc5b3e17ccc8bbce20126e25f220970a08'
MATERIAL_SHA256 = '305764e25ee05a8b8dc7e7274d74db6eb1d6d68fbd930a2e40129129e6bfd864'
MATERIAL_BYTES = 10865
OPERATIONS = [('net/Kconfig',
  None,
  None,
  b'\t  This qualification image never enables a production consumer.\n',
  b'\t  This qualification image never enables a production consumer.\n\nconfig LSF_STREAM_NODE_PCI_SETUP\n\t'
  b'bool "LSF selected PCI setup and actual retirement qualification image"\n\tdepends on LSF_STREAM_NODE_'
  b'PCI_PREFIX && ACPI\n\tdefault n\n\thelp\n\t  Observe the real selected PCI setup through firmware and '
  b'class reads.\n\t  Stop before early fixups, BAR probing, device registration or interrupts.\n\t  Wait fo'
  b'r the original firmware and PCI records to return without funding\n\t  or installing a production cons'
  b'umer.\n'),
 ('net/factory-node-bootstrap.c',
  None,
  None,
  b'    unsigned int prefix_before_live, prefix_peak_live, prefix_after_live;\n#endif\n',
  b'    unsigned int prefix_before_live, prefix_peak_live, prefix_after_live;\n#ifdef CONFIG_LSF_STREAM_NODE_'
  b'PCI_SETUP\n    struct lsf_prepaid_ticket prefix_firmware;\n    unsigned int prefix_waiting, prefix_set'
  b'up, prefix_pending, prefix_companion;\n    unsigned int prefix_header, prefix_class, prefix_config_si'
  b'ze;\n#endif\n#endif\n'),
 ('net/factory-node-bootstrap.c',
  None,
  None,
  b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_PREFIX\n#include "factory-node-pci-prefix.c"\n#endif\n',
  b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_SETUP\nstatic int lsf_node_setup_wait(struct lsf_node_parent *);\n#e'
  b'ndif\n#ifdef CONFIG_LSF_STREAM_NODE_PCI_PREFIX\n#include "factory-node-pci-prefix.c"\n#endif\n#ifdef CON'
  b'FIG_LSF_STREAM_NODE_PCI_SETUP\n#include "factory-node-pci-setup.c"\n#endif\n'),
 ('net/factory-node-bootstrap.c',
  None,
  None,
  b'    if (node->prefix_active) {\n        error = -EBUSY;\n',
  b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_SETUP\n    if (node->prefix_active || node->prefix_waiting) {\n#else'
  b'\n    if (node->prefix_active) {\n#endif\n        error = -EBUSY;\n'),
 ('include/net/lsf_stream_device_private.h',
  None,
  None,
  b'void lsf_node_prefix_pci_returned(int);\n#endif\n',
  b'void lsf_node_prefix_pci_returned(int);\n#endif\n#ifdef CONFIG_LSF_STREAM_NODE_PCI_SETUP\nint lsf_node_'
  b'setup_reached(struct pci_dev *);\nvoid lsf_node_setup_pending(struct pci_dev *, int, int);\nvoid lsf_n'
  b'ode_setup_unexpected(void);\n#endif\n'),
 ('drivers/pci/probe.c',
  b'int lsf_prepaid_pci_setup_device(struct pci_dev *dev)\n',
  b'static struct pci_dev *lsf_prepaid_pci_scan_device(struct pci_bus *bus, int devfn)\n',
  b'\t/* Early fixups, before probing the BARs */\n\tpci_fixup_device(pci_fixup_early, dev);\n',
  b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_SETUP\n\t/* Real paid setup reached: refuse before general fixups or'
  b' BAR probing. */\n\tif (lsf_node_setup_reached(dev) != 1)\n\t\treturn -EOPNOTSUPP;\n\treturn -ECANCELED'
  b';\n#endif\n\t/* Early fixups, before probing the BARs */\n\tpci_fixup_device(pci_fixup_early, dev);\n'),
 ('drivers/pci/probe.c',
  b'static struct pci_dev *lsf_prepaid_pci_scan_device(struct pci_bus *bus, int devfn)\n',
  b'struct pci_dev *lsf_prepaid_pci_scan_single_device(struct pci_bus *bus, int devfn)\n',
  b'\tstruct pci_dev *dev;\n\tu32 l;\n',
  b'\tstruct pci_dev *dev;\n\tu32 l;\n#ifdef CONFIG_LSF_STREAM_NODE_PCI_SETUP\n\tint setup_error;\n#endif\n'),
 ('drivers/pci/probe.c',
  b'static struct pci_dev *lsf_prepaid_pci_scan_device(struct pci_bus *bus, int devfn)\n',
  b'struct pci_dev *lsf_prepaid_pci_scan_single_device(struct pci_bus *bus, int devfn)\n',
  b'\tif (lsf_node_prefix_pci_birth(dev) != 1)\n\t\treturn NULL;\n\tpci_bus_put(dev->bus);\n\tlsf_node_prefi'
  b'x_pci_returned(lsf_factory_device_pci_return(dev));\n\treturn NULL;\n#endif\n\tif (lsf_prepaid_pci_setup_'
  b'device(dev)) {\n\t\tpci_bus_put(dev->bus);\n\t\t(void)lsf_factory_device_pci_return(dev);\n\t\treturn NUL'
  b'L;\n\t}\n\n\treturn dev;\n',
  b'\tif (lsf_node_prefix_pci_birth(dev) != 1)\n\t\treturn NULL;\n#ifndef CONFIG_LSF_STREAM_NODE_PCI_SETU'
  b'P\n\tpci_bus_put(dev->bus);\n\tlsf_node_prefix_pci_returned(lsf_factory_device_pci_return(dev));\n\tre'
  b'turn NULL;\n#endif\n#endif\n#ifdef CONFIG_LSF_STREAM_NODE_PCI_SETUP\n\tsetup_error = lsf_prepaid_pci_setu'
  b'p_device(dev);\n\tif (setup_error) {\n#else\n\tif (lsf_prepaid_pci_setup_device(dev)) {\n#endif\n\t\tpci_'
  b'bus_put(dev->bus);\n#ifdef CONFIG_LSF_STREAM_NODE_PCI_SETUP\n\t\tlsf_node_setup_pending(dev, setup_error'
  b', lsf_factory_device_pci_return(dev));\n#else\n\t\t(void)lsf_factory_device_pci_return(dev);\n#endif\n'
  b'\t\treturn NULL;\n\t}\n#ifdef CONFIG_LSF_STREAM_NODE_PCI_SETUP\n\t/* Never publish if the intentional s'
  b'top was skipped. Retain custody. */\n\tlsf_node_setup_unexpected();\n\treturn NULL;\n#endif\n\treturn d'
  b'ev;\n'),
 ('net/factory-node-pci-prefix.c',
  None,
  None,
  b'    mutex_unlock(&factory_lock);\n    error = lsf_node_boot_pci_prefix();\n    mutex_lock(&factory_loc'
  b'k);\n    spin_lock_irqsave(&pool_lock, flags);\n    after = lsf_node_prefix_parent_locked();\n    if (a'
  b'fter != node || !after || after->prefix_active != 1u ||\n        after->prefix_attempted != 1u || after->'
  b'prefix_task != current)\n        goto poison;\n    /* Revoke the borrowed task even after a failed or '
  b'expired attempt. */\n    after->prefix_active = 0u;\n    after->prefix_task = NULL;\n',
  b'    mutex_unlock(&factory_lock);\n    error = lsf_node_boot_pci_prefix();\n#ifdef CONFIG_LSF_STREAM_NO'
  b'DE_PCI_SETUP\n    /* End constructor authority before waiting for the original callback.\n     * The f'
  b'ile reference stays held and competing Node writes remain busy. */\n    mutex_lock(&factory_lock);\n  '
  b'  spin_lock_irqsave(&pool_lock, flags);\n    after = lsf_node_prefix_parent_locked();\n    if (after !'
  b'= node || !after || after->prefix_active != 1u ||\n        after->prefix_attempted != 1u || after->prefix'
  b'_task != current)\n        goto poison;\n    after->prefix_active = 0u;\n    after->prefix_task = NULL;'
  b'\n    if (error) {\n        goto poison;\n    }\n    after->prefix_waiting = 1u;\n    spin_unlock_irqrest'
  b'ore(&pool_lock, flags);\n    mutex_unlock(&factory_lock);\n    error = lsf_node_setup_wait(node);\n#end'
  b'if\n    mutex_lock(&factory_lock);\n    spin_lock_irqsave(&pool_lock, flags);\n    after = lsf_node_pre'
  b'fix_parent_locked();\n#ifdef CONFIG_LSF_STREAM_NODE_PCI_SETUP\n    if (after != node || !after || afte'
  b'r->prefix_active ||\n        after->prefix_waiting != 1u || after->prefix_attempted != 1u ||\n        '
  b'after->prefix_task)\n        goto poison;\n    after->prefix_waiting = 0u;\n#else\n    if (after != node'
  b' || !after || after->prefix_active != 1u ||\n        after->prefix_attempted != 1u || after->prefix_task '
  b'!= current)\n        goto poison;\n    /* Revoke the borrowed task even after a failed or expired atte'
  b'mpt. */\n    after->prefix_active = 0u;\n#endif\n    after->prefix_task = NULL;\n'),
 ('net/factory-node-pci-prefix.c',
  None,
  None,
  b'    pr_notice("LSFQ35PCIPREFIX1 bdf=0000:00:03.0 vendor=1af4 device=1041 born=1 returned=1 registered=0 '
  b'scopeRevoked=1 slot=%u generation=%llu live=%u,%u,%u cursor=%llu,%llu,%llu\\n",\n        after->prefix'
  b'_pci.slot, (unsigned long long)after->prefix_pci.generation,\n        after->prefix_before_live, after->p'
  b'refix_peak_live, after->prefix_after_live,\n        (unsigned long long)after->prefix_before_cursor,\n'
  b'        (unsigned long long)after->prefix_peak_cursor,\n        (unsigned long long)after->prefix_after_c'
  b'ursor);\n',
  b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_SETUP\n    pr_notice("LSFQ35PCISETUP1 bdf=0000:00:03.0 vendor=1af4 devi'
  b'ce=1041 header=%u class=%06x cfg=%u companion=%u born=1 setup=1 pending=1 firmwareReturned=1 pciReturned'
  b'=1 registered=0 scopeRevoked=1 pciSlot=%u pciGeneration=%llu firmwareSlot=%u firmwareGeneration=%llu liv'
  b'e=%u,%u,%u cursor=%llu,%llu,%llu\\n",\n        after->prefix_header, after->prefix_class, after->prefi'
  b'x_config_size,\n        after->prefix_companion, after->prefix_pci.slot,\n        (unsigned long long)'
  b'after->prefix_pci.generation, after->prefix_firmware.slot,\n        (unsigned long long)after->prefix_fir'
  b'mware.generation,\n        after->prefix_before_live, after->prefix_peak_live, after->prefix_after_li'
  b've,\n        (unsigned long long)after->prefix_before_cursor,\n        (unsigned long long)after->pref'
  b'ix_peak_cursor,\n        (unsigned long long)after->prefix_after_cursor);\n#else\n    pr_notice("LSFQ35'
  b'PCIPREFIX1 bdf=0000:00:03.0 vendor=1af4 device=1041 born=1 returned=1 registered=0 scopeRevoked=1 slot=%'
  b'u generation=%llu live=%u,%u,%u cursor=%llu,%llu,%llu\\n",\n        after->prefix_pci.slot, (unsigned '
  b'long long)after->prefix_pci.generation,\n        after->prefix_before_live, after->prefix_peak_live, afte'
  b'r->prefix_after_live,\n        (unsigned long long)after->prefix_before_cursor,\n        (unsigned lon'
  b'g long)after->prefix_peak_cursor,\n        (unsigned long long)after->prefix_after_cursor);\n#endif\n')]
ADDED = "net/factory-node-pci-setup.c"

def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

def identities(values):
    return {name: identity(raw) for name, raw in sorted(values.items())}

def require(value, reason):
    if not value:
        raise ValueError("node-pci-setup-" + reason)

def replace_once(raw, old, new, inverse=False):
    require(raw.count(old) == 1 and (inverse or raw.count(new) == 0), "unique-anchor")
    return raw.replace(old, new, 1)

def apply(raw, start, end, old, new, inverse=False):
    if start is None:
        return replace_once(raw, old, new, inverse)
    require(type(start) is bytes and type(end) is bytes and
        raw.count(start) == raw.count(end) == 1, "unique-region")
    first, last = raw.index(start), raw.index(end)
    require(first < last, "region-order")
    return raw[:first] + replace_once(raw[first:last], old, new, inverse) + raw[last:]

def transform(values, material):
    require(type(values) is dict and len(values) == 489 and
        all(type(k) is str and type(v) is bytes for k, v in values.items()), "input-set")
    before = identities(values)
    digest = hashlib.sha256(json.dumps(before, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    require(digest == INPUT_SHA256, "complete-input-identity")
    require(type(material) is bytes and len(material) == MATERIAL_BYTES and
        hashlib.sha256(material).hexdigest() == MATERIAL_SHA256, "material-identity")
    result = dict(values)
    changed = set()
    for name, start, end, old, new in OPERATIONS:
        require(name in result and old != new, "exact-input")
        result[name] = apply(result[name], start, end, old, new)
        changed.add(name)
    inverse = dict(result)
    for name, start, end, old, new in reversed(OPERATIONS):
        inverse[name] = apply(inverse[name], start, end, new, old, True)
    require(all(inverse[k] == values[k] for k in changed), "whole-file-inverse")
    require(ADDED not in result, "material-collision")
    result[ADDED] = material
    require(all(result[k] == v for k, v in values.items() if k not in changed), "other-inputs-exact")
    return result, {"before": before, "after": identities(result), "added": ADDED,
        "changedFiles": sorted(changed), "originalBodiesInverseExact": True,
        "defaultOff": True, "actualExecutionObserved": False,
        "consumerInstalled": False, "irqEnabled": False, "tcpEnabled": False,
        "nodeFundingQualified": False, "nodeRetirementQualified": False}
