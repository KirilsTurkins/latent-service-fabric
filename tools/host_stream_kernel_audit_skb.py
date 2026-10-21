"""Authenticated audit-SKB birth and real final-free derivation; uninstalled."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools import host_stream_kernel_avc as avc
from tools import host_stream_kernel_maintained as maintained

FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_audit_skb.json'
SKBUFF = 'net/core/skbuff.c'
EXTRAS = frozenset((SKBUFF, 'include/linux/skbuff.h', 'net/netlink/af_netlink.c'))
NAMES = frozenset(('skb_kfree_head', 'kfree_skbmem', 'kfree_skb_add_bulk',
    'napi_skb_cache_put', 'kfree_skb_partial', 'skb_clone', 'skb_copy',
    'pskb_expand_head', '__skb_clone'))


def require(value, reason):
    if not value:
        raise ValueError('kernel-audit-skb-' + reason)


def fixture():
    value = json.loads(FIXTURE.read_bytes())
    require(value['upstreamCommit'] == maintained.COMMIT and
        value['archiveSha256'] == maintained.manifest()['archive']['sha256'], 'upstream')
    require(set(value['sections']) == NAMES and
        set(value['source']) == set(avc.fixture()['source']) | EXTRAS, 'membership')
    require(all(value[key] is False for key in ('kernelBuilt', 'actualAuditExecuted',
        'actualLinuxRcuExecuted', 'completeAllocationClosure', 'productionInstallation')),
        'uninstalled-only')
    return value


def section(text, name):
    row = fixture()['sections'][name]
    prefix = row['prefix']
    starts = [i for i in range(len(text)) if text.startswith(prefix, i) and
        (not i or text[i - 1] == '\n')]
    require(len(starts) == 1, 'definition-occurrence')
    end = text.find('\n}\n', starts[0])
    require(end >= 0, 'definition-end')
    raw = text[starts[0]:end + 3]
    require(len(raw.encode()) == row['bytes'] and
        hashlib.sha256(raw.encode()).hexdigest() == row['sha256'], 'definition-preimage')
    return raw


def replace(text, before, after, count=1):
    require(text.count(before) == count, 'replacement-preimage')
    return text.replace(before, after)


def routed(raw, name):
    require(section(raw, name) == raw, 'routed-preimage')
    if name in ('skb_kfree_head', 'kfree_skbmem', 'napi_skb_cache_put'):
        address = 'head' if name == 'skb_kfree_head' else 'skb'
        kind = 'AUDIT_HEAD' if name == 'skb_kfree_head' else 'AUDIT_SKB'
        # Routing precedes even normal allocator-specific inspection. Unknown
        # in-arena addresses retain ownership instead of reaching any heap.
        guard = ('#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            f'\tif (lsf_prepaid_audit_return({address}, LSF_PREPAID_{kind}))\n'
            '\t\treturn;\n#endif\n')
        if name == 'skb_kfree_head':
            return replace(raw, '{\n', '{\n' + guard)
        if name == 'kfree_skbmem':
            return replace(raw, '\tstruct sk_buff_fclones *fclones;\n',
                '\tstruct sk_buff_fclones *fclones;\n\n' + guard)
        return replace(raw, '\tu32 i;\n', '\tu32 i;\n\n' + guard)
    if name == 'kfree_skb_add_bulk':
        return replace(raw, '\tskb_release_all(skb, reason);\n',
            '\tskb_release_all(skb, reason);\n'
            '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\tif (lsf_prepaid_audit_return(skb, LSF_PREPAID_AUDIT_SKB))\n'
            '\t\treturn;\n#endif\n')
    if name == 'kfree_skb_partial':
        return replace(raw, '\t\tkmem_cache_free(net_hotdata.skbuff_cache, skb);',
            '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\t\tif (!lsf_prepaid_audit_return(skb, LSF_PREPAID_AUDIT_SKB))\n#endif\n'
            '\t\t\tkmem_cache_free(net_hotdata.skbuff_cache, skb);')
    if name in ('skb_clone', 'pskb_expand_head'):
        marker = '\tstruct sk_buff *n;\n' if name == 'skb_clone' else '\tint i;\n'
        action = 'lsf_prepaid_audit_clone(skb, birth)' if name == 'skb_clone' else \
            'lsf_prepaid_audit_expand(skb, nhead, ntail, birth)'
        refusal = 'NULL' if name == 'skb_clone' else '-EOPNOTSUPP'
        return replace(raw, marker, marker +
            '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\tstruct lsf_factory_blob birth;\n'
            '\tint owned = lsf_factory_blob_lookup(skb, LSF_PREPAID_AUDIT_SKB, &birth);\n'
            '\tif (owned)\n'
            f'\t\treturn owned < 0 ? {refusal} : {action};\n#endif\n')
    require(name == 'skb_copy', 'routed-name')
    text = replace(raw, '\tint headerlen;\n', '\tint headerlen;\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tstruct lsf_factory_blob birth;\n'
        '\tint owned = lsf_factory_blob_lookup(skb, LSF_PREPAID_AUDIT_SKB, &birth);\n'
        '\tif (owned < 0 || (owned && !lsf_prepaid_audit_linear(skb, birth)))\n'
        '\t\treturn NULL;\n#endif\n')
    return replace(text, '\tn = __alloc_skb(size, gfp_mask,\n'
        '\t\t\tskb_alloc_rx_flag(skb), NUMA_NO_NODE);',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (owned)\n\t\tn = lsf_prepaid_audit_skb_new(birth, size);\n'
        '\telse\n#endif\n'
        '\t\tn = __alloc_skb(size, gfp_mask,\n'
        '\t\t\t\tskb_alloc_rx_flag(skb), NUMA_NO_NODE);')


def authenticate(inputs):
    value = fixture()
    maintained.authenticate_files(inputs, value['source'])
    for name, row in value['sections'].items():
        section(inputs[row['source']].decode(), name)


def derive(inputs):
    authenticate(inputs)
    outputs = avc.derive({name: inputs[name] for name in avc.fixture()['source']})
    original = inputs[SKBUFF].decode()
    text = original
    for name in sorted(NAMES - {'__skb_clone'}):
        raw = section(original, name)
        text = replace(text, raw, routed(raw, name))
    raw = section(original, '__skb_clone')
    text = replace(text, raw, raw + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "../audit-skb-private.c"\n#endif\n')
    text = ('#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "../factory-private.h"\n'
        'static int lsf_prepaid_audit_return(const void *, unsigned int);\n#endif\n' + text)
    outputs[SKBUFF] = text.encode()
    root = maintained.ROOT
    name = 'research/standard-outbound/linux-6.12-lineage/audit-skb-private.c'
    outputs['net/audit-skb-private.c'] = (root / name).read_bytes()
    return outputs
