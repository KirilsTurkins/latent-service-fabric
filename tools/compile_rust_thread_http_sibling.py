"""Compile the fixed combined ordinary HTTP and ThreadPool source for structural diagnosis.

The production component selector remains closed. This explicit compiler-only
programme reuses its original capture, Prepared, isolation and approval pieces;
it retains compiler/source proof output without writing BUILD-COMPLETE or
signing, invoking or enabling a runtime.
"""
from __future__ import annotations

from pathlib import Path
import copy
import io
import re
import shutil
import tarfile
import tempfile
import time
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import rust_owned_thread_fixture as fixture, rust_standard_logging_inputs as standard
from tools.compile_rust_owned_thread_inputs import git as git_read
from tools import rust_capsule_build as builder, rust_owned_thread_component as component
from tools import rust_standard_thread_capture as port
from tools import rust_wasi_http_inputs as http_inputs
from tools.rust_wasi_http_compose import compose as compose_http
from tools import rust_thread_object_graph as objects, rust_thread_callback_paths as callbacks
from tools import rust_thread_canonical_results as results
from tools.application_dependencies import prepare, verify_inputs
from tools.application_dependency_approval import approve, request
from tools.build_observation import build_environment, file_identity, resolve_tools
from tools.captured_compiler_isolation import Isolation
from tools.dev_workflow.common import require
from tools.guest_dependency_inputs import capture_source
from tools.rust_application_dependencies import configure
from tools.rust_capsule_project import (
    canonical, checked_path, decode_json, digest, fresh, inventory, read_file, snapshot, write_json,
    sdk_files, host_projection_inputs,
)

RECIPE = tuple(dict.fromkeys(('tools/compile_rust_thread_http_sibling.py',
    'tools/compile_rust_owned_thread_inputs.py',
    'tools/rust_thread_http_sibling_contracts.py',
    '.github/workflows/rust-http-thread-composition-diagnostic.yml',
    'tools/rust_thread_http_sibling_fixture.py', 'tools/rust_wasi_http_runtime_fixture.py',
    'tools/rust_wasi_http_fixture.py', 'tools/rust_wasi_http_profile.py',
    'tools/rust_wasi_http_inputs.py', 'tools/rust_wasi_http_compose.py',
    'tools/install_guest_bindgen.py', 'tools/toolchain.toml',
    'tools/toolchain-smoke/examples/tutorial_greeting/component.rs',
    'tools/toolchain-smoke/examples/tutorial_greeting/world.wit',
    'tools/rust_thread_object_graph.py', 'tools/rust_thread_callback_paths.py',
    'tools/rust_thread_canonical_results.py',
    *builder.selected_recipe(), *standard.source_build_inputs(standard.THREAD), *fixture.RECIPE,
    *sdk_files(), *host_projection_inputs())))
MAX_CORE = 8 * 1024 * 1024
MAX_EXPANDED_SOURCE = 128 * 1024 * 1024
MAX_SOURCE_ARCHIVE = 32 * 1024 * 1024
MAX_EXECUTOR_OBJECT = 8 * 1024 * 1024

# Used only by this unadmitted compiler diagnostic. The maintained HTTP and
# .NET composer selection remains the separately authenticated 0.10.1 input.
# The later tool can parse the canonical threading opcode emitted by the
# captured application; successful parsing alone is not component admission.
DIAGNOSTIC_COMPOSER_SIZE = 22917648
DIAGNOSTIC_COMPOSER_DIGEST = 'sha256:83259349b630f79a60490322b068e7ad2dba784720b0d467decccc0aecc743b5'
HTTP_ASYNC_FEATURES = 'cm-async,cm-async-stackful,cm-more-async-builtins'
THREAD_PREVIEW_FEATURES = 'cm-threading,' + HTTP_ASYNC_FEATURES


class DiagnosticThreadingValidation:
    """Enable threading only for this unadmitted combined-graph validation.

    The maintained HTTP builder keeps its original validation profile. Refuse
    a changed command shape rather than silently adjusting an unrelated call.
    """
    def __init__(self, commands):
        self.commands = commands
        self.validated = False

    def __getattr__(self, name):
        return getattr(self.commands, name)

    def run(self, stage, *args, **kwargs):
        if stage == 'rust-http-final-validation':
            require(not self.validated and len(args) == 5 and args[1] == 'validate'
                    and args[-2:] == ('--features', HTTP_ASYNC_FEATURES),
                    'rust-http-thread-diagnostic-validation-shape')
            result = self.commands.run(stage, *args[:-1], THREAD_PREVIEW_FEATURES, **kwargs)
            self.validated = True
            return result
        return self.commands.run(stage, *args, **kwargs)


def record_diagnostic_composition(output: Path, composition: dict, composer: dict):
    """Retain the composer's original receipt and a separate diagnostic view."""
    receipt = output / 'rust-http-composition.json'
    require(type(composition) is dict and decode_json(read_file(receipt)) == composition
            and not {'diagnosticComposer', 'diagnosticOnly', 'diagnosticValidationFeatures'} & composition.keys(),
            'rust-http-thread-composition-receipt-mismatch')
    diagnostic = {**composition, 'diagnosticComposer': composer, 'diagnosticOnly': True,
                  'diagnosticValidationFeatures': THREAD_PREVIEW_FEATURES}
    write_json(output / 'rust-http-composition-diagnostic.json', diagnostic)
    return diagnostic


