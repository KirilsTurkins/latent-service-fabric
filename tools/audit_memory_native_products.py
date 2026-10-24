"""Two immutable Audit hosts built on277; no composite native tuple is invented.

The five later native-file changes reviewed in1375 are formatting only. This
reader binds the actual277 Git closure, without claiming byte equality with a
later development tree. Signed execution and its three old helpers are separate.
"""
from pathlib import Path, PurePosixPath
from contextlib import contextmanager
import os
import stat
import sys
import urllib.error
import urllib.request
import zipfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.sdk_native_products_reader import FrozenNativeProducts
from tools.java_replay_materials import NoRedirect, Ranges, REPOSITORY, git_source_identity
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json

SOURCE = '277c8104499d414053573bce066b5e9091e74a20'
RUN, JOB = 39931902934, 120341964917
BRANCH = 'feat/audit-owner-memory-20261023'
ARTIFACT = {'id': 12492391812, 'size_in_bytes': 56326844,
    'digest': 'sha256:dd8ca4d94042dd6512bfab9127d9fe4b87507c786bbabeb397bcd1fce4892322'}
RECEIPTS = {
    'receipt.json': {'sha256': 'sha256:bf8bc3cf97f6e45333a3a20769b93519fa8ae660d049144db7c24d5792ea262a', 'bytes': 63800},
    'source-inputs.json': {'sha256': 'sha256:4c36a06c55c23a90d855e91b42479524544542951fc1a803693363fdfbf8493c', 'bytes': 21868}}
PRODUCTS = {
    'latent': {'sha256': 'sha256:9f4db9594b1e9a5e6cf1d8dbedcb6f830748368b3ca1e8ec5bc635559694f116', 'bytes': 72212720},
    'latentd': {'sha256': 'sha256:28739f4d9ac7ae3c3507011b97620c21e932b53d57584379bcd57856dbe9a0fd', 'bytes': 193434168}}
PRODUCT_LIMITS = {'latent': 128 * 1024**2, 'latentd': 256 * 1024**2}
STAGES = ('exact-source-revision', 'pinned-rust-version', 'original-node-bank-policy-list',
          'original-node-bank-policy-run', 'build-only-current-cli-and-node')
CASES = ('two-records-audit-only', 'two-records-provider', 'lowered-provider',
         'default-provider', 'oversized-fixed-refusal')
CONTROL = 'durable::worker::node_bank_policy_tests::original_node_bank_keeps_its_ceiling_across_derived_journal_policies_and_prebirth_refusal'
MATERIAL_RECIPE = (
    '.github/workflows/host-codec-memory.yml', '.cargo/managed-guest.toml',
    'tools/qualify_host_codec_native.py', 'tools/tests/test_host_codec_native.py',
    'tools/toolchain.toml', 'tools/rust_capsule_build.py', 'tools/build_observation.py',
    'tools/build_process.py', 'tools/build_process_linux.py', 'tools/build_process_signals.py',
    'tools/phase2_operator_process.py', 'tools/phase3_resource_identity.py',
    'tools/phase3_resource_profile.py', 'tools/rust_capsule_project.py', 'tools/build_snapshot.py',
    'tools/host_codec_wasmtime.py', 'tools/result_owner_bytes.py', 'tools/security_common.py',
    'crates/vendor/wasmtime/UPSTREAM.latent.json', 'crates/vendor/wasmtime/latent-dynamic-memory.patch',
    'crates/vendor/wasmtime/README.latent.md', 'examples/echo-contract/capsule.json',
    'examples/package-format/capsule/manifest.json', 'examples/package-format/capsule/config.json',
    '.github/workflows/audit-memory-owner.yml', 'tools/qualify_audit_memory.py',
    'tools/tests/test_audit_memory_programme.py', 'tools/ci/suites.json',
    '.github/workflows/audit-node-startup.yml', 'tools/qualify_audit_node_startup.py',
    'tools/tests/test_audit_node_startup.py', 'tools/node_startup_observation.py')
SOURCE_IDENTITY = {'sha256': 'sha256:e3667a208dd0ef57c95aa37f47eba95288cd024979f31f1051b5975339c81e15',
    'files': 3712, 'bytes': 33932830,
    'scope': 'explicit-apps-crates-rust-sdk-workloads-and-workspace-inputs',
    'hermetic': False, 'implicitCompilerInputs': 'not-attested'}
SELECTED = {name: 1024**2 for name in RECEIPTS} | {
    'native-binaries/' + name: maximum for name, maximum in PRODUCT_LIMITS.items()}
MEMBERS = frozenset(('commands.json', 'current-stage.json', 'receipt.json', 'result.json', 'source-inputs.json',
    *('native-binaries/' + name for name in PRODUCTS),
    *(f'logs/{index:02d}-{stage}.{stream}.txt' for index, stage in enumerate(STAGES) for stream in ('stdout', 'stderr')),
    *(f'startup/{case}/{name}' for case in CASES for name in ('result.json', 'stdout.txt', 'stderr.txt'))))


