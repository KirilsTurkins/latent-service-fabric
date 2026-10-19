"""Fresh HTTP application component with fixed-source authenticated native products."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.go_standard_http_node import run
from tools.go_standard_http_project import project
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.replay_go_dependencies import check_baseline, compiler_materials, compiler_tools, frozen, owned_output
from tools import guest_runtime_receipts
from tools.go_guest.activation import INITIALIZER_PROFILE
from tools.qualify_rust_capsules import inputs
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, read_json, write_json

MATERIALS = ('tools/replay_go_http_adversarial.py', 'tools/replay_go_dependencies.py',
    'tools/go_standard_http_node.py', 'tools/go_standard_http_project.py',
    'tools/go_http_adversarial.py', 'tools/qualify_go_http_adversarial.py',
    'tools/fixtures/go-http-adversarial/main.go')


# Exact public original HTTP recipe retained in the immutable products artifact.
# HTTP declares activation/v5 WIT; the original greeting lacks that one manifest.
HTTP_RECIPE = {'artifact': 12211733679,
    'member': 'go-standard-http-signed/build/recipe-inputs.json',
    'digest': 'sha256:e326a9535ba29295382b667ff64108fd436684ccdd606cf60675962205acbb1f',
    'size': 7688}


def original_http_recipe(original_greeting: bytes, selected: bytes):
    require(len(selected) == HTTP_RECIPE['size'] and digest(selected) == HTTP_RECIPE['digest'],
            'go-http-replay-original-http-recipe-drift')
    original, current = json.loads(original_greeting), json.loads(selected)
    manifest = 'wit/host-abi-phase3-v5.json'
    require(manifest not in original and set(current) == set(original) | {manifest}
            and {name: row for name, row in current.items() if name != manifest} == original,
            'go-http-replay-original-greeting-recipe-drift')
    return dict(HTTP_RECIPE)


def qualify(prepared, baseline, output):
    output = owned_output(output)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1200, command_seconds=900)
    before = inputs('go')
    materials = {name: file_identity(ROOT / name) for name in MATERIALS}
    stage = 'authenticate-prepared-source-and-fresh-normal-27'
    try:
        receipt, products, compiler = frozen(prepared)
        ordinary = check_baseline(prepared, baseline)
        compiler_tools(prepared, compiler)
        stage = 'capture-additional-ordinary-application'
        app = project(output / 'project')
        source = (ROOT / 'tools/fixtures/go-http-adversarial/main.go').read_bytes()
        (app / 'src/main.go').write_bytes(source)
        lock = read_json(app / 'sdk-lock.json')
        lock['template']['sourceDigest'] = digest(source)
        (app / 'sdk-lock.json').write_bytes((json.dumps(lock, indent=2) + '\n').encode())
        stage = 'compile-new-application-with-original-compiler'
        commands.run('fresh-http-component', sys.executable, ROOT / 'tools/go_capsule.py',
            'build', app, '--output', output / 'build', '--repository',
            'https://github.com/KirilsTurkins/latent-service-fabric',
            '--contracts-tool', products['examples/capsule_contracts'], '--packager', products['examples/package'])
        observation = read_json(output / 'build/build-observation.json')
        selected_compiler = compiler_materials(observation)
        require({name: row for name, row in selected_compiler.items() if name != 'standard-runtime-selection'}
                == {name: row for name, row in compiler.items() if name != 'standard-runtime-selection'},
                'go-http-replay-original-compiler-or-sdk-material-drift')
        recipe_reference = original_http_recipe(
            (prepared / 'builds/greeting/recipe-inputs.json').read_bytes(),
            (output / 'build/recipe-inputs.json').read_bytes())
        runtime_selection = read_json(output / 'build/standard-runtime-selection.json')
        runtime_material = selected_compiler['standard-runtime-selection']
        raw_selection = (output / 'build/standard-runtime-selection.json').read_bytes()
        require(runtime_material == {'name': 'standard-runtime-selection',
                'digest': digest(raw_selection), 'size': len(raw_selection)},
                'go-http-replay-new-runtime-selection-unbound')
        from tools.rust_capsule_project import snapshot
        component = (output / 'build/component.wasm').read_bytes()
        runtime_materials = [row for row in observation['materials'] if row['name'] != 'standard-runtime-selection']
        guest_runtime_receipts.verify_build(runtime_selection, 'go', snapshot(app),
            (output / 'build/source-inputs.json').read_bytes(), component, runtime_materials)
        guest_runtime_receipts.validate(runtime_selection, language='go', profile=INITIALIZER_PROFILE,
            result=digest(json.dumps(read_json(output / 'build/bindings.json'),
                                    sort_keys=True, separators=(',', ':')).encode()),
            configuration={'profile': INITIALIZER_PROFILE, 'world': 'examples:go-standard-http/service@1.0.0',
                           'target': 'wasip1/wasm', 'selection': {}}, graph=None)
        require(observation['parameters']['locked'] is True and observation['parameters']['ambientWasi'] is False,
                'go-http-replay-locked-nonambient-component-required')
        native = {name: products[name] for name in ('latent', 'latentd')}
        native['capsule_authoring'] = products['examples/capsule_authoring']
        stage = 'fresh-signed-original-33-on-new-component'
        standard = run(output / 'build', native, output / 'standard-node', deadline=commands.deadline)
        require(standard['status'] == 'passed' and len(standard['cases']) == 33,
                'go-http-replay-original-33-required')
        stage = 'fresh-signed-adversarial-9-on-same-component'
        adversarial = run(output / 'build', native, output / 'adversarial-node',
                          suite='adversarial', deadline=commands.deadline)
        require(adversarial['status'] == 'passed' and len(adversarial['cases']) == 9,
                'go-http-replay-adversarial-9-required')
        require(before == inputs('go') and frozen(prepared)[0] == receipt
                and check_baseline(prepared, baseline) == ordinary
                and materials == {name: file_identity(ROOT / name) for name in MATERIALS},
                'go-http-replay-final-input-drift')
        result = {'schemaVersion': 'latent.go.http-adversarial-replay.v1', 'status': 'passed',
            'fixtureSource': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'compiledSource': read_json(prepared / 'retrieval.json')['compiledSource'],
            'originalProducts': file_identity(prepared / 'retrieval.json'),
            'freshNormalBaseline': ordinary, 'materials': materials,
            'nativeProductsCompiled': False, 'freshApplicationComponentCompiled': True,
            'compilerRecipeByteIdentical': True, 'compilerRecipeReference': recipe_reference,
            'sdkRuntimeProductionPreimagesByteIdentical': True,
            'newSourceBoundRuntimeSelection': runtime_material, 'selectedRuntimeProfile': INITIALIZER_PROFILE,
            'build': read_json(output / 'build/BUILD-COMPLETE.json'),
            'standard': file_identity(output / 'standard-node/qualification.json'),
            'adversarial': file_identity(output / 'adversarial-node/qualification.json'),
            'countedCases': 69, 'additionalHttpEntryProbes': 4, 'fullTicketQualification': False,
            'cleanHost': False, 'hermetic': False, 'publisherAuthenticated': False}
        write_json(output / 'qualification.json', result)
        return result
    except BaseException as error:
        try:
            write_json(output / 'FAILED.json', {'status': 'failed', 'stage': stage,
                'errorCategory': type(error).__name__, 'materials': materials,
                'nativeProductsCompiled': False, 'fullTicketQualification': False})
        except Exception:
            pass  # Retention cannot replace the original compiler or node failure.
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({'status': qualify(args.prepared.resolve(), args.baseline.resolve(), args.output.resolve())['status']}))
