"""One immutable Linux operator frontend; independent from native277 origins."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import stat
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.audit_memory_native_products import _official_archive
from tools.sdk_native_products_reader import FrozenNativeProducts
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import fresh, write_json

SOURCE = '380c7df8f26ec3f0f6e54d616e8d08b80cb5cc73'
RUN, JOB = 39938568296, 120364086172
BRANCH = 'feat/stream-operator-lifecycle-20261023'
ARTIFACT = {'id': 12494847186, 'size_in_bytes': 25761049,
            'digest': 'sha256:955f0ebbd0195f244e6959f3dcb891e185da700a30d2a4358855fc08a5db1b1d'}
RECEIPTS = {
    'build.json': {'bytes': 27123, 'sha256': 'sha256:16c2bdf2d5904a8ba677bbeb0a79c8d4f5b4026a39ad898fd450c2b20b17f742'},
    'python-inventory.json': {'bytes': 14791, 'sha256': 'sha256:7b1238449734aa3ace88172368b5fd4fd6b1292d7ade00ce76d08a6f05169f01'}}
FRONTEND = {'bytes': 3045240, 'sha256': 'sha256:f2ba2bd3ada199e468f0a33990c6ecf925c6189a5c3226c580f32ee3a278fa71'}
MAXIMUM_FILE = 64 * 1024**2
MAXIMUM_EXPANDED = 64 * 1024**2


def _json(raw, identity):
    require(type(raw) is bytes and len(raw) == identity['bytes']
            and 'sha256:' + hashlib.sha256(raw).hexdigest() == identity['sha256'],
            'operator-frontend-exact-receipt-preimage')
    return json.loads(raw)


def manifest(raw):
    value = _json(raw, RECEIPTS['build.json'])
    require(value.get('schemaVersion') == 'latent.dev.frontend-build.v1'
            and value.get('sourceCommit') == SOURCE and value.get('sourceDirty') is False
            and value.get('target') == 'linux-x86_64'
            and value.get('publisherAuthenticated') is False
            and value.get('qualification') == 'native-frontend-smoke-only'
            and value.get('frontendSha256') == FRONTEND['sha256'],
            'operator-frontend-fixed-source-and-target')
    files = value.get('files')
    require(type(files) is dict and len(files) == 153
            and files.get('dist/latent-dev/latent-dev') == {'size': FRONTEND['bytes'], 'sha256': FRONTEND['sha256']},
            'operator-frontend-fixed-product-inventory')
    for name, row in files.items():
        path = PurePosixPath(name)
        require(type(name) is str and str(path) == name and not path.is_absolute()
                and '..' not in path.parts and '\\' not in name
                and type(row) is dict and set(row) == {'size', 'sha256'}
                and type(row['size']) is int and 0 <= row['size'] <= MAXIMUM_FILE,
                'operator-frontend-closed-file-bound')
    smoke = value.get('streamOperatorSmoke', {})
    require(smoke.get('passed') is True and smoke.get('outsideCheckout') is True
            and smoke.get('realLatentd') is False and smoke.get('providerReadiness') == 'not-observed',
            'operator-frontend-original-smoke-is-process-double')
    return value


class FrozenOperatorFrontend(FrozenNativeProducts):
    """Use the existing completed-origin guards with one closed artifact tuple."""
    def __init__(self):
        super().__init__(source=SOURCE, run=RUN, job=JOB, artifact=ARTIFACT,
                         receipts=RECEIPTS, branch=BRANCH, stages=('frozen-frontend-packaging',))

    def _pins(self):
        require((self.source, self.run, self.job, self.branch, self.event) == (SOURCE, RUN, JOB, BRANCH, 'push')
                and self.artifact == ARTIFACT and self.receipts == RECEIPTS
                and self.stages == ('frozen-frontend-packaging',) and self.include_protocol is False,
                'operator-frontend-fixed-completed-origin')

    def _producer_origin(self):
        return ('.github/workflows/stream-operator-packaging.yml',
                'Stream operator frontend (ubuntu-24.04)', 'stream-operator-frontend-ubuntu-24.04-')

    def preflight(self, archive):
        info = archive.getinfo('build.json')
        require(info.file_size == RECEIPTS['build.json']['bytes']
                and info.compress_size <= info.file_size + 65536 and not info.flag_bits & 1
                and not info.is_dir() and stat.S_IFMT(info.external_attr >> 16) in (0, stat.S_IFREG),
                'operator-frontend-receipt-length')
        value = manifest(archive.read(info))
        expected = value['files'] | {'build.json': {'size': RECEIPTS['build.json']['bytes'],
                                                    'sha256': RECEIPTS['build.json']['sha256']}}
        names = archive.namelist()
        require(len(names) == len(set(names)) == 154 and set(names) == set(expected),
                'operator-frontend-closed-archive-members')
        total = 0
        for name, row in expected.items():
            entry = archive.getinfo(name)
            require(not entry.is_dir() and stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG)
                    and not entry.flag_bits & 1 and entry.file_size == row['size']
                    and entry.compress_size <= row['size'] + 65536, 'operator-frontend-fixed-member')
            total += entry.file_size
        require(total == 58401986 and total <= MAXIMUM_EXPANDED, 'operator-frontend-expanded-bound')
        return expected

    def extract(self, archive, output):
        expected = self.preflight(archive)
        for name, row in expected.items():
            target = output / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            checksum, used = hashlib.sha256(), 0
            with archive.open(name) as source, target.open('xb') as destination:
                while raw := source.read(1024**2):
                    used += len(raw)
                    require(used <= row['size'], 'operator-frontend-member-expanded-bound')
                    checksum.update(raw)
                    destination.write(raw)
            require(used == row['size'] and 'sha256:' + checksum.hexdigest() == row['sha256'],
                    'operator-frontend-original-product-bytes')
            target.chmod(0o600)

    def verify_prepared(self, prepared):
        self._pins()
        self.receipt_preimages(prepared)
        value = manifest((prepared / 'build.json').read_bytes())
        _json((prepared / 'python-inventory.json').read_bytes(), RECEIPTS['python-inventory.json'])
        expected = set(value['files']) | {'build.json'}
        observed = set()
        directories = 0
        for parent, children, names in os.walk(prepared, followlinks=False):
            for name in children:
                path = Path(parent) / name
                require(not path.is_symlink() and not path.is_junction(), 'operator-frontend-prepared-links-denied')
                directories += 1
                require(directories <= 128, 'operator-frontend-prepared-directory-bound')
            for name in names:
                path = Path(parent) / name
                require(not path.is_symlink() and not path.is_junction(), 'operator-frontend-prepared-links-denied')
                observed.add(path.relative_to(prepared).as_posix())
                require(len(observed) <= 155, 'operator-frontend-prepared-file-bound')
        require(expected <= observed <= expected | {'retrieval.json'}, 'operator-frontend-closed-prepared-files')
        for name, identity in value['files'].items():
            require(file_identity(prepared / name, MAXIMUM_FILE) == {
                'bytes': identity['size'], 'sha256': identity['sha256']}, 'operator-frontend-original-product-bytes')
        return {'schemaVersion': 'latent.stream-operator.frontend-origin.v1', 'compiledSource': SOURCE,
                'producerRun': RUN, 'producerJob': JOB, 'artifact': ARTIFACT,
                'frontend': FRONTEND, 'fileInventoryRows': 153, 'originalPackagingRealLatentd': False,
                'nativeRebuilt': False, 'publisherAuthenticationClaimed': False}

    def frontend(self, prepared):
        return prepared / 'dist/latent-dev/latent-dev'

    def prepare(self, output):
        require(sys.platform == 'linux', 'operator-frontend-linux-required')
        artifact = self._official_artifact()
        output = fresh(output)
        with _official_archive(artifact) as (archive, remote):
            self.extract(archive, output)
            result = self.verify_prepared(output)
            self.frontend(output).chmod(0o700)
            result['retrieval'] = {'wholeArchiveRetained': False,
                'archiveDigestVerification': 'official-metadata-only-every-selected-member-hash-verified',
                'rangeBytes': remote.transferred, 'rangeRequests': remote.requests}
        write_json(output / 'retrieval.json', result)
        return result


READER = FrozenOperatorFrontend()
