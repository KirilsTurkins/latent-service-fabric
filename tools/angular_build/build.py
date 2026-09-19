"""Run fixed compilation/composition and retain only bounded package inputs."""
from __future__ import annotations

from pathlib import Path
import time

from tools.angular_build import cargo, package
from tools.angular_build.inputs import decode, read
from tools.angular_build.tools import BuildTools, ROOT
from tools.build_observation import file_identity, public_repository
from tools.build_snapshot import SnapshotError, canonical, digest


def compile_application(config: dict, captured: Path, work: Path, tools: BuildTools) -> tuple[Path, Path, list[dict], list[dict]]:
    scripts = ROOT / 'tools/angular_build'
    node = str(tools.paths['node'])
    toolchain = str(tools.toolchain)
    bundle = work / 'bundle'
    for mode in ('configure', 'bundle'):
        if mode == 'bundle':
            tools.call([node, str(tools.toolchain / 'node_modules/@angular/compiler-cli/bundles/src/bin/ngc.js'),
                        '-p', str(bundle / 'tsconfig.json')], captured, node=True)
        tools.call([node, str(scripts / 'bundle.mjs'), toolchain, str(captured), str(bundle), mode], captured, node=True)
    client = read(bundle, 'client.js', 8 * 1024 * 1024)
    client_path = '/client/' + digest(client)[7:] + '/main.js'
    stage = work / 'component'
    (stage / 'wit/deps/context').mkdir(parents=True)
    (stage / 'wit/deps/web').mkdir()
    for source, destination in (
        (ROOT / 'tools/angular-renderer-adapter/runtime/bridge.js', stage / 'bridge.js'),
        (ROOT / 'tools/angular-renderer-adapter/runtime/timers.js', stage / 'timers.js'),
        (scripts / 'application.js', stage / 'application.js'),
        (bundle / 'server.js', stage / 'server.js'),
        (ROOT / 'tools/angular-renderer-adapter/wit/adapter.wit', stage / 'wit/adapter.wit'),
        (ROOT / 'wit/platform/context/package.wit', stage / 'wit/deps/context/package.wit'),
        (ROOT / 'wit/platform/web/package.wit', stage / 'wit/deps/web/package.wit'),
    ):
        destination.write_bytes(read(source.parent, source.name, 8 * 1024 * 1024))
    (stage / 'assets.js').write_bytes(b'export const clientAsset=' + canonical(client_path) + b';\n')
    tools.call([node, str(scripts / 'componentize.mjs'), toolchain, str(stage)], stage, node=True, seconds=300)
    cargo_output = tools.call([str(tools.paths['cargo']), 'build', '--locked', '--offline', '-p', 'latent-angular-renderer-adapter',
                               '--target', 'wasm32-unknown-unknown', '--release', '--message-format=json'], ROOT)
    dependencies = cargo.observe(cargo_output, tools)
    core = Path(tools.environment['CARGO_TARGET_DIR']) / 'wasm32-unknown-unknown/release/latent_angular_renderer_adapter.wasm'
    adapter = stage / 'adapter.wasm'
    component = stage / 'application.wasm'
    composer = str(tools.paths['wasm-tools'])
    tools.call([composer, 'component', 'new', str(core), '-o', str(adapter)], stage, seconds=60)
    tools.call([composer, 'compose', str(adapter), '-d', str(stage / 'renderer.wasm'), '-o', str(component)], stage, seconds=60)
    tools.call([composer, 'validate', str(component)], stage, seconds=60)
    materials = [file_identity(path, name, 32 * 1024 * 1024) for name, path in (
        ('angular-client-bundle', bundle / 'client.js'), ('angular-server-bundle', bundle / 'server.js'),
        ('javascript-embedding', stage / 'renderer.wasm'), ('async-adapter', adapter), ('renderer-component', component))]
    return bundle, component, materials, dependencies


def assemble(config: dict, captured: Path, work: Path, output: Path, tools: BuildTools,
             source_inventory: bytes) -> tuple[dict, list[dict]]:
    bundle, component, materials, dependencies = compile_application(config, captured, work, tools)
    inputs = output / 'inputs'
    recipe, _client = package.stage(config, captured, bundle, component, inputs, tools.profile, source_inventory)
    sbom = package.inventory(recipe, inputs, tools.toolchain, source_inventory, tools.executables, dependencies)
    (inputs / 'sbom-inputs.json').write_bytes(sbom)
    summary = tools.cli('package', 'build', '--source', str(inputs / 'package-source.json'), '--input-root', str(inputs),
                        '--sbom-inputs', str(inputs / 'sbom-inputs.json'), '--output-dir', str(output / 'package'), '--validate-web')
    if not summary.get('sbomInventoryDigest') or not summary.get('webBuildOutputs') or summary.get('componentDigest') is not None:
        raise SnapshotError('Angular package lacks its exact componentless inventory and output identities')
    return summary, materials


def observation(config: dict, tools: BuildTools, summary: dict, materials: list[dict], inventory: bytes,
                repository: str, started: int, finished: int, reproducible: bool) -> dict:
    public_repository(repository)
    if not 0 <= finished - started <= 1800:
        raise SnapshotError('Angular observed build clock is invalid')
    outputs = summary['webBuildOutputs']
    renderer = next(item for item in materials if item['name'] == 'renderer-component')
    records = [*tools.materials(), *materials, {'name': 'source-snapshot', 'digest': digest(inventory), 'size': len(inventory)}]
    value = {'formatVersion': 1, 'buildType': 'https://latent.dev/build/angular-component/v1',
             'source': {'repository': repository, 'revision': digest(inventory)[7:], 'snapshotDigest': digest(inventory),
                        'repositoryTrust': 'operator-asserted', 'capture': 'explicit-input-files'},
             'outputsDigest': outputs['digest'], 'outputsCount': outputs['count'], 'outputsBytes': int(outputs['bytes']),
             'materials': sorted(records, key=lambda row: row['name']),
             'parameters': {'compiler': 'lsf-angular-component', 'recipeVersion': 1,
                            'rendererProfile': config['profile'], 'profileDigest': tools.profile['profileDigest'],
                            'rendererDigest': renderer['digest'], 'rendererSize': renderer['size'],
                            'maxHydrationBytes': 32768, 'lifecycleScripts': False},
             'startedAt': started, 'finishedAt': finished,
             'reproducibility': 'two-build-byte-equality' if reproducible else 'not-checked',
             'hermetic': False, 'dependencyCompleteness': 'declared-inputs-incomplete'}
    if len(records) > 64 or len(canonical(value)) > 32768 or len({item['name'] for item in records}) != len(records):
        raise SnapshotError('Angular build observation limit exceeded')
    return value
