"""Actual frozen operator and native277 configuration refusals, without startup.

No Cargo, kernel, guest, compiler or node build; no serve/listener/provider call.
The two completed binary origins and this consumer head remain distinct.
"""
from pathlib import Path
import argparse
import copy
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import audit_memory_native_products as native
from tools.stream_operator_frontend_products import READER as FRONTEND
from tools.dev_workflow import paths, process
from tools.dev_workflow.common import DevError, decode, encode, require
from tools.phase3_resource_identity import file_identity
from tools.qualify_audit_node_startup import configuration
from tools.rust_capsule_project import ROOT, fresh, write_json

SOURCE = native.SOURCE
GATE_FILES = ('apps/latentd/Cargo.toml', 'apps/latentd/src/command.rs',
              'apps/latentd/src/config/derive.rs', 'apps/latentd/src/config/providers.rs',
              'apps/latentd/src/config/providers/streams.rs', 'tools/qualify_audit_node_startup.py')
RECIPE = ('.github/workflows/stream-operator-node-check.yml',
          'tools/qualify_stream_operator_node.py', 'tools/stream_operator_frontend_products.py',
          'tools/audit_memory_native_products.py', 'tools/tests/test_stream_operator_node.py',
          'tools/tests/fixtures/stream-operator-frontend-380-build.json',
          'tools/qualify_audit_node_startup.py', 'tools/dev_workflow/process.py',
          'tools/dev_workflow/paths.py', 'tools/dev_workflow/common.py',
          'tools/build_process.py', 'tools/build_process_linux.py', 'tools/build_process_signals.py')


