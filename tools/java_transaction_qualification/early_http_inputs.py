"""Separate early-HTTP compiler custody; no addition to the original six captures."""
from pathlib import Path
import re

from tools.java_transaction_http_denial import VARIANT
from tools.rust_capsule_project import checked_path, read_file, snapshot
from .current_inputs import CurrentSelection, _validate_materials
from .inputs import ComponentInput, MAX_COMPONENT_BYTES, decode, digest, require


def load(directory: Path, selected: CurrentSelection) -> ComponentInput:
    directory = checked_path(directory)
    files = {'project/' + name: raw for name, raw in snapshot(directory / 'project').items()}
    for name in ('report.json', 'source-inputs.json', 'source.tar.gz', 'recipe-inputs.json', 'compiler-inputs.json'):
        files[name] = read_file(directory / name, 32 * 1024 * 1024)
    files['component.wasm'] = read_file(directory / 'component.wasm', MAX_COMPONENT_BYTES)
    return validate_files(directory, files, selected)


def validate_files(directory, files, selected):
    report = _validate_materials(files, selected, (VARIANT,))
    declaration_raw = files['project/java-early-http-denial-input.json']
    declaration = decode(declaration_raw, 8192)
    source = files['project/src/dev/latent/app/Capsule.java']
    require(set(declaration) == {'schemaVersion', 'variant', 'originalPostStageSourceDigest', 'sourceDigest',
                'worldDigest', 'companionDigest', 'callBefore', 'expectedTypedError', 'expectedBusinessResult',
                'componentCompiled', 'signedExecutionQualified', 'immediateHttpDenialQualified', 'postStageRollbackQualified'}
            and declaration['schemaVersion'] == 'latent.java.early-http-denial-input.v1'
            and declaration['variant'] == VARIANT
            and isinstance(declaration['originalPostStageSourceDigest'], str)
            and re.fullmatch(r'sha256:[0-9a-f]{64}', declaration['originalPostStageSourceDigest'])
            and declaration['originalPostStageSourceDigest'] != declaration['sourceDigest']
            and declaration['sourceDigest'] == digest(source)
            and declaration['worldDigest'] == digest(files['project/wit/world.wit'])
            and declaration['companionDigest'] == report['companionDigest']
            and declaration['callBefore'] == ['state-get', 'state-put', 'intent-stage']
            and declaration['expectedTypedError'] == 'permission-denied'
            and declaration['expectedBusinessResult'] == 'rejected'
            and all(declaration[name] is False for name in ('componentCompiled', 'signedExecutionQualified',
                    'immediateHttpDenialQualified', 'postStageRollbackQualified'))
            and report['earlyHttpDenialInputDigest'] == digest(declaration_raw)
            and report['immediateHttpDenialQualified'] is False and report['postStageRollbackQualified'] is False,
            'exact-early-http-source-declaration')
    text = source.decode('utf-8')
    acquire = 'try (var command = State.acquireCommand().value()) {'
    call = 'Bindings.LatentHttpClient.send('
    require(text.count(acquire) == text.count(call) == 1
            and text.index(acquire) < text.index(call)
            and all(text.index(call) < text.index(later) for later in ('command.get(KEY)', 'command.put(KEY', '.stage(command)'))
            and 'Bindings.LatentHttpClientHttpError.permissionDenied().tag()' in text
            and 'project/java-current-http-profile.json' not in files
            and 'project/deferred-http-requirements.json' not in files,
            'reachable-early-http-denial-without-effect-authority')
    project = decode(files['project/capsule-project.json'])
    require(project.get('service') == 'examples/transaction-java-forbidden-http-before-stage'
            and project.get('limits') == {'cpuFuel': 1_000_000_000, 'memoryBytes': 67_108_864,
                'wallTimeLimitMillis': 120000, 'childCalls': 0, 'outboundRequests': 0,
                'stateReadBytes': 4194304, 'stateWriteBytes': 2097152, 'blobReadBytes': 0,
                'blobWriteBytes': 0, 'logBytes': 0, 'effectCount': 32},
            'original-early-http-service-and-limits')
    return ComponentInput(VARIANT, directory, report['componentDigest'], report['companionDigest'],
                          report['sourceDigest'], selected.source_commit, report['hostAbiDigest'], None)
