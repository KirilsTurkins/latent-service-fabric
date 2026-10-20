"""One normal catalogue-free TypeScript build and three signed default clients."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import secrets
import sys
import tempfile
import time

if __package__ in {None,''}:
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools import typescript_catalogue_free_build as catalogue
from tools import typescript_published_fetch_fixture as published
from tools import typescript_fetch_phase_fixture as fixture
from tools import qualify_typescript_fetch_runtime as base
from tools import qualify_typescript_fetch_phases as phase
from tools import typescript_fetch_conformance as calls
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.http_tenant_native_products import _git_materials, native_products, verify_prepared
from tools.phase2_operator_process import require, write_json
from tools.phase2_operator_scenario import connect
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.qualify_typescript_fetch_conformance import shutdown_owned_node
from tools.rust_capsule_node import RecordingClient, deploy
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, snapshot
from tools.standard_http.observations import validate as validate_peer
from tools.standard_http.vectors import DOMAIN, json_bytes
from tools.typescript_resource_runtime_inputs import verify as verify_compiler

PRIVATE_NAME='outside-fetch-catalogue-free-7b2'
PRIVATE_VERSION='3.7.2'
VECTORS=(('ky-json',0,'ky:'),('wretch-json',1,'wretch:'),('outside-json',2,'outside:'))
SOURCES=('.github/workflows/typescript-catalogue-free-http.yml',
    'tools/typescript_catalogue_free_build.py','tools/qualify_typescript_catalogue_free.py',
    'tools/typescript_published_fetch_fixture.py','tools/typescript_fetch_phase_fixture.py',fixture.SOURCE,
    'tools/qualify_typescript_fetch_phases.py','tools/qualify_typescript_published_fetch.py',
    'tools/qualify_typescript_fetch_runtime.py','tools/typescript_fetch_conformance.py',
    'tools/qualify_typescript_fetch_conformance.py','tools/http_tenant_native_products.py',
    'tools/typescript_resource_runtime_inputs.py','tools/typescript_fetch_replay_inputs.py',
    'tools/rust_capsule_node.py','tools/phase2_operator_process.py','tools/phase2_operator_scenario.py',
    'tools/standard_http/peer.py','tools/standard_http/protocol.py','tools/standard_http/vectors.py',
    'tools/standard_http/observations.py','tools/http_phase_wit.py')


def project(directory):
    app=fixture.project(directory)
    path=app/'src/default-client.ts';source=read_file(path)
    original=("from '"+fixture.PRIVATE_NAME+"'").encode()
    require(source.count(original)==1,'catalogue-free-original-private-import')
    path.write_bytes(source.replace(original,("from '"+PRIVATE_NAME+"'").encode(),1))
    return app


def peer_evidence(value):
    validate_peer(value)
    require(value['state']=='stopped' and value['acceptedConnections']==value['startedRequests']==3
        and value['completedResponseWrites']==3 and value['rejectedRequests']==value['committedMutations']==0
        and len(value['requests'])==3 and all(row['vector']=='domain-json' and row['role']=='primary'
            and row['state']=='closed' and row['authorizationPresent'] is True
            and row['cookiePresent'] is False and row['proxyAuthorizationPresent'] is False
            for row in value['requests']), 'catalogue-free-exact-three-contacts')
    return value


def execute(artifact,native,output):
    output=fresh(output);original=base.build_evidence(artifact)
    record={'status':'in-progress','cases':[],'fullTicketQualification':False}
    stage='sign'
    try:
        signed=output/'releases'
        result=run_bounded_result([str(native['capsule_authoring']),'demo-sign',str(signed),str(artifact)],
            output,build_environment(output),timeout_seconds=30,max_output_bytes=65536)
        for stream in ('stdout','stderr'):(output/('sign.'+stream+'.log')).write_bytes(getattr(result,stream))
        require(result.returncode==0,'catalogue-free-signing')
        with tempfile.TemporaryDirectory(prefix='lsf-ts-catalogue-free-') as temporary, \
                owned_cancellation() as cancellation, ExitStack() as cleanup:
            work=Path(temporary)
            for name in ('client','node','peer'):(work/name).mkdir(mode=0o700)
            authorization=('Bearer '+secrets.token_hex(32)).encode()
            credential=work/'peer/authorization';credential.write_bytes(authorization);credential.chmod(0o600)
            peer=fixture.PhasePeer(authorization,maximum_seconds=180);cleanup.callback(peer.close)
            startup={'destinations':peer.provider_destinations(),
                'origins':{role:peer.origin(role) for role in ('primary','secondary')}}
            config,owner=phase.configuration(work/'node',signed,startup,credential)
            record.update(configurationIdentity=file_identity(config),ownerProfile=owner)
            client=RecordingClient(native['latent'],work/'client',cancellation,time.monotonic()+180,
                evidence=output/'controls',invocation_timeout_millis=120000,control_timeout_millis=125000)
            stage='start-node';node=connect(client,native['latentd'],work/'node',config,'examples',1)
            cleanup.callback(node.close);probe=Probe(node,file_identity(native['latentd']))
            source=signed/'typescript-fetch';stage='publish-and-grant'
            publication=client.call('release','publish-package',source/'package','--evidence',source/'evidence/index.json',
                '--operation-id','catalogue-free-publish','--expected-generation','0')['data']['operation']['publication']['id']
            _runtime,authorized=phase.grants(client,node,publication,startup['origins']['primary'])
            target=deploy(client,source/'deployment.json',publication,grants=authorized)
            for name,mode,prefix in VECTORS:
                stage=name
                row=calls.invoke(client,target,peer,mode,'domain-json','catalogue-free-'+name)
                write_json(output/(name+'.json'),row)
                base.require_result(row,'1|'+prefix+json_bytes(DOMAIN).decode(),1)
                base.retire(client,probe,target,output,name)
                record['cases'].append(name)
            record['shutdown']=shutdown_owned_node(client,node)
            write_json(output/'shutdown.json',record['shutdown'])
            peer.close();record['peer']=peer_evidence(peer.observation())
            write_json(output/'peer.json',record['peer'])
        require(base.build_evidence(artifact)==original,'catalogue-free-signed-build-mutated')
        record.update(status='passed',signedExecution='passed',providerExecution='passed')
        write_json(output/'qualification.json',record);return record
    except BaseException:
        record.update(status='failed',stage=stage);write_json(output/'FAILED.json',record);raise


def qualify(acquired,native_input,tools,output):
    require(sys.platform=='linux','catalogue-free-typescript-Linux-required')
    acquired,native_input,tools=(path.resolve(strict=True) for path in (acquired,native_input,tools))
    output=output.resolve()
    require(output!=ROOT and ROOT not in output.parents and output not in ROOT.parents
        and all(output!=path and output not in path.parents and path not in output.parents
                for path in (acquired,native_input,tools)),'catalogue-free-separated-inputs')
    output=fresh(output);deadline=time.monotonic()+900
    record={'schemaVersion':'latent.typescript.catalogue-free-http.v1','status':'in-progress',
        'guestComponentsCompiled':0,'fullTicketQualification':False,'nativeOrEngineRebuilt':False,
        'applicationFetchInjection':False,'packageSourceChanges':False,'commands':[]}
    stage='authenticate-existing-native-and-compiler-inputs'
    try:
        native_before=verify_prepared(native_input);native=native_products(native_input)
        binary_before={name:file_identity(path,512*1024**2) for name,path in native.items()}
        compiler_before=verify_compiler(acquired)
        materials=_git_materials()
        auxiliary={name:row for name,row in materials.items() if name.startswith(('wit/','schemas/','examples/echo-contract/wit/'))}
        require(auxiliary and all(file_identity(ROOT/name)==row for name,row in auxiliary.items()),
            'catalogue-free-native-producer-ABI-or-schema-drift')
        sources={name:file_identity(ROOT/name,2*1024**2) for name in SOURCES}
        record.update(nativeProducer=native_before,compilerInputs=compiler_before,
                      nativeAuxiliaryCompileInputs=auxiliary,sourceMaterials=sources)
        write_json(output/'qualification-source-inputs.json',sources)
        stage='ordinary-private-and-published-package-capture'
        app=project(output/'application')
        captured=published.capture(app,output/'private-original',PRIVATE_NAME,PRIVATE_VERSION)
        require(captured['privateConsumer']['outsideOriginalRemoved'] is True
            and captured['privateConsumer']['identity']==PRIVATE_NAME
            and captured['privateConsumer']['version']==PRIVATE_VERSION
            and not (output/'private-original').exists(),'catalogue-free-private-origin-unavailable')
        write_json(output/'capture.json',captured);record['capture']=captured
        before=inventory(snapshot(app))
        stage='remove-all-optional-reference-and-catalogue-data'
        staged_root=output/'catalogue-free-build-source';staged=catalogue.stage(ROOT,staged_root)
        record['buildSource']=staged
        stage='normal-maintained-build-in-catalogue-free-source-root'
        environment=build_environment(output);environment.update(PYTHONPATH='',PYTHONDONTWRITEBYTECODE='1')
        argv=[sys.executable,'-B',str(staged_root/catalogue.SELF),'--project',str(app),'--output',str(output/'build'),
            '--tools',str(tools),'--contracts-tool',str(native['capsule_contracts']),'--packager',str(native['package']),
            '--repository','https://github.com/KirilsTurkins/latent-service-fabric',
            '--runtime-engine',str(acquired/'engine/engine.wasm'),'--runtime-engine-receipt',str(acquired/'engine/engine-input.json'),
            '--runtime-splicer',str(acquired/'splicer/splicer'),'--runtime-splicer-receipt',str(acquired/'splicer/splicer-input.json'),
            '--expect-source-digest',staged['inventoryDigest']]
        started=time.monotonic()
        result=run_bounded_result(argv,output,environment,timeout_seconds=min(600,deadline-started),max_output_bytes=2*1024**2)
        for stream in ('stdout','stderr'):(output/('compile.'+stream+'.log')).write_bytes(getattr(result,stream))
        record['commands'].append({'stage':'normal-build','exitCode':result.returncode,'seconds':time.monotonic()-started,
                                  'sourceRoot':str(staged_root),'pythonPathEmpty':True})
        require(result.returncode==0,'catalogue-free-normal-build-failed')
        require(catalogue.verify(staged_root)==staged,'catalogue-free-builder-mutated')
        build=base.build_evidence(output/'build')
        bundled=read_json(output/'build/bundle-selected-inputs.json',8*1024**2)
        require(bundled['standardFetchProfile']==fixture.PROFILE,'catalogue-free-selected-phase-fetch')
        stage='signed-default-client-smokes'
        execution=execute(output/'build',native,output/'node')
        require(execution['cases']==[name for name,_mode,_prefix in VECTORS]
            and before==inventory(snapshot(app)) and catalogue.verify(staged_root)==staged
            and native_before==verify_prepared(native_input) and compiler_before==verify_compiler(acquired)
            and binary_before=={name:file_identity(path,512*1024**2) for name,path in native.items()}
            and sources=={name:file_identity(ROOT/name,2*1024**2) for name in SOURCES}
            and time.monotonic()<deadline,'catalogue-free-final-source-native-and-compiler-freeze')
        record.update(status='passed',guestComponentsCompiled=1,build=build,source=digest(before),
                      cases=execution['cases'],execution=file_identity(output/'node/qualification.json'))
        write_json(output/'qualification.json',record);return record
    except BaseException as error:
        record.update(status='failed',stage=stage,errorCategory=type(error).__name__)
        write_json(output/'FAILED.json',record);raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('acquired','native','tools','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();print(json.dumps(qualify(args.acquired,args.native,args.tools,args.output)))
