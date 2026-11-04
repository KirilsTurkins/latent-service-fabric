"""One actual PCI birth/return in a separate default-off Node image.

This is a source projection, not NodeFunding, IRQ, network or execution proof.
"""
import hashlib
import json

INPUT_SHA256 = "32130cca80117b2cc8ea1b7265a925d96a27a5378a505c39cb510bd6a3d79c07"
MATERIAL_SHA256 = "16c0c482b2e429a80d1d3a5458587e8895bcfbe3b953894e86e7e6f53441d146"
MATERIAL_BYTES = 8274


def require(value, reason):
    if not value:
        raise ValueError("node-pci-prefix-" + reason)


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def identities(values):
    return {name: identity(raw) for name, raw in sorted(values.items())}


KCONFIG_ANCHOR = b"""\t  Original OS registration remains a platform prerequisite. Only the
\t  original moved userspace escrow pays later Node/bank/PREPARE births.
"""
KCONFIG_PREFIX = b"""
config LSF_STREAM_NODE_PCI_PREFIX
\tbool "LSF selected PCI birth/return qualification image"
\tdepends on LSF_STREAM_NODE_BOOTSTRAP
\tdefault n
\thelp
\t  Permit one same-Node-actor selected PCI birth and synchronous return.
\t  Stop before setup, registration, bind, NAPI, interrupts or networking.
\t  This qualification image never enables a production consumer.
"""

FACTORY_ANCHOR = b'#include "factory-node-bootstrap.c"\n'
FACTORY_DECL = b"""#ifdef CONFIG_LSF_STREAM_NODE_PCI_PREFIX
static int lsf_node_boot_pci_prefix(void);
#endif
"""

NODE_OPCODE = b"#define LSF_NODE_CAPACITY_PREPARE 3u\n"
NODE_OPCODE_EXTRA = b"""#ifdef CONFIG_LSF_STREAM_NODE_PCI_PREFIX
#define LSF_NODE_PCI_PREFIX 4u
#endif
"""
NODE_INCLUDE_ANCHOR = b"static int lsf_node_open(struct inode *inode, struct file *file)\n"
NODE_INCLUDE = b"""#ifdef CONFIG_LSF_STREAM_NODE_PCI_PREFIX
#include "factory-node-pci-prefix.c"
#endif
"""
NODE_BUSY_OLD = b"""    if (node->reply_pending) {
        error = -EBUSY;
        goto out;
    }
"""
NODE_BUSY_NEW = b"""#ifdef CONFIG_LSF_STREAM_NODE_PCI_PREFIX
    /* The current write owns the scope while it temporarily drops the mutex. */
    if (node->prefix_active) {
        error = -EBUSY;
        goto out;
    }
#endif
""" + NODE_BUSY_OLD
NODE_CLOSE_ANCHOR = b"""    } else if (operation == LSF_NODE_CLOSE_RETAIN) {
"""
NODE_PREFIX_BRANCH = b"""#ifdef CONFIG_LSF_STREAM_NODE_PCI_PREFIX
    } else if (operation == LSF_NODE_PCI_PREFIX) {
        if (node->state != LSF_NODE_ATTACHED_UNQUALIFIED ||
            expires != node->expires_ns || generation != node->record.generation)
            goto out;
        error = lsf_node_prefix_execute(file, node);
        if (error)
            goto out;
#endif
"""

HEADER_ANCHOR = b"int lsf_factory_device_pci_return(const void *);\n"
HEADER_EXTRA = b"""#ifdef CONFIG_LSF_STREAM_NODE_PCI_PREFIX
int lsf_node_prefix_pci_birth(struct pci_dev *);
void lsf_node_prefix_pci_returned(int);
#endif
"""

PROBE_ANCHOR = b"""\tdev->device = (l >> 16) & 0xffff;

\tif (lsf_prepaid_pci_setup_device(dev)) {
"""
PROBE_NEW = b"""\tdev->device = (l >> 16) & 0xffff;

#ifdef CONFIG_LSF_STREAM_NODE_PCI_PREFIX
\t/* Stop at the actual paid PCI birth. Failure retains unknown ownership;
\t * no normal setup, registration or free fallback is permitted. */
\tif (lsf_node_prefix_pci_birth(dev) != 1)
\t\treturn NULL;
\tpci_bus_put(dev->bus);
\tlsf_node_prefix_pci_returned(lsf_factory_device_pci_return(dev));
\treturn NULL;
#endif
\tif (lsf_prepaid_pci_setup_device(dev)) {
"""

