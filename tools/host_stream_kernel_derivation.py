"""Authenticate three Linux 6.12 preimages and derive uninstalled lineage hooks.

No kernel is built, selected or installed. Neither this recipe nor its output is
a complete allocation proof, a retirement certificate or stream enablement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "adc218676eef25575469234709c2d87185ca223a"
SOURCE = {
    "net/core/sock.c": (110171, "8493cd7cc690e18edd30ee5356bb11ed53001f2b7908a4d2438d2725af9f53a8", "da50df485090ff4cd6a91d2f3c2a734a19123958"),
    "net/ipv4/inet_timewait_sock.c": (11131, "654802bafdd257f730be1340b78b2debf4ee1b2263127a89e105d3bab6d846ba", "337390ba85b4082701f78f1a0913ba47c1741378"),
    "net/core/skbuff.c": (186366, "71eaeef9c95eb6a36b2c826c91a470447a9b5ae4e2651757ae66cd98e9afc010", "74149dc4ee318d4489715510360918cce7dba566"),
}
FUNCTIONS = {
    "sk_prot_free": ("net/core/sock.c", "f5f841ccf11bc762a489f045506aea271ec3ffbd8b998601ce344ec4e33a60b2"),
    "inet_twsk_free": ("net/ipv4/inet_timewait_sock.c", "8acf696e7f74297109148404f0c20149df2bd3a1a6b5316a15267d3712b032f1"),
    "skb_kfree_head": ("net/core/skbuff.c", "b17f364ca964d10f352e25a8a68ea294335d014262b077948b8253d2c2eed4ae"),
    "skb_free_head": ("net/core/skbuff.c", "21ddb3a681dacb08912c1fe5a14d3aff25697e9bfe26b00e531edba64ad9a4eb"),
    "kfree_skbmem": ("net/core/skbuff.c", "4e7fd3c46126a83d31e442f60861f8953115fa03d778d46d1783f642bb837c71"),
}
OWNED = ROOT / "research/standard-outbound/linux-6.12-lineage"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def require(value, code):
    if not value:
        raise ValueError("kernel-lineage-" + code)


def replace_once(raw: str, before: str, after: str) -> str:
    require(raw.count(before) == 1, "hunk-preimage")
    return raw.replace(before, after)


def function(raw: str, name: str) -> str:
    require(name in FUNCTIONS, "unknown-function")
    prefix = ("void " if name == "inet_twsk_free" else "static void ") + name + "("
    starts = [0] if raw.startswith(prefix) else []
    position = 0
    while (position := raw.find("\n" + prefix, position)) != -1:
        starts.append(position + 1)
        position += len(prefix)
    require(len(starts) == 1, "function-occurrence")
    stop = raw.find("\n}\n", starts[0])
    require(stop != -1, "function-end")
    selected = raw[starts[0]:stop + 3]
    require(digest(selected.encode()) == FUNCTIONS[name][1], "function-preimage")
    return selected


def derive_function(original: str, name: str) -> str:
    require(name in FUNCTIONS and digest(original.encode()) == FUNCTIONS[name][1], "function-preimage")
    result = original
    if name == "sk_prot_free":
        result = replace_once(result, "\tstruct module *owner;\n", "\tstruct module *owner;\n"
            "\tstruct lsf_token lsf_free = lsf_stream_before_free(LSF_SOCKET, sk,\n"
            "\t\t\t\t\t\tatomic64_read(&sk->sk_cookie));\n")
        result = replace_once(result, "\tmodule_put(owner);", "\tlsf_stream_after_free(lsf_free);\n\tmodule_put(owner);")
    elif name == "inet_twsk_free":
        result = replace_once(result, "\tstruct module *owner = tw->tw_prot->owner;\n",
            "\tstruct module *owner = tw->tw_prot->owner;\n"
            "\tstruct lsf_token lsf_free = lsf_stream_before_free(LSF_TIMEWAIT, tw,\n"
            "\t\t\t\t\t\tatomic64_read(&tw->tw_cookie));\n")
        result = replace_once(result, "\tmodule_put(owner);", "\tlsf_stream_after_free(lsf_free);\n\tmodule_put(owner);")
    elif name == "skb_kfree_head":
        result = replace_once(result, "{\n", "{\n\tstruct lsf_token lsf_free = lsf_stream_before_free(LSF_SKB_HEAD, head, 0);\n")
        result = replace_once(result, "\t\tkfree(head);\n", "\t\tkfree(head);\n\tlsf_stream_after_free(lsf_free);\n")
    elif name == "skb_free_head":
        result = replace_once(result, "\tif (skb->head_frag) {\n", "\tif (skb->head_frag) {\n"
            "\t\t/* Returning a fragment/page to a pool is not final allocator free. */\n"
            "\t\tlsf_stream_unproved_fragment(head);\n")
    elif name == "kfree_skbmem":
        result = replace_once(result, "\tstruct sk_buff_fclones *fclones;\n",
            "\tstruct sk_buff_fclones *fclones;\n\tstruct lsf_token lsf_free;\n")
        result = replace_once(result, "\t\tkmem_cache_free(net_hotdata.skbuff_cache, skb);\n",
            "\t\tlsf_free = lsf_stream_before_free(LSF_SKB_HEADER, skb, 0);\n"
            "\t\tkmem_cache_free(net_hotdata.skbuff_cache, skb);\n"
            "\t\tlsf_stream_after_free(lsf_free);\n")
        result = replace_once(result, "\tkmem_cache_free(net_hotdata.skbuff_fclone_cache, fclones);\n",
            "\tlsf_free = lsf_stream_before_free(LSF_SKB_CLONE, fclones, 0);\n"
            "\tkmem_cache_free(net_hotdata.skbuff_fclone_cache, fclones);\n"
            "\tlsf_stream_after_free(lsf_free);\n")
    return result


def derive(inputs: dict[str, bytes]) -> dict[str, bytes]:
    require(set(inputs) == set(SOURCE), "source-membership")
    result = {}
    for name, (size, sha256, blob) in SOURCE.items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == size and digest(raw) == sha256
            and hashlib.sha1(b"blob " + str(size).encode() + b"\0" + raw).hexdigest() == blob,
            "whole-source-preimage")
        text = raw.decode("utf-8")
        for symbol, (source, _) in FUNCTIONS.items():
            if source == name:
                original = function(text, symbol)
                text = replace_once(text, original, derive_function(original, symbol))
        # Insert exactly once without changing any original include or other byte.
        start = text.index("#include <")
        text = text[:start] + "#include <net/lsf_stream_lineage.h>\n" + text[start:]
        require(text.count("#include <net/lsf_stream_lineage.h>") == 1, "include-occurrence")
        result[name] = text.encode()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inputs = {}
    for name, (size, _, _) in SOURCE.items():
        path = args.source_dir / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == size, "source-file")
        inputs[name] = path.read_bytes()
    outputs = derive(inputs)
    require(not args.output.exists(), "fresh-output-required")
    extras = {"include/net/lsf_stream_lineage_core.h": OWNED / "lineage.h",
        "include/net/lsf_stream_lineage.h": OWNED / "kernel-hooks.h",
        "net/core/lsf_stream_lineage.c": OWNED / "kernel-hooks.c"}
    outputs.update({name: path.read_bytes() for name, path in extras.items()})
    record = {"schemaVersion": "lsf.kernel-lineage-source-derivation.v1", "upstreamCommit": COMMIT,
        "originals": {name: {"bytes": len(raw), "sha256": digest(raw)} for name, raw in inputs.items()},
        "derived": {name: {"bytes": len(raw), "sha256": digest(raw)} for name, raw in outputs.items()},
        "hookedSourceFiles": 3, "hookedFunctions": sorted(FUNCTIONS),
        "kernelBuilt": False, "runningKernelAuthenticated": False, "btfAuthenticated": False,
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
