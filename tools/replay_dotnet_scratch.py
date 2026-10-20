"""Diagnostic ordinary .NET filesystem observations with authenticated historical native products."""
import argparse
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import qualify_sdk_scratch as qualification
from tools import replay_dotnet_tasks as tasks
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, read_json, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('prepared', 'host', 'tools', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    prepared, host = args.prepared.resolve(strict=True), args.host.resolve(strict=True)

    def authenticated_materials(directory, language, native_directory=None):
        require(directory == prepared and language == 'dotnet' and native_directory is None,
                'dotnet-scratch-fixed-diagnostic-materials-only')
        binaries, companions, record = tasks.observed(prepared, host)
        normal = read_json(prepared / 'node/workflow.json', 16 * 1024**2)
        require(normal['status'] == 'passed' and 27 <= len(normal['invocations']) <= 48
                and normal['nodeShutdown']['reaped'] and normal['nodeShutdown']['record']['clean'],
                'dotnet-scratch-original-normal-node-required')
        signed = {name: qualification.package_identity(path, read_json(path / 'BUILD-COMPLETE.json'))
                  for name, path in companions.items()}
        names = {'latent': 'latent', 'latentd': 'latentd', 'examples/package': 'package',
                 'examples/capsule_contracts': 'capsule_contracts',
                 'examples/capsule_authoring': 'capsule_authoring'}
        record.update(applicationQualification='ordinary-dotnet-filesystem-refusals',
            originalInvocations=len(normal['invocations']), companionSignerInputs=signed,
            diagnosticMaterials={name: file_identity(ROOT / name) for name in (
                'tools/replay_dotnet_scratch.py', 'tools/replay_dotnet_tasks.py',
                'tools/replay_dotnet_reflection.py', 'tools/dotnet_task_replay_acquisition.py',
                'tools/diagnostics/dotnet-entropy-original-source-03a.json')})
        return {name: binaries[value] for name, value in names.items()}, companions, record

    # The current normal-product verifier stays untouched; this diagnostic adapter
    # preserves each historical source/receipt and never claims a new native build.
    qualification.prepared = authenticated_materials
    result = qualification.qualify('dotnet', args.output.resolve(), prepared,
                                   tools=args.tools.resolve(strict=True))
    write_json(args.output / 'replay-materials.json', result['inherited'])
    print('ordinary .NET filesystem qualification:', result['status'], 'invocations:', result['invocations'])


if __name__ == '__main__':
    main()
