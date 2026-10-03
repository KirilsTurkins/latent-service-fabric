"""Explicit captured processor selection and a finite isolated source stage."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import shutil
import time

from tools.application_dependency_store import DependencyError, directory_files, read_bytes, regular_path
from tools.application_dependencies import MAX_ARTIFACTS
from tools.build_process import BuildProcessError, run_bounded_result
from tools.build_snapshot import canonical, digest
from tools.captured_compiler_isolation import Isolation
from tools.java_application_dependencies import deterministic_jar, per_jar_metadata, selected_entries

MAX_CLASSES = 32
MAX_PROCESSOR_SECONDS = 60
MAX_GENERATED_BYTES = 16 * 1024 * 1024
CLASS_NAME = re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*\Z')
ALIAS_PROFILE = 'java-processor-closure-alias-v1'
ALIAS_ASSET = 'java-processor-classpath'


def classes(value: object) -> tuple[str, ...]:
    if (not isinstance(value, list) or not 1 <= len(value) <= MAX_CLASSES
            or any(not isinstance(name, str) or len(name) > 256 or not CLASS_NAME.fullmatch(name) for name in value)
            or len(set(value)) != len(value) or len(','.join(value)) > 4096):
        raise DependencyError('java-annotation-processor-class-selection-invalid')
    return tuple(value)


def selection(config: dict, artifacts: list[dict]):
    """Use explicit declarations and graph reachability, never package routing."""
    if len(artifacts) > MAX_ARTIFACTS or len({row['id'] for row in artifacts}) != len(artifacts):
        raise DependencyError('java-annotation-processor-graph-ambiguous-or-limit')
    jars = {row['id']: row for row in artifacts if row['format'] == 'file' and row['mount'].endswith('.jar')}
    graph = {row['id']: row for row in artifacts}
    application_roots, processor_roots, processor_inputs = set(), {}, set()
    for row in config['dependencies']:
        prefix = row['group'] + ':' + row['name'] + ':'
        selected = [identity for identity, artifact in jars.items()
                    if artifact['metadata'].get('ecosystem') == 'maven'
                    and artifact['metadata'].get('coordinates', '').startswith(prefix)]
        if 'processorClasses' in row:
            if len(selected) != 1:
                raise DependencyError('java-annotation-processor-selected-root-ambiguous')
            processor_roots[selected[0]] = classes(row['processorClasses'])
        elif row.get('processorInput') is True:
            if len(selected) != 1:
                raise DependencyError('java-annotation-processor-selected-input-ambiguous')
            processor_inputs.add(selected[0])
        else:
            application_roots.update(selected)
    for row in config['localJars']:
        if row['id'] not in jars:
            raise DependencyError('java-local-jar-not-captured')
        if 'processorClasses' in row:
            processor_roots[row['id']] = classes(row['processorClasses'])
        elif row.get('processorInput') is True:
            processor_inputs.add(row['id'])
        else:
            application_roots.add(row['id'])

    def reachable(roots):
        selected, pending = set(), list(roots)
        while pending:
            identity = pending.pop()
            if identity in selected:
                continue
            if identity not in graph:
                raise DependencyError('java-annotation-processor-graph-not-closed')
            selected.add(identity)
            pending.extend(graph[identity]['dependencies'])
        return selected

    application, processors = reachable(application_roots), reachable(processor_roots)
    if not processor_inputs <= processors:
        raise DependencyError('java-annotation-processor-input-not-reachable')
    if set(processor_roots) & application:
        raise DependencyError('java-annotation-processor-also-selected-as-runtime-root')
    if sum(map(len, processor_roots.values())) > MAX_CLASSES:
        raise DependencyError('java-annotation-processor-class-count-limit')
    selected = {identity: ('build-tool', processor_roots.get(identity, ()))
                if identity in processors - application else ('application', ()) for identity in jars}
    return selected, jars, (application & processors & jars.keys())


def roles(config: dict, artifacts: list[dict]) -> dict[str, tuple[str, tuple[str, ...]]]:
    return selection(config, artifacts)[0]


def alias_id(original: str) -> str:
    return 'java-processor-input:' + digest(canonical({'profile': ALIAS_PROFILE, 'artifact': original}))[7:]


def is_alias(row: dict) -> bool:
    return row['metadata'].get('assetType') == ALIAS_ASSET


def mark(config: dict, artifacts: list[dict]) -> None:
    if any(is_alias(row) for row in artifacts):
        raise DependencyError('java-annotation-processor-capture-already-selected')
    selected, jars, shared = selection(config, artifacts)
    aliases = {identity: alias_id(identity) for identity in sorted(shared)}
    if set(aliases.values()) & {row['id'] for row in artifacts}:
        raise DependencyError('java-annotation-processor-artifact-collision')
    if len(artifacts) + len(aliases) > MAX_ARTIFACTS:
        raise DependencyError('java-annotation-processor-graph-limit')
    children = []
    for original, identity in aliases.items():
        parent = jars[original]
        children.append({'id': identity, 'role': 'build-tool', 'format': 'file',
            'mount': 'dependencies/java/processors/' + identity.split(':', 1)[1] + '.jar',
            'source': copy.deepcopy(parent['source']),
            'dependencies': [aliases.get(edge, edge) for edge in parent['dependencies']],
            'metadata': {'assetType': ALIAS_ASSET, 'profile': ALIAS_PROFILE,
                'originalArtifact': original, 'executableKind': 'java-annotation-processor',
                'processorClasses': []}})
    for row in artifacts:
        if row['id'] not in selected:
            continue
        role, names = selected[row['id']]
        row['role'] = role
        if role == 'build-tool':
            row['metadata'].update(executableKind='java-annotation-processor', processorClasses=list(names))
            row['dependencies'] = [aliases.get(edge, edge) for edge in row['dependencies']]
    artifacts.extend(children)


def verify(config: dict, artifacts: list[dict]) -> list[dict]:
    """Reconstruct every executable alias from its unchanged native JAR owner.

    Shared runtime/processor dependencies retain their ordinary runtime graph and
    resources. A second artifact containing the same original bytes makes each
    processor-classpath input explicit in the existing approval protocol.
    """
    aliases = [row for row in artifacts if is_alias(row)]
    primary = [row for row in artifacts if not is_alias(row)]
    if len(artifacts) > MAX_ARTIFACTS or len({row['id'] for row in artifacts}) != len(artifacts):
        raise DependencyError('java-annotation-processor-graph-ambiguous-or-limit')
    reverse = {}
    for row in aliases:
        original = row['metadata'].get('originalArtifact')
        if not isinstance(original, str) or row['id'] != alias_id(original) or original in reverse.values():
            raise DependencyError('java-annotation-processor-alias-identity-drift')
        reverse[row['id']] = original
    original_rows = copy.deepcopy(primary)
    resources = {}
    for row in original_rows:
        if row['format'] != 'file' or not row['mount'].endswith('.jar'):
            continue
        # These children were added after processor selection and belong to the
        # runtime JAR's immutable resource index, not to javac's processor graph.
        entries = row['metadata'].get('resourceSelection', {}).get('entries', [])
        if (not isinstance(entries, list) or any(not isinstance(entry, dict)
                or not isinstance(entry.get('artifact'), str) for entry in entries)):
            raise DependencyError('java-annotation-processor-resource-child-claim-invalid')
        added = {entry['artifact'] for entry in entries}
        resources[row['id']] = added
        row['dependencies'] = [reverse.get(edge, edge) for edge in row['dependencies'] if edge not in added]
        row['role'] = 'application'
        for field in ('executableKind', 'processorClasses'):
            row['metadata'].pop(field, None)
    mark(config, original_rows)
    expected = {row['id']: row for row in original_rows}
    actual = {row['id']: row for row in artifacts}
    if set(actual) != set(expected):
        raise DependencyError('java-annotation-processor-alias-graph-drift')
    for row in primary:
        if row['format'] != 'file' or not row['mount'].endswith('.jar'):
            continue
        wanted = expected[row['id']]
        if (row['role'] != wanted['role'] or
                set(row['dependencies']) != set(wanted['dependencies']) | resources.get(row['id'], set()) or
                row['metadata'] != wanted['metadata']):
            raise DependencyError('java-annotation-processor-declaration-drift')
    for row in aliases:
        wanted = expected[row['id']]
        parent = actual[wanted['metadata']['originalArtifact']]
        if (any(row[field] != wanted[field] for field in ('id', 'role', 'format', 'mount', 'dependencies', 'metadata'))
                or row['original'] != parent['original'] or row['source'] != parent['source']
                or row['files'] != [{'path': Path(row['mount']).name, **parent['original']}]):
            raise DependencyError('java-annotation-processor-alias-capture-drift')
    return primary


def classpath(closure, destination: Path) -> tuple[tuple[Path, ...], tuple[str, ...], dict]:
    from tools.guest_dependency_inputs import read_native
    from tools.java_dependency_resolution import declarations
    verify(declarations(json.loads(read_native(closure, 'java-dependencies.json'))), closure.lock['artifacts'])
    destination.mkdir()
    paths, names, owners, receipts = [], [], set(), []
    for row in closure.lock['artifacts']:
        if row['role'] != 'build-tool':
            continue
        if (row['format'] != 'file' or not row['mount'].endswith('.jar')
                or row['metadata'].get('executableKind') != 'java-annotation-processor'):
            raise DependencyError('java-executable-tool-kind-unqualified')
        declared = row['metadata'].get('processorClasses')
        if declared != []:
            declared = classes(declared)
        original = read_bytes(closure.work / row['mount'])
        entries = selected_entries(original, 25)
        if any(name.replace('.', '/') + '.class' not in entries for name in declared):
            raise DependencyError('java-annotation-processor-class-not-captured')
        for name in entries:
            if per_jar_metadata(name) or name == 'META-INF/services/javax.annotation.processing.Processor':
                continue
            if name in owners:
                raise DependencyError('java-duplicate-processor-class-or-resource')
            owners.add(name)
        payload = deterministic_jar(entries)
        target = destination / f'{len(paths):04d}.jar'
        target.write_bytes(payload)
        paths.append(target); names.extend(declared)
        receipts.append({'id': row['id'], 'originalDigest': digest(original), 'selectedDigest': digest(payload),
                         'processorClasses': list(declared), 'bytes': len(payload)})
    if not names or len(set(names)) != len(names) or len(','.join(names)) > 4096:
        raise DependencyError('java-annotation-processor-class-selection-invalid')
    return tuple(paths), tuple(names), {'formatVersion': 1, 'profile': 'java-isolated-source-processors-v1',
        'artifacts': receipts, 'classSelection': names, 'automaticHostServiceDiscovery': False}


class ProcessorIsolation(Isolation):
    @staticmethod
    def observe_distribution(root: Path):
        # The maintained Java observer preserves in-root JDK links and rejects
        # escaping targets; do not replace this with an ambient filesystem bind.
        from tools.java_guest.compiler import tool_inventory
        return json.loads(tool_inventory({'distribution': root}))


def isolation(compiler, workspace: Path):
    jdk = compiler.tool_roots['jdk']
    javac = jdk / 'bin/javac'
    selected = ProcessorIsolation(workspace,
        {'javac': javac, 'java': compiler.paths['java'], 'jvm-library': jdk / 'lib/server/libjvm.so'},
        {'pinned-jdk': jdk, 'pinned-java-compiler-dependencies': compiler.directory / 'gradle-home/caches/modules-2'})
    return selected


def compiler_classpath(compiler) -> tuple[Path, ...]:
    from tools.java_guest.compiler import source_module
    dependencies = source_module(compiler.sdk / 'tools/dependencies.py')
    cache = compiler.directory / 'gradle-home/caches/modules-2/files-2.1'
    observed = dependencies.cache_inventory(cache)
    dependencies.verify_inventory(observed, json.loads(read_bytes(compiler.sdk / 'feasibility/dependencies.lock.json')),
                                  compiler.sdk / 'feasibility/gradle/verification-metadata.xml')
    return tuple(sorted(cache.glob('*/*/*/*/*.jar')))


def run_stage(compiler, selected, name: str, tool: Path, arguments: list[str],
              cwd: Path, deadline: float):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise DependencyError('java-annotation-processor-deadline')
    selected.check_unchanged()
    argv = selected.wrap(tool, arguments, cwd, compiler.environment)
    started, exit_code, failure = time.monotonic(), None, None
    try:
        result = run_bounded_result(argv, cwd, compiler.environment, remaining, 1024 * 1024)
        exit_code = result.returncode
        log = result.stdout + b'\n' + result.stderr
        compiler.retained_bytes += len(log)
        if compiler.retained_bytes > 16 * 1024 * 1024:
            raise DependencyError('java-annotation-processor-diagnostic-limit')
        (compiler.directory / f'{len(compiler.records)}-{name}.log').write_bytes(log)
        return result
    except BuildProcessError as error:
        failure = error.reason
        raise
    finally:
        record = {'stage': name, 'command': argv, 'exitCode': exit_code,
                  'seconds': round(time.monotonic() - started, 6)}
        if failure is not None:
            record['processFailure'] = failure
            record['cleanup'] = 'reaped' if failure in {'command-deadline', 'command-output-limit'} else 'unconfirmed'
        elif exit_code is not None:
            record['cleanup'] = 'reaped'
        compiler.records.append(record)
        from tools.rust_capsule_project import write_json
        write_json(compiler.directory / f'{len(compiler.records) - 1}-{name}.command.json', record)


def process(compiler, java_root: Path, application_sources: tuple[str, ...], project: Path,
            stage, application_jars: tuple[Path, ...]) -> dict:
    """Javac processes fresh readonly copies; original compilation uses proc:none."""
    isolation, processor_jars, names, output, compiler_jars = stage
    inputs = isolation.workspace / 'inputs'
    selected_sources = inputs / 'processor-sources'
    shutil.copytree(java_root, selected_sources)
    before = directory_files(selected_sources)
    source_names = [name for name in application_sources if name.endswith('.java')]
    if not source_names or len(source_names) > 512:
        raise DependencyError('java-annotation-processor-source-count-limit')
    control = inputs / 'processor-control/dev/latent/compiler/SourceOwnership.java'
    control.parent.mkdir(parents=True)
    control_bytes = read_bytes(compiler.sdk / 'processors/SourceOwnership.java')
    control.write_bytes(control_bytes)
    arguments = ['-J-Xmx256m', '-J-Djava.awt.headless=true', '-proc:only', '--release', '25',
        '-processor', ','.join(names), '-processorpath', ':'.join(map(str, processor_jars)),
        '-classpath', ':'.join(map(str, (*application_jars, *processor_jars, *compiler_jars))),
        '-sourcepath', str(selected_sources), '-s', str(output / 'generated'), '-d', str(output / 'classes'),
        *[str(selected_sources / name) for name in source_names]]
    (output / 'generated').mkdir(parents=True)
    (output / 'classes').mkdir()
    isolation.protect_inputs(inputs)
    isolation.check_unchanged()
    started = time.monotonic()
    remaining = min(MAX_PROCESSOR_SECONDS, compiler.deadline - started)
    if remaining <= 0:
        raise DependencyError('java-annotation-processor-deadline')
    deadline = started + remaining
    result = run_stage(compiler, isolation, 'annotation-processors', isolation.tools['javac'],
                       arguments, selected_sources, deadline)
    if result.returncode:
        raise DependencyError('java-annotation-processor-stage-failed')
    if directory_files(output / 'classes'):
        raise DependencyError('java-annotation-processor-bytecode-output-unqualified')
    generated = directory_files(output / 'generated')
    if directory_files(output) != {'generated/' + name: data for name, data in generated.items()}:
        raise DependencyError('java-annotation-processor-unqualified-output')
    if len(generated) > 512 or sum(map(len, generated.values())) > MAX_GENERATED_BYTES:
        raise DependencyError('java-annotation-processor-generated-source-limit')
    for name, data in generated.items():
        if not name.endswith('.java') or (java_root / name).exists():
            raise DependencyError('java-annotation-processor-generated-source-collision-or-kind')
        try:
            data.decode('utf-8', 'strict')
        except UnicodeError:
            raise DependencyError('java-annotation-processor-generated-source-encoding') from None
    if directory_files(selected_sources) != before:
        raise DependencyError('java-annotation-processor-readonly-input-mutated')
    # The trusted JDK parser also checks declared class identities. A filename
    # check alone cannot protect a platform class named in a different path or
    # through Java's Unicode escapes. parse() never attributes or loads it.
    manifest = regular_path(output / 'source-ownership.inputs')
    ownership_inputs = (''.join('original\t' + name + '\n' for name in before if name.endswith('.java'))
                        + ''.join('generated\t' + name + '\n' for name in generated)).encode('utf-8')
    with manifest.open('xb') as destination:
        destination.write(ownership_inputs)
    isolation.protect_inputs(output / 'generated')
    checked = run_stage(compiler, isolation, 'processor-source-ownership', isolation.tools['java'],
        ['-Xmx256m', '--source', '25', str(control), str(selected_sources),
         str(output / 'generated'), str(manifest)], selected_sources, deadline)
    if checked.returncode or checked.stdout != b'SOURCE-OWNERSHIP-OK\n':
        raise DependencyError('java-annotation-processor-generated-source-owner-denied')
    if directory_files(selected_sources) != before or directory_files(output / 'generated') != generated:
        raise DependencyError('java-annotation-processor-input-or-output-mutated')
    isolation.check_unchanged()
    for name, data in generated.items():
        target = java_root / name; target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(data)
    return {'formatVersion': 1, 'profile': 'java-isolated-source-processors-v1',
        'maximumSeconds': MAX_PROCESSOR_SECONDS, 'actualMaximumSeconds': remaining,
        'javaHeapMaximumBytes': 256 * 1024 ** 2,
        'inputIdentity': digest(canonical({name: digest(data) for name, data in before.items()})),
        'generated': {name: {'digest': digest(data), 'size': len(data)} for name, data in generated.items()},
        'processorClasses': names, 'isolationInputsDigest': digest(canonical(isolation.receipt)),
        'processorClasspathUsage': 'isolated-javac-and-proc-disabled-compile-only',
        'sourceOwnershipControl': {'digest': digest(control_bytes), 'size': len(control_bytes),
                                   'profile': 'pinned-javac-ast-parse-only-v1'},
        'cleanup': 'reaped', 'network': 'denied', 'credentials': 'not-inherited',
        'outputs': 'new-UTF8-source-only; no bytecode or platform-source overwrite'}