def source_contract():
    # Whole immutable source identities, not a claim of a new native build.
    frozen = {}
    for name in GATE_FILES:
        raw = subprocess.check_output(['git', 'show', SOURCE + ':' + name], cwd=ROOT, timeout=15)
        require(len(raw) <= 1024**2, 'stream-operator-frozen-source-byte-bound')
        import hashlib
        frozen[name] = {'sha256': 'sha256:' + hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
        if name == 'tools/qualify_audit_node_startup.py':
            require((ROOT / name).read_bytes() == raw, 'stream-operator-original-complete-base-fixture')
    return {'compiledNodeSource': SOURCE, 'files': frozen,
            'deriveChecksDevelopmentStreamFeature': True,
            'publicFailure': {'exitCode': 2, 'stage': 'configuration', 'code': 'invalid-argument'},
            'privateFieldDiagnosticDisclosed': False,
            'attribution': 'frozen-source gate plus successful complete baseline and isolated stream addition'}


def installation():
    return {'installation': {
        'identity': {'id': 'streams', 'tenant': 'tests', 'service': 'stream-host', 'epoch': 1},
        'configuration': {'formatVersion': 1, 'profile': 'lsf-outbound-streams-v1',
            'destinations': [{'endpoint': {'host': '127.0.0.1', 'port': 32123, 'transport': 'tcp'},
                'addresses': {'networks': ['127.0.0.1/32'], 'specialAddresses': ['127.0.0.1']},
                'resolution': {'kind': 'static', 'addresses': ['127.0.0.1']}}],
            'limits': {'maximumTransferBytes': 65536, 'idleTimeoutMillis': 1000, 'absoluteTimeoutMillis': 5000}}},
        'bindings': [{'name': 'stream-binding', 'tenant': 'tests', 'consumerService': 'guest-stream',
            'providerService': 'stream-host', 'contract': 'latent:network/streams@0.1.0',
            'providerBinding': 'stream-installed'}]}


def expected_configuration(settings, record):
    value = copy.deepcopy(settings)
    value['providers']['outboundStreams'] = copy.deepcopy(record['installation'])
    value['providers']['bindings'].extend(copy.deepcopy(record['bindings']))
    return value


def operator_refusal(result, code):
    require(result.returncode == 1 and result.stdout == b'', 'stream-operator-refusal-exit-and-channel')
    value = decode(result.stderr, 65536)
    require(value == {'schemaVersion': 'latent.outbound-stream.operator.result.v1', 'command': 'prepare',
                     'status': 'failed', 'code': code, 'uncertain': False},
            'stream-operator-exact-redacted-refusal')
    return {'exitCode': 1, 'code': code, 'uncertain': False}


def clean_output(result, token, work):
    require(token.encode() not in result.stdout + result.stderr
            and str(work).encode() not in result.stdout + result.stderr,
            'stream-operator-private-input-or-path-disclosed')


def qualify(native_input, frontend_input, output):
    require(sys.platform == 'linux', 'stream-operator-actual-node-linux-required')
    output = fresh(output)
    record = {'schemaVersion': 'latent.stream-operator.actual-node-check.v1', 'status': 'incomplete',
        'consumerSourceRevision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'configurationChecksOnly': True, 'nodeStarted': False, 'providerInstalled': False,
        'providerReadiness': 'not-observed', 'executionPermission': False,
        'socketInvocationAttempted': False, 'nativeRebuilt': False, 'guestCompiled': False,
        'wholeIssue739Acceptance': False, 'outcomes': []}
    deadline = time.monotonic() + 240
    stage = 'verify-inputs'
    try:
        if native_input is None:
            native_input = output / 'native-origin'
            native.prepare(native_input)
        if frontend_input is None:
            frontend_input = output / 'frontend-origin'
            FRONTEND.prepare(frontend_input)
        record['nodeOrigin'] = native.verify_prepared(native_input)
        record['frontendOrigin'] = FRONTEND.verify_prepared(frontend_input)
        record['sourceContract'] = source_contract()
        record['consumerRecipe'] = {name: file_identity(ROOT / name) for name in RECIPE}
        node = native.native_products(native_input)['latentd']
        frontend = FRONTEND.frontend(frontend_input)
        before_node, before_frontend = file_identity(node, 256 * 1024**2), file_identity(frontend, 64 * 1024**2)
        with tempfile.TemporaryDirectory(prefix='lsf-actual-stream-config-') as temporary:
            work = Path(temporary).absolute()
            work.chmod(0o700)
            base, selected, candidate = (work / name for name in ('base.json', 'installation.json', 'candidate.json'))
            settings, selection = configuration(4096, True), installation()
            token = secrets.token_hex(32)
            settings['credentials'][0]['token'] = token
            paths.write_new(base, encode(settings))
            paths.write_new(selected, encode(selection))
            original_base, original_record = base.read_bytes(), selected.read_bytes()

            def command(arguments):
                remaining = deadline - time.monotonic()
                require(remaining > 0, 'stream-operator-overall-deadline')
                result = process.run(list(map(str, arguments)), work, timeout=min(45, remaining), maximum=65536)
                clean_output(result, token, work)
                return result

            stage = 'complete-original-baseline'
            result = command([node, 'check-config', '--config', base])
            require(result.returncode == 0 and not result.stderr, 'stream-operator-valid-baseline-must-pass')
            baseline = decode(result.stdout, 65536)
            require(baseline.get('schemaVersion') == 'latent.standalone.config-check.v1'
                    and baseline.get('protectedCredentialFile') is True,
                    'stream-operator-complete-protected-baseline-report')
            record['outcomes'].append({'case': stage, 'exitCode': 0,
                'schemaVersion': baseline['schemaVersion'], 'protectedCredentialFile': True})

            def prepare(output_path, *, base_path=base):
                return command([frontend, 'stream-operator', 'prepare', '--node', node,
                    '--base-config', base_path, '--installation-record', selected,
                    '--output', output_path, '--development-profile'])

            stage = 'actual-packaged-compiled-profile-refusal'
            result = prepare(candidate)
            observed = operator_refusal(result, 'stream-operator-node-check-rejected-prepared-file-retained')
            prepared = candidate.read_bytes()
            require(decode(prepared, 65536) == expected_configuration(settings, selection)
                    and candidate.stat().st_mode & 0o777 == 0o600,
                    'stream-operator-real-refusal-preserves-exact-private-candidate')
            record['outcomes'].append({'case': stage, **observed, 'privateCandidateRetained': True,
                                      'existingProviderAndCredentialsPreserved': True})

            stage = 'direct-same-candidate-public-node-refusal'
            result = command([node, 'check-config', '--config', candidate])
            require(result.returncode == 2 and result.stdout == b''
                    and result.stderr == b'latentd: configuration: invalid-argument\n',
                    'stream-operator-source-bound-actual-node-profile-refusal')
            record['outcomes'].append({'case': stage, 'exitCode': 2,
                'publicFailure': {'stage': 'configuration', 'code': 'invalid-argument'},
                'privateFieldDiagnosticDisclosed': False})

            stage = 'existing-private-candidate-no-overwrite'
            observed = operator_refusal(prepare(candidate), 'stream-operator-output-not-new-or-unavailable')
            require(candidate.read_bytes() == prepared, 'stream-operator-existing-candidate-changed')
            record['outcomes'].append({'case': stage, **observed, 'privateCandidateUnchanged': True})

            for stage, code in (('missing-base', 'stream-operator-file-unavailable-or-unsafe'),
                                ('hardlinked-base', 'single-link-regular-file-required'),
                                ('group-readable-base', 'stream-operator-file-protection'),
                                ('malformed-installation', 'invalid-json')):
                target = work / (stage + '.json')
                alias = work / 'linked-base.json'
                if stage == 'hardlinked-base':
                    os.link(base, alias)
                if stage == 'group-readable-base':
                    base.chmod(0o640)
                if stage == 'malformed-installation':
                    selected.write_bytes(b'{')
                try:
                    result = prepare(target, base_path=work / 'absent.json' if stage == 'missing-base' else base)
                    observed = operator_refusal(result, code)
                    require(not target.exists(), 'stream-operator-unsafe-input-created-candidate')
                    record['outcomes'].append({'case': stage, **observed, 'outputCreated': False})
                finally:
                    if stage == 'hardlinked-base':
                        alias.unlink()
                    if stage == 'group-readable-base':
                        base.chmod(0o600)
                    if stage == 'malformed-installation':
                        selected.write_bytes(original_record)
            require(base.read_bytes() == original_base and selected.read_bytes() == original_record
                    and candidate.read_bytes() == prepared and not (work / 'data').exists(),
                    'stream-operator-input-preservation-or-unexpected-node-storage')
            record['privateCandidatePreservedUntilOwnerTeardown'] = True
            record['privateInputsPublished'] = False
            record['nodeStorageCreated'] = False
        require(file_identity(node, 256 * 1024**2) == before_node
                and file_identity(frontend, 64 * 1024**2) == before_frontend,
                'stream-operator-original-products-changed')
        record['originalProductBytesUnchanged'] = True
        record['status'] = 'passed'
        return record
    except BaseException as error:
        record['status'] = 'failed'
        record['failedStage'] = stage
        record['failureCode'] = error.code if isinstance(error, DevError) else 'bounded-programme-failed'
        raise
    finally:
        write_json(output / 'result.json', record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-input', type=Path)
    parser.add_argument('--frontend-input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        qualify(args.native_input, args.frontend_input, args.output)
        return 0
    except Exception:
        print('stream-operator-owned-configuration-check-failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
