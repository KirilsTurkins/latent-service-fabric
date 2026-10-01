"""Bind reviewed frontend dependency inputs to the selected application build."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from tools import application_dependencies as dependencies
from tools.application_dependency_store import DependencyError, read_bytes, regular_path
from tools.build_snapshot import canonical, digest
from tools.rust_capsule_project import MAX_FILE, MAX_FILES, MAX_SOURCE, decode_json, snapshot

DESCRIPTOR = 'latent.project.json'
MAPPING = 'frontend-dependency-inputs.json'
RECIPE = ('tools/guest_dependency_inputs.py', 'tools/application_dependencies.py',
          'tools/application_dependency_store.py', 'tools/application_dependency_tools.py',
          'tools/application_dependency_approval.py', 'tools/build_snapshot.py',
          'tools/build_process.py', 'tools/build_process_linux.py',
          'tools/build_process_windows.py', 'tools/build_process_signals.py',
          'tools/rust_capsule_project.py', 'tools/dev_workflow/__init__.py',
          'tools/dev_workflow/common.py', 'tools/dev_workflow/project.py',
          'tools/dev_workflow/dependencies.py', 'tools/dev_workflow/snapshot.py',
          'tools/dev_workflow/paths.py', 'tools/dev_workflow/state.py',
          'tools/dev_workflow/windows.py')


def layout(project: Path, language: str) -> tuple[Path, Path, bytes | None]:
    """Find an exact descriptor/application association, never a sibling capture."""
    from tools.dev_workflow import common, project as frontend
    requested = regular_path(project)
    selected = None
    for ordinal, root in enumerate((requested, *requested.parents)):
        if ordinal > 32:
            break
        if not os.path.lexists(root / DESCRIPTOR):
            continue
        if selected is not None:
            raise DependencyError('dependency-frontend-ambiguous-project-descriptor')
        raw = read_bytes(root / DESCRIPTOR, common.MAX_DOCUMENT)
        descriptor = frontend.validate(common.decode(raw))
        if descriptor['language'] != language:
            raise DependencyError('dependency-frontend-language-mismatch')
        app = regular_path(root / descriptor['build']['workingDirectory'])
        if app == root or not app.is_relative_to(root) or requested not in {root, app}:
            raise DependencyError('dependency-frontend-application-layout')
        if os.path.lexists(app / DESCRIPTOR):
            raise DependencyError('dependency-frontend-ambiguous-project-descriptor')
        selected = root, app, raw
    return selected or (requested, requested, None)


def application_root(project: Path, language: str) -> Path:
    return layout(project, language)[1]


def _insert(files: dict[str, bytes], name: str, raw: bytes) -> None:
    from tools.dev_workflow import paths
    paths.relative(name)
    if len(raw) > MAX_FILE:
        raise DependencyError('dependency-frontend-source-file-limit')
    aliases = {paths.alias(key): key for key in files}
    previous = aliases.get(paths.alias(name))
    if previous is not None and (previous != name or files[previous] != raw):
        raise DependencyError('dependency-frontend-source-input-collision')
    files[name] = raw


@dataclass(frozen=True)
class SourceInputs:
    requested: Path
    application: Path
    dependency_root: Path
    language: str
    files: dict[str, bytes]
    descriptor: bytes | None
    exclude_when_captured: tuple[str, ...]

    def check_unchanged(self) -> None:
        after = capture_source(self.requested, self.language,
                               exclude_when_captured=self.exclude_when_captured)
        if (after.application != self.application or after.dependency_root != self.dependency_root
                or after.descriptor != self.descriptor or after.files != self.files):
            raise DependencyError('dependency-frontend-source-input-mutated')


def capture_source(project: Path, language: str, *,
                   exclude_when_captured: tuple[str, ...] = ()) -> SourceInputs:
    """Observe native-path projection without transferring the CAS into the compiler."""
    from tools.dev_workflow import dependencies as frontend_dependencies, paths, project as frontend
    requested = regular_path(project)
    owner, app, descriptor = layout(requested, language)
    outer = owner != app
    captured = any(os.path.lexists(owner / name) for name in (dependencies.MANIFEST, dependencies.LOCK))
    if outer and any(os.path.lexists(app / name) for name in (dependencies.MANIFEST, dependencies.LOCK)):
        raise DependencyError('dependency-frontend-ambiguous-application-lock')
    files = snapshot(app, exclude=exclude_when_captured if captured else ())
    if outer and captured:
        selected, _identity = frontend.load(owner)
        # This read-only verification includes native locks and original and
        # transformed object bytes. The controller still owns recipe approval.
        frontend_dependencies.verify(owner, selected)
        binding, _names = frontend_dependencies.selected(owner, language)
        if not binding:
            raise DependencyError('dependency-frontend-reviewed-lock-required')
        prefix = app.relative_to(owner).as_posix() + '/'
        manifest_bytes = read_bytes(owner / dependencies.MANIFEST, MAX_FILE)
        manifest = dependencies.validate_manifest(decode_json(manifest_bytes), language)
        mappings, mapped = [], set()
        for name in manifest['nativeLocks']:
            build_path = name[len(prefix):] if name.startswith(prefix) else name
            paths.relative(build_path)
            if (paths.excluded(build_path) or build_path.split('/')[0] in
                    {'dependency-inputs', 'dependencies', 'application-vendor'}
                    or build_path in {DESCRIPTOR, MAPPING, dependencies.MANIFEST, dependencies.LOCK}):
                raise DependencyError('dependency-frontend-native-input-reserved')
            alias = paths.alias(build_path)
            if alias in mapped:
                raise DependencyError('dependency-frontend-native-input-alias')
            mapped.add(alias)
            raw = read_bytes(owner / name, MAX_FILE)
            _insert(files, build_path, raw)
            mappings.append({'originalPath': name, 'buildPath': build_path,
                             'digest': digest(raw), 'size': len(raw)})
        _insert(files, DESCRIPTOR, descriptor)
        for name in (dependencies.MANIFEST, dependencies.LOCK):
            _insert(files, name, read_bytes(owner / name, MAX_FILE))
        if MAPPING in files:
            raise DependencyError('dependency-frontend-source-input-collision')
        _insert(files, MAPPING, canonical({'formatVersion': 1, 'language': language,
            'applicationPath': prefix[:-1], 'descriptorDigest': digest(descriptor),
            'dependencyInputs': binding, 'nativeInputs': mappings,
            'sdkLockDigest': digest(read_bytes(app / 'sdk-lock.json', MAX_FILE))}) + b'\n')
    if len(files) > MAX_FILES or sum(map(len, files.values())) > MAX_SOURCE:
        raise DependencyError('dependency-frontend-source-input-limit')
    return SourceInputs(requested, app, owner, language, dict(sorted(files.items())),
                        descriptor, exclude_when_captured)


def read_native(closure, name: str, maximum: int = 64 * 1024 * 1024) -> bytes:
    """Read the exact selected native input, preserving its original lock identity."""
    if not hasattr(closure, 'work') or not os.path.lexists(closure.work / MAPPING):
        return read_bytes(closure.project / name, maximum)
    mapping = decode_json(read_bytes(closure.work / MAPPING, MAX_FILE))
    fields = {'formatVersion', 'language', 'applicationPath', 'descriptorDigest',
              'dependencyInputs', 'nativeInputs', 'sdkLockDigest'}
    if (not isinstance(mapping, dict) or set(mapping) != fields
            or type(mapping['formatVersion']) is not int or mapping['formatVersion'] != 1
            or mapping['language'] != closure.lock['language']
            or not isinstance(mapping['nativeInputs'], list)
            or len(mapping['nativeInputs']) != len(closure.lock['nativeLocks'])
            or any(not isinstance(row, dict) or set(row) != {'originalPath', 'buildPath', 'digest', 'size'}
                   for row in mapping['nativeInputs'])):
        raise DependencyError('dependency-frontend-native-mapping-invalid')
    binding = mapping['dependencyInputs']
    owner, app, descriptor = layout(closure.project, closure.lock['language'])
    if (owner != closure.project or owner == app or descriptor is None
            or mapping['applicationPath'] != app.relative_to(owner).as_posix()
            or mapping['descriptorDigest'] != digest(descriptor)
            or not isinstance(binding, dict)
            or binding.get('applicationManifest') != digest(closure.manifest)
            or binding.get('applicationLock') != digest(closure.lock_bytes)):
        raise DependencyError('dependency-frontend-native-mapping-invalid')
    rows = [row for row in mapping['nativeInputs'] if row['buildPath'] == name]
    if len(rows) != 1:
        raise DependencyError('dependency-frontend-native-input-not-selected')
    row = rows[0]
    original = [item for item in closure.lock['nativeLocks'] if item['path'] == row['originalPath']]
    raw = read_bytes(closure.work / name, maximum)
    if (len(original) != 1 or original[0]['digest'] != row['digest'] or original[0]['size'] != row['size']
            or digest(raw) != row['digest'] or len(raw) != row['size']):
        raise DependencyError('dependency-frontend-native-input-mutated')
    return raw
