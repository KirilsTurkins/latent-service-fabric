"""Additional unchanged-library parser/framing/body-limit and fresh-state cases."""
from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import secrets
import sys
import tempfile
import time

from tools import dotnet_standard_http_node as base
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import Process, require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.rust_capsule_node import RecordingClient, delete_all, deploy, selected_revision
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json
from tools.standard_http.observations import validate

DOMAIN = '1:200:domain:7:caf\u00e9:first|\u03bb:'
CASES = (
    ('flurl-malformed-json',0,'/conformance/body/malformed-json','1:invalid-json',1),
    ('refit-malformed-json',1,'/conformance/body/malformed-json','1:invalid-json',1),
    ('flurl-oversized',0,'/conformance/body/oversized','1:transport-error',1),
    ('refit-oversized',1,'/conformance/body/oversized','1:transport-error',1),
    ('flurl-malformed-framing',0,'/conformance/body/malformed','1:transport-error',1),
    ('refit-malformed-framing',1,'/conformance/body/malformed','1:transport-error',1),
    ('flurl-truncated',0,'/conformance/body/truncated','1:transport-error',1),
    ('refit-truncated',1,'/conformance/body/truncated','1:transport-error',1),
    ('refit-404-unchanged',5,'/conformance/status/404','1:404:error:domain-error',1),
    ('refit-500-unchanged',7,'/conformance/status/500','1:500:error:domain-error',1),
    ('flurl-fresh-after-errors',0,'/conformance/json',DOMAIN,1),
    ('refit-fresh-after-errors',1,'/conformance/json',DOMAIN,1),
)
VECTORS = ['malformed-json']*2+['oversized-body']*2+['malformed-framing']*2+['truncated-body']*2+['http-404','http-500']+['domain-json']*2
MATERIALS = ('tools/dotnet_http_library_edges_node.py','tools/dotnet_published_http_node.py','tools/dotnet_standard_http_node.py',
    'tools/fixtures/dotnet-published-http/Main.cs','tools/standard_http/process_peer.py',
    'tools/standard_http/peer.py','tools/standard_http/protocol.py','tools/standard_http/vectors.py',
    'tools/standard_http/observations.py','tools/rust_capsule_node.py')


def peer_result(value):
    validate(value)
    require(value['state']=='stopped' and value['failure'] is None
        and value['acceptedConnections']==value['startedRequests']==12
        and value['openConnections']==value['rejectedRequests']==value['listeningOrigins']==0
        and value['committedMutations']==0,
        'dotnet-library-edges-exact-peer-retirement')
    rows=value['requests']
    require([row['vector'] for row in rows]==VECTORS
        and all(row['role']=='primary' and row['state']=='closed'
            and row['method']=='GET' and row['authorizationPresent'] is True
            and row['responseBytesWritten']>0 for row in rows),
        'dotnet-library-edges-exact-authorized-contacts')
    require(not any(row['kind'] in ('gate-pending','gate-released','mutation-committed')
        for row in value['events']), 'dotnet-library-edges-no-gate-or-mutation')
    require(all(row['closeReason']=='response-write-complete' for row in rows
        if row['vector'] in ('malformed-json','domain-json','http-404','http-500')), 'dotnet-library-edges-real-json-responses')
    return {'contacts':12,'completedWrites':value['completedResponseWrites'],
        'mutations':0,'allClosed':True,'exactVectors':list(VECTORS)}


