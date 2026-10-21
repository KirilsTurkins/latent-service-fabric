"""One fresh Java/.NET component; accepted late facilities and fresh two tenants."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import release_preparation_cli_native_products as products
from tools import resource_late_facilities as late
from tools import application_dependencies as inputs
from tools.build_observation import build_environment
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, inventory, read_file, read_json, snapshot
from tools.run_rust_capsule_workflow import write_workflow_receipt

SOURCES = ('tools/qualify_resource_late_facilities.py', 'tools/resource_late_facilities.py',
    'tools/fixtures/java-resource-late/Library.java', 'tools/fixtures/dotnet-resource-late/Library.cs',
    'tools/release_preparation_cli_native_products.py', 'tools/sdk_native_products_reader.py',
    'tools/dotnet_http_mixed_node.py', 'tools/java_http_release_preparation.py', *late.ACCOUNTING,
    '.github/workflows/java-resource-runtime.yml', '.github/workflows/dotnet-resource-runtime.yml')


def qualify(language, native_directory, tools, output):
    require(language in late.EXPECTED and sys.platform == 'linux' and sys.version_info >= (3, 13),
        'resource-late-language-linux-python313')
    native_directory, tools = (Path(p).resolve(strict=True) for p in (native_directory, tools))
    output = Path(output).absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents
        and all(output != p and output not in p.parents and p not in output.parents for p in (native_directory, tools)),
        'resource-late-independent-input-and-output-roots')
    if language == 'java':
        from tools import java_resource_runtime_fixture as fixture, qualify_java_resource_runtime as base
        from tools.java_capsule_build import build, FIBER_IO_PROFILE
        from tools.qualify_java_http_mixed import compiler_cache
        material_names = (*base.MATERIALS, 'tools/qualify_java_http_mixed.py')
    else:
        from tools import dotnet_resource_runtime_fixture as fixture, qualify_dotnet_resource_runtime as base
        from tools.dotnet_guest.build import build
        from tools.dotnet_guest.compiler import runtime_inputs
        material_names = base.MATERIALS
    compiled = products.verify_prepared(native_directory)
    native = products.native_products(native_directory)
    for path in native.values():
        path.chmod(0o700)
    native_before = {name: file_identity(path, 512*1024**2) for name, path in native.items()}
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=10).decode().strip()
    materials = {name: file_identity(ROOT/name) for name in dict.fromkeys((*material_names, *SOURCES))}
    sdk_before = inventory(snapshot(ROOT/('sdk/'+language+'-guest')))
    consumer_native = source_identity(ROOT)
    accounting = late.accounting_sources(products.SOURCE)
    output = fresh(output)
    commands = Commands(ROOT, fresh(output/'commands'), build_environment(output),
        deadline_seconds=1500, command_seconds=600)
    record = {'schemaVersion': 'latent.'+language+'.resource-late-qualification.v1', 'status': 'incomplete',
        'source': source, 'materials': materials, 'sdkSources': json.loads(sdk_before),
        'compiledNativeSource': products.SOURCE, 'compiledNative': compiled,
        'consumerNativeSourceObservation': consumer_native, 'consumerNativeCompiledByThisCampaign': False,
        'frozenLogAccountingSources': accounting, 'newNativeProductsBuilt': 0,
        'newGuestComponentsCompiled': 0, 'fullTicketQualification': False}
    stage = 'ordinary-outside-transitive-capture'
    try:
        if language == 'java':
            app, record['capture'] = fixture.capture(output/'project', commands, late_completion=True)
            before = inventory(snapshot(app))
            cache_root = output/'compiler'; cache_root.mkdir()
            stage = 'pinned-compiler-configurations-only-no-control-component'
            cache = compiler_cache(tools, cache_root, min(600, commands.deadline-time.monotonic()))
            record['compilerCache'] = read_json(cache_root/'compiler-cache-selection.json')
            require(record['compilerCache']['guestComponentsCompiled'] == 0,
                'resource-late-no-extra-java-control-component')
            stage = 'one-fresh-offline-java-component'
            remaining = min(900, commands.deadline-time.monotonic()-300)
            require(remaining > 60, 'resource-late-original-node-time-reserved')
            artifact = build(app, output/'build', native['capsule_contracts'], native['package'],
                'https://github.com/KirilsTurkins/latent-service-fabric', tools, timeout=remaining,
                read_only_cache=cache, runtime_profile=FIBER_IO_PROFILE)
            require(inputs.verify_inputs(app, 'java').identity == record['capture']['capturedInputIdentity'],
                'resource-late-original-reviewed-jar-closure')
            classpath = read_json(artifact/'java-classpath.json')
            require({row['id']: row['originalDigest'] for row in classpath['artifacts']} ==
                {name: row['digest'] for name, row in record['capture']['originalJars'].items()},
                'resource-late-exact-two-original-jars')
        else:
            runtime_before = runtime_inputs(ROOT)
            require(read_file(tools/'runtime-inputs.json') == runtime_before,
                'resource-late-current-compiler-runtime-installation')
            app, record['fixture'] = fixture.project(output/'project', output/'outside', late_completion=True)
            record['capture'] = fixture.capture(app, output/'outside', tools)
            before = inventory(snapshot(app))
            stage = 'one-fresh-offline-normal-native-aot-component'
            artifact = build(app, output/'build', native['capsule_contracts'], native['package'],
                'https://github.com/KirilsTurkins/latent-service-fabric', tools=tools, offline=True)
        record['newGuestComponentsCompiled'] = 1
        record['build'] = base.build_evidence(artifact)
        require(read_file(artifact/'source-inputs.json') == before,
            'resource-late-exact-ordinary-captured-build-source')
        stage = 'normal-sign-admit-two-denials-four-late-and-fresh-calls'
        if language == 'java':
            observed = base.execute(artifact, native, output/'node', commands.deadline, late_completion=True)
        else:
            observed = base.execute(artifact, native, output/'node', late_completion=True, deadline=commands.deadline)
            require(runtime_inputs(ROOT) == runtime_before and read_file(tools/'runtime-inputs.json') == runtime_before,
                'resource-late-final-dotnet-runtime-source')
        require(observed['status'] == 'passed' and observed['lateFacilitiesOnly'] is True
            and observed['originalProgrammePassed'] is False and len(observed['preparation']) == 2
            and set(observed['preparation']) == {'examples', 'foreign'}
            and len(observed['runtimeGrantDenials']) == 2
            and observed['programme']['status'] == 'passed' and len(observed['programme']['cases']) == 4
            and inventory(snapshot(app)) == before
            and inventory(snapshot(ROOT/('sdk/'+language+'-guest'))) == sdk_before
            and products.verify_prepared(native_directory) == compiled
            and {name: file_identity(path, 512*1024**2) for name, path in native.items()} == native_before
            and source_identity(ROOT) == consumer_native and time.monotonic() < commands.deadline
            and {name: file_identity(ROOT/name) for name in materials} == materials
            and late.accounting_sources(products.SOURCE) == accounting
            and subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=10).decode().strip() == source,
            'resource-late-final-cases-source-build-native-and-retirement-fences')
        record.update(status='passed', outcomes=6, signedAndAdmitted=True,
            nodeReceipt=file_identity(output/'node/qualified.json'), sourceOriginalsRemoved=True)
        write_workflow_receipt(output/'qualified.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__, commands=commands.records)
        write_workflow_receipt(output/'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language', choices=sorted(late.EXPECTED), required=True)
    for name in ('native', 'tools', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    print(qualify(args.language, args.native, args.tools, args.output)['status'])