class DiagnosticHttpComposition:
    """Bind one fixed diagnostic composer to an already-verified adapter.

    No caller selects a production SDK tool or supplies component authority.
    The original Prepared adapter and its receipt remain independently checked.
    """
    def __init__(self, prepared, composer):
        self.prepared = prepared
        self.composer = checked_path(composer)
        self.adapter = prepared.adapter
        self.check()

    def check(self):
        self.prepared.check()
        require(self.adapter == self.prepared.adapter, 'rust-http-thread-diagnostic-adapter-drift')
        require(file_identity(self.composer, 'diagnostic-composer', DIAGNOSTIC_COMPOSER_SIZE) == {
            'name': 'diagnostic-composer', 'digest': DIAGNOSTIC_COMPOSER_DIGEST,
            'size': DIAGNOSTIC_COMPOSER_SIZE}, 'rust-http-thread-diagnostic-composer-drift')

    def material(self):
        self.check()
        return self.prepared.material()


def cargo_records(raw: bytes):
    require(len(raw) <= 4 * 1024 * 1024, 'rust-thread-app-cargo-output-bound')
    lines = raw.splitlines()
    require(len(lines) <= 8192, 'rust-thread-app-cargo-record-bound')
    finished = False
    for line in lines:
        row = decode_json(line)
        require(isinstance(row, dict) and not finished, 'rust-thread-app-cargo-terminal')
        if row.get('reason') == 'build-finished':
            require(row.get('success') is True, 'rust-thread-app-build-failed')
            finished = True
        yield row
    require(finished, 'rust-thread-app-cargo-missing-terminal')


def emitted_core(raw: bytes, work: Path, target: Path, name: str) -> Path:
    selected = []
    for row in cargo_records(raw):
        if row.get('reason') != 'compiler-artifact' or row.get('target', {}).get('name') != name:
            continue
        require(row['target'].get('crate_types') == ['cdylib']
                and row.get('profile', {}).get('test') is False
                and row.get('manifest_path') == str(work / 'Cargo.toml')
                and isinstance(row.get('filenames'), list) and len(row['filenames']) <= 16,
                'rust-thread-app-emitted-target')
        for value in row['filenames']:
            require(isinstance(value, str), 'rust-thread-app-emitted-path')
            path = checked_path(Path(value))
            if path.suffix == '.wasm':
                require(path.is_relative_to(target), 'rust-thread-app-core-outside-target')
                selected.append(path)
    require(len(selected) == 1, 'rust-thread-app-core-emission-closure')
    return selected[0]


def emitted_executor(raw: bytes, work: Path, target: Path, package: dict):
    """Attribute one actual target rlib to the already verified native capture."""
    metadata = package['metadata']
    require(package['format'] == 'directory'
            and metadata['package'] == port.profile.EXECUTOR
            and metadata['version'] == port.profile.EXECUTOR_VERSION
            and metadata['vendorChecksum']['package'] == port.profile.EXECUTOR_ARCHIVE_SHA256,
            'rust-thread-app-authentic-executor-capture')
    manifest = checked_path(work / package['mount'] / 'Cargo.toml')
    source = checked_path(manifest.parent / 'src/lib.rs')
    directory = target / standard.clock.TARGET / 'release/deps'
    selected = []
    for row in cargo_records(raw):
        if row.get('reason') != 'compiler-artifact' or row.get('target', {}).get('name') != 'futures_executor':
            continue
        kind = row['target']
        features = row.get('features')
        require(isinstance(row.get('package_id'), str)
                and digest(row['package_id'].encode()) == metadata['nativeIdDigest']
                and row.get('manifest_path') == str(manifest)
                and kind.get('src_path') == str(source)
                and kind.get('kind') == ['lib'] and kind.get('crate_types') == ['lib']
                and kind.get('edition') == '2018'
                and isinstance(features, list) and len(features) <= 64
                and all(isinstance(value, str) for value in features)
                and len(features) == len(metadata['features'])
                and set(features) == set(metadata['features'])
                and row.get('profile', {}).get('test') is False
                and row.get('fresh') is False and row.get('executable') is None
                and isinstance(row.get('filenames'), list) and len(row['filenames']) <= 16,
                'rust-thread-app-executor-emission-attribution')
        for value in row['filenames']:
            require(isinstance(value, str), 'rust-thread-app-executor-emitted-path')
            path = checked_path(Path(value))
            require(path.parent == directory and path.suffix in {'.rlib', '.rmeta'},
                    'rust-thread-app-executor-target-output')
            if path.suffix == '.rlib':
                selected.append((path, row))
    require(len(selected) == 1, 'rust-thread-app-executor-emission-closure')
    return selected[0]


