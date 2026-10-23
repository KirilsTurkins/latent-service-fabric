"""Build two current hosts once; observe finite original-bank startup boundaries.

No guest/compiler/std build and no repeat of the 25/193 control programmes.
The exact retained CLI/node may later be consumed with distinct old helpers.
"""
from pathlib import Path
import argparse
import os
import re
import shutil
import sys
import tempfile
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import host_codec_wasmtime, result_owner_bytes
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.node_startup_observation import observe
from tools.phase2_operator_process import Client, Process, require, stopped_record, write_json
from tools.phase3_resource_identity import file_identity, inventory
from tools.qualify_audit_memory import inputs as audit_inputs
from tools.qualify_host_codec_native import Stages, exact_list, exact_result
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh

CONTROL = 'durable::worker::node_bank_policy_tests::original_node_bank_keeps_its_ceiling_across_derived_journal_policies_and_prebirth_refusal'
CASES = (('two-records-audit-only', 2, False), ('two-records-provider', 2, True),
         ('lowered-provider', 1024, True), ('default-provider', 4096, True),
         ('oversized-fixed-refusal', 16384, True))
TOKEN = 'LSF-PUBLIC-AUDIT-STARTUP-TEST-ONLY'
NODE = 'audit-startup-test'
PRODUCT_LIMITS = {'latent': 128 * 1024**2, 'latentd': 256 * 1024**2}
RECIPE = ('.github/workflows/audit-node-startup.yml', 'tools/qualify_audit_node_startup.py',
          'tools/tests/test_audit_node_startup.py', 'tools/node_startup_observation.py',
          'tools/build_process_signals.py', 'tools/phase2_operator_process.py')


def inputs():
    value = audit_inputs()
    value['materials'].update({name: file_identity(ROOT / name) for name in RECIPE})
    value['materials'] = dict(sorted(value['materials'].items()))
    return value


def configuration(records, providers):
    require(type(records) is int and records in (2, 1024, 4096, 16384)
            and type(providers) is bool, 'audit-startup-closed-configuration')
    value = {'formatVersion': 1, 'dataDirectory': 'data', 'nodeId': NODE,
        'bind': '127.0.0.1:0', 'workers': {'runtime': 1, 'control': 1},
        'shutdownGraceMillis': 5000,
        'credentials': [{'token': TOKEN, 'subject': 'operator', 'tenant': 'tests', 'role': 'operator'}],
        'audit': {'mode': 'durable'}}
    if records != 4096:
        value['audit']['records'] = records
    if providers:
        value.update(budgetProfile={'mode': 'phase3', 'maximumOutboundRequests': 8,
            'maximumBlobReadBytes': 65536, 'maximumBlobWriteBytes': 65536},
            capabilityPolicies={'formatVersion': 1},
            providers={'formatVersion': 1,
                'blob': {'identity': {'id': 'blob', 'tenant': 'tests', 'service': 'blob-host', 'epoch': 1},
                         'namespace': 'workflow'},
                'bindings': [{'name': 'blob-binding', 'tenant': 'tests', 'consumerService': 'guest-blob',
                    'providerService': 'blob-host', 'contract': 'latent:blob/blob@0.2.0',
                    'providerBinding': 'blob-installed'}]})
    return value


def expected_refusal(raw, code, audit_exists):
    observation = observe(raw)
    require(code == 1 and not audit_exists and observation['status'] == 'observed'
            and observation['report']['terminalFailure'] == {'owner': 'platform', 'reason': 'resource-exhausted'}
            and {'stage': 'auditCatalog', 'failure': {'owner': 'platform', 'reason': 'resource-exhausted'}}
                in observation['report']['observations'], 'audit-startup-exact-prebirth-capacity-refusal')
    return observation


def startup_case(cli, binary, output, case, deadline, cancellation):
    label, records, providers = case
    evidence = fresh(output / label)
    with tempfile.TemporaryDirectory(prefix='lsf-audit-startup-') as temporary:
        work = Path(temporary)
        work.chmod(0o700)
        config = work / 'node.json'
        settings = configuration(records, providers)
        write_json(config, settings)
        environment = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(work),
                       'LANG': 'C.UTF-8', 'RUST_BACKTRACE': '0'}
        node = Process([str(binary), 'serve', '--config', str(config)], work,
                       environment, cancellation, maximum=262144)
        record = {'label': label, 'records': records, 'providers': providers, 'status': 'incomplete'}
        primary = False
        try:
            if records == 16384:
                result = node.complete(min(deadline, time.monotonic() + 30))
                record['refusal'] = expected_refusal(result.stderr, result.returncode,
                                                     (work / 'data/audit').exists())
                record['exitCode'] = result.returncode
            else:
                started = node.line(min(deadline, time.monotonic() + 30))
                record['startup'] = started
                endpoint = started.get('endpoint', '')
                require(re.fullmatch(r'127\.0\.0\.1:[0-9]{1,5}', endpoint), 'audit-startup-loopback-endpoint')
                require(len(started.get('providers', [])) == int(providers), 'audit-startup-real-provider-count')
                profile = work / 'client.json'
                write_json(profile, {'formatVersion': 1, 'defaultProfile': 'operator', 'profiles': [{
                    'name': 'operator', 'endpoint': 'http://' + endpoint, 'tenant': 'tests',
                    'token': TOKEN, 'connectTimeoutMillis': 2000, 'rpcTimeoutMillis': 15000}]})
                client = Client(cli, work, cancellation, min(deadline, time.monotonic() + 60))
                client.config, client.node = profile, node
                # The current CLI must parse the actual node's closed schema.
                ready = client.call('node', 'get', NODE)
                require(ready['data']['inventory']['health']['ready'] is True, 'audit-startup-node-ready')
                record['ready'] = ready
                page = client.call('audit', 'query', '--scope', 'tenant', '--page-size', '2')
                require(page['outcomeKnown'] is True and page['requestDispatched'] is True
                        and page['data']['records'] == [], 'audit-startup-empty-query-owned-response')
                record['auditQuery'] = page
                client.node = None
                node.stop()
                record['shutdown'] = stopped_record(node)
                record['cliCalls'] = client.calls
            record['status'] = 'passed'
            return record
        except BaseException:
            primary = True
            record['status'] = 'failed'
            raise
        finally:
            # Keep bounded actual stderr even when the first startup line fails.
            # This observation never changes the original decision or retries it.
            try:
                try:
                    node.close()
                except BaseException:
                    record['cleanupFailed'] = True
                    if not primary:
                        raise
            finally:
                for index, stream in enumerate(('stdout', 'stderr')):
                    (evidence / (stream + '.txt')).write_bytes(bytes(node.buffers[index]))
                write_json(evidence / 'result.json', record)


