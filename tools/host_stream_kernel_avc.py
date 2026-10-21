"""Exact maintained AVC producer/destructor derivation; uninstalled source only."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.dev_workflow import paths
from tools import host_stream_kernel_netport as netport

maintained = netport.maintained
OWNED = netport.protocol.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_avc.json'
AVC = 'security/selinux/avc.c'
HEADER = 'security/selinux/include/avc.h'
CLONES = ('avc_xperms_decision_alloc', 'avc_add_xperms_decision', 'avc_xperms_alloc',
    'avc_xperms_populate', 'avc_alloc_node', 'avc_insert', 'avc_update_node',
    'avc_compute_av', 'avc_denied', 'avc_perm_nonode', 'avc_has_perm_noaudit', 'avc_has_perm')
OBSERVED = ('avc_xperms_decision_free', 'avc_xperms_free', 'avc_node_free',
    'avc_node_kill', 'avc_node_delete', 'avc_node_replace')
ORDER = CLONES


def require(value, reason):
    if not value:
        raise ValueError('kernel-avc-' + reason)


def fixture():
    value = json.loads(FIXTURE.read_bytes())
    require(value['upstreamCommit'] == maintained.COMMIT and
        value['archiveSha256'] == maintained.manifest()['archive']['sha256'], 'upstream-identity')
    require(set(value['source']) == set(netport.fixture()['source']) | {AVC, HEADER}, 'source-membership')
    require(set(value['sections']) == set(CLONES) | set(OBSERVED) | {'sock_has_perm'}, 'definition-membership')
    require(value['kernelBuilt'] is value['actualLsmExecuted'] is
        value['completeAllocationClosure'] is value['productionInstallation'] is False, 'uninstalled-only')
    return value


def section(text, name):
    rows = fixture()['sections'];require(name in rows, 'definition-name')
    prefix = rows[name]['prefix']
    starts = [i for i in range(len(text)) if text.startswith(prefix, i) and (not i or text[i-1] == '\n')]
    require(len(starts) == 1, 'definition-occurrence')
    end = text.find('\n}\n', starts[0]);require(end >= 0, 'definition-end')
    raw = text[starts[0]:end+3]
    require(hashlib.sha256(raw.encode()).hexdigest() == rows[name]['sha256'] and raw == rows[name]['text'], 'definition-preimage')
    return raw


def replace(text, before, after, count=1):
    require(text.count(before) == count, 'replacement-preimage')
    return text.replace(before, after)


def observed(raw, name):
    require(name in OBSERVED and section(raw, name) == raw, 'observed-definition')
    if name == 'avc_xperms_decision_free':
        return replace(raw, '\txpd = &xpd_node->xpd;',
            '#ifdef LSF_STREAM_AVC_SOURCE\n\tif (lsf_prepaid_avc_decision_free(xpd_node))\n\t\treturn;\n#endif\n\txpd = &xpd_node->xpd;')
    if name == 'avc_xperms_free':
        return replace(raw, '\tif (!xp_node)\n',
            '#ifdef LSF_STREAM_AVC_SOURCE\n\tif (lsf_prepaid_avc_xperms_free(xp_node))\n\t\treturn;\n#endif\n\tif (!xp_node)\n')
    if name == 'avc_node_free':
        return replace(raw, '\tavc_xperms_free(node->ae.xp_node);',
            '#ifdef LSF_STREAM_AVC_SOURCE\n\tif (lsf_prepaid_avc_node_free(node, true)) {\n'
            '\t\tavc_cache_stats_incr(frees);\n\t\treturn;\n\t}\n#endif\n\tavc_xperms_free(node->ae.xp_node);')
    if name == 'avc_node_kill':
        return replace(raw, '\tavc_xperms_free(node->ae.xp_node);\n\tkmem_cache_free(avc_node_cachep, node);',
            '#ifdef LSF_STREAM_AVC_SOURCE\n\tif (!lsf_prepaid_avc_node_free(node, false)) {\n#endif\n'
            '\tavc_xperms_free(node->ae.xp_node);\n\tkmem_cache_free(avc_node_cachep, node);\n'
            '#ifdef LSF_STREAM_AVC_SOURCE\n\t}\n#endif')
    # Logical revocation/update MUST proceed even when a private physical birth
    # is poisoned. Queue before unlink under the same original slot lock, then
    # retain uncertain private storage instead of freeing it normally.
    target = 'node' if name == 'avc_node_delete' else 'old'
    raw = replace(raw, '\n{\n', '\n{\n#ifdef LSF_STREAM_AVC_SOURCE\n'
        f'\tint owned = lsf_prepaid_avc_node_queue({target});\n#endif\n')
    return replace(raw, f'\tcall_rcu(&{target}->rhead, avc_node_free);',
        '#ifdef LSF_STREAM_AVC_SOURCE\n\tif (owned >= 0)\n#endif\n'
        f'\tcall_rcu(&{target}->rhead, avc_node_free);')


def inherited_calls(body):
    """Append the explicit source to calls inside exact hash-selected bodies."""
    # This is not an arbitrary-C frontend. The whole definition is already
    # authenticated, and its selected calls contain ordinary balanced args.
    pattern = re.compile(r'\b(' + '|'.join(CLONES) + r')\(')
    position = 0;result = ''
    while match := pattern.search(body, position):
        opening = match.end()-1;closing = opening+1;depth = 1
        while closing < len(body) and depth:
            if body[closing] == '(':depth += 1
            elif body[closing] == ')':depth -= 1
            closing += 1
        require(depth == 0, 'selected-call-shape')
        args = body[opening+1:closing-1]
        require('"' not in args and "'" not in args, 'selected-call-literal')
        result += body[position:match.start()] + 'lsf_prepaid_' + match[1] + '(' + args
        result += (', ' if args.strip() else '') + 'source)'
        position = closing
    return result + body[position:]


def private(raw, name):
    require(name in CLONES and section(raw, name) == raw, 'private-definition')
    split = raw.index('\n{\n');declaration, body = raw[:split], raw[split:]
    declaration = replace(declaration, name+'(', 'lsf_prepaid_'+name+'(')
    if name == 'avc_has_perm_noaudit':declaration = replace(declaration, 'inline int ', 'static int ')
    if name in ('avc_insert', 'avc_compute_av'):declaration = replace(declaration, 'void ', 'int ')
    closing = declaration.rfind(')');require(closing >= 0, 'declaration-shape')
    if declaration.endswith('(void)'):
        declaration = declaration[:-5]+'const struct lsf_factory_blob *source)'
    else:
        declaration = declaration[:closing]+', const struct lsf_factory_blob *source'+declaration[closing:]
    body = inherited_calls(body)
    if name == 'avc_xperms_decision_alloc':
        body = replace(body, 'kmem_cache_zalloc(avc_xperms_decision_cachep,\n\t\t\t\t     GFP_NOWAIT | __GFP_NOWARN)',
            'lsf_factory_child_allocate(*source, sizeof(*xpd_node), LSF_PREPAID_AVC_DECISION)')
        body = replace(body, 'kmem_cache_zalloc(avc_xperms_data_cachep,\n\t\t\t\t\t\tGFP_NOWAIT | __GFP_NOWARN)',
            'lsf_factory_child_allocate(*source, sizeof(struct extended_perms_data), LSF_PREPAID_AVC_DATA)', 3)
    elif name == 'avc_xperms_alloc':
        body = replace(body, 'kmem_cache_zalloc(avc_xperms_cachep, GFP_NOWAIT | __GFP_NOWARN)',
            'lsf_factory_child_allocate(*source, sizeof(*xp_node), LSF_PREPAID_AVC_XPERMS)')
    elif name == 'avc_alloc_node':
        body = replace(body, 'kmem_cache_zalloc(avc_node_cachep, GFP_NOWAIT | __GFP_NOWARN)',
            'lsf_factory_child_allocate(*source, sizeof(*node), LSF_PREPAID_AVC_NODE)')
    elif name == 'avc_insert':
        body = replace(body, '\tu32 hvalue;', '\tu32 hvalue;\n\tint rc = 0;')
        body = replace(body, '\tif (avc_latest_notif_update(avd->seqno, 1))\n\t\treturn;',
            '\tif (avc_latest_notif_update(avd->seqno, 1))\n\t\treturn -EAGAIN;')
        body = replace(body, '\t\treturn;', '\t\treturn -ENOMEM;', 2)
        body = replace(body, '\t\t\tavc_node_replace(node, pos);',
            '\t\t\trc = lsf_prepaid_avc_node_replace(node, pos, hvalue, source);\n\t\t\tif (rc)\n\t\t\t\tavc_node_kill(node);')
        body = replace(body, '\thlist_add_head_rcu(&node->list, head);',
            '\trc = lsf_prepaid_avc_node_publish(node, hvalue, source);\n\tif (rc)\n\t\tavc_node_kill(node);\n\telse\n\t\thlist_add_head_rcu(&node->list, head);')
        body = body[:-2]+'\treturn rc;\n}\n'
    elif name == 'avc_update_node':
        body = replace(body, '\tavc_node_replace(node, orig);',
            '\trc = lsf_prepaid_avc_node_replace(node, orig, hvalue, source);\n\tif (rc)\n\t\tavc_node_kill(node);')
    elif name == 'avc_compute_av':
        body = replace(body, '\tlsf_prepaid_avc_insert(', '\treturn lsf_prepaid_avc_insert(')
    elif name == 'avc_denied':
        body = replace(body, '\tlsf_prepaid_avc_update_node(', '\treturn lsf_prepaid_avc_update_node(')
        body = replace(body, '\treturn 0;\n', '')
    elif name == 'avc_perm_nonode':
        body = replace(body, '\tu32 denied;', '\tu32 denied;\n\tint rc;')
        body = replace(body, '\tlsf_prepaid_avc_compute_av(ssid, tsid, tclass, avd, &xp_node, source);',
            '\trc = lsf_prepaid_avc_compute_av(ssid, tsid, tclass, avd, &xp_node, source);\n\tif (rc)\n\t\treturn rc;')
    elif name == 'avc_has_perm':
        body = replace(body, '\tint rc, rc2;', '\tint rc, rc2;\n\n\tif (!source)\n\t\treturn -EOPNOTSUPP;')
        body = replace(body, '\trc2 = avc_audit(ssid, tsid, tclass, requested, &avd, rc,\n\t\t\tauditdata);',
            '\trc2 = lsf_prepaid_avc_audit(ssid, tsid, tclass, requested, &avd, rc,\n\t\t\tauditdata, source);')
    require('kmem_cache_zalloc(' not in body, 'private-generic-allocation')
    return declaration + body


def authenticate(inputs):
    value = fixture();require(set(inputs) == set(value['source']), 'whole-source-membership')
    for name,row in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == row['bytes'] <= maintained.MAX_FILE and
            hashlib.sha256(raw).hexdigest() == row['sha256'] and
            hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == row['gitBlob'], 'whole-source-preimage')
    require(sum(map(len,inputs.values())) <= maintained.MAX_SELECTED, 'whole-source-envelope')
    for name,row in value['sections'].items():section(inputs[row['source']].decode(), name)


def reference_body():
    value=fixture();factory=(OWNED/'factory.c').read_text();body=''
    for name,prefix in (('lsf_factory_context_current','static struct lsf_factory_context *'),
        ('lsf_factory_child_allocate','void *'),('lsf_factory_blob_lookup_locked','static int '),
        ('lsf_factory_blob_lookup','int '),('lsf_factory_blob_finish','int '),('lsf_factory_poison','void ')):
        start=prefix+name+'(';require(factory.count(start)==1,'reference-factory-definition')
        begin=factory.index(start);end=factory.index('\n}\n',begin)+3;body+=factory[begin:end]
    body+=(OWNED/'factory-avc.c').read_text()
    body+='static void avc_node_free(struct rcu_head *);\nstatic void avc_node_delete(struct avc_node *);\n'
    body+=(OWNED/'avc-private.c').read_text()
    for name in OBSERVED:body+=observed(value['sections'][name]['text'],name)
    body+='#ifdef LSF_OLD_AVC\n'+value['sections']['avc_alloc_node']['text']
    body+='#else\n'+private(value['sections']['avc_alloc_node']['text'],'avc_alloc_node')+'#endif\n'
    return body.encode()


def derive(inputs):
    authenticate(inputs)
    outputs = netport.derive({name:inputs[name] for name in netport.fixture()['source']})
    original = inputs[AVC].decode();text = original
    for name in OBSERVED:
        raw = section(original,name);text = replace(text,raw,observed(raw,name))
    includes = '#ifdef CONFIG_LSF_STREAM_FACTORY\n#define LSF_STREAM_AVC_SOURCE 1\n'
    includes += '#include "../../net/factory-private.h"\n#include <net/lsf_stream_avc_private.h>\n'
    includes += 'static bool lsf_prepaid_avc_decision_free(struct avc_xperms_decision_node *);\n'
    includes += 'static bool lsf_prepaid_avc_xperms_free(struct avc_xperms_node *);\n'
    includes += 'static bool lsf_prepaid_avc_node_free(struct avc_node *, bool);\n'
    includes += 'static int lsf_prepaid_avc_node_queue(struct avc_node *);\n#endif\n'
    # Prototypes follow the real structure definitions, avoiding prototype-
    # scope tags; no shadow structure layout is supplied by this derivation.
    text = replace(text, 'static struct selinux_avc selinux_avc;\n', 'static struct selinux_avc selinux_avc;\n'+includes)
    text += '\n#ifdef LSF_STREAM_AVC_SOURCE\n#include "lsf_avc_private.c"\n'
    text += ''.join(private(section(original,name),name) for name in ORDER)
    text += '#endif\n';outputs[AVC] = text.encode();outputs[HEADER] = inputs[HEADER]
    hooks = outputs[netport.HOOKS].decode()
    sock = section(inputs[netport.HOOKS].decode(), 'sock_has_perm')
    declaration,body = sock.split('\n{\n',1)
    declaration = replace(declaration,'sock_has_perm(', 'lsf_prepaid_sock_has_perm(')
    declaration = declaration[:-1]+', const struct lsf_factory_blob *source)'
    body = replace(body, 'return avc_has_perm(current_sid(), sksec->sid, sksec->sclass, perms,\n\t\t\t    &ad);',
        'return lsf_prepaid_avc_has_perm(current_sid(), sksec->sid, sksec->sclass, perms,\n\t\t\t    &ad, source);')
    clone = declaration+'\n{\n'+body
    # Only the owned connect branch changes; the normal sock_has_perm body and
    # every other caller remain byte-identical in the maintained whole source.
    hooks = replace(hooks, sock, sock+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'+clone+'#endif\n')
    hooks = replace(hooks, '#include <net/lsf_stream_netport_private.h>\n',
        '#include <net/lsf_stream_netport_private.h>\n#include <net/lsf_stream_avc_private.h>\n')
    selected = netport.observed(netport.section(inputs[netport.HOOKS].decode(), 'selinux_socket_connect_helper'), 'selinux_socket_connect_helper')
    hooked = replace(selected, '\terr = sock_has_perm(sk, SOCKET__CONNECT);',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n\tif (owned)\n\t\terr = lsf_prepaid_sock_has_perm(sk, SOCKET__CONNECT, &source);\n\telse\n#endif\n\terr = sock_has_perm(sk, SOCKET__CONNECT);')
    hooked = replace(hooked, '\t\terr = avc_has_perm(sksec->sid, sid, sksec->sclass, perm, &ad);',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n\t\tif (owned)\n\t\t\terr = lsf_prepaid_avc_has_perm(sksec->sid, sid, sksec->sclass, perm, &ad, &source);\n\t\telse\n#endif\n\t\terr = avc_has_perm(sksec->sid, sid, sksec->sclass, perm, &ad);')
    hooks = replace(hooks, selected, hooked);outputs[netport.HOOKS] = hooks.encode()
    outputs['net/factory.c'] = replace(outputs['net/factory.c'].decode(), '/* SPDX-License-Identifier: GPL-2.0-only */\n',
        '/* SPDX-License-Identifier: GPL-2.0-only */\n#define LSF_STREAM_AVC_SOURCE 1\n').encode()
    for name,target in (('avc-private.h','include/net/lsf_stream_avc_private.h'),
        ('avc-private.c','security/selinux/lsf_avc_private.c'),('factory-avc.c','net/factory-avc.c')):
        outputs[target] = (OWNED/name).read_bytes()
    return outputs


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();value=fixture()
    inputs={name:paths.read(args.source_dir,name,maintained.MAX_FILE) for name in value['source']}
    outputs=derive(inputs);paths.new_directory(args.output)
    for name,raw in outputs.items():
        target=args.output/name;target.parent.mkdir(parents=True,exist_ok=True);paths.write_new(target,raw)
    identity=lambda raw:{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    record={'schemaVersion':'lsf.kernel-maintained-avc.v1','upstreamCommit':maintained.COMMIT,
        'archiveSha256':value['archiveSha256'],'originals':{n:identity(r) for n,r in inputs.items()},
        'derived':{n:identity(r) for n,r in outputs.items()},'kernelBuilt':False,'actualLsmExecuted':False,
        'actualRcuExecuted':False,'mandatoryAuditImplemented':False,'completeAllocationClosure':False,
        'finalFreeCertified':False,'productionInstallation':False}
    paths.write_new(args.output/'derivation.json',(json.dumps(record,indent=2)+'\n').encode())
    print(json.dumps({'sources':len(inputs),'definitions':len(value['sections']),'derived':len(outputs),'kernelBuilt':False}))


if __name__=='__main__':main()
