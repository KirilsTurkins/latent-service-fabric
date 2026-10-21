"""Closed maintained bind-bucket producers and their original final returns."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.dev_workflow import paths
from tools import host_stream_kernel_avc as avc
from tools import host_stream_kernel_audit as audit

OWNED = avc.OWNED
FIXTURE = Path(__file__).parent/'tests/fixtures/host_stream_kernel_bind.json'
HASH = 'net/ipv4/inet_hashtables.c'
CSK = 'net/ipv4/inet_connection_sock.c'
TW = 'net/ipv4/inet_timewait_sock.c'
HEADER = 'include/net/inet_hashtables.h'
OBSERVED = ('inet_bind_bucket_destroy', 'inet_bind2_bucket_create',
    'inet_bind2_bucket_destroy', '__inet_hash_connect', '__inet_bhash2_update_saddr',
    '__inet_inherit_port', 'inet_csk_get_port')
UNMODIFIED = ('inet_bind_bucket_create', 'inet_bind2_bucket_init', '__inet_put_port',
    'inet_twsk_bind_unhash', 'inet_twsk_kill')


def require(value, reason):
    if not value:
        raise ValueError('kernel-bind-'+reason)


def fixture():
    value = json.loads(FIXTURE.read_bytes())
    require(value['upstreamCommit'] == avc.maintained.COMMIT and
        value['archiveSha256'] == avc.fixture()['archiveSha256'], 'maintained-source')
    require(set(value['source']) == set(audit.fixture()['source']) | {HASH, CSK, TW, HEADER},
        'whole-source-membership')
    require(set(value['sections']) == set(OBSERVED) | set(UNMODIFIED), 'definition-membership')
    require(value['kernelBuilt'] is value['actualKernelExecuted'] is
        value['completeAllocationClosure'] is value['finalFreeCertified'] is
        value['productionInstallation'] is False, 'uninstalled-only')
    return value


def section(text, name):
    rows = fixture()['sections'];require(name in rows, 'definition-name')
    row = rows[name];prefix = row['prefix']
    starts = [i for i in range(len(text)) if text.startswith(prefix, i) and (not i or text[i-1]=='\n')]
    require(len(starts) == 1, 'definition-occurrence')
    stop = text.find('\n}\n', starts[0]);require(stop >= 0, 'definition-end')
    raw = text[starts[0]:stop+3]
    require(len(raw.encode()) == row['bytes'] and
        hashlib.sha256(raw.encode()).hexdigest() == row['sha256'] and raw == row['text'],
        'definition-preimage')
    return raw


def replace(text, old, new, count=1):
    require(text.count(old) == count, 'replacement-preimage')
    return text.replace(old, new)


def guard(new):
    return '#ifdef LSF_STREAM_BIND_SOURCE\n'+new+'#endif\n'


def alternate(original, selected):
    return guard(selected+'#else\n'+original)


def observed(original, name):
    require(section(original, name) == original and name in OBSERVED, 'observed-preimage')
    if name in ('inet_bind_bucket_destroy', 'inet_bind2_bucket_destroy'):
        kind = 'BIND_BUCKET' if name == 'inet_bind_bucket_destroy' else 'BIND2_BUCKET'
        return replace(original, '\t\tkmem_cache_free(cachep, tb);',
            guard('\t\tif (lsf_prepaid_bind_return(tb, LSF_PREPAID_'+kind+'))\n\t\t\treturn;\n')+
            '\t\tkmem_cache_free(cachep, tb);')
    if name == 'inet_bind2_bucket_create':
        raw = '\tstruct inet_bind2_bucket *tb2 = kmem_cache_alloc(cachep, GFP_ATOMIC);\n'
        return replace(original, raw, alternate(raw,
            '\tstruct inet_bind2_bucket *tb2 = lsf_prepaid_bind2_allocate(cachep, net, sk);\n'))
    if name == '__inet_inherit_port':
        # This private factory creates outbound sockets, not listening parents.
        # Reject an owned participant before locks/cache lookup/allocation;
        # never infer the accepted child's ownership from a listener address.
        anchor = '\tint bhash, l3mdev;\n'
        return replace(original, anchor, anchor+guard(
            '\tif (lsf_prepaid_bind_owned(sk) != 0 || lsf_prepaid_bind_owned(child) != 0)\n'
            '\t\treturn -EOPNOTSUPP;\n'))
    anchor = {'__inet_hash_connect':'\tu32 index;\n',
        '__inet_bhash2_update_saddr':'\tint bhash;\n',
        'inet_csk_get_port':'\tstruct net *net = sock_net(sk);\n'}[name]
    text = replace(original, anchor, anchor+guard(
        '\tint lsf_error = lsf_prepaid_bind_check(sk);\n'
        '\tif (lsf_error)\n\t\treturn lsf_error;\n'))
    if name == '__inet_bhash2_update_saddr':
        raw = '\tnew_tb2 = kmem_cache_alloc(hinfo->bind2_bucket_cachep, GFP_ATOMIC);\n'
        text = replace(text, raw, alternate(raw,
            '\tnew_tb2 = lsf_prepaid_bind2_allocate(hinfo->bind2_bucket_cachep, net, sk);\n'))
        raw = '\tif (tb2 != new_tb2)\n\t\tkmem_cache_free(hinfo->bind2_bucket_cachep, new_tb2);\n'
        return replace(text, raw, alternate(raw,
            '\tif (tb2 != new_tb2 &&\n'
            '\t    !lsf_prepaid_bind_return(new_tb2, LSF_PREPAID_BIND2_BUCKET))\n'
            '\t\tkmem_cache_free(hinfo->bind2_bucket_cachep, new_tb2);\n'))
    raw = ('\t\ttb = inet_bind_bucket_create(hinfo->bind_bucket_cachep,\n'
        '\t\t\t\t\t     net, head, port, l3mdev);\n') if name == '__inet_hash_connect' else (
        '\t\ttb = inet_bind_bucket_create(hinfo->bind_bucket_cachep, net,\n'
        '\t\t\t\t\t     head, port, l3mdev);\n')
    return replace(text, raw, alternate(raw,
        '\t\ttb = lsf_prepaid_bind_bucket_create(hinfo->bind_bucket_cachep,\n'
        '\t\t\t\t\t     net, head, port, l3mdev, sk);\n'))


def private(original):
    require(section(original, 'inet_bind_bucket_create') == original, 'private-preimage')
    declaration, body = original.split('\n{\n', 1)
    declaration = 'static '+replace(declaration, 'inet_bind_bucket_create(',
        'lsf_prepaid_bind_bucket_create_owned(')
    declaration = declaration[:-1]+', const struct lsf_factory_blob *source)'
    body = replace(body, 'struct inet_bind_bucket *tb = kmem_cache_alloc(cachep, GFP_ATOMIC);',
        'struct inet_bind_bucket *tb = lsf_factory_child_allocate(*source,\n'
        '\t\tsizeof(struct inet_bind_bucket), LSF_PREPAID_BIND_BUCKET);\n\t(void)cachep;')
    return declaration+'\n{\n'+body


def authenticate(inputs):
    value = fixture();require(set(inputs) == set(value['source']), 'whole-source-membership')
    for name, row in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == row['bytes'] <= avc.maintained.MAX_FILE and
            hashlib.sha256(raw).hexdigest() == row['sha256'] and
            hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == row['gitBlob'],
            'whole-source-preimage')
    require(sum(map(len, inputs.values())) <= avc.maintained.MAX_SELECTED, 'whole-source-envelope')
    for name, row in value['sections'].items():
        section(inputs[row['source']].decode(), name)


def derive(inputs):
    authenticate(inputs)
    outputs = audit.derive({name:inputs[name] for name in audit.fixture()['source']})
    for path in (HASH, CSK):
        original = inputs[path].decode();text = original
        for name in OBSERVED:
            if fixture()['sections'][name]['source'] == path:
                raw = section(original, name);text = replace(text, raw, observed(raw, name))
        includes = '#ifdef CONFIG_LSF_STREAM_FACTORY\n#define LSF_STREAM_BIND_SOURCE 1\n'
        includes += '#include <net/lsf_stream_bind_private.h>\n'
        if path == HASH:
            includes += '#include "../factory-private.h"\n#include <net/lsf_stream_netlabel_private.h>\n'
        includes += '#endif\n'
        text = replace(text, '#include <net/inet_hashtables.h>\n',
            '#include <net/inet_hashtables.h>\n'+includes)
        if path == HASH:
            text += '\n#ifdef LSF_STREAM_BIND_SOURCE\n'+private(section(original, 'inet_bind_bucket_create'))
            text += '#include "lsf_bind_private.c"\n#endif\n'
        outputs[path] = text.encode()
    for path in (TW, HEADER):outputs[path] = inputs[path]
    outputs['include/net/lsf_stream_bind_private.h'] = (OWNED/'bind-private.h').read_bytes()
    outputs['net/ipv4/lsf_bind_private.c'] = (OWNED/'bind-private.c').read_bytes()
    return outputs


def reference_body():
    value = fixture();factory = (OWNED/'factory.c').read_text();body = ''
    for name, prefix in (('lsf_factory_context_current','static struct lsf_factory_context *'),
        ('lsf_factory_child_allocate','void *'),('lsf_factory_protocol_parent','int '),
        ('lsf_factory_blob_lookup_locked','static int '),('lsf_factory_blob_lookup','int '),
        ('lsf_factory_blob_finish','int '),('lsf_factory_poison','void ')):
        start = prefix+name+'(';require(factory.count(start)==1,'reference-factory-definition')
        begin = factory.index(start);end = factory.index('\n}\n',begin)+3
        body += factory[begin:end]
    label = (OWNED/'netlabel-private.c').read_text()
    start = label.index('int lsf_prepaid_netlabel_source(')
    body += label[start:label.index('\n}\n',start)+3]
    for name in ('inet_bind_bucket_create','inet_bind2_bucket_init'):
        body += value['sections'][name]['text']
    body += private(value['sections']['inet_bind_bucket_create']['text'])
    body += (OWNED/'bind-private.c').read_text()
    for name in ('inet_bind2_bucket_create','inet_bind_bucket_destroy','inet_bind2_bucket_destroy'):
        body += observed(value['sections'][name]['text'],name)
    return body.encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args();value = fixture()
    inputs = {name:paths.read(args.source_dir,name,avc.maintained.MAX_FILE) for name in value['source']}
    outputs = derive(inputs);paths.new_directory(args.output)
    for name, raw in outputs.items():
        target = args.output/name;target.parent.mkdir(parents=True,exist_ok=True);paths.write_new(target,raw)
    identity = lambda raw:{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    record = {'schemaVersion':'lsf.kernel-maintained-bind.v1','upstreamCommit':avc.maintained.COMMIT,
        'archiveSha256':value['archiveSha256'],'originals':{n:identity(r) for n,r in inputs.items()},
        'derived':{n:identity(r) for n,r in outputs.items()},'kernelBuilt':False,
        'actualKernelExecuted':False,'actualPortOrTimewaitExecuted':False,
        'completeAllocationClosure':False,'finalFreeCertified':False,'productionInstallation':False}
    paths.write_new(args.output/'derivation.json',(json.dumps(record,indent=2)+'\n').encode())
    print(json.dumps({'sources':len(inputs),'definitions':len(value['sections']),
        'derived':len(outputs),'kernelBuilt':False}))


if __name__ == '__main__':main()
