"""Finite user-project build and unsigned, exact-byte observation generation."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
import shutil
import time
import tomllib

from tools.build_observation import file_identity
from tools.c_guest.bindings import check_lock, digest, generate
from tools.c_guest.compiler import Compiler, ROOT, SDK, safe_output
from tools.c_guest.metadata import Projection, canonical, locked_sources


class ProjectError(ValueError):
    pass


def closed_json(path: Path, maximum: int = 262144) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ProjectError('missing, linked or oversized project configuration')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ProjectError('duplicate JSON key')
            result[key] = value
        return result
    value = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ProjectError('nonfinite JSON')))
    if not isinstance(value, dict):
        raise ProjectError('configuration must be an object')
    return value


def checked_root(path: Path) -> Path:
    original = path.absolute()
    if any(part.is_symlink() for part in (original, *original.parents)):
        raise ProjectError('project roots cannot traverse symlinks')
    if not original.is_dir():
        raise ProjectError('project directory is missing')
    return original.resolve()


def load(project: Path) -> tuple[Path, dict, list[Path]]:
    project = checked_root(project)
    config = closed_json(project / 'c-project.json')
    expected = {'formatVersion', 'name', 'version', 'world', 'sources', 'memoryBytes'}
    if set(config) != expected or type(config['formatVersion']) is not int or config['formatVersion'] != 1:
        raise ProjectError('unsupported or non-closed C project configuration')
    if not isinstance(config['name'], str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,62}', config['name']):
        raise ProjectError('invalid project name')
    if not isinstance(config['version'], str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', config['version']):
        raise ProjectError('use a release semantic version')
    if not isinstance(config['world'], str) or len(config['world']) > 256 or '@' not in config['world']:
        raise ProjectError('use a fully qualified WIT world')
    memory = config['memoryBytes']
    if type(memory) is not int or not 2_097_152 <= memory <= 67_108_864 or memory % 65536:
        raise ProjectError('invalid page-aligned guest memory ceiling')
    names = config['sources']
    if not isinstance(names, list) or not 1 <= len(names) <= 64 or any(not isinstance(name, str) for name in names):
        raise ProjectError('invalid C source inventory')
    if len(names) != len(set(names)):
        raise ProjectError('duplicate C sources')
    sources = []
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or any(part in ('', '.', '..') for part in path.parts) or path.as_posix() != name or path.suffix != '.c' or '\\' in name:
            raise ProjectError('C sources must be portable relative .c paths')
        source = project / name
        if any(part.is_symlink() for part in (source, *source.parents)) or not source.is_file():
            raise ProjectError('C sources must be regular files inside the project')
        sources.append(source)
    return project, config, sources


def inventory(project: Path) -> bytes:
    records, total = {}, 0
    roots = [('project', project), ('sdk', SDK / 'include'),
             ('runtime', SDK / 'src'), ('recipe', ROOT / 'tools/c_guest')]
    for prefix, root in roots:
        pending = [root]
        seen = 0
        while pending:
            directory = pending.pop()
            for path in sorted(directory.iterdir()):
                seen += 1
                if seen > 512 or path.is_symlink():
                    raise ProjectError('project inventory bound or link violation')
                if path.name == '__pycache__' or path.suffix == '.pyc':
                    continue
                if path.is_dir():
                    pending.append(path)
                elif path.is_file():
                    record = file_identity(path, prefix + '/' + path.relative_to(root).as_posix(), 262144)
                    total += record['size']
                    if total > 8 * 1024 * 1024:
                        raise ProjectError('project inventory bytes exceeded')
                    records[record.pop('name')] = record
                else:
                    raise ProjectError('project inventory contains a nonregular input')
    for name in ('tools/toolchain.toml', 'tools/stage_runtime_wit.py', 'tools/build_process.py',
                 'tools/build_process_linux.py', 'tools/build_process_windows.py',
                 'tools/build_process_signals.py', 'tools/build_observation.py',
                 'examples/echo-contract/capsule.json', 'Cargo.toml'):
        record = file_identity(ROOT / name, name, 262144)
        records[record.pop('name')] = record
    return canonical(records)


def output_for(project: Path, output: Path) -> Path:
    output = safe_output(output)
    if output == project or project in output.parents or output in project.parents:
        raise ProjectError('build output cannot overlap project inputs')
    output.mkdir(parents=True)
    return output


def bindings(project: Path, output: Path, *, update: bool) -> dict:
    project, config, _ = load(project)
    output = output_for(project, output)
    compiler = Compiler(output / 'tmp')
    _, lock = generate(compiler.run, project / 'wit', config['world'], output / 'generated')
    compiler.check_unchanged()
    check_lock(project / 'c-bindings.lock.json', lock, update=update)
    return lock


def build(project: Path, output: Path) -> dict:
    project, config, sources = load(project)
    output = output_for(project, output)
    started, before = int(time.time()), inventory(project)
    compiler = Compiler(output / 'tmp')
    component, lock = compiler.compile(sources, project / 'wit', config['world'], output / 'compiled',
                                       memory_bytes=config['memoryBytes'])
    check_lock(project / 'c-bindings.lock.json', lock)
    resolved = json.loads(compiler.run('wasm-tools', 'component', 'wit', str(output / 'compiled/wit'), '--json'))
    contracts, exports, imports = Projection(resolved).contracts(config['world'])
    package = output / 'package-inputs'
    package.mkdir()
    shutil.copyfile(component, package / 'component.wasm')
    (package / 'contracts.json').write_bytes(contracts)
    packages = locked_sources(output / 'compiled/wit', package, resolved)
    write(package / 'wit-lock.json', {'formatVersion': 1, 'world': config['world'],
                                      'contractsDigest': digest(contracts), 'packages': packages})
    manifest = closed_json(ROOT / 'examples/echo-contract/capsule.json')
    manifest['metadata'] = {'name': config['name'], 'annotations': {'latent.dev/purpose': 'c-authored-capsule'}}
    manifest['component'] = {'digest': digest(component.read_bytes()), 'version': config['version'], 'world': config['world']}
    manifest['imports'] = [{'contract': name, 'optional': False} for name in imports]
    manifest['exports'] = exports
    manifest['execution'].update(threading='single-threaded', snapshotEligible=False, fusionEligible=False)
    manifest['execution']['limits'].update(cpuFuel=100_000_000, memoryBytes=config['memoryBytes'],
        wallTimeLimitMillis=5000, childCalls=8 if 'latent:service/invoke@0.1.0' in imports else 0,
        outboundRequests=8 if imports else 0, blobReadBytes=65536 if 'latent:blob/blob@0.2.0' in imports else 0,
        blobWriteBytes=65536 if 'latent:blob/blob@0.2.0' in imports else 0, logBytes=4096, effectCount=0)
    manifest['compatibility']['minimumFabricVersion'] = tomllib.loads((ROOT / 'Cargo.toml').read_text())['workspace']['package']['version']
    write(package / 'capsule.json', manifest)
    layers = [('component.wasm', 'component', 'application/wasm'),
              ('capsule.json', 'capsule-manifest', 'application/vnd.latent.capsule.manifest.v1+json'),
              ('contracts.json', 'contracts', 'application/vnd.latent.contracts.v1+json'),
              ('wit-lock.json', 'wit-lock', 'application/vnd.latent.wit-lock.v1+json')]
    layers += [(entry['sourcePath'], 'asset', 'text/plain') for entry in packages]
    write(package / 'package-source.json', {'formatVersion': 1, 'kind': 'capsule',
        'name': config['name'], 'version': config['version'], 'entrypoint': 'component.wasm', 'annotations': {},
        'layers': [{'path': path, 'source': path, 'role': role, 'mediaType': media} for path, role, media in layers]})
    if before != inventory(project):
        raise ProjectError('project or SDK inputs changed during compilation')
    compiler.check_unchanged()
    (output / 'source-inputs.json').write_bytes(before)
    materials = [('source-snapshot', before), ('build-recipe', Path(__file__).read_bytes()),
                 ('toolchain-config', (ROOT / 'tools/toolchain.toml').read_bytes()),
                 ('c-bindings-lock', (project / 'c-bindings.lock.json').read_bytes())]
    observation = {'formatVersion': 1, 'buildType': 'https://latent.dev/build/c-guest/v1',
        'source': {'repository': 'https://github.com/KirilsTurkins/latent-service-fabric',
                   'revision': digest(before).split(':')[1], 'snapshotDigest': digest(before),
                   'repositoryTrust': 'operator-asserted', 'capture': 'explicit-input-files'},
        'componentDigest': digest(component.read_bytes()), 'componentSize': component.stat().st_size,
        'materials': [{'name': name, 'digest': digest(data), 'size': len(data)} for name, data in materials]
                     + [compiler.materials[name] for name in ('wasm-tools', 'wit-bindgen', 'zig')],
        'parameters': {'compiler': 'zig-cc', 'fixture': 'application', 'target': 'wasm32-wasi', 'optimization': 'O2'},
        'startedAt': started, 'finishedAt': int(time.time()), 'reproducibility': 'not-checked',
        'hermetic': False, 'dependencyCompleteness': 'declared-inputs-incomplete'}
    write(output / 'build-observation.json', observation)
    receipt = {'formatVersion': 1, 'componentDigest': observation['componentDigest'],
               'componentBytes': observation['componentSize'], 'bindingsDigest': digest(canonical(lock)),
               'sourceSnapshotDigest': digest(before), 'observationDigest': digest((output / 'build-observation.json').read_bytes()),
               'memoryCeilingBytes': config['memoryBytes'], 'guestExecuted': False,
               'trustEvaluated': False, 'executionAuthorized': False}
    write(output / 'BUILD-COMPLETE.json', receipt)
    return receipt


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
