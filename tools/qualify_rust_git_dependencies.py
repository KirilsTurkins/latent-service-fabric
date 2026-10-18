"""Real Git authoring/capture/offline metadata; no application compilation or node."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tomllib

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import application_dependencies as dependencies
from tools import cargo_native_authoring as authoring
from tools import rust_application_dependencies as native
from tools import rust_dependency_authoring as review
from tools.application_dependency_store import DependencyError
from tools.build_observation import build_environment, file_identity
from tools.build_process import run_bounded
from tools.build_snapshot import canonical, digest
from tools.rust_capsule_project import ROOT, create, fresh, snapshot

PACKAGE = 'unicode-xid'
REPOSITORY = 'https://github.com/unicode-rs/unicode-xid'
# Original upstream annotated release tags, resolved to their exact commits.
REVISIONS = (('0.2.5', '705256be0288a2d15ffb832ed3d8f25e8c14f49f'),
             ('0.2.6', '5d50587f19713cd35f1f48e5d4d011aa9c54dbff'))
MATERIALS = ('tools/qualify_rust_git_dependencies.py', 'tools/cargo_native_authoring.py',
             'tools/rust_application_dependencies.py', 'tools/rust_dependency_authoring.py',
             'tools/application_dependencies.py', 'tools/application_dependency_store.py',
             'tools/rust_capsule_project.py', 'tools/build_process.py', 'tools/build_observation.py')


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def offline(project: Path, output: Path, cargo: Path, version: str, revision: str) -> dict:
    """Materialize verified objects into fresh source/home, then ask real Cargo."""
    output.mkdir()
    before = snapshot(project)
    work, home = output / 'source', output / 'cargo-home'
    work.mkdir()
    require(not home.exists(), 'Git-offline-home-not-fresh')
    for name, raw in before.items():
        destination = work / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    closure = dependencies.prepare(project, work, output, 'rust')
    require(closure is not None, 'Git-reviewed-closure-missing')
    configured, configuration = native.configure(closure, work, home)
    environment = build_environment(output)
    pins = tomllib.loads((project / 'rust-toolchain.toml').read_text())
    environment.update(CARGO_HOME=str(home), HOME=str(output / 'home'), USERPROFILE=str(output / 'home'),
                       CARGO_NET_OFFLINE='true', RUSTUP_AUTO_INSTALL='0',
                       RUSTUP_TOOLCHAIN=pins['toolchain']['channel'],
                       RUSTC=str(cargo.parent / ('rustc.exe' if os.name == 'nt' else 'rustc')),
                       CARGO_TARGET_DIR=str(output / 'target'), GIT_CONFIG_NOSYSTEM='1',
                       GIT_CONFIG_GLOBAL=str(output / 'git-empty.config'), GIT_TERMINAL_PROMPT='0')
    (output / 'git-empty.config').write_bytes(b'')
    result = run_bounded([str(cargo), 'metadata', '--manifest-path', str(work / 'Cargo.toml'),
                          '--locked', '--offline', '--format-version', '1',
                          '--filter-platform', 'wasm32-unknown-unknown'],
                         work, environment, 120, native.MAX_METADATA_BYTES)
    source = authoring.selected_git(result.stdout, work, PACKAGE, version, REPOSITORY, revision)
    require(not (home / 'git').exists() and not (home / 'registry').exists(), 'Git-offline-cache-was-populated')
    require(snapshot(project) == before, 'Git-offline-original-project-mutated')
    closure.check_unchanged()
    return {'status': 'passed', 'inputIdentity': closure.identity, 'package': PACKAGE,
            'version': version, 'revision': revision, 'nativeSourceDigest': digest(source.encode()),
            'nativeMetadataDigest': digest(result.stdout), 'nativeMetadataSize': len(result.stdout),
            'selectedManifestDigest': digest(configured), 'configuration': configuration,
            'freshCargoHome': True, 'gitAndRegistryCachesAbsent': True,
            'networkResolution': False, 'applicationCompilation': False}


def qualify(output: Path, cargo: Path) -> dict:
    output, cargo = fresh(output), cargo.resolve(strict=True)
    stage = 'create'
    materials = {name: file_identity(ROOT / name, name) for name in MATERIALS}
    tools = {name: file_identity(path, name) for name, path in {
        'cargo': cargo, 'rustc': cargo.parent / ('rustc.exe' if os.name == 'nt' else 'rustc')}.items()}
    try:
        project = create(output / 'application', 'greeting', 'git-captured-greeting')
        original = snapshot(project)
        sdk_lock = (project / 'sdk-lock.json').read_bytes()
        sdk_graph = tomllib.loads((project / 'Cargo.lock').read_text())
        require(not any(row['name'] == PACKAGE for row in sdk_graph['package']), 'Git-fixture-already-in-SDK-lock')
        phases, previous = [], None
        for index, (version, revision) in enumerate(REVISIONS):
            stage = f'git-{"add" if index == 0 else "update"}'
            locked = authoring.author(project, 'add' if index == 0 else 'update', identity=PACKAGE,
                                      version=version, git=REPOSITORY, revision=revision, cargo=cargo)
            refusal = None
            if previous is not None:
                stage = 'stale-reviewed-closure'
                try:
                    review.status(project)
                except DependencyError as error:
                    require(str(error) == 'dependency-native-lock-drift', 'Git-stale-closure-wrong-refusal')
                    refusal = str(error)
                else:
                    raise ValueError('Git-changed-revision-reused-old-closure')
                require((project / dependencies.LOCK).read_bytes() == previous, 'Git-update-replaced-accepted-lock')
            stage = 'resolve-and-vendor'
            candidate = output / f'candidate-{index}.json'
            captured = native.resolve(project, candidate, cargo=cargo)
            selected = [row for row in captured['artifacts'] if row['metadata'].get('package') == PACKAGE]
            require(len(selected) == 1 and selected[0]['metadata']['version'] == version
                    and selected[0]['role'] == 'application', 'Git-captured-package-mismatch')
            require(not captured['executableInputs'], 'Git-fixture-executable-tools-not-expected')
            stage = 'exact-review'
            candidate_raw = candidate.read_bytes()
            review.review(project, candidate, digest(candidate_raw))
            require(review.status(project)['status'] == 'verified', 'Git-reviewed-status-not-verified')
            accepted = (project / dependencies.LOCK).read_bytes()
            require(accepted == candidate_raw, 'Git-review-published-different-candidate')
            if previous is not None:
                require(previous != accepted, 'Git-revision-update-did-not-change-capture')
            stage = 'fresh-home-offline-metadata'
            observed = offline(project, output / f'offline-{index}', cargo, version, revision)
            require((project / 'sdk-lock.json').read_bytes() == sdk_lock
                    and (project / 'src/lib.rs').read_bytes() == original['src/lib.rs'], 'Git-authoring-mutated-SDK-or-source')
            phase = {'status': 'passed', 'version': version, 'revision': revision,
                     'authoring': locked, 'candidateDigest': digest(candidate_raw),
                     'nativeLockDigest': digest((project / 'Cargo.lock').read_bytes()),
                     'nativeGraphDigest': digest((project / 'cargo-resolved.lock.json').read_bytes()),
                     'artifactIdentity': selected[0]['id'], 'artifactTreeDigest': selected[0]['treeDigest'],
                     'staleClosureRefusal': refusal, 'offline': observed}
            (output / f'phase-{index}.json').write_bytes(canonical(phase) + b'\n')
            phases.append(phase)
            previous = accepted
        require(materials == {name: file_identity(ROOT / name, name) for name in MATERIALS}, 'Git-qualification-recipe-mutated')
        require(tools == {name: file_identity(cargo if name == 'cargo' else cargo.parent / ('rustc.exe' if os.name == 'nt' else 'rustc'), name)
                          for name in tools}, 'Git-qualification-tools-mutated')
        result = {'formatVersion': 1, 'status': 'passed', 'scope': 'actual native Git authoring/capture/review/offline metadata',
                  'package': PACKAGE, 'repository': REPOSITORY, 'phases': phases, 'materials': materials,
                  'tools': tools, 'sdkLockDigest': digest(sdk_lock),
                  'catalogueRegistration': False, 'applicationCompilation': False,
                  'signedNodeQualification': False, 'hermetic': False}
        (output / 'qualification.json').write_bytes(canonical(result) + b'\n')
        return result
    except Exception as error:
        # Native process errors have static codes. Never project raw argv/streams.
        code = str(error) if isinstance(error, DependencyError) else type(error).__name__
        (output / 'FAILED.json').write_bytes(canonical({'status': 'failed', 'stage': stage, 'error': code,
            'materials': materials, 'applicationCompilation': False, 'signedNodeQualification': False}) + b'\n')
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cargo', type=Path, required=True)
    arguments = parser.parse_args(argv)
    result = qualify(arguments.output, arguments.cargo)
    print(json.dumps({'status': result['status'], 'phases': len(result['phases']), 'applicationCompilation': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