def source_archive(app: Path, output: Path):
    """Retain the actual normal source/capture/CAS, without compiler outputs."""
    paths, rows, total = [], [], 0
    for path in sorted(app.rglob('*')):
        relative = path.relative_to(app)
        if relative.parts[0] == 'target':
            continue
        checked_path(path)
        if path.is_dir():
            continue
        size = path.stat().st_size
        total += size
        paths.append(path)
        rows.append({'path': relative.as_posix(), 'size': size})
        require(len(rows) <= 32768, 'rust-thread-app-retained-source-entry-bound')
    # Keep the complete byte inventory even when expanded-source refusal is
    # necessary. The accepted lock is retained separately before this call.
    manifest = {'files': rows, 'expandedBytes': total, 'digestsComplete': False}
    write_json(output.with_name(output.name + '.sizes.json'), manifest)
    require(total <= MAX_EXPANDED_SOURCE
            and all(row['size'] <= 4 * 1024 * 1024 for row in rows),
            'rust-thread-app-retained-source-bound')
    for path, row in zip(paths, rows, strict=True):
        raw = read_file(path, 4 * 1024 * 1024)
        require(len(raw) == row['size'], 'rust-thread-app-archive-source-mutated')
        row['digest'] = digest(raw)
    manifest['digestsComplete'] = True
    write_json(output.with_name(output.name + '.files.json'), manifest)
    with tarfile.open(output, 'w:gz') as archive:
        for path, row in zip(paths, rows, strict=True):
            raw = read_file(path, 4 * 1024 * 1024)
            require(len(raw) == row['size'] and digest(raw) == row['digest'],
                    'rust-thread-app-archive-source-mutated')
            info = archive.gettarinfo(path, arcname=row['path'])
            require(info.isfile() and info.size == len(raw),
                    'rust-thread-app-archive-source-mutated')
            archive.addfile(info, io.BytesIO(raw))
            require(output.stat().st_size <= MAX_SOURCE_ARCHIVE,
                    'rust-thread-app-source-archive-bound')
    return file_identity(output, 'application-source-and-capture.tar.gz', MAX_SOURCE_ARCHIVE)


def bind_recipe_to_git(expected, files):
    """Bind every current compiler/HTTP recipe byte to the actual checkout."""
    require(type(expected) is str and re.fullmatch('[0-9a-f]{40}', expected) is not None
            and 0 < len(files) <= 256, 'rust-http-thread-expected-source')
    require(git_read('rev-parse', '--verify', 'HEAD').decode().strip() == expected
            and not git_read('status', '--porcelain=v1', '--untracked-files=no'),
            'rust-http-thread-clean-exact-head')
    names = sorted(files)
    raw = git_read('cat-file', '--batch', input=''.join(expected + ':' + name + '\n'
                                                        for name in names).encode())
    offset, total, rows = 0, 0, []
    for name in names:
        end = raw.find(b'\n', offset)
        require(end >= offset, 'rust-http-thread-git-header')
        fields = raw[offset:end].split()
        require(len(fields) == 3 and fields[1] == b'blob' and fields[2].isdigit(),
                'rust-http-thread-git-blob')
        size = int(fields[2]); offset = end + 1; total += size
        require(size <= 4 * 1024 * 1024 and total <= 16 * 1024 * 1024,
                'rust-http-thread-git-source-bound')
        value = raw[offset:offset + size]; offset += size
        require(raw[offset:offset + 1] == b'\n' and value == files[name],
                'rust-http-thread-git-source-preimage')
        offset += 1
        rows.append({'path': name, 'gitBlob': fields[0].decode(),
                     'digest': digest(value), 'size': size})
    require(offset == len(raw), 'rust-http-thread-git-trailing-data')
    return {'head': expected, 'tree': git_read('rev-parse', 'HEAD^{tree}').decode().strip(),
            'files': rows, 'totalBytes': total}


def verify_owned_inputs(report_path, source_path, prepared, context_tool, expected_head):
    report_raw = read_file(report_path, 1024 * 1024)
    source_raw = read_file(source_path, 4 * 1024 * 1024)
    report, source = decode_json(report_raw), decode_json(source_raw)
    require(report.get('schemaVersion') == 'latent.rust.owned-thread-inputs.v1'
            and report.get('status') == 'passed-compiler-inputs-only'
            and report.get('sourceMatchedContextToolBuilt') is True
            and report.get('ownedThreadSysrootBuilt') is True
            and report.get('actualGuestExecuted') is False
            and report.get('ordinaryThreadPoolQualified') is False
            and report.get('contextTool') == file_identity(context_tool, 'rust-context', 32 * 1024 * 1024)
            and report.get('sysrootIdentity') == prepared.value['identity']
            and source.get('head') == expected_head,
            'rust-http-thread-owned-producer-receipt')
    return report_raw, source_raw


