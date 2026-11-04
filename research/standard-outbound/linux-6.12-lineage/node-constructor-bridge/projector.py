"""Closed source projection for the not-yet-entered Node constructor bridge.

No request sets the scoped fields here. A future reviewed synchronous caller
must bind and revoke them under the original Node/file/actor fences.
"""
import hashlib
import json

INPUT_SHA256 = "0be68297bc9037e881d062389b44059af4dbe8b5ce72989e17f28210058802c3"


def require(value, reason):
    if not value:
        raise ValueError("node-constructor-bridge-" + reason)


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def identities(values):
    return {name: identity(raw) for name, raw in sorted(values.items())}


PROTO_OLD = b"    static int lsf_node_device_actor_current(void);\n".lstrip()
PROTO_NEW = PROTO_OLD + b"#ifdef CONFIG_LSF_STREAM_NODE_PCI_PREFIX\nstatic int lsf_node_constructor_actor_current(void);\n#endif\n"

PARENT_OLD = b"    unsigned int state, reply_pending;\n    struct lsf_node_capacity capacity;\n"
PARENT_NEW = b"""    unsigned int state, reply_pending;
#ifdef CONFIG_LSF_STREAM_NODE_PCI_PREFIX
    /* Borrowed only during the exact synchronous, original-Node request. */
    struct task_struct *prefix_task;
    struct lsf_prepaid_ticket prefix_pci;
    u64 prefix_before_cursor, prefix_peak_cursor, prefix_after_cursor;
    unsigned int prefix_attempted, prefix_active, prefix_birth, prefix_returned;
    unsigned int prefix_before_live, prefix_peak_live, prefix_after_live;
#endif
    struct lsf_node_capacity capacity;
"""

ACTOR_ANCHOR = b"static int lsf_node_open(struct inode *inode, struct file *file)\n"
ACTOR_HELPER = b"""#ifdef CONFIG_LSF_STREAM_NODE_PCI_PREFIX
/* Reuse the original Node actor and current Root under its existing pool
 * lock. The extra scope is inactive unless a future synchronous request has
 * authenticated its actual file and actor, marked one attempt, and retained
 * that same call until revocation. This helper does not grant a request. */
static int lsf_node_constructor_actor_current(void)
{
    struct lsf_node_parent *node;
    unsigned long base;

    lockdep_assert_held(&pool_lock);
    if (!lsf_node_device_actor_current())
        return 0;
    base = (unsigned long)page_address(factory.pages);
    node = (void *)(base + LSF_FACTORY_INFRA_OFFSET);
    node = lsf_node_capacity_parent_locked(&node->capacity);
    return node && node->prefix_attempted == 1u && node->prefix_active == 1u &&
        node->prefix_task == current;
}
#endif

"""

PCI_ACTOR_OLD = b"""        !factory.pool.stopped && current->mm == factory.mm &&
        task_tgid(current) == factory.tgid && current_cred() == factory.cred &&
        current->nsproxy && current->nsproxy->net_ns == factory.net &&
"""
PCI_ACTOR_NEW = b"""        !factory.pool.stopped &&
#if defined(LSF_STREAM_NODE_CAPACITY_IMAGE) && defined(CONFIG_LSF_STREAM_NODE_PCI_PREFIX)
        lsf_node_constructor_actor_current() &&
#else
        current->mm == factory.mm && task_tgid(current) == factory.tgid &&
        current_cred() == factory.cred && current->nsproxy &&
        current->nsproxy->net_ns == factory.net &&
#endif
"""

PCI_INCLUDE_OLD = b"#include <net/lsf_stream_constructor_private.h>\n"
PCI_INCLUDE_NEW = PCI_INCLUDE_OLD + b"#include <net/lsf_stream_device_private.h>\n"
PCI_BIND_OLD = b"""\tint selected = lsf_factory_stream_bind_selected(dev);
\tif (selected) {
"""
PCI_BIND_NEW = b"""\tint selected = lsf_factory_stream_bind_selected(dev);
#ifdef CONFIG_LSF_STREAM_NODE_PCI_PREFIX
\t/* No private bank pointer, including an invalid or retired birth, may
\t * fall through to ordinary PCI binding when no consumer is installed. */
\tif (!selected && lsf_factory_device_pci_owned(dev, sizeof(*dev)) != 0)
\t\treturn;
#endif
\tif (selected) {
"""

EDITS = {
    "net/device-prepaid.h": ((PROTO_OLD, PROTO_NEW),),
    "net/factory-node-bootstrap.c": ((PARENT_OLD, PARENT_NEW),
        (ACTOR_ANCHOR, ACTOR_HELPER + ACTOR_ANCHOR)),
    "net/factory-device.c": ((PCI_ACTOR_OLD, PCI_ACTOR_NEW),),
    "drivers/pci/bus.c": ((PCI_INCLUDE_OLD, PCI_INCLUDE_NEW),
        (PCI_BIND_OLD, PCI_BIND_NEW)),
}


def transform(values):
    require(type(values) is dict and len(values) == 488 and
        all(type(name) is str and type(raw) is bytes for name, raw in values.items()), "input-set")
    before = identities(values)
    digest = hashlib.sha256(json.dumps(before, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    require(digest == INPUT_SHA256, "complete-input-identity")
    result = dict(values)
    for name, edits in EDITS.items():
        require(name in result, "missing-input")
        data = result[name]
        for old, new in edits:
            require(old != new and data.count(old) == 1 and data.count(new) == 0, "unique-anchor")
            data = data.replace(old, new, 1)
        result[name] = data
    for name, edits in EDITS.items():
        data = result[name]
        for old, new in reversed(edits):
            require(data.count(new) == 1, "inverse-anchor")
            data = data.replace(new, old, 1)
        require(data == values[name], "whole-file-inverse")
    require(all(result[name] == raw for name, raw in values.items() if name not in EDITS),
        "other-inputs-exact")
    return result, {"before": before, "after": identities(result), "changedFiles": sorted(EDITS),
        "originalBodiesInverseExact": True, "scopeSetterImplemented": False,
        "constructorExecuted": False, "irqEnabled": False, "tcpEnabled": False,
        "consumerInstalled": False, "nodeFundingQualified": False,
        "nodeRetirementQualified": False}
