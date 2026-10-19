"""Original native products and fresh approved TypeScript source generation."""
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
import urllib.error
import urllib.request
import zipfile
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_rust_capsules import inputs
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, inventory, read_json, write_json
ORIGINAL_HEAD = 'ecb662e99ed6359921da9160b0a07e36d0ca0c25'
ORIGINAL_RUN = 39291931690
ORIGINAL_JOB = 118194523068
REPOSITORY = 'KirilsTurkins/latent-service-fabric'
ARTIFACT_NAME = 'typescript-guest-runtime-' + ORIGINAL_HEAD
PRODUCTS = ('latent', 'latentd', 'examples/capsule_contracts', 'examples/package', 'examples/capsule_authoring')
COMPANIONS = tuple(TEMPLATES)
MAX_DOCUMENT = 4 * 1024**2
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
        require(kind == 'products', 'replay-fixed-artifact-kind')
        listing = api(f'actions/runs/{ORIGINAL_RUN}/artifacts?per_page=100')
        matches = [r for r in listing['artifacts'] if r['name'] == ARTIFACT_NAME]
        require(listing['total_count'] <= 100 and len(matches) == 1, 'replay-fixed-artifact-selection')
        self.metadata = matches[0]
        artifact, size, expected_digest = (self.metadata[k] for k in ('id', 'size_in_bytes', 'digest'))
        require(type(artifact) is int and 0 < size <= 4*1024**3
                and isinstance(expected_digest, str) and expected_digest.startswith('sha256:')
                and len(expected_digest) == 71, 'replay-artifact-metadata-bounds')
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
    require(template in COMPANIONS, 'private-replay-fixed-companion-only')
    output = prepared / 'builds' / template
    output.mkdir(mode=0o700, parents=True)
    prefix = '_temp/typescript-capsule-authoring/builds/' + template + '/'
    for name in BUILD_FILES:
        artifact.extract(prefix + name, output / name)
    require(read_json(output / 'BUILD-COMPLETE.json') == expected, 'private-replay-original-build-marker')
    layers = read_json(output / 'package-source.json')['layers']
    require(1 <= len(layers) <= 32, 'private-replay-package-layer-count')
    allowed = {'component.wasm', 'capsule.json', 'contracts.json', 'wit-lock.json', 'compatibility-report.json',
               'wit/world.wit', 'wit/deps/clock/package.wit', 'wit/deps/http-v2/package.wit', 'wit/deps/http/package.wit'}
    observed = {'package-source.json': (output / 'package-source.json').read_bytes()}
    for layer in layers:
        name = layer['source']
        require(name in allowed and layer['path'] == name and name not in observed,
                'private-replay-fixed-package-layer')
        artifact.extract(prefix + name, output / name, 64*1024**2 if name == 'component.wasm' else MAX_DOCUMENT)
        observed[name] = (output / name).read_bytes()
    require(inventory(observed) == (output / 'package-inputs.json').read_bytes()
            and digest(observed['component.wasm']) == expected['componentDigest']
            and digest((output / 'build-observation.json').read_bytes()) == expected['observationDigest']
            and digest((output / 'source-inputs.json').read_bytes()) == expected['sourceDigest'],
            'private-replay-original-package-input-identity')


def retrieve_greeting_compiler(artifact, output, expected):
    prefix = '_temp/typescript-capsule-authoring/builds/greeting/'
    if not (output / 'builds/greeting/build-observation.json').exists():
        artifact.extract(prefix + 'build-observation.json', output / 'builds/greeting/build-observation.json')
    for name in ('compiler-inputs.json',):
        artifact.extract(prefix + name, output / 'builds/greeting' / name)
    observed = (output / 'builds/greeting/build-observation.json').read_bytes()
    compiler = (output / 'builds/greeting/compiler-inputs.json').read_bytes()
    require(digest(observed) == expected['observationDigest'], 'npm-replay-greeting-observation')
    materials = [row for row in json.loads(observed)['materials'] if row['name'] == 'compiler-inputs']
    require(len(materials) == 1 and materials[0]['digest'] == digest(compiler)
            and materials[0]['size'] == len(compiler), 'npm-replay-greeting-compiler-inputs')


ORIGINAL_QUALIFIER_DIGEST = 'sha256:0b185b3c6979c3656cb472984e3c891b67c7e075bf4d6117e928ca9b142ee853'
ORIGINAL_QUALIFIER_BYTES = 34432


def qualifier_delta(current):
    before = b'ROOT, TEMPLATES, create, digest, fresh, read_json, write_json'
    after = b'ROOT, TEMPLATES, create, digest, fresh, read_file, read_json, write_json'
    require(current.count(after) == 1, 'generator-replay-exact-reader-import')
    original = current.replace(after, before, 1)
    require(digest(original) == ORIGINAL_QUALIFIER_DIGEST and len(original) == ORIGINAL_QUALIFIER_BYTES,
            'generator-replay-unreviewed-qualifier-change')
    return {'sha256': digest(original), 'bytes': len(original)}


