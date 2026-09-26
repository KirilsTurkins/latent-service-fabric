#!/usr/bin/env python3
"""Build four maintained static references, then assemble their supplied bytes."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment, file_identity
from tools.build_process import run_bounded
from tools.build_snapshot import canonical, digest
from tools.static_site import capture, read, require

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'https://github.com/KirilsTurkins/latent-service-fabric'
NAMES = ('csr-a', 'csr-b', 'generator', 'generator-docs')


def record(name, data):
    return {'name': name, 'digest': digest(data), 'size': len(data)}


def run(command, environment, seconds=120):
    return run_bounded([str(value) for value in command], cwd=ROOT, env=environment,
                       timeout_seconds=seconds, max_output_bytes=2 * 1024 * 1024).stdout


def csr(version, source, work, toolchain, node, environment):
    source.mkdir()
    for name in ('main.ts', 'order.ts', 'style.css'):
        (source / name).write_bytes(read(ROOT / 'examples/static-sites/csr', name, 65536))
    (source / 'version.ts').write_text(f'export const BUILD_VERSION = "{version}";\n', encoding='utf-8')
    script = ROOT / 'tools/static-sites/build.mjs'
    run([node, script, toolchain, source, work, 'configure'], environment)
    run([node, toolchain / 'node_modules/@angular/compiler-cli/bundles/src/bin/ngc.js',
         '-p', work / 'tsconfig.json'], environment)
    run([node, script, toolchain, source, work, 'bundle'], environment)
    outputs = json.loads(read(work, 'outputs.json', 65536))
    public = work / 'public'
    style = read(source, 'style.css', 65536)
    css = 'assets/style-' + digest(style)[7:23] + '.css'
    (public / css).write_bytes(style)
    main = next(row['name'] for row in outputs['outputs'] if row['entry'])
    (public / 'index.html').write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Static orders</title>'
        f'<link rel="stylesheet" href="/{css}"></head><body><lsf-static-app></lsf-static-app>'
        f'<script type="module" src="/{main}"></script></body></html>', encoding='utf-8')
    return public, ['index.html', css, *(row['name'] for row in outputs['outputs'])], outputs


def generator(mount, source, work):
    source.mkdir()
    raw = read(ROOT / 'examples/static-sites/generator', 'pages.json', 65536)
    (source / 'pages.json').write_bytes(raw)
    (source / 'mount.json').write_bytes(canonical({'mount': mount}))
    value = json.loads(raw)
    public = work / 'public'
    (public / 'assets').mkdir(parents=True)
    css = b'body{font-family:sans-serif;color:rgb(20,50,80)}'
    style = 'assets/site-' + digest(css)[7:23] + '.css'
    (public / style).write_bytes(css)
    names = [style]
    for page in value['pages']:
        output = public / page['path']
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<title>{html.escape(value["title"])}</title><link rel="stylesheet" href="{mount}/{style}">'
            f'</head><body><h1 id="view">{html.escape(page["title"])}</h1><p>{html.escape(page["text"])}</p>'
            f'<a id="guide" href="{mount}/guide">Guide</a></body></html>', encoding='utf-8')
        names.append(page['path'])
    return public, names, {'generator': 'maintained-finite-pages-v1', 'mount': mount,
                            'dependencies': [], 'serverRenderer': False, 'lifecycleScripts': False}


def dependencies(toolchain, names):
    lock = json.loads(read(toolchain, 'package-lock.json', 4 * 1024 * 1024))
    rows = []
    for name in sorted(names):
        raw = read(toolchain, 'node_modules/' + name + '/package.json', 1024 * 1024)
        value = json.loads(raw)
        require(value['name'] == name and value['version'] == lock['packages']['node_modules/' + name]['version'],
                'installed-dependency-version')
        row = {'kind': 'guest-dependency', 'name': name, 'version': value['version'],
               'source': 'urn:lsf:registry:npm/' + name, 'digest': digest(raw), 'digestScope': 'source-manifest',
               'manifestDigest': digest(raw), 'manifestSize': len(raw), 'origin': 'observed-cache'}
        if value.get('license') in ('MIT', 'Apache-2.0', 'BSD-2-Clause', 'BSD-3-Clause', 'ISC', '0BSD'):
            row['licenseExpression'] = value['license']
        rows.append(row)
    return rows


def build(args):
    require(not args.output.exists() and args.output.parent.is_dir(), 'fresh-build-output')
    toolchain = args.toolchain.resolve(strict=True)
    for name in ('package.json', 'package-lock.json'):
        require(read(toolchain, name, 4 * 1024 * 1024) ==
                read(ROOT / 'examples/renderer-profile', name, 4 * 1024 * 1024), 'qualified-toolchain')
    node = Path(shutil.which('node')).resolve(strict=True)
    cli = args.cli.resolve(strict=True)
    materials = [file_identity(node, 'node'), file_identity(cli, 'package-assembler'),
                 file_identity(toolchain / 'package-lock.json', 'npm-lock'),
                 file_identity(ROOT / 'tools/toolchain.toml', 'toolchain-config')]
    recipe = canonical([file_identity(ROOT / path, path) for path in
                        ['tools/build_static_sites.py', 'tools/static_site.py', 'tools/static-sites/build.mjs']])
    materials.append(record('build-recipe', recipe))
    args.output.mkdir()
    summaries = []
    retained = {}
    with tempfile.TemporaryDirectory(prefix='lsf-static-build-') as temporary:
        temporary = Path(temporary)
        environment = build_environment(temporary)
        # Node subprocesses receive no inherited npm settings, tokens or Node options.
        environment['HOME'] = environment['USERPROFILE'] = str(temporary)
        require(run([node, '--version'], environment).strip() == b'v24.19.0', 'node-version')
        for name in NAMES:
            started = int(time.time())
            output = args.output / name
            output.mkdir()
            work = temporary / name
            source = temporary / (name + '-source')
            is_csr = name.startswith('csr-')
            public, files, observed = (csr(name[-1].upper(), source, work, toolchain, node, environment)
                                       if is_csr else generator('/docs' if name.endswith('docs') else '', source, work))
            if name == 'csr-b':
                for path, data in retained.items():
                    if path not in files:
                        (public / path).write_bytes(data)
                        files.append(path)
                observed['retainedPublicAssets'] = [record(path, data) for path, data in sorted(retained.items())]
            if name == 'csr-a':
                retained = {path: read(public, path, 8 * 1024 * 1024) for path in files if path != 'index.html'}
            inventory = canonical([file_identity(path, path.name, 65536) for path in sorted(source.iterdir())])
            public_records = [file_identity(public / path, path, 8 * 1024 * 1024) for path in sorted(files)]
            observed.update(actualFrameworkBuild=is_csr, publicOutputs=public_records, reproducibility='not-checked')
            observations = []
            for kind, data in [('source', inventory), ('toolchain', canonical(materials)), ('build', canonical(observed))]:
                (public / (kind + '.json')).write_bytes(data)
                observations.append({'kind': kind, 'source': kind + '.json', 'digest': digest(data)})
                (output / (kind + '.json')).write_bytes(data)
            config = {'formatVersion': 1, 'profile': 'static-site-input-v1', 'name': 'static-' + name,
                      'version': '1.0.0', 'assets': [{'path': '/' + path, 'source': path} for path in sorted(files)],
                      'entryDocument': '/index.html',
                      'directoryIndex': {'mode': 'disabled' if is_csr else 'redirect', 'document': '/index.html'},
                      'fallback': {'mode': 'spa', 'document': '/index.html'} if is_csr else {'mode': 'none'},
                      'excluded': ['server/main.mjs', '.env'], 'observations': observations}
            (output / 'static-site.json').write_bytes(canonical(config))
            capture(public, config, output / 'inputs')
            sbom_path = output / 'inputs/sbom-inputs.json'
            sbom = json.loads(sbom_path.read_bytes())
            sbom['entries'].extend(dependencies(toolchain, observed['dependencies']))
            sbom['entries'] = sorted(sbom['entries'], key=canonical)
            sbom_path.write_bytes(canonical(sbom))
            command = [cli, '--output', 'json', 'package', 'build', '--source', output / 'inputs/package-source.json',
                       '--input-root', output / 'inputs', '--sbom-inputs', sbom_path,
                       '--output-dir', output / 'package', '--validate-web']
            result = json.loads(run(command, environment))
            require(result['category'] == 'success', 'package-assembly')
            summary = result['data']
            require(summary['componentDigest'] is None and summary['webBuildOutputs'] and summary['sbomInventoryDigest'],
                    'componentless-package-inventory')
            outputs = summary['webBuildOutputs']
            assembly = {'formatVersion': 1, 'buildType': 'https://latent.dev/build/web-package-assembly/v1',
                        'source': {'repository': REPOSITORY, 'revision': digest(inventory)[7:],
                                   'snapshotDigest': digest(inventory), 'repositoryTrust': 'operator-asserted',
                                   'capture': 'explicit-input-files'},
                        'outputsDigest': outputs['digest'], 'outputsCount': outputs['count'], 'outputsBytes': int(outputs['bytes']),
                        'materials': sorted([*materials, record('source-snapshot', inventory),
                                             record('framework-build-observation', canonical(observed))], key=lambda row: row['name']),
                        'parameters': {'assembler': 'lsf-web-package-assembly', 'recipeVersion': 1,
                                       'inputMode': 'explicit-supplied-files'},
                        'startedAt': started, 'finishedAt': int(time.time()), 'reproducibility': 'not-checked',
                        'hermetic': False, 'dependencyCompleteness': 'declared-inputs-incomplete'}
            (output / 'observation.json').write_bytes(canonical(assembly))
            summaries.append({'name': name, 'packageDigest': summary['packageDigest'],
                              'assemblyObservation': digest(canonical(assembly)), 'outputs': outputs})
    (args.output / 'summary.json').write_bytes(canonical(summaries))
    print(json.dumps(summaries, separators=(',', ':')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--toolchain', type=Path, default=ROOT / 'examples/renderer-profile')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.absolute()
    build(args)


if __name__ == '__main__':
    main()
