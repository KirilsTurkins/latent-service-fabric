"""Explicitly approved, contained Java source generation before ordinary builds."""
from __future__ import annotations

import math
import os
from pathlib import Path
import re
import secrets

from tools import application_dependency_tools as generators
from tools import guest_dependency_inputs, java_dependency_authoring as authoring
from tools.application_dependency_store import DependencyError, SHA, directory_files, read_bytes, regular_path
from tools.build_snapshot import canonical, digest
from tools.dev_workflow import paths
from tools.rust_capsule_project import MAX_FILE, MAX_FILES, MAX_SOURCE, decode_json, inventory, snapshot

MANIFEST = 'java-generated-inputs.json'
MAX_RECEIPT = 1024 * 1024
MAX_RECORDS = 64
PLAN_FIELDS = {'formatVersion', 'language', 'sourceIdentity', 'sdkIdentity', 'destination',
               'tool', 'inputs', 'specification', 'limits'}


def sdk_identity(sdk) -> dict:
    return {'lock': digest(sdk[0]), 'vendor': digest(sdk[1]),
            'descriptor': digest(sdk[2]) if sdk[2] is not None else None}


def limits(timeout: float, maximum: int) -> dict:
    if (type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0 < timeout <= 60
            or type(maximum) is not int or not 0 < maximum <= MAX_RECEIPT):
        raise DependencyError('java-generator-finite-limits-required')
    return {'timeoutSeconds': timeout, 'maximumOutputBytes': maximum}


def destination_path(app: Path, name: str) -> Path:
    paths.relative(name)
    if not name.startswith('src/') or name.count('/') != 1:
        raise DependencyError('java-generator-new-source-directory-required')
    target = regular_path(app / name)
    if os.path.lexists(target):
        raise DependencyError('java-generator-destination-already-exists')
    if any(paths.alias(path.name) == paths.alias(target.name) for path in (app / 'src').iterdir()):
        raise DependencyError('java-generator-source-name-collision')
    return target


def source_identity(owner: Path) -> str:
    # Include the outer reviewed closure and descriptor in nested frontend
    # projects. Their selection cannot change under a previous tool approval.
    observed = guest_dependency_inputs.capture_source(owner, 'java')
    return digest(inventory(observed.files))


def request(project: Path, candidate: Path, *, tool: Path, arguments: list[str], inputs: Path,
            destination: str, tool_version: str, timeout_seconds: float = 60,
            maximum_output_bytes: int = MAX_RECEIPT, environment: dict[str, str] | None = None) -> dict:
    candidate = authoring.candidate_location(project, candidate)
    if os.path.lexists(candidate):
        raise DependencyError('java-generator-use-fresh-request')
    with authoring.transaction(project) as (owner, app, _private, sdk):
        destination_path(app, destination)
        validate_generated_inputs(snapshot(app))
        tool = regular_path(tool).resolve(strict=True)
        inputs = regular_path(inputs).resolve(strict=True)
        selected = generators.specification(tool, arguments, inputs, tool_version=tool_version,
                                            environment=environment)
        value = {'formatVersion': 1, 'language': 'java', 'sourceIdentity': source_identity(owner),
                 'sdkIdentity': sdk_identity(sdk), 'destination': destination,
                 'tool': str(tool), 'inputs': str(inputs), 'specification': selected,
                 'limits': limits(timeout_seconds, maximum_output_bytes)}
        raw = canonical(value) + b'\n'
        if len(raw) > MAX_RECEIPT:
            raise DependencyError('java-generator-request-limit')
        paths.write_new(candidate, raw)
        return {'formatVersion': 1, 'stage': 'java-generator-approval-request',
                'requestDigest': digest(raw), 'executionIdentity': digest(canonical(selected)),
                'destination': destination, 'compilerExecution': False,
                'generatorExecution': False, 'approvalRequired': True}


