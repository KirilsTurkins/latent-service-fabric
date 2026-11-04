"""Validate one separately captured strict post-staging HTTP denial guest."""
from pathlib import Path

from tools.java_transaction_poststage_http import VARIANT
from tools.rust_capsule_project import checked_path, read_file, snapshot
from .current_inputs import _validate_materials
from .inputs import ComponentInput, MAX_COMPONENT_BYTES, decode, digest, require


def load(directory: Path, selected) -> ComponentInput:
    directory = checked_path(directory)
    files = {'project/' + name: raw for name, raw in snapshot(directory / 'project').items()}
    for name in ('report.json', 'source-inputs.json', 'source.tar.gz', 'recipe-inputs.json', 'compiler-inputs.json'):
        files[name] = read_file(directory / name, 32 * 1024 * 1024)
    files['component.wasm'] = read_file(directory / 'component.wasm', MAX_COMPONENT_BYTES)
    report = _validate_materials(files, selected, (VARIANT,))
    raw = files['project/java-poststage-http-denial-input.json']
    declaration = decode(raw, 8192)
    source = files['project/src/dev/latent/app/Capsule.java']
    require(set(declaration) == {'schemaVersion', 'variant', 'sourceDigest', 'worldDigest', 'companionDigest',
            'callAfter', 'expectedTypedError', 'expectedBusinessResult', 'componentCompiled',
            'signedExecutionQualified', 'postStageRollbackQualified'}
            and declaration['schemaVersion'] == 'latent.java.poststage-http-denial-input.v1'
            and declaration['variant'] == VARIANT and declaration['sourceDigest'] == digest(source)
            and declaration['worldDigest'] == digest(files['project/wit/world.wit'])
            and declaration['companionDigest'] == report['companionDigest']
            and declaration['callAfter'] == ['state-put', 'intent-stage']
            and declaration['expectedTypedError'] == 'permission-denied'
            and declaration['expectedBusinessResult'] == 'rejected'
            and all(declaration[name] is False for name in
                    ('componentCompiled', 'signedExecutionQualified', 'postStageRollbackQualified'))
            and report['poststageHttpDenialInputDigest'] == digest(raw)
            and report['postStageRollbackQualified'] is False, 'exact-poststage-http-source-declaration')
    text = source.decode('utf-8')
    call = 'Bindings.LatentHttpClient.send('
    require(text.count(call) == 1 and text.index('command.put(KEY') < text.index(call)
            and text.index('.stage(command)') < text.index(call)
            and 'Bindings.LatentHttpClientHttpError.permissionDenied().tag()' in text,
            'poststage-http-after-state-and-intent')
    return ComponentInput(VARIANT, directory, report['componentDigest'], report['companionDigest'],
                          report['sourceDigest'], selected.source_commit, report['hostAbiDigest'],
                          report['deferredHttpRequirementsDigest'])