def expected_original_inputs():
    value = inputs('typescript')
    value['helpers']['qualify_rust_capsules.py'] = qualifier_delta(
        (ROOT / 'tools/qualify_rust_capsules.py').read_bytes())
    return value


def prepare(output):
    require(sys.platform == 'linux', 'npm-replay-linux-required')
    output = fresh(output)
    require(output != ROOT and ROOT not in output.parents, 'npm-replay-output-outside-source')
    job = api(f'actions/jobs/{ORIGINAL_JOB}')
    require(job['run_id'] == ORIGINAL_RUN and job['head_sha'] == ORIGINAL_HEAD
            and job['status'] == 'completed' and all(any(row['number'] == number
                and row['conclusion'] == 'success' for row in job['steps']) for number in (20,)),
            'npm-replay-original-completed-baseline')
    commit = api('git/commits/' + ORIGINAL_HEAD)
    require(commit['sha'] == ORIGINAL_HEAD, 'npm-replay-fixed-source-commit')
    artifact = Artifact('products')
    prefix = '_temp/typescript-capsule-authoring/'
    for name in ('qualification.json', 'source-inputs.json', 'source-inputs-after.json'):
        artifact.extract(prefix + name, output / name)
    receipt = read_json(output / 'qualification.json')
    source = (output / 'source-inputs.json').read_bytes()
    require(receipt['schemaVersion'] == 'latent.typescript-capsule.qualification.v1'
            and receipt['status'] == receipt['node']['status'] == 'passed'
            and set(receipt['binaries']) == set(PRODUCTS)
            and json.loads(source) == expected_original_inputs()
            and source == (output / 'source-inputs-after.json').read_bytes()
            and digest(source) == receipt['sourceIdentityDigest'], 'npm-replay-exact-original-source')
    for name in PRODUCTS:
        relative = 'native-binaries/' + name.replace('/', '-')
        target = output / relative
        artifact.extract(prefix + relative, target, 512*1024**2)
        require(file_identity(target, 512*1024**2) == receipt['binaries'][name],
                'npm-replay-original-native-identity')
        target.chmod(0o700)
    for template in COMPANIONS:
        retrieve_build(artifact, template, output, receipt['builds'][template])
    retrieve_greeting_compiler(artifact, output, receipt['builds']['greeting'])
    node_path = output / 'node/workflow.json'
    artifact.extract(prefix + 'node/workflow.json', node_path, 16*1024**2)
    node_bytes = node_path.read_bytes()
    node = read_json(node_path, 16*1024**2)
    require(digest(node_bytes) == receipt['node']['receiptDigest']
            and node['status'] == 'passed' and len(node['invocations']) >= 27,
            'npm-replay-original-normal-node')
    record = {'schemaVersion': 'latent.typescript.generator-replay-inputs.v1', 'status': 'passed',
        'compiledSource': {'head': ORIGINAL_HEAD, 'tree': commit['tree']['sha'],
                           'run': ORIGINAL_RUN, 'job': ORIGINAL_JOB},
        'fixtureSource': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'strictNativeAndCompilerSourceMatch': True,
        'permittedFixtureSourceDelta': 'only missing bounded reader import in qualifier', 'sourceIdentityDigest': receipt['sourceIdentityDigest'],
        'nativeProducts': receipt['binaries'], 'artifact': artifact.summary(),
        'normalQualificationRecreated': False, 'nativeProductsCompiled': False,
        'originalNormalNode': {'receipt': file_identity(node_path,16*1024**2),
                               'invocations': len(node['invocations'])},
        'fullTicketQualification': False}
    write_json(output / 'retrieval.json', record)
    return record


