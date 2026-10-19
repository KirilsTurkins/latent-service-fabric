"""Source-bound Go private capture and approved generation without native recompilation."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
from types import SimpleNamespace
import urllib.error
import urllib.request
import zipfile
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_rust_capsules import inputs
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, inventory, read_file, read_json, write_json
ORIGINAL_HEAD = '3050cd9d33d74eed5d746f13fbb0e9125376a3b3'
ORIGINAL_RUN = 39298177972
ORIGINAL_JOB = 118216070006
REPOSITORY = 'KirilsTurkins/latent-service-fabric'
ARTIFACTS = {'products': (12211733679, 266925280, 'sha256:2a9dd9ea62dcc4e367f413533b6d64c935f5c4c1ba5edeb17493172876821651'),
    'tools': (12209174521, 81715219, 'sha256:4c8419d5c40fcfa5082af8c8c0dddf0d6089833c23dfc386192c8766434a4395')}
PRODUCTS = ('latent', 'latentd', 'examples/capsule_contracts', 'examples/package', 'examples/capsule_authoring')
UNUSED_ORIGINAL_PRODUCTS = ('examples/go_runtime_probe',)
COMPANIONS = tuple(TEMPLATES)
MAX_DOCUMENT = 4 * 1024**2
ORIGINAL_QUALIFICATION_DIGEST = 'sha256:ab8a39c9010649aa3f13a06f6d7db74276bbfd6b21c9fc8edcd683ec579bbfcc'
BUILD_FILES = ('BUILD-COMPLETE.json', 'build-observation.json', 'source-inputs.json',
               'recipe-inputs.json', 'package-inputs.json', 'package-source.json', 'deployment.json')

def safe_name(name):
    require(isinstance(name, str) and bool(name), 'replay-artifact-member-path')
    path = PurePosixPath(name)
    require(bool(path.parts) and '\\' not in name
            and not path.is_absolute() and '..' not in path.parts
            and str(path) == name and ':' not in name, 'replay-artifact-member-path')
    return path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Ranges(io.RawIOBase):
    def __init__(self, url, size):
        self.url, self.size, self.position, self.transferred, self.requests = url, size, 0, 0, 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        require(whence in (0, 1, 2), 'replay-zip-seek-kind')
        self.position = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        require(0 <= self.position <= self.size, 'replay-zip-seek-bound')
        return self.position

    def read(self, count=-1):
        if count == -1:
            count = self.size - self.position
        require(0 <= count <= 8 * 1024**2, 'replay-range-byte-bound')
        count = min(count, self.size - self.position)
        if not count:
            return b''
        self.requests += 1
        self.transferred += count
        require(self.requests <= 4096 and self.transferred <= 2 * self.size, 'replay-total-range-bound')
        end = self.position + count - 1
        request = urllib.request.Request(self.url, headers={'Range': f'bytes={self.position}-{end}'})
        with urllib.request.urlopen(request, timeout=30) as response:
            require(response.status == 206 and response.headers['Content-Range']
                    == f'bytes {self.position}-{end}/{self.size}', 'replay-range-response')
            raw = response.read(count + 1)
        require(len(raw) == count, 'replay-range-length')
        self.position += count
        return raw


def api(path):
    raw = subprocess.check_output(['gh', 'api', 'repos/' + REPOSITORY + '/' + path], timeout=30)
    require(len(raw) <= MAX_DOCUMENT, 'replay-api-byte-bound')
    return json.loads(raw)


class Artifact:
    def __init__(self, kind):
        require(kind in ARTIFACTS, 'replay-fixed-artifact-kind')
        artifact, size, expected_digest = ARTIFACTS[kind]
        self.metadata = api(f'actions/artifacts/{artifact}')
        run = self.metadata['workflow_run']
        require(self.metadata['id'] == artifact and self.metadata['size_in_bytes'] == size
                and self.metadata['digest'] == expected_digest and not self.metadata['expired'] and run['id'] == ORIGINAL_RUN
                and run['head_sha'] == ORIGINAL_HEAD, 'replay-artifact-source-binding')
        token = os.environ.get('GH_TOKEN')
        require(bool(token), 'replay-explicit-actions-read-token-required')
        request = urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{artifact}/zip',
            headers={'Authorization': 'Bearer ' + token})
        try:
            urllib.request.build_opener(NoRedirect).open(request, timeout=30)
        except urllib.error.HTTPError as error:
            require(error.code == 302, 'replay-artifact-redirect')
            url = error.headers['Location']
        else:
            raise ValueError('replay-artifact-redirect-required')
        require(url.startswith('https://'), 'replay-artifact-https-required')
        self.remote = Ranges(url, size)
        self.archive = zipfile.ZipFile(self.remote)
        names = self.archive.namelist()
        require(len(names) <= 20000 and len(names) == len(set(names)), 'replay-artifact-entry-bound')
        self.selected = {}

    def extract(self, name, output, maximum=MAX_DOCUMENT):
        safe_name(name)
        row = self.archive.getinfo(name)
        require(0 < row.file_size <= maximum and not row.is_dir()
                and stat.S_IFMT(row.external_attr >> 16) in {0, stat.S_IFREG}, 'replay-member-type-or-byte-bound')
        output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        hasher, size = hashlib.sha256(), 0
        with self.archive.open(row) as source, output.open('xb') as target:
            while raw := source.read(1024 * 1024):
                size += len(raw)
                require(size <= maximum, 'replay-member-expanded-bound')
                hasher.update(raw)
                target.write(raw)
        require(size == row.file_size, 'replay-member-size-mismatch')
        output.chmod(0o600)
        self.selected[name] = {'sha256': 'sha256:' + hasher.hexdigest(), 'bytes': size}
        return output

    def summary(self):
        return {'id': self.metadata['id'], 'digest': self.metadata['digest'],
                'selected': self.selected, 'networkBytes': self.remote.transferred}


def retrieve_build(artifact, template, prepared, expected):
    require(template in COMPANIONS, 'go-replay-fixed-companion-only')
    output = prepared / 'builds' / template
    output.mkdir(mode=0o700, parents=True)
    prefix = 'go-capsule-authoring/builds/' + template + '/'
    for name in BUILD_FILES:
        artifact.extract(prefix + name, output / name)
    require(read_json(output / 'BUILD-COMPLETE.json') == expected, 'go-replay-original-build-marker')
    layers = read_json(output / 'package-source.json')['layers']
    require(1 <= len(layers) <= 32, 'go-replay-package-layer-count')
    allowed = {'component.wasm', 'capsule.json', 'contracts.json', 'wit-lock.json', 'compatibility-report.json',
               'wit/world.wit', 'wit/deps/clock/package.wit', 'wit/deps/random/package.wit',
               'wit/deps/http-v2/package.wit', 'wit/deps/http/package.wit'}
    observed = {'package-source.json': (output / 'package-source.json').read_bytes()}
    for layer in layers:
        name = layer['source']
        require(name in allowed and layer['path'] == name and name not in observed,
                'go-replay-fixed-package-layer')
        artifact.extract(prefix + name, output / name, 64*1024**2 if name == 'component.wasm' else MAX_DOCUMENT)
        observed[name] = (output / name).read_bytes()
    require(inventory(observed) == (output / 'package-inputs.json').read_bytes()
            and digest(observed['component.wasm']) == expected['componentDigest']
            and digest((output / 'build-observation.json').read_bytes()) == expected['observationDigest']
            and digest((output / 'source-inputs.json').read_bytes()) == expected['sourceDigest'],
            'go-replay-original-package-input-identity')
    observation = read_json(output / 'build-observation.json')
    package = (output / 'package-inputs.json').read_bytes()
    require([row for row in observation['materials'] if row['name'] == 'package-inputs']
            == [{'name': 'package-inputs', 'digest': digest(package), 'size': len(package)}],
            'go-replay-original-package-material')


ORIGINAL_QUALIFIER_DIGEST = 'sha256:1ae0dcad6739fa1f6871d5317f6a3bb6a9ebba9bf8a76b99f436ab79caebcd9c'
ORIGINAL_QUALIFIER_BYTES = 34254
AUTHORING_SOURCE = 'tools/go_application_dependencies.py'
ORIGINAL_AUTHORING_BLOB = '92b917a1629ecfe3c57a8c781b7104c48ec91c25'
ORIGINAL_AUTHORING_IDENTITY = {'sha256': 'sha256:556e773b805fc1c30bb232bbed80e7d32374f72053ca038b668418b924338dda',
                              'bytes': 29568}


def authoring_delta(current):
    before = b"netrc.write_text('machine ' + proxy.hostname + ' login ' + username + ' password ' + secret + '\\n')"
    after = before.replace(b'proxy.hostname', b'proxy.netloc')
    old_guard = b'or proxy.username or proxy.password or proxy.query'
    new_guard = b'or proxy.username is not None or proxy.password is not None or proxy.query'
    require(current.count(after) == current.count(new_guard) == 1, 'go-replay-exact-netrc-authority-fix')
    original = current.replace(after, before, 1).replace(new_guard, old_guard, 1)
    require({'sha256': digest(original), 'bytes': len(original)} == ORIGINAL_AUTHORING_IDENTITY,
            'go-replay-unreviewed-authoring-source-change')
    return {'path': AUTHORING_SOURCE, 'original': ORIGINAL_AUTHORING_IDENTITY,
            'selected': {'sha256': digest(current), 'bytes': len(current)},
            'scope': 'exact NETRC HTTPS authority including selected port; all URL userinfo denied; no SDK/compiler change'}


def qualifier_delta(current):
    before = b'ROOT, TEMPLATES, create, digest, fresh, read_json, write_json'
    after = b'ROOT, TEMPLATES, create, digest, fresh, read_file, read_json, write_json'
    require(current.count(after) == 1, 'generator-replay-exact-reader-import')
    original = current.replace(after, before, 1)
    require(digest(original) == ORIGINAL_QUALIFIER_DIGEST and len(original) == ORIGINAL_QUALIFIER_BYTES,
            'generator-replay-unreviewed-qualifier-change')
    return {'sha256': digest(original), 'bytes': len(original)}


def expected_original_inputs():
    value = inputs('go')
    value['helpers']['qualify_rust_capsules.py'] = qualifier_delta(
        (ROOT / 'tools/qualify_rust_capsules.py').read_bytes())
    value['helpers']['go_application_dependencies.py'] = authoring_delta(
        (ROOT / AUTHORING_SOURCE).read_bytes())['original']
    return value


def owned_output(output):
    require(output != ROOT and ROOT not in output.parents, 'go-replay-output-outside-source')
    return fresh(output)


def selected_products(receipt):
    require(set(receipt['binaries']) == set(PRODUCTS + UNUSED_ORIGINAL_PRODUCTS),
            'go-replay-exact-original-native-inventory')
    return {name: receipt['binaries'][name] for name in PRODUCTS}


def production_name(name):
    from tools.go_capsule_build import RECIPE
    return (name.endswith(('.rs', '/Cargo.toml', '/Cargo.lock'))
            or name in {'Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml'} or name in RECIPE
            or name.startswith(('apps/', 'crates/', '.cargo/', 'sdk/rust/', 'sdk/go-guest/',
                                 'tools/toolchain-smoke/', 'tools/native-fixture/',
                                 'tools/optimization-workloads/', 'wit/', 'schemas/')))


def production_blob(path, expected):
    relative = path.relative_to(ROOT)
    current = ROOT
    for part in relative.parts:
        current = current / part
        require(not current.is_symlink(), 'go-replay-production-source-link')
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= 16*1024**2,
            'go-replay-production-file-bound')
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        require((opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino), 'go-replay-production-source-replaced')
        raw = stream.read(16*1024**2 + 1)
        after = os.fstat(stream.fileno())
    require(after.st_nlink == 1 and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) and len(raw) == before.st_size,
            'go-replay-production-source-mutated')
    actual = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    if relative.as_posix() == AUTHORING_SOURCE:
        require(expected == ORIGINAL_AUTHORING_BLOB, 'go-replay-original-authoring-blob')
        change = authoring_delta(raw)
        return {'gitBlob': actual, 'sha256': digest(raw), 'bytes': len(raw),
                'originalGitBlob': expected, 'reviewedAuthoringDelta': change}
    require(actual == expected, 'go-replay-production-git-preimage-drift')
    return {'gitBlob': actual, 'sha256': digest(raw), 'bytes': len(raw)}


def production_preimages(expected_tree):
    tree = subprocess.check_output(['git', 'rev-parse', ORIGINAL_HEAD + '^{tree}'], cwd=ROOT, text=True).strip()
    require(tree == expected_tree, 'go-replay-original-local-tree')
    listing = subprocess.check_output(['git', 'ls-tree', '-rz', ORIGINAL_HEAD], cwd=ROOT)
    require(len(listing) <= 8*1024**2, 'go-replay-source-tree-bound')
    original = {}
    for entry in listing.split(b'\0'):
        if not entry:
            continue
        fields, path = entry.split(b'\t', 1)
        name = path.decode('utf-8')
        if not production_name(name):
            continue
        safe_name(name)
        mode, kind, object_id = fields.decode('ascii').split()
        require(kind == 'blob' and mode in {'100644', '100755'}, 'go-replay-production-git-type')
        original[name] = object_id
    current = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT)
    require(len(current) <= 8*1024**2, 'go-replay-current-source-tree-bound')
    selected = {name for name in current.decode('utf-8').split('\0') if name and production_name(name)}
    require(selected == set(original) and 0 < len(selected) <= 8192, 'go-replay-production-source-set')
    rows = {name: production_blob(ROOT / name, original[name]) for name in sorted(selected)}
    require(sum(row['bytes'] for row in rows.values()) <= 128*1024**2, 'go-replay-production-source-bytes')
    return {'schemaVersion': 'latent.go.replay-production-preimages.v1', 'originalTree': expected_tree,
            'files': rows, 'bytes': sum(row['bytes'] for row in rows.values())}


def prepare(output):
    require(sys.platform == 'linux', 'go-replay-linux-required')
    output = owned_output(output)
    job = api(f'actions/jobs/{ORIGINAL_JOB}')
    require(job['run_id'] == ORIGINAL_RUN and job['head_sha'] == ORIGINAL_HEAD
            and job['status'] == 'completed' and all(any(row['number'] == number
                and row['conclusion'] == 'success' for row in job['steps']) for number in (27, 29, 31, 33)),
            'go-replay-original-completed-baseline')
    commit = api('git/commits/' + ORIGINAL_HEAD)
    require(commit['sha'] == ORIGINAL_HEAD, 'go-replay-fixed-source-commit')
    preimages = production_preimages(commit['tree']['sha'])
    write_json(output / 'source-preimages.json', preimages)
    artifact = Artifact('products')
    prefix = 'go-capsule-authoring/'
    for name in ('qualification.json', 'source-inputs.json', 'source-inputs-after.json'):
        artifact.extract(prefix + name, output / name)
    receipt = read_json(output / 'qualification.json')
    require(digest((output / 'qualification.json').read_bytes()) == ORIGINAL_QUALIFICATION_DIGEST, 'go-replay-original-receipt-digest')
    native_products = selected_products(receipt)
    source = (output / 'source-inputs.json').read_bytes()
    require(receipt['schemaVersion'] == 'latent.go-capsule.qualification.v1'
            and receipt['status'] == receipt['node']['status'] == 'passed'
            and json.loads(source) == expected_original_inputs()
            and source == (output / 'source-inputs-after.json').read_bytes()
            and digest(source) == receipt['sourceIdentityDigest'], 'go-replay-exact-original-source')
    for name in PRODUCTS:
        relative = 'native-binaries/' + name.replace('/', '-')
        target = output / relative
        artifact.extract(prefix + relative, target, 512*1024**2)
        require(file_identity(target, 512*1024**2) == receipt['binaries'][name],
                'go-replay-original-native-identity')
        target.chmod(0o700)
    for template in COMPANIONS:
        retrieve_build(artifact, template, output, receipt['builds'][template])
    node_path = output / 'node/workflow.json'
    artifact.extract(prefix + 'node/workflow.json', node_path, 16*1024**2)
    node_bytes = node_path.read_bytes()
    node = read_json(node_path, 16*1024**2)
    require(digest(node_bytes) == receipt['node']['receiptDigest']
            and node['status'] == 'passed' and len(node['invocations']) >= 27,
            'go-replay-original-normal-node')
    record = {'schemaVersion': 'latent.go.dependency-replay-inputs.v1', 'status': 'passed',
        'compiledSource': {'head': ORIGINAL_HEAD, 'tree': commit['tree']['sha'],
                           'run': ORIGINAL_RUN, 'job': ORIGINAL_JOB},
        'fixtureSource': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'strictNativeSDKAndCompilerToolSourceMatch': True,
        'compilerRecipeByteIdentical': False,
        'reviewedAuthoringDelta': authoring_delta((ROOT / AUTHORING_SOURCE).read_bytes()),
        'nativeProductionPreimages': {'files': len(preimages['files']), 'bytes': preimages['bytes'],
                                     'receipt': file_identity(output / 'source-preimages.json')},
        'permittedFixtureSourceDelta': 'missing bounded reader import and exact reviewed NETRC authority/userinfo lines',
        'sourceIdentityDigest': receipt['sourceIdentityDigest'],
        'nativeProducts': native_products, 'unusedOriginalProducts': list(UNUSED_ORIGINAL_PRODUCTS),
        'artifact': artifact.summary(),
        'normalQualificationRecreated': False, 'nativeProductsCompiled': False,
        'originalNormalNode': {'receipt': file_identity(node_path,16*1024**2),
                               'invocations': len(node['invocations'])},
        'fullTicketQualification': False}
    tools = Artifact('tools')
    for name in ('go.tar.gz', 'componentize-go', 'wasm-tools', 'tools.sha256'):
        tools.extract(name, output / 'tools' / name, 128*1024**2)
    require(file_identity(output / 'tools/go.tar.gz', 128*1024**2)['sha256']
            == 'sha256:ecbadb99091a3f46e31f5f934b068b1864eafa7995211b39eaddf76996045fe5',
            'go-replay-original-go-archive')
    expected_tools = compiler_materials(read_json(output / 'builds/greeting/build-observation.json'))
    for name in ('componentize-go', 'wasm-tools'):
        actual = file_identity(output / 'tools' / name)
        require(expected_tools[name] == {'name': name, 'digest': actual['sha256'], 'size': actual['bytes']},
                'go-replay-original-compiler-tool')
    record['toolsArtifact'] = tools.summary()
    write_json(output / 'retrieval.json', record)
    return record


COMPILER_MATERIALS = frozenset(('go', 'componentize-go', 'wasm-tools', 'contracts-tool', 'packager',
                              'toolchain-config', 'dependency-lock'))
FIXTURE_MATERIALS = ('tools/replay_go_dependencies.py', 'tools/qualify_go_private_dependencies.py',
    'tools/go_private_proxy_fixture.py', 'tools/go_generator_fixture.py', 'tools/go_dependency_fixture.py',
    'tools/run_rust_capsule_workflow.py')


def fixture_materials():
    return {name: file_identity(ROOT / name) for name in FIXTURE_MATERIALS}


def compiler_materials(observation):
    rows = observation['materials']
    require(len({row['name'] for row in rows}) == len(rows), 'go-replay-duplicate-material')
    selected = {row['name']: row for row in rows if row['name'] in COMPILER_MATERIALS}
    require(set(selected) == COMPILER_MATERIALS, 'go-replay-compiler-materials-missing')
    return selected


def compiler_tools(prepared, expected):
    import shutil
    result = {}
    for name in ('go', 'componentize-go', 'wasm-tools'):
        path = Path(shutil.which(name) or ('missing-' + name)).resolve(strict=True)
        require(path.is_relative_to((prepared / 'tools').resolve()), 'go-replay-tool-outside-owned-inputs')
        actual = file_identity(path)
        require(expected[name] == {'name': name, 'digest': actual['sha256'], 'size': actual['bytes']},
                'go-replay-original-tool-before-execution')
        result[name] = path
    return result


def frozen(prepared):
    receipt = read_json(prepared / 'qualification.json')
    require(digest((prepared / 'qualification.json').read_bytes()) == ORIGINAL_QUALIFICATION_DIGEST, 'go-replay-original-receipt-drift')
    selected_products(receipt)
    retrieval = read_json(prepared / 'retrieval.json')
    require(retrieval['compiledSource']['head'] == ORIGINAL_HEAD
            and retrieval['compiledSource']['run'] == ORIGINAL_RUN and retrieval['compiledSource']['job'] == ORIGINAL_JOB
            and retrieval['fixtureSource'] == subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'go-replay-source-provenance-drift')
    preimages = read_json(prepared / 'source-preimages.json')
    require(production_preimages(retrieval['compiledSource']['tree']) == preimages
            and retrieval['nativeProductionPreimages']['receipt'] == file_identity(prepared / 'source-preimages.json'),
            'go-replay-production-source-drift')
    source = (prepared / 'source-inputs.json').read_bytes()
    require(receipt['status'] == 'passed' and receipt['schemaVersion'] == 'latent.go-capsule.qualification.v1'
            and json.loads(source) == expected_original_inputs()
            and source == (prepared / 'source-inputs-after.json').read_bytes()
            and digest(source) == receipt['sourceIdentityDigest'], 'go-replay-prepared-source-drift')
    products = {name: prepared / 'native-binaries' / name.replace('/', '-') for name in PRODUCTS}
    for name, path in products.items():
        require(file_identity(path, 512*1024**2) == receipt['binaries'][name], 'go-replay-native-drift')
    for name in COMPANIONS:
        build = prepared / 'builds' / name
        marker = read_json(build / 'BUILD-COMPLETE.json')
        require(marker == receipt['builds'][name], 'go-replay-companion-marker-drift')
        layers = read_json(build / 'package-source.json')['layers']
        files = {'package-source.json': (build / 'package-source.json').read_bytes()}
        for layer in layers:
            require(layer['source'] == layer['path'] and layer['source'] not in files,
                    'go-replay-companion-layer-drift')
            safe_name(layer['source'])
            files[layer['source']] = (build / layer['source']).read_bytes()
        require(inventory(files) == (build / 'package-inputs.json').read_bytes()
                and digest(files['component.wasm']) == marker['componentDigest']
                and digest((build / 'build-observation.json').read_bytes()) == marker['observationDigest']
                and digest((build / 'source-inputs.json').read_bytes()) == marker['sourceDigest'],
                'go-replay-companion-content-drift')
        package = (build / 'package-inputs.json').read_bytes()
        require([row for row in read_json(build / 'build-observation.json')['materials'] if row['name'] == 'package-inputs']
                == [{'name': 'package-inputs', 'digest': digest(package), 'size': len(package)}],
                'go-replay-companion-package-material-drift')
    node_raw = (prepared / 'node/workflow.json').read_bytes()
    node = json.loads(node_raw)
    require(node['status'] == 'passed' and len(node['invocations']) == 27
            and digest(node_raw) == receipt['node']['receiptDigest'], 'go-replay-original-node-drift')
    return receipt, products, compiler_materials(read_json(prepared / 'builds/greeting/build-observation.json'))


def check_compilation(prepared, built, original_materials):
    observation = read_json(built / 'build-observation.json')
    require(compiler_materials(observation) == original_materials,
            'go-replay-original-compiler-material-drift')
    recipe = read_json(prepared / 'builds/greeting/recipe-inputs.json')
    change = authoring_delta((ROOT / AUTHORING_SOURCE).read_bytes())
    require(recipe.get(AUTHORING_SOURCE) == {'digest': change['original']['sha256'],
                                           'size': change['original']['bytes']},
            'go-replay-original-authoring-recipe-material')
    recipe[AUTHORING_SOURCE] = {'digest': change['selected']['sha256'], 'size': change['selected']['bytes']}
    require(read_json(built / 'recipe-inputs.json') == recipe,
            'go-replay-recipe-beyond-reviewed-authoring-delta')
    require(observation['parameters']['locked'] is True and observation['parameters']['ambientWasi'] is False
            and read_json(built / 'application-dependencies.json')['networkResolution'] is False,
            'go-replay-offline-component-required')


def check_runtime_selection(prepared, built, project):
    from tools import guest_dependency_inputs, guest_runtime_receipts as runtime
    captured = guest_dependency_inputs.capture_source(project, 'go')
    source = read_file(built / 'source-inputs.json', 4 * 1024**2)
    require(source == inventory(captured.files), 'go-replay-fresh-source-inventory-drift')
    prefix = 'vendor/lsf/sdk/go-guest/'
    original = read_json(prepared / 'builds/greeting/source-inputs.json')
    sdk = {name: row for name, row in json.loads(source).items() if name.startswith(prefix)}
    require(sdk and sdk == {name: row for name, row in original.items() if name.startswith(prefix)},
            'go-replay-original-sdk-source-drift')
    component = read_file(built / 'component.wasm', 64 * 1024**2)
    observation = read_json(built / 'build-observation.json')
    marker = read_json(built / 'BUILD-COMPLETE.json')
    require(marker['sourceDigest'] == observation['source']['snapshotDigest'] == digest(source)
            and marker['componentDigest'] == observation['componentDigest'] == digest(component)
            and marker['observationDigest'] == digest(read_file(built / 'build-observation.json')),
            'go-replay-fresh-observation-binding')
    raw = read_file(built / 'standard-runtime-selection.json', runtime.MAX_BYTES)
    material = {'name': 'standard-runtime-selection', 'digest': digest(raw), 'size': len(raw)}
    require([row for row in observation['materials'] if row['name'] == material['name']] == [material],
            'go-replay-fresh-runtime-material')
    materials = [row for row in observation['materials'] if row['name'] != material['name']]
    value = runtime.read(raw)
    runtime.verify_build(value, 'go', captured.files, source, component, materials)
    bindings = read_json(built / 'bindings.json', 16 * 1024**2)
    bound = digest(json.dumps(bindings, sort_keys=True, separators=(',', ':')).encode())
    require(marker['sdkBindingDigest'] == bound, 'go-replay-fresh-binding-output')
    graph = runtime.captured_graph(captured.files)
    document = json.loads(captured.files['capsule-project.json'])
    runtime.validate(value, result=bound, configuration={'profile': value['profile'],
        'world': document['world'], 'target': 'wasip1/wasm', 'selection': graph['selection'] if graph is not None else {}})
    require(observation['parameters']['runtime'] == value['profile'], 'go-replay-fresh-profile-binding')
    captured.check_unchanged()
    return {'status': 'passed', 'profile': value['profile'], 'sourceDigest': value['sourceDigest'],
            'componentDigest': value['componentDigest'], 'graphDigest': value['graphDigest'],
            'runtimeMaterial': material, 'bindingDigest': bound, 'originalSDKInputsEqual': True}


def sign_node(commands, prepared, products, built, output, label, *, generator=None, private=None):
    from tools.run_rust_capsule_workflow import run
    require(not (generator is not None and private is not None), 'go-replay-probe-selection')
    frozen(prepared)
    signed = output / ('signed-' + label)
    companions = [prepared / 'builds' / name for name in TEMPLATES if name != 'greeting']
    commands.run('fresh-sign-' + label, products['examples/capsule_authoring'], 'demo-sign', signed, built, *companions)
    options = {}
    if generator is not None:
        write_json(signed / 'go-generator-probe.json', {key: generator[key] for key in ('nonce', 'value')})
        options['approved_go_generator'] = True
    if private is not None:
        write_json(signed / 'private-Go-probe.json', private)
        options['captured_go_private'] = True
    node_path = output / ('node-' + label)
    node = run(products['latent'], products['latentd'], signed, node_path, language='go', **options)
    require(node['status'] == 'passed' and len(node['invocations']) == 30
            and node['nodeShutdown']['reaped'] is True and node['nodeShutdown']['record']['clean'] is True,
            'go-replay-full-signed-node-required')
    probe = node['approvedGoGenerator' if generator is not None else 'capturedGoPrivate']
    require(probe['status'] == 'passed' and len(probe['cases']) == 3, 'go-replay-three-signed-probes-required')
    return {'status': 'passed', 'calls': 30, 'receipt': file_identity(node_path / 'workflow.json')}


def baseline(prepared, output):
    from tools.build_observation import build_environment
    from tools.rust_capsule_build import Commands
    from tools.run_rust_capsule_workflow import run
    output = owned_output(output)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=900, command_seconds=600)
    before, driver = inputs('go'), fixture_materials()
    receipt, products, _compiler = frozen(prepared)
    commands.run('fresh-normal-sign', products['examples/capsule_authoring'], 'demo-sign', output / 'signed',
                 *(prepared / 'builds' / name for name in TEMPLATES))
    node = run(products['latent'], products['latentd'], output / 'signed', output / 'node', language='go')
    require(node['status'] == 'passed' and len(node['invocations']) == 27
            and node['nodeShutdown']['reaped'] is True and node['nodeShutdown']['record']['clean'] is True,
            'go-replay-fresh-normal-baseline-required')
    require(frozen(prepared)[0] == receipt and before == inputs('go') and driver == fixture_materials(),
            'go-replay-baseline-final-drift')
    result = {'schemaVersion': 'latent.go.dependency-replay-baseline.v1', 'status': 'passed',
              'source': read_json(prepared / 'retrieval.json'), 'preparedReceipt': file_identity(prepared / 'qualification.json'),
              'node': file_identity(output / 'node/workflow.json'), 'calls': 27, 'fixtureMaterials': driver,
              'nativeProductsCompiled': False}
    write_json(output / 'qualification.json', result)
    return result


def check_baseline(prepared, selected):
    result = read_json(selected / 'qualification.json')
    require(result['schemaVersion'] == 'latent.go.dependency-replay-baseline.v1' and result['status'] == 'passed'
            and result['calls'] == 27 and result['source'] == read_json(prepared / 'retrieval.json')
            and result['preparedReceipt'] == file_identity(prepared / 'qualification.json')
            and result['node'] == file_identity(selected / 'node/workflow.json'), 'go-replay-baseline-binding')
    return result


def generated_steps(prepared, selected_baseline, output):
    from tools.build_observation import build_environment
    from tools.rust_capsule_build import Commands
    from tools.go_capsule_project import create
    from tools.go_capsule_build import build
    from tools.go_dependency_fixture import install as libraries
    from tools.go_generator_fixture import install as generate
    from tools.go_dependency_authoring import source_files
    original = check_baseline(prepared, selected_baseline)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1500, command_seconds=600)
    receipt, products, compiler = frozen(prepared)
    before, driver = inputs('go'), fixture_materials()
    go = compiler_tools(prepared, compiler)['go']
    project = create(output / 'application', 'greeting')
    captured = libraries(project, output / 'outside-libraries', go)
    generated = generate(project, output / 'outside-generator')
    source = inventory(source_files(project))
    builds, nodes, runtime_bindings = [], [], []
    for label in ('initial', 'rebuilt'):
        artifact = build(project, output / ('build-' + label), products['examples/capsule_contracts'],
                         products['examples/package'], 'https://github.com/' + REPOSITORY)
        check_compilation(prepared, artifact, compiler)
        runtime_bindings.append(check_runtime_selection(prepared, artifact, project))
        raw = (project / 'go-generated-inputs.json').read_bytes()
        material = {'name': 'go-generator-inputs', 'digest': digest(raw), 'size': len(raw)}
        require([row for row in read_json(artifact / 'build-observation.json')['materials']
                 if row['name'] == material['name']] == [material], 'go-replay-exact-generated-material')
        require(source == inventory(source_files(project)), 'go-replay-generated-source-drift')
        builds.append(artifact)
    for name in ('source-inputs.json', 'recipe-inputs.json', 'bindings.json'):
        require((builds[0] / name).read_bytes() == (builds[1] / name).read_bytes(), 'go-replay-generated-input-drift')
    for label, artifact in zip(('initial', 'rebuilt'), builds):
        nodes.append(sign_node(commands, prepared, products, artifact, output, label, generator=generated))
    require(frozen(prepared)[0] == receipt and before == inputs('go') and driver == fixture_materials()
            and source == inventory(source_files(project)), 'go-replay-generator-final-drift')
    result = {'schemaVersion': 'latent.go.generator-replay.v1', 'status': 'passed', 'originalBaseline': original,
              'libraries': captured, 'generator': generated, 'nodes': nodes,
              'builds': [read_json(p / 'BUILD-COMPLETE.json') for p in builds],
              'freshRuntimeBindings': runtime_bindings,
              'fixtureMaterials': driver, 'nativeProductsCompiled': False, 'freshGeneratedComponentsCompiled': True,
              'componentReproducibility': 'not-claimed', 'fullTicketQualification': False}
    write_json(output / 'qualification.json', result)
    return result


# Closed producer reasons only; arbitrary exception/Go stderr text is never public.
NATIVE_FAILURE_REASONS = frozenset((
    'go-application-overrides-immutable-sdk-runtime-module',
    'go-authoring-concurrent-input-edit',
    'go-authoring-edit-operation',
    'go-authoring-edit-target',
    'go-authoring-exact-version-required',
    'go-authoring-frontend-operation',
    'go-authoring-immutable-sdk-module-edit-denied',
    'go-authoring-invalid-or-unavailable-input',
    'go-authoring-local-source-overlaps-sdk-or-project',
    'go-authoring-receipt-limit',
    'go-authoring-sdk-or-descriptor-drift',
    'go-build-tags-invalid',
    'go-candidate-cannot-overwrite-reviewed-input',
    'go-candidate-inside-captured-source',
    'go-candidate-not-verified',
    'go-candidate-resolution-drift',
    'go-candidate-review-digest-required',
    'go-candidate-review-drift',
    'go-checksum-policy-invalid',
    'go-declaration-lock-tool-or-capture-input-mutated',
    'go-dependency-already-declared',
    'go-dependency-not-declared-or-ambiguous',
    'go-downloaded-module-not-in-reviewed-sums',
    'go-executable-tool-declarations-require-approved-isolated-stage',
    'go-expanded-module-differs-from-original-zip',
    'go-graph-manifest-cache-bound',
    'go-graph-manifest-identity',
    'go-graph-manifest-not-in-reviewed-sums',
    'go-local-module-mutated-during-resolution',
    'go-local-module-outside-owned-fetch',
    'go-local-replacement-not-in-native-declarations',
    'go-module-resolver-version-not-pinned',
    'go-native-authoring-source-tool-or-policy-mutated',
    'go-native-declaration-count-limit',
    'go-native-declarations-or-sums-not-locked',
    'go-native-graph-or-declaration-drift-resolve-and-review',
    'go-native-lock-local-byte-or-count-limit',
    'go-native-lock-local-input-mutated',
    'go-native-main-module-mismatch',
    'go-native-manifest-cache-collision',
    'go-native-metadata-byte-limit',
    'go-native-metadata-invalid-or-unresolved',
    'go-native-module-artifact-identity-mismatch',
    'go-native-module-graph-invalid',
    'go-native-module-identity-invalid',
    'go-native-module-selection-ambiguous',
    'go-native-module-version-invalid',
    'go-native-sdk-runtime-selection-or-checksum-drift',
    'go-native-selected-graph-not-closed',
    'go-native-sum-conflict',
    'go-native-sum-invalid',
    'go-native-ziphash-mismatch',
    'go-original-module-manifest-identity',
    'go-original-module-zip-identity',
    'go-private-module-policy-invalid',
    'go-project-and-captured-runtime-profile-disagree',
    'go-proxy-authorization-format',
    'go-proxy-authorization-unavailable',
    'go-proxy-configuration-must-stay-outside-project',
    'go-proxy-endpoint-invalid',
    'go-proxy-explicit-ca-requires-linux',
    'go-proxy-policy-invalid',
    'go-proxy-public-ca-bundle-required',
    'go-proxy-public-ca-unavailable-or-changed',
    'go-proxy-public-trust-declaration-invalid',
    'go-proxy-public-trust-identity-invalid',
    'go-proxy-public-trust-input-drift',
    'go-proxy-public-trust-mutated',
    'go-proxy-public-trust-path-invalid',
    'go-runtime-profile-not-installed',
    'go-runtime-project-profile-invalid',
    'go-sdk-runtime-lock-identity',
    'go-selected-build-module-identity-mismatch',
    'go-selected-module-download-missing',
    'go-selected-root-or-download-closure-missing',
    'go-selection-fields-invalid',
))

POSITIVE_LOCK_STAGES = frozenset(('initial-candidate-lock', 'updated-candidate-lock', 'removed-candidate-lock'))


def native_failure(commands):
    require(len(commands.records) <= 128, 'go-replay-private-diagnostic-record-bound')
    rows = [(ordinal, row) for ordinal, row in enumerate(commands.records)
            if row.get('stage') in POSITIVE_LOCK_STAGES and type(row.get('exitCode')) is int
            and 0 < row['exitCode'] <= 255]
    if not rows:
        return {'available': False}
    ordinal, row = rows[-1]
    result = {'available': True, 'phase': row['stage'], 'exitCode': row['exitCode']}
    path = commands.output / 'logs' / f"{ordinal:02d}-{row['stage']}.stderr.txt"
    require(not path.is_symlink() and not path.parent.is_symlink(), 'go-replay-private-diagnostic-link')
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= 65536,
            'go-replay-private-diagnostic-bound')
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        require((opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino), 'go-replay-private-diagnostic-replaced')
        raw = stream.read(65537)
        after = os.fstat(stream.fileno())
    named_after = path.lstat()
    require(len(raw) <= 65536 and after.st_nlink == named_after.st_nlink == 1
            and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'go-replay-private-diagnostic-mutated')
    require((named_after.st_dev, named_after.st_ino, named_after.st_size, named_after.st_mtime_ns)
            == (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns), 'go-replay-private-diagnostic-replaced')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'go-replay-private-diagnostic-duplicate')
            value[key] = item
        return value
    def constant(_value):
        raise ValueError('go-replay-private-diagnostic-nonfinite')
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=constant)
    require(isinstance(value, dict) and set(value) == {'formatVersion', 'stage', 'status', 'reason',
                'compilerExecution', 'automaticReplay'} and type(value['formatVersion']) is int
            and value['formatVersion'] == 1 and value['stage'] == 'go-lock' and value['status'] == 'failed'
            and value['compilerExecution'] is False and value['automaticReplay'] is False,
            'go-replay-private-diagnostic-producer')
    reason = value['reason']
    if isinstance(reason, str) and reason in NATIVE_FAILURE_REASONS:
        result['reason'] = reason
    return result


def save_failure(output, commands, stage, error, *, campaign='private'):
    category = type(error).__name__
    if category not in {'ValueError', 'WorkflowError', 'RuntimeError', 'OSError', 'BuildProcessError'}:
        category = 'unexpected-error'
    record = {'schemaVersion': 'latent.go.dependency-replay.failure.v1', 'status': 'failed', 'campaign': campaign,
              'qualification': False, 'stage': stage, 'errorCategory': category,
              'originalCauseEstablished': False, 'fullTicketQualification': False}
    try:
        record['nativeCommand'] = native_failure(commands)
    except Exception:
        record['nativeCommand'] = {'available': False}
    try:
        write_json(output / 'FAILED.json', record)
    except Exception:
        pass  # Diagnostics never replace acquisition, execution or cleanup failure.
    try:
        print(json.dumps(record), flush=True)
    except Exception:
        pass


def generated(prepared, selected_baseline, output):
    output = owned_output(output)
    try:
        return generated_steps(prepared, selected_baseline, output)
    except BaseException as error:
        save_failure(output, SimpleNamespace(output=output, records=[]), 'generator-campaign', error, campaign='generator')
        raise


def private(prepared, selected_baseline, output):
    from tools.build_observation import build_environment
    from tools.rust_capsule_build import Commands
    from tools import qualify_go_private_dependencies as maintained
    from tools.go_capsule_build import build
    from tools.go_dependency_authoring import source_files
    output = owned_output(output)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1800, command_seconds=600)
    stage = 'original-native-products'
    try:
        original = check_baseline(prepared, selected_baseline)
        receipt, products, compiler = frozen(prepared)
        before, driver = inputs('go'), fixture_materials()
        materials = {name: file_identity(ROOT / name) for name in maintained.MATERIALS}
        go = compiler_tools(prepared, compiler)['go']
        go_before = file_identity(go)
        stage = 'actual-authenticated-native-acquisition'
        phases, captured = maintained.capture(output, commands, go)
        write_json(output / 'capture.json', captured)
        builds, nodes, runtime_bindings, rebuilt_evidence = [], [], [], None
        for ordinal, (project, lock, version, removed) in enumerate(phases):
            stage = 'offline-build-' + str(ordinal)
            source = inventory(source_files(project))
            artifact = build(project, output / ('build-' + str(ordinal)), products['examples/capsule_contracts'],
                             products['examples/package'], 'https://github.com/' + REPOSITORY)
            check_compilation(prepared, artifact, compiler)
            runtime_bindings.append(check_runtime_selection(prepared, artifact, project))
            require(source == inventory(source_files(project))
                    and maintained.dependencies.verify_inputs(project, 'go').lock == lock,
                    'private-Go-offline-build-mutated-inputs')
            artifacts = [(str(ordinal), artifact)]
            if ordinal == 0:
                rebuilt = build(project, output / 'offline-rebuild', products['examples/capsule_contracts'],
                                products['examples/package'], 'https://github.com/' + REPOSITORY)
                check_compilation(prepared, rebuilt, compiler)
                runtime_bindings.append(check_runtime_selection(prepared, rebuilt, project))
                rebuilt_evidence = maintained.offline_rebuild(artifact, rebuilt, project)
                write_json(output / 'offline-rebuild-evidence.json', rebuilt_evidence)
                artifacts.append(('initial-rebuilt', rebuilt))
            for label, selected in artifacts:
                stage = 'sign-and-enforced-node-' + label
                nodes.append(sign_node(commands, prepared, products, selected, output, label,
                    private={'nonce': captured['nonce'], 'version': version, 'removed': removed}))
                builds.append(read_json(selected / 'BUILD-COMPLETE.json'))
        require(frozen(prepared)[0] == receipt and before == inputs('go') and driver == fixture_materials()
                and go_before == file_identity(go)
                and materials == {name: file_identity(ROOT / name) for name in maintained.MATERIALS},
                'go-replay-private-final-drift')
        result = {'schemaVersion': 'latent.go.private-replay.v1', 'status': 'passed',
                  'originalBaseline': original, 'capture': captured, 'builds': builds, 'nodes': nodes,
                  'materials': materials, 'fixtureMaterials': driver,
                  'freshRuntimeBindings': runtime_bindings, 'offlineRebuild': rebuilt_evidence,
                  'componentReproducibility': 'not-claimed',
                  'nativeProductsCompiled': False, 'freshPrivateComponentsCompiled': True,
                  'cleanHost': False, 'hermetic': False, 'publisherAuthenticated': False,
                  'fullTicketQualification': False}
        write_json(output / 'qualification.json', result)
        return result
    except BaseException as error:
        save_failure(output, commands, stage, error)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--campaign', choices=('baseline', 'private', 'generator'))
    args = parser.parse_args()
    if args.prepared is None:
        require(args.campaign is None and args.baseline is None, 'go-replay-explicit-prepare-mode')
        result = prepare(args.output.resolve())
    elif args.campaign == 'baseline':
        require(args.baseline is None, 'go-replay-baseline-mode')
        result = baseline(args.prepared.resolve(), args.output.resolve())
    else:
        require(args.baseline is not None and args.campaign in {'private', 'generator'}, 'go-replay-explicit-campaign')
        function = private if args.campaign == 'private' else generated
        result = function(args.prepared.resolve(), args.baseline.resolve(), args.output.resolve())
    print(json.dumps({'status': result['status']}))
