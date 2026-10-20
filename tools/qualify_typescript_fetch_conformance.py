"""Fresh signed standard Fetch/provider cases with owned pending network work."""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import secrets
import sys
import tempfile
import time

if __package__ in {None,''}: sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools import qualify_typescript_fetch_runtime as base
from tools import typescript_fetch_conformance as cases
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import require, stopped_record, write_json
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.rust_capsule_node import RecordingClient, delete_all, deploy, start_call, sample
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, snapshot
from tools.standard_http.peer import Peer
from tools.typescript_fetch_replay_inputs import native_inputs
from tools.typescript_guest.build import build

SOURCES=('.github/workflows/typescript-fetch-conformance.yml',cases.SOURCE,
    'tools/typescript_fetch_conformance.py','tools/qualify_typescript_fetch_conformance.py',
    'tools/qualify_typescript_fetch_runtime.py','tools/typescript_fetch_replay_inputs.py')


def execute(artifact, native, output):
    output=fresh(output)
    result={'schemaVersion':'latent.typescript.fetch-conformance.v1','status':'in-progress',
        'fullTicketQualification':False,'networkStreamingQualified':False,'crossTenantQualified':False,'cases':[]}
    stage='sign';expires=time.monotonic()+300
    try:
        original=base.build_evidence(artifact);result['artifact']=original
        environment=build_environment(output)
        signed=output/'releases'
        signature=run_bounded_result([str(native['capsule_authoring']),'demo-sign',str(signed),str(artifact)],
            output,environment,timeout_seconds=30,max_output_bytes=65536)
        require(signature.returncode==0,'fetch-conformance-signing')
        with tempfile.TemporaryDirectory(prefix='lsf-fetch-conformance-') as temporary, \
                owned_cancellation() as cancellation, ExitStack() as cleanup:
            work=Path(temporary)
            for name in ('client','node','peer'): (work/name).mkdir(mode=0o700)
            authorization=('Bearer '+secrets.token_hex(32)).encode()
            credential=work/'peer/authorization';credential.write_bytes(authorization);credential.chmod(0o600)
            peer=Peer(authorization,maximum_seconds=300);cleanup.callback(peer.close)
            startup={'destinations':peer.provider_destinations(),
                'origins':{role:peer.origin(role) for role in ('primary','secondary')}}
            config=cases.configuration(work/'node',signed,startup,credential)
            result['configurationIdentity']=file_identity(config)
            client=RecordingClient(native['latent'],work/'client',cancellation,expires,
                evidence=output/'controls',invocation_timeout_millis=120000,control_timeout_millis=125000)
            stage='node';node=connect(client,native['latentd'],work/'node',config,'examples',1)
            cleanup.callback(node.close);probe=Probe(node,file_identity(native['latentd']))
            source=signed/'typescript-fetch'
            stage='publication'
            published=client.call('release','publish-package',source/'package','--evidence',source/'evidence/index.json',
                '--operation-id','fetch-conformance-publish','--expected-generation','0')
            publication=published['data']['operation']['publication']['id']
            target=deploy(client,source/'deployment.json',publication)
            for phase,selected in (('runtime-denied',None),('http-denied','runtime')):
                stage=phase
                if selected is not None:
                    runtime,authorized=cases.grants(client,node,publication,startup['origins'])
                    target=deploy(client,source/'deployment.json',publication,
                        generation=str(target['generation']),grants=runtime)
                row=cases.invoke(client,target,peer,0,'domain-json','conformance-'+phase)
                base.require_denied(row)
                require(peer.observation()['acceptedConnections']==0,'fetch-conformance-denied-contact')
                base.retire(client,probe,target,output,phase)
            target=deploy(client,source/'deployment.json',publication,
                generation=str(target['generation']),grants=authorized)
            for name,mode,vector,expected,outbound in cases.vectors():
                stage=name;before=peer.observation()['startedRequests']
                row=cases.invoke(client,target,peer,mode,vector,'conformance-'+name)
                base.require_result(row,expected,outbound)
                peer.poll(0)
                require(peer.observation()['startedRequests']-before==outbound,'fetch-conformance-exact-contact-delta')
                result['cases'].append({'name':name,'outbound':outbound,'result':row['decoded']})
                base.retire(client,probe,target,output,name)
            for name,mode,vector,expected in [
                ('explicit-abort',30,'pending-headers','explicit-abort'),
                ('operation-timeout',31,'partial-body','operation-timeout'),
                ('root-return-drains-accepted',32,'pending-headers','accepted-fetch-root-return')]:
                stage=name
                row=cases.invoke(client,target,peer,mode,vector,'conformance-'+name,release_after=.15)
                base.require_result(row,expected,1)
                result['cases'].append({'name':name,'outbound':1,'result':row['decoded'],'realGateReleased':True})
                base.retire(client,probe,target,output,name)
            for name,vector,wall,code in [('root-cancel','pending-headers',5000,'cancelled'),
                                         ('root-deadline','partial-body',3000,'deadline-exceeded')]:
                stage=name;activation='conformance-'+name
                process=start_call(client,target,'typescript-fetch','run',[34,peer.url(vector)],activation,wall=wall)
                try:
                    cases.wait_gate(client,process,peer)
                    write_json(output/('active-'+name+'.json'),sample(client,probe,name,1,active=True))
                    usage=client.call('capability','list','--deployment',target['name'],'--include-node-usage')['data']['nodeUsage']
                    require(not usage['unavailable'] and int(usage['counters']['pool_running_requests'])==1
                        and int(usage['counters']['io_calls'])>=1,'fetch-conformance-held-provider-owner')
                    write_json(output/('held-'+name+'.json'),usage)
                    if name=='root-cancel':
                        canceled=client.call('activation','cancel',activation,'--reason','Fetch conformance cancellation')
                        require(canceled['outcomeKnown'] and canceled['data']['disposition']=='accepted',
                            'fetch-conformance-root-cancel-acknowledgement')
                    row=cases.drive(client,process,peer)
                    require(row['exitCode']==4 and row['response']['error']['code']==code
                        and row['response']['outcomeKnown'] and row['processReaped'],'fetch-conformance-root-terminal')
                    require(row['response']['data']['consumption']['outboundRequests']==1,'fetch-conformance-root-charge')
                    peer.poll(0)
                    require(not peer.gates(),'fetch-conformance-original-socket-retired')
                    result['cases'].append({'name':name,'terminal':code,'heldProviderOwner':True})
                    base.retire(client,probe,target,output,name)
                finally: process.close()
            stage='fresh-after-lifecycle'
            row=cases.invoke(client,target,peer,0,'domain-json','conformance-fresh')
            base.require_result(row,'200:'+cases.json_bytes(cases.DOMAIN).decode()+':used:clone',1)
            base.retire(client,probe,target,output,'fresh-after-lifecycle')
            result['cases'].append({'name':'fresh-after-lifecycle','outbound':1,'result':row['decoded']})
            delete_all(client,[target['name']]);stop(client,node)
            result['shutdown']=stopped_record(node)
            require(result['shutdown']['reaped'] and result['shutdown']['record']['clean'],'fetch-conformance-clean-shutdown')
            peer.close();result['peer']=cases.peer_evidence(peer.observation())
        require(base.build_evidence(artifact)==original,'fetch-conformance-built-input-changed')
        result.update(status='passed',signedExecution='passed',providerExecution='passed')
        write_json(output/'qualification.json',result);return result
    except BaseException:
        result.update(status='failed',stage=stage);write_json(output/'FAILED.json',result);raise


