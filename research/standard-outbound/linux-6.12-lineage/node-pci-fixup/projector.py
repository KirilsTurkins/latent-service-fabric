"""Default-off q35 early-fixup no-match projection; no execution claim."""
import hashlib
import json

INPUT_SHA256 = 'dc635944cac1643a3da568e367726afbb3ec049714ae28c5d8363506e7127772'
QUIRKS_SHA256 = '1de33cd94f06f8296e90af6a06ac7b9cb42148a3e9c923007d5d5b640d305e72'
QUIRKS_BYTES = 235001
MATERIAL_SHA256 = 'c139b6700ae1fc873673fc45265c5836199580fed04ea9a48be5cbf4726eb7d7'
MATERIAL_BYTES = 2676
OPERATIONS = [('net/Kconfig',
  None,
  None,
  b'\t  or installing a production consumer.\n',
  b'\t  or installing a production consumer.\n\nconfig LSF_STREAM_NODE_PCI_FIXUP\n\tbool "LSF selected PCI no'
  b'-match early-fixup qualification image"\n\tdepends on LSF_STREAM_NODE_PCI_SETUP && PCI_QUIRKS && STRIC'
  b'T_KERNEL_RWX\n\tdefault n\n\thelp\n\t  Prove the linked early-fixup table has no matching callback, ru'
  b'n the\n\t  original no-hook dispatcher, and stop before INTx testing or BAR writes.\n\t  This image does'
  b' not install a production provider or deliver interrupts.\n'),
 ('net/factory-node-bootstrap.c',
  None,
  None,
  b'    unsigned int prefix_header, prefix_class, prefix_config_size;\n',
  b'    unsigned int prefix_header, prefix_class, prefix_config_size;\n#ifdef CONFIG_LSF_STREAM_NODE_PCI_FIXU'
  b'P\n    unsigned int prefix_fixup, prefix_fixup_count;\n#endif\n'),
 ('net/factory-node-bootstrap.c',
  None,
  None,
  b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_SETUP\n#include "factory-node-pci-setup.c"\n#endif\n',
  b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_SETUP\n#include "factory-node-pci-setup.c"\n#endif\n#ifdef CONFIG_LSF'
  b'_STREAM_NODE_PCI_FIXUP\n#include "factory-node-pci-fixup.c"\n#endif\n'),
 ('include/net/lsf_stream_device_private.h',
  None,
  None,
  b'void lsf_node_setup_unexpected(void);\n#endif\n',
  b'void lsf_node_setup_unexpected(void);\n#endif\n#ifdef CONFIG_LSF_STREAM_NODE_PCI_FIXUP\nint lsf_pci_ear'
  b'ly_fixups_empty(struct pci_dev *, unsigned int *);\nint lsf_node_fixup_reached(struct pci_dev *, unsigned'
  b' int);\n#endif\n'),
 ('drivers/pci/quirks.c',
  None,
  None,
  b'#include "pci.h"\n',
  b'#include "pci.h"\n#ifdef CONFIG_LSF_STREAM_NODE_PCI_FIXUP\n#include <net/lsf_stream_device_private.h>\n'
  b'#endif\n'),
 ('drivers/pci/quirks.c',
  None,
  None,
  b'static void pci_do_fixups(struct pci_dev *dev, struct pci_fixup *f,\n',
  b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_FIXUP\n/* Same predicate is used by the original dispatcher and the fai'
  b'l-closed\n * preflight, so the latter cannot silently skip any matching callback. */\nstatic bool lsf_'
  b'pci_fixup_matches(const struct pci_dev *dev, const struct pci_fixup *f)\n{\n\treturn (f->class == (u32)'
  b' (dev->class >> f->class_shift) ||\n\t\t     f->class == (u32) PCI_ANY_ID) &&\n\t\t    (f->vendor == d'
  b'ev->vendor ||\n\t\t     f->vendor == (u16) PCI_ANY_ID) &&\n\t\t    (f->device == dev->device ||\n\t\t    '
  b' f->device == (u16) PCI_ANY_ID);\n}\n#endif\n\nstatic void pci_do_fixups(struct pci_dev *dev, struct pci'
  b'_fixup *f,\n'),
 ('drivers/pci/quirks.c',
  None,
  None,
  b'\t\tif ((f->class == (u32) (dev->class >> f->class_shift) ||\n\t\t     f->class == (u32) PCI_ANY_ID) '
  b'&&\n\t\t    (f->vendor == dev->vendor ||\n\t\t     f->vendor == (u16) PCI_ANY_ID) &&\n\t\t    (f->device '
  b'== dev->device ||\n\t\t     f->device == (u16) PCI_ANY_ID)) {\n',
  b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_FIXUP\n\t\tif (lsf_pci_fixup_matches(dev, f)) {\n#else\n\t\tif ((f->c'
  b'lass == (u32) (dev->class >> f->class_shift) ||\n\t\t     f->class == (u32) PCI_ANY_ID) &&\n\t\t    (f'
  b'->vendor == dev->vendor ||\n\t\t     f->vendor == (u16) PCI_ANY_ID) &&\n\t\t    (f->device == dev->dev'
  b'ice ||\n\t\t     f->device == (u16) PCI_ANY_ID)) {\n#endif\n'),
 ('drivers/pci/quirks.c',
  None,
  None,
  b'static bool pci_apply_fixup_final_quirks;\n',
  b'#ifdef CONFIG_LSF_STREAM_NODE_PCI_FIXUP\n/* The linked table is immutable built-in state. Reject an absen'
  b't, malformed,\n * oversized, or matching table; never suppress a matching original hook. */\nint lsf_p'
  b'ci_early_fixups_empty(struct pci_dev *dev, unsigned int *entries)\n{\n\tstruct pci_fixup *f;\n\tunsigned '
  b'long first = (unsigned long)__start_pci_fixups_early;\n\tunsigned long last = (unsigned long)__end_pci'
  b'_fixups_early;\n\tunsigned long bytes;\n\tunsigned int count;\n\n\tif (!entries || lsf_factory_device_p'
  b'ci_owned(dev, sizeof(*dev)) != 1)\n\t\treturn 0;\n\tif (!dev->bus || !lsf_factory_device_selected(pci_dom'
  b'ain_nr(dev->bus),\n\t\tdev->bus->number, dev->devfn) || dev->vendor != LSF_DEVICE_PCI_VENDOR ||\n\t    de'
  b'v->device != LSF_DEVICE_PCI_DEVICE ||\n\t    (dev->class >> 8) != PCI_CLASS_NETWORK_ETHERNET || pci_de'
  b'v_is_added(dev))\n\t\treturn 0;\n\tif (!first || last <= first || !IS_ALIGNED(first, __alignof__(*f))'
  b' ||\n\t    !is_kernel_rodata(first) || !is_kernel_rodata(last - 1))\n\t\treturn 0;\n\tbytes = last - fi'
  b'rst;\n\tif (bytes % sizeof(*f) || bytes / sizeof(*f) > 512u)\n\t\treturn 0;\n\tcount = bytes / sizeof(*'
  b'f);\n\tif (!count)\n\t\treturn 0;\n\tfor (f = __start_pci_fixups_early; f < __end_pci_fixups_early; f++'
  b') {\n\t\tif (f->class_shift >= 32u || lsf_pci_fixup_matches(dev, f))\n\t\t\treturn 0;\n\t}\n\t*entries '
  b'= count;\n\treturn 1;\n}\n#endif\n\nstatic bool pci_apply_fixup_final_quirks;\n'),
 ('drivers/pci/probe.c',
  b'int lsf_prepaid_pci_setup_device(struct pci_dev *dev)\n',
  b'static struct pci_dev *lsf_prepaid_pci_scan_device(struct pci_bus *bus, int devfn)\n',
  b'\tint err, pos = 0;\n',
  b'\tint err, pos = 0;\n#ifdef CONFIG_LSF_STREAM_NODE_PCI_FIXUP\n\tunsigned int lsf_fixup_before, lsf_fixup'
  b'_after;\n#endif\n'),
 ('drivers/pci/probe.c',
  b'int lsf_prepaid_pci_setup_device(struct pci_dev *dev)\n',
  b'static struct pci_dev *lsf_prepaid_pci_scan_device(struct pci_bus *bus, int devfn)\n',
  b'\tif (lsf_node_setup_reached(dev) != 1)\n\t\treturn -EOPNOTSUPP;\n\treturn -ECANCELED;\n#endif\n\t/* Earl'
  b'y fixups, before probing the BARs */\n\tpci_fixup_device(pci_fixup_early, dev);\n',
  b'\tif (lsf_node_setup_reached(dev) != 1)\n\t\treturn -EOPNOTSUPP;\n#ifndef CONFIG_LSF_STREAM_NODE_PCI_FIXU'
  b'P\n\treturn -ECANCELED;\n#else\n\tif (lsf_pci_early_fixups_empty(dev, &lsf_fixup_before) != 1)\n\t\tretu'
  b'rn -EOPNOTSUPP;\n#endif\n#endif\n\t/* Early fixups, before probing the BARs */\n\tpci_fixup_device(pci'
  b'_fixup_early, dev);\n#ifdef CONFIG_LSF_STREAM_NODE_PCI_FIXUP\n\tif (lsf_pci_early_fixups_empty(dev, &ls'
  b'f_fixup_after) != 1 ||\n\t    lsf_fixup_before != lsf_fixup_after ||\n\t    lsf_node_fixup_reached(dev, '
  b'lsf_fixup_after) != 1)\n\t\treturn -EOPNOTSUPP;\n\t/* No INTx toggle, BAR probe, registration or binding '
  b'in this profile. */\n\treturn -ECANCELED;\n#endif\n'),
 ('net/factory-node-pci-setup.c',
  b'void lsf_node_setup_pending(struct pci_dev *pci, int setup_error, int requested)\n',
  b'void lsf_node_setup_unexpected(void)\n',
  b'    node = lsf_node_prefix_parent_locked();\n    if (!node || !lsf_node_constructor_actor_current() ||\n',
  b'    node = lsf_node_prefix_parent_locked();\n#ifdef CONFIG_LSF_STREAM_NODE_PCI_FIXUP\n    if (!node ||'
  b' node->prefix_fixup != 1u || !node->prefix_fixup_count ||\n        node->prefix_fixup_count > 512u)\n '
  b'       goto poison;\n#endif\n    if (!node || !lsf_node_constructor_actor_current() ||\n'),
 ('net/factory-node-pci-setup.c',
  None,
  None,
  b'            node->prefix_returned || !lsf_node_device_actor_current() ||\n            !factory.device || '
  b'factory.device->constructor_active ||\n',
  b'            node->prefix_returned || !lsf_node_device_actor_current() ||\n#ifdef CONFIG_LSF_STREAM_NODE_P'
  b'CI_FIXUP\n            node->prefix_fixup != 1u || !node->prefix_fixup_count ||\n            node->pref'
  b'ix_fixup_count > 512u ||\n#endif\n            !factory.device || factory.device->constructor_active ||'
  b'\n'),
 ('net/factory-node-pci-prefix.c',
  None,
  None,
  b'        READ_ONCE(factory.uncertain))\n        goto poison;\n    spin_unlock_irqrestore(&pool_lock, fl'
  b'ags);\n#ifdef CONFIG_LSF_STREAM_NODE_PCI_SETUP\n    pr_notice("LSFQ35PCISETUP1',
  b'        READ_ONCE(factory.uncertain))\n        goto poison;\n#ifdef CONFIG_LSF_STREAM_NODE_PCI_FIXUP\n '
  b'   if (after->prefix_fixup != 1u || !after->prefix_fixup_count ||\n        after->prefix_fixup_count > 51'
  b'2u)\n        goto poison;\n#endif\n    spin_unlock_irqrestore(&pool_lock, flags);\n#ifdef CONFIG_LSF_STR'
  b'EAM_NODE_PCI_SETUP\n    pr_notice("LSFQ35PCISETUP1'),
 ('net/factory-node-pci-prefix.c',
  None,
  None,
  b'        (unsigned long long)after->prefix_after_cursor);\n#else\n    pr_notice("LSFQ35PCIPREFIX1',
  b'        (unsigned long long)after->prefix_after_cursor);\n#ifdef CONFIG_LSF_STREAM_NODE_PCI_FIXUP\n   '
  b' pr_notice("LSFQ35PCIFIXUP1 entries=%u matches=0 dispatcher=1 intxCheck=0 barProbe=0 registered=0\\n"'
  b',\n        after->prefix_fixup_count);\n#endif\n#else\n    pr_notice("LSFQ35PCIPREFIX1')]
ADDED = 'net/factory-node-pci-fixup.c'

def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

def identities(values):
    return {name: identity(raw) for name, raw in sorted(values.items())}

def require(value, reason):
    if not value:
        raise ValueError("node-pci-fixup-" + reason)

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

def transform(values, quirks, material):
    require(type(values) is dict and len(values) == 490 and
        all(type(k) is str and type(v) is bytes for k, v in values.items()), "input-set")
    before = identities(values)
    digest = hashlib.sha256(json.dumps(before, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    require(digest == INPUT_SHA256, "complete-input-identity")
    require(type(quirks) is bytes and len(quirks) == QUIRKS_BYTES and
        hashlib.sha256(quirks).hexdigest() == QUIRKS_SHA256, "archive-quirks-identity")
    require(type(material) is bytes and len(material) == MATERIAL_BYTES and
        hashlib.sha256(material).hexdigest() == MATERIAL_SHA256, "material-identity")
    require("drivers/pci/quirks.c" not in values and ADDED not in values, "material-collision")
    original = dict(values); original["drivers/pci/quirks.c"] = quirks
    result = dict(original); changed = set()
    for name, start, end, old, new in OPERATIONS:
        require(name in result and old != new, "exact-input")
        result[name] = apply(result[name], start, end, old, new)
        changed.add(name)
    inverse = dict(result)
    for name, start, end, old, new in reversed(OPERATIONS):
        inverse[name] = apply(inverse[name], start, end, new, old, True)
    require(all(inverse[k] == original[k] for k in changed), "whole-file-inverse")
    result[ADDED] = material
    require(all(result[k] == v for k, v in original.items() if k not in changed), "other-inputs-exact")
    return result, {"before": before, "archiveQuirks": identity(quirks),
        "after": identities(result), "added": ADDED, "changedFiles": sorted(changed),
        "originalBodiesInverseExact": True, "defaultOff": True,
        "actualExecutionObserved": False, "consumerInstalled": False,
        "irqEnabled": False, "tcpEnabled": False,
        "nodeFundingQualified": False, "nodeRetirementQualified": False}
