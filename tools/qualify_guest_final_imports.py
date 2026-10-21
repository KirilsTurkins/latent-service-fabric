"""Inspect retained six-language components; never compile, sign or execute them."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import guest_compatibility as compatibility
from tools import guest_compatibility_build as inspection
from tools import guest_final_import_control as control
from tools.build_observation import build_environment
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, read_file, read_json, write_json

FIXTURE = 'tools/tests/fixtures/final-import-components.json'
LANGUAGES = ('c', 'rust', 'go', 'typescript', 'java', 'dotnet')
# The maintained Rust/Java async profiles need more-async-builtins; C's
# component validator also selects threading. This only validates binaries.
FEATURES = 'cm-threading,cm-async-stackful,cm-more-async-builtins'
MATERIALS = (FIXTURE, 'tools/qualify_guest_final_imports.py',
    'tools/guest_final_import_control.py', 'tools/guest_compatibility.py',
    'tools/guest_compatibility_build.py', 'tools/guest_emitted_code.py',
    'tools/dev_workflow/common.py', 'tools/rust_capsule_build.py',
    'tools/rust_capsule_project.py', *inspection.HOST_MANIFESTS.values())
SOURCE_HELPERS = (
    'tools/application_dependencies.py',
    'tools/application_dependency_store.py',
    'tools/build_observation.py',
    'tools/build_process.py',
    'tools/build_process_linux.py',
    'tools/build_process_signals.py',
    'tools/build_process_windows.py',
    'tools/build_snapshot.py',
    'tools/dev_workflow/__init__.py',
    'tools/dev_workflow/dependencies.py',
    'tools/dev_workflow/paths.py',
    'tools/guest_authoring_frontend.py',
    'tools/guest_compatibility_context.py',
    'tools/guest_compatibility_context_build.py',
    'tools/guest_resources.py',
    'tools/guest_runtime_receipts.py',
    'tools/phase2_operator_process.py',
    'tools/phase3_resource_identity.py',
    'tools/phase3_resource_profile.py',
    'tools/stage_runtime_wit.py',
    'tools/transaction_guest_project.py',
)
MATERIALS = tuple(dict.fromkeys((*MATERIALS, *SOURCE_HELPERS)))
FILES = ('component.wasm', 'capsule.json')


def qualify(inputs: Path, output: Path, wasm: Path):
    specification = read_json(ROOT / FIXTURE, 65536)
    require(specification['schemaVersion'] == 'latent.final-import.control-inputs.v1'
        and [row['language'] for row in specification['cases']] == list(LANGUAGES),
        'final-import-exact-six-language-inventory')
    materials = (*MATERIALS, *(row['origin']['evidence'] for row in specification['cases']))
    before = {name: file_identity(ROOT / name, 8 * 1024**2) for name in materials}
    require(all(before[row['origin']['evidence']] == row['origin']['evidenceIdentity']
                for row in specification['cases']), 'final-import-exact-retained-origin-records')
    output = fresh(output.absolute())
    commands = Commands(ROOT, output, build_environment(output),
                        deadline_seconds=180, command_seconds=30)
    report = {'schemaVersion': 'latent.final-import.controls.v1', 'status': 'incomplete',
        'scope': 'final-component-inspector-only', 'authority': 'none',
        'guestComponentsCompiled': 0, 'guestInvocations': 0, 'packagesSigned': 0,
        'runtimeQualification': False, 'validatorFeatures': FEATURES,
        'source': before, 'cases': [], 'commands': commands.records}
    try:
        version = commands.run('pinned-validator-version', wasm, '--version')
        require(version.strip() == b'wasm-tools 1.254.0', 'final-import-pinned-wasm-tools')
        report['wasmTools'] = file_identity(wasm, 64 * 1024**2)
        (output / 'unknown.wat').write_text(control.TEMPLATE, encoding='utf8')
        commands.run('assemble-declaration-only-template', wasm, 'parse', output / 'unknown.wat',
                     '-o', output / 'unknown.wasm')
        template = read_file(output / 'unknown.wasm', 4096)
        for case in specification['cases']:
            language = case['language']
            source = inputs / language
            actual = {name: file_identity(source / name, control.MAXIMUM) for name in FILES}
            require(actual == case['files'], 'final-import-original-component-and-manifest-identities')
            raw = read_file(source / 'component.wasm', control.MAXIMUM)
            capsule = read_json(source / 'capsule.json', 65536)
            require(capsule['component']['digest'] == digest(raw), 'final-import-original-manifest-component')
            surface = {'world': capsule['component']['world'], 'exports': capsule['exports'],
                       'imports': [row['contract'] for row in capsule['imports']]}
            profile = inspection.declared_host_abi(surface)
            baseline, mutant = output / language / 'baseline', output / language / 'unknown'
            baseline.mkdir(parents=True); mutant.mkdir()
            (baseline / 'component.wasm').write_bytes(raw)
            commands.run(language + '-validate-original', wasm, 'validate', '--features',
                         FEATURES, baseline / 'component.wasm')
            original = inspection.inspect(commands, wasm, baseline, surface, host_abi_profile=profile)
            require(not any(row['classification'] in compatibility.BLOCKERS for row in original['findings']),
                    'final-import-original-current-inspection-passed')
            changed = control.append_unknown(raw, template)
            require(changed[:len(raw)] == raw and len(changed) - len(raw) <= 128,
                    'final-import-complete-original-byte-prefix')
            (mutant / 'component.wasm').write_bytes(changed)
            commands.run(language + '-validate-appended-import', wasm, 'validate', '--features',
                         FEATURES, mutant / 'component.wasm')
            graph = json.loads(commands.run(language + '-appended-callable-type', wasm,
                'component', 'wit', mutant / 'component.wasm', '--json'))
            unknown = [row for row in graph['interfaces'] if row['name'] == 'final-import'
                and graph['packages'][row['package']]['name'] == 'diagnostic:unknown@0.1.0']
            require(len(unknown) == 1 and unknown[0]['types'] == {}
                and unknown[0]['functions'] == {'touch': {'name': 'touch', 'kind': 'freestanding',
                    'params': []}}, 'final-import-exact-declaration-only-callable-type')
            try:
                inspection.inspect(commands, wasm, mutant, surface, host_abi_profile=profile)
            except ValueError as error:
                require(str(error) == 'final-component-compatibility-failed; inspect compatibility-inspection.json',
                        'final-import-original-inspector-refusal')
            else:
                raise ValueError('final-import-unknown-was-not-refused')
            refused = read_json(mutant / 'compatibility-inspection.json', 65536)
            require(refused['componentDigest'] == digest(changed)
                and set(refused['imports']) == set(original['imports']) | {control.UNKNOWN}
                and len(refused['imports']) == len(original['imports']) + 1
                and any(row == {'classification': 'unknown-import', 'phase': 'link',
                    'evidence': 'final-component', 'operation': control.UNKNOWN} for row in refused['findings']),
                'final-import-exact-new-callable-interface-refused')
            require(actual == {name: file_identity(source / name, control.MAXIMUM) for name in FILES},
                    'final-import-original-inputs-unchanged')
            report['cases'].append({'language': language, 'origin': case['origin'],
                'original': actual, 'originalInspectionPassed': True,
                'completeOriginalPrefixExact': True, 'appendedBytes': len(changed) - len(raw),
                'mutatedComponent': file_identity(mutant / 'component.wasm', control.MAXIMUM),
                'hostAbiProfile': profile, 'unknownInterface': control.UNKNOWN,
                'refusal': refused, 'runtimeOutcome': 'not-executed'})
        require(before == {name: file_identity(ROOT / name, 8 * 1024**2) for name in materials},
                'final-import-inspector-materials-unchanged')
        report['status'] = 'passed'
        write_json(output / 'qualification.json', report)
        return report
    except BaseException:
        report['status'] = 'failed'
        try:
            write_json(output / 'FAILED.json', report)
        except BaseException:
            pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--wasm-tools', required=True, type=Path)
    args = parser.parse_args()
    value = qualify(args.inputs, args.output, args.wasm_tools)
    print(json.dumps({'status': value['status'], 'languages': len(value['cases']),
                      'guestInvocations': value['guestInvocations']}))
