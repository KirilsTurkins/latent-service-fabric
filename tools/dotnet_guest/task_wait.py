"""Exact private CoreLib derivation for joined, stackful WASI Task waits."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
import xml.etree.ElementTree as XML

from tools.build_observation import file_identity
from tools.dotnet_guest import async_exports, http_errors, runtime
from tools.rust_capsule_project import digest, inventory, read_file, snapshot, write_json

PROFILE = 'dotnet-stackful-task-wait-v1'
PATCH = 'latent.dotnet.stackful-task-wait.v1'
SOURCE = 'sha256:29e4bd3f70bfb0e0ea00fb2511e28ee9832b56caf9ddb5cd60906fe3bcaad735'
MAX_ASSEMBLY = 8 * 1024 * 1024
METHOD = 'System.Boolean System.Threading.Tasks.Task::InternalWaitCore(System.Int32,System.Threading.CancellationToken)'
BODY_IDENTITIES = {
    'originalWaitBodyDigest': 'sha256:9b5bc35a1a68b80111c7eddc9cbc0903e6062d4e5e3b8f84e8f359445dd6e875',
    'originalLoopBodyDigest': 'sha256:1631857d71d2e5ecca2e22c95a6421aaecf016d9cba018412388b2d1c6646e19',
    'originalDispatchBodyDigest': 'sha256:05e0128b899121d13842a4c76993d2becaaebe2e57ecff53f1ea750ba39ba629',
    'originalContextBodyDigest': 'sha256:865b97bff2c7df2a4ce36e8b802dc2a98f5865dbaf6119def4e85d21288afa29',
    'originalContextRestoreBodyDigest': 'sha256:d55f695b66f4e330e22b6e1d3aae2ce29c4d1ce059cf9c7a7b4afc0da9dc837a',
}


def source_path(packages: Path) -> Path:
    return packages / http_errors.PACKAGE / 'native-hidden/System.Private.CoreLib.dll'


def original(path: Path) -> dict:
    value = file_identity(path, 'task-wait-original-corelib', MAX_ASSEMBLY)
    if value['digest'] != SOURCE or value['size'] != 5694976:
        raise ValueError('task-wait-unsupported-CoreLib-preimage')
    return value


def selected(declared: list[str], bridge: dict | None) -> bool:
    if not {runtime.CLOCK, runtime.HTTP, runtime.ACTIVATION} <= set(declared) or bridge is None:
        return False
    if (bridge.get('profile') != async_exports.PROFILE or type(bridge.get('exports')) is not int
            or not 1 <= bridge['exports'] <= 64):
        raise ValueError('task-wait-authenticated-async-root-required')
    return True


def validate_receipt(value: dict) -> None:
    fixed = {'patch': PATCH, 'sourceDigest': SOURCE, 'cecilDigest': http_errors.CECIL_DIGEST,
        'method': METHOD, **BODY_IDENTITIES, 'maximumNestedWaits': 32,
        'finiteAndCancellableWaits': 'original-unsupported', 'completion': 'actual-task-only',
        'exceptionPropagation': 'original-TaskAwaiter', 'nestedTaskIdentity': 'save-restore-finally',
        'defaultClientComponentQualified': False, 'completeOriginalWaitRemainderPreserved': True,
        'callerContexts': 'original-RunInternal-Default', 'contextNotifications': 'original-runtime',
        'generatedHelperCount': 9, 'contextCallback': 'same-CoreLib-ContextCallback(object)',
        'timerDriver': 'TimerQueue.SetNextTimer-only', 'timerDriverIdle': 'Timer.ActiveCount==0',
        'timerDriverCancellation': 'original-CancellationTokenSource-CancelAndDispose',
        'timerDriverIdentity': 'original-task-reference-and-epoch',
        'timerDriverCallbacks': 'original-queued-user-callbacks-preserved',
        'timerDriverScheduledToFire': 'untouched', 'timerDriverCacheCleanup': False,
        'timerDriverModifiedOriginalMethods': 3,
        'timerDriverRegistrationContext': 'no-new-capture-original-flow-restored',
        'zeroCacheLifetime': 'CheckPollables-original-Poll-call-only', 'zeroCacheDetach': 'before-original-Poll',
        'zeroCacheDispose': 'original-owned-Pollable-finally', 'zeroCacheForeignHolders': 'untouched',
        'zeroCacheModifiedOriginalMethods': 1}
    bodies = value.get('timerDriverOriginalBodies')
    cache_bodies = value.get('zeroCacheOriginalBodies')
    body_names = {'System.Void System.Threading.TimerQueue::SetNextTimer(System.Int64,System.Int64)',
        'System.Void System.Threading.TimerQueue::TimerHandler(System.Object)',
        'System.Void System.Threading.TimerQueue::DeleteTimer(System.Threading.TimerQueueTimer)'}
    if (set(value) != set(fixed) | {'outputDigest', 'unchangedOriginalMethods', 'timerDriverOriginalBodies', 'zeroCacheOriginalBodies'}
            or any(type(value.get(key)) is not type(expected) or value[key] != expected for key, expected in fixed.items())
            or type(bodies) is not dict or set(bodies) != body_names
            or any(type(item) is not str or re.fullmatch('[0-9a-f]{64}', item) is None for item in bodies.values())
            or type(cache_bodies) is not dict or set(cache_bodies) != {
                'System.Void System.Threading.WasiEventLoop::CheckPollables(System.Object)'}
            or any(type(item) is not str or re.fullmatch('[0-9a-f]{64}', item) is None for item in cache_bodies.values())
            or type(value['unchangedOriginalMethods']) is not int
            or not 10000 <= value['unchangedOriginalMethods'] <= 65536):
        raise ValueError('task-wait-rewrite-receipt')


@dataclass
class Port:
    source: Path
    original: Path
    assembly: Path
    retained: Path
    targets: Path
    references: Path
    identity: dict
    source_identity: bytes
    targets_identity: bytes
    evidence: dict

    def recheck(self) -> None:
        original(self.original)
        if inventory(snapshot(self.source)) != self.source_identity or read_file(self.targets, http_errors.MAX_RECEIPT) != self.targets_identity:
            raise ValueError('task-wait-captured-source-or-target-changed')
        if any(file_identity(path, 'task-wait-derived-corelib', MAX_ASSEMBLY) != self.identity for path in (self.assembly, self.retained)):
            raise ValueError('task-wait-derived-CoreLib-changed')

    def finish(self, project: Path, evidence: Path) -> dict:
        self.recheck()
        references = read_file(self.references, http_errors.MAX_RECEIPT).decode('utf-8-sig').splitlines()
        if (not 1 <= len(references) <= 512 or references.count(str(self.assembly)) != 1
                or any(Path(path).name == 'System.Private.CoreLib.dll' and path != str(self.assembly) for path in references)):
            raise ValueError('task-wait-reference-binding')
        responses = list((project / 'obj').rglob('*.rsp'))
        if len(responses) > 64:
            raise ValueError('task-wait-response-file-count')
        matched, total = [], 0
        for path in responses:
            body = read_file(path, http_errors.MAX_RSP)
            total += len(body)
            if total > 4 * http_errors.MAX_RSP:
                raise ValueError('task-wait-response-file-bytes')
            found = [line[3:] for line in body.decode('utf-8-sig').splitlines()
                if line.startswith('-r:') and Path(line[3:].strip('"')).name == 'System.Private.CoreLib.dll']
            if found:
                if found != [str(self.assembly)]:
                    raise ValueError('task-wait-native-aot-reference-drift')
                matched.append({'digest': digest(body), 'size': len(body)})
        if len(matched) != 1:
            raise ValueError('task-wait-native-aot-reference-not-observed')
        result = {**self.evidence, 'nativeAotReferenceBinding': {
            'referenceListDigest': digest(read_file(self.references, http_errors.MAX_RECEIPT)), 'responseFiles': matched}}
        write_json(evidence / 'task-wait-port.json', result)
        return result


def prepare(sdk: Path, tools: Path, packages: Path, dotnet: Path, declared: list[str], bridge: dict | None,
            project: Path, output: Path, evidence: Path, run, *, protect_inputs=None) -> Port | None:
    if not selected(declared, bridge):
        return None
    tool = http_errors.verify_installed(sdk, tools)
    source = source_path(packages)
    source_identity = original(source)
    owned = output / 'task-wait-port'
    owned.mkdir(mode=0o700)
    assembly, targets, receipt = owned / 'System.Private.CoreLib.dll', owned / 'TaskWait.targets', owned / 'rewrite.json'
    captured = inventory(snapshot(sdk / 'tools/http-errors'))
    target = read_file(sdk / 'tools/http-errors/TaskWait.targets', http_errors.MAX_RECEIPT)
    targets.write_bytes(target)
    run('task-wait-rewrite', dotnet, tools / 'http-errors/HttpErrors.dll', '--task-wait', source, assembly, receipt)
    result = json.loads(read_file(receipt, http_errors.MAX_RECEIPT))
    validate_receipt(result)
    identity = file_identity(assembly, 'task-wait-derived-corelib', MAX_ASSEMBLY)
    if identity['digest'] != result['outputDigest']:
        raise ValueError('task-wait-rewrite-output-drift')
    retained = evidence / 'derived-task-wait-System.Private.CoreLib.dll'
    with retained.open('xb') as stream:
        stream.write(read_file(assembly, MAX_ASSEMBLY))
    if protect_inputs is not None:
        protect_inputs(assembly, targets)
    references = owned / 'native-aot-references.txt'
    document = XML.fromstring(read_file(project / 'Capsule.csproj', http_errors.MAX_RECEIPT))
    properties = XML.SubElement(document, 'PropertyGroup')
    for name, path in (('LsfTaskWaitOriginal', source), ('LsfTaskWaitAssembly', assembly), ('LsfTaskWaitReferenceReceipt', references)):
        XML.SubElement(properties, name).text = http_errors.msbuild_literal(path)
    XML.SubElement(document, 'Import', Project=http_errors.msbuild_literal(targets))
    (project / 'Capsule.csproj').write_bytes(XML.tostring(document, encoding='utf-8', xml_declaration=True))
    record = {**result, 'profile': PROFILE, 'frameworkInput': source_identity, 'tool': tool, 'derived': identity,
        'sourceCaptureDigest': digest(captured), 'targetsDigest': digest(target), 'nativeAotReferenceBinding': None,
        'selection': {'requiredDeclarations': sorted((runtime.CLOCK, runtime.HTTP, runtime.ACTIVATION)), 'asyncExportBridge': bridge}}
    write_json(evidence / 'task-wait-port-preparation.json', record)
    return Port(sdk / 'tools/http-errors', source, assembly, retained, targets, references, identity, captured, target, record)
