#!/usr/bin/env python3
"""Verify a local C candidate and exercise its installed offline authoring tools.

Run as UID1000 in a network-none container with no checkout mount. Candidate
and captured-project inputs are readonly. Local source candidates do not carry
publisher authentication or establish released frontend qualification.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def identity(path):
    with path.open('rb') as stream:
        value = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'sha256': 'sha256:' + value, 'bytes': path.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('candidate', 'capture', 'work'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--expect-source', required=True)
    parser.add_argument('--expect-archive-sha256', required=True)
    args = parser.parse_args()
    require(os.geteuid() == 1000, 'unprivileged-linux-owner-required')
    require(re.fullmatch('[0-9a-f]{40}', args.expect_source), 'exact-source-required')
    require(re.fullmatch('sha256:[0-9a-f]{64}', args.expect_archive_sha256), 'exact-archive-required')
    work, candidate = args.work.absolute(), args.candidate.resolve(strict=True)
    require(not work.exists(), 'fresh-installed-c-work-required')
    work.mkdir(mode=0o700)
    record = {'status': 'in-progress', 'publisherAuthenticated': False, 'releasePublished': False,
              'scope': 'installed-C-creation-offline-library-build-and-review-invalidation',
              'effectiveUser': os.geteuid(), 'commands': [], 'qualifier': identity(Path(__file__))}
    began = time.monotonic()
    try:
        sys.path.insert(0, str(candidate / 'helper.pyz'))
        from tools.dev_workflow import bundle
        from tools.build_process import run_bounded_result
        document = candidate / 'developer-bundle.json'
        selected = json.loads(document.read_bytes())
        require(selected['sourceCommit'] == args.expect_source
                and selected['archive']['sha256'] == args.expect_archive_sha256, 'candidate-selection-mismatch')
        selected = bundle.manifest(selected, target='linux-x86_64', version=selected['version'],
                                   commit=args.expect_source)
        installed = work / 'installed'
        bundle.extract(candidate, selected, installed)
        record.update(candidateSource=args.expect_source, archive=selected['archive'],
                      manifest=identity(document), helper=identity(candidate / 'helper.pyz'))
        for name in ('outside-checkout', 'home', 'tmp', 'creators', 'attempt'):
            (work / name).mkdir(mode=0o700)
        python, cli = installed / 'sdk/bin/python', installed / 'recipe/tools/c_capsule.py'
        environment = {'PATH': '/nonexistent', 'HOME': str(work / 'home'), 'TMPDIR': str(work / 'tmp'),
                       'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}

        def run(name, *arguments, expected=0, timeout=120, structured=True):
            require(len(record['commands']) < 24 and time.monotonic() - began < 900, 'original-qualification-bound')
            start = time.monotonic()
            result = run_bounded_result([str(python), '-I', '-B', *map(str, arguments)], cwd=work / 'outside-checkout',
                env=environment, timeout_seconds=min(timeout, 900 - (time.monotonic() - began)), max_output_bytes=1048576)
            for suffix, raw in (('.stdout', result.stdout), ('.stderr', result.stderr)):
                (work / (name + suffix)).write_bytes(raw)
            record['commands'].append({'name': name, 'exitCode': result.returncode,
                'elapsedSeconds': time.monotonic() - start, 'stdout': identity(work / (name + '.stdout')),
                'stderr': identity(work / (name + '.stderr'))})
            require(max(len(result.stdout), len(result.stderr)) <= 1048576, 'installed-c-output-limit')
            require(result.returncode == expected, name + '-unexpected-exit')
            return json.loads(result.stdout if expected == 0 else result.stderr) if structured else None

        for template in ('greeting', 'word-count', 'shipping', 'http-status', 'recovery', 'transactional-aggregate'):
            run('create-' + template, cli, 'new', work / 'creators' / template, '--template', template, structured=False)
        app = work / 'attempt/app'
        shutil.copytree(args.capture.resolve(strict=True), app, ignore=shutil.ignore_patterns('target'))
        (work / 'attempt/build-cache').mkdir(mode=0o700)
        names = ('latent.dependencies.json', 'latent.dependencies.lock.json', 'sdk-lock.json')
        original = {name: (app / name).read_bytes() for name in names}
        before = run('verify-capture', cli, 'dependencies', app)
        require(before['status'] == 'verified', 'captured-c-inputs-not-verified')
        record['capturedInputIdentity'] = before['capturedInputIdentity']
        built = run('offline-build', installed / 'recipe/tools/dev_guest_recipe.py', '--language', 'c',
                    '--project', app, '--output', work / 'attempt/output', timeout=600)
        require(built['code'] == 'success' and built['cleanup'] == 'reaped', 'installed-c-compiler-not-complete')
        output = work / 'attempt/output'
        require(json.loads((output / 'BUILD-COMPLETE.json').read_bytes())['packageAssembled'] is False,
                'compiler-must-leave-controller-packaging')
        record['artifacts'] = {name: identity(output / name) for name in ('component.wasm', 'source-inputs.json',
            'recipe-inputs.json', 'application-dependencies.json', 'build-observation.json', 'BUILD-COMPLETE.json')}
        approved = json.loads(original['latent.dependencies.json'])
        artifact = approved['artifacts'][0]
        edited = copy.deepcopy(artifact)
        edited['mount'] += '-edited'
        for name, value in (('original-artifact', artifact), ('edited-artifact', edited)):
            (work / (name + '.json')).write_text(json.dumps(value) + '\n')
        for operation, arguments in (
            ('update', ['--id', artifact['id'], '--artifact', work / 'edited-artifact.json']),
            ('remove', ['--id', artifact['id']]),
        ):
            changed = run(operation, cli, operation, app, *arguments)
            require(changed['reviewRequired'] and changed['previousLockPreserved'] and not changed['compilerExecution'],
                    'declaration-edit-bypassed-review')
            refused = run(operation + '-requires-review', cli, 'dependencies', app, expected=1)
            require(refused['reason'] == 'dependency-lock-drift-resolve-and-review', 'changed-c-closure-not-denied')
            require(all((app / name).read_bytes() == original[name] for name in names[1:]), 'edit-altered-accepted-lock')
        run('add-original', cli, 'add', app, '--artifact', work / 'original-artifact.json')
        added = json.loads((app / names[0]).read_bytes())
        for value in (added, approved):
            value['artifacts'].sort(key=lambda row: row['id'])
        require(added == approved, 'normal-add-changed-reviewed-declarations')
        record['normalAddChangedDeclarationOrder'] = (app / names[0]).read_bytes() != original[names[0]]
        if record['normalAddChangedDeclarationOrder']:
            refused = run('reordered-add-requires-review', cli, 'dependencies', app, expected=1)
            require(refused['reason'] == 'dependency-lock-drift-resolve-and-review', 'reordered-add-bypassed-review')
            (app / names[0]).write_bytes(original[names[0]])
        restored = run('verify-original-reviewed-bytes', cli, 'dependencies', app)
        require(restored['capturedInputIdentity'] == before['capturedInputIdentity'], 'restored-capture-identity-drift')
        require(identity(Path(__file__)) == record['qualifier'], 'qualifier-source-changed')
        record.update(status='passed', elapsedSeconds=time.monotonic() - began,
                      remainingAcceptance=['authenticated frontend watch and newly reviewed version deployment'])
        (work / 'qualified.json').write_text(json.dumps(record, indent=2) + '\n')
    except BaseException as error:
        record.update(status='failed', reason=str(error) if isinstance(error, ValueError) else type(error).__name__)
        (work / 'FAILED.json').write_text(json.dumps(record, indent=2) + '\n')
        raise
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
