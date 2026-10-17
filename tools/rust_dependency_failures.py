"""Narrow native-FFI failure observations from an actual captured Rust crate."""
from __future__ import annotations

import re
from pathlib import Path

from tools import guest_compatibility as compatibility
from tools import rust_capsule_build as compiler
from tools.application_dependencies import verify_inputs
from tools.rust_capsule_project import digest, read_file, read_json, write_json

SYMBOL = 'outside_native_cpu'


def inspect_failure(output: Path, commands, wasm_tools: Path, artifact: dict) -> dict:
    failed = read_json(output / 'BUILD-FAILED.json')
    if failed['stage'] != 'component' or (output / 'BUILD-COMPLETE.json').exists() or (output / 'package').exists():
        raise ValueError('Rust FFI path did not fail at actual component assembly')
    observation = read_json(output / 'raw-core-observation.json')
    raw = read_file(output / 'raw-core.wasm', 64 * 1024 * 1024)
    source_digest = digest(read_file(output / 'source-inputs.json', 8 * 1024 * 1024))
    if (observation != {'formatVersion': 1, 'stage': 'component', 'sourceDigest': source_digest,
            'coreDigest': digest(raw), 'coreBytes': len(raw), 'state': 'retained-original-compiler-output', 'authority': 'none'}
            or not raw.startswith(b'\x00asm\x01\x00\x00\x00')):
        raise ValueError('Rust FFI original core observation is stale')
    skeleton = commands.run('inspect-actual-native-core', wasm_tools, 'print', output / 'raw-core.wasm', '--skeleton')
    if not re.search(rb'\(import\s+"env"\s+"' + SYMBOL.encode() + rb'"\s+\(func(?:\s|\))', skeleton):
        raise ValueError('Rust FFI original core lacks the exact reachable native import')
    if digest(read_file(output / 'raw-core.wasm', 64 * 1024 * 1024)) != observation['coreDigest']:
        raise ValueError('Rust FFI original core changed during inspection')
    original_raw = read_file(output / 'compatibility-report.json')
    original = compatibility.read(original_raw)
    if (original['sourceDigest'] != source_digest
            or not any(item['classification'] == 'unresolved-behavior' for item in original['findings'])):
        raise ValueError('Rust FFI original generic report was replaced or attributed speculatively')
    report = compatibility.report('rust', source_digest, None, original['runtimeProfile'],
        [{'kind': 'application', 'digest': artifact['original']['digest']}],
        [compatibility.finding('target-incompatible', 'link', 'compiler', operation='native-ffi',
            package_digest=artifact['original']['digest'], source_digest=artifact['original']['digest'], symbol=SYMBOL)])
    write_json(output / 'ffi-compatibility-report.json', report)
    if read_file(output / 'compatibility-report.json') != original_raw:
        raise ValueError('Rust FFI diagnostic overwrote original generic evidence')
    return {'case': 'reachable-external-native-ffi', 'classification': 'target-incompatible',
        'artifact': artifact['id'], 'originalPackageDigest': artifact['original']['digest'],
        'sourceDigest': source_digest, 'rawCore': observation, 'finding': report['findings'][0],
        'compatibilityReportDigest': digest(read_file(output / 'ffi-compatibility-report.json')),
        'originalGenericReportDigest': digest(original_raw), 'originalGenericStatus': original['status'],
        'finalComponent': 'unavailable-component-assembly-rejected', 'authority': 'none'}


def qualify(project: Path, output: Path, contracts: Path, packager: Path, wasm_tools: Path, commands) -> dict:
    verified = verify_inputs(project, 'rust')
    selected = [item for item in verified.lock['artifacts']
        if item['metadata'].get('package') == 'outside-qualification-library']
    if len(selected) != 1:
        raise ValueError('Rust FFI fixture requires the exact captured external source crate')
    source = project / 'src/lib.rs'
    before = source.read_bytes()
    anchor = b'outside_qualification_library::exercise(&name);'
    if before.count(anchor) != 1:
        raise ValueError('Rust FFI fixture entry point changed')
    source.write_bytes(before.replace(anchor, b'assert_eq!(outside_qualification_library::native_value(), 42);'))
    try:
        request_output = output / 'approval-required'
        try:
            compiler.build(project, request_output, contracts, packager,
                'https://github.com/KirilsTurkins/latent-service-fabric', offline=True)
        except ValueError:
            if read_json(request_output / 'BUILD-FAILED.json')['stage'] != 'executable-input-approval':
                raise
            request = read_json(request_output / 'executable-input-approval-request.json')
        else:
            raise ValueError('Rust FFI fixture executed build tools without exact approval')
        # This SDK-owned test policy approves only the same retained executable
        # sources selected by its normal captured-library fixture. Normal builds
        # never infer this consent from capture or package names.
        approved_ids = sorted(item['id'] for item in request['specification']['executableInputs'])
        if approved_ids != sorted(verified.lock['executableInputs']):
            raise ValueError('Rust FFI fixture executable input selection changed')
        rejected = output / 'reachable-native'
        try:
            compiler.build(project, rejected, contracts, packager,
                'https://github.com/KirilsTurkins/latent-service-fabric', offline=True,
                executable_approval=request['identity'])
        except ValueError:
            observed = inspect_failure(rejected, commands, wasm_tools, selected[0])
        else:
            raise ValueError('Rust FFI fixture unexpectedly acquired a native implementation')
        observed['executableApproval'] = request['identity']
        return observed
    finally:
        source.write_bytes(before)
        if verify_inputs(project, 'rust').identity != verified.identity:
            raise ValueError('Rust FFI fixture changed its original reviewed dependency closure')
