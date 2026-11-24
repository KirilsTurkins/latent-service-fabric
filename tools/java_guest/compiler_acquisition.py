"""Acquire the pinned Gradle compiler dependencies for maintained Java tools."""
from __future__ import annotations

import json
import re
import time

from tools.dev_workflow import paths
from tools.java_guest.compiler import Compiler


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
