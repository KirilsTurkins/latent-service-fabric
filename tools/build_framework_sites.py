#!/usr/bin/env python3
"""Build and capture the maintained framework fixtures; never authorize execution."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment, file_identity
from tools.build_process import run_bounded_result
from tools.build_snapshot import canonical, digest
from tools.build_static_sites import dependencies, record, REPOSITORY
from tools.static_site import capture, read, require

ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN = ROOT / 'examples/framework-compatibility'
NAMES = ('angular-root', 'angular-mounted', 'docs-root', 'docs-mounted')
RECIPE_PROFILE = 'latent.framework.static-recipe.v1'


def run(command, environment, cwd=TOOLCHAIN, seconds=300, stage='framework-tool'):
    result = run_bounded_result([str(value) for value in command], cwd=cwd, env=environment,
                               timeout_seconds=seconds, max_output_bytes=2 * 1024 * 1024)
    # Keep private command output out of diagnostics; stage is a recipe-owned label.
    require(result.returncode == 0, stage + '-command-exit')
    return result.stdout


def source_inventory():
    files = [path for path in TOOLCHAIN.iterdir() if path.is_file() and path.suffix in ('.json', '.mjs')]
    files += list((TOOLCHAIN / 'angular').rglob('*.ts')) + [TOOLCHAIN / 'angular/tsconfig.json']
    for relative in ('documentation/docs', 'documentation/i18n'):
        files += [path for path in (TOOLCHAIN / relative).rglob('*') if path.is_file()]
    files += [TOOLCHAIN / 'documentation/docusaurus.config.mjs', TOOLCHAIN / 'documentation/style.css']
    require(len(files) <= 128 and not any(path.is_symlink() for path in files), 'framework-source-inventory')
    return canonical([file_identity(path, path.relative_to(TOOLCHAIN).as_posix(), 4 * 1024 * 1024)
                      for path in sorted(set(files))])


def build(args):
    require(not args.output.exists() and args.output.parent.is_dir(), 'fresh-framework-output')
    cli, chrome = args.cli.resolve(strict=True), args.chrome.resolve(strict=True)
    node = Path(shutil.which('node')).resolve(strict=True)
    reviewed = json.loads(read(TOOLCHAIN, 'reviewed-styles.json', 65536))
    packages = json.loads(read(TOOLCHAIN, 'package.json', 65536))['dependencies']
    inventory = source_inventory()
    materials = [file_identity(node, 'node'), file_identity(cli, 'package-assembler'),
                 file_identity(TOOLCHAIN / 'package-lock.json', 'npm-lock'),
                 file_identity(ROOT / 'tools/toolchain.toml', 'toolchain-config')]
    recipe = canonical([file_identity(ROOT / path, path) for path in [
        'tools/build_framework_sites.py', 'tools/static_site.py',
        'examples/framework-compatibility/bundle-angular.mjs',
        'examples/framework-compatibility/capture-styles.mjs',
        'examples/framework-compatibility/prepare-documentation.mjs']])
    materials.append(record('build-recipe', recipe))
    args.output.mkdir()
    summaries = []
    with tempfile.TemporaryDirectory(prefix='lsf-framework-build-') as temporary:
        environment = build_environment(Path(temporary))
        environment.update(HOME=temporary, USERPROFILE=temporary, CI='true')
        require(run([node, '--version'], environment).strip() == b'v24.19.0', 'node-version')
        run([node, TOOLCHAIN / 'node_modules/@angular/compiler-cli/bundles/src/bin/ngc.js',
             '-p', TOOLCHAIN / 'angular/tsconfig.json'], environment)
        for name in NAMES:
            started = int(time.time())
            output = args.output / name
            output.mkdir()
            angular = name.startswith('angular')
            mount = ('/app' if angular else '/docs') if name.endswith('mounted') else '/'
            public = output / 'public-output'
            if angular:
                run([node, TOOLCHAIN / 'bundle-angular.mjs', public, mount], environment)
                run([node, TOOLCHAIN / 'capture-styles.mjs', public, mount, chrome, output / 'styles.json'], environment)
                observed_styles = json.loads((output / 'styles.json').read_bytes())
                require(observed_styles['styleHashes'] == reviewed['styleHashes'],
                        'unreviewed-runtime-style: inspect changed framework/component CSS; do not auto-approve hashes')
            else:
                generated = output / 'generated'
                run([node, TOOLCHAIN / 'node_modules/@docusaurus/core/bin/docusaurus.mjs', 'build',
                     TOOLCHAIN / 'documentation', '--out-dir', generated],
                    dict(environment, LSF_DOCS_BASE='/' if mount == '/' else mount + '/'))
                run([node, TOOLCHAIN / 'prepare-documentation.mjs', generated, public, mount], environment)
            files = sorted(path.relative_to(public).as_posix() for path in public.rglob('*') if path.is_file())
            require(not any(path.is_symlink() for path in public.rglob('*')), 'linked-framework-output')
            observed = {'recipeProfile': RECIPE_PROFILE, 'actualFrameworkBuild': True, 'framework': 'angular-primeng' if angular else 'docusaurus',
                        'versions': packages, 'mount': mount, 'serverRenderer': False,
                        'publicOutputs': [file_identity(public / name, name, 8 * 1024 * 1024) for name in files],
                        'runtimeBrowserQualified': False, 'reproducibility': 'not-checked'}
            if angular:
                observed['styleObservation'] = observed_styles
            else:
                observed['buildTransformation'] = json.loads(Path(str(public) + '-transformation.json').read_bytes())
            observations = []
            for kind, data in [('source', inventory), ('toolchain', canonical(materials)), ('build', canonical(observed))]:
                (public / (kind + '.json')).write_bytes(data)
                observations.append({'kind': kind, 'source': kind + '.json', 'digest': digest(data)})
                (output / (kind + '.json')).write_bytes(data)
            config = {'formatVersion': 1, 'profile': 'static-site-input-v1', 'name': 'framework-' + name,
                      'version': '1.0.0', 'assets': [{'path': '/' + name, 'source': name} for name in files],
                      'entryDocument': '/index.html',
                      'directoryIndex': {'mode': 'disabled' if angular else 'redirect', 'document': '/index.html'},
                      'fallback': {'mode': 'spa', 'document': '/index.html'} if angular else {'mode': 'none'},
                      'styleHashes': reviewed['styleHashes'] if angular else [],
                      'excluded': [], 'observations': observations}
            if not angular:
                require('404.html' in files, 'docusaurus-error-document-output')
                config['errorDocument'] = {'profile': 'html-not-found-v1', 'document': '/404.html'}
            (output / 'static-site.json').write_bytes(canonical(config))
            captured = capture(public, config, output / 'inputs')
            (output / 'capture-budget.json').write_bytes(canonical(captured['budget']))
            sbom_path = output / 'inputs/sbom-inputs.json'
            sbom = json.loads(sbom_path.read_bytes())
            sbom['entries'].extend(dependencies(TOOLCHAIN, packages))
            sbom['entries'] = sorted(sbom['entries'], key=canonical)
            sbom_path.write_bytes(canonical(sbom))
            result = json.loads(run([cli, '--output', 'json', 'package', 'build', '--source', output / 'inputs/package-source.json',
                '--input-root', output / 'inputs', '--sbom-inputs', sbom_path, '--output-dir', output / 'package', '--validate-web'], environment,
                stage=name + '-package-assembly'))
            require(result['category'] == 'success', 'framework-package-assembly')
            summary = result['data']
            require(summary['componentDigest'] is None and summary['webBuildOutputs'], 'framework-static-package')
            outputs = summary['webBuildOutputs']
            assembly = {'formatVersion': 1, 'buildType': 'https://latent.dev/build/web-package-assembly/v1',
                'source': {'repository': REPOSITORY, 'revision': digest(inventory)[7:], 'snapshotDigest': digest(inventory),
                           'repositoryTrust': 'operator-asserted', 'capture': 'explicit-input-files'},
                'outputsDigest': outputs['digest'], 'outputsCount': outputs['count'], 'outputsBytes': int(outputs['bytes']),
                'materials': sorted([*materials, record('source-snapshot', inventory),
                    record('framework-build-observation', canonical(observed))], key=lambda row: row['name']),
                'parameters': {'assembler': 'lsf-web-package-assembly', 'recipeVersion': 1, 'inputMode': 'explicit-supplied-files'},
                'startedAt': started, 'finishedAt': int(time.time()), 'reproducibility': 'not-checked',
                'hermetic': False, 'dependencyCompleteness': 'declared-inputs-incomplete'}
            (output / 'observation.json').write_bytes(canonical(assembly))
            summaries.append({'name': name, 'packageDigest': summary['packageDigest'], 'outputs': outputs,
                              'recipeProfile': RECIPE_PROFILE, 'runtimeBrowserQualified': False,
                              'captureBudget': captured['budget']})
    (args.output / 'summary.json').write_bytes(canonical(summaries))
    print(json.dumps(summaries, separators=(',', ':')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', required=True, type=Path)
    parser.add_argument('--chrome', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output = args.output.absolute()
    build(args)
