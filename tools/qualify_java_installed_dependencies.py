#!/usr/bin/env python3
"""Qualify a local installed Java candidate without claiming publisher trust.

Run with the delivered isolated Python, an application and its verified CAS
already staged in a private work directory, and readonly compiler/candidate
mounts. This owner imports only the Python standard library, not a checkout.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def identity(path):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'sha256': 'sha256:' + digest, 'bytes': path.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work', 'installed', 'candidate'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('expect-source', 'expect-archive-sha256', 'expect-component-sha256'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    require(re.fullmatch('[0-9a-f]{40}', args.expect_source), 'source-commit-required')
    for value in (args.expect_archive_sha256, args.expect_component_sha256):
        require(re.fullmatch('sha256:[0-9a-f]{64}', value), 'exact-digest-required')
    work, installed, candidate = (path.absolute() for path in (args.work, args.installed, args.candidate))
    require(os.geteuid() == 1000, 'unprivileged-linux-owner-required')
    require(all((work / name).is_dir() for name in ('attempt/app', 'attempt/build-cache',
                                                 'home', 'tmp', 'outside-checkout')), 'fresh-owned-attempt-layout')
    require(not any((work / name).exists() for name in ('installed-java-dependencies-qualified.json',
                    'installed-java-dependencies-FAILED.json', 'verify-original-capture.stdout')), 'fresh-attempt-required')
    app = work / 'attempt/app'
    python = installed / 'sdk/bin/python'
    cli = installed / 'recipe/tools/java_capsule.py'
    record = {'status': 'in-progress', 'publisherAuthenticated': False,
              'scope': 'local-candidate-captured-Java-offline-build-and-declaration-invalidation',
              'effectiveUser': os.geteuid(), 'commands': []}
    environment = {'PATH': '/nonexistent', 'HOME': str(work / 'home'), 'TMPDIR': str(work / 'tmp'),
                   'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}

    def run(name, *arguments, expected=0, timeout=900):
        start = time.monotonic()
        with (work / (name + '.stdout')).open('xb') as out, (work / (name + '.stderr')).open('xb') as err:
            result = subprocess.run([str(python), '-I', '-B', *map(str, arguments)],
                                    cwd=work / 'outside-checkout', env=environment,
                                    stdout=out, stderr=err, timeout=timeout)
        require(all((work / (name + suffix)).stat().st_size <= 4 * 1024 * 1024
                    for suffix in ('.stdout', '.stderr')), 'qualification-output-limit')
        record['commands'].append({'name': name, 'exitCode': result.returncode,
            'elapsedSeconds': time.monotonic() - start, 'stdout': identity(work / (name + '.stdout')),
            'stderr': identity(work / (name + '.stderr'))})
        require(result.returncode == expected, name + '-unexpected-exit')
        return (work / (name + ('.stdout' if expected == 0 else '.stderr'))).read_bytes()

    try:
        document = json.loads((candidate / 'developer-bundle.json').read_bytes())
        require(document['sourceCommit'] == args.expect_source, 'candidate-source-mismatch')
        require(document['archive']['sha256'] == args.expect_archive_sha256, 'candidate-archive-mismatch')
        record.update(candidateSource=document['sourceCommit'], candidateManifest=identity(candidate / 'developer-bundle.json'),
            candidateArchive=document['archive'], managedInputs=identity(installed / 'sdk/managed-inputs.json'),
            adapter=identity(installed / 'recipe/tools/dev_guest_recipe.py'), qualifier=identity(Path(__file__)))
        original = {name: (app / name).read_bytes() for name in ('java-dependencies.json', 'sdk-lock.json',
                                                               'latent.dependencies.lock.json', 'java-resolved.lock.json')}
        before = json.loads(run('verify-original-capture', cli, 'dependencies', app, timeout=30))
        require(before['status'] == 'verified', 'original-capture-not-verified')
        record['capturedInputIdentity'] = before['capturedInputIdentity']
        result = json.loads(run('offline-installed-build', installed / 'recipe/tools/dev_guest_recipe.py',
            '--language', 'java', '--project', app, '--output', work / 'attempt/output'))
        require(result['code'] == 'success' and result['cleanup'] == 'reaped', 'installed-build-not-complete')
        output = work / 'attempt/output'
        complete = json.loads((output / 'BUILD-COMPLETE.json').read_bytes())
        require(complete['packageAssembled'] is False, 'compiler-must-not-claim-controller-packaging')
        record['artifacts'] = {name: identity(output / name) for name in ('component.wasm', 'source-inputs.json',
            'recipe-inputs.json', 'compiler-inputs.json', 'application-dependencies.json', 'java-classpath.json',
            'build-observation.json', 'BUILD-COMPLETE.json')}
        require(record['artifacts']['component.wasm']['sha256'] == args.expect_component_sha256,
                'installed-component-differs-from-qualified-component')
        for operation, arguments in (('update', ('commons-codec:commons-codec', '--version', '1.17.2')),
                                     ('remove', ('commons-codec:commons-codec',))):
            edit = json.loads(run(operation, cli, operation, app, *arguments, timeout=30))
            require(edit['reviewRequired'] and edit['previousLockPreserved'] and edit['compilerExecution'] is False,
                    'declaration-edit-bypassed-review')
            refused = json.loads(run(operation + '-requires-review', cli, 'dependencies', app, expected=1, timeout=30))
            require(refused['reason'] == 'dependency-native-lock-drift', 'declaration-drift-not-denied')
            for name in ('sdk-lock.json', 'latent.dependencies.lock.json', 'java-resolved.lock.json'):
                require((app / name).read_bytes() == original[name], 'edit-mutated-accepted-or-sdk-lock')
        run('restore-normal-declaration', cli, 'add', app, 'commons-codec:commons-codec:1.17.1', timeout=30)
        added, approved = (json.loads(raw) for raw in ((app / 'java-dependencies.json').read_bytes(),
                                                       original['java-dependencies.json']))
        for configuration in (added, approved):
            configuration['dependencies'].sort(key=lambda row: json.dumps(row, sort_keys=True))
        require(added == approved, 'normal-add-did-not-restore-same-declarations')
        record['exactDeclarationOrderRestored'] = (app / 'java-dependencies.json').read_bytes() != original['java-dependencies.json']
        if record['exactDeclarationOrderRestored']:
            # Native locks bind exact configuration bytes, including order.
            # Equal declarations alone cannot revive an old approval. Restore
            # only the exact original configuration verified before this test.
            refused = json.loads(run('reordered-add-requires-review', cli, 'dependencies', app, expected=1, timeout=30))
            require(refused['reason'] == 'dependency-native-lock-drift', 'reordered-add-bypassed-review')
            (app / 'java-dependencies.json').write_bytes(original['java-dependencies.json'])
        require((app / 'java-dependencies.json').read_bytes() == original['java-dependencies.json'],
                'original-reviewed-configuration-not-restored')
        restored = json.loads(run('verify-restored-capture', cli, 'dependencies', app, timeout=30))
        require(restored['capturedInputIdentity'] == before['capturedInputIdentity'], 'restored-capture-identity-drift')
        require(identity(Path(__file__)) == record['qualifier'], 'installed-qualifier-mutated')
        record.update(status='passed', releaseQualification=False,
                      remainingAcceptance=['authenticated frontend watch/update deployment lifecycle'])
        (work / 'installed-java-dependencies-qualified.json').write_text(json.dumps(record, indent=2) + '\n')
        return 0
    except BaseException as error:
        record.update(status='failed', reason=str(error) if isinstance(error, ValueError) else type(error).__name__)
        (work / 'installed-java-dependencies-FAILED.json').write_text(json.dumps(record, indent=2) + '\n')
        raise


if __name__ == '__main__':
    raise SystemExit(main())
