"""Focused published Polly Task execution with separately authenticated historical products."""
import argparse
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import replay_dotnet_reflection as original
from tools import qualify_dotnet_published_tasks as qualification
from tools import dotnet_task_replay_acquisition as acquisition
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, read_json, write_json

HOST_SOURCE = 'e97d44ddc744c9bd738d9b3b7a7d8b7234133e36'
HOST_BINARY = {'sha256': 'sha256:1ade67dfc9c461068ac7680a397f310eaf31e0e97b671a4dafd16ad710e1d050',
               'bytes': 184227152}
HOST_IDENTITY = {'sha256': 'sha256:db1b074b88c12884ac449bb873357759ab3807bcce79135c1ec45e705e84e92a',
    'files': 3168, 'bytes': 23911170,
    'scope': 'explicit-apps-crates-rust-sdk-workloads-and-workspace-inputs',
    'hermetic': False, 'implicitCompilerInputs': 'not-attested'}


def observed(prepared, host):
    _, receipt, products = original.verify_prepared(prepared)
    artifact = original.api('actions/artifacts/12220651992')
    job = original.api('actions/jobs/118292873857')
    require(artifact['id'] == 12220651992 and artifact['size_in_bytes'] == 40105690
            and artifact['digest'] == 'sha256:a138d432358bda73357e0d887310c3cb97e1c8d1065f664c526870a2c3c52e8a'
            and not artifact['expired'] and artifact['workflow_run']['id'] == 39320463437
            and artifact['workflow_run']['head_sha'] == HOST_SOURCE
            and job['run_id'] == 39320463437 and job['head_sha'] == HOST_SOURCE
            and job['conclusion'] == 'success', 'task-replay-current-host-origin')
    binary = host / 'latentd'
    info = read_json(host / 'current-host.json')
    acquisition.validate_host(host)
    require(info['compiledSource'] == HOST_SOURCE and info['sourceIdentity'] == HOST_IDENTITY
            and info['binary'] == HOST_BINARY and info['features'] == []
            and info['profile'] == {'opt_level': '0', 'debuginfo': 0, 'debug_assertions': True,
                'overflow_checks': True, 'test': False} and info['ordinaryDefaults'] is True
            and file_identity(binary, 512 * 1024**2) == HOST_BINARY
            and acquisition.git_source_identity(HOST_SOURCE) == HOST_IDENTITY, 'task-replay-current-host-source-or-product')
    binary.chmod(0o700)
    mapping = {'latent': products['latent'], 'latentd': binary,
        'package': products['examples/package'], 'capsule_contracts': products['examples/capsule_contracts'],
        'capsule_authoring': products['examples/capsule_authoring']}
    companions = {name: prepared / 'builds' / name for name in original.COMPANIONS}
    record = {'schemaVersion': 'latent.dotnet.task-replay-materials.v1',
        'applicationQualification': 'published-Polly8.6.3-and-Polly.Core8.6.3',
        'historicalOriginal': read_json(prepared / 'retrieval.json'),
        'historicalNormalNode': {'receiptDigest': receipt['node']['receiptDigest'], 'compiledSource': original.ORIGINAL_HEAD},
        'selectedHost': {'compiledSource': HOST_SOURCE, 'run': 39320463437, 'job': 118292873857,
            'artifact': 12220651992, 'binary': HOST_BINARY, 'sourceIdentity': HOST_IDENTITY,
            'frozenHistoricalNativeSourceMatches': True, 'currentNativeSourceMatchClaimed': False, 'implicitCompilerInputs': 'not-attested'},
        'selectedBinaries': {name: file_identity(path, 512 * 1024**2) for name, path in mapping.items()},
        'companionBuilds': {name: read_json(path / 'BUILD-COMPLETE.json') for name, path in companions.items()},
        'originalHostOverwritten': False, 'nativeRecompiled': False,
        'freshApplicationNativeAotRequired': True, 'currentHeadNormalQualificationClaimed': False}
    return mapping, companions, record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--host', type=Path)
    parser.add_argument('--tools', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.prepare:
        require(not any((args.prepared, args.host, args.tools)), 'task-replay-prepare-only')
        original.prepare(args.output.resolve())
        acquisition.retrieve_host(args.output.resolve() / 'selected-host')
        return
    require(all((args.prepared, args.host, args.tools)), 'task-replay-inputs-required')
    prepared, host = args.prepared.resolve(strict=True), args.host.resolve(strict=True)
    # An explicit diagnostic material adapter keeps each original receipt and
    # binary intact. The production qualifier's strict normal path is unchanged.
    def authenticated_materials(path):
        require(path == prepared, 'task-replay-fixed-prepared-only')
        return observed(prepared, host)
    qualification.inherited = authenticated_materials
    result = qualification.qualify(args.output.resolve(), args.tools.resolve(strict=True), prepared)
    write_json(args.output / 'replay-materials.json', result['inherited'])
    print('managed tasks qualification:', result['status'], 'invocations:', result['invocations'])


if __name__ == '__main__':
    main()
