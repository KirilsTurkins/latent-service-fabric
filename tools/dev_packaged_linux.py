"""Actual packaged direct Linux and explicit SSH operations in a clean Ubuntu OS."""
from pathlib import Path
import argparse
import json
import os
import platform
import shutil
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from dev_packaged_bootstrap import authenticate, extract
    from dev_packaged_process import MAX_COMMANDS, ProbeFailure, digest, read_json, require, write_json
    from dev_packaged_windows import Frontend, acquire, prepare, verify_language, retained_invocation, preserved_source
    from dev_packaged_watch import run as watch
    from dev_packaged_recovery import deploy_with_lost_responses, invoke_with_lost_response
    from dev_packaged_failures import node_campaign
else:
    from .dev_packaged_bootstrap import authenticate, extract
    from .dev_packaged_process import MAX_COMMANDS, ProbeFailure, digest, read_json, require, write_json
    from .dev_packaged_windows import Frontend, acquire, prepare, verify_language, retained_invocation, preserved_source
    from .dev_packaged_watch import run as watch
    from .dev_packaged_recovery import deploy_with_lost_responses, invoke_with_lost_response
    from .dev_packaged_failures import node_campaign


def reject_ssh_mismatch(api, selected):
    wrong_key = api.root / 'wrong-known-hosts'
    public = Path(selected['identityFile'] + '.pub').read_text()
    wrong_key.write_text('[127.0.0.1]:2222 ' + public, encoding='utf-8')
    wrong_key.chmod(0o600)
    for name, changed, failure in (
            ('host-key', {**selected, 'knownHosts': str(wrong_key)}, 'backend-transport-lost-status-required'),
            ('helper', {**selected, 'helperSha256': 'sha256:' + '0' * 64}, 'helper-identity-mismatch-before-execution')):
        config = api.root / ('wrong-' + name + '.json')
        write_json(config, changed)
        workspace = 'test-rejected-' + name
        api.call('connect', '--workspace', workspace, '--backend-config', config, timeout=30, rejection={failure})
        require(not (api.state / workspace / 'backend.json').exists(), 'rejected-ssh-backend-was-selected')


def run(config, output):
    require(sys.platform == 'linux' and os.getuid() == 23001 and platform.machine() == 'x86_64',
            'dedicated-actual-linux-qualification-owner-required')
    require(config['independentPolicyApproved'] is True and config['consentProvisionAndInstall'] is True,
            'independently-approved-candidates-required')
    require(not output.exists(), 'new-qualification-output-required')
    output.mkdir(mode=0o700)
    started = time.monotonic()
    report = {'schemaVersion': 'latent.dev.packaged-linux-probe.v1', 'passed': False, 'qualificationComplete': False,
        'sourceCommit': config['sourceCommit'], 'sourceCheckoutUsedByApplication': False, 'runtimeCompiled': False,
        'environment': 'fresh-ubuntu-24.04-os-container-with-network-none', 'kernel': platform.release(),
        'osRelease': Path('/etc/os-release').read_text(), 'backends': {},
        'cleanup': 'not-started', 'limits': {'scheduleSeconds': 7200, 'commandsPerBackend': MAX_COMMANDS}}
    api = None
    try:
        report['absentHostCompilers'] = [name for name in ('gcc', 'g++', 'clang', 'rustc', 'cargo', 'dotnet', 'javac', 'go', 'node')
                                       if shutil.which(name) is None]
        require(len(report['absentHostCompilers']) == 9, 'clean-os-host-compiler-absence')
        manifest, report['bootstrap'] = authenticate(config, output, target='linux-x86_64')
        executable = extract(Path(config['artifacts']['linux']), manifest, output / 'frontend')
        helper_sha = digest(output / 'frontend/helper.pyz')
        require(helper_sha == config['linuxHelperSha256'], 'same-authenticated-helper-required')
        for kind in ('linux', 'ssh'):
            selected = {'kind': 'linux', 'python': '/usr/local/bin/python3.13',
                'helper': str(output / 'frontend/helper.pyz'), 'helperSha256': helper_sha} if kind == 'linux' else config['sshBackend']
            root = output / kind
            root.mkdir(mode=0o700)
            observation = report['backends'][kind] = {'commands': [], 'passed': False, 'backend': kind}
            api = Frontend(executable, root, observation)
            backend = root / 'backend.json'
            write_json(backend, selected)
            observation['hostDoctor'] = api.call('doctor')
            observation['authenticatedFrontend'] = acquire(api, config, config['artifacts']['linux'], 'linux-x86_64')
            if kind == 'ssh':
                reject_ssh_mismatch(api, selected)
                observation['strictSshIdentityRejections'] = ['wrong-host-key', 'wrong-helper-digest']
            # Both paths build the maintained Rust project; the six-language
            # Windows/WSL lane owns the language matrix rather than duplicating it.
            item = observation['application'] = prepare(api, config, 'rust', 0 if kind == 'linux' else 1,
                                                        helper_sha, backend_config=backend)
            deploy_with_lost_responses(api, config, item)
            verify_language(api, item)
            invoke_with_lost_response(api, config, item)
            observation['status'] = api.call('status', '--workspace', item['workspace'])
            observation['logs'] = api.call('logs', '--workspace', item['workspace'])
            if kind == 'ssh':
                # A concurrent second start must fail before selecting another
                # node. The existing foreground and deployment remain callable.
                observation['concurrentStart'] = api.call('up', '--workspace', item['workspace'],
                    rejection={'invalid-or-unavailable-input-inspect-doctor'}, timeout=30)
                observation['afterConcurrentStart'] = retained_invocation(api, item)
            watch(api, item)
            item['down'] = api.down(item['workspace'])
            item['repeatedDown'] = api.call('down', '--workspace', item['workspace'])
            item['retainedRestart'] = api.start(item['workspace'])
            item['afterRestart'] = retained_invocation(api, item)
            item['finalDown'] = api.down(item['workspace'])
            item['purge'] = api.call('purge', '--workspace', item['workspace'],
                '--confirm-workspace', item['workspace'], timeout=120)
            item['repeatedPurge'] = api.call('purge', '--workspace', item['workspace'],
                '--confirm-workspace', item['workspace'], timeout=120)
            item['preservedAuthorSource'] = preserved_source(item)
            observation['closedProfile'] = node_campaign(api, config, helper_sha, backend_config=backend)
            observation['passed'] = True
            write_json(output / 'observation.json', report)
        report.update(passed=True, cleanup='both-owned-node-workspaces-purged-author-source-retained')
    except BaseException as error:
        report['failure'] = str(error) if isinstance(error, ProbeFailure) else type(error).__name__
        report['cleanup'] = 'failed-attempt-private-container-state-retained'
        raise
    finally:
        if api is not None and api.running:
            report['cleanupAttempts'] = {}
            for name in list(api.running):
                try:
                    report['cleanupAttempts'][name] = api.down(name)
                except BaseException as error:
                    report['cleanupAttempts'][name] = {'failure': type(error).__name__, 'remoteTerminationConfirmed': False}
        report['seconds'] = round(time.monotonic() - started, 3)
        write_json(output / 'observation.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    result = run(read_json(arguments.inputs), arguments.output.absolute())
    print(json.dumps({'passed': result['passed'], 'cleanup': result['cleanup']}))
