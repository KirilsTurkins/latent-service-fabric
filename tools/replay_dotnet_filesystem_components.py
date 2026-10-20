"""Private node-only replay of authenticated original NativeAOT components."""
import argparse
import io
import os
from pathlib import Path
import stat
import subprocess
import sys
import zipfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import replay_dotnet_filesystem as products
from tools.build_observation import build_environment
from tools.dotnet_closed_filesystem_fixture import project
from tools.native_runtime.verify import relative
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_dotnet_closed_filesystem import MATERIALS, observed
from tools.qualify_sdk_scratch import package_identity
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_build import Commands, packaging_arguments
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, inventory, read_file, read_json, snapshot, write_json

COMPILED = 'cd6e9ac279f14efe39370f3ece5a338a56d4e617'
RUN = 39371941107
JOB = 118461535088
ARTIFACT = 12242646393
ARCHIVE_BYTES = 8968022
ARCHIVE_DIGEST = 'sha256:3deec64827602b3c5892757a16c9f98cdd2b05de0356db0d212c2490b50b237b'
MEMBERS = 716


def authenticated_components():
    api = products.acquisition.historical.api
    artifact = api(f'actions/artifacts/{ARTIFACT}')
    require(artifact['id'] == ARTIFACT and not artifact['expired']
            and artifact['size_in_bytes'] == ARCHIVE_BYTES and artifact['digest'] == ARCHIVE_DIGEST
            and artifact['workflow_run']['id'] == RUN and artifact['workflow_run']['head_sha'] == COMPILED,
            'filesystem-components-fixed-artifact-origin')
    job = api(f'actions/jobs/{JOB}')
    require(job['run_id'] == RUN and job['head_sha'] == COMPILED
            and job['status'] == 'completed' and job['conclusion'] == 'failure',
            'filesystem-components-original-failure-retained')
    raw = subprocess.check_output(['gh', 'api', 'repos/'+products.original.REPOSITORY+
        f'/actions/artifacts/{ARTIFACT}/zip'], timeout=180)
    require(len(raw) == ARCHIVE_BYTES and digest(raw) == ARCHIVE_DIGEST, 'filesystem-components-archive-digest')
    selected = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        rows = archive.infolist()
        require(len(rows) == len(set(archive.namelist())) == MEMBERS
                and sum(row.file_size for row in rows) <= 32*1024**2, 'filesystem-components-archive-bound')
        for row in rows:
            relative(row.filename)
            require(not row.is_dir() and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG)
                    and 0 <= row.file_size <= 8*1024**2, 'filesystem-components-regular-member')
            # Reading validates CRC for every authenticated member, even omitted DLLs.
            payload = archive.read(row)
            for label in ('pure', 'joined'):
                prefix = 'dotnet-closed-filesystem-replay/'+label+'/build/'
                if row.filename.startswith(prefix):
                    name = row.filename[len(prefix):]
                    if '/' not in name and (name.endswith('.json') or name == 'component.wasm'):
                        selected[label+'/'+name] = payload
    require(all(label+'/component.wasm' in selected for label in ('pure', 'joined')),
            'filesystem-components-both-original-components-required')
    return selected


def restore(location, label, selected):
    app, _ = project(location/'application', joined=label == 'joined')
    files = snapshot(app); source = inventory(files)
    build = location/'build'; build.mkdir()
    prefix = label+'/'
    for path, raw in selected.items():
        if path.startswith(prefix):
            (build/path[len(prefix):]).write_bytes(raw)
    require(read_file(build/'source-inputs.json') == source, 'filesystem-components-actual-source-mismatch')
    required = read_json(build/'package-inputs.json')
    require(type(required) is dict and 1 <= len(required) <= 128, 'filesystem-components-package-count')
    for name, identity in required.items():
        relative(name)
        destination = build/name
        if not destination.exists():
            require(name.startswith('wit/') and name in files, 'filesystem-components-unavailable-package-layer')
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(files[name])
        raw = read_file(destination, 64*1024**2)
        require(identity == {'digest': digest(raw), 'size': len(raw)}, 'filesystem-components-original-layer-mismatch')
    marker = read_json(build/'BUILD-COMPLETE.json')
    package = package_identity(build, marker)
    return app, build, files, {'originalBuildMarker': marker, 'originalBuildObservation': file_identity(build/'build-observation.json'),
        'originalPackageInputs': file_identity(build/'package-inputs.json'), 'packageLayers': package,
        'sourceInventoryEqual': True, 'nativeAotRecompiled': False, 'coreLibRewritten': False}


