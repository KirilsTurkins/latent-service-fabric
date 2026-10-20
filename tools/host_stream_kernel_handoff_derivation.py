"""Derive an uninstalled reserved-address to initialized-cookie handoff.

The same historical kernel baseline is required, plus whole cookie/header
preimages. No trusted factory, running kernel, physical profile or final-free
qualification is supplied. Existing cookie generation and clone semantics stay
unchanged; only private lineage hooks are inserted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import host_stream_kernel_birth_derivation as birth
from tools import host_stream_kernel_derivation as free

ADDITIONAL = {
    "include/net/sock.h": (83890, "5b0422aad3a0c982cbff123f3c942110b79e5a4a4408144b6ae0ba6ccfbcf4d2", "f29c14448938753799953be3b6231d2cc3d6ab02"),
    "include/linux/sock_diag.h": (2480, "241560e700d5f962d254be52f25aa2e1908cff11676ec43aa13eb64c8d021d44", "110978dc9af1b19194644151af5456b8c6644cf9"),
    "net/core/sock_diag.c": (8242, "ba437fc71e0065e9f8325b39cbf280d4f1819d322f6f6df038ee28c3a1221844", "a08eed9b9142e38d5f4a6a16c139b37d1a84cad1"),
    "include/linux/cookie.h": (1254, "fc5a26a63d46117b68842025a5c0baab6adbc690d6df7bb1b8b11fccae924a1c", "0c159f58510987609f5f954298b019b71797a4fe"),
}
SOURCE = {**free.SOURCE, **ADDITIONAL}
FUNCTIONS = {
    "sk_alloc": ("net/core/sock.c", "struct sock *", "155dff9763733f378c1e2f778ee3658e31c944df06259c1395d61f081ce87ee2"),
    "sk_clone_lock": ("net/core/sock.c", "struct sock *", "0169e1a2d03503c1264feb69d6495c6fa1f3dca336e14612f0330144c7489ccb"),
    "sk_init_common": ("net/core/sock.c", "static void ", "e4518de0b7e7c8106bdee62944b87f23f4e5e796820984de916abdcc7a555f0b"),
    "sock_copy": ("net/core/sock.c", "static void ", "24de46beb410da0fe3f684c70d1a8a2a90227f74f511b372b8d8413d280eee78"),
    "sock_gen_cookie": ("include/linux/sock_diag.h", "static inline u64 ", "f48edd228dd1bffe50a020862488577daf6033b89b585a365b1afbf4652e3a44"),
    "__sock_gen_cookie": ("net/core/sock_diag.c", "u64 ", "bcd9241165453959be61b6e1194cb6ddb14a06d7c147d0bae34064f5d5c73fa5"),
    "gen_cookie_next": ("include/linux/cookie.h", "static __always_inline u64 ", "1ea85a5fdc5403ef4d75a756df7cd00071566e772025d2da970eb24bc1ed0d43"),
}


def function(raw: str, name: str) -> str:
    free.require(name in FUNCTIONS, "unknown-handoff-function")
    prefix = FUNCTIONS[name][1] + name + "("
    starts = [0] if raw.startswith(prefix) else []
    position = 0
    while (position := raw.find("\n" + prefix, position)) != -1:
        starts.append(position + 1)
        position += len(prefix)
    free.require(len(starts) == 1, "handoff-function-occurrence")
    stop = raw.find("\n}\n", starts[0])
    free.require(stop != -1, "handoff-function-end")
    selected = raw[starts[0]:stop + 3]
    free.require(free.digest(selected.encode()) == FUNCTIONS[name][2], "handoff-function-preimage")
    return selected


def derive_function(original: str, name: str) -> str:
    free.require(name in ("sk_alloc", "sk_clone_lock") and
        free.digest(original.encode()) == FUNCTIONS[name][2], "handoff-function-preimage")
    if name == "sk_alloc":
        return free.replace_once(original, "\t\tsk_tx_queue_clear(sk);\n",
            "\t\tsk_tx_queue_clear(sk);\n\t\tlsf_stream_socket_initialized(sk);\n")
    return free.replace_once(original, "\tsmp_wmb();\n",
        "\tlsf_stream_socket_initialized(newsk);\n\tsmp_wmb();\n")


def derive_socket_constructor(original: str) -> str:
    # Start with the exact previously reviewed constructor derivation.
    result = birth.derive_function(original, "sk_prot_alloc")
    return free.replace_once(result,
        "\t/* Cookie initialization belongs to later sk_alloc/clone paths.\n"
        "\t * No live cookie handoff is qualified by this constructor seam. */\n"
        "\tif (sk)\n\t\tlsf_stream_constructor_observed(&lsf_birth, 0, sk, 0);\n",
        "\t/* Keep the original record RESERVED until its outer constructor\n"
        "\t * finishes initialization. Never inspect an allocator cookie. */\n"
        "\tif (sk)\n\t\tlsf_stream_socket_reserved(&lsf_birth, sk);\n")


def derive(inputs: dict[str, bytes]) -> dict[str, bytes]:
    free.require(set(inputs) == set(SOURCE), "handoff-source-membership")
    for name, (size, sha, blob) in ADDITIONAL.items():
        raw = inputs[name]
        free.require(type(raw) is bytes and len(raw) == size and free.digest(raw) == sha and
            hashlib.sha1(b"blob " + str(size).encode() + b"\0" + raw).hexdigest() == blob,
            "handoff-whole-source-preimage")
    for name, (source, _, _) in FUNCTIONS.items():
        function(inputs[source].decode(), name)
    outputs = birth.derive({name: inputs[name] for name in free.SOURCE})
    text = outputs["net/core/sock.c"].decode()
    for name in ("sk_alloc", "sk_clone_lock"):
        original = function(text, name)
        text = free.replace_once(text, original, derive_function(original, name))
    constructor = birth.function(inputs["net/core/sock.c"].decode(), "sk_prot_alloc")
    text = free.replace_once(text, birth.derive_function(constructor, "sk_prot_alloc"),
        derive_socket_constructor(constructor))
    anchor = "#include <net/lsf_stream_constructors.h>\n"
    outputs["net/core/sock.c"] = free.replace_once(text, anchor,
        anchor + "#include <net/lsf_stream_handoff.h>\n").encode()
    outputs.update({name: inputs[name] for name in ADDITIONAL})
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inputs = {}
    for name, (size, _, _) in SOURCE.items():
        path = args.source_dir / name
        free.require(path.is_file() and not path.is_symlink() and path.stat().st_size == size, "source-file")
        inputs[name] = path.read_bytes()
    outputs = derive(inputs)
    free.require(not args.output.exists(), "fresh-output-required")
    extras = {
        "include/net/lsf_stream_lineage_core.h": "lineage.h",
        "include/net/lsf_stream_lineage.h": "kernel-hooks.h",
        "include/net/lsf_stream_admission.h": "admission.h",
        "include/net/lsf_stream_constructors.h": "constructor-hooks.h",
        "include/net/lsf_stream_handoff_core.h": "handoff.h",
        "include/net/lsf_stream_handoff.h": "handoff-hooks.h",
        "net/core/lsf_stream_constructors.c": "constructor-hooks.c",
        "net/core/lsf_stream_handoff.c": "handoff-hooks.c",
    }
    outputs.update({name: (free.OWNED / owned).read_bytes() for name, owned in extras.items()})
    outputs["net/core/lsf_stream_lineage.c"] = (free.OWNED / "kernel-hooks.c").read_bytes() + (
        b'\n/* Same private state/lock, no new owner table. */\n'
        b'#include "lsf_stream_constructors.c"\n#include "lsf_stream_handoff.c"\n')
    record = {"schemaVersion": "lsf.kernel-cookie-handoff-derivation.v1", "upstreamCommit": free.COMMIT,
        "originals": {name: {"bytes": len(raw), "sha256": free.digest(raw)} for name, raw in inputs.items()},
        "derived": {name: {"bytes": len(raw), "sha256": free.digest(raw)} for name, raw in outputs.items()},
        "authenticatedFunctions": sorted(FUNCTIONS), "unchangedCookieGenerator": True,
        "cloneCookieReset": False, "kernelBuilt": False, "runningKernelAuthenticated": False,
        "trustedFactoryInstalled": False, "btfAuthenticated": False,
        "completeAllocationClosure": False, "preallocationEnforcedOnKernel": False,
        "finalFreeCertified": False, "productionInstallation": False}
    for name, raw in outputs.items():
        target = args.output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (args.output / "derivation.json").write_bytes((json.dumps(record, indent=2) + "\n").encode())
    print(json.dumps(record))


if __name__ == "__main__":
    main()
