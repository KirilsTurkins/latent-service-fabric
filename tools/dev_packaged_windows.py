"""Actual packaged frontend/WSL schedule; no source-built helper or node imports."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time

if __package__:
    from .dev_packaged_bootstrap import authenticate, extract
    from .dev_packaged_guest import observe, export, installation_progress
    from .dev_packaged_watch import campaign as watch_campaign
    from .dev_packaged_process import MAX_COMMANDS, Command, ProbeFailure, digest, environment, read_json, require, write_json
    from .dev_packaged_recovery import deploy_with_lost_responses, invoke_with_lost_response
    from .dev_packaged_wsl_lifecycle import restart_owned_distribution
else:
    from dev_packaged_bootstrap import authenticate, extract
    from dev_packaged_guest import observe, export, installation_progress
    from dev_packaged_watch import campaign as watch_campaign
    from dev_packaged_process import MAX_COMMANDS, Command, ProbeFailure, digest, environment, read_json, require, write_json
    from dev_packaged_recovery import deploy_with_lost_responses, invoke_with_lost_response
    from dev_packaged_wsl_lifecycle import restart_owned_distribution

LANGUAGES = ('rust', 'c', 'java', 'dotnet', 'go', 'typescript')


class Frontend:
    def __init__(self, executable, root, report):
        self.executable, self.root, self.report = executable, root, report
        self.state = root / 'controller'
        self.env = environment(root)
        self.running = {}
        self.deadline = time.monotonic() + 7200

    def command(self, *arguments):
        limit = MAX_COMMANDS if arguments[0] in {'down', 'status', 'recover'} else MAX_COMMANDS - 24
        require(len(self.report['commands']) < limit, 'qualification-command-count-limit')
        require(time.monotonic() < self.deadline, 'qualification-schedule-deadline')
        return Command([self.executable, '--state-root', self.state, 'dev', *arguments], self.root, self.env)

    def call(self, *arguments, timeout=90, rejection=None, expected_test_failure=False, expected_uncertain=None):
        require(sum((rejection is not None, expected_test_failure, expected_uncertain is not None)) <= 1,
                'one-explicit-frontend-outcome-expectation')
        process = self.command(*arguments)
        receipt = {}
        try:
            code = process.finish(timeout)
            events = process.events()
            require(events and all(event.get('schemaVersion') == 'latent.dev.result.v1' for event in events), 'frontend-output-schema')
            result = events[-1]
            receipt['response'] = result
            if arguments[0] in {'install', 'install-tools'} and result.get('code') == 'backend-transport-lost-status-required':
                # Read transfer sizes and completion markers only. The original
                # uncertain operation is never repeated or labeled resolved.
                try:
                    workspace = arguments[arguments.index('--workspace') + 1]
                    receipt['guestInstallationObservation'] = installation_progress(self, workspace)
                except BaseException as error:
                    receipt['guestInstallationObservation'] = {'failure': type(error).__name__, 'outcomeStillUncertain': True}
            if rejection is not None:
                require(code == 2 and result.get('code') in rejection and result.get('uncertain') is False,
                        'expected-certain-rejection-missing')
                return result
            if expected_uncertain is not None:
                require(code == 5 and result.get('uncertain') is True and result.get('code') in expected_uncertain,
                        'expected-uncertain-outcome-missing')
                return result
            if expected_test_failure:
                require(arguments[0] == 'test' and code == 3 and result.get('code') == 'required-tests-failed'
                        and result.get('result', {}).get('passed') is False, 'expected-required-test-failure-missing')
                return result['result']
            require(code == 0 and result.get('code') == 'success', 'frontend-command-failed-' + arguments[0])
            return result['result']
        finally:
            try:
                process.abort_controller()
            finally:
                self.report['commands'].append({**process.receipt(), **receipt})

    def start(self, workspace, *, project=None, selection=None):
        require(workspace not in self.running, 'foreground-already-owned')
        arguments = ['up', '--workspace', workspace]
        if project is not None:
            arguments.extend(['--watch', '--project', project, '--test-select', selection])
        process = self.command(*arguments)
        self.running[workspace] = process
        try:
            ready = process.until(lambda event: event.get('event') == 'ready', 210)['result']
        except BaseException:
            cleanup_failure = None
            try:
                process.abort_controller()
            except BaseException as error:
                cleanup_failure = type(error).__name__
            self.report.setdefault('startupFailures', {})[workspace] = {
                'events': process.events(), 'process': process.receipt(), 'controllerCleanupFailure': cleanup_failure}
            raise
        require(ready.get('state') == 'ready', 'authenticated-readiness-required')
        return ready

    def down(self, workspace):
        result = self.call('down', '--workspace', workspace)
        require(result.get('reaped') is True, 'owned-node-shutdown-unconfirmed')
        process = self.running.pop(workspace, None)
        if process is not None:
            try:
                code = process.finish(30)
                self.report['commands'].append({**process.receipt(), 'events': process.events()})
                failed = self.report.get('startupFailures', {}).get(workspace)
                require(code == 0 or failed is not None and failed['process']['exitCode'] == code,
                        'foreground-shutdown-failed')
            finally:
                process.abort_controller()
        return result


def make_private(root):
    # CPython 3.13 creates the private Windows DACL atomically for mode 0700,
    # exactly as the shipped frontend does. Additional icacls grants can
    # introduce account aliases rejected by its deliberately closed policy.
    require(sys.version_info >= (3, 13), 'conductor-python-3-13-required-for-private-windows-creation')
    root.mkdir(mode=0o700)


def acquire(api, config, directory, target, *, rejection=None):
    trust = config['trust']
    return api.call('acquire', '--bundle-directory', directory, '--publisher-policy', trust['developerPolicy'],
        '--trusted-root', trust['trustedRoot'], '--verifier', trust['hostVerifier'],
        '--verifier-sha256', trust['hostVerifierSha256'], '--version', config['version'],
        '--target', target, '--allow-candidate', timeout=180, rejection=rejection)


def negative_bundles(api, config, *, target='windows-x86_64'):
    require(target in {'windows-x86_64', 'linux-x86_64'}, 'closed-negative-bundle-target')
    source = Path(config['artifacts']['windows' if target == 'windows-x86_64' else 'linux'])
    wrong_target = 'linux-x86_64' if target == 'windows-x86_64' else 'windows-x86_64'
    acquire(api, config, source, wrong_target, rejection={'developer-bundle-target'})
    copied = api.root / 'tampered-bundle'
    shutil.copytree(source, copied)
    manifest = read_json(copied / 'developer-bundle.json')
    with (copied / manifest['archive']['name']).open('r+b') as stream:
        original = stream.read(1)
        stream.seek(0)
        stream.write(bytes([original[0] ^ 1]))
    acquire(api, config, copied, target, rejection={'developer-archive-digest'})
    untrusted = api.root / 'untrusted-publisher-policy.json'
    write_json(untrusted, {**config['approvedDeveloperPolicy'], 'sourceRef': 'refs/heads/not-the-approved-source'})
    trust = config['trust']
    api.call('acquire', '--bundle-directory', source, '--publisher-policy', untrusted,
        '--trusted-root', trust['trustedRoot'], '--verifier', trust['hostVerifier'],
        '--verifier-sha256', trust['hostVerifierSha256'], '--version', config['version'],
        '--target', target, '--allow-candidate', timeout=180,
        rejection={'developer-publisher-attestation-rejected'})
    require(not any((api.state / 'bundles').glob('*/verified-bundle.json')), 'rejected-candidate-became-usable')
    return {'target': target, 'wrongTargetRejected': True, 'tamperedArchiveRejected': True,
            'wrongPublisherRejected': True, 'rejectedCandidateBecameUsable': False}


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


def prepare(api, config, language, index, helper_sha, *, backend_config=None, project_parent=None, case_set=None,
            watch_project=False, recovery_case=None):
    require(case_set in {None, 'failure', 'clock'} and (case_set is None or language == 'rust'), 'closed-authored-case-set')
    require(type(watch_project) is bool and (not watch_project or language == 'rust' and case_set is None),
            'trusted-local-watch-requires-separate-provider-free-rust-project')
    require(recovery_case in {None, 'expiry', 'unknown'}
        and (recovery_case is None or language == 'rust' and case_set is None and not watch_project),
        'closed-separate-recovery-project')
    suffix = '-watch' if watch_project else '-' + recovery_case if recovery_case else '' if case_set is None else '-' + case_set
    workspace = 'test-packaged-' + language + suffix
    if backend_config is None:
        owned = api.call('wsl-workspace', '--workspace', workspace, '--helper-sha256', helper_sha)
    else:
        selected_backend = read_json(backend_config)
        require(selected_backend['kind'] in {'linux', 'ssh'} and selected_backend['helperSha256'] == helper_sha,
                'explicit-qualification-backend-required')
        api.call('connect', '--workspace', workspace, '--backend-config', backend_config)
        import pwd
        owned = {'user': selected_backend.get('user', pwd.getpwuid(os.getuid()).pw_name)}
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
    project = (project_parent or api.root) / ('Author spaces-\u00fc ' + language + suffix)
    api.call('init', project, '--bundle', cached['bundle'], '--template', relative, '--template-sha256', identity)
    sentinel = project / 'app/.env'
    sentinel.write_text('QUALIFICATION_EXCLUDED_CREDENTIAL=never-synchronize-this-marker\n', encoding='utf-8')
    if case_set is not None:
        if __package__:
            from .dev_packaged_failures import author
        else:
            from dev_packaged_failures import author
        author(project, case_set)
    if watch_project:
        if __package__:
            from .dev_watch_case_inputs import edit, populate
        else:
            from dev_watch_case_inputs import edit, populate
        populate(project, read_json(project / 'latent.project.json'))
    security = {}
    if language == 'rust' and case_set is None and not watch_project and recovery_case is None:
        if __package__:
            from .dev_packaged_security import descriptors, source_paths
        else:
            from dev_packaged_security import descriptors, source_paths
        security['descriptors'] = descriptors(api, workspace, project)
        source = project / 'app/src/lib.rs'
        source.write_bytes(source.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
        security['crlfSourceSha256'] = digest(source)
    api.call('build', '--workspace', workspace, '--project', project, rejection={'workspace-recipe-trust-required'})
    api.call('trust', '--workspace', workspace, '--project', project)
    if language == 'rust' and case_set is None and not watch_project and recovery_case is None:
        security['sourcePaths'] = source_paths(api, workspace, project)
    warm_b = None
    if watch_project:
        # Warm exactly B before A starts. The actual watch edit must still
        # transfer and revalidate those same source, recipe and tool bytes.
        edit(project, 201)
        warm_b = api.call('build', '--workspace', workspace, '--project', project, timeout=1200)
        edit(project, 101)
    built = api.call('build', '--workspace', workspace, '--project', project, timeout=1200)
    retention = None
    if recovery_case == 'expiry':
        if __package__:
            from .dev_packaged_authority import call as recovery_observation
        else:
            from dev_packaged_authority import call as recovery_observation
        retention = recovery_observation(api, config, {'workspace': workspace, 'user': owned['user'],
            'helperSha256': helper_sha}, 'configure-expiry')
    fixtures = ['--fixtures', project / 'tests/clock-zero.json'] if case_set == 'clock' else []
    admission = 'trusted-local' if watch_project else 'signed-fixture'
    profile = api.call('prepare-test', '--workspace', workspace, '--consent-test-fixtures',
                       '--admission', admission, '--tool-root', selected['directory'], *fixtures, timeout=120)
    require(profile['admission'] == admission, 'explicit-qualification-admission-required')
    authored = {entry['path']: digest(project / entry['path']) for entry in manifest['snapshot']['files']}
    authored.update({'latent.project.json': digest(project / 'latent.project.json'), 'app/.env': digest(sentinel)})
    if case_set is not None:
        for path in [*project.glob('tests/*.json'), *project.glob('app/wit/deps/clock/*.wit')]:
            authored[path.relative_to(project).as_posix()] = digest(path)
    if watch_project:
        for name in ('app/qualification_recipe.py', 'app/qualification-mode.txt',
                     'tests/value-input.json', 'tests/value-expected.json'):
            authored[name] = digest(project / name)
    result = {'workspace': workspace, 'user': owned['user'], 'project': str(project), 'helperSha256': helper_sha,
            'build': built, 'profile': profile, 'tools': selected, 'authoredSource': authored, 'sourceRejections': security}
    if watch_project:
        result['watchWarmB'] = warm_b
    if retention is not None:
        result['receiptRetention'] = retention
    return result


def verify_language(api, item):
    name = item['workspace']
    if 'startup' not in item:
        item['startup'] = api.start(name)
    item['doctor'] = api.call('doctor', '--workspace', name)
    if 'deployment' not in item:
        item['deployment'] = api.call('deploy', '--workspace', name, timeout=180)
    item['tests'] = api.call('test', '--workspace', name, '--environment', 'node', timeout=330)
    require(item['tests']['passed'] and all(case['status'] == 'passed' for case in item['tests']['results']), 'language-required-case-failed')
    require({'success', 'declared-error'} <= {case['category'] for case in item['tests']['results']}, 'success-and-declared-error-required')
    item['guest'] = observe(api, item, 'audit')
    if 'crlfSourceSha256' in item['sourceRejections']:
        item['sourceTransfer'] = observe(api, item, 'rust-source', item['build']['attempt'])
        require(item['sourceTransfer']['sha256'] == item['sourceRejections']['crlfSourceSha256']
            and item['sourceTransfer']['crlfLines'] > 0 and item['sourceTransfer']['bareLfLines'] == 0,
            'exact-crlf-source-transfer-required')
    item['publicArtifacts'] = export(api, item)


def retained_invocation(api, item):
    result = api.call('test', '--workspace', item['workspace'], '--environment', 'node',
        '--select', item['tests']['selection'][0], timeout=150)
    require(result['passed'] and result['identity']['deployment'] == item['tests']['identity']['deployment'],
            'retained-workspace-invocation-redeployed-or-failed')
    return result


def preserved_source(item):
    require(all(digest(Path(item['project']) / name) == checksum for name, checksum in item['authoredSource'].items()),
            'owned-purge-changed-authored-source')
    return {'files': len(item['authoredSource']), 'unchanged': True}


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
        'cleanup': 'not-started', 'limits': {'commands': MAX_COMMANDS, 'reservedCleanupCommands': 24, 'stdoutBytesPerCommand': 4194304,
            'stderrBytesPerCommand': 262144, 'receiptBytes': 16777216, 'maximumCommandSeconds': 1800,
            'scheduleSeconds': 7200}}
    api = None
    try:
        manifest, report['bootstrap'] = authenticate(config, output)
        executable = extract(Path(config['artifacts']['windows']), manifest, output / 'frontend')
        api = Frontend(executable, output, report)
        report['doctor'] = api.call('doctor')
        report['bundleRejections'] = negative_bundles(api, config)
        report['frontend'] = acquire(api, config, config['artifacts']['windows'], 'windows-x86_64')
        image = acquire(api, config, config['artifacts']['wsl'], 'linux-x86_64-wsl-rootfs')
        inventory = read_json(api.state / 'bundles' / image['bundle'] / 'rootfs-inventory.json')
        report['provision'] = api.call('provision', '--bundle', image['bundle'], '--consent-provision', timeout=360)
        retained = None
        for index, language in enumerate(LANGUAGES):
            item = report['languages'][language] = prepare(api, config, language, index, inventory['helperSha256'])
            if retained is None:
                deploy_with_lost_responses(api, config, item)
            verify_language(api, item)
            if retained is None:
                invoke_with_lost_response(api, config, item)
                item['logs'] = api.call('logs', '--workspace', item['workspace'])
                retained = item
                continue
            require(item['user'] != retained['user'], 'separate-wsl-users-required')
            item['guestIsolation'] = observe(api, item, 'audit', retained['user'])
            item['reverseGuestIsolation'] = observe(api, retained, 'audit', item['user'])
            item['otherWorkspaceBeforeStop'] = api.call('status', '--workspace', retained['workspace'])
            item['shutdown'] = api.down(item['workspace'])
            item['otherWorkspaceAfterStop'] = api.call('status', '--workspace', retained['workspace'])
            require(item['otherWorkspaceAfterStop']['state'] == 'ready', 'other-workspace-stopped')
            item['otherWorkspaceInvocationAfterStop'] = retained_invocation(api, retained)
            item['purge'] = api.call('purge', '--workspace', item['workspace'], '--confirm-workspace', item['workspace'], timeout=120)
            item['authoredSourceAfterPurge'] = preserved_source(item)
            write_json(output / 'observation.json', report)
        retained['actualWslLifecycle'] = restart_owned_distribution(api, retained)
        retained['afterActualWslRestart'] = retained_invocation(api, retained)
        retained['shutdown'] = api.down(retained['workspace'])
        retained['restart'] = api.start(retained['workspace'])
        retained['statusAfterRestart'] = api.call('status', '--workspace', retained['workspace'])
        retained['invocationAfterRestart'] = retained_invocation(api, retained)
        retained['shutdownAfterRestart'] = api.down(retained['workspace'])
        retained['purge'] = api.call('purge', '--workspace', retained['workspace'], '--confirm-workspace', retained['workspace'], timeout=120)
        retained['authoredSourceAfterPurge'] = preserved_source(retained)
        report['watchApplication'] = watch_campaign(api, config, inventory['helperSha256'])
        if __package__:
            from .dev_packaged_failures import node_campaign, portable_campaign
        else:
            from dev_packaged_failures import node_campaign, portable_campaign
        report['closedProfile'] = node_campaign(api, config, inventory['helperSha256'])
        report['distroPurge'] = api.call('wsl-purge', '--confirm-distribution', report['provision']['distribution'], timeout=180)
        report['distroAfterPurge'] = api.call('wsl-status')
        require(report['distroAfterPurge']['registered'] is False, 'portable-stage-still-has-owned-wsl-distribution')
        for language, item in report['languages'].items():
            item['portable'] = api.call('test', '--workspace', 'test-portable-' + language, '--environment', 'portable',
                '--project', item['project'], '--artifacts', item['publicArtifacts']['directory'],
                '--portable-bundle', report['frontend']['bundle'], '--controlled-development', timeout=330)
            require(item['portable']['passed'] and item['portable']['environment'] == 'portable'
                    and item['portable']['cleanup'] == 'owned-native-host-reaped', 'native-portable-qualification-failed')
            common = lambda result: [(case['id'], case['status'], case['category'], case['payloadSha256'])
                                     for case in result['results']]
            require(common(item['portable']) == common(item['tests']), 'native-and-linux-common-outcomes-differ')
        portable_campaign(api, report['closedProfile'], report['frontend']['bundle'])
        report['portableExecution'] = 'native-windows-after-owned-wsl-distribution-purge'
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
