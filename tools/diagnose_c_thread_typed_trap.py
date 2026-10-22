"""Two retained-component observations with a separately authenticated native cohort."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time

if __package__ in {None, ''}:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools import c_thread_minimal_inputs as inputs,c_thread_runtime_node as original
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.diagnose_c_thread_prefix import observe
from tools.java_replay_materials import git_source_identity
from tools.phase2_operator_process import require,stopped_record
from tools.phase2_operator_scenario import connect,stop
from tools.phase3_resource_identity import file_identity,source_identity
from tools.phase3_resource_os import Probe
from tools.qualify_c_thread_runtime import materials,build_evidence
from tools.qualify_resource_tenants import stop_observation_peer
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import RecordingClient,configure,delete_all,deploy,sample
from tools.rust_capsule_project import ROOT,fresh,read_json,write_json
from tools.sdk_provider_scenario import start_provider

HELPERS=('tools/c_thread_minimal_inputs.py','tools/diagnose_c_thread_typed_trap.py',
    'tools/diagnose_c_thread_prefix.py','tools/c_thread_prefix_inputs.py',
    'tools/host_codec_table_store_native_products.py',
    'tools/host_codec_table_store_native_products_reader.py',
    'tools/host_codec_native_products_reader.py','tools/sdk_native_products_reader.py',
    'tools/build_process_signals.py','tools/java_replay_materials.py',
    '.github/workflows/c-thread-typed-trap-diagnostic.yml')


def source_inputs():return {**materials(),**{name:file_identity(ROOT/name)for name in HELPERS}}


def native_evidence(products,prepared):
    record=products.verify_prepared(prepared)
    snapshot=read_json(prepared/'source-inputs.json')
    compiled=git_source_identity(products.SOURCE);current=source_identity(ROOT)
    require(compiled==current==snapshot['native'] and record['compiledSource']==products.SOURCE,
        'c-typed-new-cohort-full-compiled-source-must-be-current')
    # The frozen reader authenticates the exact new tuple/material set first.
    # No inherited148 count or old7b current-source allowance applies here.
    require(type(snapshot['materials'])is dict and 0<len(snapshot['materials'])<=256
        and snapshot['materials']=={name:file_identity(ROOT/name)for name in snapshot['materials']},
        'c-typed-new-cohort-all-actual-current-materials')
    require(set(record['products'])=={'latent','latentd','examples/package',
        'examples/capsule_contracts','examples/capsule_authoring'},'c-typed-new-cohort-five-products')
    proof={'compiledSourceRevision':products.SOURCE,'compiledNativeSource':compiled,
        'consumerNativeSource':current,'compiledSourceByteExact':True,'reviewedSourceChanges':[],
        'auxiliaryMaterialsByteExact':len(snapshot['materials']),
        'perProductCompilation':{name:{'sourceRevision':products.SOURCE,'nativeSource':compiled,
            'identity':identity}for name,identity in record['products'].items()}}
    return record,proof,products.native_products(prepared)


def run(prepared,output):
    from tools import host_codec_table_store_native_products as products
    require(sys.platform=='linux' and sys.version_info>=(3,13)and os.geteuid()!=0,
        'c-typed-unprivileged-linux-python313')
    output=output.absolute()
    require(output!=ROOT and output not in ROOT.parents and ROOT not in output.parents,
        'c-typed-output-outside-checkout')
    output=fresh(output);before=source_inputs();origin,source,tools=native_evidence(products,prepared)
    started=time.monotonic();stage='authenticate-original-component';commands=None
    record={'schemaVersion':'latent.c.thread-typed-trap.diagnostic.v1','status':'incomplete',
        'qualification':False,'diagnosticOnly':True,'full17ProgrammeQualified':False,
        'guestComponentsCompiled':0,'nativeProductsRebuilt':False,'materials':before,
        'nativeOrigin':origin,'nativeSource':source,'outcomes':[]}
    try:
        artifact,reuse=inputs.acquire(output/'original');record['originalDiagnostic']=reuse
        original_build=build_evidence(artifact,(artifact/'source-inputs.json').read_bytes())
        record['originalBuild']=original_build
        original_package=read_json(artifact/'package-inputs.json')
        commands=Commands(ROOT,fresh(output/'commands'),build_environment(output),deadline_seconds=600,command_seconds=90)
        stage='normal-package-inspect-sign-unchanged-component'
        binary={name:file_identity(tools[name])for name in('package','capsule_authoring')}
        commands.run('normal-package-retained-c-component',tools['package'],'build',artifact/'package-source.json',
            artifact,artifact/'package')
        commands.run('inspect-retained-c-component-package',tools['package'],'inspect',artifact/'package')
        signed=output/'signed'
        commands.run('normal-sign-retained-c-component',tools['capsule_authoring'],'demo-sign',signed,artifact)
        # Original compiler/BUILD-COMPLETE statements remain byte-exact. These
        # separate records describe actual current packaging/signing execution.
        record['newPackaging']={'binaryIdentities':binary,'commands':commands.records,
            'component':inputs.COMPONENT,'originalCompilerStatementRewritten':False,
            'originalPackageInputs':file_identity(artifact/'package-inputs.json'),
            'actualPackageManifest':file_identity(artifact/'package/manifest.json',65536),
            'originalCompilerSourceRevision':inputs.SOURCE}
        stage='two-diagnostic-observations'
        with owned_cancellation()as cancellation,tempfile.TemporaryDirectory(prefix='lsf-c-typed-')as temp,original.owned_cleanup(record)as cleanup:
            work=Path(temp)
            for name in('client','node','peer'):(work/name).mkdir(mode=0o700)
            client=RecordingClient(tools['latent'],work/'client',cancellation,
                min(commands.deadline,time.monotonic()+240),evidence=output/'controls')
            peer,port=start_provider(client,work/'peer',maximum_seconds=240);cleanup.callback(peer.close)
            config,settings=configure(work/'node',signed,port,language='c')
            original.configure(settings,read_json(artifact/'capsule.json'))
            config.write_bytes((json.dumps(settings,sort_keys=True,separators=(',',':'))+'\n').encode())
            record['configuration']=settings
            node=connect(client,tools['latentd'],work/'node',config,'examples',0);cleanup.callback(node.close)
            record['startup']=node.startup_record;probe=Probe(node,file_identity(tools['latentd']))
            release=signed/original.SERVICE
            published=client.call('release','publish-package',release/'package','--evidence',release/'evidence/index.json',
                '--operation-id','c-typed-publish','--expected-generation','0')
            require(published['outcomeKnown']is True and published['data']['release']['digest']==inputs.COMPONENT['sha256'],
                'c-typed-unchanged-original-component-publication')
            publication=published['data']['operation']['publication']['id'];target=deploy(client,release/'deployment.json',publication)
            grants=original.install(client,node,target)
            target=deploy(client,release/'deployment.json',publication,generation=str(target['generation']),grants=grants)
            for mode in inputs.MODES:
                record['outcomes'].append(observe(client,node,probe,target,output,mode))
                write_json(output/('progress-'+mode+'.json'),record)
            delete_all(client,[target['name']]);record['afterDelete']=sample(client,probe,'c-typed-after-delete',0)
            stop(client,node);record['nodeShutdown']=stopped_record(node);record['peerShutdown']=stop_observation_peer(peer)
            require(record['nodeShutdown']['reaped']is True and record['nodeShutdown']['record']['clean']is True,
                'c-typed-clean-reaped-node')
            cancellation.check()
        stage='source-build-product-and-original-bounds-fence'
        require(source_inputs()==before and native_evidence(products,prepared)==(origin,source,tools)
            and build_evidence(artifact,(artifact/'source-inputs.json').read_bytes())==original_build
            and read_json(artifact/'package-inputs.json')==original_package
            and binary=={name:file_identity(tools[name])for name in binary}
            and len(record['outcomes'])==2 and client.calls<=384
            and time.monotonic()-started<=1100 and time.monotonic()<commands.deadline,
            'c-typed-unchanged-source-original-component-provenance-and-bounds')
        record['rootPrefixControlPassed']=(record['outcomes'][0]['exitCode']==3
            and record['outcomes'][0]['decoded']==[{'err':'application-error'}])
        require(record['rootPrefixControlPassed'],'c-typed-root-prefix-control')
        record.update(status='observed',commands=commands.records)
        write_json(output/'diagnostic.json',record);return record
    except BaseException as error:
        record.update(status='failed',stage=stage,errorCategory=type(error).__name__,
            commands=commands.records if commands is not None else [])
        try:write_json(output/'FAILED.json',record)
        except BaseException:pass
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();value=run(args.prepared,args.output)
    print(json.dumps({'status':value['status'],'qualification':False,'attempts':len(value['outcomes'])}))