def verify_contract_tool(receipt_path, tool, expected_head):
    raw = read_file(receipt_path, 1024 * 1024)
    receipt = decode_json(raw)
    require(receipt.get('schemaVersion') == 'latent.rust.http-thread.contract-tool.v1'
            and receipt.get('status') == 'passed-current-contracts-tool'
            and receipt.get('head') == expected_head
            and receipt.get('source', {}).get('head') == expected_head
            and receipt.get('actualGuestExecuted') is False
            and receipt.get('hostQualified') is False
            and receipt.get('tool') == file_identity(tool, 'contracts-tool', 64 * 1024 * 1024)
            and len(receipt.get('commands', [])) == 1
            and receipt['commands'][0].get('stage') == 'current-contracts-build'
            and receipt['commands'][0].get('exitCode') == 0,
            'rust-http-thread-contract-tool-receipt')
    return raw


def select_http_result(graph, world, public):
    """Reuse result-layout checks only after requiring the real async WIT kind.

    The projection is local to this diagnostic's layout inspection. It does not
    rewrite component bytes, the selected contract or host admission.
    """
    require(type(graph) is dict and type(graph.get('interfaces')) is list
            and len(graph['interfaces']) <= 4096 and type(graph.get('packages')) is list
            and len(graph['packages']) <= 256, 'rust-http-thread-wit-graph-bound')
    projected = copy.deepcopy(graph)
    interface_name, function_name = public.rsplit('#', 1)
    matches = []
    for interface in projected['interfaces']:
        index = interface.get('package')
        if type(index) is not int or not 0 <= index < len(projected['packages']):
            continue
        package = projected['packages'][index]['name']
        base, separator, version = package.partition('@')
        identity = base + '/' + interface['name'] + (separator + version if separator else '')
        if identity == interface_name and function_name in interface['functions']:
            matches.append(interface['functions'][function_name])
    require(len(matches) == 1 and matches[0]['kind'] == 'async-freestanding',
            'rust-http-thread-explicit-async-wit-required')
    matches[0]['kind'] = 'freestanding'
    return results.select_wit_result(projected, world, public)


