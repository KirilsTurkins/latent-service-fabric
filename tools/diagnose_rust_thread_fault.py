"""Build only an explicit diagnostic node/control, then reuse unchanged inputs.

Four helper products retain their exact verified 193-control origin. The node
has a NEW source/product identity and is never relabelled as that cohort. No
guest/compiler/sysroot build and no runtime qualification occur here. Numeric
stderr I/O can block and perturbs wall/terminal observation; this programme
owns a draining, byte-bounded process sink and retains only numeric rows.
"""
from pathlib import Path
import argparse
import json
import os
import shutil
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, inventory, source_identity
from tools.qualify_host_codec_native import Stages, exact_list, exact_result, materials
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, write_json
from tools import rust_thread_native_products as original
from tools.rust_thread_runtime_package import prepare
from tools.rust_thread_runtime_node import run

CASE = 'rust_thread_fault::tests::rust_thread_fault_visits_only_eight_numeric_original_frames_for_authenticated_rust'
WAIT_CASE = 'early_untimed_notification_never_resumes_a_running_thread'
WAIT_SOURCE = 'sdk/rust-standard-runtime/tests/thread_wait_driver_native.rs'
# Bind the complete source-port regression, not just its test harness. These
# sources are NOT substituted into the immutable retained guest component.
WAIT_RECIPE = (WAIT_SOURCE, *(f'sdk/rust-standard-runtime/{name}.rs' for name in (
    'executor_root', 'runtime_owner', 'thread_wait_driver', 'thread_wait',
    'thread_wait_registry')))
RECIPE = ('.github/workflows/rust-thread-fault-diagnostic.yml',
          'tools/diagnose_rust_thread_fault.py', 'tools/rust_thread_fault_frames.py',
          'tools/rust_thread_runtime_node.py', 'tools/rust_thread_runtime_package.py',
          'tools/rust_thread_compiler_materials.py', 'tools/rust_thread_native_products.py',
          *WAIT_RECIPE)


def inputs():
    return {'source': source_identity(ROOT),
            'materials': dict(sorted({**materials(ROOT), **{
                name: file_identity(ROOT / name) for name in RECIPE}}.items()))}


