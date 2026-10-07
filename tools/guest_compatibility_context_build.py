"""Bind owner-emitted runtime/patch receipts after existing immutable-input checks."""
from __future__ import annotations

from pathlib import Path

from tools import guest_compatibility as compatibility
from tools import guest_compatibility_context as context
from tools import guest_emitted_code, guest_runtime_receipts
from tools.dev_workflow.common import decode, digest, encode, require
from tools.rust_capsule_project import read_file, write_json

# Rust's shared Commands/package_inputs module is imported by every owner, so
# its runtime receipt dependency belongs in their common captured closure too.
RECIPE = ('tools/guest_compatibility_context.py', 'tools/guest_compatibility_context_build.py',
          'tools/guest_runtime_receipts.py', 'tools/guest_emitted_code.py')


def finish(output: Path, files: dict[str, bytes], source_inputs: bytes,
           component: bytes, materials: list[dict]) -> dict:
    report_raw = read_file(output / 'compatibility-report.json', compatibility.MAX_BYTES)
    report = compatibility.read(report_raw)
    require(report['sourceDigest'] == digest(source_inputs) and report['componentDigest'] == digest(component),
            'compatibility-context-stale-build')
    sdk = decode(files['sdk-lock.json'], 8 * 1024 * 1024)
    selected = {'state': 'absent'}
    retained = [context.material('sdk', 'sdk-lock', digest(encode(sdk)))]
    captured = {}
    require(isinstance(materials, list) and len(materials) <= 64, 'compatibility-context-build-material-limit')
    for row in materials:
        require(isinstance(row, dict) and isinstance(row.get('name'), str) and row['name'] not in captured,
                'compatibility-context-duplicate-build-material')
        captured[row['name']] = row
        if row['name'] not in {'source-snapshot', 'package-inputs'}:
            kind = 'generated' if row['name'] in {'c-generator-inputs', 'go-generator-inputs',
                'java-generator-inputs', 'typescript-generator-inputs', 'executable-input-outputs'} else 'compiler'
            retained.append(context.material(kind, row['name'], row['digest']))

    def bound_receipt(filename, name, maximum):
        raw = read_file(output / filename, maximum)
        row = captured.get(name)
        require(row is not None and row['digest'] == digest(raw) and row['size'] == len(raw),
                'compatibility-context-stale-or-unbound-receipt')
        return raw, decode(raw, maximum)

    runtime_path = output / 'runtime-profile.json'
    owner_runtime = output / 'standard-runtime-selection.json'
    if runtime_path.exists() or owner_runtime.exists():
        filename = 'standard-runtime-selection.json' if owner_runtime.exists() else 'runtime-profile.json'
        name = 'standard-runtime-selection' if owner_runtime.exists() else 'runtime-profile'
        raw, runtime = bound_receipt(filename, name, 65536 if owner_runtime.exists() else 4 * 1024 * 1024)
        if owner_runtime.exists():
            guest_runtime_receipts.verify_build(runtime, report['language'], files, source_inputs, component,
                [row for row in materials if row['name'] != 'standard-runtime-selection'])
        require(isinstance(runtime, dict) and isinstance(runtime.get('profile'), str),
                'compatibility-context-runtime-receipt')
        profile = compatibility.token(runtime['profile'])
        retained.append(context.material('runtime', 'selected-standard-runtime', digest(raw), profile=profile))
        selected = {'state': 'selected-unqualified', 'profile': profile, 'receiptDigest': digest(raw)}
        if owner_runtime.exists():
            selected['receiptName'] = filename
            selected['ownerIssue'] = runtime['ownerIssue']
            retained.append(context.material('runtime', 'selected-runtime-original',
                runtime['originalRuntimeInputsDigest'], profile=profile))
            for transform in runtime['transformations']:
                retained.append(context.material('generated', transform['name'], transform['resultDigest'],
                    original=transform['originalDigest'], transformation=digest(encode(transform))))
        # A compiler receipt identifies selection. Even a "qualified" string
        # cannot establish this component's reachability or runtime behavior.
    patches_path = output / 'compiler-patches.json'
    if patches_path.exists():
        raw, patches = bound_receipt('compiler-patches.json', 'automatic-compiler-patches', 4 * 1024 * 1024)
        require(isinstance(patches, dict) and patches.get('formatVersion') == 1
                and isinstance(patches.get('patches'), list) and len(patches['patches']) <= 64,
                'compatibility-context-patch-receipt')
        recipe = captured.get('build-recipe')
        require(recipe is not None, 'compatibility-context-patch-recipe-required')
        for patch in patches['patches']:
            require(isinstance(patch, dict) and {'name', 'profile', 'original', 'selected', 'selection'} <= patch.keys(),
                    'compatibility-context-patch-identity-required')
            require(isinstance(patch['original'], dict) and isinstance(patch['selected'], dict),
                    'compatibility-context-patch-preimage-required')
            transformation = digest(encode({'recipeDigest': recipe['digest'], 'name': patch['name'],
                                           'profile': patch['profile'], 'selection': patch['selection']}))
            retained.append(context.material('patch', patch['name'], patch['selected']['digest'],
                profile=patch['profile'], original=patch['original']['digest'], transformation=transformation))
    # Prefer all identified runtime/patch entries if a compiler observation
    # already fills the finite material count. Omission never becomes support.
    retained.sort(key=lambda row: (row['kind'] not in {'runtime', 'patch'}, row['kind'], row['name']))
    omitted = max(0, len(retained) - context.MAX_MATERIALS)
    value = context.create(report, retained[:context.MAX_MATERIALS], selected, omitted=omitted)
    write_json(output / 'compatibility-context.json', value)
    captured_graph = guest_runtime_receipts.captured_graph(files)
    graph = digest(encode(captured_graph)) if captured_graph is not None else None
    guest_emitted_code.emit(output, component, digest(source_inputs), selected.get('profile', 'not-observed'),
        report['runtimeProfile'], graph=graph, recipe=captured.get('build-recipe', {}).get('digest'))
    require(read_file(output / 'compatibility-report.json', compatibility.MAX_BYTES) == report_raw,
            'compatibility-context-report-was-mutated')
    return value
