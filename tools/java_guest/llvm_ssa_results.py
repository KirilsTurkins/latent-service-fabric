"""Strict observations of actual LLVM tests; no compiler execution at import."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET

from tools.java_guest import llvm_ssa_patch as patch

TEST_SHA256 = '8653f5db9184cd5c2bfde09cb9820e40a3e0fe410900da588cb755f50e24e02f'


def selection() -> dict:
    raw = patch.regular(patch.DATA, 'tests.json', 16384)
    if patch.sha(raw) != TEST_SHA256:
        raise ValueError('llvm-producer-test-selection-identity')
    value = json.loads(raw)
    if (value['schemaVersion'] != 'latent.java.llvm-sjlj-regression-set.v1'
            or value['llvmCommit'] != patch.LLVM or len(value['wasmTests']) != 13
            or value['crossPass'] != 'llvm/test/CodeGen/WebAssembly/lower-wasm-ehsjlj-phi.ll'):
        raise ValueError('llvm-producer-test-selection')
    return value


def test_inputs(source: Path) -> dict:
    actual = {}
    for row in selection()['wasmTests']:
        raw = patch.regular(source, row['path'], 65536)
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        if len(raw) != row['bytes'] or blob != row['gitBlob']:
            raise ValueError('llvm-producer-original-test-mutated')
        actual[row['path']] = {'bytes': len(raw), 'gitBlob': blob, 'sha256': patch.sha(raw)}
    return actual


def xml_root(raw: bytes):
    if not 0 < len(raw) <= 256 * 1024 or b'<!' in raw:
        raise ValueError('llvm-producer-test-xml-bound')
    root = ET.fromstring(raw)
    if root.tag not in ('testsuite', 'testsuites'):
        raise ValueError('llvm-producer-test-xml-root')
    if any(node.tag in ('failure', 'error', 'skipped') for node in root.iter()):
        raise ValueError('llvm-producer-test-not-passed')
    for node in root.iter():
        for field in ('failures', 'errors', 'disabled', 'skipped'):
            if field in node.attrib and node.attrib[field] != '0':
                raise ValueError('llvm-producer-test-not-passed')
    return root


def units(raw: bytes) -> dict:
    root = xml_root(raw)
    rows = list(root.iter('testcase'))
    actual = []
    for row in rows:
        if row.get('status') != 'run' or row.get('result') != 'completed':
            raise ValueError('llvm-producer-unit-not-executed')
        actual.append(row.get('classname', '') + '.' + row.get('name', ''))
    expected = patch.unit_cases()
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise ValueError('llvm-producer-unit-case-set')
    return {'passed': len(actual), 'skipped': 0, 'cases': sorted(actual), 'xmlSha256': patch.sha(raw)}


def lit(raw: bytes) -> dict:
    root = xml_root(raw)
    rows = list(root.iter('testcase'))
    actual = []
    for row in rows:
        # lit's XML file case name is the original source basename; any
        # additional, repeated or unexecuted case is a producer failure.
        name = row.get('name', '')
        if PurePosixPath(name).name != name or row.get('status') in ('notrun', 'disabled'):
            raise ValueError('llvm-producer-lit-case-name')
        actual.append(name)
    expected = [PurePosixPath(row['path']).name for row in selection()['wasmTests']]
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise ValueError('llvm-producer-lit-case-set')
    return {'passed': len(actual), 'skipped': 0, 'cases': sorted(actual), 'xmlSha256': patch.sha(raw)}


def cross_pass(raw: bytes) -> dict:
    """Check the real verifier/codegen input, not a modeled PHI optimizer."""
    if (not 0 < len(raw) <= 256 * 1024 or b'__wasm_setjmp' not in raw
            or re.search(rb'\bcall\s+i32\s+@setjmp\(', raw)):
        raise ValueError('llvm-producer-cross-pass-shape')
    phis, switches = 0, 0
    lines = raw.decode('utf-8').splitlines()
    if len(lines) > 4096 or any(len(line.encode()) > 16384 for line in lines):
        raise ValueError('llvm-producer-cross-pass-bound')
    for line in lines:
        if line.startswith('define ') or re.match(r'^[-a-zA-Z$._0-9]+:', line):
            phis = 0
        body = line.strip()
        if re.match(r'%[-a-zA-Z$._0-9]+ = phi\b', body):
            phis += 1
        if re.search(r'\bcatchswitch\b', body.split(';', 1)[0]):
            switches += 1
            if phis:
                raise ValueError('llvm-producer-catchswitch-phi')
    if switches == 0:
        raise ValueError('llvm-producer-cross-pass-no-catchswitch')
    return {'catchswitches': switches, 'catchswitchPhis': 0,
            'bytes': len(raw), 'sha256': patch.sha(raw),
            'scope': 'Actual pinned SjLj PHI regression through SjLj, WinEH and verifier; instruction selection checked separately. No component-size claim.'}
