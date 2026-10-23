"""Actual newly packaged rotation inputs and original277 checks; no node startup."""
from pathlib import Path
import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile
import time
import secrets
import zipfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import audit_memory_native_products as native
from tools import build_dev_frontend as packaging
from tools import qualify_stream_operator_node as original
from tools.dev_distribution import frontend_files
from tools.dev_workflow import paths, process
from tools.dev_workflow.common import DevError, decode, encode, require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json

RECIPE = ('.github/workflows/stream-operator-rotation.yml', 'tools/qualify_stream_operator_rotation.py',
          'tools/outbound_stream_operator.py', 'schemas/outbound-stream-rotation.schema.json',
          'schemas/node-providers.schema.json', 'schemas/outbound-stream-provider.schema.json',
          'tools/tests/test_outbound_stream_rotation.py', 'tools/build_dev_frontend.py',
          'tools/dev-frontend-linux.lock', 'tools/dev_frontend_linux.py', 'tools/dev_distribution.py',
          'tools/audit_memory_native_products.py', 'tools/qualify_stream_operator_node.py',
          'tools/qualify_audit_node_startup.py', 'tools/dev_workflow/paths.py',
          'tools/dev_workflow/process.py', 'tools/dev_workflow/common.py',
          'tools/build_process.py', 'tools/build_process_linux.py', 'tools/build_process_signals.py')


def frontend_origin(root, source):
    value = read_json(root / 'build.json')
    require(value.get('schemaVersion') == 'latent.dev.frontend-build.v1'
            and value.get('sourceCommit') == source and value.get('sourceDirty') is False
            and value.get('target') == 'linux-x86_64' and value.get('publisherAuthenticated') is False
            and value.get('qualification') == 'native-frontend-smoke-only'
            and value.get('streamOperatorSmoke', {}).get('realLatentd') is False,
            'stream-rotation-current-frontend-build-origin')
    files = frontend_files(root)
    require(value.get('files') == files, 'stream-rotation-current-frontend-file-inventory')
    binary = root / 'dist/latent-dev/latent-dev'
    require(file_identity(binary)['sha256'] == value.get('frontendSha256')
            and file_identity(root / 'helper.pyz')['sha256'] == value.get('helperSha256'),
            'stream-rotation-current-frontend-product-identities')
    resources = packaging.preflight_resources()
    require(value.get('preflightResources') == [
        {'path': name, 'sha256': packaging.digest(raw), 'size': len(raw)} for name, raw in resources],
        'stream-rotation-canonical-packaged-resources')
    with zipfile.ZipFile(root / 'helper.pyz') as archive:
        for name, raw in resources:
            require(archive.read('tools/dev_workflow/data/' + name) == raw,
                    'stream-rotation-helper-resource-original-bytes')
        require(archive.read('tools/outbound_stream_operator.py') == (ROOT / 'tools/outbound_stream_operator.py').read_bytes(),
                'stream-rotation-helper-operator-original-source')
    return binary, files, {'compiledFrontendSource': source, 'sameJobFrontendPackaged': True,
        'buildSmokeRealLatentd': False,
        'buildReceipt': file_identity(root / 'build.json'), 'frontend': file_identity(binary),
        'helper': file_identity(root / 'helper.pyz'), 'fileInventoryRows': len(files),
        'canonicalResources': value['preflightResources'], 'publisherAuthenticationClaimed': False}


def refusal(result, code):
    require(result.returncode == 1 and not result.stdout, 'stream-rotation-refusal-exit-and-channel')
    value = decode(result.stderr, 65536)
    require(value == {'schemaVersion': 'latent.outbound-stream.operator.result.v1', 'command': 'prepare-rotation',
                     'status': 'failed', 'code': code, 'uncertain': False},
            'stream-rotation-exact-redacted-refusal')
    return {'exitCode': 1, 'code': code, 'uncertain': False}


