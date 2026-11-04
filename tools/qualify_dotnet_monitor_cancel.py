"""Compile and sign two ordinary Task and monitor witnesses on exact current products."""
from __future__ import annotations
import argparse
from pathlib import Path, PurePosixPath
import subprocess
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import dotnet_task_runtime_fixture as fixture, dotnet_monitor_cancel_node as node
from tools import dotnet_monitor_cancel_fixture as witness
from tools.dotnet_guest.build import build
from tools.dotnet_guest.compiler import runtime_inputs
from tools.java_replay_materials import git_source_identity
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.qualify_dotnet_finite_waits import build_evidence, recipe_inputs
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, snapshot, write_json

ORIGINAL_CASES = ('run', 'when-all', 'thread-pool', 'scheduler', 'error', 'cancel',
    'context', 'suppressed-context', 'delay', 'cancel-after', 'nested', 'monitor',
    'timer-periodic-context', 'timer-change', 'timer-dispose', 'timer-self-dispose-drain')
MATERIALS = tuple(sorted({
    '.github/workflows/dotnet-monitor-cancel.yml',
    'tools/dotnet_task_runtime_fixture.py', 'tools/dotnet_task_runtime_probe.py', 'tools/dotnet_monitor_cancel_fixture.py',
    'tools/dotnet_monitor_cancel_node.py', 'tools/qualify_dotnet_monitor_cancel.py',
    'tools/admit_dotnet_monitor_cancel_evidence.py', 'tools/qualify_dotnet_finite_waits.py',
    'tools/dotnet_standard_http_node.py', 'tools/wait_capsule_audit_idle.py',
    'tools/guest_runtime_grants.py', 'tools/resource_tenant_node.py',
    'tools/rust_capsule_node.py', 'tools/sdk_provider_scenario.py',
    'tools/qualify_resource_tenants.py', 'tools/phase2_operator_scenario.py',
    'tools/phase3_resource_identity.py', 'tools/phase3_resource_os.py',
    'tools/wasmtime_48_0_8_678b_native_products.py', 'tools/sdk_native_products_reader.py',
    'tools/java_replay_materials.py', 'tools/dotnet_guest/build.py',
}))


def current_materials(native_directory):
    rows = read_json(native_directory / 'native-products.json')['materials']
    require(type(rows) is dict and len(rows) == 135, 'monitor-cancel-native-material-count')
    for name, expected in rows.items():
        require(type(name) is str, 'monitor-cancel-native-material-path')
        path = PurePosixPath(name)
        require(not path.is_absolute() and all(part not in ('', '.', '..') for part in path.parts),
            'monitor-cancel-native-material-path')
        value = ROOT.joinpath(*path.parts)
        require(not value.is_symlink() and all(not ROOT.joinpath(*path.parts[:i]).is_symlink()
            for i in range(1, len(path.parts))) and file_identity(value) == expected,
            'monitor-cancel-current-native-material')
    return rows


