"""Compile one ordinary HTTP guest using only installed maintained recipe tools.

This verifies the existing installed compiler entry, not release publication,
publisher authentication or the frontend watch/deploy lifecycle. Native products
and the prepared backend have separate exact producer/source observations.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import tomllib

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import rust_wasi_http_installed_build as compiler
from tools import rust_wasi_http_installed_inputs as inputs
from tools import rust_wasi_http_installed_node as node
from tools import rust_wasi_http_runtime_fixture as fixture
from tools import rust_wasi_http_inputs as runtime
from tools import rust_wasi_http_current_backend as backend
from tools.build_observation import build_environment, resolve_tools
from tools.build_process import run_bounded_result
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_rust_wasi_http_runtime import verify_build
from tools.rust_capsule_project import ROOT, fresh, inventory, read_file, read_json, snapshot, write_json

MATERIALS = ('.github/workflows/rust-wasi-http-installed.yml', 'tools/qualify_rust_wasi_http_installed.py', 'tools/qualify_rust_wasi_http_runtime.py',
    'tools/build_dev_guest_tools.py', 'tools/install_guest_bindgen.py',
    'tools/rust_wasi_http_runtime_fixture.py', *inputs.MATERIALS, *node.MATERIALS, *backend.MATERIALS)


def qualify(native_directory, adapter_directory, zig_archive, python_prefix, output, *, retained_backend):
    require(sys.platform == 'linux' and sys.version_info[:3] == (3, 13, 5),
        'installed-rust-owning-linux-python3135')
    output = Path(output).absolute()
    selected = [Path(path).resolve(strict=True)
        for path in (native_directory, adapter_directory, zig_archive, python_prefix)]
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents
        and all(path != output and output not in path.parents and path not in output.parents for path in selected),
        'installed-rust-owning-separated-output')
    native_directory, adapter_directory, zig_archive, python_prefix = selected
    output = fresh(output)
    deadline = time.monotonic()+1100
    record = {'schemaVersion': 'latent.rust.wasi-http.installed.v1', 'status': 'incomplete',
        'source': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=10).decode().strip(),
        'entry': 'recipe/tools/dev_guest_recipe.py', 'publisherAuthenticated': False,
        'fullReleasedFrontendQualified': False, 'nativeProductsBuilt': 0, 'backendComponentsBuilt': 0,
        'guestComponentsCompiled': 0, 'installedRecipeQualification': False}
    materials = {name: file_identity(ROOT/name)
        for name in dict.fromkeys((*MATERIALS, *runtime.consumer_files()))}
    record['materials'] = materials
    stage = 'normal-ordinary-source-capture'
    try:
        record['adapterProducerOrigin'] = backend.verify(retained_backend, adapter_directory)
        tools, _ = resolve_tools(tomllib.loads(read_file(ROOT/'tools/toolchain.toml').decode()),
            ROOT, build_environment(output))
        app, outside, specs = fixture.prepare(output/'source', secrets.token_hex(8))
        record['capture'] = fixture.capture(app, outside, specs, tools['cargo'])
        captured = inventory(snapshot(app))
        stage = 'source-bound-installed-compiler-assembly'
        assembled = inputs.prepare(native_directory, adapter_directory, zig_archive, python_prefix, output/'staged')
        record['assembly'] = file_identity(output/'staged/STAGED.json', 16*1024**2)
        payload = output/'staged/payload'
        inventory_before = file_identity(payload/'guest-tools.json')
        work = output/'installed-execution'
        work.mkdir(mode=0o700)
        control = work/'control.py'
        control.write_bytes(read_file(ROOT/'tools/rust_wasi_http_installed_build.py'))
        sandbox = shutil.which('bwrap')
        require(sandbox is not None, 'installed-rust-outer-namespace-required')
        sandbox = Path(sandbox).resolve(strict=True)
        sandbox_before = file_identity(sandbox)
        command = compiler.namespace_command(sandbox, payload, app, work, control,
            assembled['assemblySource'], inventory_before['sha256'])
        record['installedCommand'] = {'arguments': command, 'sandbox': sandbox_before,
            'control': file_identity(control), 'network': 'unshare-all',
            'checkoutTreeMounted': False, 'readonlyInputs': [str(payload), str(app)], 'ownedOutput': str(work)}
        write_json(output/'installed-command.json', record['installedCommand'])
        stage = 'one-installed-entry-guest-compile'
        result = run_bounded_result(command, output, build_environment(output),
            timeout_seconds=min(930, deadline-time.monotonic()), max_output_bytes=4*1024**2)
        for suffix, body in (('stdout', result.stdout), ('stderr', result.stderr)):
            (output/('installed.'+suffix)).write_bytes(body)
        record['installedCommand'].update(exitCode=result.returncode,
            stdout=file_identity(output/'installed.stdout'), stderr=file_identity(output/'installed.stderr'))
        require(result.returncode == 0, 'installed-rust-maintained-recipe-failed')
        execution = read_json(work/'installed-build.json', 16*1024**2)
        require(execution['status'] == 'passed' and execution['entry'] == record['entry']
            and execution['assemblySource'] == assembled['assemblySource']
            and execution['guestComponentsCompiled'] == 1
            and execution['nativeProductsBuilt'] == execution['backendComponentsBuilt'] == 0,
            'installed-rust-exact-normal-compiler-result')
        record['installedBuild'] = file_identity(work/'installed-build.json', 16*1024**2)
        artifact = work/'approved/output'
        prepared = runtime.Prepared(payload/'sdk/rust-http-runtime', payload/'sdk/rust/bin/rustc',
            payload/'sdk/bin/wasm-tools')
        record['build'] = verify_build(artifact, work/'approved/app', captured, execution['approval'], prepared)
        require(read_json(artifact/'BUILD-COMPLETE.json')['packageAssembled'] is False,
            'installed-rust-controller-packaging-required')
        record['guestComponentsCompiled'] = 1
        stage = 'signed-installed-two-client-denial-retirement-fresh'
        native = inputs.products.native_products(native_directory)
        for path in native.values():
            path.chmod(0o700)
        observed = node.run(artifact, native, output/'node', deadline=deadline)
        require(observed['status'] == 'passed' and observed['guestExecutions'] == 4
            and observed['invocationAttempts'] == 6 and observed['preEntryRefusalsCount'] == 2
            and observed['peerContacts'] == 4, 'installed-rust-all-finite-cases-required')
        record['node'] = file_identity(output/'node/qualification.json', 16*1024**2)
        prepared.check()
        runtime.Prepared(adapter_directory, tools['rustc'], tools['wasm-tools']).check()
        from tools.dev_workflow import tool_inventory
        descriptor = inputs.inventory_descriptor(payload, read_json(payload/'guest-tools.json'))
        require(assembled['inventoryIdentity'] == tool_inventory.check(payload, descriptor, 'linux-x86_64')
            and inventory_before == file_identity(payload/'guest-tools.json')
            and sandbox_before == file_identity(sandbox)
            and assembled['nativeProducer'] == inputs.products.verify_prepared(native_directory)
            and assembled['adapterInputs'] == {name: file_identity(adapter_directory/name, 64*1024**2)
                for name in inputs.installed.MEMBERS}
            and assembled['source'] == {name: file_identity(ROOT/name) for name in assembled['source']}
            and materials == {name: file_identity(ROOT/name) for name in materials}
            and captured == inventory(snapshot(app)) and time.monotonic() < deadline,
            'installed-rust-final-full-inventory-source-and-deadline')
        record.update(status='passed', installedRecipeQualification=True, signedQualification=True,
            guestExecutions=4, invocationAttempts=6, preEntryRefusals=2, peerContacts=4,
            fullTicketQualification=False)
        write_json(output/'qualification.json', record)
        return record
    except BaseException:
        record.update(status='failed', stage=stage)
        try:
            write_json(output/'FAILED.json', record)
        except OSError:
            pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('native-products', 'http-runtime', 'zig-archive', 'python-prefix', 'output', 'retained-backend'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    print(qualify(args.native_products, args.http_runtime, args.zig_archive, args.python_prefix, args.output,
        retained_backend=args.retained_backend)['status'])
