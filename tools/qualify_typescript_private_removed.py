"""Execute only the unfinished captured npm removal phase with a distinct host."""
from __future__ import annotations
import argparse
from pathlib import Path
import subprocess
import sys
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import rust_thread_native_products as native
from tools import typescript_private_removed_inputs as guests
from tools.build_observation import build_environment
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, fresh, write_json
from tools.run_rust_capsule_workflow import run, write_workflow_receipt

MATERIALS = ('tools/qualify_typescript_private_removed.py','tools/typescript_private_removed_inputs.py',
    'tools/tests/fixtures/typescript_private_removed_inputs.json','tools/rust_thread_native_products.py',
    'tools/sdk_native_products_reader.py','tools/host_codec_native_products_reader.py',
    'tools/host_codec_owned_reply_native_products_reader.py','tools/run_rust_capsule_workflow.py',
    'tools/npm_private_registry_fixture.py','tools/qualify_npm_private_dependencies.py',
    '.github/workflows/typescript-private-removed.yml')


def outcome(node, probe):
    private = node['capturedNpmPrivate']
    require(node['status'] == 'passed' and node['language'] == 'typescript'
        and len(node['invocations']) == 30 and all(row['processReaped'] for row in node['invocations'])
        and private['status'] == 'passed' and len(private['cases']) == 3
        and all(row['actualSignedTarget'] and row['freshState'] for row in private['cases'])
        and {key:private[key] for key in probe} == probe
        and node['nodeShutdown']['reaped'] and node['nodeShutdown']['record']['clean'],
        'ts-private-removed-actual-signed-cases-and-physical-retirement')


def qualify(guest_directory,native_directory,output):
    require(sys.platform == 'linux' and sys.version_info >= (3,13), 'ts-private-removed-linux-python313')
    guest_directory,native_directory = (Path(p).resolve(strict=True) for p in (guest_directory,native_directory))
    output = Path(output).absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents and
        all(output != p and p not in output.parents and output not in p.parents for p in (guest_directory,native_directory))
        and guest_directory != native_directory and guest_directory not in native_directory.parents
        and native_directory not in guest_directory.parents, 'ts-private-removed-separated-owned-inputs')
    output = fresh(output);stage = 'source-and-distinct-native-guest-origins'
    record = dict(schemaVersion='lsf.typescript-private-removed-qualification.v1',status='incomplete',
        guestSource=guests.SOURCE,runtimeHostSource=native.SOURCE,packagingToolsSource=native.SOURCE,
        consumerSourceRevision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,timeout=15).decode().strip(),
        guestComponentsCompiled=0,nativeProductsBuilt=0,priorThreeProgrammesReplayed=False,
        priorThreeProgrammesClaimedOnNewHost=False,wholeOriginalProducerQualified=False,
        fullTicketQualification=False,releasePublication='not-performed')
    try:
        materials = {name:file_identity(ROOT/name,1024**2) for name in MATERIALS}
        consumer = source_identity(ROOT)
        builds,guest_origin = guests.verify_prepared(guest_directory)
        native_origin = native.verify_prepared(native_directory)
        products = native.native_products(native_directory)
        for path in products.values(): path.chmod(0o700)
        record.update(guestOrigin=guest_origin,nativeOrigin=native_origin,consumerSource=consumer,materials=materials)
        commands = Commands(ROOT,fresh(output/'commands'),build_environment(output),deadline_seconds=120,command_seconds=120)
        stage = 'sign-only-existing-removed-package-and-four-existing-companions'
        commands.run('sign-existing-removed-private-npm',products['capsule_authoring'],'demo-sign',
            output/'signed',*(builds[name] for name in TEMPLATES))
        probe = {key:guests.fixture()[key] for key in ('nonce','version','removed','condition')}
        write_json(output/'signed/private-npm-probe.json',probe)
        stage = 'one-signed-removed-phase-on-distinct-193-control-host'
        node = run(products['latent'],products['latentd'],output/'signed',output/'node',
            language='typescript',captured_npm_private=True)
        outcome(node,probe)
        require(node['binaries'] == {'cli':native_origin['products']['latent'],
            'node':native_origin['products']['latentd']}, 'ts-private-removed-actual-native-products')
        require(guests.verify_prepared(guest_directory)[1] == guest_origin
            and native.verify_prepared(native_directory) == native_origin and source_identity(ROOT) == consumer
            and {name:file_identity(ROOT/name,1024**2) for name in MATERIALS} == materials,
            'ts-private-removed-final-source-and-input-integrity')
        record.update(status='passed',signedInvocations=30,removedPhaseCases=3,
            physicalNodeReaped=True,physicalNodeShutdownClean=True,nodeReceipt=file_identity(output/'node/workflow.json'),
            signingCommands=commands.records,historicalCompletedNodes=guest_origin['historicalCompletedNodes'])
        write_workflow_receipt(output/'qualified.json',record);return record
    except BaseException as error:
        record.update(status='failed',stage=stage,errorCategory=type(error).__name__)
        write_workflow_receipt(output/'FAILED.json',record);raise


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('guests','native','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();qualify(args.guests,args.native,args.output)
