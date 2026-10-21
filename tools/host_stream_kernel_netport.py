"""Closed maintained Netport allocation/RCU derivation; uninstalled only."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.dev_workflow import paths
from tools import host_stream_kernel_netlabel as netlabel
from tools import host_stream_kernel_protocol as protocol
from tools import host_stream_kernel_maintained as maintained

FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_netport.json'
PORT = 'security/selinux/netport.c'
HOOKS = 'security/selinux/hooks.c'
NAMES = frozenset(('sel_netport_hashfn', 'sel_netport_find', 'sel_netport_insert', 'sel_netport_sid_slow', 'sel_netport_sid',
    'sel_netport_flush', 'selinux_socket_connect_helper', 'security_port_sid', 'ocontext_to_sid'))


def require(value, reason):
    if not value:
        raise ValueError('kernel-netport-' + reason)


def fixture():
    value = json.loads(FIXTURE.read_bytes())
    require(value['upstreamCommit'] == maintained.COMMIT and set(value['sections']) == NAMES,
            'maintained-definition-membership')
    require(value['archiveSha256'] == maintained.manifest()['archive']['sha256'], 'archive-identity')
    require(all(row['source'] in value['source'] for row in value['sections'].values()), 'section-whole-source')
    require(value['kernelBuilt'] is value['actualLsmExecuted'] is value['completeAllocationClosure']
            is value['productionInstallation'] is False, 'uninstalled-only')
    return value


def section(text, name):
    rows = fixture()['sections']
    require(name in rows, 'section-name')
    prefix = rows[name]['prefix']
    starts = [i for i in range(len(text)) if text.startswith(prefix, i) and (not i or text[i-1] == '\n')]
    require(len(starts) == 1, 'section-occurrence')
    stop = text.find('\n}\n', starts[0]); require(stop >= 0, 'section-end')
    raw = text[starts[0]:stop+3]
    require(hashlib.sha256(raw.encode()).hexdigest() == rows[name]['sha256'], 'section-preimage')
    return raw


def replace(text, old, new, count=1):
    require(text.count(old) == count, 'closed-replacement-preimage')
    return text.replace(old, new)


def observed(original, name):
    require(section(original, name) == original, 'observed-preimage')
    if name == 'sel_netport_insert':
        return replace(original, '\t\tkfree_rcu(tail, rcu);',
            '#ifdef CONFIG_LSF_STREAM_FACTORY\n\t\tif (!lsf_prepaid_netport_retire(tail))\n#endif\n'
            '\t\t\tkfree_rcu(tail, rcu);')
    if name == 'sel_netport_flush':
        return replace(original, '\t\t\tkfree_rcu(port, rcu);',
            '#ifdef CONFIG_LSF_STREAM_FACTORY\n\t\t\tif (!lsf_prepaid_netport_retire(port))\n#endif\n'
            '\t\t\t\tkfree_rcu(port, rcu);')
    if name == 'selinux_socket_connect_helper':
        text = replace(original, '\tint err;\n', '\tint err;\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\tstruct lsf_factory_blob source;\n'
            '\tint owned = lsf_prepaid_netlabel_source(sk, &source);\n'
            '\tif (owned < 0)\n\t\treturn owned;\n#endif\n')
        return replace(text, '\t\terr = sel_netport_sid(sk->sk_protocol, snum, &sid);',
            '#ifdef CONFIG_LSF_STREAM_FACTORY\n\t\tif (owned)\n'
            '\t\t\terr = lsf_prepaid_netport_sid(sk->sk_protocol, snum, &sid, &source);\n'
            '\t\telse\n#endif\n\t\t\terr = sel_netport_sid(sk->sk_protocol, snum, &sid);')
    require(False, 'observed-name')


def private(original, name):
    require(section(original, name) == original, 'private-preimage')
    if name == 'sel_netport_insert':
        text = observed(original, name)
        text = replace(text, 'static void sel_netport_insert(', 'static int lsf_prepaid_netport_insert(')
        text = replace(text, '\tlist_add_rcu(&port->list, &sel_netport_hash[idx].list);',
            '\tif (lsf_factory_netport_publish(port, idx) != 1)\n\t\treturn -EOPNOTSUPP;\n'
            '\tlist_add_rcu(&port->list, &sel_netport_hash[idx].list);')
        return text[:-2] + '\treturn 0;\n}\n'
    require(name in ('sel_netport_sid', 'sel_netport_sid_slow'), 'private-name')
    text = replace(original, name + '(', 'lsf_prepaid_' + name.removeprefix('sel_') + '(')
    text = replace(text, 'u32 *sid)', 'u32 *sid, const struct lsf_factory_blob *source)')
    if name == 'sel_netport_sid_slow':
        text = replace(text, 'new = kzalloc(sizeof(*new), GFP_ATOMIC);',
            'new = lsf_factory_child_allocate(*source, sizeof(*new), LSF_PREPAID_NETPORT);\n'
            '\tif (!new) {\n\t\tret = -ENOMEM;\n\t\tgoto out;\n\t}')
        return replace(text, '\t\tsel_netport_insert(new);',
            '\t\tret = lsf_prepaid_netport_insert(new);')
    text = replace(text, '\trcu_read_lock();',
        '\tif (!source)\n\t\treturn -EOPNOTSUPP;\n\trcu_read_lock();')
    return replace(text, 'return sel_netport_sid_slow(protocol, pnum, sid);',
        'return lsf_prepaid_netport_sid_slow(protocol, pnum, sid, source);')


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
    outputs = netlabel.derive({name: inputs[name] for name in netlabel.fixture()['source']})
    outputs[PORT] = inputs[PORT]
    outputs[HOOKS] = inputs[HOOKS]
    texts = {name: outputs[name].decode() for name in (PORT, HOOKS)}
    value = fixture()
    for name in ('sel_netport_insert', 'sel_netport_flush', 'selinux_socket_connect_helper'):
        source = value['sections'][name]['source']
        raw = section(original[source], name)
        texts[source] = replace(texts[source], raw, observed(raw, name))
    includes = '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "../../net/factory-private.h"\n' \
               '#include <net/lsf_stream_netport_private.h>\n'
    texts[PORT] = replace(texts[PORT], '#include "objsec.h"\n', '#include "objsec.h"\n' + includes +
        'struct sel_netport;\nstatic bool lsf_prepaid_netport_retire(struct sel_netport *);\n#endif\n')
    texts[HOOKS] = replace(texts[HOOKS], '#include <net/netlabel.h>\n',
        '#include <net/netlabel.h>\n' + includes + '#include <net/lsf_stream_netlabel_private.h>\n#endif\n')
    texts[PORT] += '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "lsf_netport_private.c"\n'
    for name in ('sel_netport_insert', 'sel_netport_sid_slow', 'sel_netport_sid'):
        texts[PORT] += private(section(original[PORT], name), name)
    texts[PORT] += '#endif\n'
    outputs.update({name: text.encode() for name, text in texts.items()})
    outputs['include/net/lsf_stream_netport_private.h'] = (protocol.OWNED/'netport-private.h').read_bytes()
    outputs['security/selinux/lsf_netport_private.c'] = (protocol.OWNED/'netport-private.c').read_bytes()
    return outputs


def reference_body():
    value = fixture()
    original = lambda name: section(value['sections'][name]['text'], name)
    factory = (protocol.OWNED/'factory.c').read_text()
    body = ''
    for name, prefix in (('lsf_factory_context_current', 'static struct lsf_factory_context *'),
                         ('lsf_factory_child_allocate', 'void *'),
                         ('lsf_factory_blob_lookup_locked', 'static int '),
                         ('lsf_factory_blob_lookup', 'int '),
                         ('lsf_factory_blob_finish', 'int '),
                         ('lsf_factory_netport_publish', 'int '),
                         ('lsf_factory_netport_queue', 'int '),
                         ('lsf_factory_netport_candidate', 'int '),
                         ('lsf_factory_netport_current', 'int '),
                         ('lsf_factory_poison', 'void ')):
        start = prefix + name + '('
        require(factory.count(start) == 1, 'owned-reference-definition')
        begin = factory.index(start)
        end = factory.index('\n}\n', begin) + 3
        body += factory[begin:end]
    for name in ('sel_netport_hashfn', 'sel_netport_find'):
        body += original(name)
    helper = (protocol.OWNED/'netport-private.c').read_text()
    body += helper + '\n' + observed(original('sel_netport_insert'), 'sel_netport_insert')
    body += observed(original('sel_netport_flush'), 'sel_netport_flush')
    body += '#ifdef LSF_OLD_NETPORT\n' + original('sel_netport_sid_slow')
    body += '#else\n' + private(original('sel_netport_insert'), 'sel_netport_insert')
    body += private(original('sel_netport_sid_slow'), 'sel_netport_sid_slow')
    body += private(original('sel_netport_sid'), 'sel_netport_sid') + '#endif\n'
    return body.encode()


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
    record = {'schemaVersion': 'lsf.kernel-maintained-netport.v1', 'upstreamCommit': maintained.COMMIT,
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
