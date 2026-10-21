"""Closed maintained Netlabel producer derivation; uninstalled source only."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.dev_workflow import paths

from tools import host_stream_kernel_protocol as protocol
from tools import host_stream_kernel_maintained as maintained

FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_netlabel.json'
NAMES = frozenset(('selinux_netlbl_sock_genattr', 'selinux_netlbl_socket_post_create',
    'selinux_netlbl_socket_connect_helper', 'security_netlbl_sid_to_secattr',
    'mls_export_netlbl_cat', 'ebitmap_netlbl_export', '_netlbl_catmap_getnode',
    'netlbl_catmap_setlong', 'netlbl_sock_setattr', 'netlbl_conn_setattr',
    'netlbl_catmap_free', 'netlbl_secattr_destroy', 'netlbl_secattr_free',
    'cipso_v4_sock_setattr', 'cipso_v4_delopt', 'inet_sock_destruct'))
RENAMES = {
    'selinux_netlbl_sock_genattr': 'lsf_prepaid_netlabel_sock_genattr',
    'security_netlbl_sid_to_secattr': 'lsf_prepaid_security_sid_to_secattr',
    'mls_export_netlbl_cat': 'lsf_prepaid_mls_export_cat',
    'ebitmap_netlbl_export': 'lsf_prepaid_ebitmap_export',
    '_netlbl_catmap_getnode': 'lsf_prepaid_catmap_getnode',
    'netlbl_catmap_setlong': 'lsf_prepaid_catmap_setlong',
    'netlbl_sock_setattr': 'lsf_prepaid_netlbl_sock_setattr',
    'netlbl_conn_setattr': 'lsf_prepaid_netlbl_conn_setattr',
    'cipso_v4_sock_setattr': 'lsf_prepaid_cipso_sock_setattr',
}


def require(value, reason):
    if not value:
        raise ValueError('kernel-netlabel-' + reason)


def fixture():
    value = json.loads(FIXTURE.read_bytes())
    require(value['upstreamCommit'] == maintained.COMMIT and set(value['sections']) == NAMES,
            'maintained-definition-membership')
    require(value['archiveSha256'] == maintained.manifest()['archive']['sha256'], 'archive-identity')
    require(value['kernelBuilt'] is value['actualLsmExecuted'] is value['completeAllocationClosure']
            is value['productionInstallation'] is False, 'uninstalled-only')
    return value


def section(text, name):
    rows = fixture()['sections']
    require(name in rows, 'section-name')
    prefix = rows[name]['prefix']
    starts = [i for i in range(len(text)) if text.startswith(prefix, i) and (not i or text[i-1] == '\n')]
    require(len(starts) == 1, 'section-occurrence')
    stop = text.find('\n}\n', starts[0]);require(stop >= 0, 'section-end')
    raw = text[starts[0]:stop+3]
    require(hashlib.sha256(raw.encode()).hexdigest() == rows[name]['sha256'], 'section-preimage')
    return raw


def replace(text, old, new, count=1):
    require(text.count(old) == count, 'closed-replacement-preimage')
    return text.replace(old, new)


def private(original, name):
    require(name in RENAMES and section(original, name) == original, 'private-preimage')
    head, body = original.split('\n{\n', 1)
    head = replace(head, name + '(', RENAMES[name] + '(')
    if name == 'selinux_netlbl_sock_genattr':
        head = replace(head, 'static struct netlbl_lsm_secattr *', 'struct netlbl_lsm_secattr *')
    close = head.rfind(')');require(close >= 0, 'signature')
    text = head[:close] + ', const struct lsf_factory_blob *source' + head[close:] + '\n{\n' + body
    if name == 'selinux_netlbl_sock_genattr':
        text = replace(text, '\tif (sksec->nlbl_secattr != NULL)\n\t\treturn sksec->nlbl_secattr;',
            '\tif (sksec->nlbl_secattr != NULL) {\n\t\tstruct lsf_factory_blob copy;\n'
            '\t\tif (lsf_factory_blob_lookup(sksec->nlbl_secattr, LSF_PREPAID_LABEL, &copy) == 1 &&\n'
            '\t\t    copy.context == source->context)\n\t\t\treturn sksec->nlbl_secattr;\n'
            '\t\tlsf_factory_poison(source->context);\n\t\treturn ERR_PTR(-EOPNOTSUPP);\n\t}')
        text = replace(text, 'netlbl_secattr_alloc(GFP_ATOMIC)',
            'lsf_factory_child_allocate(*source, sizeof(*secattr), LSF_PREPAID_LABEL)')
        return replace(text, 'security_netlbl_sid_to_secattr(sksec->sid, secattr)',
            'lsf_prepaid_security_sid_to_secattr(sksec->sid, secattr, source)')
    if name == 'security_netlbl_sid_to_secattr':
        text = replace(text, 'kstrdup(sym_name(policydb, SYM_TYPES, ctx->type - 1),\n\t\t\t\t  GFP_ATOMIC)',
            'lsf_prepaid_netlabel_strdup(sym_name(policydb, SYM_TYPES, ctx->type - 1), source)')
        return replace(text, 'mls_export_netlbl_cat(policydb, ctx, secattr)',
            'lsf_prepaid_mls_export_cat(policydb, ctx, secattr, source)')
    if name == 'mls_export_netlbl_cat':
        return replace(text, 'ebitmap_netlbl_export(&context->range.level[0].cat,\n\t\t\t\t   &secattr->attr.mls.cat)',
            'lsf_prepaid_ebitmap_export(&context->range.level[0].cat,\n\t\t\t\t   &secattr->attr.mls.cat, source)')
    if name == 'ebitmap_netlbl_export':
        return replace(text, 'netlbl_catmap_setlong(catmap, offset,\n\t\t\t\t\t\t\t   e_map, GFP_ATOMIC)',
            'lsf_prepaid_catmap_setlong(catmap, offset,\n\t\t\t\t\t\t\t   e_map, GFP_ATOMIC, source)')
    if name == '_netlbl_catmap_getnode':
        text = replace(text, '\tstruct netlbl_lsm_catmap *prev = NULL;\n',
            '\tstruct netlbl_lsm_catmap *prev = NULL;\n\tif (!source || gfp_flags != GFP_ATOMIC)\n\t\treturn NULL;\n')
        return replace(text, 'netlbl_catmap_alloc(gfp_flags)',
            'lsf_factory_child_allocate(*source, sizeof(*iter), LSF_PREPAID_LABEL_CATMAP)')
    if name == 'netlbl_catmap_setlong':
        return replace(text, '_netlbl_catmap_getnode(catmap, offset, _CM_F_ALLOC, flags)',
            'lsf_prepaid_catmap_getnode(catmap, offset, _CM_F_ALLOC, flags, source)')
    if name == 'netlbl_sock_setattr':
        text = replace(text, '\trcu_read_lock();',
            '\tif (!source || family != AF_INET)\n\t\treturn -EOPNOTSUPP;\n\trcu_read_lock();')
        return replace(text, 'cipso_v4_sock_setattr(sk,\n\t\t\t\t\t\t\tdom_entry->def.cipso,\n\t\t\t\t\t\t\tsecattr, sk_locked)',
            'lsf_prepaid_cipso_sock_setattr(sk,\n\t\t\t\t\t\t\tdom_entry->def.cipso,\n\t\t\t\t\t\t\tsecattr, sk_locked, source)')
    if name == 'netlbl_conn_setattr':
        text = replace(text, '\trcu_read_lock();',
            '\tif (!source || addr->sa_family != AF_INET)\n\t\treturn -EOPNOTSUPP;\n\trcu_read_lock();')
        return replace(text, 'cipso_v4_sock_setattr(sk,\n\t\t\t\t\t\t\tentry->cipso, secattr,\n\t\t\t\t\t\t\tnetlbl_sk_lock_check(sk))',
            'lsf_prepaid_cipso_sock_setattr(sk,\n\t\t\t\t\t\t\tentry->cipso, secattr,\n\t\t\t\t\t\t\tnetlbl_sk_lock_check(sk), source)')
    if name == 'cipso_v4_sock_setattr':
        text = replace(text, 'kmalloc(buf_len, GFP_ATOMIC)',
            'lsf_factory_child_allocate(*source, buf_len, LSF_PREPAID_CIPSO_BUFFER)')
        text = replace(text, 'kzalloc(sizeof(*opt) + opt_len, GFP_ATOMIC)',
            'lsf_factory_child_allocate(*source, sizeof(*opt) + opt_len, LSF_PREPAID_IP_OPTIONS)')
        text = replace(text, '\tkfree(buf);', '\tlsf_prepaid_cipso_buffer_return(buf);', 2)
        text = replace(text, '\tkfree(opt);', '\tlsf_prepaid_options_failed_return(opt);')
        text = replace(text, '\told = rcu_dereference_protected(sk_inet->inet_opt, sk_locked);',
            '\told = rcu_dereference_protected(sk_inet->inet_opt, sk_locked);\n'
            '\tif ((old && !lsf_factory_options_owned(old, *source)) ||\n'
            '\t    lsf_factory_options_publish(opt) != 1) {\n\t\tret_val = -EOPNOTSUPP;\n'
            '\t\tgoto socket_setattr_failure;\n\t}')
        return replace(text, '\tif (old)\n\t\tkfree_rcu(old, rcu);',
            '\tif (old && !lsf_prepaid_options_retire(old))\n\t\tkfree_rcu(old, rcu);')
    require(False, 'private-name')


def observed(original, name):
    require(section(original, name) == original, 'observed-preimage')
    if name in ('selinux_netlbl_sock_genattr', 'netlbl_sock_setattr', 'netlbl_conn_setattr'):
        anchor = {
            'selinux_netlbl_sock_genattr': '\tstruct netlbl_lsm_secattr *secattr;\n',
            'netlbl_sock_setattr': '\tstruct netlbl_dom_map *dom_entry;\n',
            'netlbl_conn_setattr': '\tstruct netlbl_dommap_def *entry;\n',
        }[name]
        error = 'ERR_PTR(owned)' if name == 'selinux_netlbl_sock_genattr' else 'owned'
        args = {
            'selinux_netlbl_sock_genattr': 'sk, &source',
            'netlbl_sock_setattr': 'sk, family, secattr, sk_locked, &source',
            'netlbl_conn_setattr': 'sk, addr, secattr, &source',
        }[name]
        guard = ('#ifdef CONFIG_LSF_STREAM_FACTORY\n\t{\n\t\tstruct lsf_factory_blob source;\n'
            '\t\tint owned = lsf_prepaid_netlabel_source(sk, &source);\n'
            '\t\tif (owned < 0)\n\t\t\treturn '+error+';\n'
            '\t\tif (owned)\n\t\t\treturn '+RENAMES[name]+'('+args+');\n\t}\n#endif\n')
        return replace(original, anchor, anchor + guard)
    if name == 'netlbl_catmap_free':
        return replace(original, '\t\tkfree(iter);',
            '#ifdef CONFIG_LSF_STREAM_FACTORY\n\t\tif (!lsf_prepaid_label_catmap_return(iter))\n#endif\n\t\t\tkfree(iter);')
    if name == 'netlbl_secattr_destroy':
        return replace(original, '\tif (secattr->flags & NETLBL_SECATTR_FREE_DOMAIN)\n\t\tkfree(secattr->domain);',
            '\tif ((secattr->flags & NETLBL_SECATTR_FREE_DOMAIN)\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\t    && !lsf_prepaid_label_domain_return(secattr->domain)\n#endif\n'
            '\t   )\n\t\tkfree(secattr->domain);')
    if name == 'netlbl_secattr_free':
        return replace(original, '\tnetlbl_secattr_destroy(secattr);',
            '#ifdef CONFIG_LSF_STREAM_FACTORY\n\tif (lsf_prepaid_label_secattr_return(secattr))\n\t\treturn;\n#endif\n'
            '\tnetlbl_secattr_destroy(secattr);')
    if name == 'cipso_v4_delopt':
        return replace(original, '\t\tkfree_rcu(opt, rcu);',
            '#ifdef CONFIG_LSF_STREAM_FACTORY\n\t\tif (!lsf_prepaid_options_retire(opt))\n#endif\n\t\t\tkfree_rcu(opt, rcu);')
    if name == 'inet_sock_destruct':
        return replace(original, '\tkfree_rcu(rcu_dereference_protected(inet->inet_opt, 1), rcu);',
            '\t{\n\t\tstruct ip_options_rcu *options = rcu_dereference_protected(inet->inet_opt, 1);\n'
            '#ifdef CONFIG_LSF_STREAM_FACTORY\n\t\tif (!lsf_prepaid_options_retire(options))\n#endif\n'
            '\t\t\tkfree_rcu(options, rcu);\n\t}')
    require(False, 'observed-name')


def authenticate(inputs):
    value = fixture()
    require(set(inputs) == set(value['source']), 'whole-source-membership')
    for name, row in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == row['bytes'] <= maintained.MAX_FILE and
            hashlib.sha256(raw).hexdigest() == row['sha256'] and
            hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == row['gitBlob'],
            'whole-source-preimage')
    require(sum(map(len, inputs.values())) <= maintained.MAX_SELECTED, 'whole-source-envelope')
    for name, row in value['sections'].items():
        section(inputs[row['source']].decode(), name)


def derive(inputs):
    authenticate(inputs)
    original = {name: raw.decode() for name, raw in inputs.items()}
    # The already reviewed original protocol recipe authenticates its own six
    # whole preimages. Its actual source outputs remain the starting point.
    outputs = protocol.derive({name: inputs[name] for name in protocol.SOURCES})
    for name in inputs:
        outputs.setdefault(name, inputs[name])
    texts = {name: raw.decode() for name, raw in outputs.items() if name in inputs}
    value = fixture()
    for name in ('selinux_netlbl_sock_genattr', 'netlbl_sock_setattr', 'netlbl_conn_setattr',
                 'netlbl_catmap_free', 'netlbl_secattr_destroy', 'netlbl_secattr_free',
                 'cipso_v4_delopt', 'inet_sock_destruct'):
        source = value['sections'][name]['source']
        raw = section(original[source], name)
        texts[source] = replace(texts[source], raw, observed(raw, name))
    header = '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_netlabel_private.h>\n#endif\n'
    # Inline normal Netlabel frees only need the narrow return declarations,
    # never the private factory structure in every ordinary translation unit.
    name = 'include/net/netlabel.h'
    texts[name] = replace(texts[name], '#include <linux/refcount.h>\n', '#include <linux/refcount.h>\n' + header)
    grouped = {}
    for name in RENAMES:
        grouped.setdefault(value['sections'][name]['source'], []).append(name)
    for source, names in grouped.items():
        include = ('../../../net/factory-private.h' if '/selinux/ss/' in source else
                   '../../net/factory-private.h' if '/selinux/' in source else '../factory-private.h')
        guard = '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "'+include+'"\n#include <net/lsf_stream_netlabel_private.h>\n#endif\n'
        # Insertion before definitions, after original includes. No original
        # include is removed and no configured security hook is changed.
        texts[source] = replace(texts[source], '#include <net/netlabel.h>\n',
                                '#include <net/netlabel.h>\n' + guard)
        additions = ''.join(private(section(original[source], name), name) for name in names)
        texts[source] += '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' + additions + '#endif\n'
    source = 'net/ipv4/af_inet.c'
    texts[source] = replace(texts[source], '#include <net/sock.h>\n', '#include <net/sock.h>\n' + header)
    # Required helper definitions are in the SAME Netlabel translation unit;
    # no new initializer, module registrar or selectable factory is installed.
    texts['net/netlabel/netlabel_kapi.c'] += '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "lsf_netlabel_private.c"\n#endif\n'
    outputs.update({name: text.encode() for name, text in texts.items()})
    outputs['include/net/lsf_stream_netlabel_private.h'] = (protocol.OWNED/'netlabel-private.h').read_bytes()
    outputs['net/netlabel/lsf_netlabel_private.c'] = (protocol.OWNED/'netlabel-private.c').read_bytes()
    return outputs


def reference_body():
    """Exact selected producers/destructors with explicit serialized doubles."""
    value = fixture()
    original = lambda name: section(value['sections'][name]['text'], name)
    body = ''.join(observed(original(name), name) for name in
                   ('netlbl_catmap_free', 'netlbl_secattr_destroy', 'netlbl_secattr_free'))
    body += '#ifdef LSF_OLD_NETLABEL\n' + original('selinux_netlbl_sock_genattr')
    body += '#else\n' + private(original('selinux_netlbl_sock_genattr'), 'selinux_netlbl_sock_genattr') + '#endif\n'
    helper = (protocol.OWNED / 'netlabel-private.c').read_text()
    for include in ('#include "../factory-private.h"\n',
                    '#include <net/lsf_stream_netlabel_private.h>\n',
                    '#include <net/ip.h>\n', '#include <net/sock.h>\n'):
        helper = replace(helper, include, '')
    factory = (protocol.OWNED / 'factory.c').read_text()
    selected = ''
    for name, prefix in (('lsf_factory_child_allocate', 'void *'),
                         ('lsf_factory_protocol_parent', 'int '),
                         ('lsf_factory_options_publish', 'int '),
                         ('lsf_factory_options_owned', 'int '),
                         ('lsf_factory_options_queue', 'int ')):
        start = prefix + name + '('
        require(factory.count(start) == 1, 'owned-reference-definition')
        begin = factory.index(start)
        end = factory.index('\n}\n', begin) + 3
        selected += factory[begin:end]
    return (selected + body + helper).encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    value = fixture()
    inputs = {name: paths.read(args.source_dir, name, maintained.MAX_FILE) for name in value['source']}
    outputs = derive(inputs)
    paths.new_directory(args.output)
    for name, raw in outputs.items():
        target = args.output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        paths.write_new(target, raw)
    record = {'schemaVersion': 'lsf.kernel-maintained-netlabel.v1', 'upstreamCommit': maintained.COMMIT,
        'archiveSha256': value['archiveSha256'],
        'originals': {name: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                      for name, raw in inputs.items()},
        'derived': {name: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                    for name, raw in outputs.items()},
        'ordinaryAllocatorPreserved': True, 'securityChecksPreserved': True,
        'kernelBuilt': False, 'actualLsmExecuted': False, 'actualRcuExecuted': False,
        'trustedFactoryInstalled': False, 'completeAllocationClosure': False,
        'finalFreeCertified': False, 'productionInstallation': False}
    paths.write_new(args.output / 'derivation.json', (json.dumps(record, indent=2)+'\n').encode())
    print(json.dumps(record))


if __name__ == '__main__':
    main()
