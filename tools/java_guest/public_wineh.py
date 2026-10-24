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

from tools.build_process import BuildProcessError, MAX_OUTPUT_BYTES, run_bounded_result
from tools.dev_workflow import paths
from tools.java_guest.compiler import Compiler
from tools.java_guest.fiber_component_inputs import JAVA, WIT, LIMITS
from tools.java_guest.wineh_ir import FUNCTION, observe
from tools.rust_capsule_project import ROOT, canonical, digest, inventory, snapshot

SCHEMA = 'latent.java.public-wineh-observation.v1'
PRINT_FLAGS = ('-mllvm', '-print-before=win-eh-prepare', '-mllvm',
               '-print-after=win-eh-prepare', '-mllvm', '-filter-print-funcs=' + FUNCTION)
TIMEOUT = 600
RESULT = 'public-wineh.json'
MAINTAINED = ('tools/java_guest/public_wineh.py', 'tools/java_guest/wineh_ir.py',
              'tools/qualify_java_fibers.py')
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
        '-std=c11', '-O2', '-DLSF_JAVA_ACTIVATION_PROFILE=1', '-DLSF_TEAVM_WASM=1',
        '-DTEAVM_CUSTOM_LOG=1', '-mllvm', '-wasm-enable-sjlj', '-lsetjmp', '-mllvm',
        '-wasm-use-legacy-eh=false', '-mexec-model=reactor', '-Wl,--no-entry',
        '-Wl,--export-memory', '-Wl,-z,stack-size=65536', '-Wl,--max-memory=67108864',
        '-include', compiler.sdk / 'runtime/native.h', '-I', destination / 'bindings',
        '-I', compiler.sdk / 'runtime', '-iquote', generated, generated / 'all.c',
        destination / 'bindings/bridge.c', compiler.sdk / 'feasibility/platform.c',
        destination / 'bindings/probe.c', destination / 'bindings/probe_component_type.o',
        '-o', destination / 'core.wasm')))


def input_identity(compiler: Compiler, output: Path) -> dict:
    public_sources(output)
    compiler.check_unchanged()  # Original exact SDK/tool closure validator.
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
    trees = {'generated': generated_inventory(output / 'build/project/build/teavm-c/c'),
             'bindings': json.loads(inventory(snapshot(binding_root)))}
    return {'trees': trees, 'toolInventoryDigest': digest(compiler.compiler_inputs),
            'sdkDigest': digest(inventory(compiler.original_sdk)),
            'environmentDigest': digest(canonical(compiler.environment))}


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
        phase = 'replay'
        result = run_bounded_result(command, compiler.directory, compiler.environment,
            timeout_seconds=TIMEOUT, max_output_bytes=MAX_OUTPUT_BYTES)
        # Hash each channel separately: stdout/stderr interleaving is not known.
        report.update(exitCode=result.returncode, stdoutDigest=digest(result.stdout),
                      stdoutBytes=len(result.stdout))
        phase = 'post-replay-identity'
        if (admitted['source'] != hosted_source(compiler)
                or admitted['inputs'] != input_identity(compiler, output)):
            raise ValueError('diagnostic-inputs-changed')
        if original_pair != {name: dict(zip(('sha256', 'bytes'),
                paths.digest_file(output / 'build', name, maximum)))
                for name, maximum in LIMITS.items()}:
            raise ValueError('diagnostic-original-products-changed')
        phase = 'parser'
        report['observation'] = observe(result.stderr)
        if result.returncode != 0 or result.stdout:
            raise ValueError('diagnostic-exit-or-stdout')
        report['status'] = report['observation']['status']
        if report['status'] == 'incomplete':
            report.update(refusalStage=phase, reason='print-incomplete')
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