@contextmanager
def _official_archive(artifact):
    token = os.environ.get('GH_TOKEN')
    require(bool(token), 'audit-native-explicit-actions-token')
    request = urllib.request.Request(
        f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}/zip',
        headers={'Authorization': 'Bearer ' + token})
    try:
        urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'audit-native-redirect')
        url = error.headers['Location']
    else:
        raise ValueError('audit-native-redirect-required')
    require(url.startswith('https://'), 'audit-native-https')
    remote = Ranges(url, artifact['size_in_bytes'])
    with zipfile.ZipFile(remote) as archive:
        yield archive, remote


class _FrozenAuditHosts(FrozenNativeProducts):
    def __init__(self):
        super().__init__(source=SOURCE, run=RUN, job=JOB, artifact=ARTIFACT,
            receipts=RECEIPTS, branch=BRANCH, stages=STAGES, include_protocol=True)

    def _valid_stages(self, stages):
        return stages == STAGES

    def _pins(self):
        require((self.source, self.run, self.job, self.branch, self.event) == (SOURCE, RUN, JOB, BRANCH, 'push')
                and self.artifact == ARTIFACT and self.receipts == RECEIPTS
                and self.stages == STAGES and self.include_protocol is True,
                'audit-native-fixed-completed-origin')

    def _producer_origin(self):
        return ('.github/workflows/audit-node-startup.yml',
                'Original node startup and five finite audit boundaries', 'audit-node-startup-')

    def _material_recipe(self):
        return MATERIAL_RECIPE

    def validate_record(self, record, snapshot, native, materials):
        self._pins()
        require(type(record) is dict and record.get('schemaVersion') == 'latent.audit.node-startup.v1'
            and record.get('status') == 'passed' and record.get('sourceRevision') == SOURCE
            and record.get('inputs') == snapshot == {'source': native, 'materials': materials}
            and native == SOURCE_IDENTITY and len(materials) == 158
            and record.get('products') == PRODUCTS and record.get('controls') == [CONTROL]
            and record.get('productionStartupObserved') is True,
            'audit-native-frozen-record-and-source')
        require(all(record.get(name) is False for name in ('signedGuestQualification', 'guestSourceCompiled',
            'historical193ProductsRebuilt', 'fullAllocationClosureQualified')),
            'audit-native-startup-not-signed-qualification')
        commands = record.get('commands')
        cargo = ['cargo', '--config', '/home/runner/work/latent-service-fabric/latent-service-fabric/.cargo/managed-guest.toml']
        test = cargo + ['test', '--locked', '-p', 'latent-audit', '--lib', CONTROL, '--', '--exact']
        argv = (['git', 'rev-parse', 'HEAD'], ['rustc', '--version'], test + ['--list'],
                test + ['--test-threads=1'], cargo + ['build', '--locked', '-p', 'latent', '-p', 'latentd'])
        require(type(commands) is list and len(commands) == 5 and all(
            row.get('stage') == stage and row.get('argv') == args and row.get('exitCode') == 0
            for row, stage, args in zip(commands, STAGES, argv)), 'audit-native-five-real-commands')
        outcomes = record.get('outcomes')
        require(type(outcomes) is list and len(outcomes) == 5
            and [row.get('label') for row in outcomes] == list(CASES)
            and [(row.get('records'), row.get('providers')) for row in outcomes]
                == [(2, False), (2, True), (1024, True), (4096, True), (16384, True)]
            and all(row.get('status') == 'passed' for row in outcomes), 'audit-native-five-startup-outcomes')
        for outcome in outcomes[:-1]:
            stopped = outcome.get('shutdown', {})
            require(stopped.get('reaped') is True and stopped.get('record', {}).get('clean') is True
                    and stopped['record'].get('report', {}).get('clean') is True
                    and outcome.get('ready', {}).get('data', {}).get('inventory', {}).get('health', {}).get('ready') is True
                    and outcome.get('auditQuery', {}).get('data', {}).get('records') == [],
                    'audit-native-real-readiness-query-and-retirement')
        refusal = outcomes[-1]
        require(refusal.get('exitCode') == 1 and refusal.get('refusal', {}).get('status') == 'observed'
                and refusal['refusal'].get('report', {}).get('terminalFailure')
                    == {'owner': 'platform', 'reason': 'resource-exhausted'}, 'audit-native-exact-refused-startup')

    def preflight(self, archive):
        names = archive.namelist()
        require(len(names) == len(set(names)) == len(MEMBERS) == 32 and set(names) == MEMBERS,
                'audit-native-closed-archive-members')
        total = 0
        for name in names:
            row = archive.getinfo(name)
            maximum = SELECTED.get(name, 4 * 1024**2)
            require(not row.is_dir() and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG)
                    and 0 <= row.file_size <= maximum, 'audit-native-archive-member-bound')
            total += row.file_size
        require(total <= 400 * 1024**2, 'audit-native-archive-expanded-bound')
        exact = RECEIPTS | {'native-binaries/' + name: identity for name, identity in PRODUCTS.items()}
        require(all(archive.getinfo(name).file_size == identity['bytes'] for name, identity in exact.items()),
                'audit-native-fixed-member-preflight-length')
        return {name: {'bytes': archive.getinfo(name).file_size,
                       'compressedBytes': archive.getinfo(name).compress_size} for name in SELECTED}

    def extract(self, archive, name, destination):
        path = PurePosixPath(name)
        require(name in SELECTED and str(path) == name and not path.is_absolute()
                and '..' not in path.parts and '\\' not in name, 'audit-native-selected-member-only')
        row = archive.getinfo(name)
        require(not row.is_dir() and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG)
                and 0 < row.file_size <= SELECTED[name], 'audit-native-selected-member-bound')
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with archive.open(row) as source, destination.open('xb') as target:
            count = 0
            while raw := source.read(1024**2):
                count += len(raw)
                require(count <= SELECTED[name], 'audit-native-selected-expanded-bound')
                target.write(raw)
        require(count == row.file_size, 'audit-native-selected-expanded-length')
        destination.chmod(0o600)

    def native_products(self, prepared):
        return {name: prepared / 'native-binaries' / name for name in PRODUCTS}

    def verify_prepared(self, prepared):
        self.receipt_preimages(prepared)
        record, snapshot = read_json(prepared / 'receipt.json'), read_json(prepared / 'source-inputs.json')
        self.validate_record(record, snapshot, git_source_identity(SOURCE), self._git_materials())
        for name, expected in PRODUCTS.items():
            require(file_identity(prepared / 'native-binaries' / name, PRODUCT_LIMITS[name]) == expected,
                    'audit-native-fixed-product-bytes')
        return {'schemaVersion': 'latent.audit.two-native-hosts.v1', 'compiledSource': SOURCE,
            'producerRun': RUN, 'producerJob': JOB, 'artifact': ARTIFACT, 'products': PRODUCTS,
            'signedGuestQualification': False, 'guestSourceCompiled': False,
            'currentDevelopmentNativeCompilationClaimed': False, 'compositeNativeTupleCreated': False}

    def prepare(self, output):
        require(sys.platform == 'linux', 'audit-native-linux-required')
        artifact = self._official_artifact()
        output = fresh(output)
        with _official_archive(artifact) as (archive, remote):
            selected = self.preflight(archive)
            for name in SELECTED:
                self.extract(archive, name, output / name)
                if name in RECEIPTS:
                    require(file_identity(output / name) == RECEIPTS[name], 'audit-native-receipt-preimage')
            result = self.verify_prepared(output)
            for name in PRODUCTS:
                (output / 'native-binaries' / name).chmod(0o700)
        result['retrieval'] = {'wholeArchiveRetained': False,
            'archiveDigestVerification': 'official-metadata-only-selected-members-hash-verified',
            'fixedMembersPreflighted': selected, 'rangeBytes': remote.transferred, 'rangeRequests': remote.requests}
        write_json(output / 'retrieval.json', result)
        return result


