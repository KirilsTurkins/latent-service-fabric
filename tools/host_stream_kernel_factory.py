"""Authenticate outer allocation preimages for the uninstalled prepaid factory.

No source acquisition, kernel build, device registration or supported platform
selection is performed. Existing upstream files are authenticated and preserved.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools import host_stream_kernel_derivation as original

SOURCE = {
    "net/socket.c": (93292, "26573c98db58359bd892a3db6664efd27674d765db2c6377b2c126e03e54c5e2", "042451f01c6520b85496213e6b3d8d2116ab2533"),
    "net/ipv4/af_inet.c": (51923, "4a055450bbb5d8e578ca2f44e4be31e262d1ced7b2fee9b129027b499ec98eac", "b24d74616637a0e5fc1183cad927fe7c862104c2"),
    "net/ipv6/af_inet6.c": (32504, "79b1a13c5ae676a3ed4a591e120a9d24377a9a495c9d6a752b141d517743d455", "ba69b86f1c7d5e8d9c8b02f3e70a95d913082701"),
    "include/linux/net.h": (12256, "48163c43b595fd24e02caa86650b9c6dd067a51c75332935a3f5b48b9798ae77", "b75bc534c1b351955ac2ada9da09c52bd3bdae3e"),
    "fs/inode.c": (75527, "05f873648c57568a496e1bde9f313152de67f3bac0e1b621e5710da1e5f50663", "8dabb224f941c0b95e7a0e154592bb9137e5bc2c"),
}
PREFIXES = {
    "sock_alloc_inode": ("net/socket.c", "static struct inode *sock_alloc_inode("),
    "sock_alloc_file": ("net/socket.c", "struct file *sock_alloc_file("),
    "sock_alloc": ("net/socket.c", "struct socket *sock_alloc(void)"),
    "__sock_create": ("net/socket.c", "int __sock_create("),
    "inet_create": ("net/ipv4/af_inet.c", "static int inet_create("),
    "inet6_create": ("net/ipv6/af_inet6.c", "static int inet6_create("),
    "alloc_inode": ("fs/inode.c", "static struct inode *alloc_inode("),
    "new_inode_pseudo": ("fs/inode.c", "struct inode *new_inode_pseudo("),
}
FIXTURE = Path(__file__).parent / "tests/fixtures/host_stream_kernel_factory.json"


def function(raw: str, name: str) -> str:
    original.require(name in PREFIXES, "factory-function-name")
    prefix = PREFIXES[name][1]
    starts = [i for i in range(len(raw)) if raw.startswith(prefix, i) and (not i or raw[i - 1] == "\n")]
    original.require(len(starts) == 1, "factory-function-occurrence")
    end = raw.find("\n}\n", starts[0])
    original.require(end != -1, "factory-function-end")
    text = raw[starts[0]:end + 3]
    expected = json.loads(FIXTURE.read_bytes())["functions"][name]
    original.require(original.digest(text.encode()) == expected["sha256"], "factory-function-preimage")
    return text


def authenticate(inputs: dict[str, bytes]) -> dict:
    original.require(set(inputs) == set(SOURCE), "factory-source-membership")
    for name, (size, sha, blob) in SOURCE.items():
        raw = inputs[name]
        original.require(type(raw) is bytes and len(raw) == size and original.digest(raw) == sha and
            hashlib.sha1(b"blob " + str(size).encode() + b"\0" + raw).hexdigest() == blob,
            "factory-whole-preimage")
    for name, (source, _) in PREFIXES.items():
        function(inputs[source].decode(), name)
    return {"schemaVersion": "lsf.kernel-factory-preimages.v1", "upstreamCommit": original.COMMIT,
        "originals": {name: {"bytes": len(raw), "sha256": original.digest(raw)} for name, raw in inputs.items()},
        "functions": sorted(PREFIXES), "upstreamChanged": False,
        "kernelBuilt": False, "trustedFactoryInstalled": False,
        "completeAllocationClosure": False, "productionInstallation": False}
