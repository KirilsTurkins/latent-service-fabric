"""Fixed-member, source-bound acquisition for explicitly pinned native producers."""
from __future__ import annotations

import copy
import hashlib
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.java_replay_materials import api, git_source_identity, NoRedirect, Ranges, REPOSITORY
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json

WORKFLOW = '.github/workflows/sdk-native-products.yml'
PRODUCTS = ('latent', 'latentd', 'examples/package', 'examples/capsule_contracts', 'examples/capsule_authoring')
MATERIALS = (WORKFLOW, '.cargo/managed-guest.toml', 'tools/qualify_rust_capsules.py',
             'tools/toolchain.toml', 'tools/rust_capsule_build.py', 'tools/build_observation.py',
             'tools/build_process.py', 'tools/build_process_linux.py')
ALLOWED = {'native-products.json': 1024**2, 'source-inputs.json': 1024**2} | {
    'native-binaries/' + name.replace('/', '-'): 512*1024**2 for name in PRODUCTS}


def _identity(value):
    return (type(value) is dict and set(value) == {'sha256', 'bytes'}
            and type(value['sha256']) is str and re.fullmatch(r'sha256:[0-9a-f]{64}', value['sha256'])
            and type(value['bytes']) is int and 0 < value['bytes'] <= 512*1024**2)


