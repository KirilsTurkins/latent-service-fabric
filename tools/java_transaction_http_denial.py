"""Separate editable early-HTTP fixture; original post-stage rollback stays intact."""
from __future__ import annotations

import json
from pathlib import Path

from tools.rust_capsule_project import digest, read_file, read_json
from tools.transaction_guest_variants import SOURCES, create as create_variant, replace_once

VARIANT = 'forbidden-http-before-stage'


def create(directory: Path) -> Path:
    project = create_variant(directory, 'java', 'forbidden-http',
                             'transaction-java-forbidden-http-before-stage')
    path = project / SOURCES['java']
    original = read_file(path)
    source = original.decode()
    start = source.index('            var forbidden = Bindings.LatentHttpClient.send(')
    end_marker = '            if (denied) return Result.err(Bindings.ExamplesTransactionalAggregateApiBusinessError.Rejected);\n'
    end = source.index(end_marker, start) + len(end_marker)
    call = source[start:end]
    selected = replace_once(source, call, '')
    selected = replace_once(selected, '        try (var command = State.acquireCommand().value()) {\n',
                            '        try (var command = State.acquireCommand().value()) {\n' + call)
    raw = selected.encode()
    path.write_bytes(raw)
    lock = read_json(project / 'sdk-lock.json')
    lock['template']['sourceDigest'] = digest(raw)
    (project / 'sdk-lock.json').write_bytes(json.dumps(lock, indent=2).encode() + b'\n')
    record = {'schemaVersion': 'latent.java.early-http-denial-input.v1', 'variant': VARIANT,
              'originalPostStageSourceDigest': digest(original), 'sourceDigest': digest(raw),
              'worldDigest': digest(read_file(project / 'wit/world.wit')),
              'companionDigest': digest(read_file(project / 'transaction-binding.json')),
              'callBefore': ['state-get', 'state-put', 'intent-stage'],
              'expectedTypedError': 'permission-denied', 'expectedBusinessResult': 'rejected',
              'componentCompiled': False, 'signedExecutionQualified': False,
              'immediateHttpDenialQualified': False, 'postStageRollbackQualified': False}
    (project / 'java-early-http-denial-input.json').write_bytes(json.dumps(record, indent=2).encode() + b'\n')
    return project
