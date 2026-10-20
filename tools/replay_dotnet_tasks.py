"""Focused published Polly Task execution with separately authenticated historical products."""
import argparse
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import replay_dotnet_reflection as original
from tools import qualify_dotnet_published_tasks as qualification
from tools import dotnet_byte_host_acquisition as acquisition
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, read_json, write_json



def observed(prepared, host):
    _, receipt, products = original.verify_prepared(prepared)
    artifact = acquisition.origin()
    info = acquisition.validate(host)
    binary = host / 'latentd'
    selected = read_json(host / 'host-retrieval.json')
    require(selected['artifact'] == artifact['id'] and selected['archiveDigest'] == artifact['digest']
            and selected['run'] == acquisition.RUN and selected['job'] == acquisition.JOB
            and selected['compiledSource'] == acquisition.SOURCE
            and selected['binary'] == info['binary']
            and selected['sourceIdentity'] == acquisition.historical.git_source_identity(acquisition.SOURCE),
            'task-replay-byte-host-source-or-product')
    binary.chmod(0o700)
    mapping = {'latent': products['latent'], 'latentd': binary,
        'package': products['examples/package'], 'capsule_contracts': products['examples/capsule_contracts'],
        'capsule_authoring': products['examples/capsule_authoring']}
    companions = {name: prepared / 'builds' / name for name in original.COMPANIONS}
    record = {'schemaVersion': 'latent.dotnet.task-replay-materials.v1',
        'applicationQualification': 'published-Polly8.6.3-and-Polly.Core8.6.3',
        'historicalOriginal': read_json(prepared / 'retrieval.json'),
        'historicalNormalNode': {'receiptDigest': receipt['node']['receiptDigest'], 'compiledSource': original.ORIGINAL_HEAD},
        'selectedHost': selected,
        'diagnosticAcquisitionHelpers': {name: file_identity(ROOT / name, 1024**2) for name in (
            'tools/replay_dotnet_tasks.py', 'tools/dotnet_byte_host_acquisition.py',
            'tools/dotnet_task_replay_acquisition.py', 'tools/replay_dotnet_reflection.py')},
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
        acquisition.retrieve(args.output.resolve() / 'selected-host')
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
