"""Delegate authoring to an explicit frontend or the same owned source tree."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import os
from pathlib import Path
import sys
import tempfile

from tools.build_observation import build_environment
from tools.build_process import BuildProcessError, run_bounded_result
from tools.dev_workflow import paths
from tools.dev_workflow.common import decode, require, sha

MAX_FRONTEND = 64 * 1024 * 1024
MAX_OUTPUT = 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]
RECIPE = ('tools/guest_authoring_frontend.py', 'tools/build_observation.py', 'tools/build_snapshot.py',
          'tools/build_process.py', 'tools/build_process_linux.py', 'tools/build_process_windows.py',
          'tools/build_process_signals.py', 'tools/dev_workflow/__init__.py',
          'tools/dev_workflow/common.py', 'tools/dev_workflow/paths.py', 'tools/dev_workflow/windows.py')


@dataclass(frozen=True)
class Outcome:
    exit_code: int
    evidence: dict
    stdout: bytes = b''
    stderr: bytes = b''


def _source_modules() -> None:
    for name, module in tuple(sys.modules.items()):
        if name == 'tools' or name.startswith('tools.'):
            location = getattr(module, '__file__', None)
            require(location is None or Path(location).resolve().is_relative_to(ROOT),
                    'authoring-frontend-source-outside-owned-tree')
            for location in getattr(module, '__path__', ()):
                require(Path(location).resolve().is_relative_to(ROOT),
                        'authoring-frontend-source-outside-owned-tree')


def _identity(descriptor: int) -> tuple[str, int, tuple]:
    before = os.fstat(descriptor)
    paths.regular(before)
    require(0 < before.st_size <= MAX_FRONTEND, 'authoring-frontend-byte-limit')
    os.lseek(descriptor, 0, os.SEEK_SET)
    checksum, size = hashlib.sha256(), 0
    while raw := os.read(descriptor, 65536):
        size += len(raw)
        require(size <= MAX_FRONTEND, 'authoring-frontend-byte-limit')
        checksum.update(raw)
    after = os.fstat(descriptor)
    stamp = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    require(size == before.st_size and stamp(before) == stamp(after), 'authoring-frontend-changed-during-read')
    return 'sha256:' + checksum.hexdigest(), size, stamp(after)


def _unchanged_path(path: Path, descriptor: int, identity) -> bool:
    try:
        if _identity(descriptor) != identity:
            return False
        with paths.opened(path.parent, path.name) as current:
            return _identity(current) == identity
    except (OSError, ValueError):
        return False


def _result(action: str, code: int, *, mode: str, identity: str, reason: str | None = None,
            cleanup='reaped', original_exit: int | None = None) -> dict:
    result = {'formatVersion': 1, 'stage': 'guest-authoring-' + action, 'exitCode': code,
              'status': 'frontend-completed' if code == 0 else 'frontend-uncertain' if code in {5, 130} else 'frontend-failed',
              'uncertain': code in {5, 130}, 'frontendMode': mode, 'frontendDigest': identity,
              'cleanup': cleanup, 'automaticReplay': False}
    if code in {5, 130}:
        result['remoteCleanupConfirmed'] = False
    if reason is not None:
        result['reason'] = reason
    if original_exit is not None:
        result['originalFrontendExitCode'] = original_exit
    return result


def execute(project: Path, action: str, argv: list[str], *, frontend: Path | None = None,
            expected: str | None = None, timeout_seconds: int = 600) -> Outcome:
    """Preserve uncertain operations; wrapper cleanup never proves remote cleanup.

    The caller supplies the language-validated maintained test/watch arguments.
    An explicit executable must be from an already authenticated installation;
    this exact byte pin selects it and does not grant publisher or recipe trust.
    """
    require(action in {'test', 'watch'}, 'authoring-frontend-operation')
    require(type(timeout_seconds) is int and 1 <= timeout_seconds <= 3600, 'authoring-frontend-time-limit')
    require(isinstance(argv, list) and argv and all(isinstance(value, str) and value and '\0' not in value for value in argv),
            'authoring-frontend-arguments')
    require((frontend is None) == (expected is None), 'authoring-explicit-frontend-identity-required')
    project = paths.absolute(project)
    if frontend is None:
        # A recipe package deliberately omits the controller. Never search PATH
        # or import a separately installed controller from another source tree.
        selected = ROOT / 'tools/dev_workflow/cli.py'
        require(selected.is_file(), 'authoring-staged-recipe-requires-explicit-frontend')
        _source_modules()
        with paths.opened(selected.parent, selected.name) as descriptor:
            identity = _identity(descriptor)
            module = importlib.import_module('tools.dev_workflow.cli')
            require(Path(module.__file__).resolve() == selected, 'authoring-frontend-source-outside-owned-tree')
            _source_modules()
            require(_unchanged_path(selected, descriptor, identity), 'authoring-frontend-changed-during-read')
            code = module.main(argv)
            if code not in {0, 2, 3, 5, 130}:
                return Outcome(5, _result(action, 5, mode='owned-source', identity=identity[0],
                    reason='authoring-frontend-exit-unrecognized-inspect-workspace-status', original_exit=code))
            if not _unchanged_path(selected, descriptor, identity):
                return Outcome(5, _result(action, 5, mode='owned-source', identity=identity[0],
                                          reason='authoring-frontend-mutated-inspect-workspace-status', original_exit=code))
            return Outcome(code, _result(action, code, mode='owned-source', identity=identity[0],
                                         cleanup='frontend-owned'))
    require(isinstance(expected, str), 'authoring-explicit-frontend-identity-required')
    sha(expected)
    frontend = paths.absolute(frontend)
    require(not frontend.is_relative_to(project), 'authoring-frontend-must-stay-outside-project')
    with paths.opened(frontend.parent, frontend.name) as descriptor:
        identity = _identity(descriptor)
        require(identity[0] == expected, 'authoring-frontend-digest-mismatch')
        with tempfile.TemporaryDirectory(prefix='lsf-authoring-frontend-') as temporary:
            environment = build_environment(Path(temporary))
            # Keep normal installed state roots; omit ambient production tokens,
            # Python import hooks and loader overrides from the delegate.
            environment.pop('CARGO_HOME', None)
            environment.pop('RUSTUP_HOME', None)
            try:
                result = run_bounded_result([str(frontend), *argv], project, environment,
                                            timeout_seconds, MAX_OUTPUT)
            except BuildProcessError as error:
                cleanup = 'reaped' if error.reason in {'command-deadline', 'command-output-limit'} else 'unconfirmed'
                return Outcome(5, _result(action, 5, mode='standalone', identity=expected,
                    reason='authoring-frontend-unresolved-inspect-workspace-status', cleanup=cleanup))
            except KeyboardInterrupt:
                return Outcome(130, _result(action, 130, mode='standalone', identity=expected,
                    reason='authoring-frontend-interrupted-inspect-workspace-status'))
        if not _unchanged_path(frontend, descriptor, identity):
            code, reason = 5, 'authoring-frontend-mutated-inspect-workspace-status'
        else:
            code, reason = result.returncode, None
            try:
                value = decode(result.stdout.splitlines()[-1])
                valid = (isinstance(value, dict) and value.get('schemaVersion') == 'latent.dev.result.v1'
                         and isinstance(value.get('code'), str) and code in {0, 2, 3, 5, 130}
                         and (code != 0 or value.get('code') == 'success')
                         and (code != 3 or value.get('code') == 'required-tests-failed')
                         and (code not in {0, 2, 3} or value.get('uncertain') is not True)
                         and (code not in {5, 130} or value.get('uncertain') is True))
            except (ValueError, KeyError, TypeError, IndexError):
                valid = False
            if not valid:
                code, reason = 5, 'authoring-frontend-protocol-invalid-inspect-workspace-status'
        evidence = _result(action, code, mode='standalone', identity=expected, reason=reason,
                           original_exit=result.returncode if code != result.returncode else None)
        evidence.update(stdoutDigest='sha256:' + hashlib.sha256(result.stdout).hexdigest(),
                        stderrDigest='sha256:' + hashlib.sha256(result.stderr).hexdigest(),
                        stdoutBytes=len(result.stdout), stderrBytes=len(result.stderr))
        return Outcome(code, evidence, result.stdout, result.stderr)


def emit(outcome: Outcome) -> None:
    for target, raw in ((sys.stdout, outcome.stdout), (sys.stderr, outcome.stderr)):
        if raw:
            if hasattr(target, 'buffer'):
                target.buffer.write(raw)
                target.buffer.flush()
            else:
                target.write(raw.decode('utf-8', 'replace'))