BOOT_ANCHOR = b"static bool lsf_node_boot_entry_ready(void)\n"
BOOT_PREFIX = b"""#ifdef CONFIG_LSF_STREAM_NODE_PCI_PREFIX
/* Enter once from the original Node syscall; the selected source wrapper
 * performs a real birth and then aborts BEFORE PCI setup/registration. */
static int lsf_node_boot_pci_prefix(void)
{
    struct pci_bus *bus;
    struct pci_dev *device;
    int result = -EOPNOTSUPP;

    pci_lock_rescan_remove();
    bus = pci_find_bus(LSF_DEVICE_PCI_DOMAIN, LSF_DEVICE_PCI_BUS);
    if (!bus || (unsigned int)pci_domain_nr(bus) != LSF_DEVICE_PCI_DOMAIN ||
        bus->number != LSF_DEVICE_PCI_BUS)
        goto out;
    device = pci_get_slot(bus, LSF_DEVICE_PCI_DEVFN);
    if (device) {
        pci_dev_put(device);
        goto out;
    }
    device = lsf_prepaid_pci_scan_single_device(bus, LSF_DEVICE_PCI_DEVFN);
    if (device)
        goto out; /* Unexpected publication remains owned and quarantined. */
    device = pci_get_slot(bus, LSF_DEVICE_PCI_DEVFN);
    if (device) {
        pci_dev_put(device);
        goto out;
    }
    result = 0;
out:
    pci_unlock_rescan_remove();
    return result;
}
#endif

"""

EDITS = {
    "net/Kconfig": ((KCONFIG_ANCHOR, KCONFIG_ANCHOR + KCONFIG_PREFIX),),
    "net/factory.c": ((FACTORY_ANCHOR, FACTORY_DECL + FACTORY_ANCHOR),),
    "net/factory-node-bootstrap.c": ((NODE_OPCODE, NODE_OPCODE + NODE_OPCODE_EXTRA),
        (NODE_INCLUDE_ANCHOR, NODE_INCLUDE + NODE_INCLUDE_ANCHOR),
        (NODE_BUSY_OLD, NODE_BUSY_NEW),
        (NODE_CLOSE_ANCHOR, NODE_PREFIX_BRANCH + NODE_CLOSE_ANCHOR)),
    "include/net/lsf_stream_device_private.h": ((HEADER_ANCHOR, HEADER_ANCHOR + HEADER_EXTRA),),
    "drivers/pci/probe.c": ((PROBE_ANCHOR, PROBE_NEW),),
    "net/factory-node-boot.c": ((BOOT_ANCHOR, BOOT_PREFIX + BOOT_ANCHOR),),
}
ADDED = "net/factory-node-pci-prefix.c"


def transform(values, material):
    require(type(values) is dict and len(values) == 488 and
        all(type(name) is str and type(raw) is bytes for name, raw in values.items()), "input-set")
    before = identities(values)
    digest = hashlib.sha256(json.dumps(before, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    require(digest == INPUT_SHA256, "complete-input-identity")
    require(type(material) is bytes and len(material) == MATERIAL_BYTES and
        hashlib.sha256(material).hexdigest() == MATERIAL_SHA256, "material-identity")
    result = dict(values)
    for name, edits in EDITS.items():
        require(name in result, "missing-input")
        data = result[name]
        for old, new in edits:
            require(old != new and data.count(old) == 1 and data.count(new) == 0, "unique-anchor")
            data = data.replace(old, new, 1)
        result[name] = data
    require(ADDED not in result, "material-collision")
    result[ADDED] = material
    for name, edits in EDITS.items():
        data = result[name]
        for old, new in reversed(edits):
            require(data.count(new) == 1, "inverse-anchor")
            data = data.replace(new, old, 1)
        require(data == values[name], "whole-file-inverse")
    require(all(result[name] == raw for name, raw in values.items() if name not in EDITS),
        "other-inputs-exact")
    return result, {"before": before, "after": identities(result), "added": ADDED,
        "changedFiles": sorted(EDITS), "originalBodiesInverseExact": True,
        "defaultOff": True, "actualExecutionObserved": False, "consumerInstalled": False,
        "irqEnabled": False, "tcpEnabled": False, "nodeFundingQualified": False,
        "nodeRetirementQualified": False}
