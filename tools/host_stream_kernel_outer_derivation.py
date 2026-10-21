"""Derive a private prepaid outer socket/VFS prefix from exact Linux sources.

This does not select the factory, build a kernel, qualify layout or implement
the remaining protocol/RX/security consumers. Ordinary socket creation keeps
its allocator, initialization and security calls. Unknown sources refuse.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import host_stream_kernel_derivation as core
from tools import host_stream_kernel_factory as factory

ADDITIONAL = {
    "security/security.c": (176625, "4502c95ba0a1ceeb3fb72bde8e2f5a8452fda859eb2454c318d72e09fba120b8", "c5981e558bc2643b485778edf5c5c20f725ccb00"),
    "include/linux/security.h": (63914, "db9905e1ea9f7a9bb060138a8e5563080c2a7f1df630f5b2c6fcd1b0918842b4", "2ec8f3014757cd78ef0d961e77f42db409db3b1c"),
    "include/linux/fs.h": (125513, "ae3453df09a8817660470524eaf868c5ed4ba67efbac84bd37755674e6c7e3bf", "3559446279c152c70b7f1f3e0154f6e66a5aba33"),
    "include/net/sock.h": (83890, "5b0422aad3a0c982cbff123f3c942110b79e5a4a4408144b6ae0ba6ccfbcf4d2", "f29c14448938753799953be3b6231d2cc3d6ab02"),
}
SOURCE = {**factory.SOURCE, **ADDITIONAL}
FIXTURE = Path(__file__).parent / "tests/fixtures/host_stream_kernel_outer.json"
SECTIONS = {
    "sock_alloc_inode": ("net/socket.c", "static struct inode *sock_alloc_inode("),
    "sock_free_inode": ("net/socket.c", "static void sock_free_inode("),
    "sock_alloc": ("net/socket.c", "struct socket *sock_alloc(void)"),
    "__sock_create": ("net/socket.c", "int __sock_create("),
    "alloc_inode": ("fs/inode.c", "static struct inode *alloc_inode("),
    "destroy_inode": ("fs/inode.c", "static void destroy_inode("),
    "__destroy_inode": ("fs/inode.c", "void __destroy_inode("),
    "i_callback": ("fs/inode.c", "static void i_callback("),
    "inode_init_always_gfp": ("fs/inode.c", "int inode_init_always_gfp("),
    "inode_init_once": ("fs/inode.c", "void inode_init_once("),
    "new_inode_pseudo": ("fs/inode.c", "struct inode *new_inode_pseudo("),
    "lsm_inode_alloc": ("security/security.c", "static int lsm_inode_alloc("),
    "security_inode_alloc": ("security/security.c", "int security_inode_alloc("),
    "security_inode_free": ("security/security.c", "void security_inode_free("),
    "inode_free_by_rcu": ("security/security.c", "static void inode_free_by_rcu("),
    "security_socket_create": ("security/security.c", "int security_socket_create("),
    "security_socket_post_create": ("security/security.c", "int security_socket_post_create("),
}
FIELDS = ("\n#ifdef CONFIG_LSF_STREAM_FACTORY\n"
    "\tstruct lsf_factory_context *lsf_factory;\n"
    "\tu64 lsf_view_generation;\n\tu32 lsf_view_slot;\n\tbool lsf_rcu_owned;\n#endif")
INITIALIZE = ("#ifdef CONFIG_LSF_STREAM_FACTORY\n"
    "\tei->lsf_factory = NULL;\n\tei->lsf_view_generation = 0;\n"
    "\tei->lsf_view_slot = 0;\n\tei->lsf_rcu_owned = false;\n#endif\n")
FREE = ("#ifdef CONFIG_LSF_STREAM_FACTORY\n"
    "\tif (lsf_outer_inode_return(ei))\n\t\treturn;\n#endif\n")


def section(raw: str, name: str) -> str:
    core.require(name in SECTIONS, "outer-section-name")
    prefix = SECTIONS[name][1]
    starts = [i for i in range(len(raw)) if raw.startswith(prefix, i) and (not i or raw[i - 1] == "\n")]
    core.require(len(starts) == 1, "outer-section-occurrence")
    stop = raw.find("\n}\n", starts[0])
    core.require(stop != -1, "outer-section-end")
    selected = raw[starts[0]:stop + 3]
    expected = json.loads(FIXTURE.read_bytes())["sections"][name]
    core.require(core.digest(selected.encode()) == expected["sha256"], "outer-section-preimage")
    return selected


def derive_private(original: str, name: str) -> str:
    core.require(name in ("sock_alloc_inode", "alloc_inode", "sock_alloc"), "outer-private-name")
    core.require(section(original, name) == original, "outer-private-preimage")
    if name == "sock_alloc_inode":
        text = core.replace_once(original, "static struct inode *sock_alloc_inode(struct super_block *sb)",
            "struct inode *lsf_outer_alloc_inode(struct super_block *sb, struct lsf_factory_context *context)")
        text = core.replace_once(text, "\tstruct socket_alloc *ei;\n",
            "\tstruct socket_alloc *ei;\n\tstruct lsf_prepaid_ticket ticket = {0};\n")
        text = core.replace_once(text, "\tei = alloc_inode_sb(sb, sock_inode_cachep, GFP_KERNEL);\n",
            "\tif (!context || !lsf_outer_superblock_supported(sb) ||\n"
            "\t    !lsf_outer_security_supported())\n\t\treturn NULL;\n"
            "\tei = lsf_factory_allocate(context, sizeof(*ei),\n"
            "\t\t(struct lsf_prepaid_ticket){0}, 0, &ticket);\n")
        return core.replace_once(text, "\tinit_waitqueue_head(&ei->socket.wq.wait);\n",
            "\tinode_init_once(&ei->vfs_inode);\n\tei->lsf_factory = context;\n"
            "\tei->lsf_view_generation = ticket.generation;\n\tei->lsf_view_slot = ticket.slot;\n"
            "\tei->lsf_rcu_owned = false;\n\tinit_waitqueue_head(&ei->socket.wq.wait);\n")
    if name == "alloc_inode":
        text = core.replace_once(original, "static struct inode *alloc_inode(struct super_block *sb)",
            "static struct inode *lsf_prepaid_alloc_inode(struct super_block *sb, struct lsf_factory_context *context)")
        return core.replace_once(text,
            "\tif (ops->alloc_inode)\n\t\tinode = ops->alloc_inode(sb);\n\telse\n"
            "\t\tinode = alloc_inode_sb(sb, inode_cachep, GFP_KERNEL);\n",
            "\tif (!context || !lsf_outer_superblock_supported(sb) ||\n"
            "\t    !lsf_outer_security_supported())\n\t\treturn NULL;\n"
            "\tinode = lsf_outer_alloc_inode(sb, context);\n")
    text = core.replace_once(original, "struct socket *sock_alloc(void)",
        "struct socket *lsf_outer_sock_alloc(struct lsf_factory_context *context)")
    return core.replace_once(text, "\tinode = new_inode_pseudo(sock_mnt->mnt_sb);\n",
        "\tif (IS_ERR_OR_NULL(sock_mnt))\n\t\treturn NULL;\n"
        "\tinode = lsf_prepaid_new_inode(sock_mnt->mnt_sb, context);\n")


def derive_observed(original: str, name: str) -> str:
    core.require(name in ("sock_alloc_inode", "sock_free_inode", "destroy_inode"), "outer-observed-name")
    core.require(section(original, name) == original, "outer-observed-preimage")
    if name == "sock_alloc_inode":
        return core.replace_once(original, "\tinit_waitqueue_head(&ei->socket.wq.wait);\n",
            INITIALIZE + "\tinit_waitqueue_head(&ei->socket.wq.wait);\n")
    if name == "sock_free_inode":
        return core.replace_once(original, "\tkmem_cache_free(sock_inode_cachep, ei);\n",
            FREE + "\tkmem_cache_free(sock_inode_cachep, ei);\n")
    return core.replace_once(original, "\tcall_rcu(&inode->i_rcu, i_callback);\n",
        "\tlsf_outer_inode_queue(inode);\n\tcall_rcu(&inode->i_rcu, i_callback);\n")


def derive(inputs: dict[str, bytes]) -> dict[str, bytes]:
    core.require(set(inputs) == set(SOURCE), "outer-source-membership")
    for name, (size, sha, blob) in SOURCE.items():
        raw = inputs[name]
        core.require(type(raw) is bytes and len(raw) == size and core.digest(raw) == sha and
            hashlib.sha1(b"blob " + str(size).encode() + b"\0" + raw).hexdigest() == blob,
            "outer-whole-preimage")
    for name, (source, _) in SECTIONS.items():
        section(inputs[source].decode(), name)
    outputs = dict(inputs)
    socket = inputs["net/socket.c"].decode()
    socket = core.replace_once(socket, "#include <net/sock.h>\n",
        "#include <net/sock.h>\n#include <net/lsf_stream_outer.h>\n"
        "#ifdef CONFIG_LSF_STREAM_FACTORY\n#include \"factory-private.h\"\n"
        "static bool lsf_outer_inode_return(struct socket_alloc *);\n#endif\n")
    constructor = section(socket, "sock_alloc_inode")
    normal = derive_observed(constructor, "sock_alloc_inode")
    socket = core.replace_once(socket, constructor, normal)
    released = section(socket, "sock_free_inode")
    socket = core.replace_once(socket, released, derive_observed(released, "sock_free_inode"))
    socket += ("\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include \"lsf_outer_private.c\"\n" +
        derive_private(constructor, "sock_alloc_inode") +
        derive_private(section(inputs["net/socket.c"].decode(), "sock_alloc"), "sock_alloc") + "#endif\n")
    outputs["net/socket.c"] = socket.encode()
    inode = inputs["fs/inode.c"].decode()
    inode = core.replace_once(inode, "#include <linux/security.h>\n",
        "#include <linux/security.h>\n#include <net/lsf_stream_outer.h>\n")
    destroy = section(inode, "destroy_inode")
    inode = core.replace_once(inode, destroy, derive_observed(destroy, "destroy_inode"))
    inode += ("\n#ifdef CONFIG_LSF_STREAM_FACTORY\n" +
        derive_private(section(inputs["fs/inode.c"].decode(), "alloc_inode"), "alloc_inode") +
        "struct inode *lsf_prepaid_new_inode(struct super_block *sb, struct lsf_factory_context *context)\n"
        "{\n\treturn lsf_prepaid_alloc_inode(sb, context);\n}\n#endif\n")
    outputs["fs/inode.c"] = inode.encode()
    sock = inputs["include/net/sock.h"].decode()
    outputs["include/net/sock.h"] = core.replace_once(sock,
        "struct socket_alloc {\n\tstruct socket socket;\n\tstruct inode vfs_inode;\n};",
        "struct socket_alloc {\n\tstruct socket socket;\n\tstruct inode vfs_inode;" + FIELDS + "\n};").encode()
    security = inputs["security/security.c"].decode()
    security = core.replace_once(security, "#include <net/sock.h>\n",
        "#include <net/sock.h>\n#include <net/lsf_stream_outer.h>\n")
    outputs["security/security.c"] = (security +
        "\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include \"lsf_outer_security.c\"\n#endif\n").encode()
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inputs = {}
    for name, (size, _, _) in SOURCE.items():
        path = args.source_dir / name
        core.require(path.is_file() and not path.is_symlink() and path.stat().st_size == size, "outer-source-file")
        inputs[name] = path.read_bytes()
    outputs = derive(inputs)
    extras = {
        "include/net/lsf_stream_outer.h": "outer-hooks.h",
        "include/net/lsf_stream_lineage_core.h": "lineage.h",
        "net/factory-private.h": "factory-private.h",
        "net/prepaid.h": "prepaid.h",
        "net/lsf_outer_private.c": "outer-private.c",
        "security/lsf_outer_security.c": "outer-security.c",
    }
    outputs.update({name: (core.OWNED / owned).read_bytes() for name, owned in extras.items()})
    core.require(not args.output.exists(), "fresh-output-required")
    record = {"schemaVersion": "lsf.kernel-prepaid-outer.v1", "upstreamCommit": core.COMMIT,
        "originals": {name: {"bytes": len(raw), "sha256": core.digest(raw)} for name, raw in inputs.items()},
        "derived": {name: {"bytes": len(raw), "sha256": core.digest(raw)} for name, raw in outputs.items()},
        "authenticatedSections": sorted(SECTIONS), "ordinaryAllocatorPreserved": True,
        "securityHooksPreserved": True, "kernelBuilt": False, "actualOuterExecuted": False,
        "trustedFactoryInstalled": False, "completeAllocationClosure": False,
        "finalFreeCertified": False, "productionInstallation": False}
    for name, raw in outputs.items():
        target = args.output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (args.output / "derivation.json").write_bytes((json.dumps(record, indent=2) + "\n").encode())
    print(json.dumps(record))


if __name__ == "__main__":
    main()
