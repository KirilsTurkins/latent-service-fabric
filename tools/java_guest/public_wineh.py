"""Opt-in fixed-public-fixture WinEH observation after original assembly failure.

The original Compiler and its command/acceptance/log paths are unchanged. This
qualifier-only subclass snapshots inputs before delegating the original clang;
diagnostic refusal can never prevent that original command or replace its error.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
from types import SimpleNamespace

from tools.build_process import BuildProcessError, MAX_OUTPUT_BYTES, run_bounded_result
from tools.dev_workflow import paths
from tools.java_guest.compiler import Compiler, _c_optimization, sdk_snapshot, tool_inventory
from tools.java_guest.fiber_component_inputs import JAVA, WIT, LIMITS
from tools.java_guest.wineh_ir import FUNCTION, KEYS, MAX_SAMPLES, MAX_LINE
from tools.rust_capsule_project import ROOT, canonical, digest, inventory, snapshot

SCHEMA = 'latent.java.public-wineh-observation.v1'
PRINT_FLAGS = ('-mllvm', '-print-before=win-eh-prepare', '-mllvm',
               '-print-after=win-eh-prepare', '-mllvm', '-filter-print-funcs=' + FUNCTION)
TIMEOUT = 600
RESULT = 'public-wineh.json'
MAINTAINED = ('tools/java_guest/public_wineh.py', 'tools/java_guest/wineh_ir.py',
              'tools/java_guest/wineh_filter.py', 'tools/qualify_java_fibers.py')
TICKET_SCHEMA = 'latent.java.public-wineh-ticket.v1'
FILTER_SCHEMA = 'latent.java.public-wineh-filter.v1'
RAW_TRANSIT_BUDGET = 256 * 1024 * 1024
SUMMARY_LIMIT = 64 * 1024
REFUSALS = {name: name for name in (
    'public-source-set', 'public-source-identity', 'public-extra-classpath',
    'original-command', 'hosted-source-context', 'hosted-source-git', 'hosted-source-head',
    'original-command-count', 'original-command-receipt', 'original-public-capture',
    'original-public-products-changed', 'original-inputs-changed', 'diagnostic-inputs-changed',
    'diagnostic-original-products-changed', 'diagnostic-exit-or-stdout',
    'generated-entry-limit', 'generated-path', 'generated-byte-limit',
    'bindings-root-exclusion',
    'file-byte-limit', 'source-file-unavailable-or-unsafe', 'single-link-regular-file-required',
    'reparse-point-rejected', 'reparse-or-file-type-rejected', 'windows-protected-open-failed',
    'absolute-owned-path-required', 'source-path-traversal', 'source-changed-during-read', 'command-output-limit',
    'command-deadline', 'process-cleanup', 'process-ownership', 'command-exit')}
REFUSALS.update({name: name for name in (
    'ticket-limit', 'ticket-digest', 'ticket-schema', 'ticket-source', 'ticket-context',
    'ticket-command', 'ticket-receipt', 'ticket-capture', 'ticket-materials', 'ticket-version',
    'filter-summary', 'filter-summary-limit', 'filter-status', 'filter-source-changed')})
REFUSALS.update({
    'Java SDK changed during build': 'sdk-changed',
    'Java compiler distribution changed during build': 'tools-changed',
    'Java compiler changed during build': 'tool-changed',
    'project entry limit exceeded': 'bindings-entry-limit',
    'project source byte limit exceeded': 'bindings-byte-limit',
    'nonportable project path': 'bindings-path',
})


def refusal(error: Exception) -> str:
    # Only literal closed codes leave this helper, never a tool/path message.
    value = error.args[0] if len(error.args) == 1 else None
    return REFUSALS.get(value, 'unavailable-or-unsafe') if type(value) is str else 'unavailable-or-unsafe'


def generated_inventory(root: Path) -> dict:
    """TeaVM's literal @ escapes, with the original independent tree bounds.

    Do not broaden the shared Rust portable-source reader. Anchored readers
    reject linked/nonregular files and symlink/reparse ancestors independently
    of this private name grammar.
    """
    result, entries, total = {}, 0, 0
    pending = [paths.absolute(root)]
    while pending:
        parent = pending.pop()
        with paths.directory(parent):
            for child in parent.iterdir():
                entries += 1
                if entries > 4096:
                    raise ValueError('generated-entry-limit')
                if child.name in {'.', '..'} or not re.fullmatch(r'[A-Za-z0-9._@-]+', child.name):
                    raise ValueError('generated-path')
                relative = child.relative_to(root).as_posix()
                paths.relative(relative)
                if stat.S_ISDIR(child.lstat().st_mode):
                    pending.append(child)
                    continue
                checksum, size = paths.digest_file(root, relative, 4 * 1024 * 1024)
                total += size
                if total > 32 * 1024 * 1024:
                    raise ValueError('generated-byte-limit')
                result[relative] = {'digest': checksum, 'size': size}
    return dict(sorted(result.items()))


def public_sources(output: Path) -> None:
    paths.absolute(output)
    if sorted(path.name for path in (output / 'src').iterdir()) != ['Capsule.java']:
        raise ValueError('public-source-set')
    for name, expected, maximum in (
            ('src/Capsule.java', JAVA, 1024 * 1024),
            ('build/project/src/main/java/Capsule.java', JAVA, 1024 * 1024),
            ('wit/service.wit', WIT, 64 * 1024),
            ('build/wit/service.wit', WIT, 64 * 1024)):
        if digest(paths.read(output, name, maximum)) != expected:
            raise ValueError('public-source-identity')
    for name in ('captured-application', 'captured-processor-api'):
        try:
            (output / 'build/project' / name).lstat()
        except FileNotFoundError:
            continue
        raise ValueError('public-extra-classpath')


def expected_command(compiler: Compiler, output: Path) -> list[str]:
    destination = output / 'build'
    generated = destination / 'project/build/teavm-c/c'
    return list(map(str, (compiler.paths['clang'], '-target', 'wasm32-wasip1',
        '-std=c11', '-' + _c_optimization(True), '-DLSF_JAVA_ACTIVATION_PROFILE=1', '-DLSF_TEAVM_WASM=1',
        '-DTEAVM_CUSTOM_LOG=1', '-mllvm', '-wasm-enable-sjlj', '-lsetjmp', '-mllvm',
        '-wasm-use-legacy-eh=false', '-mexec-model=reactor', '-Wl,--no-entry',
        '-Wl,--export-memory', '-Wl,-z,stack-size=65536', '-Wl,--max-memory=67108864',
        '-include', compiler.sdk / 'runtime/native.h', '-I', destination / 'bindings',
        '-I', compiler.sdk / 'runtime', '-iquote', generated, generated / 'all.c',
        destination / 'bindings/bridge.c', compiler.sdk / 'feasibility/platform.c',
        destination / 'bindings/probe.c', destination / 'bindings/probe_component_type.o',
        '-o', destination / 'core.wasm')))


def tree_identity(output: Path) -> dict:
    public_sources(output)
    binding_root = output / 'build/bindings'
    # The shared Rust reader omits these project-only root names. A compiler
    # input closure must instead refuse their presence, never silently omit a
    # potential included header. Leave the shared reader unchanged.
    with paths.directory(binding_root):
        for name in ('.git', 'target', 'dependency-inputs'):
            try:
                (binding_root / name).lstat()
            except FileNotFoundError:
                continue
            raise ValueError('bindings-root-exclusion')
    # Both trees keep <=4096 entries/32MiB/4MiB per file. Only the private
    # generated tree admits TeaVM's @ escapes; binding/Rust rules stay exact.
    return {'generated': generated_inventory(output / 'build/project/build/teavm-c/c'),
            'bindings': json.loads(inventory(snapshot(binding_root)))}


def input_identity(compiler: Compiler, output: Path) -> dict:
    compiler.check_unchanged()  # Original exact SDK/tool closure validator.
    return {'trees': tree_identity(output), 'toolInventoryDigest': digest(compiler.compiler_inputs),
            'sdkDigest': digest(inventory(compiler.original_sdk)),
            'environmentDigest': digest(canonical(compiler.environment))}


def load_ticket(output: Path, expected: str, environment: dict) -> dict:
    """Pure file admission for the child; never spawn Git/tools or a compiler."""
    paths.absolute(output)
    if not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('ticket-digest')
    raw = paths.read(output / 'build/wineh-observer', 'request.json', 4 * 1024 * 1024)
    if digest(raw) != 'sha256:' + expected:
        raise ValueError('ticket-digest')
    value = json.loads(raw)
    if (type(value) is not dict or set(value) != {'schemaVersion', 'source', 'inputs',
            'toolRoots', 'originalCommand', 'originalPair', 'ordinal', 'diagnosticCommand', 'output',
            'failureCommand', 'failureOrdinal'}
            or value['schemaVersion'] != TICKET_SCHEMA or value['output'] != str(output)):
        raise ValueError('ticket-schema')
    source = value['source']
    prefix = 'KirilsTurkins/latent-service-fabric/.github/workflows/java-guest-feasibility.yml@refs/heads/'
    if (type(source) is not dict or set(source) != {'repository', 'revision', 'workflowRef', 'event', 'maintainedFiles'}
            or source['repository'] != 'KirilsTurkins/latent-service-fabric'
            or source['event'] != 'workflow_dispatch' or type(source['revision']) is not str
            or not re.fullmatch(r'[0-9a-f]{40}', source['revision'])
            or type(source['workflowRef']) is not str or not source['workflowRef'].startswith(prefix)
            or not source['workflowRef'].removeprefix(prefix)):
        raise ValueError('ticket-source')
    maintained = {name: dict(zip(('sha256', 'bytes'), paths.digest_file(ROOT, name, 4 * 1024 * 1024)))
                  for name in MAINTAINED}
    if source['maintainedFiles'] != maintained:
        raise ValueError('ticket-source')
    roots = value['toolRoots']
    if (type(roots) is not dict or set(roots) != {'wasi-sdk', 'jdk', 'gradle'}
            or any(type(root) is not str for root in roots.values())):
        raise ValueError('ticket-context')
    roots = {name: paths.absolute(Path(root)) for name, root in roots.items()}
    wasi = roots['wasi-sdk']
    if (wasi.name != 'wasi-sdk-29.0-x86_64-linux'
            or paths.read(wasi, 'VERSION', 1024).decode().splitlines() != [
                '29.0', 'wasi-libc: ac020b86fd44', 'llvm: 222fc11f2b8f',
                'llvm-version: 21.1.4', 'config: f992bcc08219']):
        raise ValueError('ticket-version')
    compiler = SimpleNamespace(paths={'clang': (wasi / 'bin/clang-21').resolve(strict=True)},
                               sdk=ROOT / 'sdk/java-guest')
    original = value['originalCommand']
    if (type(original) is not dict or original.get('stage') != 'c-to-wasm'
            or type(original.get('exitCode')) is not int or original['exitCode'] != 0
            or original.get('command') != expected_command(compiler, output)
            or type(value['ordinal']) is not int or not 0 <= value['ordinal'] < 256):
        raise ValueError('ticket-command')
    receipt = json.loads(paths.read(output / 'compiler',
        str(value['ordinal']) + '-c-to-wasm.command.json', 64 * 1024))
    if receipt != original:
        raise ValueError('ticket-receipt')
    failed = value['failureCommand']
    if (type(failed) is not dict or failed.get('stage') != 'component-new'
            or type(failed.get('exitCode')) is not int or failed['exitCode'] == 0
            or type(value['failureOrdinal']) is not int or value['failureOrdinal'] != value['ordinal'] + 2
            or type(failed.get('command')) is not list or len(failed['command']) != 8
            or failed['command'][1:] != ['component', 'new', str(output / 'build/core.wasm'),
                '--adapt', 'wasi_snapshot_preview1=' + str(output / 'build/closed-runtime.wasm'),
                '-o', str(output / 'build/component.wasm')]
            or json.loads(paths.read(output / 'compiler', str(value['failureOrdinal'])
                + '-component-new.command.json', 64 * 1024)) != failed):
        raise ValueError('ticket-receipt')
    command = [*original['command'][:-1], str(output / 'build/wineh-observer/core.wasm'), *PRINT_FLAGS]
    if value['diagnosticCommand'] != command:
        raise ValueError('ticket-command')
    capture = json.loads(paths.read(output / 'build/component-inputs', 'record.json', 64 * 1024))
    pair = {name: dict(zip(('sha256', 'bytes'), paths.digest_file(output / 'build', name, maximum)))
            for name, maximum in LIMITS.items()}
    if (pair != value['originalPair'] or pair != capture.get('inputs')
            or capture.get('status') != 'retained' or capture.get('qualification') is not False
            or capture.get('fixtureSourceDigest') != JAVA or capture.get('fixtureWitDigest') != WIT):
        raise ValueError('ticket-capture')
    # Same original normal SDK/distribution primitives, without constructing a
    # Compiler (which would execute version/acquisition commands).
    inputs = {'trees': tree_identity(output),
              'toolInventoryDigest': digest(tool_inventory(roots)),
              'sdkDigest': digest(inventory(sdk_snapshot(compiler.sdk))),
              'environmentDigest': digest(canonical(dict(environment)))}
    if inputs != value['inputs']:
        raise ValueError('ticket-materials')
    return value


def write_ticket(compiler: Compiler, output: Path, admitted: dict, original: dict,
                 ordinal: int, original_pair: dict, command: list[str]) -> str:
    value = {'schemaVersion': TICKET_SCHEMA, 'output': str(output), 'source': admitted['source'],
        'inputs': admitted['inputs'], 'toolRoots': {name: str(root) for name, root in compiler.tool_roots.items()},
        'originalCommand': original, 'ordinal': ordinal, 'originalPair': original_pair,
        'failureCommand': compiler.records[-1], 'failureOrdinal': len(compiler.records) - 1,
        'diagnosticCommand': command}
    raw = canonical(value)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('ticket-limit')
    paths.write_new(output / 'build/wineh-observer/request.json', raw)
    return digest(raw).removeprefix('sha256:')


def filter_summary(result, expected: str, source: dict, command: list[str]) -> dict:
    if len(result.stdout) > SUMMARY_LIMIT or result.stderr:
        raise ValueError('filter-summary-limit')
    value = json.loads(result.stdout)
    allowed = {'schemaVersion', 'status', 'qualification', 'ticketDigest', 'sourceCommit',
        'diagnosticCommandDigest', 'childStarted', 'childExitCode', 'stdoutBytes', 'stdoutDigest',
        'stderrBytes', 'stderrDigest', 'rawTransitMaximum', 'observation', 'pipeEOFComplete',
        'refusalStage', 'reason'}
    reasons = set(REFUSALS.values()) | {'filter-deadline', 'raw-transit-limit', 'print-incomplete',
        'pipe-eof', 'pipe-error', 'child-exit', 'child-stdout', 'filter-interrupted', 'unavailable-or-unsafe'}
    if (type(value) is not dict or not set(value) <= allowed
            or value.get('schemaVersion') != FILTER_SCHEMA or value.get('qualification') is not False
            or value.get('ticketDigest') != expected or value.get('rawTransitMaximum') != RAW_TRANSIT_BUDGET
            or not (type(value.get('childStarted')) is bool or
                value.get('childStarted', True) is None and value.get('status') == 'incomplete'
                and value.get('refusalStage') == 'spawn')
            or value.get('status') not in {'observed', 'incomplete'}
            or value.get('sourceCommit', source['revision']) != source['revision']
            or value.get('diagnosticCommandDigest', digest(canonical(command))) != digest(canonical(command))):
        raise ValueError('filter-summary')
    if value['status'] == 'incomplete':
        if (result.returncode != 1 or value.get('reason') not in reasons
                or value.get('refusalStage') not in {'admission', 'spawn', 'collect', 'summary'}):
            raise ValueError('filter-status')
    elif (result.returncode != 0 or value.get('childStarted') is not True
            or type(value.get('childExitCode')) is not int or value['childExitCode'] != 0
            or value.get('pipeEOFComplete') is not True
            or value.get('sourceCommit') != source['revision'] or 'reason' in value
            or value.get('observation', {}).get('status') != 'observed'
            or value.get('observation', {}).get('prefixOnly') is not False):
        raise ValueError('filter-status')
    if value['childStarted']:
        if (value.get('sourceCommit') != source['revision']
                or value.get('diagnosticCommandDigest') != digest(canonical(command))
                or value.get('childExitCode') is not None and type(value['childExitCode']) is not int
                or type(value.get('pipeEOFComplete')) is not bool):
            raise ValueError('filter-summary')
        for name in ('stdoutBytes', 'stderrBytes'):
            if type(value.get(name)) is not int or value[name] < 0:
                raise ValueError('filter-summary')
        if value['stdoutBytes'] + value['stderrBytes'] > RAW_TRANSIT_BUDGET:
            raise ValueError('filter-summary')
        observation = value.get('observation', {})
        if (type(observation) is not dict or not set(observation) <= {
                'status', 'qualification', 'source', 'snapshots', 'samples', 'streamDigest',
                'streamBytes', 'prefixOnly', 'delta', 'reason'}
                or observation.get('qualification') is not False
                or observation.get('source') != 'pinned-llvm-text-only'
                or observation.get('status') not in {'observed', 'incomplete'}
                or type(observation.get('prefixOnly')) is not bool
                or observation.get('streamBytes') != value['stderrBytes']
                or observation.get('streamDigest') != value.get('stderrDigest')):
            raise ValueError('filter-summary')
        snapshots = observation.get('snapshots')
        samples = observation.get('samples')
        if (type(snapshots) is not dict or not set(snapshots) <= {'before', 'after'}
                or type(samples) is not list or len(samples) > 16 or len(canonical(samples)) > MAX_SAMPLES):
            raise ValueError('filter-summary')
        for row in snapshots.values():
            if (type(row) is not dict or set(row) != set(KEYS)
                    or any(type(item) is not int or not 0 <= item <= RAW_TRANSIT_BUDGET for item in row.values())):
                raise ValueError('filter-summary')
        for sample in samples:
            if (type(sample) is not dict or set(sample) != {'phase', 'opcode', 'instruction', 'lineBytes', 'lineDigest'}
                    or sample['phase'] not in {'before', 'after'} or sample['opcode'] not in {'phi', 'alloca', 'store', 'catchswitch'}
                    or type(sample['instruction']) is not int or not 1 <= sample['instruction'] <= RAW_TRANSIT_BUDGET
                    or type(sample['lineBytes']) is not int or not 1 <= sample['lineBytes'] <= MAX_LINE
                    or type(sample['lineDigest']) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', sample['lineDigest'])):
                raise ValueError('filter-summary')
        if observation['status'] == 'observed':
            if (set(snapshots) != {'before', 'after'} or observation['prefixOnly']
                    or type(observation.get('delta')) is not dict
                    or any(type(item) is not int for item in observation['delta'].values())
                    or observation.get('delta') != {key: snapshots['after'][key] - snapshots['before'][key] for key in KEYS}):
                raise ValueError('filter-summary')
        elif observation['prefixOnly'] is not True:
            raise ValueError('filter-summary')
        for name in ('stdoutDigest', 'stderrDigest'):
            if type(value.get(name)) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', value[name]):
                raise ValueError('filter-summary')
        if value['status'] == 'observed' and value['stdoutBytes'] != 0:
            raise ValueError('filter-status')
    elif set(value) & {'childExitCode', 'stdoutBytes', 'stdoutDigest', 'stderrBytes', 'stderrDigest',
                       'observation', 'pipeEOFComplete'}:
        raise ValueError('filter-summary')
    return value


def hosted_source(compiler: Compiler) -> dict:
    revision = os.environ.get('GITHUB_SHA', '')
    ref = os.environ.get('GITHUB_WORKFLOW_REF', '')
    prefix = 'KirilsTurkins/latent-service-fabric/.github/workflows/java-guest-feasibility.yml@refs/heads/'
    if (os.environ.get('GITHUB_REPOSITORY') != 'KirilsTurkins/latent-service-fabric'
            or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or os.environ.get('GITHUB_WORKSPACE') != str(ROOT)
            or not re.fullmatch(r'[0-9a-f]{40}', revision)
            or not ref.startswith(prefix) or not ref.removeprefix(prefix)):
        raise ValueError('hosted-source-context')
    git = shutil.which('git', path=compiler.environment.get('PATH'))
    if git is None:
        raise ValueError('hosted-source-git')
    result = run_bounded_result([git, '--no-lazy-fetch', 'rev-parse', '--verify', 'HEAD'],
        ROOT, compiler.environment, timeout_seconds=5, max_output_bytes=4096)
    if result.returncode or result.stdout.strip() != revision.encode('ascii'):
        raise ValueError('hosted-source-head')
    return {'repository': 'KirilsTurkins/latent-service-fabric', 'revision': revision,
            'workflowRef': ref, 'event': 'workflow_dispatch',
            'maintainedFiles': {name: dict(zip(('sha256', 'bytes'),
                paths.digest_file(ROOT, name, 4 * 1024 * 1024))) for name in MAINTAINED}}


class PublicWinEHCompiler(Compiler):
    def run(self, stage: str, tool: str, *arguments, cwd: Path | None = None) -> str:
        if stage == 'c-to-wasm':
            # A rejected observation must not stop or modify the ordinary run.
            self.public_wineh = None
            phase = 'admission-command'
            try:
                output = self.directory.parent
                command = [str(self.paths.get(tool, Path(tool))), *map(str, arguments)]
                if (tool != 'clang' or cwd is not None
                        or self.directory != output / 'compiler'
                        or command != expected_command(self, output)):
                    raise ValueError('original-command')
                phase = 'admission-host'
                source = hosted_source(self)
                phase = 'admission-materials'
                inputs = input_identity(self, output)
                self.public_wineh = {'command': command, 'source': source, 'inputs': inputs}
            except Exception as error:
                self.public_wineh_refusal = {'refusalStage': phase, 'reason': refusal(error)}
        return super().run(stage, tool, *arguments, cwd=cwd)


def retain(compiler: Compiler | None, output: Path) -> None:
    """Never replace the original exception; retain small observation only."""
    report = {'schemaVersion': SCHEMA, 'status': 'not-applicable', 'qualification': False,
              'publicFixtureOnly': True, 'compilerAcceptanceChanged': False,
              'originalLogLimitBytes': 16 * 1024 * 1024, 'timeoutSeconds': TIMEOUT,
              'combinedOutputLimitBytes': MAX_OUTPUT_BYTES, 'rawIRRetained': False}
    target = output / 'build/component-inputs'
    phase = 'selection'
    try:
        if not isinstance(compiler, PublicWinEHCompiler):
            return
        if (not compiler.records or compiler.records[-1]['stage'] != 'component-new'
                or type(compiler.records[-1]['exitCode']) is not int
                or compiler.records[-1]['exitCode'] == 0):
            report['reason'] = 'original-failed-component-new-required'
            return
        report['status'] = 'incomplete'
        admitted = getattr(compiler, 'public_wineh', None)
        if admitted is None:
            report.update(getattr(compiler, 'public_wineh_refusal',
                {'refusalStage': 'admission', 'reason': 'unavailable-or-unsafe'}))
            return
        phase = 'command-receipt'
        selected = [(index, row) for index, row in enumerate(compiler.records)
                    if row.get('stage') == 'c-to-wasm']
        if len(selected) != 1:
            raise ValueError('original-command-count')
        ordinal, original = selected[0]
        receipt = json.loads(paths.read(compiler.directory,
            str(ordinal) + '-c-to-wasm.command.json', 64 * 1024))
        if (original != receipt or type(original.get('exitCode')) is not int
                or original['exitCode'] != 0 or original['command'] != admitted['command']
                or original['command'] != expected_command(compiler, output)):
            raise ValueError('original-command-receipt')
        # Normal bounded capture must already have authenticated the Wasm pair.
        phase = 'original-capture'
        capture = json.loads(paths.read(target, 'record.json', 64 * 1024))
        if (capture.get('status') != 'retained' or capture.get('fixtureSourceDigest') != JAVA
                or capture.get('fixtureWitDigest') != WIT or capture.get('qualification') is not False):
            raise ValueError('original-public-capture')
        original_pair = {name: dict(zip(('sha256', 'bytes'),
            paths.digest_file(output / 'build', name, maximum)))
            for name, maximum in LIMITS.items()}
        if original_pair != capture.get('inputs'):
            raise ValueError('original-public-products-changed')
        phase = 'pre-replay-identity'
        if (admitted['source'] != hosted_source(compiler)
                or admitted['inputs'] != input_identity(compiler, output)):
            raise ValueError('original-inputs-changed')
        diagnostic = output / 'build/wineh-observer'
        paths.new_directory(diagnostic)
        command = [*original['command'][:-1], str(diagnostic / 'core.wasm'), *PRINT_FLAGS]
        report.update(source=admitted['source'], originalCommand=original,
            originalInputDigest=digest(canonical(admitted['inputs'])), diagnosticCommand=command)
        phase = 'replay-ticket'
        ticket_digest = write_ticket(compiler, output, admitted, original, ordinal, original_pair, command)
        filter_command = [str(Path(sys.executable).resolve()), '-I', '-B',
            str(ROOT / 'tools/java_guest/wineh_filter.py'), str(output), ticket_digest]
        report.update(filterCommand=filter_command, diagnosticRawTransitLimitBytes=RAW_TRANSIT_BUDGET)
        phase = 'replay'
        result = run_bounded_result(filter_command, compiler.directory, compiler.environment,
            timeout_seconds=TIMEOUT, max_output_bytes=MAX_OUTPUT_BYTES)
        # The original owner has accounted the filter+compiler group BEFORE
        # returning either successful OR incomplete bounded summary bytes.
        phase = 'post-replay-identity'
        if (admitted['source'] != hosted_source(compiler)
                or admitted['inputs'] != input_identity(compiler, output)):
            raise ValueError('diagnostic-inputs-changed')
        if original_pair != {name: dict(zip(('sha256', 'bytes'),
                paths.digest_file(output / 'build', name, maximum)))
                for name, maximum in LIMITS.items()}:
            raise ValueError('diagnostic-original-products-changed')
        if paths.digest_file(diagnostic, 'request.json', 4 * 1024 * 1024)[0] != 'sha256:' + ticket_digest:
            raise ValueError('filter-source-changed')
        report['postReplayIdentitiesVerified'] = True
        phase = 'parser'
        summary = filter_summary(result, ticket_digest, admitted['source'], command)
        report['filter'] = summary
        report['status'] = summary['status']
        if report['status'] == 'incomplete':
            report.update(refusalStage='replay', reason=summary['reason'])
    except BuildProcessError as error:
        report.update(status='incomplete', refusalStage=phase, reason=refusal(error))
    except Exception as error:
        report.update(status='incomplete', refusalStage=phase, reason=refusal(error))
    finally:
        try:
            # No raw IR, alternate Wasm output or complete input tree is
            # retained by the artifact selector. Only this finite JSON record.
            raw = canonical(report)
            if len(raw) > 64 * 1024:
                raise ValueError('observation-record-limit')
            target.mkdir(exist_ok=True)
            paths.write_new(target / RESULT, raw)
        except Exception:
            pass
