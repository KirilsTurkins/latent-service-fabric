"""Assemble a focused installed Rust recipe from authenticated existing products.

No native, backend or guest compilation occurs here. This is not a released
frontend archive or a replacement for the complete distribution/SBOM builder.
"""
from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tomllib

from tools import dev_tool_distribution as distribution
from tools import dev_rust_http_runtime as installed
from tools import activation_stack_native_products as products
from tools import rust_wasi_http_inputs as runtime
from tools.build_observation import build_environment, resolve_tools
from tools.build_process import run_bounded_result
from tools.dev_distribution import file_digest
from tools.dev_guest_tools import ZIG_BYTES, ZIG_SHA256
from tools.dev_workflow import tool_inventory
from tools.dev_workflow.common import HOST_ABI
from tools.activation_stack_native_source import assert_current
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_rust_capsules import source_identity
from tools.rust_capsule_project import ROOT, fresh, read_file, read_json, write_json

MATERIALS = ('tools/rust_wasi_http_installed_inputs.py', 'tools/dev_tool_distribution.py',
    'tools/activation_stack_native_products.py', 'tools/activation_stack_native_source.py',
    'tools/sdk_native_products_reader.py', 'tools/java_replay_materials.py',
    'tools/rust_wasi_http_installed_build.py',
    'tools/dev_rust_http_runtime.py', 'tools/dev_guest_recipe.py', 'tools/dev_guest_tools.py',
    'tools/dev_distribution.py', 'tools/dev_workflow/tool_inventory.py',
    'tools/dev_workflow/paths.py', 'tools/dev_workflow/common.py')


def loaded_sources():
    names=set()
    for module in tuple(sys.modules.values()):
        filename=getattr(module,'__file__',None)
        if type(filename) is not str:
            continue
        path=Path(filename).resolve()
        if path.suffix=='.py' and path.is_relative_to(ROOT):
            names.add(path.relative_to(ROOT).as_posix())
    require(len(names)<=4096,'rust-http-installed-loaded-helper-count-bound')
    return names


def inventory_descriptor(payload, value):
    return {'language': 'rust', 'hostAbi': HOST_ABI,
        'template': {'ownerIssue': 544, 'revision': value['sourceCommit']},
        'build': {'inventory': {'path': 'guest-tools.json',
            'sha256': file_digest(payload/'guest-tools.json')[0]}, 'tools': []}}


def native_evidence(native_directory):
    original = products.verify_prepared(native_directory)
    proof = assert_current(ROOT)
    require(products.SOURCE == proof['compiledSourceRevision'],
        'rust-http-installed-exact-native-origin')
    source_inputs = read_json(native_directory/'source-inputs.json')
    require(source_inputs['native'] == proof['compiledNativeSource'],
        'rust-http-installed-authenticated-compiled-native-identity')
    auxiliary = {name: file_identity(ROOT/name) for name in source_inputs['materials']}
    require(type(source_inputs['materials']) is dict and len(auxiliary) == 134
        and auxiliary == source_inputs['materials'],
        'rust-http-installed-current-native-auxiliary-exact')
    return original, proof, auxiliary, products.native_products(native_directory)


