"""Derive maintained private constructors and actual composite LSM blob returns.

This is uninstalled source. It does not authenticate running geometry, close
LSM/Netlabel/TX/RX allocations, select a consumer or qualify physical retirement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.dev_workflow import paths
from tools import host_stream_kernel_maintained as maintained
from tools import host_stream_kernel_derivation as core
from tools import host_stream_kernel_outer_derivation as outer

ROOT = Path(__file__).resolve().parents[1]
OWNED = ROOT / 'research/standard-outbound/linux-6.12-lineage'
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_protocol.json'
SOURCES = ('net/socket.c', 'net/core/sock.c', 'net/ipv4/af_inet.c', 'fs/inode.c',
           'include/net/sock.h', 'security/security.c')
SECTIONS = {
    'sock_alloc_inode': ('net/socket.c', 'static struct inode *sock_alloc_inode('),
    'sock_free_inode': ('net/socket.c', 'static void sock_free_inode('),
    'sock_alloc': ('net/socket.c', 'struct socket *sock_alloc(void)'),
    '__sock_create': ('net/socket.c', 'int __sock_create('),
    'alloc_inode': ('fs/inode.c', 'static struct inode *alloc_inode('),
    'inode_init_always_gfp': ('fs/inode.c', 'int inode_init_always_gfp('),
    'destroy_inode': ('fs/inode.c', 'static void destroy_inode('),
    'lsm_inode_alloc': ('security/security.c', 'static int lsm_inode_alloc('),
    'security_inode_alloc': ('security/security.c', 'int security_inode_alloc('),
    'security_inode_free': ('security/security.c', 'void security_inode_free('),
    'inode_free_by_rcu': ('security/security.c', 'static void inode_free_by_rcu('),
    'lsm_sock_alloc': ('security/security.c', 'static int lsm_sock_alloc('),
    'security_sk_alloc': ('security/security.c', 'int security_sk_alloc('),
    'security_sk_free': ('security/security.c', 'void security_sk_free('),
    'sk_prot_alloc': ('net/core/sock.c', 'static struct sock *sk_prot_alloc('),
    'sk_prot_free': ('net/core/sock.c', 'static void sk_prot_free('),
    'sk_alloc': ('net/core/sock.c', 'struct sock *sk_alloc('),
    'sock_lock_init': ('net/core/sock.c', 'static inline void sock_lock_init('),
    '__sk_destruct': ('net/core/sock.c', 'static void __sk_destruct('),
    'sk_destruct': ('net/core/sock.c', 'void sk_destruct('),
    'inet_create': ('net/ipv4/af_inet.c', 'static int inet_create('),
}
INCLUDE = '#include <net/lsf_stream_protocol_private.h>\n'


def section(text, name):
    core.require(name in SECTIONS, 'protocol-section-name')
    prefix = SECTIONS[name][1]
    starts = [i for i in range(len(text)) if text.startswith(prefix, i) and (not i or text[i-1] == '\n')]
    core.require(len(starts) == 1, 'protocol-section-occurrence')
    stop = text.find('\n}\n', starts[0])
    core.require(stop >= 0, 'protocol-section-end')
    selected = text[starts[0]:stop+3]
    expected = json.loads(FIXTURE.read_bytes())['sections'][name]
    core.require(core.digest(selected.encode()) == expected['sha256'], 'protocol-section-preimage')
    return selected


def replace(text, old, new):
    return core.replace_once(text, old, new)


def private(original, name):
    core.require(section(original, name) == original, 'protocol-private-preimage')
    if name == 'security_inode_alloc':
        text = replace(original, 'int security_inode_alloc(struct inode *inode, gfp_t gfp)',
            'int lsf_prepaid_security_inode_alloc(struct inode *inode, gfp_t gfp, struct lsf_factory_context *context)')
        return replace(text, 'lsm_inode_alloc(inode, gfp)', 'lsf_prepaid_lsm_inode_alloc(inode, gfp, context)')
    if name == 'security_sk_alloc':
        text = replace(original, 'int security_sk_alloc(struct sock *sk, int family, gfp_t priority)',
            'int lsf_prepaid_security_sk_alloc(struct sock *sk, int family, gfp_t priority, struct lsf_factory_context *context)')
        return replace(text, 'lsm_sock_alloc(sk, priority)', 'lsf_prepaid_lsm_sock_alloc(sk, priority, context)')
    if name == 'inode_init_always_gfp':
        text = replace(original, 'int inode_init_always_gfp(struct super_block *sb, struct inode *inode, gfp_t gfp)',
            'static int lsf_prepaid_inode_init(struct super_block *sb, struct inode *inode, gfp_t gfp, struct lsf_factory_context *context)')
        return replace(text, 'security_inode_alloc(inode, gfp)', 'lsf_prepaid_security_inode_alloc(inode, gfp, context)')
    if name == 'alloc_inode':
        text = outer.derive_private(original, name)
        return replace(text, 'inode_init_always(sb, inode)', 'lsf_prepaid_inode_init(sb, inode, GFP_NOFS, context)')
    if name == 'sk_prot_alloc':
        text = replace(original, 'static struct sock *sk_prot_alloc(struct proto *prot, gfp_t priority,\n\t\tint family)',
            'static struct sock *lsf_prepaid_sk_prot_alloc(struct proto *prot, gfp_t priority,\n\t\tint family, struct lsf_factory_context *context)')
        start = text.index('\tstruct kmem_cache *slab;\n')
        stop = text.index('\n\tif (sk != NULL) {', start)
        text = text[:start] + '\n\tsk = lsf_prepaid_protocol_allocate(prot, priority, family, context);\n' + text[stop:]
        text = replace(text, 'security_sk_alloc(sk, family, priority)',
            'lsf_prepaid_security_sk_alloc(sk, family, priority, context)')
        return replace(text, '\tif (slab != NULL)\n\t\tkmem_cache_free(slab, sk);\n\telse\n\t\tkfree(sk);',
            '\tif (!lsf_prepaid_protocol_return(sk))\n\t\tlsf_factory_poison(context);')
    if name == 'sk_alloc':
        text = replace(original, 'struct sock *sk_alloc(struct net *net, int family, gfp_t priority,\n\t\t      struct proto *prot, int kern)',
            'struct sock *lsf_prepaid_sk_alloc(struct net *net, int family, gfp_t priority,\n\t\t      struct proto *prot, int kern, struct lsf_factory_context *context)')
        text = replace(text, '\tsk = sk_prot_alloc(prot, priority | __GFP_ZERO, family);',
            '\tif (!context || !kern)\n\t\treturn NULL;\n'
            '\tsk = lsf_prepaid_sk_prot_alloc(prot, priority | __GFP_ZERO, family, context);')
        # A private bump arena does not inherit SLAB_TYPESAFE_BY_RCU reuse.
        # Set the real flag before publication; retain original destructor flow.
        return replace(text, '\t\tsk_tx_queue_clear(sk);',
            '\t\tsk_tx_queue_clear(sk);\n\t\tsock_set_flag(sk, SOCK_RCU_FREE);')
    if name == 'inet_create':
        text = replace(original, 'static int inet_create(struct net *net, struct socket *sock, int protocol,\n\t\t       int kern)',
            'int lsf_prepaid_inet_create(struct net *net, struct socket *sock, int protocol,\n\t\t       int kern, struct lsf_factory_context *context, const struct net_proto_family *family)')
        text = replace(text, '\tint try_loading_module = 0;\n', '')
        text = replace(text, '\tif (protocol < 0 || protocol >= IPPROTO_MAX)',
            '\tif (!context || !kern || family != &inet_family_ops ||\n'
            '\t    sock->type != SOCK_STREAM || (protocol != 0 && protocol != IPPROTO_TCP))\n'
            '\t\treturn -EOPNOTSUPP;\n\tif (protocol < 0 || protocol >= IPPROTO_MAX)')
        start = text.index('lookup_protocol:\n')
        text = text[:start] + text[start:].replace('lookup_protocol:\n', '', 1)
        start = text.index('\tif (unlikely(err)) {')
        stop = text.index('\n\terr = -EPERM;', start)
        text = text[:start] + '\tif (unlikely(err))\n\t\tgoto out_rcu_unlock;\n' + text[stop:]
        text = replace(text, '\tsock->ops = answer->ops;',
            '\tif (answer->prot != &tcp_prot || answer->ops != &inet_stream_ops) {\n'
            '\t\terr = -EOPNOTSUPP;\n\t\tgoto out_rcu_unlock;\n\t}\n\tsock->ops = answer->ops;')
        return replace(text, 'sk_alloc(net, PF_INET, GFP_KERNEL, answer_prot, kern)',
            'lsf_prepaid_sk_alloc(net, PF_INET, GFP_KERNEL, answer_prot, kern, context)')
    if name == '__sock_create':
        text = replace(original, 'int __sock_create(struct net *net, int family, int type, int protocol,\n\t\t\t struct socket **res, int kern)',
            'int lsf_prepaid_sock_create(struct net *net, int family, int type, int protocol,\n\t\t\t struct socket **res, int kern, struct lsf_factory_context *context)')
        text = replace(text, '\tconst struct net_proto_family *pf;\n',
            '\tconst struct net_proto_family *pf;\n\t*res = NULL;\n'
            '\tif (!context || !kern || family != PF_INET || type != SOCK_STREAM ||\n'
            '\t    (protocol != 0 && protocol != IPPROTO_TCP) || !lsf_prepaid_protocol_security_supported())\n'
            '\t\treturn -EOPNOTSUPP;\n')
        text = replace(text, '\tsock = sock_alloc();', '\tsock = lsf_outer_sock_alloc(context);')
        start = text.index('#ifdef CONFIG_MODULES\n')
        stop = text.index('#endif\n', start) + len('#endif\n')
        text = text[:start] + text[stop:]
        text = replace(text, '\tif (!pf)\n', '\tif (!pf || !lsf_prepaid_protocol_family(pf))\n')
        return replace(text, 'pf->create(net, sock, protocol, kern)',
            'lsf_prepaid_inet_create(net, sock, protocol, kern, context, pf)')
    core.require(False, 'protocol-private-name')


def observed(original, name):
    core.require(section(original, name) == original, 'protocol-observed-preimage')
    if name == 'security_inode_free':
        return replace(original, '\tcall_rcu((struct rcu_head *)inode->i_security, inode_free_by_rcu);',
            '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\tif (lsf_factory_blob_queue(inode->i_security) < 0)\n\t\treturn;\n#endif\n'
            '\tcall_rcu((struct rcu_head *)inode->i_security, inode_free_by_rcu);')
    if name == 'inode_free_by_rcu':
        text = replace(original, '{\n', '{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\tstruct lsf_factory_blob copy;\n'
            '\tint owned = lsf_factory_blob_lookup(head, LSF_PREPAID_INODE_BLOB, &copy);\n'
            '\tif (owned < 0)\n\t\treturn;\n#endif\n')
        return replace(text, '\tkmem_cache_free(lsm_inode_cache, head);',
            '#ifdef CONFIG_LSF_STREAM_FACTORY\n\tif (owned) {\n'
            '\t\tlsf_factory_blob_finish(copy, LSF_PREPAID_INODE_BLOB);\n\t\treturn;\n\t}\n#endif\n'
            '\tkmem_cache_free(lsm_inode_cache, head);')
    if name == 'security_sk_free':
        text = replace(original, '{\n', '{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\tstruct lsf_factory_blob copy;\n'
            '\tint owned = lsf_factory_blob_lookup(sk->sk_security, LSF_PREPAID_SOCK_BLOB, &copy);\n'
            '\tif (owned < 0)\n\t\treturn;\n#endif\n')
        return replace(text, '\tkfree(sk->sk_security);',
            '#ifdef CONFIG_LSF_STREAM_FACTORY\n\tif (owned)\n'
            '\t\tlsf_factory_blob_finish(copy, LSF_PREPAID_SOCK_BLOB);\n\telse\n#endif\n'
            '\t\tkfree(sk->sk_security);')
    if name == 'sk_prot_alloc':
        return replace(original, '\tif (sk != NULL) {',
            '\tif (sk != NULL) {\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\t\tlsf_prepaid_protocol_clear(sk);\n#endif')
    if name == 'sk_prot_free':
        return replace(original, '\tif (slab != NULL)\n\t\tkmem_cache_free(slab, sk);',
            '#ifdef CONFIG_LSF_STREAM_FACTORY\n\tif (lsf_prepaid_protocol_return(sk))\n'
            '\t\tgoto lsf_module_put;\n#endif\n'
            '\tif (slab != NULL)\n\t\tkmem_cache_free(slab, sk);').replace(
                '\tmodule_put(owner);', '#ifdef CONFIG_LSF_STREAM_FACTORY\nlsf_module_put:\n#endif\n\tmodule_put(owner);')
    core.require(False, 'protocol-observed-name')


def derive(inputs):
    value = maintained.manifest()
    expected = {name: value['source'][name] for name in SOURCES}
    maintained.authenticate_files(inputs, expected)
    original = {name: raw.decode('utf-8') for name, raw in inputs.items()}
    for name, (source, _) in SECTIONS.items():
        section(original[source], name)
    outputs = dict(original)
    # Preserve current original bodies; add only closed private free branches.
    for name in ('security_inode_free', 'inode_free_by_rcu', 'security_sk_free', 'sk_prot_alloc', 'sk_prot_free'):
        source = SECTIONS[name][0]
        before = section(original[source], name)
        outputs[source] = replace(outputs[source], before, observed(before, name))
    for source in ('security/security.c', 'net/core/sock.c', 'fs/inode.c', 'net/socket.c', 'net/ipv4/af_inet.c'):
        outputs[source] = replace(outputs[source], '#include <net/sock.h>\n', '#include <net/sock.h>\n' + INCLUDE) if source not in ('fs/inode.c',) else replace(
            outputs[source], '#include <linux/security.h>\n', '#include <linux/security.h>\n' + INCLUDE)
    outputs['security/security.c'] = replace(outputs['security/security.c'], INCLUDE,
        INCLUDE + '#include <net/lsf_stream_outer.h>\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "../net/factory-private.h"\n#endif\n')
    outputs['security/security.c'] += '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "lsf_security_private.c"\n' + ''.join(
        private(section(original['security/security.c'], name), name)
        for name in ('security_inode_alloc', 'security_sk_alloc')) + '#endif\n'
    outputs['net/core/sock.c'] += '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "lsf_protocol_private.c"\n' + ''.join(
        private(section(original['net/core/sock.c'], name), name)
        for name in ('sk_prot_alloc', 'sk_alloc')) + '#endif\n'
    # New private origin fields live in sock_common's NONCOPIED region. Any
    # later clone/TIMEWAIT consumer needs its own birth, never copied origin.
    fields = ('#ifdef CONFIG_LSF_STREAM_FACTORY\n\tstruct lsf_factory_context *skc_lsf_factory;\n'
        '\tu64 skc_lsf_view_generation;\n\tu32 skc_lsf_view_slot;\n#endif\n')
    outputs['include/net/sock.h'] = replace(outputs['include/net/sock.h'], '\tint\t\t\tskc_dontcopy_begin[0];\n',
        '\tint\t\t\tskc_dontcopy_begin[0];\n' + fields)
    outputs['include/net/sock.h'] = replace(outputs['include/net/sock.h'], '#define sk_dontcopy_begin\t__sk_common.skc_dontcopy_begin\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n#define sk_lsf_factory __sk_common.skc_lsf_factory\n'
        '#define sk_lsf_view_generation __sk_common.skc_lsf_view_generation\n'
        '#define sk_lsf_view_slot __sk_common.skc_lsf_view_slot\n#endif\n'
        '#define sk_dontcopy_begin\t__sk_common.skc_dontcopy_begin\n')
    # The full private outer prefix remains the independently reviewed source.
    # Current 17 sections match its historical per-function preimages exactly;
    # whole-file provenance above is independently current, not re-labelled.
    outputs['include/net/sock.h'] = replace(outputs['include/net/sock.h'],
        'struct socket_alloc {\n\tstruct socket socket;\n\tstruct inode vfs_inode;\n};',
        'struct socket_alloc {\n\tstruct socket socket;\n\tstruct inode vfs_inode;' + outer.FIELDS + '\n};')
    for name in ('sock_alloc_inode', 'sock_free_inode', 'destroy_inode'):
        source = SECTIONS[name][0]
        before = section(original[source], name)
        outputs[source] = replace(outputs[source], before, outer.derive_observed(before, name))
    outputs['net/socket.c'] = replace(outputs['net/socket.c'], INCLUDE,
        INCLUDE + '#include <net/lsf_stream_outer.h>\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "factory-private.h"\nstatic bool lsf_outer_inode_return(struct socket_alloc *);\n#endif\n')
    outputs['fs/inode.c'] = replace(outputs['fs/inode.c'], INCLUDE, INCLUDE + '#include <net/lsf_stream_outer.h>\n')
    outputs['net/socket.c'] += '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "lsf_outer_private.c"\n' + ''.join(
        outer.derive_private(section(original['net/socket.c'], name), name)
        for name in ('sock_alloc_inode', 'sock_alloc')) + private(section(original['net/socket.c'], '__sock_create'), '__sock_create') + '#endif\n'
    outputs['fs/inode.c'] += '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' + ''.join(
        private(section(original['fs/inode.c'], name), name)
        for name in ('inode_init_always_gfp', 'alloc_inode')) + (
        'struct inode *lsf_prepaid_new_inode(struct super_block *sb, struct lsf_factory_context *context)\n'
        '{\n\treturn lsf_prepaid_alloc_inode(sb, context);\n}\n#endif\n')
    outputs['net/ipv4/af_inet.c'] += ('\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        'bool lsf_prepaid_protocol_family(const struct net_proto_family *family)\n'
        '{\n\treturn family == &inet_family_ops;\n}\n' +
        private(section(original['net/ipv4/af_inet.c'], 'inet_create'), 'inet_create') + '#endif\n')
    # Existing closed unknown-hook preflight is retained, not disabled. Real
    # Netlabel/other-hook producers still need prepaid routing before selection.
    outputs['security/security.c'] += ('\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "lsf_outer_security.c"\n'
        'bool lsf_prepaid_protocol_security_supported(void)\n{\n\tstruct lsm_static_call *scall;\n'
        '\tif (!lsf_outer_security_supported())\n\t\treturn false;\n'
        '\tlsm_for_each_hook(scall, sk_alloc_security) { return false; }\n'
        '\tlsm_for_each_hook(scall, sk_free_security) { return false; }\n\treturn true;\n}\n#endif\n')
    extras = {
        'include/net/lsf_stream_protocol_private.h': 'protocol-private.h',
        'include/net/lsf_stream_outer.h': 'outer-hooks.h',
        'include/net/lsf_stream_lineage_core.h': 'lineage.h',
        'net/factory-private.h': 'factory-private.h', 'net/prepaid.h': 'prepaid.h',
        'net/factory.c': 'factory.c', 'net/core/lsf_protocol_private.c': 'protocol-private.c',
        'security/lsf_security_private.c': 'security-private.c',
        'net/lsf_outer_private.c': 'outer-private.c', 'security/lsf_outer_security.c': 'outer-security.c',
    }
    return {**{name: text.encode() for name, text in outputs.items()},
            **{name: (OWNED / owned).read_bytes() for name, owned in extras.items()}}


def reference_body():
    """Exact selected bodies plus explicit doubles; never a Linux execution."""
    fixture = json.loads(FIXTURE.read_bytes())
    original = lambda name: section(fixture['sections'][name]['text'], name)
    body = original('lsm_inode_alloc') + original('lsm_sock_alloc')
    for name in ('inode_free_by_rcu', 'security_inode_free', 'security_sk_free'):
        body += '#ifdef LSF_OLD_SECURITY\n' + original(name) + '#else\n' + observed(original(name), name) + '#endif\n'
    body += original('security_inode_alloc') + original('security_sk_alloc')
    owned = (OWNED / 'security-private.c').read_text()
    owned = replace(owned, '#include "../net/factory-private.h"\n', '')
    body += owned + ''.join(private(original(name), name) for name in ('security_inode_alloc', 'security_sk_alloc'))
    return body.encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    inputs = {name: paths.read(args.source_dir, name, maintained.MAX_FILE) for name in SOURCES}
    outputs = derive(inputs)
    paths.new_directory(args.output)
    for name, raw in outputs.items():
        target = args.output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        paths.write_new(target, raw)
    record = {'schemaVersion': 'lsf.kernel-maintained-protocol.v1', 'upstreamCommit': maintained.COMMIT,
        'originals': {name: {'bytes': len(raw), 'sha256': core.digest(raw)} for name, raw in inputs.items()},
        'derived': {name: {'bytes': len(raw), 'sha256': core.digest(raw)} for name, raw in outputs.items()},
        'ordinaryAllocatorPreserved': True, 'securityHooksPreserved': True,
        'kernelBuilt': False, 'actualKernelExecuted': False, 'trustedFactoryInstalled': False,
        'completeAllocationClosure': False, 'finalFreeCertified': False, 'productionInstallation': False}
    paths.write_new(args.output / 'derivation.json', (json.dumps(record, indent=2)+'\n').encode())
    print(json.dumps(record))


if __name__ == '__main__':
    main()
