"""Authenticated closed CoreLib filesystem boundary, without runtime authority."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import xml.etree.ElementTree as XML

from tools.build_observation import file_identity
from tools.dotnet_guest import http_errors, task_wait
from tools.rust_capsule_project import digest, inventory, read_file, snapshot, write_json

PROFILE = 'dotnet-closed-filesystem-v1'
PATCH = 'latent.dotnet.closed-filesystem.v1'
METHODS = {
    'Microsoft.Win32.SafeHandles.SafeFileHandle Interop/Sys::Open(System.String,Interop/Sys/OpenFlags,System.Int32)':
        '45c08142a966e0bf75b1199633662f29f40bb13b5e6c731685c18c18d673e947',
    'System.IntPtr Interop/Sys::MksTemps(System.Byte*,System.Int32)':
        '706bc70525fa1dc2baec392c7ddb1febd377a584567dd6565fa9f65b87a31ccc',
}


def validate_receipt(value: dict, base_digest: str, joined: bool) -> None:
    fixed = {'patch': PATCH, 'originalDigest': task_wait.SOURCE, 'baseDigest': base_digest,
        'cecilDigest': http_errors.CECIL_DIGEST, 'originalMethodBodies': METHODS,
        'modifiedOriginalMethods': 2, 'unchangedBaseMethods': 44753 if joined else 44744,
        'otherBaseBodiesUnchanged': True, 'publicWrappersUnchanged': True,
        'newHostImports': 0, 'filesystemAuthority': False}
    if (type(value) is not dict or set(value) != set(fixed) | {'outputDigest'}
            or any(type(value.get(key)) is not type(expected) or value[key] != expected for key, expected in fixed.items())
            or type(value.get('outputDigest')) is not str):
        raise ValueError('closed-filesystem-rewrite-receipt')


@dataclass
class Port:
    source: Path
    original: Path
    base: Path
    assembly: Path
    retained: Path
    targets: Path
    references: Path
    base_identity: dict
    identity: dict
    source_identity: bytes
    targets_identity: bytes
    evidence: dict
    task_wait_port: task_wait.Port | None

    def recheck(self) -> None:
        task_wait.original(self.original)
        if self.task_wait_port is not None:
            if type(self.task_wait_port) is not task_wait.Port or self.base != self.task_wait_port.assembly:
                raise ValueError('closed-filesystem-task-wait-base')
            self.task_wait_port.recheck()
        elif self.base != self.original:
            raise ValueError('closed-filesystem-original-base')
        if file_identity(self.base, 'closed-filesystem-base-corelib', task_wait.MAX_ASSEMBLY) != self.base_identity:
            raise ValueError('closed-filesystem-base-changed')
        if (inventory(snapshot(self.source)) != self.source_identity
                or read_file(self.targets, http_errors.MAX_RECEIPT) != self.targets_identity):
            raise ValueError('closed-filesystem-source-or-target-changed')
        if any(file_identity(path, 'closed-filesystem-derived-corelib', task_wait.MAX_ASSEMBLY) != self.identity
               for path in (self.assembly, self.retained)):
            raise ValueError('closed-filesystem-derived-corelib-changed')

    def final_for(self, intermediate: task_wait.Port) -> Path:
        if self.task_wait_port is not intermediate:
            raise ValueError('closed-filesystem-foreign-task-wait-chain')
        self.recheck()
        return self.assembly

    def finish(self, project: Path, evidence: Path) -> dict:
        self.recheck()
        references = read_file(self.references, http_errors.MAX_RECEIPT).decode('utf-8-sig').splitlines()
        if (not 1 <= len(references) <= 512 or references.count(str(self.assembly)) != 1
                or any(Path(path).name == 'System.Private.CoreLib.dll' and path != str(self.assembly) for path in references)):
            raise ValueError('closed-filesystem-reference-binding')
        responses = list((project / 'obj').rglob('*.rsp'))
        if len(responses) > 64:
            raise ValueError('closed-filesystem-response-file-count')
        matched, total = [], 0
        for path in responses:
            body = read_file(path, http_errors.MAX_RSP)
            total += len(body)
            if total > 4 * http_errors.MAX_RSP:
                raise ValueError('closed-filesystem-response-file-bytes')
            found = [line[3:] for line in body.decode('utf-8-sig').splitlines()
                if line.startswith('-r:') and Path(line[3:].strip('"')).name == 'System.Private.CoreLib.dll']
            if found:
                if found != [str(self.assembly)]:
                    raise ValueError('closed-filesystem-native-aot-reference-drift')
                matched.append({'digest': digest(body), 'size': len(body)})
        if len(matched) != 1:
            raise ValueError('closed-filesystem-native-aot-reference-not-observed')
        result = {**self.evidence, 'nativeAotReferenceBinding': {
            'referenceListDigest': digest(read_file(self.references, http_errors.MAX_RECEIPT)),
            'responseFiles': matched, 'selectedCoreLibDigest': self.identity['digest']}}
        write_json(evidence / 'closed-filesystem-port.json', result)
        return result


def prepare(sdk: Path, tools: Path, packages: Path, dotnet: Path, project: Path, output: Path,
            evidence: Path, run, *, task_wait_port=None, protect_inputs=None) -> Port:
    """Every maintained profile is closed; no CLOCK/HTTP/ACTIVATION selection is required."""
    original = task_wait.source_path(packages)
    original_identity = task_wait.original(original)
    if task_wait_port is not None:
        if type(task_wait_port) is not task_wait.Port or task_wait_port.original != original:
            raise ValueError('closed-filesystem-authenticated-task-wait-required')
        task_wait_port.recheck()
    tool = http_errors.verify_installed(sdk, tools)
    base = original if task_wait_port is None else task_wait_port.assembly
    base_identity = file_identity(base, 'closed-filesystem-base-corelib', task_wait.MAX_ASSEMBLY)
    captured = inventory(snapshot(sdk / 'tools/http-errors'))
    if task_wait_port is not None and captured != task_wait_port.source_identity:
        raise ValueError('closed-filesystem-task-wait-source-drift')
    owned = output / 'closed-filesystem-port'
    owned.mkdir(mode=0o700)
    assembly, targets, receipt = owned / 'System.Private.CoreLib.dll', owned / 'ClosedFilesystem.targets', owned / 'rewrite.json'
    target = read_file(sdk / 'tools/http-errors/ClosedFilesystem.targets', http_errors.MAX_RECEIPT)
    targets.write_bytes(target)
    run('closed-filesystem-rewrite', dotnet, tools / 'http-errors/HttpErrors.dll', '--closed-filesystem',
        original, base, assembly, receipt)
    result = json.loads(read_file(receipt, http_errors.MAX_RECEIPT))
    validate_receipt(result, base_identity['digest'], task_wait_port is not None)
    identity = file_identity(assembly, 'closed-filesystem-derived-corelib', task_wait.MAX_ASSEMBLY)
    if identity['digest'] != result['outputDigest']:
        raise ValueError('closed-filesystem-rewrite-output-drift')
    retained = evidence / 'derived-closed-filesystem-System.Private.CoreLib.dll'
    with retained.open('xb') as stream:
        stream.write(read_file(assembly, task_wait.MAX_ASSEMBLY))
    if protect_inputs is not None:
        protect_inputs(assembly, targets)
    references = owned / 'native-aot-references.txt'
    document = XML.fromstring(read_file(project / 'Capsule.csproj', http_errors.MAX_RECEIPT))
    properties = XML.SubElement(document, 'PropertyGroup')
    for name, path in (('LsfClosedFilesystemBase', base), ('LsfClosedFilesystemAssembly', assembly),
                       ('LsfClosedFilesystemReferenceReceipt', references)):
        XML.SubElement(properties, name).text = http_errors.msbuild_literal(path)
    if task_wait_port is not None:
        XML.SubElement(properties, 'LsfClosedFilesystemDependencies').text = 'LsfBindActualTaskWait'
    XML.SubElement(document, 'Import', Project=http_errors.msbuild_literal(targets))
    (project / 'Capsule.csproj').write_bytes(XML.tostring(document, encoding='utf-8', xml_declaration=True))
    record = {**result, 'profile': PROFILE, 'frameworkInput': original_identity, 'base': base_identity,
        'derived': identity, 'tool': tool, 'sourceCaptureDigest': digest(captured), 'targetsDigest': digest(target),
        'taskWaitIntermediate': None if task_wait_port is None else task_wait_port.identity,
        'nativeAotReferenceBinding': None, 'requiredDeclarations': [], 'guestExecutionQualified': False}
    port = Port(sdk / 'tools/http-errors', original, base, assembly, retained, targets, references,
        base_identity, identity, captured, target, record, task_wait_port)
    port.recheck()
    write_json(evidence / 'closed-filesystem-port-preparation.json', record)
    return port