def qualify(frontend_root, output, native_input=None):
    require(sys.platform == 'linux', 'stream-rotation-linux-required')
    output = fresh(output)
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    started = time.monotonic()
    deadline = started + 240
    record = {'schemaVersion': 'latent.stream-operator.rotation-observation.v1', 'status': 'incomplete',
        'consumerSourceRevision': source, 'configurationChecksOnly': True,
        'nodeStarted': False, 'providerInstalled': False, 'providerReadiness': 'not-observed',
        'executionPermission': False, 'providerRotationPerformed': False, 'liveFileReplaced': False,
        'baseEpochOrigin': 'supplied-protected-file-not-live-provider-observation',
        'streamInvocationAttempted': False, 'nodeRebuilt': False, 'guestCompiled': False,
        'wholeIssue739Acceptance': False, 'outcomes': []}
    stage = 'verify-inputs'
    try:
        if native_input is None:
            native_input = output / 'native-origin'
            native.prepare(native_input)
        record['nodeOrigin'] = native.verify_prepared(native_input)
        frontend, inventory, record['frontendOrigin'] = frontend_origin(frontend_root, source)
        node = native.native_products(native_input)['latentd']
        node_before = file_identity(node, 256 * 1024**2)
        recipe = {name: file_identity(ROOT / name) for name in RECIPE}
        record['consumerRecipe'] = recipe
        record['sourceContract'] = original.source_contract()
        record['productVerificationMillis'] = int((time.monotonic() - started) * 1000)
        with tempfile.TemporaryDirectory(prefix='lsf-stream-rotation-') as temporary:
            work = Path(temporary).absolute()
            work.chmod(0o700)
            empty_path = work / 'empty-path'
            empty_path.mkdir(mode=0o700)
            environment = process.environment(work)
            environment['PATH'] = str(empty_path)
            base, selected, candidate = (work / name for name in ('base.json', 'rotation.json', 'candidate.json'))
            baseline = original.configuration(4096, True)
            token = secrets.token_hex(32)
            baseline['credentials'][0]['token'] = token
            paths.write_new(base, encode(baseline))

            def command(arguments):
                remaining = deadline - time.monotonic()
                require(remaining > 0, 'stream-rotation-overall-deadline')
                result = process.run(list(map(str, arguments)), work, timeout=min(45, remaining),
                                     maximum=65536, env=environment)
                original.clean_output(result, token, work)
                return result

            stage = 'complete-original-protected-baseline'
            result = command([node, 'check-config', '--config', base])
            value = decode(result.stdout, 65536) if result.returncode == 0 else {}
            require(result.returncode == 0 and not result.stderr
                    and value.get('schemaVersion') == 'latent.standalone.config-check.v1'
                    and value.get('protectedCredentialFile') is True, 'stream-rotation-complete-baseline-must-pass')
            record['outcomes'].append({'case': stage, 'exitCode': 0, 'protectedCredentialFile': True})
            settings = original.expected_configuration(baseline, original.installation())
            base.write_bytes(encode(settings))
            rotation = {'formatVersion': 1,
                'provider': {'id': 'streams', 'tenant': 'tests', 'service': 'stream-host'},
                'expectedEpoch': 1, 'newEpoch': 2,
                'limits': {'maximumTransferBytes': 32768, 'idleTimeoutMillis': 500, 'absoluteTimeoutMillis': 4000}}
            paths.write_new(selected, encode(rotation))
            before_base, before_rotation = base.read_bytes(), selected.read_bytes()

            def prepare(output_path):
                return command([frontend, 'stream-operator', 'prepare-rotation', '--node', node,
                    '--base-config', base, '--rotation-record', selected,
                    '--output', output_path, '--development-profile'])

            stage = 'actual-packaged-rotation-closed-profile-refusal'
            observed = refusal(prepare(candidate), 'stream-operator-node-check-rejected-prepared-file-retained')
            prepared = candidate.read_bytes()
            expected = copy.deepcopy(settings)
            expected['providers']['outboundStreams']['identity']['epoch'] = 2
            expected['providers']['outboundStreams']['configuration']['limits'] = rotation['limits']
            require(decode(prepared, 65536) == expected and candidate.stat().st_mode & 0o777 == 0o600,
                    'stream-rotation-exact-private-candidate')
            record['outcomes'].append({'case': stage, **observed, 'privateCandidateRetained': True,
                'onlyEpochAndLimitsChanged': True, 'existingAuthorityAndCredentialsPreserved': True})

            stage = 'direct-candidate-public-node-refusal'
            result = command([node, 'check-config', '--config', candidate])
            require(result.returncode == 2 and not result.stdout
                    and result.stderr == b'latentd: configuration: invalid-argument\n',
                    'stream-rotation-source-bound-public-node-refusal')
            record['outcomes'].append({'case': stage, 'exitCode': 2,
                'publicFailure': {'stage': 'configuration', 'code': 'invalid-argument'}})

            stage = 'existing-candidate-no-overwrite'
            observed = refusal(prepare(candidate), 'stream-operator-output-not-new-or-unavailable')
            require(candidate.read_bytes() == prepared, 'stream-rotation-existing-candidate-changed')
            record['outcomes'].append({'case': stage, **observed, 'privateCandidateUnchanged': True})

            for stage, changes, code in (
                ('stale-supplied-base-epoch', {'expectedEpoch': 2}, 'stream-operator-rotation-base-epoch-mismatch'),
                ('foreign-provider-identity', {'provider': {**rotation['provider'], 'id': 'foreign'}}, 'stream-operator-rotation-provider-mismatch'),
                ('overbroad-transfer-limit', {'limits': {**rotation['limits'], 'maximumTransferBytes': 1048577}}, 'stream-operator-configuration-invalid')):
                selected.write_bytes(encode({**rotation, **changes}))
                target = work / (stage + '.json')
                try:
                    observed = refusal(prepare(target), code)
                    require(not target.exists(), 'stream-rotation-invalid-record-created-output')
                    record['outcomes'].append({'case': stage, **observed, 'outputCreated': False})
                finally:
                    selected.write_bytes(before_rotation)

            stage = 'hardlinked-private-rotation-record'
            alias = work / 'linked-rotation.json'
            target = work / 'linked-output.json'
            os.link(selected, alias)
            try:
                observed = refusal(prepare(target), 'single-link-regular-file-required')
                require(not target.exists(), 'stream-rotation-linked-record-created-output')
                record['outcomes'].append({'case': stage, **observed, 'outputCreated': False})
            finally:
                alias.unlink()
            require(base.read_bytes() == before_base and selected.read_bytes() == before_rotation
                    and candidate.read_bytes() == prepared and not (work / 'data').exists(),
                    'stream-rotation-private-input-or-unexpected-storage-change')
            record['outsideCheckout'] = True
            record['pythonOnChildPath'] = False
            record['privateCandidatePreservedUntilOwnerTeardown'] = True
            record['privateInputsPublished'] = False
        require(file_identity(node, 256 * 1024**2) == node_before and frontend_files(frontend_root) == inventory,
                'stream-rotation-original-products-changed')
        require({name: file_identity(ROOT / name) for name in RECIPE} == recipe, 'stream-rotation-consumer-source-changed')
        record['productsAndConsumerSourceUnchanged'] = True
        record['status'] = 'passed'
        return record
    except BaseException as error:
        record['status'] = 'failed'
        record['failedStage'] = stage
        record['failureCode'] = error.code if isinstance(error, DevError) else 'bounded-programme-failed'
        raise
    finally:
        record['elapsedMillis'] = int((time.monotonic() - started) * 1000)
        write_json(output / 'result.json', record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frontend-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native-input', type=Path)
    arguments = parser.parse_args()
    try:
        qualify(arguments.frontend_root.absolute(), arguments.output, arguments.native_input)
        return 0
    except Exception:
        print('stream-rotation-owned-configuration-check-failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