def prepare(native_directory: Path, adapter_directory: Path, zig_archive: Path,
            python_prefix: Path, output: Path) -> dict:
    require(sys.platform == 'linux' and platform.machine() == 'x86_64'
        and sys.version_info[:3] == (3, 13, 5), 'rust-http-installed-linux-python3135')
    output = Path(output).absolute()
    require(ROOT != output and ROOT not in output.parents and output not in ROOT.parents,
        'rust-http-installed-output-outside-checkout')
    for path in (native_directory, adapter_directory, zig_archive, python_prefix):
        path = Path(path).resolve(strict=True)
        require(output != path and output not in path.parents and path not in output.parents,
            'rust-http-installed-output-separated-from-inputs')
    original_native, native_proof, auxiliary, native = native_evidence(native_directory)
    before_native = native_proof['consumerNativeSource']
    original_binaries = {name: file_identity(path, 512*1024**2) for name, path in native.items()}
    tools, _ = resolve_tools(tomllib.loads(read_file(ROOT/'tools/toolchain.toml').decode()),
        ROOT, build_environment(output))
    prepared = runtime.Prepared(adapter_directory, tools['rustc'], tools['wasm-tools'])
    prepared.check()
    original_adapter = {name: file_identity(adapter_directory/name, 64*1024**2)
        for name in installed.MEMBERS}
    require(file_digest(zig_archive) == ('sha256:'+ZIG_SHA256, ZIG_BYTES),
        'rust-http-installed-exact-zig-archive')
    bindgen = shutil.which('wit-bindgen')
    require(bindgen is not None, 'rust-http-installed-binding-tool-required')
    bindgen = Path(bindgen).resolve(strict=True)
    version = run_bounded_result([str(bindgen), '--version'], ROOT, build_environment(output),
        timeout_seconds=10, max_output_bytes=4096)
    require(version.returncode == 0 and version.stdout.strip() == b'wit-bindgen-cli 0.62.0',
        'rust-http-installed-exact-binding-tool')
    selected_tools={**tools,'wit-bindgen':bindgen}
    tool_ids={name:file_identity(path,512*1024**2) for name,path in selected_tools.items()}
    names = dict.fromkeys((*MATERIALS, *runtime.consumer_files(), *sorted(loaded_sources())))
    source = {name: file_identity(ROOT/name) for name in names}
    require(sum(row['bytes'] for row in source.values())<=16*1024**2,
        'rust-http-installed-source-material-byte-bound')
    output = fresh(output)
    payload = output/'payload'
    payload.mkdir(mode=0o700)
    stage = 'copy-observed-tool-distributions'
    record = {'schemaVersion': 'latent.rust.wasi-http.installed-inputs.v1',
        'status': 'incomplete', 'assemblySource': subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=10).decode().strip(),
        'nativeProducer': original_native, 'compiledNativeSource': native_proof['compiledNativeSource'],
        'consumerNativeSource': before_native, 'nativeSourceCompatibility': native_proof,
        'allNativeAuxiliaryRowsByteExact': True,
        'adapterInputs': original_adapter,
        'observedCompilerBinaries': tool_ids,
        'source': source, 'nativeProductsBuilt': 0, 'backendComponentsBuilt': 0,
        'guestComponentsBuilt': 0, 'publisherAuthenticated': False,
        'fullDeveloperArchiveQualification': False, 'signedRuntimeQualification': False}
    try:
        executables = distribution.python(payload, python_prefix)
        executables.update(distribution.rust(payload, tools['rustc'].parents[3]))
        for source_path, target in ((tools['wasm-tools'], 'wasm-tools'), (bindgen, 'wit-bindgen'),
                (native['capsule_contracts'], 'capsule-contracts'),
                (native['capsule_authoring'], 'capsule-test-signer')):
            distribution.copy(source_path, payload/'sdk/bin'/target)
            executables.add('sdk/bin/'+target)
        distribution.copy(zig_archive, payload/'sdk/zig.tar.xz')
        destinations={'cargo':'sdk/rust/bin/cargo','rustc':'sdk/rust/bin/rustc',
            'wasm-tools':'sdk/bin/wasm-tools','wit-bindgen':'sdk/bin/wit-bindgen'}
        require(tool_ids=={name:file_identity(payload/path,512*1024**2)
            for name,path in destinations.items()}, 'rust-http-installed-exact-observed-tool-copies')
        # Normal locked base SDK cache, captured as bytes; no resolver runs here.
        cargo_home = Path(os.environ.get('CARGO_HOME', str(Path.home()/'.cargo')))
        distribution.registry(payload, cargo_home)
        stage = 'original-prepared-runtime-and-current-consumer-recipe'
        executables.update(installed.prepare(payload, adapter_directory))
        distribution.recipe(payload, 'rust', rust_http_runtime=True)
        write_json(payload/'sdk/native-compiler-origin.json', {
            'assemblySource': record['assemblySource'], 'compiledSource': products.SOURCE,
            'producer': original_native, 'copiedProducts': {
                'sdk/bin/capsule-contracts': original_binaries['capsule_contracts'],
                'sdk/bin/capsule-test-signer': original_binaries['capsule_authoring']},
            'nativeCompilationPerformed': False})
        for name in executables:
            (payload/name).chmod(0o700)
        stage = 'complete-authenticated-installed-inventory'
        value = distribution.compiler_inventory(payload, record['assemblySource'], 'rust')
        descriptor = inventory_descriptor(payload, value)
        require(tool_inventory.check(payload, descriptor, 'linux-x86_64') == value['identity'],
            'rust-http-installed-complete-inventory')
        require(read_file(payload/installed.DIRECTORY/runtime.RECEIPT) == prepared.material(),
            'rust-http-installed-original-adapter-receipt')
        require(all(read_file(payload/'recipe'/name) == body
            for name, body in runtime.consumer_files().items()), 'rust-http-installed-current-consumer-source')
        require(original_native == products.verify_prepared(native_directory)
            and original_adapter == {name: file_identity(adapter_directory/name, 64*1024**2)
                for name in installed.MEMBERS}
            and before_native == source_identity(ROOT)
            and auxiliary == {name: file_identity(ROOT/name) for name in auxiliary}
            and loaded_sources()<=set(names)
            and tool_ids=={name:file_identity(path,512*1024**2) for name,path in selected_tools.items()}
            and file_digest(zig_archive)==file_digest(payload/'sdk/zig.tar.xz')==('sha256:'+ZIG_SHA256,ZIG_BYTES)
            and source == {name: file_identity(ROOT/name) for name in names}
            and original_binaries == {name: file_identity(path, 512*1024**2) for name, path in native.items()},
            'rust-http-installed-original-inputs-unchanged')
        record.update(status='staged', toolInventory=file_identity(payload/'guest-tools.json'),
            inventoryIdentity=value['identity'], inventoryFiles=len(value['files']),
            installedEntry='recipe/tools/dev_guest_recipe.py',
            installedRecipeQualification=False, defaultTemplatesRebuilt=False,
            compilerNetwork='existing captured compiler namespace has no network')
        write_json(output/'STAGED.json', record)
        return record
    except BaseException:
        record.update(status='failed', stage=stage)
        try:
            write_json(output/'FAILED.json', record)
        except OSError:
            pass
        raise