READER = _FrozenAuditHosts()
prepare = READER.prepare
verify_prepared = READER.verify_prepared
native_products = READER.native_products

HELPERS = ('package', 'capsule_contracts', 'capsule_authoring')


def _historical_helper_record(prepared):
    from tools import rust_thread_native_products as original
    reader = original.READER
    reader.receipt_preimages(prepared)
    record = read_json(prepared / 'native-products.json')
    snapshot = read_json(prepared / 'source-inputs.json')
    # All original193 source/control/recipe guards still run. Only the exact
    # three helper products are copied; neither obsolete CLI nor node is fetched.
    reader.validate_record(record, snapshot, git_source_identity(original.SOURCE), reader._git_materials())
    return original, record


def verify_historical_helpers(prepared):
    original, record = _historical_helper_record(prepared)
    products = {}
    for name in HELPERS:
        expected = record['products']['examples/' + name]
        require(file_identity(prepared / 'native' / name, 512 * 1024**2) == expected,
                'audit-native-three-original-helper-bytes')
        products[name] = expected
    return {'schemaVersion': 'latent.audit.three-original-helpers.v1', 'compiledSource': original.SOURCE,
        'producerRun': original.RUN, 'producerJob': original.JOB, 'artifact': original.ARTIFACT,
        'products': products, 'original193ReceiptRewritten': False, 'nativeRebuilt': False,
        'compositeNativeTupleCreated': False}


def prepare_historical_helpers(output):
    require(sys.platform == 'linux', 'audit-native-linux-required')
    from tools import rust_thread_native_products as original
    reader = original.READER
    artifact = reader._official_artifact()
    output = fresh(output)
    with _official_archive(artifact) as (archive, remote):
        reader.preflight(archive)
        for name in original.RECEIPTS:
            reader.extract(archive, name, output / name)
        _historical_helper_record(output)
        for name in HELPERS:
            target = output / 'native' / name
            reader.extract(archive, 'native-binaries/examples-' + name, target)
            target.chmod(0o700)
        result = verify_historical_helpers(output)
        result['retrieval'] = {'wholeArchiveRetained': False,
            'archiveDigestVerification': 'official-metadata-only-selected-members-hash-verified',
            'rangeBytes': remote.transferred, 'rangeRequests': remote.requests}
    write_json(output / 'retrieval.json', result)
    return result
