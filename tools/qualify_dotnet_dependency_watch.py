#!/usr/bin/env python3
"""Exercise delivered .NET dependency authoring through the maintained watcher.

Run with the delivered Python, as an unprivileged Linux user in a compiler-contained
fixture with explicit native .NET registry fetch. The supplied helper and native node are explicit source fixtures;
this programme does not manufacture publisher authentication or installation.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import importlib.util
import json
import itertools
import re
import stat
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()


def require(value, reason):
    if not value:
        raise ValueError(reason)


def write(path: Path, value) -> None:
    path.write_text(json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8')


# Only actual producer enums and numeric statuses may leave the private build.
_FAILURE_STAGES = frozenset({'capture', 'resource-inputs', 'contracts', 'compiler-inputs',
    'executable-input-approval', 'compile', 'compatibility', 'package', 'recheck'})
_COMMAND_STAGES = frozenset({'contracts', 'dotnet-version', 'wasm-tools-version',
    'wit-bindgen-version', 'dotnet-sdks', 'nuget-content-hash', 'component-composer-version',
    'declared-runtime-wit', 'bindings', 'bindings-drift', 'canonical-wit', 'locked-restore',
    'native-aot', 'native-runtime-wit', 'closed-runtime-composition', 'validate',
    'runtime-final-wit', 'surface', 'package', 'inspect'})
_CONTROL_REASONS = frozenset({'guest-build-failed-last-deployment-retained',
    'guest-build-cleanup-unconfirmed', 'language-adapter-result-invalid', 'build-deadline-exceeded',
    'owned-process-cleanup-unconfirmed', 'guest-build-cancelled', 'guest-build-superseded',
    'build-interrupted', 'build-complete', 'guest-restarted-build-interrupted'})


# Exact static raises from the inspected compile setup helpers. Dynamic messages,
# prefixes and other stages are deliberately excluded. A code is usable only
# after the retained tool inventory and build recipe bind its actual helper.
_COMPILE_REASON_PRODUCERS = {
    'tools/dotnet_guest/sdk.py': {'helper': 'dotnet-sdk-facades', 'codes': {
        'ambiguous generated C# world namespace': 'dotnet-generated-world-namespace-ambiguous',
        'intent staging requires the canonical imported state owner': 'dotnet-intent-canonical-state-owner-required',
    }},
    'tools/dotnet_guest/compiler.py': {'helper': 'dotnet-compiler-resources', 'codes': {
        'nuget-compiler-resource-preimage-mismatch': 'nuget-compiler-resource-preimage-mismatch',
    }},
    'tools/dotnet_application_dependencies.py': {'helper': 'dotnet-application-dependencies', 'codes': {
        'dotnet-executable-resource-not-selected-original': 'dotnet-executable-resource-not-selected-original',
        'dotnet-executable-resource-preimage-mismatch': 'dotnet-executable-resource-preimage-mismatch',
        'dotnet-package-asset-policy-invalid': 'dotnet-package-asset-policy-invalid',
        'dotnet-package-reference-ambiguous': 'dotnet-package-reference-ambiguous',
        'dotnet-package-reference-not-reviewed': 'dotnet-package-reference-not-reviewed',
        'dotnet-package-version-not-native-literal': 'dotnet-package-version-not-native-literal',
        'dotnet-project-build-target-not-reviewed': 'dotnet-project-build-target-not-reviewed',
        'dotnet-project-declaration-limit': 'dotnet-project-declaration-limit',
        'dotnet-project-input-outside-reviewed-recipe': 'dotnet-project-input-outside-reviewed-recipe',
        'dotnet-project-item-metadata-invalid': 'dotnet-project-item-metadata-invalid',
        'dotnet-project-sdk-compiler-input-mutated': 'dotnet-project-sdk-compiler-input-mutated',
        'dotnet-project-sdk-not-reviewed': 'dotnet-project-sdk-not-reviewed',
        'dotnet-resource-input-not-captured': 'dotnet-resource-input-not-captured',
        'dotnet-resource-item-not-reviewed': 'dotnet-resource-item-not-reviewed',
        'dotnet-resource-logical-name-invalid': 'dotnet-resource-logical-name-invalid',
        'nuget-captured-package-closure-not-native-selection': 'nuget-captured-package-closure-not-native-selection',
        'nuget-captured-package-not-native-original': 'nuget-captured-package-not-native-original',
        'nuget-feed-trust-identity-invalid': 'nuget-feed-trust-identity-invalid',
        'nuget-native-asset-file-limit': 'nuget-native-asset-file-limit',
        'nuget-native-asset-metadata-invalid': 'nuget-native-asset-metadata-invalid',
        'nuget-native-asset-package-identity-mismatch': 'nuget-native-asset-package-identity-mismatch',
        'nuget-native-assets-invalid': 'nuget-native-assets-invalid',
        'nuget-native-assets-or-resource-selection-drift': 'nuget-native-assets-or-resource-selection-drift',
        'nuget-native-content-hash-conflict': 'nuget-native-content-hash-conflict',
        'nuget-native-content-hash-invalid': 'nuget-native-content-hash-invalid',
        'nuget-native-dependency-unresolved': 'nuget-native-dependency-unresolved',
        'nuget-native-framework-runtime-selection-invalid': 'nuget-native-framework-runtime-selection-invalid',
        'nuget-native-json-duplicate-field': 'nuget-native-json-duplicate-field',
        'nuget-native-json-invalid': 'nuget-native-json-invalid',
        'nuget-native-json-limit': 'nuget-native-json-limit',
        'nuget-native-lock-assets-version-invalid': 'nuget-native-lock-assets-version-invalid',
        'nuget-native-package-identity-ambiguous': 'nuget-native-package-identity-ambiguous',
        'nuget-native-selected-graph-not-closed': 'nuget-native-selected-graph-not-closed',
        'nuget-native-selection-or-sdk-baseline-drift': 'nuget-native-selection-or-sdk-baseline-drift',
        'nuget-offline-cache-package-collision': 'nuget-offline-cache-package-collision',
        'nuget-offline-native-layout-collision': 'nuget-offline-native-layout-collision',
        'nuget-original-manifest-name-not-native-package': 'nuget-original-manifest-name-not-native-package',
        'nuget-sdk-compiler-runtime-closure-missing': 'nuget-sdk-compiler-runtime-closure-missing',
        'nuget-sdk-compiler-runtime-lock-mutated': 'nuget-sdk-compiler-runtime-lock-mutated',
        'nuget-selected-assembly-missing-managed-cli-header': 'nuget-selected-assembly-missing-managed-cli-header',
        'nuget-selected-asset-missing-from-original-package': 'nuget-selected-asset-missing-from-original-package',
        'nuget-selected-native-asset-runtime-abi-unavailable': 'nuget-selected-native-asset-runtime-abi-unavailable',
    }},
    'tools/captured_compiler_isolation.py': {'helper': 'captured-compiler-isolation', 'codes': {
        'compiler-read-only-inputs-outside-owned-workspace': 'compiler-read-only-inputs-outside-owned-workspace',
    }},
    'tools/dotnet_guest/resources.py': {'helper': 'dotnet-resources', 'codes': {
        'embedded resource compiler template differs from its closed profile': 'dotnet-resource-compiler-template-drift',
    }},
    'tools/dotnet_guest/task_wait.py': {'helper': 'dotnet-task-wait', 'codes': {
        'task-wait-authenticated-async-root-required': 'task-wait-authenticated-async-root-required',
        'task-wait-rewrite-output-drift': 'task-wait-rewrite-output-drift',
    }},
    'tools/dotnet_guest/http_errors.py': {'helper': 'dotnet-http-errors', 'codes': {
        'http-error-port-rewrite-output-drift': 'http-error-port-rewrite-output-drift',
        'http-error-port-rewrite-receipt': 'http-error-port-rewrite-receipt',
        'http-sync-read-authenticated-task-wait-required': 'http-sync-read-authenticated-task-wait-required',
        'http-sync-read-task-wait-source-drift': 'http-sync-read-task-wait-source-drift',
    }},
    'tools/dotnet_guest/entropy.py': {'helper': 'dotnet-entropy', 'codes': {
        'noncrypto-entropy-unreviewed-upstream': 'noncrypto-entropy-unreviewed-upstream',
        'noncrypto-entropy-unsupported-member-preimage': 'noncrypto-entropy-unsupported-member-preimage',
    }},
    'tools/dotnet_guest/managed_entropy.py': {'helper': 'dotnet-managed-entropy', 'codes': {
        'managed-entropy-rewrite-receipt': 'managed-entropy-rewrite-receipt',
        'managed-entropy-staged-source-drift': 'managed-entropy-staged-source-drift',
    }},
}


def _failure_file(root, relative, maximum):
    """Read only one fixed, anchored regular file; missing files are optional."""
    from tools.dev_workflow import paths
    parts = paths.relative(relative).split('/')
    parent = root
    with ExitStack() as held:
        for index, part in enumerate(parts):
            held.enter_context(paths.directory(parent))
            path = parent / part
            try:
                metadata = path.lstat()
            except FileNotFoundError:
                return None
            if index < len(parts) - 1:
                require(stat.S_ISDIR(metadata.st_mode)
                    and not getattr(metadata, 'st_file_attributes', 0) & 0x400,
                    'failure-projection-unsafe-parent')
            else:
                paths.regular(metadata)
            parent = path
        return paths.read(root, relative, maximum)


def _bound_compile_reason(builds, entry_name, output, selected, failure):
    """Bind an exact static producer code; never interpret arbitrary failure text."""
    from tools.dev_workflow import paths, tool_inventory
    from tools.dev_workflow.common import decode, digest, sha
    if (type(failure) is not dict or type(failure.get('formatVersion')) is not int
            or failure['formatVersion'] != 1 or failure.get('stage') != 'compile'
            or type(failure.get('reason')) is not str):
        return {}, []
    matched = [(name, producer) for name, producer in _COMPILE_REASON_PRODUCERS.items()
               if failure['reason'] in producer['codes']]
    if len(matched) != 1:
        return {}, []
    name, producer = matched[0]
    descriptor = selected['descriptor']
    recorded = descriptor['build'].get('inventory')
    if recorded is None:
        return {}, []
    inventory_path = entry_name + '/tool-inventory.json'
    recipe_path = entry_name + '/source/' + output + '/recipe-inputs.json'
    inventory_raw = _failure_file(builds, inventory_path, tool_inventory.MAX_DOCUMENT)
    recipe_raw = _failure_file(builds, recipe_path, tool_inventory.MAX_DOCUMENT)
    if inventory_raw is None or recipe_raw is None:
        return {}, []
    require(digest(inventory_raw) == recorded['sha256'], 'failure-projection-producer-identity')
    inventory = tool_inventory.validate(decode(inventory_raw, tool_inventory.MAX_DOCUMENT),
        'dotnet', 549, 'linux-x86_64', host_abi=descriptor['hostAbi'])
    require(descriptor['language'] == 'dotnet' and descriptor['template']['ownerIssue'] == 549
        and type(descriptor['template']['ownerIssue']) is int
        and inventory['sourceCommit'] == descriptor['template']['revision'],
        'failure-projection-producer-identity')
    recipe = decode(recipe_raw, tool_inventory.MAX_DOCUMENT)
    require(type(recipe) is dict and 0 < len(recipe) <= tool_inventory.MAX_FILES,
        'failure-projection-producer-schema')
    for path, row in recipe.items():
        paths.relative(path)
        require(type(row) is dict and set(row) == {'digest', 'size'}
            and type(row['size']) is int and 0 <= row['size'] <= 4 * 1024 * 1024,
            'failure-projection-producer-schema')
        sha(row['digest'])
    files = {row['path']: row for row in inventory['files']}
    source_root = Path(__file__).resolve().parents[1]
    evidence = [(builds, inventory_path, tool_inventory.MAX_DOCUMENT, inventory_raw),
                (builds, recipe_path, tool_inventory.MAX_DOCUMENT, recipe_raw)]
    # The serializer, call path and code's own helper must all be this version.
    for helper in dict.fromkeys(('tools/dotnet_guest/build.py', 'tools/dotnet_guest/compiler.py', name)):
        data = _failure_file(source_root, helper, 4 * 1024 * 1024)
        require(data is not None, 'failure-projection-producer-identity')
        identity = {'digest': digest(data), 'size': len(data)}
        require(recipe.get(helper) == identity and files.get('recipe/' + helper) ==
            {'path': 'recipe/' + helper, 'sha256': identity['digest'], 'size': identity['size']},
            'failure-projection-producer-identity')
        evidence.append((source_root, helper, 4 * 1024 * 1024, data))
    return {'reasonCode': producer['codes'][failure['reason']],
        'reasonProducer': {'helper': producer['helper'], 'digest': recipe[name]['digest']}}, evidence


def _public_build_failure(value):
    if (type(value) is not dict or type(value.get('formatVersion')) is not int
            or value['formatVersion'] != 1):
        return {}
    result = {}
    if type(value.get('stage')) is str and value['stage'] in _FAILURE_STAGES:
        result['stage'] = value['stage']
    # No arbitrary reason, command, path or hash of private text is published.
    if type(value.get('reason')) is str and value['reason'] in {
            'command-deadline', 'command-output-limit', 'process-cleanup', 'process-ownership',
            'KeyboardInterrupt', 'SystemExit', 'FileNotFoundError', 'PermissionError',
            'OSError', 'RuntimeError', 'TypeError', 'KeyError'}:
        result['reasonCode'] = value['reason']
    commands = value.get('commands')
    if type(commands) is list and len(commands) <= 512:
        result['commands'] = []
        for command in commands[-8:]:
            if (type(command) is dict and type(command.get('stage')) is str
                    and command['stage'] in _COMMAND_STAGES
                    and type(command.get('exitCode')) is int
                    and -255 <= command['exitCode'] <= 255):
                result['commands'].append({'stage': command['stage'], 'exitCode': command['exitCode']})
    return result


_PROJECTION_PHASES = frozenset({'workspace-owner', 'control-lock', 'control-state', 'project-selection',
    'attempt-inventory', 'attempt-owner', 'failure-document', 'failure-producer', 'adapter-result', 'final-state'})
_PROJECTION_REFUSALS = frozenset({'bound', 'owner', 'schema', 'changed', 'missing-or-unsafe',
    'missing', 'access', 'busy', 'unavailable'})


class _ProjectionRefusal(Exception):
    def __init__(self, phase, refusal):
        self.phase, self.refusal = phase, refusal


def _projection_refusal(error):
    # Match only fixed producer/reader codes; never publish an exception message.
    code = error.args[0] if len(error.args) == 1 and type(error.args[0]) is str else None
    if code in {'file-byte-limit', 'document-byte-limit', 'document-complexity-limit',
                'failure-projection-attempt-limit'}:
        return 'bound'
    if code in {'workspace-owner-mismatch', 'private-state-directory-required',
                'single-link-regular-file-required', 'reparse-point-rejected',
                'unowned-build-attempt', 'failure-projection-producer-identity', 'failure-projection-workspace-owner',
                'failure-projection-owned-attempt', 'failure-projection-unsafe-parent',
                'reparse-or-file-type-rejected'}:
        return 'owner'
    if code in {'invalid-json', 'duplicate-field', 'nonfinite-number', 'active-build-state',
                'build-attempt-state', 'build-request-identity', 'invalid-sha256',
                'document-object-required', 'unknown-or-missing-field', 'failure-projection-producer-schema'}:
        return 'schema'
    if code in {'source-changed-during-read', 'failure-projection-state-changed'}:
        return 'changed'
    if code in {'source-file-unavailable-or-unsafe', 'windows-protected-open-failed'}:
        return 'missing-or-unsafe'
    if isinstance(error, FileNotFoundError):
        return 'missing'
    if isinstance(error, PermissionError):
        return 'access'
    if isinstance(error, (BlockingIOError, TimeoutError)):
        return 'busy'
    if isinstance(error, (KeyError, TypeError)):
        return 'schema'
    return 'unavailable'


def collect_build_failure_metadata(workspace):
    observed = {'phase': 'workspace-owner'}
    try:
        return _collect_build_failure_metadata(workspace, observed)
    except Exception as error:
        raise _ProjectionRefusal(observed['phase'], _projection_refusal(error)) from None


def _collect_build_failure_metadata(workspace, observed):
    """Inspect only this owned workspace/current selection, without executing a recipe."""
    from tools.dev_workflow import build_cache, paths, state
    from tools.dev_workflow.common import DevError, decode, sha
    from tools.dev_workflow import build_control
    with paths.directory(workspace):
        require(state.workspace(workspace.parent, workspace.name) == workspace,
                'failure-projection-workspace-owner')
        # The build creates this lock. Do not create a new workspace/control owner.
        observed['phase'] = 'control-lock'
        paths.read(workspace, 'build-control.lock', 1)
        with state.lock(workspace, 'build-control.lock', timeout=1):
            observed['phase'] = 'control-state'
            active = build_control.status(workspace)
            result = {'qualification': False, 'state': active['state'], 'attempts': []}
            if type(active.get('reason')) is str and active['reason'] in _CONTROL_REASONS:
                result['reasonCode'] = active['reason']
            if active['state'] not in {'reaped', 'uncertain'}:
                return result
            observed['phase'] = 'project-selection'
            selected = state.load(workspace, 'project.json')
            source, recipe = sha(selected['snapshot']), sha(selected['trust'])
            output = paths.relative(selected['descriptor']['build']['outputRoot'])
            builds = workspace / 'builds'
            observed['phase'] = 'attempt-inventory'
            with paths.directory(builds):
                entries = list(itertools.islice(builds.iterdir(), build_cache.MAX_ATTEMPTS + 1))
                require(len(entries) <= build_cache.MAX_ATTEMPTS, 'failure-projection-attempt-limit')
                for entry in sorted(entries):
                    observed['phase'] = 'attempt-owner'
                    require(re.fullmatch('[0-9a-f]{32}', entry.name), 'failure-projection-owned-attempt')
                    with paths.directory(entry):
                        owner = build_cache.owner(entry)
                        if (owner['state'] not in {'failed', 'uncertain'}
                                or owner['source'] != source or owner['recipe'] != recipe):
                            continue
                        row = {'state': owner['state'], 'source': source, 'recipe': recipe, 'buildKey': owner['key']}
                        prefix = entry.name + '/source/'
                        observed['phase'] = 'failure-document'
                        raw = _failure_file(builds, prefix + output + '/BUILD-FAILED.json', 65536)
                        evidence = []
                        row['failureDocument'] = 'missing'
                        if raw is not None:
                            failure = decode(raw, 65536)
                            projected = _public_build_failure(failure)
                            row['failureDocument'] = ('observed' if type(failure) is dict
                                and type(failure.get('formatVersion')) is int and failure['formatVersion'] == 1 else 'invalid')
                            row.update(projected)
                            observed['phase'] = 'failure-producer'
                            reason, evidence = _bound_compile_reason(builds, entry.name, output, selected, failure)
                            row.update(reason)
                            if reason:
                                evidence.append((builds, prefix + output + '/BUILD-FAILED.json', 65536, raw))
                        observed['phase'] = 'adapter-result'
                        row['adapterResult'] = 'missing'
                        try:
                            raw = _failure_file(builds, prefix + 'build-cache/compiler-stdout.log', 262144)
                        except DevError as error:
                            if error.code != 'file-byte-limit':
                                raise
                            raw = None
                            row.update(adapterResult='invalid', adapterRefusal='bound')
                        if raw is not None:
                            row['adapterResult'] = 'invalid'
                            try:
                                adapter = decode(raw)
                            except DevError as error:
                                refusal = _projection_refusal(error)
                                if refusal not in {'bound', 'schema'}:
                                    raise
                                row['adapterRefusal'] = refusal
                                adapter = None
                            if (type(adapter) is dict and set(adapter) == {'schemaVersion', 'language', 'ownerIssue', 'cleanup', 'code'}
                                    and adapter['schemaVersion'] == 'latent.dev.compiler-result.v1'
                                    and adapter['language'] == 'dotnet' and type(adapter['ownerIssue']) is int
                                    and adapter['ownerIssue'] == 549 and type(adapter['code']) is str
                                    and adapter['code'] in {'success', 'compiler-process-failed', 'compiler-cleanup-unconfirmed',
                                        'compiler-cancelled', 'compiler-input-or-build-failed'}
                                    and adapter['cleanup'] == ('uncertain' if adapter['code'] == 'compiler-cleanup-unconfirmed' else 'reaped')):
                                row['adapterCode'], row['adapterCleanup'] = adapter['code'], adapter['cleanup']
                                row['adapterResult'] = 'observed'
                        observed['phase'] = 'final-state'
                        for root, relative, maximum, data in evidence:
                            require(_failure_file(root, relative, maximum) == data, 'failure-projection-state-changed')
                        require(build_cache.owner(entry) == owner, 'failure-projection-state-changed')
                        result['attempts'].append(row)
            observed['phase'] = 'final-state'
            require(state.load(workspace, 'project.json') == selected, 'failure-projection-state-changed')
            require(build_control.status(workspace) == active, 'failure-projection-state-changed')
            return result


def add_public_build_failure(public, workspace):
    """A failed observation must never replace the original failure or uncertainty."""
    if public.get('passed') is not False or workspace is None:
        return
    try:
        public['buildFailureMetadata'] = collect_build_failure_metadata(workspace)
    except Exception as error:
        value = {'qualification': False, 'status': 'unavailable'}
        if (type(error) is _ProjectionRefusal and type(error.phase) is str and error.phase in _PROJECTION_PHASES
                and type(error.refusal) is str and error.refusal in _PROJECTION_REFUSALS):
            value.update(readerPhase=error.phase, refusal=error.refusal)
        public['buildFailureMetadata'] = value


class ShutdownOnce:
    """Fence an external shutdown before dispatch, including uncertain failure."""
    def __init__(self):
        self.attempted = False

    def call(self, operation):
        require(not self.attempted, 'watch-down-already-attempted-no-retry')
        self.attempted = True
        return operation()


def write_frontend(frontend, python, args, events):
    frontend.write_text('#!' + str(python) + ' -IB' + '''
import hashlib,io,pathlib,sys
p=pathlib.Path(''' + repr(str(args.helper)) + ''')
assert 'sha256:'+hashlib.sha256(p.read_bytes()).hexdigest()==''' + repr(args.helper_sha256) + '''
class Tee(io.RawIOBase):
    def writable(self): return True
    def write(self,raw):
        with open(''' + repr(str(events)) + ''','ab',buffering=0) as out: out.write(raw)
        sys.__stdout__.buffer.write(raw); sys.__stdout__.buffer.flush()
        return len(raw)
sys.stdout=io.TextIOWrapper(Tee(),encoding='utf-8',write_through=True)
sys.path.insert(0,str(p))
from tools.dev_workflow.cli import main
raise SystemExit(main())
''', encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installed', required=True, type=Path)
    parser.add_argument('--helper', required=True, type=Path)
    parser.add_argument('--helper-sha256', required=True)
    parser.add_argument('--source-probe', required=True, type=Path)
    parser.add_argument('--source-probe-sha256', required=True)
    parser.add_argument('--source-node', required=True, type=Path)
    parser.add_argument('--fixture-source', required=True, type=Path)
    parser.add_argument('--fixture-sha256', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    require(sys.platform == 'linux' and os.geteuid() != 0, 'unprivileged-linux-required')
    require(not args.output.exists(), 'fresh-output-required')
    args.output.mkdir(mode=0o700)
    root = args.output.resolve()
    shutil.copyfile(__file__, root / 'qualifier-source.py')
    require(digest(args.helper) == args.helper_sha256, 'source-helper-changed')
    require(digest(args.source_probe) == args.source_probe_sha256, 'source-probe-changed')
    sys.path.insert(0, str(args.helper))
    from tools.dev_workflow import paths, project, state
    from tools.dev_workflow.common import decode
    module_spec = importlib.util.spec_from_file_location('source_node_probe', args.source_probe)
    source_probe = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(source_probe)
    require(digest(args.fixture_source) == args.fixture_sha256, 'fixture-source-changed')
    fixture_spec = importlib.util.spec_from_file_location('dotnet_watch_inputs', args.fixture_source)
    fixture = importlib.util.module_from_spec(fixture_spec)
    fixture_spec.loader.exec_module(fixture)
    installed = args.installed.resolve()
    python = installed / 'sdk/bin/python'
    dotnet_cli = installed / 'recipe/tools/dotnet_capsule.py'
    fixed_inputs = {str(p): digest(p) for p in (Path(__file__), python, dotnet_cli, args.helper, args.source_probe,
        args.fixture_source, installed / 'guest-tools.json', installed / 'sdk/managed-inputs.json', installed / 'sdk/managed.zip')}
    report = {'schemaVersion': 'latent.dotnet.dependency-watch-qualification.v1', 'passed': False,
        'publisherAuthenticated': False, 'cleanHost': False, 'sourceCandidate': True,
        'admission': 'explicit-signed-fixture-per-reviewed-build',
        'resolverNetwork': 'explicit-native-registry-fetch',
        'compilerNetwork': 'required-captured-compiler-network-namespace-denied',
        'ambientPath': os.environ.get('PATH'), 'uid': os.geteuid(), 'inputs': fixed_inputs,
        'sourceNode': json.loads((args.source_node / 'source-node.json').read_bytes()),
        'commands': [], 'stages': [], 'phase': 'prepare'}
    began = time.monotonic()
    watcher = None
    node_root = None
    shutdown = ShutdownOnce()
    frontend = root / 'latent-dev-source'
    events = root / 'frontend-events.jsonl'
    controller = root / 'controller'
    workspace_prefix = 'test-dotnet-lib-' + root.name
    workspace_name = workspace_prefix + '-initial'
    application = root / 'application'
    env = {'PATH': '/nonexistent', 'HOME': str(Path.home()), 'LANG': 'C.UTF-8',
           'TMPDIR': str(root), 'TEMP': str(root), 'TMP': str(root)}

    def command(label, argv, *, timeout=1000, expected=0):
        require(time.monotonic() - began < 2400, 'qualification-total-deadline')
        result = subprocess.run([str(item) for item in argv], cwd=root, env=env,
                                capture_output=True, timeout=timeout)
        require(len(result.stdout) + len(result.stderr) <= 1024 * 1024, 'command-output-limit')
        (root / (label + '.stdout')).write_bytes(result.stdout)
        (root / (label + '.stderr')).write_bytes(result.stderr)
        report['commands'].append({'id': label, 'exitCode': result.returncode,
            'stdout': digest(root / (label + '.stdout')), 'stderr': digest(root / (label + '.stderr'))})
        write(root / 'qualification.json', report)
        require(result.returncode == expected, label + '-failed')
        return result

    def author(label, *arguments):
        native = ['--dotnet', resolver_dotnet, '--tools', managed / 'tools', '--feed-config', feed_policy, '--update-lock'] if arguments[0] == 'resolve' else []
        return command(label, [python, '-I', '-B', dotnet_cli, *arguments, *native])

    def front(label, operation, *arguments):
        return command(label, [frontend, '--state-root', controller, 'dev', operation,
                               '--workspace', workspace_name, *arguments])

    def observed():
        raw = events.read_bytes() if events.exists() else b''
        require(len(raw) <= 4 * 1024 * 1024, 'watch-event-byte-limit')
        result = []
        for line in raw.splitlines():
            try:
                result.append(json.loads(line))
            except ValueError:
                pass  # A bounded observer can overlap a partial output write.
        return result

    def await_event(offset, predicate, label, timeout=1000):
        deadline = min(began + 2400, time.monotonic() + timeout)
        while time.monotonic() < deadline:
            values = observed()
            for index, value in enumerate(values[offset:], offset):
                if predicate(value):
                    return index + 1, value
            require(watcher is not None and watcher.poll() is None, 'watch-exited-before-' + label)
            time.sleep(0.2)
        raise ValueError('watch-event-deadline-' + label)

    def tests(expected):
        location = application / 'tests'
        (location / 'library-input.json').write_bytes(b'["SDK"]')
        (location / 'library-expected.json').write_bytes(json.dumps([{'ok': expected}], separators=(',', ':')).encode())
        selected_random = location / 'random-fixture.json'
        write(selected_random, {'random': {'maximumOperations': 16, 'maximumOutputBytes': 4096}})
        write(location / 'scenarios.json', {'schemaVersion': 'latent.dev.scenarios.v1', 'scenarios': [{
            'id': 'dependency-output', 'service': 'examples/my-greeting',
            'contract': 'examples:greeting/api@1.0.0', 'function': 'greet',
            'input': 'tests/library-input.json', 'mediaType': 'application/vnd.latent.wit-values.v1+json',
            'expect': {'category': 'success', 'payload': 'tests/library-expected.json'},
            'requires': ['clock', 'random'],
            'execution': {'grants': ['latent:clock/monotonic@0.1.0', 'latent:random/random@0.1.0']},
            'timeoutMillis': 5000, 'required': True, 'fixtures': [{
                'id': 'resource-hash-entropy', 'kind': 'real-provider',
                'identity': digest(selected_random), 'configuration': 'tests/random-fixture.json'}]}]})

    def review(label):
        candidate = root / (label + '-candidate.json')
        author(label + '-resolve', 'resolve', application, '--candidate', candidate)
        author(label + '-review', 'review-lock', application, '--candidate', candidate,
               '--expect', digest(candidate))
        author(label + '-offline-status', 'dependencies', application)

    def after_deploy(offset, label):
        offset, deployed = await_event(offset, lambda value: value.get('event') == 'deployed', label)
        offset, tested = await_event(offset, lambda value: value.get('event') == 'post-deploy-tests', label + '-test')
        require(tested['passed'] is True and tested['report']['passed'] is True,
                label + '-actual-node-test-failed')
        report['stages'].append({'id': label, 'deployment': deployed['deployment'], 'tests': tested['report'],
                                 'build': deployed['build']})
        write(root / 'qualification.json', report)
        return offset

    def start_watch(label):
        nonlocal workspace_name, watcher, shutdown, node_root
        require(watcher is None or watcher.poll() is not None, 'previous-watch-owner-not-retired')
        shutdown = ShutdownOnce()
        workspace_name = workspace_prefix + '-' + label
        node_root = source_probe.helper.root_directory() / workspace_name
        front(label + '-connect', 'connect', '--backend-config', root / 'backend.json')
        require(state.workspace(source_probe.helper.root_directory(), workspace_name, create=True) == node_root,
                'explicit-source-node-workspace-mismatch')
        source_probe.stage_runtime(node_root, args.source_node)
        front(label + '-trust', 'trust', '--project', application)
        front(label + '-build', 'build', '--project', application, '--tool-root', installed)
        front(label + '-prepare-explicit-signed-profile', 'prepare-test', '--consent-test-fixtures',
              '--admission', 'signed-fixture', '--tool-root', installed,
              '--fixtures', application / 'tests/random-fixture.json')
        offset = len(observed())
        watch_command = [python, '-I', '-B', dotnet_cli, 'watch', application, '--workspace', workspace_name,
            '--state-root', controller, '--tool-root', installed, '--select', 'dependency-output',
            '--frontend', frontend, '--frontend-sha256', digest(frontend), '--frontend-timeout', '1800']
        with (root / (label + '-watch.stdout')).open('xb') as stdout, (root / (label + '-watch.stderr')).open('xb') as stderr:
            watcher = subprocess.Popen([str(item) for item in watch_command], cwd=root, env=env,
                                       stdout=stdout, stderr=stderr, start_new_session=True)
        return after_deploy(offset, label)

    def stop_watch(label):
        stopped = json.loads(shutdown.call(lambda: front(label + '-normal-down', 'down')).stdout)['result']
        require(stopped['state'] == 'stopped' and stopped.get('reaped') is True
                and stopped.get('cleanShutdown') is True, 'normal-node-shutdown-unconfirmed')
        watcher.wait(timeout=30)
        require(watcher.returncode == 0, 'dotnet-authoring-watch-did-not-complete-normally')
        report.setdefault('shutdowns', []).append({'id': label, 'result': stopped, 'watchExitCode': watcher.returncode})

    try:
        # No controller or recipe is imported from a checkout. The explicit
        # wrapper verifies the helper and delegates to its unchanged CLI.
        write_frontend(frontend, python, args, events)
        frontend.chmod(0o700)
        report['frontend'] = digest(frontend)
        template_entry = decode((installed / 'templates.json').read_bytes())['templates']['greeting']
        template_root = installed / template_entry['path']
        project.scaffold(template_root, application, decode((template_root / 'template.json').read_bytes()),
                         template_entry['identity'])
        unpack = ('import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);'
                  'from tools.dev_managed_tools import unpack;unpack(Path(sys.argv[2]),Path(sys.argv[3]),lambda:None)')
        managed = root / 'resolver-tools'
        command('delivered-compiler-unpack', [python, '-I', '-B', '-c', unpack,
            installed / 'recipe', installed / 'sdk', managed])
        resolver_dotnet = managed / 'dotnet/dotnet'
        require(resolver_dotnet.is_file(), 'delivered-pinned-dotnet-compiler-required')
        fixed_inputs[str(resolver_dotnet)] = digest(resolver_dotnet)
        # The normal maintained adapter relocates only this private input copy.
        write(managed / 'tools/wasi-sdk.json', {'path': str(managed / 'wasi-sdk')})
        preparation = root / 'library-preparation'
        command('prepare-reviewed-external-libraries', [python, '-I', '-B', args.fixture_source,
            '--app', application / 'app', '--output', preparation,
            '--tools', managed / 'tools', '--dotnet', resolver_dotnet,
            '--sdk-bin', installed / 'sdk/bin', '--recipe', installed / 'recipe'])
        prepared = json.loads((preparation / 'preparation.json').read_bytes())
        inputs = fixture.create(application, prepared)
        feed_policy = root / 'feed-policy.json'
        write(feed_policy, {'sources': [{'name': 'developer', 'path': inputs['feed'], 'patterns': [fixture.PRIMARY]}]})
        report['outsideInputs'] = inputs['inputDigests']
        sdk_lock = application / 'app/sdk-lock.json'
        sdk_identity = digest(sdk_lock)
        author('add-closed-graph', 'add', application, fixture.PRIMARY, '--version', '1.0.0')
        capsule = application / 'app/src/Main.cs'
        capsule.write_text(fixture.application_source(), encoding='utf-8')
        tests('42/SDK/captured watch data')
        review('initial')
        fixture.remove_original(inputs)
        report['originalInputsRemovedBeforeCompile'] = True
        report['phase'] = 'runtime'
        config = root / 'backend.json'
        write(config, {'kind': 'linux', 'python': str(python), 'helper': str(args.helper),
                       'helperSha256': args.helper_sha256})
        report['phase'] = 'watch'
        offset = start_watch('initial')
        fixture.restore_revision(inputs, 2)
        author('update-child', 'update', application, fixture.PRIMARY, '--version', '1.0.1')
        offset, denied = await_event(offset, lambda value: value.get('event') == 'edit-failed', 'unreviewed-update', 30)
        require(denied['uncertain'] is False, 'unreviewed-update-must-be-certain')
        report['updateBeforeReview'] = denied
        review('updated')
        fixture.remove_original(inputs)
        tests('43/SDK/captured watch data')
        offset, denied = await_event(offset, lambda value: value.get('code') == 'workspace-recipe-trust-required',
                                     'updated-recipe-trust', 30)
        report['updateBeforeTrust'] = denied
        front('updated-explicit-trust', 'trust', '--project', application)
        offset, denied = await_event(offset, lambda value: value.get('code') == 'signed-test-build-changed-use-new-workspace',
                                     'updated-signature-boundary')
        report['updateBeforeNewSignedWorkspace'] = denied
        stop_watch('initial')
        offset = start_watch('updated')
        author('remove-closed-graph', 'remove', application, fixture.PRIMARY)
        offset, denied = await_event(offset, lambda value: value.get('event') == 'edit-failed', 'unreviewed-remove', 30)
        require(denied['uncertain'] is False, 'unreviewed-remove-must-be-certain')
        report['removeBeforeReview'] = denied
        capsule.write_text(fixture.application_source(removed=True), encoding='utf-8')
        tests('removed/SDK')
        write(feed_policy, {'sources': []})
        review('removed')
        offset, denied = await_event(offset, lambda value: value.get('code') == 'workspace-recipe-trust-required',
                                     'removed-recipe-trust', 30)
        report['removeBeforeTrust'] = denied
        front('removed-explicit-trust', 'trust', '--project', application)
        offset, denied = await_event(offset, lambda value: value.get('code') == 'signed-test-build-changed-use-new-workspace',
                                     'removed-signature-boundary')
        report['removeBeforeNewSignedWorkspace'] = denied
        stop_watch('updated')
        offset = start_watch('removed')
        front('final-actual-node-test', 'test', '--environment', 'node', '--select', 'dependency-output')
        report['finalStatus'] = json.loads(front('final-status', 'status').stdout)['result']
        stop_watch('removed')
        report['watchExitCode'] = watcher.returncode
        require(digest(sdk_lock) == sdk_identity, 'application-lifecycle-changed-platform-sdk-lock')
        actual_deployments = [row for row in observed() if row.get('event') == 'deployed']
        require(len(actual_deployments) == 3, 'exactly-one-deployment-per-reviewed-selection-required')
        require(all(digest(Path(path)) == identity for path, identity in fixed_inputs.items()), 'tool-input-changed')
        require(digest(args.helper) == args.helper_sha256 and digest(args.source_probe) == args.source_probe_sha256,
                'source-owner-changed')
        report.update(passed=True, phase='complete', deploymentCount=3, cleanup='confirmed-normal-down')
        return 0
    except BaseException as error:
        add_public_build_failure(report, node_root)
        report['failure'] = str(error) if isinstance(error, ValueError) else type(error).__name__
        raise
    finally:
        if watcher is not None and watcher.poll() is None:
            try:
                report['cleanupAfterFailure'] = json.loads(shutdown.call(lambda: front('failure-normal-down', 'down')).stdout)
                watcher.wait(timeout=30)
            except BaseException:
                report['cleanup'] = 'unconfirmed'
                try:
                    try:
                        os.killpg(watcher.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        watcher.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(watcher.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        watcher.wait(timeout=10)
                except BaseException:
                    # Preserve the original command failure; failed observer
                    # retirement cannot establish a clean node shutdown.
                    report['observerCleanup'] = 'unconfirmed'
        report['durationSeconds'] = round(time.monotonic() - began, 6)
        write(root / 'qualification.json', report)
        # Only this bounded projection is suitable for public CI artifacts.
        # Raw workspace state and private signed fixtures stay on the runner.
        public = {key: report[key] for key in (
            'schemaVersion', 'passed', 'publisherAuthenticated', 'cleanHost', 'sourceCandidate',
            'admission', 'resolverNetwork', 'compilerNetwork', 'phase', 'durationSeconds')}
        public.update(qualifier=digest(Path(__file__)), fixture=args.fixture_sha256,
            helper=args.helper_sha256, sourceProbe=args.source_probe_sha256,
            outsideInputs=report.get('outsideInputs', {}),
            originalInputsRemovedBeforeCompile=report.get('originalInputsRemovedBeforeCompile', False),
            deploymentCount=len(report['stages']),
            shutdowns=[{'id': row['id'], 'watchExitCode': row['watchExitCode'],
                        'state': row['result']['state'], 'reaped': row['result']['reaped'],
                        'cleanShutdown': row['result']['cleanShutdown']} for row in report.get('shutdowns', [])],
            stages=[{'id': row['id'], 'passed': row['tests']['passed']} for row in report['stages']])
        if 'buildFailureMetadata' in report:
            public['buildFailureMetadata'] = report['buildFailureMetadata']
        if 'failure' in report:
            public['failure'] = report['failure']
        write(root / 'public-qualification.json', public)


if __name__ == '__main__':
    raise SystemExit(main())
