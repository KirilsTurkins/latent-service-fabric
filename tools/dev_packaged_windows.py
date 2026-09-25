"""Actual packaged frontend/WSL schedule; no source-built helper or node imports."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import time

if __package__:
    from .dev_packaged_bootstrap import authenticate, extract
    from .dev_packaged_process import Command, ProbeFailure, digest, environment, read_json, require, write_json
else:
    from dev_packaged_bootstrap import authenticate, extract
    from dev_packaged_process import Command, ProbeFailure, digest, environment, read_json, require, write_json

LANGUAGES = ('rust', 'c', 'java', 'dotnet', 'go', 'typescript')


class Frontend:
    def __init__(self, executable, root, report):
        self.executable, self.root, self.report = executable, root, report
        self.state = root / 'controller'
        self.env = environment(root)
        self.running = {}
        self.deadline = time.monotonic() + 7200

    def command(self, *arguments):
        require(len(self.report['commands']) < 190, 'qualification-command-count-limit')
        require(time.monotonic() < self.deadline, 'qualification-schedule-deadline')
        return Command([self.executable, '--state-root', self.state, 'dev', *arguments], self.root, self.env)

    def call(self, *arguments, timeout=90, rejection=None):
        process = self.command(*arguments)
        receipt = {}
        try:
            code = process.finish(timeout)
            events = process.events()
            require(events and all(event.get('schemaVersion') == 'latent.dev.result.v1' for event in events), 'frontend-output-schema')
            result = events[-1]
            receipt['response'] = result
            if rejection is not None:
                require(code == 2 and result.get('code') in rejection and result.get('uncertain') is False,
                        'expected-certain-rejection-missing')
                return result
            require(code == 0 and result.get('code') == 'success', 'frontend-command-failed-' + arguments[0])
            return result['result']
        finally:
            try:
                process.abort_controller()
            finally:
                self.report['commands'].append({**process.receipt(), **receipt})

    def start(self, workspace):
        require(workspace not in self.running, 'foreground-already-owned')
        process = self.command('up', '--workspace', workspace)
        self.running[workspace] = process
        ready = process.until(lambda event: event.get('event') == 'ready', 210)['result']
        require(ready.get('state') == 'ready', 'authenticated-readiness-required')
        return ready

    def down(self, workspace):
        result = self.call('down', '--workspace', workspace)
        require(result.get('reaped') is True, 'owned-node-shutdown-unconfirmed')
        process = self.running.pop(workspace, None)
        if process is not None:
            try:
                require(process.finish(30) == 0, 'foreground-shutdown-failed')
                self.report['commands'].append({**process.receipt(), 'events': process.events()})
            finally:
                process.abort_controller()
        return result


def make_private(root):
    root.mkdir(mode=0o700)
    command = Command([str(Path(os.environ['SystemRoot']) / 'System32/whoami.exe'), '/user', '/fo', 'csv', '/nh'],
                      root, environment(root))
    try:
        require(command.finish(10) == 0, 'windows-owner-observation')
        sid = next(csv.reader(io.StringIO(command.raw().decode('utf-8', errors='replace'))))[1]
        require(re.fullmatch(r'S-1-\d+(?:-\d+){1,15}', sid), 'windows-owner-sid')
    finally:
        command.abort_controller()
    command = Command([str(Path(os.environ['SystemRoot']) / 'System32/icacls.exe'), root, '/inheritance:r',
        '/grant:r', f'*{sid}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F'], root, environment(root))
    try:
        require(command.finish(10) == 0, 'private-conductor-directory-acl')
    finally:
        command.abort_controller()


def acquire(api, config, directory, target, *, rejection=None):
    trust = config['trust']
    return api.call('acquire', '--bundle-directory', directory, '--publisher-policy', trust['developerPolicy'],
        '--trusted-root', trust['trustedRoot'], '--verifier', trust['hostVerifier'],
        '--verifier-sha256', trust['hostVerifierSha256'], '--version', config['version'],
        '--target', target, '--allow-candidate', timeout=180, rejection=rejection)


def negative_bundles(api, config):
    source = Path(config['artifacts']['windows'])
    acquire(api, config, source, 'linux-x86_64', rejection={'developer-bundle-target'})
    copied = api.root / 'tampered-bundle'
    shutil.copytree(source, copied)
    manifest = read_json(copied / 'developer-bundle.json')
    with (copied / manifest['archive']['name']).open('r+b') as stream:
        original = stream.read(1)
        stream.seek(0)
        stream.write(bytes([original[0] ^ 1]))
    acquire(api, config, copied, 'windows-x86_64', rejection={'developer-archive-digest'})


def inputs(api, config, language, index):
    trust = config['trust']
    common = {'version': config['version'], 'trustedRoot': trust['trustedRoot'], 'verifier': trust['guestVerifier'],
              'verifierSha256': trust['guestVerifierSha256'], 'allowCandidate': True, 'consent': True}
    runtime = {**common, 'schemaVersion': 'latent.dev.install-inputs.v1', 'publisherPolicy': trust['runtimePolicy'],
        'releaseDirectory': config['artifacts']['native'], 'profile': 'local-experimental-v1', 'port': 18080 + index}
    tools = {**common, 'schemaVersion': 'latent.dev.tool-inputs.v1', 'publisherPolicy': trust['developerPolicy'],
        'bundleDirectory': config['artifacts'][language], 'language': language}
    runtime_path, tools_path = api.root / f'{language}-runtime.json', api.root / f'{language}-tools.json'
    write_json(runtime_path, runtime)
    write_json(tools_path, tools)
    return runtime_path, tools_path


def prepare(api, config, language, index, helper_sha):
    workspace = 'test-packaged-' + language
    owned = api.call('wsl-workspace', '--workspace', workspace, '--helper-sha256', helper_sha)
    runtime, tools = inputs(api, config, language, index)
    api.call('install', '--workspace', workspace, '--runtime-inputs', runtime, timeout=1200)
    selected = api.call('install-tools', '--workspace', workspace, '--tool-inputs', tools, timeout=1800)
    require(selected['publisherAuthenticated'] is True and selected['sourceCommit'] == config['sourceCommit'],
            'authenticated-installed-tools-required')
    cached = acquire(api, config, config['artifacts'][language], 'linux-x86_64')
    template_root = api.state / 'bundles' / cached['bundle']
    index_value = read_json(template_root / 'templates.json')
    template = index_value['templates']['greeting']
    # The inventory names the language-owned template. Never substitute an SDK client.
    relative = Path(template['path']).relative_to('templates').as_posix()
    manifest = read_json(template_root / template['path'] / 'template.json')
    identity = 'sha256:' + hashlib.sha256((json.dumps(manifest, sort_keys=True,
        separators=(',', ':'), ensure_ascii=True, allow_nan=False) + '\n').encode()).hexdigest()
    project = api.root / ('Author spaces-\u00fc ' + language)
    api.call('init', project, '--bundle', cached['bundle'], '--template', relative, '--template-sha256', identity)
    sentinel = project / 'app/.env'
    sentinel.write_text('QUALIFICATION_EXCLUDED_CREDENTIAL=never-synchronize-this-marker\n', encoding='utf-8')
    api.call('build', '--workspace', workspace, '--project', project, rejection={'workspace-recipe-trust-required'})
    api.call('trust', '--workspace', workspace, '--project', project)
    built = api.call('build', '--workspace', workspace, '--project', project, timeout=1200)
    profile = api.call('prepare-test', '--workspace', workspace, '--consent-test-fixtures',
                       '--admission', 'signed-fixture', '--tool-root', selected['directory'], timeout=120)
    return {'workspace': workspace, 'user': owned['user'], 'project': str(project),
            'build': built, 'profile': profile, 'tools': selected}


def verify_language(api, item):
    name = item['workspace']
    item['startup'] = api.start(name)
    item['doctor'] = api.call('doctor', '--workspace', name)
    item['deployment'] = api.call('deploy', '--workspace', name, timeout=180)
    item['tests'] = api.call('test', '--workspace', name, '--environment', 'node', timeout=330)
    require(item['tests']['passed'] and all(case['status'] == 'passed' for case in item['tests']['results']), 'language-required-case-failed')
    require({'success', 'declared-error'} <= {case['category'] for case in item['tests']['results']}, 'success-and-declared-error-required')


def retained_invocation(api, item):
    result = api.call('test', '--workspace', item['workspace'], '--environment', 'node',
        '--select', item['tests']['selection'][0], timeout=150)
    require(result['passed'] and result['identity']['deployment'] == item['tests']['identity']['deployment'],
            'retained-workspace-invocation-redeployed-or-failed')
    return result


def run(config, output):
    require(os.name == 'nt' and platform.machine().lower() in {'amd64', 'x86_64'}, 'actual-windows-x64-required')
    require(config['consentProvisionAndInstall'] is True and config['independentPolicyApproved'] is True,
            'explicit-provision-install-and-policy-approval-required')
    require(not output.exists() and output.parent.is_dir(), 'new-existing-parent-output-required')
    make_private(output)
    started = time.monotonic()
    report = {'schemaVersion': 'latent.dev.packaged-windows-probe.v1', 'passed': False, 'qualificationComplete': False,
        'sourceCommit': config['sourceCommit'], 'host': {'osVersion': platform.version(), 'architecture': platform.machine()},
        'sourceCheckoutUsedByApplication': False, 'runtimeCompiled': False, 'commands': [], 'languages': {},
        'cleanup': 'not-started', 'limits': {'commands': 190, 'stdoutBytesPerCommand': 4194304,
            'stderrBytesPerCommand': 262144, 'receiptBytes': 16777216, 'maximumCommandSeconds': 1800,
            'scheduleSeconds': 7200}}
    api = None
    try:
        manifest, report['bootstrap'] = authenticate(config, output)
        executable = extract(Path(config['artifacts']['windows']), manifest, output / 'frontend')
        api = Frontend(executable, output, report)
        report['doctor'] = api.call('doctor')
        negative_bundles(api, config)
        report['frontend'] = acquire(api, config, config['artifacts']['windows'], 'windows-x86_64')
        image = acquire(api, config, config['artifacts']['wsl'], 'linux-x86_64-wsl-rootfs')
        inventory = read_json(api.state / 'bundles' / image['bundle'] / 'rootfs-inventory.json')
        report['provision'] = api.call('provision', '--bundle', image['bundle'], '--consent-provision', timeout=360)
        retained = None
        for index, language in enumerate(LANGUAGES):
            item = report['languages'][language] = prepare(api, config, language, index, inventory['helperSha256'])
            verify_language(api, item)
            if retained is None:
                retained = item
                continue
            require(item['user'] != retained['user'], 'separate-wsl-users-required')
            item['otherWorkspaceBeforeStop'] = api.call('status', '--workspace', retained['workspace'])
            item['shutdown'] = api.down(item['workspace'])
            item['otherWorkspaceAfterStop'] = api.call('status', '--workspace', retained['workspace'])
            require(item['otherWorkspaceAfterStop']['state'] == 'ready', 'other-workspace-stopped')
            item['otherWorkspaceInvocationAfterStop'] = retained_invocation(api, retained)
            item['purge'] = api.call('purge', '--workspace', item['workspace'], '--confirm-workspace', item['workspace'], timeout=120)
            require(Path(item['project']).is_dir(), 'purge-removed-authored-source')
            write_json(output / 'observation.json', report)
        retained['shutdown'] = api.down(retained['workspace'])
        retained['restart'] = api.start(retained['workspace'])
        retained['statusAfterRestart'] = api.call('status', '--workspace', retained['workspace'])
        retained['invocationAfterRestart'] = retained_invocation(api, retained)
        retained['shutdownAfterRestart'] = api.down(retained['workspace'])
        retained['purge'] = api.call('purge', '--workspace', retained['workspace'], '--confirm-workspace', retained['workspace'], timeout=120)
        require(Path(retained['project']).is_dir(), 'purge-removed-authored-source')
        report['distroPurge'] = api.call('wsl-purge', '--confirm-distribution', report['provision']['distribution'], timeout=180)
        report.update(passed=True, cleanup='owned-workspaces-and-distribution-purged-author-source-retained')
    except BaseException as error:
        report['failure'] = str(error) if isinstance(error, ProbeFailure) else type(error).__name__
        report['cleanup'] = 'failed-attempt-private-state-retained'
        raise
    finally:
        if api is not None and api.running:
            report['cleanupAttempts'] = {}
            for name in list(api.running):
                try:
                    report['cleanupAttempts'][name] = api.down(name)
                except BaseException as error:
                    report['cleanupAttempts'][name] = {'failure': type(error).__name__, 'remoteTerminationConfirmed': False}
            report['cleanup'] = 'failed-attempt-private-workspaces-retained-inspect-cleanup-receipts'
        report['seconds'] = round(time.monotonic() - started, 3)
        write_json(output / 'observation.json', report)
    return report
