"""Authenticated private route cache publication, real parent references and drain."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import host_stream_kernel_route as route
from tools.dev_workflow import paths

OWNED=route.OWNED
FIXTURE=Path(__file__).parent/'tests/fixtures/host_stream_kernel_route_cache.json'
CLONES=('rt_cache_route','rt_bind_exception','rt_set_nexthop')
NAMES={n:'lsf_prepaid_'+n for n in CLONES}
require=route.require
replace=route.replace


def fixture():
    v=json.loads(FIXTURE.read_bytes())
    require(v['upstreamCommit']==route.bind.avc.maintained.COMMIT and
        v['archiveSha256']==route.fixture()['archiveSha256'],'cache-maintained-identity')
    require(set(route.fixture()['source'])<set(v['source']) and
        all(v['source'][n]==r for n,r in route.fixture()['source'].items()),'cache-prefix-membership')
    require(all(v[k] is False for k in ('kernelBuilt','actualRouteOrXfrmExecuted','actualLinuxRcuExecuted',
        'completeAllocationClosure','finalFreeCertified','productionInstallation')),'cache-uninstalled')
    return v


def section(text,name):
    row=fixture()['sections'][name];prefix=row['prefix']
    starts=[i for i in range(len(text)) if text.startswith(prefix,i) and (not i or text[i-1]=='\n')]
    require(len(starts)==1,'cache-definition-occurrence')
    end=text.find('\n}\n',starts[0]);require(end>=0,'cache-definition-end')
    raw=text[starts[0]:end+3]
    require(raw==row['text'] and len(raw.encode())==row['bytes'] and
        hashlib.sha256(raw.encode()).hexdigest()==row['sha256'],'cache-definition-preimage')
    return raw


def authenticate(inputs):
    v=fixture();require(set(inputs)==set(v['source']),'cache-whole-membership')
    for n,row in v['source'].items():
        raw=inputs[n]
        require(type(raw) is bytes and len(raw)==row['bytes']<=route.bind.avc.maintained.MAX_FILE and
            hashlib.sha256(raw).hexdigest()==row['sha256'] and
            hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==row['gitBlob'],
            'cache-whole-preimage')
    require(sum(map(len,inputs.values()))<=route.bind.avc.maintained.MAX_SELECTED,'cache-input-envelope')
    for name,row in v['sections'].items():section(inputs[row['source']].decode(),name)


def private(raw,name):
    require(name in CLONES and section(raw,name)==raw,'cache-private-preimage')
    declaration,body=raw.split('\n{\n',1)
    declaration=replace(declaration,name+'(',NAMES[name]+'(')
    if name=='rt_cache_route':
        body=replace(body,'\tbool ret = true;\n','\tbool ret = true;\n'
            '\tbool pinned = false;\n\tunsigned int cpu = 0, kind;\n')
        old='\t\tp = (struct rtable **)&nhc->nhc_rth_input;\n'
        body=replace(body,old,old+'\t\tkind = LSF_ROUTE_CACHE_INPUT;\n')
        body=replace(body,'\t\tp = (struct rtable **)raw_cpu_ptr(nhc->nhc_pcpu_rth_output);\n',
            '\t\t/* Pin the actual CPU through metadata + real cache CAS. */\n'
            '\t\tcpu = get_cpu();\n\t\tpinned = true;\n'
            '\t\tp = (struct rtable **)per_cpu_ptr(nhc->nhc_pcpu_rth_output, cpu);\n'
            '\t\tkind = LSF_ROUTE_CACHE_OUTPUT;\n')
        old='\tdst_hold(&rt->dst);\n\tprev = cmpxchg(p, orig, rt);\n'
        new='\tif (!lsf_factory_route_cache_publish(rt, (struct rtable __rcu **)p,\n'
        new+='\t\t\torig, kind, cpu, 0, &prev)) {\n'
        new+='\t\tif (pinned)\n\t\t\tput_cpu();\n\t\treturn false;\n\t}\n'
        new+='\tif (pinned)\n\t\tput_cpu();\n'
        body=replace(body,old,new)
    elif name=='rt_bind_exception':
        old='\t\tdst_hold(&rt->dst);\n\t\trcu_assign_pointer(*porig, rt);\n'
        # The maintained body uses three tabs inside if (do_cache).
        old=old.replace('\t\t','\t\t\t')
        new='\t\t\tif (lsf_factory_route_cache_publish(rt, porig, orig,\n'
        new+='\t\t\t\trt_is_input_route(rt) ? LSF_ROUTE_CACHE_EXCEPTION_INPUT :\n'
        new+='\t\t\t\tLSF_ROUTE_CACHE_EXCEPTION_OUTPUT, 0, (__force u32)daddr, &orig)) {\n'
        body=replace(body,old,new)
        anchor='\t\t\tret = true;\n\t\t}\n'
        body=replace(body,anchor,'\t\t\tret = true;\n\t\t\t}\n\t\t}\n')
    else:
        for original in CLONES[:2]:body=replace(body,original+'(',NAMES[original]+'(')
    return declaration+'\n{\n'+body


def derive(inputs):
    authenticate(inputs)
    outputs=route.derive({n:inputs[n] for n in route.fixture()['source']})
    for n in set(inputs)-set(route.fixture()['source']):outputs[n]=inputs[n]
    for path in (route.ROUTE,route.DST,route.HEADER):
        text=outputs[path].decode()
        text=replace(text,'#include <net/lsf_stream_route_private.h>\n',
            '#include <net/lsf_stream_route_private.h>\n#include <net/lsf_stream_route_cache_private.h>\n')
        if path==route.DST:
            text=replace(text,'lsf_factory_route_return(dst)','lsf_prepaid_route_cache_return(dst)')
        if path==route.ROUTE:
            proto=private(section(inputs[path].decode(),'rt_set_nexthop'),'rt_set_nexthop').split('\n{\n',1)[0]+';\n'
            anchor='static void *lsf_prepaid_route_allocate('
            start=text.index(anchor)
            text=text[:start]+('static int lsf_prepaid_route_parent_attach(struct rtable *, const struct fib_result *, struct fib_info *, bool);\n'+proto)+text[start:]
            original=route.private(route.section(inputs[path].decode(),'__mkroute_output'),'__mkroute_output')
            selected=replace(original,'\tbool do_cache;\n','\tbool do_cache;\n\tint error;\n')
            old='\trt_set_nexthop(rth, fl4->daddr, res, fnhe, fi, type, 0, do_cache);\n'
            new='\terror = lsf_prepaid_route_parent_attach(rth, res, fi, do_cache);\n'
            new+='\tif (error) {\n\t\tip_rt_put(rth);\n\t\treturn ERR_PTR(error);\n\t}\n'
            new+='\tlsf_prepaid_rt_set_nexthop(rth, fl4->daddr, res, fnhe, fi, type, 0, do_cache);\n'
            selected=replace(selected,old,new)
            text=replace(text,original,selected)
            extra='\n#ifdef LSF_STREAM_ROUTE_SOURCE\n'
            for n in CLONES:extra+=private(section(inputs[path].decode(),n),n)
            extra+='#include "lsf_route_cache_private.c"\n#endif\n'
            text+=extra
        outputs[path]=text.encode()
    text=outputs['net/prepaid.h'].decode()
    text=replace(text,'#include "lineage.h"\n#endif\n','#include "lineage.h"\n#endif\n#include "route-cache-owner.h"\n')
    text=replace(text,'    lsf_u64 cache_anchor;\n','    lsf_u64 cache_anchor;\n    struct lsf_route_cache_owner route_cache;\n')
    text=replace(text,'(kind == LSF_PREPAID_ROUTE && record->deferred == LSF_PREPAID_PUBLISHED) ||\n',
        '(kind == LSF_PREPAID_ROUTE && (record->deferred == LSF_PREPAID_PUBLISHED ||\n'
        '         !lsf_route_cache_empty(&record->route_cache))) ||\n')
    outputs['net/prepaid.h']=text.encode()
    text=outputs['net/factory-private.h'].decode()
    text=replace(text,'#include "prepaid.h"\n','#include "prepaid.h"\n#include <net/lsf_stream_route_cache_private.h>\n')
    outputs['net/factory-private.h']=text.encode()
    text=outputs['net/factory.c'].decode()
    text=replace(text,'#include "factory-private.h"\n','#include "factory-private.h"\n#include <net/route.h>\n#define LSF_STREAM_ROUTE_CACHE_SOURCE 1\n')
    anchor='    /* Closing a descriptor is not final-free. No __free_pages, object release,\n'
    text=replace(text,anchor,'#ifdef LSF_STREAM_ROUTE_CACHE_SOURCE\n'
        '    for (i = 0; i < LSF_FACTORY_CONTEXTS; ++i)\n'
        '        lsf_prepaid_route_cache_drain(&factory.contexts[i]);\n#endif\n'+anchor)
    text+='\n#include "route-cache-factory.c"\n'
    outputs['net/factory.c']=text.encode()
    for source,target in (('route-cache-owner.h','net/route-cache-owner.h'),
        ('route-cache-private.h','include/net/lsf_stream_route_cache_private.h'),
        ('route-cache-factory.c','net/route-cache-factory.c'),
        ('route-cache-private.c','net/ipv4/lsf_route_cache_private.c')):
        outputs[target]=(OWNED/source).read_bytes()
    return outputs



def reference_body():
    """Exact selected C bodies; the reference supplies serialized types/locks."""
    factory=(OWNED/'factory.c').read_text();body=''
    for name,prefix in (('lsf_factory_context_current','static struct lsf_factory_context *'),
        ('lsf_factory_blob_lookup_locked','static int '),('lsf_factory_route_return','int '),
        ('lsf_factory_poison','void ')):
        start=prefix+name+'(';require(factory.count(start)==1,'cache-reference-factory-definition')
        begin=factory.index(start);end=factory.index('\n}\n',begin)+3;body+=factory[begin:end]
    for name in ('fib_info_hold_safe','fib_info_put','nexthop_get','nexthop_put','fnhe_flush_routes'):
        body+=fixture()['sections'][name]['text']
    body+='#include "route-cache-factory.c"\n'
    for name in CLONES[:2]:body+=private(fixture()['sections'][name]['text'],name)
    body+='#include "route-cache-private.c"\n'
    return body.encode()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();v=fixture();inputs={n:paths.read(a.source_dir,n,route.bind.avc.maintained.MAX_FILE) for n in v['source']}
    outputs=derive(inputs);paths.new_directory(a.output)
    for n,b in outputs.items():
        target=a.output/n;target.parent.mkdir(parents=True,exist_ok=True);paths.write_new(target,b)
    identity=lambda b:{'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
    receipt={'schemaVersion':'lsf.kernel-maintained-route-cache.v1','upstreamCommit':v['upstreamCommit'],
        'archiveSha256':v['archiveSha256'],'originals':{n:identity(b) for n,b in inputs.items()},
        'derived':{n:identity(b) for n,b in outputs.items()},'kernelBuilt':False,
        'actualRouteOrXfrmExecuted':False,'actualLinuxRcuExecuted':False,'completeAllocationClosure':False,
        'finalFreeCertified':False,'productionInstallation':False}
    paths.write_new(a.output/'derivation.json',(json.dumps(receipt,indent=2)+'\n').encode())
    print(json.dumps({'sources':len(inputs),'definitions':len(v['sections']),'derived':len(outputs),'kernelBuilt':False}))


if __name__=='__main__':main()
