"""Same-products Math.random approved and undeclared component programme."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_typescript_dependencies import prepared_native
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, fresh, inventory, read_json, snapshot, write_json
from tools.typescript_guest.build import build
from tools.typescript_guest.project import create
from tools.typescript_guest.entropy_profile import PROFILE, CLOSED
from tools.typescript_entropy_probe import prepare

MATERIALS = ('tools/qualify_typescript_standard_entropy.py', 'tools/typescript_entropy_probe.py',
    'tools/typescript_guest/entropy.mjs', 'tools/typescript_guest/entropy_profile.py',
    'tools/typescript_guest/compiler.py', 'tools/typescript_guest/bundle.mjs', 'tools/run_rust_capsule_workflow.py')


def qualify(prepared, tools, output):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'typescript-entropy-Linux-Python313')
    output = fresh(output)
    products, inherited = prepared_native(prepared)
    receipt = read_json(prepared/'qualification.json')
    sources = {name: file_identity(ROOT/name) for name in MATERIALS}
    record = {'schemaVersion': 'latent.typescript.standard-entropy-qualification.v1', 'status': 'incomplete',
        'inherited': inherited, 'sourceInputs': sources, 'fullTicketQualification': False,
        'publisherAuthenticated': False, 'releasePublished': False, 'randomPayloadRetained': False,
        'cryptographicAPI': False, 'normalNativeProductsRebuilt': False}
    stage = 'fresh-components'
    try:
        builds, inputs = {}, {}
        for name in TEMPLATES:
            if name not in {'greeting', 'word-count'}:
                builds[name] = prepared/'builds'/name
                require(read_json(builds[name]/'BUILD-COMPLETE.json') == receipt['builds'][name],
                        'typescript-entropy-original-companion-marker')
                continue
            app = create(output/('project-'+name), name)
            write_json(output/('fixture-'+name+'.json'), prepare(app, name))
            before = inventory(snapshot(app))
            builds[name] = build(app, output/('build-'+name), products['capsule_contracts'], products['package'],
                'https://github.com/KirilsTurkins/latent-service-fabric', tools=tools)
            require(inventory(snapshot(app)) == before and (builds[name]/'source-inputs.json').read_bytes() == before,
                    'typescript-entropy-component-source-changed')
            selection = read_json(builds[name]/'typescript-entropy-selection.json')
            require(selection['profile'] == (PROFILE if name == 'greeting' else CLOSED)
                    and selection['engineInputRebound'] is False, 'typescript-entropy-actual-profile-required')
            inputs[name] = read_json(builds[name]/'BUILD-COMPLETE.json')
        record['freshBuilds'] = inputs
        stage = 'normal-signing'
        commands = Commands(ROOT, output, build_environment(output))
        commands.run('entropy-demo-sign', products['capsule_authoring'], 'demo-sign', output/'signed',
                     *(builds[name] for name in TEMPLATES))
        stage = 'signed-original-and-entropy-programme'
        node = run(products['latent'], products['latentd'], output/'signed', output/'node', language='typescript',
                   standard_typescript_entropy=True)
        require(node['status'] == 'passed' and len(node['invocations']) == 34
                and node['typescriptStandardEntropy']['status'] == 'passed'
                and len(node['typescriptStandardEntropy']['cases']) == 6
                and all(row['processReaped'] for row in node['invocations'])
                and node['nodeShutdown']['reaped'] and node['nodeShutdown']['record']['clean'],
                'typescript-entropy-actual-original-and-new-outcomes-required')
        require(prepared_native(prepared)[1] == inherited and {name: file_identity(ROOT/name) for name in MATERIALS} == sources,
                'typescript-entropy-final-source-or-products-changed')
        record.update(status='passed', outcomes=34, node=file_identity(output/'node/workflow.json'))
        write_json(output/'qualification.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        write_json(output/'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared-qualification', type=Path, required=True)
    parser.add_argument('--tools', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.prepared_qualification.resolve(), args.tools.resolve(), args.output.resolve())))
