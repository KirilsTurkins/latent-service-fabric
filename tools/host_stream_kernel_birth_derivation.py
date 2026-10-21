"""Derive fail-unknown constructor admission on the exact uninstalled kernel.

No running kernel, layout, factory or final-free profile is authenticated here.
The selected CONFIG gate refuses all constructors until that trusted binding
exists. Protocol-double controls cannot qualify real allocation accounting.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import host_stream_kernel_derivation as free

FUNCTIONS = {
    "sk_prot_alloc": ("net/core/sock.c", "static struct sock *",
        "7417e2a7b92a95ab3ddd5ece7bc4d762e0881cdb46b00e59feefaa837d769fb8"),
    "inet_twsk_alloc": ("net/ipv4/inet_timewait_sock.c", "struct inet_timewait_sock *",
        "bcfc841c6909422f9ed6dd5235e38dbb0fc2dfc5d07bc53d879243047931f7ef"),
    "__alloc_skb": ("net/core/skbuff.c", "struct sk_buff *",
        "4530caefbab0eb8731ee3bcbc68ee3bf4a4d11e943b76d02d1ffea3216829f5a"),
}


def function(raw: str, name: str) -> str:
    free.require(name in FUNCTIONS, "unknown-constructor")
    prefix = FUNCTIONS[name][1] + name + "("
    starts = [0] if raw.startswith(prefix) else []
    position = 0
    while (position := raw.find("\n" + prefix, position)) != -1:
        starts.append(position + 1)
        position += len(prefix)
    free.require(len(starts) == 1, "constructor-occurrence")
    stop = raw.find("\n}\n", starts[0])
    free.require(stop != -1, "constructor-end")
    selected = raw[starts[0]:stop + 3]
    free.require(free.digest(selected.encode()) == FUNCTIONS[name][2], "constructor-preimage")
    return selected


def derive_function(original: str, name: str) -> str:
    free.require(name in FUNCTIONS and free.digest(original.encode()) == FUNCTIONS[name][2],
        "constructor-preimage")
    change = free.replace_once
    result = change(original, "\n{\n", "\n{\n\tstruct lsf_bundle lsf_birth;\n")
    if name == "sk_prot_alloc":
        result = change(result, "\tslab = prot->slab;\n",
            "\tif (!lsf_stream_constructor_prepare(LSF_CONSTRUCT_SOCKET, prot, 0,\n"
            "\t\t\t\tpriority, family, 0, &lsf_birth))\n"
            "\t\treturn NULL;\n\n\tslab = prot->slab;\n")
        result = change(result, "\t\tif (!sk)\n\t\t\treturn sk;\n",
            "\t\tif (!sk) {\n\t\t\tlsf_stream_constructor_uncertain(&lsf_birth);\n"
            "\t\t\treturn sk;\n\t\t}\n")
        result = change(result, "\treturn sk;\n\nout_free_sec:",
            "\t/* Cookie initialization belongs to later sk_alloc/clone paths.\n"
            "\t * No live cookie handoff is qualified by this constructor seam. */\n"
            "\tif (sk)\n\t\tlsf_stream_constructor_observed(&lsf_birth, 0, sk, 0);\n"
            "\telse\n\t\tlsf_stream_constructor_uncertain(&lsf_birth);\n"
            "\treturn sk;\n\nout_free_sec:")
        result = change(result, "out_free:\n", "out_free:\n\tlsf_stream_constructor_uncertain(&lsf_birth);\n")
    elif name == "inet_twsk_alloc":
        result = change(result, "\ttw = kmem_cache_alloc(",
            "\tif (!lsf_stream_constructor_prepare(LSF_CONSTRUCT_TIMEWAIT, sk, 0,\n"
            "\t\t\t\tGFP_ATOMIC, 0, 0, &lsf_birth))\n"
            "\t\treturn NULL;\n\n\ttw = kmem_cache_alloc(")
        result = change(result, "\treturn tw;\n",
            "\tif (tw)\n\t\tlsf_stream_constructor_observed(&lsf_birth, 0, tw,\n"
            "\t\t\t\t\t\tatomic64_read(&tw->tw_cookie));\n"
            "\telse\n\t\tlsf_stream_constructor_uncertain(&lsf_birth);\n\treturn tw;\n")
    else:
        result = change(result, "\t/* Get the HEAD */\n",
            "\t/* Reserve BOTH physical records before either allocator. NAPI,\n"
            "\t * size-class rounding and full layout remain trusted-profile gates. */\n"
            "\tif (!lsf_stream_constructor_prepare((flags & SKB_ALLOC_FCLONE) ?\n"
            "\t\tLSF_CONSTRUCT_FCLONE : LSF_CONSTRUCT_SKB, NULL, size,\n"
            "\t\t\t\tgfp_mask, flags, node, &lsf_birth))\n"
            "\t\treturn NULL;\n\n\t/* Get the HEAD */\n")
        result = change(result, "\tif (unlikely(!skb))\n\t\treturn NULL;\n",
            "\tif (unlikely(!skb)) {\n\t\tlsf_stream_constructor_uncertain(&lsf_birth);\n"
            "\t\treturn NULL;\n\t}\n"
            "\tlsf_stream_constructor_observed(&lsf_birth, 0,\n"
            "\t\t(flags & SKB_ALLOC_FCLONE) ? (void *)container_of(skb,\n"
            "\t\tstruct sk_buff_fclones, skb1) : (void *)skb, 0);\n")
        result = change(result, "\t/* kmalloc_size_roundup()",
            "\tlsf_stream_constructor_observed(&lsf_birth, 1, data, 0);\n\t/* kmalloc_size_roundup()")
        result = change(result, "nodata:\n", "nodata:\n\tlsf_stream_constructor_uncertain(&lsf_birth);\n")
    return result


def derive(inputs: dict[str, bytes]) -> dict[str, bytes]:
    # Existing full length/SHA/Git-blob authentication and five free hooks remain
    # mandatory. A function fixture cannot replace any complete file.
    outputs = free.derive(inputs)
    for name, raw in outputs.items():
        text = raw.decode()
        for symbol, (source, _, _) in FUNCTIONS.items():
            if source == name:
                original = function(text, symbol)
                text = free.replace_once(text, original, derive_function(original, symbol))
        anchor = "#include <net/lsf_stream_lineage.h>\n"
        outputs[name] = free.replace_once(text, anchor,
            anchor + "#include <net/lsf_stream_constructors.h>\n").encode()
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inputs = {}
    for name, (size, _, _) in free.SOURCE.items():
        path = args.source_dir / name
        free.require(path.is_file() and not path.is_symlink() and path.stat().st_size == size,
            "source-file")
        inputs[name] = path.read_bytes()
    outputs = derive(inputs)
    free.require(not args.output.exists(), "fresh-output-required")
    extras = {
        "include/net/lsf_stream_lineage_core.h": "lineage.h",
        "include/net/lsf_stream_lineage.h": "kernel-hooks.h",
        "include/net/lsf_stream_admission.h": "admission.h",
        "include/net/lsf_stream_constructors.h": "constructor-hooks.h",
        "net/core/lsf_stream_constructors.c": "constructor-hooks.c",
    }
    outputs.update({name: (free.OWNED / source).read_bytes() for name, source in extras.items()})
    outputs["net/core/lsf_stream_lineage.c"] = (free.OWNED / "kernel-hooks.c").read_bytes() + (
        b'\n/* Same private state/lock; no second owner table. */\n'
        b'#include "lsf_stream_constructors.c"\n')
    record = {
        "schemaVersion": "lsf.kernel-constructor-source-derivation.v1",
        "upstreamCommit": free.COMMIT,
        "originals": {name: {"bytes": len(raw), "sha256": free.digest(raw)} for name, raw in inputs.items()},
        "derived": {name: {"bytes": len(raw), "sha256": free.digest(raw)} for name, raw in outputs.items()},
        "constructorFunctions": sorted(FUNCTIONS), "freeFunctions": sorted(free.FUNCTIONS),
        "unknownContextAndLayoutRefused": True,
        "kernelBuilt": False, "runningKernelAuthenticated": False, "btfAuthenticated": False,
        "trustedFactoryInstalled": False, "completeAllocationClosure": False,
        "preallocationEnforcedOnKernel": False, "finalFreeCertified": False,
        "productionInstallation": False,
    }
    for name, raw in outputs.items():
        target = args.output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (args.output / "derivation.json").write_bytes((json.dumps(record, indent=2) + "\n").encode())
    print(json.dumps(record))


if __name__ == "__main__":
    main()
