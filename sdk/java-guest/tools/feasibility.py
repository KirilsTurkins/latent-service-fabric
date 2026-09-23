#!/usr/bin/env python3
"""Compile actual Java to a Component Model candidate; retain failed stages.

A successful compiler probe is NOT LSF guest-authoring qualification. No package
is signed or published and no node admission rule is weakened by this tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sys
import time
import tomllib

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


class ProbeFailure(ValueError):
    """The observed compiler stage failed; see the retained diagnostic."""


def identity(path: Path) -> dict:
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        while data := stream.read(1024 * 1024):
            size += len(data)
            if size > 256 * 1024 * 1024:
                raise ProbeFailure('input-file-size-limit')
            digest.update(data)
    return {"sha256": digest.hexdigest(), "size": size}


def verify_version(stage: str, log: str, expected: str) -> None:
    patterns = {
        'java-version': r'build ([^\s),]+)',
        'gradle-version': r'^Gradle (\S+)$',
        'zig-version': r'^(\S+)$',
        'wit-bindgen-version': r'^wit-bindgen(?:-cli)? (\S+)$',
        'wasm-tools-version': r'^wasm-tools (\S+)',
    }
    values = re.findall(patterns[stage], log, re.MULTILINE)
    if stage == 'java-version':
        values = [v.removesuffix('-LTS') for v in values]
    if not values or set(values) != {expected}:
        raise ProbeFailure(f'{stage}: expected exact version {expected}; observed {values}')


def failure_kind(stage: str, entry: dict) -> str:
    if stage.endswith('-version') or 'spawnError' in entry.get('exit', {}):
        return 'toolchain-preflight'
    if entry.get('exit', {}).get('returncode') in (None, 0):
        return 'probe-infrastructure'
    if stage == 'java-source-test':
        return 'source-self-test'
    return 'candidate-stage-failure'


def source_inputs(root: Path) -> dict:
    inputs = [root / '.github/workflows/java-guest-feasibility.yml', root / 'tools/toolchain.toml', root / 'tools/build_process.py',
              root / 'tools/build_process_linux.py', root / 'tools/build_process_windows.py',
              root / 'tools/build_process_signals.py']
    inputs.extend(p for p in (root / 'sdk/java-guest').rglob('*')
                  if p.is_file() and not set(p.relative_to(root).parts) & {'__pycache__', 'build', '.gradle'})
    inputs.extend(p for p in (root / 'wit/platform').rglob('*.wit'))
    inputs.append(root / 'crates/latent-wasmtime/src/surface.rs')
    return {str(p.relative_to(root)): identity(p) for p in sorted(inputs)}


def new_output(path: Path, root: Path = ROOT) -> Path:
    output = path.resolve()
    root = root.resolve()
    if output == root or (output.is_relative_to(root) and not output.is_relative_to(root / 'target')):
        raise ProbeFailure('output must be outside sources (use target/java-guest-feasibility)')
    # Each attempt has its own immutable evidence directory. Do not overwrite a
    # previous failure, and never recursively delete a caller-supplied path.
    output.mkdir(parents=True, exist_ok=False)
    return output


def probe(output: Path, gradle: str, zig: str, bindgen: str, wasm_tools: str,
          bootstrap_dependencies: bool = False) -> dict:
    config = tomllib.loads((ROOT / 'tools/toolchain.toml').read_text())
    sources = source_inputs(ROOT)
    report = {'formatVersion': 1, 'candidate': 'teavm-0.15.0-c',
              'status': 'running', 'qualified': False, 'lsfExecution': 'not-run',
              'startedAt': int(time.time()), 'sources': sources, 'stages': [],
              'dependencyCompleteness': 'unqualified-transitive-inputs',
              'javaBaseline': config['sdk']['java'],
              'engineBaseline': config['rust']['dependencies']['wasmtime']}
    environment = dict(os.environ)
    environment.update({'GRADLE_USER_HOME': str(output / 'gradle-home'),
                        'TMPDIR': str(output / 'tmp')})
    (output / 'tmp').mkdir()
    project = output / 'project'
    shutil.copytree(ROOT / 'sdk/java-guest/feasibility', project)
    deadline = time.monotonic() + 1200

    def run(stage: str, command: list[str]) -> str:
        from tools.build_process import run_bounded
        entry = {'name': stage, 'command': command, 'status': 'running'}
        report['stages'].append(entry)
        started = time.monotonic()
        try:
            timeout = min(600, deadline - time.monotonic())
            if timeout <= 0:
                raise ProbeFailure('overall compiler probe deadline exceeded')
            status_file = output / (stage + '.exit.json')
            wrapper = ROOT / 'sdk/java-guest/tools/capture.py'
            result = run_bounded([sys.executable, str(wrapper), str(status_file), *command],
                                 project, environment, timeout_seconds=timeout,
                                 max_output_bytes=4 * 1024 * 1024)
            log = result.stdout + b'\n' + result.stderr
            (output / (stage + '.log')).write_bytes(log)
            entry['log'] = identity(output / (stage + '.log'))
            print(log.decode('utf-8', errors='replace'), flush=True)
            status = json.loads(status_file.read_text())
            entry['exit'] = status
            if status != {'returncode': 0}:
                raise ProbeFailure(f'{stage}: {status}')
            entry['status'] = 'passed'
            return result.stdout.decode('utf-8')
        except Exception as error:
            entry.update(status='failed', error=str(error))
            (output / (stage + '.failure.txt')).write_text(str(error) + '\n')
            print(f'{stage}: {error}', file=sys.stderr, flush=True)
            raise ProbeFailure(stage) from error
        finally:
            entry['elapsedMillis'] = round((time.monotonic() - started) * 1000)

    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    try:
        for stage, command, expected in (
            ('java-version', ['java', '-version'], config['sdk']['java']),
            ('gradle-version', [gradle, '--version'], config['sdk']['gradle']),
            ('zig-version', [zig, 'version'], config['sdk']['zig']),
            ('wit-bindgen-version', [bindgen, '--version'], config['rust']['dependencies']['wit-bindgen']),
            ('wasm-tools-version', [wasm_tools, '--version'], config['contracts']['wasm-tools']),
        ):
            run(stage, command)
            try:
                verify_version(stage, (output / (stage + '.log')).read_text(), expected)
            except ProbeFailure as error:
                report['stages'][-1].update(status='failed', error=str(error))
                raise
        verification = ['--write-verification-metadata', 'sha256'] if bootstrap_dependencies else []
        if not bootstrap_dependencies and not (project / 'gradle/verification-metadata.xml').is_file():
            raise ProbeFailure('missing-reviewed-dependency-metadata')
        run('java-source-test', [gradle, '--no-daemon', *verification, 'probeJvm'])
        run('java-to-c', [gradle, '--no-daemon', 'generateC'])
        from dependencies import retain
        try:
            dependencies = retain(output / 'gradle-home/caches/modules-2/files-2.1',
                                  project, output, bootstrap_dependencies)
        except (ValueError, OSError) as error:
            raise ProbeFailure(f'dependency-evidence: {error}') from error
        report['dependencies'] = dependencies
        report['dependencyCompleteness'] = dependencies['status']
        generated = project / 'build/teavm-c/c'
        if not (generated / 'all.c').is_file():
            raise ProbeFailure('missing-generated-c-entrypoint')
        report['generatedC'] = {str(p.relative_to(generated)): identity(p)
                                for p in sorted(generated.rglob('*')) if p.is_file()}
        from teavm_platform import adapt
        try:
            report['platformAdaptation'] = adapt(generated)
        except ValueError as error:
            raise ProbeFailure(str(error)) from error
        from tools.stage_runtime_wit import stage
        stage(output / 'wit', project / 'wit')
        run('wit-bindings', [bindgen, 'c', str(output / 'wit'), '--world', 'capsule',
                            '--rename-world', 'probe', '--out-dir', str(output / 'bindings')])
        core = output / 'probe.core.wasm'
        run('c-to-wasm', [zig, 'cc', '-target', 'wasm32-wasi', '-std=c11', '-O2',
                         '-DLSF_TEAVM_WASM=1', '-DTEAVM_USE_SETJMP=0', '-DTEAVM_CUSTOM_LOG=1',
                         '-mexec-model=reactor', '-Wl,--no-entry', '-Wl,--export-memory',
                         '-Wl,-z,stack-size=65536', '-I', str(output / 'bindings'),
                         '-iquote', str(generated), str(generated / 'all.c'),
                         str(project / 'bridge.c'), str(project / 'platform.c'), str(output / 'bindings/probe.c'),
                         str(output / 'bindings/probe_component_type.o'), '-o', str(core)])
        component = output / 'probe.wasm'
        run('component-new', [wasm_tools, 'component', 'new', str(core), '-o', str(component)])
        run('component-validate', [wasm_tools, 'validate', str(component)])
        run('component-wit', [wasm_tools, 'component', 'wit', str(component)])
        report.update(status='component-built-unqualified', component=identity(component))
    except ProbeFailure as error:
        last = report['stages'][-1] if report['stages'] else {}
        kind = failure_kind(last.get('name', ''), last)
        report.update(status='blocked', blocker=str(error), blockerKind=kind)
    finally:
        if sources != source_inputs(ROOT):
            report.update(status='invalid-evidence', blocker='source-inputs-changed')
        report['finishedAt'] = int(time.time())
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--bootstrap-dependencies', action='store_true',
                        help='write unreviewed candidates only inside the fresh output directory')
    parser.add_argument('--gradle', default='gradle')
    parser.add_argument('--zig', default='zig')
    parser.add_argument('--wit-bindgen', default='wit-bindgen')
    parser.add_argument('--wasm-tools', default='wasm-tools')
    args = parser.parse_args()
    try:
        report = probe(new_output(args.output), args.gradle, args.zig, args.wit_bindgen, args.wasm_tools,
                       args.bootstrap_dependencies)
    except (OSError, ValueError) as error:
        print(f'Java feasibility preflight failed: {error}', file=sys.stderr)
        return 1
    print(f"Java feasibility: {report['status']}; LSF qualification: false")
    return 0 if report['status'] == 'component-built-unqualified' else 1


if __name__ == '__main__':
    raise SystemExit(main())