def qualify(prepared, tools, output):
    from tools.build_observation import build_environment
    from tools.rust_capsule_build import Commands
    from tools.qualify_rust_capsules import read_file
    from tools.run_rust_capsule_workflow import run as node_workflow
    from tools.typescript_guest.project import create
    from tools.typescript_guest.build import build
    from tools.typescript_dependency_fixture import install as install_libraries
    from tools.typescript_generator_fixture import install as install_generator
    from tools.typescript_dependency_authoring import source_files
    output = fresh(output)
    require(ROOT not in output.parents and output != ROOT, 'generator-replay-output-outside-source')
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1500, command_seconds=600)
    before = inputs('typescript')
    driver_identity = file_identity(Path(__file__))
    require(json.loads((prepared/'source-inputs.json').read_bytes()) == expected_original_inputs(),
            'generator-replay-prepared-source')
    receipt = read_json(prepared/'qualification.json')
    products = {name: prepared/'native-binaries'/name.replace('/','-') for name in PRODUCTS}
    for name, path in products.items():
        require(file_identity(path,512*1024**2) == receipt['binaries'][name], 'generator-replay-native-identity')
    old_builds = [prepared/'builds'/name for name in TEMPLATES]
    commands.run('fresh-normal-demo-sign', products['examples/capsule_authoring'], 'demo-sign', output/'normal-signed', *old_builds)
    baseline = node_workflow(products['latent'], products['latentd'], output/'normal-signed', output/'normal-node', language='typescript')
    require(baseline['status'] == 'passed' and len(baseline['invocations']) == 27,
            'generator-replay-actual-normal-programme')
    project = create(output/'application','greeting')
    libraries = install_libraries(project,output/'outside-libraries')
    generated = install_generator(project,output/'outside-generator')
    source_before = inventory(source_files(project))
    builds = []
    for label in ('initial','rebuilt'):
        artifact = build(project,output/('build-'+label),products['examples/capsule_contracts'],products['examples/package'],
            'https://github.com/KirilsTurkins/latent-service-fabric',tools=tools)
        require(source_before == inventory(source_files(project)), 'generator-replay-source-mutated')
        compiler = read_file(artifact/'compiler-inputs.json')
        require(compiler == read_file(prepared/'builds/greeting/compiler-inputs.json'),
                'generator-replay-original-compiler-inputs')
        raw = read_file(project/'typescript-generated-inputs.json')
        material = {'name':'typescript-generator-inputs','digest':digest(raw),'size':len(raw)}
        observation = read_json(artifact/'build-observation.json')
        require([m for m in observation['materials'] if m['name'] == material['name']] == [material],
                'generator-replay-exact-generated-material')
        require(read_json(artifact/'application-dependencies.json')['networkResolution'] is False,
                'generator-replay-offline-compiler')
        builds.append(artifact)
    for name in ('source-inputs.json','recipe-inputs.json','compiler-inputs.json','bindings.json'):
        require(read_file(builds[0]/name) == read_file(builds[1]/name), 'generator-replay-offline-input-drift')
    nodes = []
    companions = [prepared/'builds'/name for name in TEMPLATES if name != 'greeting']
    for label,artifact in zip(('initial','rebuilt'),builds):
        signed = output/('signed-'+label)
        commands.run('fresh-generated-sign-'+label,products['examples/capsule_authoring'],'demo-sign',signed,artifact,*companions)
        write_json(signed/'typescript-generator-probe.json', {k:generated[k] for k in ('nonce','value')})
        node = node_workflow(products['latent'],products['latentd'],signed,output/('node-'+label),
                            language='typescript',approved_typescript_generator=True)
        require(node['status'] == 'passed' and len(node['invocations']) == 30
                and node['approvedTypeScriptGenerator']['status'] == 'passed'
                and len(node['approvedTypeScriptGenerator']['cases']) == 3,
                'generator-replay-signed-generated-values')
        nodes.append({'status':node['status'],'invocations':len(node['invocations']),
                      'receipt':file_identity(output/('node-'+label)/'workflow.json')})
    require(driver_identity == file_identity(Path(__file__)) and before == inputs('typescript') and source_before == inventory(source_files(project)),
            'generator-replay-final-input-drift')
    for name,path in products.items():
        require(file_identity(path,512*1024**2) == receipt['binaries'][name], 'generator-replay-final-native-drift')
    result = {'schemaVersion':'latent.typescript.generator-replay.v1','status':'passed',
        'originalInputs':read_json(prepared/'retrieval.json'), 'libraries':libraries,'generator':generated,
        'normalBaseline':{'invocations':27,'receipt':file_identity(output/'normal-node/workflow.json')},
        'builds':[read_json(p/'BUILD-COMPLETE.json') for p in builds],'generatedNodes':nodes,
        'fixtureSource':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'nativeCargoProductsCompilationPerformed':False,'freshGeneratedComponentCompilationPerformed':True,
        'componentReproducibility':'not-claimed','cleanHost':False,'hermetic':False,
        'publisherAuthenticated':False,'fullTicketQualification':False,'releasePublished':False}
    write_json(output/'qualification.json',result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--prepared',type=Path)
    parser.add_argument('--tools',type=Path)
    args = parser.parse_args()
    if args.prepared is None:
        result = prepare(args.output.resolve())
    else:
        require(args.tools is not None, 'generator-replay-explicit-tools')
        result = qualify(args.prepared.resolve(),args.tools.resolve(),args.output.resolve())
    print(json.dumps({'status':result['status']}))
