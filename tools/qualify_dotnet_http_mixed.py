"""One normal managed HTTP component, finite content/task controls, frozen native provenance."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import dotnet_catalogue_free_build as staging
from tools import dotnet_http_mixed_fixture as fixture, dotnet_http_mixed_node as node
from tools import dotnet_http_tenant_node as tenants
from tools import release_preparation_cli_native_products as products
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.dotnet_dependency_authoring import source_files
from tools.dotnet_guest import http_errors, managed_work, task_wait
from tools.dotnet_guest.compiler import runtime_inputs
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, snapshot, write_json

MATERIALS = (
    fixture.SOURCE, 'tools/fixtures/dotnet-http-mixed/Reference.cs',
    'tools/dotnet_http_mixed_fixture.py', 'tools/dotnet_http_mixed_node.py',
    'tools/dotnet_http_tenant_node.py', 'tools/qualify_resource_tenants.py', 'tools/resource_tenant_node.py',
    'tools/qualify_dotnet_http_mixed.py', 'tools/dotnet_standard_http_project.py',
    'tools/dotnet_standard_http_node.py', 'examples/dotnet-standard-http/world.wit',
    'tools/standard_http/peer.py', 'tools/standard_http/protocol.py', 'tools/standard_http/vectors.py',
    'tools/standard_http/observations.py', 'tools/java_http_mixed_node.py',
    'tools/java_http_tenant_node.py', 'tools/java_http_release_preparation.py',
    'tools/release_preparation_cli_native_products.py', 'tools/sdk_native_products_reader.py',
    'tools/rust_capsule_node.py', 'tools/phase2_operator_process.py', 'tools/phase2_operator_scenario.py',
    'tools/phase3_resource_identity.py', 'tools/phase3_resource_os.py', 'tools/phase3_resource_profile.py',
    '.github/workflows/dotnet-published-http.yml')
REFERENCE = b'managed-reference:incomplete-producer:4096:borrowed-output:owned-dispose:late-cancel-preserved'


def reference(output):
    """Ordinary CLR semantics of this exact source, not a WASI/HTTP qualification."""
    output = fresh(output);source = output/'source';source.mkdir()
    for name in ('Main.cs', 'Reference.cs'):
        (source/name).write_bytes(read_file(ROOT/'tools/fixtures/dotnet-http-mixed'/name))
    (source/'global.json').write_bytes(read_file(ROOT/'sdk/dotnet-guest/global.json'))
    (source/'Reference.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        '<OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework>'
        '<ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable><NuGetAudit>false</NuGetAudit>'
        '<UseSharedCompilation>false</UseSharedCompilation></PropertyGroup></Project>', encoding='utf8')
    config = source/'nuget.config'
    config.write_text('<configuration><packageSources><clear/></packageSources></configuration>', encoding='utf8')
    before = inventory(snapshot(source))
    commands = Commands(source, output, build_environment(output), deadline_seconds=180, command_seconds=120)
    dotnet = shutil.which('dotnet', path=commands.environment['PATH'])
    require(dotnet is not None and commands.run('dotnet-version', dotnet, '--version').strip() == b'10.0.100',
        'managed-mixed-reference-pinned-sdk')
    commands.run('reference-build', dotnet, 'build', source/'Reference.csproj', '-c', 'Release',
        '--output', output/'bin', '--artifacts-path', output/'artifacts',
        '-p:RestoreConfigFile='+str(config), '-p:NuGetAudit=false', '-nodeReuse:false')
    result = commands.run('reference-execute', dotnet, output/'bin/Reference.dll')
    require(result.strip() == REFERENCE and inventory(snapshot(source)) == before,
        'managed-mixed-reference-result-or-source-drift')
    value = {'scope': 'ordinary-CLR-managed-content-and-task-semantics-only', 'source': json.loads(before),
        'expected': REFERENCE.decode('ascii'), 'commands': commands.records,
        'guestIoExecuted': False, 'signedComponentQualified': False}
    write_json(output/'reference.json', value)
    return file_identity(output/'reference.json')


def build_evidence(artifact):
    identities = node.identities(artifact)
    marker = read_json(artifact/'BUILD-COMPLETE.json', 16*1024**2)
    observation = read_json(artifact/'build-observation.json', 16*1024**2)
    component = identities['component.wasm']
    require(marker['packageAssembled'] is True
        and marker['componentDigest'] == observation['componentDigest'] == component['sha256']
        and observation['componentSize'] == component['bytes']
        and marker['observationDigest'] == identities['build-observation.json']['sha256'],
        'managed-mixed-actual-component-and-observation')
    ports = {name: read_json(artifact/name, 16*1024**2) for name in (
        'http-error-port.json', 'task-wait-port.json', 'closed-filesystem-port.json')}
    http, task, fs = (ports[name] for name in ports)
    http_errors.validate_sync_read({name: value for name, value in http['synchronousRead'].items()
        if name != 'taskWaitDerivedDigest'})
    extra = {'profile', 'frameworkInput', 'tool', 'derived', 'sourceCaptureDigest',
        'targetsDigest', 'nativeAotReferenceBinding', 'selection'}
    # The unchanged standard world explicitly declares all four runtime inputs;
    # the maintained compiler therefore selects the finite Task.Wait derivation.
    task_wait.validate_receipt({name: value for name, value in task.items() if name not in extra}, finite=True, managed=True)
    managed_work.validate_http_rewrite(http['requiredContentWork'])
    require(http['sourceDigest'] == http_errors.SOURCE_DIGEST
        and all(row['digest'] == http_errors.SOURCE_DIGEST for row in http['frameworkInputs'])
        and http['derived']['digest'] == http['outputDigest']
        and len(http['nativeAotReferenceBinding']['responseFiles']) == 1
        and task['frameworkInput']['digest'] == task_wait.SOURCE
        and len(task['nativeAotReferenceBinding']['responseFiles']) == 1
        and http['synchronousRead']['taskWaitDerivedDigest'] == task['derived']['digest']
        and fs['nativeAotReferenceBinding']['selectedCoreLibDigest'] == fs['derived']['digest']
        and task['nativeAotReferenceBinding']['finalCoreLibDerivation']['intermediateDigest'] == task['derived']['digest']
        and task['nativeAotReferenceBinding']['finalCoreLibDerivation']['selectedDigest'] == fs['derived']['digest'],
        'managed-mixed-real-private-bcl-reference-binding')
    for material, name in (('dotnet-http-error-port', 'http-error-port.json'),
            ('dotnet-task-wait-port', 'task-wait-port.json'),
            ('runtime-profile', 'runtime-profile.json')):
        identity = identities[name]
        require([row for row in observation['materials'] if row['name'] == material] == [{
            'name': material, 'digest': identity['sha256'], 'size': identity['bytes']}],
            'managed-mixed-observed-actual-runtime-material')
    return {'component': component, 'identities': identities, 'httpPort': http, 'taskPort': task,
        'closedFilesystemPort': file_identity(artifact/'closed-filesystem-port.json', 16*1024**2)}


def qualify(native_directory, tools, output):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'managed-mixed-linux-python313')
    native_directory, tools = (Path(path).resolve(strict=True) for path in (native_directory, tools))
    output = Path(output).absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents
        and all(output != path and output not in path.parents and path not in output.parents
            for path in (native_directory, tools)), 'managed-mixed-separated-owned-inputs')
    output = fresh(output);deadline = time.monotonic()+1800
    native_record = products.verify_prepared(native_directory)
    native = products.native_products(native_directory)
    for path in native.values():path.chmod(0o700)
    original_products = {name: file_identity(path, 512*1024**2) for name, path in native.items()}
    materials = {name: file_identity(ROOT/name) for name in MATERIALS}
    sdk = inventory(snapshot(ROOT/'sdk/dotnet-guest'))
    consumer_native = source_identity(ROOT)
    runtime = runtime_inputs(ROOT)
    require(read_file(tools/'runtime-inputs.json') == runtime, 'managed-mixed-exact-current-runtime-installation')
    installation = {name: file_identity(tools/name, 16*1024**2)
        for name in ('INSTALL-COMPLETE.json', 'runtime-inputs.json', 'wasi-sdk.json')}
    record = {'schemaVersion': 'latent.dotnet.http-mixed-campaign.v1', 'status': 'in-progress',
        'fixtureSource': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'compiledNativeSource': products.SOURCE, 'nativeProducer': native_record,
        'consumerNativeSourceObservation': consumer_native, 'consumerNativeCompiledByThisCampaign': False,
        'materials': materials, 'sdkSources': json.loads(sdk), 'runtimeInputsDigest': digest(runtime),
        'installation': installation, 'newNativeProductsBuilt': 0, 'newGuestComponentsCompiled': 0,
        'applicationHandlerInjection': False, 'full693Qualified': False, 'full746Qualified': False}
    stage = 'actual-managed-reference'
    try:
        record['managedReference'] = reference(output/'reference')
        stage = 'normal-project-capture'
        app = fixture.project(output/'application')
        captured = inventory(source_files(app))
        stage = 'catalogue-free-normal-builder'
        staged = output/'staged-recipe';selected = staging.stage(ROOT, staged)
        write_json(output/'catalogue-free-source.json', selected)
        artifact = output/'build'
        result = run_bounded_result([sys.executable, '-I', '-S', '-B', str(staged/staging.SELF),
            '--project', str(app), '--output', str(artifact), '--tools', str(tools),
            '--contracts-tool', str(native['capsule_contracts']), '--packager', str(native['package']),
            '--repository', 'https://github.com/KirilsTurkins/latent-service-fabric',
            '--expect-source-digest', selected['inventoryDigest']], staged, build_environment(output),
            timeout_seconds=min(900, deadline-time.monotonic()), max_output_bytes=4*1024**2)
        artifact.mkdir(exist_ok=True)
        for name in ('stdout', 'stderr'):(artifact/('compiler.'+name+'.txt')).write_bytes(getattr(result, name))
        require(result.returncode == 0, 'managed-mixed-normal-native-aot-build')
        record['newGuestComponentsCompiled'] = 1
        require(read_file(artifact/'source-inputs.json') == captured
            and inventory(source_files(app)) == captured and staging.verify(staged) == selected,
            'managed-mixed-real-capture-and-builder-inputs')
        record['build'] = build_evidence(artifact)
        stage = 'signed-default-http-content-and-work'
        execution = node.run(artifact, native, output/'node', deadline=deadline)
        require(execution['status'] == 'passed' and execution['invocations'] == len(fixture.CASES) == 20
            and execution['httpContacts'] == 26,
            'managed-mixed-all-mandatory-outcomes')
        record['mixedNodeReceipt'] = file_identity(output/'node/qualification.json')
        stage = 'same-component-same-node-independent-tenants'
        isolated = tenants.run(artifact, native, output/'tenants', deadline=deadline)
        require(isolated['status'] == 'passed' and isolated['invocations'] == 10
            and isolated['preEntryRefusals'] == isolated['credentialRefusals'] == 1
            and isolated['httpContacts'] == 8, 'managed-mixed-all-independent-tenant-outcomes')
        require(time.monotonic() < deadline and products.verify_prepared(native_directory) == native_record
            and original_products == {name: file_identity(path, 512*1024**2) for name, path in native.items()}
            and materials == {name: file_identity(ROOT/name) for name in MATERIALS}
            and inventory(snapshot(ROOT/'sdk/dotnet-guest')) == sdk and runtime_inputs(ROOT) == runtime
            and read_file(tools/'runtime-inputs.json') == runtime and source_identity(ROOT) == consumer_native
            and installation == {name: file_identity(tools/name, 16*1024**2) for name in installation}
            and inventory(source_files(app)) == captured and staging.verify(staged) == selected,
            'managed-mixed-final-source-native-runtime-and-deadline-fences')
        record.update(status='passed', invocations=30, mixedInvocations=20, tenantInvocations=10, httpContacts=34,
            tenantReceipt=file_identity(output/'tenants/qualification.json'),
            catalogueDataPresent=False, publisherAuthenticated=False, hermetic=False,
            limitations=['Native execution uses the exact historical6fd producer and134materials; current consumer native bytes are only observed, not recompiled or relabelled.',
                'Late completion is after logical task cancellation but before activation retirement; no post-retired Store callback is claimed.',
                'Original Flurl/Refit, HTTPS and Task campaigns retain their own exact source attribution.'])
        write_json(output/'qualification.json', record)
        return record
    except BaseException:
        try:write_json(output/'FAILED.json', {**record, 'status': 'failed', 'stage': stage})
        except BaseException:pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('native', 'tools', 'output'):parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    print(qualify(args.native, args.tools, args.output)['status'])
