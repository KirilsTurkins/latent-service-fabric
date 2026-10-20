"""Build once and execute ordinary microtask/timer cases on authenticated tools."""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import secrets
import sys
import tempfile
import time
if __package__ in {None,''}:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import qualify_typescript_fetch_runtime as base
from tools import typescript_runtime_semantics as cases
from tools.typescript_fetch_buffered import peer_evidence
from tools.qualify_typescript_fetch_conformance import shutdown_owned_node
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import require,write_json
from tools.phase2_operator_scenario import connect
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.rust_capsule_node import RecordingClient,deploy,call
from tools.rust_capsule_project import ROOT,digest,fresh,inventory,snapshot
from tools.standard_http.peer import Peer
from tools.typescript_fetch_replay_inputs import native_inputs
from tools.typescript_guest.build import build

SOURCES=('.github/workflows/typescript-runtime-semantics.yml',cases.SOURCE,
    'tools/typescript_runtime_semantics.py','tools/qualify_typescript_runtime_semantics.py',
    'tools/qualify_typescript_fetch_runtime.py','tools/typescript_fetch_replay_inputs.py',
    'tools/typescript_fetch_buffered.py','tools/qualify_typescript_fetch_conformance.py')


def execute(artifact,native,output):
    output=fresh(output)
    result={'status':'in-progress','cases':[],'fullTicketQualification':False,
        'ownerLimits':dict(base.OWNER_LIMITS),'callbackOriginProven':False}
    before=base.build_evidence(artifact);stage='sign'
    try:
        signed=output/'releases'
        signature=run_bounded_result([str(native['capsule_authoring']),'demo-sign',str(signed),str(artifact)],
            output,build_environment(output),timeout_seconds=30,max_output_bytes=65536)
        require(signature.returncode==0,'typescript-semantics-signing')
        with tempfile.TemporaryDirectory(prefix='lsf-ts-semantics-') as temporary, \
                owned_cancellation() as cancellation,ExitStack() as cleanup:
            work=Path(temporary)
            for directory in ('client','node','peer'):(work/directory).mkdir(mode=0o700)
            authorization=('Bearer '+secrets.token_hex(32)).encode()
            credential=work/'peer/authorization';credential.write_bytes(authorization);credential.chmod(0o600)
            peer=Peer(authorization,maximum_seconds=300);cleanup.callback(peer.close)
            startup={'destinations':peer.provider_destinations(),
                'origins':{role:peer.origin(role) for role in ('primary','secondary')}}
            config=base.configuration(work/'node',signed,startup,credential)
            client=RecordingClient(native['latent'],work/'client',cancellation,time.monotonic()+300,
                evidence=output/'controls',invocation_timeout_millis=120000,control_timeout_millis=125000)
            node=connect(client,native['latentd'],work/'node',config,'examples',1)
            cleanup.callback(node.close);probe=Probe(node,file_identity(native['latentd']))
            source=signed/'typescript-fetch'
            publication=client.call('release','publish-package',source/'package','--evidence',source/'evidence/index.json',
                '--operation-id','semantics-publish','--expected-generation','0')['data']['operation']['publication']['id']
            _runtime,authorized=base.grants(client,node,publication,startup['origins']['primary'])
            target=deploy(client,source/'deployment.json',publication,grants=authorized)
            rows=[('bootstrap',0,'ready|fresh=1',None),
                *((name,mode,expected,None) for name,mode,expected in cases.VECTORS)]
            for name,mode,code in cases.NEGATIVE:
                if mode==10:rows.append(('fuel-bootstrap',0,'ready|fresh=1',cases.FUEL))
                rows.extend(((name,mode,code,cases.FUEL if mode==10 else None),
                    ('fresh-after-'+name,0,'ready|fresh=1',cases.FUEL if mode==10 else None)))
            for name,mode,expected,fuel in rows:
                stage=name
                selected={**target,'budget':{**target['budget'],'cpuFuel':fuel}} if fuel else target
                row=call(client,selected,'typescript-fetch','run',[mode,'unused'],name)
                write_json(output/('invocation-'+name+'.json'),row)
                if mode>=8:cases.require_negative(row,expected)
                else:base.require_result(row,expected,0)
                base.retire(client,probe,target,output,name)
                result['cases'].append({'name':name,'mode':mode,'decoded':row['decoded'],
                    'terminal':(row['response'].get('error') or {}).get('code'),'cpuFuelBudget':selected['budget']['cpuFuel']})
            result['shutdown']=shutdown_owned_node(client,node)
            peer.close();result['peer']=peer_evidence(peer.observation())
        require(base.build_evidence(artifact)==before,'typescript-semantics-built-input-changed')
        result.update(status='passed',artifact=before)
        write_json(output/'qualification.json',result);return result
    except BaseException:
        result.update(status='failed',stage=stage);write_json(output/'FAILED.json',result);raise


def qualify(acquired,tools,output):
    acquired,tools,output=(Path(p).resolve() for p in (acquired,tools,output))
    require(output!=ROOT and ROOT not in output.parents and all(output!=p and output not in p.parents
        and p not in output.parents for p in (acquired,tools)),'typescript-semantics-separated-inputs')
    native,identity=native_inputs(acquired/'native');output=fresh(output)
    before_source={name:file_identity(ROOT/name,2*1024**2) for name in SOURCES}
    write_json(output/'qualification-source-inputs.json',before_source)
    before_native={name:file_identity(path,192*1024**2) for name,path in native.items()}
    app=cases.project(output/'application');before=inventory(snapshot(app))
    artifact=build(app,output/'build',native['capsule_contracts'],native['package'],
        'https://github.com/KirilsTurkins/latent-service-fabric',tools=tools,
        runtime_engine=acquired/'engine/engine.wasm',runtime_engine_receipt=acquired/'engine/engine-input.json',
        runtime_splicer=acquired/'splicer/splicer',runtime_splicer_receipt=acquired/'splicer/splicer-input.json')
    observed=execute(artifact,native,output/'node')
    require(before==inventory(snapshot(app)) and before_source=={name:file_identity(ROOT/name,2*1024**2) for name in SOURCES},
        'typescript-semantics-source-changed')
    require(native_inputs(acquired/'native')[1]==identity
        and before_native=={name:file_identity(path,192*1024**2) for name,path in native.items()},
        'typescript-semantics-native-changed')
    value={'status':'passed','source':digest(before),'build':base.build_evidence(artifact),
        'execution':file_identity(output/'node/qualification.json'),'cases':observed['cases'],
        'historicalNative':identity,'qualificationSources':before_source,'fullTicketQualification':False,
        'callbackOriginProven':False}
    write_json(output/'qualification.json',value);return value


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('acquired','tools','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();print(json.dumps(qualify(args.acquired,args.tools,args.output)))
