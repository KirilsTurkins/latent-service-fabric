"""Explicitly approve, contain and capture Go source generators before ordinary builds."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import secrets

from tools import application_dependency_tools as generators
from tools import go_dependency_authoring as authoring
from tools.application_dependency_store import DependencyError, SHA, directory_files, read_bytes, regular_path
from tools.build_snapshot import canonical, digest
from tools.dev_workflow import paths
from tools.rust_capsule_project import decode_json, inventory

MANIFEST = 'go-generated-inputs.json'
MAX_RECORDS = 64
PLAN_FIELDS = {'formatVersion', 'language', 'sourceIdentity', 'sdkIdentity', 'destination',
               'tool', 'inputs', 'specification', 'limits'}


def sdk_identity(sdk) -> dict:
    return {'lock': digest(sdk[0]), 'vendor': digest(sdk[1]),
            'frontend': digest(sdk[2]) if sdk[2] is not None else None}


def limits(timeout: float, maximum: int) -> dict:
    if (type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0 < timeout <= 60
            or type(maximum) is not int or not 0 < maximum <= 1024 * 1024):
        raise DependencyError('go-generator-finite-limits-required')
    return {'timeoutSeconds': timeout, 'maximumOutputBytes': maximum}


def destination_path(app: Path, name: str) -> Path:
    paths.relative(name)
    if not name.startswith('src/') or name.count('/') != 1:
        raise DependencyError('go-generator-new-source-directory-required')
    target = regular_path(app / name)
    if os.path.lexists(target):
        raise DependencyError('go-generator-destination-already-exists')
    if any(paths.alias(path.name) == paths.alias(target.name) for path in (app / 'src').iterdir()):
        raise DependencyError('go-generator-source-name-collision')
    return target


def request(project: Path, candidate: Path, *, tool: Path, arguments: list[str], inputs: Path,
            destination: str, tool_version: str, timeout_seconds: float = 60,
            maximum_output_bytes: int = 1024 * 1024, environment: dict[str, str] | None = None) -> dict:
    candidate = authoring.candidate_location(project, candidate)
    if os.path.lexists(candidate):
        raise DependencyError('go-generator-use-fresh-request')
    with authoring.transaction(project) as (owner, app, _private, sdk):
        destination_path(app, destination)
        tool = regular_path(tool).resolve(strict=True)
        inputs = regular_path(inputs).resolve(strict=True)
        selected = generators.specification(tool, arguments, inputs, tool_version=tool_version,
                                            environment=environment)
        value = {'formatVersion': 1, 'language': 'go',
                 'sourceIdentity': digest(inventory(authoring.source_files(app))),
                 'sdkIdentity': sdk_identity(sdk), 'destination': destination,
                 'tool': str(tool), 'inputs': str(inputs), 'specification': selected,
                 'limits': limits(timeout_seconds, maximum_output_bytes)}
        raw = canonical(value) + b'\n'
        if len(raw) > authoring.MAX_RECEIPT:
            raise DependencyError('go-generator-request-limit')
        paths.write_new(candidate, raw)
        return {'formatVersion': 1, 'stage': 'go-generator-approval-request',
                'requestDigest': digest(raw), 'executionIdentity': digest(canonical(selected)),
                'destination': destination, 'compilerExecution': False,
                'generatorExecution': False, 'approvalRequired': True}


def validate_plan(value: dict) -> None:
    if (not isinstance(value, dict) or set(value) != PLAN_FIELDS
            or type(value['formatVersion']) is not int or value['formatVersion'] != 1
            or value['language'] != 'go' or not SHA.fullmatch(value['sourceIdentity'])
            or not isinstance(value['sdkIdentity'], dict)
            or set(value['sdkIdentity']) != {'lock', 'vendor', 'frontend'}
            or not isinstance(value['specification'], dict)
            or not isinstance(value['limits'], dict)
            or set(value['limits']) != {'timeoutSeconds', 'maximumOutputBytes'}):
        raise DependencyError('go-generator-request-invalid')
    limits(value['limits']['timeoutSeconds'], value['limits']['maximumOutputBytes'])


def run(project: Path, candidate: Path, expected: str) -> dict:
    candidate = authoring.candidate_location(project, candidate)
    raw = read_bytes(candidate, authoring.MAX_RECEIPT)
    if not isinstance(expected, str) or not SHA.fullmatch(expected) or digest(raw) != expected:
        raise DependencyError('go-generator-request-approval-mismatch')
    selected = decode_json(raw)
    validate_plan(selected)
    with authoring.transaction(project) as (owner, app, private, sdk):
        target = destination_path(app, selected['destination'])
        before = authoring.source_files(app)
        if digest(inventory(before)) != selected['sourceIdentity'] or sdk_identity(sdk) != selected['sdkIdentity']:
            raise DependencyError('go-generator-source-or-sdk-drift')
        tool, inputs = regular_path(Path(selected['tool'])), regular_path(Path(selected['inputs']))
        spec = selected['specification']
        if generators.specification(tool, spec['arguments'], inputs, tool_version=spec['toolVersion'],
                                    environment=spec['environment']) != spec:
            raise DependencyError('go-generator-tool-or-input-drift')
        stage = private / ('generator-' + secrets.token_hex(16))
        stage.mkdir(mode=0o700)
        outputs, receipt = stage / 'outputs', stage / 'execution.json'
        public = {'formatVersion': 1, 'stage': 'go-generator-execution', 'requestDigest': expected,
                  'status': 'failed', 'sourceChanged': False, 'cleanup': 'unconfirmed',
                  'automaticReplay': False, 'compilerExecution': False}
        try:
            executed = generators.execute(tool, spec['arguments'], inputs, outputs, receipt,
                tool_version=spec['toolVersion'], approved_identity=digest(canonical(spec)),
                environment=spec['environment'], timeout_seconds=selected['limits']['timeoutSeconds'],
                maximum_output_bytes=selected['limits']['maximumOutputBytes'])
            produced = directory_files(outputs)
            if not produced or any(not name.endswith('.go') for name in produced):
                raise DependencyError('go-generator-outputs-must-be-go-source')
            expected_files = {selected['destination'] + '/' + name: data for name, data in produced.items()}
            if (authoring.source_files(app) != before or read_bytes(candidate) != raw
                    or sdk_identity(authoring.seal(owner)[2]) != selected['sdkIdentity']):
                raise DependencyError('go-generator-project-mutated-during-execution')
            previous = decode_json(before[MANIFEST]) if MANIFEST in before else {'formatVersion': 1, 'language': 'go', 'records': []}
            validate_generated_inputs(before)
            if len(previous['records']) >= MAX_RECORDS:
                raise DependencyError('go-generator-record-count-limit')
            output_rows = [{'path': name, 'digest': digest(data), 'size': len(data)} for name, data in sorted(expected_files.items())]
            entry = {'requestDigest': expected, 'executionIdentity': executed['identity'],
                     'toolDigest': spec['executableDigest'], 'toolVersion': spec['toolVersion'],
                     'inputsDigest': spec['inputsDigest'], 'specificationDigest': digest(canonical(spec)),
                     'executionReceiptDigest': digest(read_bytes(receipt)), 'outputs': output_rows,
                     'outputsIdentity': digest(canonical(output_rows)), 'cleanup': executed['cleanup']}
            updated = {**previous, 'records': [*previous['records'], entry]}
            manifest = canonical(updated) + b'\n'
            validate_generated_inputs({**before, **expected_files, MANIFEST: manifest})
            # Install only a new source subtree. Existing source and SDK files
            # are never replaced, and failed execution leaves private evidence.
            os.rename(outputs, target)
            pending = stage / 'generated-inputs.json'
            paths.write_new(pending, manifest)
            try:
                os.replace(pending, app / MANIFEST)
            except BaseException:
                os.rename(target, outputs)
                raise
            public['sourceChanged'] = True
            after = authoring.source_files(app)
            if after != {**before, **expected_files, MANIFEST: manifest}:
                raise DependencyError('go-generator-adopted-source-drift')
            authoring.unchanged(owner, sdk)
            public.update(status='succeeded', sourceChanged=True, cleanup=executed['cleanup'],
                          outputsIdentity=entry['outputsIdentity'], generatedInputsDigest=digest(manifest),
                          generatedFiles=len(output_rows), destination=selected['destination'])
            return public
        finally:
            if receipt.exists():
                public['executionReceiptDigest'] = digest(read_bytes(receipt))
                public['cleanup'] = decode_json(read_bytes(receipt)).get('cleanup', 'unconfirmed')
            paths.write_new(stage / 'outcome.json', canonical(public) + b'\n')


def validate_generated_inputs(files: dict[str, bytes]) -> dict | None:
    if MANIFEST not in files:
        return None
    value = decode_json(files[MANIFEST])
    if (not isinstance(value, dict) or set(value) != {'formatVersion', 'language', 'records'}
            or type(value['formatVersion']) is not int or value['formatVersion'] != 1
            or value['language'] != 'go' or not isinstance(value['records'], list)
            or not 0 < len(value['records']) <= MAX_RECORDS):
        raise DependencyError('go-generated-inputs-format')
    seen = set()
    for row in value['records']:
        expected_fields = {'requestDigest', 'executionIdentity', 'toolDigest', 'toolVersion', 'inputsDigest',
                           'specificationDigest', 'executionReceiptDigest', 'outputs', 'outputsIdentity', 'cleanup'}
        if (not isinstance(row, dict) or set(row) != expected_fields or row['cleanup'] != 'reaped'
                or any(not isinstance(row[field], str) or not SHA.fullmatch(row[field]) for field in expected_fields - {'toolVersion', 'outputs', 'cleanup'})
                or not isinstance(row['toolVersion'], str) or not row['toolVersion']
                or not isinstance(row['outputs'], list) or not 0 < len(row['outputs']) <= 8192
                or digest(canonical(row['outputs'])) != row['outputsIdentity']):
            raise DependencyError('go-generated-inputs-record')
        for output in row['outputs']:
            if not isinstance(output, dict) or set(output) != {'path', 'digest', 'size'}:
                raise DependencyError('go-generated-inputs-output')
            name = paths.relative(output['path'])
            if (not name.startswith('src/') or not name.endswith('.go') or paths.alias(name) in seen
                    or name not in files or type(output['size']) is not int or output['size'] != len(files[name])
                    or digest(files[name]) != output['digest']):
                raise DependencyError('go-generated-inputs-drift')
            seen.add(paths.alias(name))
    return value