def qualify(output, revision):
    require(sys.platform == 'linux' and re.fullmatch('[0-9a-f]{40}', revision), 'audit-startup-real-linux-source')
    output = fresh(output)
    record = {'schemaVersion': 'latent.audit.node-startup.v1', 'status': 'incomplete',
        'sourceRevision': revision, 'signedGuestQualification': False,
        'guestSourceCompiled': False, 'historical193ProductsRebuilt': False}
    stage, stages, primary = 'prebuild-source', None, False
    try:
        host_codec_wasmtime.verify(ROOT)
        result_owner_bytes.verify(ROOT)
        before = inputs()
        write_json(output / 'source-inputs.json', before)
        environment = build_environment(output)
        target = Path(os.environ.get('CARGO_TARGET_DIR', ROOT / 'target')).resolve()
        environment.update(CARGO_TARGET_DIR=str(target), RUSTUP_TOOLCHAIN='1.97.1',
            CARGO_BUILD_JOBS='2', CARGO_INCREMENTAL='0', CARGO_PROFILE_DEV_DEBUG='0',
            CARGO_PROFILE_TEST_DEBUG='0', CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true',
            CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true', CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true',
            CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
        stages = Stages(Commands(ROOT, output, environment, deadline_seconds=1320, command_seconds=1200), output)
        stage = 'exact-source-revision'
        require(stages.run(stage, 'git', 'rev-parse', 'HEAD').decode().strip() == revision, 'audit-startup-source-revision')
        stage = 'pinned-rust-version'
        compiler = stages.run(stage, 'rustc', '--version').decode().strip()
        require(compiler.startswith('rustc 1.97.1 ('), 'audit-startup-rust-version')
        cargo = ('cargo', '--config', ROOT / '.cargo/managed-guest.toml')
        args = (*cargo, 'test', '--locked', '-p', 'latent-audit', '--lib', CONTROL, '--', '--exact')
        stage = 'original-node-bank-policy-list'
        exact_list(stages.run(stage, *args, '--list'), (CONTROL,))
        stage = 'original-node-bank-policy-run'
        exact_result(stages.run(stage, *args, '--test-threads=1'), (CONTROL,))
        stage = 'build-only-current-cli-and-node'
        stages.run(stage, *cargo, 'build', '--locked', '-p', 'latent', '-p', 'latentd')
        products = fresh(output / 'native-binaries')
        identities = {}
        for name in ('latent', 'latentd'):
            source = target / 'debug' / name
            identities[name] = file_identity(source, PRODUCT_LIMITS[name])
            shutil.copyfile(source, products / name)
            (products / name).chmod(0o700)
            require(file_identity(products / name, PRODUCT_LIMITS[name]) == identities[name], 'audit-startup-product-copy')
        stage = 'five-actual-startup-boundaries'
        cases = fresh(output / 'startup')
        with owned_cancellation() as cancellation:
            results = [startup_case(products / 'latent', products / 'latentd', cases, case,
                                    stages.commands.deadline, cancellation) for case in CASES]
        require(before == inputs(), 'audit-startup-source-or-recipe-changed')
        require(identities == {name: file_identity(products / name, PRODUCT_LIMITS[name])
                for name in identities}, 'audit-startup-products-changed')
        record.update(status='passed', compiler=compiler, inputs=before, products=identities,
            controls=[CONTROL], outcomes=results, commands=stages.records,
            productionStartupObserved=True, fullAllocationClosureQualified=False)
        write_json(output / 'receipt.json', record)
        return record
    except BaseException:
        primary = True
        record.update(status='failed', failedStage=stage, commands=stages.records if stages else [])
        raise
    finally:
        try:
            write_json(output / 'result.json', record)
            inventory(output, maximum_files=256, maximum_bytes=400 * 1024**2,
                      deadline=time.monotonic() + 60)
        except BaseException:
            if not primary:
                raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    args = parser.parse_args()
    qualify(args.output, args.source_commit)