def diagnose(prepared: Path, compiler_materials: Path, output: Path, revision: str):
    require(sys.platform == 'linux', 'rust-thread-diagnostic-linux-owner')
    output = fresh(output)
    record = {'schemaVersion': 'latent.rust.thread-fault.programme.v1',
              'status': 'incomplete', 'runtimeQualification': False,
              'full743Qualified': False, 'historicalReceiptRewritten': False,
              'guestCompilerAndSysrootRebuilt': False,
              'diagnosticIoMayPerturbTimingAndTerminalObservation': True}
    stage, primary = 'verify-original-193-helper-origin', False
    stages = None
    try:
        old = original.verify_prepared(prepared)
        products = original.native_products(prepared)
        record['originalNativeOrigin'] = old
        before = inputs()
        write_json(output / 'source-inputs.json', before)
        build = fresh(output / 'build')
        environment = build_environment(build)
        target = Path(os.environ.get('CARGO_TARGET_DIR', ROOT / 'target')).resolve()
        environment.update(CARGO_TARGET_DIR=str(target), RUSTUP_TOOLCHAIN='1.97.1',
            CARGO_BUILD_JOBS='2', CARGO_INCREMENTAL='0',
            CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0',
            CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
            CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
        stages = Stages(Commands(ROOT, build, environment,
            deadline_seconds=960, command_seconds=900), build)
        require(stages.run('source-revision', 'git', 'rev-parse', 'HEAD').decode().strip() == revision,
                'rust-thread-diagnostic-exact-source')
        compiler = stages.run('rust-version', 'rustc', '--version').decode().strip()
        require(compiler.startswith('rustc 1.97.1 ('), 'rust-thread-diagnostic-rust-pin')
        # Exercise the actual root registry, affine owner and fixed Wait driver
        # together. The explicit Source callback is not a captured executor or
        # engine/signed-guest qualification, and cannot change the fault gate.
        stage = 'native-root-retirement-wakeup-control'
        wait_control = build / 'root-retirement-wakeup-control'
        stages.run('root-wait-build', 'rustc', '--edition=2024', '--test',
                   ROOT / WAIT_SOURCE, '-o', wait_control)
        exact_list(stages.run('root-wait-list', wait_control, WAIT_CASE, '--exact', '--list'),
                   (WAIT_CASE,))
        exact_result(stages.run('root-wait-run', wait_control, WAIT_CASE, '--exact',
                                '--test-threads=1'), (WAIT_CASE,))
        record['nativeRootRetirementWakeupControl'] = WAIT_CASE
        cargo = ('cargo', '--config', ROOT / '.cargo/managed-guest.toml')
        stage = 'one-real-numeric-original-trap-control'
        test = (*cargo, 'test', '--locked', '-p', 'latent-wasmtime', '--lib',
                '--features', 'rust-thread-trap-diagnostic', CASE, '--')
        exact_list(stages.run('numeric-control-list', *test, '--list'), (CASE,))
        exact_result(stages.run('numeric-control-run', *test, '--exact', '--test-threads=1'), (CASE,))
        stage = 'only-new-diagnostic-node-build'
        stages.run(stage, *cargo, 'build', '--locked', '-p', 'latentd', '--bin', 'latentd',
                   '--features', 'rust-thread-trap-diagnostic')
        require(before == inputs(), 'rust-thread-diagnostic-source-changed')
        owned = fresh(output / 'diagnostic-native')
        source, destination = target / 'debug/latentd', owned / 'latentd'
        identity = file_identity(source, 256 * 1024 * 1024)
        shutil.copyfile(source, destination)
        destination.chmod(0o700)
        require(identity == file_identity(destination, 256 * 1024 * 1024)
                == file_identity(source, 256 * 1024 * 1024), 'rust-thread-diagnostic-product-changed')
        # The composite is explicit: four immutable old helpers, ONE rebuilt
        # diagnostic node. Never call original.verify_prepared on this tuple.
        products = {**products, 'latentd': destination}
        record['compositeProducts'] = {name: file_identity(path, 512 * 1024 * 1024)
                                       for name, path in products.items()}
        record.update(sourceRevision=revision, source=before, compiler=compiler,
                      buildCommands=stages.records, newDiagnosticNode=identity,
                      original193NodeReused=False, originalFourHelpersReused=True)
        write_json(output / 'diagnostic-native-origin.json', record)
        stage = 'unchanged-retained-component-package'
        assembly = fresh(output / 'assembly')
        commands = Commands(ROOT, assembly, build_environment(assembly),
                            deadline_seconds=600, command_seconds=60)
        record['package'] = prepare(compiler_materials, products, output / 'package', commands)
        stage = 'actual-original-guest-with-numeric-fault-observation'
        record['diagnosticConsumer'] = run(output / 'package', products, output / 'node', diagnostic=True)
        record.update(status=('completed-with-fault' if
            record['diagnosticConsumer'].get('diagnosticFaultObserved') is True
            else 'completed-without-fault'), runtimeQualification=False)
        return record
    except BaseException:
        primary = True
        record.update(status='failed', stage=stage, runtimeQualification=False)
        raise
    finally:
        if stages is not None:
            record['buildCommands'] = stages.records
        try:
            write_json(output / 'diagnostic-result.json', record)
            # Explicit distinct domains: a node may be 256 MiB, unlike public
            # consumer evidence (128 MiB). No source/log trimming or success waiver.
            inventory(output, maximum_files=512, maximum_bytes=400 * 1024 * 1024,
                      deadline=time.monotonic() + 60)
        except BaseException:
            if not primary:
                raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--compiler-materials', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    args = parser.parse_args()
    diagnose(args.prepared, args.compiler_materials, args.output, args.source_commit)
