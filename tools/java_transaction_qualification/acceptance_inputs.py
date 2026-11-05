"""Separate compiler custody for value and strict child-call acceptance guests.

These checks establish input identity only; they do not grant authority or prove
that either component has been signed, admitted, or executed.
"""
from pathlib import Path
import json
import re

from tools.java_transaction_values import SELECTORS, UTF8_TEXT
from tools.rust_capsule_project import checked_path, read_file, snapshot
from .current_inputs import _validate_materials
from .inputs import ComponentInput, MAX_COMPONENT_BYTES, decode, digest, require

VALUES = 'put-once-values'
CHILD = 'forbidden-child'


def load(directory: Path, selected) -> ComponentInput:
    directory = checked_path(directory)
    files = {'project/' + name: raw for name, raw in snapshot(directory / 'project').items()}
    for name in ('report.json', 'source-inputs.json', 'source.tar.gz', 'recipe-inputs.json', 'compiler-inputs.json'):
        files[name] = read_file(directory / name, 32 * 1024 * 1024)
    files['component.wasm'] = read_file(directory / 'component.wasm', MAX_COMPONENT_BYTES)
    return validate_files(directory, files, selected)


def validate_files(directory, files, selected):
    report = _validate_materials(files, selected, (VALUES, CHILD))
    source = files['project/src/dev/latent/app/Capsule.java']
    text = source.decode('utf-8')
    if selected.variant == VALUES:
        raw = files['project/transaction-value-inputs.json']
        value = decode(raw, 8192)
        require(set(value) == {'schemaVersion', 'selectors', 'expectedUnsignedValues', 'utf8Text',
                'utf8PayloadDigest', 'absentOptionalRequired', 'freshInstanceRequired', 'originalSourceDigest',
                'sourceDigest', 'worldDigest', 'companionDigest', 'componentCompiled',
                'signedStateExecutionQualified', 'unsignedRoundtripQualified', 'utf8RoundtripQualified',
                'absentOptionalQualified'}
                and value['schemaVersion'] == 'latent.java.transaction-value-inputs.v1'
                and value['selectors'] == SELECTORS
                and value['expectedUnsignedValues'] == {'highBit': '9223372036854775808',
                                                         'unsignedMaximum': '18446744073709551615'}
                and value['utf8Text'] == UTF8_TEXT
                and value['utf8PayloadDigest'] == digest(json.dumps([None, UTF8_TEXT], ensure_ascii=False,
                                                         separators=(',', ':')).encode())
                and value['absentOptionalRequired'] is True and value['freshInstanceRequired'] is True
                and re.fullmatch(r'sha256:[0-9a-f]{64}', value['originalSourceDigest'] or '')
                and value['sourceDigest'] == digest(source)
                and value['worldDigest'] == digest(files['project/wit/world.wit'])
                and value['companionDigest'] == report['companionDigest']
                and all(value[name] is False for name in ('componentCompiled', 'signedStateExecutionQualified',
                    'unsignedRoundtripQualified', 'utf8RoundtripQualified', 'absentOptionalQualified'))
                and report['valueInputDigest'] == digest(raw)
                and report['applicationVariant'] == 'values', 'exact-java-value-source-declaration')
        require(all(fragment in text for fragment in ('Long.MIN_VALUE', '0xffff_fff1L', 'UTF8_VALUE',
                    'command.get(ABSENT_KEY)', 'query.get(ABSENT_KEY)', 'value-instance-reused', '.stage(command)')),
                'java-value-source-exercises-declared-vectors')
        requirements = report['deferredHttpRequirementsDigest']
    else:
        acquire = 'try (var command = State.acquireCommand().value()) {'
        call = 'Bindings.LatentServiceInvoke.call('
        require(text.count(acquire) == text.count(call) == 1 and text.index(acquire) < text.index(call)
                and 'Bindings.LatentServiceInvokePlatformErrorCode.PermissionDenied' in text
                and 'return Result.err(Bindings.ExamplesTransactionalAggregateApiBusinessError.Rejected)' in text
                and 'project/deferred-http-requirements.json' not in files,
                'reachable-java-child-call-without-effect-authority')
        requirements = None
    return ComponentInput(selected.variant, directory, report['componentDigest'], report['companionDigest'],
                          report['sourceDigest'], selected.source_commit, report['hostAbiDigest'], requirements)
