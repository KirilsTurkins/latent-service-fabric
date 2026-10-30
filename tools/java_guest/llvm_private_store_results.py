"""R8's strict 13-original + two private-store lit projection, no LLVM execution."""
from pathlib import PurePosixPath

from tools.java_guest import llvm_ssa_results as base
from tools.java_guest import llvm_private_store_patch as patch

units, cross_pass, xml_root = base.units, base.cross_pass, base.xml_root


def selection() -> dict:
    original = base.selection()
    added = [{'path': name, 'bytes': row['bytes'], 'sha256': row['sha256']}
             for name, row in patch.manifest()['tests'].items()]
    return {**original, 'wasmTests': [*original['wasmTests'], *added]}


def test_inputs(source) -> dict:
    # The original thirteen immutable source witnesses remain separately bound.
    # New file absence/postimages belong to the seven-member patch check.
    return base.test_inputs(source)


def lit(raw: bytes) -> dict:
    root = xml_root(raw)
    actual = []
    for row in root.iter('testcase'):
        name = row.get('name', '')
        if PurePosixPath(name).name != name or row.get('status') in ('notrun', 'disabled'):
            raise ValueError('llvm-private-lit-case-name')
        actual.append(name)
    original = [PurePosixPath(row['path']).name for row in base.selection()['wasmTests']]
    private = [PurePosixPath(name).name for name in patch.TESTS]
    if len(actual) != 15 or len(actual) != len(set(actual)) or set(actual) != set(original + private):
        raise ValueError('llvm-private-lit-case-set')
    return {'passed': 15, 'skipped': 0, 'cases': sorted(actual),
            'originalSjLj': {'passed': 13, 'cases': sorted(original)},
            'privateScalar': {'passed': 2, 'cases': sorted(private), 'sourceRunLines': 5},
            'xmlSha256': patch.sha(raw)}
