"""Build one source-bound instrumented poll-prefetch variant and observe one signed call."""
from __future__ import annotations
import argparse
from pathlib import Path, PurePosixPath
import subprocess
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import dotnet_finite_wait_fixture as fixture, dotnet_poll_prefetch_node as node
from tools.dotnet_guest.build import build
from tools.dotnet_guest.compiler import runtime_inputs
from tools.java_replay_materials import git_source_identity
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.qualify_dotnet_finite_waits import build_evidence, recipe_inputs
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, snapshot, write_json

FIXTURE = 'tools/fixtures/dotnet-poll-prefetch/Library.cs'
MATERIALS = (FIXTURE, 'tools/dotnet_finite_wait_fixture.py', 'tools/dotnet_poll_prefetch_node.py',
    'tools/qualify_dotnet_poll_prefetch.py', 'sdk/dotnet-guest/tools/http-errors/AggregateTaskWait.cs',
    'sdk/dotnet-guest/tools/http-errors/ManagedWorkHooks.cs', 'sdk/dotnet-guest/tools/http-errors/TaskWait.cs',
    'sdk/dotnet-guest/tools/http-errors/IdleTimerDriver.cs', 'tools/dotnet_guest/aggregate_task_wait.py',
    'tools/dotnet_guest/task_wait.py', 'tools/run_dotnet_poll_prefetch_pair.py',
    'tools/admit_dotnet_poll_prefetch_evidence.py', '.github/workflows/dotnet-poll-prefetch-diagnostic.yml',
    'tools/wasmtime_48_0_8_678b_native_products.py', 'tools/sdk_native_products_reader.py',
    'tools/java_replay_materials.py', 'tools/phase3_resource_identity.py', 'tools/dotnet_guest/build.py',
    'tools/dotnet_standard_http_node.py', 'tools/wait_capsule_audit_idle.py',
    'tools/dotnet_task_runtime_probe.py', 'tools/guest_runtime_grants.py',
    'tools/resource_tenant_node.py', 'tools/rust_capsule_node.py', 'tools/sdk_provider_scenario.py',
    'tools/qualify_resource_tenants.py', 'tools/phase2_operator_scenario.py', 'tools/phase3_resource_os.py')
VARIANTS = {'baseline': ('latent.dotnet.wait-all.v2', 'prefetch-observed:driver-before-sibling'),
            'fixed': ('latent.dotnet.wait-all.v3', 'prefetch-observed:sibling-before-driver')}


def current_materials(native_directory):
    record = read_json(native_directory / 'native-products.json')
    rows = record['materials']; require(type(rows) is dict and len(rows) == 135,
        'poll-prefetch-source-material-count')
    for name, expected in rows.items():
        path = PurePosixPath(name)
        require(type(name) is str and not path.is_absolute() and all(x not in ('', '.', '..') for x in path.parts),
            'poll-prefetch-source-material-path')
        value = ROOT.joinpath(*path.parts)
        require(not value.is_symlink() and all(not ROOT.joinpath(*path.parts[:i]).is_symlink()
            for i in range(1, len(path.parts))) and file_identity(value) == expected,
            'poll-prefetch-current-native-material')
    return rows