def run(artifact: Path, native: dict, output: Path):
    output = fresh(output)
    before = {name:file_identity(path,512*1024**2) for name,path in native.items()}
    source = {name:file_identity(ROOT/name) for name in MATERIALS}
    component = file_identity(artifact/'component.wasm')
    record = {'schemaVersion':'latent.dotnet.http-library-edges.node.v1','status':'incomplete',
        'cases':[],'preEntryRefusals':[],'sources':source,'native':before,'component':component,
        'defaultFactories':['FlurlClient()','RestService.CreateHttpClient(endpoint, settings)',
            'RestService.ForGenerated<IDomainApi>(client, settings)'],
        'optionalGuestExtensionCases':[],
        'fullTicketQualification':False}
    stage = 'normal-signing'
    try:
        signed = output/'releases'
        environment = build_environment(output)
        completed = run_bounded_result([str(native['capsule_authoring']),'demo-sign',str(signed),str(artifact)],
            output,environment,timeout_seconds=30,max_output_bytes=65536)
        require(completed.returncode==0,'published-dotnet-normal-signing')
        with tempfile.TemporaryDirectory(prefix='lsf-dotnet-http-library-edges-') as temporary, \
                owned_cancellation() as cancellation, ExitStack() as cleanup:
            private = Path(temporary)
            for name in ('client','node','peer'):(private/name).mkdir(mode=0o700)
            credential = private/'peer/authorization'
            secret = ('Bearer '+secrets.token_hex(32)).encode('ascii')
            credential.write_bytes(secret);credential.chmod(0o600)
            client = RecordingClient(native['latent'],private/'client',cancellation,time.monotonic()+300,
                evidence=output/'controls',invocation_timeout_millis=120000)
            stage = 'real-peer-and-node'
            peer = Process([sys.executable,str(ROOT/'tools/standard_http/process_peer.py'),
                '--credential',str(credential)],private/'peer',environment,cancellation,maximum=65536)
            cleanup.callback(peer.close)
            startup = peer.line(min(client.deadline,time.monotonic()+10))
            config = base.configuration(private/'node',signed,startup,credential)
            record['configurationIdentity'] = file_identity(config)
            node = connect(client,native['latentd'],private/'node',config,'examples',1)
            cleanup.callback(node.close)
            probe = Probe(node,before['latentd'])
            release = signed/'dotnet-standard-http'
            published = client.call('release','publish-package',release/'package','--evidence',
                release/'evidence/index.json','--operation-id','library-edges-publish','--expected-generation','0')
            publication = published['data']['operation']['publication']['id']
            target = deploy(client,release/'deployment.json',publication)
            origin, foreign = (startup['origins'][role] for role in ('primary','secondary'))
            url = f"http://{origin['host']}:{origin['port']}"
            for label, runtime_only in (('runtime-missing',False),('http-missing',True)):
                stage = label
                if runtime_only:
                    runtime,authorized = base.grants(client,node,publication,origin)
                    target = deploy(client,release/'deployment.json',publication,
                        generation=str(target['generation']),grants=runtime)
                row = base.invoke(client,target,0,url+'/conformance/json','library-edges-'+label)
                require(row['exitCode']==4 and row['processReaped'] is True
                    and row['response']['outcomeKnown'] is True and row['response']['error']['code']=='permission-denied'
                    and int(row['response']['data']['consumption']['cpuFuel'])==0
                    and int(row['response']['data']['consumption']['outboundRequests'])==0,
                    'published-dotnet-before-guest-denial')
                record['preEntryRefusals'].append({'case':label,'invocation':row})
                base.retire(client,target,probe,output,label)
            target = deploy(client,release/'deployment.json',publication,
                generation=str(target['generation']),grants=authorized)
            pin = selected_revision(client,target)
            require(pin['releaseDigest']==component['sha256'],'published-dotnet-original-component-revision')
            for label,which,path,expected,outbound in CASES:
                stage = label
                endpoint = f"http://{foreign['host']}:{foreign['port']}/conformance/denied-target" if path=='secondary' else url+path
                row = base.invoke(client,target,which,endpoint,'library-edges-'+label)
                write_json(output/('invocation-'+label+'.json'),row)
                require(row['exitCode']==0 and row['decoded']==[expected] and row['processReaped'] is True
                    and row['response']['outcomeKnown'] is True
                    and row['response']['data']['resolvedRevision']==pin,'published-dotnet-exact-library-result')
                consumption = row['response']['data']['consumption']
                require(type(consumption['outboundRequests']) is int and consumption['outboundRequests']==outbound
                    and 0<int(consumption['cpuFuel'])<=target['budget']['cpuFuel']
                    and 0<int(consumption['peakMemoryBytes'])<=target['budget']['memoryBytes'],
                    'published-dotnet-original-budget-and-outbound-count')
                base.retire(client,target,probe,output,label)
                record['cases'].append({'case':label,'invocation':row,'physicalRetirementVerified':True})
                write_json(output/('progress-'+label+'.json'),record)
            delete_all(client,[target['name']]);stop(client,node)
            record['shutdown'] = stopped_record(node)
            require(record['shutdown']['reaped'] is True and record['shutdown']['record']['clean'] is True,
                    'published-dotnet-clean-node-stop')
            peer.stop()
            raw = bytes(peer.buffers[0])
            observation = json.loads(raw.splitlines()[-1])
            public = json.dumps(observation,ensure_ascii=True).encode('ascii')
            require(all(value not in encoded for value in (secret,secret.removeprefix(b'Bearer '))
                        for encoded in (raw,public)), 'published-dotnet-peer-secret-retention')
            write_json(output/'peer-observation.json',observation)
            record['peer'] = peer_result(observation)
            require(peer.owner.finished,'published-dotnet-peer-reaped')
        require(before=={name:file_identity(path,512*1024**2) for name,path in native.items()}
            and source=={name:file_identity(ROOT/name) for name in MATERIALS}
            and component==file_identity(artifact/'component.wasm'),'published-dotnet-final-source-and-products')
        record.update(status='passed',guestExecutions=12,preIoRefusals=2)
        write_json(output/'qualification.json',record)
        return record
    except BaseException:
        record.update(status='failed',stage=stage)
        write_json(output/'FAILED.json',record)
        raise