def replay(prepared, host, output):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and os.geteuid() != 0,
            'filesystem-components-unprivileged-linux-python313')
    output = output.absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
            'filesystem-components-output-outside-checkout')
    output = fresh(output)
    record = {'schemaVersion': 'latent.dotnet.filesystem.component-replay.v1', 'status': 'incomplete',
        'compiledSource': COMPILED, 'compiledRun': RUN, 'compiledJob': JOB, 'compiledJobConclusion': 'failure',
        'compiledArtifact': ARTIFACT, 'archiveDigest': ARCHIVE_DIGEST, 'archiveBytes': ARCHIVE_BYTES,
        'nativeAotRecompiled': False, 'nativeHostRebuilt': False, 'normalReceiptFabricated': False,
        'fullTicketQualification': False, 'filesystemAuthority': False}
    stage = 'authenticate-original-products'
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1100, command_seconds=600)
    try:
        binaries, companions, origin = products.observed(prepared, host)
        record['nativeAncestry'] = {name: origin[name] for name in ('historicalOriginal', 'selectedHost',
            'historicalOriginalNode', 'selectedBinaries', 'companionBuilds')}
        record['productionSource'] = products.PRODUCTION
        material_names = (*MATERIALS, 'tools/replay_dotnet_filesystem_components.py')
        materials = {name: file_identity(ROOT/name) for name in material_names}
        record['materials'] = materials
        stage = 'authenticate-original-components'
        selected = authenticated_components()
        for label in ('pure', 'joined'):
            stage = label+'-restore-original-public-package'
            location = output/label; location.mkdir()
            app, build, files, proof = restore(location, label, selected)
            # All reconstructed signer bytes match the original observed inventory.
            # Derive the public contracts anew with the original authenticated tool.
            wit_input = location/'wit-inputs.json'
            descriptor = read_json(app/'capsule-project.json')
            write_json(wit_input, {'world': descriptor['world'], 'sources': [
                {'path': name, 'content': data.decode('utf-8')} for name, data in files.items()
                if name.startswith('wit/') and name.endswith('.wit')]})
            commands.run(label+'-derive-original-public-contracts', binaries['examples/capsule_contracts'],
                wit_input, location/'derived')
            require(all(read_file(location/'derived'/name) == read_file(build/name)
                        for name in ('contracts.json', 'wit-lock.json', 'surface.json')),
                    'filesystem-components-public-contract-mismatch')
            commands.run(label+'-package-original-bytes', binaries['examples/package'], 'build',
                build/'package-source.json', build, build/'package', *packaging_arguments(files))
            commands.run(label+'-inspect-original-package', binaries['examples/package'], 'inspect',
                build/'package', *packaging_arguments(files))
            stage = label+'-fresh-sign'
            commands.run(label+'-demo-sign', binaries['examples/capsule_authoring'], 'demo-sign', location/'signed',
                *(build if name == 'greeting' else companions[name] for name in TEMPLATES))
            stage = label+'-signed-original-cases-and-authority'
            run(binaries['latent'], binaries['latentd'], location/'signed', location/'node', language='dotnet',
                standard_scratch_refusal=True, dotnet_scratch_task_runtime=label == 'joined')
            record[label] = {'execution': observed(location, joined=label == 'joined'), 'reconstruction': proof}
            require(inventory(snapshot(app)) == read_file(build/'source-inputs.json')
                    and package_identity(build, proof['originalBuildMarker']) == proof['packageLayers'],
                    'filesystem-components-replayed-input-drift')
        stage = 'final-input-recheck'
        require(products.observed(prepared, host)[2] == origin
                and materials == {name: file_identity(ROOT/name) for name in material_names},
                'filesystem-components-source-or-products-changed')
        record.update(status='passed', actualInvocations=79, commands=commands.records)
        write_json(output/'qualified.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__, commands=commands.records)
        write_json(output/'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('prepared', 'host', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    print(replay(args.prepared.resolve(strict=True), args.host.resolve(strict=True), args.output)['status'])
