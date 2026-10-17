"""Normal reviewed Maven capture for two unchanged default-worker libraries."""
from __future__ import annotations

from pathlib import Path

from tools.application_dependencies import prepare, verify_inputs
from tools.build_snapshot import digest
from tools.java_application_dependencies import classpath
from tools.java_capsule_project import create
from tools.java_dependency_authoring import edit, review
from tools.java_dependency_resolution import resolve
from tools.rust_capsule_project import fresh, inventory, read_file, snapshot, write_json


LIBRARIES = {
    'org.apache.commons:commons-lang3:3.14.0':
        'sha256:7b96bf3ee68949abb5bc465559ac270e0551596fa34523fddf890ec418dde13c',
    'cn.hutool:hutool-core:5.8.40':
        'sha256:d6bedc908cba480cd12dbe6f8422fa60c0da31030b58a68c3c077f555fc0cbbc',
}


def capture(output: Path, *, gradle: str) -> tuple[tuple[Path, ...], tuple[Path, ...], dict]:
    """Resolve explicitly, review exact bytes, then materialize the sealed closure.

    The source fixture exercises library workers at execution time. No library
    class is initialized here; JDK reference execution is a later explicit step.
    """
    root = fresh(output)
    application = create(root / 'application', 'greeting')
    sdk = read_file(application / 'sdk-lock.json')
    for coordinate in LIBRARIES:
        edit(application, 'add', coordinate=coordinate)
    candidate = root / 'candidate.json'
    lock = resolve(application, candidate, gradle=gradle)
    application_artifacts = [row for row in lock['artifacts'] if row['role'] == 'application'
                             and row['metadata'].get('assetType') != 'maven-resolution-metadata']
    observed = {row['id']: row['original']['digest'] for row in application_artifacts}
    if observed != LIBRARIES:
        raise ValueError('Java worker libraries require the exact reviewed original Maven archives')
    review(application, candidate, digest(read_file(candidate, 8 * 1024 * 1024)))
    if verify_inputs(application, 'java') is None:
        raise ValueError('Java worker libraries require normal accepted dependency inputs')
    work = fresh(root / 'offline-inputs')
    receipts = fresh(root / 'receipts')
    closure = prepare(application, work, receipts, 'java')
    jars, selected = classpath(closure, root / 'selected-application-jars')
    originals = tuple(work / row['mount'] for row in application_artifacts)
    if read_file(application / 'sdk-lock.json') != sdk:
        raise ValueError('Java worker library capture changed the SDK lock')
    closure.check_unchanged()
    write_json(receipts / 'java-classpath.json', selected)
    report = {
        'status': 'captured-not-executed', 'sourceModified': False, 'externalExecutorInjected': False,
        'originalLibraries': observed, 'capturedInputIdentity': closure.identity,
        'sdkLockDigest': digest(sdk), 'applicationIdentity': digest(inventory(snapshot(application))),
        'selectedJars': [{'id': row['id'], 'originalDigest': row['originalDigest'],
                          'selectedDigest': row['selectedDigest']} for row in selected['artifacts']],
        'classpathDigest': digest(read_file(receipts / 'java-classpath.json', 8 * 1024 * 1024)),
    }
    write_json(receipts / 'capture.json', report)
    return jars, originals, report


def check(output: Path, report: dict) -> None:
    root = output
    verified = verify_inputs(root / 'application', 'java')
    if verified is None:
        raise ValueError('Java worker library accepted dependency closure disappeared')
    if digest(inventory(snapshot(root / 'application'))) != report['applicationIdentity']:
        raise ValueError('Java worker library acquired source changed')
    for artifact in verified.lock['artifacts']:
        if artifact['id'] in LIBRARIES:
            original = read_file(root / 'offline-inputs' / artifact['mount'], 64 * 1024 * 1024)
            if digest(original) != LIBRARIES[artifact['id']]:
                raise ValueError('Java worker library original archive changed')
    if digest(read_file(root / 'receipts/java-classpath.json', 8 * 1024 * 1024)) != report['classpathDigest']:
        raise ValueError('Java worker library classpath receipt changed')
    for index, row in enumerate(report['selectedJars']):
        if digest(read_file(root / 'selected-application-jars' / f'{index:04d}.jar', 64 * 1024 * 1024)) != row['selectedDigest']:
            raise ValueError('Java worker library selected archive changed')
