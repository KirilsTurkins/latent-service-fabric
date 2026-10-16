#!/usr/bin/env python3
"""Exercise delivered Java dependency authoring through the maintained watcher.

Run with the delivered Python, as an unprivileged Linux user in a network-none
container. The supplied helper and native node are explicit source fixtures;
this programme does not manufacture publisher authentication or installation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import zipfile


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()


def require(value, reason):
    if not value:
        raise ValueError(reason)


def write(path: Path, value) -> None:
    path.write_text(json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8')


def public_projection(report, *, qualifier, helper, source_probe):
    public = {key: report[key] for key in (
        'schemaVersion', 'passed', 'publisherAuthenticated', 'cleanHost', 'sourceCandidate',
        'admission', 'phase', 'durationSeconds')}
    public.update(qualifier=qualifier, helper=helper, sourceProbe=source_probe,
        outsideJars=report.get('outsideJars', {}),
        originalInputsRemovedBeforeCompile=report.get('originalInputsRemovedBeforeCompile', False),
        deploymentCount=len(report['stages']), cleanup=report.get('cleanup', 'not-performed'),
        shutdowns=[{'id': row['id'], 'watchExitCode': row['watchExitCode'],
                    'state': row['result']['state'], 'reaped': row['result']['reaped'],
                    'cleanShutdown': row['result']['cleanShutdown']} for row in report.get('shutdowns', [])],
        stages=[{'id': row['id'], 'passed': row['tests']['passed']} for row in report['stages']])
    if 'failure' in report:
        public['failure'] = report['failure']
    return public


class ShutdownOnce:
    """Fence an external shutdown before dispatch, including uncertain failure."""
    def __init__(self):
        self.attempted = False

    def call(self, operation):
        require(not self.attempted, 'watch-down-already-attempted-no-retry')
        self.attempted = True
        return operation()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installed', required=True, type=Path)
    parser.add_argument('--helper', required=True, type=Path)
    parser.add_argument('--helper-sha256', required=True)
    parser.add_argument('--source-probe', required=True, type=Path)
    parser.add_argument('--source-probe-sha256', required=True)
    parser.add_argument('--source-node', required=True, type=Path)
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
    installed = args.installed.resolve()
    python = installed / 'sdk/bin/python'
    java_cli = installed / 'recipe/tools/java_capsule.py'
    fixed_inputs = {str(p): digest(p) for p in (Path(__file__), python, java_cli, args.helper, args.source_probe,
        installed / 'guest-tools.json', installed / 'sdk/managed-inputs.json', installed / 'sdk/managed.zip')}
    report = {'schemaVersion': 'latent.java.dependency-watch-qualification.v1', 'passed': False,
        'publisherAuthenticated': False, 'cleanHost': False, 'sourceCandidate': True,
        'admission': 'explicit-signed-fixture-per-reviewed-build',
        'ambientPath': os.environ.get('PATH'), 'uid': os.geteuid(), 'inputs': fixed_inputs,
        'sourceNode': json.loads((args.source_node / 'source-node.json').read_bytes()),
        'commands': [], 'stages': [], 'phase': 'prepare'}
    began = time.monotonic()
    watcher = None
    shutdown = ShutdownOnce()
    frontend = root / 'latent-dev-source'
    events = root / 'frontend-events.jsonl'
    controller = root / 'controller'
    workspace_prefix = 'test-java-lib-' + root.name
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
        return command(label, [python, '-I', '-B', java_cli, *arguments])

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
        write(location / 'scenarios.json', {'schemaVersion': 'latent.dev.scenarios.v1', 'scenarios': [{
            'id': 'dependency-output', 'service': 'examples/my-greeting',
            'contract': 'examples:greeting/api@1.0.0', 'function': 'greet',
            'input': 'tests/library-input.json', 'mediaType': 'application/vnd.latent.wit-values.v1+json',
            'expect': {'category': 'success', 'payload': 'tests/library-expected.json'},
            'requires': ['clock'], 'execution': {'grants': [
                'latent:clock/monotonic@0.1.0', 'latent:clock/wall@0.1.0']},
            'timeoutMillis': 30000, 'nodeTimeoutMillis': 120000, 'required': True, 'fixtures': []}]})

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
        nonlocal workspace_name, watcher, shutdown
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
              '--admission', 'signed-fixture', '--tool-root', installed)
        offset = len(observed())
        watch_command = [python, '-I', '-B', java_cli, 'watch', application, '--workspace', workspace_name,
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
        require(watcher.returncode == 0, 'java-authoring-watch-did-not-complete-normally')
        report.setdefault('shutdowns', []).append({'id': label, 'result': stopped, 'watchExitCode': watcher.returncode})

    try:
        # No controller or recipe is imported from a checkout. The explicit
        # wrapper verifies the helper and delegates to its unchanged CLI.
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
        jdks = list(managed.glob('jdk/bin/javac'))
        require(len(jdks) == 1, 'single-captured-javac-required')
        library = root / 'outside-library'
        (library / 'source/outside/owner').mkdir(mode=0o700, parents=True)
        (library / 'classes').mkdir(mode=0o700)
        source = library / 'source/outside/owner'
        (source / 'Arithmetic.java').write_text('''package outside.owner;
public final class Arithmetic {
  public static int increment(int value) { return Child.increment(value); }
  public static String resource() throws java.io.IOException {
    try (java.io.InputStream stream=Arithmetic.class.getResourceAsStream("badge.txt")) {
      if(stream==null) throw new java.io.IOException("resource-missing");
      return new String(stream.readAllBytes(),java.nio.charset.StandardCharsets.UTF_8);
    }
  }
}
''', encoding='utf-8')
        jars = {}
        for revision, increment in (('v1', 39), ('v2', 40)):
            (source / 'Child.java').write_text('package outside.owner;public final class Child {'
                'public static int increment(int value){return value+' + str(increment) + ';}}', encoding='utf-8')
            command('outside-javac-' + revision, [jdks[0], '--release', '17', '-proc:none', '-encoding', 'UTF-8',
                '-d', library / 'classes', source / 'Child.java', source / 'Arithmetic.java'], timeout=30)
            entries = {'child-' + revision: {'outside/owner/Child.class':
                       (library / 'classes/outside/owner/Child.class').read_bytes()}}
            if revision == 'v1':
                entries['primary'] = {'outside/owner/Arithmetic.class':
                    (library / 'classes/outside/owner/Arithmetic.class').read_bytes(),
                    'outside/owner/badge.txt': b'captured watch resource'}
            for name, files in entries.items():
                path = library / (name + '.jar')
                with zipfile.ZipFile(path, 'x') as archive:
                    for relative, raw in sorted(files.items()):
                        item = zipfile.ZipInfo(relative, (2026, 10, 16, 0, 0, 0))
                        item.create_system = 3
                        item.external_attr = 0o100644 << 16
                        archive.writestr(item, raw)
                jars[name] = {'path': path, 'sha256': digest(path), 'bytes': path.read_bytes()}
        report['outsideJars'] = {name: value['sha256'] for name, value in jars.items()}
        child, primary = 'outside-watch-child/2026.10.16', 'outside-watch-primary/2026.10.16'
        author('add-child', 'add-local', application, '--id', child, '--jar', jars['child-v1']['path'])
        author('add-primary', 'add-local', application, '--id', primary, '--jar', jars['primary']['path'], '--depends', child)
        capsule = application / 'app/src/dev/latent/app/Capsule.java'
        capsule.write_text('''package dev.latent.app;
import dev.latent.generated.Bindings;import dev.latent.guest.Result;import outside.owner.Arithmetic;
public final class Capsule implements Bindings.Exports {
  private static int calls;
  public Result<String,String> greet(String name) {
    if(++calls!=1)return Result.err("activation-state-reused");
    try{return Result.ok(Arithmetic.increment(3)+"/"+name+"/"+Arithmetic.resource());}
    catch(java.io.IOException failure){return Result.err(failure.getMessage());}
  }
}
''', encoding='utf-8')
        tests('42/SDK/captured watch resource')
        review('initial')
        jars['child-v1']['path'].unlink()
        jars['primary']['path'].unlink()
        shutil.rmtree(library / 'source')
        shutil.rmtree(library / 'classes')
        report['originalInputsRemovedBeforeCompile'] = True
        report['phase'] = 'runtime'
        config = root / 'backend.json'
        write(config, {'kind': 'linux', 'python': str(python), 'helper': str(args.helper),
                       'helperSha256': args.helper_sha256})
        report['phase'] = 'watch'
        offset = start_watch('initial')
        author('update-child', 'update', application, child, '--jar', jars['child-v2']['path'])
        offset, denied = await_event(offset, lambda value: value.get('event') == 'edit-failed', 'unreviewed-update', 30)
        require(denied['uncertain'] is False, 'unreviewed-update-must-be-certain')
        report['updateBeforeReview'] = denied
        # Resolution explicitly reselects the unchanged original primary JAR.
        # Its source/classes stay absent and both JARs are removed again before
        # compilation; no resolver silently recovers or substitutes input bytes.
        jars['primary']['path'].write_bytes(jars['primary']['bytes'])
        require(digest(jars['primary']['path']) == jars['primary']['sha256'], 'restored-original-primary-drift')
        review('updated')
        jars['primary']['path'].unlink()
        jars['child-v2']['path'].unlink()
        tests('43/SDK/captured watch resource')
        offset, denied = await_event(offset, lambda value: value.get('code') == 'workspace-recipe-trust-required',
                                     'updated-recipe-trust', 30)
        report['updateBeforeTrust'] = denied
        front('updated-explicit-trust', 'trust', '--project', application)
        offset, denied = await_event(offset, lambda value: value.get('code') == 'signed-test-build-changed-use-new-workspace',
                                     'updated-signature-boundary')
        report['updateBeforeNewSignedWorkspace'] = denied
        stop_watch('initial')
        offset = start_watch('updated')
        author('remove-primary', 'remove', application, primary)
        author('remove-child', 'remove', application, child)
        offset, denied = await_event(offset, lambda value: value.get('event') == 'edit-failed', 'unreviewed-remove', 30)
        report['removeBeforeReview'] = denied
        capsule.write_text('''package dev.latent.app;
import dev.latent.generated.Bindings;import dev.latent.guest.Result;
public final class Capsule implements Bindings.Exports {
  public Result<String,String> greet(String name){return Result.ok("removed/"+name);}
}
''', encoding='utf-8')
        tests('removed/SDK')
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
        actual_deployments = [row for row in observed() if row.get('event') == 'deployed']
        require(len(actual_deployments) == 3, 'exactly-one-deployment-per-reviewed-selection-required')
        require(all(digest(Path(path)) == identity for path, identity in fixed_inputs.items()), 'tool-input-changed')
        require(digest(args.helper) == args.helper_sha256 and digest(args.source_probe) == args.source_probe_sha256,
                'source-owner-changed')
        report.update(passed=True, phase='complete', deploymentCount=3, cleanup='confirmed-normal-down')
        return 0
    except BaseException as error:
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
        write(root / 'public-qualification.json', public_projection(report,
            qualifier=digest(Path(__file__)), helper=args.helper_sha256,
            source_probe=args.source_probe_sha256))


if __name__ == '__main__':
    raise SystemExit(main())
