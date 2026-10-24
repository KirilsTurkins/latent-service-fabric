"""One normal source build, then bounded intrinsic borrow-observer diagnostics.

No signed Component Model, provider physical-retirement or whole-cost claim.
This recipe does not change/reissue old source receipts or relax validators.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import time

from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, digest, fresh, read_file, write_json
from tools.typescript_guest import activation_engine, native_build, promise_library, splicer_build

BASELINE = '5e465f8c534ee31d407dbb9720fdec35cb9da71d'
BASELINE_HEADER = 'sdk/typescript-guest/activation/native_imports.h'
BASELINE_BYTES = 9865
BASELINE_DIGEST = 'sha256:40b5737a75a9c8c06511a2ea36df14110b3577fb7f7098b202940e5abc839dd7'
NORMAL_CASES = (
    'borrow-observer-blocked-cancel-awaits-actual-drop',
    'borrow-observer-rejects-foreign-and-unregistered-handles',
    'borrow-observer-native-denial-precedes-node-and-Promise',
    'cancel-keeps-import-buffer-until-terminal',
)
REFUSAL_CASES = (
    'borrow-refusal-observer-Promise-admission',
    'borrow-refusal-bounded-cycle',
    'borrow-refusal-original-work-ack',
    'borrow-refusal-original-result-ack',
    'borrow-refusal-original-native-ack',
    'borrow-refusal-original-record-ack',
    'borrow-refusal-observer-owner-ack',
)
CASES = NORMAL_CASES + REFUSAL_CASES
RECIPE = (
    'tools/qualify_typescript_borrow_release.py', 'tools/typescript_guest/borrow_controls.py',
    'tools/typescript_guest/borrow_controls_wasi.mjs', 'tools/typescript_guest/borrow_support.py',
    'tools/typescript_guest/native_build.py', 'tools/typescript_guest/promise_library.py',
    'tools/tests/test_typescript_import_cancellation.py',
    'sdk/typescript-guest/activation/tests/native_imports.cpp',
    'tools/typescript_guest/import_cancellation.mjs', 'tools/typescript_guest/async_waiters.mjs',
    'tools/build_process.py', 'tools/build_process_linux.py',
    'tools/build_observation.py', 'tools/phase3_resource_identity.py',
    'tools/typescript_borrow_splicer_inputs.py', 'tools/typescript_borrow_retry_inputs.py', '.github/workflows/typescript-borrow-release.yml',
    'tools/typescript_tracking_replay_inputs.py', 'tools/typescript_fetch_replay_inputs.py',
    'tools/java_replay_materials.py',
    *activation_engine.engine_input_paths('spidermonkey-activation-promises-clocks-imports-v1'),
)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def source_controls(value: dict) -> None:
    require(type(value) is dict and set(value) == {'testsRun', 'skipped', 'failures', 'errors'},
            'borrow-source-control-result-shape')
    require(all(type(item) is int for item in value.values()) and value == {
        'testsRun': 6, 'skipped': 0, 'failures': 0, 'errors': 0}, 'borrow-source-controls-require-six-no-skips')


def workflow_origin(source_commit: str) -> dict:
    names = ('GITHUB_REPOSITORY', 'GITHUB_WORKFLOW_REF', 'GITHUB_WORKFLOW_SHA', 'GITHUB_EVENT_NAME',
             'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_SHA', 'GITHUB_REF')
    values = {name: os.environ.get(name) for name in names}
    require(all(isinstance(value, str) and 0 < len(value) <= 1024 for value in values.values()),
            'borrow-controls-workflow-origin-required')
    require(values['GITHUB_REPOSITORY'] == 'KirilsTurkins/latent-service-fabric'
            and values['GITHUB_WORKFLOW_REF'].startswith(
                'KirilsTurkins/latent-service-fabric/.github/workflows/typescript-borrow-release.yml@refs/')
            and values['GITHUB_EVENT_NAME'] in {'push', 'workflow_dispatch'}
            and values['GITHUB_SHA'] == source_commit
            and re.fullmatch(r'[0-9a-f]{40}', values['GITHUB_WORKFLOW_SHA']) is not None,
            'borrow-controls-workflow-origin-identity')
    require(re.fullmatch(r'[0-9]{1,20}', values['GITHUB_RUN_ID']) is not None
            and re.fullmatch(r'[0-9]{1,6}', values['GITHUB_RUN_ATTEMPT']) is not None
            and int(values['GITHUB_RUN_ID']) > 0 and int(values['GITHUB_RUN_ATTEMPT']) > 0,
            'borrow-controls-workflow-attempt-bound')
    return values


def native_control(value: dict, case: str) -> dict:
    require(case in CASES and type(value) is dict and value.get('case') == case
            and type(value.get('status')) is int and value['status'] == 0,
            'borrow-native-control-case-or-status')
    require(value.get('hostcallInGC') is False and value.get('dropOrderValid') is True,
            'borrow-native-control-drop-or-GC-order')
    require(all(type(value.get(name)) is int and 0 <= value[name] <= 256
                for name in ('subtaskDrops', 'cancelRequests', 'exactAckRefusals')),
            'borrow-native-control-counter-shape')
    quarantine = case in REFUSAL_CASES
    require(value.get('expectedQuarantine') is quarantine and type(value.get('owners')) is int
            and 0 <= value['owners'] <= 256
            and (value['owners'] > 0 if quarantine else value['owners'] == 0),
            'borrow-native-control-exact-retention')
    if quarantine:
        require(value.get('recordDestroyed') is True and value.get('observerDestroyed') is True,
                'borrow-native-control-physical-destruction')
        ack = case.endswith('-ack')
        require(value.get('exactAckRefusals') == (1 if ack else 0)
                and value.get('subtaskDrops') == (1 if ack else 0)
                and value.get('cancelRequests') == (1 if ack else 0),
                'borrow-native-control-refusal-not-exercised')
    if case == NORMAL_CASES[0]:
        require(value.get('recordDestroyed') is True and value.get('observerDestroyed') is True
                and value.get('subtaskDrops') == 1 and value.get('cancelRequests') == 1,
                'borrow-native-control-blocked-drop-not-exercised')
    names = ('managerBytes', 'baselineManagerBytes', 'fixedManagerDeltaBytes', 'recordBytes', 'observerBytes')
    require(all(type(value.get(name)) is int and 0 < value[name] < 65536 for name in names),
            'borrow-native-control-ABI-measurement')
    require(value['managerBytes'] - value['baselineManagerBytes'] == value['fixedManagerDeltaBytes'],
            'borrow-native-control-ABI-delta')
    return {name: value[name] for name in names}


def diagnostic_phase(label, arguments, *, run, deadline, output, phases):
    remaining = min(120, deadline - time.monotonic())
    require(remaining > 0, 'borrow-controls-diagnostic-aggregate-deadline')
    began = time.monotonic()
    phase = {'phase': label, 'maximumSeconds': remaining, 'status': 'in-progress'}
    phases.append(phase)
    write_json(output / (label + '.phase-start.json'), dict(phase))
    try:
        run(label, *arguments, seconds=min(remaining, deadline - time.monotonic()))
        require(time.monotonic() < deadline, 'borrow-controls-diagnostic-aggregate-deadline')
        phase['status'] = 'passed'
    except BaseException:
        phase['status'] = 'failed'
        raise
    finally:
        phase['elapsedSeconds'] = time.monotonic() - began
        write_json(output / (label + '.phase-result.json'), dict(phase))

def build(output: Path, tools: Path, prepared_products: Path, *, wasm_tools='wasm-tools') -> dict:
    require(sys.platform == 'linux' and platform.machine() in {'x86_64', 'AMD64'}, 'borrow-controls-linux-x86-64')
    require(sys.version_info[:3] == (3, 13, 5), 'borrow-controls-pinned-python')
    tools = tools.resolve(strict=True)
    from tools import typescript_borrow_retry_inputs as retry
    prepared_products = prepared_products.resolve(strict=True)
    source_splicer = prepared_products / retry.SPLICER
    output = output.resolve()
    require(output != ROOT and ROOT not in output.parents and output not in tools.parents
            and tools not in output.parents and output != tools and output != source_splicer
            and source_splicer not in output.parents and output not in source_splicer.parents
            and output != prepared_products and output not in prepared_products.parents and prepared_products not in output.parents,
            'borrow-controls-fresh-independent-output')
    output = fresh(output)
    environment = build_environment(output)
    deadline = time.monotonic() + 4500
    recipe = {name: file_identity(ROOT / name) for name in dict.fromkeys(RECIPE)}
    record = {'schemaVersion': 'latent.typescript.borrow-controls.v1', 'status': 'in-progress',
              'qualification': 'unknown', 'apiSupport': 'not-evaluated', 'signedExecution': 'not-run',
              'physicalProviderQualification': 'not-evaluated', 'wholeCostQualification': False,
              'scope': 'source-built-intrinsic-controls-with-fixture-canonical-and-broker-imports',
              'recipe': recipe, 'limits': {'overallSeconds': 4500, 'productReuse': 'frozen completed library and engine; no builds',
                  'diagnosticSupportSeconds': 300, 'diagnosticCompileAndLinkSeconds': 120, 'diagnosticOptimization': 'O0; diagnostic only',
                  'caseSeconds': 20, 'caseCount': len(CASES), 'outputBytesPerCommand': 4 * 1024**2}}

    def run(label, *command, seconds=20, cwd=output, env=None):
        remaining = min(seconds, deadline - time.monotonic())
        require(remaining > 0, 'borrow-controls-overall-deadline')
        write_json(output / (label + '.command.json'), {'command': list(map(str, command)), 'maximumSeconds': remaining})
        result = run_bounded_result(list(map(str, command)), cwd, env or environment,
                                    timeout_seconds=remaining, max_output_bytes=4 * 1024**2)
        for name in ('stdout', 'stderr'):
            (output / (label + '.' + name + '.log')).write_bytes(getattr(result, name))
        write_json(output / (label + '.result.json'), {'returncode': result.returncode,
                   'stdoutDigest': digest(result.stdout), 'stderrDigest': digest(result.stderr)})
        require(result.returncode == 0, 'borrow-controls-command-failed:' + label)
        return result.stdout

    stage = 'existing-inputs'
    try:
        source_commit = run('source-commit', 'git', 'rev-parse', 'HEAD', cwd=ROOT).decode().strip()
        source_tree = run('source-tree', 'git', 'rev-parse', 'HEAD^{tree}', cwd=ROOT).decode().strip()
        require(re.fullmatch(r'[0-9a-f]{40}', source_commit) is not None
                and re.fullmatch(r'[0-9a-f]{40}', source_tree) is not None,
                'borrow-controls-source-identity')
        require(not run('source-clean', 'git', 'status', '--porcelain', '--untracked-files=normal', cwd=ROOT).strip(),
                'borrow-controls-committed-source-required')
        record.update(sourceCommit=source_commit, sourceTree=source_tree, workflowOrigin=workflow_origin(source_commit))
        # Reject source drift before acquiring the fixed diagnostic toolchain.
        # These unchanged normal validators do not rewrite producer receipts.
        record['sourceInputReuse'] = retry.validate(prepared_products)
        record['splicer'] = native_build.source_splicer(source_splicer)
        record['publicCompiler'] = splicer_build.compiler_inventory(tools)
        node = shutil.which('node', path=environment['PATH'])
        require(node is not None, 'borrow-controls-node-required')
        require(run('node-version', node, '--version').strip() == b'v24.19.0', 'borrow-controls-pinned-node')
        parser = tools / 'node_modules/acorn/dist/acorn.mjs'
        parser_identity = file_identity(parser, 2 * 1024**2)
        record['node'] = file_identity(Path(node), 128 * 1024**2)
        record['pinnedParser'] = parser_identity
        baseline = run('baseline-source', 'git', 'show', BASELINE + ':' + BASELINE_HEADER, cwd=ROOT)
        require(len(baseline) == BASELINE_BYTES and digest(baseline) == BASELINE_DIGEST,
                'borrow-controls-baseline-source-identity')
        current = read_file(ROOT / BASELINE_HEADER)
        def declaration(raw):
            return raw[raw.index(b'  struct Record {'):raw.index(b'  BrokerAccounting& jobs_;')]
        require(declaration(current) == declaration(baseline), 'borrow-controls-default-record-layout-changed')
        includes = output / 'control-includes'; includes.mkdir()
        (includes / 'borrow-baseline-native-imports.h').write_bytes(baseline)
        record['baseline'] = {'revision': BASELINE, 'path': BASELINE_HEADER, 'digest': digest(baseline), 'bytes': len(baseline)}

        stage = 'pinned-parser-controls'
        control_env = dict(environment, LSF_TYPESCRIPT_ACORN=str(parser))
        program = ("import json,sys,unittest; suite=unittest.defaultTestLoader.loadTestsFromName('tools.tests.test_typescript_import_cancellation');"
                   "result=unittest.TextTestRunner(verbosity=2).run(suite);"
                   "print(json.dumps(dict(testsRun=result.testsRun,skipped=len(result.skipped),failures=len(result.failures),errors=len(result.errors))));"
                   "sys.exit(0 if result.wasSuccessful() else 1)")
        source_controls(json.loads(run('pinned-parser-controls', sys.executable, '-c', program,
                                      seconds=30, cwd=ROOT, env=control_env)))

        stage = 'reused-source-inputs'
        library = prepared_products / retry.PREFIX / 'library'
        engine = prepared_products / retry.PREFIX / 'engine'
        compilation = json.loads(read_file(engine / 'engine-compilation.json', 1024**2))
        products = {
            'libraryReceipt': (library / 'library-build.json', 4 * 1024**2),
            'engineReceipt': (engine / 'engine-compilation.json', 4 * 1024**2),
            'engineInput': (engine / 'engine-input.json', 1024**2),
            'engineCore': (engine / 'engine.wasm', 64 * 1024**2),
            'combinedLibrary': (engine / 'spidermonkey/libspidermonkey.a',
                                compilation['archiveCompositionLimits']['maximumCombinedBytes']),
        }
        record['products'] = {name: file_identity(path, maximum) for name, (path, maximum) in products.items()}
        stage = 'fixed-wasi-toolchain'
        wasi_archive = output / 'wasi-sdk.archive'
        record['diagnosticToolchainAcquisition'] = promise_library.acquire(
            wasi_archive, promise_library.SOURCES['wasi-sdk'], deadline)
        wasi = promise_library.extract(wasi_archive, output / 'wasi-source',
                                      'wasi-sdk-30.0-x86_64-linux', deadline=deadline)
        stage = 'maintained-diagnostic-support'
        from tools.typescript_guest import borrow_support
        record['supportBuild'] = borrow_support.build(output / 'support', wasi, engine, run, environment)
        support = record['supportBuild']['products']
        products.update({
            'diagnosticRustLibrary': (Path(support['library']), borrow_support.MAX_LIBRARY),
            'diagnosticRustWrapper': (Path(support['wrapper']), 1024**2),
            'diagnosticClang': ((wasi / 'bin/clang++').resolve(strict=True), 256 * 1024**2),
            **{'diagnosticWasi-' + name: (Path(path), 32 * 1024**2)
               for name, path in support['emulation'].items()},
        })
        record['products'] = {name: file_identity(path, maximum) for name, (path, maximum) in products.items()}
        core, object_file = output / 'borrow-controls.wasm', output / 'borrow-controls.o'
        diagnostic_deadline = time.monotonic() + 120
        record['diagnosticPhases'] = []
        def phase(label, *arguments):
            diagnostic_phase(label, arguments, run=run, deadline=diagnostic_deadline,
                             output=output, phases=record['diagnosticPhases'])
        stage = 'diagnostic-compile'
        phase('compile-controls', wasi / 'bin/clang++', '-std=c++20', '-O0', '-fno-sized-deallocation',
            '-DSTATIC_JS_API', '-DJS_STANDALONE',
            '-DLSF_TYPESCRIPT_BORROW_CONTROLS=1', '-I' + str(engine / 'spidermonkey/include'),
            '-I' + str(engine / 'jobs-generated'), '-I' + str(engine / 'clocks-generated'),
            '-I' + str(ROOT / 'sdk/typescript-guest/activation'), '-I' + str(includes),
            '-include', engine / 'spidermonkey/include/js-confdefs.h', '-c',
            ROOT / 'sdk/typescript-guest/activation/tests/native_imports.cpp', '-o', object_file)
        record['controlObject'] = file_identity(object_file, 32 * 1024**2)
        stage = 'diagnostic-link'
        # The normal library is ThinLTO bitcode. Disable diagnostic link-time
        # optimization explicitly; do not rebuild or alter the production core.
        phase('link-controls', wasi / 'bin/clang++', '-O0', object_file,
            engine / 'spidermonkey/libspidermonkey.a', Path(support['library']), Path(support['wrapper']),
            *(Path(path) for path in support['emulation'].values()), '-Wl,--lto-O0', '-Wl,--strip-debug', '-Wl,--wrap=_ZdlPv',
            '-Wl,-z,stack-size=8388608', '-Wl,--max-memory=268435456', '-o', core)
        require(time.monotonic() < diagnostic_deadline, 'borrow-controls-diagnostic-final-deadline')
        run('validate-control-core', wasm_tools, 'validate', core)
        record['controlCore'] = file_identity(core, 64 * 1024**2)
        stage = 'native-controls'
        rows, abi = [], None
        for case in CASES:
            value = json.loads(run(case, node, ROOT / 'tools/typescript_guest/borrow_controls_wasi.mjs', core, case))
            observed = native_control(value, case)
            require(abi is None or abi == observed, 'borrow-controls-inconsistent-ABI')
            abi = observed
            rows.append(value)
        record.update(controls=rows, actualWasm32ABI=abi)
        require(recipe == {name: file_identity(ROOT / name) for name in recipe}, 'borrow-controls-source-changed')
        require(parser_identity == file_identity(parser, 2 * 1024**2), 'borrow-controls-parser-changed')
        require(record['node'] == file_identity(Path(node), 128 * 1024**2), 'borrow-controls-node-changed')
        require(record['splicer'] == native_build.source_splicer(source_splicer), 'borrow-controls-splicer-changed')
        require(record['products'] == {name: file_identity(path, maximum) for name, (path, maximum) in products.items()},
                'borrow-controls-source-built-product-changed')
        require(run('final-source-commit', 'git', 'rev-parse', 'HEAD', cwd=ROOT).decode().strip() == source_commit
                and run('final-source-tree', 'git', 'rev-parse', 'HEAD^{tree}', cwd=ROOT).decode().strip() == source_tree
                and not run('final-source-clean', 'git', 'status', '--porcelain', '--untracked-files=normal', cwd=ROOT).strip(),
                'borrow-controls-source-checkout-changed')
        require(time.monotonic() < deadline, 'borrow-controls-final-deadline')
        require(record['sourceInputReuse'] == retry.validate(prepared_products), 'borrow-controls-reused-inputs-changed')
        promise_library.recheck_archives(output, {'wasi-sdk': promise_library.SOURCES['wasi-sdk']},
            {'wasi-sdk': record['diagnosticToolchainAcquisition']})
        require(time.monotonic() < deadline, 'borrow-controls-final-reuse-recheck-deadline')
        record.update(status='passed', libraryBuildCount=0, engineBuildCount=0,
                      limitations=['Fixture intrinsics are not real signed canonical cancellation.',
                                   'Borrow acknowledgement does not establish physical IoCall retirement.',
                                   'ABI size measurements do not establish whole-runtime cost acceptance.'])
        write_json(output / 'BORROW-CONTROLS.json', record)
        require(time.monotonic() < deadline, 'borrow-controls-final-exit-deadline')
        return record
    except BaseException as error:
        (output / 'BORROW-CONTROLS.json').unlink(missing_ok=True)
        record.update(status='failed', stage=stage, reason=str(error)[:4096] if isinstance(error, ValueError) else type(error).__name__)
        write_json(output / 'FAILED.json', record)
        raise
