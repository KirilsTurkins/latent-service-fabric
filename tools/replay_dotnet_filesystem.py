"""Diagnostic-only fresh BCL components using authenticated03a products and75 host."""
import argparse
from pathlib import Path
import subprocess
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import replay_dotnet_reflection as original
from tools import dotnet_byte_host_acquisition as acquisition
from tools import qualify_dotnet_closed_filesystem as qualification
from tools.dotnet_guest.build import RECIPE
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, read_json

PRODUCTION = '3e3eac58cac0604fcf7f8baf8afc4adc3e3be6f4'


def production_inputs():
    selected = sorted(set(RECIPE) | set(qualification.MATERIALS) | {
        'sdk/dotnet-guest', 'wit', 'schemas', 'tools/sdk_scratch_fixture.py', 'tools/sdk_scratch_probe.py'})
    result = subprocess.run(['git', 'diff', '--exit-code', PRODUCTION, '--', *selected], cwd=ROOT,
        capture_output=True, timeout=30, check=False)
    require(result.returncode == 0 and not result.stdout, 'filesystem-replay-current-production-input-drift')
    status = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, timeout=30)
    require(not status, 'filesystem-replay-clean-checkout')
    return {'productionSource': PRODUCTION, 'currentProductionInputsEqual': True,
        'fixtureSource': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()}


def observed(prepared, host):
    source = production_inputs()
    _, receipt, products = original.verify_prepared(prepared)
    artifact = acquisition.origin()
    info = acquisition.validate(host)
    retrieval = read_json(host / 'host-retrieval.json')
    require(retrieval['artifact'] == artifact['id'] and retrieval['archiveDigest'] == artifact['digest']
            and retrieval['run'] == acquisition.RUN and retrieval['job'] == acquisition.JOB
            and retrieval['compiledSource'] == acquisition.SOURCE and retrieval['binary'] == info['binary']
            and retrieval['sourceIdentity'] == acquisition.historical.git_source_identity(acquisition.SOURCE),
            'filesystem-replay-authenticated-byte-host')
    products = {**products, 'latentd': host / 'latentd'}
    for value in products.values(): value.chmod(0o700)
    companions = {name: prepared / 'builds' / name for name in original.COMPANIONS}
    record = {**source, 'historicalOriginal': read_json(prepared / 'retrieval.json'), 'selectedHost': retrieval,
        'historicalOriginalNode': {'digest': receipt['node']['receiptDigest'],
            'invocations': len(read_json(prepared / 'node/workflow.json')['invocations']),
            'compiledSource': original.ORIGINAL_HEAD},
        'selectedBinaries': {name: file_identity(path, 512*1024**2) for name, path in products.items()},
        'companionBuilds': {name: read_json(path / 'BUILD-COMPLETE.json') for name, path in companions.items()},
        'currentProgrammeBaseInvocations': 27, 'currentProgrammeFilesystemCalls': 12,
        'currentNormalReceiptFabricated': False, 'nativeHostRebuilt': False,
        'freshCurrentNativeAotRequired': True, 'normalProductionVerifierChanged': False}
    return products, companions, record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    for name in ('prepared', 'host', 'tools'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.prepare:
        require(not any((args.prepared, args.host, args.tools)), 'filesystem-replay-prepare-only')
        production_inputs()
        original.prepare(args.output.resolve())
        acquisition.retrieve(args.output.resolve() / 'selected-host')
    else:
        require(all((args.prepared, args.host, args.tools)), 'filesystem-replay-required-inputs')
        prepared, host = args.prepared.resolve(strict=True), args.host.resolve(strict=True)
        def inherited(path):
            require(path == prepared, 'filesystem-replay-fixed-prepared-only')
            return observed(prepared, host)
        # This process-local explicit material adapter never changes the normal
        # qualifier's source verifier or rewrites an original receipt.
        qualification.inherited = inherited
        result = qualification.qualify(args.output.resolve(), args.tools.resolve(strict=True), prepared)
        print('fresh pure/joined filesystem:', result['status'], 'invocations:', result['actualInvocations'])
