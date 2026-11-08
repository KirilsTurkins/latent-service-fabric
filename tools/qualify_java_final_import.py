"""Prepare a declaration-only adversarial import from the current Java timer fixture.

This tool validates and records component bytes; it does not sign, admit, or
execute a guest. The normal enforced catalog remains the admission authority.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import guest_compatibility_build as inspection
from tools import guest_final_import_control as control
from tools.build_observation import build_environment
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, checked_path, digest, fresh, read_file, read_json, write_json

FEATURES = 'cm-threading,cm-async-stackful,cm-more-async-builtins'
SOURCE = 'sdk/java-guest/fibers/conformance/timers/Capsule.java'
INPUTS = {'component': ('build/component.wasm', control.MAXIMUM),
          'source': ('src/Capsule.java', 1024 * 1024),
          'wit': ('wit/service.wit', 1024 * 1024),
          'compileReceipt': ('FIBERS-COMPILE.json', 8 * 1024 * 1024)}


def prepare(fixture: Path, output: Path, wasm: Path):
    fixture = checked_path(fixture)
    require(fixture.is_dir(), 'java-final-import-fixture')
    values = {key: read_file(fixture / name, maximum) for key, (name, maximum) in INPUTS.items()}
    record = read_json(fixture / INPUTS['compileReceipt'][0], INPUTS['compileReceipt'][1])
    require(record.get('fixture') == 'timers'
            and record.get('profile') == 'teavm-activation-fibers-v1'
            and record.get('status') == 'component-built-unqualified'
            and record.get('sourceDigest') == digest(values['source'])
            and record.get('componentDigest') == digest(values['component'])
            and values['source'] == read_file(ROOT / SOURCE, 1024 * 1024),
            'java-final-import-source-and-compile-receipt')
    wasm = checked_path(wasm)
    wasm_identity = file_identity(wasm, 64 * 1024 * 1024)
    output = fresh(output)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=180, command_seconds=30)
    require(commands.run('pinned-validator-version', wasm, '--version').strip() == b'wasm-tools 1.254.0',
            'java-final-import-pinned-wasm-tools')
    (output / 'unknown.wat').write_text(control.TEMPLATE, encoding='utf8')
    commands.run('assemble-declaration-only-template', wasm, 'parse', output / 'unknown.wat',
                 '-o', output / 'unknown.wasm')
    template = read_file(output / 'unknown.wasm', 4096)
    original_path = fixture / INPUTS['component'][0]
    commands.run('validate-original', wasm, 'validate', '--features', FEATURES, original_path)
    original_graph = json.loads(commands.run('original-wit', wasm, 'component', 'wit', original_path, '--json'))
    original_names = inspection.interface_names(original_graph)
    require(control.UNKNOWN not in original_names['imports'], 'java-final-import-already-present')
    mutant = control.append_unknown(values['component'], template)
    suffix = mutant[len(values['component']):]
    require(mutant.startswith(values['component']) and 0 < len(suffix) <= 128,
            'java-final-import-complete-original-prefix')
    (output / 'component.wasm').write_bytes(mutant)
    commands.run('validate-appended-import', wasm, 'validate', '--features', FEATURES, output / 'component.wasm')
    graph = json.loads(commands.run('appended-wit', wasm, 'component', 'wit', output / 'component.wasm', '--json'))
    names = inspection.interface_names(graph)
    require(set(names['imports']) == set(original_names['imports']) | {control.UNKNOWN}
            and len(names['imports']) == len(original_names['imports']) + 1
            and names['typeImports'] == original_names['typeImports']
            and names['exports'] == original_names['exports'], 'java-final-import-exact-surface-change')
    unknown = [row for row in graph['interfaces'] if row['name'] == 'final-import'
               and graph['packages'][row['package']]['name'] == 'diagnostic:unknown@0.1.0']
    require(len(unknown) == 1 and unknown[0]['types'] == {}
            and unknown[0]['functions'] == {'touch': {'name': 'touch', 'kind': 'freestanding', 'params': []}},
            'java-final-import-exact-callable-type')
    require(values == {key: read_file(fixture / name, maximum) for key, (name, maximum) in INPUTS.items()},
            'java-final-import-inputs-unchanged')
    result = {'schemaVersion': 'latent.java.final-import.preparation.v1', 'status': 'prepared',
              'scope': 'test-only-adversarial-declaration', 'runtimeOutcome': 'not-executed',
              'unknownInterface': control.UNKNOWN, 'componentDigest': digest(values['component']),
              'mutantDigest': digest(mutant), 'sourceDigest': digest(values['source']),
              'witDigest': digest(values['wit']), 'compileReceiptDigest': digest(values['compileReceipt']),
              'suffixDigest': digest(suffix), 'suffixBytes': len(suffix),
              'wasmTools': wasm_identity, 'validatorFeatures': FEATURES, 'commands': commands.records}
    write_json(output / 'PREPARED.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--wasm-tools', required=True, type=Path)
    args = parser.parse_args()
    value = prepare(args.fixture, args.output, args.wasm_tools)
    print(json.dumps({'status': value['status'], 'mutantDigest': value['mutantDigest'],
                      'runtimeOutcome': value['runtimeOutcome']}))