def qualify(native_directory, tools_directory, output, *, variant, expected_head):
    from tools import wasmtime_48_0_8_678b_native_products as products
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'poll-prefetch-linux-python313')
    require(type(variant) is str and variant in VARIANTS and type(expected_head) is str
        and len(expected_head) == 40 and all(c in '0123456789abcdef' for c in expected_head),
        'poll-prefetch-closed-variant-source')
    native_directory, tools_directory = (Path(path).resolve(strict=True) for path in (native_directory, tools_directory))
    output = Path(output).absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents
        and all(output != p and output not in p.parents and p not in output.parents
            for p in (native_directory, tools_directory)), 'poll-prefetch-separated-inputs')
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=ROOT, timeout=20).decode().strip()
    require(git('rev-parse', 'HEAD') == expected_head and not git('status', '--porcelain'),
        'poll-prefetch-clean-exact-source')
    compiled = products.verify_prepared(native_directory); native = products.native_products(native_directory)
    require(set(native) == {'latent', 'latentd', 'package', 'capsule_contracts', 'capsule_authoring'},
        'poll-prefetch-exact-five-native-products')
    for path in native.values(): path.chmod(0o700)
    current_native = source_identity(ROOT)
    require(current_native == git_source_identity(products.SOURCE), 'poll-prefetch-current-native-source')
    source_materials = current_materials(native_directory)
    runtime = runtime_inputs(ROOT)
    require(read_file(tools_directory / 'runtime-inputs.json') == runtime,
        'poll-prefetch-source-matched-compiler-installation')
    installation = {name: file_identity(tools_directory / name, 16 * 1024**2)
        for name in ('INSTALL-COMPLETE.json', 'runtime-inputs.json', 'wasi-sdk.json')}
    materials = {name: file_identity(ROOT / name) for name in MATERIALS}
    output = fresh(output)
    record = {'schemaVersion': 'latent.dotnet.poll-prefetch.variant.v1', 'status': 'incomplete',
        'variant': variant, 'sourceCommit': expected_head, 'fixture': materials[FIXTURE],
        'materials': materials, 'nativeProducts': compiled, 'nativeSource': current_native,
        'runtimeInputs': {'sha256': digest(runtime), 'bytes': len(runtime)}, 'installation': installation,
        'diagnosticOnly': True, 'ordinaryRuntimeQualified': False, 'fullTicketQualification': False,
        'nativeAotCompilationAttempted': False}
    stage = 'normal-capture-of-diagnostic-fixture'
    try:
        app, captured = fixture.prepare(output / 'project', output / 'outside', tools_directory,
            poll_prefetch_diagnostic=True)
        require(captured['originalLibraryAndFeedRemoved'] and captured['cases'] == ['poll-prefetch']
            and captured['librarySourceDigest'] == materials[FIXTURE]['sha256'],
            'poll-prefetch-captured-exact-fixture')
        record['capture'] = captured; write_json(output / 'capture.json', captured)
        source = inventory(snapshot(app)); stage = 'fresh-offline-native-aot'; record['nativeAotCompilationAttempted'] = True
        artifact = build(app, output / 'build', native['capsule_contracts'], native['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric', tools=tools_directory, offline=True)
        require(read_file(artifact / 'source-inputs.json') == source
            and read_file(artifact / 'recipe-inputs.json') == recipe_inputs(artifact),
            'poll-prefetch-exact-captured-source-and-recipe')
        built = build_evidence(artifact, aggregate=True); port = built['taskWaitPort']
        require(port['aggregateTaskWait']['patch'] == VARIANTS[variant][0], 'poll-prefetch-exact-corelib-variant')
        record['freshBuild'] = built
        stage = 'one-signed-original-node-observation'
        observed = node.run(artifact, native, output / 'node', expected=VARIANTS[variant][1])
        require(observed['status'] == 'passed' and len(observed['attempts']) == 1
            and observed['nodeShutdown']['reaped'] and observed['nodeShutdown']['record']['clean'],
            'poll-prefetch-signed-observation-and-cleanup')
        require(products.verify_prepared(native_directory) == compiled and current_materials(native_directory) == source_materials
            and source_identity(ROOT) == current_native and runtime_inputs(ROOT) == runtime
            and read_file(tools_directory / 'runtime-inputs.json') == runtime
            and installation == {name: file_identity(tools_directory / name, 16 * 1024**2) for name in installation}
            and materials == {name: file_identity(ROOT / name) for name in MATERIALS}
            and inventory(snapshot(app)) == source and git('rev-parse', 'HEAD') == expected_head
            and not git('status', '--porcelain'), 'poll-prefetch-final-source-and-native-identities')
        record.update(status='passed', result=VARIANTS[variant][1],
            nodeReceipt=file_identity(output / 'node/qualified.json'))
        write_json(output / 'qualified.json', record); return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        write_json(output / 'FAILED.json', record); raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('native', 'tools', 'output'): parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--variant', choices=tuple(VARIANTS), required=True)
    parser.add_argument('--expected-head', required=True)
    args = parser.parse_args()
    print(qualify(args.native, args.tools, args.output, variant=args.variant, expected_head=args.expected_head)['status'])
