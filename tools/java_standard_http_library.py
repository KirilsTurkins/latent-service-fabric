"""One pinned default-client fixture, never a compiler eligibility catalogue."""
from __future__ import annotations

import json
import re
from pathlib import Path
import sys
import time

from tools.build_snapshot import digest
from tools.dev_workflow import paths
from tools.java_capsule_build import build
from tools.java_capsule_project import create
from tools.java_guest.compiler import Compiler, read_only_dependency_cache, tool_inventory
from tools.java_dependency_authoring import edit
from tools.java_standard_http_node import run as provider_controls
from tools.java_standard_http_project import project as standard_project
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, fresh, read_file, read_json, write_json

COORDINATE = 'com.github.kevinsawicki:http-request:6.0'
ORIGINAL_JAR = 'sha256:673dd02ade4196ab511e812a6857dacaeb5716dea83aa217dba654824b5d5476'
# Exact original closure reviewed for this test, not an application allowlist.
CANDIDATE = 'sha256:0159ae14f34c314b8d5ff06a5b2defac711eb6911e85066f7176cece4513e5c5'
SOURCE = 'examples/java-http-request/Capsule.java'


_MISSING_COMPILER = re.compile(r"(?m)^[ \t]*> Could not find (org\.teavm:[A-Za-z0-9_.-]+:[A-Za-z0-9_.+-]+)\.$")
_METADATA_URL = re.compile(r"(?m)^[ \t]+- ([^\s]+)$")


_RATE_LIMITED_POM = re.compile(
    r"(?m)^[ \t]*> Could not resolve (?P<coordinate>org\.teavm:[A-Za-z0-9_.-]+:[A-Za-z0-9_.+-]+)\.\n"
    r"[ \t]+Required by:\n[ \t]+buildscript of root project 'lsf-java-guest-feasibility'\n"
    r"[ \t]+> Could not resolve (?P=coordinate)\.\n"
    r"[ \t]+> Could not get resource '(?P<url>https://[^'\s]+)'\.\n"
    r"[ \t]+> Could not GET '(?P=url)'\. Received status code 429 from server: Too Many Requests$"
)


def compiler_metadata_retry_delay(log: str, lock: bytes) -> int:
    """Return the initial backoff for a known locked metadata acquisition failure."""
    if (log.count('FAILURE: Build failed with an exception.') != 1
            or log.count("A problem occurred configuring root project 'lsf-java-guest-feasibility'.") != 1
            or log.count("Could not resolve all artifacts for configuration 'classpath'.") != 1
            or log.count('BUILD FAILED') != 1 or '> Task ' in log
            or 'verification' in log.lower() or 'Execution failed for task' in log):
        return 0
    missing = _MISSING_COMPILER.findall(log)
    throttled = _RATE_LIMITED_POM.findall(log)
    if not (missing or throttled) or log.count('Could not ') != 1 + len(missing) + 4 * len(throttled):
        return 0
    locked = {}
    for item in json.loads(lock)['artifacts']:
        parts = item['path'].split('/')
        if (len(parts) == 5 and parts[:2] == ['org', 'teavm']
                and parts[-1] == parts[2] + '-' + parts[3] + '.jar'):
            coordinate = 'org.teavm:' + parts[2] + ':' + parts[3]
            locked[coordinate] = 'https://repo.maven.apache.org/maven2/' + item['path'][:-4] + '.pom'
    if any(name not in locked for name in missing):
        return 0
    if set(_METADATA_URL.findall(log)) != {locked[name] for name in missing}:
        return 0
    if any(locked.get(name) != url for name, url in throttled):
        return 0
    return 15 if throttled else 2


def missing_compiler_metadata(log: str, lock: bytes) -> bool:
    return compiler_metadata_retry_delay(log, lock) == 2


class AcquisitionCompiler(Compiler):
    """Retry bounded metadata failures during the maintained greeting's online acquisition.

    Ordinary application compilers are unchanged. Every attempt still uses the
    pinned build, dependency verification, original deadline and retention cap.
    Offline builds, task failures, compiler errors and unverifiable diagnostics
    never become retries. All failed command/log records remain retained.
    """
    def run(self, stage, tool, *arguments, **kwargs):
        retry_command = (stage == 'java-to-c' and tool == 'gradle' and not self.offline
                         and arguments == ('--no-daemon', 'generateC'))
        for attempt in range(3):
            selected = arguments if attempt == 0 else (*arguments[:-1], '--refresh-dependencies', arguments[-1])
            try:
                return super().run(stage, tool, *selected, **kwargs)
            except ValueError as error:
                if (not retry_command or attempt == 2
                        or str(error) != 'Java compiler stage failed: java-to-c; see retained log'):
                    raise
                try:
                    ordinal = len(self.records) - 1
                    record = self.records[ordinal]
                    log = paths.read(self.directory, str(ordinal) + '-java-to-c.log', 4 * 1024 * 1024).decode('utf-8')
                    delay = 0
                    if (record['stage'] == stage and type(record['exitCode']) is int
                            and record['exitCode'] == 1 and 'processFailure' not in record):
                        delay = compiler_metadata_retry_delay(log, self.original_sdk['feasibility/dependencies.lock.json'])
                except Exception:
                    delay = 0
                if not delay:
                    raise
                self.check_unchanged()
                deadline = self.deadline
                if getattr(self, '_parent_deadline', None) is not None:
                    deadline = min(deadline, self._parent_deadline - 5)
                delay *= attempt + 1
                if time.monotonic() + delay >= deadline:
                    raise
                time.sleep(delay)