def validate_plan(value: dict) -> None:
    if (not isinstance(value, dict) or set(value) != PLAN_FIELDS
            or type(value['formatVersion']) is not int or value['formatVersion'] != 1
            or value['language'] != 'java' or not isinstance(value['sourceIdentity'], str)
            or not SHA.fullmatch(value['sourceIdentity'])
            or not isinstance(value['sdkIdentity'], dict)
            or set(value['sdkIdentity']) != {'lock', 'vendor', 'descriptor'}
            or any(not isinstance(value[field], str) for field in ('destination', 'tool', 'inputs'))
            or not isinstance(value['specification'], dict)
            or not isinstance(value['limits'], dict)
            or set(value['limits']) != {'timeoutSeconds', 'maximumOutputBytes'}):
        raise DependencyError('java-generator-request-invalid')
    limits(value['limits']['timeoutSeconds'], value['limits']['maximumOutputBytes'])


def run(project: Path, candidate: Path, expected: str) -> dict:
    candidate = authoring.candidate_location(project, candidate)
    raw = read_bytes(candidate, MAX_RECEIPT)
    if not isinstance(expected, str) or not SHA.fullmatch(expected) or digest(raw) != expected:
        raise DependencyError('java-generator-request-approval-mismatch')
    selected = decode_json(raw)
    validate_plan(selected)
    with authoring.transaction(project) as (owner, app, private, sdk):
        target = destination_path(app, selected['destination'])
        before = snapshot(app)
        validate_generated_inputs(before)
        if source_identity(owner) != selected['sourceIdentity'] or sdk_identity(sdk) != selected['sdkIdentity']:
            raise DependencyError('java-generator-source-or-sdk-drift')
        tool, inputs = regular_path(Path(selected['tool'])), regular_path(Path(selected['inputs']))
        spec = selected['specification']
        if generators.specification(tool, spec['arguments'], inputs, tool_version=spec['toolVersion'],
                                    environment=spec['environment']) != spec:
            raise DependencyError('java-generator-tool-or-input-drift')
        stage = private / ('generator-' + secrets.token_hex(16))
        stage.mkdir(mode=0o700)
        outputs, receipt = stage / 'outputs', stage / 'execution.json'
        public = {'formatVersion': 1, 'stage': 'java-generator-execution', 'requestDigest': expected,
                  'status': 'failed', 'sourceChanged': False, 'cleanup': 'unconfirmed',
                  'automaticReplay': False, 'compilerExecution': False}
        try:
            executed = generators.execute(tool, spec['arguments'], inputs, outputs, receipt,
                tool_version=spec['toolVersion'], approved_identity=digest(canonical(spec)),
                environment=spec['environment'], timeout_seconds=selected['limits']['timeoutSeconds'],
                maximum_output_bytes=selected['limits']['maximumOutputBytes'])
            produced = directory_files(outputs)
            if not produced or any(not name.endswith('.java') for name in produced):
                raise DependencyError('java-generator-outputs-must-be-java-source')
            expected_files = {selected['destination'] + '/' + name: data for name, data in produced.items()}
            if (snapshot(app) != before or read_bytes(candidate) != raw
                    or source_identity(owner) != selected['sourceIdentity']
                    or sdk_identity(authoring.seal(owner)[2]) != selected['sdkIdentity']):
                raise DependencyError('java-generator-project-mutated-during-execution')
            previous = decode_json(before[MANIFEST]) if MANIFEST in before else {'formatVersion': 1, 'language': 'java', 'records': []}
            if len(previous['records']) >= MAX_RECORDS:
                raise DependencyError('java-generator-record-count-limit')
            output_rows = [{'path': name, 'digest': digest(data), 'size': len(data)} for name, data in sorted(expected_files.items())]
            entry = {'requestDigest': expected, 'executionIdentity': executed['identity'],
                     'toolDigest': spec['executableDigest'], 'toolVersion': spec['toolVersion'],
                     'inputsDigest': spec['inputsDigest'], 'specificationDigest': digest(canonical(spec)),
                     'executionReceiptDigest': digest(read_bytes(receipt)), 'outputs': output_rows,
                     'outputsIdentity': digest(canonical(output_rows)), 'cleanup': executed['cleanup']}
            manifest = canonical({**previous, 'records': [*previous['records'], entry]}) + b'\n'
            if len(manifest) > MAX_RECEIPT:
                raise DependencyError('java-generator-record-byte-limit')
            adopted = {**before, **expected_files, MANIFEST: manifest}
            if (len(adopted) > MAX_FILES or sum(map(len, adopted.values())) > MAX_SOURCE
                    or any(len(data) > MAX_FILE for data in expected_files.values())):
                raise DependencyError('java-generator-project-source-limit')
            if any(any(not re.fullmatch(r'[A-Za-z0-9._-]+', part) for part in name.split('/'))
                   for name in expected_files):
                raise DependencyError('java-generator-nonportable-source-path')
            entry_names = set()
            pending_directories = [app]
            while pending_directories:
                parent = pending_directories.pop()
                for path in parent.iterdir():
                    if parent == app and path.name in {'.git', 'target', 'dependency-inputs'}:
                        continue
                    path = regular_path(path)
                    entry_names.add(path.relative_to(app).as_posix())
                    if len(entry_names) > MAX_FILES:
                        raise DependencyError('java-generator-project-source-limit')
                    if path.is_dir():
                        pending_directories.append(path)
            for name in expected_files:
                pieces = name.split('/')
                entry_names.update('/'.join(pieces[:count]) for count in range(1, len(pieces) + 1))
            entry_names.add(MANIFEST)
            if len(entry_names) > MAX_FILES:
                raise DependencyError('java-generator-project-source-limit')
            from tools.java_capsule_project import validate
            # Normal nested builds project the outer reviewed manifest/lock
            # into the app snapshot. Validate that same view, including local
            # JAR approval, rather than treating captured binaries as ambient.
            projected = {**guest_dependency_inputs.capture_source(owner, 'java').files,
                         **expected_files, MANIFEST: manifest}
            if len(projected) > MAX_FILES or sum(map(len, projected.values())) > MAX_SOURCE:
                raise DependencyError('java-generator-project-source-limit')
            validate(projected)
            # Adopt only a fresh source subtree. A failed process never replaces
            # source/SDK inputs, and its private execution receipt is retained.
            os.rename(outputs, target)
            pending = stage / 'generated-inputs.json'
            try:
                paths.write_new(pending, manifest)
                os.replace(pending, app / MANIFEST)
            except BaseException:
                os.rename(target, outputs)
                raise
            public['sourceChanged'] = True
            if snapshot(app) != adopted:
                raise DependencyError('java-generator-adopted-source-drift')
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
    if len(files[MANIFEST]) > MAX_RECEIPT:
        raise DependencyError('java-generator-record-byte-limit')
    value = decode_json(files[MANIFEST])
    if (not isinstance(value, dict) or set(value) != {'formatVersion', 'language', 'records'}
            or type(value['formatVersion']) is not int or value['formatVersion'] != 1
            or value['language'] != 'java' or not isinstance(value['records'], list)
            or not 0 < len(value['records']) <= MAX_RECORDS):
        raise DependencyError('java-generated-inputs-format')
    seen = set()
    for row in value['records']:
        expected_fields = {'requestDigest', 'executionIdentity', 'toolDigest', 'toolVersion', 'inputsDigest',
                           'specificationDigest', 'executionReceiptDigest', 'outputs', 'outputsIdentity', 'cleanup'}
        if (not isinstance(row, dict) or set(row) != expected_fields or row['cleanup'] != 'reaped'
                or any(not isinstance(row[field], str) or not SHA.fullmatch(row[field]) for field in expected_fields - {'toolVersion', 'outputs', 'cleanup'})
                or not isinstance(row['toolVersion'], str) or not 0 < len(row['toolVersion']) <= 80
                or not isinstance(row['outputs'], list) or not 0 < len(row['outputs']) <= 8192
                or digest(canonical(row['outputs'])) != row['outputsIdentity']):
            raise DependencyError('java-generated-inputs-record')
        for output in row['outputs']:
            if not isinstance(output, dict) or set(output) != {'path', 'digest', 'size'}:
                raise DependencyError('java-generated-inputs-output')
            name = paths.relative(output['path'])
            if (not name.startswith('src/') or not name.endswith('.java') or paths.alias(name) in seen
                    or name not in files or type(output['size']) is not int or output['size'] != len(files[name])
                    or digest(files[name]) != output['digest']):
                raise DependencyError('java-generated-inputs-drift')
            seen.add(paths.alias(name))
    return value
