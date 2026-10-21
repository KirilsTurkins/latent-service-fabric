"""Exact maintained IPv4 route producers; uninstalled bounded source only."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import host_stream_kernel_bind as bind
from tools.dev_workflow import paths

OWNED = bind.OWNED
FIXTURE = Path(__file__).parent/'tests/fixtures/host_stream_kernel_route.json'
ROUTE = 'net/ipv4/route.c'
DST = 'net/core/dst.c'
HEADER = 'include/net/route.h'
CLONES = ('rt_dst_alloc','__mkroute_output','ip_route_output_key_hash_rcu','ip_route_output_key_hash')
OBSERVED = ('rt_dst_clone','ip_route_output_flow','ip_route_connect','dst_release','dst_destroy')
UNMODIFIED = ('ip_route_newports','dst_init','dst_alloc','dst_release_immediate','dst_destroy_rcu',
    'rt_bind_exception','rt_cache_route','rt_set_nexthop','ipv4_dst_destroy','ipv4_cow_metrics',
    'find_exception','rt_fibinfo_free','rt_fibinfo_free_cpus','fib_nh_common_release',
    'ip_dst_init_metrics','ip_dst_metrics_put','ip_fib_metrics_put',
    'xfrm_lookup_with_ifid','xfrm_lookup_route')
NAMES = {'rt_dst_alloc':'lsf_prepaid_route_alloc_owned',
    '__mkroute_output':'lsf_prepaid_mkroute_output_owned',
    'ip_route_output_key_hash_rcu':'lsf_prepaid_route_key_hash_rcu_owned',
    'ip_route_output_key_hash':'lsf_prepaid_route_key_hash_owned'}


def require(value, reason):
    if not value:raise ValueError('kernel-route-'+reason)


def fixture():
    value = json.loads(FIXTURE.read_bytes())
    require(value['upstreamCommit'] == bind.avc.maintained.COMMIT and
        value['archiveSha256'] == bind.fixture()['archiveSha256'], 'maintained-identity')
    require(set(value['sections']) == set(CLONES)|set(OBSERVED)|set(UNMODIFIED), 'definition-membership')
    require(set(bind.fixture()['source']) < set(value['source']) and
        all(value['source'][n] == row for n,row in bind.fixture()['source'].items()), 'prefix-membership')
    require(value['kernelBuilt'] is value['actualRouteOrXfrmExecuted'] is value['actualLinuxRcuExecuted'] is
        value['completeAllocationClosure'] is value['finalFreeCertified'] is value['productionInstallation'] is False,
        'uninstalled-only')
    return value


def section(text, name):
    rows = fixture()['sections'];require(name in rows, 'definition-name')
    row = rows[name];prefix = row['prefix']
    starts = [i for i in range(len(text)) if text.startswith(prefix,i) and (not i or text[i-1]=='\n')]
    require(len(starts)==1, 'definition-occurrence')
    end = text.find('\n}\n',starts[0]);require(end>=0, 'definition-end')
    raw = text[starts[0]:end+3]
    require(raw == row['text'] and len(raw.encode()) == row['bytes'] and
        hashlib.sha256(raw.encode()).hexdigest()==row['sha256'], 'definition-preimage')
    return raw


def replace(text, old, new, count=1):
    require(text.count(old)==count, 'replacement-preimage')
    return text.replace(old,new)


def guard(body):return '#ifdef LSF_STREAM_ROUTE_SOURCE\n'+body+'#endif\n'


def alternate(original, selected):return guard(selected+'#else\n'+original)


def private(raw, name):
    require(name in CLONES and section(raw,name)==raw, 'private-preimage')
    declaration,body = raw.split('\n{\n',1)
    declaration = replace(declaration,name+'(',NAMES[name]+'(')
    if not declaration.startswith('static '):declaration = 'static '+declaration
    declaration = declaration[:-1]+', const struct lsf_factory_blob *source)'
    if name == 'rt_dst_alloc':
        body = replace(body,'dst_alloc(&ipv4_dst_ops, dev, DST_OBSOLETE_FORCE_CHK,\n\t\t       (noxfrm ? DST_NOXFRM : 0))',
            'lsf_prepaid_route_allocate(dev, (noxfrm ? DST_NOXFRM : 0), source)')
    elif name == '__mkroute_output':
        anchor = '\t\tstruct fib_nh_common *nhc = FIB_RES_NHC(*res);\n'
        body = replace(body,anchor,anchor+
            '\t\t/* No unclosed LWT producer is entered by this private prefix. */\n'
            '\t\tif (nhc->nhc_lwtstate)\n\t\t\treturn ERR_PTR(-EOPNOTSUPP);\n')
        body = replace(body,'rt_dst_alloc(dev_out, flags, type,\n\t\t\t   IN_DEV_ORCONF(in_dev, NOXFRM))',
            NAMES['rt_dst_alloc']+'(dev_out, flags, type,\n\t\t\t   IN_DEV_ORCONF(in_dev, NOXFRM), source)')
    elif name == 'ip_route_output_key_hash_rcu':
        body = replace(body,'__mkroute_output(res, fl4, orig_oif, dev_out, flags)',
            NAMES['__mkroute_output']+'(res, fl4, orig_oif, dev_out, flags, source)')
    else:
        body = replace(body,'ip_route_output_key_hash_rcu(net, fl4, &res, skb)',
            NAMES['ip_route_output_key_hash_rcu']+'(net, fl4, &res, skb, source)')
    return declaration+'\n{\n'+body


def observed(raw, name):
    require(name in OBSERVED and section(raw,name)==raw, 'observed-preimage')
    if name == 'rt_dst_clone':
        old = '\tnew_rt = dst_alloc(&ipv4_dst_ops, dev, DST_OBSOLETE_FORCE_CHK,\n\t\t\t   rt->dst.flags);\n'
        return replace(raw,old,alternate(old,'\tnew_rt = lsf_prepaid_route_clone_allocate(dev, rt);\n'))
    if name == 'ip_route_output_flow':
        old = '\tstruct rtable *rt = __ip_route_output_key(net, flp4);\n'
        text = replace(raw,old,alternate(old,'\tstruct rtable *rt = lsf_prepaid_route_key(net, flp4, sk);\n'))
        old = '\t\trt = dst_rtable(xfrm_lookup_route(net, &rt->dst,\n\t\t\t\t\t\t  flowi4_to_flowi(flp4),\n\t\t\t\t\t\t  sk, 0));\n'
        return replace(text,old,alternate(old,'\t\trt = lsf_prepaid_route_xfrm(net, rt, flp4, sk);\n'))
    if name == 'ip_route_connect':
        old = '\t\trt = __ip_route_output_key(net, fl4);\n'
        return replace(raw,old,alternate(old,'\t\trt = lsf_prepaid_route_key(net, fl4, sk);\n'))
    if name == 'dst_release':
        old = '\t\tcall_rcu_hurry(&dst->rcu_head, dst_destroy_rcu);\n'
        return replace(raw,old,guard('\t\t/* Queue only after the real final rcuref_put. */\n'
            '\t\tlsf_factory_route_queue(dst);\n')+old)
    old = '\t\tkmem_cache_free(dst->ops->kmem_cachep, dst);\n'
    return replace(raw,old,guard('\t\tif (lsf_factory_route_return(dst) == 0)\n')+old)


def authenticate(inputs):
    value = fixture();require(set(inputs)==set(value['source']), 'whole-source-membership')
    for name,row in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw)==row['bytes']<=bind.avc.maintained.MAX_FILE and
            hashlib.sha256(raw).hexdigest()==row['sha256'] and
            hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==row['gitBlob'],
            'whole-source-preimage')
    require(sum(map(len,inputs.values()))<=bind.avc.maintained.MAX_SELECTED, 'whole-source-envelope')
    for name,row in value['sections'].items():section(inputs[row['source']].decode(),name)


def derive(inputs):
    authenticate(inputs)
    outputs = bind.derive({n:inputs[n] for n in bind.fixture()['source']})
    for name in set(inputs)-set(bind.fixture()['source']):outputs[name] = inputs[name]
    for path in (ROUTE,DST,HEADER):
        original = inputs[path].decode();text = original
        for name in OBSERVED:
            if fixture()['sections'][name]['source']==path:
                raw = section(original,name);text = replace(text,raw,observed(raw,name))
        includes = '#ifdef CONFIG_LSF_STREAM_FACTORY\n#define LSF_STREAM_ROUTE_SOURCE 1\n'
        includes += '#include <net/lsf_stream_route_private.h>\n'
        if path != HEADER:includes += '#include "../factory-private.h"\n'
        if path == ROUTE:
            includes += '#include <net/lsf_stream_netlabel_private.h>\n'
            includes += ('static void *lsf_prepaid_route_allocate(struct net_device *, unsigned short, const struct lsf_factory_blob *);\n'
                'static void *lsf_prepaid_route_clone_allocate(struct net_device *, struct rtable *);\n')
            for name in CLONES:includes += private(section(original,name),name).split('\n{\n',1)[0]+';\n'
        includes += '#endif\n'
        anchor = {'net/ipv4/route.c':'#include "fib_lookup.h"\n',
            'net/core/dst.c':'#include <net/dst_metadata.h>\n',
            'include/net/route.h':'#include <linux/security.h>\n'}[path]
        text = replace(text,anchor,anchor+includes)
        if path == ROUTE:
            text += '\n#ifdef LSF_STREAM_ROUTE_SOURCE\n'
            for name in CLONES:text += private(section(original,name),name)
            text += '#include "lsf_route_private.c"\n#endif\n'
        outputs[path] = text.encode()
    outputs['include/net/lsf_stream_route_private.h'] = (OWNED/'route-private.h').read_bytes()
    outputs['net/ipv4/lsf_route_private.c'] = (OWNED/'route-private.c').read_bytes()
    return outputs


def reference_body():
    factory = (OWNED/'factory.c').read_text();body = ''
    for name,prefix in (('lsf_factory_context_current','static struct lsf_factory_context *'),
        ('lsf_factory_child_allocate','void *'),('lsf_factory_protocol_parent','int '),
        ('lsf_factory_blob_lookup_locked','static int '),('lsf_factory_blob_lookup','int '),
        ('lsf_factory_route_queue','int '),('lsf_factory_route_return','int '),('lsf_factory_poison','void ')):
        start = prefix+name+'(';require(factory.count(start)==1, 'reference-factory-definition')
        begin = factory.index(start);end = factory.index('\n}\n',begin)+3;body += factory[begin:end]
    label = (OWNED/'netlabel-private.c').read_text();begin = label.index('int lsf_prepaid_netlabel_source(')
    body += label[begin:label.index('\n}\n',begin)+3]
    # Real initialization, destructor and both original release algorithms are
    # executed with explicitly serialized type/refcount/RCU doubles.
    for name in ('dst_init','dst_alloc'):body += fixture()['sections'][name]['text']
    body += private(fixture()['sections']['rt_dst_alloc']['text'],'rt_dst_alloc')
    body += (OWNED/'route-private.c').read_text()
    body += observed(fixture()['sections']['rt_dst_clone']['text'],'rt_dst_clone')
    for name in ('dst_destroy','dst_release','dst_release_immediate'):
        raw = fixture()['sections'][name]['text']
        body += observed(raw,name) if name in OBSERVED else raw
    body += fixture()['sections']['dst_destroy_rcu']['text']
    return body.encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args();value = fixture()
    inputs = {n:paths.read(args.source_dir,n,bind.avc.maintained.MAX_FILE) for n in value['source']}
    outputs = derive(inputs);paths.new_directory(args.output)
    for name,raw in outputs.items():
        target = args.output/name;target.parent.mkdir(parents=True,exist_ok=True);paths.write_new(target,raw)
    identity = lambda raw:{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    record = {'schemaVersion':'lsf.kernel-maintained-route.v1','upstreamCommit':bind.avc.maintained.COMMIT,
        'archiveSha256':value['archiveSha256'],'originals':{n:identity(r) for n,r in inputs.items()},
        'derived':{n:identity(r) for n,r in outputs.items()},'kernelBuilt':False,
        'actualRouteOrXfrmExecuted':False,'actualLinuxRcuExecuted':False,'completeAllocationClosure':False,
        'finalFreeCertified':False,'productionInstallation':False}
    paths.write_new(args.output/'derivation.json',(json.dumps(record,indent=2)+'\n').encode())
    print(json.dumps({'sources':len(inputs),'definitions':len(value['sections']),
        'derived':len(outputs),'kernelBuilt':False}))


if __name__ == '__main__':main()
