"""Bounded generated-source evidence retained before component composition."""
from __future__ import annotations

import os
from pathlib import Path

from tools.application_dependency_store import DependencyError, directory_files, regular_path
from tools.build_snapshot import canonical, digest
from tools.dev_workflow.common import decode
from tools.rust_capsule_project import read_file, write_json

MAX_BYTES = 64 * 1024 * 1024
MAX_RECEIPT = 4 * 1024 * 1024


def files(source: Path) -> dict[str, bytes]:
    source = regular_path(source)
    selected = directory_files(source) if os.path.lexists(source) else {}
    if len(selected) > 8192 or sum(len(data) for data in selected.values()) > MAX_BYTES:
        raise DependencyError('NuGet-executable-generated-output-limit')
    return selected


def binding(approval) -> dict:
    if approval is None or digest(canonical(approval.specification)) != approval.identity:
        raise DependencyError('NuGet-executable-generated-output-approval')
    return {'approvalIdentity': approval.identity,
            'inputIdentity': approval.specification['inputIdentity'],
            'recipeDigest': approval.specification['recipeDigest'],
            'compilerInputsDigest': approval.specification['compilerInputsDigest']}


def capture(source: Path, output: Path, approval, *, compiler_command_succeeded: bool) -> dict:
    """Capture after the bounded compiler process exits, even if linking fails."""
    if type(compiler_command_succeeded) is not bool:
        raise DependencyError('NuGet-executable-generated-output-status')
    identity, selected = binding(approval), files(source)
    output = regular_path(output)
    destination = regular_path(output / 'executable-input-outputs')
    receipt = regular_path(output / 'executable-input-outputs.json')
    if os.path.lexists(destination) or os.path.lexists(receipt):
        raise DependencyError('NuGet-executable-generated-output-capture-exists')
    destination.mkdir(mode=0o700)
    for name, data in selected.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
    value = {'formatVersion': 1, **identity,
             'outputs': {name: {'digest': digest(data), 'size': len(data)} for name, data in selected.items()},
             'compilerCommandSucceeded': compiler_command_succeeded,
             'captureBoundary': 'native-aot-process-reaped-before-component-composition',
             'cleanup': 'namespace-and-owned-process-reaped', 'hermetic': False}
    encoded = canonical(value)
    if len(encoded) > MAX_RECEIPT:
        raise DependencyError('NuGet-executable-generated-output-receipt-limit')
    write_json(receipt, value)
    verify(output, approval, source=source, compiler_command_succeeded=compiler_command_succeeded)
    return value


def verify(output: Path, approval, *, source: Path | None = None,
           compiler_command_succeeded: bool = True) -> dict:
    if type(compiler_command_succeeded) is not bool:
        raise DependencyError('NuGet-executable-generated-output-status')
    retained_root = regular_path(output / 'executable-input-outputs')
    if not retained_root.is_dir():
        raise DependencyError('NuGet-executable-generated-output-missing')
    value = decode(read_file(regular_path(output / 'executable-input-outputs.json'), MAX_RECEIPT),
                   MAX_RECEIPT, maximum_items=65536)
    identity = binding(approval)
    if (not isinstance(value, dict) or set(value) != {'formatVersion', *identity,
            'outputs', 'compilerCommandSucceeded', 'captureBoundary', 'cleanup', 'hermetic'}
            or value['formatVersion'] != 1 or any(value[name] != data for name, data in identity.items())
            or value['compilerCommandSucceeded'] is not compiler_command_succeeded
            or value['captureBoundary'] != 'native-aot-process-reaped-before-component-composition'
            or value['cleanup'] != 'namespace-and-owned-process-reaped' or value['hermetic'] is not False):
        raise DependencyError('NuGet-executable-generated-output-stale-receipt')
    retained = files(retained_root)
    actual = {name: {'digest': digest(data), 'size': len(data)} for name, data in retained.items()}
    if value['outputs'] != actual or source is not None and files(source) != retained:
        raise DependencyError('NuGet-executable-generated-output-mutated')
    return value
