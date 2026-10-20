"""Authenticate a partial allocation graph and retain cache-return ownership.

This is an additive uninstalled recipe. It authenticates source observations,
not a maintained/running kernel or a complete allocation bound. Existing model
recipes remain separate. No acquisition, layout selection or factory is implicit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import host_stream_kernel_derivation as free
from tools import host_stream_kernel_handoff_derivation as handoff

# Fixed whole-file and function facts from the historical source baseline.
ADDITIONAL = {'include/linux/skbuff.h': (149284,
                            '7bf07791f2aa5c4914e80139113406d36148d8b69e24ce34d777aead9beb80dc',
                            '39f1d16f362887821caa022464695c4045461493'),
 'include/linux/slab.h': (36868,
                          '5af4c4ab86b1ed2378cbf342b9be9b2a306043b7d7624493d7e1f9c37a3d70fe',
                          'b35e2db7eb0ecc4933126f56b2c3dbf369cbb44b'),
 'include/net/page_pool/helpers.h': (15104,
                                     '54beec50f9cad98a651a8a6e83388145f4e14e1fecbf5ca53f26206ef61d39eb',
                                     '793e6fd78bc5c0890bc875a0ddfcc896e89896dd'),
 'include/net/page_pool/types.h': (9558,
                                   'b7ca44304a7bb01ea3370c35d25cfc3da4952227863fe0ceed3355f372ef2b8b',
                                   'c022c410abe39d588c0933479ab131b3c07391fd'),
 'net/core/dev.c': (316577,
                    'a200c79da6df04e95435219a09f1c46673cffce89667e429c3880a1e2f508956',
                    '8453e14d301b63a84f3d505a1f3dc08f88fe8f7b'),
 'net/core/page_pool.c': (31648,
                          'f66cb52a2abc055881fd45d10810ade4e40030170432eaa8b111e541e6c55efd',
                          'a813d30d213536beab16106ea9a4b6856fa991bb'),
 'net/core/dst.c': (8541,
                    '2e2fda0decc922dd427b4696f071ce782b9f9510fd74f363cf18a55386fc7392',
                    '9552a90d4772dce49b5fe94d2f1d8da6979d9908'),
 'net/core/neighbour.c': (100504,
                          '9d5a9b83248a6ee1b0aad45f7eaeb404ac193c86249f62bb3881993b944cd599',
                          '77b819cd995b2510fed7ace688bce60c98a57563'),
 'mm/page_alloc.c': (202777,
                     '55a8c09ee0fb9f64bef126ce9645bac9b77e440476d50cf80b43df3c3ae503eb',
                     'b6958333054d06ed910f8fef863d83a7312eca9e'),
 'mm/slub.c': (190999,
               '7bd937024342d5c7a40120aaaf50061644c2fefe92ca71b069a38bb6b4770f04',
               '5b832512044e3ead8ccde2c02308bd8954246db5'),
 'net/ipv4/route.c': (95588,
                      '51936639a42e42d71051d834e43b2f8164c104d3772a213e65f6c040a44f5ba0',
                      '723ac9181558c3240204d7b6830a9557d06b10f3'),
 'net/ipv4/tcp.c': (142868,
                    'a323a8aa41a10e1e30f5dead2a6be0fed4c7912e27c624ac273e7d5198d7adef',
                    '4f77bd862e957f865eb919a30475c929da369792'),
 'net/ipv4/tcp_output.c': (131725,
                           '81a3e778a6b698192745c4fc9c50c26245374ffd605b095d894659ca2cbc751a',
                           '68804fd01dafc48101ca8c3f15991dbe02a0dd6f'),
 'net/ipv4/tcp_input.c': (216789,
                          '8007c66e4cf200085935805d33863a75a03089487a53a8b42a596025d859749d',
                          '2d844e1f867f0a67187fcd7f5eed2e30156f2bd7'),
 'net/ipv4/ip_output.c': (43475,
                          '39af3b45940a3926ab7c82545049af631eec59308fa1bfd2f9a2c0009eda0b1c',
                          '49811c9281d424bc4b43b8e9075da9fe724773cb'),
 'net/ipv4/udp.c': (94445,
                    'aef73b6f132756fdba97937cb5205b060dd075e520ba182b9355770728b33f5d',
                    '2849b273b131076cf8300633d6642a6b84468235'),
 'net/ipv6/route.c': (171168,
                      'f66fdcfe8a3d817514462f1a4335518d6eda445d6ee4ecdd3eaabcd2ecfbe2a7',
                      'b4251915585f75ff4ae2038befda9efd09bc5887'),
 'net/ipv6/ip6_output.c': (53932,
                           '5472439d49f2832ecf1eee212ce5f9128848f797d6062cfa7cb6b061509e7b29',
                           'f26841f1490f5c31e3b09bce5773391e779128e1')}
FUNCTIONS = {'napi_skb_cache_get': ('net/core/skbuff.c',
                        'static struct sk_buff *napi_skb_cache_get(',
                        'd5d7ec98d2885972e8353a7d6f2a7286413ccf14bed7897529295492fda74449',
                        'prelookup-bulk-header-cache'),
 '__build_skb': ('net/core/skbuff.c',
                 'struct sk_buff *__build_skb(',
                 'adc749df23aed1b903ccc3f551acbea025d0ce22c888ab1849f6aecc63a42ff4',
                 'preexisting-rx-data-before-header'),
 '__napi_build_skb': ('net/core/skbuff.c',
                      'static struct sk_buff *__napi_build_skb(',
                      '7eb75c4883a04750e0d5d30c4c7abff8087152f25b15736d01113cf94143f315',
                      'prelookup-cached-header'),
 'kmalloc_reserve': ('net/core/skbuff.c',
                     'static void *kmalloc_reserve(',
                     'ab543fca18d8363d1d755e60ea5ead7a836d62b962b5aa7bc482121c509e36e4',
                     'size-roundup-small-head-and-emergency-cache'),
 '__alloc_skb': ('net/core/skbuff.c',
                 'struct sk_buff *__alloc_skb(',
                 '4530caefbab0eb8731ee3bcbc68ee3bf4a4d11e943b76d02d1ffea3216829f5a',
                 'distinct-header-and-data-extents'),
 '__netdev_alloc_skb': ('net/core/skbuff.c',
                        'struct sk_buff *__netdev_alloc_skb(',
                        '7823e8515b43f18cbacc0a6dcbd7d3ad4cca0714bf87b013d17571fa37e67006',
                        'prelookup-page-fragments'),
 'napi_alloc_skb': ('net/core/skbuff.c',
                    'struct sk_buff *napi_alloc_skb(',
                    'c3de20dca2e9618aad081ac05253766b64b867a40d8f9d8090042baec59a87e3',
                    'prelookup-small-and-normal-fragments'),
 'skb_clone': ('net/core/skbuff.c',
               'struct sk_buff *skb_clone(',
               '7a26ccfc7ce40445d5ae30567d3641937fbfbeaf8756b8a7c3c9ea001e317c83',
               'shared-data-and-conditional-fclone-view'),
 'pskb_expand_head': ('net/core/skbuff.c',
                      'int pskb_expand_head(',
                      '07698a5f83542395b269bee01c4bd01f26d5d46e10e7c1b2f1c5032fc76ad25e',
                      'new-head-overlaps-old-shared-lifetime'),
 'skb_release_data': ('net/core/skbuff.c',
                      'static void skb_release_data(',
                      'bd3c68ebee8724b90456c42125e4c9f6b782b3087cbbb25c665ec57e36c63b25',
                      'last-dataref-fraglist-and-page-recycling'),
 'napi_skb_cache_put': ('net/core/skbuff.c',
                        'static void napi_skb_cache_put(',
                        '00395d528cb85866d073f3ac8768a50c5aec9394b9e1f0eeffc5b77647b38981',
                        'cache-return-not-backing-free'),
 'napi_pp_put_page': ('net/core/skbuff.c',
                      'bool napi_pp_put_page(',
                      '99c0ee16ca738e6226bfd2abb34698e5347238d157f0de7954d02e8386327a9a',
                      'page-pool-return-not-final-free'),
 'alloc_skb_with_frags': ('net/core/skbuff.c',
                          'struct sk_buff *alloc_skb_with_frags(',
                          '90755fbd7241a4b245ac61c5431324a92ee55b6c851be7b330bfc98f430761e3',
                          'header-plus-compound-pages'),
 '__page_pool_alloc_pages_slow': ('net/core/page_pool.c',
                                  'static noinline netmem_ref __page_pool_alloc_pages_slow(',
                                  '81d272316513b3c208a5c09dd149ceefcc2d96f0d8970ba488f5ceddf2fd7dc9',
                                  'bulk-or-order-page-allocation'),
 'page_pool_recycle_in_cache': ('net/core/page_pool.c',
                                'static bool page_pool_recycle_in_cache(',
                                'eb7cf4ceb8b930bd564ba70b999b7b14b0e76220086b01446f34d8efef5d8b3b',
                                'shared-page-cache-retention'),
 'page_pool_return_page': ('net/core/page_pool.c',
                           'void page_pool_return_page(',
                           '5e4406d22824712ab4ec2821e71de79dc0b9b2e502dd7784df04fef3302f5a81',
                           'dma-release-and-page-owner-drop'),
 'page_pool_put_unrefed_netmem': ('net/core/page_pool.c',
                                  'void page_pool_put_unrefed_netmem(',
                                  '075991270e31235937c486f82a7989e5680f25d2fee2bac9662125965f32e6d1',
                                  'reference-and-recycle-choice'),
 'page_pool_destroy': ('net/core/page_pool.c',
                       'void page_pool_destroy(',
                       '2399fb3b814b151be3970700262dcefc62af95b56906c0174e0f9b042cbe87e8',
                       'deferred-pool-lifetime'),
 '__page_frag_cache_refill': ('mm/page_alloc.c',
                              'static struct page *__page_frag_cache_refill(',
                              '5356c9ad625842080a502b117532e24b068b9b44dd463dbbc394f1aa32e8fd19',
                              'compound-fallback-page-allocation'),
 '__page_frag_alloc_align': ('mm/page_alloc.c',
                             'void *__page_frag_alloc_align(',
                             '1f3fea5ca0a2f08cd802c1c4f9460bd0dfd1758133c8930e31bb503953d0ebb0',
                             'shared-fragment-refcounts-and-cache'),
 'page_frag_free': ('mm/page_alloc.c',
                    'void page_frag_free(',
                    '216eb080c3a775109207b278fc3af19a7a55813b26a72d3c270bf0857b34a2fd',
                    'last-fragment-before-page-return'),
 'free_unref_page': ('mm/page_alloc.c',
                     'void free_unref_page(',
                     '49e3af96081e51fa55df6720b645880e65bdacf264662cf2c0794808bc98c8bb',
                     'percpu-page-return-not-observed-unmapping'),
 '__slab_free': ('mm/slub.c',
                 'static void __slab_free(',
                 'd45ad5966e93b9694f6b3777ea24db1e6490304553461fcb5d84cb3e72e3d64a',
                 'partial-slab-or-release-choice'),
 'discard_slab': ('mm/slub.c',
                  'static void discard_slab(',
                  '66edd88c8e262d08c56a70ee5596429355226bcf1b5130ab256cfe1d26bd3583',
                  'slab-backing-release-entry'),
 'free_slab': ('mm/slub.c',
               'static void free_slab(',
               'c2cc7c56cf673c107298f52e9ba54db7773055ae73471dc41a39f1462822bfd8',
               'optional-rcu-before-backing-release'),
 '__free_slab': ('mm/slub.c',
                 'static void __free_slab(',
                 'c651c34fbef865f25f70816d82df209c1a7dcbfe3a555c35bc8a61d7faf08818',
                 'slab-metadata-plus-backing-page-release'),
 'dst_alloc': ('net/core/dst.c',
               'void *dst_alloc(',
               'f52b665aca1ae1eb8b4a8a13fd85fab5662ff12b711f8faa660d8ac64e935dbd',
               'shared-route-slab-allocation'),
 'dst_destroy': ('net/core/dst.c',
                 'static void dst_destroy(',
                 '3d246b801af8046a4bd5ef121d125fc7c1e197fafbd020dbc7201f2ccce25685',
                 'route-destruction-and-slab-return'),
 'dst_destroy_rcu': ('net/core/dst.c',
                     'static void dst_destroy_rcu(',
                     '63203b38c0d15d1bd98b73efa028a05d766f2e412c53d0cd499910bc1af6d51c',
                     'deferred-route-destruction'),
 'neigh_alloc': ('net/core/neighbour.c',
                 'static struct neighbour *neigh_alloc(',
                 '61947d18155253866e54bb7e8512f4869352a8262c13ebd9ac79d288f6c0fcb5',
                 'separate-neighbour-allocation'),
 '__netif_receive_skb_core': ('net/core/dev.c',
                              'static int __netif_receive_skb_core(',
                              '291a00f0358aae6c3e5e2aa4e7fd6a3ed620e1c6c97b921f44696caee98d8689',
                              'receive-demux-after-driver-allocation'),
 'tcp_stream_alloc_skb': ('net/ipv4/tcp.c',
                          'struct sk_buff *tcp_stream_alloc_skb(',
                          'ef5bad925e32e3bc9619f2b876f83f745693c420d3aea77c0669dc4b64c1d8c6',
                          'socket-owned-tx-header-before-data'),
 'tcp_sendmsg_locked': ('net/ipv4/tcp.c',
                        'int tcp_sendmsg_locked(',
                        '5dcff08f97ce41fa8f871746e4749bc848736b186bcd1be49dadecc2ec7e1e2d',
                        'socket-page-frag-and-coalescing'),
 '__tcp_close': ('net/ipv4/tcp.c',
                 'void __tcp_close(',
                 '4de67bc18451ad80a6a18f52ea38502456ad8dd941eb71e5943fb570876f574c',
                 'close-with-deferred-descendants'),
 '__tcp_retransmit_skb': ('net/ipv4/tcp_output.c',
                          'int __tcp_retransmit_skb(',
                          'da551be5583e9392cb3f97ab0237347a04e752307a7aa65aea0d091ea23fce09',
                          'retransmit-copy-clone-and-head-expansion'),
 'ip_finish_output2': ('net/ipv4/ip_output.c',
                       'static int ip_finish_output2(',
                       'bba4d68dc2610832a55bee69efd9226484bd359319abf165dcb6fe8ec011941c',
                       'route-neighbour-and-head-expansion'),
 'ip6_finish_output2': ('net/ipv6/ip6_output.c',
                        'static int ip6_finish_output2(',
                        '5c6d3a127c78efcf388b6489800ad97186246a4c41e1a601cf374d62dadc0ddb',
                        'ipv6-route-neighbour-and-head-expansion')}
SOURCE = {**handoff.SOURCE, **ADDITIONAL}


def function(raw: str, name: str) -> str:
    free.require(name in FUNCTIONS, "unknown-physical-function")
    prefix = FUNCTIONS[name][1]
    starts = []
    position = 0
    while True:
        found = raw.find(prefix, position)
        if found == -1:
            break
        position = found + len(prefix)
        if found and raw[found - 1] != "\n":
            continue
        brace, semicolon = raw.find("{", found), raw.find(";", found)
        if brace != -1 and (semicolon == -1 or brace < semicolon):
            starts.append(found)
    free.require(len(starts) == 1, "physical-function-occurrence")
    stop = raw.find("\n}\n", starts[0])
    free.require(stop != -1, "physical-function-end")
    result = raw[starts[0]:stop + 3]
    free.require(free.digest(result.encode()) == FUNCTIONS[name][2], "physical-function-preimage")
    return result


def retain_slot_returns(raw: str, count: int) -> str:
    free.require(count in (1, 3) and raw.count("lsf_stream_after_free(lsf_free);") == count,
        "physical-slot-return-occurrence")
    return raw.replace("lsf_stream_after_free(lsf_free);", "lsf_stream_allocator_returned(lsf_free);")


def derive(inputs: dict[str, bytes]) -> dict[str, bytes]:
    free.require(set(inputs) == set(SOURCE), "physical-source-membership")
    for name, (size, sha, blob) in ADDITIONAL.items():
        raw = inputs[name]
        free.require(type(raw) is bytes and len(raw) == size and free.digest(raw) == sha and
            hashlib.sha1(b"blob " + str(size).encode() + b"\0" + raw).hexdigest() == blob,
            "physical-whole-source-preimage")
    for name, (source, _, _, _) in FUNCTIONS.items():
        function(inputs[source].decode(), name)
    outputs = handoff.derive({name: inputs[name] for name in handoff.SOURCE})
    # Those five object-return notifications cannot certify backing-page free.
    # All original Linux statements and every pre-free copied token stay intact.
    for path, count in (("net/core/sock.c", 1), ("net/ipv4/inet_timewait_sock.c", 1),
                        ("net/core/skbuff.c", 3)):
        text = outputs[path].decode()
        text = retain_slot_returns(text, count)
        anchor = "#include <net/lsf_stream_lineage.h>\n"
        outputs[path] = free.replace_once(text, anchor,
            anchor + "#include <net/lsf_stream_physical.h>\n").encode()
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
        free.require(path.is_file() and not path.is_symlink() and path.stat().st_size == size,
            "physical-source-file")
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
        "include/net/lsf_stream_physical_core.h": "physical-plan.h",
        "include/net/lsf_stream_physical.h": "physical-hooks.h",
        "net/core/lsf_stream_constructors.c": "constructor-hooks.c",
        "net/core/lsf_stream_handoff.c": "handoff-hooks.c",
        "net/core/lsf_stream_physical.c": "physical-hooks.c",
    }
    outputs.update({name: (free.OWNED / owned).read_bytes() for name, owned in extras.items()})
    outputs["net/core/lsf_stream_lineage.c"] = (free.OWNED / "kernel-hooks.c").read_bytes() + (
        b'\n/* Same private state/lock; no second ledger or owner table. */\n'
        b'#include "lsf_stream_constructors.c"\n#include "lsf_stream_handoff.c"\n'
        b'#include "lsf_stream_physical.c"\n')
    record = {"schemaVersion": "lsf.kernel-physical-plan-derivation.v1", "upstreamCommit": free.COMMIT,
        "originals": {name: {"bytes": len(raw), "sha256": free.digest(raw)} for name, raw in inputs.items()},
        "derived": {name: {"bytes": len(raw), "sha256": free.digest(raw)} for name, raw in outputs.items()},
        "authenticatedFunctions": sorted(FUNCTIONS), "slotReturnsRetainOriginalCharge": True,
        "allocationGraphComplete": False, "kernelBuilt": False, "runningKernelAuthenticated": False,
        "trustedFactoryInstalled": False, "beforeLookupClassified": False,
        "physicalLayoutAuthenticated": False, "completeAllocationClosure": False,
        "preallocationEnforcedOnKernel": False, "btfAuthenticated": False,
        "finalFreeCertified": False, "productionInstallation": False}
    for name, raw in outputs.items():
        target = args.output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (args.output / "derivation.json").write_bytes((json.dumps(record, indent=2) + "\n").encode())
    print(json.dumps({"output": str(args.output), "sourceFiles": len(inputs),
        "sourceBytes": sum(map(len, inputs.values())), "functions": len(FUNCTIONS),
        "completeAllocationClosure": False, "productionInstallation": False}))


if __name__ == "__main__":
    main()
