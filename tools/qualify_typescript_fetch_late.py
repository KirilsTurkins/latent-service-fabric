"""Actual accepted-provider completion after public Fetch abort."""
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
from tools import typescript_fetch_late as late
from tools.qualify_typescript_fetch_conformance import shutdown_owned_node
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import require, stopped_record, write_json
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.rust_capsule_node import RecordingClient, deploy, start_call, sample
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, snapshot
from tools.standard_http.peer import Peer
from tools.typescript_fetch_replay_inputs import native_inputs
from tools.typescript_guest.build import build

SOURCES=('.github/workflows/typescript-fetch-late.yml',late.SOURCE,
    'tools/typescript_fetch_late.py','tools/qualify_typescript_fetch_late.py',
    'tools/typescript_fetch_conformance.py','tools/qualify_typescript_fetch_conformance.py',
    'tools/qualify_typescript_fetch_runtime.py','tools/typescript_fetch_replay_inputs.py')


def execute(artifact,native,output):
    output=fresh(output);original=base.build_evidence(artifact)
    result={'schemaVersion':'latent.typescript.fetch-late.v1','status':'in-progress',
        'fullTicketQualification':False,'crossTenantQualified':False,'cases':[]}
    stage='sign'
    try:
        environment=build_environment(output);signed=output/'releases'
        signature=run_bounded_result([str(native['capsule_authoring']),'demo-sign',str(signed),str(artifact)],
            output,environment,timeout_seconds=30,max_output_bytes=65536)
        require(signature.returncode==0,'fetch-late-signing')
        with tempfile.TemporaryDirectory(prefix='lsf-fetch-late-') as temporary, \
                owned_cancellation() as cancellation, ExitStack() as cleanup:
            work=Path(temporary)
            for name in ('client','node','peer'):(work/name).mkdir(mode=0o700)
            authorization=('Bearer '+secrets.token_hex(32)).encode()
            credential=work/'peer/authorization';credential.write_bytes(authorization);credential.chmod(0o600)
            peer=Peer(authorization,maximum_seconds=300);cleanup.callback(peer.close)
            startup={'destinations':peer.provider_destinations(),
                'origins':{role:peer.origin(role) for role in ('primary','secondary')}}
            config=base.configuration(work/'node',signed,startup,credential)
            result['configurationIdentity']=file_identity(config)
            client=RecordingClient(native['latent'],work/'client',cancellation,time.monotonic()+300,
                evidence=output/'controls',invocation_timeout_millis=120000,control_timeout_millis=125000)
            node=connect(client,native['latentd'],work/'node',config,'examples',1)
            cleanup.callback(node.close);probe=Probe(node,file_identity(native['latentd']))
            source=signed/'typescript-fetch'
            published=client.call('release','publish-package',source/'package','--evidence',source/'evidence/index.json',
                '--operation-id','fetch-late-publish','--expected-generation','0')
            publication=published['data']['operation']['publication']['id']
            _runtime,authorized=cases.grants(client,node,publication,startup['origins'])
            target=deploy(client,source/'deployment.json',publication,grants=authorized)
            for name,mode,vector in [('bootstrap',0,'domain-json'),
                    *[(vector,1,vector) for vector in late.VECTORS],('fresh',0,'domain-json')]:
                stage=name
                row=cases.invoke(client,target,peer,mode,vector,'late-'+name,
                    release_after=2.0 if mode==1 else None)
                write_json(output/('invocation-'+name+'.json'),row)
                base.require_result(row,late.EXPECTED if mode==1 else 'ready|fresh=1',mode)
                if mode==1:
                    require(int(row['elapsedNanos'])>=4000000000,'fetch-late-actual-elapsed')
                base.retire(client,probe,target,output,name)
                result['cases'].append({'name':name,'result':row['decoded'],'outbound':mode})
            result['shutdown']=shutdown_owned_node(client,node)
            peer.close();result['peer']=late.peer_evidence(peer.observation())
        require(base.build_evidence(artifact)==original,'fetch-late-built-input-changed')
        result.update(status='passed',artifact=original)
        write_json(output/'qualification.json',result);return result
    except BaseException:
        result.update(status='failed',stage=stage);write_json(output/'FAILED.json',result);raise


def qualify(acquired, tools, output):
    acquired,tools,output=(Path(p).resolve() for p in (acquired,tools,output))
    require(output!=ROOT and ROOT not in output.parents and all(output!=p and output not in p.parents
        and p not in output.parents for p in (acquired,tools)),'fetch-conformance-separated-inputs')
    native,identity=native_inputs(acquired/'native');output=fresh(output)
    sources=SOURCES
    source_before={name:file_identity(ROOT/name,2*1024**2) for name in sources}
    write_json(output/'qualification-source-inputs.json',source_before)
    before_native={name:file_identity(path,192*1024**2) for name,path in native.items()}
    app=late.project(output/'application');before=inventory(snapshot(app))
    artifact=build(app,output/'build',native['capsule_contracts'],native['package'],
        'https://github.com/KirilsTurkins/latent-service-fabric',tools=tools,
        runtime_engine=acquired/'engine/engine.wasm',runtime_engine_receipt=acquired/'engine/engine-input.json',
        runtime_splicer=acquired/'splicer/splicer',runtime_splicer_receipt=acquired/'splicer/splicer-input.json')
    observed=execute(artifact,native,output/'node')
    require(before==inventory(snapshot(app)),'fetch-conformance-source-changed')
    require(source_before=={name:file_identity(ROOT/name,2*1024**2) for name in sources},
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
