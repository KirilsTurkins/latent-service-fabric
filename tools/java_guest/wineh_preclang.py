"""One explicit pre-Clang WinEH observation of the fixed failed public baseline.

No ordinary Clang/component command is executed first or afterwards. Reuse the
existing supervised filter, authenticated R7 reader primitives and hard bounds.
Every result remains diagnostic-only; the original no-improvement gate fails.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace

from tools.build_process import BuildProcessError, MAX_OUTPUT_BYTES, run_bounded_result
from tools.java_guest import public_wineh as old
from tools.java_guest import llvm_ssa_consumer_inputs as inputs
from tools.java_guest import llvm_ssa_distribution as carrier, llvm_ssa_patch as patch
from tools.java_guest.copy_cost_observation import BASELINE, c_shape
from tools.rust_capsule_project import ROOT, canonical, digest

TICKET_SCHEMA = 'latent.java.public-wineh-preclang-ticket.v1'
SCHEMA = 'latent.java.public-wineh-preclang-observation.v1'
BASELINE_PATH = 'tools/data/java-public-wineh/e782-baseline.json'
BASELINE_DIGEST = 'sha256:2311ad8d5456ba50ff784304bf803c8a505e3e2b36ef75b776bd72856d81766b'
RESULT = 'public-wineh-preclang.json'
MAINTAINED = (*old.MAINTAINED, 'tools/java_guest/wineh_preclang.py',
    'tools/java_guest/copy_cost_observation.py', 'tools/java_guest/llvm_ssa_consumer.py',
    'tools/java_guest/llvm_ssa_consumer_inputs.py', 'tools/java_guest/llvm_ssa_distribution.py',
    'tools/java_guest/llvm_ssa_io.py', 'tools/java_guest/llvm_ssa_patch.py',
    'tools/java_guest/llvm_ssa_producer.py', 'tools/java_guest/llvm_ssa_results.py',
    'tools/data/java-llvm-ssa/patch.json', BASELINE_PATH)


def need(condition, reason):
    if not condition:
        raise ValueError('preclang-' + reason)


def strict_equal(left, right) -> bool:
    # Semantic JSON values, with int/bool/float distinctions preserved.
    return canonical(left) == canonical(right)


def no_duplicate_pairs(rows):
    result = {}
    for key, value in rows:
        need(key not in result, 'ticket-duplicate-key')
        result[key] = value
    return result


def baseline() -> dict:
    raw = old.paths.read(ROOT, BASELINE_PATH, 16384)
    need(digest(raw) == BASELINE_DIGEST, 'baseline-source')
    return json.loads(raw)


def require_baseline(value: dict, identity: dict) -> None:
    reference = baseline()
    generated = identity['trees']['generated']
    actual = {'digest': digest(canonical(generated)), 'files': len(generated),
              'bytes': sum(row['size'] for row in generated.values())}
    need(value.get('schemaVersion') == 'latent.java.public-copy-cost-candidate.v1'
         and value.get('qualification') is False and value.get('improved') is False
         and value.get('reason') == 'candidate-not-improved'
         and value.get('clangDecision') == 'refused-not-invoked'
         and strict_equal(value.get('shape'), reference['shape']) and strict_equal(reference['shape'], BASELINE)
         and strict_equal(value.get('trace'), reference['trace'])
         and strict_equal(value.get('inputIdentity'), identity)
         and strict_equal(actual, reference['generatedInventory']), 'baseline-match')


def maintained_files() -> dict:
    return {name: dict(zip(('sha256', 'bytes'),
        old.paths.digest_file(ROOT, name, 4 * 1024 * 1024))) for name in MAINTAINED}


def child_environment(ticket: dict, environment: dict) -> dict:
    # RUNNER_TEMP exists only in the filter to let the UNCHANGED private R7
    # validator establish its fixed root. It never reaches diagnostic Clang.
    need(environment.get('RUNNER_TEMP') == str(Path(ticket['output']).parent), 'filter-root')
    need(digest(canonical(environment)) == ticket['filterEnvironmentDigest'], 'filter-environment')
    result = dict(environment)
    result.pop('RUNNER_TEMP')
    need(digest(canonical(result)) == ticket['compilerEnvironmentDigest'], 'compiler-environment')
    return result


def recheck_sdk(wasi: Path, output: Path, deadline: float) -> None:
    directory = inputs._root()
    need(directory == output.parent / 'java-llvm-public-inputs'
         and output.name == 'java-activation-fibers', 'fixed-root')
    # The raw manifest is pinned by the SAME normal reader's immutable tuple.
    raw = patch.regular(directory, carrier.MANIFEST, carrier.MANIFEST_BYTES)
    need(inputs.identity(raw) == inputs.pinned()['manifest'], 'carrier-manifest')
    admitted = inputs._Admitted(directory, directory / 'products', {}, json.loads(raw), deadline)
    admitted.recheck(wasi)  # No acquisition, extraction, compiler or network.


def load_ticket(output: Path, expected: str, environment: dict, value: dict,
                deadline: float) -> dict:
    need(type(value) is dict and set(value) == {'schemaVersion', 'output', 'source', 'inputs',
        'toolRoots', 'originalCommand', 'diagnosticCommand', 'baselineDigest', 'gateRecord',
        'compilerEnvironmentDigest', 'filterEnvironmentDigest'}
        and value['schemaVersion'] == TICKET_SCHEMA and value['output'] == str(output)
        and value['baselineDigest'] == BASELINE_DIGEST, 'ticket-schema')
    need(time.monotonic() < deadline, 'deadline')
    source = value['source']
    need(type(source) is dict and set(source) == {'repository', 'revision', 'workflowRef',
            'event', 'maintainedFiles'}
         and source['repository'] == inputs.REPOSITORY and source['event'] == 'workflow_dispatch'
         and type(source['revision']) is str and re.fullmatch('[0-9a-f]{40}', source['revision'])
         and source['workflowRef'] == inputs.REPOSITORY
            + '/.github/workflows/java-guest-feasibility.yml@refs/heads/' + inputs.CONSUMER_BRANCH,
         'ticket-source')
    need(strict_equal(source['maintainedFiles'], maintained_files()), 'ticket-source')
    clang_env = child_environment(value, environment)
    roots = value['toolRoots']
    need(type(roots) is dict and set(roots) == {'wasi-sdk', 'jdk', 'gradle'}
         and all(type(root) is str for root in roots.values()), 'ticket-roots')
    roots = {name: old.paths.absolute(Path(root)) for name, root in roots.items()}
    wasi = roots['wasi-sdk']
    recheck_sdk(wasi, output, deadline)
    compiler = SimpleNamespace(paths={'clang': (wasi / 'bin/clang-21').resolve(strict=True)},
        sdk=ROOT / 'sdk/java-guest')
    original = old.expected_command(compiler, output)
    need(value['originalCommand'] == original, 'original-command')
    diagnostic = output / 'build/wineh-observer'
    need(value['diagnosticCommand'] == [*original[:-1], str(diagnostic / 'core.wasm'), *old.PRINT_FLAGS],
         'diagnostic-command')
    current = {'trees': old.tree_identity(output),
        'toolInventoryDigest': digest(old.tool_inventory(roots)),
        'sdkDigest': digest(old.inventory(old.sdk_snapshot(compiler.sdk))),
        'environmentDigest': digest(canonical(clang_env))}
    need(strict_equal(current, value['inputs']), 'materials')
    raw = old.paths.read(output / 'compiler', 'public-copy-cost-candidate.json', 131072)
    need(strict_equal(dict(zip(('digest', 'bytes'), (digest(raw), len(raw)))), value['gateRecord']), 'gate-record')
    require_baseline(json.loads(raw), current)
    need(c_shape(old.paths.read(output, 'build/project/build/teavm-c/c/c/d/l/a/Capsule.c', 4194304))
         == baseline()['shape'], 'actual-c')
    need(not list((output / 'compiler').glob('*-c-to-wasm.command.json'))
         and not list((output / 'compiler').glob('*-component-new.command.json')), 'no-original-compile')
    need(time.monotonic() < deadline, 'deadline')
    return value


def observe(compiler, output: Path, original: list[str], identity: dict) -> None:
    """Return no authority; even observed data cannot turn the failed gate PASS."""
    report = {'schemaVersion': SCHEMA, 'status': 'incomplete', 'qualification': False,
        'sourceBaseline': 'e782a6e476c6c17783a682718f9cdfe15c9a1d5d',
        'originalNoImprovement': True, 'diagnosticOnly': True, 'ordinaryCToWasmInvoked': False,
        'componentNewInvoked': False, 'runtimeInvoked': False, 'rawIRRetained': False,
        'baselineDigest': BASELINE_DIGEST, 'commandCeilingSeconds': 600,
        'compilerCeilingSeconds': 1200, 'cleanupReserveSeconds': 5}
    phase = 'admission'
    try:
        need(compiler.deadline - time.monotonic() > 10, 'deadline')
        need(not any(row['stage'] in {'c-to-wasm', 'component-new'} for row in compiler.records),
             'no-original-compile')
        source = old.hosted_source(compiler)
        need(source['workflowRef'] == inputs.REPOSITORY
             + '/.github/workflows/java-guest-feasibility.yml@refs/heads/' + inputs.CONSUMER_BRANCH,
             'source-ref')
        source['maintainedFiles'] = maintained_files()
        raw = old.paths.read(compiler.directory, 'public-copy-cost-candidate.json', 131072)
        require_baseline(json.loads(raw), identity)
        need(old.input_identity(compiler, output) == identity, 'inputs-before')
        need(original == old.expected_command(compiler, output), 'original-command')
        diagnostic = output / 'build/wineh-observer'
        old.paths.new_directory(diagnostic)
        command = [*original[:-1], str(diagnostic / 'core.wasm'), *old.PRINT_FLAGS]
        filter_env = dict(compiler.environment)
        need('RUNNER_TEMP' not in filter_env, 'ambient-filter-root')
        need(os.environ.get('RUNNER_TEMP') == str(output.parent), 'fixed-root')
        filter_env['RUNNER_TEMP'] = str(output.parent)
        ticket = {'schemaVersion': TICKET_SCHEMA, 'output': str(output), 'source': source,
            'inputs': identity, 'toolRoots': {name: str(root) for name, root in compiler.tool_roots.items()},
            'originalCommand': original, 'diagnosticCommand': command, 'baselineDigest': BASELINE_DIGEST,
            'gateRecord': {'digest': digest(raw), 'bytes': len(raw)},
            'compilerEnvironmentDigest': digest(canonical(compiler.environment)),
            'filterEnvironmentDigest': digest(canonical(filter_env))}
        raw = canonical(ticket)
        need(len(raw) <= 4 * 1024 * 1024, 'ticket-bound')
        old.paths.write_new(diagnostic / 'request.json', raw)
        seal = digest(raw).removeprefix('sha256:')
        filter_command = [str(Path(sys.executable).resolve()), '-I', '-B',
            str(ROOT / 'tools/java_guest/wineh_filter.py'), str(output), seal]
        remaining = compiler.deadline - time.monotonic()
        need(remaining > 0, 'deadline')
        report.update(source=source, diagnosticCommand=command, filterCommand=filter_command,
            inputDigest=digest(canonical(identity)), ticketDigest=seal)
        phase = 'diagnostic'
        allowance = min(595, remaining)
        started = time.monotonic()
        report.update(executionAllowanceSeconds=allowance, ordinaryDiagnosticMaximumBytes=16777216,
                      rawTransitMaximumBytes=old.RAW_TRANSIT_BUDGET, summaryMaximumBytes=65536)
        result = run_bounded_result(filter_command, compiler.directory, filter_env,
            timeout_seconds=allowance, max_output_bytes=MAX_OUTPUT_BYTES)
        report.update(filterExitCode=result.returncode, diagnosticSeconds=round(time.monotonic()-started, 6))
        phase = 'post-identity'
        need(compiler.deadline > time.monotonic(), 'deadline')
        need(old.input_identity(compiler, output) == identity, 'inputs-after')
        need(strict_equal(maintained_files(), source['maintainedFiles']), 'source-after')
        need(compiler.deadline > time.monotonic(), 'deadline')
        need(old.paths.digest_file(diagnostic, 'request.json', 4 * 1024 * 1024)[0] == 'sha256:' + seal,
             'ticket-after')
        summary = old.filter_summary(result, seal, source, command)
        report.update(status=summary['status'], filter=summary, postIdentitiesVerified=True)
        if summary['status'] == 'incomplete':
            report.update(refusalStage='diagnostic', reason=summary['reason'])
    except BuildProcessError as error:
        report.update(refusalStage=phase, reason=old.refusal(error))
    except Exception as error:
        report.update(refusalStage=phase, reason=old.refusal(error))
    finally:
        raw = canonical(report)
        if len(raw) > 65536:
            raw = canonical({'schemaVersion': SCHEMA, 'status': 'incomplete', 'qualification': False,
                'originalNoImprovement': True, 'reason': 'summary-limit', 'rawIRRetained': False})
        try:
            old.paths.write_new(compiler.directory / RESULT, raw)
        except Exception:
            pass  # Missing observation cannot replace or pass the original failed gate.