class FrozenNativeProducts:
    """One explicit, immutable-producer configuration; never select a branch tip.

    The original HTTP8f consumer remains independently frozen. This shared reader
    retains its fixed members, source/material verification, limits and origin
    checks for later exact tuples without copying another acquisition algorithm.
    """
    def __init__(self, *, source, run, job, artifact, receipts, branch, stages, event='push', include_protocol=False):
        require(type(source) is str and re.fullmatch(r'[0-9a-f]{40}', source)
            and type(run) is int and run > 0 and type(job) is int and job > 0
            and type(branch) is str and re.fullmatch(r'[A-Za-z0-9._/-]{1,128}', branch)
            and type(event) is str and event in ('push', 'workflow_dispatch')
            and type(include_protocol) is bool
            and type(stages) is tuple and 0 < len(stages) <= 32
            and len(set(stages)) == len(stages)
            and all(type(stage) is str and re.fullmatch(r'[a-z0-9-]{1,80}', stage) for stage in stages),
            'sdk-native-frozen-configuration')
        self.source, self.run, self.job, self.branch = source, run, job, branch
        self.stages, self.event = stages, event
        self.include_protocol = include_protocol
        # Own detached data so callers cannot mutate the original pin dictionaries.
        self.artifact, self.receipts = copy.deepcopy(artifact), copy.deepcopy(receipts)
        self._pins()
    def validate_record(self, record, snapshot, native, materials):
        require(type(record) is dict and set(record) == {'schemaVersion', 'status', 'sourceRevision', 'source',
            'materials', 'compiler', 'products', 'commands', 'profile', 'signedQualification',
            'guestComponentsCompiled', 'historicalReceiptRewritten'}, 'sdk-native-record-fields')
        require(record['schemaVersion'] == 'latent.sdk.native-products.v1' and record['status'] == 'built'
            and record['sourceRevision'] == self.source and record['source'] == native
            and record['materials'] == materials and snapshot == {'native': native, 'materials': materials},
            'sdk-native-source-or-materials')
        require(record['profile'] == 'normal-managed-guest-default-features'
            and record['signedQualification'] is False and record['guestComponentsCompiled'] is False
            and record['historicalReceiptRewritten'] is False and type(record['compiler']) is str
            and record['compiler'].startswith('rustc 1.97.1 ('), 'sdk-native-profile-not-qualification')
        products = record['products']
        require(type(products) is dict and set(products) == set(PRODUCTS)
            and all(_identity(value) for value in products.values()), 'sdk-native-five-products')
        commands = record['commands']
        require(type(commands) is list and len(commands) == len(self.stages), 'sdk-native-command-count')
        for row, stage in zip(commands, self.stages):
            require(type(row) is dict and set(row) == {'stage', 'exitCode', 'seconds'}
                and row['stage'] == stage and type(row['exitCode']) is int and row['exitCode'] == 0
                and type(row['seconds']) in (int, float) and math.isfinite(row['seconds'])
                and 0 <= row['seconds'] <= 1320, 'sdk-native-command-outcome')
        require(sum(row['seconds'] for row in commands) <= 1320.001,
            'sdk-native-overall-command-bound')

    def _git_materials(self):
        """One bounded Git batch binds all actual auxiliary compile-input trees."""
        trees = {'wit': (2048, 8*1024**2), 'schemas': (256, 4*1024**2),
                 'examples/echo-contract/wit': (128, 1024**2)}
        # Historical tuples retain exactly their original auxiliary tree set.
        # New generated-RPC producers opt in before freezing immutable pins.
        if self.include_protocol:
            trees['api/proto'] = (128, 1024**2)
        raw = subprocess.check_output(['git', 'ls-tree', '-rz', self.source, '--',
            *MATERIALS, *trees], cwd=ROOT, timeout=30)
        require(len(raw) <= 1024**2, 'sdk-native-material-tree-bound')
        entries, counts, sizes = [], dict.fromkeys(trees, 0), dict.fromkeys(trees, 0)
        for item in raw.rstrip(b'\0').split(b'\0'):
            metadata, name = item.split(b'\t')
            mode, kind, oid = metadata.decode('ascii').split()
            name = name.decode('utf-8')
            require(mode in ('100644', '100755') and kind == 'blob'
                and PurePosixPath(name).as_posix() == name and '..' not in PurePosixPath(name).parts
                and not PurePosixPath(name).is_absolute(), 'sdk-native-material-regular')
            require(name in MATERIALS or any(name.startswith(tree+'/') for tree in trees),
                'sdk-native-material-scope')
            entries.append((name, oid))
        names = [name for name, _ in entries]
        require(set(MATERIALS) <= set(names) and len(names) == len(set(names))
            and 0 < len(names) <= len(MATERIALS)+sum(cap[0] for cap in trees.values()),
            'sdk-native-material-file-bound')
        data = subprocess.run(['git', 'cat-file', '--batch'],
            input=''.join(oid+'\n' for _, oid in entries).encode(), stdout=subprocess.PIPE,
            check=True, cwd=ROOT, timeout=60).stdout
        require(len(data) <= 16*1024**2, 'sdk-native-material-batch-bound')
        result, position = {}, 0
        for name, oid in entries:
            line = data.index(b'\n', position)
            header = data[position:line].decode('ascii').split()
            require(len(header) == 3 and header[:2] == [oid, 'blob'],
                'sdk-native-material-Git-header')
            size = int(header[2]);position = line+1
            maximum = 1024**2 if name in MATERIALS else next(
                cap[1] for tree, cap in trees.items() if name.startswith(tree+'/'))
            require(0 < size <= maximum and position+size < len(data),
                'sdk-native-material-Git-bound')
            payload = data[position:position+size]
            require(hashlib.sha1(b'blob '+str(size).encode()+b'\0'+payload).hexdigest() == oid
                and data[position+size:position+size+1] == b'\n',
                'sdk-native-material-Git-identity')
            result[name] = {'sha256': 'sha256:'+hashlib.sha256(payload).hexdigest(), 'bytes': size}
            for tree, (count_cap, byte_cap) in trees.items():
                if name.startswith(tree+'/'):
                    counts[tree] += 1;sizes[tree] += size
                    require(counts[tree] <= count_cap and sizes[tree] <= byte_cap,
                        'sdk-native-material-tree-cap')
            position += size+1
        require(position == len(data) and all(counts.values()), 'sdk-native-material-complete')
        return dict(sorted(result.items()))

    def _pins(self):
        require(type(self.artifact) is dict and set(self.artifact) == {'id', 'size_in_bytes', 'digest'}
            and type(self.artifact['id']) is int and self.artifact['id'] > 0
            and type(self.artifact['size_in_bytes']) is int and 0 < self.artifact['size_in_bytes'] <= 1024**3
            and type(self.artifact['digest']) is str
            and re.fullmatch(r'sha256:[0-9a-f]{64}', self.artifact['digest'])
            and type(self.receipts) is dict and set(self.receipts) == {'native-products.json', 'source-inputs.json'}
            and all(_identity(value) and value['bytes'] <= 1024**2 for value in self.receipts.values()),
            'sdk-native-completed-producer-pins-required')

    def preflight(self, archive):
        names = archive.namelist()
        require(len(names) <= 20000 and len(names) == len(set(names)), 'sdk-native-archive-index')
        result = {}
        for name, maximum in ALLOWED.items():
            row = archive.getinfo(name)
            require(0 < row.file_size <= maximum and not row.is_dir()
                and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG),
                'sdk-native-fixed-member-preflight')
            result[name] = {'bytes': row.file_size, 'compressedBytes': row.compress_size}
        return result

    def extract(self, archive, name, destination):
        path = PurePosixPath(name)
        require(name in ALLOWED and str(path) == name and not path.is_absolute()
            and '..' not in path.parts and '\\' not in name, 'sdk-native-fixed-member-only')
        row = archive.getinfo(name)
        require(0 < row.file_size <= ALLOWED[name] and not row.is_dir()
            and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG), 'sdk-native-member-type')
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with archive.open(row) as source, destination.open('xb') as target:
            count = 0
            while raw := source.read(1024**2):
                count += len(raw)
                require(count <= ALLOWED[name], 'sdk-native-expanded-bound')
                target.write(raw)
        require(count == row.file_size, 'sdk-native-expanded-length')
        destination.chmod(0o600)

    def _official_artifact(self):
        self._pins()
        run, job = api(f'actions/runs/{self.run}'), api(f'actions/jobs/{self.job}')
        require(run['id'] == self.run and run['head_sha'] == self.source and run['path'] == WORKFLOW
            and run['event'] == self.event and run['head_branch'] == self.branch
            and run['status'] == 'completed' and run['conclusion'] == 'success'
            and job['id'] == self.job and job['run_id'] == self.run and job['head_sha'] == self.source
            and job['name'] == 'Build and retain five source-bound native products'
            and job['status'] == 'completed' and job['conclusion'] == 'success',
            'sdk-native-official-producer')
        listing = api(f'actions/runs/{self.run}/artifacts?per_page=100')
        require(listing['total_count'] == len(listing['artifacts']) <= 100, 'sdk-native-artifact-pages')
        selected = [a for a in listing['artifacts'] if a['name'] == 'sdk-native-products-' + self.source]
        require(len(selected) == 1, 'sdk-native-unique-artifact')
        artifact = selected[0]
        require(type(artifact['id']) is int and artifact['id'] > 0 and not artifact['expired']
            and type(artifact['size_in_bytes']) is int and 0 < artifact['size_in_bytes'] <= 1024**3
            and type(artifact['digest']) is str and re.fullmatch(r'sha256:[0-9a-f]{64}', artifact['digest'])
            and artifact['workflow_run']['id'] == self.run and artifact['workflow_run']['head_sha'] == self.source,
            'sdk-native-artifact-origin')
        require(all(artifact[key] == value for key, value in self.artifact.items()),
            'sdk-native-fixed-artifact')
        return artifact

    def native_products(self, prepared):
        return {('capsule_authoring' if name == 'examples/capsule_authoring' else name.split('/')[-1]):
                prepared/'native'/name.replace('/', '-') for name in PRODUCTS}

    def receipt_preimages(self, prepared):
        self._pins()
        for name, expected in self.receipts.items():
            require(file_identity(prepared/name) == expected, 'sdk-native-receipt-preimage')

    def verify_prepared(self, prepared):
        self.receipt_preimages(prepared)
        record, snapshot = read_json(prepared/'native-products.json'), read_json(prepared/'source-inputs.json')
        self.validate_record(record, snapshot, git_source_identity(self.source), self._git_materials())
        retained = read_json(prepared/'retrieval.json')
        require(retained['schemaVersion'] == 'latent.sdk.phase-native-products.v1'
            and retained['compiledSource'] == self.source and retained['producerRun'] == self.run
            and retained['producerJob'] == self.job and retained['signedQualification'] is False
            and retained['guestComponentsCompiledByProducer'] is False
            and retained['historicalNormalReceiptCreated'] is False
            and retained['compiledTree'] == subprocess.check_output(['git', 'rev-parse', self.source+'^{tree}'],
                cwd=ROOT, text=True, timeout=30).strip()
            and retained['producerReceipt'] == file_identity(prepared/'native-products.json')
            and retained['sourceSnapshot'] == file_identity(prepared/'source-inputs.json')
            and retained['products'] == record['products']
            and retained['origin']['artifact'] == self.artifact['id']
            and retained['origin']['archiveDigest'] == self.artifact['digest'], 'sdk-native-retained-record-drift')
        for name, expected in record['products'].items():
            require(file_identity(prepared/'native'/name.replace('/', '-'), 512*1024**2) == expected,
                'sdk-native-product-drift')
        return retained

    def prepare(self, output):
        require(sys.platform == 'linux', 'sdk-native-linux-required')
        artifact = self._official_artifact()
        output = fresh(output)
        token = os.environ.get('GH_TOKEN')
        require(bool(token), 'sdk-native-explicit-actions-token')
        request = urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}/zip',
            headers={'Authorization': 'Bearer ' + token})
        try:
            urllib.request.build_opener(NoRedirect).open(request, timeout=30)
        except urllib.error.HTTPError as error:
            require(error.code == 302, 'sdk-native-redirect')
            url = error.headers['Location']
        else:
            raise ValueError('sdk-native-redirect-required')
        require(url.startswith('https://'), 'sdk-native-https')
        remote = Ranges(url, artifact['size_in_bytes'])
        with zipfile.ZipFile(remote) as archive:
            selected = self.preflight(archive)
            for name in ('native-products.json', 'source-inputs.json'):
                self.extract(archive, name, output/name)
            self.receipt_preimages(output)
            record, snapshot = read_json(output/'native-products.json'), read_json(output/'source-inputs.json')
            self.validate_record(record, snapshot, git_source_identity(self.source), self._git_materials())
            for name in PRODUCTS:
                target = output/'native'/name.replace('/', '-')
                self.extract(archive, 'native-binaries/'+name.replace('/', '-'), target)
                require(file_identity(target, 512*1024**2) == record['products'][name],
                    'sdk-native-original-product')
                target.chmod(0o700)
        result = {'schemaVersion': 'latent.sdk.phase-native-products.v1', 'compiledSource': self.source,
            'compiledTree': subprocess.check_output(['git', 'rev-parse', self.source+'^{tree}'], cwd=ROOT,
                text=True, timeout=30).strip(), 'producerRun': self.run, 'producerJob': self.job,
            'producerReceipt': file_identity(output/'native-products.json'),
            'sourceSnapshot': file_identity(output/'source-inputs.json'), 'products': record['products'],
            'signedQualification': False, 'guestComponentsCompiledByProducer': False,
            'historicalNormalReceiptCreated': False, 'wholeArchiveRetained': False,
            'origin': {'artifact': artifact['id'], 'archiveDigest': artifact['digest'],
                'archiveDigestVerification': 'official-metadata-only-selected-members-hash-verified',
                'fixedMembersPreflighted': selected, 'rangeBytes': remote.transferred, 'rangeRequests': remote.requests}}
        write_json(output/'retrieval.json', result)
        require(self.verify_prepared(output) == result, 'sdk-native-final-recheck')
        return result