def run(output: Path, rust_bin: Path, owned_sysroot: Path, context_tool: Path,
        http_runtime: Path, diagnostic_composer: Path, contracts_tool: Path, contracts_receipt: Path,
        owned_report: Path, owned_source: Path, *, expected_head: str, deadline: float):
    require(sys.platform == 'linux', 'rust-thread-app-linux-captured-compiler-required')
    output = fresh(output)
    record = {'schemaVersion': 'latent.rust.http-thread-core-observation.v1',
              'status': 'in-progress', 'stage': 'prepare', 'actualGuestExecuted': False,
              'ordinaryThreadPoolQualified': False, 'privateExecutorGraphAuthenticated': False,
              'canonicalAbiBodiesAuthenticated': False, 'canonicalCreationEnabled': False,
              'standardRuntimeQualified': False, 'normalBuildComplete': False,
              'httpCompositionIncluded': False, 'hostAuthenticated': False,
              'blockedSiblingProgressQualified': False}
    commands = None
    try:
        host_projection = host_projection_inputs()
        rust_bin, context_tool = checked_path(rust_bin), checked_path(context_tool)
        http_runtime, contracts_tool = checked_path(http_runtime), checked_path(contracts_tool)
        contracts_receipt = checked_path(contracts_receipt)
        contracts_receipt_raw = verify_contract_tool(contracts_receipt, contracts_tool, expected_head)
        record['contractsReceiptDigest'] = digest(contracts_receipt_raw)
        context_identity = file_identity(context_tool, 'context-tool', 32 * 1024 * 1024)
        prepared = standard.Prepared(owned_sysroot, rust_bin / 'rustc', standard.THREAD)
        owned_report, owned_source = checked_path(owned_report), checked_path(owned_source)
        owned_material = verify_owned_inputs(owned_report, owned_source, prepared, context_tool, expected_head)
        record['ownedProducerReportDigest'] = digest(owned_material[0])
        record['ownedProducerSourceDigest'] = digest(owned_material[1])
        try:
            component.select(prepared, rust_bin / 'rustc')
        except ValueError as error:
            require(str(error) == 'rust-thread-private-executor-and-canonical-graph-unqualified',
                    'rust-thread-app-production-gate-changed')
        else:
            raise ValueError('rust-thread-app-unqualified-production-gate-open')
        record['normalComponentGateRefused'] = True
        require(time.monotonic() < deadline, 'rust-thread-app-programme-deadline')
        with tempfile.TemporaryDirectory(prefix='lsf-rust-thread-input-') as directory:
            temporary = Path(directory)
            environment = build_environment(temporary)
            remaining = min(600, int(deadline - time.monotonic()))
            require(remaining > 0, 'rust-thread-app-programme-deadline')
            commands = builder.Commands(builder.ROOT, output, environment,
                deadline_seconds=remaining, command_seconds=min(180, remaining))
            record['stage'] = 'normal-source-and-capture'
            capture_root = temporary / 'http-thread-capture'
            app = capture_root / 'application'
            # The normal authored/captured clients and executor remain independent
            # inputs; no executor, transport, authority or budget is injected.
            commands.run('capture-original-application', sys.executable, '-B',
                builder.ROOT / 'tools/rust_thread_http_sibling_fixture.py',
                '--output', capture_root, '--cargo', rust_bin / 'cargo', '--report', output / 'capture.json')
            captured = decode_json(read_file(output / 'capture.json'))
            record['capture'] = captured
            observed = capture_source(app, 'rust')
            files = observed.files
            project, pins = builder.validate_project(files)
            require(standard.selection(project) == standard.THREAD,
                    'rust-thread-app-selected-profile')
            verified = verify_inputs(observed.dependency_root, 'rust')
            require(verified is not None, 'rust-thread-app-original-capture-required')
            port.verify_capture(verified, standard.THREAD)
            runtime = [row for row in verified.lock['artifacts']
                       if row['id'] == captured['runtimeArtifact']]
            require(len(runtime) == 1, 'rust-thread-app-captured-executor-identity')
            source = inventory(files)
            require(captured['sourceDigest'] == digest(source)
                    and captured['publicExport'] == fixture.PUBLIC
                    and captured['postReturnExport'] == fixture.POST
                    and captured['actualGuestExecuted'] is False
                    and captured['ordinaryThreadPoolQualified'] is False,
                    'rust-thread-app-original-capture-receipt')
            (output / 'source-inputs.json').write_bytes(source)
            (output / 'accepted-dependencies.lock.json').write_bytes(verified.lock_bytes)
            (output / 'accepted-dependencies.json').write_bytes(verified.manifest_bytes)
            record['retainedOriginalSource'] = source_archive(app, output / 'application-source-and-capture.tar.gz')
            work = temporary / 'compiler/source'
            work.mkdir(parents=True)
            for name, raw in files.items():
                path = work / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            commands.root = work
            environment.update(CARGO_NET_OFFLINE='true', RUSTUP_AUTO_INSTALL='0',
                CARGO_INCREMENTAL='0', CARGO_HOME=str(temporary / 'cargo-home'),
                CARGO_TARGET_DIR=str(temporary / 'target'), RUSTC=str(rust_bin / 'rustc'),
                RUSTUP_TOOLCHAIN=pins['toolchain']['rust']['toolchain'])
            paths, identities = resolve_tools(pins['toolchain'], work, environment, installed=rust_bin)
            for name in ('wit-bindgen', 'zig', 'sh'):
                value = shutil.which(name, path=environment.get('PATH'))
                require(value is not None, 'rust-thread-app-pinned-build-tool-unavailable')
                paths[name] = checked_path(Path(value).resolve(strict=True))
            # Verify the same explicitly selected HTTP adapter and composer
            # that the maintained builder would use, without granting it.
            prepared_http = http_inputs.Prepared(http_runtime, paths['rustc'], paths['wasm-tools'])
            diagnostic = DiagnosticHttpComposition(prepared_http, diagnostic_composer)
            require(commands.run('rust-http-thread-diagnostic-composer-version', diagnostic.composer,
                                 '--version').strip() == b'wac-cli 0.11.0',
                    'rust-http-thread-diagnostic-composer-version')
            diagnostic.check()
            record['diagnosticComposer'] = file_identity(diagnostic.composer, 'diagnostic-composer',
                                                          DIAGNOSTIC_COMPOSER_SIZE)
            record['sharedSdkComposerChanged'] = False
            paths['contracts-tool'] = contracts_tool
            http_material = prepared_http.material()
            record['httpPreparedReceiptDigest'] = digest(http_material)
            contracts_identity = file_identity(contracts_tool, 'contracts-tool', 64 * 1024 * 1024)
            # These existing compiler tools keep normal builder material
            # limits; the retained owned context executable remains <=32MiB.
            identities.extend(file_identity(paths[n], n) for n in ('wit-bindgen', 'zig', 'sh'))
            identities.extend((contracts_identity, context_identity))
            record['tools'] = identities
            require(commands.run('zig-version', paths['zig'], 'version').decode().strip()
                    == pins['toolchain']['sdk']['zig'], 'rust-thread-app-pinned-zig')
            require(commands.run('bindgen-version', paths['wit-bindgen'], '--version').decode().strip()
                    == 'wit-bindgen-cli ' + pins['toolchain']['contracts']['wit-bindgen-cli'],
                    'rust-thread-app-pinned-bindgen')
            linker = temporary / 'captured-host-linker'
            linker.write_text('#!' + str(paths['sh'])
                + '\nexec "$LSF_CAPTURED_ZIG" cc -target x86_64-linux-gnu.2.39 "$@"\n')
            linker.chmod(0o700)
            environment.update(CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=str(linker),
                LSF_CAPTURED_ZIG=str(paths['zig']), ZIG_GLOBAL_CACHE_DIR=str(temporary / 'zig-global'),
                ZIG_LOCAL_CACHE_DIR=str(temporary / 'zig-local'))
            selected = {name: paths[name] for name in ('cargo', 'rustc', 'wasm-tools', 'wit-bindgen', 'zig')}
            selected.update(shell=paths['sh'], linker=linker)
            isolation = Isolation(temporary, selected, {
                'rust-compiler-and-sysroot': rust_bin.parent,
                'zig-host-linker-and-sysroot': paths['zig'].parent,
                'rust-standard-stdio-sysroot': prepared.root})
            guard = builder.RustEnvironment(environment, isolation)
            write_json(output / 'rust-compiler-inputs.json', isolation.receipt)
            recipe_files = {name: read_file(builder.ROOT / name) for name in RECIPE}
            http_recipe = http_inputs.consumer_files()
            require(all(name not in recipe_files or recipe_files[name] == value
                        for name, value in http_recipe.items()), 'rust-http-thread-recipe-overlap')
            recipe_files.update(http_recipe)
            require(len(recipe_files) <= 256, 'rust-http-thread-recipe-bound')
            recipe = inventory(recipe_files)
            git_recipe = bind_recipe_to_git(expected_head, recipe_files)
            write_json(output / 'recipe-origin.json', git_recipe)
            (output / 'recipe-inputs.json').write_bytes(recipe)
            specification = request(verified, isolation, digest(canonical({
                'sourceSnapshot': digest(source), 'prepared': digest(prepared.raw),
                'recipe': digest(recipe)})))
            approval = approve(verified, isolation, specification['recipeDigest'], digest(canonical(specification)))
            write_json(output / 'executable-input-approval.json', {
                'identity': approval.identity, 'specification': specification,
                'scope': 'explicit-reviewed-SDK-owned-compiler-only-programme'})
            closure = prepare(observed.dependency_root, work, output, 'rust', execution_approval=approval)
            adapted, cargo_inputs = configure(closure, work, Path(environment['CARGO_HOME']))
            write_json(output / 'cargo-inputs.json', cargo_inputs)
            isolation.protect_inputs(work)
            record['bindingDigest'] = builder.binding_check(work, pins, commands, paths['wit-bindgen'])
            record['stage'] = 'one-isolated-offline-original-compile'
            prepared.check()
            from tools.rust_thread_path_remap import source_mapping, APPLICATION
            record['applicationSourcePathRemap'] = source_mapping(work, APPLICATION)
            target_arguments = prepared.arguments(source_root=work)
            record['targetCargoConfiguration'] = target_arguments
            raw = guard.compile(commands, paths['cargo'], [
                'build', '--locked', '--release', '--lib', '--target', 'wasm32-unknown-unknown',
                '--message-format=json', '--verbose', *target_arguments], work)
            prepared.check()
            executable_outputs = builder.RustExecutableOutputs(temporary / 'target', output, approval.identity)
            core_path = emitted_core(raw, work, temporary / 'target', project['name'].replace('-', '_'))
            executor_path, executor_emission = emitted_executor(raw, work, temporary / 'target', runtime[0])
            executor_identity = file_identity(executor_path, 'captured-futures-executor.rlib', MAX_EXECUTOR_OBJECT)
            shutil.copyfile(executor_path, output / 'captured-futures-executor.rlib')
            require(file_identity(output / 'captured-futures-executor.rlib',
                                  'captured-futures-executor.rlib', MAX_EXECUTOR_OBJECT) == executor_identity,
                    'rust-thread-app-executor-object-copy')
            write_json(output / 'executor-object-emission.json', {
                'capturedArtifact': runtime[0]['id'], 'capturedTreeDigest': runtime[0]['treeDigest'],
                'compilerArtifact': executor_emission, 'object': executor_identity,
                'privateExecutorGraphAuthenticated': False, 'runtimeQualified': False})
            record['executorObject'] = executor_identity
            core = read_file(core_path, MAX_CORE)
            (output / 'raw-core.wasm').write_bytes(core)
            record['originalCore'] = file_identity(output / 'raw-core.wasm', 'original-core', MAX_CORE)
            record['actualApplicationCoreCompiled'] = True
            record['stage'] = 'actual-owned-core-transform'
            commands.run('validate-original-core', paths['wasm-tools'], 'validate', output / 'raw-core.wasm')
            record['stage'] = 'live-original-object-and-canonical-observation'
            # These are the actual same-job Prepared libraries and the emitted
            # Cargo package object, not a caller-selected source/hash catalogue.
            libraries = tuple(objects.Library(name, read_file(prepared.directory / name,
                objects.MAX_LIBRARY_BYTES), row['digest']) for name, row in prepared.libraries.items())
            executor_object = read_file(output / 'captured-futures-executor.rlib', MAX_EXECUTOR_OBJECT)
            libraries += (objects.Library('captured-futures-executor.rlib', executor_object,
                                          executor_identity['digest']),)
            extra_roots = []
            for label, raw in objects.archive(executor_object):
                for node in objects.object_nodes(raw, 'captured-futures-executor.rlib/' + label)[0]:
                    if node['kind'] == 0 and node['name'].endswith((
                            '_10ThreadPool3new', '_10ThreadPool14spawn_admitted', '_4Pool12admit_future')):
                        require(len(extra_roots) < 3, 'rust-thread-app-original-default-pool-entry-bound')
                        extra_roots.append(('captured-futures-executor.rlib', node['name']))
            extra_roots = tuple(extra_roots)
            require(len(extra_roots) == 3, 'rust-thread-app-original-default-pool-entry-roles')
            _, _, exports = objects.memory_table(core)
            roots = tuple(name for name, (kind, _) in exports.items()
                          if kind == 0 and name.startswith('__lsf_rust_'))
            original_graph = objects.observe_objects(core, libraries, roots, extra_roots)
            # Retain real graph gaps even when the closed proof refuses them.
            write_json(output / 'original-object-graph.json', original_graph)
            require(not original_graph['failures'] and not original_graph['unresolvedReferents']
                    and not original_graph['instructionDecodeFailures'],
                    'rust-thread-app-original-object-closure-refused')
            std_names = [name for name, row in prepared.libraries.items() if row['crate'] == 'std']
            require(len(std_names) == 1, 'rust-thread-app-one-original-std-library')
            targets, sites, callback_roles = callbacks.derive_plan(core, original_graph,
                std_library=std_names[0], executor_library='captured-futures-executor.rlib')
            write_json(output / 'callback-original-roles.json', callback_roles)
            sealed, isolation_receipt = callbacks.seal_callback_paths(core, digest(core), targets, sites)
            (output / 'callback-isolated-core.wasm').write_bytes(sealed)
            write_json(output / 'callback-isolation.json', isolation_receipt)
            source_wit_raw = commands.run('original-source-wit-graph', paths['wasm-tools'],
                'component', 'wit', work / 'wit', '--json')
            emitted_wit_raw = commands.run('original-emitted-wit-graph', paths['wasm-tools'],
                'component', 'wit', output / 'raw-core.wasm', '--json')
            (output / 'original-source-wit.json').write_bytes(source_wit_raw)
            (output / 'original-emitted-wit.json').write_bytes(emitted_wit_raw)
            source_result = select_http_result(decode_json(source_wit_raw), project['world'], fixture.PUBLIC)
            emitted_result = select_http_result(decode_json(emitted_wit_raw), project['world'], fixture.PUBLIC)
            require(source_result == emitted_result, 'rust-thread-app-original-result-layout-drift')
            result_observation = results.observe_canonical_result(
                core, fixture.PUBLIC, fixture.POST, original_graph, source_result)
            write_json(output / 'canonical-result-source.json', result_observation)
            panic_observation = results.observe_system_panic_trap(
                core, original_graph, fixture.POST, 'cabi_realloc')
            _, sealed_imports, sealed_bodies = objects.code(sealed)
            require(digest(sealed_bodies[panic_observation['originalFunction'] - len(sealed_imports)])
                    == panic_observation['linkedOriginalBodyDigest'], 'rust-thread-app-panic-body-sealing-drift')
            write_json(output / 'canonical-system-panic-source.json', panic_observation)
            record['stage'] = 'actual-guarded-owned-core-transform'
            commands.run('ordinary-owned-core', context_tool, '--guarded-ordinary-core-panic',
                output / 'callback-isolated-core.wasm', digest(sealed), fixture.PUBLIC, fixture.POST,
                'cabi_realloc', str(result_observation['staticResultArea']),
                str(result_observation['originalHeapLow']),
                str(panic_observation['originalFunction']), panic_observation['linkedOriginalBodyDigest'],
                output / 'derived')
            commands.run('validate-derived-core', paths['wasm-tools'], 'validate', output / 'derived/core.wasm',
                '--features', 'cm-async,cm-async-stackful,cm-more-async-builtins')
            receipt = decode_json(read_file(output / 'derived/receipt.json'))
            require(receipt['originalDigest'] == digest(sealed)
                    and receipt['canonicalResultGuardInstalled'] is True
                    and receipt['canonicalStaticResultArea'] == result_observation['staticResultArea']
                    and receipt['canonicalSystemPanicOriginalFunction'] == panic_observation['originalFunction']
                    and receipt['canonicalSystemPanicTrapFunction'] == panic_observation['originalFunction'] +
                        int(receipt['nativeAdmissionImportInserted'])
                    and receipt['privateExecutorGraphAuthenticated'] is False
                    and receipt['canonicalAbiBodiesAuthenticated'] is False
                    and receipt['standardRuntimeQualified'] is False, 'rust-thread-app-source-only-receipt')
            # This is an explicit compiler-only preview, not the maintained
            # HTTP composition or a valid host admission. Capture the actual
            # component graph needed to design the missing combined proof.
            record['stage'] = 'uncomposed-http-thread-component-preview'
            commands.run('preview-component-encode', paths['wasm-tools'], 'component', 'new',
                output / 'derived/core.wasm', '-o', output / 'preview-component.wasm')
            commands.run('validate-preview-component', paths['wasm-tools'], 'validate',
                output / 'preview-component.wasm',
                '--features', 'cm-threading,cm-async,cm-async-stackful,cm-more-async-builtins')
            graph = commands.run('preview-component-graph', paths['wasm-tools'],
                'component', 'wit', output / 'preview-component.wasm', '--json')
            require(len(graph) <= 4 * 1024 * 1024, 'rust-http-thread-preview-graph-bound')
            decode_json(graph)
            (output / 'preview-component-graph.json').write_bytes(graph)
            record['uncomposedPreview'] = file_identity(output / 'preview-component.wasm',
                'uncomposed-http-thread-preview', 16 * 1024 * 1024)
            record['stage'] = 'maintained-http-composition-preview'
            wit_input = output / 'http-thread-wit-inputs.json'
            write_json(wit_input, {'world': project['world'], 'sources': [
                {'path': name, 'content': data.decode()} for name, data in sorted(files.items())
                if name.startswith('wit/') and name.endswith('.wit')]})
            contracts_output = output / 'http-thread-contracts'
            commands.run('http-thread-contracts', contracts_tool, wit_input, contracts_output)
            surface = decode_json(read_file(contracts_output / 'surface.json'))
            combined = output / 'combined-component.wasm'
            shutil.copyfile(output / 'preview-component.wasm', combined)
            diagnostic.check()
            preview_commands = DiagnosticThreadingValidation(commands)
            composition = compose_http(preview_commands, paths, combined, surface, diagnostic,
                work, isolation=isolation, environment_guard=guard)
            require(preview_commands.validated, 'rust-http-thread-diagnostic-validation-missing')
            diagnostic.check()
            composition = record_diagnostic_composition(output, composition, record['diagnosticComposer'])
            record['httpCompositionIncluded'] = True
            record['httpComposition'] = composition
            record['combinedComponent'] = file_identity(combined, 'unadmitted-http-thread-component',
                64 * 1024 * 1024)
            record['stage'] = 'retain-composed-http-thread-graph'
            final_graph = commands.run('combined-component-graph', paths['wasm-tools'],
                'component', 'wit', combined, '--json')
            require(len(final_graph) <= 4 * 1024 * 1024, 'rust-http-thread-final-graph-bound')
            decode_json(final_graph)
            (output / 'combined-component-graph.json').write_bytes(final_graph)
            closure.check_unchanged()
            executable_outputs.check_unchanged()
            guard.check_unchanged(environment)
            isolation.check_unchanged()
            prepared.check()
            require(verify_owned_inputs(owned_report, owned_source, prepared, context_tool, expected_head)
                    == owned_material, 'rust-http-thread-owned-material-mutated')
            diagnostic.check()
            require(file_identity(contracts_tool, 'contracts-tool', 64 * 1024 * 1024) == contracts_identity
                    and verify_contract_tool(contracts_receipt, contracts_tool, expected_head) == contracts_receipt_raw
                    and file_identity(context_tool, 'context-tool', 32 * 1024 * 1024) == context_identity
                    and prepared_http.material() == http_material,
                    'rust-http-thread-prepared-material-mutated')
            require(all(objects.digest(read_file(prepared.directory / item.label,
                                objects.MAX_LIBRARY_BYTES)) == item.expected_digest for item in libraries[:-1])
                    and digest(read_file(output / 'captured-futures-executor.rlib', MAX_EXECUTOR_OBJECT))
                        == executor_identity['digest'], 'rust-thread-app-original-objects-mutated')
            compiled_source = snapshot(work, exclude=('dependencies', 'application-vendor'))
            require(compiled_source.get('Cargo.toml') == adapted,
                    'rust-thread-app-adapted-manifest-mutated')
            compiled_source['Cargo.toml'] = files['Cargo.toml']
            observed.check_unchanged()
            require(bind_recipe_to_git(expected_head, recipe_files) == git_recipe,
                    'rust-http-thread-recipe-git-origin-mutated')
            require(inventory(snapshot(app)) == source
                    and compiled_source == files
                    and host_projection_inputs() == host_projection
                    and inventory({**{name: read_file(builder.ROOT / name) for name in RECIPE},
                                   **http_inputs.consumer_files()}) == recipe
                    and time.monotonic() < deadline,
                    'rust-thread-app-final-source-or-deadline')
            record.update(status='observed-composed-http-thread-source-runtime-unqualified', stage='complete',
                          commands=commands.records, actualApplicationCoreCompiled=True)
            write_json(output / 'observation.json', record)
            return record
    except Exception as error:
        record.update(status='failed', errorType=type(error).__name__, reason=str(error),
                      commands=[] if commands is None else commands.records)
        write_json(output / 'FAILED.json', record)
        raise



if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rust-bin', type=Path, required=True)
    parser.add_argument('--owned-sysroot', type=Path, required=True)
    parser.add_argument('--context-tool', type=Path, required=True)
    parser.add_argument('--http-runtime', type=Path, required=True)
    parser.add_argument('--diagnostic-composer', type=Path, required=True)
    parser.add_argument('--contracts-tool', type=Path, required=True)
    parser.add_argument('--contracts-receipt', type=Path, required=True)
    parser.add_argument('--owned-report', type=Path, required=True)
    parser.add_argument('--owned-source', type=Path, required=True)
    parser.add_argument('--expected-head', required=True)
    args = parser.parse_args()
    run(args.output, args.rust_bin, args.owned_sysroot, args.context_tool,
        args.http_runtime, args.diagnostic_composer, args.contracts_tool, args.contracts_receipt,
        args.owned_report, args.owned_source, expected_head=args.expected_head,
        deadline=time.monotonic() + 600)
