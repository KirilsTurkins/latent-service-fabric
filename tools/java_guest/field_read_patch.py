"""Exact TeaVM 0.15 field-cache repair at exceptional control-flow entries."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from tools.rust_capsule_project import read_file

UPSTREAM_SHA256 = '4c63bc1a7f22a7302cc2ae7fdf8f3b3cc7bd784ca5974613b7d43d21d77a780f'
ROOT = 'org/teavm/model/optimization/'
CLASSES = frozenset(ROOT + 'RepeatedFieldReadElimination' + suffix + '.class' for suffix in (
    '', '$Traversal', '$State', '$InstructionAnalyzer', '$FieldAndInstance'))
CONTROL = ROOT + 'FieldReadCheck.class'
REPLACEMENTS = (
    ('        classSource = context.getClassSource();',
     '        changed = false;\n        invalidFields.clear();\n        classSource = context.getClassSource();'),
    ('                exceptionHandlers[tryCatchBlock.getHandler().getIndex()] = true;',
     '                exceptionHandlers[tryCatchBlock.getHandler().getIndex()] = true;\n'
     '                everythingInvalid[tryCatchBlock.getHandler().getIndex()] = true;'),
)


def corrected_source(raw: bytes) -> bytes:
    if hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('unreviewed-teavm-field-read-source')
    source = raw.decode('utf-8')
    for before, after in REPLACEMENTS:
        if source.count(before) != 1:
            raise ValueError('unreviewed-teavm-field-read-preimage')
        source = source.replace(before, after)
    # The pinned published JAR relocates the upstream HPPC dependency.
    if source.count('import com.carrotsearch.hppc.') != 8:
        raise ValueError('unreviewed-teavm-field-read-relocation')
    return source.replace('import com.carrotsearch.hppc.', 'import org.teavm.hppc.').encode('utf-8')


def prepare(sdk: Path, folder: Path) -> tuple[Path, Path]:
    source, control = folder / 'RepeatedFieldReadElimination.java', folder / 'FieldReadCheck.java'
    source.write_bytes(corrected_source(read_file(sdk / source.name)))
    control.write_bytes(read_file(sdk / control.name))
    return source, control


def check(compiler, original: Path, replacement: Path, classes: Path, jars: list[Path]) -> dict:
    for mode, selected in (('original', original), ('corrected', replacement)):
        classpath = os.pathsep.join(map(str, [selected, classes, *[p for p in jars if p != original]]))
        observed = compiler.run('java-field-read-' + mode + '-control', 'java', '-Xmx256m', '-cp',
            classpath, 'org.teavm.model.optimization.FieldReadCheck', mode)
        record = json.loads(observed)
        if type(record) is not dict or type(record.get('passed')) is not bool or record != {'schemaVersion': 'latent.java.field-read-exception-control.v1',
                'mode': mode, 'passed': True}:
            raise ValueError('field-read-real-ir-control')
    raw = read_file(compiler.sdk / 'fibers/compiler-patch/RepeatedFieldReadElimination.java')
    return {'upstreamFieldReadSourceSha256': UPSTREAM_SHA256,
            'correctedFieldReadSourceSha256': hashlib.sha256(corrected_source(raw)).hexdigest(),
            'realOriginalExceptionalFieldCacheDefectObserved': True,
            'realCorrectedExceptionalFieldReadsPreserved': True,
            'realCorrectedFieldReadPassReusePreserved': True}