def qualify(native_directory, tools_directory, output, *, expected_head):
    # This reader must be the actual verified producer, never a refusal stub.
    from tools import wasmtime_48_0_8_678b_native_products as products
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'monitor-cancel-linux-python313')
    require(type(expected_head) is str and len(expected_head) == 40
        and all(c in '0123456789abcdef' for c in expected_head), 'monitor-cancel-exact-source')
    require(fixture.CASES == ORIGINAL_CASES and witness.CASES == node.MODES,
        'monitor-cancel-original-and-two-new-cases')
    native_directory, tools_directory = (Path(path).resolve(strict=True) for path in (native_directory, tools_directory))
    output = Path(output).absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents
        and all(output != path and output not in path.parents and path not in output.parents
            for path in (native_directory, tools_directory)), 'monitor-cancel-separated-inputs')
    output = fresh(output)
    record = {'schemaVersion': 'latent.dotnet.monitor-cancel.qualification.v1', 'status': 'incomplete',
        'sourceCommit': expected_head, 'selectedModes': list(node.MODES),
        'theseTwoCasesOnly': True, 'fullTicketQualification': False,
        'nativeAotCompilationAttempted': False}
    stage = 'exact-source-and-native-authentication'
    try:
        def git(*args):
            return subprocess.check_output(['git', *args], cwd=ROOT, timeout=20).decode().strip()
        require(git('rev-parse', 'HEAD') == expected_head and not git('status', '--porcelain'),
            'monitor-cancel-clean-exact-source')
        compiled = products.verify_prepared(native_directory)
        native = products.native_products(native_directory)
        require(set(native) == {'latent', 'latentd', 'package', 'capsule_contracts', 'capsule_authoring'},
            'monitor-cancel-exact-five-native-products')
        for path in native.values(): path.chmod(0o700)
        current_native = source_identity(ROOT)
        require(current_native == git_source_identity(products.SOURCE), 'monitor-cancel-current-native-source')
        native_materials = current_materials(native_directory)
        runtime = runtime_inputs(ROOT)
        require(read_file(tools_directory / 'runtime-inputs.json') == runtime,
            'monitor-cancel-source-matched-compiler-installation')
        installation = {name: file_identity(tools_directory / name, 16 * 1024**2)
            for name in ('INSTALL-COMPLETE.json', 'runtime-inputs.json', 'wasi-sdk.json')}
        materials = {name: file_identity(ROOT / name) for name in MATERIALS}
        record.update(materials=materials, nativeProducts=compiled, nativeSource=current_native,
            runtimeInputs={'sha256': digest(runtime), 'bytes': len(runtime)}, installation=installation)
        stage = 'normal-capture-of-original-task-library'
        app, captured = fixture.prepare(output / 'project', output / 'outside', tools_directory, monitor_cancel=True)
        require(captured['originalLibraryAndFeedRemoved'] and captured['cases'] == list(witness.CASES)
            and captured['originalFiles'].get('Library.cs') == digest(witness.library_source(fixture.LIBRARY_SOURCE).encode('utf-8')),
            'monitor-cancel-exact-captured-cases-and-source')
        record['capture'] = captured
        write_json(output / 'capture.json', captured)
        source = inventory(snapshot(app)); stage = 'fresh-offline-native-aot'
        record['nativeAotCompilationAttempted'] = True
        artifact = build(app, output / 'build', native['capsule_contracts'], native['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric', tools=tools_directory, offline=True)
        require(read_file(artifact / 'source-inputs.json') == source
            and read_file(artifact / 'recipe-inputs.json') == recipe_inputs(artifact),
            'monitor-cancel-exact-captured-source-and-recipe')
        record['freshBuild'] = build_evidence(artifact, aggregate=True)
        stage = 'two-signed-original-node-observations'
        observed = node.run(artifact, native, output / 'node')
        require(observed['status'] == 'passed'
            and [row['mode'] for row in observed['attempts']] == list(node.MODES)
            and all('retirement' in row for row in observed['attempts'])
            and observed['nodeShutdown']['reaped'] and observed['nodeShutdown']['record']['clean'],
            'monitor-cancel-signed-observations-and-cleanup')
        require(products.verify_prepared(native_directory) == compiled and current_materials(native_directory) == native_materials
            and source_identity(ROOT) == current_native and runtime_inputs(ROOT) == runtime
            and read_file(tools_directory / 'runtime-inputs.json') == runtime
            and installation == {name: file_identity(tools_directory / name, 16 * 1024**2) for name in installation}
            and materials == {name: file_identity(ROOT / name) for name in MATERIALS}
            and inventory(snapshot(app)) == source and git('rev-parse', 'HEAD') == expected_head
            and not git('status', '--porcelain'), 'monitor-cancel-final-source-and-native-identities')
        record.update(status='passed', nodeReceipt=file_identity(output / 'node/qualified.json'))
        write_json(output / 'qualified.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        write_json(output / 'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('native', 'tools', 'output'): parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--expected-head', required=True)
    args = parser.parse_args()
    print(qualify(args.native, args.tools, args.output, expected_head=args.expected_head)['status'])
