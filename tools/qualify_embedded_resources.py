"""Fresh embedded-data greeting on authenticated normal products and companions."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time

if __package__ in {None,''}:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools.application_dependencies import verify_inputs
from tools.build_observation import build_environment
from tools.embedded_resource_fixture import DATA, EXPECTED, LANGUAGES, MATERIALS, PACKAGES, capture
from tools.embedded_resource_probe import PREFIX
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.qualify_rust_capsules import inputs
from tools.qualify_sdk_scratch import PRODUCTS, package_identity
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, inventory, read_file, read_json, snapshot, write_json

HELPERS = (*MATERIALS,'tools/embedded_resource_fixture.py','tools/embedded_resource_probe.py',
    'tools/qualify_embedded_resources.py','tools/run_rust_capsule_workflow.py')


def prepared(directory, language):
    """Exact current normal proof only; historical replay must supply its own ancestry."""
    require(language in LANGUAGES, 'embedded-resource-language')
    q = read_json(directory/'qualification.json')
    source = read_file(directory/'source-inputs.json',16*1024**2)
    require(q.get('schemaVersion') == 'latent.'+language+'-capsule.qualification.v1'
        and q.get('status') == 'passed' and 'applicationDependencies' not in q
        and digest(source) == q['sourceIdentityDigest'] and json.loads(source) == inputs(language),
        'embedded-resource-original-current-normal-required')
    binaries = {name:directory/'native-binaries'/name.replace('/','-') for name in PRODUCTS}
    require({name:file_identity(path,512*1024**2) for name,path in binaries.items()} == q['binaries'],
        'embedded-resource-native-products-changed')
    companions = {}
    for name in TEMPLATES:
        if name == 'greeting': continue
        location = directory/'builds'/name
        marker = read_json(location/'BUILD-COMPLETE.json')
        require(marker == q['builds'][name], 'embedded-resource-original-companion-marker')
        package_identity(location,marker)
        companions[name] = location
    node = read_json(directory/'node/workflow.json',1024**2)
    require(file_identity(directory/'node/workflow.json')['sha256'] == q['node']['receiptDigest']
        and node['status'] == 'passed' and node['language'] == language
        and 27 <= len(node['invocations']) <= 40
        and all(row['processReaped'] and row['response']['outcomeKnown'] is True for row in node['invocations'])
        and node['nodeShutdown']['reaped'] and node['nodeShutdown']['record']['clean'],
        'embedded-resource-original-normal-node')
    return binaries,companions,{'qualification':file_identity(directory/'qualification.json'),
        'sourceInputs':file_identity(directory/'source-inputs.json',16*1024**2),
        'nativeProducts':q['binaries'],'normalActivations':[row['activation'] for row in node['invocations']],
        'physicalSamples':len(node['samples']),'idleSamples':len(node['providerIdle'])}


def selected_go_packages(value):
    rows = value.get('packages')
    require(type(rows) is list and len(rows) <= 4096, 'embedded-resource-Go-package-bound')
    for name in ('embed','io/fs'):
        selected = [row for row in rows if row.get('importPath') == name]
        require(len(selected) == 1 and selected[0].get('standard') is True,
                'embedded-resource-Go-real-standard-package')
    selected = [row for row in rows if row.get('importPath') == PACKAGES['go'][1]]
    require(len(selected) == 1 and selected[0].get('standard') is False
        and selected[0].get('embedFiles') == sorted(DATA), 'embedded-resource-Go-exact-transitive-assets')
    return selected[0]


def observation(node, ancestry, language):
    require(node['status'] == 'passed' and node['language'] == language, 'embedded-resource-node-failed')
    rows = node['invocations']
    original = [row['activation'] for row in rows if not row['activation'].startswith(PREFIX)]
    require(original == ancestry['normalActivations'] and len(original) == len(set(original)),
            'embedded-resource-original-programme-changed')
    observed = node['embeddedResourceConformance']
    require(observed['status'] == 'passed' and observed['language'] == language
        and [row['mode'] for row in observed['cases']] == list(EXPECTED[language])
        and all(row['invocation'] in rows and row['invocation']['exitCode'] == 0
            and row['invocation']['decoded'] == [{'ok':EXPECTED[language][row['mode']]}]
            for row in observed['cases'])
        and observed['explicitTrap'] in rows and observed['explicitTrap']['response']['error']['code'] == 'guest-trap'
        and observed['freshAfterTrap'] in rows
        and observed['freshAfterTrap']['decoded'] == [{'ok':EXPECTED[language]['binary']}],
        'embedded-resource-exact-data-trap-fresh')
    count = len(EXPECTED[language])+2
    require(len(rows) == len(original)+count == len(set(row['activation'] for row in rows))
        and all(row['processReaped'] and row['response']['outcomeKnown'] is True for row in rows)
        and len(node['samples']) == ancestry['physicalSamples']+count
        and len(node['providerIdle']) == ancestry['idleSamples']+count
        and all(not row['unavailable'] and all(int(row['counters'][key]) == 0 for key in ACTIVE_COUNTERS)
            for row in node['providerIdle'])
        and node['nodeShutdown']['reaped'] and node['nodeShutdown']['record']['clean'],
        'embedded-resource-physical-retirement-or-original-counts')
    return {'originalInvocations':len(original),'newInvocations':count,'totalInvocations':len(rows),
        'physicalSamples':len(node['samples']),'zeroActiveOwnerSamples':len(node['providerIdle']),
        'allKnownReaped':True,'cleanShutdown':True,'crossTenantQualification':False}


def campaign(language, output, binaries, companions, ancestry, *, tools=None):
    require(language in LANGUAGES and sys.platform == 'linux' and sys.version_info >= (3,13)
        and os.geteuid() != 0, 'embedded-resource-unprivileged-linux-python313')
    output = output.absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
            'embedded-resource-output-outside-checkout')
    require(set(companions) == set(TEMPLATES)-{'greeting'}, 'embedded-resource-four-companions')
    output = fresh(output)
    materials = {name:file_identity(ROOT/name) for name in HELPERS}
    native = {name:file_identity(path,512*1024**2) for name,path in binaries.items()}
    previous = {name:package_identity(path,read_json(path/'BUILD-COMPLETE.json')) for name,path in companions.items()}
    record = {'schemaVersion':'latent.embedded-resources.qualification.v1','language':language,
        'status':'incomplete','inherited':ancestry,'materials':materials,'nativeProducts':native,
        'nativeRebuilt':False,'companionsRecompiled':False,'fullTicketQualification':False}
    commands = Commands(ROOT,output,build_environment(output),deadline_seconds=1100,command_seconds=600)
    stage = 'ordinary-source-capture'
    try:
        if language == 'typescript':
            node = Path(shutil.which('node') or 'missing-node')
            npm = node.parent/'node_modules/npm/bin/npm-cli.js' if os.name == 'nt' else Path(shutil.which('npm') or 'missing-npm').resolve()
            compiler = (node,npm)
        else:
            compiler = Path(shutil.which('go' if language == 'go' else 'cargo') or 'missing-compiler')
        app,captured = capture(language,output/'application',output/'outside-originals',compiler)
        record['capture'] = captured
        before = inventory(snapshot(app))
        stage = 'fresh-offline-component'
        arguments = (app,output/'build',binaries['examples/capsule_contracts'],binaries['examples/package'],
                     'https://github.com/KirilsTurkins/latent-service-fabric')
        if language == 'go':
            from tools.go_capsule_build import build
            artifact = build(*arguments)
            record['selectedGoPackages'] = selected_go_packages(read_json(artifact/'go-module-build-inputs.json'))
            require(read_json(artifact/'compiler-containment.json')['network'] == 'denied', 'embedded-resource-Go-network-not-denied')
        elif language == 'rust':
            from tools.qualify_sdk_scratch import locked_dependencies
            from tools.rust_capsule_build import build
            record['lockedDownload'] = locked_dependencies(language,app,commands)
            artifact = build(*arguments,offline=True)
            require(read_json(artifact/'cargo-inputs.json')['networkResolution'] is False,
                    'embedded-resource-Rust-network-resolution')
        else:
            from tools.typescript_guest.build import build
            require(tools is not None, 'embedded-resource-TypeScript-tools-required')
            artifact = build(*arguments,tools=tools)
        require(read_file(artifact/'source-inputs.json',16*1024**2) == before,
                'embedded-resource-compiled-source-changed')
        marker = read_json(artifact/'BUILD-COMPLETE.json'); package_identity(artifact,marker)
        stage = 'normal-sign-admit-and-original-programme'
        commands.run('embedded-resource-sign',binaries['examples/capsule_authoring'],'demo-sign',output/'signed',
            *(artifact if name == 'greeting' else companions[name] for name in TEMPLATES))
        node = run(binaries['latent'],binaries['latentd'],output/'signed',output/'node',
            language=language,embedded_resource_conformance=True)
        observed = observation(node,ancestry,language)
        require(inventory(snapshot(app)) == before
            and verify_inputs(app,language).identity == captured['capturedInputIdentity']
            and materials == {name:file_identity(ROOT/name) for name in HELPERS}
            and native == {name:file_identity(path,512*1024**2) for name,path in binaries.items()}
            and previous == {name:package_identity(path,read_json(path/'BUILD-COMPLETE.json')) for name,path in companions.items()}
            and time.monotonic() <= commands.deadline, 'embedded-resource-final-source-products-or-deadline')
        record.update(status='passed',observation=observed,build=marker,
            source=file_identity(artifact/'source-inputs.json',16*1024**2),
            recipe=file_identity(artifact/'recipe-inputs.json',16*1024**2),
            compatibilityReport=file_identity(artifact/'compatibility-report.json'),
            workflow=file_identity(output/'node/workflow.json'),commands=commands.records)
        write_json(output/'qualified.json',record)
        return record
    except BaseException as error:
        record.update(status='failed',stage=stage,errorCategory=type(error).__name__,commands=commands.records)
        write_json(output/'FAILED.json',record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language',choices=LANGUAGES,required=True)
    for name in ('output','native-qualification'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--tools',type=Path)
    args = parser.parse_args()
    products,companions,ancestry = prepared(args.native_qualification.resolve(strict=True),args.language)
    result = campaign(args.language,args.output,products,companions,ancestry,tools=args.tools)
    require(prepared(args.native_qualification,args.language)[2] == ancestry,'embedded-resource-original-inputs-changed')
    print(result['status'])