def qualify(acquired, tools, output):
    acquired,tools,output=(Path(p).resolve() for p in (acquired,tools,output))
    require(output!=ROOT and ROOT not in output.parents and all(output!=p and output not in p.parents
        and p not in output.parents for p in (acquired,tools)),'fetch-conformance-separated-inputs')
    native,identity=native_inputs(acquired/'native');output=fresh(output)
    source_before={name:file_identity(ROOT/name,2*1024**2) for name in SOURCES}
    write_json(output/'qualification-source-inputs.json',source_before)
    before_native={name:file_identity(path,192*1024**2) for name,path in native.items()}
    app=cases.project(output/'application');before=inventory(snapshot(app))
    artifact=build(app,output/'build',native['capsule_contracts'],native['package'],
        'https://github.com/KirilsTurkins/latent-service-fabric',tools=tools,
        runtime_engine=acquired/'engine/engine.wasm',runtime_engine_receipt=acquired/'engine/engine-input.json',
        runtime_splicer=acquired/'splicer/splicer',runtime_splicer_receipt=acquired/'splicer/splicer-input.json')
    observed=execute(artifact,native,output/'node')
    require(before==inventory(snapshot(app)),'fetch-conformance-source-changed')
    require(source_before=={name:file_identity(ROOT/name,2*1024**2) for name in SOURCES},
        'fetch-conformance-qualification-source-changed')
    require(native_inputs(acquired/'native')[1]==identity
        and before_native=={name:file_identity(path,192*1024**2) for name,path in native.items()},
        'fetch-conformance-native-input-changed')
    value={'status':'passed','source':digest(before),'build':base.build_evidence(artifact),
        'execution':file_identity(output/'node/qualification.json'),'cases':observed['cases'],
        'historicalNative':identity,'qualificationSources':source_before,'fullTicketQualification':False}
    write_json(output/'qualification.json',value);return value


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('acquired','tools','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();print(json.dumps(qualify(args.acquired,args.tools,args.output)))