def compiler_cache(commands, wasi_sdk: Path, output: Path, selected: Path | None) -> Path:
    """A captured application never turns compiler registry resolution back on."""
    remaining = min(900, commands.deadline-time.monotonic())
    if remaining <= 0:
        raise ValueError('standard-java-original-deadline-expired')
    if selected is None:
        fixture = create(output/'compiler-source', 'greeting')
        # Source capture and constructor setup must not restart the owner's clock.
        compiler = AcquisitionCompiler(output/'compiler-acquisition', wasi_sdk, timeout=remaining,
                                       _deadline=commands.deadline)
        compiler.compile(fixture/'src', fixture/'wit', 'examples:greeting/service@1.0.0', output/'compiler-build')
        compiler.check_unchanged()
        selected = compiler.directory/'gradle-home/caches/modules-2'
        mode = 'maintained-source-compiler-acquisition'
    else:
        mode = 'explicit-read-only-cache'
    selected = read_only_dependency_cache(selected)
    write_json(output/'compiler-cache-selection.json', {'formatVersion': 1, 'mode': mode,
        'inventoryDigest': digest(tool_inventory({'gradle-cache': selected})),
        'applicationRegistryResolution': False})
    return selected


def project(directory: Path) -> Path:
    app = standard_project(directory)
    source = read_file(ROOT/SOURCE)
    (app/'src/dev/latent/app/Capsule.java').write_bytes(source)
    lock = read_json(app/'sdk-lock.json')
    lock['template'].update(name='java-default-http-request', sourceDigest=digest(source))
    (app/'sdk-lock.json').write_text(json.dumps(lock, indent=2)+'\n', encoding='utf-8')
    edit(app, 'add', coordinate=COORDINATE)
    return app


def qualify(commands, binaries: dict, wasi_sdk: Path, output: Path, *, read_only_cache: Path | None = None) -> dict:
    """Reuse the original native tuple, provider matrix and overall deadline."""
    output = fresh(output)
    before = {name: file_identity(ROOT/name) for name in (SOURCE, 'tools/java_standard_http_library.py')}
    app = project(output/'application')
    candidate = output/'candidate.json'
    commands.run('default-client-native-resolve', sys.executable, ROOT/'tools/java_capsule.py',
                 'resolve', app, '--candidate', candidate, '--gradle', 'gradle')
    if digest(read_file(candidate)) != CANDIDATE:
        raise ValueError('standard-java-test-client-closure-changed-review-required')
    commands.run('default-client-review', sys.executable, ROOT/'tools/java_capsule.py',
                 'review-lock', app, '--candidate', candidate, '--expect', CANDIDATE)
    selected_cache = compiler_cache(commands, wasi_sdk, output, read_only_cache)
    remaining = min(900, commands.deadline-time.monotonic())
    if remaining <= 0:
        raise ValueError('standard-java-original-deadline-expired')
    artifact = build(app, output/'build', binaries['examples/capsule_contracts'], binaries['examples/package'],
        'https://github.com/KirilsTurkins/latent-service-fabric', wasi_sdk,
        timeout=remaining, read_only_cache=selected_cache)
    classpath = read_json(artifact/'java-classpath.json')
    matches = [row for row in classpath['artifacts'] if row['id'] == COORDINATE]
    if len(matches) != 1 or matches[0]['originalDigest'] != ORIGINAL_JAR:
        raise ValueError('standard-java-test-client-original-jar-changed')
    controls = provider_controls(artifact, {'latent': binaries['latent'], 'latentd': binaries['latentd'],
        'capsule_authoring': binaries['examples/capsule_authoring']}, output/'provider', deadline=commands.deadline)
    if before != {name: file_identity(ROOT/name) for name in before}:
        raise ValueError('standard-java-test-client-source-changed')
    result = {'schemaVersion': 'latent.java.default-client.qualification.v1', 'status': 'passed',
        'scope': 'one-unchanged-published-default-client-finite-signed-provider-subset',
        'library': {'coordinate': COORDINATE, 'originalJarDigest': ORIGINAL_JAR,
                    'capturedClosureDigest': CANDIDATE, 'classpath': matches[0]},
        'sources': before, 'component': file_identity(artifact/'component.wasm'),
        'sourceInputs': file_identity(artifact/'source-inputs.json'),
        'recipeInputs': file_identity(artifact/'recipe-inputs.json'),
        'runtimeProfile': file_identity(artifact/'http-client-profile.json'),
        'compilerCacheSelection': read_json(output/'compiler-cache-selection.json'),
        'providerReceipt': file_identity(output/'provider/qualification.json'),
        'cases': controls['cases'], 'peer': controls['peer'],
        'shutdown': controls['shutdown'], 'nativeProducts': controls['binaries'],
        'limitations': ['One published client; no two-client or private-client acceptance.',
            'Plain HTTP synchronous factory/body/early-close subset; full async/cancel/HTTPS matrix pending.',
            'Native RSS is sampled; no allocator/native/kernel upper-bound claim.']}
    write_json(output/'qualification.json', result)
    return result
