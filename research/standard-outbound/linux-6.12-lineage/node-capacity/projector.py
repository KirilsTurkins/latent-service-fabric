"""Distinct, still closed Node native-capacity image.

Inputs are immutable captured bytes supplied by the bounded owning loader.
No filesystem source discovery, old-stage replay, grant or NodeFunding issuer.
The full prior463 map is authenticated before any edit. Every old byte is
reconstructed by the inverse edit ledger, including shared allocator hooks.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
COMPILED_ABI = "lsf-q35-node-capacity-v1"
INPUT_SHA = "9951be36cfb1a64387e36842a694cb19542bc50f4cb33766c0f5839e9acdb074"
MATERIAL_PINS = {'factory-node-capacity.c': {'bytes': 66778, 'sha256': 'bb37daf080f8408981a8fd1ad54a11a1bd70227d7046988ff06fd1642dfd7e3e'}, 'factory-node-irq-action-pool.c': {'bytes': 3258, 'sha256': '9dc240a95dd463ef7c6d8777d201449eb4da46e4b3b3ed797aa3662205d86f32'}, 'factory-node-irq-loan.c': {'bytes': 29283, 'sha256': '8f3c4c3400123f15e45f7a350bbf19d2d9db75dde3640d1375aff14c05c58633'}, 'factory-node-irq-proc-pool.c': {'bytes': 5102, 'sha256': 'cd59d886d9300c8029da6d5d8bcf45e7a37bad943f15afee9760263cffc2711f'}, 'factory-node-parent-vector.c': {'bytes': 15886, 'sha256': 'd5e288adf3256539eb8530ce97a62592501af816bcf0bcfed0b9998c8635d3bf'}, 'factory-node-radix.c': {'bytes': 11478, 'sha256': 'dab28b1451761064f9a2d38fc3ddbe636d2a66a6e0bfe21d9aea793cad6171aa'}, 'factory-node-small-objects.c': {'bytes': 5297, 'sha256': '2f9f3f3a475658e6950ec25aba0f2d43af01751c64b945ddf314ebba8d61ff58'}, 'lsf-node-capacity-private.h': {'bytes': 16076, 'sha256': 'd50f5a232c871d13270c55c63424dad7529982b0958ecb623f68d5f68620c02a'}, 'lsf-node-irq-action.c': {'bytes': 2560, 'sha256': '1a0fc8e6755d7a3ba431a535d04530c3a12fc8960ac6d0bda55ef4bc47cd8b91'}, 'lsf-node-irq-proc.c': {'bytes': 7717, 'sha256': 'c0f6fccb7c741721b5942d1461ee99deceeb6cc989200b63cbce7dcbcb121748'}, 'lsf-node-irq-revmap.c': {'bytes': 5606, 'sha256': '8dc28e02cf46a677b2e87d4b2d6cf35d740fd2d448cf647c04e55f3e877b3132'}, 'lsf-node-irq.c': {'bytes': 10332, 'sha256': '8fe59c4f4839e22e9e54ae68e322496bb9d89067f9f1896518bba17b48f50058'}, 'lsf-node-irqdomain.c': {'bytes': 2886, 'sha256': '7657bb5e1c2c539dd6c54dfcf3c55d4985263eef68069311b8a32a1dd732fd4e'}, 'lsf-node-kobject.c': {'bytes': 1842, 'sha256': '177a7278be396e554bd5b10535b25ce6b8813b9bbfe2235edc359366bfa68200'}, 'lsf-node-maple.c': {'bytes': 5351, 'sha256': 'e223df5d2ec76c72d07d37634ef8f8b83ca3182315727246519a75123554d073'}, 'lsf-node-matrix.c': {'bytes': 1656, 'sha256': '0923693deae23971caa29bdc709e17961f6f4d77465e74c69bccac497298632b'}, 'lsf-node-pcpu.c': {'bytes': 11632, 'sha256': '3ce20ca155ee460ad66fca0f97c3b64ba2ee4072d3468af5f3b581fd17138f58'}, 'lsf-node-radix.c': {'bytes': 10274, 'sha256': 'cb6831a081d972be68003a1e2bebbd586a15ebd8f80bb09791b1fbf15cf7826d'}, 'lsf-node-vector.c': {'bytes': 7724, 'sha256': '24f0aeac7c1e2921bb204b18866d289e7872b1c4f8d1ea4ee322e537b09da783'}, 'lsf-node-vmalloc.c': {'bytes': 22509, 'sha256': '50eb867ea457e3fdd2bfa70454fcecb3db93eac73c1415a1fe9c2226aec3cc2a'}, 'native-irq-manage.c': {'bytes': 80223, 'sha256': '4842b22569bb8791f8c7df4dfc3bd75c94198ac75fce011d929ee885522df743'}, 'native-irq-proc.c': {'bytes': 16482, 'sha256': '09baa1e040fb467cda929b9caf8ed86a07dfa60e010eabf7b9684acdcbf20b7f'}, 'native-proc-generic.c': {'bytes': 20918, 'sha256': '7fe9637cf5b8ae6d98977fba1f5d0cdbb6563157063a2d2b7eca8a9ef01f6997'}, 'native-proc-inode.c': {'bytes': 17537, 'sha256': '5c8ce2883bfe35810bab0b192b2b9f8e49d0a836e975dfe4bbc88607e28831b1'}, 'native-vp-transport.c': {'bytes': 17738, 'sha256': 'a8195766c4a95f682329a30a466b1989606820a7b375b476d30338440b631474'}}
PRIMARY_PINS = {'mm/percpu.c': {'bytes': 103541, 'sha256': 'b74279d0cd0d8a3b31f26f0892a1bbb718f32812ee8ffb44f3f71199584964e0'}, 'mm/percpu-vm.c': {'bytes': 11969, 'sha256': '220a0772b528a11a42de9a1417f43eeb91293435156f69ee7664153949a3645d'}, 'mm/percpu-internal.h': {'bytes': 7895, 'sha256': '8c0b90d893cc890832f1846a449121450ec5ba0ccd907905a0161b9cd672a02d'}, 'lib/maple_tree.c': {'bytes': 196713, 'sha256': 'd11eba94051ba43ebcf908e10165ba1724681a6e2803db9dc9d931f342feaa3c'}, 'mm/vmalloc.c': {'bytes': 139333, 'sha256': '351e940965d3b2d0b0c44a970f596787613cb87dace7c6790e9c948c51246188'}, 'mm/memory.c': {'bytes': 196705, 'sha256': '134b138551e90a3ce3a4d9f79391d11fdec7d2d79dd34a9eca2739a2eea8c64f'}, 'include/linux/mm.h': {'bytes': 132024, 'sha256': 'a15410bd33802e92e80b973a33dfeb480ddbb36f0fc0f357f9a73d14524ddadb'}, 'include/asm-generic/pgalloc.h': {'bytes': 6160, 'sha256': '08c4b5d8812e8fd5258e40c1a50cf9f413283718e686224f2353ea940339bf57'}, 'arch/x86/include/asm/pgalloc.h': {'bytes': 5317, 'sha256': '4aab1f7de117aed2aadb1886f5b9f37b96818518dbb418763fe4afa4de9b2035'}, 'mm/pgalloc-track.h': {'bytes': 1298, 'sha256': '497e7d1f41803446f5d94f11a63836a8c6b6a5d9e4124108fd6a6c1796fb86c1'}, 'kernel/irq/irqdesc.c': {'bytes': 25422, 'sha256': '3ebc03602452076511e54fd3e0e84a692bcc479fd0c426186ff1900659f89079'}, 'kernel/irq/irqdomain.c': {'bytes': 59948, 'sha256': '0715731e7132f88d8d7b9969ce2aa6d5c0a44deba9114f7cd2d5ef7a543ae066'}, 'kernel/irq/matrix.c': {'bytes': 13742, 'sha256': '8e3a5f1c2dbfc39cc258f3f9fee9b65c13b494c0a26c7f056c726d338f8a549b'}, 'arch/x86/kernel/apic/vector.c': {'bytes': 37921, 'sha256': '58f24baf4e401325e04da562a2a8d2378011df2754baf6b378d9edb0fee59c97'}, 'lib/kobject.c': {'bytes': 28433, 'sha256': '0161a3faaa770cf7a724f94773104a5ab33c5dbafe525729276360cd8120d4ab'}, 'kernel/irq/manage.c': {'bytes': 79503, 'sha256': '764415dc7e1732033e3b6dce8227190287546055a75c4fd5122293e0c710e96a'}, 'kernel/irq/proc.c': {'bytes': 13328, 'sha256': '90e5826537275a5cc183460be6b593c68dee0f823a3ae46de4b5a84838189b6a'}, 'lib/radix-tree.c': {'bytes': 44109, 'sha256': '71b4e536fcdc6bc52857bdb255f06d4b303e9e5e9c3d63f621ef1e91d103421e'}}
OUTPUTS = {
    "lsf-node-capacity-private.h": "include/net/lsf_node_capacity_private.h",
    "factory-node-capacity.c": "net/factory-node-capacity.c",
    "lsf-node-pcpu.c": "mm/lsf-node-pcpu.c",
    "lsf-node-vmalloc.c": "mm/lsf-node-vmalloc.c",
    "lsf-node-maple.c": "lib/lsf-node-maple.c",
    "lsf-node-irq.c": "kernel/irq/lsf-node-irq.c",
    "factory-node-irq-loan.c": "net/factory-node-irq-loan.c",
    "lsf-node-kobject.c": "lib/lsf-node-kobject.c",
    "factory-node-parent-vector.c": "net/factory-node-parent-vector.c",
    "lsf-node-irqdomain.c": "kernel/irq/lsf-node-irqdomain.c",
    "lsf-node-vector.c": "arch/x86/kernel/apic/lsf-node-vector.c",
    "lsf-node-matrix.c": "kernel/irq/lsf-node-matrix.c",
    "factory-node-irq-action-pool.c": "net/factory-node-irq-action-pool.c",
    "factory-node-irq-proc-pool.c": "net/factory-node-irq-proc-pool.c",
    "lsf-node-irq-action.c": "kernel/irq/lsf-node-irq-action.c",
    "lsf-node-irq-proc.c": "fs/proc/lsf-node-irq-proc.c",
    "factory-node-small-objects.c": "net/factory-node-small-objects.c",
    "factory-node-radix.c": "net/factory-node-radix.c",
    "lsf-node-radix.c": "lib/lsf-node-radix.c",
    "lsf-node-irq-revmap.c": "kernel/irq/lsf-node-irq-revmap.c",
}
REPLACEMENTS = {
    "native-irq-manage.c": "kernel/irq/manage.c",
    "native-irq-proc.c": "kernel/irq/proc.c",
    "native-proc-generic.c": "fs/proc/generic.c",
    "native-proc-inode.c": "fs/proc/inode.c",
    "native-vp-transport.c": "drivers/virtio/lsf-stream-vp-transport.c",
}
NEW_NATIVE = ("kernel/irq/manage.c", "kernel/irq/proc.c")
HEADER = b"#include <net/lsf_node_capacity_private.h>\n"
GUARDED_HEADER = b"#ifdef CONFIG_LSF_STREAM_FACTORY\n" + HEADER + b"#endif\n"


def require(value, reason):
    if not value:
        raise ValueError("node-capacity-" + reason)


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def whole_function(raw, signature):
    """Closed source extraction; signatures are fixed source, never requests."""
    require(type(raw) is bytes and type(signature) is bytes, "function-types")
    require(raw.count(signature) == 1, "function-signature")
    start = raw.index(signature)
    opening = raw.index(b"{", start)
    depth = 1
    # All fixed selected bodies contain no quoted or commented brace tokens.
    # The caller separately pins their complete original bytes.
    index = opening + 1
    while index < len(raw) and depth:
        depth += (raw[index] == 123) - (raw[index] == 125)
        index += 1
    require(depth == 0, "function-close")
    return raw[start:index]


class Editor:
    def __init__(self, values):
        self.values = dict(values)
        self.edits = []

    def replace(self, name, old, new, count=1):
        raw = self.values[name]
        require(old != new and old and raw.count(old) == count, "anchor-" + name)
        require(new not in raw, "fresh-edit-" + name)
        self.values[name] = raw.replace(old, new)
        self.edits.append((name, old, new, count))

    def prefix_body(self, name, signature, prefix):
        raw = self.values[name]
        require(raw.count(signature) == 1, "body-signature")
        offset = raw.index(b"{", raw.index(signature)) + 1
        old = raw[raw.index(signature):offset]
        self.replace(name, old, old + b"\n" + prefix)

    def append(self, name, suffix):
        raw = self.values[name]
        require(suffix not in raw, "append-fresh")
        self.values[name] = raw + suffix
        self.edits.append((name, None, suffix, 1))

    def add_primary(self, name, raw):
        require(name not in self.values and type(raw) is bytes and raw, "fresh-native-primary")
        self.values[name] = raw
        self.edits.append((name, None, raw, 0))

    def inverse(self):
        restored = dict(self.values)
        for name, old, new, count in reversed(self.edits):
            if old is None and count == 0:
                require(restored[name] == new, "inverse-new-native-primary")
                del restored[name]
            elif old is None:
                require(restored[name].endswith(new), "inverse-tail")
                restored[name] = restored[name][:-len(new)]
            else:
                require(restored[name].count(new) == count, "inverse-count")
                restored[name] = restored[name].replace(new, old)
        return restored


def header_hooks(editor):
    # These headers are rewritten only in this distinct captured image. Their
    # ordinary branches still run the complete original constructors/destructors.
    # All TUs, including deferred frees, see the same ownership classifiers.
    for name in ("include/linux/mm.h", "include/asm-generic/pgalloc.h",
                 "arch/x86/include/asm/pgalloc.h"):
        raw = editor.values[name]
        if name == "include/asm-generic/pgalloc.h":
            line = b"#define __ASM_GENERIC_PGALLOC_H\n"
            require(raw.count(line) == 1, "generic-pgalloc-guard")
        else:
            position = raw.index(b"#include ")
            line = raw[position:raw.index(b"\n", position) + 1]
        editor.replace(name, line, line + GUARDED_HEADER)
    for name, signature, address, role in (
        ("include/asm-generic/pgalloc.h", b"static inline void pte_free_kernel(", b"pte", b"PTE"),
        ("include/asm-generic/pgalloc.h", b"static inline void pmd_free(", b"pmd", b"PMD"),
        ("include/asm-generic/pgalloc.h", b"static inline void __pud_free(", b"pud", b"PUD"),
        ("arch/x86/include/asm/pgalloc.h", b"static inline void p4d_free(", b"p4d", b"P4D"),
    ):
        prefix = (b"#ifdef CONFIG_LSF_STREAM_FACTORY\n" +
            b"\tif (lsf_node_pgtable_pre_free(mm, " + address + b", LSF_NODE_" + role +
            b"_PAGE) < 0)\n\t\treturn;\n#endif\n")
        if role in (b"PMD", b"PUD"):
            body = whole_function(editor.values[name], signature)
            anchor = b"\tstruct ptdesc *ptdesc = virt_to_ptdesc(" + address + b");\n"
            require(body.count(anchor) == 1, "pgtable-declaration-anchor")
            editor.replace(name, body, body.replace(anchor, anchor + prefix, 1))
        else:
            editor.prefix_body(name, signature, prefix)
    editor.replace("include/linux/mm.h",
        b"\t__free_pages(page, compound_order(page));",
        b"#ifdef CONFIG_LSF_STREAM_FACTORY\n"
        b"\tif (lsf_node_pgtable_backing_hold(page_address(page)))\n\t\treturn;\n"
        b"#endif\n\t__free_pages(page, compound_order(page));")
    editor.replace("arch/x86/include/asm/pgalloc.h",
        b"\tfree_page((unsigned long)p4d);",
        b"#ifdef CONFIG_LSF_STREAM_FACTORY\n"
        b"\tif (lsf_node_pgtable_backing_hold(p4d))\n\t\treturn;\n"
        b"#endif\n\tfree_page((unsigned long)p4d);")


def shared_native_hooks(editor):
    for name in ("mm/percpu.c", "mm/vmalloc.c", "lib/maple_tree.c", "kernel/irq/irqdesc.c"):
        editor.replace(name, editor.values[name][:editor.values[name].index(b"\n") + 1],
            editor.values[name][:editor.values[name].index(b"\n") + 1] + HEADER)
    editor.replace("mm/percpu.c", b"\tbool need_balance = false;\n",
        b"\tbool need_balance = false;\n\n"
        b"\tif (lsf_node_pcpu_free(ptr))\n\t\treturn;\n")
    # Every vmap-area terminal cache free must classify a Node split carrier,
    # including a later unrelated global merge; no bank address reaches SLUB.
    name = "mm/vmalloc.c"
    old = b"kmem_cache_free(vmap_area_cachep, "
    count = editor.values[name].count(old)
    require(count > 0, "vmap-free-sites")
    editor.replace(name, old, b"lsf_node_vmap_cache_free(", count)
    editor.replace(name,
        b"\tBUG_ON(ret != area);\n\tkfree(area);",
        b"\tBUG_ON(ret != area);\n"
        b"\tif (!lsf_node_capacity_native_free(area, LSF_NODE_VM_STRUCT))\n"
        b"\t\tkfree(area);")
    name = "lib/maple_tree.c"
    editor.replace(name, b"\tunsigned int max_req = 0;\n",
        b"\tunsigned int max_req = 0;\n\n"
        b"\tif (lsf_node_mas_allocate(mas, gfp))\n\t\treturn;\n")
    editor.replace(name, b"\tkmem_cache_free(maple_node_cache, node);",
        b"\tlsf_node_mt_free_one(node);", 2)
    editor.replace(name,
        b"\tkmem_cache_free_bulk(maple_node_cache, size, (void **)nodes);",
        b"\tlsf_node_mt_free_bulk(size, nodes);")
    editor.replace(name, b"\tcall_rcu(&node->rcu, mt_free_rcu);",
        b"\tif (lsf_node_maple_rcu_queue(node) >= 0)\n"
        b"\t\tcall_rcu(&node->rcu, mt_free_rcu);")
    editor.replace(name,
        b"\t\tif (in_rcu)\n\t\t\tcall_rcu(&node->rcu, mt_free_walk);",
        b"\t\tif (in_rcu && lsf_node_maple_rcu_queue(node) >= 0)\n"
        b"\t\t\tcall_rcu(&node->rcu, mt_free_walk);")
    editor.replace(name, b"\t\tcall_rcu(&node->rcu, mt_free_walk);\n\t} else {",
        b"\t\tif (lsf_node_maple_rcu_queue(node) >= 0)\n"
        b"\t\t\tcall_rcu(&node->rcu, mt_free_walk);\n\t} else {")
    editor.append("mm/percpu.c", b'\n#include "lsf-node-pcpu.c"\n')
    editor.append("mm/vmalloc.c", b'\n#include "lsf-node-vmalloc.c"\n')
    editor.append("lib/maple_tree.c", b'\n#include "lsf-node-maple.c"\n')
    name = "kernel/irq/irqdesc.c"
    release = whole_function(editor.values[name], b"static void irq_kobj_release(struct kobject *kobj)\n")
    require(release.count(b"\tkfree(desc);") == 1, "descriptor-terminal-free")
    editor.replace(name, release, release.replace(b"\tkfree(desc);",
        b"\tif (!lsf_node_capacity_native_free(desc, LSF_NODE_IRQ_DESC))\n\t\tkfree(desc);"))
    editor.replace(name, b"\tdelete_irq_desc(irq);\n\n\t/*\n\t * We free",
        b"\tif (lsf_node_irq_desc_delete(irq, desc))\n\t\treturn;\n\n\t/*\n\t * We free")
    editor.replace(name, b"\tcall_rcu(&desc->rcu, delayed_free_desc);",
        b"\tif (lsf_node_irq_desc_queue(desc) >= 0)\n"
        b"\t\tcall_rcu(&desc->rcu, delayed_free_desc);")
    editor.append("kernel/irq/irqdesc.c", b"\n" +
        b"int lsf_node_irq_sparse_identity(const struct maple_tree *tree)\n{\n"
        b"\tlockdep_assert_held(&sparse_irq_lock);\n"
        b"\treturn tree == &sparse_irqs;\n}\n"
        b'#include "lsf-node-irq.c"\n')


def node_entry(editor):
    # The old ordinary and old bootstrap profiles are separate prior stages.
    # This image changes the ABI before open, never by a caller request flag.
    name = "net/factory-node-bootstrap.c"
    editor.replace("net/factory.c", b"#define LSF_STREAM_NODE_BOOTSTRAP_IMAGE 1\n",
        b"#define LSF_STREAM_NODE_CAPACITY_IMAGE 1\n"
        b"#define LSF_STREAM_NODE_BOOTSTRAP_IMAGE 1\n")
    editor.replace(name, b"#define LSF_NODE_VERSION 1u", b"#define LSF_NODE_VERSION 2u")
    editor.replace(name, b"#define LSF_NODE_CLOSE_RETAIN 2u",
        b"#define LSF_NODE_CLOSE_RETAIN 2u\n#define LSF_NODE_CAPACITY_PREPARE 3u")
    editor.replace(name, b"struct lsf_node_parent {", HEADER + b"\nstruct lsf_node_parent {")
    editor.replace(name, b"    unsigned int state, reply_pending;\n};",
        b"    unsigned int state, reply_pending;\n    struct lsf_node_capacity capacity;\n};")
    anchor = b"static_assert(sizeof(struct lsf_node_parent) <= LSF_FACTORY_INFRA_BYTES);"
    floor = whole_function(editor.values["net/factory-cleanup-observer.c"],
        b"static int lsf_cleanup_bootstrap_fits(")
    floor = floor.replace(b"static int lsf_cleanup_bootstrap_fits(",
        b"static unsigned long lsf_node_native_bootstrap_bytes(", 1)
    require(floor.count(b"    return fixed <= ") == 1 and floor.endswith(b";\n}"),
        "native-bootstrap-source-form")
    start = floor.index(b"    return fixed <= ")
    condition = floor[start + len(b"    return "):-len(b";\n}")]
    floor = floor[:start] + b"    if (" + condition + b")\n" + \
        b"        return fixed + irq + observers;\n    return ULONG_MAX;\n}"
    editor.replace(name, anchor, anchor + b"\n\n" + floor +
        b'\n#include "factory-node-capacity.c"\n')
    parent = whole_function(editor.values[name], b"static struct lsf_node_parent *lsf_node_parent_for(")
    require(parent.count(b"        factory.device || READ_ONCE(factory.uncertain))") == 1,
        "node-parent-old-no-child")
    parent_new = parent.replace(b"        factory.device || READ_ONCE(factory.uncertain))",
        b"        READ_ONCE(factory.uncertain))", 1)
    require(parent_new.count(b"        record->cache_bucket || record->cache_anchor ||\n") == 1,
        "node-parent-original-anchor")
    parent_new = parent_new.replace(b"        record->cache_bucket || record->cache_anchor ||\n",
        b"        record->cache_bucket || record->cache_anchor ||\n"
        b"        !lsf_node_capacity_device_child_locked(node) ||\n", 1)
    editor.replace(name, parent, parent_new)
    anchor = b"    } else if (operation == LSF_NODE_CLOSE_RETAIN) {"
    editor.replace(name, anchor,
        b"    } else if (operation == LSF_NODE_CAPACITY_PREPARE) {\n"
        b"        if (node->state != LSF_NODE_ATTACHED_UNQUALIFIED ||\n"
        b"            expires != node->expires_ns || generation != node->record.generation)\n"
        b"            goto out;\n"
        b"        error = lsf_node_pcpu_prepare(&node->capacity);\n"
        b"        if (error) {\n"
        b"            node->state = LSF_NODE_RETAINED;\n            goto out;\n        }\n" + anchor)
    editor.replace(name,
        b"        factory.pool.contexts[node->owner.slot].closed = 1u;\n"
        b"        spin_unlock_irqrestore(&pool_lock, flags);",
        b"        factory.pool.contexts[node->owner.slot].closed = 1u;\n"
        b"        spin_unlock_irqrestore(&pool_lock, flags);\n"
        b"        if (lsf_node_pcpu_close_private(&node->capacity))\n"
        b"            WRITE_ONCE(factory.uncertain, 1);", 2)


def device_child_hooks(editor):
    name = "net/device-prepaid.h"
    editor.replace(name, b'#include "prepaid.h"\n', b'#include "prepaid.h"\n'
        b"#ifdef LSF_STREAM_NODE_CAPACITY_IMAGE\n"
        b"static int lsf_node_device_admission_current(struct lsf_prepaid *pool,\n"
        b"    struct lsf_prepaid_key key);\n"
        b"static int lsf_node_device_child_quiescent(struct lsf_prepaid *pool,\n"
        b"    struct lsf_prepaid_key key, struct lsf_prepaid_ticket ticket, unsigned int queued);\n"
        b"static int lsf_node_device_child_close(struct lsf_prepaid *pool,\n"
        b"    struct lsf_prepaid_key key);\n"
        b"static int lsf_node_device_actor_current(void);\n" + HEADER +
        b"#endif\n")
    editor.prefix_body("net/factory-device-core.c", b"static int lsf_factory_device_core_actor(",
        b"#ifdef LSF_STREAM_NODE_CAPACITY_IMAGE\n"
        b"    if (factory.pool.records[1].kind == LSF_NODE_CAPACITY_PARENT_KIND)\n"
        b"        return lsf_node_device_actor_current();\n#endif\n")
    close = whole_function(editor.values[name], b"static inline int lsf_device_close(")
    anchor = b"    struct lsf_prepaid_context *context = lsf_device_context(pool, key);\n"
    require(close.count(anchor) == 1, "device-close-original-context")
    selected = close.replace(anchor, anchor +
        b"#ifdef LSF_STREAM_NODE_CAPACITY_IMAGE\n    int selected;\n#endif\n", 1)
    anchor = b"    if (!context)\n        return 0;\n"
    require(selected.count(anchor) == 1, "device-close-original-refusal")
    selected = selected.replace(anchor, anchor +
        b"#ifdef LSF_STREAM_NODE_CAPACITY_IMAGE\n"
        b"    selected = lsf_node_device_child_close(pool, key);\n"
        b"    if (selected)\n        return selected == 1;\n#endif\n", 1)
    editor.replace(name, close, selected)
    allocation = whole_function(editor.values[name], b"static inline int lsf_device_allocate(")
    anchor = b"    unsigned int i;\n"
    require(allocation.count(anchor) == 1, "device-allocation-declaration")
    selected = allocation.replace(anchor, anchor +
        b"#ifdef LSF_STREAM_NODE_CAPACITY_IMAGE\n"
        b"    if (!lsf_node_device_admission_current(pool, key))\n        return 0;\n"
        b"#endif\n", 1)
    editor.replace(name, allocation, selected)
    finish = whole_function(editor.values[name], b"static inline int lsf_device_finish(")
    anchor = b"         context->continuations != queued)))"
    require(finish.count(anchor) == 1, "device-root-return-original-bound")
    selected = finish.replace(anchor,
        b"         context->continuations != queued)\n"
        b"#ifdef LSF_STREAM_NODE_CAPACITY_IMAGE\n"
        b"         && !lsf_node_device_child_quiescent(pool, key, ticket, queued)\n"
        b"#endif\n        ))", 1)
    editor.replace(name, finish, selected)


def irq_birth_and_sysfs_hooks(editor, primary):
    for name in ("kernel/irq/irqdomain.c", "lib/kobject.c", "drivers/base/core.c"):
        raw = editor.values[name]
        line = raw[:raw.index(b"\n") + 1]
        editor.replace(name, line, line + HEADER)
    name = "kernel/irq/irqdomain.c"
    # The source also has a prototype and a non-hierarchy CONFIG stub. Select
    # the complete real allocating body by its pinned native opening, not by
    # accepting the first textual function-name occurrence.
    signature = (b"static int irq_domain_alloc_irqs_locked(struct irq_domain *domain, int irq_base,\n"
        b"\t\t\t\t\tunsigned int nr_irqs, int node, void *arg,\n"
        b"\t\t\t\t\tbool realloc, const struct irq_affinity_desc *affinity)\n"
        b"{\n\tint i, ret, virq;")
    original = whole_function(primary[name], signature)
    require(editor.values[name].count(original) == 1, "real-domain-body")
    renamed = original.replace(b"static int irq_domain_alloc_irqs_locked(",
        b"static int lsf_node_ordinary_irq_domain_alloc_irqs_locked(", 1)
    wrapper = (signature[:signature.index(b"{\n")] + b"{\n"
        b"\tstruct lsf_node_irq_call call = {0};\n\tint selected, result, ended;\n\n"
        b"\tselected = lsf_node_irq_call_enter(domain, &call);\n"
        b"\tif (selected < 0)\n\t\treturn selected;\n"
        b"\tif (selected && (realloc || !nr_irqs || nr_irqs > LSF_NODE_CAPACITY_VECTORS)) {\n"
        b"\t\tlsf_node_irq_call_leave(&call);\n\t\treturn -EOPNOTSUPP;\n\t}\n"
        b"\tresult = lsf_node_ordinary_irq_domain_alloc_irqs_locked(domain, irq_base,\n"
        b"\t\tnr_irqs, node, arg, realloc, affinity);\n"
        b"\tif (!selected)\n\t\treturn result;\n"
        b"\tended = lsf_node_irq_call_leave(&call);\n"
        b"\t/* A post-publication unknown remains with its original owner.\n"
        b"\t * Do not recurse into irq_domain_free_irqs under root->mutex. */\n"
        b"\treturn result < 0 ? result : (ended ? ended : result);\n}")
    editor.replace(name, original, renamed + b"\n\n" + wrapper)
    name = "kernel/irq/irqdesc.c"
    editor.replace(name,
        b"\t\tdesc = alloc_desc(start + i, node, flags, mask, owner);\n"
        b"\t\tif (!desc)\n\t\t\tgoto err;\n\t\tirq_insert_desc(start + i, desc);",
        b"\t\tdesc = lsf_node_irq_desc_allocate(start + i, node, flags, mask, owner);\n"
        b"\t\tif (!desc)\n\t\t\tgoto err;\n"
        b"\t\tif (lsf_node_irq_desc_insert(start + i, desc))\n\t\t\tgoto err;")
    editor.replace(name, b'kobject_add(&desc->kobj, irq_kobj_base, "%d", irq)',
        b"lsf_node_irq_kobject_add(desc, irq)")
    name = "net/device-prepaid.h"
    editor.replace(name, b"static int lsf_node_device_actor_current(void);\n",
        b"static int lsf_node_device_actor_current(void);\n"
        b"struct lsf_device_registration_source;\n"
        b"static int lsf_node_irq_kobject_source_locked(const void *object,\n"
        b"    struct lsf_device_registration_source *copy);\n")
    name = "net/factory-device-registration.c"
    raw = whole_function(editor.values[name], b"int lsf_factory_device_registration_kobject(")
    anchor = b"    spin_lock_irqsave(&pool_lock, flags);\n"
    require(raw.count(anchor) == 1, "registration-node-loan-lock")
    replacement = raw.replace(anchor, anchor +
        b"#ifdef LSF_STREAM_NODE_CAPACITY_IMAGE\n"
        b"    result = lsf_node_irq_kobject_source_locked(kobject, copy);\n"
        b"    if (result) {\n"
        b"        if (result < 0)\n            lsf_factory_device_firmware_poison();\n"
        b"        spin_unlock_irqrestore(&pool_lock, flags);\n        return result;\n    }\n"
        b"#endif\n", 1)
    editor.replace(name, raw, replacement)
    name = "drivers/base/core.c"
    anchor = (b"\tif (kobj->ktype != &device_ktype || kobj_to_dev(kobj)->class ||\n")
    editor.replace(name, anchor,
        b"\t{\n\t\tint node = lsf_node_irq_kobject_ready(kobj);\n"
        b"\t\tif (node)\n\t\t\treturn node == 1;\n\t}\n" + anchor)
    editor.prefix_body("lib/kobject.c", b"static void kobject_cleanup(struct kobject *kobj)\n",
        b"\tif (lsf_node_irq_kobject_cleanup(kobj))\n\t\treturn;\n")
    editor.append("lib/kobject.c", b'\n#include "lsf-node-kobject.c"\n')


def parent_vector_hooks(editor):
    name = "kernel/irq/irqdomain.c"
    anchor = b"static struct irq_data *irq_domain_insert_irq_data("
    editor.replace(name, anchor,
        b"#include <net/lsf_node_capacity_private.h>\n"
        b"static int lsf_node_parent_data(struct irq_domain *, struct irq_data *, struct irq_data **);\n"
        b"static void lsf_node_parent_data_free(struct irq_data *);\n"
        b"static int lsf_node_refuse_domain_reparent(unsigned int);\n\n" + anchor)
    body = whole_function(editor.values[name], anchor)
    old = (b"\tstruct irq_data *irq_data;\n\n"
        b"\tirq_data = kzalloc_node(sizeof(*irq_data), GFP_KERNEL,\n"
        b"\t\t\t\tirq_data_get_node(child));")
    new = (b"\tstruct irq_data *irq_data;\n\tint selected;\n\n"
        b"\tselected = lsf_node_parent_data(domain, child, &irq_data);\n"
        b"\tif (selected < 0)\n\t\treturn NULL;\n"
        b"\tif (!selected)\n\t\tirq_data = kzalloc_node(sizeof(*irq_data), GFP_KERNEL,\n"
        b"\t\t\t\tirq_data_get_node(child));")
    require(body.count(old) == 1, "parent-data-native-birth")
    editor.replace(name, body, body.replace(old, new, 1))
    body = whole_function(editor.values[name], b"static void __irq_domain_free_hierarchy(")
    require(body.count(b"\t\tkfree(tmp);") == 1, "parent-data-native-free")
    editor.replace(name, body, body.replace(b"\t\tkfree(tmp);", b"\t\tlsf_node_parent_data_free(tmp);", 1))
    # The supported profile is exactly one native parent. Do not silently enter
    # alternate push/pop kzalloc or copy/reparent algorithms for a Node IRQ.
    for signature, declaration in (
        (b"int irq_domain_push_irq(", b"\tint rv = 0;\n"),
        (b"int irq_domain_pop_irq(", b"\tstruct irq_desc *desc;\n"),
    ):
        body = whole_function(editor.values[name], signature)
        require(body.count(declaration) == 1, "no-reparent-declaration")
        editor.replace(name, body, body.replace(declaration, declaration +
            b"\n\tif (lsf_node_refuse_domain_reparent(virq))\n\t\treturn -EOPNOTSUPP;\n", 1))
    editor.append(name, b'\n#include "lsf-node-irqdomain.c"\n')

    name = "arch/x86/kernel/apic/vector.c"
    anchor = b"static struct apic_chip_data *alloc_apic_chip_data(int node)"
    declarations = (b"#include <net/lsf_node_capacity_private.h>\n"
        b"static struct apic_chip_data *lsf_node_alloc_apic(struct irq_data *, int, const struct irq_alloc_info *);\n"
        b"static int lsf_node_retire_apic(struct apic_chip_data *);\n"
        b"static int lsf_node_vector_alloc(struct irq_data *, const struct cpumask *, bool, unsigned int *);\n"
        b"static void lsf_node_vector_matrix_free(unsigned int, unsigned int, bool);\n"
        b"static int lsf_node_reserve_vector(struct irq_data *);\n"
        b"static void lsf_node_remove_vector_reservation(struct irq_data *);\n\n")
    body = whole_function(editor.values[name], b"static void free_apic_chip_data(")
    require(body.count(b"\tkfree(apicd);") == 1, "apic-native-free")
    editor.replace(name, body, body.replace(b"\tkfree(apicd);",
        b"\tif (!lsf_node_retire_apic(apicd))\n\t\tkfree(apicd);", 1))
    body = whole_function(editor.values[name], b"static int x86_vector_alloc_irqs(")
    require(body.count(b"\t\tapicd = alloc_apic_chip_data(node);") == 1, "apic-native-birth")
    editor.replace(name, body, body.replace(b"\t\tapicd = alloc_apic_chip_data(node);",
        b"\t\tapicd = lsf_node_alloc_apic(irqd, node, info);", 1))
    editor.replace(name, b"vector = irq_matrix_alloc(vector_matrix, dest, resvd, &cpu);",
        b"vector = lsf_node_vector_alloc(irqd, dest, resvd, &cpu);")
    # ALL native free points remain in place, including deferred move cleanup.
    # The wrapper retains exact Node bits; ordinary calls invoke original free.
    old = b"irq_matrix_free(vector_matrix, "
    count = editor.values[name].count(old)
    require(count > 0, "matrix-native-free-sites")
    editor.replace(name, old, b"lsf_node_vector_matrix_free(", count)
    body = whole_function(editor.values[name], b"static int reserve_irq_vector(")
    require(body.count(b"\tunsigned long flags;\n") == 1 and body.count(b"\treturn 0;") == 1,
        "vector-reserve-native-body")
    changed = body.replace(b"\tunsigned long flags;\n", b"\tunsigned long flags;\n\tint ret;\n", 1)
    changed = changed.replace(b"\treserve_irq_vector_locked(irqd);", b"\tret = lsf_node_reserve_vector(irqd);", 1)
    changed = changed.replace(b"\treturn 0;", b"\treturn ret;", 1)
    editor.replace(name, body, changed)
    body = whole_function(editor.values[name], b"static void x86_vector_deactivate(")
    require(body.count(b"\t\treserve_irq_vector_locked(irqd);") == 1, "vector-deactivate-reserve")
    editor.replace(name, body, body.replace(b"\t\treserve_irq_vector_locked(irqd);",
        b"\t\tlsf_node_reserve_vector(irqd);", 1))
    body = whole_function(editor.values[name], b"static void vector_free_reserved_and_managed(")
    require(body.count(b"\t\tirq_matrix_remove_reserved(vector_matrix);") == 1, "vector-soft-release")
    editor.replace(name, body, body.replace(b"\t\tirq_matrix_remove_reserved(vector_matrix);",
        b"\t\tlsf_node_remove_vector_reservation(irqd);", 1))
    editor.replace(name, anchor, declarations + anchor)
    editor.append(name, b'\n#include "lsf-node-vector.c"\n')
    editor.append("kernel/irq/matrix.c", b'\n#include "lsf-node-matrix.c"\n')


def irq_revmap_hooks(editor, primary):
    name = 'lib/radix-tree.c'
    first = editor.values[name].splitlines(keepends=True)[0]
    editor.replace(name, first, first + HEADER)
    signature = b'static inline void\nradix_tree_node_free(struct radix_tree_node *node)'
    old = whole_function(primary[name], signature)
    guard = (b'\tint lsf_selected = lsf_node_radix_queue(node);\n'
             b'\tif (lsf_selected < 0)\n\t\treturn;\n')
    editor.replace(name, old, old.replace(b'{\n', b'{\n' + guard, 1))
    # This precedes, rather than replaces, existing original MSI/IDR dispatch.
    opening = b'void radix_tree_node_rcu_free(struct rcu_head *head)\n{\n'
    guard = (b'\tstruct radix_tree_node *lsf_paid =\n'
             b'\t\tcontainer_of(head, struct radix_tree_node, rcu_head);\n'
             b'\tint lsf_selected = lsf_node_radix_rcu_ready(lsf_paid);\n'
             b'\tif (lsf_selected) {\n\t\tif (lsf_selected < 0) return;\n'
             b'\t\tmemset(lsf_paid->slots, 0, sizeof(lsf_paid->slots));\n'
             b'\t\tmemset(lsf_paid->tags, 0, sizeof(lsf_paid->tags));\n'
             b'\t\tINIT_LIST_HEAD(&lsf_paid->private_list);\n'
             b'\t\tlsf_paid->array = NULL;\n\t\tlsf_paid->parent = NULL;\n'
             b'\t\t(void)lsf_node_radix_finish(lsf_paid);\n\t\treturn;\n\t}\n')
    editor.replace(name, opening, opening + guard)
    editor.append(name, b'\n#include "lsf-node-radix.c"\n')

    name = 'kernel/irq/irqdomain.c'
    signature = (b'static int irq_domain_alloc_irqs_locked(struct irq_domain *domain, int irq_base,\n'
        b'\t\t\t\t\tunsigned int nr_irqs, int node, void *arg,\n'
        b'\t\t\t\t\tbool realloc, const struct irq_affinity_desc *affinity)\n'
        b'{\n\tint i, ret, virq;')
    native = whole_function(primary[name], signature)
    ordinary = native.replace(b'static int irq_domain_alloc_irqs_locked(',
        b'static int lsf_node_ordinary_irq_domain_alloc_irqs_locked(', 1)
    prepaid = native.replace(b'static int irq_domain_alloc_irqs_locked(',
        b'static int lsf_node_prepaid_irq_domain_alloc_irqs_locked(', 1)
    prepaid = prepaid.replace(b'\tint i, ret, virq;', b'\tint i, ret, virq, pruned;', 1)
    before = (b'\tfor (i = 0; i < nr_irqs; i++)\n'
              b'\t\tirq_domain_insert_irq(virq + i);')
    prepare = (b'\tret = lsf_node_irq_revmap_prepare(domain, virq, nr_irqs);\n'
        b'\tif (ret) {\n'
        b'\t\t/* Hierarchy ops already constructed real APIC/vector state. */\n'
        b'\t\tirq_domain_free_irqs_hierarchy(domain, virq, nr_irqs);\n'
        b'\t\tpruned = lsf_node_radix_prune_private(&domain->revmap_tree);\n'
        b'\t\tif (pruned)\n\t\t\tret = pruned;\n'
        b'\t\tgoto out_free_irq_data;\n\t}\n\n')
    require(prepaid.count(before) == 1, 'revmap-publication-loop')
    prepaid = prepaid.replace(before, prepare + before, 1)
    # Retain the complete prior ordinary body, including original errors.
    editor.replace(name, ordinary, ordinary + b'\n\n' + prepaid)
    old = (b'\tresult = lsf_node_ordinary_irq_domain_alloc_irqs_locked(domain, irq_base,\n'
           b'\t\tnr_irqs, node, arg, realloc, affinity);')
    new = (b'\tif (selected)\n'
        b'\t\tresult = lsf_node_prepaid_irq_domain_alloc_irqs_locked(domain, irq_base,\n'
        b'\t\t\tnr_irqs, node, arg, realloc, affinity);\n'
        b'\telse\n'
        b'\t\tresult = lsf_node_ordinary_irq_domain_alloc_irqs_locked(domain, irq_base,\n'
        b'\t\t\tnr_irqs, node, arg, realloc, affinity);')
    editor.replace(name, old, new)
    editor.append(name, b'\n#include "lsf-node-irq-revmap.c"\n')

    # q35 selected remove_allowed requires an empty root BEFORE native remove.
    # This helper locks the true native root mutex; allocation failure above
    # uses the already-locked lib helper and never recursively takes the lock.
    name = 'kernel/irq/lsf-stream-q35-domain.c'
    first = editor.values[name].splitlines(keepends=True)[0]
    editor.replace(name, first, first + HEADER)
    opening = (b'int lsf_q35_domain_remove(struct irq_domain *domain)\n{\n'
               b'    int known = lsf_q35_domain_remove_allowed(domain);')
    replacement = (b'int lsf_q35_domain_remove(struct irq_domain *domain)\n{\n'
        b'    int pruned = lsf_node_irq_revmap_prune(domain);\n'
        b'    int known;\n'
        b'    if (pruned < 0) return pruned;\n'
        b'    known = lsf_q35_domain_remove_allowed(domain);')
    editor.replace(name, opening, replacement)

    # In the NEW factory-node-capacity.c material, integrator adds the actual
    # lsf_node_radix_layout(owner->extent) call to capacity_begin's layout chain
    # BEFORE its extent-validation loop and any capacity preparation.
    # Integrator also captures these three pinned C files as logical outputs:
    # lib/lsf-node-radix.c, kernel/irq/lsf-node-irq-revmap.c, net/factory-node-radix.c;
    # include the factory file AFTER factory-node-irq-loan.c. Header fragment
    # and role26/27 packer support are composed separately, not runtime inputs.


def transform(values, primary, materials):
    require(type(values) is dict and len(values) == 463 and all(
        type(name) is str and type(raw) is bytes for name, raw in values.items()), "source-set")
    before = {name: identity(raw) for name, raw in sorted(values.items())}
    canonical = (json.dumps(before, sort_keys=True, separators=(",", ":")) + "\n").encode()
    require(hashlib.sha256(canonical).hexdigest() == INPUT_SHA, "complete463")
    for source, pins in ((primary, PRIMARY_PINS), (materials, MATERIAL_PINS)):
        require(type(source) is dict and set(source) == set(pins), "captured-set")
        for name, pin in pins.items():
            require(type(source[name]) is bytes and identity(source[name]) == pin, "input-pin")
    require(set(materials) == set(OUTPUTS) | set(REPLACEMENTS) and
        not set(OUTPUTS) & set(REPLACEMENTS) and
        not set(OUTPUTS.values()) & set(values),
        "material-output-set")
    editor = Editor(values)
    for name in NEW_NATIVE:
        editor.add_primary(name, primary[name])
    header_hooks(editor)
    shared_native_hooks(editor)
    node_entry(editor)
    device_child_hooks(editor)
    irq_birth_and_sysfs_hooks(editor, primary)
    parent_vector_hooks(editor)
    irq_revmap_hooks(editor, primary)
    for material, destination in REPLACEMENTS.items():
        editor.replace(destination, editor.values[destination], materials[material])
    require(editor.inverse() == values, "all-prior463-inverse")
    result = editor.values
    result.update({destination: materials[name] for name, destination in OUTPUTS.items()})
    require(len(result) <= 512 and sum(map(len, result.values())) <= 16 * 1024 * 1024,
        "unchanged-source-domain-bounds")
    return result, {
        "stage": "node-native-capacity-prepare", "compiledAbi": COMPILED_ABI,
        "beforeCount": 463, "afterCount": len(result), "prior463": before,
        "sourceInverseExact": True, "nodeFundingIssued": False, "irqEnabled": False,
        "nodeRetired": False, "physicalRefund": False, "runtimeFitQualified": False,
        "sharedBootstrapOwnershipQualified": False,
    }
