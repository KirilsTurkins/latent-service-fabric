"""Execute ordinary published clients over TLS using their authenticated build."""
from __future__ import annotations
import argparse
from pathlib import Path
import subprocess
import sys

if __package__ in {None,''}:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import dotnet_https_node as node, replay_dotnet_published_http as original
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json
from tools.wait_runtime_native_products import native_products, verify_prepared

MATERIALS=tuple(sorted(set((*node.MATERIALS,'tools/qualify_dotnet_https_libraries.py',
    'tools/replay_dotnet_published_http.py','.github/workflows/dotnet-https-libraries.yml'))))


def qualify(native_input,output):
    native_input=native_input.resolve();output=output.resolve()
    require(output!=ROOT and ROOT not in output.parents and output not in ROOT.parents
        and output!=native_input and output not in native_input.parents and native_input not in output.parents,
        'dotnet-https-separated-owned-output')
    output=fresh(output)
    retained=verify_prepared(native_input);native=native_products(native_input)
    sources={name:file_identity(ROOT/name) for name in MATERIALS}
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=10).decode().strip()
    record={'schemaVersion':'latent.dotnet.https.libraries.v1','status':'incomplete',
        'executionSource':head,'executionSources':sources,'compiledSource':original.SOURCE,
        'nativeProducer':retained,'componentRecompiled':False,'fullTicketQualification':False}
    stage='original-build-acquisition'
    try:
        artifact,record['origin']=original.acquire(output/'original')
        previous=read_json(artifact.parent/'FAILED.json')
        record['originalBuildVerification']=original.verify_original(previous,artifact,output/'verified-recipe')
        require(previous['nativeProducer']==retained,'dotnet-https-same-original-native-products')
        stage='signed-real-tls-library-programme'
        execution=node.run(artifact,native,output/'node')
        require(execution['status']=='passed' and execution['guestExecutions']==15
            and [row['profile'] for row in execution['profiles']]==list(node.PROFILES)
            and retained==verify_prepared(native_input)
            and sources=={name:file_identity(ROOT/name) for name in MATERIALS}
            and head==subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=10).decode().strip(),
            'dotnet-https-all-original-limits-and-final-sources')
        record.update(status='passed',guestExecutions=15)
        write_json(output/'qualification.json',record)
        return record
    except BaseException:
        record.update(status='failed',stage=stage);write_json(output/'FAILED.json',record);raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('native','output'):parser.add_argument('--'+name,required=True,type=Path)
    args=parser.parse_args();print(qualify(args.native,args.output)['status'])
